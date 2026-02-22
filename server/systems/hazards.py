"""
Hazard System — Environmental hazard physics.

Applies per-tick effects for hazard zones that the player's ship passes through.

Two hazard sources:
  1. Entity hazards (world.hazards list) — positioned zones with radius.
  2. Sector-type hazards — derived from the sector the ship is currently in.

Entity hazard types and effects:
  nebula         — reduces sensor range; shields recharge slower.
  minefield      — 5.0 HP/s hull damage.
  gravity_well   — caps ship velocity to GRAVITY_WELL_MAX_VEL (100 u/s).
  radiation_zone — 2.0 HP/s hull damage; reduces sensor range.

Sector-type hazard effects:
  nebula         — sensor range × sector.sensor_modifier; shields 50% slower.
  asteroid_field — hull damage when throttle > 30%.
  gravity_well   — velocity capped at GRAVITY_WELL_SECTOR_VEL_CAP (200 u/s).
  radiation_zone — 1.5 HP/s hull damage; shield absorption; sensor reduction.

After tick_hazards(), callers read modifier state via the getter functions to
apply effects in sensors, combat, and AI systems.
"""
from __future__ import annotations

import math

from server.models.ship import Ship
from server.models.world import Hazard, World

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Entity hazard damage rates (per second).
MINEFIELD_DAMAGE_PER_SEC: float = 4.0
RADIATION_DAMAGE_PER_SEC: float = 2.0

# Entity gravity well velocity cap (u/s).
GRAVITY_WELL_MAX_VEL: float = 100.0

# Nebula entity effects (no sector_modifier available for entity hazards).
NEBULA_ENTITY_SENSOR_MODIFIER: float = 0.5
NEBULA_SHIELD_REGEN_MODIFIER: float = 0.5   # applies to both entity and sector nebula

# Asteroid field sector effects.
ASTEROID_THROTTLE_THRESHOLD: float = 30.0    # throttle % above which damage applies
ASTEROID_DAMAGE_PER_SEC: float = 2.0         # hull damage per second at any throttle > threshold

# Gravity well sector effects.
GRAVITY_WELL_SECTOR_VEL_CAP: float = 200.0   # gentler cap than entity hazard

# Radiation zone sector effects.
RADIATION_SECTOR_DAMAGE_PER_SEC: float = 1.5
RADIATION_SHIELD_THRESHOLD: float = 50.0     # combined front+rear HP required for absorption
RADIATION_SHIELD_ABSORPTION_FRAC: float = 0.6  # fraction absorbed when shields are adequate
RADIATION_SENSOR_MODIFIER: float = 0.75     # sensor range multiplier in radiation zone

# ---------------------------------------------------------------------------
# Module-level modifier state (recomputed every tick by tick_hazards)
# ---------------------------------------------------------------------------

_sensor_modifier: float = 1.0
_shield_regen_modifier: float = 1.0
_velocity_cap: float | None = None
_active_hazard_types: list[str] = []


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


def reset_state() -> None:
    """Reset hazard modifier state to defaults. Call at game start/resume."""
    global _sensor_modifier, _shield_regen_modifier, _velocity_cap, _active_hazard_types
    _sensor_modifier = 1.0
    _shield_regen_modifier = 1.0
    _velocity_cap = None
    _active_hazard_types = []


# ---------------------------------------------------------------------------
# Modifier getters
# ---------------------------------------------------------------------------


def get_sensor_modifier() -> float:
    """Current sensor range multiplier (1.0 = unaffected; < 1.0 = reduced)."""
    return _sensor_modifier


def get_shield_regen_modifier() -> float:
    """Current shield regen multiplier (1.0 = unaffected; 0.5 = half speed)."""
    return _shield_regen_modifier


def get_velocity_cap() -> float | None:
    """Current velocity cap in u/s, or None if no gravity hazard is active."""
    return _velocity_cap


def get_active_hazard_types() -> list[str]:
    """Sorted list of hazard type strings currently affecting the ship."""
    return list(_active_hazard_types)


# ---------------------------------------------------------------------------
# Public tick
# ---------------------------------------------------------------------------


def tick_hazards(world: World, ship: Ship, dt: float) -> list[dict]:
    """Apply hazard effects to the player ship for one simulation tick.

    Resets and recomputes all modifier state from scratch on each call.

    Returns a list of event dicts for hazards that dealt hull damage:
      ``{"hazard_id": str, "hazard_type": str, "damage": float}``

    Side-effects:
      - Updates module-level modifier state.
      - Reduces ``ship.hull`` for damage-dealing hazards.
      - Caps ``ship.velocity`` when gravity hazards are present.
    """
    global _sensor_modifier, _shield_regen_modifier, _velocity_cap, _active_hazard_types

    # Reset modifier state for this tick.
    _sensor_modifier = 1.0
    _shield_regen_modifier = 1.0
    min_vel_cap: float | None = None
    active: list[str] = []

    events: list[dict] = []

    # ── Entity hazard zones ─────────────────────────────────────────────────
    for hz in world.hazards:
        if not ship_in_hazard(ship, hz):
            continue

        if hz.hazard_type == "minefield":
            damage = round(MINEFIELD_DAMAGE_PER_SEC * dt, 3)
            ship.hull = max(0.0, ship.hull - damage)
            events.append({"hazard_id": hz.id, "hazard_type": "minefield", "damage": damage})
            if "minefield" not in active:
                active.append("minefield")

        elif hz.hazard_type == "radiation_zone":
            damage = round(RADIATION_DAMAGE_PER_SEC * dt, 3)
            ship.hull = max(0.0, ship.hull - damage)
            events.append({"hazard_id": hz.id, "hazard_type": "radiation_zone", "damage": damage})
            if "radiation_zone" not in active:
                active.append("radiation_zone")
            _sensor_modifier = min(_sensor_modifier, RADIATION_SENSOR_MODIFIER)

        elif hz.hazard_type == "gravity_well":
            cap = GRAVITY_WELL_MAX_VEL
            if min_vel_cap is None or cap < min_vel_cap:
                min_vel_cap = cap
            if "gravity_well" not in active:
                active.append("gravity_well")

        elif hz.hazard_type == "nebula":
            _sensor_modifier = min(_sensor_modifier, NEBULA_ENTITY_SENSOR_MODIFIER)
            _shield_regen_modifier = min(_shield_regen_modifier, NEBULA_SHIELD_REGEN_MODIFIER)
            if "nebula" not in active:
                active.append("nebula")

    # ── Sector-type hazards ─────────────────────────────────────────────────
    if world.sector_grid is not None:
        sector = world.sector_grid.sector_at_position(ship.x, ship.y)
        if sector is not None:
            stype = sector.properties.type
            smod = sector.properties.sensor_modifier

            if stype == "nebula":
                _sensor_modifier = min(_sensor_modifier, smod)
                _shield_regen_modifier = min(_shield_regen_modifier, NEBULA_SHIELD_REGEN_MODIFIER)
                if "nebula" not in active:
                    active.append("nebula")

            elif stype == "asteroid_field":
                if "asteroid_field" not in active:
                    active.append("asteroid_field")
                _sensor_modifier = min(_sensor_modifier, smod)
                if ship.throttle > ASTEROID_THROTTLE_THRESHOLD:
                    damage = round(ASTEROID_DAMAGE_PER_SEC * dt, 3)
                    ship.hull = max(0.0, ship.hull - damage)
                    events.append({
                        "hazard_id": sector.id,
                        "hazard_type": "asteroid_field",
                        "damage": damage,
                    })

            elif stype == "gravity_well":
                if "gravity_well" not in active:
                    active.append("gravity_well")
                cap = GRAVITY_WELL_SECTOR_VEL_CAP
                if min_vel_cap is None or cap < min_vel_cap:
                    min_vel_cap = cap
                _sensor_modifier = min(_sensor_modifier, smod)

            elif stype == "radiation_zone":
                if "radiation_zone" not in active:
                    active.append("radiation_zone")
                _sensor_modifier = min(_sensor_modifier, smod)
                total_shields = ship.shields.front + ship.shields.rear
                absorption = (
                    RADIATION_SHIELD_ABSORPTION_FRAC
                    if total_shields >= RADIATION_SHIELD_THRESHOLD
                    else 0.0
                )
                raw = RADIATION_SECTOR_DAMAGE_PER_SEC * dt
                damage = round(raw * (1.0 - absorption), 3)
                ship.hull = max(0.0, ship.hull - damage)
                events.append({
                    "hazard_id": sector.id,
                    "hazard_type": "radiation_zone",
                    "damage": damage,
                })

    # ── Apply velocity cap ──────────────────────────────────────────────────
    _velocity_cap = min_vel_cap
    if _velocity_cap is not None and ship.velocity > _velocity_cap:
        ship.velocity = _velocity_cap

    _active_hazard_types = active
    return events


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def ship_in_hazard(ship: Ship, hz: Hazard) -> bool:
    """Return True if the ship's position is within the hazard zone radius."""
    return math.hypot(ship.x - hz.x, ship.y - hz.y) <= hz.radius
