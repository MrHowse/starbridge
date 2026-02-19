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


# ---------------------------------------------------------------------------
# Arc check (shared by player and enemy callers)
# ---------------------------------------------------------------------------


def beam_in_arc(shooter_heading: float, bearing: float, arc_deg: float) -> bool:
    """Return True if *bearing* is within ±arc_deg of *shooter_heading*."""
    return abs(angle_diff(shooter_heading, bearing)) <= arc_deg


# ---------------------------------------------------------------------------
# Damage pipeline — player ship
# ---------------------------------------------------------------------------


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
    # 1. Determine whether the hit is from the front or rear.
    brg = bearing_to(ship.x, ship.y, attacker_x, attacker_y)
    diff = angle_diff(ship.heading, brg)
    is_front = abs(diff) < 90.0

    # 2. Shield absorption: shields absorb up to shield_hp × COEFF of the hit.
    if is_front:
        absorbed = min(ship.shields.front * SHIELD_ABSORPTION_COEFF, damage)
        ship.shields.front = max(0.0, ship.shields.front - absorbed / SHIELD_ABSORPTION_COEFF)
    else:
        absorbed = min(ship.shields.rear * SHIELD_ABSORPTION_COEFF, damage)
        ship.shields.rear = max(0.0, ship.shields.rear - absorbed / SHIELD_ABSORPTION_COEFF)

    hull_damage = damage - absorbed

    # 3. Hull damage + optional system damage roll + crew casualties.
    damaged_systems: list[tuple[str, float]] = []
    if hull_damage > 0:
        ship.hull = max(0.0, ship.hull - hull_damage)
        if rng.random() < HULL_SYSTEM_DAMAGE_CHANCE:
            system_name = rng.choice(list(ship.systems.keys()))
            dmg = rng.uniform(SYSTEM_DAMAGE_MIN, SYSTEM_DAMAGE_MAX)
            ship.systems[system_name].health = max(0.0, ship.systems[system_name].health - dmg)
            damaged_systems.append((system_name, ship.systems[system_name].health))
        # Crew casualties: deterministic count (1 per CREW_CASUALTY_PER_HULL_DAMAGE points).
        # Uses rng.choice only for deck selection; does not add an extra rng.random() call.
        casualties = int(hull_damage / CREW_CASUALTY_PER_HULL_DAMAGE)
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
) -> None:
    """Apply damage to an enemy ship (shields + hull; no system damage roll)."""
    brg = bearing_to(enemy.x, enemy.y, attacker_x, attacker_y)
    diff = angle_diff(enemy.heading, brg)
    is_front = abs(diff) < 90.0

    if is_front:
        absorbed = min(enemy.shield_front * SHIELD_ABSORPTION_COEFF, damage)
        enemy.shield_front = max(0.0, enemy.shield_front - absorbed / SHIELD_ABSORPTION_COEFF)
    else:
        absorbed = min(enemy.shield_rear * SHIELD_ABSORPTION_COEFF, damage)
        enemy.shield_rear = max(0.0, enemy.shield_rear - absorbed / SHIELD_ABSORPTION_COEFF)

    enemy.hull = max(0.0, enemy.hull - (damage - absorbed))


# ---------------------------------------------------------------------------
# Shield regeneration
# ---------------------------------------------------------------------------


def regenerate_shields(ship: Ship) -> None:
    """Regenerate player shields each tick, scaled by shield system efficiency."""
    regen = SHIELD_REGEN_PER_TICK * ship.systems["shields"].efficiency
    ship.shields.front = min(100.0, ship.shields.front + regen)
    ship.shields.rear = min(100.0, ship.shields.rear + regen)
