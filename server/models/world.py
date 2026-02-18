"""
World Model.

The World contains all entities in the 2D simulation space: the player ship
and (from Phase 4) enemy ships, stations, and projectiles.

The sector is 100,000 × 100,000 world units. The coordinate origin is the
top-left corner: x increases eastward, y increases southward. Heading 0° is
north (toward y=0), clockwise.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from server.models.ship import Ship

# Sector dimensions in world units (100k × 100k).
SECTOR_WIDTH: float = 100_000.0
SECTOR_HEIGHT: float = 100_000.0


@dataclass
class World:
    """The full simulation state: sector bounds and all entities within it."""

    width: float = SECTOR_WIDTH
    height: float = SECTOR_HEIGHT

    # The player-controlled vessel.
    ship: Ship = field(default_factory=Ship)

    # Enemy ships, stations, projectiles, etc. — populated from Phase 4.
    # entities: list[Entity] = field(default_factory=list)
