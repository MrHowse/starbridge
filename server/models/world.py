"""
World Model.

The World contains all entities in the 2D simulation space: the player ship
and (from Phase 4) enemy ships, stations, and projectiles.

The sector is 100,000 × 100,000 world units. The coordinate origin is the
top-left corner: x increases eastward, y increases southward. Heading 0° is
north (toward y=0), clockwise.
"""
from __future__ import annotations

import random as _rng_module
from dataclasses import dataclass, field
from typing import ClassVar, Literal, Optional

_SHIELD_FREQUENCIES = ("alpha", "beta", "gamma", "delta")

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
class Hazard:
    """A persistent environmental hazard in the sector.

    hazard_type values:
      ``nebula``         — sensor-obscuring cloud (visual + puzzle context).
      ``minefield``      — deals hull damage to ships inside (5 HP/s).
      ``gravity_well``   — caps ship velocity to 100 u/s when inside.
      ``radiation_zone`` — deals light hull damage (2 HP/s).
    """

    id: str
    x: float
    y: float
    radius: float = 10_000.0
    hazard_type: Literal["nebula", "minefield", "gravity_well", "radiation_zone"] = "nebula"
    label: Optional[str] = None   # display name (optional)


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
    torpedo_type: str = "standard"   # standard | emp | probe | nuclear
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
    # v0.02g — EMP stun (ticks remaining; 0 = not stunned)
    stun_ticks: int = 0
    # v0.03k — Electronic Warfare
    jam_factor: float = 0.0          # 0.0 = not jammed; jam reduces beam damage fraction
    intrusion_stun_ticks: int = 0    # EW network intrusion: blocks beam fire when > 0
    # Gap closure — beam frequency vulnerability
    shield_frequency: str = ""       # alpha | beta | gamma | delta — matched by Weapons


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

    # Session 2c entities — persistent hazard zones.
    hazards: list[Hazard] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def spawn_station(station_id: str, x: float, y: float) -> Station:
    """Create a new Station at the given position."""
    return Station(id=station_id, x=x, y=y)


def spawn_hazard(
    hazard_id: str,
    x: float,
    y: float,
    radius: float = 10_000.0,
    hazard_type: Literal["nebula", "minefield", "gravity_well", "radiation_zone"] = "nebula",
    label: str | None = None,
) -> Hazard:
    """Create a new Hazard zone at the given position."""
    return Hazard(id=hazard_id, x=x, y=y, radius=radius, hazard_type=hazard_type, label=label)


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
        shield_frequency=_rng_module.choice(_SHIELD_FREQUENCIES),
    )
