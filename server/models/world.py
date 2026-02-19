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
from typing import ClassVar, Literal

from server.models.ship import Ship

# Sector dimensions in world units (100k × 100k).
SECTOR_WIDTH: float = 100_000.0
SECTOR_HEIGHT: float = 100_000.0


# ---------------------------------------------------------------------------
# Enemy type parameters
# ---------------------------------------------------------------------------

#: Per-type stats: hull, speed, detect_range, weapon_range, arc_deg,
#:                 beam_dmg, beam_cooldown, flee_threshold (fraction of max hull).
ENEMY_TYPE_PARAMS: dict[str, dict] = {
    "scout": {
        "hull":           40.0,
        "speed":         280.0,
        "detect_range": 15_000.0,
        "weapon_range":  4_000.0,
        "arc_deg":         40.0,
        "beam_dmg":         5.0,
        "beam_cooldown":    1.5,
        "flee_threshold":   0.30,
    },
    "cruiser": {
        "hull":           70.0,
        "speed":         150.0,
        "detect_range": 12_000.0,
        "weapon_range":  6_000.0,
        "arc_deg":         40.0,
        "beam_dmg":        10.0,
        "beam_cooldown":    2.0,
        "flee_threshold":   0.20,
    },
    "destroyer": {
        "hull":          100.0,
        "speed":         100.0,
        "detect_range": 20_000.0,
        "weapon_range": 10_000.0,
        "arc_deg":         30.0,
        "beam_dmg":        15.0,
        "beam_cooldown":    3.0,
        "flee_threshold":   0.15,
    },
}


# ---------------------------------------------------------------------------
# Entity dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Station:
    """A friendly (or neutral) stationary structure in the sector."""

    id: str
    x: float
    y: float
    hull: float = 200.0
    hull_max: float = 200.0


@dataclass
class Asteroid:
    """An inert hazard in the sector. Causes hull damage on collision."""

    id: str
    x: float
    y: float
    radius: float = 1_000.0  # collision radius in world units


@dataclass
class Torpedo:
    """A short-lived projectile entity travelling through the sector."""

    id: str
    owner: str            # "player" or enemy entity_id
    x: float
    y: float
    heading: float
    velocity: float = 500.0
    distance_travelled: float = 0.0
    MAX_RANGE: ClassVar[float] = 20_000.0


@dataclass
class Enemy:
    """An enemy vessel with its own AI state machine."""

    id: str
    type: Literal["scout", "cruiser", "destroyer"]
    x: float
    y: float
    heading: float = 0.0
    velocity: float = 0.0
    hull: float = 100.0
    shield_front: float = 100.0
    shield_rear: float = 100.0
    ai_state: Literal["idle", "chase", "attack", "flee"] = "idle"
    beam_cooldown: float = 0.0    # seconds until next beam fire
    # Phase 5 — Science scanning
    scan_state: Literal["unknown", "scanned"] = "unknown"


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------


@dataclass
class World:
    """The full simulation state: sector bounds and all entities within it."""

    width: float = SECTOR_WIDTH
    height: float = SECTOR_HEIGHT

    # The player-controlled vessel.
    ship: Ship = field(default_factory=Ship)

    # Phase 4 entities — enemies and torpedoes.
    enemies: list[Enemy] = field(default_factory=list)
    torpedoes: list[Torpedo] = field(default_factory=list)

    # Phase 7 entities — friendly stations (Mission 2+) and asteroids (Mission 3).
    stations: list[Station] = field(default_factory=list)
    asteroids: list[Asteroid] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def spawn_station(station_id: str, x: float, y: float) -> Station:
    """Create a new Station at the given position."""
    return Station(id=station_id, x=x, y=y)


def spawn_enemy(type_: Literal["scout", "cruiser", "destroyer"], x: float, y: float, entity_id: str) -> Enemy:
    """Create a new Enemy with type-appropriate starting stats."""
    params = ENEMY_TYPE_PARAMS[type_]
    return Enemy(
        id=entity_id,
        type=type_,
        x=x,
        y=y,
        hull=params["hull"],
        shield_front=100.0,
        shield_rear=100.0,
        ai_state="idle",
    )
