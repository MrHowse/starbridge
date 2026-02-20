"""Tests for v0.04c — New Graph-Native Missions.

Covers four new missions that showcase MissionGraph capabilities:
  salvage_run            — 3-way branch (science vs comms vs timer)
  first_contact_remastered — 3-way branch (scan vs destroy vs flee)
  the_convoy             — parallel (count=2 of 3 attack groups)
  pandemic               — 3-way branch + two parallel outcome paths
"""
from __future__ import annotations

import pytest

from server.mission_graph import MissionGraph
from server.missions.loader import load_mission
from server.models.ship import Ship
from server.models.world import World, spawn_enemy, spawn_station


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_world_ship() -> tuple[World, Ship]:
    ship = Ship()
    ship.x = 50_000.0
    ship.y = 50_000.0
    ship.hull = 100.0
    world = World(ship=ship, width=100_000.0, height=100_000.0)
    return world, ship


def make_graph(mission_id: str) -> tuple[MissionGraph, World, Ship]:
    mission = load_mission(mission_id)
    world, ship = make_world_ship()
    graph = MissionGraph(mission)
    return graph, world, ship


def _all_nodes_flat(mission: dict) -> list[dict]:
    """Recursively collect all nodes including parallel children."""
    result: list[dict] = []

    def _collect(nodes: list[dict]) -> None:
        for node in nodes:
            result.append(node)
            _collect(node.get("children", []))

    _collect(mission.get("nodes", []))
    return result


def _node_ids_of_type(mission: dict, ntype: str) -> list[str]:
    return [n["id"] for n in _all_nodes_flat(mission) if n.get("type") == ntype]


# ---------------------------------------------------------------------------
# TestSalvageRunLoad — structure
# ---------------------------------------------------------------------------


class TestSalvageRunLoad:
    @pytest.fixture(autouse=True)
    def mission(self):
        self.m = load_mission("salvage_run")

    def test_loads(self):
        assert self.m["id"] == "salvage_run"

    def test_has_nodes(self):
        assert len(self.m["nodes"]) > 0

    def test_has_edges(self):
        assert len(self.m["edges"]) > 0

    def test_has_start_node(self):
        assert self.m["start_node"] == "navigate_to_site"

    def test_has_victory_nodes(self):
        assert "return_to_base" in self.m["victory_nodes"]

    def test_defeat_condition_hull_zero(self):
        assert self.m["defeat_condition"]["type"] == "player_hull_zero"

    def test_has_branch_node(self):
        assert "survey_branch" in _node_ids_of_type(self.m, "branch")

    def test_has_parallel_node(self):
        assert "survivors_found" in _node_ids_of_type(self.m, "parallel")

    def test_parallel_has_two_children(self):
        survivors = next(n for n in _all_nodes_flat(self.m) if n["id"] == "survivors_found")
        assert len(survivors["children"]) == 2

    def test_has_conditional_node(self):
        assert "hull_emergency" in _node_ids_of_type(self.m, "conditional")

    def test_three_branch_trigger_edges(self):
        bt_edges = [e for e in self.m["edges"] if e.get("type") == "branch_trigger"]
        assert len(bt_edges) == 3

    def test_all_branch_paths_reach_victory(self):
        # Each branch target must eventually reach return_to_base via edges
        bt_targets = {e["to"] for e in self.m["edges"] if e.get("type") == "branch_trigger"}
        all_edge_froms = {e["from"] for e in self.m["edges"]}
        # Each branch target should be a "from" in at least one edge (leading to victory)
        for target in bt_targets:
            # Either is directly return_to_base, or has an outgoing edge
            assert target in all_edge_froms or target == "return_to_base"


# ---------------------------------------------------------------------------
# TestSalvageRunBranches — simulation
# ---------------------------------------------------------------------------


class TestSalvageRunBranches:
    def _reach_survey_branch(self, graph: MissionGraph, world: World, ship: Ship) -> None:
        """Drive the graph to survey_branch activation."""
        ship.x = 25_000.0
        ship.y = 30_000.0
        # navigate_to_site completes (player_in_area)
        graph.tick(world, ship, dt=0.1)
        # survey_branch now active

    def test_science_branch_reaches_trap_discovered(self):
        graph, world, ship = make_graph("salvage_run")
        self._reach_survey_branch(graph, world, ship)
        # Resolve sensor_analysis → trap_discovered branch fires
        graph.notify_puzzle_result("sensor_analysis", True)
        completed = graph.tick(world, ship, dt=0.1)
        assert "survey_branch" in completed
        assert graph._graph_nodes["trap_discovered"].status == "active"
        assert graph._graph_nodes["survivors_found"].status == "pending"
        assert graph._graph_nodes["ambush_sprung"].status == "pending"

    def test_comms_branch_reaches_survivors_found(self):
        graph, world, ship = make_graph("salvage_run")
        self._reach_survey_branch(graph, world, ship)
        graph.notify_puzzle_result("decode_distress", True)
        completed = graph.tick(world, ship, dt=0.1)
        assert "survey_branch" in completed
        assert graph._graph_nodes["survivors_found"].status == "active"
        assert graph._graph_nodes["trap_discovered"].status == "pending"

    def test_timer_branch_reaches_ambush_sprung(self):
        graph, world, ship = make_graph("salvage_run")
        self._reach_survey_branch(graph, world, ship)
        # Advance past 90-second threshold
        graph.tick(world, ship, dt=90.0)
        assert graph._graph_nodes["ambush_sprung"].status == "active"
        assert graph._graph_nodes["trap_discovered"].status == "pending"
        assert graph._graph_nodes["survivors_found"].status == "pending"

    def test_combat_path_leads_to_victory(self):
        graph, world, ship = make_graph("salvage_run")
        self._reach_survey_branch(graph, world, ship)
        graph.notify_puzzle_result("sensor_analysis", True)
        graph.tick(world, ship, dt=0.1)  # trap_discovered activates
        # No enemies → trap_discovered fires all_enemies_destroyed
        completed = graph.tick(world, ship, dt=0.1)
        assert "trap_discovered" in completed
        # return_to_base now active — move ship there
        ship.x = 85_000.0
        ship.y = 50_000.0
        graph.tick(world, ship, dt=0.1)
        over, result = graph.is_over()
        assert over is True
        assert result == "victory"

    def test_ambush_path_leads_to_victory(self):
        graph, world, ship = make_graph("salvage_run")
        self._reach_survey_branch(graph, world, ship)
        graph.tick(world, ship, dt=90.0)  # timer fires → ambush_sprung activates
        ship.x = 70_000.0
        ship.y = 65_000.0
        graph.tick(world, ship, dt=0.1)  # ambush_sprung fires player_in_area
        ship.x = 85_000.0
        ship.y = 50_000.0
        graph.tick(world, ship, dt=0.1)  # return_to_base fires
        over, result = graph.is_over()
        assert over is True
        assert result == "victory"

    def test_hull_emergency_conditional_activates(self):
        graph, world, ship = make_graph("salvage_run")
        ship.hull = 25.0
        graph.tick(world, ship, dt=0.1)
        assert graph._graph_nodes["hull_emergency"].status == "active"
        # hull_emergency on_activate queues a start_puzzle action
        actions = graph.pop_pending_actions()
        puzzle_actions = [a for a in actions if a.get("action") == "start_puzzle"]
        assert any(a["label"] == "emergency_repair" for a in puzzle_actions)

    def test_hull_emergency_deactivates_on_recovery(self):
        graph, world, ship = make_graph("salvage_run")
        ship.hull = 25.0
        graph.tick(world, ship, dt=0.1)
        assert graph._graph_nodes["hull_emergency"].status == "active"
        graph.pop_pending_actions()  # consume on_activate action
        ship.hull = 55.0  # above deactivate threshold (50)
        graph.tick(world, ship, dt=0.1)
        assert graph._graph_nodes["hull_emergency"].status == "pending"


# ---------------------------------------------------------------------------
# TestFirstContactRemasteredLoad
# ---------------------------------------------------------------------------


class TestFirstContactRemasteredLoad:
    @pytest.fixture(autouse=True)
    def mission(self):
        self.m = load_mission("first_contact_remastered")

    def test_loads(self):
        assert self.m["id"] == "first_contact_remastered"

    def test_has_start_node(self):
        assert self.m["start_node"] == "patrol_sector"

    def test_victory_node_is_return_to_command(self):
        assert "return_to_command" in self.m["victory_nodes"]

    def test_has_branch_node(self):
        assert "response_branch" in _node_ids_of_type(self.m, "branch")

    def test_parallel_complete_when_any(self):
        diplomatic = next(n for n in _all_nodes_flat(self.m) if n["id"] == "diplomatic_path")
        assert diplomatic["complete_when"] == "any"

    def test_three_branch_trigger_edges(self):
        bt_edges = [e for e in self.m["edges"] if e.get("type") == "branch_trigger"]
        assert len(bt_edges) == 3

    def test_conditional_boarding_alert(self):
        assert "boarding_alert" in _node_ids_of_type(self.m, "conditional")

    def test_alien_vessel_spawned_on_edge(self):
        # Enemy spawned via on_complete from patrol_sector → detect_contact
        spawn_edges = [
            e for e in self.m["edges"]
            if isinstance(e.get("on_complete"), dict)
            and e["on_complete"].get("action") == "spawn_wave"
        ]
        enemies = []
        for e in spawn_edges:
            enemies.extend(e["on_complete"].get("enemies", []))
        assert any(en["id"] == "alien_vessel" for en in enemies)


# ---------------------------------------------------------------------------
# TestFirstContactRemasteredBranches
# ---------------------------------------------------------------------------


class TestFirstContactRemasteredBranches:
    def _reach_response_branch(self, graph, world, ship):
        """Drive to response_branch, with alien_vessel in world."""
        ship.x = 30_000.0
        ship.y = 70_000.0
        # patrol_sector → detect_contact (timer_elapsed 20 fires after mission t≥20)
        graph.tick(world, ship, dt=0.1)   # patrol_sector completes
        # On edge on_complete: alien_vessel spawned — add to world manually
        # (game_loop would do this; in test we do it directly)
        alien = spawn_enemy("cruiser", 40_000.0, 60_000.0, "alien_vessel")
        world.enemies.append(alien)
        graph.tick(world, ship, dt=21.0)  # detect_contact completes (timer ≥ 20)
        # response_branch now active

    def test_diplomatic_branch_fires_on_scan(self):
        graph, world, ship = make_graph("first_contact_remastered")
        self._reach_response_branch(graph, world, ship)
        # Science scans the alien vessel
        world.enemies[0].scan_state = "scanned"
        completed = graph.tick(world, ship, dt=0.1)
        assert "response_branch" in completed
        assert graph._graph_nodes["diplomatic_path"].status == "active"
        assert graph._graph_nodes["combat_outcome"].status == "pending"
        assert graph._graph_nodes["avoidance_path"].status == "pending"

    def test_diplomatic_parallel_any_completes_on_first_puzzle(self):
        graph, world, ship = make_graph("first_contact_remastered")
        self._reach_response_branch(graph, world, ship)
        world.enemies[0].scan_state = "scanned"
        graph.tick(world, ship, dt=0.1)  # diplomatic_path activates
        # Science finishes sensor_sweep → diplomatic_path complete (any mode)
        graph.notify_puzzle_result("sensor_sweep", True)
        completed = graph.tick(world, ship, dt=0.1)
        assert "diplomatic_path" in completed
        # comms_negotiation child should be cancelled
        assert graph._graph_nodes["comms_negotiation"].status == "cancelled"

    def test_combat_branch_fires_on_entity_destroyed(self):
        graph, world, ship = make_graph("first_contact_remastered")
        self._reach_response_branch(graph, world, ship)
        # Weapons destroys alien_vessel (removed from enemies)
        world.enemies.clear()
        completed = graph.tick(world, ship, dt=0.1)
        assert "response_branch" in completed
        assert graph._graph_nodes["combat_outcome"].status == "active"
        assert graph._graph_nodes["diplomatic_path"].status == "pending"

    def test_avoidance_branch_fires_on_flee(self):
        graph, world, ship = make_graph("first_contact_remastered")
        self._reach_response_branch(graph, world, ship)
        # Helm moves ship to avoidance coordinates
        ship.x = 80_000.0
        ship.y = 20_000.0
        completed = graph.tick(world, ship, dt=0.1)
        assert "response_branch" in completed
        assert graph._graph_nodes["avoidance_path"].status == "active"
        assert graph._graph_nodes["diplomatic_path"].status == "pending"
        assert graph._graph_nodes["combat_outcome"].status == "pending"

    def test_combat_path_leads_to_victory(self):
        graph, world, ship = make_graph("first_contact_remastered")
        self._reach_response_branch(graph, world, ship)
        world.enemies.clear()
        graph.tick(world, ship, dt=0.1)  # combat_outcome activates (all_enemies_destroyed)
        # No enemies → combat_outcome fires immediately
        completed = graph.tick(world, ship, dt=0.1)
        assert "combat_outcome" in completed
        ship.x = 85_000.0
        ship.y = 50_000.0
        graph.tick(world, ship, dt=0.1)
        over, result = graph.is_over()
        assert over is True
        assert result == "victory"


# ---------------------------------------------------------------------------
# TestConvoyLoad
# ---------------------------------------------------------------------------


class TestConvoyLoad:
    @pytest.fixture(autouse=True)
    def mission(self):
        self.m = load_mission("the_convoy")

    def test_loads(self):
        assert self.m["id"] == "the_convoy"

    def test_has_three_transports_in_spawn(self):
        stations = [s for s in self.m["spawn"] if s["type"] == "station"]
        assert len(stations) == 3

    def test_has_parallel_count_node(self):
        escort = next(n for n in _all_nodes_flat(self.m) if n["id"] == "escort_gauntlet")
        assert escort["complete_when"] == {"count": 2}

    def test_parallel_has_three_children(self):
        escort = next(n for n in _all_nodes_flat(self.m) if n["id"] == "escort_gauntlet")
        assert len(escort["children"]) == 3

    def test_defeat_condition_is_compound(self):
        dc = self.m["defeat_condition"]
        assert dc["type"] == "any_of"
        types = [t["type"] for t in dc["triggers"]]
        assert "player_hull_zero" in types
        assert "all_of" in types

    def test_has_hull_emergency_conditional(self):
        assert "hull_emergency" in _node_ids_of_type(self.m, "conditional")

    def test_has_transport_danger_conditional(self):
        assert "transport_danger" in _node_ids_of_type(self.m, "conditional")

    def test_spawn_wave_on_rendezvous_edge(self):
        rendezvous_edges = [e for e in self.m["edges"] if e["from"] == "rendezvous"]
        assert len(rendezvous_edges) == 1
        oc = rendezvous_edges[0].get("on_complete", {})
        assert isinstance(oc, dict)
        assert oc.get("action") == "spawn_wave"
        assert len(oc.get("enemies", [])) >= 3


# ---------------------------------------------------------------------------
# TestConvoySimulation
# ---------------------------------------------------------------------------


class TestConvoySimulation:
    def _reach_escort_gauntlet(self, graph, world, ship):
        """Rendezvous with convoy; enemies added to world manually."""
        ship.x = 20_000.0
        ship.y = 50_000.0
        graph.tick(world, ship, dt=0.1)  # rendezvous completes → escort_gauntlet activates

    def _add_convoy_enemies(self, world: World) -> None:
        """Simulate the spawn_wave from rendezvous on_complete."""
        for eid, etype, ex, ey in [
            ("alpha_1", "scout", 10_000.0, 45_000.0),
            ("alpha_2", "scout", 8_000.0, 55_000.0),
            ("beta_cruiser", "cruiser", 15_000.0, 40_000.0),
            ("gamma_1", "destroyer", 25_000.0, 35_000.0),
            ("gamma_2", "scout", 28_000.0, 30_000.0),
        ]:
            world.enemies.append(spawn_enemy(etype, ex, ey, eid))

    def test_count_2_completes_on_alpha_and_beta(self):
        graph, world, ship = make_graph("the_convoy")
        self._reach_escort_gauntlet(graph, world, ship)
        self._add_convoy_enemies(world)

        # Defeat alpha wave (remove alpha_ enemies)
        world.enemies = [e for e in world.enemies if not e.id.startswith("alpha_")]
        graph.tick(world, ship, dt=0.1)  # fend_off_alpha fires

        # Defeat beta cruiser
        world.enemies = [e for e in world.enemies if e.id != "beta_cruiser"]
        completed = graph.tick(world, ship, dt=0.1)  # fend_off_beta fires → count=2 → escort_gauntlet complete

        assert "escort_gauntlet" in completed
        # fend_off_gamma should be cancelled (3rd not needed)
        assert graph._graph_nodes["fend_off_gamma"].status == "cancelled"

    def test_count_2_completes_on_beta_and_gamma(self):
        graph, world, ship = make_graph("the_convoy")
        self._reach_escort_gauntlet(graph, world, ship)
        self._add_convoy_enemies(world)

        world.enemies = [e for e in world.enemies if e.id != "beta_cruiser"]
        graph.tick(world, ship, dt=0.1)  # fend_off_beta fires (count=1)

        world.enemies = [e for e in world.enemies if not e.id.startswith("gamma_")]
        completed = graph.tick(world, ship, dt=0.1)  # fend_off_gamma fires (count=2) → complete

        assert "escort_gauntlet" in completed
        assert graph._graph_nodes["fend_off_alpha"].status == "cancelled"

    def test_full_convoy_mission_to_victory(self):
        graph, world, ship = make_graph("the_convoy")
        self._reach_escort_gauntlet(graph, world, ship)
        self._add_convoy_enemies(world)

        # Defeat 2 groups
        world.enemies = [e for e in world.enemies if not e.id.startswith("alpha_")]
        graph.tick(world, ship, dt=0.1)
        world.enemies = [e for e in world.enemies if e.id != "beta_cruiser"]
        graph.tick(world, ship, dt=0.1)  # escort_gauntlet complete

        # Deliver convoy
        ship.x = 80_000.0
        ship.y = 50_000.0
        graph.tick(world, ship, dt=0.1)
        over, result = graph.is_over()
        assert over is True
        assert result == "victory"

    def test_transport_danger_conditional_activates(self):
        graph, world, ship = make_graph("the_convoy")
        # Add transport_beta to world.stations
        tb = spawn_station("transport_beta", 22_000.0, 52_000.0)
        tb.hull = 40.0  # below threshold of 50
        world.stations.append(tb)

        graph.tick(world, ship, dt=0.1)
        assert graph._graph_nodes["transport_danger"].status == "active"

    def test_defeat_when_all_transports_destroyed(self):
        graph, world, ship = make_graph("the_convoy")
        # Place all 3 transports with hull = 0
        for sid, sx, sy in [
            ("transport_alpha", 20_000.0, 50_000.0),
            ("transport_beta",  22_000.0, 52_000.0),
            ("transport_gamma", 18_000.0, 48_000.0),
        ]:
            s = spawn_station(sid, sx, sy)
            s.hull = 0.0
            world.stations.append(s)
        graph.tick(world, ship, dt=0.1)
        over, result = graph.is_over()
        assert over is True
        assert result == "defeat"


# ---------------------------------------------------------------------------
# TestPandemicLoad
# ---------------------------------------------------------------------------


class TestPandemicLoad:
    @pytest.fixture(autouse=True)
    def mission(self):
        self.m = load_mission("pandemic")

    def test_loads(self):
        assert self.m["id"] == "pandemic"

    def test_has_station_aether7_in_spawn(self):
        assert any(s["id"] == "station_aether7" for s in self.m["spawn"])

    def test_has_branch_node(self):
        assert "pathogen_branch" in _node_ids_of_type(self.m, "branch")

    def test_three_branch_trigger_edges(self):
        bt_edges = [e for e in self.m["edges"] if e.get("type") == "branch_trigger"]
        assert len(bt_edges) == 3

    def test_alien_pathogen_parallel_complete_all(self):
        ap = next(n for n in _all_nodes_flat(self.m) if n["id"] == "alien_pathogen")
        assert ap["complete_when"] == "all"
        assert len(ap["children"]) == 2

    def test_weaponised_pathogen_parallel_complete_all(self):
        wp = next(n for n in _all_nodes_flat(self.m) if n["id"] == "weaponised_pathogen")
        assert wp["complete_when"] == "all"
        assert len(wp["children"]) == 2

    def test_three_paths_all_lead_to_depart_station(self):
        # All 3 parallel groups and standard_protocol should have edges to depart_station
        to_depart = {e["from"] for e in self.m["edges"] if e["to"] == "depart_station"}
        assert "alien_pathogen" in to_depart
        assert "weaponised_pathogen" in to_depart
        assert "standard_protocol" in to_depart

    def test_has_hull_emergency_conditional(self):
        assert "hull_emergency" in _node_ids_of_type(self.m, "conditional")


# ---------------------------------------------------------------------------
# TestPandemicBranches
# ---------------------------------------------------------------------------


class TestPandemicBranches:
    def _reach_pathogen_branch(self, graph, world, ship):
        """Drive graph past navigate_to_station so pathogen_branch is active."""
        # receive_distress fires immediately (timer_elapsed 0)
        ship.x = 30_000.0
        ship.y = 70_000.0
        graph.tick(world, ship, dt=0.1)  # receive_distress → navigate_to_station
        graph.tick(world, ship, dt=0.1)  # navigate_to_station → pathogen_branch

    def test_alien_path_fires_on_bio_scan_completed(self):
        graph, world, ship = make_graph("pandemic")
        self._reach_pathogen_branch(graph, world, ship)
        graph.notify_puzzle_result("bio_scan", True)  # puzzle_completed
        completed = graph.tick(world, ship, dt=0.1)
        assert "pathogen_branch" in completed
        assert graph._graph_nodes["alien_pathogen"].status == "active"
        assert graph._graph_nodes["weaponised_pathogen"].status == "pending"
        assert graph._graph_nodes["standard_protocol"].status == "pending"

    def test_weaponised_path_fires_on_intercept_comm_completed(self):
        graph, world, ship = make_graph("pandemic")
        self._reach_pathogen_branch(graph, world, ship)
        graph.notify_puzzle_result("intercept_comm", True)
        completed = graph.tick(world, ship, dt=0.1)
        assert "pathogen_branch" in completed
        assert graph._graph_nodes["weaponised_pathogen"].status == "active"
        assert graph._graph_nodes["alien_pathogen"].status == "pending"

    def test_standard_path_fires_on_timer(self):
        graph, world, ship = make_graph("pandemic")
        self._reach_pathogen_branch(graph, world, ship)
        # Advance past 120-second threshold without resolving puzzles
        graph.tick(world, ship, dt=125.0)
        assert graph._graph_nodes["standard_protocol"].status == "active"
        assert graph._graph_nodes["alien_pathogen"].status == "pending"
        assert graph._graph_nodes["weaponised_pathogen"].status == "pending"

    def test_alien_path_requires_both_children(self):
        graph, world, ship = make_graph("pandemic")
        self._reach_pathogen_branch(graph, world, ship)
        graph.notify_puzzle_result("bio_scan", True)
        graph.tick(world, ship, dt=0.1)  # alien_pathogen activates

        # Resolve only frequency_analysis
        graph.notify_puzzle_result("pathogen_frequency", True)
        graph.tick(world, ship, dt=0.1)
        # alien_pathogen should NOT be complete yet (both children required)
        assert graph._graph_nodes["alien_pathogen"].status == "active"

        # Resolve alien_triage → now both done
        graph.notify_puzzle_result("alien_triage", True)
        completed = graph.tick(world, ship, dt=0.1)
        assert "alien_pathogen" in completed

    def test_alien_path_leads_to_victory(self):
        graph, world, ship = make_graph("pandemic")
        self._reach_pathogen_branch(graph, world, ship)
        graph.notify_puzzle_result("bio_scan", True)
        graph.tick(world, ship, dt=0.1)  # alien_pathogen activates
        graph.notify_puzzle_result("pathogen_frequency", True)
        graph.notify_puzzle_result("alien_triage", True)
        graph.tick(world, ship, dt=0.1)  # alien_pathogen complete → depart_station active
        ship.x = 85_000.0
        ship.y = 50_000.0
        graph.tick(world, ship, dt=0.1)
        over, result = graph.is_over()
        assert over is True
        assert result == "victory"

    def test_standard_path_leads_to_victory(self):
        graph, world, ship = make_graph("pandemic")
        self._reach_pathogen_branch(graph, world, ship)
        graph.tick(world, ship, dt=125.0)  # timer → standard_protocol activates
        graph.notify_puzzle_result("standard_triage", True)
        graph.tick(world, ship, dt=0.1)  # standard_protocol complete → depart_station
        ship.x = 85_000.0
        ship.y = 50_000.0
        graph.tick(world, ship, dt=0.1)
        over, result = graph.is_over()
        assert over is True
        assert result == "victory"

    def test_weaponised_path_on_complete_queues_two_puzzles(self):
        graph, world, ship = make_graph("pandemic")
        self._reach_pathogen_branch(graph, world, ship)
        graph.notify_puzzle_result("intercept_comm", True)
        graph.tick(world, ship, dt=0.1)  # weaponised_pathogen activates
        actions = graph.pop_pending_actions()
        puzzle_labels = [a["label"] for a in actions if a.get("action") == "start_puzzle"]
        assert "security_sweep" in puzzle_labels
        assert "emergency_triage" in puzzle_labels
