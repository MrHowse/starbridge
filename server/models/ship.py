"""
Ship Model.

Dataclasses representing the player-controlled vessel and its subsystems.
All fields are mutable game state — the physics system updates them each tick.

Ship is the single player vessel for v0.01. In Phase 3, Engineering controls
power allocation; in Phase 4, shield and weapon fields become active.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Subsystem
# ---------------------------------------------------------------------------


@dataclass
class ShipSystem:
    """One of the six ship subsystems, each with independent power and health.

    power  — Engineering's allocation, 0-150 (percentage of base draw).
    health — Structural integrity, 0-100. Reaches 0 when destroyed.
    efficiency — Derived: (power / 100) * (health / 100). Ranges 0.0-1.5.
                 At full power (100%) and full health (100%) efficiency = 1.0.
                 Overclock to 150% gives efficiency 1.5 (Phase 3 risk mechanic).
    """

    name: str
    power: float = 100.0   # 0-150 (%)
    health: float = 100.0  # 0-100 (%)

    @property
    def efficiency(self) -> float:
        """Effective output fraction. 0.0 (offline) to 1.5 (overclocked, healthy)."""
        return (self.power / 100.0) * (self.health / 100.0)


# ---------------------------------------------------------------------------
# Shields
# ---------------------------------------------------------------------------


@dataclass
class Shields:
    """Front and rear shield charge levels. 0 = down, 100 = full strength."""

    front: float = 100.0  # 0-100 (%)
    rear: float = 100.0   # 0-100 (%)


# ---------------------------------------------------------------------------
# Ship
# ---------------------------------------------------------------------------


def _default_systems() -> dict[str, ShipSystem]:
    """Return the six default ship systems at full power and health."""
    return {
        name: ShipSystem(name)
        for name in ("engines", "beams", "torpedoes", "shields", "sensors", "manoeuvring")
    }


@dataclass
class Ship:
    """Complete mutable state of the player-controlled vessel.

    Movement fields (heading, velocity, throttle, target_heading) are updated
    by the physics system each tick. In Phase 2, only engines and manoeuvring
    systems actively affect physics; the others default to 100% power and wait
    for Engineering (Phase 3) and Weapons (Phase 4).
    """

    name: str = "TSS Endeavour"

    # --- Position (world units, origin = top-left corner of sector) ---
    x: float = 50_000.0   # starts at sector centre
    y: float = 50_000.0

    # --- Movement ---
    heading: float = 0.0         # current actual heading, degrees (0 = north/up, clockwise)
    target_heading: float = 0.0  # desired heading set by Helm (physics turns ship toward it)
    velocity: float = 0.0        # current speed, world units/sec
    throttle: float = 0.0        # desired speed fraction, 0-100 (%)

    # --- Hull ---
    hull: float = 100.0  # 0-100 HP; 0 = destroyed

    # --- Shields ---
    shields: Shields = field(default_factory=Shields)

    # --- Subsystems ---
    systems: dict[str, ShipSystem] = field(default_factory=_default_systems)

    # --- Engineering ---
    repair_focus: str | None = None  # System currently receiving repair attention
