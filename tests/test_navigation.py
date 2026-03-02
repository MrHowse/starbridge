"""Tests for the navigation module (server/game_loop_navigation.py) — v0.05c."""
from __future__ import annotations

import math
import pytest

import server.game_loop_navigation as gln
from server.models.sector import (
    Rect,
    Sector,
    SectorGrid,
    SectorProperties,
)
from server.models.messages.navigation import MapClearRoutePayload, MapPlotRoutePayload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_2x2_grid() -> SectorGrid:
    """2×2 grid for most navigation tests."""
    sectors = {
        "A1": Sector(
            id="A1", name="Alpha One",
            grid_position=(0, 0),
            world_bounds=Rect(0, 0, 100_000, 100_000),
        ),
        "B1": Sector(
            id="B1", name="Bravo One",
            grid_position=(1, 0),
            world_bounds=Rect(100_000, 0, 200_000, 100_000),
        ),
        "A2": Sector(
            id="A2", name="Alpha Two",
            grid_position=(0, 1),
            world_bounds=Rect(0, 100_000, 100_000, 200_000),
        ),
        "B2": Sector(
            id="B2", name="Bravo Two",
            grid_position=(1, 1),
            world_bounds=Rect(100_000, 100_000, 200_000, 200_000),
        ),
    }
    return SectorGrid(sectors=sectors, grid_size=(2, 2))


def _make_hostile_grid() -> SectorGrid:
    """Grid with one hostile sector for warning tests."""
    props_hostile = SectorProperties(type="hostile_space")
    props_nebula  = SectorProperties(type="nebula")
    props_ast     = SectorProperties(type="asteroid_field")
    props_rad     = SectorProperties(type="radiation_zone")
    props_grav    = SectorProperties(type="gravity_well")
    sectors = {
        "H1": Sector(
            id="H1", name="Hostile",
            grid_position=(0, 0),
            world_bounds=Rect(0, 0, 100_000, 100_000),
            properties=props_hostile,
        ),
        "N1": Sector(
            id="N1", name="Nebula",
            grid_position=(1, 0),
            world_bounds=Rect(100_000, 0, 200_000, 100_000),
            properties=props_nebula,
        ),
        "A1": Sector(
            id="A1", name="Asteroids",
            grid_position=(2, 0),
            world_bounds=Rect(200_000, 0, 300_000, 100_000),
            properties=props_ast,
        ),
        "R1": Sector(
            id="R1", name="Radiation",
            grid_position=(3, 0),
            world_bounds=Rect(300_000, 0, 400_000, 100_000),
            properties=props_rad,
        ),
        "G1": Sector(
            id="G1", name="Gravity",
            grid_position=(4, 0),
            world_bounds=Rect(400_000, 0, 500_000, 100_000),
            properties=props_grav,
        ),
    }
    return SectorGrid(sectors=sectors, grid_size=(5, 1))


# ---------------------------------------------------------------------------
# _heading_between
# ---------------------------------------------------------------------------


class TestHeadingBetween:
    """Y increases southward; heading 0° = north (decreasing y)."""

    def test_due_north(self) -> None:
        h = gln._heading_between(0, 100, 0, 0)
        assert abs(h - 0) < 1 or abs(h - 360) < 1

    def test_due_east(self) -> None:
        h = gln._heading_between(0, 0, 100, 0)
        assert abs(h - 90) < 1

    def test_due_south(self) -> None:
        h = gln._heading_between(0, 0, 0, 100)
        assert abs(h - 180) < 1

    def test_due_west(self) -> None:
        h = gln._heading_between(100, 0, 0, 0)
        assert abs(h - 270) < 1

    def test_northeast(self) -> None:
        h = gln._heading_between(0, 0, 100, -100)
        assert abs(h - 45) < 1

    def test_same_point(self) -> None:
        """Zero-distance route has a defined (non-crashing) heading."""
        h = gln._heading_between(50, 50, 50, 50)
        assert 0 <= h < 360


# ---------------------------------------------------------------------------
# calculate_route — basic structure
# ---------------------------------------------------------------------------


class TestCalculateRoute:
    def test_returns_dict(self) -> None:
        r = gln.calculate_route(0, 0, 100, 0)
        assert isinstance(r, dict)

    def test_required_keys(self) -> None:
        r = gln.calculate_route(0, 0, 100, 0)
        for key in (
            "from_x", "from_y", "plot_x", "plot_y",
            "heading", "total_distance", "estimated_travel_time_s",
            "sectors_traversed", "waypoints", "warnings", "turn_by_turn",
        ):
            assert key in r, f"Missing key: {key}"

    def test_coordinates_stored(self) -> None:
        r = gln.calculate_route(10, 20, 30, 40)
        assert r["from_x"] == 10.0
        assert r["from_y"] == 20.0
        assert r["plot_x"] == 30.0
        assert r["plot_y"] == 40.0

    def test_distance_correct(self) -> None:
        r = gln.calculate_route(0, 0, 3, 4)
        assert abs(r["total_distance"] - 5.0) < 0.1

    def test_travel_time_at_speed(self) -> None:
        r = gln.calculate_route(0, 0, 10_000, 0, current_speed=100.0)
        assert abs(r["estimated_travel_time_s"] - 100.0) < 1.0

    def test_travel_time_zero_distance(self) -> None:
        r = gln.calculate_route(50, 50, 50, 50, current_speed=100.0)
        assert r["estimated_travel_time_s"] == 0.0

    def test_destination_in_waypoints(self) -> None:
        r = gln.calculate_route(0, 0, 500, 500)
        last = r["waypoints"][-1]
        assert last["label"] == "DESTINATION"

    def test_no_grid_empty_sectors(self) -> None:
        r = gln.calculate_route(0, 0, 500, 500, grid=None)
        assert r["sectors_traversed"] == []
        assert r["warnings"] == []

    def test_with_grid_single_sector(self) -> None:
        grid = _make_2x2_grid()
        r = gln.calculate_route(10_000, 10_000, 50_000, 50_000, grid=grid)
        assert r["sectors_traversed"] == ["A1"]

    def test_with_grid_crosses_sectors(self) -> None:
        grid = _make_2x2_grid()
        r = gln.calculate_route(50_000, 50_000, 150_000, 50_000, grid=grid)
        assert "A1" in r["sectors_traversed"]
        assert "B1" in r["sectors_traversed"]
        assert r["sectors_traversed"].index("A1") < r["sectors_traversed"].index("B1")


# ---------------------------------------------------------------------------
# Sector traversal & warnings
# ---------------------------------------------------------------------------


class TestTraceSectors:
    def test_single_sector(self) -> None:
        grid = _make_2x2_grid()
        sectors, _ = gln._trace_sectors(10_000, 10_000, 90_000, 90_000, grid)
        assert sectors == ["A1"]

    def test_two_sectors_horizontal(self) -> None:
        grid = _make_2x2_grid()
        sectors, _ = gln._trace_sectors(50_000, 50_000, 150_000, 50_000, grid)
        assert "A1" in sectors and "B1" in sectors

    def test_two_sectors_vertical(self) -> None:
        grid = _make_2x2_grid()
        sectors, _ = gln._trace_sectors(50_000, 50_000, 50_000, 150_000, grid)
        assert "A1" in sectors and "A2" in sectors

    def test_hostile_warning(self) -> None:
        grid = _make_hostile_grid()
        _, warnings = gln._trace_sectors(50_000, 50_000, 50_000, 50_000, grid)
        assert "HOSTILE SPACE" in warnings

    def test_nebula_warning(self) -> None:
        grid = _make_hostile_grid()
        _, warnings = gln._trace_sectors(150_000, 50_000, 150_000, 50_000, grid)
        assert "SENSOR DEGRADATION (nebula)" in warnings

    def test_asteroid_warning(self) -> None:
        grid = _make_hostile_grid()
        _, warnings = gln._trace_sectors(250_000, 50_000, 250_000, 50_000, grid)
        assert "NAVIGATION HAZARD (asteroids)" in warnings

    def test_radiation_warning(self) -> None:
        grid = _make_hostile_grid()
        _, warnings = gln._trace_sectors(350_000, 50_000, 350_000, 50_000, grid)
        assert "RADIATION ZONE" in warnings

    def test_gravity_warning(self) -> None:
        grid = _make_hostile_grid()
        _, warnings = gln._trace_sectors(450_000, 50_000, 450_000, 50_000, grid)
        assert "GRAVITY WELL (reduced speed)" in warnings

    def test_friendly_no_warnings(self) -> None:
        grid = _make_2x2_grid()
        _, warnings = gln._trace_sectors(10_000, 10_000, 90_000, 90_000, grid)
        assert warnings == []

    def test_warnings_sorted(self) -> None:
        """Warnings must be in sorted (deterministic) order."""
        grid = _make_hostile_grid()
        _, warnings = gln._trace_sectors(0, 50_000, 200_000, 50_000, grid)
        assert warnings == sorted(warnings)


# ---------------------------------------------------------------------------
# Build waypoints
# ---------------------------------------------------------------------------


class TestBuildWaypoints:
    def test_single_sector_no_crossings(self) -> None:
        grid = _make_2x2_grid()
        wp = gln._build_waypoints(10_000, 10_000, 90_000, 90_000, grid)
        # No sector boundary crossing within A1.
        assert all(w["label"] == "DESTINATION" or "ENTER" in w["label"] for w in wp)
        enter_pts = [w for w in wp if "ENTER" in w.get("label", "")]
        assert len(enter_pts) == 0

    def test_two_sectors_has_crossing(self) -> None:
        grid = _make_2x2_grid()
        wp = gln._build_waypoints(50_000, 50_000, 150_000, 50_000, grid)
        labels = [w["label"] for w in wp]
        assert any("ENTER B1" in lbl for lbl in labels)


# ---------------------------------------------------------------------------
# Turn-by-turn
# ---------------------------------------------------------------------------


class TestTurnByTurn:
    def test_heading_in_first_entry(self) -> None:
        tt = gln._build_turn_by_turn(90.0, 10_000, 100.0, [])
        assert "090" in tt[0]

    def test_distance_in_second_entry(self) -> None:
        tt = gln._build_turn_by_turn(90.0, 10_000, 100.0, [])
        assert "10.0k" in tt[1]

    def test_arrive_at_end(self) -> None:
        tt = gln._build_turn_by_turn(90.0, 10_000, 100.0, [])
        assert tt[-1] == "Arrive at destination"

    def test_sector_crossing_listed(self) -> None:
        tt = gln._build_turn_by_turn(90.0, 200_000, 2000.0, ["A1", "B1", "C1"])
        assert any("Enter sector B1" in s for s in tt)
        assert any("Enter sector C1" in s for s in tt)
        # Origin sector (A1) is NOT listed.
        assert not any("Enter sector A1" in s for s in tt)

    def test_single_sector_no_crossings_in_tt(self) -> None:
        tt = gln._build_turn_by_turn(45.0, 5_000, 50.0, ["A1"])
        assert len(tt) == 3  # set heading + travel + arrive


# ---------------------------------------------------------------------------
# Route state management
# ---------------------------------------------------------------------------


class TestRouteState:
    def setup_method(self) -> None:
        gln.reset()

    def test_initial_none(self) -> None:
        assert gln.get_route() is None

    def test_set_route(self) -> None:
        route = {"plot_x": 50_000, "plot_y": 50_000}
        gln.set_route(route)
        assert gln.get_route() is route

    def test_clear_route(self) -> None:
        gln.set_route({"x": 1})
        gln.clear_route()
        assert gln.get_route() is None

    def test_reset_clears(self) -> None:
        gln.set_route({"x": 1})
        gln.reset()
        assert gln.get_route() is None

    def test_pop_pending_after_set(self) -> None:
        gln.set_route({"x": 1})
        assert gln.pop_pending_broadcast() is True

    def test_pop_pending_clears_flag(self) -> None:
        gln.set_route({"x": 1})
        gln.pop_pending_broadcast()
        assert gln.pop_pending_broadcast() is False

    def test_pop_pending_after_clear(self) -> None:
        gln.clear_route()
        assert gln.pop_pending_broadcast() is True

    def test_no_pending_after_reset(self) -> None:
        gln.reset()
        assert gln.pop_pending_broadcast() is False


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------


class TestPayloads:
    def test_map_plot_route_valid(self) -> None:
        p = MapPlotRoutePayload(to_x=50_000.0, to_y=75_000.0)
        assert p.to_x == 50_000.0
        assert p.to_y == 75_000.0

    def test_map_plot_route_integer_coercion(self) -> None:
        p = MapPlotRoutePayload(to_x=50_000, to_y=75_000)
        assert isinstance(p.to_x, float)

    def test_map_clear_route_empty(self) -> None:
        p = MapClearRoutePayload()
        assert p is not None

    def test_map_capable_roles_includes_helm_captain(self) -> None:
        assert "captain" in gln.MAP_CAPABLE_ROLES
        assert "helm" in gln.MAP_CAPABLE_ROLES

    def test_map_capable_roles_count(self) -> None:
        # captain, helm, science, operations, comms, flight_ops
        assert len(gln.MAP_CAPABLE_ROLES) == 6
