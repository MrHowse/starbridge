"""
Physics System.

Applies movement physics to the player ship each game tick:
  1. Turn heading toward target_heading at the current turn rate.
  2. Accelerate/decelerate velocity toward the throttle target.
  3. Move ship in heading direction; clamp to sector bounds.

All physics constants are at module level so tests can inspect them.
`tick()` is the public entry point — call once per game loop iteration.
"""
from __future__ import annotations

import math

from server.models.ship import Ship
from server.utils.math_helpers import angle_diff, wrap_angle

# ---------------------------------------------------------------------------
# Physics constants
# ---------------------------------------------------------------------------

BASE_MAX_SPEED: float = 200.0  # world units/sec at 100% engine power/efficiency
BASE_TURN_RATE: float = 45.0   # degrees/sec at 100% manoeuvring power/efficiency
ACCELERATION: float = 50.0     # world units/sec² — how fast velocity rises to target
DECELERATION: float = 80.0     # world units/sec² — braking is faster than acceleration


# ---------------------------------------------------------------------------
# Derived quantities (depend on ship system state)
# ---------------------------------------------------------------------------


def max_speed(ship: Ship) -> float:
    """Maximum speed in world units/sec, scaled by engine efficiency."""
    return BASE_MAX_SPEED * ship.systems["engines"].efficiency


def turn_rate(ship: Ship) -> float:
    """Turn rate in degrees/sec, scaled by manoeuvring efficiency."""
    return BASE_TURN_RATE * ship.systems["manoeuvring"].efficiency


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def tick(ship: Ship, dt: float, sector_width: float, sector_height: float) -> None:
    """Apply one physics step to the ship. Mutates ship in place.

    Args:
        ship: The player ship to update.
        dt: Time delta in seconds (typically 1/TICK_RATE = 0.1 s).
        sector_width: Sector boundary on the x-axis (world units).
        sector_height: Sector boundary on the y-axis (world units).
    """
    _turn(ship, dt)
    _thrust(ship, dt)
    _move(ship, dt, sector_width, sector_height)


# ---------------------------------------------------------------------------
# Private step functions
# ---------------------------------------------------------------------------


def _turn(ship: Ship, dt: float) -> None:
    """Rotate heading toward target_heading at the current turn rate."""
    rate = turn_rate(ship)
    diff = angle_diff(ship.heading, ship.target_heading)
    max_turn = rate * dt

    if abs(diff) <= max_turn:
        # Close enough — snap to target to avoid floating-point drift.
        ship.heading = ship.target_heading
    else:
        ship.heading = wrap_angle(
            ship.heading + (max_turn if diff > 0.0 else -max_turn)
        )


def _thrust(ship: Ship, dt: float) -> None:
    """Accelerate or decelerate velocity toward the throttle target speed."""
    target_speed = (ship.throttle / 100.0) * max_speed(ship)

    if ship.velocity < target_speed:
        ship.velocity = min(ship.velocity + ACCELERATION * dt, target_speed)
    else:
        ship.velocity = max(ship.velocity - DECELERATION * dt, target_speed)


def _move(ship: Ship, dt: float, sector_width: float, sector_height: float) -> None:
    """Translate ship position in heading direction; clamp to sector bounds.

    If the ship hits a boundary it stops (velocity → 0). The player must
    change heading and reapply throttle to continue.

    TODO: Boundary behaviour could be made configurable per-mission in a future
    phase — some missions may want wrap-around (continuous space) or open
    boundaries rather than hard walls.
    """
    heading_rad = math.radians(ship.heading)
    # Heading 0 = north = –y direction (y increases downward in world space).
    new_x = ship.x + ship.velocity * math.sin(heading_rad) * dt
    new_y = ship.y - ship.velocity * math.cos(heading_rad) * dt

    clamped_x = max(0.0, min(sector_width, new_x))
    clamped_y = max(0.0, min(sector_height, new_y))

    if clamped_x != new_x or clamped_y != new_y:
        # Ship hit a boundary — stop it completely.
        ship.velocity = 0.0

    ship.x = clamped_x
    ship.y = clamped_y
