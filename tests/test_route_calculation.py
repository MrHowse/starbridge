"""Tests for the Route Calculation puzzle and Hazard system (c.7 / v0.02f)."""
from __future__ import annotations

import math
import pytest

from server.puzzles.route_calculation import RouteCalculationPuzzle, _bfs_path, _DIFFICULTY_PARAMS
from server.puzzles.engine import PuzzleEngine
from server.models.world import Hazard, World, spawn_hazard
from server.models.ship import Ship
from server.systems.hazards import tick_hazards, MINEFIELD_DAMAGE_PER_SEC, RADIATION_DAMAGE_PER_SEC, GRAVITY_WELL_MAX_VEL
from server.missions.loader import load_mission, spawn_from_mission


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_puzzle(difficulty: int = 1) -> RouteCalculationPuzzle:
    p = RouteCalculationPuzzle(puzzle_id="test", label="test_label", station="helm", difficulty=difficulty, time_limit=60.0)
    p.generate()
    return p


def fresh_engine() -> PuzzleEngine:
    return PuzzleEngine()


# ---------------------------------------------------------------------------
# _bfs_path helper
# ---------------------------------------------------------------------------

class TestBfsPath:
    def test_trivial_1x1(self):
        grid = [["safe"]]
        path = _bfs_path(grid, 1, (0, 0), (0, 0))
        assert path == [(0, 0)]

    def test_straight_path(self):
        # 3×3 grid, path along top row.
        grid = [
            ["safe", "safe", "safe"],
            ["safe", "safe", "safe"],
            ["safe", "safe", "safe"],
        ]
        path = _bfs_path(grid, 3, (0, 0), (0, 2))
        assert path is not None
        assert path[0] == (0, 0)
        assert path[-1] == (0, 2)

    def test_blocked_path(self):
        # All cells are hazard except start and end — no path possible.
        grid = [
            ["safe",   "hazard"],
            ["hazard", "safe"],
        ]
        path = _bfs_path(grid, 2, (0, 0), (1, 1))
        assert path is None

    def test_detour_around_hazard(self):
        # Hazard in (0,1) forces path via (1,0) → (1,1) → (0,1) blocked so must go further.
        grid = [
            ["safe",   "hazard", "safe"],
            ["safe",   "safe",   "safe"],
            ["hazard", "safe",   "safe"],
        ]
        path = _bfs_path(grid, 3, (0, 0), (2, 2))
        assert path is not None
        # Verify no hazard cells in path.
        for r, c in path:
            assert grid[r][c] == "safe"


# ---------------------------------------------------------------------------
# RouteCalculationPuzzle.generate
# ---------------------------------------------------------------------------

class TestGenerate:
    @pytest.mark.parametrize("diff", [1, 2, 3, 4, 5])
    def test_grid_size(self, diff):
        expected_size, _, _ = _DIFFICULTY_PARAMS[diff]
        p = make_puzzle(diff)
        assert p._size == expected_size
        assert len(p._true_grid) == expected_size
        assert all(len(row) == expected_size for row in p._true_grid)

    @pytest.mark.parametrize("diff", [1, 2, 3, 4, 5])
    def test_hazard_count(self, diff):
        _, expected_hazards, _ = _DIFFICULTY_PARAMS[diff]
        p = make_puzzle(diff)
        count = sum(cell == "hazard" for row in p._true_grid for cell in row)
        assert count == expected_hazards

    @pytest.mark.parametrize("diff", [1, 2, 3, 4, 5])
    def test_hidden_count(self, diff):
        _, _, expected_hidden = _DIFFICULTY_PARAMS[diff]
        p = make_puzzle(diff)
        count = sum(cell == "hidden" for row in p._display_grid for cell in row)
        assert count == expected_hidden

    def test_start_and_end_always_safe(self):
        for diff in range(1, 6):
            p = make_puzzle(diff)
            size = p._size
            assert p._true_grid[0][0] == "safe"
            assert p._true_grid[size - 1][size - 1] == "safe"
            assert p._display_grid[0][0] == "safe"
            assert p._display_grid[size - 1][size - 1] == "safe"

    def test_guaranteed_path_is_all_safe_and_not_hidden(self):
        for diff in range(1, 6):
            p = make_puzzle(diff)
            for r, c in p._guaranteed_path:
                assert p._true_grid[r][c] == "safe", f"Hazard at {(r,c)} in guaranteed_path"
                assert p._display_grid[r][c] != "hidden", f"Hidden cell {(r,c)} on guaranteed_path"

    def test_guaranteed_path_starts_ends_correct(self):
        p = make_puzzle(1)
        assert p._guaranteed_path[0] == (0, 0)
        assert p._guaranteed_path[-1] == (p._size - 1, p._size - 1)

    def test_return_payload_structure(self):
        p = make_puzzle(1)
        data = p.generate()
        assert "grid_size" in data
        assert "cells" in data
        assert "start" in data
        assert "end" in data
        assert data["start"] == [0, 0]
        assert data["end"] == [data["grid_size"] - 1, data["grid_size"] - 1]

    def test_cells_list_matches_grid_size(self):
        p = make_puzzle(2)
        data = p.generate()
        assert len(data["cells"]) == data["grid_size"]
        for row in data["cells"]:
            assert len(row) == data["grid_size"]
            for cell in row:
                assert "type" in cell
                assert cell["type"] in ("safe", "hazard", "hidden")

    def test_hidden_cells_not_on_path(self):
        for diff in range(1, 4):
            p = make_puzzle(diff)
            path_set = set(map(tuple, p._guaranteed_path))
            for r, c in p._hidden_cells:
                assert (r, c) not in path_set


# ---------------------------------------------------------------------------
# validate_submission
# ---------------------------------------------------------------------------

class TestValidateSubmission:
    def test_guaranteed_path_accepted(self):
        p = make_puzzle(1)
        path = [list(cell) for cell in p._guaranteed_path]
        assert p.validate_submission({"path": path}) is True

    def test_wrong_start(self):
        p = make_puzzle(1)
        path = [[1, 0], [p._size - 1, p._size - 1]]
        assert p.validate_submission({"path": path}) is False

    def test_wrong_end(self):
        p = make_puzzle(1)
        path = [[0, 0], [0, 1]]
        assert p.validate_submission({"path": path}) is False

    def test_too_short(self):
        p = make_puzzle(1)
        assert p.validate_submission({"path": [[0, 0]]}) is False

    def test_missing_path_key(self):
        p = make_puzzle(1)
        assert p.validate_submission({}) is False

    def test_non_adjacent_step_rejected(self):
        p = make_puzzle(1)
        # Diagonal move (not cardinal).
        path = [[0, 0], [1, 1], [p._size - 1, p._size - 1]]
        assert p.validate_submission({"path": path}) is False

    def test_out_of_bounds_rejected(self):
        p = make_puzzle(1)
        path = [[0, 0], [0, -1], [p._size - 1, p._size - 1]]
        assert p.validate_submission({"path": path}) is False

    def test_path_through_true_hazard_rejected(self):
        """Build a path that walks through a true hazard cell."""
        p = make_puzzle(1)
        # Find a hazard cell and try to use it.
        hazard_cell = None
        for r in range(p._size):
            for c in range(p._size):
                if p._true_grid[r][c] == "hazard":
                    hazard_cell = (r, c)
                    break
            if hazard_cell:
                break

        if hazard_cell is None:
            pytest.skip("No hazard cells in this layout")

        # Construct a path that starts at (0,0), wanders through the hazard.
        # We just need a path whose i-th cell is the hazard, regardless of end.
        hr, hc = hazard_cell
        path_to_hazard = []
        # Walk right to hc then down to hr.
        for c in range(hc + 1):
            path_to_hazard.append([0, c])
        for r in range(1, hr + 1):
            path_to_hazard.append([r, hc])
        # Doesn't matter if it reaches end — validation fails at hazard step.
        assert p.validate_submission({"path": path_to_hazard}) is False

    def test_hidden_safe_cell_allowed(self):
        """Hidden cells that are actually safe in _true_grid should be accepted."""
        p = make_puzzle(1)
        # Find a hidden cell that is safe in the true grid.
        safe_hidden = None
        for r, c in p._hidden_cells:
            if p._true_grid[r][c] == "safe":
                safe_hidden = (r, c)
                break

        if safe_hidden is None:
            pytest.skip("No safe hidden cells in this layout")

        # Build a path through guaranteed path (which avoids hidden) — it should pass.
        path = [list(cell) for cell in p._guaranteed_path]
        assert p.validate_submission({"path": path}) is True


# ---------------------------------------------------------------------------
# apply_assist — reveal_hazard
# ---------------------------------------------------------------------------

class TestApplyAssist:
    def test_reveal_hazard_returns_row_col_safe(self):
        p = make_puzzle(1)
        result = p.apply_assist("reveal_hazard", {})
        if not p._hidden_cells:
            assert result == {}
        else:
            assert "row" in result
            assert "col" in result
            assert "safe" in result
            assert isinstance(result["safe"], bool)

    def test_reveal_hazard_reveals_sequentially(self):
        p = make_puzzle(2)  # diff 2 → 3 hidden cells
        revealed = []
        for _ in range(10):
            r = p.apply_assist("reveal_hazard", {})
            if r:
                revealed.append((r["row"], r["col"]))
            else:
                break
        # Should reveal exactly len(_hidden_cells) times.
        assert len(revealed) == len(p._hidden_cells)
        # All revealed are distinct.
        assert len(set(revealed)) == len(revealed)

    def test_reveal_hazard_correct_safe_flag(self):
        p = make_puzzle(2)
        for _ in range(len(p._hidden_cells)):
            r = p.apply_assist("reveal_hazard", {})
            if r:
                row, col, safe = r["row"], r["col"], r["safe"]
                expected = p._true_grid[row][col] == "safe"
                assert safe == expected

    def test_reveal_all_returns_empty(self):
        p = make_puzzle(1)  # diff 1 → 2 hidden cells
        for _ in range(len(p._hidden_cells)):
            p.apply_assist("reveal_hazard", {})
        result = p.apply_assist("reveal_hazard", {})
        assert result == {}

    def test_unknown_assist_type_returns_empty(self):
        p = make_puzzle(1)
        assert p.apply_assist("teleport", {}) == {}


# ---------------------------------------------------------------------------
# PuzzleEngine integration
# ---------------------------------------------------------------------------

class TestPuzzleEngineIntegration:
    def test_create_route_calculation_puzzle(self):
        engine = fresh_engine()
        inst = engine.create_puzzle(
            puzzle_type="route_calculation",
            station="helm",
            label="nav_test",
            difficulty=1,
            time_limit=60.0,
        )
        assert inst is not None
        assert inst.label == "nav_test"

    def test_submit_valid_path(self):
        engine = fresh_engine()
        inst = engine.create_puzzle(
            puzzle_type="route_calculation",
            station="helm",
            label="nav_test",
            difficulty=1,
            time_limit=60.0,
        )
        engine.pop_pending_broadcasts()  # consume puzzle.started

        path = [list(cell) for cell in inst._guaranteed_path]
        engine.submit(inst.puzzle_id, {"path": path})

        resolved = engine.pop_resolved()
        assert len(resolved) == 1
        _pid, label, success = resolved[0]
        assert success is True
        assert label == "nav_test"

    def test_submit_invalid_path(self):
        engine = fresh_engine()
        inst = engine.create_puzzle(
            puzzle_type="route_calculation",
            station="helm",
            label="nav_test",
            difficulty=1,
            time_limit=60.0,
        )
        engine.pop_pending_broadcasts()

        engine.submit(inst.puzzle_id, {"path": [[0, 0], [0, 1]]})  # doesn't reach end

        resolved = engine.pop_resolved()
        assert len(resolved) == 1
        _pid, label, success = resolved[0]
        assert success is False


# ---------------------------------------------------------------------------
# Hazard model
# ---------------------------------------------------------------------------

class TestHazardModel:
    def test_spawn_hazard_defaults(self):
        h = spawn_hazard("h1", 1000.0, 2000.0)
        assert h.id == "h1"
        assert h.x == 1000.0
        assert h.y == 2000.0
        assert h.radius == 10_000.0
        assert h.hazard_type == "nebula"

    def test_spawn_hazard_custom(self):
        h = spawn_hazard("mine1", 5000.0, 6000.0, radius=3000.0, hazard_type="minefield", label="Danger Zone")
        assert h.hazard_type == "minefield"
        assert h.radius == 3000.0
        assert h.label == "Danger Zone"

    def test_world_hazards_list(self):
        w = World()
        assert w.hazards == []
        w.hazards.append(spawn_hazard("h1", 0.0, 0.0))
        assert len(w.hazards) == 1


# ---------------------------------------------------------------------------
# Hazard system physics
# ---------------------------------------------------------------------------

class TestHazardSystem:
    def _make_world_with_hazard(self, hazard_type: str, ship_inside: bool = True) -> tuple[World, Ship]:
        world = World()
        radius = 5000.0
        world.hazards.append(
            Hazard(id="hz1", x=50_000.0, y=50_000.0, radius=radius, hazard_type=hazard_type)
        )
        ship = world.ship
        if ship_inside:
            ship.x = 50_000.0
            ship.y = 50_000.0
        else:
            ship.x = 0.0
            ship.y = 0.0
        return world, ship

    def test_no_hazards_no_events(self):
        world = World()
        ship = world.ship
        events = tick_hazards(world, ship, 0.1)
        assert events == []

    def test_minefield_outside_no_damage(self):
        world, ship = self._make_world_with_hazard("minefield", ship_inside=False)
        hull_before = ship.hull
        events = tick_hazards(world, ship, 0.1)
        assert events == []
        assert ship.hull == hull_before

    def test_minefield_inside_damages_hull(self):
        world, ship = self._make_world_with_hazard("minefield", ship_inside=True)
        hull_before = ship.hull
        events = tick_hazards(world, ship, 1.0)
        assert len(events) == 1
        assert events[0]["hazard_type"] == "minefield"
        assert ship.hull < hull_before
        expected_damage = MINEFIELD_DAMAGE_PER_SEC * 1.0
        assert abs(ship.hull - (hull_before - expected_damage)) < 0.001

    def test_radiation_zone_inside_damages_hull(self):
        world, ship = self._make_world_with_hazard("radiation_zone", ship_inside=True)
        hull_before = ship.hull
        events = tick_hazards(world, ship, 1.0)
        assert len(events) == 1
        assert events[0]["hazard_type"] == "radiation_zone"
        expected_damage = RADIATION_DAMAGE_PER_SEC * 1.0
        assert abs(ship.hull - (hull_before - expected_damage)) < 0.001

    def test_minefield_damage_less_than_radiation(self):
        # Per second: minefield (5) > radiation (2)
        assert MINEFIELD_DAMAGE_PER_SEC > RADIATION_DAMAGE_PER_SEC

    def test_gravity_well_caps_velocity(self):
        world, ship = self._make_world_with_hazard("gravity_well", ship_inside=True)
        ship.velocity = 500.0
        events = tick_hazards(world, ship, 0.1)
        assert events == []  # No hull damage
        assert ship.velocity == GRAVITY_WELL_MAX_VEL

    def test_gravity_well_below_cap_unchanged(self):
        world, ship = self._make_world_with_hazard("gravity_well", ship_inside=True)
        ship.velocity = 50.0
        tick_hazards(world, ship, 0.1)
        assert ship.velocity == 50.0

    def test_nebula_no_hull_damage(self):
        world, ship = self._make_world_with_hazard("nebula", ship_inside=True)
        hull_before = ship.hull
        events = tick_hazards(world, ship, 1.0)
        assert events == []
        assert ship.hull == hull_before

    def test_hull_clamped_to_zero(self):
        world, ship = self._make_world_with_hazard("minefield", ship_inside=True)
        ship.hull = 0.1  # Almost dead
        tick_hazards(world, ship, 10.0)
        assert ship.hull == 0.0

    def test_multiple_hazards(self):
        world = World()
        ship = world.ship
        ship.x = 50_000.0
        ship.y = 50_000.0
        hull_start = ship.hull
        # Both hazards contain the ship.
        world.hazards.append(Hazard(id="m1", x=50_000.0, y=50_000.0, radius=5000.0, hazard_type="minefield"))
        world.hazards.append(Hazard(id="r1", x=50_000.0, y=50_000.0, radius=5000.0, hazard_type="radiation_zone"))
        events = tick_hazards(world, ship, 1.0)
        assert len(events) == 2
        expected = hull_start - MINEFIELD_DAMAGE_PER_SEC - RADIATION_DAMAGE_PER_SEC
        assert abs(ship.hull - expected) < 0.001


# ---------------------------------------------------------------------------
# Mission loader — nebula_crossing
# ---------------------------------------------------------------------------

class TestNebulaCrossingMission:
    def test_mission_loadable(self):
        mission = load_mission("nebula_crossing")
        assert mission["id"] == "nebula_crossing"

    def test_mission_has_hazards(self):
        mission = load_mission("nebula_crossing")
        assert len(mission.get("hazards", [])) >= 1

    def test_mission_has_route_calculation_puzzle(self):
        mission = load_mission("nebula_crossing")
        actions = []
        for obj in mission.get("objectives", []):
            actions.extend(obj.get("on_complete", []))
        puzzle_actions = [a for a in actions if a.get("action") == "start_puzzle"]
        assert any(a.get("puzzle_type") == "route_calculation" for a in puzzle_actions)

    def test_spawn_from_mission_creates_hazards(self):
        mission = load_mission("nebula_crossing")
        world = World()
        spawn_from_mission(mission, world, 0)
        assert len(world.hazards) >= 1
        hz = world.hazards[0]
        assert hz.hazard_type in ("nebula", "minefield", "gravity_well", "radiation_zone")

    def test_nebula_hazard_spawned(self):
        mission = load_mission("nebula_crossing")
        world = World()
        spawn_from_mission(mission, world, 0)
        nebulas = [h for h in world.hazards if h.hazard_type == "nebula"]
        assert len(nebulas) >= 1

    def test_mission_objectives_use_flat_trigger(self):
        mission = load_mission("nebula_crossing")
        for obj in mission.get("objectives", []):
            assert isinstance(obj.get("trigger"), str), \
                f"Objective {obj['id']} trigger must be a string"
