"""
Flight Operations data models.

Drones fly to a target and passively extend sensor coverage.
Probes are stationary, expendable, and create a permanent detection bubble.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DRONE_SPEED: float = 800.0             # world units / second in transit
DRONE_SENSOR_RANGE_BASE: float = 5_000.0  # range at flight_deck efficiency 1.0
PROBE_SENSOR_RANGE: float = 8_000.0    # stationary probe detection range

DRONE_FUEL_DRAIN_TRANSIT: float = 4.0   # % / second while flying to/from target
DRONE_FUEL_DRAIN_DEPLOYED: float = 1.5  # % / second while hovering at target
DRONE_FUEL_REFILL_RATE: float = 20.0    # % / second while in hangar
DRONE_LOW_FUEL: float = 20.0            # auto-recall threshold
DRONE_RECOVERY_DIST: float = 800.0      # distance at which returning drone lands

# Default complement per frigate (ship-class overrides future).
DEFAULT_DRONE_COUNT: int = 2
DEFAULT_PROBE_STOCK: int = 4


# ---------------------------------------------------------------------------
# Craft dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Drone:
    """Autonomous reconnaissance craft.

    States:
        hangar    — aboard ship; fuel slowly recharges.
        transit   — flying toward target_x/target_y.
        deployed  — stationary at target; sensors active; fuel draining.
        returning — flying back to ship position.
    """

    id: str
    state: str = "hangar"     # hangar | transit | deployed | returning
    x: float = 0.0
    y: float = 0.0
    target_x: float = 0.0
    target_y: float = 0.0
    fuel: float = 100.0       # 0 – 100 %


@dataclass
class Probe:
    """Expendable stationary sensor buoy deployed at a world position."""

    id: str
    x: float
    y: float
