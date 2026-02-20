"""Tests for server/models/ship.py — Ship and ShipSystem defaults and derived values."""
from __future__ import annotations

import pytest

from server.models.ship import Ship, ShipSystem, Shields


# ---------------------------------------------------------------------------
# ShipSystem.efficiency
# ---------------------------------------------------------------------------


def test_ship_system_full_power_and_health():
    s = ShipSystem(name="engines")
    assert s.efficiency == pytest.approx(1.0)


def test_ship_system_half_power():
    s = ShipSystem(name="engines", power=50.0)
    assert s.efficiency == pytest.approx(0.5)


def test_ship_system_half_health():
    s = ShipSystem(name="engines", health=50.0)
    assert s.efficiency == pytest.approx(0.5)


def test_ship_system_half_power_half_health():
    s = ShipSystem(name="engines", power=50.0, health=50.0)
    assert s.efficiency == pytest.approx(0.25)


def test_ship_system_overclock_efficiency_above_one():
    # Power can go to 150 — efficiency scales proportionally
    s = ShipSystem(name="engines", power=150.0)
    assert s.efficiency == pytest.approx(1.5)


def test_ship_system_zero_health_zero_efficiency():
    s = ShipSystem(name="engines", health=0.0)
    assert s.efficiency == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Shields defaults
# ---------------------------------------------------------------------------


def test_shields_defaults():
    sh = Shields()
    assert sh.front == pytest.approx(100.0)
    assert sh.rear == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Ship defaults
# ---------------------------------------------------------------------------


def test_ship_default_name():
    ship = Ship()
    assert ship.name == "TSS Endeavour"


def test_ship_default_position_is_sector_centre():
    ship = Ship()
    assert ship.x == pytest.approx(50_000.0)
    assert ship.y == pytest.approx(50_000.0)


def test_ship_default_heading_zero():
    ship = Ship()
    assert ship.heading == pytest.approx(0.0)
    assert ship.target_heading == pytest.approx(0.0)


def test_ship_default_velocity_and_throttle_zero():
    ship = Ship()
    assert ship.velocity == pytest.approx(0.0)
    assert ship.throttle == pytest.approx(0.0)


def test_ship_default_hull_full():
    ship = Ship()
    assert ship.hull == pytest.approx(100.0)


def test_ship_has_seven_systems():
    ship = Ship()
    expected = {"engines", "beams", "torpedoes", "shields", "sensors", "manoeuvring", "flight_deck"}
    assert set(ship.systems.keys()) == expected


def test_ship_all_systems_start_at_full_efficiency():
    ship = Ship()
    for name, system in ship.systems.items():
        assert system.efficiency == pytest.approx(1.0), f"{name} efficiency not 1.0"


def test_ship_systems_are_independent_instances():
    ship = Ship()
    ship.systems["engines"].power = 50.0
    assert ship.systems["manoeuvring"].power == pytest.approx(100.0)
