"""
Math Helpers — Angle wrapping, distance calculation, interpolation.

Common mathematical utilities used across game systems. All angle operations
use degrees (0-359). Distances are in world units.
"""
from __future__ import annotations


def wrap_angle(angle: float) -> float:
    """Wrap an angle to the range [0, 360)."""
    return angle % 360


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Calculate Euclidean distance between two points."""
    return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between a and b by factor t (0-1)."""
    return a + (b - a) * t


def angle_diff(from_angle: float, to_angle: float) -> float:
    """Shortest signed angular difference from from_angle to to_angle (degrees).

    Returns a value in (-180, 180]. Positive means clockwise (increasing angle).
    Examples:
        angle_diff(0, 90)   →  90  (turn right 90°)
        angle_diff(90, 0)   → -90  (turn left 90°)
        angle_diff(350, 10) →  20  (shortest path: 20° right, not 340° left)
    """
    diff = (to_angle - from_angle) % 360.0
    if diff > 180.0:
        diff -= 360.0
    return diff


def bearing_to(x1: float, y1: float, x2: float, y2: float) -> float:
    """Compass bearing from point (x1, y1) to point (x2, y2) in degrees [0, 360).

    Heading convention: 0° = north (–y direction), clockwise.
    """
    import math
    return math.degrees(math.atan2(x2 - x1, y1 - y2)) % 360
