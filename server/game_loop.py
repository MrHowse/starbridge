"""
Game Loop — Fixed Timestep Simulation.

Runs as an asyncio background task at TICK_RATE Hz.
Tick sequence: drain inputs → physics → engineering → torpedoes → AI
→ combat → shields → scan → docking → cooldowns → mission → broadcast.

init(world, manager, queue) — inject dependencies.
start(mission_id) — begin the game loop.
stop() — halt the loop.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time as _time
from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import BaseModel

from server.models.messages import (
    EngineeringSetPowerPayload,
    EngineeringSetRepairPayload,
    HelmSetHeadingPayload,
    HelmSetThrottlePayload,
    MedicalCancelTreatmentPayload,
    MedicalTreatCrewPayload,
    Message,
    PuzzleAssistPayload,
    PuzzleCancelPayload,
    PuzzleSubmitPayload,
    ScienceCancelScanPayload,
    ScienceStartScanPayload,
    WeaponsFireBeamsPayload,
    WeaponsFireTorpedoPayload,
    WeaponsSelectTargetPayload,
    WeaponsSetShieldsPayload,
)
from server.models.crew import CrewRoster
from server.models.ship import Ship
from server.models.world import World
from server.systems import physics, sensors
from server.systems.ai import tick_enemies
from server.systems.combat import regenerate_shields
import server.game_loop_weapons as glw
import server.game_loop_mission as glm
import server.game_loop_medical as glmed
from server.puzzles import PuzzleEngine
import server.puzzles.sequence_match    # noqa: F401 — registers sequence_match type
import server.puzzles.circuit_routing   # noqa: F401 — registers circuit_routing type
import server.puzzles.frequency_matching  # noqa: F401 — registers frequency_matching type

logger = logging.getLogger("starbridge.game_loop")

_puzzle_engine: PuzzleEngine = PuzzleEngine()

TICK_RATE: int = 10
TICK_DT: float = 1.0 / TICK_RATE

# Engineering constants — tunable for gameplay feel
POWER_BUDGET: float = 600.0
OVERCLOCK_THRESHOLD: float = 100.0
OVERCLOCK_DAMAGE_CHANCE: float = 0.10
OVERCLOCK_DAMAGE_HP: float = 3.0
REPAIR_HP_PER_TICK: float = 1.0


class _ManagerProtocol(Protocol):
    async def broadcast(self, message: Message) -> None: ...
    async def broadcast_to_roles(self, roles: list[str], message: Message) -> None: ...


# Module-level state (set by init)
_world: World | None = None
_manager: _ManagerProtocol | None = None
_queue: asyncio.Queue[tuple[str, BaseModel]] | None = None
_task: asyncio.Task[None] | None = None
_tick_count: int = 0
_game_start_time: float = 0.0
_on_game_end: Callable[[], Awaitable[None]] | None = None

# Sensor-assist tracking: puzzle IDs that have already received the
# Engineering sensor-boost assist (one application per puzzle lifetime).
_applied_sensor_assists: set[str] = set()

# Sensor efficiency threshold that triggers the cross-station assist.
SENSOR_ASSIST_THRESHOLD: float = 1.2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init(
    world: World,
    manager: _ManagerProtocol,
    queue: asyncio.Queue[tuple[str, BaseModel]],
) -> None:
    """Inject dependencies. Call once from main.py before starting the game."""
    global _world, _manager, _queue
    _world = world
    _manager = manager
    _queue = queue


def register_game_end_callback(cb: Callable[[], Awaitable[None]]) -> None:
    """Register a coroutine called when the game ends (victory, defeat, or stop)."""
    global _on_game_end
    _on_game_end = cb


async def start(mission_id: str) -> None:
    """Begin the game loop. Called when the host launches a game."""
    global _task, _tick_count, _game_start_time
    _tick_count = 0
    _game_start_time = _time.monotonic()
    glw.reset()
    glmed.reset()
    _puzzle_engine.reset()
    _applied_sensor_assists.clear()
    sensors.reset()

    if _task is not None and not _task.done():
        logger.warning("Game loop already running — stopping before restart")
        await stop()

    assert _world is not None
    _world.enemies.clear()
    _world.torpedoes.clear()
    _world.stations.clear()
    _world.asteroids.clear()
    _world.ship.alert_level = "green"
    _world.ship.crew = CrewRoster()

    glm.init_mission(mission_id, _world)

    _task = asyncio.create_task(_loop(), name="game_loop")
    logger.info("Game loop started (mission: %s, %d Hz)", mission_id, TICK_RATE)


async def stop() -> None:
    """Stop the game loop task."""
    global _task
    if _task is not None and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
    logger.info("Game loop stopped")
    if _on_game_end is not None:
        await _on_game_end()


# ---------------------------------------------------------------------------
# Loop internals
# ---------------------------------------------------------------------------


async def _loop() -> None:
    global _tick_count
    assert _world is not None and _manager is not None and _queue is not None

    while True:
        tick_start = asyncio.get_event_loop().time()

        # 1. Drain inputs. 1.5 Signal scans.
        action_events = _drain_queue(_world.ship, _world)
        await glm.handle_signal_scans(action_events, _manager)

        # 2. Physics. 2.5 Asteroid collisions.
        physics.tick(_world.ship, TICK_DT, _world.width, _world.height)
        _tick_count += 1
        glm.apply_asteroid_collisions(_world)

        # 3. Engineering. 3.5 Crew factors + medical. 4. Torpedoes. 5. Enemy AI.
        damaged_systems = _apply_engineering(_world.ship)
        _world.ship.update_crew_factors()
        glmed.tick_treatments(_world.ship, TICK_DT)
        # 3.6 Cross-station sensor assist (Engineering → Science frequency puzzle).
        sensor_assist_msg = _check_sensor_assist(_world.ship)
        if sensor_assist_msg:
            await _manager.broadcast_to_roles(["engineering"], sensor_assist_msg)
        torpedo_events = glw.tick_torpedoes(_world)
        stations = _world.stations if _world.stations else None
        beam_hit_events = tick_enemies(_world.enemies, _world.ship, TICK_DT, stations)

        # 6. Enemy beam hits. 7. Shields. 7.5 Scan. 7.6 Docking. 8. Cooldowns.
        combat_damage_events = await glw.handle_enemy_beam_hits(beam_hit_events, _world, _manager)
        regenerate_shields(_world.ship)
        scan_completed = sensors.tick(_world, _world.ship, TICK_DT)
        await glm.tick_docking(_world, _manager, TICK_DT)
        glw.tick_cooldowns(TICK_DT)

        # 8.5 Mission tick.
        over, result = await glm.tick_mission(_world, _world.ship, _manager, TICK_DT)
        if over:
            await _manager.broadcast(
                Message.build("game.over", {"result": result, "stats": _build_game_stats()})
            )
            await stop()
            return

        # 8.6. Puzzle engine: tick, broadcast, notify mission engine, start new puzzles.
        _puzzle_engine.tick(TICK_DT)
        for roles, msg in _puzzle_engine.pop_pending_broadcasts():
            await _manager.broadcast_to_roles(roles, msg)
        if me := glm.get_mission_engine():
            for _pid, label, success in _puzzle_engine.pop_resolved():
                me.notify_puzzle_result(label, success)
        else:
            _puzzle_engine.pop_resolved()  # discard if no mission engine
        for pstart in glm.pop_pending_puzzle_starts():
            inst = _puzzle_engine.create_puzzle(
                puzzle_type=pstart["puzzle_type"],
                station=pstart["station"],
                label=pstart["label"],
                difficulty=pstart.get("difficulty", 1),
                time_limit=pstart.get("time_limit", 30.0),
            )
            # Assist chain: frequency_matching on Science → notify Engineering.
            if (
                pstart["puzzle_type"] == "frequency_matching"
                and pstart["station"] == "science"
                and inst is not None
            ):
                await _manager.broadcast_to_roles(
                    ["engineering"],
                    Message.build("puzzle.assist_available", {
                        "puzzle_id": inst.puzzle_id,
                        "label": inst.label,
                        "target_station": "science",
                        "instructions": (
                            "Boost SENSORS above 120% to widen Science frequency tolerance"
                        ),
                    }),
                )

        # 9. Hull check (safety net when no mission engine).
        if glm.get_mission_engine() is None and _world.ship.hull <= 0.0:
            await _manager.broadcast(
                Message.build("game.over", {"result": "defeat", "stats": _build_game_stats()})
            )
            await stop()
            return

        # 10. Ship state. 11a. World entities. 11b. Sensor contacts.
        await _manager.broadcast(_build_ship_state(_world.ship, _tick_count))
        await _manager.broadcast_to_roles(
            ["helm", "engineering", "captain", "viewscreen"],
            glm.build_world_entities(_world),
        )
        await _manager.broadcast_to_roles(
            ["weapons", "science"],
            glm.build_sensor_contacts(_world, _world.ship),
        )

        # 11c. Scan progress.
        scan_progress = sensors.get_scan_progress()
        if scan_progress is not None:
            entity_id, progress = scan_progress
            await _manager.broadcast(
                Message.build(
                    "science.scan_progress",
                    {"entity_id": entity_id, "progress": round(progress, 1)},
                )
            )

        # 11d. Scan complete.
        for cid in scan_completed:
            ce = next((e for e in _world.enemies if e.id == cid), None)
            if ce is not None:
                await _manager.broadcast(Message.build("science.scan_complete", {
                    "entity_id": cid,
                    "results": sensors.build_scan_result(ce),
                }))

        # 12–15. Damage events, torpedo hits, action events.
        for s, h in damaged_systems:
            await _manager.broadcast(Message.build(
                "ship.system_damaged", {"system": s, "new_health": h, "cause": "overclock"}))
        for s, h in combat_damage_events:
            await _manager.broadcast(Message.build(
                "ship.system_damaged", {"system": s, "new_health": h, "cause": "combat"}))
        for evt in torpedo_events:
            await _manager.broadcast(Message.build("weapons.torpedo_hit", evt))
        for evt in action_events:
            await _manager.broadcast(Message.build(evt[0], evt[1]))

        # 16. Sleep for remainder of tick budget.
        elapsed = asyncio.get_event_loop().time() - tick_start
        await asyncio.sleep(max(0.0, TICK_DT - elapsed))


def _drain_queue(ship: Ship, world: World | None = None) -> list[tuple[str, dict]]:
    """Apply all pending input messages; return list of (event_type, payload) to broadcast."""
    assert _queue is not None
    events: list[tuple[str, dict]] = []

    while True:
        try:
            msg_type, payload = _queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        if msg_type == "helm.set_heading" and isinstance(payload, HelmSetHeadingPayload):
            ship.target_heading = payload.heading
        elif msg_type == "helm.set_throttle" and isinstance(payload, HelmSetThrottlePayload):
            ship.throttle = payload.throttle
        elif msg_type == "engineering.set_power" and isinstance(payload, EngineeringSetPowerPayload):
            _apply_power(ship, payload.system, payload.level)
        elif msg_type == "engineering.set_repair" and isinstance(payload, EngineeringSetRepairPayload):
            ship.repair_focus = payload.system
        elif msg_type == "weapons.select_target" and isinstance(payload, WeaponsSelectTargetPayload):
            glw.set_target(payload.entity_id)
        elif msg_type == "weapons.fire_beams" and isinstance(payload, WeaponsFireBeamsPayload):
            if world is not None:
                evt = glw.fire_player_beams(ship, world)
                if evt:
                    events.append(evt)
        elif msg_type == "weapons.fire_torpedo" and isinstance(payload, WeaponsFireTorpedoPayload):
            if world is not None:
                evt = glw.fire_torpedo(ship, world, payload.tube)
                if evt:
                    events.append(evt)
        elif msg_type == "weapons.set_shields" and isinstance(payload, WeaponsSetShieldsPayload):
            ship.shields.front = payload.front
            ship.shields.rear = payload.rear
        elif msg_type == "science.start_scan" and isinstance(payload, ScienceStartScanPayload):
            if glm.is_signal_scan(payload.entity_id):
                events.append(("signal.scan_result", {"ship_x": ship.x, "ship_y": ship.y}))
            else:
                sensors.start_scan(payload.entity_id)
        elif msg_type == "science.cancel_scan" and isinstance(payload, ScienceCancelScanPayload):
            sensors.cancel_scan()
        elif msg_type == "medical.treat_crew" and isinstance(payload, MedicalTreatCrewPayload):
            glmed.start_treatment(payload.deck, payload.injury_type, ship)
        elif msg_type == "medical.cancel_treatment" and isinstance(payload, MedicalCancelTreatmentPayload):
            glmed.cancel_treatment(payload.deck)
        elif msg_type == "puzzle.submit" and isinstance(payload, PuzzleSubmitPayload):
            _puzzle_engine.submit(payload.puzzle_id, payload.submission)
        elif msg_type == "puzzle.request_assist" and isinstance(payload, PuzzleAssistPayload):
            _puzzle_engine.apply_assist(payload.puzzle_id, payload.assist_type, payload.data)
        elif msg_type == "puzzle.cancel" and isinstance(payload, PuzzleCancelPayload):
            _puzzle_engine.cancel(payload.puzzle_id)
        else:
            logger.warning("Unrecognised queued input type: %s", msg_type)

    return events


def _apply_power(ship: Ship, system_name: str, requested: float) -> None:
    """Set a system's power level, clamped to the remaining budget."""
    sys_obj = ship.systems[system_name]
    other_total = sum(s.power for name, s in ship.systems.items() if name != system_name)
    available = POWER_BUDGET - other_total
    sys_obj.power = max(0.0, min(requested, available))


def _apply_engineering(ship: Ship) -> list[tuple[str, float]]:
    """Apply repair healing and overclock damage for this tick."""
    damaged: list[tuple[str, float]] = []

    if ship.repair_focus is not None:
        sys_obj = ship.systems.get(ship.repair_focus)
        if sys_obj is not None and sys_obj.health < 100.0:
            sys_obj.health = min(100.0, sys_obj.health + REPAIR_HP_PER_TICK)

    for name, sys_obj in ship.systems.items():
        if sys_obj.power > OVERCLOCK_THRESHOLD and sys_obj.health > 0.0:
            if random.random() < OVERCLOCK_DAMAGE_CHANCE:
                sys_obj.health = max(0.0, sys_obj.health - OVERCLOCK_DAMAGE_HP)
                damaged.append((name, sys_obj.health))

    return damaged


def _build_ship_state(ship: Ship, tick: int) -> Message:
    """Serialise the ship into a ship.state envelope ready to broadcast."""
    return Message.build(
        "ship.state",
        {
            "position": {"x": round(ship.x, 1), "y": round(ship.y, 1)},
            "heading": round(ship.heading, 2),
            "velocity": round(ship.velocity, 2),
            "throttle": ship.throttle,
            "hull": ship.hull,
            "shields": {
                "front": round(ship.shields.front, 2),
                "rear": round(ship.shields.rear, 2),
            },
            "systems": {
                name: {
                    "power": s.power,
                    "health": s.health,
                    "efficiency": round(s.efficiency, 3),
                }
                for name, s in ship.systems.items()
            },
            "repair_focus": ship.repair_focus,
            "alert_level": ship.alert_level,
            "target_id": glw.get_target(),
            "torpedo_ammo": glw.get_ammo(),
            "tube_cooldowns": [round(c, 2) for c in glw.get_cooldowns()],
            "crew": {
                name: {
                    "total": d.total,
                    "active": d.active,
                    "injured": d.injured,
                    "critical": d.critical,
                    "dead": d.dead,
                    "crew_factor": round(d.crew_factor, 3),
                }
                for name, d in ship.crew.decks.items()
            },
            "medical_supplies": ship.medical_supplies,
            "active_treatments": glmed.get_active_treatments(),
        },
        tick=tick,
    )


def _check_sensor_assist(ship: Ship) -> Message | None:
    """Apply Engineering → Science sensor-boost assist exactly once per puzzle.

    Conditions:
      - Science has an active frequency_matching puzzle.
      - ship.systems["sensors"].efficiency >= SENSOR_ASSIST_THRESHOLD (1.2, i.e. 120 %).
      - The assist has not already been applied for this puzzle.

    Returns a ``puzzle.assist_sent`` Message to broadcast to Engineering,
    or None if the conditions are not met.
    """
    puzzle = _puzzle_engine.get_active_for_station("science")
    if puzzle is None or not puzzle.is_active():
        return None
    if puzzle.puzzle_id in _applied_sensor_assists:
        return None
    # Duck-type check: frequency_matching puzzles have _tolerance attribute.
    if not hasattr(puzzle, "_tolerance"):
        return None
    if ship.systems["sensors"].efficiency < SENSOR_ASSIST_THRESHOLD:
        return None

    _puzzle_engine.apply_assist(puzzle.puzzle_id, "widen_tolerance", {})
    _applied_sensor_assists.add(puzzle.puzzle_id)
    return Message.build("puzzle.assist_sent", {
        "puzzle_id": puzzle.puzzle_id,
        "label": puzzle.label,
        "message": "Sensor calibration data relayed to Science.",
    })


def _build_game_stats() -> dict:
    """Build stats payload for game.over — duration and remaining hull."""
    duration = round(_time.monotonic() - _game_start_time, 1)
    hull = round(_world.ship.hull if _world is not None else 0.0, 1)
    return {"duration_s": duration, "hull_remaining": hull}
