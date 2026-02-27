"""
Negotiation Game Loop — v0.07 Phase 6.3.

Module-level state managing trade channels, negotiation sessions, counter-offers,
barter, bluffing, walk-away/callback, bundle discounts, and combat pressure.

Public API follows the same pattern as game_loop_vendor / game_loop_docking:
  reset(), serialise(), deserialise(), tick(), pop_pending_events()
"""
from __future__ import annotations

import logging
import math
import random

from server.models.negotiation import (
    BARTER_PENALTY,
    BLUFF_BASE_CHANCE,
    BLUFF_COMMS_BONUS,
    BLUFF_COMPETING_SUCCESS_DISCOUNT,
    BLUFF_DAMAGE_PENALTY,
    BLUFF_MILITARY_BONUS,
    BLUFF_MILITARY_FAIL_COOLDOWN,
    BLUFF_MILITARY_FAIL_REP,
    BLUFF_MILITARY_SUCCESS_DISCOUNT,
    BLUFF_NOT_URGENT_PENALTY_REP,
    BLUFF_REP_BONUS,
    BLUFF_REP_PENALTY,
    BLUFF_TYPES,
    BUNDLE_DISCOUNT_2ND,
    BUNDLE_DISCOUNT_3RD,
    CHANNEL_RANGE_DEGRADED,
    CHANNEL_RANGE_STABLE,
    COMBAT_SPEED_MULTIPLIER,
    COMBAT_URGENCY_MULTIPLIER,
    COUNTER_COOLDOWN,
    DEGRADED_ROUND_MULTIPLIER,
    INSPECT_COST_FRACTION,
    MAX_COUNTER_ROUNDS,
    SERVICE_CONTRACT_FAILURE_REP,
    SERVICE_CONTRACT_FAILURE_STANDING,
    SERVICE_CONTRACT_TYPES,
    WALK_AWAY_CALLBACK_CHANCE,
    WALK_AWAY_CALLBACK_DELAY,
    WALK_AWAY_CALLBACK_DISCOUNT,
    BarterOffer,
    NegotiationSession,
    TradeChannel,
    calculate_barter_value,
    calculate_intel_value,
    evaluate_counter_offer,
)
from server.models.vendor import BASE_PRICES

logger = logging.getLogger("starbridge.negotiation")

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_channels: list[TradeChannel] = []
_sessions: list[NegotiationSession] = []
_channel_counter: int = 0
_session_counter: int = 0
_pending_events: list[dict] = []
_bundle_counts: dict[str, int] = {}       # vendor_id → items traded this docking
_bluff_blocked: dict[str, set[str]] = {}  # vendor_id → set of blocked bluff types
_combat_active: bool = False
_rng: random.Random = random.Random()


# ---------------------------------------------------------------------------
# Reset / serialise / deserialise
# ---------------------------------------------------------------------------


def reset() -> None:
    """Reset negotiation state for a new game."""
    global _channel_counter, _session_counter, _combat_active
    _channels.clear()
    _sessions.clear()
    _channel_counter = 0
    _session_counter = 0
    _pending_events.clear()
    _bundle_counts.clear()
    _bluff_blocked.clear()
    _combat_active = False


def serialise() -> dict:
    """Serialise all negotiation state for save system."""
    return {
        "channels": [c.to_dict() for c in _channels],
        "sessions": [s.to_dict() for s in _sessions],
        "channel_counter": _channel_counter,
        "session_counter": _session_counter,
        "bundle_counts": dict(_bundle_counts),
        "bluff_blocked": {k: list(v) for k, v in _bluff_blocked.items()},
        "combat_active": _combat_active,
    }


def deserialise(data: dict) -> None:
    """Restore negotiation state from save data."""
    global _channel_counter, _session_counter, _combat_active  # noqa: PLW0603
    reset()

    for cd in data.get("channels", []):
        _channels.append(TradeChannel.from_dict(cd))
    for sd in data.get("sessions", []):
        _sessions.append(NegotiationSession.from_dict(sd))
    _channel_counter = int(data.get("channel_counter", len(_channels)))
    _session_counter = int(data.get("session_counter", len(_sessions)))
    _bundle_counts = dict(data.get("bundle_counts", {}))
    for k, v in data.get("bluff_blocked", {}).items():
        _bluff_blocked[k] = set(v)
    _combat_active = bool(data.get("combat_active", False))


# ---------------------------------------------------------------------------
# Event helpers
# ---------------------------------------------------------------------------


def pop_pending_events() -> list[dict]:
    """Drain and return all pending negotiation events."""
    events = list(_pending_events)
    _pending_events.clear()
    return events


def _emit(event_type: str, **kwargs: object) -> None:
    _pending_events.append({"type": event_type, **kwargs})


# ---------------------------------------------------------------------------
# Channel management
# ---------------------------------------------------------------------------


def open_channel(
    vendor_id: str,
    station_id: str | None,
    distance: float,
    is_docked: bool,
    tick: float = 0.0,
) -> TradeChannel | str:
    """Open a trade channel to a vendor.

    Returns a TradeChannel on success, or an error string on failure.
    """
    global _channel_counter

    import server.game_loop_vendor as glvr
    vendor = glvr.get_vendor_by_id(vendor_id)
    if vendor is None:
        return "Vendor not found"
    if not vendor.available:
        return "Vendor not available"

    # Check no existing channel for this vendor.
    existing = get_channel_for_vendor(vendor_id)
    if existing is not None:
        return "Channel already open for this vendor"

    # Range check (docked = unlimited).
    if not is_docked and distance > CHANNEL_RANGE_DEGRADED:
        return "Out of range"

    _channel_counter += 1
    cid = f"ch_{_channel_counter}"

    status = "open"
    if not is_docked and distance > CHANNEL_RANGE_STABLE:
        status = "degraded"

    channel = TradeChannel(
        id=cid,
        vendor_id=vendor_id,
        station_id=station_id,
        status=status,
        opened_at=tick,
        distance=distance,
        is_docked=is_docked,
    )
    _channels.append(channel)

    _emit("channel_opened", channel_id=cid, vendor_id=vendor_id, status=status)
    logger.info("Trade channel %s opened to vendor %s (%s)", cid, vendor_id, status)
    return channel


def close_channel(channel_id: str) -> bool:
    """Close a trade channel. Also closes any active sessions on it."""
    for i, ch in enumerate(_channels):
        if ch.id == channel_id:
            # Close any sessions on this channel.
            for sess in _sessions:
                if sess.channel_id == channel_id and sess.status not in ("completed", "broken_off"):
                    sess.status = "broken_off"
                    _emit("session_broken_off", session_id=sess.id, reason="channel_closed")
            _channels.pop(i)
            _emit("channel_closed", channel_id=channel_id)
            return True
    return False


def get_channels() -> list[TradeChannel]:
    return list(_channels)


def get_channel_for_vendor(vendor_id: str) -> TradeChannel | None:
    for ch in _channels:
        if ch.vendor_id == vendor_id:
            return ch
    return None


def _get_channel(channel_id: str) -> TradeChannel | None:
    for ch in _channels:
        if ch.id == channel_id:
            return ch
    return None


def _get_session(session_id: str) -> NegotiationSession | None:
    for s in _sessions:
        if s.id == session_id:
            return s
    return None


def _get_active_session() -> NegotiationSession | None:
    """Return the single active session (if any). Enforces one-at-a-time."""
    for s in _sessions:
        if s.status not in ("completed", "broken_off"):
            return s
    return None


# ---------------------------------------------------------------------------
# Bundle discount helpers
# ---------------------------------------------------------------------------


def _apply_bundle_discount(price: float, bundle_index: int) -> float:
    if bundle_index == 1:
        return round(price * (1.0 - BUNDLE_DISCOUNT_2ND), 2)
    if bundle_index >= 2:
        return round(price * (1.0 - BUNDLE_DISCOUNT_3RD), 2)
    return price


def _apply_combat_modifier(price: float, combat_active: bool) -> float:
    if combat_active:
        return round(price * COMBAT_URGENCY_MULTIPLIER, 2)
    return price


# ---------------------------------------------------------------------------
# Negotiation lifecycle
# ---------------------------------------------------------------------------


def start_negotiation(
    channel_id: str,
    item_type: str,
    quantity: int,
    is_selling: bool,
    ship,
) -> dict:
    """Start a negotiation for an item on an open channel.

    Returns {ok, session_id, vendor_offer, quantity_available} or {ok: False, error}.
    """
    global _session_counter

    # Only one active session at a time.
    active = _get_active_session()
    if active is not None:
        return {"ok": False, "error": "Another negotiation is already active"}

    channel = _get_channel(channel_id)
    if channel is None:
        return {"ok": False, "error": "Channel not found"}
    if channel.status == "closed":
        return {"ok": False, "error": "Channel is closed"}

    import server.game_loop_vendor as glvr
    vendor = glvr.get_vendor_by_id(channel.vendor_id)
    if vendor is None:
        return {"ok": False, "error": "Vendor not found"}

    # Item cooldown check on vendor.
    if vendor.cooldown_items.get(item_type, 0.0) > 0.0:
        return {"ok": False, "error": f"Item on cooldown: {item_type}"}

    # Stock check.
    if not is_selling:
        available = vendor.inventory.get(item_type, 0)
        if available <= 0:
            return {"ok": False, "error": "Item out of stock"}
        actual_qty = min(quantity, available)
    else:
        actual_qty = quantity

    # Get initial price from vendor pricing system.
    price_info = glvr.request_price(
        channel.vendor_id, item_type, actual_qty, ship, is_selling=is_selling,
    )
    if price_info is None:
        return {"ok": False, "error": "Unable to get price quote"}

    unit_price = float(price_info["final_price"])

    # Apply bundle discount.
    bundle_idx = _bundle_counts.get(channel.vendor_id, 0)
    unit_price = _apply_bundle_discount(unit_price, bundle_idx)

    # Apply combat modifier.
    unit_price = _apply_combat_modifier(unit_price, _combat_active)

    _session_counter += 1
    sid = f"neg_{_session_counter}"

    session = NegotiationSession(
        id=sid,
        channel_id=channel_id,
        vendor_id=channel.vendor_id,
        status="offer_presented",
        item_type=item_type,
        quantity=actual_qty,
        is_selling=is_selling,
        vendor_offer=unit_price,
        original_offer=unit_price,
        bundle_index=bundle_idx,
        combat_active=_combat_active,
    )
    _sessions.append(session)

    _emit(
        "negotiation_started",
        session_id=sid,
        vendor_id=channel.vendor_id,
        item_type=item_type,
        quantity=actual_qty,
        vendor_offer=unit_price,
        is_selling=is_selling,
    )

    return {
        "ok": True,
        "session_id": sid,
        "vendor_offer": unit_price,
        "quantity_available": actual_qty,
    }


def accept_offer(session_id: str, ship) -> dict:
    """Accept the current vendor offer and execute the trade."""
    session = _get_session(session_id)
    if session is None:
        return {"ok": False, "error": "Session not found"}
    if session.status in ("completed", "broken_off"):
        return {"ok": False, "error": f"Session is {session.status}"}

    import server.game_loop_vendor as glvr

    if session.is_selling:
        result = glvr.sell_to_vendor_at_price(
            session.vendor_id, session.item_type, session.quantity,
            session.vendor_offer, ship,
        )
    else:
        result = glvr.execute_trade_at_price(
            session.vendor_id, session.item_type, session.quantity,
            session.vendor_offer, ship,
        )

    if result.get("ok"):
        session.status = "completed"
        # Increment bundle count for this vendor.
        _bundle_counts[session.vendor_id] = _bundle_counts.get(session.vendor_id, 0) + 1
        _emit("negotiation_completed", session_id=session_id, **result)
    else:
        _emit("negotiation_error", session_id=session_id, error=result.get("error", ""))

    return result


def counter_offer(session_id: str, proposed_price: float, ship) -> dict:
    """Submit a counter-offer. Returns response and new price."""
    session = _get_session(session_id)
    if session is None:
        return {"ok": False, "error": "Session not found"}
    if session.status in ("completed", "broken_off"):
        return {"ok": False, "error": f"Session is {session.status}"}
    if session.status == "final_offer":
        return {"ok": False, "error": "Final offer — accept or walk away"}
    if session.counter_rounds >= session.max_counter_rounds:
        return {"ok": False, "error": "Maximum counter rounds reached"}

    response, new_price = evaluate_counter_offer(
        proposed_price, session.vendor_offer, session.original_offer,
    )

    session.counter_rounds += 1

    if response == "accepted":
        session.vendor_offer = new_price
        session.status = "offer_presented"
    elif response == "split":
        session.vendor_offer = new_price
        session.status = "offer_presented"
    elif response == "concession":
        session.vendor_offer = new_price
        session.status = "offer_presented"
    elif response == "raised":
        session.vendor_offer = new_price
        session.status = "counter_round"
    elif response == "broken_off":
        session.status = "broken_off"
        # Set cooldown on vendor for this item.
        import server.game_loop_vendor as glvr
        vendor = glvr.get_vendor_by_id(session.vendor_id)
        if vendor is not None:
            vendor.cooldown_items[session.item_type] = COUNTER_COOLDOWN
    else:
        session.status = "counter_round"

    # Mark as final_offer if we've hit the limit.
    if session.counter_rounds >= session.max_counter_rounds and session.status not in ("completed", "broken_off"):
        session.status = "final_offer"

    _emit(
        "counter_result",
        session_id=session_id,
        response=response,
        new_price=new_price,
        counter_rounds=session.counter_rounds,
        is_final=session.status == "final_offer",
    )

    return {
        "ok": True,
        "response": response,
        "new_price": new_price,
        "counter_rounds": session.counter_rounds,
        "is_final": session.status == "final_offer",
    }


def walk_away(session_id: str) -> dict:
    """Walk away from the negotiation. May trigger a callback."""
    session = _get_session(session_id)
    if session is None:
        return {"ok": False, "error": "Session not found"}
    if session.status in ("completed", "broken_off"):
        return {"ok": False, "error": f"Session is {session.status}"}

    if session.walk_away_used:
        # Second walk-away: close for good.
        session.status = "broken_off"
        _emit("negotiation_broken_off", session_id=session_id, reason="second_walk_away")
        return {"ok": True, "callback": False, "closed": True}

    session.walk_away_used = True

    # 30% chance of callback.
    if _rng.random() < WALK_AWAY_CALLBACK_CHANCE:
        session.status = "callback_pending"
        session.callback_timer = WALK_AWAY_CALLBACK_DELAY
        session.callback_discount = WALK_AWAY_CALLBACK_DISCOUNT
        _emit("walk_away_callback", session_id=session_id, delay=WALK_AWAY_CALLBACK_DELAY)
        return {"ok": True, "callback": True, "delay": WALK_AWAY_CALLBACK_DELAY}
    else:
        session.status = "broken_off"
        _emit("negotiation_broken_off", session_id=session_id, reason="walk_away")
        return {"ok": True, "callback": False, "closed": True}


def accept_callback(session_id: str, ship) -> dict:
    """Accept a vendor callback offer (with discount)."""
    session = _get_session(session_id)
    if session is None:
        return {"ok": False, "error": "Session not found"}
    if session.status != "callback_pending":
        return {"ok": False, "error": "No callback pending"}

    # Apply discount.
    discount_price = round(session.vendor_offer * (1.0 - session.callback_discount), 2)
    session.vendor_offer = discount_price
    session.status = "offer_presented"

    _emit("callback_accepted", session_id=session_id, new_price=discount_price)

    # Auto-accept at the callback price.
    return accept_offer(session_id, ship)


def inspect_item(session_id: str, ship) -> dict:
    """Pay to inspect item details. Costs 5% of item value."""
    session = _get_session(session_id)
    if session is None:
        return {"ok": False, "error": "Session not found"}
    if session.status in ("completed", "broken_off"):
        return {"ok": False, "error": f"Session is {session.status}"}
    if session.inspect_paid:
        return {"ok": False, "error": "Already inspected"}

    cost = round(session.vendor_offer * session.quantity * INSPECT_COST_FRACTION, 2)
    credits = getattr(ship, "credits", 0.0)
    if credits < cost:
        return {"ok": False, "error": "Insufficient credits for inspection", "cost": cost}

    ship.credits = round(credits - cost, 2)
    session.inspect_paid = True

    import server.game_loop_vendor as glvr
    vendor = glvr.get_vendor_by_id(session.vendor_id)
    stock = vendor.inventory.get(session.item_type, 0) if vendor else 0

    _emit(
        "item_inspected",
        session_id=session_id,
        item_type=session.item_type,
        exact_stock=stock,
        cost=cost,
    )

    return {"ok": True, "exact_stock": stock, "cost": cost}


# ---------------------------------------------------------------------------
# Bluff
# ---------------------------------------------------------------------------


def attempt_bluff(session_id: str, bluff_type: str, ship) -> dict:
    """Attempt a bluff during negotiation."""
    session = _get_session(session_id)
    if session is None:
        return {"ok": False, "error": "Session not found"}
    if session.status in ("completed", "broken_off"):
        return {"ok": False, "error": f"Session is {session.status}"}
    if session.bluff_used:
        return {"ok": False, "error": "Bluff already used this session"}
    if bluff_type not in BLUFF_TYPES:
        return {"ok": False, "error": f"Invalid bluff type: {bluff_type}"}

    # Check vendor-level bluff blocks.
    blocked = _bluff_blocked.get(session.vendor_id, set())
    if bluff_type in blocked:
        return {"ok": False, "error": f"Vendor no longer responds to {bluff_type} bluffs"}

    session.bluff_used = True

    # Calculate success chance.
    chance = _calculate_bluff_chance(bluff_type, ship, session.vendor_id)
    success = _rng.random() < chance

    if success:
        result = _apply_bluff_success(session, bluff_type, ship)
    else:
        result = _apply_bluff_failure(session, bluff_type, ship)

    _emit(
        "bluff_result",
        session_id=session_id,
        bluff_type=bluff_type,
        success=success,
        chance=round(chance, 2),
        **result,
    )

    return {"ok": True, "success": success, "chance": round(chance, 2), **result}


def _calculate_bluff_chance(bluff_type: str, ship, vendor_id: str) -> float:
    """Calculate success probability for a bluff attempt."""
    chance = BLUFF_BASE_CHANCE

    # Reputation modifier.
    rep = getattr(ship, "trade_reputation", 0.0)
    if rep > 30:
        chance += BLUFF_REP_BONUS
    elif rep < 0:
        chance += BLUFF_REP_PENALTY  # negative

    # Decoded vendor signals bonus.
    if _has_decoded_vendor_signals(vendor_id):
        chance += BLUFF_COMMS_BONUS

    # Type-specific modifiers.
    if bluff_type == "not_urgent":
        hull = getattr(ship, "hull", 100.0)
        hull_max = getattr(ship, "hull_max", 100.0)
        if hull_max > 0 and hull / hull_max < 0.5:
            chance += BLUFF_DAMAGE_PENALTY  # negative — hard to bluff not-urgent with visible damage

    elif bluff_type == "military_authority":
        ship_class = getattr(ship, "ship_class", "")
        if ship_class in ("battleship", "cruiser", "carrier"):
            chance += BLUFF_MILITARY_BONUS

    return max(0.0, min(1.0, chance))


def _has_decoded_vendor_signals(vendor_id: str) -> bool:
    """Check if comms has decoded signals from the vendor's faction."""
    try:
        import server.game_loop_vendor as glvr
        vendor = glvr.get_vendor_by_id(vendor_id)
        if vendor is None:
            return False
        import server.game_loop_comms as glco
        return glco.has_decoded_vendor_signals(vendor.faction)
    except (ImportError, AttributeError):
        return False


def _apply_bluff_success(session: NegotiationSession, bluff_type: str, ship) -> dict:
    """Apply the effects of a successful bluff."""
    if bluff_type == "not_urgent":
        # Remove urgency modifier from price (approximation: reduce by urgency fraction).
        old_price = session.vendor_offer
        session.vendor_offer = round(old_price / COMBAT_URGENCY_MULTIPLIER, 2) if session.combat_active else old_price
        return {"new_price": session.vendor_offer, "effect": "urgency_removed"}

    elif bluff_type == "military_authority":
        old_price = session.vendor_offer
        session.vendor_offer = round(old_price * (1.0 - BLUFF_MILITARY_SUCCESS_DISCOUNT), 2)
        return {"new_price": session.vendor_offer, "effect": "military_discount"}

    elif bluff_type == "competing_offer":
        old_price = session.vendor_offer
        session.vendor_offer = round(old_price * (1.0 - BLUFF_COMPETING_SUCCESS_DISCOUNT), 2)
        return {"new_price": session.vendor_offer, "effect": "competing_discount"}

    return {}


def _apply_bluff_failure(session: NegotiationSession, bluff_type: str, ship) -> dict:
    """Apply the penalties of a failed bluff."""
    import server.game_loop_vendor as glvr

    if bluff_type == "not_urgent":
        glvr.adjust_reputation(ship, BLUFF_NOT_URGENT_PENALTY_REP, "bluff_failed")
        return {"penalty": "reputation", "rep_change": BLUFF_NOT_URGENT_PENALTY_REP}

    elif bluff_type == "military_authority":
        glvr.adjust_reputation(ship, BLUFF_MILITARY_FAIL_REP, "military_bluff_failed")
        # Block this bluff type for this vendor.
        if session.vendor_id not in _bluff_blocked:
            _bluff_blocked[session.vendor_id] = set()
        _bluff_blocked[session.vendor_id].add("military_authority")
        return {
            "penalty": "reputation_and_blocked",
            "rep_change": BLUFF_MILITARY_FAIL_REP,
            "cooldown": BLUFF_MILITARY_FAIL_COOLDOWN,
        }

    elif bluff_type == "competing_offer":
        # Vendor raises price slightly.
        session.vendor_offer = round(session.vendor_offer * 1.05, 2)
        return {"penalty": "price_increase", "new_price": session.vendor_offer}

    return {}


# ---------------------------------------------------------------------------
# Barter
# ---------------------------------------------------------------------------


def propose_barter(session_id: str, barter_offer: dict, ship) -> dict:
    """Propose a barter trade (goods/intel for the negotiated item)."""
    session = _get_session(session_id)
    if session is None:
        return {"ok": False, "error": "Session not found"}
    if session.status in ("completed", "broken_off"):
        return {"ok": False, "error": f"Session is {session.status}"}

    resource_items = barter_offer.get("resource_items", {})
    intel_items = barter_offer.get("intel_items", [])

    # Calculate total credit value.
    resource_value = calculate_barter_value(resource_items, BASE_PRICES)

    import server.game_loop_vendor as glvr
    vendor = glvr.get_vendor_by_id(session.vendor_id)
    vendor_type = vendor.vendor_type if vendor else "neutral_station"
    intel_value = calculate_intel_value(len(intel_items), vendor_type)

    total_value = round(resource_value + intel_value, 2)
    needed = round(session.vendor_offer * session.quantity, 2)

    if total_value < needed:
        shortfall = round(needed - total_value, 2)
        _emit("barter_shortfall", session_id=session_id, shortfall=shortfall, offered=total_value, needed=needed)
        return {"ok": False, "error": "Insufficient barter value", "shortfall": shortfall, "offered": total_value}

    # Verify ship has the resources.
    res = getattr(ship, "resources", None)
    if res is not None:
        for item_type, qty in resource_items.items():
            available = res.get(item_type) if hasattr(res, "get") else 0
            if available < qty:
                return {"ok": False, "error": f"Insufficient {item_type}"}

    # Execute: remove bartered goods from ship.
    if res is not None:
        for item_type, qty in resource_items.items():
            res.consume(item_type, float(qty))

    # Give negotiated item to ship (via vendor at-price trade with 0 credits).
    if vendor is not None:
        # Add item directly.
        glvr._add_to_ship(ship, session.item_type, session.quantity)
        vendor.inventory[session.item_type] = vendor.inventory.get(session.item_type, 0) - session.quantity

    session.status = "completed"
    _bundle_counts[session.vendor_id] = _bundle_counts.get(session.vendor_id, 0) + 1

    _emit(
        "barter_completed",
        session_id=session_id,
        resource_value=resource_value,
        intel_value=intel_value,
        total_value=total_value,
    )

    return {"ok": True, "total_value": total_value, "resource_value": resource_value, "intel_value": intel_value}


# ---------------------------------------------------------------------------
# Service contracts
# ---------------------------------------------------------------------------


def propose_service_contract(session_id: str, contract_type: str, ship) -> dict:
    """Propose a service contract to cover the trade cost."""
    session = _get_session(session_id)
    if session is None:
        return {"ok": False, "error": "Session not found"}
    if session.status in ("completed", "broken_off"):
        return {"ok": False, "error": f"Session is {session.status}"}
    if contract_type not in SERVICE_CONTRACT_TYPES:
        return {"ok": False, "error": f"Invalid contract type: {contract_type}"}

    import server.game_loop_vendor as glvr
    vendor = glvr.get_vendor_by_id(session.vendor_id)
    if vendor is None:
        return {"ok": False, "error": "Vendor not found"}

    credit_value = round(session.vendor_offer * session.quantity, 2)

    # Create a dynamic mission for the service contract.
    try:
        import server.game_loop_dynamic_missions as gldm
        from server.models.dynamic_mission import generate_service_contract_mission
        mission = generate_service_contract_mission(
            mission_id=f"contract_{session.id}",
            contract_type=contract_type,
            vendor_id=vendor.id,
            vendor_name=vendor.name,
            target_position=vendor.position,
            deadline=300.0,
            credit_value=credit_value,
        )
        offered = gldm.offer_mission(mission)
        if not offered:
            return {"ok": False, "error": "Cannot offer contract mission (max active reached)"}
    except (ImportError, AttributeError) as e:
        return {"ok": False, "error": f"Dynamic missions unavailable: {e}"}

    # Execute the trade immediately (vendor trusts the contract).
    if session.is_selling:
        result = glvr.sell_to_vendor_at_price(
            session.vendor_id, session.item_type, session.quantity,
            session.vendor_offer, ship,
        )
    else:
        # For buying, the trade is "on credit" — no credits deducted.
        glvr._add_to_ship(ship, session.item_type, session.quantity)
        if vendor:
            vendor.inventory[session.item_type] = max(
                0, vendor.inventory.get(session.item_type, 0) - session.quantity
            )
        result = {"ok": True, "item_type": session.item_type, "quantity": session.quantity}

    session.status = "completed"
    _bundle_counts[session.vendor_id] = _bundle_counts.get(session.vendor_id, 0) + 1

    _emit(
        "service_contract_created",
        session_id=session_id,
        contract_type=contract_type,
        mission_id=f"contract_{session.id}",
        credit_value=credit_value,
    )

    return {
        "ok": True,
        "contract_type": contract_type,
        "mission_id": f"contract_{session.id}",
        "credit_value": credit_value,
    }


# ---------------------------------------------------------------------------
# Combat pressure
# ---------------------------------------------------------------------------


def set_combat_active(active: bool) -> None:
    """Update combat state — affects prices and negotiation speed."""
    global _combat_active
    _combat_active = active


def is_combat_active() -> bool:
    return _combat_active


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


def tick(world, ship, dt: float) -> list[dict]:
    """Advance negotiation state: channel distances, callback timers."""
    events: list[dict] = []

    ship_x = getattr(ship, "x", 0.0)
    ship_y = getattr(ship, "y", 0.0)

    # Update channel distances and statuses.
    import server.game_loop_vendor as glvr
    channels_to_close: list[str] = []

    for ch in _channels:
        vendor = glvr.get_vendor_by_id(ch.vendor_id)
        if vendor is None:
            channels_to_close.append(ch.id)
            continue

        if ch.is_docked:
            ch.distance = 0.0
            ch.status = "open"
            continue

        vx, vy = vendor.position
        ch.distance = math.hypot(ship_x - vx, ship_y - vy)

        if ch.distance <= CHANNEL_RANGE_STABLE:
            ch.status = "open"
        elif ch.distance <= CHANNEL_RANGE_DEGRADED:
            if ch.status != "degraded":
                ch.status = "degraded"
                evt = {"type": "channel_degraded", "channel_id": ch.id}
                events.append(evt)
                _pending_events.append(evt)
        else:
            channels_to_close.append(ch.id)

    for cid in channels_to_close:
        close_channel(cid)
        evt = {"type": "channel_out_of_range", "channel_id": cid}
        events.append(evt)
        _pending_events.append(evt)

    # Tick callback timers.
    for sess in _sessions:
        if sess.status == "callback_pending" and sess.callback_timer > 0:
            sess.callback_timer -= dt
            if sess.callback_timer <= 0:
                sess.status = "broken_off"
                evt = {"type": "callback_expired", "session_id": sess.id}
                events.append(evt)
                _pending_events.append(evt)

    return events


# ---------------------------------------------------------------------------
# Public accessors for tests
# ---------------------------------------------------------------------------


def get_sessions() -> list[NegotiationSession]:
    return list(_sessions)


def get_bundle_count(vendor_id: str) -> int:
    return _bundle_counts.get(vendor_id, 0)
