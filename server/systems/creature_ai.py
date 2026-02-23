"""Creature AI — per-type state machines for space creatures (v0.05k).

Five creature types each with unique behaviour:
  void_whale   — passive, flees when approached, generates sensor-disrupting wake
  rift_stalker — territorial predator, attacks intruders, 4 interaction paths
  hull_leech   — parasitic, approaches and attaches to the player hull
  swarm        — hive intelligence, adapts to weapon types
  leviathan    — dormant giant, redirectable via communication chain

Public entry point: tick_creatures(creatures, ship, dt) -> list[BeamHitEvent]
"""
from __future__ import annotations

import math
import random

from server.models.world import Creature, CREATURE_TYPE_PARAMS
from server.models.ship import Ship
from server.systems.ai import BeamHitEvent
from server.utils.math_helpers import bearing_to, distance

# Turn rate for creature heading changes (degrees per second).
CREATURE_TURN_RATE: float = 60.0


# ---------------------------------------------------------------------------
# Movement helpers
# ---------------------------------------------------------------------------


def _apply_movement(c: Creature, dt: float) -> None:
    """Update creature position from current heading and velocity."""
    rad = math.radians(c.heading)
    c.x += math.sin(rad) * c.velocity * dt
    c.y -= math.cos(rad) * c.velocity * dt


def _turn_toward(c: Creature, target_heading: float, dt: float) -> None:
    """Rotate creature heading toward target_heading at CREATURE_TURN_RATE."""
    diff = ((target_heading - c.heading + 180.0) % 360.0) - 180.0
    max_turn = CREATURE_TURN_RATE * dt
    c.heading = (c.heading + max(min(diff, max_turn), -max_turn)) % 360.0


# ---------------------------------------------------------------------------
# Per-type AI tickers
# ---------------------------------------------------------------------------


def _tick_void_whale(c: Creature, ship: Ship, dt: float) -> list[BeamHitEvent]:
    """Passive — drifts, flees when player gets close, emits sensor wake."""
    params = CREATURE_TYPE_PARAMS["void_whale"]
    dist = distance(c.x, c.y, ship.x, ship.y)

    if c.behaviour_state == "idle":
        c.velocity = params["speed"] * 0.3
        # Gentle random heading drift.
        c.heading = (c.heading + random.uniform(-2.0, 2.0)) % 360.0
        if dist < params["flee_range"]:
            c.behaviour_state = "fleeing"
            c.wake_active = True
            c.wake_timer = params["wake_duration"]

    elif c.behaviour_state == "fleeing":
        # Flee directly away from the player.
        flee_bearing = bearing_to(ship.x, ship.y, c.x, c.y)
        _turn_toward(c, flee_bearing, dt)
        c.velocity = params["speed"]
        if c.wake_timer > 0:
            c.wake_timer = max(0.0, c.wake_timer - dt)
            if c.wake_timer <= 0:
                c.wake_active = False
        # Return to idle once far enough away.
        if dist > params["flee_range"] * 5:
            c.behaviour_state = "idle"
            c.wake_active = False

    _apply_movement(c, dt)
    return []


def _tick_rift_stalker(c: Creature, ship: Ship, dt: float) -> list[BeamHitEvent]:
    """Territorial — attacks player inside territory; 4 interaction paths."""
    events: list[BeamHitEvent] = []
    params = CREATURE_TYPE_PARAMS["rift_stalker"]
    dist = distance(c.x, c.y, ship.x, ship.y)
    dist_to_territory = distance(c.x, c.y, c.territory_x, c.territory_y)

    # Tick sedation timer.
    if c.sedated_timer > 0:
        c.sedated_timer = max(0.0, c.sedated_timer - dt)
        c.behaviour_state = "sedated"
        c.velocity = 0.0
        return []

    if c.behaviour_state == "sedated":
        # Sedation just expired — return to idle.
        c.behaviour_state = "idle"

    # Hull regeneration.
    if c.hull < c.hull_max:
        c.regen_timer += dt
        if c.regen_timer >= 1.0:
            c.hull = min(c.hull_max, c.hull + params["regen_rate"])
            c.regen_timer = 0.0

    if c.behaviour_state == "idle":
        # Patrol territory perimeter slowly.
        c.velocity = params["speed"] * 0.3
        c.heading = (c.heading + 1.5 * dt * 10.0) % 360.0
        if dist_to_territory > c.territory_radius:
            toward_territory = bearing_to(c.x, c.y, c.territory_x, c.territory_y)
            _turn_toward(c, toward_territory, dt)
        if dist < c.territory_radius:
            c.behaviour_state = "aggressive"

    elif c.behaviour_state == "aggressive":
        c.velocity = params["speed"]
        _turn_toward(c, bearing_to(c.x, c.y, ship.x, ship.y), dt)
        if dist < params["weapon_range"]:
            c.behaviour_state = "attacking"
        if c.hull < c.hull_max * 0.2:
            c.behaviour_state = "fleeing"

    elif c.behaviour_state == "attacking":
        c.velocity = params["speed"] * 0.5
        _turn_toward(c, bearing_to(c.x, c.y, ship.x, ship.y), dt)
        c.beam_cooldown -= dt
        if c.beam_cooldown <= 0 and dist < params["weapon_range"]:
            c.beam_cooldown = params["beam_cooldown"]
            events.append(BeamHitEvent(
                attacker_id=c.id,
                attacker_x=c.x,
                attacker_y=c.y,
                damage=params["beam_dmg"],
                shield_bypass=params.get("shield_bypass", 0.0),
            ))
        if dist > params["weapon_range"] * 1.5:
            c.behaviour_state = "aggressive"
        if c.hull < c.hull_max * 0.2:
            c.behaviour_state = "fleeing"

    elif c.behaviour_state == "fleeing":
        _turn_toward(c, bearing_to(ship.x, ship.y, c.x, c.y), dt)
        c.velocity = params["speed"]
        if dist > c.territory_radius * 2:
            c.behaviour_state = "idle"

    _apply_movement(c, dt)
    return events


def _tick_hull_leech(c: Creature, ship: Ship, dt: float) -> list[BeamHitEvent]:
    """Parasitic — approaches and attaches to hull; deals periodic damage."""
    events: list[BeamHitEvent] = []
    params = CREATURE_TYPE_PARAMS["hull_leech"]
    dist = distance(c.x, c.y, ship.x, ship.y)

    if c.attached:
        # Ride the ship.
        c.x = ship.x
        c.y = ship.y
        c.velocity = 0.0
        c.leech_damage_timer -= dt
        if c.leech_damage_timer <= 0:
            c.leech_damage_timer = params["damage_interval"]
            events.append(BeamHitEvent(
                attacker_id=c.id,
                attacker_x=c.x,
                attacker_y=c.y,
                damage=params["damage_per_interval"],
                shield_bypass=params.get("shield_bypass", 0.0),
            ))
        return events

    if c.behaviour_state == "idle":
        c.velocity = params["speed"] * 0.2
        c.heading = (c.heading + random.uniform(-3.0, 3.0)) % 360.0
        if dist < 5_000.0:
            c.behaviour_state = "approaching"

    elif c.behaviour_state == "approaching":
        _turn_toward(c, bearing_to(c.x, c.y, ship.x, ship.y), dt)
        c.velocity = params["speed"]
        if dist < params["attach_range"]:
            c.behaviour_state = "attached"
            c.attached = True
            c.detected = True  # Becomes visible after attaching.
            c.leech_damage_timer = params["damage_interval"]
            c.velocity = 0.0
            return events

    _apply_movement(c, dt)
    return events


def _tick_swarm(c: Creature, ship: Ship, dt: float) -> list[BeamHitEvent]:
    """Hive intelligence — attacks player, adapts to weapon types."""
    events: list[BeamHitEvent] = []
    params = CREATURE_TYPE_PARAMS["swarm"]
    dist = distance(c.x, c.y, ship.x, ship.y)

    if c.behaviour_state == "dispersed":
        # EW-disrupted: flee from player.
        _turn_toward(c, bearing_to(ship.x, ship.y, c.x, c.y), dt)
        c.velocity = params["speed"]
        _apply_movement(c, dt)
        return []

    if c.behaviour_state == "idle":
        c.velocity = params["speed"] * 0.1
        if dist < params["swarm_range"]:
            c.behaviour_state = "attacking"

    elif c.behaviour_state in ("attacking", "spread", "clustered"):
        _turn_toward(c, bearing_to(c.x, c.y, ship.x, ship.y), dt)
        c.velocity = params["speed"] * 0.5
        c.beam_cooldown -= dt
        if c.beam_cooldown <= 0 and dist < params["weapon_range"]:
            c.beam_cooldown = params["beam_cooldown"]
            events.append(BeamHitEvent(
                attacker_id=c.id,
                attacker_x=c.x,
                attacker_y=c.y,
                damage=params["beam_dmg"],
                shield_bypass=params.get("shield_bypass", 0.0),
            ))

    _apply_movement(c, dt)
    return events


def _tick_leviathan(c: Creature, ship: Ship, dt: float) -> list[BeamHitEvent]:
    """Dormant giant — wanders toward populated sector; redirectable via Comms."""
    events: list[BeamHitEvent] = []
    params = CREATURE_TYPE_PARAMS["leviathan"]
    dist = distance(c.x, c.y, ship.x, ship.y)

    if c.behaviour_state == "redirected":
        # Head away (south) — mission resolved.
        _turn_toward(c, 180.0, dt)
        c.velocity = params["speed"]
        _apply_movement(c, dt)
        return []

    if c.behaviour_state == "dormant":
        c.velocity = 0.0
        if dist < params["wake_range"] or c.hull < c.hull_max:
            c.behaviour_state = "wandering"

    elif c.behaviour_state == "wandering":
        # Slowly head north (toward populated sector).
        _turn_toward(c, 0.0, dt)
        c.velocity = params["speed"]
        if c.communication_progress >= 100.0:
            c.behaviour_state = "redirected"

    elif c.behaviour_state == "agitated":
        _turn_toward(c, bearing_to(c.x, c.y, ship.x, ship.y), dt)
        c.velocity = params["speed"]
        c.beam_cooldown -= dt
        if c.beam_cooldown <= 0 and dist < params["weapon_range"]:
            c.beam_cooldown = params["beam_cooldown"]
            events.append(BeamHitEvent(
                attacker_id=c.id,
                attacker_x=c.x,
                attacker_y=c.y,
                damage=params["beam_dmg"],
                shield_bypass=params.get("shield_bypass", 0.0),
            ))
        if c.communication_progress >= 100.0:
            c.behaviour_state = "redirected"

    _apply_movement(c, dt)
    return events


# ---------------------------------------------------------------------------
# Dispatch table + public entry point
# ---------------------------------------------------------------------------

_TICKERS = {
    "void_whale":   _tick_void_whale,
    "rift_stalker": _tick_rift_stalker,
    "hull_leech":   _tick_hull_leech,
    "swarm":        _tick_swarm,
    "leviathan":    _tick_leviathan,
}


def tick_creatures(
    creatures: list[Creature],
    ship: Ship,
    dt: float,
) -> list[BeamHitEvent]:
    """Update all creature AI states and movement; return beam hit events."""
    events: list[BeamHitEvent] = []
    for creature in creatures:
        if creature.hull <= 0.0 and not creature.attached:
            continue
        ticker = _TICKERS.get(creature.creature_type)
        if ticker is not None:
            events.extend(ticker(creature, ship, dt))
    return events
