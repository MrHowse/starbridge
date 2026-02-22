"""
v0.05n — New Story Missions.

Tests cover:
  - long_patrol.json: parallel(all) sector sweep, docking, on_complete wave spawn,
    creature conditional, hull emergency conditional
  - deep_space_rescue.json: signal_located, no_creatures_type hull_leech,
    proximity_with_shields, compound defeat condition
  - siege_breaker.json: parallel(all) assault_prep (station_sensor_jammed +
    component_destroyed), station_captured, reinforcements conditional (max_activations=1)
  - first_survey.json: parallel(count=4) grid sectors, parallel("any")
    document_findings, creature_study_complete, signal_located
  - spawn_from_mission for each mission (stations, enemies, creatures)
  - MissionGraph integration trigger tests
"""
from __future__ import annotations

import pytest

from server.mission_graph import MissionGraph
from server.missions.loader import load_mission, spawn_from_mission
from server.models.world import (
    Creature,
    Ship,
    Station,
    World,
    spawn_creature,
    spawn_enemy_station,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_world() -> World:
    return World()


def _make_ship(x: float = 0.0, y: float = 0.0) -> Ship:
    ship = Ship()
    ship.x = x
    ship.y = y
    return ship


def _fresh_graph(mission_id: str) -> MissionGraph:
    return MissionGraph(load_mission(mission_id))


def _graph_eval(trigger_def: dict, world: World, ship: Ship) -> bool:
    g = MissionGraph({"nodes": [], "edges": [], "start_node": None, "victory_nodes": []})
    return g._eval_trigger(trigger_def, world, ship, "")


def _make_creature(
    creature_id: str,
    creature_type: str,
    study_progress: float = 0.0,
    behaviour_state: str = "idle",
) -> Creature:
    c = spawn_creature(creature_id, creature_type, 0.0, 0.0)
    c.study_progress = study_progress
    c.behaviour_state = behaviour_state
    return c


# ---------------------------------------------------------------------------
# 1. Long Patrol — structure
# ---------------------------------------------------------------------------


class TestLongPatrolStructure:
    def test_mission_loads(self):
        m = load_mission("long_patrol")
        assert m["id"] == "long_patrol"

    def test_start_node(self):
        assert load_mission("long_patrol")["start_node"] == "patrol_begin"

    def test_victory_node(self):
        assert load_mission("long_patrol")["victory_nodes"] == ["extract_south"]

    def test_defeat_is_player_hull_zero(self):
        assert load_mission("long_patrol")["defeat_condition"]["type"] == "player_hull_zero"

    def test_patrol_begin_is_checkpoint(self):
        m = load_mission("long_patrol")
        node = next(n for n in m["nodes"] if n["id"] == "patrol_begin")
        assert node["type"] == "checkpoint"

    def test_sweep_sectors_is_parallel_all(self):
        m = load_mission("long_patrol")
        node = next(n for n in m["nodes"] if n["id"] == "sweep_sectors")
        assert node["type"] == "parallel"
        assert node["complete_when"] == "all"

    def test_sweep_has_3_children(self):
        m = load_mission("long_patrol")
        node = next(n for n in m["nodes"] if n["id"] == "sweep_sectors")
        assert len(node["children"]) == 3

    def test_sector_children_ids(self):
        m = load_mission("long_patrol")
        node = next(n for n in m["nodes"] if n["id"] == "sweep_sectors")
        ids = {c["id"] for c in node["children"]}
        assert ids == {"sector_west", "sector_north", "sector_east"}

    def test_repel_raiders_uses_wave_defeated(self):
        m = load_mission("long_patrol")
        node = next(n for n in m["nodes"] if n["id"] == "repel_raiders")
        assert node["trigger"]["type"] == "wave_defeated"
        assert node["trigger"]["prefix"] == "raider_"

    def test_dock_on_complete_spawns_raiders(self):
        m = load_mission("long_patrol")
        edge = next(e for e in m["edges"] if e["from"] == "dock_resupply")
        assert edge["on_complete"]["action"] == "spawn_wave"
        assert len(edge["on_complete"]["enemies"]) == 3

    def test_whale_study_bonus_is_conditional(self):
        m = load_mission("long_patrol")
        node = next(n for n in m["nodes"] if n["id"] == "whale_study_bonus")
        assert node["type"] == "conditional"
        assert node["condition"]["type"] == "creature_study_complete"

    def test_spawn_has_station_and_creature(self):
        m = load_mission("long_patrol")
        world = _make_world()
        spawn_from_mission(m, world, 0)
        assert len(world.stations) == 1
        assert world.stations[0].id == "patrol_outpost"
        assert len(world.creatures) == 1
        assert world.creatures[0].creature_type == "void_whale"


# ---------------------------------------------------------------------------
# 2. Deep Space Rescue — structure
# ---------------------------------------------------------------------------


class TestDeepSpaceRescueStructure:
    def test_mission_loads(self):
        m = load_mission("deep_space_rescue")
        assert m["id"] == "deep_space_rescue"

    def test_start_node(self):
        assert load_mission("deep_space_rescue")["start_node"] == "intercept_signal"

    def test_victory_node(self):
        assert load_mission("deep_space_rescue")["victory_nodes"] == ["extract_survivors"]

    def test_intercept_signal_trigger(self):
        m = load_mission("deep_space_rescue")
        node = next(n for n in m["nodes"] if n["id"] == "intercept_signal")
        assert node["trigger"]["type"] == "signal_located"

    def test_clear_leeches_uses_no_creatures_type(self):
        m = load_mission("deep_space_rescue")
        node = next(n for n in m["nodes"] if n["id"] == "clear_leeches")
        assert node["trigger"]["type"] == "no_creatures_type"
        assert node["trigger"]["creature_type"] == "hull_leech"

    def test_dock_evacuate_uses_proximity_with_shields(self):
        m = load_mission("deep_space_rescue")
        node = next(n for n in m["nodes"] if n["id"] == "dock_evacuate")
        assert node["trigger"]["type"] == "proximity_with_shields"
        assert node["trigger"]["duration"] == 8

    def test_sequential_chain(self):
        m = load_mission("deep_space_rescue")
        by_from = {e["from"]: e["to"] for e in m["edges"] if e["type"] == "sequence"}
        assert by_from["intercept_signal"] == "scan_derelict"
        assert by_from["scan_derelict"] == "clear_leeches"
        assert by_from["clear_leeches"] == "dock_evacuate"
        assert by_from["dock_evacuate"] == "repel_scavengers"
        assert by_from["repel_scavengers"] == "extract_survivors"

    def test_defeat_includes_station_destroyed(self):
        m = load_mission("deep_space_rescue")
        dc = m["defeat_condition"]
        assert dc["type"] == "any_of"
        types = {t["type"] for t in dc["triggers"]}
        assert "station_hull_below" in types

    def test_spawn_has_2_leeches(self):
        m = load_mission("deep_space_rescue")
        world = _make_world()
        spawn_from_mission(m, world, 0)
        leeches = [c for c in world.creatures if c.creature_type == "hull_leech"]
        assert len(leeches) == 2

    def test_spawn_has_derelict_station(self):
        m = load_mission("deep_space_rescue")
        world = _make_world()
        spawn_from_mission(m, world, 0)
        assert any(s.id == "derelict_nova" for s in world.stations)


# ---------------------------------------------------------------------------
# 3. Siege Breaker — structure
# ---------------------------------------------------------------------------


class TestSiegeBreaker:
    def test_mission_loads(self):
        m = load_mission("siege_breaker")
        assert m["id"] == "siege_breaker"

    def test_start_node(self):
        assert load_mission("siege_breaker")["start_node"] == "break_blockade"

    def test_victory_node(self):
        assert load_mission("siege_breaker")["victory_nodes"] == ["capture_command"]

    def test_assault_prep_is_parallel_all(self):
        m = load_mission("siege_breaker")
        node = next(n for n in m["nodes"] if n["id"] == "assault_prep")
        assert node["type"] == "parallel"
        assert node["complete_when"] == "all"

    def test_assault_prep_children(self):
        m = load_mission("siege_breaker")
        node = next(n for n in m["nodes"] if n["id"] == "assault_prep")
        ids = {c["id"] for c in node["children"]}
        assert ids == {"jam_sensor", "destroy_shields"}

    def test_jam_sensor_trigger(self):
        m = load_mission("siege_breaker")
        node = next(n for n in m["nodes"] if n["id"] == "assault_prep")
        jam = next(c for c in node["children"] if c["id"] == "jam_sensor")
        assert jam["trigger"]["type"] == "station_sensor_jammed"
        assert jam["trigger"]["station_id"] == "siege_command"

    def test_destroy_shields_trigger(self):
        m = load_mission("siege_breaker")
        node = next(n for n in m["nodes"] if n["id"] == "assault_prep")
        destroy = next(c for c in node["children"] if c["id"] == "destroy_shields")
        assert destroy["trigger"]["type"] == "component_destroyed"
        assert destroy["trigger"]["component_id"] == "siege_command_gen_0"

    def test_capture_command_uses_station_captured(self):
        m = load_mission("siege_breaker")
        node = next(n for n in m["nodes"] if n["id"] == "capture_command")
        assert node["trigger"]["type"] == "station_captured"
        assert node["trigger"]["station_id"] == "siege_command"

    def test_reinforcements_conditional_max_activations(self):
        m = load_mission("siege_breaker")
        node = next(n for n in m["nodes"] if n["id"] == "reinforcements_wave")
        assert node["type"] == "conditional"
        assert node.get("max_activations") == 1

    def test_reinforcements_condition_is_distress_call(self):
        m = load_mission("siege_breaker")
        node = next(n for n in m["nodes"] if n["id"] == "reinforcements_wave")
        assert node["condition"]["type"] == "station_reinforcements_called"

    def test_spawn_has_enemy_station(self):
        m = load_mission("siege_breaker")
        world = _make_world()
        spawn_from_mission(m, world, 0)
        station_ids = {s.id for s in world.stations}
        assert "outpost_nova" in station_ids
        assert "siege_command" in station_ids

    def test_spawn_has_3_blockade_enemies(self):
        m = load_mission("siege_breaker")
        world = _make_world()
        spawn_from_mission(m, world, 0)
        blockade = [e for e in world.enemies if e.id.startswith("blockade_")]
        assert len(blockade) == 3

    def test_siege_command_has_defenses(self):
        m = load_mission("siege_breaker")
        world = _make_world()
        spawn_from_mission(m, world, 0)
        siege = next(s for s in world.stations if s.id == "siege_command")
        assert siege.defenses is not None


# ---------------------------------------------------------------------------
# 4. First Survey — structure
# ---------------------------------------------------------------------------


class TestFirstSurvey:
    def test_mission_loads(self):
        m = load_mission("first_survey")
        assert m["id"] == "first_survey"

    def test_start_node(self):
        assert load_mission("first_survey")["start_node"] == "depart_hq"

    def test_victory_node(self):
        assert load_mission("first_survey")["victory_nodes"] == ["survey_complete"]

    def test_survey_grid_is_parallel_count_4(self):
        m = load_mission("first_survey")
        node = next(n for n in m["nodes"] if n["id"] == "survey_grid")
        assert node["type"] == "parallel"
        assert node["complete_when"]["count"] == 4

    def test_survey_grid_has_6_children(self):
        m = load_mission("first_survey")
        node = next(n for n in m["nodes"] if n["id"] == "survey_grid")
        assert len(node["children"]) == 6

    def test_document_findings_is_parallel_any(self):
        m = load_mission("first_survey")
        node = next(n for n in m["nodes"] if n["id"] == "document_findings")
        assert node["type"] == "parallel"
        assert node["complete_when"] == "any"

    def test_document_findings_has_2_children(self):
        m = load_mission("first_survey")
        node = next(n for n in m["nodes"] if n["id"] == "document_findings")
        assert len(node["children"]) == 2

    def test_bio_catalogue_trigger(self):
        m = load_mission("first_survey")
        doc_node = next(n for n in m["nodes"] if n["id"] == "document_findings")
        bio = next(c for c in doc_node["children"] if c["id"] == "bio_catalogue")
        assert bio["trigger"]["type"] == "creature_study_complete"
        assert bio["trigger"]["creature_id"] == "leviathan_alpha"

    def test_comms_relay_trigger(self):
        m = load_mission("first_survey")
        doc_node = next(n for n in m["nodes"] if n["id"] == "document_findings")
        relay = next(c for c in doc_node["children"] if c["id"] == "comms_relay")
        assert relay["trigger"]["type"] == "signal_located"

    def test_stalker_conditional(self):
        m = load_mission("first_survey")
        cond = next(n for n in m["nodes"] if n["id"] == "stalker_territory_warning")
        assert cond["type"] == "conditional"
        assert cond["condition"]["creature_id"] == "survey_rift"

    def test_spawn_has_research_hq(self):
        m = load_mission("first_survey")
        world = _make_world()
        spawn_from_mission(m, world, 0)
        assert any(s.id == "research_hq" for s in world.stations)

    def test_spawn_has_leviathan_and_stalker(self):
        m = load_mission("first_survey")
        world = _make_world()
        spawn_from_mission(m, world, 0)
        types = {c.creature_type for c in world.creatures}
        assert "leviathan" in types
        assert "rift_stalker" in types


# ---------------------------------------------------------------------------
# 5. MissionGraph integration
# ---------------------------------------------------------------------------


class TestLongPatrolIntegration:
    def test_parallel_all_completes_when_all_sectors_visited(self):
        g = _fresh_graph("long_patrol")
        world = _make_world()
        ship = _make_ship()
        # Tick to activate patrol_begin (checkpoint activates immediately).
        for _ in range(3):
            g.tick(world, ship, 0.1)
        # sweep_sectors should now be active. Visit all 3 sectors.
        ship.x, ship.y = 15000.0, 50000.0   # sector_west
        for _ in range(3):
            g.tick(world, ship, 0.1)
        ship.x, ship.y = 50000.0, 15000.0   # sector_north
        for _ in range(3):
            g.tick(world, ship, 0.1)
        ship.x, ship.y = 85000.0, 50000.0   # sector_east
        for _ in range(3):
            g.tick(world, ship, 0.1)
        completed = g.get_complete_node_ids()
        assert "sector_west" in completed
        assert "sector_north" in completed
        assert "sector_east" in completed
        assert "sweep_sectors" in completed

    def test_whale_study_conditional_activates(self):
        g = _fresh_graph("long_patrol")
        world = _make_world()
        ship = _make_ship()
        world.creatures.append(_make_creature("patrol_whale", "void_whale", study_progress=100.0))
        for _ in range(5):
            g.tick(world, ship, 0.1)
        assert "whale_study_bonus" in g.get_active_node_ids()


class TestDeepSpaceRescueIntegration:
    def test_signal_located_fires_after_two_scans(self):
        g = _fresh_graph("deep_space_rescue")
        world = _make_world()
        ship = _make_ship()
        g.record_signal_scan(10000.0, 20000.0)
        g.record_signal_scan(30000.0, 40000.0)
        for _ in range(3):
            g.tick(world, ship, 0.1)
        assert "intercept_signal" in g.get_complete_node_ids()

    def test_no_creatures_type_fires_when_leeches_gone(self):
        world = _make_world()
        ship = _make_ship()
        # Leech 1 and 2 present.
        world.creatures.append(_make_creature("leech_1", "hull_leech"))
        world.creatures.append(_make_creature("leech_2", "hull_leech"))
        assert not _graph_eval({"type": "no_creatures_type", "creature_type": "hull_leech"}, world, ship)
        world.creatures.clear()
        assert _graph_eval({"type": "no_creatures_type", "creature_type": "hull_leech"}, world, ship)


class TestSiegeBreakerIntegration:
    def test_station_captured_trigger_fires_after_notify(self):
        g = _fresh_graph("siege_breaker")
        world = _make_world()
        ship = _make_ship()
        g.notify_station_captured("siege_command")
        assert g._eval_trigger(
            {"type": "station_captured", "station_id": "siege_command"}, world, ship, ""
        )

    def test_reinforcements_max_activations_guard(self):
        """Conditional fires once then is suppressed by max_activations=1."""
        g = _fresh_graph("siege_breaker")
        world = _make_world()
        ship = _make_ship()
        # Spawn siege_command with defenses and trigger distress.
        stn = spawn_enemy_station("siege_command", 75000.0, 50000.0, "outpost")
        stn.defenses.sensor_array.distress_sent = True
        world.stations.append(stn)
        # Tick multiple times — should only queue spawn_wave once.
        for _ in range(20):
            g.tick(world, ship, 0.1)
        actions = g.pop_pending_actions()
        spawn_actions = [a for a in actions if a.get("action") == "spawn_wave"]
        assert len(spawn_actions) == 1


class TestFirstSurveyIntegration:
    def test_count_4_of_6_completes_survey_grid(self):
        """4 of 6 sector visits completes the survey_grid parallel."""
        g = _fresh_graph("first_survey")
        world = _make_world()
        # Start at HQ to complete depart_hq.
        ship = _make_ship(50000.0, 50000.0)
        for _ in range(3):
            g.tick(world, ship, 0.1)
        # Visit 4 of 6 sectors.
        sector_positions = [
            (15000.0, 15000.0),   # grid_nw
            (50000.0, 12000.0),   # grid_n
            (85000.0, 15000.0),   # grid_ne
            (88000.0, 50000.0),   # grid_e
        ]
        for sx, sy in sector_positions:
            ship.x, ship.y = sx, sy
            for _ in range(3):
                g.tick(world, ship, 0.1)
        assert "survey_grid" in g.get_complete_node_ids()

    def test_document_findings_any_via_signal(self):
        """signal_located alone completes document_findings (parallel any)."""
        g = _fresh_graph("first_survey")
        world = _make_world()
        ship = _make_ship(50000.0, 50000.0)
        # Complete depart_hq + 4 sectors.
        for _ in range(3):
            g.tick(world, ship, 0.1)
        for sx, sy in [(15000.0, 15000.0), (50000.0, 12000.0),
                       (85000.0, 15000.0), (88000.0, 50000.0)]:
            ship.x, ship.y = sx, sy
            for _ in range(3):
                g.tick(world, ship, 0.1)
        # document_findings now active. Trigger via signal.
        g.record_signal_scan(10000.0, 20000.0)
        g.record_signal_scan(30000.0, 40000.0)
        for _ in range(3):
            g.tick(world, ship, 0.1)
        completed = g.get_complete_node_ids()
        assert "comms_relay" in completed
        assert "document_findings" in completed

    def test_document_findings_any_via_bio_study(self):
        """creature_study_complete alone completes document_findings (parallel any)."""
        g = _fresh_graph("first_survey")
        world = _make_world()
        ship = _make_ship(50000.0, 50000.0)
        lev = _make_creature("leviathan_alpha", "leviathan", study_progress=100.0)
        world.creatures.append(lev)
        # Complete depart_hq + 4 sectors.
        for _ in range(3):
            g.tick(world, ship, 0.1)
        for sx, sy in [(15000.0, 15000.0), (50000.0, 12000.0),
                       (85000.0, 15000.0), (88000.0, 50000.0)]:
            ship.x, ship.y = sx, sy
            for _ in range(3):
                g.tick(world, ship, 0.1)
        # document_findings active. Bio study already complete.
        for _ in range(3):
            g.tick(world, ship, 0.1)
        assert "bio_catalogue" in g.get_complete_node_ids()
        assert "document_findings" in g.get_complete_node_ids()

    def test_full_victory_path(self):
        """Complete full mission: depart → 4 sectors → signal → return."""
        g = _fresh_graph("first_survey")
        world = _make_world()
        ship = _make_ship(50000.0, 50000.0)
        for _ in range(3):
            g.tick(world, ship, 0.1)
        for sx, sy in [(15000.0, 15000.0), (50000.0, 12000.0),
                       (85000.0, 15000.0), (88000.0, 50000.0)]:
            ship.x, ship.y = sx, sy
            for _ in range(3):
                g.tick(world, ship, 0.1)
        g.record_signal_scan(10000.0, 20000.0)
        g.record_signal_scan(30000.0, 40000.0)
        for _ in range(3):
            g.tick(world, ship, 0.1)
        # Return to HQ.
        ship.x, ship.y = 50000.0, 50000.0
        for _ in range(5):
            g.tick(world, ship, 0.1)
        over, result = g.is_over()
        assert over
        assert result == "victory"
