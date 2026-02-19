"""
Enemy AI — Behaviour state machine.

Simple state machine for enemy ships: idle → chase → attack → flee.
State transitions are based on distance to the player, health thresholds,
and weapon range. Each enemy type has different parameters.

Public entry point: tick_enemies(enemies, ship, dt) → list[BeamHitEvent]
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from server.models.ship import Ship
from server.models.world import Enemy, Station, ENEMY_TYPE_PARAMS
from server.utils.math_helpers import angle_diff, bearing_to, distance, wrap_angle

# AI turn rate in degrees per second (all enemy types use the same turn rate).
AI_TURN_RATE: float = 90.0


# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------


@dataclass
class BeamHitEvent:
    """Represents a beam hit fired by an enemy this tick."""

    attacker_id: str
    attacker_x: float
    attacker_y: float
    damage: float
    target: str = "player"  # "player" or a station_id


# ---------------------------------------------------------------------------
# Arc check helper
# ---------------------------------------------------------------------------


def beam_in_arc(shooter_heading: float, bearing: float, arc_deg: float) -> bool:
    """Return True if the bearing is within ±arc_deg of the shooter's heading."""
    return abs(angle_diff(shooter_heading, bearing)) <= arc_deg


# ---------------------------------------------------------------------------
# Public tick function
# ---------------------------------------------------------------------------


def tick_enemies(
    enemies: list[Enemy],
    ship: Ship,
    dt: float,
    stations: list[Station] | None = None,
) -> list[BeamHitEvent]:
    """Update all enemy AI states and movement; return any beam hit events.

    When `stations` is non-empty, enemies use station-priority targeting:
    they chase and attack the nearest station rather than the player ship.
    """
    events: list[BeamHitEvent] = []
    dead_ids: list[str] = []

    for enemy in enemies:
        params = ENEMY_TYPE_PARAMS[enemy.type]

        # ── Determine primary target ───────────────────────────────────────
        if stations:
            nearest = min(stations, key=lambda s: distance(enemy.x, enemy.y, s.x, s.y))
            target_x, target_y, target_id = nearest.x, nearest.y, nearest.id
        else:
            target_x, target_y, target_id = ship.x, ship.y, "player"

        dist = distance(enemy.x, enemy.y, target_x, target_y)

        # ── State transitions ─────────────────────────────────────────────
        _update_state(enemy, params, dist)

        # ── Despawn check (fleeing enemy too far away) ────────────────────
        if enemy.ai_state == "flee" and dist > 2.0 * params["detect_range"]:
            dead_ids.append(enemy.id)
            continue

        # ── Movement ──────────────────────────────────────────────────────
        _update_movement(enemy, params, target_x, target_y, dist, dt)

        # ── Beam cooldown ─────────────────────────────────────────────────
        enemy.beam_cooldown = max(0.0, enemy.beam_cooldown - dt)

        # ── Beam fire ─────────────────────────────────────────────────────
        if enemy.ai_state == "attack" and enemy.beam_cooldown <= 0.0:
            brg = bearing_to(enemy.x, enemy.y, target_x, target_y)
            if beam_in_arc(enemy.heading, brg, params["arc_deg"]):
                events.append(
                    BeamHitEvent(
                        attacker_id=enemy.id,
                        attacker_x=enemy.x,
                        attacker_y=enemy.y,
                        damage=params["beam_dmg"],
                        target=target_id,
                    )
                )
                enemy.beam_cooldown = params["beam_cooldown"]

    # Remove despawned enemies in-place (iterate in reverse to preserve indices).
    for eid in dead_ids:
        for i, e in enumerate(enemies):
            if e.id == eid:
                enemies.pop(i)
                break

    return events


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _update_state(enemy: Enemy, params: dict, dist: float) -> None:
    """Apply state-machine transitions."""
    state = enemy.ai_state
    max_hull = params["hull"]

    if state == "idle":
        if dist < params["detect_range"]:
            enemy.ai_state = "chase"

    elif state == "chase":
        if dist < params["weapon_range"]:
            enemy.ai_state = "attack"

    elif state == "attack":
        flee_hp = params["flee_threshold"] * max_hull
        if enemy.hull < flee_hp:
            enemy.ai_state = "flee"

    # "flee" has no return transitions; enemy despawns when far enough away.


def _update_movement(
    enemy: Enemy,
    params: dict,
    target_x: float,
    target_y: float,
    dist: float,
    dt: float,
) -> None:
    """Steer and move the enemy according to its current AI state."""
    state = enemy.ai_state
    max_speed = params["speed"]
    weapon_range = params["weapon_range"]

    # Calculate bearing toward / away from target.
    brg_to_target = bearing_to(enemy.x, enemy.y, target_x, target_y)
    brg_away = wrap_angle(brg_to_target + 180.0)

    if state == "idle":
        # Slow drift — no steering change needed.
        enemy.velocity = max(0.0, enemy.velocity - max_speed * dt)

    elif state == "chase":
        desired_heading = brg_to_target
        _steer(enemy, desired_heading, dt)
        enemy.velocity = max_speed

    elif state == "attack":
        enemy_type = enemy.type

        if enemy_type == "scout":
            if dist < 2_000.0:
                # Strafe: +90° offset on bearing to target to circle.
                desired_heading = wrap_angle(brg_to_target + 90.0)
            else:
                desired_heading = brg_to_target
            _steer(enemy, desired_heading, dt)
            enemy.velocity = max_speed

        elif enemy_type == "cruiser":
            # Press toward target.
            _steer(enemy, brg_to_target, dt)
            enemy.velocity = max_speed

        elif enemy_type == "destroyer":
            # Maintain standoff: approach if too far, back away if too close.
            standoff_far = weapon_range
            standoff_close = weapon_range * 0.6
            if dist > standoff_far:
                _steer(enemy, brg_to_target, dt)
                enemy.velocity = max_speed
            elif dist < standoff_close:
                _steer(enemy, brg_away, dt)
                enemy.velocity = max_speed
            else:
                # In the sweet spot — slow down.
                enemy.velocity = max(0.0, enemy.velocity - max_speed * dt)

    elif state == "flee":
        _steer(enemy, brg_away, dt)
        enemy.velocity = max_speed

    # Move in current heading direction.
    heading_rad = math.radians(enemy.heading)
    enemy.x += enemy.velocity * math.sin(heading_rad) * dt
    enemy.y -= enemy.velocity * math.cos(heading_rad) * dt


def _steer(enemy: Enemy, desired_heading: float, dt: float) -> None:
    """Rotate enemy toward desired_heading at AI_TURN_RATE."""
    diff = angle_diff(enemy.heading, desired_heading)
    max_turn = AI_TURN_RATE * dt
    if abs(diff) <= max_turn:
        enemy.heading = desired_heading
    else:
        sign = 1.0 if diff > 0.0 else -1.0
        enemy.heading = wrap_angle(enemy.heading + sign * max_turn)
