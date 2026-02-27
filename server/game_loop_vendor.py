"""
Vendor Game Loop — v0.07 Phase 6.2.

Module-level state managing vendor spawning, trade execution, reputation,
and vendor lifecycle (trade windows, cooldowns).

Public API follows the same pattern as game_loop_docking / game_loop_comms:
  reset(), serialise(), deserialise(), tick(), pop_pending_events()
"""
from __future__ import annotations

import logging
import random

from server.models.vendor import (
    REPUTATION_MAX,
    REPUTATION_MIN,
    REPUTATION_TRADE_GAIN,
    VENDOR_TEMPLATES,
    Vendor,
    calculate_price,
    can_trade_with,
    generate_vendor_inventory,
    get_price_breakdown,
    map_station_to_vendor_type,
)

logger = logging.getLogger("starbridge.vendor")

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_vendors: list[Vendor] = []
_vendor_counter: int = 0
_pending_events: list[dict] = []
_rng: random.Random = random.Random()


# ---------------------------------------------------------------------------
# Reset / serialise / deserialise
# ---------------------------------------------------------------------------


def reset() -> None:
    """Reset vendor state for a new game."""
    global _vendor_counter
    _vendors.clear()
    _vendor_counter = 0
    _pending_events.clear()


def serialise() -> dict:
    """Serialise all vendor state for save system."""
    return {
        "vendors": [v.to_dict() for v in _vendors],
        "vendor_counter": _vendor_counter,
    }


def deserialise(data: dict) -> None:
    """Restore vendor state from save data."""
    global _vendor_counter
    _vendors.clear()
    _pending_events.clear()
    for vd in data.get("vendors", []):
        _vendors.append(Vendor.from_dict(vd))
    _vendor_counter = int(data.get("vendor_counter", len(_vendors)))


# ---------------------------------------------------------------------------
# Public accessors
# ---------------------------------------------------------------------------


def get_vendors() -> list[Vendor]:
    """Return all active vendors."""
    return list(_vendors)


def get_vendor_by_id(vendor_id: str) -> Vendor | None:
    """Find a vendor by ID."""
    for v in _vendors:
        if v.id == vendor_id:
            return v
    return None


def get_vendors_for_station(station_id: str) -> list[Vendor]:
    """Return all vendors linked to a given station."""
    return [v for v in _vendors if v.station_id == station_id]


def pop_pending_events() -> list[dict]:
    """Drain and return all pending vendor events."""
    events = list(_pending_events)
    _pending_events.clear()
    return events


# ---------------------------------------------------------------------------
# Spawn / remove
# ---------------------------------------------------------------------------


def spawn_vendor(
    vendor_type: str,
    name: str,
    position: tuple[float, float],
    faction: str = "neutral",
    station_id: str | None = None,
    rng: random.Random | None = None,
) -> Vendor:
    """Create and register a new vendor. Returns the Vendor."""
    global _vendor_counter
    _vendor_counter += 1
    vid = f"vendor_{_vendor_counter}"

    if rng is None:
        rng = _rng

    template = VENDOR_TEMPLATES.get(vendor_type, VENDOR_TEMPLATES["neutral_station"])
    base_mult = template["base_multiplier"]

    # Outposts get a random base multiplier.
    if vendor_type == "outpost":
        base_mult = round(rng.uniform(0.8, 1.5), 2)

    inventory, inventory_max, hidden = generate_vendor_inventory(vendor_type, rng)

    trade_window = template.get("trade_window")

    vendor = Vendor(
        id=vid,
        vendor_type=vendor_type,
        name=name,
        faction=faction,
        position=position,
        inventory=inventory,
        inventory_max=inventory_max,
        hidden_inventory=hidden,
        base_multiplier=base_mult,
        station_id=station_id,
        available=True,
        trade_window=trade_window,
    )
    _vendors.append(vendor)

    _pending_events.append({
        "type": "vendor_spawned",
        "vendor_id": vid,
        "vendor_type": vendor_type,
        "name": name,
        "station_id": station_id,
    })

    logger.info("Spawned vendor %s (%s) at (%.0f, %.0f)", vid, vendor_type, *position)
    return vendor


def remove_vendor(vendor_id: str) -> bool:
    """Remove a vendor by ID. Returns True if found and removed."""
    for i, v in enumerate(_vendors):
        if v.id == vendor_id:
            _vendors.pop(i)
            _pending_events.append({
                "type": "vendor_removed",
                "vendor_id": vendor_id,
            })
            return True
    return False


# ---------------------------------------------------------------------------
# Catalog / pricing
# ---------------------------------------------------------------------------


def get_catalog(vendor_id: str, ship) -> dict | None:
    """Get available categories and items for a vendor.

    Returns a dict of {item_type: {available: int, unit_price: float}} or None.
    """
    vendor = get_vendor_by_id(vendor_id)
    if vendor is None or not vendor.available:
        return None

    template = VENDOR_TEMPLATES.get(vendor.vendor_type, {})
    restricted = template.get("restricted_items", frozenset())

    catalog: dict[str, dict] = {}
    for item_type, qty in vendor.inventory.items():
        if item_type in restricted:
            continue
        if vendor.cooldown_items.get(item_type, 0.0) > 0.0:
            continue
        unit_price = calculate_price(
            item_type, vendor,
            faction_standing=_get_faction_standing(ship, vendor),
            trade_reputation=getattr(ship, "trade_reputation", 0.0),
            ship_resource_fraction=_get_ship_resource_fraction(ship, item_type),
        )
        catalog[item_type] = {
            "available": qty,
            "unit_price": round(unit_price, 2),
        }

    return catalog


def request_price(
    vendor_id: str,
    item_type: str,
    quantity: int,
    ship,
    is_selling: bool = False,
) -> dict | None:
    """Get a price quote for a trade. Returns breakdown dict or None."""
    vendor = get_vendor_by_id(vendor_id)
    if vendor is None or not vendor.available:
        return None

    breakdown = get_price_breakdown(
        item_type, vendor,
        faction_standing=_get_faction_standing(ship, vendor),
        trade_reputation=getattr(ship, "trade_reputation", 0.0),
        ship_resource_fraction=_get_ship_resource_fraction(ship, item_type),
        is_selling=is_selling,
    )
    breakdown["quantity"] = quantity
    breakdown["total_price"] = round(breakdown["final_price"] * quantity, 2)

    if not is_selling:
        available = vendor.inventory.get(item_type, 0)
        breakdown["quantity_available"] = available
    else:
        breakdown["quantity_available"] = quantity  # player decides how much to sell

    return breakdown


# ---------------------------------------------------------------------------
# Trade execution
# ---------------------------------------------------------------------------


def execute_trade(
    vendor_id: str,
    item_type: str,
    quantity: int,
    ship,
) -> dict:
    """Buy items from vendor. Returns result dict with success/failure."""
    vendor = get_vendor_by_id(vendor_id)
    if vendor is None:
        return {"ok": False, "error": "Vendor not found"}
    if not vendor.available:
        return {"ok": False, "error": "Vendor not available"}

    template = VENDOR_TEMPLATES.get(vendor.vendor_type, {})
    restricted = template.get("restricted_items", frozenset())
    if item_type in restricted:
        return {"ok": False, "error": f"Item restricted: {item_type}"}

    # Standing gate check.
    faction_standing = _get_faction_standing(ship, vendor)
    if not can_trade_with(vendor, faction_standing):
        return {"ok": False, "error": "Insufficient faction standing"}

    # Cooldown check.
    if vendor.cooldown_items.get(item_type, 0.0) > 0.0:
        return {"ok": False, "error": f"Item on cooldown: {item_type}"}

    available = vendor.inventory.get(item_type, 0)
    actual_qty = min(quantity, available)
    if actual_qty <= 0:
        return {"ok": False, "error": "Item out of stock"}

    unit_price = calculate_price(
        item_type, vendor,
        faction_standing=faction_standing,
        trade_reputation=getattr(ship, "trade_reputation", 0.0),
        ship_resource_fraction=_get_ship_resource_fraction(ship, item_type),
    )
    total_cost = round(unit_price * actual_qty, 2)

    credits = getattr(ship, "credits", 0.0)
    if total_cost > 0 and credits < total_cost:
        return {"ok": False, "error": "Insufficient credits", "cost": total_cost, "credits": credits}

    # Execute trade.
    ship.credits = round(credits - total_cost, 2)
    vendor.inventory[item_type] = available - actual_qty

    # Add resources to ship.
    _add_to_ship(ship, item_type, actual_qty)

    # Reputation gain.
    adjust_reputation(ship, REPUTATION_TRADE_GAIN, "fair_trade")

    result = {
        "ok": True,
        "item_type": item_type,
        "quantity": actual_qty,
        "unit_price": unit_price,
        "total_cost": total_cost,
        "credits_remaining": ship.credits,
    }

    _pending_events.append({
        "type": "trade_buy",
        "vendor_id": vendor_id,
        **result,
    })

    # Hostile station: chance to report ship position.
    if vendor.vendor_type == "hostile_station" and not vendor.reported_position:
        report_chance = template.get("report_chance", 0.0)
        if _rng.random() < report_chance:
            vendor.reported_position = True
            _pending_events.append({
                "type": "vendor_reported_position",
                "vendor_id": vendor_id,
            })

    return result


def sell_to_vendor(
    vendor_id: str,
    item_type: str,
    quantity: int,
    ship,
) -> dict:
    """Sell items to a vendor. Returns result dict."""
    vendor = get_vendor_by_id(vendor_id)
    if vendor is None:
        return {"ok": False, "error": "Vendor not found"}
    if not vendor.available:
        return {"ok": False, "error": "Vendor not available"}

    # Check ship has enough to sell.
    ship_qty = _get_ship_quantity(ship, item_type)
    actual_qty = min(quantity, ship_qty)
    if actual_qty <= 0:
        return {"ok": False, "error": "Nothing to sell"}

    unit_price = calculate_price(
        item_type, vendor,
        faction_standing=_get_faction_standing(ship, vendor),
        trade_reputation=getattr(ship, "trade_reputation", 0.0),
        is_selling=True,
    )
    total_earned = round(unit_price * actual_qty, 2)

    # Execute sale.
    _remove_from_ship(ship, item_type, actual_qty)
    ship.credits = round(getattr(ship, "credits", 0.0) + total_earned, 2)
    vendor.inventory[item_type] = vendor.inventory.get(item_type, 0) + actual_qty

    # Reputation gain.
    adjust_reputation(ship, REPUTATION_TRADE_GAIN, "fair_trade")

    result = {
        "ok": True,
        "item_type": item_type,
        "quantity": actual_qty,
        "unit_price": unit_price,
        "total_earned": total_earned,
        "credits_remaining": ship.credits,
    }

    _pending_events.append({
        "type": "trade_sell",
        "vendor_id": vendor_id,
        **result,
    })

    return result


# ---------------------------------------------------------------------------
# Reputation
# ---------------------------------------------------------------------------


def adjust_reputation(ship, amount: float, reason: str) -> float:
    """Adjust trade reputation on the ship. Returns new value."""
    current = getattr(ship, "trade_reputation", 0.0)
    new_val = max(REPUTATION_MIN, min(REPUTATION_MAX, current + amount))
    ship.trade_reputation = round(new_val, 2)
    return ship.trade_reputation


def get_reputation_descriptor(trade_reputation: float) -> str:
    """Return a human-readable reputation descriptor."""
    if trade_reputation > 75:
        return "Renowned Trader"
    if trade_reputation > 50:
        return "Trusted Merchant"
    if trade_reputation > 20:
        return "Known Trader"
    if trade_reputation >= 0:
        return "Unknown"
    if trade_reputation >= -50:
        return "Unreliable"
    return "Blacklisted"


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


def tick(world, ship, dt: float) -> list[dict]:
    """Advance vendor state: trade windows, cooldowns.

    Returns list of events (also available via pop_pending_events).
    """
    events: list[dict] = []

    to_remove: list[str] = []
    for vendor in _vendors:
        # Tick trade window countdown.
        if vendor.trade_window is not None:
            vendor.trade_window -= dt
            if vendor.trade_window <= 0.0:
                vendor.available = False
                to_remove.append(vendor.id)
                evt = {
                    "type": "vendor_expired",
                    "vendor_id": vendor.id,
                    "vendor_name": vendor.name,
                }
                events.append(evt)
                _pending_events.append(evt)

        # Tick item cooldowns.
        expired_cooldowns = []
        for item, remaining in vendor.cooldown_items.items():
            remaining -= dt
            if remaining <= 0.0:
                expired_cooldowns.append(item)
            else:
                vendor.cooldown_items[item] = remaining
        for item in expired_cooldowns:
            del vendor.cooldown_items[item]

    # Remove expired vendors.
    for vid in to_remove:
        remove_vendor(vid)

    return events


# ---------------------------------------------------------------------------
# Auto-spawn from docking
# ---------------------------------------------------------------------------


def spawn_vendor_for_station(station, rng: random.Random | None = None) -> Vendor | None:
    """Auto-spawn a vendor for a docked station (if none exists).

    Called from game_loop_docking on docking.complete.
    """
    # Check if vendor already exists for this station.
    existing = get_vendors_for_station(station.id)
    if existing:
        return existing[0]

    vendor_type = map_station_to_vendor_type(station.station_type, station.faction)
    return spawn_vendor(
        vendor_type=vendor_type,
        name=f"{station.name} Trading Post",
        position=(station.x, station.y),
        faction=station.faction,
        station_id=station.id,
        rng=rng,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_faction_standing(ship, vendor: Vendor) -> float:
    """Get faction standing between ship and vendor faction.

    For now returns a simple mapping based on vendor faction.
    Future: pull from comms faction standing system.
    """
    # Try to get from comms module if available.
    try:
        import server.game_loop_comms as glco
        fs = glco.get_faction_standing(vendor.faction)
        if fs is not None:
            return fs.standing
    except (ImportError, AttributeError):
        pass

    # Default standings.
    if vendor.faction == "friendly":
        return 50.0
    if vendor.faction == "neutral":
        return 0.0
    return -30.0


def _get_ship_resource_fraction(ship, item_type: str) -> float:
    """Get the ship's current fraction for a resource type (for urgency pricing)."""
    res = getattr(ship, "resources", None)
    if res is None:
        return 1.0

    # Map torpedo types to general torpedo availability.
    if item_type.endswith("_torpedo"):
        return 1.0  # No urgency modifier for torpedoes

    return res.fraction(item_type) if hasattr(res, "fraction") else 1.0


def _get_ship_quantity(ship, item_type: str) -> int:
    """Get how much of an item the ship currently has (for selling)."""
    res = getattr(ship, "resources", None)
    if res is None:
        return 0

    if item_type.endswith("_torpedo"):
        # Torpedoes are managed by weapons module.
        try:
            import server.game_loop_weapons as glw
            ammo = glw.get_ammo()
            torp_type = item_type.replace("_torpedo", "")
            return ammo.get(torp_type, 0)
        except (ImportError, AttributeError):
            return 0

    return int(res.get(item_type))


def _add_to_ship(ship, item_type: str, quantity: int) -> None:
    """Add purchased items to the ship."""
    res = getattr(ship, "resources", None)

    if item_type.endswith("_torpedo"):
        try:
            import server.game_loop_weapons as glw
            torp_type = item_type.replace("_torpedo", "")
            current = glw.get_ammo_for_type(torp_type)
            glw.set_ammo_for_type(torp_type, current + quantity)
        except (ImportError, AttributeError):
            pass
        return

    if res is not None:
        res.add(item_type, float(quantity))


def _remove_from_ship(ship, item_type: str, quantity: int) -> None:
    """Remove sold items from the ship."""
    res = getattr(ship, "resources", None)

    if item_type.endswith("_torpedo"):
        try:
            import server.game_loop_weapons as glw
            torp_type = item_type.replace("_torpedo", "")
            current = glw.get_ammo_for_type(torp_type)
            glw.set_ammo_for_type(torp_type, max(0, current - quantity))
        except (ImportError, AttributeError):
            pass
        return

    if res is not None:
        res.consume(item_type, float(quantity))
