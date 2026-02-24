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

Enhanced combat API (v0.06.3):
    init_marine_teams(ship_class, crew_ids)  — called at game start
    start_enhanced_boarding(interior, ...)    — create boarding party
    send_team(team_id, destination)           — player: move team
    set_team_patrol(team_id, route)           — player: patrol route
    assign_escort(team_id, repair_team_id)    — player: escort duty
    tick_combat(interior, ship, dt)           — enhanced combat tick
    get_marine_teams() → list[MarineTeam]
    get_boarding_parties() → list[BoardingParty]

Broadcast format for security events (returned from tick_security):
    Each item is (event_type: str, payload: dict), broadcast to ["security"].
    Event types:
        "security.intruder_reached_objective"  — intruder arrived at target room
        "security.intruder_defeated"           — intruder health reached zero
        "security.squad_casualty"              — squad lost a member in combat
        "security.squad_eliminated"            — squad count reached zero
        "security.boarding_alert"              — new boarding party detected
        "security.party_eliminated"            — boarding party wiped out
        "security.party_retreating"            — boarding party retreating
        "security.sabotage_started"            — boarders sabotaging objective
        "security.sabotage_complete"           — sabotage succeeded
        "security.room_secured"               — room cleared of hostiles
        "security.team_arrived"               — marine team reached destination
        "security.team_engaging"              — marine team engaging boarders
"""
from __future__ import annotations

import random as _random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # ShipInterior used below via string annotations

from server.models.boarding import (
    ADVANCE_TIME_PER_ROOM,
    BREACH_TIME,
    SABOTAGE_RATE,
    BoardingParty,
    generate_boarding_party,
)
from server.models.interior import ShipInterior
from server.models.marine_teams import (
    TRAVEL_TIME_PER_ROOM as MARINE_TRAVEL_TIME,
    MarineTeam,
    generate_marine_teams,
)
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

# v0.06.3 — enhanced combat state
_marine_teams: list[MarineTeam] = []
_boarding_parties: list[BoardingParty] = []
_next_party_id: int = 0
_damage_accum: dict[str, float] = {}  # entity_id -> fractional damage

# Crew combat constants
CREW_FIREPOWER: float = 0.15       # per crew member (untrained)
ARMED_CREW_FIREPOWER: float = 0.25 # armed crew (armoury issued)
MARINE_ARMOUR_MULT: float = 0.5    # marines take 50% less damage
BASE_CASUALTIES_PER_TICK: float = 0.3


def reset() -> None:
    """Clear all boarding state. Called at game start."""
    global _boarding_active, _station_boarding_active, _station_boarding_interior
    global _next_party_id
    _boarding_active = False
    _eliminated_reported.clear()
    _station_boarding_active = False
    _station_boarding_interior = None
    _station_eliminated_reported.clear()
    _marine_teams.clear()
    _boarding_parties.clear()
    _next_party_id = 0
    _damage_accum.clear()




def serialise() -> dict:
    return {
        "boarding_active": _boarding_active,
        "eliminated_reported": list(_eliminated_reported),
        "station_boarding_active": _station_boarding_active,
        "station_eliminated_reported": list(_station_eliminated_reported),
        "marine_teams": [t.to_dict() for t in _marine_teams],
        "boarding_parties": [p.to_dict() for p in _boarding_parties],
        "next_party_id": _next_party_id,
    }


def deserialise(data: dict) -> None:
    global _boarding_active, _station_boarding_active, _station_boarding_interior
    global _next_party_id
    _boarding_active = data.get("boarding_active", False)
    _eliminated_reported.clear()
    _eliminated_reported.update(data.get("eliminated_reported", []))
    # Station boarding is not resumed from saves (transient combat state).
    _station_boarding_active = False
    _station_boarding_interior = None
    _station_eliminated_reported.clear()
    # Restore enhanced combat state.
    _marine_teams.clear()
    for td in data.get("marine_teams", []):
        _marine_teams.append(MarineTeam.from_dict(td))
    _boarding_parties.clear()
    for pd in data.get("boarding_parties", []):
        _boarding_parties.append(BoardingParty.from_dict(pd))
    _next_party_id = data.get("next_party_id", 0)


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
        "marine_teams": [t.to_dict() for t in _marine_teams],
        "boarding_parties": [
            {
                "id": p.id, "location": p.location,
                "members": p.members, "max_members": p.max_members,
                "objective": p.objective, "status": p.status,
                "morale": round(p.morale, 2),
                "sabotage_progress": round(p.sabotage_progress, 2),
            }
            for p in _boarding_parties
            if not p.is_eliminated
        ],
    }


# ---------------------------------------------------------------------------
# Enhanced combat system (v0.06.3)
# ---------------------------------------------------------------------------


def init_marine_teams(
    ship_class: str = "frigate",
    crew_member_ids: list[str] | None = None,
) -> list[MarineTeam]:
    """Create marine teams at game start based on ship class.

    Returns the created teams (also stored in module state).
    """
    _marine_teams.clear()
    teams = generate_marine_teams(ship_class, crew_member_ids)
    _marine_teams.extend(teams)
    return list(_marine_teams)


def get_marine_teams() -> list[MarineTeam]:
    """Return current marine teams (read-only view)."""
    return list(_marine_teams)


def get_boarding_parties() -> list[BoardingParty]:
    """Return current boarding parties (read-only view)."""
    return list(_boarding_parties)


def start_enhanced_boarding(
    interior: ShipInterior,
    entry_point: str = "cargo_hold",
    difficulty_scale: float = 1.0,
    objective_override: str | None = None,
    rng: _random.Random | None = None,
) -> BoardingParty:
    """Create and register a new boarding party.

    Returns the created party. Activates boarding mode.
    """
    global _boarding_active, _next_party_id
    _next_party_id += 1
    party_id = f"bp_{_next_party_id:03d}"
    party = generate_boarding_party(
        party_id,
        entry_point=entry_point,
        difficulty_scale=difficulty_scale,
        rng=rng,
        objective_override=objective_override,
        interior=interior,
    )
    _boarding_parties.append(party)
    _boarding_active = True
    return party


# ---------------------------------------------------------------------------
# Player commands (enhanced)
# ---------------------------------------------------------------------------


def send_team(team_id: str, destination: str) -> bool:
    """Order a marine team to respond to a room.

    Returns False if team not found or unavailable.
    """
    team = next((t for t in _marine_teams if t.id == team_id), None)
    if team is None or team.is_incapacitated:
        return False
    team.order_respond(destination)
    return True


def set_team_patrol(team_id: str, route: list[str]) -> bool:
    """Set a patrol route for a marine team.

    Returns False if team not found or route empty.
    """
    if not route:
        return False
    team = next((t for t in _marine_teams if t.id == team_id), None)
    if team is None or team.is_incapacitated:
        return False
    team.order_patrol(route)
    return True


def station_team(team_id: str) -> bool:
    """Order a marine team to hold its current position."""
    team = next((t for t in _marine_teams if t.id == team_id), None)
    if team is None or team.is_incapacitated:
        return False
    team.order_station()
    return True


def assign_escort(team_id: str, repair_team_id: str) -> bool:
    """Assign a marine team to escort a repair team."""
    team = next((t for t in _marine_teams if t.id == team_id), None)
    if team is None or team.is_incapacitated:
        return False
    team.order_escort(repair_team_id)
    return True


def disengage_team(team_id: str) -> bool:
    """Order a marine team to break contact and retreat."""
    team = next((t for t in _marine_teams if t.id == team_id), None)
    if team is None:
        return False
    if team.status != "engaging":
        return False
    team.disengage()
    return True


# ---------------------------------------------------------------------------
# Enhanced tick — boarding party movement
# ---------------------------------------------------------------------------


def _tick_boarding_parties(
    interior: ShipInterior,
    dt: float,
    events: list[tuple[str, dict]],
) -> None:
    """Advance boarding parties: movement, breaching, sabotage."""
    for party in _boarding_parties:
        if party.is_eliminated:
            continue

        if party.status == "advancing":
            _advance_party(party, interior, dt, events)
        elif party.status == "sabotaging":
            party.sabotage_progress += SABOTAGE_RATE * dt
            if party.sabotage_progress >= 1.0:
                events.append((
                    "security.sabotage_complete",
                    {"party_id": party.id, "objective": party.objective,
                     "room_id": party.location},
                ))
                party.status = "retreating"
        elif party.status == "retreating":
            _retreat_party(party, interior, dt, events)

        # Morale check
        if party.check_morale():
            events.append((
                "security.party_retreating",
                {"party_id": party.id, "reason": "morale"},
            ))


def _advance_party(
    party: BoardingParty,
    interior: ShipInterior,
    dt: float,
    events: list[tuple[str, dict]],
) -> None:
    """Move a boarding party one step toward its objective."""
    if party.is_at_objective:
        # At objective — start sabotaging
        party.status = "sabotaging"
        events.append((
            "security.sabotage_started",
            {"party_id": party.id, "objective": party.objective,
             "room_id": party.location},
        ))
        return

    # Check if there's a calculated path to follow
    if party.path and party.path_index < len(party.path) - 1:
        next_room_id = party.path[party.path_index + 1]
    else:
        # Recalculate path
        path = interior.find_path(party.location, party.objective_room, ignore_sealed=True)
        if not path or len(path) < 2:
            return  # stuck
        party.path = path
        party.path_index = 0
        next_room_id = path[1]

    # Check for locked door
    next_room = interior.rooms.get(next_room_id)
    if next_room and next_room.door_sealed:
        # Breach
        party.breach_progress += dt
        if party.breach_progress >= BREACH_TIME:
            next_room.door_sealed = False  # door breached open
            party.breach_progress = 0.0
            events.append((
                "security.door_breached",
                {"party_id": party.id, "room_id": next_room_id},
            ))
        return

    # Advance
    party.advance_progress += dt
    if party.advance_progress >= ADVANCE_TIME_PER_ROOM:
        party.advance_progress = 0.0
        party.location = next_room_id
        party.path_index += 1

        if party.is_at_objective:
            party.status = "sabotaging"
            events.append((
                "security.sabotage_started",
                {"party_id": party.id, "objective": party.objective,
                 "room_id": party.location},
            ))


def _retreat_party(
    party: BoardingParty,
    interior: ShipInterior,
    dt: float,
    events: list[tuple[str, dict]],
) -> None:
    """Move a retreating boarding party back toward entry point."""
    if party.location == party.entry_point:
        # Escaped
        party.status = "eliminated"
        events.append((
            "security.party_escaped",
            {"party_id": party.id},
        ))
        return

    path = interior.find_path(party.location, party.entry_point)
    if not path or len(path) < 2:
        return
    party.advance_progress += dt
    if party.advance_progress >= ADVANCE_TIME_PER_ROOM:
        party.advance_progress = 0.0
        party.location = path[1]


# ---------------------------------------------------------------------------
# Enhanced tick — marine team movement
# ---------------------------------------------------------------------------


def _tick_marine_teams(
    interior: ShipInterior,
    dt: float,
    events: list[tuple[str, dict]],
) -> None:
    """Advance marine teams: respond, patrol, arrive."""
    for team in _marine_teams:
        if team.is_incapacitated:
            continue

        if team.status == "responding" and team.destination:
            _move_team_toward(team, team.destination, interior, dt)
            if team.location == team.destination:
                team.order_station()
                events.append((
                    "security.team_arrived",
                    {"team_id": team.id, "room_id": team.location},
                ))
                # Check if boarders here — auto-engage
                party_here = _get_boarder_at(team.location)
                if party_here:
                    team.engage(party_here.id)
                    party_here.status = "engaging"
                    party_here.engaged_by = team.id
                    events.append((
                        "security.team_engaging",
                        {"team_id": team.id, "party_id": party_here.id,
                         "room_id": team.location},
                    ))

        elif team.status == "patrolling":
            if not team.patrol_route:
                team.order_station()
                continue
            dest = team.patrol_route[team.patrol_index % len(team.patrol_route)]
            _move_team_toward(team, dest, interior, dt)
            if team.location == dest:
                team.patrol_index = (team.patrol_index + 1) % len(team.patrol_route)
                next_dest = team.patrol_route[team.patrol_index]
                team.destination = next_dest
                team.travel_progress = 0.0
                # Check for boarders
                party_here = _get_boarder_at(team.location)
                if party_here:
                    team.engage(party_here.id)
                    party_here.status = "engaging"
                    party_here.engaged_by = team.id
                    events.append((
                        "security.team_engaging",
                        {"team_id": team.id, "party_id": party_here.id,
                         "room_id": team.location},
                    ))

        # Decay suppression when not engaging
        if team.status != "engaging":
            team.decay_suppression()


def _move_team_toward(
    team: MarineTeam,
    destination: str,
    interior: ShipInterior,
    dt: float,
) -> None:
    """Advance a marine team one step toward destination."""
    if team.location == destination:
        return
    path = interior.find_path(team.location, destination)
    if not path or len(path) < 2:
        return
    team.travel_progress += dt
    if team.travel_progress >= MARINE_TRAVEL_TIME:
        team.travel_progress = 0.0
        team.location = path[1]


def _get_boarder_at(room_id: str) -> BoardingParty | None:
    """Return the first active boarding party at a room, or None."""
    for p in _boarding_parties:
        if p.location == room_id and not p.is_eliminated and p.status != "retreating":
            return p
    return None


# ---------------------------------------------------------------------------
# Enhanced tick — room combat resolution
# ---------------------------------------------------------------------------


def _tick_room_combat(
    dt: float,
    events: list[tuple[str, dict]],
) -> None:
    """Resolve combat in rooms where marines and boarders coexist."""
    # Collect contested rooms
    contested: set[str] = set()
    for party in _boarding_parties:
        if party.is_eliminated:
            continue
        for team in _marine_teams:
            if team.is_incapacitated:
                continue
            if team.location == party.location:
                contested.add(party.location)
                # Ensure both sides are in engaging status
                if team.status != "engaging":
                    team.engage(party.id)
                if party.status not in ("engaging", "retreating"):
                    party.status = "engaging"
                    party.engaged_by = team.id

    for room_id in contested:
        boarders = [p for p in _boarding_parties
                    if p.location == room_id and not p.is_eliminated]
        marines = [t for t in _marine_teams
                   if t.location == room_id and not t.is_incapacitated]

        if not boarders or not marines:
            continue

        # Calculate combat power
        attacker_power = sum(p.combat_power for p in boarders)
        defender_power = sum(t.firepower * t.size for t in marines)

        if attacker_power <= 0 and defender_power <= 0:
            continue

        total_power = attacker_power + defender_power
        attacker_ratio = attacker_power / total_power
        defender_ratio = defender_power / total_power

        # Casualties (scaled by dt for frame-rate independence)
        base_cas = BASE_CASUALTIES_PER_TICK * dt * 10  # normalise to 10Hz

        # Boarder losses (accumulate fractional damage)
        boarder_losses = base_cas * defender_ratio
        for party in boarders:
            share = party.combat_power / max(attacker_power, 0.01)
            acc = _damage_accum.get(party.id, 0.0) + boarder_losses * share
            losses = int(acc)
            _damage_accum[party.id] = acc - losses
            if losses > 0:
                party.apply_casualties(losses)
                if party.is_eliminated:
                    events.append((
                        "security.party_eliminated",
                        {"party_id": party.id, "room_id": room_id},
                    ))

        # Marine losses (reduced by armour, accumulate fractional damage)
        marine_losses = base_cas * attacker_ratio * MARINE_ARMOUR_MULT
        for team in marines:
            share = (team.firepower * team.size) / max(defender_power, 0.01)
            acc = _damage_accum.get(team.id, 0.0) + marine_losses * share
            losses = int(acc)
            _damage_accum[team.id] = acc - losses
            if losses > 0:
                actual = team.apply_casualties(losses)
                if actual > 0:
                    events.append((
                        "security.squad_casualty",
                        {"squad_id": team.id, "count": team.size},
                    ))
            team.consume_ammo()

        # Suppression
        if defender_power > attacker_power * 1.5:
            for party in boarders:
                party.morale = max(0.0, party.morale - 0.02 * dt * 10)

        # Room secured check
        all_eliminated = all(p.is_eliminated for p in boarders)
        if all_eliminated:
            for team in marines:
                if team.status == "engaging":
                    team.order_station()
            events.append((
                "security.room_secured",
                {"room_id": room_id},
            ))


# ---------------------------------------------------------------------------
# Enhanced tick — main entry point
# ---------------------------------------------------------------------------


def tick_combat(
    interior: ShipInterior,
    ship: Ship,
    dt: float,
) -> list[tuple[str, dict]]:
    """Run one tick of the enhanced combat system.

    Returns events to broadcast. Should be called each tick alongside
    tick_security (which handles the legacy system).
    """
    if not _marine_teams and not _boarding_parties:
        return []

    events: list[tuple[str, dict]] = []

    _tick_boarding_parties(interior, dt, events)
    _tick_marine_teams(interior, dt, events)
    _tick_room_combat(dt, events)

    # Clean up eliminated parties
    _boarding_parties[:] = [p for p in _boarding_parties if not p.is_eliminated]

    # If no more boarding parties, deactivate (but keep marine teams)
    if not _boarding_parties and _boarding_active:
        # Only deactivate if legacy intruders are also gone
        if not interior.intruders:
            pass  # Keep boarding_active managed by legacy system

    return events
