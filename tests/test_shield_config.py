"""Tests for v0.07 §1.6 — Shield configuration per ship class.

Covers:
  - Per-class shield stats loaded from JSON
  - Ship model shield_capacity / shield_recharge_rate defaults
  - tick_shields (regenerate_shields) uses ship fields
  - Shield capacity caps per-facing max HP
  - Recharge rate scaling
  - Shield initialisation at game start
  - Save round-trip
"""
from __future__ import annotations

from pathlib import Path

import pytest

from server.models.ship import Ship, Shields, TOTAL_SHIELD_CAPACITY
from server.models.ship_class import load_ship_class, SHIP_CLASS_ORDER
from server.systems.combat import regenerate_shields

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
# §1.6 — Per-class JSON data correctness
# ---------------------------------------------------------------------------

EXPECTED_SHIELDS = {
    "scout":        {"capacity": 40,  "recharge_rate": 8.0},
    "corvette":     {"capacity": 60,  "recharge_rate": 5.0},
    "frigate":      {"capacity": 80,  "recharge_rate": 5.0},
    "cruiser":      {"capacity": 120, "recharge_rate": 6.0},
    "battleship":   {"capacity": 200, "recharge_rate": 4.0},
    "carrier":      {"capacity": 150, "recharge_rate": 5.0},
    "medical_ship": {"capacity": 70,  "recharge_rate": 7.0},
}


@pytest.mark.parametrize("class_id", list(EXPECTED_SHIELDS.keys()))
def test_ship_class_json_has_shields_section(class_id: str):
    """Each ship class JSON must contain a 'shields' section."""
    sc = load_ship_class(class_id)
    assert sc.shields is not None, f"{class_id} missing shields section"


@pytest.mark.parametrize("class_id", list(EXPECTED_SHIELDS.keys()))
def test_ship_class_shield_values(class_id: str):
    """Shield stats in JSON match the spec."""
    sc = load_ship_class(class_id)
    expected = EXPECTED_SHIELDS[class_id]
    for key, val in expected.items():
        actual = sc.shields[key]
        assert actual == val, f"{class_id}.shields.{key}: expected {val}, got {actual}"


# ---------------------------------------------------------------------------
# Ship model defaults
# ---------------------------------------------------------------------------

def test_ship_defaults_backward_compat():
    """Bare Ship() should have legacy-compatible shield defaults."""
    s = Ship()
    assert s.shield_capacity == 200.0  # matches old TOTAL_SHIELD_CAPACITY
    assert s.shield_recharge_rate == 5.0  # matches old SHIELD_REGEN_PER_TICK * 10


def test_total_shield_capacity_constant_still_exists():
    """TOTAL_SHIELD_CAPACITY constant retained for backward compat."""
    assert TOTAL_SHIELD_CAPACITY == 200.0


# ---------------------------------------------------------------------------
# regenerate_shields uses ship fields
# ---------------------------------------------------------------------------

def test_regen_uses_ship_capacity():
    """Shield regen caps at ship.shield_capacity, not the old constant."""
    ship = _make_ship(
        shield_capacity=40.0,
        shield_recharge_rate=100.0,  # very fast — should cap in one tick
    )
    # Start with 0 shields on all facings.
    ship.shields = Shields(fore=0.0, aft=0.0, port=0.0, starboard=0.0)
    # Centre distribution: each facing gets 25% of capacity = 10 HP max.
    regenerate_shields(ship)
    assert ship.shields.fore <= 40.0 * 0.25  # max = 10
    assert ship.shields.fore > 0.0  # should have regenerated something


def test_regen_uses_ship_recharge_rate():
    """Shield regen rate comes from ship.shield_recharge_rate."""
    ship = _make_ship(
        shield_capacity=200.0,
        shield_recharge_rate=10.0,  # 10 HP/s → 1.0 HP/tick
    )
    ship.shields = Shields(fore=0.0, aft=0.0, port=0.0, starboard=0.0)
    regenerate_shields(ship)
    # At 10 HP/s, shields efficiency 1.0: regen = 10.0/10 = 1.0 HP/tick.
    # Distributed equally to all 4 facings.
    assert abs(ship.shields.fore - 1.0) < 0.01


def test_regen_scout_fast_recharge():
    """Scout (capacity=40, recharge=8) recharges faster than battleship."""
    scout = _make_ship(shield_capacity=40.0, shield_recharge_rate=8.0)
    scout.shields = Shields(fore=0.0, aft=0.0, port=0.0, starboard=0.0)

    battleship = _make_ship(shield_capacity=200.0, shield_recharge_rate=4.0)
    battleship.shields = Shields(fore=0.0, aft=0.0, port=0.0, starboard=0.0)

    # 100 ticks = 10 seconds.
    for _ in range(100):
        regenerate_shields(scout)
        regenerate_shields(battleship)

    # Scout should be at max (40 × 0.25 = 10 per facing).
    assert abs(scout.shields.fore - 10.0) < 0.01
    # Battleship at max would be 200 × 0.25 = 50. At 0.4 HP/tick it would
    # take 125 ticks. After 100 ticks it should still be under max.
    assert battleship.shields.fore < 50.0


def test_regen_respects_hazard_modifier():
    """Hazard modifier reduces regen rate."""
    ship = _make_ship(shield_capacity=200.0, shield_recharge_rate=10.0)
    ship.shields = Shields(fore=0.0, aft=0.0, port=0.0, starboard=0.0)
    regenerate_shields(ship, hazard_modifier=0.5)
    # regen = (10/10) * 1.0 * 0.5 = 0.5 HP/tick
    assert abs(ship.shields.fore - 0.5) < 0.01


def test_regen_respects_shield_efficiency():
    """Shield system efficiency scales regen."""
    ship = _make_ship(shield_capacity=200.0, shield_recharge_rate=10.0)
    ship.shields = Shields(fore=0.0, aft=0.0, port=0.0, starboard=0.0)
    ship.systems["shields"].power = 50.0  # efficiency = 0.5
    regenerate_shields(ship)
    # regen = (10/10) * 0.5 * 1.0 = 0.5 HP/tick
    assert abs(ship.shields.fore - 0.5) < 0.01


def test_regen_caps_at_facing_max():
    """Shield facing cannot exceed capacity × distribution fraction."""
    ship = _make_ship(shield_capacity=80.0, shield_recharge_rate=100.0)
    # Custom distribution: 50% fore, rest split.
    ship.shield_distribution = {"fore": 0.5, "aft": 0.2, "port": 0.15, "starboard": 0.15}
    ship.shields = Shields(fore=0.0, aft=0.0, port=0.0, starboard=0.0)
    # With very high recharge (100 HP/s = 10 HP/tick), many ticks fill all facings.
    for _ in range(100):
        regenerate_shields(ship)
    assert abs(ship.shields.fore - 40.0) < 0.01  # 80 × 0.5
    assert abs(ship.shields.aft - 16.0) < 0.01   # 80 × 0.2
    assert abs(ship.shields.port - 12.0) < 0.01  # 80 × 0.15


def test_shield_zero_recharge():
    """Zero recharge rate means shields don't regenerate."""
    ship = _make_ship(shield_capacity=100.0, shield_recharge_rate=0.0)
    ship.shields = Shields(fore=0.0, aft=0.0, port=0.0, starboard=0.0)
    regenerate_shields(ship)
    assert ship.shields.fore == 0.0


# ---------------------------------------------------------------------------
# Shield initialisation
# ---------------------------------------------------------------------------

def test_shield_init_matches_capacity():
    """At game start, shield facings should be initialised to capacity × distribution."""
    ship = _make_ship(shield_capacity=120.0)
    # Simulate game_loop.start() shield init.
    for facing in ("fore", "aft", "port", "starboard"):
        frac = ship.shield_distribution[facing]
        setattr(ship.shields, facing, ship.shield_capacity * frac)
    assert ship.shields.fore == 30.0  # 120 × 0.25
    assert ship.shields.aft == 30.0


# ---------------------------------------------------------------------------
# Spread across classes
# ---------------------------------------------------------------------------

def test_capacity_spread():
    """Shield capacities span from scout (40) to battleship (200) — 5× range."""
    capacities = {k: v["capacity"] for k, v in EXPECTED_SHIELDS.items()}
    assert min(capacities.values()) == 40
    assert max(capacities.values()) == 200


def test_recharge_spread():
    """Recharge rates span from battleship (4) to scout (8)."""
    rates = {k: v["recharge_rate"] for k, v in EXPECTED_SHIELDS.items()}
    assert min(rates.values()) == 4.0
    assert max(rates.values()) == 8.0


# ---------------------------------------------------------------------------
# Save round-trip
# ---------------------------------------------------------------------------

def test_shield_fields_serialise():
    """save_system serialises shield_capacity and shield_recharge_rate."""
    from server.save_system import _serialise_ship
    ship = _make_ship(shield_capacity=120.0, shield_recharge_rate=6.0)
    data = _serialise_ship(ship)
    assert data["shield_capacity"] == 120.0
    assert data["shield_recharge_rate"] == 6.0


def test_shield_fields_deserialise():
    """save_system deserialises shield_capacity and shield_recharge_rate."""
    from server.save_system import _serialise_ship, _deserialise_ship
    original = _make_ship(shield_capacity=40.0, shield_recharge_rate=8.0)
    data = _serialise_ship(original)
    restored = Ship()
    _deserialise_ship(data, restored)
    assert restored.shield_capacity == 40.0
    assert restored.shield_recharge_rate == 8.0


def test_shield_fields_deserialise_old_save():
    """Old saves missing shield fields get Ship defaults."""
    from server.save_system import _deserialise_ship
    ship = Ship()
    _deserialise_ship({}, ship)
    assert ship.shield_capacity == 200.0
    assert ship.shield_recharge_rate == 5.0


# ---------------------------------------------------------------------------
# Cross-class: all classes have shields section
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("class_id", [
    c for c in SHIP_CLASS_ORDER
    if (SHIPS_DIR / f"{c}.json").exists()
])
def test_all_ship_classes_have_shields(class_id: str):
    """Every ship class that exists as a JSON file has a shields section."""
    sc = load_ship_class(class_id)
    assert sc.shields is not None
