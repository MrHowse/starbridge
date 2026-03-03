"""
Captain Orders — Priority Target Marker + General Orders + Bridge Control.

C.1.1: Priority target marking visible on all station maps.
C.1.2: Ship-wide general orders (battle_stations, silent_running, etc.).
C.2.1: Bridge control timer — boarders controlling the bridge cause defeat.

Public API (called by game_loop.py):
    reset()
    set_priority_target(entity_id, world) -> dict
    get_priority_target() -> str | None
    on_entity_destroyed(entity_id) -> bool
    get_crew_factor_boost() -> float
    set_general_order(order, ship, world) -> dict
    get_active_order() -> str | None
    acknowledge_all_stop() -> dict
    is_all_stop_active() -> bool
    get_target_profile_modifier() -> float
    get_accuracy_modifier() -> float
    tick(dt, ship, interior) -> list[tuple[str, dict]]
    serialise() -> dict
    deserialise(data)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.models.interior import ShipInterior
    from server.models.ship import Ship
    from server.models.world import World

logger = logging.getLogger("starbridge.captain_orders")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRIORITY_ACCURACY_BONUS: float = 0.05       # +5% hit chance on priority target
MORALE_BOOST_DURATION: float = 60.0         # seconds of crew factor boost after kill
MORALE_BOOST_AMOUNT: float = 0.02           # crew factor bonus per system
BRIDGE_CONTROL_DEFEAT_TIME: float = 60.0    # seconds of bridge control → defeat

VALID_ORDERS = frozenset({
    "battle_stations",
    "silent_running",
    "evasive_manoeuvres",
    "all_stop",
    "condition_green",
})

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_priority_target_id: str | None = None
_morale_boost_timer: float = 0.0
_morale_destroyed_id: str | None = None

_active_order: str | None = None
_all_stop_acknowledged: bool = False

_bridge_control_timer: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset() -> None:
    """Clear all captain orders state."""
    global _priority_target_id, _morale_boost_timer, _morale_destroyed_id
    global _active_order, _all_stop_acknowledged, _bridge_control_timer
    _priority_target_id = None
    _morale_boost_timer = 0.0
    _morale_destroyed_id = None
    _active_order = None
    _all_stop_acknowledged = False
    _bridge_control_timer = 0.0


# --- Priority Target ---

def set_priority_target(entity_id: str | None, world: "World") -> dict:
    """Set or clear the priority target. Returns result dict."""
    global _priority_target_id
    if entity_id is None:
        _priority_target_id = None
        return {"ok": True, "cleared": True}
    # Validate entity exists.
    found = any(e.id == entity_id for e in world.enemies)
    if not found:
        # Also check stations and creatures.
        found = any(s.id == entity_id for s in world.stations)
        if not found:
            found = any(c.id == entity_id for c in world.creatures)
    if not found:
        return {"ok": False, "reason": "Entity not found."}
    _priority_target_id = entity_id
    return {"ok": True, "entity_id": entity_id}


def get_priority_target() -> str | None:
    """Return the current priority target entity_id, or None."""
    return _priority_target_id


def on_entity_destroyed(entity_id: str) -> bool:
    """Called when an entity is destroyed. Returns True if it was the priority target."""
    global _priority_target_id, _morale_boost_timer, _morale_destroyed_id
    if _priority_target_id is not None and _priority_target_id == entity_id:
        _morale_destroyed_id = _priority_target_id
        _priority_target_id = None
        _morale_boost_timer = MORALE_BOOST_DURATION
        return True
    return False


def get_crew_factor_boost() -> float:
    """Return current morale boost amount (0.0 if no active boost)."""
    if _morale_boost_timer > 0.0:
        return MORALE_BOOST_AMOUNT
    return 0.0


# --- General Orders ---

def set_general_order(order: str, ship: "Ship", world: "World") -> dict:
    """Issue a general order. Returns result dict."""
    global _active_order, _all_stop_acknowledged
    if order not in VALID_ORDERS:
        return {"ok": False, "reason": f"Unknown order: {order}"}

    events: list[tuple[str, dict]] = []

    if order == "condition_green":
        # Clear active order and restore normal.
        prev = _active_order
        _active_order = None
        _all_stop_acknowledged = False
        ship.alert_level = "green"
        # Deactivate stealth if active.
        import server.game_loop_ew as glew
        if glew.is_stealth_engaged():
            glew.toggle_stealth(False)
        return {"ok": True, "order": "condition_green", "previous": prev}

    if order == "silent_running":
        import server.game_loop_ew as glew
        if not glew.is_stealth_capable():
            return {"ok": False, "reason": "Ship not stealth-capable."}
        result = glew.toggle_stealth(True)
        if not result.get("ok"):
            return {"ok": False, "reason": result.get("reason", "Stealth activation failed.")}
        _active_order = order
        _all_stop_acknowledged = False
        return {"ok": True, "order": order}

    if order == "battle_stations":
        ship.alert_level = "red"
        _active_order = order
        _all_stop_acknowledged = False
        return {"ok": True, "order": order}

    if order == "evasive_manoeuvres":
        _active_order = order
        _all_stop_acknowledged = False
        return {"ok": True, "order": order}

    if order == "all_stop":
        ship.throttle = 0
        _active_order = order
        _all_stop_acknowledged = False
        return {"ok": True, "order": order}

    return {"ok": False, "reason": "Unhandled order."}


def get_active_order() -> str | None:
    """Return the active general order, or None."""
    return _active_order


def acknowledge_all_stop() -> dict:
    """Helm acknowledges ALL STOP, resuming control."""
    global _active_order, _all_stop_acknowledged
    if _active_order != "all_stop":
        return {"ok": False, "reason": "No ALL STOP active."}
    _all_stop_acknowledged = True
    _active_order = None
    return {"ok": True}


def is_all_stop_active() -> bool:
    """True when ALL STOP is active and not yet acknowledged."""
    return _active_order == "all_stop" and not _all_stop_acknowledged


# --- Evasive Manoeuvres modifiers ---

def get_target_profile_modifier() -> float:
    """Multiplier for incoming hit chance (< 1.0 = harder to hit us). Used for evasive."""
    if _active_order == "evasive_manoeuvres":
        return 0.85
    return 1.0


def get_accuracy_modifier() -> float:
    """Additive modifier to our hit chance (negative = less accurate). Used for evasive."""
    if _active_order == "evasive_manoeuvres":
        return -0.10
    return 0.0


# --- Tick ---

def tick(dt: float, ship: "Ship", interior: "ShipInterior") -> list[tuple[str, dict]]:
    """Advance captain orders state. Returns events to broadcast."""
    global _morale_boost_timer, _bridge_control_timer
    events: list[tuple[str, dict]] = []

    # Morale boost countdown.
    if _morale_boost_timer > 0.0:
        _morale_boost_timer = max(0.0, _morale_boost_timer - dt)

    # ALL STOP enforcement.
    if is_all_stop_active():
        ship.throttle = 0

    # Bridge control timer — check if boarders control the bridge.
    import server.game_loop_security as gls
    occupied = gls.get_occupied_rooms()
    system_rooms = getattr(interior, "system_rooms", {})
    bridge_room = system_rooms.get("manoeuvring")
    if bridge_room and occupied.get(bridge_room) == "controlled":
        prev_timer = _bridge_control_timer
        _bridge_control_timer += dt
        if _bridge_control_timer >= BRIDGE_CONTROL_DEFEAT_TIME and prev_timer < BRIDGE_CONTROL_DEFEAT_TIME:
            events.append(("game.defeat", {"reason": "bridge_captured"}))
    else:
        _bridge_control_timer = 0.0

    return events


# --- Serialise / Deserialise ---

def serialise() -> dict:
    """Serialise captain orders state for save."""
    return {
        "priority_target_id": _priority_target_id,
        "morale_boost_timer": _morale_boost_timer,
        "morale_destroyed_id": _morale_destroyed_id,
        "active_order": _active_order,
        "all_stop_acknowledged": _all_stop_acknowledged,
        "bridge_control_timer": _bridge_control_timer,
    }


def deserialise(data: dict) -> None:
    """Restore captain orders state from save."""
    global _priority_target_id, _morale_boost_timer, _morale_destroyed_id
    global _active_order, _all_stop_acknowledged, _bridge_control_timer
    _priority_target_id = data.get("priority_target_id")
    _morale_boost_timer = data.get("morale_boost_timer", 0.0)
    _morale_destroyed_id = data.get("morale_destroyed_id")
    _active_order = data.get("active_order")
    _all_stop_acknowledged = data.get("all_stop_acknowledged", False)
    _bridge_control_timer = data.get("bridge_control_timer", 0.0)
