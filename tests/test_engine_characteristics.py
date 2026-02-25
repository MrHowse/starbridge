"""Tests for v0.07 §1.8 — Engine characteristics per ship class.

Covers:
  - Per-class fuel_multiplier loaded from JSON
  - Ship model fuel_multiplier default
  - Spread across classes
  - Save round-trip
"""
from __future__ import annotations

from pathlib import Path

import pytest

from server.models.ship import Ship
from server.models.ship_class import load_ship_class, SHIP_CLASS_ORDER

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
# §1.8 — Per-class JSON data correctness
# ---------------------------------------------------------------------------

EXPECTED_FUEL_MULT = {
    "scout":        1.5,
    "corvette":     0.7,
    "frigate":      1.0,
    "cruiser":      0.8,
    "battleship":   1.8,
    "carrier":      1.0,
    "medical_ship": 0.75,
}


@pytest.mark.parametrize("class_id", list(EXPECTED_FUEL_MULT.keys()))
def test_ship_class_json_has_engines_section(class_id: str):
    """Each ship class JSON must contain an 'engines' section."""
    sc = load_ship_class(class_id)
    assert sc.engines is not None, f"{class_id} missing engines section"


@pytest.mark.parametrize("class_id", list(EXPECTED_FUEL_MULT.keys()))
def test_ship_class_fuel_multiplier_values(class_id: str):
    """Fuel multiplier in JSON matches the spec."""
    sc = load_ship_class(class_id)
    expected = EXPECTED_FUEL_MULT[class_id]
    actual = sc.engines["fuel_multiplier"]
    assert actual == expected, f"{class_id}.engines.fuel_multiplier: expected {expected}, got {actual}"


# ---------------------------------------------------------------------------
# Ship model defaults
# ---------------------------------------------------------------------------

def test_ship_defaults_backward_compat():
    """Bare Ship() should have baseline fuel_multiplier."""
    s = Ship()
    assert s.fuel_multiplier == 1.0


# ---------------------------------------------------------------------------
# Spread across classes
# ---------------------------------------------------------------------------

def test_fuel_multiplier_spread():
    """Fuel multipliers range from efficient (0.7) to thirsty (1.8)."""
    values = list(EXPECTED_FUEL_MULT.values())
    assert min(values) == 0.7
    assert max(values) == 1.8


def test_frigate_baseline():
    """Frigate is the 1.0x baseline."""
    sc = load_ship_class("frigate")
    assert sc.engines["fuel_multiplier"] == 1.0


def test_corvette_most_efficient():
    """Corvette has the lowest fuel consumption."""
    assert EXPECTED_FUEL_MULT["corvette"] == min(EXPECTED_FUEL_MULT.values())


def test_battleship_most_thirsty():
    """Battleship has the highest fuel consumption."""
    assert EXPECTED_FUEL_MULT["battleship"] == max(EXPECTED_FUEL_MULT.values())


# ---------------------------------------------------------------------------
# Save round-trip
# ---------------------------------------------------------------------------

def test_fuel_multiplier_serialise():
    """save_system serialises fuel_multiplier."""
    from server.save_system import _serialise_ship
    ship = _make_ship(fuel_multiplier=1.5)
    data = _serialise_ship(ship)
    assert data["fuel_multiplier"] == 1.5


def test_fuel_multiplier_deserialise():
    """save_system deserialises fuel_multiplier."""
    from server.save_system import _serialise_ship, _deserialise_ship
    original = _make_ship(fuel_multiplier=0.7)
    data = _serialise_ship(original)
    restored = Ship()
    _deserialise_ship(data, restored)
    assert restored.fuel_multiplier == 0.7


def test_fuel_multiplier_deserialise_old_save():
    """Old saves missing fuel_multiplier get Ship default."""
    from server.save_system import _deserialise_ship
    ship = Ship()
    _deserialise_ship({}, ship)
    assert ship.fuel_multiplier == 1.0


# ---------------------------------------------------------------------------
# Cross-class: all classes have engines section
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("class_id", [
    c for c in SHIP_CLASS_ORDER
    if (SHIPS_DIR / f"{c}.json").exists()
])
def test_all_ship_classes_have_engines(class_id: str):
    """Every ship class that exists as a JSON file has an engines section."""
    sc = load_ship_class(class_id)
    assert sc.engines is not None
