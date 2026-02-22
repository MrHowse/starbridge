"""
Navigation — sector-aware route calculation and active-route state.

Route dict:
{
  "from_x":  float,
  "from_y":  float,
  "plot_x":  float,
  "plot_y":  float,
  "heading": float,                  # compass, 0 = north, 90 = east
  "total_distance": float,           # world units
  "estimated_travel_time_s": float,  # at the supplied speed
  "sectors_traversed": list[str],    # ordered sector IDs
  "waypoints": list[dict],           # {x, y, label}
  "warnings": list[str],             # human-readable hazard notes
  "turn_by_turn": list[str],         # step-by-step directions for Helm
}
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.models.sector import SectorGrid

# Roles that receive map.sector_grid and map.route_updated broadcasts.
MAP_CAPABLE_ROLES: list[str] = [
    "captain", "helm", "science", "tactical", "comms", "flight_ops",
]

_active_route: dict | None = None
_pending_broadcast: bool = False  # True when route changed and broadcast is needed

_SECTOR_SAMPLES = 40  # resolution for sector-traversal tracing


def reset() -> None:
    """Clear all state at game start / stop."""
    global _active_route, _pending_broadcast
    _active_route = None
    _pending_broadcast = False


def get_route() -> dict | None:
    """Return the current active route, or None."""
    return _active_route


def set_route(route: dict) -> None:
    """Store a route and flag it for broadcast on the next tick."""
    global _active_route, _pending_broadcast
    _active_route = route
    _pending_broadcast = True


def clear_route() -> None:
    """Remove the active route and flag for broadcast."""
    global _active_route, _pending_broadcast
    _active_route = None
    _pending_broadcast = True


def pop_pending_broadcast() -> bool:
    """Return True (and clear the flag) if a route broadcast is pending."""
    global _pending_broadcast
    p = _pending_broadcast
    _pending_broadcast = False
    return p


# ---------------------------------------------------------------------------
# Route calculation
# ---------------------------------------------------------------------------

def calculate_route(
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    grid: "SectorGrid | None" = None,
    current_speed: float = 100.0,
) -> dict:
    """Return a route dict from (from_x, from_y) to (to_x, to_y).

    *grid* may be None — sector-specific fields will be empty.
    *current_speed* is the ship speed (world-units/second) for time estimates.
    """
    dx = to_x - from_x
    dy = to_y - from_y
    distance = math.hypot(dx, dy)
    heading = _heading_between(from_x, from_y, to_x, to_y)
    speed = max(current_speed, 1.0)
    travel_s = distance / speed if distance > 0 else 0.0

    sectors_traversed: list[str] = []
    warnings: list[str] = []
    waypoints: list[dict] = []

    if grid is not None:
        sectors_traversed, warnings = _trace_sectors(from_x, from_y, to_x, to_y, grid)
        waypoints = _build_waypoints(from_x, from_y, to_x, to_y, grid)

    waypoints.append({"x": round(to_x), "y": round(to_y), "label": "DESTINATION"})

    turn_by_turn = _build_turn_by_turn(heading, distance, travel_s, sectors_traversed)

    return {
        "from_x":                  round(from_x, 1),
        "from_y":                  round(from_y, 1),
        "plot_x":                  round(to_x, 1),
        "plot_y":                  round(to_y, 1),
        "heading":                 round(heading, 1),
        "total_distance":          round(distance, 1),
        "estimated_travel_time_s": round(travel_s, 1),
        "sectors_traversed":       sectors_traversed,
        "waypoints":               waypoints,
        "warnings":                warnings,
        "turn_by_turn":            turn_by_turn,
    }


def _heading_between(x1: float, y1: float, x2: float, y2: float) -> float:
    """Compass heading from (x1, y1) to (x2, y2). 0 = north, 90 = east."""
    dx = x2 - x1
    dy = y2 - y1
    return (math.degrees(math.atan2(dx, -dy)) % 360)


def _trace_sectors(
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    grid: "SectorGrid",
) -> tuple[list[str], list[str]]:
    """Sample along the straight-line route; return ordered sector IDs + warnings."""
    sectors_seen: list[str] = []
    seen_set: set[str] = set()
    warnings_set: set[str] = set()

    for i in range(_SECTOR_SAMPLES + 1):
        t = i / _SECTOR_SAMPLES
        px = from_x + (to_x - from_x) * t
        py = from_y + (to_y - from_y) * t
        s = grid.sector_at_position(px, py)
        if s is None:
            continue
        if s.id not in seen_set:
            sectors_seen.append(s.id)
            seen_set.add(s.id)
            pt = s.properties.type
            if pt == "hostile_space":
                warnings_set.add("HOSTILE SPACE")
            elif pt == "nebula":
                warnings_set.add("SENSOR DEGRADATION (nebula)")
            elif pt == "asteroid_field":
                warnings_set.add("NAVIGATION HAZARD (asteroids)")
            elif pt == "radiation_zone":
                warnings_set.add("RADIATION ZONE")
            elif pt == "gravity_well":
                warnings_set.add("GRAVITY WELL (reduced speed)")

    return sectors_seen, sorted(warnings_set)


def _build_waypoints(
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    grid: "SectorGrid",
) -> list[dict]:
    """Return approximate sector-boundary crossing points as waypoints."""
    waypoints: list[dict] = []
    prev_sid: str | None = None

    for i in range(_SECTOR_SAMPLES + 1):
        t = i / _SECTOR_SAMPLES
        px = from_x + (to_x - from_x) * t
        py = from_y + (to_y - from_y) * t
        s = grid.sector_at_position(px, py)
        sid = s.id if s is not None else None
        if prev_sid is not None and sid is not None and sid != prev_sid:
            waypoints.append({
                "x": round(px),
                "y": round(py),
                "label": f"ENTER {sid}",
            })
        prev_sid = sid

    return waypoints


def _build_turn_by_turn(
    heading: float,
    distance: float,
    travel_s: float,
    sectors_traversed: list[str],
) -> list[str]:
    """Human-readable step-by-step directions for the Helm display."""
    directions: list[str] = []
    hdg_str = f"{round(heading):03d}"
    dist_str = f"{distance / 1000:.1f}k"
    time_min = round(travel_s / 60, 1)

    directions.append(f"Set heading {hdg_str}°")
    directions.append(f"Travel {dist_str} units ({time_min} min at current speed)")

    for sid in sectors_traversed[1:]:  # skip origin sector
        directions.append(f"Enter sector {sid}")

    directions.append("Arrive at destination")
    return directions
