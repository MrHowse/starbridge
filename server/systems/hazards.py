"""
Hazard System — Environmental hazard physics.

Applies per-tick effects for hazard zones that the player's ship passes through.

Hazard types and effects (per second):
  nebula         — no hull damage; cosmetic / puzzle context.
  minefield      — 5.0 HP/s hull damage.
  gravity_well   — caps ship velocity to GRAVITY_WELL_MAX_VEL.
  radiation_zone — 2.0 HP/s hull damage.
"""
from __future__ import annotations

import math

from server.models.ship import Ship
from server.models.world import Hazard, World

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MINEFIELD_DAMAGE_PER_SEC: float = 5.0
RADIATION_DAMAGE_PER_SEC: float = 2.0
GRAVITY_WELL_MAX_VEL: float = 100.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def tick_hazards(world: World, ship: Ship, dt: float) -> list[dict]:
    """Apply hazard effects to the player ship for one simulation tick.

    Returns a list of event dicts for hazards that dealt damage:
      ``{"hazard_id": str, "hazard_type": str, "damage": float}``

    Side-effects:
      - Reduces ``ship.hull`` for minefield / radiation_zone damage.
      - Caps ``ship.velocity`` for gravity_well zones.
    """
    events: list[dict] = []
    if not world.hazards:
        return events

    for hz in world.hazards:
        dist = math.hypot(ship.x - hz.x, ship.y - hz.y)
        if dist > hz.radius:
            continue  # ship outside this hazard zone

        if hz.hazard_type == "minefield":
            damage = MINEFIELD_DAMAGE_PER_SEC * dt
            ship.hull = max(0.0, ship.hull - damage)
            events.append({"hazard_id": hz.id, "hazard_type": "minefield", "damage": round(damage, 3)})

        elif hz.hazard_type == "radiation_zone":
            damage = RADIATION_DAMAGE_PER_SEC * dt
            ship.hull = max(0.0, ship.hull - damage)
            events.append({"hazard_id": hz.id, "hazard_type": "radiation_zone", "damage": round(damage, 3)})

        elif hz.hazard_type == "gravity_well":
            if ship.velocity > GRAVITY_WELL_MAX_VEL:
                ship.velocity = GRAVITY_WELL_MAX_VEL

        # nebula: no physics damage — handled at puzzle/mission layer.

    return events


def ship_in_hazard(ship: Ship, hz: Hazard) -> bool:
    """Return True if the ship's position is within the hazard zone radius."""
    return math.hypot(ship.x - hz.x, ship.y - hz.y) <= hz.radius
