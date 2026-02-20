"""
Weapons sub-module for the game loop.

Manages all weapons state and computation: target selection, torpedo ammo,
tube cooldowns, torpedo type loading, beam/torpedo firing, torpedo movement,
and applying enemy beam hits to the player or stations.

v0.02g additions:
  - Four torpedo types: standard, emp, probe, nuclear.
  - Per-tube loading system (TUBE_LOAD_TIME to switch torpedo type).
  - EMP torpedoes stun enemy weapon systems (stun_ticks).
  - Probe torpedoes trigger an automatic sensor scan on impact.
  - Nuclear torpedoes require Captain authorisation before firing.
"""
from __future__ import annotations

import math
import random as _rng
import uuid

import server.game_logger as gl
from server.models.messages import Message
from server.models.ship import Ship
from server.models.world import Torpedo, World
from server.systems.combat import (
    BEAM_PLAYER_ARC_DEG,
    BEAM_PLAYER_DAMAGE,
    BEAM_PLAYER_RANGE,
    apply_hit_to_enemy,
    apply_hit_to_player,
    beam_in_arc,
)
from server.utils.math_helpers import bearing_to, distance

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TORPEDO_RELOAD_TIME: float = 5.0   # seconds after firing (scaled by efficiency)
TUBE_LOAD_TIME: float = 3.0        # seconds to load a different torpedo type

#: Damage dealt on impact by each torpedo type.
TORPEDO_DAMAGE_BY_TYPE: dict[str, float] = {
    "standard": 50.0,
    "emp":      15.0,   # lower damage, but stuns weapon systems
    "probe":     5.0,   # minimal damage, auto-scans target
    "nuclear":  80.0,   # high damage, requires Captain authorisation
}

#: EMP stun duration in ticks (at 10 Hz → 5 seconds).
EMP_STUN_TICKS: int = 50

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_weapons_target: str | None = None
_torpedo_ammo: int = 10

# Reload timers (seconds until tube can fire again after launch).
_tube_cooldowns: list[float] = [0.0, 0.0]

# Currently loaded torpedo type per tube.
_tube_types: list[str] = ["standard", "standard"]

# Loading timers (seconds remaining until a new type finishes loading).
_tube_loading: list[float] = [0.0, 0.0]

# Torpedo type being loaded (undefined when _tube_loading[idx] == 0).
_tube_type_loading: list[str] = ["standard", "standard"]

# Pending nuclear launch authorisation requests: request_id → {tube, tube_idx}.
_pending_nuclear_auths: dict[str, dict] = {}

_entity_counter: int = 0


def reset(initial_ammo: int = 10) -> None:
    """Reset all weapons state. Call at game start."""
    global _weapons_target, _torpedo_ammo, _tube_cooldowns, _entity_counter
    global _tube_types, _tube_loading, _tube_type_loading, _pending_nuclear_auths
    _weapons_target = None
    _torpedo_ammo = initial_ammo
    _tube_cooldowns = [0.0, 0.0]
    _tube_types = ["standard", "standard"]
    _tube_loading = [0.0, 0.0]
    _tube_type_loading = ["standard", "standard"]
    _pending_nuclear_auths = {}
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


def get_tube_types() -> list[str]:
    return list(_tube_types)


def get_tube_loading() -> list[float]:
    return list(_tube_loading)


def tick_cooldowns(dt: float) -> None:
    _tube_cooldowns[0] = max(0.0, _tube_cooldowns[0] - dt)
    _tube_cooldowns[1] = max(0.0, _tube_cooldowns[1] - dt)


def tick_tube_loading(dt: float) -> None:
    """Advance per-tube loading timers; apply type when loading completes."""
    for idx in range(2):
        if _tube_loading[idx] > 0.0:
            _tube_loading[idx] = max(0.0, _tube_loading[idx] - dt)
            if _tube_loading[idx] == 0.0:
                _tube_types[idx] = _tube_type_loading[idx]


def next_entity_id(prefix: str) -> str:
    global _entity_counter
    _entity_counter += 1
    return f"{prefix}_{_entity_counter}"


# ---------------------------------------------------------------------------
# Tube loading
# ---------------------------------------------------------------------------


def load_tube(tube: int, torpedo_type: str) -> tuple[str, dict] | None:
    """Begin loading *torpedo_type* into *tube* (1 or 2).

    Returns a broadcast event tuple or None if tube is busy.
    """
    tube_idx = tube - 1
    if _tube_loading[tube_idx] > 0.0:
        return None   # already loading
    if _tube_cooldowns[tube_idx] > 0.0:
        return None   # tube is reloading after firing

    if _tube_types[tube_idx] == torpedo_type:
        # Already loaded — no action needed.
        return ("weapons.tube_loaded", {"tube": tube, "torpedo_type": torpedo_type})

    _tube_loading[tube_idx] = TUBE_LOAD_TIME
    _tube_type_loading[tube_idx] = torpedo_type
    return ("weapons.tube_loading", {"tube": tube, "torpedo_type": torpedo_type, "load_time": TUBE_LOAD_TIME})


# ---------------------------------------------------------------------------
# Nuclear authorisation
# ---------------------------------------------------------------------------


def request_nuclear_auth(tube: int) -> tuple[str, dict]:
    """Create a pending nuclear authorisation request and return the broadcast event."""
    request_id = str(uuid.uuid4())[:8]
    _pending_nuclear_auths[request_id] = {"tube": tube, "tube_idx": tube - 1}
    return (
        "captain.authorization_request",
        {"request_id": request_id, "action": "nuclear_torpedo", "tube": tube},
    )


def resolve_nuclear_auth(
    request_id: str,
    approved: bool,
    ship: Ship,
    world: World,
) -> list[tuple[str, dict]]:
    """Resolve a pending nuclear authorisation request.

    Returns a list of broadcast event tuples (may be empty).
    """
    auth = _pending_nuclear_auths.pop(request_id, None)
    if auth is None:
        return []

    tube = auth["tube"]
    tube_idx = auth["tube_idx"]

    result_event = (
        "weapons.authorization_result",
        {"request_id": request_id, "approved": approved, "tube": tube},
    )

    if not approved:
        return [result_event]

    # Captain approved — attempt to fire.
    if _torpedo_ammo <= 0 or _tube_cooldowns[tube_idx] > 0.0 or _tube_loading[tube_idx] > 0.0:
        # Tube no longer ready.
        return [result_event]

    fire_event = _do_fire(ship, world, tube_idx, "nuclear")
    if fire_event is None:
        return [result_event]
    return [result_event, fire_event]


# ---------------------------------------------------------------------------
# Firing helpers
# ---------------------------------------------------------------------------


def fire_player_beams(ship: Ship, world: World, beam_frequency: str = "") -> tuple[str, dict] | None:
    """Fire player beam weapons at the selected target. Returns broadcast event or None.

    *beam_frequency* — the Weapons station's selected frequency (alpha/beta/gamma/delta).
    Matched frequencies deal 1.5× damage; mismatched deal 0.5×.
    """
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
    apply_hit_to_enemy(target, dmg, ship.x, ship.y, beam_frequency=beam_frequency)

    if target.hull <= 0.0:
        world.enemies = [e for e in world.enemies if e.id != target.id]
        if _weapons_target == target.id:
            _weapons_target = None
        gl.log_event("combat", "enemy_destroyed", {"enemy_id": target.id, "cause": "beam"})

    return (
        "weapons.beam_fired",
        {
            "target_id": target.id,
            "target_x": target.x,
            "target_y": target.y,
            "damage": round(dmg, 2),
            "beam_frequency": beam_frequency,
        },
    )


def fire_torpedo(ship: Ship, world: World, tube: int) -> list[tuple[str, dict]]:
    """Launch a torpedo from the specified tube.

    Returns a list of broadcast event tuples.
    For nuclear torpedoes, returns an authorisation request instead of a fire event.
    """
    tube_idx = tube - 1

    if _torpedo_ammo <= 0:
        return []
    if _tube_cooldowns[tube_idx] > 0.0:
        return []
    if _tube_loading[tube_idx] > 0.0:
        return []

    torpedo_type = _tube_types[tube_idx]

    if torpedo_type == "nuclear":
        # Nuclear requires Captain authorisation — do not fire yet.
        return [request_nuclear_auth(tube)]

    event = _do_fire(ship, world, tube_idx, torpedo_type)
    return [event] if event else []


def _do_fire(
    ship: Ship,
    world: World,
    tube_idx: int,
    torpedo_type: str,
) -> tuple[str, dict] | None:
    """Internal: deduct ammo, set cooldown, spawn torpedo. Returns event or None."""
    global _torpedo_ammo
    reload_time = TORPEDO_RELOAD_TIME / max(0.01, ship.systems["torpedoes"].efficiency)

    if _torpedo_ammo <= 0:
        return None

    _torpedo_ammo -= 1
    _tube_cooldowns[tube_idx] = reload_time

    torp = Torpedo(
        id=next_entity_id("torpedo"),
        owner="player",
        x=ship.x,
        y=ship.y,
        heading=ship.heading,
        torpedo_type=torpedo_type,
    )
    world.torpedoes.append(torp)

    return (
        "weapons.torpedo_fired",
        {"torpedo_id": torp.id, "tube": tube_idx + 1, "torpedo_type": torpedo_type},
    )


# ---------------------------------------------------------------------------
# Per-tick helpers
# ---------------------------------------------------------------------------


def tick_torpedoes(world: World, ship: Ship | None = None) -> list[dict]:
    """Move all torpedoes and check for collisions. Returns hit event dicts.

    *ship* — when provided, the point_defence system may intercept incoming
    (non-player-owned) torpedoes before they can impact.
    """
    from server.game_loop_physics import TICK_DT
    from server.systems.sensors import build_scan_result

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

        # Point defence: passive intercept of incoming (non-player) torpedoes.
        if torp.owner != "player" and ship is not None:
            pd = ship.systems.get("point_defence")
            if pd is not None and pd.efficiency > 0.0:
                intercept_chance = pd.efficiency * 0.3  # 30% at full efficiency
                if _rng.random() < intercept_chance:
                    dead_torpedo_ids.append(torp.id)
                    events.append({
                        "type": "pd_intercept",
                        "torpedo_id": torp.id,
                        "x": round(torp.x, 1),
                        "y": round(torp.y, 1),
                    })
                    continue

        if torp.owner == "player":
            hit_enemy = None
            for enemy in world.enemies:
                if distance(torp.x, torp.y, enemy.x, enemy.y) < 200.0:
                    hit_enemy = enemy
                    break

            if hit_enemy is not None:
                torp_type = torp.torpedo_type
                damage = TORPEDO_DAMAGE_BY_TYPE.get(torp_type, 50.0)
                apply_hit_to_enemy(hit_enemy, damage, torp.x, torp.y)

                event: dict = {
                    "torpedo_id": torp.id,
                    "target_id": hit_enemy.id,
                    "damage": damage,
                    "torpedo_type": torp_type,
                }

                # Type-specific effects on alive enemies.
                if hit_enemy.hull > 0.0:
                    if torp_type == "emp":
                        hit_enemy.stun_ticks = EMP_STUN_TICKS
                        event["stun_duration"] = EMP_STUN_TICKS / 10.0  # seconds
                    elif torp_type == "probe":
                        # Auto-scan: include scan data in the event.
                        event["probe_scan"] = build_scan_result(hit_enemy)

                if hit_enemy.hull <= 0.0:
                    world.enemies = [e for e in world.enemies if e.id != hit_enemy.id]
                    gl.log_event("combat", "enemy_destroyed", {"enemy_id": hit_enemy.id, "cause": "torpedo", "torpedo_type": torp_type})

                events.append(event)
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
            gl.log_event("combat", "ship_hit", {
                "attacker_id": ev.attacker_id,
                "damage": round(ev.damage, 2),
                "hull": round(world.ship.hull, 2),
            })
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
