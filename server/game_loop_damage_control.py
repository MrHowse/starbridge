"""
Damage Control — room fire/damage events and DCT dispatch.

When the hull takes significant damage, a random interior room is escalated
in severity (normal → damaged → fire). Fires spread periodically to adjacent
rooms. Engineering can dispatch Damage Control Teams (DCTs) to repair rooms
one severity level at a time.

Severity order: normal < damaged < fire < decompressed
DCT can fix: fire → damaged → normal
Decompressed rooms cannot be repaired by DCT (they require EVA).

State is module-level; reset() is called at game start.
"""
from __future__ import annotations

import logging
import random

from server.models.interior import ShipInterior, Room
import server.game_loop_rationing as glrat

logger = logging.getLogger("starbridge.damage_control")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DCT_REPAIR_DURATION: float = 8.0     # seconds to reduce a room by one severity level
FIRE_SPREAD_INTERVAL: float = 20.0   # seconds between automatic fire-spread ticks
HULL_DAMAGE_THRESHOLD: float = 5.0   # accumulated hull damage required to trigger a room event
FIRE_CHANCE: float = 0.35            # probability that a new room event results in fire (vs damaged)

# Severity level mapping
_SEVERITY: dict[str, int] = {
    "normal": 0,
    "damaged": 1,
    "fire": 2,
    "decompressed": 3,
}
# One step down in severity (for DCT repair)
_SEVERITY_DOWN: dict[int, str] = {3: "fire", 2: "damaged", 1: "normal"}

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_active_dcts: dict[str, float] = {}         # room_id → elapsed repair seconds
_fire_spread_timer: float = FIRE_SPREAD_INTERVAL
_pending_hull_damage: float = 0.0            # accumulated hull damage not yet processed

_rng: random.Random = random.Random()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset() -> None:
    """Clear all damage-control state. Called at game start."""
    global _active_dcts, _fire_spread_timer, _pending_hull_damage
    _active_dcts = {}
    _fire_spread_timer = FIRE_SPREAD_INTERVAL
    _pending_hull_damage = 0.0




def serialise() -> dict:
    return {
        "active_dcts": dict(_active_dcts),
        "fire_spread_timer": _fire_spread_timer,
        "pending_hull_damage": _pending_hull_damage,
    }


def deserialise(data: dict) -> None:
    global _fire_spread_timer, _pending_hull_damage
    _active_dcts.clear()
    _active_dcts.update(data.get("active_dcts", {}))
    _fire_spread_timer    = data.get("fire_spread_timer", 0.0)
    _pending_hull_damage  = data.get("pending_hull_damage", 0.0)


def apply_hull_damage(amount: float, interior: ShipInterior) -> None:
    """Accumulate hull damage and trigger room events when threshold is reached.

    Each HULL_DAMAGE_THRESHOLD points of hull damage triggers one room event.
    Multiple threshold crossings in one call trigger multiple events.
    """
    global _pending_hull_damage
    if amount <= 0.0:
        return
    _pending_hull_damage += amount
    while _pending_hull_damage >= HULL_DAMAGE_THRESHOLD:
        _pending_hull_damage -= HULL_DAMAGE_THRESHOLD
        _trigger_room_event(interior)


def dispatch_dct(room_id: str, interior: ShipInterior) -> bool:
    """Dispatch a DCT to repair the specified room.

    Returns False if the room is already normal or decompressed (unrepairable).
    Preserves existing repair progress if a DCT was already active.
    """
    room = interior.rooms.get(room_id)
    if room is None or room.state in ("normal", "decompressed"):
        return False
    # Preserve existing progress if already dispatched.
    if room_id not in _active_dcts:
        _active_dcts[room_id] = 0.0
    return True


def cancel_dct(room_id: str) -> bool:
    """Cancel an active DCT. Returns False if no DCT was active for this room."""
    if room_id in _active_dcts:
        del _active_dcts[room_id]
        return True
    return False


def tick(interior: ShipInterior, dt: float, difficulty: object | None = None,
         resources: object | None = None) -> None:
    """Advance DCT repairs and fire spreading for one simulation tick.

    *difficulty* — when provided, ``repair_speed_multiplier`` scales DCT
    repair duration (>1 = faster repairs, shorter duration).
    *resources* — when provided (ResourceStore), repair material consumption
    is gated: fire→damaged costs 2 RMU, damaged→normal costs 5 RMU.
    At 0 RMU only fire→damaged (minor repair) works.
    """
    global _fire_spread_timer

    repair_mult = getattr(difficulty, "repair_speed_multiplier", 1.0) if difficulty else 1.0
    effective_repair_dur = DCT_REPAIR_DURATION / max(0.1, repair_mult)
    # v0.07 §6.6: Rationing slows repairs.
    _rm_eff = glrat.get_effectiveness_multiplier("repair_materials")
    effective_repair_dur /= max(0.1, _rm_eff)

    # Advance DCT repairs.
    completed: list[str] = []
    for room_id in list(_active_dcts):
        elapsed = _active_dcts[room_id] + dt
        room = interior.rooms.get(room_id)

        # Cancel if room no longer exists or is already normal.
        if room is None or room.state == "normal":
            completed.append(room_id)
            continue

        if elapsed >= effective_repair_dur:
            # Check repair material cost before completing.
            old_sev = _SEVERITY.get(room.state, 0)
            # fire→damaged = 2 RMU, damaged→normal = 5 RMU, decompressed→fire = 10 RMU
            if old_sev == 2:     # fire → damaged
                rmu_cost = 2
            elif old_sev == 1:   # damaged → normal
                rmu_cost = 5
            elif old_sev == 3:   # decompressed → fire
                rmu_cost = 10
            else:
                rmu_cost = 0

            # Gate major repairs behind repair materials.
            if resources is not None and rmu_cost > 0:
                available = getattr(resources, "repair_materials", float("inf"))
                if old_sev == 1 and available < rmu_cost:
                    # At 0 RMU: damaged→normal blocked (major repair).
                    # Keep timer at threshold so it retries when materials arrive.
                    _active_dcts[room_id] = effective_repair_dur
                    continue
                # Consume materials.
                if hasattr(resources, "consume"):
                    resources.consume("repair_materials", rmu_cost)
                    glrat.record_consumption("repair_materials", rmu_cost, 0.0)

            # Reduce severity by one level.
            new_state = _SEVERITY_DOWN.get(_SEVERITY.get(room.state, 0), "normal")
            room.state = new_state
            logger.debug("DCT repair: %s → %s", room_id, new_state)
            if room.state == "normal":
                completed.append(room_id)
            else:
                # Still damaged; restart timer for the next level.
                _active_dcts[room_id] = 0.0
        else:
            _active_dcts[room_id] = elapsed

    for room_id in completed:
        _active_dcts.pop(room_id, None)

    # Fire spread timer.
    _fire_spread_timer -= dt
    if _fire_spread_timer <= 0.0:
        _fire_spread_timer = FIRE_SPREAD_INTERVAL
        _tick_fire_spread(interior)


def build_dc_state(interior: ShipInterior, difficulty: object | None = None) -> dict:
    """Serialise current DC state for broadcasting to Engineering.

    Returns:
        {
          "rooms": {room_id: {"name", "state", "deck"}} — only non-normal rooms,
          "active_dcts": {room_id: progress_fraction}   — 0.0 to 1.0
        }
    """
    repair_mult = getattr(difficulty, "repair_speed_multiplier", 1.0) if difficulty else 1.0
    effective_repair_dur = DCT_REPAIR_DURATION / max(0.1, repair_mult)
    damaged_rooms = {
        room_id: {
            "name": room.name,
            "state": room.state,
            "deck": room.deck,
        }
        for room_id, room in interior.rooms.items()
        if room.state != "normal"
    }
    active_dcts = {
        room_id: round(min(elapsed / effective_repair_dur, 1.0), 2)
        for room_id, elapsed in _active_dcts.items()
    }
    return {"rooms": damaged_rooms, "active_dcts": active_dcts}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _trigger_room_event(interior: ShipInterior) -> None:
    """Pick a random non-decompressed room and escalate its damage state."""
    eligible = [r for r in interior.rooms.values() if r.state != "decompressed"]
    if not eligible:
        return
    room = _rng.choice(eligible)

    if room.state == "normal":
        room.state = "fire" if _rng.random() < FIRE_CHANCE else "damaged"
        logger.debug("Room event (from normal): %s → %s", room.id, room.state)
    elif room.state == "damaged":
        if _rng.random() < 0.5:
            room.state = "fire"
            logger.debug("Room event (escalation): %s → fire", room.id)
    elif room.state == "fire":
        # A room that is already on fire spreads immediately rather than escalating.
        _spread_fire_from(room, interior)


def _tick_fire_spread(interior: ShipInterior) -> None:
    """Each fire room attempts to ignite one adjacent room."""
    fire_rooms = [r for r in interior.rooms.values() if r.state == "fire"]
    for room in fire_rooms:
        candidates = [
            interior.rooms[rid]
            for rid in room.connections
            if rid in interior.rooms
            and interior.rooms[rid].state not in ("fire", "decompressed")
        ]
        if candidates:
            target = _rng.choice(candidates)
            old_state = target.state
            target.state = "damaged" if target.state == "normal" else "fire"
            logger.debug("Fire spread: %s → %s (%s → %s)", room.id, target.id, old_state, target.state)


def _spread_fire_from(room: Room, interior: ShipInterior) -> None:
    """Immediate fire spread from a room that was triggered while already burning."""
    candidates = [
        interior.rooms[rid]
        for rid in room.connections
        if rid in interior.rooms
        and interior.rooms[rid].state not in ("fire", "decompressed")
    ]
    if candidates:
        target = _rng.choice(candidates)
        target.state = "damaged" if target.state == "normal" else "fire"
        logger.debug("Immediate spread: %s → %s → %s", room.id, target.id, target.state)
