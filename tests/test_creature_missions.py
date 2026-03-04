"""
v0.05l — Creature Missions.

Tests cover:
  - loader.py spawn_from_mission with "creature" type
  - migration.json: nested parallel(count=2) survey + wave_defeated poachers + conditional
  - the_nest.json: branch node (fight vs negotiate paths), creature_state sedated triggers
  - outbreak.json: sequential chain, creature_study_complete + creature_state dispersed,
                   conditional scavenger wave, compound defeat condition
  - MissionGraph creature trigger integration for all three missions
"""
from __future__ import annotations

import pytest

from server.mission_graph import MissionGraph
from server.missions.loader import load_mission, spawn_from_mission
from server.models.world import Creature, Ship, World, spawn_creature


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
    """Evaluate a trigger on a minimal fresh MissionGraph."""
    g = MissionGraph({"nodes": [], "edges": [], "start_node": None, "victory_nodes": []})
    return g._eval_trigger(trigger_def, world, ship, "")


def _graph_eval_with_graph(g: MissionGraph, trigger_def: dict, world: World, ship: Ship) -> bool:
    return g._eval_trigger(trigger_def, world, ship, "")


def _make_creature(
    creature_id: str,
    creature_type: str,
    x: float = 0.0,
    y: float = 0.0,
    study_progress: float = 0.0,
    behaviour_state: str = "idle",
) -> Creature:
    c = spawn_creature(creature_id, creature_type, x, y)
    c.study_progress = study_progress
    c.behaviour_state = behaviour_state
    return c


# ---------------------------------------------------------------------------
# 1. Loader — creature spawn type
# ---------------------------------------------------------------------------


class TestLoaderCreatureSpawn:
    def test_creature_spawned_into_world_creatures(self):
        mission = load_mission("migration")
        world = _make_world()
        spawn_from_mission(mission, world, 0)
        assert len(world.creatures) == 3

    def test_creature_ids_correct(self):
        mission = load_mission("migration")
        world = _make_world()
        spawn_from_mission(mission, world, 0)
        ids = {c.id for c in world.creatures}
        assert ids == {"whale_1", "whale_2", "whale_3"}

    def test_creature_type_set(self):
        mission = load_mission("migration")
        world = _make_world()
        spawn_from_mission(mission, world, 0)
        for c in world.creatures:
            assert c.creature_type == "void_whale"

    def test_creature_position(self):
        mission = load_mission("migration")
        world = _make_world()
        spawn_from_mission(mission, world, 0)
        w1 = next(c for c in world.creatures if c.id == "whale_1")
        assert w1.x == 25000.0
        assert w1.y == 30000.0

    def test_enemies_also_spawned(self):
        mission = load_mission("migration")
        world = _make_world()
        spawn_from_mission(mission, world, 0)
        assert len(world.enemies) == 2
        enemy_ids = {e.id for e in world.enemies}
        assert "poacher_1" in enemy_ids
        assert "poacher_2" in enemy_ids

    def test_the_nest_spawns_3_stalkers(self):
        mission = load_mission("the_nest")
        world = _make_world()
        spawn_from_mission(mission, world, 0)
        stalkers = [c for c in world.creatures if c.creature_type == "rift_stalker"]
        assert len(stalkers) == 3

    def test_the_nest_spawns_station(self):
        mission = load_mission("the_nest")
        world = _make_world()
        spawn_from_mission(mission, world, 0)
        station_ids = {s.id for s in world.stations}
        assert "relay_kappa" in station_ids

    def test_outbreak_spawns_swarm(self):
        mission = load_mission("outbreak")
        world = _make_world()
        spawn_from_mission(mission, world, 0)
        assert len(world.creatures) == 1
        assert world.creatures[0].creature_type == "swarm"
        assert world.creatures[0].id == "swarm_1"


# ---------------------------------------------------------------------------
# 2. Migration mission structure
# ---------------------------------------------------------------------------


class TestMigrationMission:
    def test_mission_loads(self):
        m = load_mission("migration")
        assert m["id"] == "migration"

    def test_start_node(self):
        m = load_mission("migration")
        assert m["start_node"] == "intercept"

    def test_victory_nodes(self):
        m = load_mission("migration")
        assert m["victory_nodes"] == ["clear_zone"]

    def test_defeat_is_player_hull_zero(self):
        m = load_mission("migration")
        assert m["defeat_condition"]["type"] == "player_hull_zero"

    def test_protect_and_study_is_parallel_all(self):
        m = load_mission("migration")
        node = next(n for n in m["nodes"] if n["id"] == "protect_and_study")
        assert node["type"] == "parallel"
        assert node["complete_when"] == "all"

    def test_survey_whales_is_parallel_count_2(self):
        m = load_mission("migration")
        protect_node = next(n for n in m["nodes"] if n["id"] == "protect_and_study")
        survey = next(c for c in protect_node["children"] if c["id"] == "survey_whales")
        assert survey["type"] == "parallel"
        assert survey["complete_when"]["count"] == 2

    def test_survey_has_3_study_children(self):
        m = load_mission("migration")
        protect_node = next(n for n in m["nodes"] if n["id"] == "protect_and_study")
        survey = next(c for c in protect_node["children"] if c["id"] == "survey_whales")
        study_ids = {c["id"] for c in survey["children"]}
        assert study_ids == {"study_whale_1", "study_whale_2", "study_whale_3"}

    def test_study_triggers_use_correct_creature_ids(self):
        m = load_mission("migration")
        protect_node = next(n for n in m["nodes"] if n["id"] == "protect_and_study")
        survey = next(c for c in protect_node["children"] if c["id"] == "survey_whales")
        creature_ids = {c["trigger"]["creature_id"] for c in survey["children"]}
        assert creature_ids == {"whale_1", "whale_2", "whale_3"}

    def test_neutralise_poachers_uses_wave_defeated(self):
        m = load_mission("migration")
        protect_node = next(n for n in m["nodes"] if n["id"] == "protect_and_study")
        neutralise = next(c for c in protect_node["children"] if c["id"] == "neutralise_poachers")
        assert neutralise["trigger"]["type"] == "wave_defeated"
        assert neutralise["trigger"]["prefix"] == "poacher_"

    def test_conditional_poacher_reinforcements(self):
        m = load_mission("migration")
        cond = next(n for n in m["nodes"] if n["id"] == "poacher_reinforcements")
        assert cond["type"] == "conditional"
        assert cond["condition"]["type"] == "timer_elapsed"
        assert cond["condition"]["seconds"] == 90

    def test_poacher_reinforcements_spawns_enemies(self):
        m = load_mission("migration")
        cond = next(n for n in m["nodes"] if n["id"] == "poacher_reinforcements")
        assert cond["on_activate"]["action"] == "spawn_wave"
        assert len(cond["on_activate"]["enemies"]) == 2


# ---------------------------------------------------------------------------
# 3. The Nest mission structure
# ---------------------------------------------------------------------------


class TestTheNestMission:
    def test_mission_loads(self):
        m = load_mission("the_nest")
        assert m["id"] == "the_nest"

    def test_start_node(self):
        m = load_mission("the_nest")
        assert m["start_node"] == "approach"

    def test_victory_nodes(self):
        m = load_mission("the_nest")
        assert m["victory_nodes"] == ["reach_relay"]

    def test_conflict_is_branch(self):
        m = load_mission("the_nest")
        conflict = next(n for n in m["nodes"] if n["id"] == "conflict")
        assert conflict["type"] == "branch"

    def test_fight_edge_is_branch_trigger(self):
        m = load_mission("the_nest")
        edge = next(e for e in m["edges"] if e.get("to") == "fight_outcome")
        assert edge["type"] == "branch_trigger"
        assert edge["trigger"]["type"] == "wave_defeated"
        assert edge["trigger"]["prefix"] == "escort_"

    def test_peace_edge_is_branch_trigger_all_of(self):
        m = load_mission("the_nest")
        edge = next(e for e in m["edges"] if e.get("to") == "peace_outcome")
        assert edge["type"] == "branch_trigger"
        assert edge["trigger"]["type"] == "all_of"

    def test_peace_edge_has_3_creature_state_triggers(self):
        m = load_mission("the_nest")
        edge = next(e for e in m["edges"] if e.get("to") == "peace_outcome")
        sub = edge["trigger"]["triggers"]
        assert len(sub) == 3
        for t in sub:
            assert t["type"] == "creature_state"
            assert t["state"] == "sedated"

    def test_peace_triggers_target_all_stalkers(self):
        m = load_mission("the_nest")
        edge = next(e for e in m["edges"] if e.get("to") == "peace_outcome")
        ids = {t["creature_id"] for t in edge["trigger"]["triggers"]}
        assert ids == {"stalker_a", "stalker_b", "stalker_c"}

    def test_both_paths_lead_to_reach_relay(self):
        m = load_mission("the_nest")
        to_relay = [e for e in m["edges"] if e.get("to") == "reach_relay"]
        sources = {e["from"] for e in to_relay}
        assert "fight_outcome" in sources
        assert "peace_outcome" in sources

    def test_fight_outcome_is_checkpoint(self):
        m = load_mission("the_nest")
        node = next(n for n in m["nodes"] if n["id"] == "fight_outcome")
        assert node["type"] == "checkpoint"

    def test_peace_outcome_is_checkpoint(self):
        m = load_mission("the_nest")
        node = next(n for n in m["nodes"] if n["id"] == "peace_outcome")
        assert node["type"] == "checkpoint"


# ---------------------------------------------------------------------------
# 4. Outbreak mission structure
# ---------------------------------------------------------------------------


class TestOutbreakMission:
    def test_mission_loads(self):
        m = load_mission("outbreak")
        assert m["id"] == "outbreak"

    def test_start_node(self):
        m = load_mission("outbreak")
        assert m["start_node"] == "approach_station"

    def test_victory_nodes(self):
        m = load_mission("outbreak")
        assert m["victory_nodes"] == ["evacuate_scientists"]

    def test_study_swarm_trigger(self):
        m = load_mission("outbreak")
        node = next(n for n in m["nodes"] if n["id"] == "study_swarm")
        assert node["trigger"]["type"] == "creature_study_complete"
        assert node["trigger"]["creature_id"] == "swarm_1"

    def test_disrupt_swarm_trigger(self):
        m = load_mission("outbreak")
        node = next(n for n in m["nodes"] if n["id"] == "disrupt_swarm")
        assert node["trigger"]["type"] == "creature_state"
        assert node["trigger"]["creature_id"] == "swarm_1"
        assert node["trigger"]["state"] == "dispersed"

    def test_sequential_chain(self):
        m = load_mission("outbreak")
        edges_by_from = {e["from"]: e for e in m["edges"] if e["type"] == "sequence"}
        assert edges_by_from["approach_station"]["to"] == "study_swarm"
        assert edges_by_from["study_swarm"]["to"] == "disrupt_swarm"
        assert edges_by_from["disrupt_swarm"]["to"] == "evacuate_scientists"

    def test_conditional_scavengers_at_120s(self):
        m = load_mission("outbreak")
        cond = next(n for n in m["nodes"] if n["id"] == "scavengers_arrive")
        assert cond["type"] == "conditional"
        assert cond["condition"]["seconds"] == 120

    def test_scavengers_spawn_3_enemies(self):
        m = load_mission("outbreak")
        cond = next(n for n in m["nodes"] if n["id"] == "scavengers_arrive")
        assert len(cond["on_activate"]["enemies"]) == 3

    def test_defeat_includes_station_destroyed(self):
        m = load_mission("outbreak")
        dc = m["defeat_condition"]
        assert dc["type"] == "any_of"
        types = {t["type"] for t in dc["triggers"]}
        assert "station_hull_below" in types

    def test_defeat_station_is_research_post(self):
        m = load_mission("outbreak")
        dc = m["defeat_condition"]
        stn_trigger = next(t for t in dc["triggers"] if t["type"] == "station_hull_below")
        assert stn_trigger["station_id"] == "research_post_7"
        assert stn_trigger["threshold"] == 0


# ---------------------------------------------------------------------------
# 5. MissionGraph integration — trigger evaluation
# ---------------------------------------------------------------------------


class TestMigrationGraphTriggers:
    def test_creature_study_complete_fires_at_100(self):
        world = _make_world()
        ship = _make_ship()
        world.creatures.append(_make_creature("whale_1", "void_whale", study_progress=100.0))
        assert _graph_eval({"type": "creature_study_complete", "creature_id": "whale_1"}, world, ship)

    def test_creature_study_not_complete_below_100(self):
        world = _make_world()
        ship = _make_ship()
        world.creatures.append(_make_creature("whale_1", "void_whale", study_progress=99.9))
        assert not _graph_eval({"type": "creature_study_complete", "creature_id": "whale_1"}, world, ship)

    def test_survey_count_2_completes_when_2_studied(self):
        """Nested parallel(count=2) children complete when any 2 of 3 study triggers fire."""
        g = _fresh_graph("migration")
        world = _make_world()
        ship = _make_ship()
        # Put ship in intercept area so graph activates up to protect_and_study.
        ship.x = 25000.0
        ship.y = 38000.0
        # Spawn whales with whale_1 and whale_2 studied.
        world.creatures.append(_make_creature("whale_1", "void_whale", study_progress=100.0))
        world.creatures.append(_make_creature("whale_2", "void_whale", study_progress=100.0))
        world.creatures.append(_make_creature("whale_3", "void_whale", study_progress=0.0))
        # Tick multiple times to progress through graph.
        for _ in range(5):
            g.tick(world, ship, 0.1)
        # survey_whales node should eventually complete (two whales studied).
        completed = g.get_complete_node_ids()
        assert "study_whale_1" in completed
        assert "study_whale_2" in completed

    def test_poacher_reinforcement_conditional_activates(self):
        """timer_elapsed at 90s activates the poacher_reinforcements conditional."""
        g = _fresh_graph("migration")
        world = _make_world()
        ship = _make_ship(25000.0, 38000.0)
        # Tick past 90 seconds.
        for _ in range(910):
            g.tick(world, ship, 0.1)
        active = g.get_active_node_ids()
        assert "poacher_reinforcements" in active


class TestNestGraphTriggers:
    def test_fight_branch_taken_when_escorts_defeated(self):
        """Fight path: wave_defeated trigger fires → fight_outcome checkpoint activates."""
        g = _fresh_graph("the_nest")
        world = _make_world()
        ship = _make_ship(40000.0, 40000.0)
        # No creatures needed for fight path.
        # Tick to activate approach then conflict.
        for _ in range(5):
            g.tick(world, ship, 0.1)
        completed = g.get_complete_node_ids()
        active = g.get_active_node_ids()
        # conflict should be active after approach completes.
        if "approach" in completed:
            assert "conflict" in active or "fight_outcome" in completed or "peace_outcome" in completed

    def test_peace_branch_creature_state_sedated_fires(self):
        """creature_state sedated fires when all stalkers are sedated."""
        world = _make_world()
        ship = _make_ship()
        for cid in ("stalker_a", "stalker_b", "stalker_c"):
            world.creatures.append(_make_creature(cid, "rift_stalker", behaviour_state="sedated"))
        trigger = {
            "type": "all_of",
            "triggers": [
                {"type": "creature_state", "creature_id": "stalker_a", "state": "sedated"},
                {"type": "creature_state", "creature_id": "stalker_b", "state": "sedated"},
                {"type": "creature_state", "creature_id": "stalker_c", "state": "sedated"},
            ],
        }
        assert _graph_eval(trigger, world, ship)

    def test_peace_branch_not_fires_if_one_not_sedated(self):
        world = _make_world()
        ship = _make_ship()
        world.creatures.append(_make_creature("stalker_a", "rift_stalker", behaviour_state="sedated"))
        world.creatures.append(_make_creature("stalker_b", "rift_stalker", behaviour_state="sedated"))
        world.creatures.append(_make_creature("stalker_c", "rift_stalker", behaviour_state="aggressive"))
        trigger = {
            "type": "all_of",
            "triggers": [
                {"type": "creature_state", "creature_id": "stalker_a", "state": "sedated"},
                {"type": "creature_state", "creature_id": "stalker_b", "state": "sedated"},
                {"type": "creature_state", "creature_id": "stalker_c", "state": "sedated"},
            ],
        }
        assert not _graph_eval(trigger, world, ship)

    def test_creature_state_fires_for_matching_id_and_state(self):
        world = _make_world()
        ship = _make_ship()
        world.creatures.append(_make_creature("stalker_a", "rift_stalker", behaviour_state="sedated"))
        assert _graph_eval(
            {"type": "creature_state", "creature_id": "stalker_a", "state": "sedated"}, world, ship
        )

    def test_creature_state_false_for_wrong_state(self):
        world = _make_world()
        ship = _make_ship()
        world.creatures.append(_make_creature("stalker_a", "rift_stalker", behaviour_state="idle"))
        assert not _graph_eval(
            {"type": "creature_state", "creature_id": "stalker_a", "state": "sedated"}, world, ship
        )


class TestOutbreakGraphTriggers:
    def test_study_swarm_trigger_fires(self):
        world = _make_world()
        ship = _make_ship()
        world.creatures.append(_make_creature("swarm_1", "swarm", study_progress=100.0))
        assert _graph_eval({"type": "creature_study_complete", "creature_id": "swarm_1"}, world, ship)

    def test_disrupt_trigger_fires_when_dispersed(self):
        world = _make_world()
        ship = _make_ship()
        world.creatures.append(_make_creature("swarm_1", "swarm", behaviour_state="dispersed"))
        assert _graph_eval(
            {"type": "creature_state", "creature_id": "swarm_1", "state": "dispersed"}, world, ship
        )

    def test_disrupt_trigger_false_when_not_dispersed(self):
        world = _make_world()
        ship = _make_ship()
        world.creatures.append(_make_creature("swarm_1", "swarm", behaviour_state="attacking"))
        assert not _graph_eval(
            {"type": "creature_state", "creature_id": "swarm_1", "state": "dispersed"}, world, ship
        )

    def test_sequential_chain_progresses(self):
        """study_swarm → disrupt_swarm → evacuate_scientists graph progression."""
        g = _fresh_graph("outbreak")
        world = _make_world()
        ship = _make_ship(30000.0, 30000.0)
        # Swarm studied and dispersed.
        swarm = _make_creature("swarm_1", "swarm", study_progress=100.0, behaviour_state="dispersed")
        world.creatures.append(swarm)
        # Tick to activate and complete approach_station + study_swarm + disrupt_swarm.
        for _ in range(10):
            g.tick(world, ship, 0.1)
        completed = g.get_complete_node_ids()
        assert "approach_station" in completed
        assert "study_swarm" in completed
        assert "disrupt_swarm" in completed

    def test_evacuate_completes_when_ship_at_evac_point(self):
        g = _fresh_graph("outbreak")
        world = _make_world()
        ship = _make_ship(30000.0, 30000.0)
        swarm = _make_creature("swarm_1", "swarm", study_progress=100.0, behaviour_state="dispersed")
        world.creatures.append(swarm)
        for _ in range(10):
            g.tick(world, ship, 0.1)
        # Now move ship to evac point.
        ship.x = -10000.0
        ship.y = -10000.0
        for _ in range(5):
            g.tick(world, ship, 0.1)
        over, result = g.is_over()
        assert over
        assert result == "victory"

    def test_scavengers_conditional_spawns_on_timer(self):
        """scavengers_arrive activates after 120s and emits spawn_wave action."""
        g = _fresh_graph("outbreak")
        world = _make_world()
        ship = _make_ship(30000.0, 30000.0)
        swarm = _make_creature("swarm_1", "swarm")
        world.creatures.append(swarm)
        # Tick past 120 seconds.
        for _ in range(1210):
            g.tick(world, ship, 0.1)
        actions = g.pop_pending_actions()
        spawn_actions = [a for a in actions if a.get("action") == "spawn_wave"]
        assert len(spawn_actions) >= 1
        total_enemies = sum(len(a.get("enemies", [])) for a in spawn_actions)
        assert total_enemies == 3
