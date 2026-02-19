"""
Weapons sub-module for the game loop.

Manages all weapons state and computation: target selection, torpedo ammo,
tube cooldowns, beam/torpedo firing, torpedo movement, and applying enemy
beam hits to the player or stations.
"""
from __future__ import annotations

import math

from server.models.messages import Message
from server.models.ship import Ship
from server.models.world import Torpedo, World
from server.systems.combat import (
    BEAM_PLAYER_ARC_DEG,
    BEAM_PLAYER_DAMAGE,
    BEAM_PLAYER_RANGE,
    TORPEDO_DAMAGE,
    apply_hit_to_enemy,
    apply_hit_to_player,
    beam_in_arc,
)
from server.utils.math_helpers import bearing_to, distance

TORPEDO_RELOAD_TIME: float = 5.0  # seconds; scaled by torpedo system efficiency

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_weapons_target: str | None = None
_torpedo_ammo: int = 10
_tube_cooldowns: list[float] = [0.0, 0.0]
_entity_counter: int = 0


def reset(initial_ammo: int = 10) -> None:
    """Reset all weapons state. Call at game start."""
    global _weapons_target, _torpedo_ammo, _tube_cooldowns, _entity_counter
    _weapons_target = None
    _torpedo_ammo = initial_ammo
    _tube_cooldowns = [0.0, 0.0]
    _entity_counter = 0


# ---------------------------------------------------------------------------
# State accessors
# ---------------------------------------------------------------------------


def get_target() -> str | None:
    return _weapons_target


def set_target(entity_id: str | None) -> None:
    global _weapons_target
    _weapons_target = entity_id


def get_ammo() -> int:
    return _torpedo_ammo


def set_ammo(ammo: int) -> None:
    global _torpedo_ammo
    _torpedo_ammo = ammo


def get_cooldowns() -> list[float]:
    return _tube_cooldowns


def tick_cooldowns(dt: float) -> None:
    _tube_cooldowns[0] = max(0.0, _tube_cooldowns[0] - dt)
    _tube_cooldowns[1] = max(0.0, _tube_cooldowns[1] - dt)


def next_entity_id(prefix: str) -> str:
    global _entity_counter
    _entity_counter += 1
    return f"{prefix}_{_entity_counter}"


# ---------------------------------------------------------------------------
# Firing helpers
# ---------------------------------------------------------------------------


def fire_player_beams(ship: Ship, world: World) -> tuple[str, dict] | None:
    """Fire player beam weapons at the selected target. Returns broadcast event or None."""
    global _weapons_target

    if _weapons_target is None:
        return None

    target = next((e for e in world.enemies if e.id == _weapons_target), None)
    if target is None:
        return None

    dist = distance(ship.x, ship.y, target.x, target.y)
    if dist > BEAM_PLAYER_RANGE:
        return None

    brg = bearing_to(ship.x, ship.y, target.x, target.y)
    if not beam_in_arc(ship.heading, brg, BEAM_PLAYER_ARC_DEG):
        return None

    dmg = BEAM_PLAYER_DAMAGE * ship.systems["beams"].efficiency
    apply_hit_to_enemy(target, dmg, ship.x, ship.y)

    if target.hull <= 0.0:
        world.enemies = [e for e in world.enemies if e.id != target.id]
        if _weapons_target == target.id:
            _weapons_target = None

    return (
        "weapons.beam_fired",
        {
            "target_id": target.id,
            "target_x": target.x,
            "target_y": target.y,
            "damage": round(dmg, 2),
        },
    )


def fire_torpedo(ship: Ship, world: World, tube: int) -> tuple[str, dict] | None:
    """Launch a torpedo from the specified tube. Returns broadcast event or None."""
    global _torpedo_ammo
    tube_idx = tube - 1
    reload_time = TORPEDO_RELOAD_TIME / max(0.01, ship.systems["torpedoes"].efficiency)

    if _torpedo_ammo <= 0:
        return None
    if _tube_cooldowns[tube_idx] > 0.0:
        return None

    _torpedo_ammo -= 1
    _tube_cooldowns[tube_idx] = reload_time

    torp = Torpedo(
        id=next_entity_id("torpedo"),
        owner="player",
        x=ship.x,
        y=ship.y,
        heading=ship.heading,
    )
    world.torpedoes.append(torp)

    return (
        "weapons.torpedo_fired",
        {"torpedo_id": torp.id, "tube": tube},
    )


# ---------------------------------------------------------------------------
# Per-tick helpers
# ---------------------------------------------------------------------------


def tick_torpedoes(world: World) -> list[dict]:
    """Move all torpedoes and check for collisions. Returns hit event dicts."""
    from server.game_loop_physics import TICK_DT

    heading_rad_cache: dict[str, float] = {}
    dead_torpedo_ids: list[str] = []
    events: list[dict] = []

    for torp in world.torpedoes:
        if torp.id not in heading_rad_cache:
            heading_rad_cache[torp.id] = math.radians(torp.heading)
        h_rad = heading_rad_cache[torp.id]

        torp.x += torp.velocity * math.sin(h_rad) * TICK_DT
        torp.y -= torp.velocity * math.cos(h_rad) * TICK_DT
        torp.distance_travelled += torp.velocity * TICK_DT

        if torp.distance_travelled >= Torpedo.MAX_RANGE:
            dead_torpedo_ids.append(torp.id)
            continue

        if torp.owner == "player":
            hit_enemy = None
            for enemy in world.enemies:
                if distance(torp.x, torp.y, enemy.x, enemy.y) < 200.0:
                    hit_enemy = enemy
                    break
            if hit_enemy is not None:
                apply_hit_to_enemy(hit_enemy, TORPEDO_DAMAGE, torp.x, torp.y)
                events.append(
                    {
                        "torpedo_id": torp.id,
                        "target_id": hit_enemy.id,
                        "damage": TORPEDO_DAMAGE,
                    }
                )
                if hit_enemy.hull <= 0.0:
                    world.enemies = [e for e in world.enemies if e.id != hit_enemy.id]
                dead_torpedo_ids.append(torp.id)

    world.torpedoes = [t for t in world.torpedoes if t.id not in dead_torpedo_ids]
    return events


async def handle_enemy_beam_hits(
    beam_hit_events: list,
    world: World,
    manager: object,
) -> list[tuple[str, float]]:
    """Apply enemy beam hits to player or stations. Returns combat damage events."""
    combat_damage_events: list[tuple[str, float]] = []

    for ev in beam_hit_events:
        if ev.target == "player":
            sys_damaged = apply_hit_to_player(
                world.ship, ev.damage, ev.attacker_x, ev.attacker_y
            )
            combat_damage_events.extend(sys_damaged)
            await manager.broadcast(  # type: ignore[union-attr]
                Message.build(
                    "ship.hull_hit",
                    {
                        "attacker_id": ev.attacker_id,
                        "attacker_x": ev.attacker_x,
                        "attacker_y": ev.attacker_y,
                        "damage": ev.damage,
                        "hull": world.ship.hull,
                        "shields": {
                            "front": world.ship.shields.front,
                            "rear": world.ship.shields.rear,
                        },
                    },
                )
            )
        else:
            station = next((s for s in world.stations if s.id == ev.target), None)
            if station is not None:
                station.hull = max(0.0, station.hull - ev.damage)
                await manager.broadcast(  # type: ignore[union-attr]
                    Message.build(
                        "station.hull_hit",
                        {
                            "station_id": station.id,
                            "attacker_id": ev.attacker_id,
                            "damage": ev.damage,
                            "hull": round(station.hull, 1),
                        },
                    )
                )

    return combat_damage_events
