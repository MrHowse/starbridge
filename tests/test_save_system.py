"""
Tests for server/save_system.py — v0.04f.

Covers serialise/deserialise round-trips for ship, crew, interior, entities,
plus the public save_game / list_saves / load_save / restore_game API.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from server.models.ship import Ship, ShipSystem, Shields
from server.models.crew import CrewRoster, DeckCrew
from server.models.interior import ShipInterior, make_default_interior
from server.models.security import MarineSquad, Intruder
from server.models.world import World, Enemy, Torpedo, Station, Asteroid, Hazard
from server.difficulty import DifficultySettings

import server.save_system as ss


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_world() -> World:
    """World with minimal state; enemies/stations cleared for test isolation."""
    w = World()
    w.enemies.clear()
    w.torpedoes.clear()
    w.stations.clear()
    w.asteroids.clear()
    w.hazards.clear()
    return w


def _fresh_ship() -> Ship:
    """Ship with predictable state for round-trip tests."""
    s = Ship()
    s.x = 1234.5
    s.y = 5678.9
    s.heading = 45.0
    s.velocity = 250.0
    s.hull = 77.5
    s.shields.fore      = 80.0
    s.shields.aft       = 60.0
    s.shields.port      = 40.0
    s.shields.starboard = 45.0
    s.alert_level = "red"
    s.medical_supplies = 12
    return s


# ---------------------------------------------------------------------------
# Ship serialise / deserialise
# ---------------------------------------------------------------------------


def test_serialise_ship_basic_fields():
    ship = _fresh_ship()
    data = ss._serialise_ship(ship)
    assert data["x"] == pytest.approx(1234.5)
    assert data["y"] == pytest.approx(5678.9)
    assert data["heading"] == pytest.approx(45.0)
    assert data["hull"] == pytest.approx(77.5)
    assert data["alert_level"] == "red"
    assert data["medical_supplies"] == 12


def test_serialise_ship_shields():
    ship = _fresh_ship()
    data = ss._serialise_ship(ship)
    assert data["shields"]["fore"]      == pytest.approx(80.0)
    assert data["shields"]["aft"]       == pytest.approx(60.0)
    assert data["shields"]["port"]      == pytest.approx(40.0)
    assert data["shields"]["starboard"] == pytest.approx(45.0)


def test_serialise_ship_systems_include_captain_offline():
    ship = _fresh_ship()
    ship.systems["engines"]._captain_offline = True
    data = ss._serialise_ship(ship)
    assert data["systems"]["engines"]["_captain_offline"] is True


def test_deserialise_ship_restores_position_and_hull():
    ship = _fresh_ship()
    data = ss._serialise_ship(ship)
    target = Ship()
    ss._deserialise_ship(data, target)
    assert target.x == pytest.approx(1234.5)
    assert target.y == pytest.approx(5678.9)
    assert target.hull == pytest.approx(77.5)


def test_deserialise_ship_restores_shields():
    ship = _fresh_ship()
    data = ss._serialise_ship(ship)
    target = Ship()
    ss._deserialise_ship(data, target)
    assert target.shields.fore      == pytest.approx(80.0)
    assert target.shields.aft       == pytest.approx(60.0)
    assert target.shields.port      == pytest.approx(40.0)
    assert target.shields.starboard == pytest.approx(45.0)


def test_deserialise_ship_restores_alert_level():
    ship = _fresh_ship()
    data = ss._serialise_ship(ship)
    target = Ship()
    ss._deserialise_ship(data, target)
    assert target.alert_level == "red"


def test_deserialise_ship_restores_captain_offline():
    ship = _fresh_ship()
    ship.systems["beams"]._captain_offline = True
    data = ss._serialise_ship(ship)
    target = Ship()
    ss._deserialise_ship(data, target)
    assert target.systems["beams"]._captain_offline is True


def test_deserialise_ship_restores_difficulty():
    ship = _fresh_ship()
    ship.difficulty = DifficultySettings(
        enemy_damage_multiplier=2.0, puzzle_time_mult=0.5,
        sensor_range_multiplier=1.5, injury_chance=0.8,
        hints_enabled=True,
    )
    data = ss._serialise_ship(ship)
    target = Ship()
    ss._deserialise_ship(data, target)
    assert target.difficulty.enemy_damage_multiplier == pytest.approx(2.0)
    assert target.difficulty.hints_enabled is True


# ---------------------------------------------------------------------------
# Crew serialise / deserialise
# ---------------------------------------------------------------------------


def test_serialise_crew_has_all_decks():
    ship = Ship()
    data = ss._serialise_crew(ship.crew)
    assert "decks" in data
    assert len(data["decks"]) > 0


def test_crew_round_trip():
    ship = Ship()
    # Mutate one deck directly.
    first_deck = next(iter(ship.crew.decks.values()))
    first_deck.active  = 3
    first_deck.injured = 1
    first_deck.dead    = 1

    data = ss._serialise_crew(ship.crew)
    target = Ship()
    ss._deserialise_crew(data, target.crew)

    deck_name = first_deck.deck_name
    restored = target.crew.decks[deck_name]
    assert restored.active  == 3
    assert restored.injured == 1
    assert restored.dead    == 1


# ---------------------------------------------------------------------------
# Interior serialise / deserialise
# ---------------------------------------------------------------------------


def test_serialise_interior_room_states():
    interior = make_default_interior()
    first_room = next(iter(interior.rooms.values()))
    first_room.state = "damaged"
    data = ss._serialise_interior(interior)
    assert data["room_states"][first_room.id]["state"] == "damaged"


def test_interior_round_trip_door_sealed():
    interior = make_default_interior()
    first_room = next(iter(interior.rooms.values()))
    first_room.door_sealed = True
    data = ss._serialise_interior(interior)
    target = make_default_interior()
    ss._deserialise_interior(data, target)
    assert target.rooms[first_room.id].door_sealed is True


def test_interior_round_trip_marine_squads():
    interior = make_default_interior()
    sq = MarineSquad(id="sq1", room_id="conn", health=80.0, action_points=6.0, count=3)
    interior.marine_squads.append(sq)
    data = ss._serialise_interior(interior)
    target = make_default_interior()
    ss._deserialise_interior(data, target)
    assert len(target.marine_squads) == 1
    assert target.marine_squads[0].id == "sq1"
    assert target.marine_squads[0].count == 3


def test_interior_round_trip_intruders():
    interior = make_default_interior()
    intr = Intruder(id="i1", room_id="conn", objective_id="obj1", health=50.0)
    intr.move_timer = 12.5
    interior.intruders.append(intr)
    data = ss._serialise_interior(interior)
    target = make_default_interior()
    ss._deserialise_interior(data, target)
    assert len(target.intruders) == 1
    assert target.intruders[0].move_timer == pytest.approx(12.5)


# ---------------------------------------------------------------------------
# Entities serialise / deserialise
# ---------------------------------------------------------------------------


def test_entities_round_trip_enemies():
    world = _fresh_world()
    enemy = Enemy(id="e1", type="scout", x=100.0, y=200.0)
    enemy.hull = 55.0
    enemy.shield_frequency = "alpha"
    world.enemies.append(enemy)

    data = ss._serialise_entities(world)
    target = _fresh_world()
    ss._deserialise_entities(data, target)

    assert len(target.enemies) == 1
    assert target.enemies[0].hull == pytest.approx(55.0)
    assert target.enemies[0].shield_frequency == "alpha"


def test_entities_round_trip_torpedoes():
    world = _fresh_world()
    torp = Torpedo(id="t1", owner="player", x=0.0, y=0.0, heading=90.0, velocity=500.0)
    torp.torpedo_type = "emp"
    world.torpedoes.append(torp)

    data = ss._serialise_entities(world)
    target = _fresh_world()
    ss._deserialise_entities(data, target)

    assert len(target.torpedoes) == 1
    assert target.torpedoes[0].torpedo_type == "emp"


def test_entities_round_trip_hazards():
    world = _fresh_world()
    hazard = Hazard(id="h1", x=5000.0, y=6000.0, radius=2000.0,
                    hazard_type="nebula", label="Sigma Nebula")
    world.hazards.append(hazard)

    data = ss._serialise_entities(world)
    target = _fresh_world()
    ss._deserialise_entities(data, target)

    assert len(target.hazards) == 1
    assert target.hazards[0].label == "Sigma Nebula"


def test_entities_clears_on_deserialise():
    world = _fresh_world()
    enemy = Enemy(id="e1", type="scout", x=0.0, y=0.0)
    world.enemies.append(enemy)

    # Serialise with one enemy.
    data = ss._serialise_entities(world)

    # Target already has two enemies — they should be replaced.
    target = _fresh_world()
    target.enemies.append(Enemy(id="old1", type="cruiser", x=0.0, y=0.0))
    target.enemies.append(Enemy(id="old2", type="cruiser", x=0.0, y=0.0))
    ss._deserialise_entities(data, target)

    assert len(target.enemies) == 1
    assert target.enemies[0].id == "e1"


# ---------------------------------------------------------------------------
# save_game / list_saves / load_save / restore_game (file-system tests)
# ---------------------------------------------------------------------------


def _mock_modules():
    """Return a dict of module mocks that return minimal serialise() results."""
    empty = {}
    m = MagicMock()
    m.serialise.return_value = empty
    m.deserialise.return_value = None
    m.serialise_mission.return_value = {}
    m.deserialise_mission.return_value = None
    return m


@pytest.fixture()
def tmp_saves(tmp_path, monkeypatch):
    """Redirect SAVES_DIR to a temporary directory."""
    monkeypatch.setattr(ss, "SAVES_DIR", tmp_path)
    return tmp_path


def test_save_game_creates_file(tmp_saves):
    world = _fresh_world()
    with patch.multiple(
        "server.save_system",
        glw=_mock_modules(), glmed=_mock_modules(), gls=_mock_modules(),
        glfo=_mock_modules(), gldc=_mock_modules(), glco=_mock_modules(),
        glcap=_mock_modules(), gltr=_mock_modules(), glew=_mock_modules(),
        gltac=_mock_modules(), glm=_mock_modules(),
    ):
        save_id = ss.save_game(world, "first_contact", "officer", "frigate", 500)

    assert (tmp_saves / f"{save_id}.json").exists()


def test_save_game_returns_save_id(tmp_saves):
    world = _fresh_world()
    with patch.multiple(
        "server.save_system",
        glw=_mock_modules(), glmed=_mock_modules(), gls=_mock_modules(),
        glfo=_mock_modules(), gldc=_mock_modules(), glco=_mock_modules(),
        glcap=_mock_modules(), gltr=_mock_modules(), glew=_mock_modules(),
        gltac=_mock_modules(), glm=_mock_modules(),
    ):
        save_id = ss.save_game(world, "first_contact", "officer", "frigate", 100)

    assert "first_contact" in save_id


def test_save_game_file_contains_metadata(tmp_saves):
    world = _fresh_world()
    with patch.multiple(
        "server.save_system",
        glw=_mock_modules(), glmed=_mock_modules(), gls=_mock_modules(),
        glfo=_mock_modules(), gldc=_mock_modules(), glco=_mock_modules(),
        glcap=_mock_modules(), gltr=_mock_modules(), glew=_mock_modules(),
        gltac=_mock_modules(), glm=_mock_modules(),
    ):
        save_id = ss.save_game(world, "defend_station", "admiral", "cruiser", 250)

    data = json.loads((tmp_saves / f"{save_id}.json").read_text())
    assert data["mission_id"] == "defend_station"
    assert data["difficulty_preset"] == "admiral"
    assert data["ship_class"] == "cruiser"
    assert data["tick_count"] == 250


def test_list_saves_empty_dir(tmp_saves):
    result = ss.list_saves()
    assert result == []


def test_list_saves_returns_entries(tmp_saves):
    # Write two fake save files.
    for i, ts in enumerate(["2026-02-21T10:00:00", "2026-02-21T11:00:00"]):
        path = tmp_saves / f"save_{i}.json"
        path.write_text(json.dumps({
            "save_id": f"save_{i}",
            "saved_at": ts,
            "mission_id": "test",
            "ship_class": "frigate",
            "difficulty_preset": "officer",
            "tick_count": i * 100,
        }))

    result = ss.list_saves()
    assert len(result) == 2


def test_list_saves_sorted_newest_first(tmp_saves):
    for ts, name in [("2026-02-21T09:00:00", "old"), ("2026-02-21T12:00:00", "new")]:
        (tmp_saves / f"{name}.json").write_text(json.dumps({
            "save_id": name, "saved_at": ts,
            "mission_id": "test", "ship_class": "frigate",
            "difficulty_preset": "officer", "tick_count": 0,
        }))

    result = ss.list_saves()
    assert result[0]["save_id"] == "new"
    assert result[1]["save_id"] == "old"


def test_load_save_returns_dict(tmp_saves):
    (tmp_saves / "mysave.json").write_text(json.dumps({"save_id": "mysave", "mission_id": "test"}))
    data = ss.load_save("mysave")
    assert data["mission_id"] == "test"


def test_load_save_raises_for_missing(tmp_saves):
    with pytest.raises(FileNotFoundError):
        ss.load_save("nonexistent")


def test_restore_game_returns_metadata(tmp_saves):
    world = _fresh_world()

    # Write a minimal save file with ship and entity data.
    save_data = {
        "save_id": "r1",
        "saved_at": "2026-02-21T10:00:00",
        "mission_id": "search_rescue",
        "difficulty_preset": "commander",
        "ship_class": "corvette",
        "tick_count": 750,
        "ship": ss._serialise_ship(world.ship),
        "entities": ss._serialise_entities(world),
        "modules": {"game_state": {}},
    }
    (tmp_saves / "r1.json").write_text(json.dumps(save_data))

    with patch.multiple(
        "server.save_system",
        glw=_mock_modules(), glmed=_mock_modules(), gls=_mock_modules(),
        glfo=_mock_modules(), gldc=_mock_modules(), glco=_mock_modules(),
        glcap=_mock_modules(), gltr=_mock_modules(), glew=_mock_modules(),
        gltac=_mock_modules(), glm=_mock_modules(),
    ):
        result = ss.restore_game("r1", world)

    assert result["mission_id"] == "search_rescue"
    assert result["difficulty_preset"] == "commander"
    assert result["ship_class"] == "corvette"
    assert result["tick_count"] == 750


def test_restore_game_restores_ship_hull(tmp_saves):
    world = _fresh_world()
    world.ship.hull = 42.5

    save_data = {
        "save_id": "r2",
        "saved_at": "2026-02-21T10:00:00",
        "mission_id": "sandbox",
        "difficulty_preset": "officer",
        "ship_class": "frigate",
        "tick_count": 0,
        "ship": ss._serialise_ship(world.ship),
        "entities": ss._serialise_entities(world),
        "modules": {"game_state": {}},
    }
    (tmp_saves / "r2.json").write_text(json.dumps(save_data))

    # Reset hull before restoring.
    world.ship.hull = 100.0

    with patch.multiple(
        "server.save_system",
        glw=_mock_modules(), glmed=_mock_modules(), gls=_mock_modules(),
        glfo=_mock_modules(), gldc=_mock_modules(), glco=_mock_modules(),
        glcap=_mock_modules(), gltr=_mock_modules(), glew=_mock_modules(),
        gltac=_mock_modules(), glm=_mock_modules(),
    ):
        ss.restore_game("r2", world)

    assert world.ship.hull == pytest.approx(42.5)


def test_restore_game_not_found_raises(tmp_saves):
    with pytest.raises(FileNotFoundError):
        ss.restore_game("no_such_save", _fresh_world())
