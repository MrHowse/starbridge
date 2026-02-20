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
from server.models.world import World, spawn_enemy
from server.missions.engine import MissionEngine
from server.missions.loader import load_mission, spawn_from_mission, spawn_wave
from server.systems import sensors
from server.utils.math_helpers import distance

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

_mission_engine: MissionEngine | None = None
_signal_location: tuple[float, float] | None = None
_dock_timer: float = 0.0
_pending_puzzle_starts: list[dict] = []
_pending_boardings: list[dict] = []
_pending_deployments: list[dict] = []
_pending_outbreaks: list[dict] = []


def reset() -> None:
    """Reset mission state. Called automatically by init_mission."""
    global _mission_engine, _signal_location, _dock_timer
    _mission_engine = None
    _signal_location = None
    _dock_timer = 0.0
    _pending_puzzle_starts.clear()
    _pending_boardings.clear()
    _pending_deployments.clear()
    _pending_outbreaks.clear()


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


def get_mission_engine() -> MissionEngine | None:
    return _mission_engine


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init_mission(mission_id: str, world: World) -> None:
    """Load and initialise the mission, spawn all entities."""
    import server.game_loop_weapons as glw

    global _mission_engine, _signal_location, _dock_timer
    _dock_timer = 0.0

    mission = load_mission(mission_id)

    if mission_id == "sandbox":
        _spawn_sandbox_enemies(world)
    else:
        spawn_from_mission(mission, world, 0)

    _mission_engine = MissionEngine(mission)

    sig = mission.get("signal_location")
    _signal_location = (float(sig["x"]), float(sig["y"])) if sig else None


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
            from server.game_loop_medical import RESUPPLY_AMOUNT as MED_AMOUNT, RESUPPLY_MAX as MED_MAX
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
        elif action.get("action") == "start_puzzle":
            _pending_puzzle_starts.append(action)
        elif action.get("action") == "deploy_squads":
            _pending_deployments.append(action)
        elif action.get("action") == "start_boarding":
            _pending_boardings.append(action)
        elif action.get("action") == "start_outbreak":
            _pending_outbreaks.append(action)

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
# Broadcast builder helpers
# ---------------------------------------------------------------------------


def build_sensor_contacts(
    world: World,
    ship: object,
    extra_bubbles: list[tuple[float, float, float]] | None = None,
) -> Message:
    """Build the sensor.contacts message for Weapons / Science clients."""
    torpedoes = [
        {
            "id": t.id,
            "owner": t.owner,
            "x": round(t.x, 1),
            "y": round(t.y, 1),
            "heading": round(t.heading, 2),
        }
        for t in world.torpedoes
    ]
    return Message.build(
        "sensor.contacts",
        {
            "contacts": sensors.build_sensor_contacts(world, ship, extra_bubbles),  # type: ignore[arg-type]
            "torpedoes": torpedoes,
        },
    )


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
    return Message.build(
        "world.entities",
        {
            "enemies": enemies,
            "torpedoes": torpedoes,
            "stations": stations,
            "asteroids": asteroids,
            "hazards": hazards,
        },
    )
