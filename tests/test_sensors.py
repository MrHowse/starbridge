"""Tests for server/systems/sensors.py.

Covers: scan range calculation, scan start/cancel/reset, tick progress
increment (including sensor efficiency scaling), scan completion marking
enemy.scan_state, build_sensor_contacts (range filter + type strip for
unknowns + full details for scanned), and _compute_weakness heuristics.
"""
from __future__ import annotations

import pytest

from server.models.world import Enemy, World
from server.models.ship import Ship
from server.systems import sensors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_sensors():
    """Reset module-level scan state before each test."""
    sensors.reset()


def _make_world_with_enemy(dist: float = 5_000.0) -> tuple[World, Enemy, Ship]:
    """Return a World + one enemy + a default ship.

    The enemy is placed `dist` units north of the ship (sector centre).
    """
    world = World()
    ship = world.ship
    enemy = Enemy(
        id="enemy_1",
        type="scout",
        x=ship.x,
        y=ship.y - dist,
    )
    world.enemies.append(enemy)
    return world, enemy, ship


# ---------------------------------------------------------------------------
# Sensor range
# ---------------------------------------------------------------------------


def test_sensor_range_at_full_efficiency():
    _fresh_sensors()
    ship = Ship()
    assert sensors.sensor_range(ship) == pytest.approx(sensors.BASE_SENSOR_RANGE)


def test_sensor_range_halved_at_half_efficiency():
    _fresh_sensors()
    ship = Ship()
    ship.systems["sensors"].health = 50.0  # efficiency = 0.5
    expected = sensors.BASE_SENSOR_RANGE * 0.5
    assert sensors.sensor_range(ship) == pytest.approx(expected)


def test_sensor_range_zero_when_sensors_offline():
    _fresh_sensors()
    ship = Ship()
    ship.systems["sensors"].health = 0.0  # efficiency = 0.0
    assert sensors.sensor_range(ship) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Start / cancel / reset
# ---------------------------------------------------------------------------


def test_start_scan_sets_active_scan():
    _fresh_sensors()
    sensors.start_scan("enemy_1")
    result = sensors.get_scan_progress()
    assert result is not None
    entity_id, progress = result
    assert entity_id == "enemy_1"
    assert progress == pytest.approx(0.0)


def test_cancel_scan_clears_active_scan():
    _fresh_sensors()
    sensors.start_scan("enemy_1")
    sensors.cancel_scan()
    assert sensors.get_scan_progress() is None


def test_reset_clears_active_scan():
    _fresh_sensors()
    sensors.start_scan("enemy_1")
    sensors.reset()
    assert sensors.get_scan_progress() is None


def test_start_scan_replaces_existing_scan():
    _fresh_sensors()
    sensors.start_scan("enemy_1")
    sensors.start_scan("enemy_2")
    result = sensors.get_scan_progress()
    assert result is not None
    entity_id, _ = result
    assert entity_id == "enemy_2"


def test_no_active_scan_returns_none():
    _fresh_sensors()
    assert sensors.get_scan_progress() is None


# ---------------------------------------------------------------------------
# Tick — progress increment
# ---------------------------------------------------------------------------


def test_tick_advances_progress():
    _fresh_sensors()
    world, enemy, ship = _make_world_with_enemy()
    sensors.start_scan(enemy.id)

    completed = sensors.tick(world, ship, 1.0)  # 1 second, 100% efficiency

    result = sensors.get_scan_progress()
    assert result is not None
    _, progress = result
    # At 100% efficiency: progress_per_sec = 100 / BASE_SCAN_TIME
    expected_progress = 100.0 / sensors.BASE_SCAN_TIME
    assert progress == pytest.approx(expected_progress, rel=1e-3)
    assert completed == []  # not done yet


def test_tick_at_half_efficiency_is_slower():
    _fresh_sensors()
    world, enemy, ship = _make_world_with_enemy()
    ship.systems["sensors"].health = 50.0  # efficiency = 0.5
    sensors.start_scan(enemy.id)

    sensors.tick(world, ship, 1.0)

    result = sensors.get_scan_progress()
    assert result is not None
    _, progress = result
    # At 50% efficiency: progress_per_sec = 100 / (BASE_SCAN_TIME / 0.5) = 100 * 0.5 / BASE_SCAN_TIME
    expected = (100.0 / sensors.BASE_SCAN_TIME) * 0.5
    assert progress == pytest.approx(expected, rel=1e-3)


def test_tick_completes_scan_and_returns_entity_id():
    _fresh_sensors()
    world, enemy, ship = _make_world_with_enemy()
    sensors.start_scan(enemy.id)

    # Tick for enough seconds to complete: BASE_SCAN_TIME at 100% efficiency.
    completed = sensors.tick(world, ship, sensors.BASE_SCAN_TIME)

    assert enemy.id in completed
    assert sensors.get_scan_progress() is None  # cleared on completion


def test_tick_marks_enemy_scan_state_scanned():
    _fresh_sensors()
    world, enemy, ship = _make_world_with_enemy()
    assert enemy.scan_state == "unknown"
    sensors.start_scan(enemy.id)

    sensors.tick(world, ship, sensors.BASE_SCAN_TIME)

    assert enemy.scan_state == "scanned"


def test_tick_with_no_active_scan_returns_empty():
    _fresh_sensors()
    world, enemy, ship = _make_world_with_enemy()
    completed = sensors.tick(world, ship, 1.0)
    assert completed == []


def test_tick_caps_progress_at_100():
    _fresh_sensors()
    world, enemy, ship = _make_world_with_enemy()
    sensors.start_scan(enemy.id)

    # Tick for 3× the required time.
    sensors.tick(world, ship, sensors.BASE_SCAN_TIME * 3)

    # After completion scan is cleared, so get_scan_progress is None.
    assert sensors.get_scan_progress() is None
    assert enemy.scan_state == "scanned"


# ---------------------------------------------------------------------------
# build_sensor_contacts — range filtering
# ---------------------------------------------------------------------------


def test_contact_within_range_is_included():
    _fresh_sensors()
    world, enemy, ship = _make_world_with_enemy(dist=5_000.0)
    contacts = sensors.build_sensor_contacts(world, ship)
    assert len(contacts) == 1
    assert contacts[0]["id"] == enemy.id


def test_contact_beyond_sensor_range_still_included():
    """Distance filtering was removed — all enemies appear in contacts."""
    _fresh_sensors()
    world, enemy, ship = _make_world_with_enemy(dist=sensors.BASE_SENSOR_RANGE + 1_000.0)
    contacts = sensors.build_sensor_contacts(world, ship)
    assert len(contacts) == 1
    assert contacts[0]["id"] == enemy.id


def test_contacts_independent_of_sensor_efficiency():
    """All enemies included regardless of sensor efficiency (no range filter)."""
    _fresh_sensors()
    world, enemy, ship = _make_world_with_enemy(dist=20_000.0)
    ship.systems["sensors"].health = 50.0  # efficiency = 0.5

    contacts = sensors.build_sensor_contacts(world, ship)
    assert len(contacts) == 1

    ship.systems["sensors"].health = 100.0
    contacts = sensors.build_sensor_contacts(world, ship)
    assert len(contacts) == 1


# ---------------------------------------------------------------------------
# build_sensor_contacts — type stripping for unknowns
# ---------------------------------------------------------------------------


def test_unknown_contact_has_no_type_field():
    _fresh_sensors()
    world, enemy, ship = _make_world_with_enemy()
    assert enemy.scan_state == "unknown"

    contacts = sensors.build_sensor_contacts(world, ship)
    assert len(contacts) == 1
    assert "type" not in contacts[0]
    assert "hull" not in contacts[0]
    assert contacts[0]["scan_state"] == "unknown"


def test_scanned_contact_includes_full_details():
    _fresh_sensors()
    world, enemy, ship = _make_world_with_enemy()
    enemy.scan_state = "scanned"

    contacts = sensors.build_sensor_contacts(world, ship)
    c = contacts[0]
    assert c["scan_state"] == "scanned"
    assert "type" in c
    assert "hull" in c
    assert "hull_max" in c
    assert "shield_front" in c
    assert "shield_rear" in c


def test_scanned_contact_type_matches_enemy():
    _fresh_sensors()
    world, enemy, ship = _make_world_with_enemy()
    enemy.type = "cruiser"  # type: ignore[assignment]
    enemy.scan_state = "scanned"

    contacts = sensors.build_sensor_contacts(world, ship)
    assert contacts[0]["type"] == "cruiser"


# ---------------------------------------------------------------------------
# build_scan_result / _compute_weakness
# ---------------------------------------------------------------------------


def test_scan_result_weakness_rear_shields_compromised():
    _fresh_sensors()
    enemy = Enemy(id="e1", type="cruiser", x=0.0, y=0.0)
    enemy.shield_front = 80.0
    enemy.shield_rear = 10.0   # < 50% of 80

    result = sensors.build_scan_result(enemy)
    assert result["weakness"] is not None
    assert "rear" in result["weakness"].lower()


def test_scan_result_weakness_front_shields_critical():
    _fresh_sensors()
    enemy = Enemy(id="e1", type="cruiser", x=0.0, y=0.0)
    enemy.shield_front = 15.0
    enemy.shield_rear = 80.0

    result = sensors.build_scan_result(enemy)
    assert result["weakness"] is not None
    assert "forward" in result["weakness"].lower()


def test_scan_result_weakness_hull_critical():
    _fresh_sensors()
    from server.models.world import ENEMY_TYPE_PARAMS
    enemy = Enemy(id="e1", type="scout", x=0.0, y=0.0)
    max_hull = ENEMY_TYPE_PARAMS["scout"]["hull"]
    enemy.hull = max_hull * 0.2   # 20% of max = below 30% threshold
    enemy.shield_front = 50.0
    enemy.shield_rear = 30.0     # not < 50% of front

    result = sensors.build_scan_result(enemy)
    assert result["weakness"] is not None
    assert "hull" in result["weakness"].lower()


def test_scan_result_weakness_none_when_no_weakness():
    _fresh_sensors()
    enemy = Enemy(id="e1", type="cruiser", x=0.0, y=0.0)
    enemy.hull = 70.0       # at max for cruiser
    enemy.shield_front = 100.0
    enemy.shield_rear = 100.0

    result = sensors.build_scan_result(enemy)
    assert result["weakness"] is None
