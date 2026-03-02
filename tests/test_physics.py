"""Tests for server/systems/physics.py — physics.tick and its sub-steps."""
from __future__ import annotations

import math

import pytest

from server.models.ship import Ship
from server.models.world import SECTOR_HEIGHT, SECTOR_WIDTH
from server.systems.physics import (
    ACCELERATION,
    BASE_MAX_SPEED,
    BASE_TURN_RATE,
    DECELERATION,
    acceleration_rate,
    max_speed,
    tick,
    turn_rate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DT = 0.1  # matches TICK_DT in game_loop.py


def make_ship(**kwargs: object) -> Ship:
    """Return a default Ship with any overrides applied."""
    ship = Ship()
    for key, val in kwargs.items():
        setattr(ship, key, val)
    return ship


# ---------------------------------------------------------------------------
# Derived quantities
# ---------------------------------------------------------------------------


def test_max_speed_at_full_efficiency():
    ship = Ship()
    assert max_speed(ship) == pytest.approx(ship.max_speed_base)


def test_max_speed_halved_at_half_engine_power():
    ship = Ship()
    ship.systems["engines"].power = 50.0
    assert max_speed(ship) == pytest.approx(ship.max_speed_base * 0.5)


def test_turn_rate_at_full_efficiency():
    ship = Ship()
    assert turn_rate(ship) == pytest.approx(ship.turn_rate_base)


def test_turn_rate_halved_at_half_manoeuvring_power():
    ship = Ship()
    ship.systems["manoeuvring"].power = 50.0
    assert turn_rate(ship) == pytest.approx(ship.turn_rate_base * 0.5)


def test_acceleration_rate_reads_from_ship():
    ship = Ship()
    assert acceleration_rate(ship) == pytest.approx(ship.acceleration_base)


def test_max_speed_uses_class_specific_value():
    """Ships with different max_speed_base produce different max speeds."""
    ship = Ship()
    ship.max_speed_base = 250.0  # scout
    assert max_speed(ship) == pytest.approx(250.0)

    ship.max_speed_base = 80.0  # battleship
    assert max_speed(ship) == pytest.approx(80.0)


def test_speed_floor_prevents_near_zero():
    """Damaged engines should never drop below 25% of max speed."""
    ship = Ship()
    ship.max_speed_base = 120.0  # cruiser
    ship.systems["engines"].health = 10.0  # 10% health
    # Without floor: 120 * 0.1 = 12. With floor: max(12, 30) = 30
    assert max_speed(ship) == pytest.approx(30.0)


def test_speed_floor_does_not_apply_when_offline():
    """Speed floor should not apply when engines are completely off."""
    ship = Ship()
    ship.max_speed_base = 120.0
    ship.systems["engines"].power = 0.0
    assert max_speed(ship) == pytest.approx(0.0)


def test_speed_floor_cruiser_at_10pct_health():
    """A cruiser at 10% engine health should still move at 25% max speed."""
    ship = Ship()
    ship.max_speed_base = 120.0
    ship.systems["engines"].health = 10.0
    # floor = 120 * 0.25 = 30, calculated = 120 * 0.10 = 12
    assert max_speed(ship) >= 120.0 * 0.25


def test_turn_rate_uses_class_specific_value():
    ship = Ship()
    ship.turn_rate_base = 180.0  # scout
    assert turn_rate(ship) == pytest.approx(180.0)


# ---------------------------------------------------------------------------
# Heading / turning
# ---------------------------------------------------------------------------


def test_ship_turns_toward_target_heading():
    ship = make_ship(heading=0.0, target_heading=90.0)
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    # Should have moved clockwise by (turn_rate_base * DT)
    assert ship.heading == pytest.approx(ship.turn_rate_base * DT)


def test_ship_snaps_to_target_when_within_one_step():
    ship = make_ship(heading=0.0)
    step = ship.turn_rate_base * DT
    ship.target_heading = step * 0.5
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    assert ship.heading == pytest.approx(ship.target_heading)


def test_ship_heading_wraps_past_360():
    ship = make_ship(heading=358.0, target_heading=20.0)
    step = ship.turn_rate_base * DT
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    # Shortest path is clockwise (+22°). Step is 9°, so heading = (358+9) % 360 = 7.0
    assert ship.heading == pytest.approx((358.0 + step) % 360.0)


def test_ship_turns_counter_clockwise_for_shorter_path():
    # target is 270°, easiest path from 0° is counter-clockwise (-90°)
    ship = make_ship(heading=0.0, target_heading=270.0)
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    # Heading should decrease (turn left)
    expected = (0.0 - ship.turn_rate_base * DT) % 360.0
    assert ship.heading == pytest.approx(expected)


def test_ship_at_target_heading_does_not_move():
    ship = make_ship(heading=45.0, target_heading=45.0)
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    assert ship.heading == pytest.approx(45.0)


# ---------------------------------------------------------------------------
# Thrust / velocity
# ---------------------------------------------------------------------------


def test_ship_accelerates_from_zero():
    ship = make_ship(throttle=100.0)
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    assert ship.velocity == pytest.approx(ship.acceleration_base * DT)


def test_ship_decelerates_when_throttle_cut():
    ship = make_ship(throttle=0.0, velocity=100.0)
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    # Deceleration is proportional: accel * (DECELERATION / ACCELERATION)
    decel = ship.acceleration_base * (DECELERATION / ACCELERATION)
    assert ship.velocity == pytest.approx(100.0 - decel * DT)


def test_ship_velocity_capped_at_max_speed():
    ship = make_ship(throttle=100.0)
    ship.velocity = ship.max_speed_base - 1.0
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    assert ship.velocity == pytest.approx(ship.max_speed_base)


def test_ship_velocity_does_not_go_below_zero():
    ship = make_ship(throttle=0.0, velocity=0.5)  # less than decel*DT
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    assert ship.velocity == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------


def test_ship_moves_north_at_heading_zero():
    ship = make_ship(heading=0.0, target_heading=0.0, throttle=0.0, velocity=100.0)
    y_before = ship.y
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    # Heading 0 = north = -y direction
    assert ship.y < y_before


def test_ship_moves_south_at_heading_180():
    ship = make_ship(heading=180.0, target_heading=180.0, throttle=0.0, velocity=100.0)
    y_before = ship.y
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    assert ship.y > y_before


def test_ship_moves_east_at_heading_90():
    ship = make_ship(heading=90.0, target_heading=90.0, throttle=0.0, velocity=100.0)
    x_before = ship.x
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    assert ship.x > x_before


def test_ship_moves_west_at_heading_270():
    ship = make_ship(heading=270.0, target_heading=270.0, throttle=0.0, velocity=100.0)
    x_before = ship.x
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    assert ship.x < x_before


def test_ship_displacement_matches_velocity():
    v = 100.0
    ship = make_ship(heading=90.0, target_heading=90.0, throttle=0.0, velocity=v)
    x_before = ship.x
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    assert ship.x == pytest.approx(x_before + v * math.sin(math.radians(90.0)) * DT, rel=0.05)


# ---------------------------------------------------------------------------
# Boundary clamping
# ---------------------------------------------------------------------------


def test_ship_clamped_at_north_boundary():
    # Place ship at y=5, moving north — should hit y=0 boundary
    ship = make_ship(heading=0.0, target_heading=0.0, throttle=0.0,
                     y=5.0, velocity=200.0)
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    assert ship.y == pytest.approx(0.0)
    assert ship.velocity == pytest.approx(0.0)


def test_ship_clamped_at_south_boundary():
    ship = make_ship(heading=180.0, target_heading=180.0, throttle=0.0,
                     y=SECTOR_HEIGHT - 5.0, velocity=200.0)
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    assert ship.y == pytest.approx(SECTOR_HEIGHT)
    assert ship.velocity == pytest.approx(0.0)


def test_ship_clamped_at_east_boundary():
    ship = make_ship(heading=90.0, target_heading=90.0, throttle=0.0,
                     x=SECTOR_WIDTH - 5.0, velocity=200.0)
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    assert ship.x == pytest.approx(SECTOR_WIDTH)
    assert ship.velocity == pytest.approx(0.0)


def test_ship_within_bounds_velocity_unchanged_by_clamping():
    ship = make_ship(heading=90.0, target_heading=90.0, throttle=100.0, velocity=50.0)
    tick(ship, DT, SECTOR_WIDTH, SECTOR_HEIGHT)
    # Ship started in centre, nowhere near boundary — velocity should not be zeroed
    assert ship.velocity > 0.0
