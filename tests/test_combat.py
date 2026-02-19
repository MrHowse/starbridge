"""Tests for the combat system.

Covers:
  beam_in_arc — target in arc, out of arc, edge cases
  apply_hit_to_player — front/rear shield absorption, hull damage, system damage roll
  apply_hit_to_enemy — hull and shield reduction
  regenerate_shields — heals per tick scaled by shield efficiency, caps at 100
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from server.models.ship import Ship
from server.models.world import Enemy, spawn_enemy
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
# apply_hit_to_player — front shield absorbs front hit
# ---------------------------------------------------------------------------


def test_hit_from_front_reduces_front_shield():
    # Attacker south of ship (y+) bearing 180° from ship heading 0°.
    # angle_diff(0, 180) = 180 → abs = 180 >= 90 → rear!
    # Wait: ship faces north (heading 0), attacker is south.
    # bearing_to(0,0, 0, 1000) = atan2(0-0, 0-1000) = atan2(0, -1000) = 180°.
    # angle_diff(0, 180) = 180; abs=180 >= 90 → rear hit.
    # So to test front hit: attacker must be in front (north of ship).
    # bearing_to(0,0, 0, -1000) = atan2(0, 1000) = 0° (north).
    # angle_diff(0, 0) = 0 < 90 → front hit.
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    initial_front = ship.shields.front
    initial_rear = ship.shields.rear
    damage = 10.0
    apply_hit_to_player(ship, damage, 0.0, -1_000.0)  # attacker north of ship
    assert ship.shields.front < initial_front, "Front shield should absorb front hit"
    assert ship.shields.rear == initial_rear, "Rear shield should be unchanged"


def test_hit_from_rear_reduces_rear_shield():
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    initial_rear = ship.shields.rear
    initial_front = ship.shields.front
    damage = 10.0
    # Attacker south = bearing 180° → rear hit.
    apply_hit_to_player(ship, damage, 0.0, 1_000.0)
    assert ship.shields.rear < initial_rear, "Rear shield should absorb rear hit"
    assert ship.shields.front == initial_front, "Front shield unchanged for rear hit"


def test_hull_damage_when_shields_depleted():
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    ship.shields.front = 0.0  # no front shields
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
    ship.shields.front = 12.5  # can absorb 12.5 × 0.8 = 10 damage
    damage = 20.0

    mock_rng = MagicMock()
    mock_rng.random.return_value = 1.0  # no system damage
    apply_hit_to_player(ship, damage, 0.0, -1_000.0, rng=mock_rng)

    # absorbed = min(12.5 * 0.8, 20) = min(10, 20) = 10
    # hull_damage = 20 - 10 = 10
    assert ship.hull == pytest.approx(100.0 - 10.0)


def test_system_damage_on_hull_hit_when_rng_triggers():
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    ship.shields.front = 0.0  # ensure hull damage
    damage = 20.0

    mock_rng = MagicMock()
    mock_rng.random.return_value = 0.0  # below HULL_SYSTEM_DAMAGE_CHANCE → triggers
    mock_rng.choice.return_value = "engines"
    mock_rng.uniform.return_value = 15.0

    result = apply_hit_to_player(ship, damage, 0.0, -1_000.0, rng=mock_rng)

    assert len(result) == 1
    assert result[0][0] == "engines"
    assert ship.systems["engines"].health == pytest.approx(100.0 - 15.0)


def test_no_system_damage_when_rng_suppresses():
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    ship.shields.front = 0.0
    damage = 20.0

    mock_rng = MagicMock()
    mock_rng.random.return_value = 1.0  # above chance → no system damage

    result = apply_hit_to_player(ship, damage, 0.0, -1_000.0, rng=mock_rng)
    assert result == []


def test_no_system_damage_when_hull_damage_is_zero():
    """If shields absorb the full hit, no hull damage → no system damage roll."""
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    ship.shields.front = 100.0  # full shields
    damage = 1.0  # tiny hit — absorbed fully by 100 × 0.8 = 80 capacity

    mock_rng = MagicMock()
    mock_rng.random.return_value = 0.0  # would trigger if called

    result = apply_hit_to_player(ship, damage, 0.0, -1_000.0, rng=mock_rng)
    # Hull damage = 1 - min(80, 1) = 0 → no system damage
    assert ship.hull == 100.0
    assert result == []


def test_hull_does_not_go_below_zero():
    ship = make_ship()
    ship.shields.front = 0.0
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


def test_regenerate_shields_heals_both_hemispheres():
    ship = make_ship()
    ship.shields.front = 80.0
    ship.shields.rear = 70.0
    ship.systems["shields"].power = 100.0  # efficiency = 1.0
    ship.systems["shields"].health = 100.0

    regenerate_shields(ship)

    expected_regen = SHIELD_REGEN_PER_TICK * 1.0
    assert ship.shields.front == pytest.approx(80.0 + expected_regen)
    assert ship.shields.rear == pytest.approx(70.0 + expected_regen)


def test_regenerate_shields_caps_at_100():
    ship = make_ship()
    ship.shields.front = 99.9
    ship.shields.rear = 99.9
    ship.systems["shields"].power = 100.0
    ship.systems["shields"].health = 100.0

    regenerate_shields(ship)

    assert ship.shields.front == 100.0
    assert ship.shields.rear == 100.0


def test_regenerate_shields_scaled_by_efficiency():
    ship = make_ship()
    ship.shields.front = 50.0
    ship.shields.rear = 50.0
    # Set efficiency to 0.5 (50% power, 100% health → efficiency = 0.5).
    ship.systems["shields"].power = 50.0
    ship.systems["shields"].health = 100.0

    regenerate_shields(ship)

    expected_regen = SHIELD_REGEN_PER_TICK * 0.5
    assert ship.shields.front == pytest.approx(50.0 + expected_regen)


def test_regenerate_shields_zero_when_shields_offline():
    ship = make_ship()
    ship.shields.front = 50.0
    ship.shields.rear = 50.0
    ship.systems["shields"].power = 0.0
    ship.systems["shields"].health = 0.0

    regenerate_shields(ship)

    assert ship.shields.front == 50.0  # no regen when efficiency = 0
    assert ship.shields.rear == 50.0
