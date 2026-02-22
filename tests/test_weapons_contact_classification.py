"""Tests for weapons contact classification features (v0.06).

Covers:
  - sensors.build_sensor_contacts: kind + classification fields on enemies,
    stations, and creatures; station transponder gating.
  - game_loop_weapons.try_select_target: friendly lock denial stored in
    _pending_targeting_denials; non-friendly contacts allowed.
  - game_loop_weapons.pop_targeting_denials: returns and clears the list.
  - game_loop_weapons._classify_target: enemy → hostile/unknown, station
    faction mapping, creature → unknown.
"""
from __future__ import annotations

import pytest

from server.models.world import Enemy, World, Station, Creature, spawn_creature
from server.models.ship import Ship
from server.systems import sensors
import server.game_loop_weapons as glw


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh() -> None:
    sensors.reset()
    glw.reset()


def _ship_at_origin() -> Ship:
    return World().ship


def _world_with_enemy(faction_note: str = "hostile") -> tuple[World, Enemy]:
    """One scout enemy at (0, 5000) relative to ship, unscanned."""
    world = World()
    enemy = Enemy(id="e1", type="scout", x=world.ship.x, y=world.ship.y - 5_000)
    world.enemies.append(enemy)
    return world, enemy


def _world_with_station(faction: str = "hostile", transponder: bool = True) -> tuple[World, Station]:
    world = World()
    station = Station(
        id="s1",
        name="Alpha Base",
        station_type="military",
        faction=faction,
        x=world.ship.x,
        y=world.ship.y - 5_000,
        transponder_active=transponder,
    )
    world.stations.append(station)
    return world, station


def _world_with_creature() -> tuple[World, Creature]:
    world = World()
    creature = spawn_creature("c1", "void_whale", world.ship.x, world.ship.y - 5_000)
    creature.detected = True
    world.creatures.append(creature)
    return world, creature


# ---------------------------------------------------------------------------
# sensors.build_sensor_contacts — kind + classification on enemies
# ---------------------------------------------------------------------------


def test_enemy_contact_has_kind_enemy():
    _fresh()
    world, enemy = _world_with_enemy()
    contacts = sensors.build_sensor_contacts(world, world.ship)
    assert contacts[0]["kind"] == "enemy"


def test_unscanned_enemy_classification_is_unknown():
    _fresh()
    world, enemy = _world_with_enemy()
    assert enemy.scan_state == "unknown"
    contacts = sensors.build_sensor_contacts(world, world.ship)
    assert contacts[0]["classification"] == "unknown"


def test_scanned_enemy_classification_is_hostile():
    _fresh()
    world, enemy = _world_with_enemy()
    enemy.scan_state = "scanned"
    contacts = sensors.build_sensor_contacts(world, world.ship)
    assert contacts[0]["classification"] == "hostile"


# ---------------------------------------------------------------------------
# sensors.build_sensor_contacts — stations
# ---------------------------------------------------------------------------


def test_hostile_station_in_range_included():
    _fresh()
    world, station = _world_with_station(faction="hostile")
    contacts = sensors.build_sensor_contacts(world, world.ship)
    ids = [c["id"] for c in contacts]
    assert "s1" in ids


def test_friendly_station_with_transponder_included():
    _fresh()
    world, station = _world_with_station(faction="friendly", transponder=True)
    contacts = sensors.build_sensor_contacts(world, world.ship)
    assert any(c["id"] == "s1" for c in contacts)


def test_friendly_station_no_transponder_excluded():
    _fresh()
    world, station = _world_with_station(faction="friendly", transponder=False)
    contacts = sensors.build_sensor_contacts(world, world.ship)
    assert not any(c["id"] == "s1" for c in contacts)


def test_neutral_station_with_transponder_included():
    _fresh()
    world, station = _world_with_station(faction="neutral", transponder=True)
    contacts = sensors.build_sensor_contacts(world, world.ship)
    assert any(c["id"] == "s1" for c in contacts)


def test_station_contact_has_kind_station():
    _fresh()
    world, station = _world_with_station(faction="hostile")
    contacts = sensors.build_sensor_contacts(world, world.ship)
    sc = next(c for c in contacts if c["id"] == "s1")
    assert sc["kind"] == "station"


def test_hostile_station_classification_hostile():
    _fresh()
    world, station = _world_with_station(faction="hostile")
    contacts = sensors.build_sensor_contacts(world, world.ship)
    sc = next(c for c in contacts if c["id"] == "s1")
    assert sc["classification"] == "hostile"


def test_friendly_station_classification_friendly():
    _fresh()
    world, station = _world_with_station(faction="friendly", transponder=True)
    contacts = sensors.build_sensor_contacts(world, world.ship)
    sc = next(c for c in contacts if c["id"] == "s1")
    assert sc["classification"] == "friendly"


def test_neutral_station_classification_neutral():
    _fresh()
    world, station = _world_with_station(faction="neutral", transponder=True)
    contacts = sensors.build_sensor_contacts(world, world.ship)
    sc = next(c for c in contacts if c["id"] == "s1")
    assert sc["classification"] == "neutral"


def test_station_contact_includes_hull_and_name():
    _fresh()
    world, station = _world_with_station(faction="hostile")
    contacts = sensors.build_sensor_contacts(world, world.ship)
    sc = next(c for c in contacts if c["id"] == "s1")
    assert "hull" in sc
    assert "hull_max" in sc
    assert sc["name"] == "Alpha Base"


# ---------------------------------------------------------------------------
# sensors.build_sensor_contacts — creatures
# ---------------------------------------------------------------------------


def test_creature_contact_has_kind_creature():
    _fresh()
    world, creature = _world_with_creature()
    contacts = sensors.build_sensor_contacts(world, world.ship)
    cc = next((c for c in contacts if c["id"] == "c1"), None)
    assert cc is not None
    assert cc["kind"] == "creature"


def test_creature_classification_is_unknown():
    _fresh()
    world, creature = _world_with_creature()
    contacts = sensors.build_sensor_contacts(world, world.ship)
    cc = next(c for c in contacts if c["id"] == "c1")
    assert cc["classification"] == "unknown"


def test_undetected_creature_excluded():
    _fresh()
    world, creature = _world_with_creature()
    creature.detected = False
    contacts = sensors.build_sensor_contacts(world, world.ship)
    assert not any(c["id"] == "c1" for c in contacts)


# ---------------------------------------------------------------------------
# game_loop_weapons._classify_target
# ---------------------------------------------------------------------------


def test_classify_enemy_unscanned_is_hostile():
    """_classify_target returns 'hostile' for enemies regardless of scan state.
    (Sensor contacts display 'unknown' for unscanned enemies, but targeting
    classification always treats enemies as hostile — they can be targeted.)
    """
    _fresh()
    world, enemy = _world_with_enemy()
    assert glw._classify_target(world, "e1") == "hostile"


def test_classify_enemy_scanned_is_hostile():
    _fresh()
    world, enemy = _world_with_enemy()
    enemy.scan_state = "scanned"
    assert glw._classify_target(world, "e1") == "hostile"


def test_classify_hostile_station_is_hostile():
    _fresh()
    world, station = _world_with_station(faction="hostile")
    assert glw._classify_target(world, "s1") == "hostile"


def test_classify_friendly_station_is_friendly():
    _fresh()
    world, station = _world_with_station(faction="friendly")
    assert glw._classify_target(world, "s1") == "friendly"


def test_classify_neutral_station_is_neutral():
    _fresh()
    world, station = _world_with_station(faction="neutral")
    assert glw._classify_target(world, "s1") == "neutral"


def test_classify_unknown_entity_id_is_unknown():
    _fresh()
    world = World()
    assert glw._classify_target(world, "nonexistent") == "unknown"


def test_classify_none_entity_id_is_unknown():
    _fresh()
    world = World()
    assert glw._classify_target(world, None) == "unknown"


# ---------------------------------------------------------------------------
# game_loop_weapons.try_select_target
# ---------------------------------------------------------------------------


def test_try_select_hostile_target_succeeds():
    _fresh()
    world, enemy = _world_with_enemy()
    enemy.scan_state = "scanned"
    denial = glw.try_select_target("e1", world)
    assert denial is None
    assert glw.get_target() == "e1"


def test_try_select_unknown_target_succeeds():
    _fresh()
    world, enemy = _world_with_enemy()
    assert enemy.scan_state == "unknown"
    denial = glw.try_select_target("e1", world)
    assert denial is None
    assert glw.get_target() == "e1"


def test_try_select_friendly_station_returns_denial():
    _fresh()
    world, station = _world_with_station(faction="friendly")
    denial = glw.try_select_target("s1", world)
    assert denial is not None
    assert denial["denied"] is True
    assert denial["entity_id"] == "s1"


def test_try_select_friendly_does_not_set_target():
    _fresh()
    world, station = _world_with_station(faction="friendly")
    glw.try_select_target("s1", world)
    assert glw.get_target() is None


def test_try_select_neutral_station_succeeds():
    _fresh()
    world, station = _world_with_station(faction="neutral")
    denial = glw.try_select_target("s1", world)
    assert denial is None
    assert glw.get_target() == "s1"


def test_try_select_none_clears_target():
    _fresh()
    world, enemy = _world_with_enemy()
    glw.set_target("e1")
    denial = glw.try_select_target(None, world)
    assert denial is None
    assert glw.get_target() is None


# ---------------------------------------------------------------------------
# game_loop_weapons.pop_targeting_denials
# ---------------------------------------------------------------------------


def test_pop_targeting_denials_empty_initially():
    _fresh()
    assert glw.pop_targeting_denials() == []


def test_pop_targeting_denials_returns_denial_after_friendly_lock():
    _fresh()
    world, station = _world_with_station(faction="friendly")
    glw.try_select_target("s1", world)
    denials = glw.pop_targeting_denials()
    assert len(denials) == 1
    assert denials[0]["entity_id"] == "s1"


def test_pop_targeting_denials_clears_list():
    _fresh()
    world, station = _world_with_station(faction="friendly")
    glw.try_select_target("s1", world)
    glw.pop_targeting_denials()
    assert glw.pop_targeting_denials() == []


def test_pop_targeting_denials_cleared_by_reset():
    _fresh()
    world, station = _world_with_station(faction="friendly")
    glw.try_select_target("s1", world)
    glw.reset()
    assert glw.pop_targeting_denials() == []
