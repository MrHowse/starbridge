"""
v0.05j — Station Assault Missions.

Tests cover:
  - Five new MissionGraph trigger types: station_destroyed, station_captured,
    component_destroyed, station_sensor_jammed, station_reinforcements_called
  - Conditional max_activations (one-shot guard)
  - notify_station_captured() API
  - serialise/deserialise_state roundtrip for new state fields
  - spawn_from_mission with "enemy_station" type
  - Fortress mission: branch structure, stealth vs assault path selection
  - Supply Line mission: parallel structure, wave conditionals, reinforcement conditional
"""
from __future__ import annotations

import pytest

from server.mission_graph import MissionGraph
from server.missions.loader import load_mission, spawn_from_mission
from server.models.world import (
    Enemy,
    EnemyStationDefenses,
    FighterBay,
    SensorArray,
    ShieldArc,
    Ship,
    Station,
    StationReactor,
    Turret,
    World,
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


def _make_station_with_defenses(
    station_id: str,
    x: float = 50000.0,
    y: float = 50000.0,
    hull: float = 800.0,
) -> Station:
    """Create a minimal hostile station with one shield arc and sensor array."""
    return Station(
        id=station_id,
        x=x,
        y=y,
        faction="hostile",
        hull=hull,
        hull_max=800.0,
        defenses=EnemyStationDefenses(
            shield_arcs=[ShieldArc(id=f"{station_id}_gen_0", hp=80.0, hp_max=80.0)],
            turrets=[],
            launchers=[],
            fighter_bays=[],
            sensor_array=SensorArray(id=f"{station_id}_sensor", hp=50.0, hp_max=50.0),
            reactor=StationReactor(id=f"{station_id}_reactor", hp=100.0, hp_max=100.0),
        ),
    )


def _graph_from_dict(nodes: list, edges: list, start: str, **kwargs) -> MissionGraph:
    """Build a minimal MissionGraph from explicit nodes/edges."""
    mission = {
        "nodes": nodes,
        "edges": edges,
        "start_node": start,
        "victory_nodes": kwargs.get("victory_nodes", []),
        "defeat_condition": kwargs.get("defeat_condition"),
    }
    return MissionGraph(mission)


# ---------------------------------------------------------------------------
# 1. New trigger types
# ---------------------------------------------------------------------------


class TestStationDestroyedTrigger:
    def test_fires_when_station_absent(self):
        """station_destroyed → True when station not in world.stations."""
        world = _make_world()
        ship = _make_ship()
        g = _graph_from_dict(
            nodes=[{
                "id": "obj", "type": "objective", "text": "",
                "trigger": {"type": "station_destroyed", "station_id": "tgt"},
            }],
            edges=[],
            start="obj",
        )
        # No station in world — trigger fires.
        assert g._eval_trigger(
            {"type": "station_destroyed", "station_id": "tgt"}, world, ship, "obj"
        )

    def test_fires_when_hull_zero(self):
        """station_destroyed → True when station hull == 0."""
        world = _make_world()
        ship = _make_ship()
        station = _make_station_with_defenses("tgt", hull=0.0)
        world.stations.append(station)
        assert g_eval(world, ship, {"type": "station_destroyed", "station_id": "tgt"})

    def test_false_when_alive(self):
        """station_destroyed → False when station hull > 0."""
        world = _make_world()
        ship = _make_ship()
        world.stations.append(_make_station_with_defenses("tgt"))
        assert not g_eval(world, ship, {"type": "station_destroyed", "station_id": "tgt"})


def g_eval(world: World, ship: Ship, trigger_def: dict) -> bool:
    """Convenience: eval a trigger on a fresh graph."""
    g = MissionGraph({"nodes": [], "edges": [], "start_node": None, "victory_nodes": []})
    return g._eval_trigger(trigger_def, world, ship, "")


class TestStationCapturedTrigger:
    def test_false_before_notification(self):
        world, ship = _make_world(), _make_ship()
        assert not g_eval(world, ship, {"type": "station_captured", "station_id": "stn"})

    def test_true_after_notify(self):
        world, ship = _make_world(), _make_ship()
        g = MissionGraph({"nodes": [], "edges": [], "start_node": None, "victory_nodes": []})
        g.notify_station_captured("stn")
        assert g._eval_trigger({"type": "station_captured", "station_id": "stn"}, world, ship, "")

    def test_only_affects_named_station(self):
        world, ship = _make_world(), _make_ship()
        g = MissionGraph({"nodes": [], "edges": [], "start_node": None, "victory_nodes": []})
        g.notify_station_captured("stn_a")
        assert not g._eval_trigger(
            {"type": "station_captured", "station_id": "stn_b"}, world, ship, ""
        )


class TestComponentDestroyedTrigger:
    def test_false_when_component_alive(self):
        world, ship = _make_world(), _make_ship()
        stn = _make_station_with_defenses("stn")
        world.stations.append(stn)
        # gen_0 is alive (hp=80)
        assert not g_eval(world, ship, {"type": "component_destroyed", "component_id": "stn_gen_0"})

    def test_true_when_component_hp_zero(self):
        world, ship = _make_world(), _make_ship()
        stn = _make_station_with_defenses("stn")
        stn.defenses.shield_arcs[0].hp = 0.0
        world.stations.append(stn)
        assert g_eval(world, ship, {"type": "component_destroyed", "component_id": "stn_gen_0"})

    def test_true_when_station_gone(self):
        """If station is removed (destroyed), component is also gone → True."""
        world, ship = _make_world(), _make_ship()
        # Station not in world → component "stn_gen_0" not found → returns True
        assert g_eval(world, ship, {"type": "component_destroyed", "component_id": "stn_gen_0"})


class TestStationSensorJammedTrigger:
    def test_false_when_not_jammed(self):
        world, ship = _make_world(), _make_ship()
        stn = _make_station_with_defenses("stn")
        world.stations.append(stn)
        assert not g_eval(world, ship, {"type": "station_sensor_jammed", "station_id": "stn"})

    def test_true_when_jammed(self):
        world, ship = _make_world(), _make_ship()
        stn = _make_station_with_defenses("stn")
        stn.defenses.sensor_array.jammed = True
        world.stations.append(stn)
        assert g_eval(world, ship, {"type": "station_sensor_jammed", "station_id": "stn"})

    def test_false_when_station_absent(self):
        world, ship = _make_world(), _make_ship()
        assert not g_eval(world, ship, {"type": "station_sensor_jammed", "station_id": "missing"})


class TestReinforcementsCalledTrigger:
    def test_false_when_not_sent(self):
        world, ship = _make_world(), _make_ship()
        stn = _make_station_with_defenses("stn")
        world.stations.append(stn)
        assert not g_eval(
            world, ship, {"type": "station_reinforcements_called", "station_id": "stn"}
        )

    def test_true_when_distress_sent(self):
        world, ship = _make_world(), _make_ship()
        stn = _make_station_with_defenses("stn")
        stn.defenses.sensor_array.distress_sent = True
        world.stations.append(stn)
        assert g_eval(
            world, ship, {"type": "station_reinforcements_called", "station_id": "stn"}
        )

    def test_false_when_station_absent(self):
        world, ship = _make_world(), _make_ship()
        assert not g_eval(
            world, ship, {"type": "station_reinforcements_called", "station_id": "gone"}
        )


# ---------------------------------------------------------------------------
# 2. max_activations (one-shot conditional)
# ---------------------------------------------------------------------------


class TestMaxActivations:
    def _make_graph(self, max_act: int) -> MissionGraph:
        return MissionGraph({
            "nodes": [
                {
                    "id": "cond",
                    "type": "conditional",
                    "text": "test cond",
                    "max_activations": max_act,
                    "condition": {"type": "all_enemies_destroyed"},
                    "on_activate": {"action": "spawn_wave", "enemies": []},
                    "deactivate_when": {"type": "timer_elapsed", "seconds": 999},
                }
            ],
            "edges": [],
            "start_node": None,
            "victory_nodes": [],
        })

    def test_one_shot_fires_once(self):
        """max_activations=1: conditional activates once and stays inactive afterwards."""
        g = self._make_graph(max_act=1)
        world = _make_world()
        ship = _make_ship()
        # No enemies → condition true immediately.
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["cond"].status == "active"
        assert g._conditional_activation_count.get("cond", 0) == 1

        # Manually deactivate (as deactivate_when would — simulate timer not yet elapsed)
        g._graph_nodes["cond"].status = "pending"
        g._active_set.discard("cond")

        # Should not re-activate — already used its one activation.
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["cond"].status == "pending"
        assert g._conditional_activation_count.get("cond", 0) == 1

    def test_unlimited_fires_multiple_times(self):
        """max_activations=0 (unlimited): conditional can re-activate."""
        g = self._make_graph(max_act=0)
        world = _make_world()
        ship = _make_ship()

        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["cond"].status == "active"
        count_after_first = g._conditional_activation_count.get("cond", 0)
        assert count_after_first == 1

        # Reset manually
        g._graph_nodes["cond"].status = "pending"
        g._active_set.discard("cond")

        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["cond"].status == "active"
        assert g._conditional_activation_count.get("cond", 0) == 2

    def test_serialise_preserves_activation_count(self):
        """Activation count survives serialise/deserialise."""
        g = self._make_graph(max_act=1)
        world, ship = _make_world(), _make_ship()
        g.tick(world, ship, dt=0.1)

        state = g.serialise_state()
        assert "conditional_activation_count" in state
        assert state["conditional_activation_count"].get("cond", 0) == 1

        g2 = self._make_graph(max_act=1)
        g2.deserialise_state(state)
        assert g2._conditional_activation_count.get("cond", 0) == 1
        # After restore, still one-shot exhausted.
        g2._graph_nodes["cond"].status = "pending"
        g2._active_set.discard("cond")
        g2.tick(world, ship, dt=0.1)
        assert g2._graph_nodes["cond"].status == "pending"


# ---------------------------------------------------------------------------
# 3. notify_station_captured and serialise/deserialise
# ---------------------------------------------------------------------------


class TestNotifyStationCaptured:
    def test_notify_sets_internal_state(self):
        g = MissionGraph({"nodes": [], "edges": [], "start_node": None, "victory_nodes": []})
        assert "alpha" not in g._captured_station_ids
        g.notify_station_captured("alpha")
        assert "alpha" in g._captured_station_ids

    def test_serialise_includes_captured_ids(self):
        g = MissionGraph({"nodes": [], "edges": [], "start_node": None, "victory_nodes": []})
        g.notify_station_captured("stn1")
        state = g.serialise_state()
        assert "stn1" in state["captured_station_ids"]

    def test_deserialise_restores_captured_ids(self):
        g = MissionGraph({"nodes": [], "edges": [], "start_node": None, "victory_nodes": []})
        g.notify_station_captured("stn1")
        state = g.serialise_state()

        g2 = MissionGraph({"nodes": [], "edges": [], "start_node": None, "victory_nodes": []})
        g2.deserialise_state(state)
        assert "stn1" in g2._captured_station_ids


# ---------------------------------------------------------------------------
# 4. spawn_from_mission — enemy_station type
# ---------------------------------------------------------------------------


class TestSpawnEnemyStation:
    def test_spawn_from_mission_creates_hostile_station(self):
        mission = {
            "spawn": [
                {"type": "enemy_station", "id": "base1", "x": 50000, "y": 50000, "variant": "outpost"}
            ],
            "nodes": [], "edges": [], "start_node": None, "victory_nodes": [],
        }
        world = World()
        spawn_from_mission(mission, world, 0)
        assert len(world.stations) == 1
        stn = world.stations[0]
        assert stn.id == "base1"
        assert stn.faction == "hostile"
        assert stn.defenses is not None

    def test_spawn_enemy_station_default_outpost(self):
        """enemy_station with no variant defaults to outpost."""
        mission = {
            "spawn": [
                {"type": "enemy_station", "id": "base2", "x": 40000, "y": 40000}
            ],
            "nodes": [], "edges": [], "start_node": None, "victory_nodes": [],
        }
        world = World()
        spawn_from_mission(mission, world, 0)
        stn = world.stations[0]
        assert stn.defenses is not None
        assert len(stn.defenses.shield_arcs) == 2  # outpost has 2

    def test_spawn_enemy_station_fortress_variant(self):
        """enemy_station with variant=fortress creates fortress."""
        mission = {
            "spawn": [
                {"type": "enemy_station", "id": "fort1", "x": 60000, "y": 60000, "variant": "fortress"}
            ],
            "nodes": [], "edges": [], "start_node": None, "victory_nodes": [],
        }
        world = World()
        spawn_from_mission(mission, world, 0)
        stn = world.stations[0]
        assert len(stn.defenses.shield_arcs) == 4  # fortress has 4

    def test_mixed_spawn_friendly_and_hostile(self):
        """Friendly (type:station) and hostile (type:enemy_station) can coexist."""
        mission = {
            "spawn": [
                {"type": "station", "id": "friendly1", "x": 10000, "y": 10000},
                {"type": "enemy_station", "id": "enemy1", "x": 60000, "y": 60000, "variant": "outpost"},
            ],
            "nodes": [], "edges": [], "start_node": None, "victory_nodes": [],
        }
        world = World()
        spawn_from_mission(mission, world, 0)
        assert len(world.stations) == 2
        ids = {s.id for s in world.stations}
        assert "friendly1" in ids and "enemy1" in ids

    def test_spawn_also_creates_regular_enemies(self):
        """Regular enemy entries still work alongside enemy_station entries."""
        mission = {
            "spawn": [
                {"type": "enemy_station", "id": "dep1", "x": 50000, "y": 50000, "variant": "outpost"},
                {"type": "scout", "id": "patrol_1", "x": 45000, "y": 45000},
            ],
            "nodes": [], "edges": [], "start_node": None, "victory_nodes": [],
        }
        world = World()
        spawn_from_mission(mission, world, 0)
        assert len(world.stations) == 1
        assert len(world.enemies) == 1


# ---------------------------------------------------------------------------
# 5. Fortress mission
# ---------------------------------------------------------------------------


class TestFortressMissionLoads:
    def test_load_fortress(self):
        m = load_mission("fortress")
        assert m["id"] == "fortress"
        assert m["start_node"] == "approach"
        assert "capture_station" in m["victory_nodes"]

    def test_fortress_spawns_station_and_patrols(self):
        m = load_mission("fortress")
        world = World()
        spawn_from_mission(m, world, 0)
        assert len(world.stations) == 1
        assert world.stations[0].id == "cygnus_base"
        assert world.stations[0].faction == "hostile"
        assert len(world.enemies) == 2  # patrol_a + patrol_b

    def test_fortress_graph_has_branch(self):
        m = load_mission("fortress")
        g = MissionGraph(m)
        assert "choose_approach" in g._all_nodes
        assert g._all_nodes["choose_approach"]["type"] == "branch"

    def test_fortress_reinforcements_conditional_exists(self):
        m = load_mission("fortress")
        g = MissionGraph(m)
        assert "reinforcements_conditional" in g._conditional_ids

    def test_fortress_max_activations_on_reinforcements(self):
        m = load_mission("fortress")
        g = MissionGraph(m)
        node = g._all_nodes["reinforcements_conditional"]
        assert node.get("max_activations", 0) == 1


class TestFortressStealthBranch:
    def _setup(self):
        m = load_mission("fortress")
        world = World()
        spawn_from_mission(m, world, 0)
        g = MissionGraph(m)
        ship = _make_ship(x=50000, y=50000)
        return g, world, ship

    def test_branch_inactive_before_approach(self):
        g, world, ship = self._setup()
        # Ship far from station
        ship.x, ship.y = 5000, 50000
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["approach"].status == "active"
        assert g._graph_nodes["choose_approach"].status == "pending"

    def test_approach_completes_within_range(self):
        g, world, ship = self._setup()
        # Within 30000 of (50000, 50000)
        ship.x, ship.y = 50000, 50000
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["approach"].status == "complete"
        assert g._graph_nodes["choose_approach"].status == "active"

    def test_stealth_branch_fires_on_sensor_jammed(self):
        """Stealth branch_trigger fires when sensor is jammed."""
        g, world, ship = self._setup()
        # Advance to branch
        ship.x, ship.y = 50000, 50000
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["choose_approach"].status == "active"

        # Jam sensor
        world.stations[0].defenses.sensor_array.jammed = True
        g.tick(world, ship, dt=0.1)

        assert g._graph_nodes["choose_approach"].status == "complete"
        assert g._graph_nodes["stealth_close"].status == "active"
        assert g._graph_nodes["assault_gen1"].status == "pending"

    def test_assault_branch_fires_on_component_destroyed(self):
        """Assault branch_trigger fires when gen_0 is destroyed."""
        g, world, ship = self._setup()
        ship.x, ship.y = 50000, 50000
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["choose_approach"].status == "active"

        # Destroy gen_0
        world.stations[0].defenses.shield_arcs[0].hp = 0.0
        g.tick(world, ship, dt=0.1)

        assert g._graph_nodes["choose_approach"].status == "complete"
        assert g._graph_nodes["assault_gen1"].status == "active"
        assert g._graph_nodes["stealth_close"].status == "pending"

    def test_stealth_path_leads_to_capture(self):
        """stealth_close → capture_station sequence."""
        g, world, ship = self._setup()
        # Activate branch
        ship.x, ship.y = 50000, 50000
        g.tick(world, ship, dt=0.1)
        world.stations[0].defenses.sensor_array.jammed = True
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["stealth_close"].status == "active"

        # Close to docking range (r=2500, station at 50000,50000)
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["stealth_close"].status == "complete"
        assert g._graph_nodes["capture_station"].status == "active"

    def test_capture_station_fires_on_notify(self):
        """station_captured trigger fires after notify_station_captured."""
        g, world, ship = self._setup()
        # Fast-track to capture_station
        ship.x, ship.y = 50000, 50000
        g.tick(world, ship, dt=0.1)
        world.stations[0].defenses.sensor_array.jammed = True
        g.tick(world, ship, dt=0.1)
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["capture_station"].status == "active"

        g.notify_station_captured("cygnus_base")
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["capture_station"].status == "complete"
        over, result = g.is_over()
        assert over and result == "victory"

    def test_assault_path_full_sequence(self):
        """Full assault path: gen0 destroyed → gen1 → hull < 50% → dock → capture."""
        g, world, ship = self._setup()
        stn = world.stations[0]
        ship.x, ship.y = 50000, 50000

        # Advance to branch
        g.tick(world, ship, dt=0.1)
        # Trigger assault branch: destroy gen_0
        stn.defenses.shield_arcs[0].hp = 0.0
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["assault_gen1"].status == "active"

        # Destroy gen_1 (outpost has 2 gens: index 0 and 1)
        stn.defenses.shield_arcs[1].hp = 0.0
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["assault_gen1"].status == "complete"
        assert g._graph_nodes["assault_weaken"].status == "active"

        # Reduce hull below 400 (50% of 800)
        stn.hull = 399.0
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["assault_weaken"].status == "complete"
        assert g._graph_nodes["assault_dock"].status == "active"

        # Close to 2500 (ship already at station coords)
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["assault_dock"].status == "complete"
        assert g._graph_nodes["capture_station"].status == "active"

    def test_reinforcement_conditional_fires(self):
        """Reinforcements spawn when sensor array calls distress."""
        g, world, ship = self._setup()
        stn = world.stations[0]
        ship.x, ship.y = 50000, 50000

        # Enable distress
        stn.defenses.sensor_array.distress_sent = True
        g.tick(world, ship, dt=0.1)

        # Conditional should be active and spawn_wave action queued
        actions = g.pop_pending_actions()
        spawn_actions = [a for a in actions if a.get("action") == "spawn_wave"]
        assert len(spawn_actions) == 1
        assert len(spawn_actions[0]["enemies"]) == 2


# ---------------------------------------------------------------------------
# 6. Supply Line mission
# ---------------------------------------------------------------------------


class TestSupplyLineMissionLoads:
    def test_load_supply_line(self):
        m = load_mission("supply_line")
        assert m["id"] == "supply_line"
        assert m["start_node"] == "start"
        assert "extract" in m["victory_nodes"]

    def test_supply_line_spawns_depot_and_supplies(self):
        m = load_mission("supply_line")
        world = World()
        spawn_from_mission(m, world, 0)
        assert len(world.stations) == 1
        assert world.stations[0].id == "depot_alpha"
        assert world.stations[0].faction == "hostile"
        # Initial supply ships
        assert len(world.enemies) == 2

    def test_supply_line_has_parallel_node(self):
        m = load_mission("supply_line")
        g = MissionGraph(m)
        assert g._all_nodes["main_ops"]["type"] == "parallel"
        assert g._all_nodes["main_ops"]["complete_when"] == "all"

    def test_supply_line_conditionals_have_max_activations(self):
        m = load_mission("supply_line")
        g = MissionGraph(m)
        for cid in ["resupply_wave_1", "resupply_wave_2", "reinforcements_conditional"]:
            assert g._all_nodes[cid].get("max_activations") == 1


class TestSupplyLineParallelObjectives:
    def _setup(self):
        m = load_mission("supply_line")
        world = World()
        spawn_from_mission(m, world, 0)
        g = MissionGraph(m)
        ship = _make_ship(x=50000, y=50000)
        return g, world, ship

    def test_start_activates_main_ops(self):
        """Checkpoint 'start' immediately completes and activates main_ops."""
        g, world, ship = self._setup()
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["start"].status == "complete"
        assert g._graph_nodes["main_ops"].status == "active"
        assert g._graph_nodes["destroy_depot"].status == "active"
        assert g._graph_nodes["intercept_all"].status == "active"

    def test_destroy_depot_fires_on_station_destroyed(self):
        g, world, ship = self._setup()
        g.tick(world, ship, dt=0.1)
        # Destroy depot
        world.stations[0].hull = 0.0
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["destroy_depot"].status == "complete"

    def test_intercept_all_fires_when_all_supply_enemies_gone(self):
        g, world, ship = self._setup()
        g.tick(world, ship, dt=0.1)
        # Remove all supply_ enemies
        world.enemies = []
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["intercept_all"].status == "complete"

    def test_main_ops_requires_both_objectives(self):
        g, world, ship = self._setup()
        g.tick(world, ship, dt=0.1)

        # Only one objective complete
        world.enemies = []
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["intercept_all"].status == "complete"
        assert g._graph_nodes["main_ops"].status == "active"  # still waiting for depot

    def test_extract_activates_after_both_objectives(self):
        g, world, ship = self._setup()
        g.tick(world, ship, dt=0.1)
        world.enemies = []
        world.stations[0].hull = 0.0
        g.tick(world, ship, dt=0.1)
        assert g._graph_nodes["main_ops"].status == "complete"
        assert g._graph_nodes["extract"].status == "active"

    def test_extract_completes_for_victory(self):
        g, world, ship = self._setup()
        g.tick(world, ship, dt=0.1)
        world.enemies = []
        world.stations[0].hull = 0.0
        g.tick(world, ship, dt=0.1)
        # Move ship to extraction point (x=5000, y=50000, r=8000)
        ship.x, ship.y = 5000, 50000
        g.tick(world, ship, dt=0.1)
        over, result = g.is_over()
        assert over and result == "victory"


class TestSupplyLineWaveConditionals:
    def _setup(self):
        m = load_mission("supply_line")
        world = World()
        spawn_from_mission(m, world, 0)
        g = MissionGraph(m)
        ship = _make_ship(x=50000, y=50000)
        g.tick(world, ship, dt=0.1)  # advance past start checkpoint
        g.pop_pending_actions()
        return g, world, ship

    def test_wave_1_spawns_at_t60(self):
        """resupply_wave_1 activates at t=60 and queues a spawn_wave action."""
        g, world, ship = self._setup()
        # Tick up to just past 60 seconds total elapsed
        ticks_needed = int(60.0 / 0.1) + 2
        for _ in range(ticks_needed):
            g.tick(world, ship, dt=0.1)

        actions = g.pop_pending_actions()
        spawns = [a for a in actions if a.get("action") == "spawn_wave"]
        assert any(
            any(e["id"].startswith("supply_w1") for e in s["enemies"])
            for s in spawns
        ), "Wave 1 supply enemies not found in spawn actions"

    def test_wave_1_fires_only_once(self):
        """max_activations=1 ensures wave_1 spawns exactly once."""
        g, world, ship = self._setup()
        ticks = int(60.0 / 0.1) + 5
        for _ in range(ticks):
            g.tick(world, ship, dt=0.1)

        _ = g.pop_pending_actions()  # clear first batch

        # More ticks — wave should NOT fire again
        for _ in range(100):
            g.tick(world, ship, dt=0.1)

        actions = g.pop_pending_actions()
        w1_spawns = [
            a for a in actions
            if a.get("action") == "spawn_wave"
            and any(e["id"].startswith("supply_w1") for e in a["enemies"])
        ]
        assert len(w1_spawns) == 0

    def test_wave_2_spawns_at_t120(self):
        """resupply_wave_2 activates at t=120."""
        g, world, ship = self._setup()
        ticks_needed = int(120.0 / 0.1) + 2
        for _ in range(ticks_needed):
            g.tick(world, ship, dt=0.1)

        actions = g.pop_pending_actions()
        spawns = [a for a in actions if a.get("action") == "spawn_wave"]
        assert any(
            any(e["id"].startswith("supply_w2") for e in s["enemies"])
            for s in spawns
        )

    def test_wave_does_not_fire_after_depot_destroyed(self):
        """Waves don't spawn after depot is destroyed (condition guards depot alive)."""
        g, world, ship = self._setup()
        # Simulate depot destroyed and removed (as game_loop.py does)
        world.stations.clear()
        # Tick past t=60 — condition includes none_of(station_destroyed) so it stays False
        ticks = int(65.0 / 0.1) + 2
        for _ in range(ticks):
            g.tick(world, ship, dt=0.1)

        actions = g.pop_pending_actions()
        supply_wave_actions = [
            a for a in actions
            if a.get("action") == "spawn_wave"
            and any(e["id"].startswith("supply_w1") for e in a.get("enemies", []))
        ]
        assert len(supply_wave_actions) == 0

    def test_reinforcements_fire_when_distress_sent(self):
        """Reinforcements conditional fires when depot distress_sent=True."""
        g, world, ship = self._setup()
        world.stations[0].defenses.sensor_array.distress_sent = True
        g.tick(world, ship, dt=0.1)

        actions = g.pop_pending_actions()
        reinf = [a for a in actions if a.get("action") == "spawn_wave"
                 and any(e["id"].startswith("depot_reinf") for e in a.get("enemies", []))]
        assert len(reinf) == 1
        assert len(reinf[0]["enemies"]) == 3


# ---------------------------------------------------------------------------
# 7. Station.captured field and world model
# ---------------------------------------------------------------------------


class TestStationCapturedField:
    def test_station_captured_defaults_false(self):
        stn = Station(id="s1", x=0, y=0)
        assert stn.captured is False

    def test_spawn_enemy_station_captured_false(self):
        stn = spawn_enemy_station("s2", 50000, 50000)
        assert stn.captured is False

    def test_can_set_captured_true(self):
        stn = Station(id="s3", x=0, y=0)
        stn.captured = True
        assert stn.captured is True
