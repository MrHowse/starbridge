"""Tests for the sector system (server/models/sector.py) — v0.05b."""
from __future__ import annotations

import pytest

from server.models.sector import (
    PatrolRoute,
    Rect,
    Sector,
    SectorFeature,
    SectorGrid,
    SectorProperties,
    SectorVisibility,
    _sector_grid_from_dict,
    load_sector_grid,
)
from server.models.world import World


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_grid_2x2() -> SectorGrid:
    """Minimal 2×2 grid used by most unit tests."""
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


def _make_grid_3x3() -> SectorGrid:
    """3×3 grid used for adjacency tests."""
    sectors: dict = {}
    for col in range(3):
        for row in range(3):
            sid = f"{chr(65+col)}{row+1}"
            sectors[sid] = Sector(
                id=sid,
                name=sid,
                grid_position=(col, row),
                world_bounds=Rect(
                    col * 100_000, row * 100_000,
                    (col + 1) * 100_000, (row + 1) * 100_000,
                ),
            )
    return SectorGrid(sectors=sectors, grid_size=(3, 3))


# ---------------------------------------------------------------------------
# Rect
# ---------------------------------------------------------------------------


class TestRect:
    def test_contains_interior(self) -> None:
        r = Rect(0, 0, 100_000, 100_000)
        assert r.contains(50_000, 50_000)

    def test_contains_left_edge(self) -> None:
        r = Rect(0, 0, 100_000, 100_000)
        assert r.contains(0, 50_000)

    def test_contains_top_edge(self) -> None:
        r = Rect(0, 0, 100_000, 100_000)
        assert r.contains(50_000, 0)

    def test_does_not_contain_right_edge(self) -> None:
        """Right and bottom edges belong to the next sector."""
        r = Rect(0, 0, 100_000, 100_000)
        assert not r.contains(100_000, 50_000)

    def test_does_not_contain_bottom_edge(self) -> None:
        r = Rect(0, 0, 100_000, 100_000)
        assert not r.contains(50_000, 100_000)

    def test_does_not_contain_outside(self) -> None:
        r = Rect(0, 0, 100_000, 100_000)
        assert not r.contains(150_000, 50_000)


# ---------------------------------------------------------------------------
# SectorProperties defaults
# ---------------------------------------------------------------------------


class TestSectorProperties:
    def test_defaults(self) -> None:
        p = SectorProperties()
        assert p.type == "deep_space"
        assert p.sensor_modifier == 1.0
        assert p.navigation_hazard == "none"
        assert p.faction == "unclaimed"
        assert p.threat_level == "low"


# ---------------------------------------------------------------------------
# SectorGrid — spatial queries
# ---------------------------------------------------------------------------


class TestSectorAtPosition:
    def test_finds_a1(self) -> None:
        grid = _make_grid_2x2()
        s = grid.sector_at_position(50_000, 50_000)
        assert s is not None and s.id == "A1"

    def test_finds_b1(self) -> None:
        grid = _make_grid_2x2()
        s = grid.sector_at_position(150_000, 50_000)
        assert s is not None and s.id == "B1"

    def test_finds_a2(self) -> None:
        grid = _make_grid_2x2()
        s = grid.sector_at_position(50_000, 150_000)
        assert s is not None and s.id == "A2"

    def test_finds_b2(self) -> None:
        grid = _make_grid_2x2()
        s = grid.sector_at_position(150_000, 150_000)
        assert s is not None and s.id == "B2"

    def test_outside_grid_returns_none(self) -> None:
        grid = _make_grid_2x2()
        assert grid.sector_at_position(999_999, 999_999) is None

    def test_negative_coords_return_none(self) -> None:
        grid = _make_grid_2x2()
        assert grid.sector_at_position(-1, 50_000) is None


# ---------------------------------------------------------------------------
# SectorGrid — adjacency
# ---------------------------------------------------------------------------


class TestAdjacentSectors:
    def test_corner_has_three_neighbours(self) -> None:
        """A1 at [0,0] is a corner — only 3 neighbours."""
        grid = _make_grid_3x3()
        adj = {s.id for s in grid.adjacent_sectors("A1")}
        assert adj == {"B1", "A2", "B2"}

    def test_edge_has_five_neighbours(self) -> None:
        """B1 at [1,0] is a top edge — 5 neighbours."""
        grid = _make_grid_3x3()
        adj = {s.id for s in grid.adjacent_sectors("B1")}
        assert adj == {"A1", "C1", "A2", "B2", "C2"}

    def test_center_has_eight_neighbours(self) -> None:
        """B2 at [1,1] is the centre of a 3×3 — 8 neighbours."""
        grid = _make_grid_3x3()
        adj = {s.id for s in grid.adjacent_sectors("B2")}
        assert len(adj) == 8

    def test_unknown_sector_returns_empty(self) -> None:
        grid = _make_grid_3x3()
        assert grid.adjacent_sectors("Z9") == []


# ---------------------------------------------------------------------------
# SectorGrid — visibility management
# ---------------------------------------------------------------------------


class TestVisibility:
    def test_default_visibility_unknown(self) -> None:
        grid = _make_grid_2x2()
        for s in grid.sectors.values():
            assert s.visibility == SectorVisibility.UNKNOWN

    def test_set_visibility(self) -> None:
        grid = _make_grid_2x2()
        grid.set_visibility("A1", SectorVisibility.SCANNED)
        assert grid.sectors["A1"].visibility == SectorVisibility.SCANNED

    def test_set_visibility_unknown_sector_is_noop(self) -> None:
        grid = _make_grid_2x2()
        grid.set_visibility("Z9", SectorVisibility.ACTIVE)  # should not raise

    def test_update_ship_position_sets_active(self) -> None:
        grid = _make_grid_2x2()
        sid = grid.update_ship_position(50_000, 50_000)
        assert sid == "A1"
        assert grid.sectors["A1"].visibility == SectorVisibility.ACTIVE

    def test_update_ship_position_outside_returns_none(self) -> None:
        grid = _make_grid_2x2()
        assert grid.update_ship_position(999_999, 999_999) is None

    def test_on_sector_leave_active_to_visited(self) -> None:
        grid = _make_grid_2x2()
        grid.sectors["A1"].visibility = SectorVisibility.ACTIVE
        grid.on_sector_leave("A1")
        assert grid.sectors["A1"].visibility == SectorVisibility.VISITED

    def test_on_sector_leave_non_active_unchanged(self) -> None:
        """Leaving a non-Active sector (e.g. Scanned) must not change it."""
        grid = _make_grid_2x2()
        grid.sectors["A1"].visibility = SectorVisibility.SCANNED
        grid.on_sector_leave("A1")
        assert grid.sectors["A1"].visibility == SectorVisibility.SCANNED

    def test_on_sector_leave_unknown_sector_is_noop(self) -> None:
        grid = _make_grid_2x2()
        grid.on_sector_leave("Z9")  # should not raise

    def test_update_already_active_no_change(self) -> None:
        """Calling update_ship_position for an already-Active sector is idempotent."""
        grid = _make_grid_2x2()
        grid.sectors["A1"].visibility = SectorVisibility.ACTIVE
        grid.update_ship_position(50_000, 50_000)
        assert grid.sectors["A1"].visibility == SectorVisibility.ACTIVE


# ---------------------------------------------------------------------------
# Transponder auto-reveal
# ---------------------------------------------------------------------------


class TestTransponderReveal:
    def test_friendly_station_reveals_sector(self) -> None:
        grid = _make_grid_2x2()
        grid.sectors["A1"].features.append(
            SectorFeature(
                id="home_station", type="friendly_station",
                position=(50_000, 50_000), name="Home", visible_without_scan=True,
            )
        )
        grid.apply_transponder_reveals()
        assert grid.sectors["A1"].visibility == SectorVisibility.TRANSPONDER

    def test_non_broadcasting_feature_does_not_reveal(self) -> None:
        grid = _make_grid_2x2()
        grid.sectors["A1"].features.append(
            SectorFeature(
                id="hidden_station", type="friendly_station",
                position=(50_000, 50_000), name="Hidden", visible_without_scan=False,
            )
        )
        grid.apply_transponder_reveals()
        assert grid.sectors["A1"].visibility == SectorVisibility.UNKNOWN

    def test_enemy_station_does_not_reveal(self) -> None:
        grid = _make_grid_2x2()
        grid.sectors["A1"].features.append(
            SectorFeature(
                id="enemy", type="enemy_station",
                position=(50_000, 50_000), visible_without_scan=True,
            )
        )
        grid.apply_transponder_reveals()
        assert grid.sectors["A1"].visibility == SectorVisibility.UNKNOWN

    def test_already_visible_sector_not_downgraded(self) -> None:
        """A SCANNED sector with a transponder stays SCANNED (not demoted to TRANSPONDER)."""
        grid = _make_grid_2x2()
        grid.sectors["A1"].visibility = SectorVisibility.SCANNED
        grid.sectors["A1"].features.append(
            SectorFeature(
                id="s", type="friendly_station",
                position=(50_000, 50_000), visible_without_scan=True,
            )
        )
        grid.apply_transponder_reveals()
        assert grid.sectors["A1"].visibility == SectorVisibility.SCANNED

    def test_transponder_type_also_reveals(self) -> None:
        grid = _make_grid_2x2()
        grid.sectors["B2"].features.append(
            SectorFeature(
                id="beacon", type="transponder",
                position=(150_000, 150_000), visible_without_scan=True,
            )
        )
        grid.apply_transponder_reveals()
        assert grid.sectors["B2"].visibility == SectorVisibility.TRANSPONDER


# ---------------------------------------------------------------------------
# Serialisation round-trip
# ---------------------------------------------------------------------------


class TestSerialisation:
    def test_serialise_all_unknown(self) -> None:
        grid = _make_grid_2x2()
        data = grid.serialise()
        assert set(data.keys()) == {"A1", "B1", "A2", "B2"}
        assert all(v == "unknown" for v in data.values())

    def test_serialise_mixed_visibility(self) -> None:
        grid = _make_grid_2x2()
        grid.sectors["A1"].visibility = SectorVisibility.ACTIVE
        grid.sectors["B1"].visibility = SectorVisibility.VISITED
        data = grid.serialise()
        assert data["A1"] == "active"
        assert data["B1"] == "visited"
        assert data["A2"] == "unknown"

    def test_deserialise_round_trip(self) -> None:
        grid = _make_grid_2x2()
        grid.sectors["A1"].visibility = SectorVisibility.ACTIVE
        grid.sectors["B2"].visibility = SectorVisibility.SURVEYED
        snapshot = grid.serialise()

        grid2 = _make_grid_2x2()
        grid2.deserialise_visibility(snapshot)
        assert grid2.sectors["A1"].visibility == SectorVisibility.ACTIVE
        assert grid2.sectors["B2"].visibility == SectorVisibility.SURVEYED
        assert grid2.sectors["A2"].visibility == SectorVisibility.UNKNOWN

    def test_deserialise_unknown_sector_skipped(self) -> None:
        grid = _make_grid_2x2()
        grid.deserialise_visibility({"Z9": "active"})  # should not raise

    def test_deserialise_invalid_value_skipped(self) -> None:
        grid = _make_grid_2x2()
        grid.deserialise_visibility({"A1": "invalid_state"})  # should not raise
        assert grid.sectors["A1"].visibility == SectorVisibility.UNKNOWN


# ---------------------------------------------------------------------------
# JSON loading
# ---------------------------------------------------------------------------


class TestLoadSectorGrid:
    def test_load_standard_grid(self) -> None:
        grid = load_sector_grid("standard_grid")
        assert grid.grid_size == (5, 5)
        assert len(grid.sectors) == 25
        assert grid.layout_id == "standard_grid"

    def test_load_exploration_grid(self) -> None:
        grid = load_sector_grid("exploration_grid")
        assert grid.grid_size == (8, 8)
        assert len(grid.sectors) == 64
        assert grid.layout_id == "exploration_grid"

    def test_missing_layout_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_sector_grid("no_such_layout")

    def test_standard_grid_has_all_sector_ids(self) -> None:
        grid = load_sector_grid("standard_grid")
        for col, letter in enumerate("ABCDE"):
            for row in range(1, 6):
                assert f"{letter}{row}" in grid.sectors

    def test_standard_grid_sector_at_origin(self) -> None:
        """The default gameplay world (100k×100k) maps to A1."""
        grid = load_sector_grid("standard_grid")
        s = grid.sector_at_position(50_000, 50_000)
        assert s is not None and s.id == "A1"

    def test_standard_grid_properties_parsed(self) -> None:
        grid = load_sector_grid("standard_grid")
        a1 = grid.sectors["A1"]
        assert a1.properties.type == "friendly_space"
        assert a1.properties.faction == "imperial"

    def test_standard_grid_features_parsed(self) -> None:
        grid = load_sector_grid("standard_grid")
        a1 = grid.sectors["A1"]
        assert len(a1.features) == 1
        f = a1.features[0]
        assert f.type == "friendly_station"
        assert f.visible_without_scan is True

    def test_standard_grid_transponder_reveal(self) -> None:
        """A1 and B2 have friendly stations → TRANSPONDER after apply."""
        grid = load_sector_grid("standard_grid")
        grid.apply_transponder_reveals()
        assert grid.sectors["A1"].visibility == SectorVisibility.TRANSPONDER
        assert grid.sectors["B2"].visibility == SectorVisibility.TRANSPONDER
        # A sector without transponders stays unknown.
        assert grid.sectors["C1"].visibility == SectorVisibility.UNKNOWN

    def test_standard_grid_adjacency(self) -> None:
        """A1 (corner) has exactly 3 neighbours in the 5×5 grid."""
        grid = load_sector_grid("standard_grid")
        adj = {s.id for s in grid.adjacent_sectors("A1")}
        assert adj == {"B1", "A2", "B2"}

    def test_standard_grid_centre_adjacency(self) -> None:
        """C3 (centre) has 8 neighbours."""
        grid = load_sector_grid("standard_grid")
        adj = grid.adjacent_sectors("C3")
        assert len(adj) == 8

    def test_patrol_routes_parsed(self) -> None:
        grid = load_sector_grid("standard_grid")
        b1 = grid.sectors["B1"]
        assert len(b1.patrol_routes) == 1
        pr = b1.patrol_routes[0]
        assert isinstance(pr, PatrolRoute)
        assert pr.faction == "imperial"
        assert pr.ship_count == 2


# ---------------------------------------------------------------------------
# World integration
# ---------------------------------------------------------------------------


class TestWorldIntegration:
    def test_world_sector_grid_defaults_none(self) -> None:
        w = World()
        assert w.sector_grid is None

    def test_world_accepts_sector_grid(self) -> None:
        grid = load_sector_grid("standard_grid")
        w = World()
        w.sector_grid = grid
        assert w.sector_grid is grid
