"""Tests for the Diplomatic Summit mission (c.9 / v0.02h).

Covers:
  - Mission JSON structure and loading
  - Spawn (two faction stations)
  - Objective chain integrity
  - All 7 active puzzle types represented
  - Runtime engine tick-through (objectives complete in sequence)
  - Balance checks (difficulty params within expected ranges)
"""
from __future__ import annotations

import pytest

from server.missions.loader import load_mission, spawn_from_mission
from server.missions.engine import MissionEngine
from server.models.world import World
from server.models.ship import Ship


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh_world() -> World:
    world = World()
    world.ship = Ship()
    world.ship.x = 50_000.0
    world.ship.y = 50_000.0
    return world


def load_summit() -> dict:
    return load_mission("diplomatic_summit")


def _all_puzzle_actions(mission: dict) -> list[dict]:
    """Collect every start_puzzle action across all objectives."""
    actions: list[dict] = []
    for obj in mission.get("objectives", []):
        for a in obj.get("on_complete", []):
            if a.get("action") == "start_puzzle":
                actions.append(a)
    return actions


# ---------------------------------------------------------------------------
# TestDiplomaticSummitLoad — basic structure checks
# ---------------------------------------------------------------------------


class TestDiplomaticSummitLoad:
    def test_loadable(self):
        m = load_summit()
        assert m["id"] == "diplomatic_summit"

    def test_has_name(self):
        m = load_summit()
        assert "Diplomatic Summit" in m["name"]

    def test_has_briefing(self):
        m = load_summit()
        assert len(m["briefing"]) > 20

    def test_has_signal_location(self):
        m = load_summit()
        sig = m.get("signal_location")
        assert sig is not None
        assert "x" in sig and "y" in sig

    def test_victory_condition(self):
        m = load_summit()
        assert m["victory_condition"] == "all_objectives_complete"

    def test_defeat_condition(self):
        m = load_summit()
        assert m["defeat_condition"] == "player_hull_zero"

    def test_has_two_spawn_stations(self):
        m = load_summit()
        spawns = m.get("spawn", [])
        station_spawns = [s for s in spawns if s["type"] == "station"]
        assert len(station_spawns) == 2

    def test_spawn_station_ids(self):
        m = load_summit()
        ids = {s["id"] for s in m["spawn"]}
        assert "meridian_ship" in ids
        assert "talon_ship" in ids

    def test_has_nine_objectives(self):
        m = load_summit()
        assert len(m["objectives"]) == 9

    def test_spawn_creates_two_world_stations(self):
        world = fresh_world()
        m = load_summit()
        spawn_from_mission(m, world, entity_counter=0)
        assert len(world.stations) == 2
        assert len(world.enemies) == 0

    def test_spawn_station_positions_differ(self):
        world = fresh_world()
        m = load_summit()
        spawn_from_mission(m, world, entity_counter=0)
        s1, s2 = world.stations
        assert (s1.x, s1.y) != (s2.x, s2.y)


# ---------------------------------------------------------------------------
# TestDiplomaticSummitObjectives — objective chain structure
# ---------------------------------------------------------------------------


class TestDiplomaticSummitObjectives:
    def setup_method(self):
        self.m = load_summit()
        self.objs = self.m["objectives"]

    def test_first_objective_is_timer(self):
        assert self.objs[0]["trigger"] == "timer_elapsed"
        assert self.objs[0]["args"]["seconds"] == 5

    def test_first_objective_starts_five_puzzles(self):
        puzzle_actions = [
            a for a in self.objs[0]["on_complete"]
            if a.get("action") == "start_puzzle"
        ]
        assert len(puzzle_actions) == 5

    def test_first_objective_includes_deploy_squads(self):
        deploy_actions = [
            a for a in self.objs[0]["on_complete"]
            if a.get("action") == "deploy_squads"
        ]
        assert len(deploy_actions) == 1
        assert len(deploy_actions[0]["squads"]) == 2

    def test_all_seven_puzzle_types_present(self):
        puzzle_actions = _all_puzzle_actions(self.m)
        types = {a["puzzle_type"] for a in puzzle_actions}
        expected = {
            "frequency_matching",
            "transmission_decoding",
            "circuit_routing",
            "triage",
            "tactical_positioning",
            "route_calculation",
            "firing_solution",
        }
        assert types == expected

    def test_puzzle_labels_unique(self):
        puzzle_actions = _all_puzzle_actions(self.m)
        labels = [a["label"] for a in puzzle_actions]
        assert len(labels) == len(set(labels))

    def test_tactical_positioning_has_intruder_specs(self):
        puzzle_actions = _all_puzzle_actions(self.m)
        tp = next(a for a in puzzle_actions if a["puzzle_type"] == "tactical_positioning")
        assert "intruder_specs" in tp
        assert len(tp["intruder_specs"]) >= 2

    def test_science_objective_trigger(self):
        obj = next(o for o in self.objs if o["id"] == "obj_science")
        assert obj["trigger"] == "puzzle_resolved"
        assert obj["args"]["puzzle_label"] == "faction_signatures"

    def test_comms_objective_trigger(self):
        obj = next(o for o in self.objs if o["id"] == "obj_comms")
        assert obj["trigger"] == "puzzle_resolved"
        assert obj["args"]["puzzle_label"] == "summit_channel"

    def test_engineering_objective_trigger(self):
        obj = next(o for o in self.objs if o["id"] == "obj_engineering")
        assert obj["trigger"] == "puzzle_resolved"
        assert obj["args"]["puzzle_label"] == "summit_power"

    def test_medical_objective_trigger(self):
        obj = next(o for o in self.objs if o["id"] == "obj_medical")
        assert obj["trigger"] == "puzzle_resolved"
        assert obj["args"]["puzzle_label"] == "crew_prep"

    def test_security_objective_trigger(self):
        obj = next(o for o in self.objs if o["id"] == "obj_security")
        assert obj["trigger"] == "puzzle_resolved"
        assert obj["args"]["puzzle_label"] == "security_sweep"

    def test_security_starts_helm_and_weapons_puzzles(self):
        obj = next(o for o in self.objs if o["id"] == "obj_security")
        puzzle_actions = [
            a for a in obj.get("on_complete", [])
            if a.get("action") == "start_puzzle"
        ]
        types = {a["puzzle_type"] for a in puzzle_actions}
        assert "route_calculation" in types
        assert "firing_solution" in types

    def test_helm_objective_trigger(self):
        obj = next(o for o in self.objs if o["id"] == "obj_helm")
        assert obj["trigger"] == "puzzle_resolved"
        assert obj["args"]["puzzle_label"] == "exit_route"

    def test_weapons_objective_trigger(self):
        obj = next(o for o in self.objs if o["id"] == "obj_weapons")
        assert obj["trigger"] == "puzzle_resolved"
        assert obj["args"]["puzzle_label"] == "summit_defense"

    def test_final_objective_timer_at_least_200s(self):
        final = next(o for o in self.objs if o["id"] == "obj_summit")
        assert final["trigger"] == "timer_elapsed"
        assert final["args"]["seconds"] >= 200

    def test_all_time_limits_reasonable(self):
        """Every puzzle should have a time_limit >= 60s."""
        puzzle_actions = _all_puzzle_actions(self.m)
        for a in puzzle_actions:
            assert a["time_limit"] >= 60.0, f"Puzzle {a['label']} time_limit too short"

    def test_all_difficulties_in_range(self):
        """Every puzzle difficulty should be 1–5."""
        puzzle_actions = _all_puzzle_actions(self.m)
        for a in puzzle_actions:
            assert 1 <= a["difficulty"] <= 5, f"Puzzle {a['label']} difficulty out of range"


# ---------------------------------------------------------------------------
# TestDiplomaticSummitEngine — runtime tick-through
# ---------------------------------------------------------------------------


class TestDiplomaticSummitEngine:
    def setup_method(self):
        self.world = fresh_world()
        spawn_from_mission(load_summit(), self.world, entity_counter=0)
        self.engine = MissionEngine(load_summit())

    def _tick(self, seconds: float, dt: float = 0.1) -> list[str]:
        """Tick the engine for `seconds` of game time. Uses ceiling to avoid
        floating-point accumulation landing just short of the target (e.g.
        50 × 0.1 = 4.999... rather than 5.0)."""
        completed: list[str] = []
        ticks = round(seconds / dt) + 1  # +1 guarantees we exceed the target
        for _ in range(ticks):
            completed.extend(self.engine.tick(self.world, self.world.ship, dt))
        return completed

    def test_not_over_at_start(self):
        over, _ = self.engine.is_over()
        assert not over

    def test_arrival_not_complete_at_4s(self):
        """4 seconds elapsed — 5-second timer should not have fired."""
        completed: list[str] = []
        for _ in range(40):  # exactly 4.0s
            completed.extend(self.engine.tick(self.world, self.world.ship, 0.1))
        assert "obj_arrival" not in completed

    def test_arrival_completes_after_5s(self):
        """5+ seconds elapsed — 5-second timer should fire."""
        completed = self._tick(5.0)
        assert "obj_arrival" in completed

    def test_arrival_queues_six_actions(self):
        self._tick(5.0)
        actions = self.engine.pop_pending_actions()
        assert len(actions) == 6  # 5 start_puzzle + 1 deploy_squads

    def test_arrival_queues_five_puzzle_starts(self):
        self._tick(5.0)
        actions = self.engine.pop_pending_actions()
        puzzle_starts = [a for a in actions if a.get("action") == "start_puzzle"]
        assert len(puzzle_starts) == 5

    def test_science_puzzle_label_in_actions(self):
        self._tick(5.0)
        actions = self.engine.pop_pending_actions()
        labels = [a.get("label") for a in actions if a.get("action") == "start_puzzle"]
        assert "faction_signatures" in labels

    def test_obj_science_completes_on_notify(self):
        """After arrival fires, notifying the science puzzle resolved advances obj_science."""
        self._tick(5.0)
        self.engine.pop_pending_actions()
        self.engine.notify_puzzle_result("faction_signatures", True)
        completed = self.engine.tick(self.world, self.world.ship)
        assert "obj_science" in completed

    def test_obj_comms_completes_after_science(self):
        self._tick(5.0)
        self.engine.pop_pending_actions()
        # Science resolves first.
        self.engine.notify_puzzle_result("faction_signatures", True)
        self.engine.tick(self.world, self.world.ship)  # obj_science completes
        # Comms already resolved.
        self.engine.notify_puzzle_result("summit_channel", True)
        completed = self.engine.tick(self.world, self.world.ship)
        assert "obj_comms" in completed

    def test_puzzle_block_resolves_sequentially(self):
        """All 5 block-1 puzzles resolved before security → objectives 2–6 complete."""
        self._tick(5.0)
        self.engine.pop_pending_actions()

        for label in ["faction_signatures", "summit_channel", "summit_power", "crew_prep", "security_sweep"]:
            self.engine.notify_puzzle_result(label, True)

        completed: list[str] = []
        for _ in range(10):
            completed.extend(self.engine.tick(self.world, self.world.ship))

        obj_ids = {o.id for o in self.engine.get_objectives()}
        completed_set = set(completed)
        for oid in ["obj_science", "obj_comms", "obj_engineering", "obj_medical", "obj_security"]:
            assert oid in completed_set, f"{oid} should have completed"

    def test_security_completion_queues_two_puzzles(self):
        """Completing obj_security triggers route_calculation and firing_solution."""
        self._tick(5.0)
        self.engine.pop_pending_actions()

        for label in ["faction_signatures", "summit_channel", "summit_power", "crew_prep", "security_sweep"]:
            self.engine.notify_puzzle_result(label, True)

        for _ in range(10):
            self.engine.tick(self.world, self.world.ship)

        actions = self.engine.pop_pending_actions()
        types = {a["puzzle_type"] for a in actions if a.get("action") == "start_puzzle"}
        assert "route_calculation" in types
        assert "firing_solution" in types

    def test_not_over_until_final_timer(self):
        """Even with all puzzles resolved, victory requires elapsed >= 240s."""
        self._tick(5.0)
        self.engine.pop_pending_actions()

        all_labels = [
            "faction_signatures", "summit_channel", "summit_power",
            "crew_prep", "security_sweep", "exit_route", "summit_defense",
        ]
        for label in all_labels:
            self.engine.notify_puzzle_result(label, True)

        # Advance enough for objectives 2–8 to clear but less than 240s total.
        for _ in range(20):
            self.engine.tick(self.world, self.world.ship)

        over, _ = self.engine.is_over()
        assert not over

    def test_victory_after_240s(self):
        """All puzzles resolved + 240s elapsed → victory."""
        self._tick(5.0)
        self.engine.pop_pending_actions()

        all_labels = [
            "faction_signatures", "summit_channel", "summit_power",
            "crew_prep", "security_sweep", "exit_route", "summit_defense",
        ]
        for label in all_labels:
            self.engine.notify_puzzle_result(label, True)

        # Tick objectives 2–8 through.
        for _ in range(20):
            self.engine.tick(self.world, self.world.ship)

        # Tick to 240s total.
        self._tick(235.0)
        over, result = self.engine.is_over()
        assert over
        assert result == "victory"

    def test_defeat_on_hull_zero(self):
        self.world.ship.hull = 0.0
        self.engine.tick(self.world, self.world.ship)
        over, result = self.engine.is_over()
        assert over
        assert result == "defeat"


# ---------------------------------------------------------------------------
# TestDiplomaticSummitBalance — puzzle difficulty sanity checks
# ---------------------------------------------------------------------------


_PUZZLE_ARGS = dict(puzzle_id="p_test", label="test", station="test", time_limit=90.0)


class TestDiplomaticSummitBalance:
    """Ensure all puzzle types at their mission difficulty can be generated."""

    def test_frequency_matching_diff2_generates(self):
        from server.puzzles.frequency_matching import FrequencyMatchingPuzzle
        p = FrequencyMatchingPuzzle(difficulty=2, **_PUZZLE_ARGS)
        data = p.generate()
        assert "component_count" in data
        assert "target_components" in data

    def test_transmission_decoding_diff2_generates(self):
        from server.puzzles.transmission_decoding import TransmissionDecodingPuzzle
        p = TransmissionDecodingPuzzle(difficulty=2, **_PUZZLE_ARGS)
        data = p.generate()
        assert "symbols" in data

    def test_circuit_routing_diff1_generates(self):
        from server.puzzles.circuit_routing import CircuitRoutingPuzzle
        p = CircuitRoutingPuzzle(difficulty=1, **_PUZZLE_ARGS)
        data = p.generate()
        assert "grid_rows" in data

    def test_triage_diff1_generates(self):
        from server.puzzles.triage import TriagePuzzle
        p = TriagePuzzle(difficulty=1, **_PUZZLE_ARGS)
        data = p.generate()
        assert "patients" in data

    def test_route_calculation_diff2_generates(self):
        from server.puzzles.route_calculation import RouteCalculationPuzzle
        p = RouteCalculationPuzzle(difficulty=2, **_PUZZLE_ARGS)
        data = p.generate()
        assert "cells" in data
        assert "grid_size" in data

    def test_firing_solution_diff2_generates(self):
        from server.puzzles.firing_solution import FiringSolutionPuzzle
        p = FiringSolutionPuzzle(difficulty=2, **_PUZZLE_ARGS)
        data = p.generate()
        assert "target_bearing" in data
        assert "tolerance" in data

    def test_firing_solution_diff1_tolerance_wider_than_diff5(self):
        from server.puzzles.firing_solution import FiringSolutionPuzzle
        p1 = FiringSolutionPuzzle(difficulty=1, **_PUZZLE_ARGS)
        p5 = FiringSolutionPuzzle(difficulty=5, **_PUZZLE_ARGS)
        d1 = p1.generate()
        d5 = p5.generate()
        assert d1["tolerance"] > d5["tolerance"]

    def test_triage_diff1_easier_than_diff3(self):
        from server.puzzles.triage import TriagePuzzle
        p1 = TriagePuzzle(difficulty=1, **_PUZZLE_ARGS)
        p3 = TriagePuzzle(difficulty=3, **_PUZZLE_ARGS)
        d1 = p1.generate()
        d3 = p3.generate()
        # Difficulty 1 has fewer or equal patients.
        assert len(d1["patients"]) <= len(d3["patients"])

    def test_route_calculation_diff1_smaller_grid_than_diff3(self):
        from server.puzzles.route_calculation import RouteCalculationPuzzle
        p1 = RouteCalculationPuzzle(difficulty=1, **_PUZZLE_ARGS)
        p3 = RouteCalculationPuzzle(difficulty=3, **_PUZZLE_ARGS)
        d1 = p1.generate()
        d3 = p3.generate()
        assert d1["grid_size"] < d3["grid_size"]

    def test_all_mission_time_limits_at_least_60s(self):
        """Regression: no puzzle in the summit should time out in < 60 seconds."""
        m = load_summit()
        puzzle_actions = _all_puzzle_actions(m)
        for a in puzzle_actions:
            assert a["time_limit"] >= 60.0
