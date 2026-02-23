"""
Combat System — Damage calculation and weapon firing.

Handles beam weapon mechanics (arc checking, damage over time), torpedo
mechanics (projectile travel, impact), and the damage pipeline
(weapon → shield → hull → system damage).
"""
from __future__ import annotations

import random as _random_module
from typing import Any

from server.models.ship import Ship
from server.models.world import Enemy
from server.utils.math_helpers import angle_diff, bearing_to

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BEAM_PLAYER_DAMAGE: float = 20.0       # per fire_beams command
CREW_CASUALTY_PER_HULL_DAMAGE: float = 5.0  # 1 casualty per N hull damage points
BEAM_PLAYER_ARC_DEG: float = 45.0      # ±45° from heading
BEAM_PLAYER_RANGE: float = 8_000.0
TORPEDO_DAMAGE: float = 50.0
SHIELD_ABSORPTION_COEFF: float = 0.8   # shields absorb 80% of their value per hit
HULL_SYSTEM_DAMAGE_CHANCE: float = 0.25
SYSTEM_DAMAGE_MIN: float = 10.0
SYSTEM_DAMAGE_MAX: float = 25.0
SHIELD_REGEN_PER_TICK: float = 0.5     # HP/tick at full shield efficiency
COUNTERMEASURE_REDUCTION: float = 0.30  # fraction of hull damage absorbed per charge
# Beam frequency matching
FREQ_MATCH_MULT: float = 1.5     # matched frequency → 50% bonus damage
FREQ_MISMATCH_MULT: float = 0.5  # mismatched frequency → 50% penalty


# ---------------------------------------------------------------------------
# Arc check (shared by player and enemy callers)
# ---------------------------------------------------------------------------


def beam_in_arc(shooter_heading: float, bearing: float, arc_deg: float) -> bool:
    """Return True if *bearing* is within ±arc_deg of *shooter_heading*."""
    return abs(angle_diff(shooter_heading, bearing)) <= arc_deg


# ---------------------------------------------------------------------------
# Damage pipeline — player ship
# ---------------------------------------------------------------------------


def get_hit_facing(
    ship_heading: float,
    ship_x: float,
    ship_y: float,
    attacker_x: float,
    attacker_y: float,
) -> str:
    """Return 'fore'|'aft'|'port'|'starboard' for an incoming hit.

    Uses the attacker's bearing relative to the ship's heading:
      fore:      |diff| ≤ 45°
      aft:       |diff| ≥ 135°
      starboard: diff  > 0  (right side)
      port:      diff  < 0  (left side)
    """
    brg  = bearing_to(ship_x, ship_y, attacker_x, attacker_y)
    diff = angle_diff(ship_heading, brg)   # -180..+180; positive = clockwise = starboard
    if abs(diff) <= 45.0:
        return "fore"
    if abs(diff) >= 135.0:
        return "aft"
    return "starboard" if diff > 0 else "port"


def apply_hit_to_player(
    ship: Ship,
    damage: float,
    attacker_x: float,
    attacker_y: float,
    rng: Any = _random_module,
) -> list[tuple[str, float]]:
    """Apply damage to the player ship.

    Returns a list of (system_name, new_health) for any system that took
    structural damage this hit (for broadcasting ship.system_damaged events).
    """
    # 1. Determine which facing takes the hit.
    facing    = get_hit_facing(ship.heading, ship.x, ship.y, attacker_x, attacker_y)
    shield_hp = getattr(ship.shields, facing)

    # 2. Shield absorption: shields absorb up to shield_hp × COEFF of the hit.
    absorbed = min(shield_hp * SHIELD_ABSORPTION_COEFF, damage)
    setattr(ship.shields, facing, max(0.0, shield_hp - absorbed / SHIELD_ABSORPTION_COEFF))

    # Apply difficulty enemy damage multiplier.
    hull_damage = (damage - absorbed) * ship.difficulty.enemy_damage_multiplier

    # Apply Electronic Warfare countermeasure reduction.
    if hull_damage > 0.0 and ship.ew_countermeasure_active and ship.countermeasure_charges > 0:
        hull_damage *= (1.0 - COUNTERMEASURE_REDUCTION)
        ship.countermeasure_charges = max(0, ship.countermeasure_charges - 1)
        if ship.countermeasure_charges == 0:
            ship.ew_countermeasure_active = False

    # 3. Hull damage + optional system damage roll + crew casualties.
    damaged_systems: list[tuple[str, float]] = []
    if hull_damage > 0:
        ship.hull = max(0.0, ship.hull - hull_damage)
        if rng.random() < ship.difficulty.component_damage_chance:
            system_name = rng.choice(list(ship.systems.keys()))
            dmg = rng.uniform(SYSTEM_DAMAGE_MIN, SYSTEM_DAMAGE_MAX) * ship.difficulty.component_severity_multiplier
            ship.systems[system_name].health = max(0.0, ship.systems[system_name].health - dmg)
            damaged_systems.append((system_name, ship.systems[system_name].health))
        # Crew casualties scaled by difficulty.injury_chance (normalised to officer=0.4).
        casualties = int((hull_damage * ship.difficulty.injury_chance / 0.4) / CREW_CASUALTY_PER_HULL_DAMAGE)
        if casualties > 0 and ship.crew.decks:
            deck_name = rng.choice(list(ship.crew.decks.keys()))
            ship.crew.apply_casualties(deck_name, casualties)

    return damaged_systems


# ---------------------------------------------------------------------------
# Damage pipeline — enemy
# ---------------------------------------------------------------------------


def apply_hit_to_enemy(
    enemy: Enemy,
    damage: float,
    attacker_x: float,
    attacker_y: float,
    beam_frequency: str = "",
    shield_absorption_mult: float = 1.0,
) -> None:
    """Apply damage to an enemy ship (shields + hull; no system damage roll).

    If *beam_frequency* matches the enemy's shield_frequency the damage is
    multiplied by FREQ_MATCH_MULT (1.5×); a mismatch applies FREQ_MISMATCH_MULT
    (0.5×). No effect when either side has no frequency set.

    *shield_absorption_mult* scales the shield absorption coefficient — 1.0 is
    full absorption, 0.25 means shields only absorb 25% (piercing torpedoes).
    """
    # Apply beam frequency modifier before shield absorption.
    if beam_frequency and enemy.shield_frequency:
        if beam_frequency == enemy.shield_frequency:
            damage *= FREQ_MATCH_MULT
        else:
            damage *= FREQ_MISMATCH_MULT

    brg = bearing_to(enemy.x, enemy.y, attacker_x, attacker_y)
    diff = angle_diff(enemy.heading, brg)
    is_front = abs(diff) < 90.0

    eff_coeff = SHIELD_ABSORPTION_COEFF * shield_absorption_mult
    if is_front:
        absorbed = min(enemy.shield_front * eff_coeff, damage)
        if eff_coeff > 0.0:
            enemy.shield_front = max(0.0, enemy.shield_front - absorbed / eff_coeff)
    else:
        absorbed = min(enemy.shield_rear * eff_coeff, damage)
        if eff_coeff > 0.0:
            enemy.shield_rear = max(0.0, enemy.shield_rear - absorbed / eff_coeff)

    enemy.hull = max(0.0, enemy.hull - (damage - absorbed))


# ---------------------------------------------------------------------------
# Shield regeneration
# ---------------------------------------------------------------------------


def regenerate_shields(ship: Ship, hazard_modifier: float = 1.0) -> None:
    """Regenerate player shields each tick, scaled by shield system efficiency.

    Each facing regenerates toward its distribution-based maximum.
    *hazard_modifier* reduces the regen rate when inside a nebula (0.5 = 50%
    slower).  Defaults to 1.0 (no reduction).
    """
    from server.models.ship import TOTAL_SHIELD_CAPACITY
    regen = SHIELD_REGEN_PER_TICK * ship.systems["shields"].efficiency * hazard_modifier
    for facing in ("fore", "aft", "port", "starboard"):
        max_hp  = TOTAL_SHIELD_CAPACITY * ship.shield_distribution[facing]
        current = getattr(ship.shields, facing)
        setattr(ship.shields, facing, min(max_hp, current + regen))
