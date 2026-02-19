"""
Firing Solution Puzzle — Weapons station.

The player must calculate the intercept bearing for a torpedo shot against a
moving target.  The torpedo travels at a fixed speed (500 u/s); the target
moves at an unknown speed and heading.  The player enters the bearing they
wish to fire on and submits.  The puzzle validates that the bearing is within
the allowed tolerance of the mathematically correct intercept heading.

Difficulty controls target distance, target speed, and tolerance:
  1 → close range,  slow target,  ±15° tolerance  (easiest)
  2 → medium range, medium target, ±10°
  3 → long range,   fast target,   ±8°
  4 → long range,   faster target, ±6°
  5 → max range,    fastest target, ±5°            (hardest)

Science → Weapons assist:
  velocity_data — Science provides exact target heading and velocity; the
                  tolerance is widened by +8° to reward collaboration.
"""
from __future__ import annotations

import math
import random
from typing import Any

from server.puzzles.base import PuzzleInstance
from server.puzzles.engine import register_puzzle_type
from server.utils.math_helpers import angle_diff, wrap_angle

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TORPEDO_SPEED: float = 500.0   # must match world.Torpedo.velocity

# (dist_min, dist_max, spd_min, spd_max, tolerance_deg)
_DIFFICULTY_PARAMS: dict[int, tuple[int, int, int, int, float]] = {
    1: (2_000, 4_000,  50, 100, 15.0),
    2: (3_000, 6_000,  80, 130, 10.0),
    3: (5_000, 8_000, 100, 160,  8.0),
    4: (6_000, 9_000, 130, 180,  6.0),
    5: (7_000,10_000, 150, 200,  5.0),
}

# Tolerance bonus when the Science velocity-data assist is applied.
_ASSIST_TOLERANCE_BONUS: float = 8.0


# ---------------------------------------------------------------------------
# Intercept maths helper
# ---------------------------------------------------------------------------


def _compute_intercept_bearing(
    target_x: float,
    target_y: float,
    target_heading: float,
    target_speed: float,
    torp_speed: float,
) -> float:
    """Compute the intercept bearing (degrees, 0–360) from the origin (player)
    to the predicted intercept point, using a quadratic equation.

    Falls back to direct bearing if no positive-time solution exists.
    """
    vx = target_speed * math.sin(math.radians(target_heading))
    vy = -target_speed * math.cos(math.radians(target_heading))

    # (vx^2 + vy^2 - torp_speed^2)*t^2 + 2*(tx*vx + ty*vy)*t + (tx^2 + ty^2) = 0
    a = vx ** 2 + vy ** 2 - torp_speed ** 2
    b = 2.0 * (target_x * vx + target_y * vy)
    c = target_x ** 2 + target_y ** 2

    direct_brg = math.degrees(math.atan2(target_x, -target_y)) % 360.0

    if abs(a) < 0.01:
        # Essentially stationary target relative to torpedo speed.
        return direct_brg

    discriminant = b ** 2 - 4.0 * a * c
    if discriminant < 0.0:
        return direct_brg

    sqrt_d = math.sqrt(discriminant)
    t1 = (-b + sqrt_d) / (2.0 * a)
    t2 = (-b - sqrt_d) / (2.0 * a)
    positives = [t for t in (t1, t2) if t > 0.01]

    if not positives:
        return direct_brg

    t = min(positives)
    ix = target_x + vx * t
    iy = target_y + vy * t
    return math.degrees(math.atan2(ix, -iy)) % 360.0


# ---------------------------------------------------------------------------
# Puzzle class
# ---------------------------------------------------------------------------


class FiringSolutionPuzzle(PuzzleInstance):
    """Weapons station firing solution puzzle."""

    def generate(self, **kwargs: Any) -> dict:
        params = _DIFFICULTY_PARAMS.get(self.difficulty, _DIFFICULTY_PARAMS[2])
        dist_min, dist_max, spd_min, spd_max, tol = params

        # Generate a solvable scenario: retry up to 20× to get a valid intercept.
        for _ in range(20):
            target_brg  = random.uniform(0.0, 360.0)
            target_dist = random.uniform(dist_min, dist_max)

            # Target position relative to player (ship at origin).
            tx = target_dist * math.sin(math.radians(target_brg))
            ty = -target_dist * math.cos(math.radians(target_brg))

            # Target heading is offset from its bearing by a perpendicular angle
            # (60–120° or mirror) so there's always an interesting lead angle.
            offset = random.choice([60, 75, 90, 105, 120, -60, -75, -90, -105, -120])
            target_heading = wrap_angle(target_brg + offset)
            target_speed   = random.uniform(spd_min, spd_max)

            correct_brg = _compute_intercept_bearing(tx, ty, target_heading, target_speed, TORPEDO_SPEED)

            # Reject trivially identical to direct bearing (no real intercept lead).
            if abs(angle_diff(correct_brg, target_brg)) > 1.0:
                break
        else:
            # Fall-through: use direct bearing.
            correct_brg = target_brg

        self._target_bearing: float   = round(target_brg, 1)
        self._target_distance: float  = round(target_dist, 1)
        self._target_heading: float   = round(target_heading, 1)
        self._target_velocity: float  = round(target_speed, 1)
        self._correct_bearing: float  = round(correct_brg, 1)
        self._tolerance: float        = tol
        self._assist_applied: bool    = False   # duck-type hook for assist chain

        return {
            "target_bearing":  self._target_bearing,
            "target_distance": self._target_distance,
            "target_heading":  self._target_heading,
            "target_velocity": None,           # hidden until Science assist
            "torp_velocity":   TORPEDO_SPEED,
            "tolerance":       tol,
        }

    def validate_submission(self, data: dict) -> bool:
        """Return True iff data["bearing"] is within tolerance of the correct intercept bearing."""
        bearing = data.get("bearing")
        if bearing is None:
            return False
        try:
            bearing = float(bearing)
        except (TypeError, ValueError):
            return False

        diff = abs(angle_diff(bearing, self._correct_bearing))
        return diff <= self._tolerance

    def apply_assist(self, assist_type: str, data: dict) -> dict:
        """Apply Science velocity-data assist.

        ``velocity_data`` — Science provides exact target heading and velocity;
            the submit tolerance is widened by ``_ASSIST_TOLERANCE_BONUS`` degrees.
            Returns ``{"target_velocity": float, "target_heading": float, "tolerance": float}``
            or ``{}`` if already applied.
        """
        if assist_type == "velocity_data" and not self._assist_applied:
            self._tolerance = min(self._tolerance + _ASSIST_TOLERANCE_BONUS, 25.0)
            self._assist_applied = True
            return {
                "target_velocity": self._target_velocity,
                "target_heading":  self._target_heading,
                "tolerance":       self._tolerance,
            }
        return {}


register_puzzle_type("firing_solution", FiringSolutionPuzzle)
