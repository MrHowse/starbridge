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
    CaptainAddLogPayload,
    CaptainAuthorizePayload,
    CommsHailPayload,
    CommsTuneFrequencyPayload,
    CrewNotifyPayload,
    GameBriefingLaunchPayload,
    EngineeringCancelDCTPayload,
    EngineeringDispatchDCTPayload,
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
    SecurityMoveSquadPayload,
    SecurityToggleDoorPayload,
    WeaponsFireBeamsPayload,
    WeaponsFireTorpedoPayload,
    WeaponsLoadTubePayload,
    WeaponsSelectTargetPayload,
    WeaponsSetShieldsPayload,
)
from server.models.crew import CrewRoster
from server.models.interior import make_default_interior
from server.models.ship_class import load_ship_class
from server.difficulty import get_preset
from server.models.ship import Ship
from server.models.world import World
from server.systems import physics, sensors
from server.systems.ai import tick_enemies
from server.systems.combat import regenerate_shields
from server.systems import hazards as hazard_system
import server.game_logger as gl
import server.game_loop_weapons as glw
import server.game_loop_mission as glm
import server.game_loop_medical as glmed
import server.game_loop_security as gls
import server.game_loop_comms as glco
import server.game_loop_captain as glcap
import server.game_loop_damage_control as gldc
from server.puzzles import PuzzleEngine
import server.puzzles.sequence_match          # noqa: F401 — registers sequence_match type
import server.puzzles.circuit_routing         # noqa: F401 — registers circuit_routing type
import server.puzzles.frequency_matching      # noqa: F401 — registers frequency_matching type
import server.puzzles.tactical_positioning    # noqa: F401 — registers tactical_positioning type
import server.puzzles.transmission_decoding   # noqa: F401 — registers transmission_decoding type
import server.puzzles.triage                  # noqa: F401 — registers triage type
import server.puzzles.route_calculation        # noqa: F401 — registers route_calculation type
import server.puzzles.firing_solution           # noqa: F401 — registers firing_solution type

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

# Science → Medical triage assist tracking (one application per puzzle).
_applied_science_medical_assists: set[str] = set()

# Science → Helm route-calculation assist tracking (one application per puzzle).
_applied_science_helm_assists: set[str] = set()

# Science → Weapons firing-solution assist tracking (one application per puzzle).
_applied_science_weapons_assists: set[str] = set()

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


async def start(mission_id: str, difficulty: str = "officer", ship_class: str = "frigate") -> None:
    """Begin the game loop. Called when the host launches a game."""
    global _task, _tick_count, _game_start_time
    _tick_count = 0
    _game_start_time = _time.monotonic()

    # Apply ship class stats before subsystem resets (so ammo uses class defaults).
    try:
        sc = load_ship_class(ship_class)
    except FileNotFoundError:
        logger.warning("Unknown ship class %r — using frigate defaults", ship_class)
        sc = load_ship_class("frigate")

    glw.reset(initial_ammo=sc.torpedo_ammo)
    glmed.reset()
    gls.reset()
    glco.reset()
    glcap.reset()
    gldc.reset()
    _puzzle_engine.reset()
    _applied_sensor_assists.clear()
    _applied_science_medical_assists.clear()
    _applied_science_helm_assists.clear()
    _applied_science_weapons_assists.clear()
    sensors.reset()

    if _task is not None and not _task.done():
        logger.warning("Game loop already running — stopping before restart")
        await stop()

    assert _world is not None
    _world.enemies.clear()
    _world.torpedoes.clear()
    _world.stations.clear()
    _world.asteroids.clear()
    _world.hazards.clear()
    _world.ship.alert_level = "green"
    _world.ship.hull = sc.max_hull
    _world.ship.crew = CrewRoster()
    _world.ship.interior = make_default_interior()
    _world.ship.difficulty = get_preset(difficulty)
    logger.info(
        "Ship class: %s (hull=%.0f, ammo=%d), difficulty: %s",
        sc.id, sc.max_hull, sc.torpedo_ammo, difficulty,
    )

    glm.init_mission(mission_id, _world)

    _task = asyncio.create_task(_loop(), name="game_loop")
    logger.info("Game loop started (mission: %s, %d Hz)", mission_id, TICK_RATE)


async def stop() -> None:
    """Stop the game loop task."""
    global _task
    if gl.is_logging():
        gl.stop_logging("interrupted", _build_game_stats())
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
        gl.set_tick(_tick_count)
        if _tick_count % 100 == 0:
            gl.log_event("game", "tick_summary", {
                "hull": round(_world.ship.hull, 1),
                "shields": {
                    "front": round(_world.ship.shields.front, 1),
                    "rear": round(_world.ship.shields.rear, 1),
                },
                "ammo": glw.get_ammo(),
                "enemy_count": len(_world.enemies),
            })
        glm.apply_asteroid_collisions(_world)

        # 3. Engineering. 3.5 Crew factors + medical + disease. 3.6 Security. 3.7 Comms.
        damaged_systems = _apply_engineering(_world.ship)
        gldc.tick(_world.ship.interior, TICK_DT)
        _world.ship.update_crew_factors()
        glmed.tick_treatments(_world.ship, TICK_DT)
        disease_events = glmed.tick_disease(_world.ship.interior, TICK_DT)
        security_events = gls.tick_security(_world.ship.interior, _world.ship, TICK_DT)
        comms_responses = glco.tick_comms(TICK_DT)
        hazard_events = hazard_system.tick_hazards(_world, _world.ship, TICK_DT)
        # 3.7 Cross-station assists.
        # Engineering → Science (sensor boost widens frequency tolerance).
        sensor_assist_msg = _check_sensor_assist(_world.ship)
        if sensor_assist_msg:
            await _manager.broadcast_to_roles(["engineering"], sensor_assist_msg)
        # Science → Medical (pathogen analysis reveals triage patient).
        science_medical_msg = _check_science_medical_assist(_world.ship)
        if science_medical_msg:
            await _manager.broadcast_to_roles(["science"], science_medical_msg)
        # Science → Helm (sensor scan reveals hidden cells on route calculation).
        science_helm_msg = _check_science_helm_assist(_world.ship)
        if science_helm_msg:
            await _manager.broadcast_to_roles(["science"], science_helm_msg)
        # Science → Weapons (velocity data widens firing solution tolerance).
        science_weapons_msg = _check_science_weapons_assist(_world.ship)
        if science_weapons_msg:
            await _manager.broadcast_to_roles(["science"], science_weapons_msg)
        # Tube loading advancement.
        glw.tick_tube_loading(TICK_DT)
        torpedo_events = glw.tick_torpedoes(_world)
        stations = _world.stations if _world.stations else None
        beam_hit_events = tick_enemies(_world.enemies, _world.ship, TICK_DT, stations)

        # 6. Enemy beam hits. 7. Shields. 7.5 Scan. 7.6 Docking. 8. Cooldowns.
        _hull_before_combat = _world.ship.hull
        combat_damage_events = await glw.handle_enemy_beam_hits(beam_hit_events, _world, _manager)
        gldc.apply_hull_damage(_hull_before_combat - _world.ship.hull, _world.ship.interior)
        regenerate_shields(_world.ship)
        scan_completed = sensors.tick(_world, _world.ship, TICK_DT)
        await glm.tick_docking(_world, _manager, TICK_DT)
        glw.tick_cooldowns(TICK_DT)

        # 8.5 Mission tick.
        over, result = await glm.tick_mission(_world, _world.ship, _manager, TICK_DT)
        if over:
            stats = _build_game_stats()
            gl.stop_logging(result or "unknown", stats)
            await _manager.broadcast(
                Message.build("game.over", {"result": result, "stats": stats})
            )
            await stop()
            return

        # 8.55. Deploy squads (planning phase — before puzzle creation).
        for deploy_action in glm.pop_pending_deployments():
            gls.deploy_squads(_world.ship.interior, deploy_action.get("squads", []))

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
            # Build extra kwargs for puzzle types that need runtime references.
            extra_kwargs: dict = {}
            if pstart["puzzle_type"] == "tactical_positioning":
                extra_kwargs = {
                    "interior": _world.ship.interior,
                    "intruder_specs": pstart.get("intruder_specs", []),
                }
            base_time = pstart.get("time_limit", 30.0)
            time_mult = _world.ship.difficulty.puzzle_time_mult if _world else 1.0
            inst = _puzzle_engine.create_puzzle(
                puzzle_type=pstart["puzzle_type"],
                station=pstart["station"],
                label=pstart["label"],
                difficulty=pstart.get("difficulty", 1),
                time_limit=base_time * time_mult,
                **extra_kwargs,
            )
            # Assist chain: triage on Medical → notify Science (pathogen analysis).
            if (
                pstart["puzzle_type"] == "triage"
                and pstart["station"] == "medical"
                and inst is not None
            ):
                await _manager.broadcast_to_roles(
                    ["science"],
                    Message.build("puzzle.assist_available", {
                        "puzzle_id":      inst.puzzle_id,
                        "label":          inst.label,
                        "target_station": "medical",
                        "instructions": (
                            "Boost SENSORS above 120% to run pathogen analysis "
                            "and assist Medical triage"
                        ),
                    }),
                )

            # Assist chain: firing_solution on Weapons → notify Science (velocity data widens tolerance).
            if (
                pstart["puzzle_type"] == "firing_solution"
                and pstart["station"] == "weapons"
                and inst is not None
            ):
                await _manager.broadcast_to_roles(
                    ["science"],
                    Message.build("puzzle.assist_available", {
                        "puzzle_id":      inst.puzzle_id,
                        "label":          inst.label,
                        "target_station": "weapons",
                        "instructions": (
                            "Boost SENSORS above 120% to relay target velocity data "
                            "and widen the Weapons firing tolerance"
                        ),
                    }),
                )

            # Assist chain: route_calculation on Helm → notify Science (sensor scan reveals hidden cells).
            if (
                pstart["puzzle_type"] == "route_calculation"
                and pstart["station"] == "helm"
                and inst is not None
            ):
                await _manager.broadcast_to_roles(
                    ["science"],
                    Message.build("puzzle.assist_available", {
                        "puzzle_id":      inst.puzzle_id,
                        "label":          inst.label,
                        "target_station": "helm",
                        "instructions": (
                            "Boost SENSORS above 120% to scan nebula cells "
                            "and reveal hidden hazards to Helm"
                        ),
                    }),
                )

            # Assist chain: frequency_matching on Science → notify Engineering + Comms.
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
                await _manager.broadcast_to_roles(
                    ["comms"],
                    Message.build("puzzle.assist_available", {
                        "puzzle_id": inst.puzzle_id,
                        "label": inst.label,
                        "target_station": "science",
                        "instructions": (
                            "Decode the alien transmission to relay a frequency component to Science"
                        ),
                    }),
                )

        # 8.65. Comms→Science relay assist: auto-apply decoded frequency to Science puzzle.
        for station, relay_component in _puzzle_engine.pop_relay_data():
            if station == "comms":
                science_puzzle = _puzzle_engine.get_active_for_station("science")
                if science_puzzle is not None and science_puzzle.is_active():
                    _puzzle_engine.apply_assist(
                        science_puzzle.puzzle_id, "relay_frequency", relay_component
                    )
                    await _manager.broadcast_to_roles(
                        ["comms"],
                        Message.build("puzzle.assist_sent", {
                            "label": "comms_relay",
                            "message": "Decoded frequency signature relayed to Science station.",
                        }),
                    )

        # 8.7 Boarding: process start_boarding actions from mission engine.
        # 8.71 Outbreaks: process start_outbreak actions from mission engine.
        for outbreak_action in glm.pop_pending_outbreaks():
            glmed.start_outbreak(
                outbreak_action.get("deck", "medical"),
                outbreak_action.get("pathogen", "Unknown Pathogen"),
            )
        for boarding_action in glm.pop_pending_boardings():
            gls.start_boarding(
                _world.ship.interior,
                boarding_action.get("squads", []),
                boarding_action.get("intruders", []),
            )
            gl.log_event("security", "boarding_started", {
                "intruder_count": len(boarding_action.get("intruders", [])),
            })

        # 9. Hull check (safety net when no mission engine).
        if glm.get_mission_engine() is None and _world.ship.hull <= 0.0:
            stats = _build_game_stats()
            gl.stop_logging("defeat", stats)
            await _manager.broadcast(
                Message.build("game.over", {"result": "defeat", "stats": stats})
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
                gl.log_event("science", "scan_completed", {"entity_id": cid})

        # 11e. Security interior state (always broadcast so Security can show the map).
        await _manager.broadcast_to_roles(
            ["security"],
            Message.build("security.interior_state", gls.build_interior_state(_world.ship.interior, _world.ship)),
        )

        # 11f. Comms state + NPC responses.
        await _manager.broadcast_to_roles(
            ["comms"],
            Message.build("comms.state", glco.build_comms_state()),
        )
        for npc_resp in comms_responses:
            await _manager.broadcast_to_roles(
                ["comms"],
                Message.build("comms.npc_response", npc_resp),
            )

        # 11g. Medical disease state + spread events.
        await _manager.broadcast_to_roles(
            ["medical"],
            Message.build("medical.disease_state", glmed.get_disease_state()),
        )
        for dev in disease_events:
            await _manager.broadcast_to_roles(
                ["medical"],
                Message.build("medical.disease_spread", dev),
            )

        # 11h. Hazard damage events → hull_hit broadcast.
        for hev in hazard_events:
            await _manager.broadcast(
                Message.build("ship.hull_hit", {"cause": hev["hazard_type"], "damage": hev["damage"]})
            )

        # 11i. Engineering damage-control state → Engineering station.
        await _manager.broadcast_to_roles(
            ["engineering"],
            Message.build("engineering.dc_state", gldc.build_dc_state(_world.ship.interior)),
        )

        # 12–15. Damage events, torpedo hits, action events, security events.
        for s, h in damaged_systems:
            await _manager.broadcast(Message.build(
                "ship.system_damaged", {"system": s, "new_health": h, "cause": "overclock"}))
            gl.log_event("engineering", "overclock_damage", {"system": s, "new_health": round(h, 1)})
        for s, h in combat_damage_events:
            await _manager.broadcast(Message.build(
                "ship.system_damaged", {"system": s, "new_health": h, "cause": "combat"}))
            gl.log_event("combat", "system_damaged", {"system": s, "new_health": round(h, 1)})
        for evt in torpedo_events:
            await _manager.broadcast(Message.build("weapons.torpedo_hit", evt))
            gl.log_event("weapons", "torpedo_hit", {
                "target_id": evt["target_id"],
                "torpedo_type": evt["torpedo_type"],
                "damage": evt["damage"],
            })
            # Probe torpedo: broadcast scan data as a completed scan result.
            if evt.get("torpedo_type") == "probe" and "probe_scan" in evt:
                await _manager.broadcast(Message.build("science.scan_complete", {
                    "entity_id": evt["target_id"],
                    "results":   evt["probe_scan"],
                }))
        for evt in action_events:
            await _manager.broadcast(Message.build(evt[0], evt[1]))
        for evt_type, evt_data in security_events:
            await _manager.broadcast_to_roles(["security"], Message.build(evt_type, evt_data))

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
            if payload.heading != ship.target_heading:
                gl.log_event("helm", "heading_changed", {"from": round(ship.target_heading, 1), "to": payload.heading})
            ship.target_heading = payload.heading
        elif msg_type == "helm.set_throttle" and isinstance(payload, HelmSetThrottlePayload):
            if payload.throttle != ship.throttle:
                gl.log_event("helm", "throttle_changed", {"from": ship.throttle, "to": payload.throttle})
            ship.throttle = payload.throttle
        elif msg_type == "engineering.set_power" and isinstance(payload, EngineeringSetPowerPayload):
            _prev_power = ship.systems[payload.system].power
            _apply_power(ship, payload.system, payload.level)
            _new_power = ship.systems[payload.system].power
            if _new_power != _prev_power:
                gl.log_event("engineering", "power_changed", {"system": payload.system, "from": _prev_power, "to": _new_power})
        elif msg_type == "engineering.set_repair" and isinstance(payload, EngineeringSetRepairPayload):
            ship.repair_focus = payload.system
            gl.log_event("engineering", "repair_started", {"system": payload.system})
        elif msg_type == "engineering.dispatch_dct" and isinstance(payload, EngineeringDispatchDCTPayload):
            gldc.dispatch_dct(payload.room_id, ship.interior)
            gl.log_event("engineering", "dct_dispatched", {"room_id": payload.room_id})
        elif msg_type == "engineering.cancel_dct" and isinstance(payload, EngineeringCancelDCTPayload):
            gldc.cancel_dct(payload.room_id)
            gl.log_event("engineering", "dct_cancelled", {"room_id": payload.room_id})
        elif msg_type == "weapons.select_target" and isinstance(payload, WeaponsSelectTargetPayload):
            glw.set_target(payload.entity_id)
            gl.log_event("weapons", "target_selected", {"target_id": payload.entity_id})
        elif msg_type == "weapons.fire_beams" and isinstance(payload, WeaponsFireBeamsPayload):
            if world is not None:
                evt = glw.fire_player_beams(ship, world)
                if evt:
                    events.append(evt)
                    gl.log_event("weapons", "beam_fired", evt[1])
        elif msg_type == "weapons.fire_torpedo" and isinstance(payload, WeaponsFireTorpedoPayload):
            if world is not None:
                for evt in glw.fire_torpedo(ship, world, payload.tube):
                    events.append(evt)
                    if evt[0] == "weapons.torpedo_fired":
                        gl.log_event("weapons", "torpedo_fired", evt[1])
        elif msg_type == "weapons.load_tube" and isinstance(payload, WeaponsLoadTubePayload):
            evt = glw.load_tube(payload.tube, payload.torpedo_type)
            if evt:
                events.append(evt)
        elif msg_type == "weapons.set_shields" and isinstance(payload, WeaponsSetShieldsPayload):
            ship.shields.front = payload.front
            ship.shields.rear = payload.rear
            gl.log_event("weapons", "shield_changed", {"front": payload.front, "rear": payload.rear})
        elif msg_type == "science.start_scan" and isinstance(payload, ScienceStartScanPayload):
            if glm.is_signal_scan(payload.entity_id):
                events.append(("signal.scan_result", {"ship_x": ship.x, "ship_y": ship.y}))
            else:
                sensors.start_scan(payload.entity_id)
                gl.log_event("science", "scan_started", {"entity_id": payload.entity_id})
        elif msg_type == "science.cancel_scan" and isinstance(payload, ScienceCancelScanPayload):
            sensors.cancel_scan()
        elif msg_type == "medical.treat_crew" and isinstance(payload, MedicalTreatCrewPayload):
            glmed.start_treatment(payload.deck, payload.injury_type, ship)
            gl.log_event("medical", "treatment_started", {"deck": payload.deck, "injury_type": payload.injury_type})
        elif msg_type == "medical.cancel_treatment" and isinstance(payload, MedicalCancelTreatmentPayload):
            glmed.cancel_treatment(payload.deck)
        elif msg_type == "security.move_squad" and isinstance(payload, SecurityMoveSquadPayload):
            gls.move_squad(ship.interior, payload.squad_id, payload.room_id)
            gl.log_event("security", "squad_moved", {"squad_id": payload.squad_id, "room_id": payload.room_id})
        elif msg_type == "security.toggle_door" and isinstance(payload, SecurityToggleDoorPayload):
            gls.toggle_door(ship.interior, payload.room_id, payload.squad_id)
            gl.log_event("security", "door_toggled", {"room_id": payload.room_id, "squad_id": payload.squad_id})
        elif msg_type == "captain.authorize" and isinstance(payload, CaptainAuthorizePayload):
            if world is not None:
                for evt in glw.resolve_nuclear_auth(payload.request_id, payload.approved, ship, world):
                    events.append(evt)
        elif msg_type == "captain.add_log" and isinstance(payload, CaptainAddLogPayload):
            entry = glcap.add_log_entry(payload.text)
            events.append(("captain.log_entry", {"text": entry["text"], "timestamp": entry["timestamp"]}))
        elif msg_type == "comms.tune_frequency" and isinstance(payload, CommsTuneFrequencyPayload):
            glco.tune(payload.frequency)
        elif msg_type == "comms.hail" and isinstance(payload, CommsHailPayload):
            glco.hail(payload.contact_id, payload.message_type)
        elif msg_type == "puzzle.submit" and isinstance(payload, PuzzleSubmitPayload):
            _puzzle_engine.submit(payload.puzzle_id, payload.submission)
        elif msg_type == "puzzle.request_assist" and isinstance(payload, PuzzleAssistPayload):
            _puzzle_engine.apply_assist(payload.puzzle_id, payload.assist_type, payload.data)
        elif msg_type == "puzzle.cancel" and isinstance(payload, PuzzleCancelPayload):
            _puzzle_engine.cancel(payload.puzzle_id)
        elif msg_type == "crew.notify" and isinstance(payload, CrewNotifyPayload):
            msg_text = payload.message.strip()[:120]
            if msg_text:
                events.append(("crew.notification", {
                    "message":   msg_text,
                    "from_role": payload.from_role.strip()[:20] or "crew",
                }))
        elif msg_type == "game.briefing_launch" and isinstance(payload, GameBriefingLaunchPayload):
            events.append(("game.all_ready", {}))
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
            "tube_types": glw.get_tube_types(),
            "tube_loading": [round(t, 2) for t in glw.get_tube_loading()],
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


def _check_science_medical_assist(ship: Ship) -> Message | None:
    """Apply Science → Medical pathogen-analysis assist exactly once per puzzle.

    Conditions:
      - Medical has an active triage puzzle.
      - ship.systems["sensors"].efficiency >= SENSOR_ASSIST_THRESHOLD (120 %).
      - The assist has not already been applied for this puzzle.

    Returns a ``puzzle.assist_sent`` Message to broadcast to Science,
    or None if the conditions are not met.
    """
    puzzle = _puzzle_engine.get_active_for_station("medical")
    if puzzle is None or not puzzle.is_active():
        return None
    if puzzle.puzzle_id in _applied_science_medical_assists:
        return None
    # Duck-type check: triage puzzles have _patients attribute.
    if not hasattr(puzzle, "_patients"):
        return None
    if ship.systems["sensors"].efficiency < SENSOR_ASSIST_THRESHOLD:
        return None

    _puzzle_engine.apply_assist(puzzle.puzzle_id, "reveal_pathogen", {})
    _applied_science_medical_assists.add(puzzle.puzzle_id)
    return Message.build("puzzle.assist_sent", {
        "puzzle_id": puzzle.puzzle_id,
        "label":     puzzle.label,
        "message":   "Pathogen analysis relayed to Medical station.",
    })


def _check_science_helm_assist(ship: Ship) -> Message | None:
    """Apply Science → Helm route-calculation reveal-hazard assist exactly once per puzzle.

    Conditions:
      - Helm has an active route_calculation puzzle.
      - ship.systems["sensors"].efficiency >= SENSOR_ASSIST_THRESHOLD (120 %).
      - The assist has not already been applied for this puzzle.

    Returns a ``puzzle.assist_sent`` Message to broadcast to Science,
    or None if the conditions are not met.
    """
    puzzle = _puzzle_engine.get_active_for_station("helm")
    if puzzle is None or not puzzle.is_active():
        return None
    if puzzle.puzzle_id in _applied_science_helm_assists:
        return None
    # Duck-type check: route_calculation puzzles have _hidden_cells attribute.
    if not hasattr(puzzle, "_hidden_cells"):
        return None
    if ship.systems["sensors"].efficiency < SENSOR_ASSIST_THRESHOLD:
        return None

    _puzzle_engine.apply_assist(puzzle.puzzle_id, "reveal_hazard", {})
    _applied_science_helm_assists.add(puzzle.puzzle_id)
    return Message.build("puzzle.assist_sent", {
        "puzzle_id": puzzle.puzzle_id,
        "label":     puzzle.label,
        "message":   "Sensor scan relayed to Helm — hidden cell revealed.",
    })


def _check_science_weapons_assist(ship: Ship) -> Message | None:
    """Apply Science → Weapons velocity-data assist exactly once per puzzle.

    Conditions:
      - Weapons has an active firing_solution puzzle.
      - ship.systems["sensors"].efficiency >= SENSOR_ASSIST_THRESHOLD (120 %).
      - The assist has not already been applied for this puzzle.

    Returns a ``puzzle.assist_sent`` Message to broadcast to Science,
    or None if the conditions are not met.
    """
    puzzle = _puzzle_engine.get_active_for_station("weapons")
    if puzzle is None or not puzzle.is_active():
        return None
    if puzzle.puzzle_id in _applied_science_weapons_assists:
        return None
    # Duck-type check: firing_solution puzzles have _assist_applied attribute.
    if not hasattr(puzzle, "_assist_applied"):
        return None
    if ship.systems["sensors"].efficiency < SENSOR_ASSIST_THRESHOLD:
        return None

    result = _puzzle_engine.apply_assist(puzzle.puzzle_id, "velocity_data", {})
    _applied_science_weapons_assists.add(puzzle.puzzle_id)
    return Message.build("puzzle.assist_sent", {
        "puzzle_id": puzzle.puzzle_id,
        "label":     puzzle.label,
        "message":   "Target velocity data relayed to Weapons station.",
    })


def _build_game_stats() -> dict:
    """Build stats payload for game.over — duration, remaining hull, captain's log."""
    duration = round(_time.monotonic() - _game_start_time, 1)
    hull = round(_world.ship.hull if _world is not None else 0.0, 1)
    return {
        "duration_s": duration,
        "hull_remaining": hull,
        "captain_log": glcap.get_log(),
    }
