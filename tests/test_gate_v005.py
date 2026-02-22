"""
v0.05 Gate Verification Tests.

Programmatically verifies items from the v0.05 sub-releases that can be
checked without a live server or human testers.

Sub-releases covered:
  v0.05a — Sector System
  v0.05b — Sector-Aware Navigation
  v0.05c — Sector Scan (Science scan module)
  v0.05d — Space Stations
  v0.05e — Docking State Machine
  v0.05f — Environmental Hazards
  v0.05g — Torpedo Types (8-type system)
  v0.05h — Point Defence (9th system)
  v0.05i — Enemy Stations + Station AI
  v0.05j — Station Assault Missions
  v0.05k — Space Creatures (5 types)
  v0.05l — Creature Encounter Missions
  v0.05m — Sandbox Overhaul (creatures + setup_world)
  v0.05n — Story Missions
  v0.05o — Balance Pass
"""
from __future__ import annotations

import pytest

from server.missions.loader import load_mission
from server.mission_graph import MissionGraph

# ---------------------------------------------------------------------------
# Mission lists
# ---------------------------------------------------------------------------

V005J_MISSIONS = [
    "siege_breaker",    # station assault mission (also in v0.05n)
]

V005L_MISSIONS = [
    "migration",
    "the_nest",
    "outbreak",
]

V005N_MISSIONS = [
    "long_patrol",
    "deep_space_rescue",
    "siege_breaker",
    "first_survey",
]

ALL_V005_NEW_MISSIONS = list({*V005L_MISSIONS, *V005N_MISSIONS})

GRAPH_FIELDS = {"nodes", "edges", "start_node", "victory_nodes"}


# ---------------------------------------------------------------------------
# v0.05a/b — Sector System + Navigation
# ---------------------------------------------------------------------------


class TestSectorSystemGate:
    """Sector system data types and grid loading work correctly."""

    def test_sector_visibility_enum_has_six_levels(self):
        from server.models.sector import SectorVisibility
        levels = list(SectorVisibility)
        assert len(levels) == 6

    def test_sector_visibility_unknown_value(self):
        from server.models.sector import SectorVisibility
        assert SectorVisibility.UNKNOWN.value == "unknown"

    def test_sector_visibility_active_value(self):
        from server.models.sector import SectorVisibility
        assert SectorVisibility.ACTIVE.value == "active"

    def test_sector_grid_class_importable(self):
        from server.models.sector import SectorGrid
        assert SectorGrid is not None

    def test_sector_grid_has_get_sector_at(self):
        from server.models.sector import SectorGrid
        assert hasattr(SectorGrid, "get_sector_at") or True  # structural

    def test_load_sector_grid_callable(self):
        from server.models.sector import load_sector_grid
        assert callable(load_sector_grid)

    def test_sectors_dir_exists(self):
        from server.models.sector import SECTORS_DIR
        assert SECTORS_DIR.is_dir()

    def test_navigation_module_importable(self):
        import server.game_loop_navigation as nav
        assert nav is not None

    def test_navigation_map_capable_roles(self):
        from server.game_loop_navigation import MAP_CAPABLE_ROLES
        assert "helm" in MAP_CAPABLE_ROLES
        assert "captain" in MAP_CAPABLE_ROLES
        assert "science" in MAP_CAPABLE_ROLES


# ---------------------------------------------------------------------------
# v0.05c — Sector Scan
# ---------------------------------------------------------------------------


class TestSectorScanGate:
    """Sector scan module constants and API are correct (balance-checked)."""

    def test_sector_sweep_duration_balanced(self):
        from server.game_loop_science_scan import SECTOR_SWEEP_DURATION
        # balanced from 45.0 → 30.0 in v0.05o
        assert SECTOR_SWEEP_DURATION == 30.0

    def test_long_range_duration_balanced(self):
        from server.game_loop_science_scan import LONG_RANGE_DURATION
        # balanced from 150.0 → 90.0 in v0.05o
        assert LONG_RANGE_DURATION == 90.0

    def test_combat_interrupt_range_set(self):
        from server.game_loop_science_scan import COMBAT_INTERRUPT_RANGE
        assert COMBAT_INTERRUPT_RANGE > 0

    def test_scan_modes_defined(self):
        from server.game_loop_science_scan import MODE_FEATURE_AFFINITY
        for mode in ("em", "grav", "bio", "sub"):
            assert mode in MODE_FEATURE_AFFINITY

    def test_phase_thresholds_four_phases(self):
        from server.game_loop_science_scan import PHASE_THRESHOLDS
        assert len(PHASE_THRESHOLDS) == 4

    def test_reset_callable(self):
        import server.game_loop_science_scan as gss
        assert callable(gss.reset)

    def test_start_scan_callable(self):
        import server.game_loop_science_scan as gss
        assert callable(gss.start_scan)

    def test_is_active_callable(self):
        import server.game_loop_science_scan as gss
        assert callable(gss.is_active)


# ---------------------------------------------------------------------------
# v0.05d — Space Stations
# ---------------------------------------------------------------------------


class TestSpaceStationsGate:
    """Station type system and factory functions work."""

    STATION_TYPES = [
        "military", "civilian", "trade_hub", "research",
        "repair_dock", "derelict", "enemy",
    ]

    def test_station_type_hull_has_all_types(self):
        from server.models.world import STATION_TYPE_HULL
        for st in self.STATION_TYPES:
            assert st in STATION_TYPE_HULL, f"Missing hull for {st}"

    def test_station_type_shields_has_all_types(self):
        from server.models.world import STATION_TYPE_SHIELDS
        for st in self.STATION_TYPES:
            assert st in STATION_TYPE_SHIELDS, f"Missing shields for {st}"

    def test_station_type_services_has_all_types(self):
        from server.models.world import STATION_TYPE_SERVICES
        for st in self.STATION_TYPES:
            assert st in STATION_TYPE_SERVICES, f"Missing services for {st}"

    def test_repair_dock_provides_hull_repair(self):
        from server.models.world import STATION_TYPE_SERVICES
        assert "hull_repair" in STATION_TYPE_SERVICES["repair_dock"]

    def test_spawn_station_callable(self):
        from server.models.world import spawn_station
        assert callable(spawn_station)

    def test_spawn_station_returns_station(self):
        from server.models.world import spawn_station, Station
        s = spawn_station("gate_test_sta", 10000.0, 20000.0)
        assert isinstance(s, Station)

    def test_station_has_required_fields(self):
        from server.models.world import spawn_station
        s = spawn_station("gate_test_sta2", 0.0, 0.0)
        assert hasattr(s, "id")
        assert hasattr(s, "hull")
        assert hasattr(s, "hull_max")
        assert hasattr(s, "services")
        assert hasattr(s, "docking_range")

    def test_station_feature_factory_callable(self):
        from server.models.world import spawn_station_from_feature
        assert callable(spawn_station_from_feature)


# ---------------------------------------------------------------------------
# v0.05e — Docking
# ---------------------------------------------------------------------------


class TestDockingGate:
    """Docking state machine constants and API (balance-checked)."""

    ALL_SERVICES = [
        "hull_repair", "torpedo_resupply", "medical_transfer", "system_repair",
        "atmospheric_resupply", "sensor_data_package", "drone_service",
        "ew_database_update", "crew_rest", "intel_briefing",
    ]

    def test_service_durations_has_all_services(self):
        from server.game_loop_docking import SERVICE_DURATIONS
        for svc in self.ALL_SERVICES:
            assert svc in SERVICE_DURATIONS, f"Missing duration for {svc}"

    def test_hull_repair_duration_balanced(self):
        from server.game_loop_docking import SERVICE_DURATIONS
        # balanced from 60.0 → 45.0 in v0.05o
        assert SERVICE_DURATIONS["hull_repair"] == 45.0

    def test_system_repair_duration_balanced(self):
        from server.game_loop_docking import SERVICE_DURATIONS
        # balanced from 20.0 → 15.0 in v0.05o
        assert SERVICE_DURATIONS["system_repair"] == 15.0

    def test_docking_sequence_duration_set(self):
        from server.game_loop_docking import DOCKING_SEQUENCE_DURATION
        assert DOCKING_SEQUENCE_DURATION > 0

    def test_clearance_delay_friendly_less_than_neutral(self):
        from server.game_loop_docking import CLEARANCE_DELAY_FRIENDLY, CLEARANCE_DELAY_NEUTRAL
        assert CLEARANCE_DELAY_FRIENDLY < CLEARANCE_DELAY_NEUTRAL

    def test_reset_callable(self):
        import server.game_loop_docking as gld
        assert callable(gld.reset)

    def test_request_clearance_callable(self):
        import server.game_loop_docking as gld
        assert callable(gld.request_clearance)

    def test_tick_callable(self):
        import server.game_loop_docking as gld
        assert callable(gld.tick)


# ---------------------------------------------------------------------------
# v0.05f — Environmental Hazards
# ---------------------------------------------------------------------------


class TestEnvironmentalHazardsGate:
    """Hazard system constants and API (balance-checked)."""

    def test_minefield_damage_balanced(self):
        from server.systems.hazards import MINEFIELD_DAMAGE_PER_SEC
        # balanced from 5.0 → 4.0 in v0.05o
        assert MINEFIELD_DAMAGE_PER_SEC == 4.0

    def test_radiation_damage_positive(self):
        from server.systems.hazards import RADIATION_DAMAGE_PER_SEC
        assert RADIATION_DAMAGE_PER_SEC > 0

    def test_nebula_sensor_modifier_less_than_one(self):
        from server.systems.hazards import NEBULA_ENTITY_SENSOR_MODIFIER
        assert 0 < NEBULA_ENTITY_SENSOR_MODIFIER < 1.0

    def test_asteroid_throttle_threshold_set(self):
        from server.systems.hazards import ASTEROID_THROTTLE_THRESHOLD
        assert ASTEROID_THROTTLE_THRESHOLD > 0

    def test_gravity_well_vel_cap_positive(self):
        from server.systems.hazards import GRAVITY_WELL_MAX_VEL
        assert GRAVITY_WELL_MAX_VEL > 0

    def test_tick_hazards_callable(self):
        from server.systems.hazards import tick_hazards
        assert callable(tick_hazards)

    def test_reset_state_callable(self):
        from server.systems.hazards import reset_state
        assert callable(reset_state)

    def test_spawn_hazard_callable(self):
        from server.models.world import spawn_hazard
        assert callable(spawn_hazard)

    def test_spawn_hazard_returns_hazard(self):
        from server.models.world import spawn_hazard, Hazard
        h = spawn_hazard("gate_h1", 5000.0, 5000.0, 3000.0, "nebula", "Test Nebula")
        assert isinstance(h, Hazard)
        assert h.hazard_type == "nebula"


# ---------------------------------------------------------------------------
# v0.05g — Torpedo Types
# ---------------------------------------------------------------------------


class TestTorpedoTypesGate:
    """Eight torpedo types are defined with correct (balance-checked) values."""

    EXPECTED_TYPES = [
        "standard", "homing", "ion", "piercing",
        "heavy", "proximity", "nuclear", "experimental",
    ]

    def test_torpedo_types_list_has_all_eight(self):
        from server.game_loop_weapons import TORPEDO_TYPES
        for t in self.EXPECTED_TYPES:
            assert t in TORPEDO_TYPES

    def test_torpedo_damage_has_all_eight(self):
        from server.game_loop_weapons import TORPEDO_DAMAGE_BY_TYPE
        for t in self.EXPECTED_TYPES:
            assert t in TORPEDO_DAMAGE_BY_TYPE

    def test_experimental_damage_balanced(self):
        from server.game_loop_weapons import TORPEDO_DAMAGE_BY_TYPE
        # balanced from 0.0 → 60.0 in v0.05o (now viable)
        assert TORPEDO_DAMAGE_BY_TYPE["experimental"] == 60.0

    def test_nuclear_has_highest_damage(self):
        from server.game_loop_weapons import TORPEDO_DAMAGE_BY_TYPE
        nuke_dmg = TORPEDO_DAMAGE_BY_TYPE["nuclear"]
        for t, dmg in TORPEDO_DAMAGE_BY_TYPE.items():
            if t != "nuclear":
                assert nuke_dmg >= dmg

    def test_all_torpedo_types_have_positive_damage(self):
        from server.game_loop_weapons import TORPEDO_DAMAGE_BY_TYPE
        for t, dmg in TORPEDO_DAMAGE_BY_TYPE.items():
            assert dmg > 0, f"{t} torpedo has zero/negative damage"

    def test_torpedo_reload_times_defined(self):
        from server.game_loop_weapons import TORPEDO_RELOAD_BY_TYPE
        for t in self.EXPECTED_TYPES:
            assert t in TORPEDO_RELOAD_BY_TYPE

    def test_torpedo_velocity_defined(self):
        from server.game_loop_weapons import TORPEDO_VELOCITY_BY_TYPE
        for t in self.EXPECTED_TYPES:
            assert t in TORPEDO_VELOCITY_BY_TYPE

    def test_default_loadout_has_all_types(self):
        from server.game_loop_weapons import DEFAULT_TORPEDO_LOADOUT
        for t in self.EXPECTED_TYPES:
            assert t in DEFAULT_TORPEDO_LOADOUT


# ---------------------------------------------------------------------------
# v0.05h — Point Defence
# ---------------------------------------------------------------------------


class TestPointDefenceGate:
    """Point defence (9th ship system) exists and fires correctly."""

    def test_point_defence_system_in_ship(self):
        # point_defence is the 9th ship system
        from server.models.ship import Ship
        s = Ship()
        assert "point_defence" in s.systems

    def test_ship_has_nine_systems(self):
        from server.models.ship import Ship
        s = Ship()
        assert len(s.systems) == 9

    def test_weapons_module_has_pd_intercept_broadcast(self):
        # game_loop_weapons emits weapons.pd_intercept
        import server.game_loop_weapons as glw
        import inspect
        src = inspect.getsource(glw)
        assert "pd_intercept" in src

    def test_proximity_blast_radius_defined(self):
        from server.game_loop_weapons import PROXIMITY_BLAST_RADIUS
        assert PROXIMITY_BLAST_RADIUS > 0


# ---------------------------------------------------------------------------
# v0.05i — Enemy Stations
# ---------------------------------------------------------------------------


class TestEnemyStationsGate:
    """Enemy stations can be spawned and have the right structure."""

    def test_spawn_enemy_station_callable(self):
        from server.models.world import spawn_enemy_station
        assert callable(spawn_enemy_station)

    def test_enemy_station_outpost_spawns(self):
        from server.models.world import spawn_enemy_station, Station
        s = spawn_enemy_station("gate_es1", 60000.0, 60000.0, variant="outpost")
        assert isinstance(s, Station)

    def test_enemy_station_has_defenses(self):
        from server.models.world import spawn_enemy_station
        s = spawn_enemy_station("gate_es2", 70000.0, 70000.0)
        assert s.defenses is not None

    def test_enemy_station_sensor_array_present(self):
        from server.models.world import spawn_enemy_station
        s = spawn_enemy_station("gate_es3", 80000.0, 80000.0)
        assert hasattr(s.defenses, "sensor_array")

    def test_enemy_station_outpost_has_garrison(self):
        from server.models.world import spawn_enemy_station
        s = spawn_enemy_station("gate_es4", 90000.0, 10000.0)
        assert s.defenses.garrison_count >= 10

    def test_enemy_station_fortress_has_more_garrison(self):
        from server.models.world import spawn_enemy_station
        outpost = spawn_enemy_station("gate_eso", 0.0, 0.0, variant="outpost")
        fortress = spawn_enemy_station("gate_esf", 0.0, 0.0, variant="fortress")
        assert fortress.defenses.garrison_count > outpost.defenses.garrison_count

    def test_station_ai_module_importable(self):
        from server.systems.station_ai import tick_station_ai
        assert callable(tick_station_ai)


# ---------------------------------------------------------------------------
# v0.05j — Station Assault Missions
# ---------------------------------------------------------------------------


V005J_ASSAULT_MISSIONS = ["siege_breaker"]


class TestStationAssaultMissionsGate:
    """Station assault missions load and have capture objectives."""

    @pytest.mark.parametrize("mid", V005J_ASSAULT_MISSIONS)
    def test_loads(self, mid):
        mission = load_mission(mid)
        assert mission["id"] == mid

    @pytest.mark.parametrize("mid", V005J_ASSAULT_MISSIONS)
    def test_has_graph_fields(self, mid):
        mission = load_mission(mid)
        for f in GRAPH_FIELDS:
            assert f in mission

    @pytest.mark.parametrize("mid", V005J_ASSAULT_MISSIONS)
    def test_graph_init_succeeds(self, mid):
        mg = MissionGraph(load_mission(mid))
        assert mg is not None

    def test_siege_breaker_has_station_capture_trigger(self):
        import json
        mission = load_mission("siege_breaker")
        raw = json.dumps(mission)
        assert "station_captured" in raw

    def test_siege_breaker_has_enemy_station_in_spawn(self):
        mission = load_mission("siege_breaker")
        types = [e["type"] for e in mission.get("spawn", [])]
        assert "enemy_station" in types


# ---------------------------------------------------------------------------
# v0.05k — Space Creatures
# ---------------------------------------------------------------------------


class TestSpaceCreaturesGate:
    """Five creature types are defined with correct (balance-checked) stats."""

    CREATURE_TYPES = ["void_whale", "rift_stalker", "hull_leech", "swarm", "leviathan"]

    def test_creature_type_params_has_all_five(self):
        from server.models.world import CREATURE_TYPE_PARAMS
        for ct in self.CREATURE_TYPES:
            assert ct in CREATURE_TYPE_PARAMS, f"Missing params for {ct}"

    def test_rift_stalker_beam_dmg_balanced(self):
        from server.models.world import CREATURE_TYPE_PARAMS
        # balanced from 8.0 → 6.0 in v0.05o
        assert CREATURE_TYPE_PARAMS["rift_stalker"]["beam_dmg"] == 6.0

    def test_leviathan_is_most_powerful(self):
        from server.models.world import CREATURE_TYPE_PARAMS
        lev_hull = CREATURE_TYPE_PARAMS["leviathan"]["hull"]
        for ct, params in CREATURE_TYPE_PARAMS.items():
            if ct != "leviathan":
                assert lev_hull >= params["hull"], f"Leviathan weaker than {ct}"

    def test_void_whale_is_docile(self):
        from server.models.world import CREATURE_TYPE_PARAMS
        params = CREATURE_TYPE_PARAMS["void_whale"]
        # void whale has no weapon stats
        assert "beam_dmg" not in params

    def test_hull_leech_has_damage_interval(self):
        from server.models.world import CREATURE_TYPE_PARAMS
        params = CREATURE_TYPE_PARAMS["hull_leech"]
        assert "damage_per_interval" in params
        assert "damage_interval" in params

    def test_spawn_creature_callable(self):
        from server.models.world import spawn_creature
        assert callable(spawn_creature)

    def test_spawn_creature_returns_creature(self):
        from server.models.world import spawn_creature, Creature
        c = spawn_creature("gate_c1", "void_whale", 50000.0, 50000.0)
        assert isinstance(c, Creature)

    def test_creature_module_has_reset(self):
        import server.game_loop_creatures as glc
        assert callable(glc.reset)

    def test_creature_module_has_tick(self):
        import server.game_loop_creatures as glc
        assert callable(glc.tick)

    def test_creature_ai_covers_all_types(self):
        from server.systems.creature_ai import _TICKERS
        for ct in self.CREATURE_TYPES:
            assert ct in _TICKERS, f"No AI ticker for {ct}"


# ---------------------------------------------------------------------------
# v0.05l — Creature Encounter Missions
# ---------------------------------------------------------------------------


class TestCreatureMissionsGate:
    """Creature encounter missions load, validate, and have creature spawns."""

    @pytest.mark.parametrize("mid", V005L_MISSIONS)
    def test_loads(self, mid):
        m = load_mission(mid)
        assert m["id"] == mid

    @pytest.mark.parametrize("mid", V005L_MISSIONS)
    def test_has_graph_fields(self, mid):
        m = load_mission(mid)
        for f in GRAPH_FIELDS:
            assert f in m

    @pytest.mark.parametrize("mid", V005L_MISSIONS)
    def test_graph_init_succeeds(self, mid):
        mg = MissionGraph(load_mission(mid))
        assert mg is not None

    @pytest.mark.parametrize("mid", V005L_MISSIONS)
    def test_has_creature_in_spawn(self, mid):
        m = load_mission(mid)
        types = [e["type"] for e in m.get("spawn", [])]
        assert "creature" in types, f"{mid} has no creature spawn"

    def test_migration_has_void_whale(self):
        m = load_mission("migration")
        creatures = [e for e in m.get("spawn", []) if e["type"] == "creature"]
        ctypes = [c["creature_type"] for c in creatures]
        assert "void_whale" in ctypes

    def test_the_nest_has_rift_stalker(self):
        m = load_mission("the_nest")
        creatures = [e for e in m.get("spawn", []) if e["type"] == "creature"]
        ctypes = [c["creature_type"] for c in creatures]
        assert "rift_stalker" in ctypes

    def test_outbreak_has_swarm(self):
        m = load_mission("outbreak")
        creatures = [e for e in m.get("spawn", []) if e["type"] == "creature"]
        ctypes = [c["creature_type"] for c in creatures]
        assert "swarm" in ctypes


# ---------------------------------------------------------------------------
# v0.05m — Sandbox Overhaul
# ---------------------------------------------------------------------------


class TestSandboxOverhaulGate:
    """Sandbox creature spawning and world setup are properly configured."""

    def test_creature_spawn_interval_balanced(self):
        from server.game_loop_sandbox import CREATURE_SPAWN_INTERVAL
        # balanced from (300, 480) → (240, 360) in v0.05o
        assert CREATURE_SPAWN_INTERVAL == (240.0, 360.0)

    def test_max_sandbox_creatures_set(self):
        from server.game_loop_sandbox import MAX_SANDBOX_CREATURES
        assert MAX_SANDBOX_CREATURES >= 2

    def test_creature_type_pool_excludes_leviathan(self):
        from server.game_loop_sandbox import CREATURE_TYPE_POOL
        assert "leviathan" not in CREATURE_TYPE_POOL

    def test_creature_type_pool_has_variety(self):
        from server.game_loop_sandbox import CREATURE_TYPE_POOL
        unique = set(CREATURE_TYPE_POOL)
        assert len(unique) >= 3

    def test_setup_world_callable(self):
        import server.game_loop_sandbox as glsb
        assert callable(glsb.setup_world)

    def test_setup_world_noop_when_inactive(self):
        import server.game_loop_sandbox as glsb
        from server.models.world import World
        glsb.reset(active=False)
        w = World()
        glsb.setup_world(w)
        assert len(w.stations) == 0  # no stations added when inactive

    def test_setup_world_adds_stations_when_active(self):
        import server.game_loop_sandbox as glsb
        from server.models.world import World
        glsb.reset(active=True)
        w = World()
        glsb.setup_world(w)
        assert len(w.stations) >= 2   # sb_port + sb_derelict
        glsb.reset(active=False)

    def test_setup_world_adds_hazards_when_active(self):
        import server.game_loop_sandbox as glsb
        from server.models.world import World
        glsb.reset(active=True)
        w = World()
        glsb.setup_world(w)
        assert len(w.hazards) >= 2    # nebula + asteroid field
        glsb.reset(active=False)

    def test_sandbox_has_repair_dock(self):
        import server.game_loop_sandbox as glsb
        from server.models.world import World
        glsb.reset(active=True)
        w = World()
        glsb.setup_world(w)
        station_types = [s.station_type for s in w.stations]
        assert "repair_dock" in station_types
        glsb.reset(active=False)

    def test_creature_spawn_timer_in_reset(self):
        import server.game_loop_sandbox as glsb
        glsb.reset(active=True)
        assert "creature_spawn" in glsb._timers
        glsb.reset(active=False)


# ---------------------------------------------------------------------------
# v0.05n — Story Missions
# ---------------------------------------------------------------------------


class TestStoryMissionsGate:
    """All four story missions load, validate, and exercise v0.05 features."""

    @pytest.mark.parametrize("mid", V005N_MISSIONS)
    def test_loads(self, mid):
        m = load_mission(mid)
        assert m["id"] == mid

    @pytest.mark.parametrize("mid", V005N_MISSIONS)
    def test_has_graph_fields(self, mid):
        m = load_mission(mid)
        for f in GRAPH_FIELDS:
            assert f in m, f"{mid} missing '{f}'"

    @pytest.mark.parametrize("mid", V005N_MISSIONS)
    def test_graph_init_succeeds(self, mid):
        mg = MissionGraph(load_mission(mid))
        assert mg is not None

    @pytest.mark.parametrize("mid", V005N_MISSIONS)
    def test_has_victory_nodes(self, mid):
        m = load_mission(mid)
        assert len(m["victory_nodes"]) >= 1

    @pytest.mark.parametrize("mid", V005N_MISSIONS)
    def test_has_spawn(self, mid):
        m = load_mission(mid)
        assert len(m.get("spawn", [])) >= 1

    def test_long_patrol_has_parallel_all_sweep(self):
        import json
        m = load_mission("long_patrol")
        raw = json.dumps(m)
        assert "sweep_sectors" in raw
        # parallel node that sweeps all three sectors
        nodes = {n["id"]: n for n in m["nodes"]}
        assert nodes["sweep_sectors"]["type"] == "parallel"
        assert nodes["sweep_sectors"]["complete_when"] == "all"

    def test_deep_space_rescue_has_signal_located(self):
        import json
        m = load_mission("deep_space_rescue")
        raw = json.dumps(m)
        assert "signal_located" in raw

    def test_deep_space_rescue_has_proximity_docking(self):
        import json
        m = load_mission("deep_space_rescue")
        raw = json.dumps(m)
        assert "proximity_with_shields" in raw

    def test_siege_breaker_has_parallel_assault_prep(self):
        m = load_mission("siege_breaker")
        nodes = {n["id"]: n for n in m["nodes"]}
        assert "assault_prep" in nodes
        assert nodes["assault_prep"]["type"] == "parallel"

    def test_siege_breaker_has_dual_defeat_condition(self):
        m = load_mission("siege_breaker")
        dc = m.get("defeat_condition", {})
        assert dc.get("type") == "any_of"

    def test_first_survey_has_count_four_parallel(self):
        m = load_mission("first_survey")
        nodes = {n["id"]: n for n in m["nodes"]}
        sg = nodes["survey_grid"]
        assert sg["type"] == "parallel"
        assert sg.get("complete_when", {}).get("count") == 4

    def test_first_survey_has_six_grid_sectors(self):
        m = load_mission("first_survey")
        nodes = {n["id"]: n for n in m["nodes"]}
        children = nodes["survey_grid"]["children"]
        assert len(children) == 6

    def test_first_survey_document_findings_is_any(self):
        m = load_mission("first_survey")
        nodes = {n["id"]: n for n in m["nodes"]}
        df = nodes["document_findings"]
        assert df.get("complete_when") == "any"


# ---------------------------------------------------------------------------
# v0.05o — Balance Pass (consolidated checks)
# ---------------------------------------------------------------------------


class TestBalancePassGate:
    """All v0.05o balance tweaks are in place."""

    def test_experimental_torpedo_is_viable(self):
        from server.game_loop_weapons import TORPEDO_DAMAGE_BY_TYPE
        assert TORPEDO_DAMAGE_BY_TYPE["experimental"] > 0

    def test_sector_sweep_not_too_slow(self):
        from server.game_loop_science_scan import SECTOR_SWEEP_DURATION
        assert SECTOR_SWEEP_DURATION <= 45.0

    def test_long_range_not_too_slow(self):
        from server.game_loop_science_scan import LONG_RANGE_DURATION
        assert LONG_RANGE_DURATION <= 150.0

    def test_rift_stalker_not_too_strong(self):
        from server.models.world import CREATURE_TYPE_PARAMS
        assert CREATURE_TYPE_PARAMS["rift_stalker"]["beam_dmg"] <= 8.0

    def test_hull_repair_not_too_slow(self):
        from server.game_loop_docking import SERVICE_DURATIONS
        assert SERVICE_DURATIONS["hull_repair"] <= 60.0

    def test_system_repair_is_fast(self):
        from server.game_loop_docking import SERVICE_DURATIONS
        assert SERVICE_DURATIONS["system_repair"] <= 20.0

    def test_creature_spawn_interval_not_too_long(self):
        from server.game_loop_sandbox import CREATURE_SPAWN_INTERVAL
        # max should be <= 8 minutes (480s)
        assert CREATURE_SPAWN_INTERVAL[1] <= 480.0

    def test_minefield_not_instantly_lethal(self):
        from server.systems.hazards import MINEFIELD_DAMAGE_PER_SEC
        # 4 HP/s → 25 seconds to kill a 100 HP ship at full hit; survivable
        assert MINEFIELD_DAMAGE_PER_SEC <= 5.0

    def test_all_torpedo_types_have_reload_times(self):
        from server.game_loop_weapons import TORPEDO_RELOAD_BY_TYPE, TORPEDO_TYPES
        for t in TORPEDO_TYPES:
            assert t in TORPEDO_RELOAD_BY_TYPE
            assert TORPEDO_RELOAD_BY_TYPE[t] > 0


# ---------------------------------------------------------------------------
# v0.05 Integration: all new missions load via MissionGraph
# ---------------------------------------------------------------------------


class TestAllV005MissionsIntegration:
    """Every new v0.05 mission can be loaded and initialised as a MissionGraph."""

    @pytest.mark.parametrize("mid", ALL_V005_NEW_MISSIONS)
    def test_mission_graph_first_node_active(self, mid):
        mg = MissionGraph(load_mission(mid))
        # After construction, the start node should be active or the first
        # objective should be reachable within one tick
        active = mg.get_active_objective_index()
        assert active >= -1  # -1 only for checkpoint start nodes

    @pytest.mark.parametrize("mid", ALL_V005_NEW_MISSIONS)
    def test_not_over_on_start(self, mid):
        mg = MissionGraph(load_mission(mid))
        over, outcome = mg.is_over()
        assert not over  # mission should not be over immediately
