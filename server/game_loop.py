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
import json
import logging
import random
import time as _time
from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import BaseModel

from server.models.messages import (
    CaptainAcceptMissionPayload,
    CaptainAddLogPayload,
    CaptainAuthorizePayload,
    CaptainDeclineMissionPayload,
    CaptainUndockPayload,
    CommsAssessDistressPayload,
    CommsDecodeSignalPayload,
    CommsDismissSignalPayload,
    CommsHailPayload,
    CommsProbePayload,
    CommsRespondPayload,
    CommsRouteIntelPayload,
    CommsSetChannelPayload,
    CommsTuneFrequencyPayload,
    CreatureCommProgressPayload,
    CreatureEWDisruptPayload,
    CreatureLeeechRemovePayload,
    CreatureSedatePayload,
    DockingCancelServicePayload,
    DockingRequestClearancePayload,
    DockingStartServicePayload,
    CrewNotifyPayload,
    EWBeginIntrusionPayload,
    EWSetJamTargetPayload,
    EWToggleCountermeasuresPayload,
    TacticalSetEngagementPriorityPayload,
    TacticalSetInterceptTargetPayload,
    TacticalAddAnnotationPayload,
    TacticalRemoveAnnotationPayload,
    TacticalCreateStrikePlanPayload,
    TacticalExecuteStrikePlanPayload,
    FlightOpsAbortLandingPayload,
    FlightOpsCancelLaunchPayload,
    FlightOpsClearToLandPayload,
    FlightOpsPrioritiseRecoveryPayload,
    FlightOpsDeployBuoyPayload,
    FlightOpsDeployDecoyPayload,
    FlightOpsDesignateTargetPayload,
    FlightOpsEscortAssignPayload,
    FlightOpsLaunchDronePayload,
    FlightOpsRecallDronePayload,
    FlightOpsRushTurnaroundPayload,
    FlightOpsSetBehaviourPayload,
    FlightOpsSetEngagementRulesPayload,
    FlightOpsSetLoiterPointPayload,
    FlightOpsSetWaypointPayload,
    FlightOpsSetWaypointsPayload,
    EngineeringCancelDCTPayload,
    EngineeringCancelRepairOrderPayload,
    EngineeringDispatchDCTPayload,
    EngineeringDispatchTeamPayload,
    EngineeringRecallTeamPayload,
    EngineeringRequestEscortPayload,
    EngineeringSetBatteryModePayload,
    EngineeringSetPowerPayload,
    EngineeringSetRepairPayload,
    EngineeringStartReroutePayload,
    HelmSetHeadingPayload,
    HelmSetThrottlePayload,
    MedicalAdmitPayload,
    MedicalCancelTreatmentPayload,
    MedicalDischargePayload,
    MedicalQuarantinePayload,
    MedicalStabilisePayload,
    MedicalTreatCrewPayload,
    MedicalTreatPayload,
    Message,
    PuzzleAssistPayload,
    PuzzleCancelPayload,
    PuzzleSubmitPayload,
    ScienceCancelScanPayload,
    ScienceStartScanPayload,
    ScienceStartSectorScanPayload,
    ScienceCancelSectorScanPayload,
    ScienceScanInterruptResponsePayload,
    SecurityMoveSquadPayload,
    SecurityToggleDoorPayload,
    SecuritySendTeamPayload,
    SecuritySetPatrolPayload,
    SecurityStationTeamPayload,
    SecurityDisengageTeamPayload,
    SecurityAssignEscortPayload,
    SecurityLockDoorPayload,
    SecurityUnlockDoorPayload,
    SecurityLockdownDeckPayload,
    SecurityLiftLockdownPayload,
    SecuritySealBulkheadPayload,
    SecurityUnsealBulkheadPayload,
    SecuritySetDeckAlertPayload,
    SecurityArmCrewPayload,
    SecurityDisarmCrewPayload,
    SecurityQuarantineRoomPayload,
    SecurityLiftQuarantinePayload,
    WeaponsFireBeamsPayload,
    WeaponsFireTorpedoPayload,
    WeaponsLoadTubePayload,
    WeaponsSelectTargetPayload,
    WeaponsSetShieldFocusPayload,
    MapPlotRoutePayload,
    MapClearRoutePayload,
    JanitorPerformTaskPayload,
    JanitorDismissStickyPayload,
)
from server.models.crew import CrewRoster
from server.models.crew_roster import IndividualCrewRoster
from server.models.injuries import generate_injuries
from server.models.interior import make_default_interior
from server.models.ship_class import load_ship_class
from server.difficulty import get_preset
from server.models.ship import Ship, calculate_shield_distribution
from server.models.world import (
    World, spawn_enemy, spawn_creature, spawn_station_from_feature, STATION_FEATURE_TYPES,
)
from server.systems import physics, sensors
from server.systems.ai import tick_enemies
from server.systems.combat import apply_hit_to_enemy, regenerate_shields
from server.systems import hazards as hazard_system
from server.systems.station_ai import tick_station_ai
import server.game_logger as gl
import server.game_debrief as gdb
import server.game_loop_weapons as glw
import server.game_loop_mission as glm
import server.game_loop_medical_v2 as glmed
import server.game_loop_security as gls
import server.game_loop_comms as glco
import server.game_loop_captain as glcap
import server.game_loop_damage_control as gldc
import server.game_loop_flight_ops as glfo
import server.game_loop_ew as glew
import server.game_loop_tactical as gltac
import server.game_loop_training as gltr
import server.game_loop_sandbox as glsb
import server.game_loop_navigation as gln
import server.game_loop_science_scan as glss
import server.game_loop_docking as gldo
import server.game_loop_creatures as glc
import server.game_loop_engineering as gle
import server.game_loop_dynamic_missions as gldm
import server.game_loop_janitor as glj
from server.puzzles import PuzzleEngine
import server.puzzles.sequence_match          # noqa: F401 — registers sequence_match type
import server.puzzles.circuit_routing         # noqa: F401 — registers circuit_routing type
import server.puzzles.frequency_matching      # noqa: F401 — registers frequency_matching type
import server.puzzles.tactical_positioning    # noqa: F401 — registers tactical_positioning type
import server.puzzles.transmission_decoding   # noqa: F401 — registers transmission_decoding type
import server.puzzles.triage                  # noqa: F401 — registers triage type
import server.puzzles.route_calculation        # noqa: F401 — registers route_calculation type
import server.puzzles.firing_solution           # noqa: F401 — registers firing_solution type
import server.puzzles.network_intrusion        # noqa: F401 — registers network_intrusion type

logger = logging.getLogger("starbridge.game_loop")

_puzzle_engine: PuzzleEngine = PuzzleEngine()

TICK_RATE: int = 10
TICK_DT: float = 1.0 / TICK_RATE

# Engineering constants — tunable for gameplay feel
POWER_BUDGET: float = 900.0
OVERCLOCK_THRESHOLD: float = 100.0
OVERCLOCK_DAMAGE_CHANCE: float = 0.10
OVERCLOCK_DAMAGE_HP: float = 3.0
REPAIR_HP_PER_TICK: float = 1.0


class _ManagerProtocol(Protocol):
    async def broadcast(self, message: Message) -> None: ...
    async def broadcast_to_roles(self, roles: list[str], message: Message) -> None: ...
    def get_by_role(self, role: str) -> list: ...


# Module-level state (set by init)
_world: World | None = None
_manager: _ManagerProtocol | None = None
_queue: asyncio.Queue[tuple[str, BaseModel]] | None = None
_task: asyncio.Task[None] | None = None
_tick_count: int = 0
_game_start_time: float = 0.0
_on_game_end: Callable[[], Awaitable[None]] | None = None

# Save/resume metadata — set by start() and resume().
_mission_id: str = ""
_difficulty_preset: str = "officer"
_ship_class_id: str = "frigate"

# Training: track the last objective index for which a hint was broadcast.
_training_last_hint_idx: int = -1

# Sensor-assist tracking: puzzle IDs that have already received the
# Engineering sensor-boost assist (one application per puzzle lifetime).
_applied_sensor_assists: set[str] = set()

# Evasive manoeuvre detection: track heading change rate for Helm ↔ Flight Ops.
_prev_heading: float = 0.0
_EVASIVE_TURN_RATE: float = 30.0  # degrees/second to be considered evasive

# Science → Medical triage assist tracking (one application per puzzle).
_applied_science_medical_assists: set[str] = set()

# Science → Helm route-calculation assist tracking (one application per puzzle).
_applied_science_helm_assists: set[str] = set()

# Science → Weapons firing-solution assist tracking (one application per puzzle).
_applied_science_weapons_assists: set[str] = set()

# Sensor efficiency threshold that triggers the cross-station assist.
SENSOR_ASSIST_THRESHOLD: float = 1.2

# Session player mapping: role → player_name.  Set by set_session_players()
# (called from main.py just before game_loop.start()), used to update profiles
# at game end.
_session_players: dict[str, str] = {}

# Admin pause flag — when True the tick body is skipped, only sleep runs.
_paused: bool = False

# Crew factor tracking — previous crew factor per system for threshold notifications.
_prev_crew_factors: dict[str, float] = {}

# Performance: last serialised DC state — avoid redundant broadcasts when idle.
_last_dc_state_json: str = ""

# Sector tracking: ID of the sector the ship was in at the previous tick.
# Used to fire on_sector_leave() when the ship crosses a sector boundary.
_current_sector_id: str | None = None

# Navigation: dirty flag triggers map.sector_grid broadcast on next tick.
_sector_grid_dirty: bool = False

# Performance: last serialised sector-grid payload — avoid redundant broadcasts.
_last_sector_grid_json: str = ""


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


# ---------------------------------------------------------------------------
# Save/resume accessors (used by captain.py → save_system)
# ---------------------------------------------------------------------------


def get_world() -> World | None:
    """Return the active World, or None if game is not running."""
    return _world


def get_tick_count() -> int:
    """Return the current tick count."""
    return _tick_count


def get_mission_id() -> str:
    """Return the mission ID of the current or last game."""
    return _mission_id


def get_difficulty_preset() -> str:
    """Return the difficulty preset name of the current or last game."""
    return _difficulty_preset


def get_ship_class_id() -> str:
    """Return the ship class ID of the current or last game."""
    return _ship_class_id


def set_session_players(players: dict[str, str]) -> None:
    """Register a role → player_name mapping used for profile updates at game end.

    Called from main.py immediately before game_loop.start() so that when the
    game ends the loop knows which player names to credit for each role.
    """
    global _session_players
    _session_players = dict(players)


def pause() -> None:
    """Pause the game loop.  Ticks are skipped until resume() is called."""
    global _paused
    _paused = True
    logger.info("Game loop paused by admin")


def resume() -> None:
    """Resume the game loop after a pause() call."""
    global _paused
    _paused = False
    logger.info("Game loop resumed by admin")


def is_paused() -> bool:
    """Return True if the game loop is currently paused."""
    return _paused


def is_running() -> bool:
    """Return True if the game loop task is active."""
    return _task is not None and not _task.done()


def get_game_state() -> dict:
    """Return game_loop-level state for save/resume."""
    return {
        "tick_count": _tick_count,
        "training_last_hint_idx": _training_last_hint_idx,
        "applied_sensor_assists": list(_applied_sensor_assists),
        "applied_science_medical_assists": list(_applied_science_medical_assists),
        "applied_science_helm_assists": list(_applied_science_helm_assists),
        "applied_science_weapons_assists": list(_applied_science_weapons_assists),
    }


def _restore_game_state(data: dict) -> None:
    """Restore game_loop-level state from save data."""
    global _tick_count, _training_last_hint_idx
    _tick_count = int(data.get("tick_count", 0))
    _training_last_hint_idx = int(data.get("training_last_hint_idx", -1))
    _applied_sensor_assists.clear()
    _applied_sensor_assists.update(data.get("applied_sensor_assists", []))
    _applied_science_medical_assists.clear()
    _applied_science_medical_assists.update(data.get("applied_science_medical_assists", []))
    _applied_science_helm_assists.clear()
    _applied_science_helm_assists.update(data.get("applied_science_helm_assists", []))
    _applied_science_weapons_assists.clear()
    _applied_science_weapons_assists.update(data.get("applied_science_weapons_assists", []))


def _spawn_stations_from_grid(world: "World") -> None:
    """Populate world.stations from sector grid feature definitions (v0.05e)."""
    if world.sector_grid is None:
        return
    world.stations.clear()
    for sector in world.sector_grid.sectors.values():
        for feature in sector.features:
            if feature.type in STATION_FEATURE_TYPES:
                st = spawn_station_from_feature(feature, sector.name)
                world.stations.append(st)
    logger.info("Spawned %d station entities from sector grid", len(world.stations))


def _load_sector_grid_for_mission(mission_dict: dict, mission_id: str):  # type: ignore[return]
    """Load and initialise the sector grid for the given mission.

    Uses the mission's ``sector_layout`` key if present.  The sandbox mission
    defaults to ``standard_grid``.  Returns ``None`` if no layout is specified
    or the file is missing.
    """
    from server.models.sector import load_sector_grid
    layout_id: str | None = mission_dict.get("sector_layout")
    if not layout_id:
        if mission_id == "sandbox":
            layout_id = "standard_grid"
        else:
            return None
    try:
        grid = load_sector_grid(layout_id)
        grid.apply_transponder_reveals()
        return grid
    except FileNotFoundError:
        logger.warning("Sector layout %r not found — running without sector grid", layout_id)
        return None


async def start(mission_id: str, difficulty: str = "officer", ship_class: str = "frigate") -> None:
    """Begin the game loop. Called when the host launches a game."""
    global _task, _tick_count, _game_start_time, _training_last_hint_idx
    global _mission_id, _difficulty_preset, _ship_class_id
    _tick_count = 0
    _game_start_time = _time.monotonic()
    _training_last_hint_idx = -1
    _mission_id = mission_id
    _difficulty_preset = difficulty
    _ship_class_id = ship_class

    # Apply ship class stats before subsystem resets (so ammo uses class defaults).
    try:
        sc = load_ship_class(ship_class)
    except FileNotFoundError:
        logger.warning("Unknown ship class %r — using frigate defaults", ship_class)
        sc = load_ship_class("frigate")

    global _paused, _last_dc_state_json, _current_sector_id
    global _sector_grid_dirty, _last_sector_grid_json, _prev_heading
    _paused = False  # always start unpaused
    _prev_heading = 0.0
    _last_dc_state_json = ""
    _last_sector_grid_json = ""
    _current_sector_id = None
    _sector_grid_dirty = True  # broadcast on first tick
    gln.reset()
    glss.reset()
    # Apply starting_torpedo_multiplier from difficulty preset.
    _diff_preset = get_preset(difficulty)
    _base_loadout = sc.get_torpedo_loadout()
    _scaled_loadout = {
        k: max(0, int(v * _diff_preset.starting_torpedo_multiplier + 0.5))
        for k, v in _base_loadout.items()
    }
    glw.reset(_scaled_loadout)
    glmed.reset()
    if _diff_preset.medical_supply_multiplier != 1.0:
        _base_med = glmed.get_supplies()
        glmed.set_supplies(round(_base_med * _diff_preset.medical_supply_multiplier, 1))
    gls.reset()
    glco.reset()
    glcap.reset()
    gldc.reset()
    glfo.reset(ship_class)
    glew.reset()
    gltac.reset()
    gltr.reset()
    gldo.reset()
    hazard_system.reset_state()
    glsb.reset(active=(mission_id == "sandbox"))
    gldm.reset()
    _puzzle_engine.reset()
    _applied_sensor_assists.clear()
    _applied_science_medical_assists.clear()
    _applied_science_helm_assists.clear()
    _applied_science_weapons_assists.clear()
    _prev_crew_factors.clear()
    sensors.reset()
    glc.reset()
    gle.reset()
    glj.reset()

    if _task is not None and not _task.done():
        logger.warning("Game loop already running — stopping before restart")
        await stop()

    assert _world is not None
    _world.enemies.clear()
    _world.torpedoes.clear()
    _world.stations.clear()
    _world.asteroids.clear()
    _world.hazards.clear()
    _world.creatures.clear()
    _world.ship.alert_level = "green"
    _world.ship.hull = sc.max_hull
    _world.ship.hull_max = sc.max_hull
    _world.ship.max_speed_base = sc.max_speed
    _world.ship.acceleration_base = sc.acceleration
    _world.ship.turn_rate_base = sc.turn_rate
    _world.ship.target_profile = sc.target_profile
    _world.ship.armour = sc.armour
    _world.ship.armour_max = sc.armour
    _world.ship.docked_at = None
    _world.ship.crew = CrewRoster()
    _world.ship.interior = make_default_interior()
    _world.ship.difficulty = _diff_preset

    # v0.06.1: Generate individual crew roster and wire into medical v2.
    _crew_count = (sc.min_crew + sc.max_crew) // 2
    _individual_roster = IndividualCrewRoster.generate(_crew_count, ship_class=ship_class)
    glmed.init_roster(_individual_roster, ship_class=ship_class)

    logger.info(
        "Ship class: %s (hull=%.0f, ammo=%d, crew=%d), difficulty: %s",
        sc.id, sc.max_hull, sum(sc.get_torpedo_loadout().values()), _crew_count, difficulty,
    )

    # Apply difficulty scaling to medical supplies.
    _world.ship.medical_supplies = int(
        _world.ship.medical_supplies * _diff_preset.medical_supply_multiplier + 0.5
    )

    glm.init_mission(mission_id, _world)
    gltr.init_training(glm.get_mission_dict())
    _world.sector_grid = _load_sector_grid_for_mission(glm.get_mission_dict(), mission_id)
    _spawn_stations_from_grid(_world)
    glsb.setup_world(_world)  # no-op unless sandbox is active

    # Apply enemy_health_multiplier to all initially spawned enemies.
    if _diff_preset.enemy_health_multiplier != 1.0:
        for _ene in _world.enemies:
            _ene.hull = round(_ene.hull * _diff_preset.enemy_health_multiplier, 1)

    # v0.06.2 Engineering subsystems (power grid, repair teams, damage model).
    _crew_ids: list[str] = []
    for _dk_name, _dk in _world.ship.crew.decks.items():
        for _ci in range(_dk.total):
            _crew_ids.append(f"{_dk_name}_{_ci}")
    gle.init(_world.ship, crew_member_ids=_crew_ids)

    # v0.06.3: Initialise marine teams for security station.
    gls.init_marine_teams(ship_class, crew_member_ids=_crew_ids)

    # Apply battery_capacity_multiplier to the power grid.
    _pg = gle.get_power_grid()
    if _pg is not None and _diff_preset.battery_capacity_multiplier != 1.0:
        _pg.battery_capacity = round(
            _pg.battery_capacity * _diff_preset.battery_capacity_multiplier, 1
        )
        _pg.battery_charge = min(_pg.battery_charge, _pg.battery_capacity)

    # Apply fog_of_war_reveal — pre-reveal a fraction of sectors.
    if _world.sector_grid is not None and _diff_preset.fog_of_war_reveal > 0.0:
        from server.models.sector import SectorVisibility
        _all_sids = list(_world.sector_grid.sectors.keys())
        _n_reveal = int(len(_all_sids) * _diff_preset.fog_of_war_reveal + 0.5)
        if _n_reveal > 0:
            _reveal_ids = random.sample(_all_sids, min(_n_reveal, len(_all_sids)))
            for _sid in _reveal_ids:
                s = _world.sector_grid.sectors[_sid]
                if s.visibility == SectorVisibility.UNKNOWN:
                    _world.sector_grid.set_visibility(_sid, SectorVisibility.SCANNED)

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


async def resume(
    mission_id: str,
    difficulty_preset: str,
    ship_class: str,
    tick_count: int,
    game_state: dict | None = None,
) -> None:
    """Resume a saved game. State is already restored by save_system.restore_game().

    Does NOT reset modules or re-initialise the mission — all state has been
    loaded before this call. Sets metadata globals and starts the game loop.
    """
    global _task, _tick_count, _game_start_time
    global _mission_id, _difficulty_preset, _ship_class_id
    global _sector_grid_dirty, _last_sector_grid_json

    if _task is not None and not _task.done():
        logger.warning("Game loop already running — stopping before resume")
        await stop()

    _game_start_time = _time.monotonic()
    _mission_id = mission_id
    _difficulty_preset = difficulty_preset
    _ship_class_id = ship_class
    _last_sector_grid_json = ""
    _sector_grid_dirty = True  # broadcast sector grid on first tick after resume
    gln.reset()
    glss.reset()
    gldo.reset()
    glc.reset()

    # Restore game_loop-level state (tick count, assist-tracking sets).
    if game_state:
        _restore_game_state(game_state)
    else:
        _tick_count = tick_count

    # Re-init training from the restored mission dict (reads already-restored gltr state).
    gltr.init_training(glm.get_mission_dict())

    # Re-spawn station entities if the save pre-dates v0.05e station support.
    if not _world.stations and _world.sector_grid is not None:
        _spawn_stations_from_grid(_world)

    _task = asyncio.create_task(_loop(), name="game_loop")
    logger.info("Game loop resumed (mission: %s, tick: %d)", mission_id, _tick_count)


# ---------------------------------------------------------------------------
# Evasive manoeuvre detection (Helm ↔ Flight Ops)
# ---------------------------------------------------------------------------


def _is_ship_evasive(ship: Ship) -> bool:
    """Return True if the ship is currently executing evasive manoeuvres.

    Based on turn rate exceeding the threshold. Used to penalise drone
    recovery attempts per spec Part 7 (Helm ↔ Flight Ops).
    """
    global _prev_heading
    heading_delta = abs(ship.heading - _prev_heading)
    if heading_delta > 180.0:
        heading_delta = 360.0 - heading_delta
    turn_rate = heading_delta / TICK_DT
    _prev_heading = ship.heading
    return turn_rate > _EVASIVE_TURN_RATE


# ---------------------------------------------------------------------------
# Loop internals
# ---------------------------------------------------------------------------


async def _loop() -> None:
    global _tick_count, _current_sector_id, _sector_grid_dirty, _last_sector_grid_json, _last_dc_state_json
    assert _world is not None and _manager is not None and _queue is not None

    while True:
        tick_start = asyncio.get_event_loop().time()

        # Admin pause: skip all tick work, just sleep.
        if _paused:
            await asyncio.sleep(TICK_DT)
            continue

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
                    "fore":      round(_world.ship.shields.fore, 1),
                    "aft":       round(_world.ship.shields.aft,  1),
                    "port":      round(_world.ship.shields.port, 1),
                    "starboard": round(_world.ship.shields.starboard, 1),
                },
                "ammo": glw.get_ammo(),
                "enemy_count": len(_world.enemies),
                "x": round(_world.ship.x, 0),
                "y": round(_world.ship.y, 0),
            })
        glm.apply_asteroid_collisions(_world)

        # 2.6 Sector visibility update.
        if _world.sector_grid is not None:
            _new_sid = _world.sector_grid.update_ship_position(_world.ship.x, _world.ship.y)
            if _current_sector_id != _new_sid:
                if _current_sector_id:
                    _world.sector_grid.on_sector_leave(_current_sector_id)
                _current_sector_id = _new_sid
                _sector_grid_dirty = True

        # 3. Engineering. 3.5 Crew factors + medical + disease. 3.6 Security. 3.7 Comms.
        _eng_result = gle.tick(_world.ship, _world.ship.interior, TICK_DT)
        # 3.1 Training auto-simulation (only active during training missions).
        gltr.auto_helm_tick(_world.ship, TICK_DT)
        gltr.auto_engineering_tick(_world.ship, TICK_DT)
        gldc.tick(_world.ship.interior, TICK_DT, difficulty=_world.ship.difficulty)
        # Build lightweight contact list for drone AI from world entities.
        _fo_contacts: list[dict] = []
        for _foe in _world.enemies:
            _fo_contacts.append({
                "id": _foe.id, "x": _foe.x, "y": _foe.y,
                "heading": _foe.heading, "kind": "enemy",
                "classification": "hostile", "hull": _foe.hull,
            })
        for _sta in getattr(_world, "stations", []):
            _fo_contacts.append({
                "id": _sta.id, "x": _sta.x, "y": _sta.y,
                "heading": 0.0, "kind": "station",
                "classification": "hostile" if getattr(_sta, "faction", "hostile") == "hostile" else "neutral",
            })
        _fo_events = glfo.tick(
            _world.ship, TICK_DT,
            contacts=_fo_contacts,
            in_combat=bool(_world.enemies),
            tick_num=_tick_count,
            ship_evasive=_is_ship_evasive(_world.ship),
        )

        # v0.06.5 Part 7: Process flight ops events for cross-station effects.
        for _foe in _fo_events:
            _foe_type = _foe.get("type", "")
            # Combat drone damage → apply to enemy (Weapons integration).
            if _foe_type == "drone_attack":
                _target_id = _foe.get("target_id", "")
                _dmg = _foe.get("damage", 0.0)
                _drone_id = _foe.get("drone_id", "")
                _atk_drone = glfo.get_drone_by_id(_drone_id)
                if _atk_drone and _dmg > 0:
                    for _enemy in _world.enemies:
                        if _enemy.id == _target_id:
                            apply_hit_to_enemy(
                                _enemy, _dmg,
                                _atk_drone.position[0], _atk_drone.position[1],
                            )
                            break
            # ECM drone jamming → apply jam_factor buildup (EW integration).
            elif _foe_type == "ecm_jamming":
                _jam_tid = _foe.get("target_id", "")
                _jam_str = _foe.get("strength", 0.0)
                for _enemy in _world.enemies:
                    if _enemy.id == _jam_tid:
                        _enemy.jam_factor = min(
                            0.8, _enemy.jam_factor + _jam_str * TICK_DT
                        )
                        break
            # Rescue drone survivor delivery → Medical integration.
            elif _foe_type == "survivors_transferred":
                _surv_count = _foe.get("count", 0)
                if _surv_count > 0:
                    glmed.admit_survivors(_surv_count, _world.ship)

        glew.tick(_world, _world.ship, TICK_DT)
        gltac.tick(_world, _world.ship, TICK_DT)
        # Tick crew reassignment timers before updating crew factors.
        _reassignment_roster = glmed.get_roster()
        _reassignment_events = _reassignment_roster.tick_reassignments(TICK_DT) if _reassignment_roster else []
        _world.ship.update_crew_factors(individual_roster=_reassignment_roster)
        glj.apply_buffs(_world.ship)
        _crew_factor_events = _check_crew_factor_thresholds(_world.ship)
        glmed.tick_treatments(_world.ship, TICK_DT)
        disease_events = glmed.tick_disease(_world.ship.interior, TICK_DT)
        # v0.06.1: tick individual crew injuries/treatments if roster initialised.
        _med_roster = glmed.get_roster()
        medical_v2_events = glmed.tick(_med_roster, TICK_DT, difficulty=_world.ship.difficulty) if _med_roster else []
        security_events = gls.tick_security(_world.ship.interior, _world.ship, TICK_DT)
        # v0.06.3: Enhanced combat system (marine teams + boarding parties).
        combat_events = gls.tick_combat(_world.ship.interior, _world.ship, TICK_DT)
        security_events.extend(combat_events)
        station_boarding_events = gls.tick_station_boarding(_world.ship, TICK_DT)
        glco.set_tick(_tick_count)
        gldm.set_tick(_tick_count)
        comms_responses = glco.tick_comms(TICK_DT)
        hazard_events = hazard_system.tick_hazards(_world, _world.ship, TICK_DT)
        _hazard_sensor_mod = hazard_system.get_sensor_modifier()
        _hazard_shield_mod = hazard_system.get_shield_regen_modifier()
        # 3.8b Janitor maintenance tick.
        _janitor_events = glj.tick(_world.ship, TICK_DT, _world)
        # 3.8 Science sector scan.
        glss_events = glss.tick(TICK_DT, _world)
        # Advance creature study while BIO sector scan is active.
        if glss.get_active_mode() == "bio":
            glc.advance_bio_study(_world.creatures, TICK_DT)
        for _glss_evt in glss_events:
            if _glss_evt["type"] == "sector_visibility_changed":
                _sector_grid_dirty = True
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
        # Auto-fire targeting computer.
        glw.set_weapons_crewed(len(_manager.get_by_role("weapons")) > 0)
        auto_fire_events = glw.tick_auto_fire(_world.ship, _world, TICK_DT)
        _af_status = glw.pop_auto_fire_status_changed()
        if _af_status is not None:
            _af_label = "AUTO-TARGETING ENGAGED" if _af_status else "MANUAL TARGETING ACTIVE"
            await _manager.broadcast_to_roles(
                ["captain"],
                Message.build("weapons.auto_fire_status", {"active": _af_status, "message": _af_label}),
            )
        torpedo_events = glw.tick_torpedoes(_world, _world.ship)
        stations = _world.stations if _world.stations else None
        beam_hit_events = tick_enemies(
            _world.enemies, _world.ship, TICK_DT, stations,
            sensor_modifier=_hazard_sensor_mod, difficulty=_world.ship.difficulty,
        )

        # 5.5 Station AI — turrets, launchers, fighter bays, sensor arrays.
        _station_attacked_ids = glw.pop_stations_attacked()
        station_beam_hits, launched_fighters, reinforcement_calls = tick_station_ai(
            _world.stations, _world.ship, _world, TICK_DT, _station_attacked_ids,
        )
        for fighter in launched_fighters:
            _world.enemies.append(fighter)
        for sid in reinforcement_calls:
            await _manager.broadcast(
                Message.build("station.reinforcement_call", {"station_id": sid})
            )
        # Component-destroyed events from player beam/torpedo hits.
        for comp_ev in glw.pop_component_destroyed_events():
            await _manager.broadcast(
                Message.build("station.component_destroyed", comp_ev)
            )
        # Diplomatic incidents from firing on non-hostile stations.
        for diplo_ev in glw.pop_diplomatic_events():
            await _manager.broadcast(
                Message.build("weapons.diplomatic_incident", diplo_ev)
            )
        # Friendly targeting denials — route only to weapons role.
        for denial in glw.pop_targeting_denials():
            await _manager.broadcast_to_roles(
                ["weapons"],
                Message.build("weapons.targeting_denied", denial),
            )
        # Station outcomes (capture / destroyed).
        for station in list(_world.stations):
            if station.hull <= 0.0 and station.faction == "hostile":
                await _manager.broadcast(
                    Message.build("station.destroyed", {"station_id": station.id})
                )
                _world.stations = [s for s in _world.stations if s.id != station.id]
            elif (not station.captured
                  and station.defenses is not None
                  and gls.check_station_capture(station.id)):
                station.captured = True
                await _manager.broadcast(
                    Message.build("station.captured", {"station_id": station.id})
                )
                engine = glm.get_mission_engine()
                if engine is not None:
                    engine.notify_station_captured(station.id)

        # 5.6 Creature AI tick.
        creature_beam_hits, creature_events = glc.tick(_world, TICK_DT)
        for _cevt in creature_events:
            _ctype = _cevt["type"]
            _cpayload = {k: v for k, v in _cevt.items() if k != "type"}
            if _ctype == "creature.wake_started":
                glss.cancel_scan()
            elif _ctype == "creature.destroyed":
                _cm_engine = glm.get_mission_engine()
                if _cm_engine is not None:
                    _cm_engine.notify_creature_destroyed(_cpayload.get("creature_id", ""))
            await _manager.broadcast(Message.build(_ctype, _cpayload))

        # 6. Enemy beam hits (ship AI + station turrets + creatures). 7. Shields. 7.5 Scan. 7.6 Docking. 8. Cooldowns.
        _hull_before_combat = _world.ship.hull
        _combat_health_snapshot = {n: s.health for n, s in _world.ship.systems.items()}
        combat_damage_events, combat_casualties = await glw.handle_enemy_beam_hits(
            list(beam_hit_events) + list(station_beam_hits) + creature_beam_hits, _world, _manager
        )
        gldc.apply_hull_damage(_hull_before_combat - _world.ship.hull, _world.ship.interior)
        regenerate_shields(_world.ship, hazard_modifier=_hazard_shield_mod)
        scan_completed = sensors.tick(_world, _world.ship, TICK_DT)
        await gldo.tick(_world, _world.ship, _manager, TICK_DT)
        glw.tick_cooldowns(TICK_DT)

        # 8.5 Mission tick.
        over, result = await glm.tick_mission(_world, _world.ship, _manager, TICK_DT)

        # 8.51 Training hint broadcast — sent once per objective advance.
        if gltr.is_training_active():
            _me = glm.get_mission_engine()
            if _me is not None:
                _new_obj_idx = _me.get_active_objective_index()
                if _new_obj_idx != _training_last_hint_idx:
                    _training_last_hint_idx = _new_obj_idx
                    _hint_text = gltr.get_hint_for_idx(_new_obj_idx)
                    if _hint_text:
                        await _manager.broadcast_to_roles(
                            [gltr.get_target_role()],
                            Message.build(
                                "training.hint",
                                {"text": _hint_text, "objective_index": _new_obj_idx},
                            ),
                        )

        if over:
            stats = _build_game_stats()
            _log_path = gl.get_log_path()
            gl.stop_logging(result or "unknown", stats)
            # Compute debrief from completed log.
            if _log_path is not None:
                try:
                    stats["debrief"] = gdb.compute_from_log(_log_path)
                except Exception as _exc:
                    logger.warning("Debrief computation failed: %s", _exc)
            # Update player profiles.
            _update_profiles(result or "defeat", stats)
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
                # EW intrusion: apply beam stun on successful network intrusion.
                if label.startswith("intrusion_") and success and _world is not None:
                    target_id = label[len("intrusion_"):]
                    glew.apply_intrusion_success(target_id, _world)
        else:
            for _pid, label, success in _puzzle_engine.pop_resolved():
                # Apply EW intrusion effect even without a mission engine.
                if label.startswith("intrusion_") and success and _world is not None:
                    target_id = label[len("intrusion_"):]
                    glew.apply_intrusion_success(target_id, _world)
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
            # v0.06.3: Comms intercept — if Comms is crewed, give intel hint.
            if len(_manager.get_by_role("comms")) > 0:
                await _manager.broadcast_to_roles(
                    ["comms", "security", "captain"],
                    Message.build("comms.boarding_intercept", {
                        "message": "Intercepted enemy comms: boarding party detected.",
                    }),
                )

        # 8.72. Sandbox activity events (free-play only).
        for sb_evt in glsb.tick(
            _world, TICK_DT, difficulty=_world.ship.difficulty,
            active_mission_count=len(gldm.get_active_missions()),
        ):
            _sb_type = sb_evt["type"]
            if _sb_type == "spawn_enemy":
                _sb_enemy = spawn_enemy(sb_evt["enemy_type"], sb_evt["x"], sb_evt["y"], sb_evt["id"])
                _ehm = _world.ship.difficulty.enemy_health_multiplier
                if _ehm != 1.0:
                    _sb_enemy.hull = round(_sb_enemy.hull * _ehm, 1)
                _world.enemies.append(_sb_enemy)
                gl.log_event("sandbox", "enemy_spawned", {
                    "type": sb_evt["enemy_type"], "id": sb_evt["id"],
                })
            elif _sb_type == "system_damage":
                _sb_sys = _world.ship.systems.get(sb_evt["system"])
                if _sb_sys is not None:
                    _sb_comp_events = gle.apply_system_damage(sb_evt["system"], sb_evt["amount"], "environment", tick=_tick_count)
                    _sb_dm = gle.get_damage_model()
                    _sb_new_health = _sb_dm.get_system_health(sb_evt["system"]) if _sb_dm else max(0.0, _sb_sys.health - sb_evt["amount"])
                    _sb_comp_hit = _sb_comp_events[0] if _sb_comp_events else {}
                    await _manager.broadcast(Message.build(
                        "ship.system_damaged",
                        {"system": sb_evt["system"],
                         "new_health": round(_sb_new_health, 1),
                         "cause": "environment",
                         "component": _sb_comp_hit.get("component_id", ""),
                         "component_health": round(_sb_comp_hit.get("health", 0.0), 1),
                         "effect": _sb_comp_hit.get("effect", "")},
                    ))
                    gl.log_event("sandbox", "system_damaged", {
                        "system": sb_evt["system"], "amount": sb_evt["amount"],
                        "component": _sb_comp_hit.get("component_id", ""),
                        "component_health": round(_sb_comp_hit.get("health", 0.0), 1),
                        "effect": _sb_comp_hit.get("effect", ""),
                    })
            elif _sb_type == "crew_casualty":
                _world.ship.crew.apply_casualties(sb_evt["deck"], sb_evt["count"])
                # v0.06.1: generate individual injuries via the injury system.
                _sb_roster = glmed.get_roster()
                if _sb_roster is not None:
                    _DECK_NAME_TO_NUM = {"bridge": 1, "sensors": 2, "weapons": 3, "shields": 3, "engineering": 5, "medical": 4}
                    _sb_phys_deck = _DECK_NAME_TO_NUM.get(sb_evt["deck"], 1)
                    _sb_injuries = generate_injuries(
                        "system_malfunction", _sb_phys_deck, _sb_roster,
                        severity_scale=1.0, tick=_tick_count,
                        difficulty=_world.ship.difficulty,
                    )
                    for _sb_cid, _sb_inj in _sb_injuries:
                        _sb_member = _sb_roster.members.get(_sb_cid)
                        if _sb_member is not None:
                            _sb_member.injuries.append(_sb_inj)
                            _sb_member.update_status()
                    for _sb_cid, _sb_inj in _sb_injuries:
                        _sb_member = _sb_roster.members.get(_sb_cid)
                        gl.log_event("sandbox", "crew_casualty", {
                            "deck": sb_evt["deck"],
                            "crew_id": _sb_cid,
                            "crew_name": _sb_member.display_name if _sb_member else _sb_cid,
                            "injury_type": _sb_inj.type,
                            "body_region": _sb_inj.body_region,
                            "severity": _sb_inj.severity,
                        })
                else:
                    gl.log_event("sandbox", "crew_casualty", {
                        "deck": sb_evt["deck"], "count": sb_evt["count"],
                    })
            elif _sb_type == "start_boarding":
                if not gls.is_boarding_active():
                    gls.start_boarding(_world.ship.interior, [], sb_evt["intruders"])
                    gl.log_event("security", "sandbox_boarding_started", {
                        "intruder_count": len(sb_evt["intruders"]),
                    })
            elif _sb_type == "incoming_transmission":
                # Create a Signal object in the comms system
                _sb_faction = sb_evt["faction"]
                _sb_hint = sb_evt["message_hint"]
                # Generate a location near the ship for fleet-movement intel
                import math as _math_sb
                _sb_tx_angle = random.uniform(0.0, 360.0)
                _sb_tx_dist = random.uniform(20000.0, 50000.0)
                _sb_tx_x = _world.ship.x + _math_sb.cos(_math_sb.radians(_sb_tx_angle)) * _sb_tx_dist
                _sb_tx_y = _world.ship.y + _math_sb.sin(_math_sb.radians(_sb_tx_angle)) * _sb_tx_dist
                glco.add_signal(
                    source=f"sb_{_sb_faction}_vessel",
                    source_name=f"{_sb_faction.title()} Vessel",
                    frequency=sb_evt["frequency"],
                    signal_type="broadcast",
                    priority="medium",
                    raw_content=_sb_hint,
                    decoded_content="",
                    requires_decode=True,
                    faction=_sb_faction,
                    threat_level="unknown",
                    expires_ticks=3000,
                    intel_category="fleet",
                    location_data={
                        "type": "approximate",
                        "position": [round(_sb_tx_x, 1), round(_sb_tx_y, 1)],
                        "radius": random.uniform(8000.0, 15000.0),
                    },
                )
                await _manager.broadcast_to_roles(
                    ["comms"],
                    Message.build("comms.incoming_transmission", {
                        "faction":      _sb_faction,
                        "frequency":    sb_evt["frequency"],
                        "message_hint": _sb_hint,
                    }),
                )
                gl.log_event("sandbox", "incoming_transmission", {"faction": _sb_faction})
            elif _sb_type == "hull_micro_damage":
                _world.ship.hull = max(0.0, _world.ship.hull - sb_evt["amount"])
                await _manager.broadcast(Message.build(
                    "ship.hull_hit",
                    {"cause": "micrometeorite", "damage": sb_evt["amount"]},
                ))
                gl.log_event("sandbox", "hull_micro_damage", {"amount": sb_evt["amount"]})
            elif _sb_type == "sensor_anomaly":
                await _manager.broadcast_to_roles(
                    ["science"],
                    Message.build("science.sensor_anomaly", {
                        "x":           sb_evt["x"],
                        "y":           sb_evt["y"],
                        "id":          sb_evt["id"],
                        "anomaly_type": sb_evt["anomaly_type"],
                    }),
                )
                gl.log_event("sandbox", "sensor_anomaly", {
                    "id": sb_evt["id"], "type": sb_evt["anomaly_type"],
                })
            elif _sb_type == "drone_opportunity":
                await _manager.broadcast_to_roles(
                    ["flight_ops"],
                    Message.build("flight_ops.scan_target", {
                        "x":     sb_evt["x"],
                        "y":     sb_evt["y"],
                        "id":    sb_evt["id"],
                        "label": sb_evt["label"],
                    }),
                )
                gl.log_event("sandbox", "drone_opportunity", {
                    "id": sb_evt["id"], "label": sb_evt["label"],
                })
            elif _sb_type == "enemy_jamming":
                await _manager.broadcast_to_roles(
                    ["electronic_warfare"],
                    Message.build("ew.jamming_alert", {"strength": sb_evt["strength"]}),
                )
                gl.log_event("sandbox", "enemy_jamming", {"strength": sb_evt["strength"]})
            elif _sb_type == "distress_signal":
                # Create a distress Signal in the comms system
                _sb_dx, _sb_dy = sb_evt["x"], sb_evt["y"]
                glco.add_signal(
                    source="distress_beacon",
                    source_name="Distress Beacon",
                    frequency=sb_evt["frequency"],
                    signal_type="distress",
                    priority="critical",
                    raw_content=f"EMERGENCY — vessel in distress at ({int(_sb_dx)}, {int(_sb_dy)}). Requesting immediate assistance.",
                    decoded_content="",
                    auto_decoded=True,
                    requires_decode=False,
                    faction="unknown",
                    threat_level="unknown",
                    response_deadline=90.0,
                    location_data={
                        "type": "exact",
                        "position": [_sb_dx, _sb_dy],
                        "radius": 0.0,
                        "entity_type": "ship",
                    },
                )
                await _manager.broadcast_to_roles(
                    ["comms", "helm", "captain"],
                    Message.build("comms.distress_signal", {
                        "x":         _sb_dx,
                        "y":         _sb_dy,
                        "frequency": sb_evt["frequency"],
                    }),
                )
                gl.log_event("sandbox", "distress_signal", {
                    "x": _sb_dx, "y": _sb_dy,
                })
            elif _sb_type == "spawn_creature":
                _world.creatures.append(
                    spawn_creature(sb_evt["id"], sb_evt["creature_type"], sb_evt["x"], sb_evt["y"])
                )
                gl.log_event("sandbox", "creature_spawned", {
                    "type": sb_evt["creature_type"], "id": sb_evt["id"],
                })
            elif _sb_type == "mission_signal":
                glco.add_signal(**sb_evt["signal_params"])
                gl.log_event("sandbox", "mission_signal", {
                    "mission_type": sb_evt["mission_type"],
                })

        # 9. Hull check (safety net when no mission engine).
        if glm.get_mission_engine() is None and _world.ship.hull <= 0.0:
            stats = _build_game_stats()
            gl.stop_logging("defeat", stats)
            _update_profiles("defeat", stats)
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
        # v0.06.5 Part 7: Wire drone/buoy detection bubbles into sensor contacts.
        _detection_bubbles = glfo.get_detection_bubbles(
            _world.ship.systems["flight_deck"].efficiency
        )
        _sensor_contacts_payload = glm.build_sensor_contacts(
            _world, _world.ship, extra_bubbles=_detection_bubbles,
        )
        await _manager.broadcast_to_roles(
            ["weapons", "science"],
            _sensor_contacts_payload,
        )

        # 11b2. Comms intelligence contacts — broadcast to relevant stations.
        glco.pop_pending_contact_updates()  # drain update queue
        _all_comms_contacts = glco.get_comms_contacts()
        if _all_comms_contacts:
            # Try merging comms contacts with sensor contacts
            _sc_list = _sensor_contacts_payload.payload.get("contacts", [])
            _merge_events = glco.try_merge_contacts_with_sensors(_sc_list)
            for _me in _merge_events:
                await _manager.broadcast_to_roles(
                    ["captain", "helm", "science", "weapons"],
                    Message.build("comms.contact_merged", _me),
                )

            # Build per-role contact lists and broadcast
            _comms_roles = {"captain", "helm", "science", "weapons", "comms"}
            for _cr in _comms_roles:
                _role_contacts = glco.get_comms_contacts_for_role(_cr)
                if _role_contacts:
                    await _manager.broadcast_to_roles(
                        [_cr],
                        Message.build("comms.contacts", {"contacts": _role_contacts}),
                    )

        # 11b3. Dynamic missions — offer generated missions, tick lifecycle, broadcast.
        # Drain missions generated by comms signal decode.
        for _gen_mission in glco.pop_pending_generated_missions():
            gldm.offer_mission(_gen_mission)
        # Tick mission timers and auto-complete objectives.
        gldm.tick_missions(
            _world.ship.x, _world.ship.y, TICK_DT,
            enemy_ids=frozenset(e.id for e in _world.enemies),
            docked_station_id=gldo.get_docked_station_id(),
        )
        # Broadcast mission events to captain and log for debrief.
        _dm_events = gldm.pop_pending_mission_events()
        for _dme in _dm_events:
            await _manager.broadcast_to_roles(
                ["captain", "comms"],
                Message.build(f"mission.{_dme['event']}", _dme),
            )
            gl.log_event("dynamic_mission", _dme["event"], _dme)
        # Broadcast active/offered mission list to captain every tick.
        _dm_list = gldm.get_missions_for_broadcast()
        if _dm_list:
            await _manager.broadcast_to_roles(
                ["captain"],
                Message.build("mission.dynamic_list", {"missions": _dm_list}),
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

        # 11c2. Science sector scan progress + completion/interrupt events.
        _glss_progress = glss.build_progress()
        if _glss_progress.get("active"):
            await _manager.broadcast_to_roles(
                ["science"],
                Message.build("science.sector_scan_progress", _glss_progress),
            )
            _scan_indicator = glss.get_scan_indicator()
            if _scan_indicator:
                await _manager.broadcast_to_roles(
                    ["captain", "helm"],
                    Message.build("map.scan_indicator", {"text": _scan_indicator}),
                )
        for _glss_evt in glss_events:
            if _glss_evt["type"] == "complete":
                await _manager.broadcast_to_roles(
                    ["science", "captain", "helm"],
                    Message.build("science.sector_scan_complete", {
                        "scale": _glss_evt["scale"],
                        "sector_id": _glss_evt["sector_id"],
                        "mode": _glss_evt["mode"],
                    }),
                )
                gl.log_event("science", "sector_scan_completed", {
                    "scale": _glss_evt["scale"],
                    "sector_id": _glss_evt["sector_id"],
                    "mode": _glss_evt["mode"],
                })
            elif _glss_evt["type"] == "interrupted":
                await _manager.broadcast_to_roles(
                    ["science", "captain"],
                    Message.build("science.scan_interrupted", {"reason": _glss_evt["reason"]}),
                )
                gl.log_event("science", "sector_scan_interrupted", {
                    "reason": _glss_evt["reason"],
                })

        # 11d. Scan complete.
        for cid in scan_completed:
            ce = next((e for e in _world.enemies if e.id == cid), None)
            if ce is not None:
                await _manager.broadcast(Message.build("science.scan_complete", {
                    "entity_id": cid,
                    "results": sensors.build_scan_result(ce),
                }))
                gl.log_event("science", "scan_completed", {"entity_id": cid})
            # Notify dynamic missions of scan completion.
            gldm.notify_scan_completed(cid)

        # 11e. Security interior state (always broadcast so Security can show the map).
        await _manager.broadcast_to_roles(
            ["security"],
            Message.build("security.interior_state", gls.build_interior_state(_world.ship.interior, _world.ship)),
        )
        # 11e2. Station interior state (when station boarding is active).
        if gls.is_station_boarding_active():
            _boarded_station_id = next(
                (s.id for s in _world.stations if s.defenses is not None
                 and s.defenses.station_interior is not None),
                "station",
            )
            await _manager.broadcast_to_roles(
                ["security"],
                Message.build("security.station_interior",
                              gls.build_station_interior_state(_boarded_station_id)),
            )

        # 11f. Comms state + NPC responses.
        await _manager.broadcast_to_roles(
            ["comms"],
            Message.build("comms.state", glco.build_comms_state(_world)),
        )
        for npc_resp in comms_responses:
            await _manager.broadcast_to_roles(
                ["comms"],
                Message.build("comms.npc_response", npc_resp),
            )

        # 11f1b. Log signal decode completions for debrief.
        for _dc in glco.pop_pending_decode_completions():
            gl.log_event("comms", "signal_decoded", _dc)

        # 11f2. Intel routes → broadcast to target stations.
        for intel_route in glco.pop_pending_intel_routes():
            _target = intel_route.get("target_station", "captain")
            await _manager.broadcast_to_roles(
                [_target],
                Message.build("comms.intel_routed", intel_route),
            )
            gl.log_event("comms", "intel_routed", {
                "target": _target,
                "signal_id": intel_route.get("signal_id"),
            })

        # 11f3. Standing changes → broadcast to comms + captain.
        for sc in glco.pop_pending_standing_changes():
            await _manager.broadcast_to_roles(
                ["comms", "captain"],
                Message.build("comms.standing_changed", sc),
            )
            gl.log_event("comms", "standing_changed", {
                "faction": sc.get("faction_id", ""),
                "amount": sc.get("amount", 0),
                "reason": sc.get("reason", ""),
            })

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

        # 11g2. v0.06.1 Medical v2 state + crew roster broadcast.
        await _manager.broadcast_to_roles(
            ["medical"],
            Message.build("medical.state", glmed.get_medical_state()),
        )
        roster = glmed.get_roster()
        if roster is not None:
            _roster_payload = {"members": {
                cid: m.to_dict() for cid, m in roster.members.items()
            }}
            await _manager.broadcast_to_roles(
                ["medical"],
                Message.build("medical.crew_roster", _roster_payload),
            )
            # Broadcast crew roster to ALL roles for the crew manifest overlay.
            await _manager.broadcast(
                Message.build("crew.roster", _roster_payload),
            )
        for mev in medical_v2_events:
            await _manager.broadcast_to_roles(
                ["medical"],
                Message.build("medical.event", mev),
            )

        # 11g3. Crew factor threshold notifications.
        for cfe in _crew_factor_events:
            await _manager.broadcast_to_roles(
                cfe["roles"],
                Message.build("crew.factor_changed", {
                    "system": cfe["system"],
                    "crew_factor": cfe["crew_factor"],
                    "level": cfe["level"],
                    "message": cfe["message"],
                }),
            )

        # 11g4. Crew reassignment completion notifications.
        for _re in _reassignment_events:
            await _manager.broadcast(
                Message.build("crew.reassignment_complete", _re),
            )

        # 11h. Hazard damage events → hull_hit broadcast + hazard status.
        for hev in hazard_events:
            await _manager.broadcast(
                Message.build("ship.hull_hit", {"cause": hev["hazard_type"], "damage": hev["damage"]})
            )
        _active_hazard_types = hazard_system.get_active_hazard_types()
        if _active_hazard_types:
            await _manager.broadcast(Message.build("hazard.status", {
                "active_types": _active_hazard_types,
                "sensor_modifier": round(_hazard_sensor_mod, 3),
                "shield_regen_modifier": round(_hazard_shield_mod, 3),
                "velocity_cap": hazard_system.get_velocity_cap(),
            }))

        # 11i. Engineering damage-control state → Engineering + Damage Control stations.
        # Performance: only broadcast if state has changed since last tick.
        _dc_state_msg = gldc.build_dc_state(_world.ship.interior, difficulty=_world.ship.difficulty)
        _dc_json = json.dumps(_dc_state_msg, separators=(",", ":"), sort_keys=True)
        if _dc_json != _last_dc_state_json:
            _last_dc_state_json = _dc_json
            await _manager.broadcast_to_roles(
                ["engineering"],
                Message.build("engineering.dc_state", _dc_state_msg),
            )
            await _manager.broadcast_to_roles(
                ["damage_control"],
                Message.build("damage_control.state", _dc_state_msg),
            )

        # 11i-b. Engineering system state → Engineering station.
        await _manager.broadcast_to_roles(
            ["engineering"],
            Message.build("engineering.state", gle.build_state(_world.ship)),
        )

        # 11j. Flight ops state → Flight Ops station.
        await _manager.broadcast_to_roles(
            ["flight_ops"],
            Message.build("flight_ops.state", glfo.build_state(_world.ship)),
        )

        # 11j-b. Flight ops events (launch, recovery, bingo, etc.).
        if _fo_events:
            await _manager.broadcast_to_roles(
                ["flight_ops"],
                Message.build("flight_ops.events", {"events": _fo_events}),
            )
            # v0.06.5 Part 7: Route relevant events to cross-stations.
            _cross_events: dict[str, list[dict]] = {}
            for _foe in _fo_events:
                _foe_type = _foe.get("type", "")
                _targets: list[str] = []
                if _foe_type == "contact_detected":
                    _targets = ["science"]
                elif _foe_type == "drone_attack":
                    _targets = ["weapons"]
                elif _foe_type == "ecm_jamming":
                    _targets = ["electronic_warfare"]
                elif _foe_type == "survivors_transferred":
                    _targets = ["medical", "captain"]
                elif _foe_type in ("drone_destroyed", "drone_crash_on_deck"):
                    _targets = ["captain"]
                for _tgt in _targets:
                    _cross_events.setdefault(_tgt, []).append(_foe)
            for _role, _evts in _cross_events.items():
                await _manager.broadcast_to_roles(
                    [_role],
                    Message.build("flight_ops.events", {"events": _evts}),
                )

        # 11k. EW state → Electronic Warfare station.
        await _manager.broadcast_to_roles(
            ["electronic_warfare"],
            Message.build("ew.state", glew.build_state(_world, _world.ship)),
        )

        # 11l. Tactical state → Tactical station + cross-station broadcasts.
        await _manager.broadcast_to_roles(
            ["tactical"],
            Message.build("tactical.state", gltac.build_state(_world, _world.ship)),
        )
        await _manager.broadcast_to_roles(
            ["weapons"],
            Message.build("tactical.designations", gltac.get_designations()),
        )
        _intercept = gltac.calc_intercept(_world, _world.ship)
        await _manager.broadcast_to_roles(
            ["helm"],
            Message.build("tactical.intercept", _intercept or {}),
        )
        for _roles, _cdata in gltac.pop_pending_broadcasts():
            await _manager.broadcast_to_roles(
                _roles,
                Message.build("tactical.strike_countdown", _cdata),
            )

        # 11m. Janitor state → janitor station (secret).
        await _manager.broadcast_to_roles(
            ["janitor"],
            Message.build("janitor.state", glj.build_state(_world.ship, _world)),
        )
        # Forward janitor task results/errors to janitor station.
        for _jevt in _janitor_events:
            _jevt_type = _jevt.get("type", "janitor.event")
            await _manager.broadcast_to_roles(
                ["janitor"],
                Message.build(_jevt_type, _jevt),
            )

        # 12–15. Damage events, torpedo hits, action events, security events.
        # 12a. Overclock damage events (from gle.tick).
        for _oc_evt in _eng_result.overclock_events:
            _oc_sys = _oc_evt["system"]
            _oc_health = _world.ship.systems[_oc_sys].health
            _oc_comp_hit = _oc_evt["components"][0] if _oc_evt.get("components") else {}
            await _manager.broadcast(Message.build(
                "ship.system_damaged", {
                    "system": _oc_sys, "new_health": round(_oc_health, 1), "cause": "overclock",
                    "component": _oc_comp_hit.get("component_id", ""),
                    "component_health": round(_oc_comp_hit.get("health", 0.0), 1),
                    "effect": _oc_comp_hit.get("effect", ""),
                }))
            gl.log_event("engineering", "overclock_damage", {
                "system": _oc_sys, "new_health": round(_oc_health, 1),
                "component": _oc_comp_hit.get("component_id", ""),
                "component_health": round(_oc_comp_hit.get("health", 0.0), 1),
                "effect": _oc_comp_hit.get("effect", ""),
            })
        # 12b. Repair team notable events.
        _NOTABLE_TEAM_EVENTS = {"team_arrived", "team_returned", "casualty", "team_eliminated"}
        for _rt_evt in _eng_result.repair_team_events:
            if _rt_evt.get("type") in _NOTABLE_TEAM_EVENTS:
                await _manager.broadcast_to_roles(
                    ["engineering"],
                    Message.build("engineering.repair_team_event", _rt_evt),
                )
        for s, h in combat_damage_events:
            _combat_delta = _combat_health_snapshot.get(s, 100.0) - h
            _combat_comp_events: list[dict] = []
            if _combat_delta > 0:
                _combat_comp_events = gle.apply_system_damage(s, _combat_delta, "combat", tick=_tick_count)
            _combat_comp_hit = _combat_comp_events[0] if _combat_comp_events else {}
            await _manager.broadcast(Message.build(
                "ship.system_damaged", {
                    "system": s, "new_health": h, "cause": "combat",
                    "component": _combat_comp_hit.get("component_id", ""),
                    "component_health": round(_combat_comp_hit.get("health", 0.0), 1),
                    "effect": _combat_comp_hit.get("effect", ""),
                }))
            gl.log_event("combat", "system_damaged", {
                "system": s, "new_health": round(h, 1),
                "component": _combat_comp_hit.get("component_id", ""),
                "component_health": round(_combat_comp_hit.get("health", 0.0), 1),
                "effect": _combat_comp_hit.get("effect", ""),
            })
        # 12c. Combat crew casualties — generate individual injuries.
        _combat_roster = glmed.get_roster()
        if _combat_roster is not None:
            for _cc in combat_casualties:
                _cc_injuries = generate_injuries(
                    "explosion", _cc.physical_deck, _combat_roster,
                    severity_scale=min(_cc.count, 3) * 0.5, tick=_tick_count,
                    difficulty=_world.ship.difficulty,
                )
                for _cc_cid, _cc_inj in _cc_injuries:
                    _cc_member = _combat_roster.members.get(_cc_cid)
                    if _cc_member is not None:
                        _cc_member.injuries.append(_cc_inj)
                        _cc_member.update_status()
                for _cc_cid, _cc_inj in _cc_injuries:
                    _cc_member = _combat_roster.members.get(_cc_cid)
                    gl.log_event("combat", "crew_casualty", {
                        "deck": _cc.deck_name,
                        "crew_id": _cc_cid,
                        "crew_name": _cc_member.display_name if _cc_member else _cc_cid,
                        "injury_type": _cc_inj.type,
                        "body_region": _cc_inj.body_region,
                        "severity": _cc_inj.severity,
                    })

        for evt in torpedo_events:
            if evt.get("type") == "pd_intercept":
                await _manager.broadcast(Message.build("weapons.pd_intercept", {
                    "torpedo_id": evt["torpedo_id"],
                    "x": evt["x"],
                    "y": evt["y"],
                }))
                continue
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
        for evt in auto_fire_events:
            await _manager.broadcast(Message.build(evt[0], evt[1]))
        for evt_type, evt_data in security_events:
            await _manager.broadcast_to_roles(["security"], Message.build(evt_type, evt_data))
            # v0.06.3: Forward critical security events to captain + medical.
            if evt_type in (
                "security.boarding_alert", "security.party_eliminated",
                "security.sabotage_started", "security.sabotage_complete",
                "security.squad_eliminated",
            ):
                await _manager.broadcast_to_roles(["captain"], Message.build(evt_type, evt_data))
            if evt_type in ("security.squad_casualty",):
                await _manager.broadcast_to_roles(["medical"], Message.build(evt_type, evt_data))
        for evt_type, evt_data in station_boarding_events:
            await _manager.broadcast_to_roles(["security"], Message.build(evt_type, evt_data))

        # 11m. Navigation: sector grid broadcast (only when changed).
        if _world.sector_grid is not None:
            # Route pending broadcast also marks grid dirty.
            if gln.pop_pending_broadcast():
                _sector_grid_dirty = True
            if _sector_grid_dirty:
                _sg_payload = _build_sector_grid_payload(_world)
                _sg_json = json.dumps(_sg_payload, separators=(",", ":"), sort_keys=True)
                if _sg_json != _last_sector_grid_json:
                    _last_sector_grid_json = _sg_json
                    await _manager.broadcast_to_roles(
                        gln.MAP_CAPABLE_ROLES,
                        Message.build("map.sector_grid", _sg_payload),
                    )
                _sector_grid_dirty = False

        # 16. Sleep for remainder of tick budget.
        elapsed = asyncio.get_event_loop().time() - tick_start
        await asyncio.sleep(max(0.0, TICK_DT - elapsed))


def _build_sector_grid_payload(world: World) -> dict:
    """Serialise the sector grid for a map.sector_grid broadcast."""
    grid = world.sector_grid
    if grid is None:
        return {}
    sectors_out: dict[str, dict] = {}
    for sid, s in grid.sectors.items():
        sectors_out[sid] = {
            "id": sid,
            "name": s.name,
            "grid_position": list(s.grid_position),
            "visibility": s.visibility.value,
            "properties": {
                "type": s.properties.type,
                "faction": s.properties.faction,
                "threat_level": s.properties.threat_level,
                "sensor_modifier": s.properties.sensor_modifier,
                "navigation_hazard": s.properties.navigation_hazard,
            },
            "features": [
                {
                    "id": f.id,
                    "type": f.type,
                    "name": f.name,
                    "position": list(f.position),
                    "visible_without_scan": f.visible_without_scan,
                }
                for f in s.features
            ],
        }
    return {
        "grid_size": list(grid.grid_size),
        "sectors": sectors_out,
        "ship_sector_id": _current_sector_id,
        "route": gln.get_route(),
        "station_entities": [
            {
                "id": st.id,
                "x": st.x,
                "y": st.y,
                "name": st.name,
                "station_type": st.station_type,
                "faction": st.faction,
                "transponder_active": st.transponder_active,
                "requires_scan": st.requires_scan,
                "hull": st.hull,
                "hull_max": st.hull_max,
            }
            for st in world.stations
        ],
    }


def _get_treatment_type(crew_id: str, injury_id: str) -> str:
    """Look up the treatment_type for a specific injury on a crew member."""
    roster = glmed.get_roster()
    if roster is None:
        return "first_aid"
    member = roster.members.get(crew_id)
    if member is None:
        return "first_aid"
    for inj in member.injuries:
        if inj.id == injury_id:
            return inj.treatment_type
    return "first_aid"


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
                gl.log_debounced("helm", "heading_changed", {"from": round(ship.target_heading, 1), "to": payload.heading})
            ship.target_heading = payload.heading
            _set_training_flag(glm, "helm_heading_set")
        elif msg_type == "helm.set_throttle" and isinstance(payload, HelmSetThrottlePayload):
            if payload.throttle != ship.throttle:
                gl.log_debounced("helm", "throttle_changed", {"from": ship.throttle, "to": payload.throttle})
            ship.throttle = payload.throttle
            _set_training_flag(glm, "helm_throttle_set")
        elif msg_type == "engineering.set_power" and isinstance(payload, EngineeringSetPowerPayload):
            _prev_power = ship.systems[payload.system].power
            gle.set_power(payload.system, payload.level)
            if payload.level != _prev_power:
                gl.log_debounced("engineering", "power_changed", {"system": payload.system, "from": _prev_power, "to": payload.level})
            _set_training_flag(glm, "engineering_power_set")
        elif msg_type == "engineering.set_repair" and isinstance(payload, EngineeringSetRepairPayload):
            ship.repair_focus = payload.system
            gle.add_repair_order(payload.system)
            gl.log_event("engineering", "repair_started", {"system": payload.system})
            _set_training_flag(glm, "engineering_repair_set")
        elif msg_type in ("engineering.dispatch_dct", "damage_control.dispatch_dct") and isinstance(payload, EngineeringDispatchDCTPayload):
            gldc.dispatch_dct(payload.room_id, ship.interior)
            gl.log_event("engineering", "dct_dispatched", {"room_id": payload.room_id})
            _set_training_flag(glm, "dc_team_dispatched")
        elif msg_type in ("engineering.cancel_dct", "damage_control.cancel_dct") and isinstance(payload, EngineeringCancelDCTPayload):
            gldc.cancel_dct(payload.room_id)
            gl.log_event("engineering", "dct_cancelled", {"room_id": payload.room_id})
        elif msg_type == "engineering.dispatch_team" and isinstance(payload, EngineeringDispatchTeamPayload):
            gle.dispatch_team(payload.team_id, payload.system, ship.interior)
            gl.log_event("engineering", "team_dispatched", {"team_id": payload.team_id, "system": payload.system})
        elif msg_type == "engineering.recall_team" and isinstance(payload, EngineeringRecallTeamPayload):
            gle.recall_team(payload.team_id, ship.interior)
            gl.log_event("engineering", "team_recalled", {"team_id": payload.team_id})
        elif msg_type == "engineering.set_battery_mode" and isinstance(payload, EngineeringSetBatteryModePayload):
            gle.set_battery_mode(payload.mode)
            gl.log_event("engineering", "battery_mode_changed", {"mode": payload.mode})
        elif msg_type == "engineering.start_reroute" and isinstance(payload, EngineeringStartReroutePayload):
            gle.start_reroute(payload.target_bus)
            gl.log_event("engineering", "reroute_started", {"target_bus": payload.target_bus})
        elif msg_type == "engineering.request_escort" and isinstance(payload, EngineeringRequestEscortPayload):
            # v0.06.3: prefer new-style marine teams; fall back to legacy squads.
            _escort_team = next(
                (t for t in gls.get_marine_teams()
                 if t.status in ("idle", "patrolling") and len(t.members) > 0),
                None,
            )
            if _escort_team is not None:
                gls.assign_escort(_escort_team.id, payload.team_id)
                gle.request_escort(payload.team_id, _escort_team.id)
            else:
                _escort_squad = next(
                    (sq for sq in ship.interior.marine_squads if sq.health > 0),
                    None,
                )
                if _escort_squad is not None:
                    gle.request_escort(payload.team_id, _escort_squad.id)
            gl.log_event("engineering", "escort_requested", {"team_id": payload.team_id})
        elif msg_type == "engineering.cancel_repair_order" and isinstance(payload, EngineeringCancelRepairOrderPayload):
            gle.cancel_repair_order(payload.order_id)
            gl.log_event("engineering", "repair_order_cancelled", {"order_id": payload.order_id})
        elif msg_type == "weapons.select_target" and isinstance(payload, WeaponsSelectTargetPayload):
            if world is not None:
                denial = glw.try_select_target(payload.entity_id, world)
                if not denial:
                    gl.log_event("weapons", "target_selected", {"target_id": payload.entity_id})
                    _set_training_flag(glm, "weapons_target_selected")
                # Denial payload stored in glw._pending_targeting_denials; broadcast in async loop.
            else:
                glw.set_target(payload.entity_id)
                gl.log_event("weapons", "target_selected", {"target_id": payload.entity_id})
                _set_training_flag(glm, "weapons_target_selected")
        elif msg_type == "weapons.fire_beams" and isinstance(payload, WeaponsFireBeamsPayload):
            if world is not None:
                evt = glw.fire_player_beams(ship, world, beam_frequency=payload.beam_frequency)
                if evt:
                    events.append(evt)
                    gl.log_event("weapons", "beam_fired", evt[1])
            _set_training_flag(glm, "weapons_beams_fired")
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
        elif msg_type == "weapons.set_shield_focus" and isinstance(payload, WeaponsSetShieldFocusPayload):
            ship.shield_focus = {"x": payload.x, "y": payload.y}
            ship.shield_distribution = calculate_shield_distribution(payload.x, payload.y)
            gl.log_event("weapons", "shield_focus_changed", {"x": payload.x, "y": payload.y})
            _set_training_flag(glm, "weapons_shield_focus_set")
        elif msg_type == "science.start_scan" and isinstance(payload, ScienceStartScanPayload):
            if glm.is_signal_scan(payload.entity_id):
                events.append(("signal.scan_result", {"ship_x": ship.x, "ship_y": ship.y}))
            else:
                sensors.start_scan(payload.entity_id)
                gl.log_event("science", "scan_started", {"entity_id": payload.entity_id})
            _set_training_flag(glm, "science_scan_started")
        elif msg_type == "science.cancel_scan" and isinstance(payload, ScienceCancelScanPayload):
            sensors.cancel_scan()
        elif msg_type == "science.start_sector_scan" and isinstance(payload, ScienceStartSectorScanPayload):
            if world is not None and world.sector_grid is not None:
                _adj = world.sector_grid.adjacent_sectors(_current_sector_id or "")
                _adj_ids = [s.id for s in _adj]
                glss.start_scan(
                    payload.scale,
                    payload.mode,
                    _current_sector_id or "",
                    _adj_ids,
                    scan_time_multiplier=ship.difficulty.scan_time_multiplier,
                )
                gl.log_event("science", "sector_scan_started", {
                    "scale": payload.scale,
                    "mode": payload.mode,
                    "sector_id": _current_sector_id,
                })
                _set_training_flag(glm, "science_sector_scan_started")
        elif msg_type == "science.cancel_sector_scan" and isinstance(payload, ScienceCancelSectorScanPayload):
            glss.cancel_scan()
            gl.log_event("science", "sector_scan_cancelled", {})
        elif msg_type == "science.scan_interrupt_response" and isinstance(payload, ScienceScanInterruptResponsePayload):
            glss.set_interrupt_response(payload.continue_scan)
            gl.log_event("science", "scan_interrupt_response", {"continue": payload.continue_scan})
        elif msg_type == "medical.treat_crew" and isinstance(payload, MedicalTreatCrewPayload):
            glmed.start_treatment(payload.deck, payload.injury_type, ship)
            gl.log_event("medical", "treatment_started", {"deck": payload.deck, "injury_type": payload.injury_type})
            _set_training_flag(glm, "medical_treatment_started")
        elif msg_type == "medical.cancel_treatment" and isinstance(payload, MedicalCancelTreatmentPayload):
            glmed.cancel_treatment(payload.deck)
            _set_training_flag(glm, "medical_treatment_cancelled")
        # v0.06.1 individual crew medical messages
        elif msg_type == "medical.admit" and isinstance(payload, MedicalAdmitPayload):
            result = glmed.admit_patient(payload.crew_id)
            gl.log_event("medical", "patient_admit", {"crew_id": payload.crew_id, "success": result["success"]})
        elif msg_type == "medical.treat" and isinstance(payload, MedicalTreatPayload):
            result = glmed.start_crew_treatment(payload.crew_id, payload.injury_id, _get_treatment_type(payload.crew_id, payload.injury_id))
            gl.log_event("medical", "treatment_v2_started", {"crew_id": payload.crew_id, "injury_id": payload.injury_id, "success": result["success"]})
        elif msg_type == "medical.stabilise" and isinstance(payload, MedicalStabilisePayload):
            result = glmed.stabilise_crew(payload.crew_id, payload.injury_id)
            gl.log_event("medical", "stabilise", {"crew_id": payload.crew_id, "injury_id": payload.injury_id, "success": result["success"]})
        elif msg_type == "medical.discharge" and isinstance(payload, MedicalDischargePayload):
            result = glmed.discharge_patient(payload.crew_id)
            gl.log_event("medical", "discharge", {"crew_id": payload.crew_id, "success": result["success"]})
        elif msg_type == "medical.quarantine" and isinstance(payload, MedicalQuarantinePayload):
            result = glmed.quarantine_crew(payload.crew_id)
            gl.log_event("medical", "quarantine", {"crew_id": payload.crew_id, "success": result["success"]})
        elif msg_type == "security.move_squad" and isinstance(payload, SecurityMoveSquadPayload):
            gls.move_squad(ship.interior, payload.squad_id, payload.room_id)
            gl.log_event("security", "squad_moved", {"squad_id": payload.squad_id, "room_id": payload.room_id})
            _set_training_flag(glm, "security_squad_moved")
        elif msg_type == "security.toggle_door" and isinstance(payload, SecurityToggleDoorPayload):
            gls.toggle_door(ship.interior, payload.room_id, payload.squad_id)
            gl.log_event("security", "door_toggled", {"room_id": payload.room_id, "squad_id": payload.squad_id})
            _set_training_flag(glm, "security_door_toggled")
        # v0.06.3 — enhanced security commands
        elif msg_type == "security.send_team" and isinstance(payload, SecuritySendTeamPayload):
            gls.send_team(payload.team_id, payload.destination)
            gl.log_event("security", "team_sent", {"team_id": payload.team_id, "destination": payload.destination})
        elif msg_type == "security.set_patrol" and isinstance(payload, SecuritySetPatrolPayload):
            gls.set_team_patrol(payload.team_id, payload.route)
            gl.log_event("security", "patrol_set", {"team_id": payload.team_id, "route": payload.route})
        elif msg_type == "security.station_team" and isinstance(payload, SecurityStationTeamPayload):
            gls.station_team(payload.team_id)
            gl.log_event("security", "team_stationed", {"team_id": payload.team_id})
        elif msg_type == "security.disengage_team" and isinstance(payload, SecurityDisengageTeamPayload):
            gls.disengage_team(payload.team_id)
            gl.log_event("security", "team_disengaged", {"team_id": payload.team_id})
        elif msg_type == "security.assign_escort" and isinstance(payload, SecurityAssignEscortPayload):
            gls.assign_escort(payload.team_id, payload.repair_team_id)
            gle.request_escort(payload.repair_team_id, payload.team_id)
            gl.log_event("security", "escort_assigned", {"team_id": payload.team_id, "repair_team_id": payload.repair_team_id})
        elif msg_type == "security.lock_door" and isinstance(payload, SecurityLockDoorPayload):
            gls.lock_door(ship.interior, payload.room_id)
            gl.log_event("security", "door_locked", {"room_id": payload.room_id})
        elif msg_type == "security.unlock_door" and isinstance(payload, SecurityUnlockDoorPayload):
            gls.unlock_door(ship.interior, payload.room_id)
            gl.log_event("security", "door_unlocked", {"room_id": payload.room_id})
        elif msg_type == "security.lockdown_deck" and isinstance(payload, SecurityLockdownDeckPayload):
            count = gls.lockdown_deck(ship.interior, payload.deck)
            gl.log_event("security", "deck_lockdown", {"deck": payload.deck, "locked": count})
        elif msg_type == "security.lift_lockdown" and isinstance(payload, SecurityLiftLockdownPayload):
            if payload.all:
                count = gls.lift_lockdown_all(ship.interior)
                gl.log_event("security", "lift_lockdown_all", {"unlocked": count})
            elif payload.deck is not None:
                count = gls.lift_deck_lockdown(ship.interior, payload.deck)
                gl.log_event("security", "lift_deck_lockdown", {"deck": payload.deck, "unlocked": count})
        elif msg_type == "security.seal_bulkhead" and isinstance(payload, SecuritySealBulkheadPayload):
            gls.seal_bulkhead(payload.deck_above, payload.deck_below)
            gl.log_event("security", "bulkhead_sealed", {"deck_above": payload.deck_above, "deck_below": payload.deck_below})
        elif msg_type == "security.unseal_bulkhead" and isinstance(payload, SecurityUnsealBulkheadPayload):
            gls.start_unseal_bulkhead(payload.deck_above, payload.deck_below)
            gl.log_event("security", "bulkhead_unseal_started", {"deck_above": payload.deck_above, "deck_below": payload.deck_below})
        elif msg_type == "security.set_deck_alert" and isinstance(payload, SecuritySetDeckAlertPayload):
            gls.set_deck_alert(payload.deck, payload.level)
            gl.log_event("security", "deck_alert_set", {"deck": payload.deck, "level": payload.level})
        elif msg_type == "security.arm_crew" and isinstance(payload, SecurityArmCrewPayload):
            gls.arm_crew(payload.deck)
            gl.log_event("security", "crew_armed", {"deck": payload.deck})
        elif msg_type == "security.disarm_crew" and isinstance(payload, SecurityDisarmCrewPayload):
            gls.disarm_crew(payload.deck)
            gl.log_event("security", "crew_disarmed", {"deck": payload.deck})
        elif msg_type == "security.quarantine_room" and isinstance(payload, SecurityQuarantineRoomPayload):
            gls.quarantine_room(ship.interior, payload.room_id)
            gl.log_event("security", "room_quarantined", {"room_id": payload.room_id})
        elif msg_type == "security.lift_quarantine" and isinstance(payload, SecurityLiftQuarantinePayload):
            gls.lift_quarantine(ship.interior, payload.room_id)
            gl.log_event("security", "quarantine_lifted", {"room_id": payload.room_id})
        elif msg_type == "captain.authorize" and isinstance(payload, CaptainAuthorizePayload):
            if world is not None:
                for evt in glw.resolve_nuclear_auth(payload.request_id, payload.approved, ship, world):
                    events.append(evt)
            _set_training_flag(glm, "captain_authorized")
        elif msg_type == "captain.add_log" and isinstance(payload, CaptainAddLogPayload):
            entry = glcap.add_log_entry(payload.text)
            events.append(("captain.log_entry", {"text": entry["text"], "timestamp": entry["timestamp"]}))
            _set_training_flag(glm, "captain_log_added")
        elif msg_type == "captain.accept_mission" and isinstance(payload, CaptainAcceptMissionPayload):
            result = gldm.accept_mission(payload.mission_id)
            if result.get("ok"):
                events.append(("mission.accepted", result.get("mission", {})))
            else:
                events.append(("mission.accept_error", {"error": result.get("error", "")}))
        elif msg_type == "captain.decline_mission" and isinstance(payload, CaptainDeclineMissionPayload):
            result = gldm.decline_mission(payload.mission_id)
            if result.get("ok"):
                events.append(("mission.declined", {
                    "mission_id": payload.mission_id,
                    "consequences": result.get("consequences", {}),
                }))
            else:
                events.append(("mission.decline_error", {"error": result.get("error", "")}))
        elif msg_type == "comms.tune_frequency" and isinstance(payload, CommsTuneFrequencyPayload):
            glco.tune(payload.frequency)
            _set_training_flag(glm, "comms_frequency_tuned")
        elif msg_type == "comms.hail" and isinstance(payload, CommsHailPayload):
            glco.hail(payload.contact_id, payload.message_type,
                       frequency=payload.frequency, hail_type=payload.hail_type)
            _set_training_flag(glm, "comms_hail_sent")
            gl.log_event("comms", "hail_sent", {"contact_id": payload.contact_id})
        elif msg_type == "comms.decode_signal" and isinstance(payload, CommsDecodeSignalPayload):
            glco.start_decode(payload.signal_id)
            gl.log_event("comms", "decode_started", {"signal_id": payload.signal_id})
        elif msg_type == "comms.respond" and isinstance(payload, CommsRespondPayload):
            glco.respond_to_signal(payload.signal_id, payload.response_id)
            gldm.notify_signal_responded(payload.signal_id)
            gl.log_event("comms", "diplomatic_response", {
                "signal_id": payload.signal_id, "response_id": payload.response_id,
            })
        elif msg_type == "comms.route_intel" and isinstance(payload, CommsRouteIntelPayload):
            glco.route_intel(payload.signal_id, payload.target_station)
        elif msg_type == "comms.set_channel" and isinstance(payload, CommsSetChannelPayload):
            glco.set_channel_status(payload.channel, payload.status)
        elif msg_type == "comms.probe" and isinstance(payload, CommsProbePayload):
            glco.start_probe(payload.target_id)
        elif msg_type == "comms.assess_distress" and isinstance(payload, CommsAssessDistressPayload):
            assessment = glco.assess_distress(payload.signal_id)
            if assessment:
                events.append(("comms.distress_assessment", assessment))
        elif msg_type == "comms.dismiss_signal" and isinstance(payload, CommsDismissSignalPayload):
            glco.dismiss_signal(payload.signal_id)
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
        elif msg_type == "flight_ops.launch_drone" and isinstance(payload, FlightOpsLaunchDronePayload):
            glfo.launch_drone(payload.drone_id, ship)
            gl.log_event("flight_ops", "drone_launched", {"drone_id": payload.drone_id})
            _set_training_flag(glm, "flightops_drone_launched")
        elif msg_type == "flight_ops.recall_drone" and isinstance(payload, FlightOpsRecallDronePayload):
            glfo.recall_drone(payload.drone_id)
            gl.log_event("flight_ops", "drone_recalled", {"drone_id": payload.drone_id})
            _set_training_flag(glm, "flightops_drone_recalled")
        elif msg_type == "flight_ops.set_waypoint" and isinstance(payload, FlightOpsSetWaypointPayload):
            glfo.set_waypoint(payload.drone_id, payload.x, payload.y)
        elif msg_type == "flight_ops.set_loiter_point" and isinstance(payload, FlightOpsSetLoiterPointPayload):
            glfo.set_loiter_point(payload.drone_id, payload.x, payload.y)
        elif msg_type == "flight_ops.set_waypoints" and isinstance(payload, FlightOpsSetWaypointsPayload):
            wps = [(p[0], p[1]) for p in payload.waypoints if len(p) >= 2]
            glfo.set_waypoints(payload.drone_id, wps)
        elif msg_type == "flight_ops.set_engagement_rules" and isinstance(payload, FlightOpsSetEngagementRulesPayload):
            glfo.set_engagement_rules(payload.drone_id, payload.rules)
        elif msg_type == "flight_ops.set_behaviour" and isinstance(payload, FlightOpsSetBehaviourPayload):
            glfo.set_behaviour(payload.drone_id, payload.behaviour)
        elif msg_type == "flight_ops.designate_target" and isinstance(payload, FlightOpsDesignateTargetPayload):
            glfo.designate_target(payload.drone_id, payload.target_id)
        elif msg_type == "flight_ops.deploy_decoy" and isinstance(payload, FlightOpsDeployDecoyPayload):
            glfo.deploy_decoy_cmd(payload.direction, ship)
            gl.log_event("flight_ops", "decoy_deployed", {"direction": payload.direction})
        elif msg_type == "flight_ops.deploy_buoy" and isinstance(payload, FlightOpsDeployBuoyPayload):
            glfo.deploy_buoy_cmd(payload.drone_id)
        elif msg_type == "flight_ops.escort_assign" and isinstance(payload, FlightOpsEscortAssignPayload):
            glfo.escort_assign(payload.drone_id, payload.escort_target)
        elif msg_type == "flight_ops.clear_to_land" and isinstance(payload, FlightOpsClearToLandPayload):
            glfo.clear_to_land(payload.drone_id)
        elif msg_type == "flight_ops.rush_turnaround" and isinstance(payload, FlightOpsRushTurnaroundPayload):
            glfo.rush_turnaround(payload.drone_id, skip=payload.skip if payload.skip else None)
        elif msg_type == "flight_ops.abort_landing" and isinstance(payload, FlightOpsAbortLandingPayload):
            glfo.abort_landing(payload.drone_id)
        elif msg_type == "flight_ops.cancel_launch" and isinstance(payload, FlightOpsCancelLaunchPayload):
            glfo.cancel_launch(payload.drone_id)
        elif msg_type == "flight_ops.prioritise_recovery" and isinstance(payload, FlightOpsPrioritiseRecoveryPayload):
            glfo.prioritise_recovery(payload.order)
        elif msg_type == "ew.set_jam_target" and isinstance(payload, EWSetJamTargetPayload):
            glew.set_jam_target(payload.entity_id)
            gl.log_event("ew", "jam_target_set", {"entity_id": payload.entity_id})
            _set_training_flag(glm, "ew_jam_set")
        elif msg_type == "ew.toggle_countermeasures" and isinstance(payload, EWToggleCountermeasuresPayload):
            if ship is not None:
                glew.toggle_countermeasures(payload.active, ship)
            gl.log_event("ew", "countermeasures_toggled", {"active": payload.active})
            _set_training_flag(glm, "ew_countermeasures_set")
        elif msg_type == "ew.begin_intrusion" and isinstance(payload, EWBeginIntrusionPayload):
            if world is not None:
                target_enemy = next((e for e in world.enemies if e.id == payload.entity_id), None)
                if target_enemy is not None:
                    glew.set_intrusion_target(payload.entity_id, payload.target_system)
                    label = f"intrusion_{payload.entity_id}"
                    _puzzle_engine.create_puzzle(
                        puzzle_type="network_intrusion",
                        station="electronic_warfare",
                        label=label,
                        difficulty=1,
                        time_limit=30.0,
                        target_id=payload.entity_id,
                        target_system=payload.target_system,
                    )
                    gl.log_event("ew", "intrusion_started", {
                        "target_id": payload.entity_id,
                        "target_system": payload.target_system,
                    })
        elif msg_type == "tactical.set_engagement_priority" and isinstance(payload, TacticalSetEngagementPriorityPayload):
            gltac.set_engagement_priority(payload.entity_id, payload.priority)
            gl.log_event("tactical", "engagement_priority_set", {
                "entity_id": payload.entity_id, "priority": payload.priority,
            })
            _set_training_flag(glm, "tactical_priority_set")
        elif msg_type == "tactical.set_intercept_target" and isinstance(payload, TacticalSetInterceptTargetPayload):
            gltac.set_intercept_target(payload.entity_id)
            gl.log_event("tactical", "intercept_target_set", {"entity_id": payload.entity_id})
            _set_training_flag(glm, "tactical_intercept_set")
        elif msg_type == "tactical.add_annotation" and isinstance(payload, TacticalAddAnnotationPayload):
            ann_id = gltac.add_annotation(
                payload.annotation_type, payload.x, payload.y, payload.label, payload.text,
            )
            gl.log_event("tactical", "annotation_added", {"id": ann_id, "type": payload.annotation_type})
        elif msg_type == "tactical.remove_annotation" and isinstance(payload, TacticalRemoveAnnotationPayload):
            gltac.remove_annotation(payload.annotation_id)
            gl.log_event("tactical", "annotation_removed", {"id": payload.annotation_id})
        elif msg_type == "tactical.create_strike_plan" and isinstance(payload, TacticalCreateStrikePlanPayload):
            plan_id = gltac.create_strike_plan([s.model_dump() for s in payload.steps])
            gl.log_event("tactical", "strike_plan_created", {"plan_id": plan_id, "step_count": len(payload.steps)})
            if len(payload.steps) >= 2:
                _set_training_flag(glm, "tactical_plan_created")
        elif msg_type == "tactical.execute_strike_plan" and isinstance(payload, TacticalExecuteStrikePlanPayload):
            ok = gltac.execute_strike_plan(payload.plan_id)
            gl.log_event("tactical", "strike_plan_executed", {"plan_id": payload.plan_id, "found": ok})
        elif msg_type == "map.plot_route" and isinstance(payload, MapPlotRoutePayload):
            if world is not None:
                route = gln.calculate_route(
                    ship.x, ship.y,
                    payload.to_x, payload.to_y,
                    grid=world.sector_grid,
                    current_speed=max(ship.velocity, 50.0),
                )
                gln.set_route(route)
                gl.log_event("navigation", "route_plotted", {
                    "to_x": payload.to_x,
                    "to_y": payload.to_y,
                    "distance": route["total_distance"],
                })
        elif msg_type == "map.clear_route" and isinstance(payload, MapClearRoutePayload):
            gln.clear_route()
            gl.log_event("navigation", "route_cleared", {})
        elif msg_type == "docking.request_clearance" and isinstance(payload, DockingRequestClearancePayload):
            if world is not None:
                err = gldo.request_clearance(payload.station_id, world, ship)
                if err:
                    events.append(("docking.clearance_denied", {
                        "station_id": payload.station_id,
                        "reason": err,
                    }))
                gl.log_event("comms", "docking_clearance_requested", {"station_id": payload.station_id})
        elif msg_type == "docking.start_service" and isinstance(payload, DockingStartServicePayload):
            err = gldo.start_service(payload.service, difficulty=ship.difficulty)
            if err:
                logger.warning("docking.start_service error: %s", err)
            else:
                gl.log_event("captain", "docking_service_started", {"service": payload.service})
        elif msg_type == "docking.cancel_service" and isinstance(payload, DockingCancelServicePayload):
            gldo.cancel_service(payload.service)
            gl.log_event("captain", "docking_service_cancelled", {"service": payload.service})
        elif msg_type == "captain.undock" and isinstance(payload, CaptainUndockPayload):
            err = gldo.captain_undock(payload.emergency)
            if err:
                logger.warning("captain.undock error: %s", err)
            else:
                gl.log_event("captain", "undock_ordered", {"emergency": payload.emergency})
        elif msg_type == "creature.sedate" and isinstance(payload, CreatureSedatePayload):
            if world is not None:
                glc.sedate_creature(payload.creature_id, world)
                gl.log_event("creature", "sedate", {"creature_id": payload.creature_id})
        elif msg_type == "creature.ew_disrupt" and isinstance(payload, CreatureEWDisruptPayload):
            if world is not None:
                glc.ew_disrupt_swarm(payload.creature_id, world)
                gl.log_event("creature", "ew_disrupt", {"creature_id": payload.creature_id})
        elif msg_type == "creature.set_comm_progress" and isinstance(payload, CreatureCommProgressPayload):
            if world is not None:
                glc.set_comm_progress(payload.creature_id, payload.progress, world)
                gl.log_event("creature", "comm_progress", {
                    "creature_id": payload.creature_id,
                    "progress": payload.progress,
                })
        elif msg_type == "creature.leech_remove" and isinstance(payload, CreatureLeeechRemovePayload):
            if world is not None:
                method = payload.method
                if method == "depressurise":
                    glc.remove_leech_depressurise(payload.creature_id, world)
                elif method == "electrical":
                    glc.remove_leech_electrical(payload.creature_id, world)
                elif method == "eva":
                    glc.remove_leech_eva(payload.creature_id, world)
                gl.log_event("creature", "leech_removed", {
                    "creature_id": payload.creature_id,
                    "method": method,
                })
        elif msg_type == "janitor.perform_task" and isinstance(payload, JanitorPerformTaskPayload):
            result = glj.perform_task(payload.task_id, ship, world)
            if result.get("ok"):
                events.append(("janitor.task_result", result))
                gl.log_event("maintenance", "general", {"task_id": payload.task_id})
            else:
                events.append(("janitor.task_error", result))
        elif msg_type == "janitor.dismiss_sticky" and isinstance(payload, JanitorDismissStickyPayload):
            glj.dismiss_sticky(payload.sticky_id)
        else:
            logger.warning("Unrecognised queued input type: %s", msg_type)

    return events


def _set_training_flag(glm_module: object, flag: str) -> None:
    """Set a training flag on the active mission engine (no-op if not training)."""
    if not gltr.is_training_active():
        return
    me = glm_module.get_mission_engine()  # type: ignore[union-attr]
    if me is not None:
        me.set_training_flag(flag)


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
                "fore":      round(ship.shields.fore,      2),
                "aft":       round(ship.shields.aft,       2),
                "port":      round(ship.shields.port,      2),
                "starboard": round(ship.shields.starboard, 2),
            },
            "shield_focus":        ship.shield_focus,
            "shield_distribution": ship.shield_distribution,
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
            "torpedo_ammo_max": glw.get_ammo_max(),
            "tube_cooldowns": [round(c, 2) for c in glw.get_cooldowns()],
            "tube_reload_times": [round(t, 2) for t in glw.get_tube_reload_times()],
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
            "countermeasure_charges": ship.countermeasure_charges,
            "ew_countermeasure_active": ship.ew_countermeasure_active,
            "system_overrides": {
                name: not s._captain_offline
                for name, s in ship.systems.items()
            },
            "hull_max": ship.hull_max,
            "armour": ship.armour,
            "armour_max": ship.armour_max,
            "docked_at": ship.docked_at,
            "docking_phase": gldo.get_state(),
            "active_services": {
                svc: round(t, 1)
                for svc, t in gldo.get_active_services().items()
            },
            "active_hazard_types": hazard_system.get_active_hazard_types(),
            "hazard_sensor_modifier": round(hazard_system.get_sensor_modifier(), 3),
            "auto_fire_active": glw.is_auto_fire_active(),
            # v0.06.3: Security status for Captain display.
            "boarding_active": gls.is_boarding_active(),
            "boarding_party_count": len(gls.get_boarding_parties()),
            "marine_squad_count": len([t for t in gls.get_marine_teams() if len(t.members) > 0]),
            "marine_squad_total": len(gls.get_marine_teams()),
            "locked_door_count": len(gls.get_locked_doors()),
            "deck_alerts": gls.get_all_deck_alerts(),
            "armed_decks": sorted(gls.get_armed_decks()),
            "sealed_bulkheads": [list(b) for b in gls.get_sealed_bulkheads()],
            "quarantined_rooms": sorted(gls.get_quarantined_rooms()),
            "sensor_coverage": round(gls.get_sensor_coverage(ship.interior), 3),
            # v0.06.5 Part 7: Drone summary for Captain display.
            "drone_summary": glfo.build_drone_summary(),
        },
        tick=tick,
    )


# ---------------------------------------------------------------------------
# Crew factor threshold notifications
# ---------------------------------------------------------------------------

# System name → roles that should receive the notification.
_CREW_FACTOR_NOTIFY_ROLES: dict[str, list[str]] = {
    "engines":       ["helm", "captain", "engineering"],
    "beams":         ["weapons", "captain", "engineering"],
    "torpedoes":     ["weapons", "captain", "engineering"],
    "shields":       ["helm", "captain", "engineering"],
    "sensors":       ["science", "captain", "engineering"],
    "manoeuvring":   ["helm", "captain", "engineering"],
    "flight_deck":   ["flight_ops", "captain", "engineering"],
    "ecm_suite":     ["electronic_warfare", "captain", "engineering"],
    "point_defence": ["weapons", "captain", "engineering"],
}

_CREW_FACTOR_THRESHOLDS = [0.75, 0.50, 0.25]


def _check_crew_factor_thresholds(ship: Ship) -> list[dict]:
    """Detect crew factor crossing thresholds and return notification events.

    Compares current crew factors with previously recorded values to detect
    drops below 75%, 50%, 25% thresholds and recovery above them.
    """
    global _prev_crew_factors
    events: list[dict] = []

    for sys_name, sys_obj in ship.systems.items():
        factor = sys_obj._crew_factor
        prev = _prev_crew_factors.get(sys_name, 1.0)

        # Check for crossing below thresholds
        for threshold in _CREW_FACTOR_THRESHOLDS:
            if prev >= threshold > factor:
                pct = round(factor * 100)
                level = "critical" if threshold <= 0.25 else "warning" if threshold <= 0.50 else "caution"
                events.append({
                    "system": sys_name,
                    "crew_factor": round(factor, 2),
                    "threshold": threshold,
                    "level": level,
                    "message": f"{sys_name.upper()} crew {'critical' if level == 'critical' else 'reduced'} — {pct}% effectiveness",
                    "roles": _CREW_FACTOR_NOTIFY_ROLES.get(sys_name, ["captain", "engineering"]),
                })

        # Check for recovery above a previously-crossed threshold
        if factor > prev:
            for threshold in _CREW_FACTOR_THRESHOLDS:
                if prev < threshold <= factor:
                    pct = round(factor * 100)
                    events.append({
                        "system": sys_name,
                        "crew_factor": round(factor, 2),
                        "threshold": threshold,
                        "level": "recovery",
                        "message": f"{sys_name.upper()} crew restored to {pct}%",
                        "roles": _CREW_FACTOR_NOTIFY_ROLES.get(sys_name, ["captain", "engineering"]),
                    })

        _prev_crew_factors[sys_name] = factor

    return events


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
    diff = _world.ship.difficulty if _world is not None else None
    return {
        "duration_s": duration,
        "hull_remaining": hull,
        "captain_log": glcap.get_log(),
        "difficulty": diff.name if diff else "Officer",
    }


def _update_profiles(result: str, stats: dict) -> None:
    """Update player profiles after a game ends.  Errors are logged, not raised."""
    if not _session_players:
        return
    try:
        import server.profiles as _prof  # lazy import avoids circular deps
        per_station = stats.get("debrief", {}).get("per_station_stats", {})
        duration_s  = stats.get("duration_s", 0.0)
        for role, player_name in _session_players.items():
            newly = _prof.update_game_result(
                name=player_name,
                role=role,
                result=result,
                mission_id=_mission_id,
                duration_s=duration_s,
                station_stats=per_station,
            )
            if newly:
                logger.info(
                    "Player %r unlocked achievements: %s", player_name, newly
                )
    except Exception as exc:
        logger.warning("Profile update failed: %s", exc)
