"""Tests for v0.07 §1.7 — Sensor range per ship class.

Covers:
  - Per-class sensor range loaded from JSON
  - Ship model sensor_range_base default
  - sensor_range() uses ship.sensor_range_base
  - Difficulty multiplier still applies
  - Hazard modifier still applies
  - Save round-trip
"""
from __future__ import annotations

from pathlib import Path

import pytest

from server.models.ship import Ship
from server.models.ship_class import load_ship_class, SHIP_CLASS_ORDER
from server.systems.sensors import sensor_range, BASE_SENSOR_RANGE

SHIPS_DIR = Path(__file__).parent.parent / "ships"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ship(**overrides) -> Ship:
    ship = Ship()
    for k, v in overrides.items():
        setattr(ship, k, v)
    return ship


# ---------------------------------------------------------------------------
# §1.7 — Per-class JSON data correctness
# ---------------------------------------------------------------------------

EXPECTED_SENSOR_RANGE = {
    "scout":        40_000,
    "corvette":     35_000,
    "frigate":      30_000,
    "cruiser":      35_000,
    "battleship":   25_000,
    "carrier":      30_000,
    "medical_ship": 35_000,
}


@pytest.mark.parametrize("class_id", list(EXPECTED_SENSOR_RANGE.keys()))
def test_ship_class_json_has_sensors_section(class_id: str):
    """Each ship class JSON must contain a 'sensors' section."""
    sc = load_ship_class(class_id)
    assert sc.sensors is not None, f"{class_id} missing sensors section"


@pytest.mark.parametrize("class_id", list(EXPECTED_SENSOR_RANGE.keys()))
def test_ship_class_sensor_range_values(class_id: str):
    """Sensor range in JSON matches the spec."""
    sc = load_ship_class(class_id)
    expected = EXPECTED_SENSOR_RANGE[class_id]
    actual = sc.sensors["range"]
    assert actual == expected, f"{class_id}.sensors.range: expected {expected}, got {actual}"


# ---------------------------------------------------------------------------
# Ship model defaults
# ---------------------------------------------------------------------------

def test_ship_defaults_backward_compat():
    """Bare Ship() should have legacy-compatible sensor range."""
    s = Ship()
    assert s.sensor_range_base == 30_000.0  # matches BASE_SENSOR_RANGE


def test_base_sensor_range_constant_still_exists():
    """BASE_SENSOR_RANGE constant retained for backward compat."""
    assert BASE_SENSOR_RANGE == 30_000.0


# ---------------------------------------------------------------------------
# sensor_range() uses ship fields
# ---------------------------------------------------------------------------

def test_sensor_range_uses_ship_base():
    """sensor_range() uses ship.sensor_range_base instead of constant."""
    ship = _make_ship(sensor_range_base=40_000.0)
    r = sensor_range(ship)
    assert r == 40_000.0  # efficiency 1.0, no hazard, no difficulty mult


def test_sensor_range_scout_sees_further():
    """Scout (40k) has longer sensor range than battleship (25k)."""
    scout = _make_ship(sensor_range_base=40_000.0)
    battleship = _make_ship(sensor_range_base=25_000.0)
    assert sensor_range(scout) > sensor_range(battleship)


def test_sensor_range_efficiency_scaling():
    """Sensor efficiency scales the effective range."""
    ship = _make_ship(sensor_range_base=30_000.0)
    ship.systems["sensors"].power = 50.0  # efficiency = 0.5
    r = sensor_range(ship)
    assert abs(r - 15_000.0) < 1.0


def test_sensor_range_hazard_modifier():
    """Hazard modifier reduces effective range."""
    ship = _make_ship(sensor_range_base=30_000.0)
    r = sensor_range(ship, hazard_modifier=0.5)
    assert abs(r - 15_000.0) < 1.0


def test_sensor_range_difficulty_multiplier():
    """Difficulty sensor_range_multiplier applies."""
    from server.difficulty import get_preset
    ship = _make_ship(sensor_range_base=30_000.0)
    ship.difficulty = get_preset("cadet")  # sensor_range_multiplier=1.25
    r = sensor_range(ship)
    assert abs(r - 37_500.0) < 1.0


def test_sensor_range_all_multipliers():
    """All multipliers combine: base × efficiency × hazard × difficulty."""
    from server.difficulty import get_preset
    ship = _make_ship(sensor_range_base=40_000.0)
    ship.systems["sensors"].power = 50.0  # eff = 0.5
    ship.difficulty = get_preset("cadet")  # ×1.25
    r = sensor_range(ship, hazard_modifier=0.5)
    # 40000 × 0.5 × 0.5 × 1.25 = 12500
    assert abs(r - 12_500.0) < 1.0


# ---------------------------------------------------------------------------
# Spread across classes
# ---------------------------------------------------------------------------

def test_sensor_range_spread():
    """Sensor ranges span from 25k (battleship) to 40k (scout)."""
    ranges = list(EXPECTED_SENSOR_RANGE.values())
    assert min(ranges) == 25_000
    assert max(ranges) == 40_000


# ---------------------------------------------------------------------------
# Save round-trip
# ---------------------------------------------------------------------------

def test_sensor_range_serialise():
    """save_system serialises sensor_range_base."""
    from server.save_system import _serialise_ship
    ship = _make_ship(sensor_range_base=40_000.0)
    data = _serialise_ship(ship)
    assert data["sensor_range_base"] == 40_000.0


def test_sensor_range_deserialise():
    """save_system deserialises sensor_range_base."""
    from server.save_system import _serialise_ship, _deserialise_ship
    original = _make_ship(sensor_range_base=25_000.0)
    data = _serialise_ship(original)
    restored = Ship()
    _deserialise_ship(data, restored)
    assert restored.sensor_range_base == 25_000.0


def test_sensor_range_deserialise_old_save():
    """Old saves missing sensor_range_base get Ship default."""
    from server.save_system import _deserialise_ship
    ship = Ship()
    _deserialise_ship({}, ship)
    assert ship.sensor_range_base == 30_000.0


# ---------------------------------------------------------------------------
# Cross-class: all classes have sensors section
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("class_id", [
    c for c in SHIP_CLASS_ORDER
    if (SHIPS_DIR / f"{c}.json").exists()
])
def test_all_ship_classes_have_sensors(class_id: str):
    """Every ship class that exists as a JSON file has a sensors section."""
    sc = load_ship_class(class_id)
    assert sc.sensors is not None
