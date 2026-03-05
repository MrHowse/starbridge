"""
Mission sub-module for the game loop.

Manages all mission state: the mission engine, signal-triangulation,
resupply docking, and the per-tick mission update. Also owns the broadcast
builder functions for world entities and sensor contacts.
"""
from __future__ import annotations

import dataclasses
import math

import server.game_logger as gl
from server.models.messages import Message
from server.models.world import ENEMY_TYPE_PARAMS, World, spawn_enemy
from server.mission_graph import MissionGraph
from server.missions.loader import load_mission, spawn_from_mission, spawn_wave
from server.systems import sensors
from server.utils.math_helpers import distance
import server.game_loop_flight_ops as glfo
import server.game_loop_hazard_control as glhc
import server.game_loop_atmosphere as glatm
import server.game_loop_comms as glcomms

# ---------------------------------------------------------------------------
# Docking / resupply constants
# ---------------------------------------------------------------------------

DOCK_RANGE: float = 1_500.0
DOCK_TIME: float = 3.0
RESUPPLY_HULL: float = 20.0
RESUPPLY_AMMO: int = 5
RESUPPLY_AMMO_MAX: int = 10

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_mission_engine: MissionGraph | None = None
_signal_location: tuple[float, float] | None = None
_dock_timer: float = 0.0
_pending_puzzle_starts: list[dict] = []
_pending_boardings: list[dict] = []
_pending_deployments: list[dict] = []
_pending_outbreaks: list[dict] = []
_pending_casualties: list[dict] = []
_mission_dict: dict = {}


def reset() -> None:
    """Reset mission state. Called automatically by init_mission."""
    global _mission_engine, _signal_location, _dock_timer, _mission_dict
    _mission_engine = None
    _signal_location = None
    _dock_timer = 0.0
    _mission_dict = {}
    _pending_puzzle_starts.clear()
    _pending_boardings.clear()
    _pending_deployments.clear()
    _pending_outbreaks.clear()
    _pending_casualties.clear()


def pop_pending_casualties() -> list[dict]:
    """Return and clear crew_casualty actions queued since the last tick_mission call."""
    actions = list(_pending_casualties)
    _pending_casualties.clear()
    return actions


def pop_pending_puzzle_starts() -> list[dict]:
    """Return and clear start_puzzle actions queued since the last tick_mission call."""
    actions = list(_pending_puzzle_starts)
    _pending_puzzle_starts.clear()
    return actions


def pop_pending_deployments() -> list[dict]:
    """Return and clear deploy_squads actions queued since the last tick_mission call."""
    actions = list(_pending_deployments)
    _pending_deployments.clear()
    return actions


def pop_pending_boardings() -> list[dict]:
    """Return and clear start_boarding actions queued since the last tick_mission call."""
    actions = list(_pending_boardings)
    _pending_boardings.clear()
    return actions


def pop_pending_outbreaks() -> list[dict]:
    """Return and clear start_outbreak actions queued since the last tick_mission call."""
    actions = list(_pending_outbreaks)
    _pending_outbreaks.clear()
    return actions


def get_mission_engine() -> MissionGraph | None:
    return _mission_engine


def is_mission_active() -> bool:
    """Return True if a mission is currently loaded and running."""
    return _mission_engine is not None


def get_mission_dict() -> dict:
    """Return the currently loaded mission dict (empty if no mission loaded)."""
    return dict(_mission_dict)


def serialise_mission() -> dict:
    """Capture mission module state for save/resume."""
    return {
        "signal_location": list(_signal_location) if _signal_location else None,
        "dock_timer": _dock_timer,
        "graph_state": _mission_engine.serialise_state() if _mission_engine else None,
    }


def deserialise_mission(data: dict, mission_id: str) -> None:
    """Restore mission module state from save data.

    Reloads the mission JSON, creates a fresh MissionGraph, then overlays
    the saved runtime state so the graph resumes exactly where it left off.
    """
    global _mission_engine, _signal_location, _dock_timer, _mission_dict

    # Clear all transient pending queues — they don't survive a save/load.
    _pending_puzzle_starts.clear()
    _pending_boardings.clear()
    _pending_deployments.clear()
    _pending_outbreaks.clear()
    _pending_casualties.clear()

    _dock_timer = float(data.get("dock_timer", 0.0))

    sig = data.get("signal_location")
    _signal_location = (float(sig[0]), float(sig[1])) if sig else None

    # Reload mission dict from file and create a fresh engine.
    mission = load_mission(mission_id)
    _mission_dict = mission
    _mission_engine = MissionGraph(mission)

    # Overlay the saved runtime state on top of the freshly constructed graph.
    graph_state = data.get("graph_state")
    if graph_state is not None:
        _mission_engine.deserialise_state(graph_state)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init_mission(mission_id: str, world: World) -> None:
    """Load and initialise the mission, spawn all entities."""
    import server.game_loop_weapons as glw

    global _mission_engine, _signal_location, _dock_timer, _mission_dict
    _dock_timer = 0.0

    mission = load_mission(mission_id)
    _mission_dict = mission

    if mission_id == "sandbox":
        _spawn_sandbox_enemies(world)
    else:
        spawn_from_mission(mission, world, 0)

    _mission_engine = MissionGraph(mission)

    sig = mission.get("signal_location")
    _signal_location = (float(sig["x"]), float(sig["y"])) if sig else None

    # Place ship at mission-defined start position if specified.
    start_pos = mission.get("start_position")
    if start_pos:
        world.ship.x = float(start_pos.get("x", world.ship.x))
        world.ship.y = float(start_pos.get("y", world.ship.y))
        if "heading" in start_pos:
            world.ship.heading = float(start_pos["heading"])


def _spawn_sandbox_enemies(world: World) -> None:
    """Spawn initial enemies at fixed offsets from the sector centre."""
    import server.game_loop_weapons as glw

    cx = world.width / 2
    cy = world.height / 2
    scout = spawn_enemy("scout", cx + 20_000.0, cy - 18_000.0, glw.next_entity_id("enemy"))
    world.enemies.append(scout)
    cruiser = spawn_enemy("cruiser", cx - 18_000.0, cy + 18_000.0, glw.next_entity_id("enemy"))
    world.enemies.append(cruiser)


# ---------------------------------------------------------------------------
# Signal scan helpers
# ---------------------------------------------------------------------------


def is_signal_scan(entity_id: str) -> bool:
    """Return True if this entity_id is the mission signal (for triangulation)."""
    return entity_id == "signal" and _signal_location is not None


async def handle_signal_scans(action_events: list[tuple[str, dict]], manager: object) -> None:
    """Process signal.scan_result events (Mission 3 triangulation)."""
    if _signal_location is None or _mission_engine is None or manager is None:
        return

    for i in range(len(action_events) - 1, -1, -1):
        event_type, payload = action_events[i]
        if event_type == "signal.scan_result":
            action_events.pop(i)
            ship_x = payload["ship_x"]
            ship_y = payload["ship_y"]
            sig_x, sig_y = _signal_location

            bearing = math.degrees(math.atan2(sig_x - ship_x, ship_y - sig_y)) % 360

            _mission_engine.record_signal_scan(ship_x, ship_y)
            scan_count = _mission_engine._triangulation_count  # type: ignore[attr-defined]

            await manager.broadcast(  # type: ignore[union-attr]
                Message.build(
                    "mission.signal_bearing",
                    {
                        "bearing": round(bearing, 1),
                        "scan_count": scan_count,
                        "ship_x": round(ship_x, 1),
                        "ship_y": round(ship_y, 1),
                    },
                )
            )


# ---------------------------------------------------------------------------
# Asteroid collisions (Mission 3)
# ---------------------------------------------------------------------------


def apply_asteroid_collisions(world: World) -> None:
    """Apply hull damage and velocity reduction when ship is inside an asteroid."""
    ship = world.ship
    for asteroid in world.asteroids:
        if distance(ship.x, ship.y, asteroid.x, asteroid.y) < asteroid.radius:
            ship.hull = max(0.0, ship.hull - 2.0)
            ship.velocity = ship.velocity * 0.8


# ---------------------------------------------------------------------------
# Resupply docking (Mission 2)
# ---------------------------------------------------------------------------


async def tick_docking(world: World, manager: object, dt: float) -> None:
    """Check proximity to a station and apply resupply if docked long enough."""
    import server.game_loop_weapons as glw

    global _dock_timer
    if not world.stations:
        return

    near_station = next(
        (s for s in world.stations if distance(world.ship.x, world.ship.y, s.x, s.y) < DOCK_RANGE),
        None,
    )
    if near_station is not None:
        _dock_timer += dt
        if _dock_timer >= DOCK_TIME:
            _dock_timer = 0.0
            world.ship.hull = min(100.0, world.ship.hull + RESUPPLY_HULL)
            new_ammo = min(RESUPPLY_AMMO_MAX, glw.get_ammo() + RESUPPLY_AMMO)
            glw.set_ammo(new_ammo)
            from server.game_loop_medical_v2 import RESUPPLY_AMOUNT as MED_AMOUNT, RESUPPLY_MAX as MED_MAX
            world.ship.medical_supplies = min(MED_MAX, world.ship.medical_supplies + MED_AMOUNT)
            await manager.broadcast(  # type: ignore[union-attr]
                Message.build(
                    "ship.resupplied",
                    {
                        "hull": round(world.ship.hull, 1),
                        "torpedo_ammo": new_ammo,
                        "medical_supplies": world.ship.medical_supplies,
                    },
                )
            )
    else:
        _dock_timer = 0.0


# ---------------------------------------------------------------------------
# Mission engine tick
# ---------------------------------------------------------------------------


async def tick_mission(
    world: World,
    ship: object,
    manager: object,
    dt: float,
) -> tuple[bool, str | None]:
    """Tick the mission engine. Returns (game_over, result)."""
    if _mission_engine is None:
        return False, None

    newly_completed = _mission_engine.tick(world, ship, dt)  # type: ignore[arg-type]
    for obj_id in newly_completed:
        gl.log_event("mission", "objective_completed", {"objective_id": obj_id})

    for action in _mission_engine.pop_pending_actions():
        if action.get("action") == "spawn_wave":
            spawn_wave(action.get("enemies", []), world)
            _ehm = getattr(ship.difficulty, "enemy_health_multiplier", 1.0)
            if _ehm != 1.0:
                for _e in world.enemies:
                    if _e.hull == ENEMY_TYPE_PARAMS.get(_e.type, {}).get("hull", 0):
                        # Only scale freshly spawned enemies at base hull.
                        _e.hull = round(_e.hull * _ehm, 1)
        elif action.get("action") == "start_puzzle":
            _pending_puzzle_starts.append(action)
        elif action.get("action") == "deploy_squads":
            _pending_deployments.append(action)
        elif action.get("action") == "start_boarding":
            _pending_boardings.append(action)
        elif action.get("action") == "start_outbreak":
            _pending_outbreaks.append(action)
        elif action.get("action") == "start_fire":
            _exec_start_fire(action, ship)
        elif action.get("action") == "create_breach":
            _exec_create_breach(action, ship)
        elif action.get("action") == "apply_radiation":
            _exec_apply_radiation(action, ship)
        elif action.get("action") == "structural_damage":
            _exec_structural_damage(action, ship)
        elif action.get("action") == "contaminate_atmosphere":
            _exec_contaminate_atmosphere(action, ship)
        elif action.get("action") == "system_damage":
            _exec_system_damage(action, ship)
        elif action.get("action") == "crew_casualty":
            _pending_casualties.append(action)
        elif action.get("action") == "send_transmission":
            _exec_send_transmission(action)

    if newly_completed:
        await manager.broadcast(  # type: ignore[union-attr]
            Message.build(
                "mission.objective_update",
                {
                    "objectives": [
                        dataclasses.asdict(o)
                        for o in _mission_engine.get_objectives()
                    ]
                },
            )
        )

    over, result = _mission_engine.is_over()
    return over, result


# ---------------------------------------------------------------------------
# v0.08 environmental action executors
# ---------------------------------------------------------------------------

_VALID_SYSTEMS = frozenset(
    {"engines", "beams", "torpedoes", "shields", "sensors", "manoeuvring",
     "flight_deck", "ecm_suite", "point_defence"}
)

_VALID_CONTAMINANTS = frozenset({"toxic_gas", "smoke", "biological", "chemical"})

# Map contaminant name → AtmosphereState attribute
_CONTAMINANT_ATTR = {
    "toxic_gas": "coolant",
    "smoke": "smoke",
    "biological": "chemical",
    "chemical": "chemical",
}


def _exec_start_fire(action: dict, ship: object) -> None:
    """Start a fire in a ship room via HazCon module."""
    room_id = action.get("room_id", "")
    intensity = max(1, min(5, int(action.get("intensity", 2))))
    interior = getattr(ship, "interior", None)
    if interior is None:
        gl.log_event("mission", "action_error", {"action": "start_fire", "error": "no interior"})
        return
    try:
        glhc.start_fire(room_id, intensity, interior)
    except Exception as exc:
        gl.log_event("mission", "action_error", {"action": "start_fire", "room_id": room_id, "error": str(exc)})


def _exec_create_breach(action: dict, ship: object) -> None:
    """Create a hull breach in a ship room via atmosphere module."""
    room_id = action.get("room_id", "")
    severity = action.get("severity", "minor")
    # Normalise "moderate" → "major" (atmosphere API only has minor/major)
    if severity == "moderate":
        severity = "major"
    if severity not in ("minor", "major"):
        severity = "minor"
    interior = getattr(ship, "interior", None)
    if interior is None:
        gl.log_event("mission", "action_error", {"action": "create_breach", "error": "no interior"})
        return
    try:
        glatm.create_breach(room_id, severity, interior)
    except Exception as exc:
        gl.log_event("mission", "action_error", {"action": "create_breach", "room_id": room_id, "error": str(exc)})


def _exec_apply_radiation(action: dict, ship: object) -> None:
    """Apply radiation to a room's atmosphere."""
    room_id = action.get("room_id", "")
    tier = max(1, min(4, int(action.get("tier", 1))))
    amount = tier * 25  # tier 1→25, 2→50, 3→75, 4→100
    try:
        atm = glatm.get_atmosphere(room_id)
        if atm is None:
            gl.log_event("mission", "action_error", {"action": "apply_radiation", "room_id": room_id, "error": "unknown room"})
            return
        atm.radiation = min(100.0, atm.radiation + amount)
    except Exception as exc:
        gl.log_event("mission", "action_error", {"action": "apply_radiation", "error": str(exc)})


def _exec_structural_damage(action: dict, ship: object) -> None:
    """Apply structural damage to a ship section via a room_id lookup."""
    room_id = action.get("section", action.get("room_id", ""))
    amount = max(1.0, min(100.0, float(action.get("amount", 10))))
    try:
        sec = glhc.get_section_for_room(room_id)
        if sec is None:
            gl.log_event("mission", "action_error", {"action": "structural_damage", "section": room_id, "error": "unknown room/section"})
            return
        sec.integrity = max(0.0, sec.integrity - amount)
    except Exception as exc:
        gl.log_event("mission", "action_error", {"action": "structural_damage", "error": str(exc)})


def _exec_contaminate_atmosphere(action: dict, ship: object) -> None:
    """Add contaminant to a room's atmosphere."""
    room_id = action.get("room_id", "")
    contaminant = action.get("contaminant", "smoke")
    concentration = max(0.0, min(1.0, float(action.get("concentration", 0.5))))
    attr = _CONTAMINANT_ATTR.get(contaminant, "smoke")
    try:
        atm = glatm.get_atmosphere(room_id)
        if atm is None:
            gl.log_event("mission", "action_error", {"action": "contaminate_atmosphere", "room_id": room_id, "error": "unknown room"})
            return
        current = getattr(atm, attr, 0.0)
        setattr(atm, attr, min(100.0, current + concentration * 100))
    except Exception as exc:
        gl.log_event("mission", "action_error", {"action": "contaminate_atmosphere", "error": str(exc)})


def _exec_system_damage(action: dict, ship: object) -> None:
    """Apply damage to a named ship system."""
    system_name = action.get("system", "")
    amount = max(1.0, min(100.0, float(action.get("amount", 10))))
    if system_name not in _VALID_SYSTEMS:
        gl.log_event("mission", "action_error", {"action": "system_damage", "system": system_name, "error": "invalid system"})
        return
    systems = getattr(ship, "systems", {})
    sys_obj = systems.get(system_name) if isinstance(systems, dict) else None
    if sys_obj is None:
        gl.log_event("mission", "action_error", {"action": "system_damage", "system": system_name, "error": "system not found"})
        return
    try:
        sys_obj.health = max(0.0, sys_obj.health - amount)
    except Exception as exc:
        gl.log_event("mission", "action_error", {"action": "system_damage", "error": str(exc)})


def _exec_send_transmission(action: dict) -> None:
    """Inject a signal into the comms queue."""
    faction = action.get("faction", "unknown")
    message = action.get("message", "")
    channel = action.get("channel", "open")
    try:
        kwargs: dict = {
            "source": faction,
            "source_name": faction.capitalize(),
            "raw_content": message,
            "decoded_content": message,
            "faction": faction,
        }
        if channel == "open":
            kwargs["auto_decoded"] = True
            kwargs["requires_decode"] = False
        elif channel == "encrypted":
            kwargs["requires_decode"] = True
            kwargs["auto_decoded"] = False
        elif channel == "distress":
            kwargs["signal_type"] = "distress"
            kwargs["auto_decoded"] = True
            kwargs["requires_decode"] = False
            kwargs["priority"] = "high"
        glcomms.add_signal(**kwargs)
    except Exception as exc:
        gl.log_event("mission", "action_error", {"action": "send_transmission", "error": str(exc)})


# ---------------------------------------------------------------------------
# Broadcast builder helpers
# ---------------------------------------------------------------------------


def build_sensor_contacts(
    world: World,
    ship: object,
    extra_bubbles: list[tuple[float, float, float]] | None = None,
    hazard_modifier: float = 1.0,
    ghost_contacts: list[dict] | None = None,
) -> Message:
    """Build the sensor.contacts message for Weapons / Science clients.

    *hazard_modifier* reduces the effective sensor range when environmental
    hazards are active (e.g. 0.5 inside a nebula sector).
    *ghost_contacts* — corvette ECM ghost contacts to inject.
    """
    torpedoes = [
        {
            "id": t.id,
            "owner": t.owner,
            "x": round(t.x, 1),
            "y": round(t.y, 1),
            "heading": round(t.heading, 2),
            "torpedo_type": t.torpedo_type,
        }
        for t in world.torpedoes
    ]
    return Message.build(
        "sensor.contacts",
        {
            "contacts": sensors.build_sensor_contacts(world, ship, extra_bubbles, hazard_modifier, ghost_contacts=ghost_contacts),  # type: ignore[arg-type]
            "torpedoes": torpedoes,
        },
    )


def _serialise_defenses(defenses: object) -> dict:
    """Serialise EnemyStationDefenses to a JSON-safe dict."""
    arcs = [
        {"id": g.id, "hp": round(g.hp, 1), "hp_max": g.hp_max,
         "arc_start": g.arc_start, "arc_end": g.arc_end, "active": g.active}
        for g in defenses.shield_arcs  # type: ignore[attr-defined]
    ]
    turrets = [
        {"id": t.id, "hp": round(t.hp, 1), "hp_max": t.hp_max,
         "facing": t.facing, "arc_deg": t.arc_deg, "active": t.active}
        for t in defenses.turrets  # type: ignore[attr-defined]
    ]
    launchers = [
        {"id": l.id, "hp": round(l.hp, 1), "hp_max": l.hp_max, "active": l.active}
        for l in defenses.launchers  # type: ignore[attr-defined]
    ]
    bays = [
        {"id": b.id, "hp": round(b.hp, 1), "hp_max": b.hp_max,
         "active": b.active, "fighters_in_bay": b.fighters_in_bay}
        for b in defenses.fighter_bays  # type: ignore[attr-defined]
    ]
    sa = defenses.sensor_array  # type: ignore[attr-defined]
    reactor = defenses.reactor  # type: ignore[attr-defined]
    return {
        "shield_arcs": arcs,
        "turrets": turrets,
        "launchers": launchers,
        "fighter_bays": bays,
        "sensor_array": {
            "id": sa.id, "hp": round(sa.hp, 1), "hp_max": sa.hp_max,
            "active": sa.active, "jammed": sa.jammed,
        },
        "reactor": {
            "id": reactor.id, "hp": round(reactor.hp, 1),
            "hp_max": reactor.hp_max, "active": reactor.active,
        },
        "garrison_count": defenses.garrison_count,  # type: ignore[attr-defined]
    }


def build_world_entities(world: World) -> Message:
    """Serialise enemies, torpedoes, and stations into a world.entities message."""
    enemies = [
        {
            "id": e.id,
            "type": e.type,
            "x": round(e.x, 1),
            "y": round(e.y, 1),
            "heading": round(e.heading, 2),
            "hull": round(e.hull, 2),
            "shield_front": round(e.shield_front, 2),
            "shield_rear": round(e.shield_rear, 2),
            "ai_state": e.ai_state,
        }
        for e in world.enemies
    ]
    torpedoes = [
        {
            "id": t.id,
            "owner": t.owner,
            "x": round(t.x, 1),
            "y": round(t.y, 1),
            "heading": round(t.heading, 2),
            "torpedo_type": t.torpedo_type,
        }
        for t in world.torpedoes
    ]
    stations = [
        {
            "id": s.id,
            "x": round(s.x, 1),
            "y": round(s.y, 1),
            "hull": round(s.hull, 1),
            "hull_max": s.hull_max,
            "defenses": _serialise_defenses(s.defenses) if s.defenses else None,
        }
        for s in world.stations
    ]
    asteroids = [
        {
            "id": a.id,
            "x": round(a.x, 1),
            "y": round(a.y, 1),
            "radius": a.radius,
        }
        for a in world.asteroids
    ]
    hazards = [
        {
            "id": h.id,
            "x": round(h.x, 1),
            "y": round(h.y, 1),
            "radius": h.radius,
            "hazard_type": h.hazard_type,
            "label": h.label,
        }
        for h in world.hazards
    ]
    # v0.06.5 Part 7: Include active drones + buoys for Captain tactical map.
    drones = []
    for d in glfo.get_drones():
        if d.status not in ("active", "recovering", "rtb"):
            continue
        drones.append({
            "id": d.id,
            "callsign": d.callsign,
            "drone_type": d.drone_type,
            "x": round(d.position[0], 1),
            "y": round(d.position[1], 1),
            "heading": round(d.heading, 1),
            "hull": round(d.hull, 1),
            "status": d.status,
            "survivors": d.cargo_current if d.drone_type == "rescue" else 0,
        })
    buoys = []
    for b in glfo.get_buoys():
        if b.active:
            buoys.append({
                "id": b.id,
                "x": round(b.position[0], 1),
                "y": round(b.position[1], 1),
                "sensor_range": round(b.sensor_range, 1),
            })
    return Message.build(
        "world.entities",
        {
            "enemies": enemies,
            "torpedoes": torpedoes,
            "stations": stations,
            "asteroids": asteroids,
            "hazards": hazards,
            "drones": drones,
            "buoys": buoys,
        },
    )
