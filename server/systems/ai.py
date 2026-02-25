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
    target: str = "player"         # "player" or a station_id
    shield_bypass: float = 0.0     # fraction of damage that ignores shields (0–1)


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
    sensor_modifier: float = 1.0,
    *,
    difficulty: object | None = None,
    ghosts: list[dict] | None = None,
    ghost_class: str | None = None,
    freq_lock_target_ids: set[str] | None = None,
) -> list[BeamHitEvent]:
    """Update all enemy AI states and movement; return any beam hit events.

    When `stations` is non-empty, enemies use station-priority targeting:
    they chase and attack the nearest station rather than the player ship.

    *sensor_modifier* scales each enemy's detect_range to model nebula /
    hazard concealment (e.g. 0.5 = half the normal detection range).

    *difficulty* — a DifficultyPreset object. When provided, ``enemy_accuracy``
    scales beam hit probability and ``enemy_ai_aggression`` adjusts the flee
    threshold (higher = enemies stay in the fight longer).

    *ghosts* — ghost contacts deployed by corvette ECM. Enemies may target
    ghosts instead of the player.

    *ghost_class* — sensor disguise. Certain classes alter enemy AI behaviour.

    *freq_lock_target_ids* — entities under frequency lock; suffer accuracy debuff.
    """
    import random as _rng_mod
    from server.systems.combat import calculate_effective_profile
    accuracy_mult = getattr(difficulty, "enemy_accuracy", 1.0) if difficulty else 1.0
    # v0.07: target profile reduces hit chance on the player ship.
    effective_profile = calculate_effective_profile(ship)
    # Default aggression=0.25 (no scaling) when no difficulty is provided;
    # Officer preset uses 0.75 which halves the effective flee threshold.
    aggression = getattr(difficulty, "enemy_ai_aggression", 0.25) if difficulty else 0.25
    events: list[BeamHitEvent] = []
    dead_ids: list[str] = []

    for enemy in enemies:
        params = ENEMY_TYPE_PARAMS[enemy.type]
        eff_detect_range = params["detect_range"] * sensor_modifier

        # ── Determine primary target ───────────────────────────────────────
        if stations:
            nearest = min(stations, key=lambda s: distance(enemy.x, enemy.y, s.x, s.y))
            target_x, target_y, target_id = nearest.x, nearest.y, nearest.id
        else:
            target_x, target_y, target_id = ship.x, ship.y, "player"
            # Corvette ECM: ghosts act as alternate targets
            if ghosts:
                candidates: list[tuple[float, float, float, str]] = [
                    (ship.x, ship.y, distance(enemy.x, enemy.y, ship.x, ship.y), "player"),
                ]
                for g in ghosts:
                    gd = distance(enemy.x, enemy.y, g["x"], g["y"])
                    if gd <= eff_detect_range:
                        candidates.append((g["x"], g["y"], gd, g["id"]))
                nearest_c = min(candidates, key=lambda c: c[2])
                target_x, target_y, target_id = nearest_c[0], nearest_c[1], nearest_c[3]

        dist = distance(enemy.x, enemy.y, target_x, target_y)

        # ── State transitions ─────────────────────────────────────────────
        _update_state(enemy, params, dist, eff_detect_range, aggression=aggression,
                       ghost_class=ghost_class)

        # ── Despawn check (fleeing enemy too far away) ────────────────────
        if enemy.ai_state == "flee" and dist > 2.0 * eff_detect_range:
            dead_ids.append(enemy.id)
            continue

        # ── Movement ──────────────────────────────────────────────────────
        _update_movement(enemy, params, target_x, target_y, dist, dt)

        # ── Beam cooldown ─────────────────────────────────────────────────
        enemy.beam_cooldown = max(0.0, enemy.beam_cooldown - dt)

        # ── EMP stun decay ────────────────────────────────────────────────
        if enemy.stun_ticks > 0:
            enemy.stun_ticks -= 1

        # ── EW intrusion stun decay ───────────────────────────────────────
        if enemy.intrusion_stun_ticks > 0:
            enemy.intrusion_stun_ticks -= 1

        # ── Beam fire (blocked when stunned or intruded) ──────────────────
        stunned = enemy.stun_ticks > 0 or enemy.intrusion_stun_ticks > 0
        if enemy.ai_state == "attack" and enemy.beam_cooldown <= 0.0 and not stunned:
            brg = bearing_to(enemy.x, enemy.y, target_x, target_y)
            if beam_in_arc(enemy.heading, brg, params["arc_deg"]):
                # Accuracy check: miss probability scales with difficulty × target profile.
                # Target profile only applies vs player ship, not stations.
                profile = effective_profile if target_id == "player" else 1.0
                hit_chance = min(1.0, accuracy_mult * profile)
                # Frequency lock debuff: 15% accuracy penalty on locked enemies.
                if freq_lock_target_ids and enemy.id in freq_lock_target_ids:
                    hit_chance *= 0.85
                if hit_chance < 1.0 and _rng_mod.random() > hit_chance:
                    enemy.beam_cooldown = params["beam_cooldown"]
                    continue  # miss
                # Jamming reduces beam damage (jam_factor=0 → full damage).
                effective_dmg = params["beam_dmg"] * max(0.0, 1.0 - enemy.jam_factor)
                events.append(
                    BeamHitEvent(
                        attacker_id=enemy.id,
                        attacker_x=enemy.x,
                        attacker_y=enemy.y,
                        damage=effective_dmg,
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


def _update_state(
    enemy: Enemy,
    params: dict,
    dist: float,
    detect_range: float | None = None,
    aggression: float = 0.75,
    ghost_class: str | None = None,
) -> None:
    """Apply state-machine transitions.

    *detect_range* overrides ``params["detect_range"]`` when provided (used by
    hazard sensor-modifier to model enemy detection in nebulae).

    *aggression* scales the flee threshold: higher values (closer to 1.0) mean
    the enemy stays in the fight longer (flees at lower HP fraction).

    *ghost_class* — corvette sensor disguise. "battleship"/"destroyer" cause
    enemies to flee on detection; "freighter"/"transport" increase the detect
    range threshold by 50% (enemies less alert to civilians).
    """
    state = enemy.ai_state
    max_hull = params["hull"]
    eff_detect = detect_range if detect_range is not None else params["detect_range"]
    # Ghost class influence on detection threshold.
    if ghost_class in ("freighter", "transport"):
        eff_detect *= 1.5

    if state == "idle":
        if dist < eff_detect:
            # Ghost class bluff: enemies flee from large warship signatures.
            if ghost_class in ("battleship", "destroyer"):
                enemy.ai_state = "flee"
            else:
                enemy.ai_state = "chase"

    elif state == "chase":
        if dist < params["weapon_range"]:
            enemy.ai_state = "attack"

    elif state == "attack":
        # aggression scales flee_threshold: at 1.0 use full threshold,
        # at 0.5 flee at double the threshold (flee earlier).
        eff_flee = params["flee_threshold"] * max(0.1, 1.0 - aggression + 0.25)
        if enemy.hull < eff_flee * max_hull:
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
