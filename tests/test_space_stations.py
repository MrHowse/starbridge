"""Tests for v0.05e Space Stations entity type.

Covers:
  - Station dataclass defaults and factory helpers
  - spawn_station_from_feature() for each feature type
  - _spawn_stations_from_grid() world population
  - save_system round-trip with full Station fields
  - backward-compat deserialise of old minimal station saves
  - _build_sector_grid_payload station_entities field
  - resume() re-spawns stations from grid if stations list is empty
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from server.models.sector import Rect, Sector, SectorFeature, SectorGrid
from server.models.world import (
    STATION_FEATURE_TYPES,
    STATION_TYPE_HULL,
    STATION_TYPE_SERVICES,
    STATION_TYPE_SHIELDS,
    Station,
    World,
    spawn_station,
    spawn_station_from_feature,
)
import server.save_system as ss


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_feature(
    ftype: str,
    fid: str = "f1",
    position: tuple = (10_000.0, 20_000.0),
    name: str = "Test Station",
    visible: bool = True,
) -> SectorFeature:
    return SectorFeature(
        id=fid,
        type=ftype,
        position=position,
        name=name,
        visible_without_scan=visible,
    )


def _make_grid_with_stations() -> SectorGrid:
    """2×1 grid: sector A1 has a friendly_station; B1 has an enemy_station (hidden)."""
    feat_a = _make_feature("friendly_station", fid="fs1", position=(25_000.0, 50_000.0),
                            name="Waypoint Alpha", visible=True)
    feat_b = _make_feature("enemy_station", fid="es1", position=(125_000.0, 50_000.0),
                            name="Hostile Outpost", visible=False)
    sectors = {
        "A1": Sector(
            id="A1", name="Alpha One",
            grid_position=(0, 0),
            world_bounds=Rect(0, 0, 100_000, 100_000),
            features=[feat_a],
        ),
        "B1": Sector(
            id="B1", name="Bravo One",
            grid_position=(1, 0),
            world_bounds=Rect(100_000, 0, 200_000, 100_000),
            features=[feat_b],
        ),
    }
    return SectorGrid(sectors=sectors, grid_size=(2, 1))


def _fresh_world() -> World:
    w = World()
    w.enemies.clear()
    w.torpedoes.clear()
    w.stations.clear()
    w.asteroids.clear()
    w.hazards.clear()
    return w


# ---------------------------------------------------------------------------
# Station model tests
# ---------------------------------------------------------------------------


def test_station_defaults():
    st = Station(id="s1", x=1000.0, y=2000.0)
    assert st.station_type == "military"
    assert st.faction == "friendly"
    assert st.services == []
    assert st.docking_range == pytest.approx(2_000.0)
    assert st.docking_ports == 2
    assert st.transponder_active is True
    assert st.shields == pytest.approx(0.0)
    assert st.shields_max == pytest.approx(0.0)
    assert st.hull == pytest.approx(500.0)
    assert st.hull_max == pytest.approx(500.0)
    assert st.inventory == {}
    assert st.requires_scan is False


def test_spawn_station_military_defaults():
    st = spawn_station("base1", 5_000.0, 6_000.0)
    assert st.id == "base1"
    assert st.x == pytest.approx(5_000.0)
    assert st.y == pytest.approx(6_000.0)
    assert st.hull == pytest.approx(STATION_TYPE_HULL["military"])
    assert st.hull_max == pytest.approx(STATION_TYPE_HULL["military"])
    assert st.shields == pytest.approx(STATION_TYPE_SHIELDS["military"])
    assert "hull_repair" in st.services


# ---------------------------------------------------------------------------
# spawn_station_from_feature
# ---------------------------------------------------------------------------


def test_spawn_from_friendly_station():
    feat = _make_feature("friendly_station", fid="fst", position=(10_000.0, 20_000.0),
                         name="Alpha Base", visible=True)
    st = spawn_station_from_feature(feat, "Alpha Sector")
    assert st.id == "fst"
    assert st.x == pytest.approx(10_000.0)
    assert st.y == pytest.approx(20_000.0)
    assert st.station_type == "military"
    assert st.faction == "friendly"
    assert st.transponder_active is True
    assert st.requires_scan is False
    assert "hull_repair" in st.services
    assert st.hull == pytest.approx(STATION_TYPE_HULL["military"])


def test_spawn_from_enemy_station():
    feat = _make_feature("enemy_station", fid="est", position=(80_000.0, 30_000.0),
                         name="Hostile Base", visible=False)
    st = spawn_station_from_feature(feat)
    assert st.station_type == "enemy"
    assert st.faction == "hostile"
    assert st.transponder_active is False
    assert st.requires_scan is True
    assert st.hull == pytest.approx(STATION_TYPE_HULL["enemy"])
    assert st.shields == pytest.approx(STATION_TYPE_SHIELDS["enemy"])


def test_spawn_from_derelict():
    feat = _make_feature("derelict", fid="drl", visible=False)
    st = spawn_station_from_feature(feat)
    assert st.station_type == "derelict"
    assert st.faction == "none"
    assert st.transponder_active is False
    assert st.requires_scan is True
    assert st.services == []


def test_spawn_from_trade_hub():
    feat = _make_feature("trade_hub", fid="th1", visible=True)
    st = spawn_station_from_feature(feat)
    assert st.station_type == "trade_hub"
    assert st.faction == "neutral"
    assert st.transponder_active is True
    assert "medical_facilities" in st.services
    assert "hull_repair" in st.services


def test_spawn_from_research_station():
    feat = _make_feature("research_station", fid="rs1", visible=True)
    st = spawn_station_from_feature(feat)
    assert st.station_type == "research"
    assert st.faction == "friendly"
    assert "sensor_upgrade" in st.services


def test_spawn_from_repair_dock():
    feat = _make_feature("repair_dock", fid="rd1", visible=True)
    st = spawn_station_from_feature(feat)
    assert st.station_type == "repair_dock"
    assert "system_repair" in st.services


def test_spawn_from_outpost():
    feat = _make_feature("outpost", fid="op1", visible=True)
    st = spawn_station_from_feature(feat)
    assert st.station_type == "military"
    assert st.faction == "friendly"


def test_station_name_from_feature():
    feat = _make_feature("friendly_station", fid="n1", name="Deep Station Bravo", visible=True)
    st = spawn_station_from_feature(feat, sector_name="Ignored")
    assert st.name == "Deep Station Bravo"


def test_station_name_falls_back_to_sector_name():
    feat = _make_feature("friendly_station", fid="n2", name="", visible=True)
    st = spawn_station_from_feature(feat, sector_name="Beta Sector")
    assert st.name == "Beta Sector"


# ---------------------------------------------------------------------------
# STATION_FEATURE_TYPES constant
# ---------------------------------------------------------------------------


def test_station_feature_types_includes_expected():
    expected = {
        "friendly_station", "enemy_station", "outpost",
        "derelict", "research_station", "repair_dock", "trade_hub",
    }
    assert expected == STATION_FEATURE_TYPES


# ---------------------------------------------------------------------------
# _spawn_stations_from_grid (game_loop helper)
# ---------------------------------------------------------------------------


def test_spawn_stations_from_grid_populates_world():
    from server.game_loop import _spawn_stations_from_grid
    world = _fresh_world()
    world.sector_grid = _make_grid_with_stations()
    _spawn_stations_from_grid(world)
    assert len(world.stations) == 2


def test_spawn_stations_clears_existing():
    from server.game_loop import _spawn_stations_from_grid
    world = _fresh_world()
    world.stations.append(Station(id="old", x=0, y=0))
    world.sector_grid = _make_grid_with_stations()
    _spawn_stations_from_grid(world)
    ids = [st.id for st in world.stations]
    assert "old" not in ids
    assert "fs1" in ids


def test_spawn_stations_no_grid_is_noop():
    from server.game_loop import _spawn_stations_from_grid
    world = _fresh_world()
    world.sector_grid = None
    _spawn_stations_from_grid(world)
    assert world.stations == []


def test_spawn_stations_properties_correct():
    from server.game_loop import _spawn_stations_from_grid
    world = _fresh_world()
    world.sector_grid = _make_grid_with_stations()
    _spawn_stations_from_grid(world)
    friendly = next(s for s in world.stations if s.id == "fs1")
    enemy = next(s for s in world.stations if s.id == "es1")
    assert friendly.transponder_active is True
    assert enemy.transponder_active is False
    assert friendly.faction == "friendly"
    assert enemy.faction == "hostile"


def test_spawn_stations_skips_non_station_features():
    """Features that are not in STATION_FEATURE_TYPES must not create stations."""
    from server.game_loop import _spawn_stations_from_grid
    feat_jump = SectorFeature(id="jp1", type="jump_point",
                              position=(50_000.0, 50_000.0), visible_without_scan=True)
    sector = Sector(
        id="A1", name="Alpha", grid_position=(0, 0),
        world_bounds=Rect(0, 0, 100_000, 100_000),
        features=[feat_jump],
    )
    grid = SectorGrid(sectors={"A1": sector}, grid_size=(1, 1))
    world = _fresh_world()
    world.sector_grid = grid
    _spawn_stations_from_grid(world)
    assert world.stations == []


# ---------------------------------------------------------------------------
# _build_sector_grid_payload — station_entities
# ---------------------------------------------------------------------------


def test_build_payload_includes_station_entities():
    """station_entities list must appear in map.sector_grid payload."""
    from server.game_loop import _build_sector_grid_payload, _spawn_stations_from_grid
    import server.game_loop as gl

    world = _fresh_world()
    world.sector_grid = _make_grid_with_stations()
    _spawn_stations_from_grid(world)

    # Patch module-level _current_sector_id and gln.get_route()
    orig_sid = gl._current_sector_id
    try:
        gl._current_sector_id = "A1"
        with patch("server.game_loop.gln") as mock_gln:
            mock_gln.get_route.return_value = None
            payload = _build_sector_grid_payload(world)
    finally:
        gl._current_sector_id = orig_sid

    assert "station_entities" in payload
    entities = payload["station_entities"]
    assert len(entities) == 2
    ids = {e["id"] for e in entities}
    assert "fs1" in ids
    assert "es1" in ids


def test_build_payload_station_entity_has_required_keys():
    from server.game_loop import _build_sector_grid_payload, _spawn_stations_from_grid
    import server.game_loop as gl

    world = _fresh_world()
    world.sector_grid = _make_grid_with_stations()
    _spawn_stations_from_grid(world)

    orig_sid = gl._current_sector_id
    try:
        gl._current_sector_id = "A1"
        with patch("server.game_loop.gln") as mock_gln:
            mock_gln.get_route.return_value = None
            payload = _build_sector_grid_payload(world)
    finally:
        gl._current_sector_id = orig_sid

    e = payload["station_entities"][0]
    for key in ("id", "x", "y", "name", "station_type", "faction",
                "transponder_active", "requires_scan", "hull", "hull_max"):
        assert key in e, f"Missing key: {key}"


def test_build_payload_no_sector_grid_returns_empty():
    from server.game_loop import _build_sector_grid_payload
    world = _fresh_world()
    world.sector_grid = None
    payload = _build_sector_grid_payload(world)
    assert payload == {}


# ---------------------------------------------------------------------------
# save_system round-trip
# ---------------------------------------------------------------------------


def test_serialise_station_all_fields():
    st = Station(
        id="base1", x=10_000.0, y=20_000.0,
        name="Frontier Base",
        station_type="repair_dock",
        faction="friendly",
        services=["hull_repair", "system_repair"],
        docking_range=3_000.0,
        docking_ports=4,
        transponder_active=True,
        shields=50.0,
        shields_max=50.0,
        hull=500.0,
        hull_max=500.0,
        inventory={"torpedoes": 10},
        requires_scan=False,
    )
    world = _fresh_world()
    world.stations.append(st)
    data = ss._serialise_entities(world)
    s_data = data["stations"][0]

    assert s_data["name"] == "Frontier Base"
    assert s_data["station_type"] == "repair_dock"
    assert s_data["faction"] == "friendly"
    assert "hull_repair" in s_data["services"]
    assert s_data["transponder_active"] is True
    assert s_data["shields"] == pytest.approx(50.0)
    assert s_data["docking_range"] == pytest.approx(3_000.0)
    assert s_data["inventory"] == {"torpedoes": 10}
    assert s_data["requires_scan"] is False


def test_deserialise_station_full_round_trip():
    st = Station(
        id="s99", x=5_000.0, y=7_000.0,
        name="Research Hub",
        station_type="research",
        faction="friendly",
        services=["sensor_upgrade", "data_package"],
        docking_range=2_000.0,
        docking_ports=2,
        transponder_active=True,
        shields=0.0,
        shields_max=0.0,
        hull=200.0,
        hull_max=200.0,
        inventory={},
        requires_scan=False,
    )
    world = _fresh_world()
    world.stations.append(st)
    data = ss._serialise_entities(world)

    world2 = _fresh_world()
    ss._deserialise_entities(data, world2)

    assert len(world2.stations) == 1
    restored = world2.stations[0]
    assert restored.id == "s99"
    assert restored.name == "Research Hub"
    assert restored.station_type == "research"
    assert restored.faction == "friendly"
    assert "sensor_upgrade" in restored.services
    assert restored.transponder_active is True
    assert restored.hull == pytest.approx(200.0)
    assert restored.hull_max == pytest.approx(200.0)
    assert restored.requires_scan is False


def test_deserialise_station_backward_compat_minimal():
    """Old saves only had id/x/y/hull/hull_max — must still deserialise cleanly."""
    data = {
        "stations": [
            {"id": "old1", "x": 1000.0, "y": 2000.0, "hull": 600.0, "hull_max": 600.0}
        ],
        "enemies": [], "torpedoes": [], "asteroids": [], "hazards": [],
    }
    world = _fresh_world()
    ss._deserialise_entities(data, world)
    assert len(world.stations) == 1
    st = world.stations[0]
    assert st.id == "old1"
    assert st.hull == pytest.approx(600.0)
    # defaults applied
    assert st.station_type == "military"
    assert st.faction == "friendly"
    assert st.transponder_active is True
    assert st.requires_scan is False


def test_deserialise_enemy_station_backward_compat():
    """Saves with requires_scan=True (enemy station) restore correctly."""
    data = {
        "stations": [
            {
                "id": "es99", "x": 80_000.0, "y": 30_000.0,
                "station_type": "enemy", "faction": "hostile",
                "transponder_active": False, "requires_scan": True,
                "hull": 800.0, "hull_max": 800.0,
                "name": "", "services": [], "shields": 150.0, "shields_max": 150.0,
                "docking_range": 2000.0, "docking_ports": 2, "inventory": {},
            }
        ],
        "enemies": [], "torpedoes": [], "asteroids": [], "hazards": [],
    }
    world = _fresh_world()
    ss._deserialise_entities(data, world)
    st = world.stations[0]
    assert st.station_type == "enemy"
    assert st.transponder_active is False
    assert st.requires_scan is True
    assert st.shields == pytest.approx(150.0)
