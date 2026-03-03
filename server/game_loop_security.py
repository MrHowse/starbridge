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
    DEFAULT_POSITIONS as MARINE_DEFAULT_POSITIONS,
    TEAM_NAMES as MARINE_TEAM_NAMES,
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
import server.game_loop_hazard_control as glhc
import server.game_loop_rationing as glrat

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

# v0.06.3 — ship security systems state
BULKHEAD_UNSEAL_TIME: float = 30.0   # seconds to unseal a bulkhead
ARM_CREW_TIME: float = 20.0          # seconds to arm/disarm crew on a deck
MAX_ARMED_DECKS: int = 2             # armoury can arm 2 decks at once
ALERT_LEVELS = ("normal", "caution", "combat", "evacuate")
EVACUATE_CREW_FACTOR: float = 0.10   # crew factor when deck evacuated
COMBAT_ALERT_CASUALTY_MULT: float = 0.5  # crew take 50% fewer casualties

# Door/room state per room (supplements Room.door_sealed)
_locked_doors: set[str] = set()          # room_ids with security-locked doors
_breached_doors: set[str] = set()        # room_ids with breached (broken) doors
_lockdown_decks: set[int] = set()        # decks under lockdown
_ship_lockdown: bool = False             # ship-wide lockdown active

# Internal sensors
_sensor_status: dict[str, str] = {}      # room_id -> "active"/"damaged"/"boosted"
_sensor_boost_rooms: set[str] = set()    # rooms with boosted sensors

# Emergency bulkheads (between deck pairs)
_sealed_bulkheads: set[tuple[int, int]] = set()  # (deck_above, deck_below)
_bulkhead_unseal_progress: dict[tuple[int, int], float] = {}  # progress toward unseal

# Alert levels per deck
_deck_alerts: dict[int, str] = {}        # deck_number -> alert level

# Armoury
_armed_decks: set[int] = set()           # decks with armed crew
_arming_progress: dict[int, float] = {}  # deck -> progress toward arming

# Quarantine
_quarantined_rooms: set[str] = set()     # room_ids under quarantine

# C.11: Security ↔ Hazard Control integration
_door_lock_origins: dict[str, str] = {}         # room_id → "security"|"hazard_control"
_pending_sabotage_fires: list[str] = []         # room_ids where sabotage sparked fire
FIRE_MARINE_DMG: float = 0.5    # HP/s from intensity ≥ 3 fire
VACUUM_MARINE_DMG: float = 2.0  # HP/s in vacuum
RAD_MARINE_DMG: float = 0.3     # HP/s in radiation zone
BOARDER_VACUUM_DMG: float = 3.0  # HP/s for boarders in vacuum
SABOTAGE_FIRE_CHANCE: float = 0.20  # chance of fire on sabotage complete


def reset() -> None:
    """Clear all boarding state. Called at game start."""
    global _boarding_active, _station_boarding_active, _station_boarding_interior
    global _next_party_id, _ship_lockdown, _active_deck_rooms
    _boarding_active = False
    _active_deck_rooms = None
    _eliminated_reported.clear()
    _station_boarding_active = False
    _station_boarding_interior = None
    _station_eliminated_reported.clear()
    _marine_teams.clear()
    _boarding_parties.clear()
    _next_party_id = 0
    _damage_accum.clear()
    # Security systems
    _locked_doors.clear()
    _breached_doors.clear()
    _lockdown_decks.clear()
    _ship_lockdown = False
    _sensor_status.clear()
    _sensor_boost_rooms.clear()
    _sealed_bulkheads.clear()
    _bulkhead_unseal_progress.clear()
    _deck_alerts.clear()
    _armed_decks.clear()
    _arming_progress.clear()
    _quarantined_rooms.clear()
    # C.11: Security ↔ HC integration.
    _door_lock_origins.clear()
    _pending_sabotage_fires.clear()




def serialise() -> dict:
    return {
        "boarding_active": _boarding_active,
        "eliminated_reported": list(_eliminated_reported),
        "station_boarding_active": _station_boarding_active,
        "station_eliminated_reported": list(_station_eliminated_reported),
        "marine_teams": [t.to_dict() for t in _marine_teams],
        "boarding_parties": [p.to_dict() for p in _boarding_parties],
        "next_party_id": _next_party_id,
        # Security systems
        "locked_doors": sorted(_locked_doors),
        "breached_doors": sorted(_breached_doors),
        "lockdown_decks": sorted(_lockdown_decks),
        "ship_lockdown": _ship_lockdown,
        "sensor_status": dict(_sensor_status),
        "sealed_bulkheads": [[a, b] for a, b in sorted(_sealed_bulkheads)],
        "deck_alerts": {str(k): v for k, v in _deck_alerts.items()},
        "armed_decks": sorted(_armed_decks),
        "quarantined_rooms": sorted(_quarantined_rooms),
        # C.11
        "door_lock_origins": dict(_door_lock_origins),
    }


def deserialise(data: dict) -> None:
    global _boarding_active, _station_boarding_active, _station_boarding_interior
    global _next_party_id, _ship_lockdown
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
    # Restore security systems.
    _locked_doors.clear()
    _locked_doors.update(data.get("locked_doors", []))
    _breached_doors.clear()
    _breached_doors.update(data.get("breached_doors", []))
    _lockdown_decks.clear()
    _lockdown_decks.update(data.get("lockdown_decks", []))
    _ship_lockdown = data.get("ship_lockdown", False)
    _sensor_status.clear()
    _sensor_status.update(data.get("sensor_status", {}))
    _sealed_bulkheads.clear()
    for pair in data.get("sealed_bulkheads", []):
        _sealed_bulkheads.add(tuple(pair))
    _deck_alerts.clear()
    for k, v in data.get("deck_alerts", {}).items():
        _deck_alerts[int(k)] = v
    _armed_decks.clear()
    _armed_decks.update(data.get("armed_decks", []))
    _quarantined_rooms.clear()
    _quarantined_rooms.update(data.get("quarantined_rooms", []))
    # C.11
    _door_lock_origins.clear()
    _door_lock_origins.update(data.get("door_lock_origins", {}))


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
    smoke = frozenset(glhc.get_smoke_rooms())

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
        if is_intruder_visible(i, interior.marine_squads, sensor_eff, smoke)
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
        "smoke_rooms": sorted(smoke),
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
        "locked_doors": sorted(_locked_doors),
        "breached_doors": sorted(_breached_doors),
        "ship_lockdown": _ship_lockdown,
        "lockdown_decks": sorted(_lockdown_decks),
        "sealed_bulkheads": [[a, b] for a, b in sorted(_sealed_bulkheads)],
        "deck_alerts": {str(k): v for k, v in _deck_alerts.items()},
        "armed_decks": sorted(_armed_decks),
        "quarantined_rooms": sorted(_quarantined_rooms),
        "sensor_status": dict(_sensor_status),
        "sensor_coverage": round(get_sensor_coverage(interior), 3),
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


def add_extra_marine_squad(
    crew_member_ids: list[str] | None = None,
) -> MarineTeam | None:
    """Add one extra marine squad (v0.07 §2.3 Marine Barracks module).

    Returns the created team, or None if already at max (3 teams).
    """
    idx = len(_marine_teams)
    if idx >= len(MARINE_TEAM_NAMES):
        return None  # max 3 teams

    meta = MARINE_TEAM_NAMES[idx]
    position = MARINE_DEFAULT_POSITIONS[idx] if idx < len(MARINE_DEFAULT_POSITIONS) else "conn"
    team_size = 4

    available_crew = list(crew_member_ids) if crew_member_ids else []
    members: list[str] = []
    for _ in range(team_size):
        if available_crew:
            members.append(available_crew.pop(0))
        else:
            members.append(f"{meta['id']}_marine_{len(members)}")

    leader = members[0] if members else ""

    team = MarineTeam(
        id=meta["id"],
        name=meta["name"],
        callsign=meta["callsign"],
        members=members,
        leader=leader,
        size=len(members),
        max_size=team_size,
        location=position,
    )
    _marine_teams.append(team)
    return team


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
# Ship security systems (v0.06.3 Part 5)
# ---------------------------------------------------------------------------

# Deck → room_id mapping for the default (frigate) interior.
DECK_ROOMS: dict[int, list[str]] = {
    1: ["bridge", "conn", "ready_room", "observation"],
    2: ["sensor_array", "science_lab", "comms_center", "astrometrics"],
    3: ["weapons_bay", "torpedo_room", "shields_control", "combat_info"],
    4: ["medbay", "surgery", "quarantine", "pharmacy"],
    5: ["main_engineering", "engine_room", "auxiliary_power", "cargo_hold"],
}

# Per-ship-class override (set by init_interior_config).
_active_deck_rooms: dict[int, list[str]] | None = None

# Inter-deck corridor connections (vertical corridor rooms).
DECK_CORRIDOR_PAIRS: list[tuple[str, str]] = [
    ("conn", "science_lab"),           # deck 1-2
    ("science_lab", "torpedo_room"),   # deck 2-3
    ("torpedo_room", "surgery"),       # deck 3-4
    ("surgery", "engine_room"),        # deck 4-5
]


def init_interior_config(ship_class: str) -> None:
    """Load per-ship-class deck rooms. Call at game start after reset()."""
    global _active_deck_rooms
    from server.models.interior import get_deck_rooms
    _active_deck_rooms = get_deck_rooms(ship_class)


def _get_deck_rooms() -> dict[int, list[str]]:
    """Return active deck rooms (class-specific if initialised, else frigate default)."""
    return _active_deck_rooms if _active_deck_rooms is not None else DECK_ROOMS


def _room_deck(room_id: str) -> int:
    """Return the deck number for a room_id, or 0 if unknown."""
    for deck, rooms in _get_deck_rooms().items():
        if room_id in rooms:
            return deck
    return 0


# ---- Door control ----


def lock_door(interior: ShipInterior, room_id: str,
              origin: str = "security") -> bool:
    """Lock a door. Returns False if room unknown or already breached.

    *origin* — "security" or "hazard_control" (C.11: origin tracking).
    """
    if room_id not in interior.rooms:
        return False
    if room_id in _breached_doors:
        return False  # breached doors can't be locked
    room = interior.rooms[room_id]
    room.door_sealed = True
    _locked_doors.add(room_id)
    _door_lock_origins[room_id] = origin
    return True


def unlock_door(interior: ShipInterior, room_id: str) -> bool:
    """Unlock a door. Returns False if room unknown."""
    if room_id not in interior.rooms:
        return False
    room = interior.rooms[room_id]
    room.door_sealed = False
    _locked_doors.discard(room_id)
    return True


# ---------------------------------------------------------------------------
# C.11: Security ↔ Hazard Control public API
# ---------------------------------------------------------------------------


def get_door_lock_origins() -> dict[str, str]:
    """Return room_id → origin mapping for locked doors."""
    return dict(_door_lock_origins)


def pop_sabotage_fires() -> list[str]:
    """Drain and return room_ids where sabotage sparked a fire."""
    fires = list(_pending_sabotage_fires)
    _pending_sabotage_fires.clear()
    return fires


def apply_hazard_damage_to_marines(
    fire_rooms: dict[str, int],
    vacuum_rooms: set[str],
    radiation_rooms: set[str],
    dt: float,
) -> list[tuple[str, dict]]:
    """Apply environmental hazard damage to marine teams.

    *fire_rooms* — room_id → intensity (only rooms with intensity ≥ 3).
    Returns list of (event_type, payload) tuples.
    """
    events: list[tuple[str, dict]] = []
    for team in _marine_teams:
        if team.is_incapacitated or team.size <= 0:
            continue
        loc = team.location
        dmg = 0.0
        cause = ""
        if loc in fire_rooms and fire_rooms[loc] >= 3:
            dmg += FIRE_MARINE_DMG * dt
            cause = "fire"
        if loc in vacuum_rooms:
            dmg += VACUUM_MARINE_DMG * dt
            cause = cause or "vacuum"
        if loc in radiation_rooms:
            dmg += RAD_MARINE_DMG * dt
            cause = cause or "radiation"
        if dmg <= 0:
            continue
        key = f"marine_{team.id}"
        _damage_accum[key] = _damage_accum.get(key, 0.0) + dmg
        while _damage_accum[key] >= 1.0 and team.size > 0:
            _damage_accum[key] -= 1.0
            if team.members:
                team.members.pop()
            team.size = max(0, team.size - 1)
            events.append((
                "security.marine_hazard_casualty",
                {"team_id": team.id, "cause": cause, "remaining": team.size},
            ))
    return events


def apply_vent_damage_to_boarders(
    vacuum_rooms: set[str],
    dt: float,
) -> list[tuple[str, dict]]:
    """Apply vacuum damage to boarding parties in vented rooms.

    Returns list of (event_type, payload) tuples.
    """
    events: list[tuple[str, dict]] = []
    for party in _boarding_parties:
        if party.is_eliminated:
            continue
        if party.location not in vacuum_rooms:
            continue
        key = f"boarder_{party.id}"
        _damage_accum[key] = _damage_accum.get(key, 0.0) + BOARDER_VACUUM_DMG * dt
        while _damage_accum[key] >= 1.0 and party.members > 0:
            _damage_accum[key] -= 1.0
            party.members -= 1
            events.append((
                "security.boarder_vacuum_casualty",
                {"party_id": party.id, "remaining": party.members},
            ))
    return events


def lockdown_deck(interior: ShipInterior, deck: int) -> int:
    """Lock all doors on a deck. Returns count of doors locked."""
    rooms = _get_deck_rooms().get(deck, [])
    count = 0
    for rid in rooms:
        if rid in interior.rooms and rid not in _breached_doors:
            interior.rooms[rid].door_sealed = True
            _locked_doors.add(rid)
            count += 1
    _lockdown_decks.add(deck)
    return count


def lift_deck_lockdown(interior: ShipInterior, deck: int) -> int:
    """Unlock all doors on a deck. Returns count of doors unlocked."""
    rooms = _get_deck_rooms().get(deck, [])
    count = 0
    for rid in rooms:
        if rid in interior.rooms and rid not in _breached_doors:
            interior.rooms[rid].door_sealed = False
            _locked_doors.discard(rid)
            count += 1
    _lockdown_decks.discard(deck)
    return count


def lockdown_all(interior: ShipInterior) -> int:
    """Ship-wide lockdown. Returns count of doors locked."""
    global _ship_lockdown
    count = 0
    for rid, room in interior.rooms.items():
        if rid not in _breached_doors:
            room.door_sealed = True
            _locked_doors.add(rid)
            count += 1
    _ship_lockdown = True
    _lockdown_decks.update(DECK_ROOMS.keys())
    return count


def lift_lockdown_all(interior: ShipInterior) -> int:
    """Lift ship-wide lockdown. Returns count of doors unlocked."""
    global _ship_lockdown
    count = 0
    for rid, room in interior.rooms.items():
        if rid not in _breached_doors:
            room.door_sealed = False
            _locked_doors.discard(rid)
            count += 1
    _ship_lockdown = False
    _lockdown_decks.clear()
    return count


def is_ship_lockdown() -> bool:
    return _ship_lockdown


def get_locked_doors() -> set[str]:
    return set(_locked_doors)


def get_breached_doors() -> set[str]:
    return set(_breached_doors)


def mark_door_breached(room_id: str) -> None:
    """Mark a door as breached (broken open by boarders). Called internally."""
    _breached_doors.add(room_id)
    _locked_doors.discard(room_id)


# ---- Internal sensors ----


def get_sensor_status(room_id: str) -> str:
    """Return sensor status for a room: 'active', 'damaged', or 'boosted'."""
    return _sensor_status.get(room_id, "active")


def set_sensor_status(room_id: str, status: str) -> None:
    """Set sensor status for a room."""
    _sensor_status[room_id] = status


def activate_sensor_boost(room_id: str) -> bool:
    """Boost sensors in a room. Returns True if successful."""
    if _sensor_status.get(room_id) == "damaged":
        return False  # can't boost damaged sensors
    _sensor_status[room_id] = "boosted"
    _sensor_boost_rooms.add(room_id)
    return True


def deactivate_sensor_boost(room_id: str) -> None:
    """Remove sensor boost from a room."""
    _sensor_boost_rooms.discard(room_id)
    if _sensor_status.get(room_id) == "boosted":
        _sensor_status[room_id] = "active"


def get_sensor_coverage(interior: ShipInterior) -> float:
    """Return fraction of rooms with working sensors (0.0-1.0)."""
    if not interior.rooms:
        return 0.0
    working = sum(
        1 for rid in interior.rooms
        if _sensor_status.get(rid, "active") != "damaged"
    )
    return working / len(interior.rooms)


# ---- Emergency bulkheads ----


def _normalise_bulkhead(deck_a: int, deck_b: int) -> tuple[int, int]:
    return (min(deck_a, deck_b), max(deck_a, deck_b))


def seal_bulkhead(deck_above: int, deck_below: int) -> bool:
    """Seal the bulkhead between two adjacent decks. Returns True if sealed."""
    pair = _normalise_bulkhead(deck_above, deck_below)
    if abs(pair[1] - pair[0]) != 1:
        return False  # decks must be adjacent
    _sealed_bulkheads.add(pair)
    _bulkhead_unseal_progress.pop(pair, None)
    return True


def start_unseal_bulkhead(deck_above: int, deck_below: int) -> bool:
    """Start unsealing a bulkhead (takes BULKHEAD_UNSEAL_TIME seconds).

    Returns True if unseal started. Actual unseal happens in tick.
    """
    pair = _normalise_bulkhead(deck_above, deck_below)
    if pair not in _sealed_bulkheads:
        return False
    _bulkhead_unseal_progress[pair] = 0.0
    return True


def is_bulkhead_sealed(deck_above: int, deck_below: int) -> bool:
    pair = _normalise_bulkhead(deck_above, deck_below)
    return pair in _sealed_bulkheads


def get_sealed_bulkheads() -> set[tuple[int, int]]:
    return set(_sealed_bulkheads)


def is_inter_deck_blocked(room_from: str, room_to: str) -> bool:
    """Return True if movement between rooms is blocked by a sealed bulkhead."""
    deck_from = _room_deck(room_from)
    deck_to = _room_deck(room_to)
    if deck_from == 0 or deck_to == 0 or deck_from == deck_to:
        return False
    pair = _normalise_bulkhead(deck_from, deck_to)
    return pair in _sealed_bulkheads


# ---- Alert levels ----


def set_deck_alert(deck: int, level: str) -> bool:
    """Set alert level for a deck. Returns False if invalid level."""
    if level not in ALERT_LEVELS:
        return False
    if deck not in _get_deck_rooms():
        return False
    _deck_alerts[deck] = level
    return True


def get_deck_alert(deck: int) -> str:
    return _deck_alerts.get(deck, "normal")


def get_all_deck_alerts() -> dict[int, str]:
    return {d: _deck_alerts.get(d, "normal") for d in DECK_ROOMS}


def get_casualty_multiplier(room_id: str) -> float:
    """Return crew casualty multiplier based on deck alert level.

    Combat alert halves casualties. Normal/caution = 1.0.
    """
    deck = _room_deck(room_id)
    level = _deck_alerts.get(deck, "normal")
    if level == "combat":
        return COMBAT_ALERT_CASUALTY_MULT
    return 1.0


def get_crew_factor_override(deck: int) -> float | None:
    """Return crew factor override if deck is evacuated, else None."""
    level = _deck_alerts.get(deck, "normal")
    if level == "evacuate":
        return EVACUATE_CREW_FACTOR
    return None


# ---- Armoury ----


def arm_crew(deck: int) -> bool:
    """Issue sidearms to crew on a deck. Returns False if at max armed decks."""
    if deck not in DECK_ROOMS:
        return False
    if deck in _armed_decks:
        return True  # already armed
    if len(_armed_decks) >= MAX_ARMED_DECKS:
        return False  # armoury stock exhausted
    _armed_decks.add(deck)
    return True


def disarm_crew(deck: int) -> bool:
    """Collect weapons from crew on a deck."""
    if deck not in _armed_decks:
        return False
    _armed_decks.discard(deck)
    return True


def is_crew_armed(deck: int) -> bool:
    return deck in _armed_decks


def get_armed_decks() -> set[int]:
    return set(_armed_decks)


def get_crew_firepower(room_id: str) -> float:
    """Return per-crew firepower for a room based on arming status."""
    deck = _room_deck(room_id)
    if deck in _armed_decks:
        return ARMED_CREW_FIREPOWER
    return CREW_FIREPOWER


# ---- Quarantine ----


def quarantine_room(interior: ShipInterior, room_id: str) -> bool:
    """Quarantine a room: lock doors and isolate atmosphere."""
    if room_id not in interior.rooms:
        return False
    _quarantined_rooms.add(room_id)
    interior.rooms[room_id].door_sealed = True
    _locked_doors.add(room_id)
    return True


def quarantine_deck(interior: ShipInterior, deck: int) -> int:
    """Quarantine all rooms on a deck. Returns count of rooms quarantined."""
    rooms = DECK_ROOMS.get(deck, [])
    count = 0
    for rid in rooms:
        if rid in interior.rooms:
            _quarantined_rooms.add(rid)
            interior.rooms[rid].door_sealed = True
            _locked_doors.add(rid)
            count += 1
    return count


def lift_quarantine(interior: ShipInterior, room_id: str) -> bool:
    """Lift quarantine on a room."""
    if room_id not in _quarantined_rooms:
        return False
    _quarantined_rooms.discard(room_id)
    interior.rooms[room_id].door_sealed = False
    _locked_doors.discard(room_id)
    return True


def is_quarantined(room_id: str) -> bool:
    return room_id in _quarantined_rooms


def get_quarantined_rooms() -> set[str]:
    return set(_quarantined_rooms)


# ---- Tick bulkhead unseal progress ----


def tick_security_systems(dt: float) -> list[tuple[str, dict]]:
    """Tick security systems that have timers (bulkhead unseal).

    Returns events to broadcast.
    """
    events: list[tuple[str, dict]] = []
    completed = []
    for pair, progress in _bulkhead_unseal_progress.items():
        _bulkhead_unseal_progress[pair] = progress + dt
        if _bulkhead_unseal_progress[pair] >= BULKHEAD_UNSEAL_TIME:
            _sealed_bulkheads.discard(pair)
            completed.append(pair)
            events.append((
                "security.bulkhead_unsealed",
                {"deck_above": pair[0], "deck_below": pair[1]},
            ))
    for pair in completed:
        del _bulkhead_unseal_progress[pair]
    return events


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
                # C.11: Sabotage may spark a fire.
                if _random.random() < SABOTAGE_FIRE_CHANCE:
                    _pending_sabotage_fires.append(party.location)
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
            mark_door_breached(next_room_id)
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
    resources: object | None = None,
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
        # v0.07 §6.1.1.7: At 0 AMU, marine firepower drops by 60%.
        if resources is not None and hasattr(resources, "is_depleted") and resources.is_depleted("ammunition"):
            from server.models.resources import AMMO_DEPLETED_FIREPOWER_PENALTY
            defender_power *= (1.0 - AMMO_DEPLETED_FIREPOWER_PENALTY)

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
            # v0.07 §6.1: Consume from ship ResourceStore (5 AMU per active squad per round).
            if resources is not None and hasattr(resources, "consume"):
                _ammo_amt = 5.0 * dt * 10 * glrat.get_consumption_multiplier("ammunition")
                resources.consume("ammunition", _ammo_amt)
                glrat.record_consumption("ammunition", _ammo_amt, 0.0)

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
    resources: object | None = None,
) -> list[tuple[str, dict]]:
    """Run one tick of the enhanced combat system.

    Returns events to broadcast. Should be called each tick alongside
    tick_security (which handles the legacy system).
    *resources* — when provided (ResourceStore), ammunition is consumed per
    active squad per round. At 0 AMU, firepower penalised by 60%.
    """
    if not _marine_teams and not _boarding_parties:
        return []

    events: list[tuple[str, dict]] = []

    _tick_boarding_parties(interior, dt, events)
    _tick_marine_teams(interior, dt, events)
    _tick_room_combat(dt, events, resources=resources)

    # Tick security system timers (bulkhead unseal)
    events.extend(tick_security_systems(dt))

    # Clean up eliminated parties
    _boarding_parties[:] = [p for p in _boarding_parties if not p.is_eliminated]

    # If no more boarding parties, deactivate (but keep marine teams)
    if not _boarding_parties and _boarding_active:
        # Only deactivate if legacy intruders are also gone
        if not interior.intruders:
            pass  # Keep boarding_active managed by legacy system

    return events


# ---------------------------------------------------------------------------
# C.2.1: Boarding Area Impact — occupied rooms + system penalties
# ---------------------------------------------------------------------------


def get_occupied_rooms() -> dict[str, str]:
    """Return {room_id: "contested"|"controlled"} for rooms with boarders.

    "controlled" = boarders present, no marines.
    "contested"  = both boarders and marines present.
    """
    occupied: dict[str, str] = {}
    # Gather rooms with boarding parties.
    boarder_rooms: set[str] = set()
    for party in _boarding_parties:
        if not party.is_eliminated and hasattr(party, "location") and party.location:
            boarder_rooms.add(party.location)

    # Gather rooms with marines.
    marine_rooms: set[str] = set()
    for team in _marine_teams:
        if team.status != "eliminated" and len(team.members) > 0 and team.location:
            marine_rooms.add(team.location)

    for room_id in boarder_rooms:
        if room_id in marine_rooms:
            occupied[room_id] = "contested"
        else:
            occupied[room_id] = "controlled"
    return occupied


def get_boarding_system_penalties(interior: ShipInterior) -> dict[str, float]:
    """Return {system_name: multiplier} for systems in boarder-occupied rooms.

    0.0 = fully controlled by boarders (system disabled).
    0.5 = contested (system at half effectiveness).
    """
    occupied = get_occupied_rooms()
    if not occupied:
        return {}
    system_rooms = getattr(interior, "system_rooms", {})
    penalties: dict[str, float] = {}
    for sys_name, room_id in system_rooms.items():
        status = occupied.get(room_id)
        if status == "controlled":
            penalties[sys_name] = 0.0
        elif status == "contested":
            penalties[sys_name] = 0.5
    return penalties


def get_boarder_proximity_rooms(interior: ShipInterior) -> set[str]:
    """Return rooms adjacent to boarder-occupied rooms (warning zone)."""
    occupied = get_occupied_rooms()
    if not occupied:
        return set()
    proximity: set[str] = set()
    for room_id in occupied:
        room = interior.rooms.get(room_id)
        if room:
            for conn_id in room.connections:
                if conn_id not in occupied:
                    proximity.add(conn_id)
    return proximity


def get_casualty_prediction() -> dict:
    """Return casualty prediction data for medical cross-station alert."""
    contested = sum(1 for s in get_occupied_rooms().values() if s == "contested")
    # Rough estimate: each contested room causes ~1 casualty per minute.
    return {
        "contested_rooms": contested,
        "estimated_casualties_per_minute": contested * 1.0,
    }
