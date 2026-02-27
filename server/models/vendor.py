"""
Vendor Model — v0.07 Phase 6.2.

Defines vendor types, inventory templates, base prices, and the 6-modifier
pricing formula.  Vendors are entities that sell/buy resources for credits.

Vendor types:
  allied_station, neutral_station, hostile_station, outpost,
  merchant, black_market, salvage_yard, allied_warship
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VENDOR_TYPES: tuple[str, ...] = (
    "allied_station",
    "neutral_station",
    "hostile_station",
    "outpost",
    "merchant",
    "black_market",
    "salvage_yard",
    "allied_warship",
)

# Base unit prices for every tradeable resource/item.
BASE_PRICES: dict[str, float] = {
    "fuel": 2,
    "standard_torpedo": 15,
    "homing_torpedo": 30,
    "ion_torpedo": 30,
    "piercing_torpedo": 30,
    "heavy_torpedo": 45,
    "proximity_torpedo": 30,
    "nuclear_torpedo": 100,
    "experimental_torpedo": 60,
    "medical_supplies": 5,
    "repair_materials": 8,
    "drone_fuel": 3,
    "drone_parts": 20,
    "ammunition": 4,
    "provisions": 1,
}

MILITARY_ITEMS: frozenset[str] = frozenset({
    "homing_torpedo", "ion_torpedo", "piercing_torpedo", "heavy_torpedo",
    "proximity_torpedo", "nuclear_torpedo", "experimental_torpedo",
    "ammunition",
})

HEAVY_MILITARY_ITEMS: frozenset[str] = frozenset({
    "heavy_torpedo", "nuclear_torpedo", "experimental_torpedo",
})

# Per-ship-class starting credits (before difficulty multiplier).
STARTING_CREDITS: dict[str, float] = {
    "scout": 300,
    "corvette": 500,
    "frigate": 800,
    "cruiser": 1200,
    "battleship": 1500,
    "carrier": 1000,
    "medical_ship": 600,
}

# Trade reputation bounds.
REPUTATION_MIN: float = -100.0
REPUTATION_MAX: float = 100.0

# Reputation change on fair trade.
REPUTATION_TRADE_GAIN: float = 2.0


# ---------------------------------------------------------------------------
# Vendor type templates
# ---------------------------------------------------------------------------

# Each template: (base_multiplier, sell_multiplier_override | None,
#   inventory_ranges, flags)
# inventory_ranges: {resource_type: (min, max)} or None → use defaults
# Flags: dict with optional keys:
#   "military_restricted": bool — cannot buy military items
#   "heavy_restricted": bool — cannot buy heavy/nuclear/experimental
#   "standing_gate": float — minimum faction standing to trade
#   "trade_window": float — seconds until vendor leaves (None=unlimited)
#   "hidden_inventory": bool — has hidden items revealed on request
#   "defective_chance": float — chance of defective goods
#   "free_transfer": bool — no cost, just transfer
#   "keep_fraction": float — warship keeps this fraction of own stock

_DEFAULT_INVENTORY_RANGES: dict[str, tuple[int, int]] = {
    "fuel": (200, 800),
    "medical_supplies": (20, 60),
    "repair_materials": (15, 50),
    "drone_fuel": (50, 200),
    "drone_parts": (5, 15),
    "ammunition": (20, 60),
    "provisions": (100, 400),
    "standard_torpedo": (4, 12),
    "homing_torpedo": (2, 6),
    "ion_torpedo": (2, 6),
    "piercing_torpedo": (2, 6),
    "heavy_torpedo": (1, 4),
    "proximity_torpedo": (2, 6),
    "nuclear_torpedo": (0, 2),
    "experimental_torpedo": (0, 1),
}

_BASICS_ONLY_ITEMS: frozenset[str] = frozenset({
    "fuel", "provisions", "medical_supplies", "repair_materials",
})


VENDOR_TEMPLATES: dict[str, dict] = {
    "allied_station": {
        "base_multiplier": 1.0,
        "sell_multiplier": None,  # same as buy
        "restricted_items": frozenset(),
        "standing_gate": None,
        "trade_window": None,
        "hidden_inventory": False,
        "defective_chance": 0.0,
        "free_transfer": False,
        "keep_fraction": 0.0,
        "report_chance": 0.0,
    },
    "neutral_station": {
        "base_multiplier": 1.3,
        "sell_multiplier": None,
        "restricted_items": HEAVY_MILITARY_ITEMS,
        "standing_gate": None,
        "trade_window": None,
        "hidden_inventory": False,
        "defective_chance": 0.0,
        "free_transfer": False,
        "keep_fraction": 0.0,
        "report_chance": 0.0,
    },
    "hostile_station": {
        "base_multiplier": 2.0,
        "sell_multiplier": None,
        "restricted_items": MILITARY_ITEMS,
        "standing_gate": -50.0,
        "trade_window": None,
        "hidden_inventory": False,
        "defective_chance": 0.0,
        "free_transfer": False,
        "keep_fraction": 0.0,
        "report_chance": 0.30,
    },
    "outpost": {
        "base_multiplier": 1.15,  # random 0.8-1.5 applied at spawn
        "sell_multiplier": None,
        "restricted_items": MILITARY_ITEMS | frozenset({"drone_fuel", "drone_parts"}),
        "standing_gate": None,
        "trade_window": None,
        "hidden_inventory": False,
        "defective_chance": 0.0,
        "free_transfer": False,
        "keep_fraction": 0.0,
        "report_chance": 0.0,
    },
    "merchant": {
        "base_multiplier": 1.1,
        "sell_multiplier": None,
        "restricted_items": HEAVY_MILITARY_ITEMS,
        "standing_gate": None,
        "trade_window": 180.0,
        "hidden_inventory": False,
        "defective_chance": 0.0,
        "free_transfer": False,
        "keep_fraction": 0.0,
        "report_chance": 0.0,
    },
    "black_market": {
        "base_multiplier": 2.5,
        "sell_multiplier": None,
        "restricted_items": frozenset(),
        "standing_gate": None,
        "trade_window": None,
        "hidden_inventory": True,
        "defective_chance": 0.15,
        "free_transfer": False,
        "keep_fraction": 0.0,
        "report_chance": 0.0,
    },
    "salvage_yard": {
        "base_multiplier": 0.7,
        "sell_multiplier": 0.9,
        "restricted_items": HEAVY_MILITARY_ITEMS,
        "standing_gate": None,
        "trade_window": None,
        "hidden_inventory": False,
        "defective_chance": 0.0,
        "free_transfer": False,
        "keep_fraction": 0.0,
        "report_chance": 0.0,
    },
    "allied_warship": {
        "base_multiplier": 0.0,  # free transfer
        "sell_multiplier": None,
        "restricted_items": frozenset(),
        "standing_gate": 30.0,
        "trade_window": 60.0,
        "hidden_inventory": False,
        "defective_chance": 0.0,
        "free_transfer": True,
        "keep_fraction": 0.60,
        "report_chance": 0.0,
    },
}


# ---------------------------------------------------------------------------
# Vendor dataclass
# ---------------------------------------------------------------------------


@dataclass
class Vendor:
    """A vendor entity that can trade resources for credits."""

    id: str
    vendor_type: str                     # one of VENDOR_TYPES
    name: str
    faction: str                         # friendly | neutral | hostile
    position: tuple[float, float]
    inventory: dict[str, int] = field(default_factory=dict)
    inventory_max: dict[str, int] = field(default_factory=dict)
    hidden_inventory: dict[str, int] = field(default_factory=dict)
    base_multiplier: float = 1.0
    station_id: str | None = None        # linked Station.id
    available: bool = True
    trade_window: float | None = None    # seconds remaining, None = unlimited
    cooldown_items: dict[str, float] = field(default_factory=dict)
    reported_position: bool = False      # hostile station: already reported ship?

    def to_dict(self) -> dict:
        """Serialise to a JSON-friendly dict."""
        return {
            "id": self.id,
            "vendor_type": self.vendor_type,
            "name": self.name,
            "faction": self.faction,
            "position": list(self.position),
            "inventory": dict(self.inventory),
            "inventory_max": dict(self.inventory_max),
            "hidden_inventory": dict(self.hidden_inventory),
            "base_multiplier": self.base_multiplier,
            "station_id": self.station_id,
            "available": self.available,
            "trade_window": self.trade_window,
            "cooldown_items": dict(self.cooldown_items),
            "reported_position": self.reported_position,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Vendor:
        """Reconstruct a Vendor from a serialised dict."""
        pos = data.get("position", [0.0, 0.0])
        return cls(
            id=data["id"],
            vendor_type=data["vendor_type"],
            name=data["name"],
            faction=data.get("faction", "neutral"),
            position=(float(pos[0]), float(pos[1])),
            inventory=dict(data.get("inventory", {})),
            inventory_max=dict(data.get("inventory_max", {})),
            hidden_inventory=dict(data.get("hidden_inventory", {})),
            base_multiplier=float(data.get("base_multiplier", 1.0)),
            station_id=data.get("station_id"),
            available=bool(data.get("available", True)),
            trade_window=data.get("trade_window"),
            cooldown_items={k: float(v) for k, v in data.get("cooldown_items", {}).items()},
            reported_position=bool(data.get("reported_position", False)),
        )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def is_military_item(item_type: str) -> bool:
    """Return True if the item is classified as military."""
    return item_type in MILITARY_ITEMS


def can_trade_with(vendor: Vendor, faction_standing: float) -> bool:
    """Check if trade is allowed based on faction standing gate."""
    template = VENDOR_TEMPLATES.get(vendor.vendor_type, {})
    gate = template.get("standing_gate")
    if gate is not None and faction_standing < gate:
        return False
    return vendor.available


def generate_vendor_inventory(
    vendor_type: str,
    rng: random.Random | None = None,
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Generate (inventory, inventory_max, hidden_inventory) for a vendor type.

    Returns:
        (inventory, inventory_max, hidden_inventory)
    """
    if rng is None:
        rng = random.Random()

    template = VENDOR_TEMPLATES.get(vendor_type, VENDOR_TEMPLATES["neutral_station"])
    restricted = template.get("restricted_items", frozenset())

    inventory: dict[str, int] = {}
    inventory_max: dict[str, int] = {}
    hidden: dict[str, int] = {}

    if vendor_type == "outpost":
        # Basics only with limited stock.
        for item in _BASICS_ONLY_ITEMS:
            lo, hi = _DEFAULT_INVENTORY_RANGES.get(item, (10, 30))
            # Outposts have smaller stock.
            lo = max(1, lo // 2)
            hi = max(2, hi // 2)
            qty = rng.randint(lo, hi)
            inventory[item] = qty
            inventory_max[item] = hi

    elif vendor_type == "merchant":
        # 1-2 bulk categories from a selection.
        categories = [
            ["fuel", "provisions"],
            ["medical_supplies", "repair_materials"],
            ["standard_torpedo", "homing_torpedo", "ion_torpedo"],
            ["drone_fuel", "drone_parts"],
            ["ammunition"],
        ]
        num_cats = rng.randint(1, 2)
        chosen = rng.sample(categories, min(num_cats, len(categories)))
        for cat in chosen:
            for item in cat:
                if item in restricted:
                    continue
                lo, hi = _DEFAULT_INVENTORY_RANGES.get(item, (10, 30))
                # Merchants carry more of their speciality.
                lo = int(lo * 1.5)
                hi = int(hi * 1.5)
                qty = rng.randint(lo, hi)
                inventory[item] = qty
                inventory_max[item] = hi

    elif vendor_type == "salvage_yard":
        # Random subset of items with random stock.
        all_items = list(_DEFAULT_INVENTORY_RANGES.keys())
        num_items = rng.randint(4, 8)
        chosen_items = rng.sample(all_items, min(num_items, len(all_items)))
        for item in chosen_items:
            if item in restricted:
                continue
            lo, hi = _DEFAULT_INVENTORY_RANGES[item]
            qty = rng.randint(max(1, lo // 2), hi)
            inventory[item] = qty
            inventory_max[item] = hi

    elif vendor_type == "allied_warship":
        # Has all basics, but keeps 60% for itself.
        keep = template.get("keep_fraction", 0.60)
        for item, (lo, hi) in _DEFAULT_INVENTORY_RANGES.items():
            total = rng.randint(lo, hi)
            if total <= 0:
                continue
            available = max(1, int(total * (1.0 - keep)))
            inventory[item] = available
            inventory_max[item] = total

    elif vendor_type == "black_market":
        # Everything including rare items; some items hidden.
        for item, (lo, hi) in _DEFAULT_INVENTORY_RANGES.items():
            qty = rng.randint(lo, hi)
            if rng.random() < 0.3:  # 30% chance item is hidden
                hidden[item] = qty
                inventory_max[item] = hi
            else:
                inventory[item] = qty
                inventory_max[item] = hi

    else:
        # allied_station, neutral_station, hostile_station: standard stock.
        for item, (lo, hi) in _DEFAULT_INVENTORY_RANGES.items():
            if item in restricted:
                continue
            qty = rng.randint(lo, hi)
            inventory[item] = qty
            inventory_max[item] = hi

    return inventory, inventory_max, hidden


# ---------------------------------------------------------------------------
# Pricing engine — 6-modifier formula (§6.2.3.3)
# ---------------------------------------------------------------------------


def _faction_modifier(faction_standing: float) -> float:
    """Price modifier based on faction standing with the vendor's faction."""
    if faction_standing > 50:
        return 0.85
    if faction_standing > 20:
        return 0.95
    if faction_standing >= 0:
        return 1.0
    if faction_standing >= -20:
        return 1.1
    return 1.3


def _urgency_modifier(ship_resource_fraction: float) -> float:
    """Price modifier based on how desperate the ship is for this resource."""
    if ship_resource_fraction < 0.10:
        return 1.5
    if ship_resource_fraction < 0.25:
        return 1.2
    return 1.0


def _reputation_modifier(trade_reputation: float) -> float:
    """Price modifier based on the ship's trade reputation."""
    if trade_reputation > 50:
        return 0.9
    if trade_reputation > 20:
        return 0.95
    if trade_reputation >= 0:
        return 1.0
    return 1.15


def _scarcity_modifier(vendor: Vendor, item_type: str) -> float:
    """Price modifier based on vendor's remaining stock fraction."""
    max_qty = vendor.inventory_max.get(item_type, 0)
    if max_qty <= 0:
        return 1.0
    current = vendor.inventory.get(item_type, 0)
    fraction = current / max_qty
    if fraction < 0.30:
        return 1.3
    if fraction > 0.80:
        return 0.9
    return 1.0


def calculate_price(
    item_type: str,
    vendor: Vendor,
    faction_standing: float = 0.0,
    trade_reputation: float = 0.0,
    ship_resource_fraction: float = 1.0,
    is_selling: bool = False,
) -> float:
    """Calculate the actual price for one unit of an item.

    Applies the 6-modifier formula:
      actual = base × vendor_type × faction × urgency × reputation × scarcity

    For selling, the vendor type multiplier may differ (salvage_yard uses 0.9×).
    For allied_warship (free_transfer), returns 0.
    """
    template = VENDOR_TEMPLATES.get(vendor.vendor_type, {})

    if template.get("free_transfer", False):
        return 0.0

    base = BASE_PRICES.get(item_type, 10.0)

    if is_selling:
        # Sell price uses sell_multiplier if set, otherwise 50% of buy price.
        sell_mult = template.get("sell_multiplier")
        if sell_mult is not None:
            type_mod = sell_mult
        else:
            type_mod = vendor.base_multiplier * 0.5
    else:
        type_mod = vendor.base_multiplier

    faction_mod = _faction_modifier(faction_standing)
    urgency_mod = _urgency_modifier(ship_resource_fraction) if not is_selling else 1.0
    rep_mod = _reputation_modifier(trade_reputation)
    scarcity_mod = _scarcity_modifier(vendor, item_type) if not is_selling else 1.0

    return round(base * type_mod * faction_mod * urgency_mod * rep_mod * scarcity_mod, 2)


def get_price_breakdown(
    item_type: str,
    vendor: Vendor,
    faction_standing: float = 0.0,
    trade_reputation: float = 0.0,
    ship_resource_fraction: float = 1.0,
    is_selling: bool = False,
) -> dict:
    """Return a dict with each modifier and the final price."""
    template = VENDOR_TEMPLATES.get(vendor.vendor_type, {})
    is_free = template.get("free_transfer", False)

    base = BASE_PRICES.get(item_type, 10.0)

    if is_selling:
        sell_mult = template.get("sell_multiplier")
        type_mod = sell_mult if sell_mult is not None else vendor.base_multiplier * 0.5
    else:
        type_mod = vendor.base_multiplier

    return {
        "base_price": base,
        "vendor_type_modifier": type_mod,
        "faction_modifier": _faction_modifier(faction_standing),
        "urgency_modifier": _urgency_modifier(ship_resource_fraction) if not is_selling else 1.0,
        "reputation_modifier": _reputation_modifier(trade_reputation),
        "scarcity_modifier": _scarcity_modifier(vendor, item_type) if not is_selling else 1.0,
        "final_price": 0.0 if is_free else calculate_price(
            item_type, vendor, faction_standing, trade_reputation,
            ship_resource_fraction, is_selling,
        ),
        "is_free": is_free,
    }


def map_station_to_vendor_type(station_type: str, faction: str) -> str:
    """Map a Station's station_type + faction to a vendor type.

    Used when auto-spawning a vendor on dock.
    """
    if faction == "hostile":
        return "hostile_station"
    if station_type == "trade_hub":
        return "merchant"
    if station_type == "repair_dock":
        return "salvage_yard"
    if station_type == "derelict":
        return "salvage_yard"
    if station_type == "civilian":
        return "outpost"
    if faction == "friendly":
        return "allied_station"
    return "neutral_station"
