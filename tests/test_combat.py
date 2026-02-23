"""Tests for the combat system.

Covers:
  beam_in_arc — target in arc, out of arc, edge cases
  apply_hit_to_player — 4-facing shield absorption, hull damage, system damage roll
  apply_hit_to_enemy — hull and shield reduction
  regenerate_shields — heals per tick scaled by shield efficiency, caps per distribution
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from server.models.ship import Ship
from server.models.world import Enemy, spawn_enemy
from server.models.ship import TOTAL_SHIELD_CAPACITY
from server.systems.combat import (
    BEAM_PLAYER_ARC_DEG,
    HULL_SYSTEM_DAMAGE_CHANCE,
    SHIELD_ABSORPTION_COEFF,
    SHIELD_REGEN_PER_TICK,
    SYSTEM_DAMAGE_MAX,
    SYSTEM_DAMAGE_MIN,
    apply_hit_to_enemy,
    apply_hit_to_player,
    beam_in_arc,
    get_hit_facing,
    regenerate_shields,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ship(x: float = 0.0, y: float = 0.0, heading: float = 0.0) -> Ship:
    s = Ship()
    s.x = x
    s.y = y
    s.heading = heading
    return s


def make_enemy(x: float = 0.0, y: float = 0.0, heading: float = 0.0) -> Enemy:
    e = spawn_enemy("cruiser", x, y, "enemy_1")
    e.heading = heading
    return e


# ---------------------------------------------------------------------------
# beam_in_arc
# ---------------------------------------------------------------------------


def test_beam_in_arc_directly_ahead():
    assert beam_in_arc(0.0, 0.0, BEAM_PLAYER_ARC_DEG) is True


def test_beam_in_arc_at_positive_edge():
    assert beam_in_arc(0.0, BEAM_PLAYER_ARC_DEG, BEAM_PLAYER_ARC_DEG) is True


def test_beam_in_arc_at_negative_edge():
    assert beam_in_arc(0.0, 360.0 - BEAM_PLAYER_ARC_DEG, BEAM_PLAYER_ARC_DEG) is True


def test_beam_in_arc_just_outside_positive():
    assert beam_in_arc(0.0, BEAM_PLAYER_ARC_DEG + 1.0, BEAM_PLAYER_ARC_DEG) is False


def test_beam_in_arc_just_outside_negative():
    assert beam_in_arc(0.0, 360.0 - BEAM_PLAYER_ARC_DEG - 1.0, BEAM_PLAYER_ARC_DEG) is False


def test_beam_in_arc_wrap_around():
    # Shooter heading 350°, target bearing 10° — diff = 20° within ±45°.
    assert beam_in_arc(350.0, 10.0, BEAM_PLAYER_ARC_DEG) is True


def test_beam_in_arc_behind():
    # Target directly behind (180°) — outside arc.
    assert beam_in_arc(0.0, 180.0, BEAM_PLAYER_ARC_DEG) is False


# ---------------------------------------------------------------------------
# apply_hit_to_player — 4-facing shield absorption
# ---------------------------------------------------------------------------


def test_hit_from_fore_reduces_fore_shield():
    # Ship heading 0° (north). Attacker due north → bearing 0° → diff=0 → fore.
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    initial_fore = ship.shields.fore
    initial_aft  = ship.shields.aft
    damage = 10.0
    apply_hit_to_player(ship, damage, 0.0, -1_000.0)  # attacker north of ship
    assert ship.shields.fore < initial_fore, "Fore shield should absorb fore hit"
    assert ship.shields.aft == initial_aft, "Aft shield should be unchanged"


def test_hit_from_aft_reduces_aft_shield():
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    initial_aft  = ship.shields.aft
    initial_fore = ship.shields.fore
    damage = 10.0
    # Attacker due south = bearing 180° → diff=180 → aft hit.
    apply_hit_to_player(ship, damage, 0.0, 1_000.0)
    assert ship.shields.aft < initial_aft, "Aft shield should absorb aft hit"
    assert ship.shields.fore == initial_fore, "Fore shield unchanged for aft hit"


def test_hull_damage_when_shields_depleted():
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    ship.shields.fore = 0.0  # no fore shields
    initial_hull = ship.hull
    damage = 20.0

    # Force no system damage for clean hull test.
    mock_rng = MagicMock()
    mock_rng.random.return_value = 1.0  # above HULL_SYSTEM_DAMAGE_CHANCE → no system damage
    apply_hit_to_player(ship, damage, 0.0, -1_000.0, rng=mock_rng)

    assert ship.hull < initial_hull, "Hull should take damage when shields are 0"
    assert ship.hull == pytest.approx(initial_hull - damage)


def test_hull_damage_partial_shield_absorption():
    """With partial shields, hull takes the unabsorbed remainder."""
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    ship.shields.fore = 12.5  # can absorb 12.5 × 0.8 = 10 damage
    damage = 20.0

    mock_rng = MagicMock()
    mock_rng.random.return_value = 1.0  # no system damage
    apply_hit_to_player(ship, damage, 0.0, -1_000.0, rng=mock_rng)

    # absorbed = min(12.5 * 0.8, 20) = min(10, 20) = 10
    # hull_damage = 20 - 10 = 10
    assert ship.hull == pytest.approx(100.0 - 10.0)


def test_system_damage_on_hull_hit_when_rng_triggers():
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    ship.shields.fore = 0.0  # ensure hull damage
    damage = 20.0

    mock_rng = MagicMock()
    mock_rng.random.return_value = 0.0  # below HULL_SYSTEM_DAMAGE_CHANCE → triggers
    mock_rng.choice.return_value = "engines"
    mock_rng.uniform.return_value = 15.0

    result = apply_hit_to_player(ship, damage, 0.0, -1_000.0, rng=mock_rng)

    assert len(result.damaged_systems) == 1
    assert result.damaged_systems[0][0] == "engines"
    assert ship.systems["engines"].health == pytest.approx(100.0 - 15.0)


def test_no_system_damage_when_rng_suppresses():
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    ship.shields.fore = 0.0
    damage = 20.0

    mock_rng = MagicMock()
    mock_rng.random.return_value = 1.0  # above chance → no system damage

    result = apply_hit_to_player(ship, damage, 0.0, -1_000.0, rng=mock_rng)
    assert result.damaged_systems == []


def test_no_system_damage_when_hull_damage_is_zero():
    """If shields absorb the full hit, no hull damage → no system damage roll."""
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    ship.shields.fore = 50.0  # full fore shields (default distribution max)
    damage = 1.0  # tiny hit — absorbed fully by 50 × 0.8 = 40 capacity

    mock_rng = MagicMock()
    mock_rng.random.return_value = 0.0  # would trigger if called

    result = apply_hit_to_player(ship, damage, 0.0, -1_000.0, rng=mock_rng)
    # Hull damage = 1 - min(40, 1) = 0 → no system damage
    assert ship.hull == 100.0
    assert result.damaged_systems == []


def test_hull_does_not_go_below_zero():
    ship = make_ship()
    ship.shields.fore = 0.0
    ship.hull = 5.0

    mock_rng = MagicMock()
    mock_rng.random.return_value = 1.0  # no system damage
    apply_hit_to_player(ship, 100.0, 0.0, -1_000.0, rng=mock_rng)
    assert ship.hull == 0.0


# ---------------------------------------------------------------------------
# apply_hit_to_enemy
# ---------------------------------------------------------------------------


def test_apply_hit_to_enemy_reduces_hull():
    enemy = make_enemy(x=0.0, y=0.0, heading=0.0)
    enemy.shield_rear = 0.0   # no rear shields — all damage goes to hull
    initial_hull = enemy.hull
    # Attacker south of enemy (behind) → rear hit.
    apply_hit_to_enemy(enemy, 10.0, 0.0, 1_000.0)
    assert enemy.hull == pytest.approx(initial_hull - 10.0)


def test_apply_hit_to_enemy_front_shield_absorbs_front():
    enemy = make_enemy(x=0.0, y=0.0, heading=0.0)
    initial_front = enemy.shield_front
    initial_rear = enemy.shield_rear
    # Attacker north of enemy (in front).
    apply_hit_to_enemy(enemy, 10.0, 0.0, -1_000.0)
    assert enemy.shield_front < initial_front
    assert enemy.shield_rear == initial_rear


def test_apply_hit_to_enemy_hull_does_not_go_below_zero():
    enemy = make_enemy()
    enemy.shield_front = 0.0
    enemy.shield_rear = 0.0
    enemy.hull = 5.0
    apply_hit_to_enemy(enemy, 100.0, 0.0, 0.0)
    assert enemy.hull == 0.0


# ---------------------------------------------------------------------------
# regenerate_shields
# ---------------------------------------------------------------------------


def test_regenerate_shields_heals_all_facings():
    ship = make_ship()
    ship.shields.fore      = 30.0
    ship.shields.aft       = 20.0
    ship.shields.port      = 25.0
    ship.shields.starboard = 25.0
    ship.systems["shields"].power = 100.0  # efficiency = 1.0
    ship.systems["shields"].health = 100.0

    regenerate_shields(ship)

    expected_regen = SHIELD_REGEN_PER_TICK * 1.0
    assert ship.shields.fore      == pytest.approx(30.0 + expected_regen)
    assert ship.shields.aft       == pytest.approx(20.0 + expected_regen)
    assert ship.shields.port      == pytest.approx(25.0 + expected_regen)
    assert ship.shields.starboard == pytest.approx(25.0 + expected_regen)


def test_regenerate_shields_caps_at_distribution_max():
    # Centre distribution: max per facing = TOTAL_SHIELD_CAPACITY × 0.25 = 50.0
    ship = make_ship()
    cap = TOTAL_SHIELD_CAPACITY * 0.25  # 50.0
    ship.shields.fore      = cap - 0.1
    ship.shields.aft       = cap - 0.1
    ship.shields.port      = cap - 0.1
    ship.shields.starboard = cap - 0.1
    ship.systems["shields"].power = 100.0
    ship.systems["shields"].health = 100.0

    regenerate_shields(ship)

    assert ship.shields.fore      == pytest.approx(cap)
    assert ship.shields.aft       == pytest.approx(cap)
    assert ship.shields.port      == pytest.approx(cap)
    assert ship.shields.starboard == pytest.approx(cap)


def test_regenerate_shields_scaled_by_efficiency():
    ship = make_ship()
    ship.shields.fore = 20.0
    # Set efficiency to 0.5 (50% power, 100% health → efficiency = 0.5).
    ship.systems["shields"].power = 50.0
    ship.systems["shields"].health = 100.0

    regenerate_shields(ship)

    expected_regen = SHIELD_REGEN_PER_TICK * 0.5
    assert ship.shields.fore == pytest.approx(20.0 + expected_regen)


def test_regenerate_shields_zero_when_shields_offline():
    ship = make_ship()
    ship.shields.fore = 20.0
    ship.shields.aft  = 20.0
    ship.systems["shields"].power = 0.0
    ship.systems["shields"].health = 0.0

    regenerate_shields(ship)

    assert ship.shields.fore == 20.0  # no regen when efficiency = 0
    assert ship.shields.aft  == 20.0
