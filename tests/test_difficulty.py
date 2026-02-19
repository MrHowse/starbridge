"""Tests for the difficulty preset system."""
from __future__ import annotations

import pytest

from server.difficulty import DifficultySettings, PRESETS, get_preset
from server.models.ship import Ship
from server.models.world import Enemy
from server.systems.combat import apply_hit_to_player
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# DifficultySettings
# ---------------------------------------------------------------------------


def test_presets_exist():
    assert set(PRESETS.keys()) == {"cadet", "officer", "commander", "admiral"}


def test_officer_is_all_ones():
    d = PRESETS["officer"]
    assert d.enemy_damage_mult == 1.0
    assert d.puzzle_time_mult == 1.0
    assert d.spawn_rate_mult == 1.0
    assert d.crew_casualty_mult == 1.0
    assert d.hints_enabled is False


def test_cadet_halves_damage():
    assert PRESETS["cadet"].enemy_damage_mult == 0.5


def test_cadet_hints_enabled():
    assert PRESETS["cadet"].hints_enabled is True


def test_admiral_multiplies_damage():
    assert PRESETS["admiral"].enemy_damage_mult == 1.6


def test_admiral_reduces_puzzle_time():
    # Admiral gets 60% of default puzzle time.
    assert PRESETS["admiral"].puzzle_time_mult == 0.6


def test_get_preset_known():
    assert get_preset("cadet") is PRESETS["cadet"]


def test_get_preset_fallback_to_officer():
    assert get_preset("nonexistent") is PRESETS["officer"]


def test_settings_are_frozen():
    d = PRESETS["officer"]
    with pytest.raises((AttributeError, TypeError)):
        d.enemy_damage_mult = 99.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Ship carries difficulty
# ---------------------------------------------------------------------------


def test_ship_default_difficulty_is_officer():
    ship = Ship()
    assert ship.difficulty is PRESETS["officer"]


def test_ship_difficulty_can_be_set():
    ship = Ship()
    ship.difficulty = get_preset("cadet")
    assert ship.difficulty.enemy_damage_mult == 0.5


# ---------------------------------------------------------------------------
# combat.py respects difficulty enemy_damage_mult
# ---------------------------------------------------------------------------


def _make_ship(difficulty: str = "officer") -> Ship:
    ship = Ship()
    ship.x, ship.y = 0.0, 0.0
    ship.heading = 0.0
    ship.shields.front = 0.0
    ship.shields.rear = 0.0
    ship.difficulty = get_preset(difficulty)
    return ship


def test_combat_full_damage_on_officer():
    ship = _make_ship("officer")
    rng = MagicMock()
    rng.random.return_value = 1.0  # no system damage
    initial_hull = ship.hull
    apply_hit_to_player(ship, 10.0, 0.0, 1000.0, rng=rng)
    # Officer: hull_damage = 10.0 * 1.0 = 10.0
    assert ship.hull == pytest.approx(initial_hull - 10.0)


def test_combat_halved_damage_on_cadet():
    ship = _make_ship("cadet")
    rng = MagicMock()
    rng.random.return_value = 1.0  # no system damage
    initial_hull = ship.hull
    apply_hit_to_player(ship, 10.0, 0.0, 1000.0, rng=rng)
    # Cadet: hull_damage = 10.0 * 0.5 = 5.0
    assert ship.hull == pytest.approx(initial_hull - 5.0)


def test_combat_increased_damage_on_admiral():
    ship = _make_ship("admiral")
    rng = MagicMock()
    rng.random.return_value = 1.0  # no system damage
    initial_hull = ship.hull
    apply_hit_to_player(ship, 10.0, 0.0, 1000.0, rng=rng)
    # Admiral: hull_damage = 10.0 * 1.6 = 16.0
    assert ship.hull == pytest.approx(initial_hull - 16.0)
