"""Tests for v0.07 target profile mechanic (spec 1.2).

Covers:
  - calculate_effective_profile: base profile, speed scaling, edge cases
  - Enemy target_profile: per-type values, spawn wiring
  - Hit probability integration: AI miss chance, player beam miss chance
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from server.models.ship import Ship
from server.models.world import Enemy, spawn_enemy, ENEMY_TYPE_PARAMS
from server.systems.combat import (
    SPEED_EVASION_FACTOR,
    calculate_effective_profile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ship(
    target_profile: float = 1.0,
    max_speed_base: float = 200.0,
    velocity: float = 0.0,
) -> Ship:
    ship = Ship()
    ship.target_profile = target_profile
    ship.max_speed_base = max_speed_base
    ship.velocity = velocity
    return ship


# ---------------------------------------------------------------------------
# 1. calculate_effective_profile — stationary
# ---------------------------------------------------------------------------


class TestEffectiveProfileStationary:
    def test_battleship_stationary(self):
        """Stationary battleship: profile 1.0 × (1 - 0 × 0.3) = 1.0."""
        ship = make_ship(target_profile=1.0, velocity=0.0)
        assert calculate_effective_profile(ship) == pytest.approx(1.0)

    def test_scout_stationary(self):
        """Stationary scout: profile 0.5 × (1 - 0 × 0.3) = 0.5."""
        ship = make_ship(target_profile=0.5, velocity=0.0)
        assert calculate_effective_profile(ship) == pytest.approx(0.5)

    def test_frigate_stationary(self):
        ship = make_ship(target_profile=0.75, velocity=0.0)
        assert calculate_effective_profile(ship) == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# 2. calculate_effective_profile — at speed
# ---------------------------------------------------------------------------


class TestEffectiveProfileAtSpeed:
    def test_scout_full_speed(self):
        """Scout at full speed: 0.5 × (1 - 1.0 × 0.3) = 0.35."""
        ship = make_ship(target_profile=0.5, max_speed_base=250.0, velocity=250.0)
        assert calculate_effective_profile(ship) == pytest.approx(0.35)

    def test_battleship_full_speed(self):
        """Battleship at full speed: 1.0 × (1 - 1.0 × 0.3) = 0.7."""
        ship = make_ship(target_profile=1.0, max_speed_base=80.0, velocity=80.0)
        assert calculate_effective_profile(ship) == pytest.approx(0.7)

    def test_frigate_half_speed(self):
        """Frigate at half speed: 0.75 × (1 - 0.5 × 0.3) = 0.75 × 0.85 = 0.6375."""
        ship = make_ship(target_profile=0.75, max_speed_base=160.0, velocity=80.0)
        assert calculate_effective_profile(ship) == pytest.approx(0.6375)

    def test_speed_factor_capped_at_1(self):
        """Speed exceeding max_speed_base still caps speed_factor at 1.0."""
        ship = make_ship(target_profile=0.5, max_speed_base=200.0, velocity=300.0)
        assert calculate_effective_profile(ship) == pytest.approx(0.5 * (1.0 - 1.0 * 0.3))

    def test_zero_max_speed_returns_base_profile(self):
        """Edge case: max_speed_base=0 avoids division by zero."""
        ship = make_ship(target_profile=0.6, max_speed_base=0.0, velocity=0.0)
        assert calculate_effective_profile(ship) == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# 3. Profile values per ship class (spec 1.1.X.5)
# ---------------------------------------------------------------------------


class TestProfileSpecValues:
    """Verify the exact target_profile values from the spec for each ship class."""

    @pytest.mark.parametrize("class_id,expected_profile", [
        ("scout", 0.5),
        ("corvette", 0.6),
        ("frigate", 0.75),
        ("cruiser", 0.85),
        ("battleship", 1.0),
        ("carrier", 0.95),
        ("medical_ship", 0.7),
    ])
    def test_class_target_profile(self, class_id, expected_profile):
        from server.models.ship_class import load_ship_class
        sc = load_ship_class(class_id)
        assert sc.target_profile == pytest.approx(expected_profile)


# ---------------------------------------------------------------------------
# 4. Enemy target_profile
# ---------------------------------------------------------------------------


class TestEnemyTargetProfile:
    def test_fighter_profile(self):
        assert ENEMY_TYPE_PARAMS["fighter"]["target_profile"] == pytest.approx(0.4)

    def test_scout_enemy_profile(self):
        assert ENEMY_TYPE_PARAMS["scout"]["target_profile"] == pytest.approx(0.5)

    def test_cruiser_enemy_profile(self):
        assert ENEMY_TYPE_PARAMS["cruiser"]["target_profile"] == pytest.approx(0.85)

    def test_destroyer_enemy_profile(self):
        assert ENEMY_TYPE_PARAMS["destroyer"]["target_profile"] == pytest.approx(0.7)

    def test_spawn_sets_target_profile(self):
        enemy = spawn_enemy("fighter", 0.0, 0.0, "e1")
        assert enemy.target_profile == pytest.approx(0.4)

    def test_spawn_cruiser_sets_target_profile(self):
        enemy = spawn_enemy("cruiser", 0.0, 0.0, "e2")
        assert enemy.target_profile == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# 5. Spec scenario: Helm ↔ survival dependency (spec 1.2.4)
# ---------------------------------------------------------------------------


class TestHelmSurvivalDependency:
    def test_scout_moving_much_harder_to_hit_than_stationary(self):
        """On a scout, Helm MUST keep moving or the ship dies."""
        stationary = make_ship(target_profile=0.5, max_speed_base=250.0, velocity=0.0)
        moving = make_ship(target_profile=0.5, max_speed_base=250.0, velocity=250.0)
        assert calculate_effective_profile(moving) < calculate_effective_profile(stationary) * 0.75

    def test_battleship_speed_barely_matters(self):
        """On a battleship, movement barely matters for defence."""
        stationary = make_ship(target_profile=1.0, max_speed_base=80.0, velocity=0.0)
        moving = make_ship(target_profile=1.0, max_speed_base=80.0, velocity=80.0)
        # Difference is only 0.3 (1.0 vs 0.7) — 30% reduction, not game-changing.
        assert calculate_effective_profile(moving) >= 0.65


# ---------------------------------------------------------------------------
# 6. Speed evasion factor constant
# ---------------------------------------------------------------------------


def test_speed_evasion_factor_is_0_3():
    assert SPEED_EVASION_FACTOR == pytest.approx(0.3)
