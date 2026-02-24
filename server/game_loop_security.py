"""
Security sub-module for the game loop.

Manages boarding events: marine squad deployment, intruder pathfinding,
combat resolution, AP economy, and per-tick interior state broadcast building.

The interior itself lives on ship.interior (ShipInterior). This module owns
the simulation logic and the boarding-active flag.

Public API (called by game_loop.py):
    reset()                          — called at game start
    start_boarding(interior, squads, intruders) — spawn combatants
    move_squad(interior, squad_id, room_id) → bool  — player move command
    toggle_door(interior, room_id, squad_id) → bool — player door command
    tick_security(interior, ship, dt) → list[tuple[str, dict]]
    is_boarding_active() → bool
    build_interior_state(interior, ship) → dict

Broadcast format for security events (returned from tick_security):
    Each item is (event_type: str, payload: dict), broadcast to ["security"].
    Event types:
        "security.intruder_reached_objective"  — intruder arrived at target room
        "security.intruder_defeated"           — intruder health reached zero
        "security.squad_casualty"              — squad lost a member in combat
        "security.squad_eliminated"            — squad count reached zero
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # ShipInterior used below via string annotations

from server.models.interior import ShipInterior
from server.models.security import (
    MARINE_DAMAGE_PER_TICK,
    INTRUDER_DAMAGE_PER_TICK,
    Intruder,
    MarineSquad,
    is_intruder_visible,
)
from server.models.ship import Ship

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_boarding_active: bool = False
_eliminated_reported: set[str] = set()   # squad IDs whose elimination was already emitted

# v0.05i — station boarding state
_station_boarding_active: bool = False
_station_boarding_interior: "ShipInterior | None" = None
_station_eliminated_reported: set[str] = set()


def reset() -> None:
    """Clear all boarding state. Called at game start."""
    global _boarding_active, _station_boarding_active, _station_boarding_interior
    _boarding_active = False
    _eliminated_reported.clear()
    _station_boarding_active = False
    _station_boarding_interior = None
    _station_eliminated_reported.clear()




def serialise() -> dict:
    return {
        "boarding_active": _boarding_active,
        "eliminated_reported": list(_eliminated_reported),
        "station_boarding_active": _station_boarding_active,
        "station_eliminated_reported": list(_station_eliminated_reported),
    }


def deserialise(data: dict) -> None:
    global _boarding_active, _station_boarding_active, _station_boarding_interior
    _boarding_active = data.get("boarding_active", False)
    _eliminated_reported.clear()
    _eliminated_reported.update(data.get("eliminated_reported", []))
    # Station boarding is not resumed from saves (transient combat state).
    _station_boarding_active = False
    _station_boarding_interior = None
    _station_eliminated_reported.clear()


# ---------------------------------------------------------------------------
# Boarding initialisation
# ---------------------------------------------------------------------------


def deploy_squads(interior: ShipInterior, squad_specs: list[dict]) -> None:
    """Place marine squads on the ship interior without activating boarding mode.

    Used during the tactical planning phase — squads are positioned before
    intruders arrive. Existing squads are replaced by the new specs.
    squad_specs: list of {id, room_id} dicts.
    """
    interior.marine_squads = [
        MarineSquad(id=s["id"], room_id=s["room_id"])
        for s in squad_specs
    ]


_DEFAULT_SQUAD_SPECS: list[dict] = [
    {"id": "squad_1", "room_id": "bridge"},
    {"id": "squad_2", "room_id": "combat_info"},
]


def start_boarding(
    interior: ShipInterior,
    squad_specs: list[dict],
    intruder_specs: list[dict],
) -> None:
    """Place marine squads and intruders on the ship, activate boarding mode.

    squad_specs: list of {id, room_id} dicts. If empty, any squads already
    placed by deploy_squads() are preserved (planning → combat transition).
    If no squads exist at all, default squads are auto-created.
    intruder_specs: list of {id, room_id, objective_id} dicts.
    """
    global _boarding_active

    if squad_specs:
        interior.marine_squads = [
            MarineSquad(id=s["id"], room_id=s["room_id"])
            for s in squad_specs
        ]
    elif not interior.marine_squads:
        # No squads provided and none pre-deployed — auto-create defaults.
        interior.marine_squads = [
            MarineSquad(id=s["id"], room_id=s["room_id"])
            for s in _DEFAULT_SQUAD_SPECS
            if s["room_id"] in interior.rooms
        ]

    interior.intruders = [
        Intruder(
            id=i["id"],
            room_id=i["room_id"],
            objective_id=i["objective_id"],
        )
        for i in intruder_specs
    ]
    _boarding_active = True
    _eliminated_reported.clear()


# ---------------------------------------------------------------------------
# Player commands
# ---------------------------------------------------------------------------


def move_squad(interior: ShipInterior, squad_id: str, target_room_id: str) -> bool:
    """Move a marine squad one BFS step toward the target room.

    Returns True if the move was executed, False if:
    - squad_id is unknown
    - squad has insufficient AP
    - target_room_id is unknown or unreachable
    - squad is already in the target room (no-op, still returns True)
    """
    squad = next((s for s in interior.marine_squads if s.id == squad_id), None)
    if squad is None:
        return False
    if target_room_id not in interior.rooms:
        return False
    if squad.room_id == target_room_id:
        return True   # already there — no AP cost
    if not squad.can_move():
        return False

    path = interior.find_path(squad.room_id, target_room_id)
    if not path or len(path) < 2:
        return False   # no path (blocked or disconnected)

    # Advance one room at a time along the path.
    squad.room_id = path[1]
    squad.deduct_move_ap()
    return True


def toggle_door(interior: ShipInterior, room_id: str, squad_id: str) -> bool:
    """Seal or unseal the door of a room.

    The acting squad must be in the target room or in an adjacent connected room.
    Returns True if the door was toggled, False if AP insufficient or not in range.
    """
    squad = next((s for s in interior.marine_squads if s.id == squad_id), None)
    if squad is None:
        return False
    room = interior.rooms.get(room_id)
    if room is None:
        return False
    if not squad.can_seal_door():
        return False

    # Squad must be in the room or an adjacent room.
    squad_room = interior.rooms.get(squad.room_id)
    if squad_room is None:
        return False
    in_room = squad.room_id == room_id
    adjacent = room_id in squad_room.connections
    if not in_room and not adjacent:
        return False

    room.door_sealed = not room.door_sealed
    squad.deduct_door_ap()
    return True


# ---------------------------------------------------------------------------
# Per-tick simulation
# ---------------------------------------------------------------------------


def tick_security(
    interior: ShipInterior,
    ship: Ship,
    dt: float,
) -> list[tuple[str, dict]]:
    """Simulate one tick of the boarding encounter.

    Returns a list of (event_type, payload) tuples to be broadcast to ["security"].
    Does nothing and returns [] when boarding is not active.
    """
    if not _boarding_active:
        return []

    events: list[tuple[str, dict]] = []

    # 1. Regen AP for squads that are still in the fight.
    for squad in interior.marine_squads:
        if not squad.is_eliminated():
            squad.regen_ap()

    # 2. Tick intruder move timers; move intruders that are ready.
    for intruder in interior.intruders:
        intruder.tick_move_timer()
        if not intruder.is_ready_to_move():
            continue

        if intruder.room_id == intruder.objective_id:
            # Already at objective — stay and report (once per "arrival" cycle).
            intruder.reset_move_timer()
            events.append((
                "security.intruder_reached_objective",
                {"intruder_id": intruder.id, "room_id": intruder.room_id},
            ))
            continue

        path = interior.find_path(intruder.room_id, intruder.objective_id)
        if path and len(path) >= 2:
            intruder.room_id = path[1]
        intruder.reset_move_timer()

        if intruder.room_id == intruder.objective_id:
            events.append((
                "security.intruder_reached_objective",
                {"intruder_id": intruder.id, "room_id": intruder.room_id},
            ))

    # 3. Combat: squads and intruders sharing a room fight each other.
    for squad in interior.marine_squads:
        if squad.is_eliminated():
            continue
        room_intruders = [
            i for i in interior.intruders
            if i.room_id == squad.room_id and not i.is_defeated()
        ]
        for intruder in room_intruders:
            # Marines deal damage to the intruder (scaled by active marine count).
            intruder.take_damage(MARINE_DAMAGE_PER_TICK * squad.count)
            # Intruder deals damage to the squad.
            casualty = squad.take_damage(INTRUDER_DAMAGE_PER_TICK)
            if casualty:
                events.append((
                    "security.squad_casualty",
                    {"squad_id": squad.id, "count": squad.count},
                ))

    # 4. Remove defeated intruders and emit events.
    defeated = [i for i in interior.intruders if i.is_defeated()]
    for d in defeated:
        events.append(("security.intruder_defeated", {"intruder_id": d.id}))
    interior.intruders = [i for i in interior.intruders if not i.is_defeated()]

    # 5. Emit elimination events for newly-eliminated squads (only once).
    for squad in interior.marine_squads:
        if squad.is_eliminated() and squad.id not in _eliminated_reported:
            _eliminated_reported.add(squad.id)
            events.append((
                "security.squad_eliminated",
                {"squad_id": squad.id},
            ))

    return events


# ---------------------------------------------------------------------------
# State broadcast builder
# ---------------------------------------------------------------------------


def is_boarding_active() -> bool:
    return _boarding_active


# ---------------------------------------------------------------------------
# Station boarding (v0.05i)
# ---------------------------------------------------------------------------


def start_station_boarding(
    station: "object",
    squad_specs: list[dict],
) -> None:
    """Board an enemy station: place squads and activate garrison as intruders.

    *station* must have a ``defenses`` attribute with a ``station_interior``
    (ShipInterior) and ``garrison_count`` (int).
    """
    global _station_boarding_active, _station_boarding_interior

    defenses = getattr(station, "defenses", None)
    if defenses is None or defenses.station_interior is None:
        return

    interior: ShipInterior = defenses.station_interior
    station_id: str = getattr(station, "id", "station")

    # Place the boarding party (squads from squad_specs).
    if squad_specs:
        interior.marine_squads = [
            MarineSquad(id=s["id"], room_id=s["room_id"])
            for s in squad_specs
        ]

    # Garrison becomes intruders — distributed across non-command rooms.
    garrison_count: int = defenses.garrison_count
    room_ids = [
        rid for rid in interior.rooms
        if not rid.endswith("_command")
    ]
    interior.intruders = [
        Intruder(
            id=f"{station_id}_garrison_{i}",
            room_id=room_ids[i % len(room_ids)] if room_ids else list(interior.rooms.keys())[0],
            objective_id=f"{station_id}_command",   # garrison defends command centre
        )
        for i in range(garrison_count)
    ]

    _station_boarding_active = True
    _station_boarding_interior = interior
    _station_eliminated_reported.clear()


def is_station_boarding_active() -> bool:
    return _station_boarding_active


def check_station_capture(station_id: str) -> bool:
    """Return True if the station has been captured.

    Capture condition: all garrison (intruders) defeated AND at least one
    marine squad is in the command centre room.
    """
    if not _station_boarding_active or _station_boarding_interior is None:
        return False
    interior = _station_boarding_interior
    if interior.intruders:
        return False   # garrison not yet defeated
    command_room_id = f"{station_id}_command"
    return any(
        sq.room_id == command_room_id and not sq.is_eliminated()
        for sq in interior.marine_squads
    )


def tick_station_boarding(ship: Ship, dt: float) -> list[tuple[str, dict]]:
    """Simulate one tick of station boarding. Returns events to broadcast to security."""
    if not _station_boarding_active or _station_boarding_interior is None:
        return []

    interior = _station_boarding_interior
    events: list[tuple[str, dict]] = []

    # AP regen
    for squad in interior.marine_squads:
        if not squad.is_eliminated():
            squad.regen_ap()

    # Intruder movement
    for intruder in interior.intruders:
        intruder.tick_move_timer()
        if not intruder.is_ready_to_move():
            continue
        if intruder.room_id == intruder.objective_id:
            intruder.reset_move_timer()
            events.append((
                "security.intruder_reached_objective",
                {"intruder_id": intruder.id, "room_id": intruder.room_id},
            ))
            continue
        path = interior.find_path(intruder.room_id, intruder.objective_id)
        if path and len(path) >= 2:
            intruder.room_id = path[1]
        intruder.reset_move_timer()
        if intruder.room_id == intruder.objective_id:
            events.append((
                "security.intruder_reached_objective",
                {"intruder_id": intruder.id, "room_id": intruder.room_id},
            ))

    # Combat
    for squad in interior.marine_squads:
        if squad.is_eliminated():
            continue
        room_intruders = [
            i for i in interior.intruders
            if i.room_id == squad.room_id and not i.is_defeated()
        ]
        for intruder in room_intruders:
            intruder.take_damage(MARINE_DAMAGE_PER_TICK * squad.count)
            casualty = squad.take_damage(INTRUDER_DAMAGE_PER_TICK)
            if casualty:
                events.append((
                    "security.squad_casualty",
                    {"squad_id": squad.id, "count": squad.count},
                ))

    # Remove defeated intruders
    defeated = [i for i in interior.intruders if i.is_defeated()]
    for d in defeated:
        events.append(("security.intruder_defeated", {"intruder_id": d.id}))
    interior.intruders = [i for i in interior.intruders if not i.is_defeated()]

    # Elimination events
    for squad in interior.marine_squads:
        if squad.is_eliminated() and squad.id not in _station_eliminated_reported:
            _station_eliminated_reported.add(squad.id)
            events.append(("security.squad_eliminated", {"squad_id": squad.id}))

    return events


def build_station_interior_state(station_id: str) -> dict:
    """Build the security.station_interior payload (no fog-of-war)."""
    if not _station_boarding_active or _station_boarding_interior is None:
        return {"is_boarding": False, "station_id": station_id, "squads": [], "intruders": [], "rooms": {}}

    interior = _station_boarding_interior
    squads = [
        {
            "id": sq.id,
            "room_id": sq.room_id,
            "health": round(sq.health, 1),
            "action_points": round(sq.action_points, 1),
            "count": sq.count,
        }
        for sq in interior.marine_squads
    ]
    intruders = [
        {
            "id": i.id,
            "room_id": i.room_id,
            "health": round(i.health, 1),
            "objective_id": i.objective_id,
        }
        for i in interior.intruders
    ]
    rooms = {
        rid: {"state": room.state, "door_sealed": room.door_sealed}
        for rid, room in interior.rooms.items()
    }
    return {
        "is_boarding": True,
        "station_id": station_id,
        "squads": squads,
        "intruders": intruders,
        "rooms": rooms,
    }


def build_interior_state(interior: ShipInterior, ship: Ship) -> dict:
    """Build the security.interior_state payload.

    Intruders are fog-of-war filtered: included only if a marine squad shares
    their room OR sensor efficiency is >= SENSOR_FOW_THRESHOLD.
    """
    sensor_eff = ship.systems["sensors"].efficiency

    squads = [
        {
            "id": sq.id,
            "room_id": sq.room_id,
            "health": round(sq.health, 1),
            "action_points": round(sq.action_points, 1),
            "count": sq.count,
        }
        for sq in interior.marine_squads
    ]

    intruders = [
        {
            "id": i.id,
            "room_id": i.room_id,
            "health": round(i.health, 1),
            "objective_id": i.objective_id,
        }
        for i in interior.intruders
        if is_intruder_visible(i, interior.marine_squads, sensor_eff)
    ]

    rooms = {
        room_id: {
            "state": room.state,
            "door_sealed": room.door_sealed,
        }
        for room_id, room in interior.rooms.items()
    }

    return {
        "is_boarding": _boarding_active,
        "squads": squads,
        "intruders": intruders,
        "rooms": rooms,
    }
