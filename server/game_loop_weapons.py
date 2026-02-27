"""
Weapons sub-module for the game loop.

Manages all weapons state and computation: target selection, torpedo magazine,
tube cooldowns, torpedo type loading, beam/torpedo firing, torpedo movement,
and applying enemy beam hits to the player or stations.

v0.05g additions:
  - Eight torpedo types: standard, homing, ion, piercing, heavy, proximity,
    nuclear, experimental (replaces old standard/emp/probe/nuclear).
  - Per-type magazine management (dict[str, int] instead of single int).
  - Homing torpedoes track the selected target in flight (HOMING_TURN_RATE).
  - Ion torpedoes drain enemy shields and stun for 10 seconds (100 ticks).
  - Piercing torpedoes ignore 75% of shield absorption.
  - Proximity torpedoes detonate in an AOE blast radius.
  - Heavy torpedoes deal maximum damage at reduced velocity.
  - Per-type reload times (slower for heavy/nuclear, faster for standard).
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
    BEAM_PLAYER_RANGE,
    CombatHitResult,
    apply_hit_to_enemy,
    apply_hit_to_player,
    beam_in_arc,
)
from server.utils.math_helpers import angle_diff, bearing_to, distance, wrap_angle
import server.game_loop_salvage as glsalv

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TUBE_LOAD_TIME: float = 3.0        # seconds to load a different torpedo type

#: All valid torpedo type identifiers.
TORPEDO_TYPES: list[str] = [
    "standard", "homing", "ion", "piercing",
    "heavy", "proximity", "nuclear", "experimental",
]

#: Damage dealt on direct impact by each torpedo type.
TORPEDO_DAMAGE_BY_TYPE: dict[str, float] = {
    "standard":     50.0,
    "homing":       35.0,   # tracks target; offset by guidance advantage
    "ion":          10.0,   # low hull damage + drains shields + stuns 10s
    "piercing":     40.0,   # ignores 75% of shield absorption
    "heavy":       100.0,   # maximum damage; very slow
    "proximity":    30.0,   # AOE — hits all enemies within blast radius
    "nuclear":     200.0,   # devastating; Captain authorisation required
    "experimental": 60.0,   # unpredictable; secondary effects vary
}

#: Velocity (world units / second) for each torpedo type.
TORPEDO_VELOCITY_BY_TYPE: dict[str, float] = {
    "standard":   500.0,
    "homing":     500.0,
    "ion":        500.0,
    "piercing":   400.0,
    "heavy":      300.0,   # very slow — easily intercepted
    "proximity":  500.0,
    "nuclear":    400.0,   # slow for maximum drama
    "experimental": 500.0,
}

#: Base reload time (seconds) after firing — scaled by torpedoes system efficiency.
TORPEDO_RELOAD_BY_TYPE: dict[str, float] = {
    "standard":   3.0,
    "homing":     4.0,
    "ion":        5.0,
    "piercing":   4.0,
    "heavy":      8.0,
    "proximity":  4.0,
    "nuclear":   10.0,
    "experimental": 6.0,
}

#: Default loadout matching the frigate and scope document.
DEFAULT_TORPEDO_LOADOUT: dict[str, int] = {
    "standard": 8, "homing": 4, "ion": 4, "piercing": 4,
    "heavy": 2, "proximity": 4, "nuclear": 1, "experimental": 0,
}

#: Proximity torpedo blast radius (world units) — all enemies inside detonate.
PROXIMITY_BLAST_RADIUS: float = 2_000.0

#: Ion torpedo: drain shields + stun ticks (100 ticks @ 10 Hz = 10 seconds).
ION_STUN_TICKS: int = 100

#: Homing torpedo turn rate (degrees / second).
HOMING_TURN_RATE: float = 90.0

# Auto-fire targeting computer (activates when Weapons station is uncrewed).
AUTO_FIRE_INTERVAL: float = 1.0    # seconds between shots (2× manual 0.5s)
AUTO_FIRE_ACCURACY: float = 0.75   # 75% hit chance
AUTO_FIRE_DELAY: float = 3.0       # seconds after player leaves before engaging

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_weapons_target: str | None = None

# Per-type ammo counts.
_torpedo_ammo: dict[str, int] = dict(DEFAULT_TORPEDO_LOADOUT)
# Maximum ammo counts (set from ship class at game start; used for resupply).
_torpedo_ammo_max: dict[str, int] = dict(DEFAULT_TORPEDO_LOADOUT)

# Reload timers (seconds until tube can fire again after launch).
_tube_cooldowns: list[float] = [0.0, 0.0]

# Reference total reload time for each tube (set when fired; for UI progress).
_tube_reload_times: list[float] = [TORPEDO_RELOAD_BY_TYPE["standard"],
                                    TORPEDO_RELOAD_BY_TYPE["standard"]]

# Currently loaded torpedo type per tube.
_tube_types: list[str] = ["standard", "standard"]

# Loading timers (seconds remaining until a new type finishes loading).
_tube_loading: list[float] = [0.0, 0.0]

# Torpedo type being loaded (undefined when _tube_loading[idx] == 0).
_tube_type_loading: list[str] = ["standard", "standard"]

# Pending nuclear launch authorisation requests: request_id → {tube, tube_idx}.
_pending_nuclear_auths: dict[str, dict] = {}

_entity_counter: int = 0
_beam_cooldown: float = 0.0   # seconds until beams can fire again (v0.07)

# v0.05i — station IDs attacked by the player this tick (for sensor-array logic)
_stations_attacked_this_tick: set[str] = set()
# v0.05i — component-destroyed events pending broadcast by game_loop.py
_pending_component_destroyed: list[dict] = []
# v0.06 — diplomatic incidents triggered by firing on neutral contacts
_pending_diplomatic_events: list[dict] = []
# v0.06 — targeting denial payloads (friendly lock refused) pending broadcast
_pending_targeting_denials: list[dict] = []

# Auto-fire targeting computer state.
_auto_fire_active: bool = False
_auto_fire_cooldown: float = 0.0
_auto_fire_delay: float = 0.0
_weapons_crewed: bool = False
_auto_fire_status_changed: bool | None = None


def reset(initial_loadout: dict[str, int] | None = None,
          tube_count: int = 2) -> None:
    """Reset all weapons state. Call at game start.

    *tube_count* sets the number of torpedo tubes (0 = no torpedoes).
    """
    global _weapons_target, _torpedo_ammo, _torpedo_ammo_max, _entity_counter
    global _tube_types, _tube_loading, _tube_type_loading, _pending_nuclear_auths
    global _tube_cooldowns, _tube_reload_times
    global _auto_fire_active, _auto_fire_cooldown, _auto_fire_delay
    global _weapons_crewed, _auto_fire_status_changed
    global _beam_cooldown
    loadout = dict(initial_loadout) if initial_loadout else dict(DEFAULT_TORPEDO_LOADOUT)
    _torpedo_ammo = dict(loadout)
    _torpedo_ammo_max = dict(loadout)
    _weapons_target = None
    _tube_cooldowns = [0.0] * tube_count
    _tube_reload_times = [TORPEDO_RELOAD_BY_TYPE["standard"]] * tube_count
    _tube_types = ["standard"] * tube_count
    _tube_loading = [0.0] * tube_count
    _tube_type_loading = ["standard"] * tube_count
    _pending_nuclear_auths = {}
    _entity_counter = 0
    _beam_cooldown = 0.0
    _stations_attacked_this_tick.clear()
    _pending_component_destroyed.clear()
    _pending_diplomatic_events.clear()
    _pending_targeting_denials.clear()
    _auto_fire_active = False
    _auto_fire_cooldown = 0.0
    _auto_fire_delay = 0.0
    _weapons_crewed = True   # assume crewed — first set_weapons_crewed(False) starts delay
    _auto_fire_status_changed = None


def serialise() -> dict:
    return {
        "weapons_target": _weapons_target,
        "torpedo_ammo": dict(_torpedo_ammo),
        "torpedo_ammo_max": dict(_torpedo_ammo_max),
        "tube_cooldowns": list(_tube_cooldowns),
        "tube_reload_times": list(_tube_reload_times),
        "tube_types": list(_tube_types),
        "tube_loading": list(_tube_loading),
        "tube_type_loading": list(_tube_type_loading),
        "entity_counter": _entity_counter,
        "auto_fire_active": _auto_fire_active,
        "auto_fire_delay": _auto_fire_delay,
        "beam_cooldown": _beam_cooldown,
        # pending nuclear auths not serialised — requests don't survive save/resume
    }


def deserialise(data: dict) -> None:
    global _weapons_target, _torpedo_ammo, _torpedo_ammo_max, _tube_cooldowns
    global _tube_types, _tube_loading, _tube_type_loading, _entity_counter
    global _tube_reload_times
    global _auto_fire_active, _auto_fire_delay
    global _beam_cooldown
    _weapons_target = data.get("weapons_target")

    # Backward compat: old saves stored torpedo_ammo as an int.
    raw_ammo = data.get("torpedo_ammo", dict(DEFAULT_TORPEDO_LOADOUT))
    if isinstance(raw_ammo, int):
        _torpedo_ammo = dict(DEFAULT_TORPEDO_LOADOUT)
    else:
        _torpedo_ammo = dict(raw_ammo)

    raw_max = data.get("torpedo_ammo_max", dict(_torpedo_ammo))
    _torpedo_ammo_max = dict(raw_max) if isinstance(raw_max, dict) else dict(_torpedo_ammo)

    # Variable tube count: restore from saved array length (backward compat: default 2).
    saved_cooldowns = data.get("tube_cooldowns", [0.0, 0.0])
    _tube_cooldowns = list(saved_cooldowns)
    _tube_reload_times = list(data.get("tube_reload_times",
                                       [TORPEDO_RELOAD_BY_TYPE["standard"]] * len(_tube_cooldowns)))
    _tube_types        = list(data.get("tube_types", ["standard"] * len(_tube_cooldowns)))
    _tube_loading      = list(data.get("tube_loading", [0.0] * len(_tube_cooldowns)))
    _tube_type_loading = list(data.get("tube_type_loading", ["standard"] * len(_tube_cooldowns)))
    _entity_counter       = data.get("entity_counter", 0)
    _auto_fire_active     = data.get("auto_fire_active", False)
    _auto_fire_delay      = data.get("auto_fire_delay", 0.0)
    _beam_cooldown        = float(data.get("beam_cooldown", 0.0))
    _pending_nuclear_auths.clear()


# ---------------------------------------------------------------------------
# State accessors
# ---------------------------------------------------------------------------


def get_target() -> str | None:
    return _weapons_target


def set_target(entity_id: str | None) -> None:
    global _weapons_target
    _weapons_target = entity_id


def get_ammo() -> dict[str, int]:
    """Return a copy of the per-type ammo dict."""
    return dict(_torpedo_ammo)


def get_ammo_max() -> dict[str, int]:
    """Return the maximum per-type ammo (ship class loadout)."""
    return dict(_torpedo_ammo_max)


def get_ammo_for_type(torpedo_type: str) -> int:
    return _torpedo_ammo.get(torpedo_type, 0)


def set_ammo_for_type(torpedo_type: str, count: int) -> None:
    global _torpedo_ammo
    _torpedo_ammo[torpedo_type] = max(0, count)


def get_cooldowns() -> list[float]:
    return list(_tube_cooldowns)


def get_tube_reload_times() -> list[float]:
    """Return reference reload times for each tube (set when last fired)."""
    return list(_tube_reload_times)


def get_tube_types() -> list[str]:
    return list(_tube_types)


def get_tube_loading() -> list[float]:
    return list(_tube_loading)


def pop_stations_attacked() -> set[str]:
    """Return and clear the set of station IDs hit by the player this tick."""
    result = set(_stations_attacked_this_tick)
    _stations_attacked_this_tick.clear()
    return result


def pop_component_destroyed_events() -> list[dict]:
    """Return and clear pending station.component_destroyed event dicts."""
    result = list(_pending_component_destroyed)
    _pending_component_destroyed.clear()
    return result


def pop_diplomatic_events() -> list[dict]:
    """Return and clear pending weapons.diplomatic_incident event dicts."""
    result = list(_pending_diplomatic_events)
    _pending_diplomatic_events.clear()
    return result


def pop_targeting_denials() -> list[dict]:
    """Return and clear pending weapons.targeting_denied payloads."""
    result = list(_pending_targeting_denials)
    _pending_targeting_denials.clear()
    return result


# ---------------------------------------------------------------------------
# Auto-fire targeting computer
# ---------------------------------------------------------------------------


def is_auto_fire_active() -> bool:
    """Return True if the auto-fire targeting computer is currently engaged."""
    return _auto_fire_active


def set_weapons_crewed(crewed: bool) -> None:
    """Update whether a player is occupying the Weapons station.

    Called every tick by game_loop.py.
    """
    global _weapons_crewed, _auto_fire_active, _auto_fire_delay, _auto_fire_status_changed
    if crewed and not _weapons_crewed:
        # Player just arrived — immediately disable auto-fire.
        if _auto_fire_active:
            _auto_fire_active = False
            _auto_fire_status_changed = False
            gl.log_event("weapons", "auto_fire", {"active": False})
        _auto_fire_delay = 0.0
    elif not crewed and _weapons_crewed:
        # Player just left — start the activation delay.
        _auto_fire_delay = AUTO_FIRE_DELAY
    _weapons_crewed = crewed


def pop_auto_fire_status_changed() -> bool | None:
    """Return True/False when auto-fire status changed, or None if unchanged."""
    global _auto_fire_status_changed
    result = _auto_fire_status_changed
    _auto_fire_status_changed = None
    return result


def tick_auto_fire(ship: Ship, world: World, dt: float) -> list[tuple[str, dict]]:
    """Advance the auto-fire targeting computer.

    Returns a list of (event_type, payload) tuples to broadcast.
    """
    global _auto_fire_active, _auto_fire_cooldown, _auto_fire_delay, _auto_fire_status_changed

    if _weapons_crewed:
        return []

    # Activation delay countdown.
    if not _auto_fire_active:
        if _auto_fire_delay > 0.0:
            _auto_fire_delay = max(0.0, _auto_fire_delay - dt)
            if _auto_fire_delay <= 0.0:
                _auto_fire_active = True
                _auto_fire_cooldown = 0.0
                _auto_fire_status_changed = True
                gl.log_event("weapons", "auto_fire", {"active": True})
        return []

    # Active — countdown cooldown, then attempt to fire.
    _auto_fire_cooldown = max(0.0, _auto_fire_cooldown - dt)
    if _auto_fire_cooldown > 0.0:
        return []

    target = _find_auto_fire_target(ship, world)
    if target is None:
        return []

    # Accuracy roll — miss resets cooldown without damage.
    # v0.07: target profile reduces hit chance (spec 1.2.5).
    eff_accuracy = AUTO_FIRE_ACCURACY * getattr(target, "target_profile", 1.0)
    if _rng.random() > eff_accuracy:
        _auto_fire_cooldown = AUTO_FIRE_INTERVAL
        return []

    dmg = ship.beam_damage_base * ship.systems["beams"].efficiency
    apply_hit_to_enemy(target, dmg, ship.x, ship.y, beam_frequency="")

    event_payload = {
        "target_id": target.id,
        "target_x": target.x,
        "target_y": target.y,
        "damage": round(dmg, 2),
        "beam_frequency": "",
        "source": "auto",
    }
    gl.log_event("weapons", "beam_fired", {
        "target_id": target.id, "damage": round(dmg, 2), "source": "auto",
    })

    if target.hull <= 0.0:
        glsalv.spawn_wreck("enemy", target.id, target.type, target.x, target.y)
        world.enemies = [e for e in world.enemies if e.id != target.id]
        gl.log_event("combat", "enemy_destroyed", {"enemy_id": target.id, "cause": "beam_auto"})

    _auto_fire_cooldown = AUTO_FIRE_INTERVAL
    return [("weapons.beam_fired", event_payload)]


def _find_auto_fire_target(ship: Ship, world: World):
    """Return the nearest scanned hostile enemy in beam range+arc, or None."""
    if ship.beam_count <= 0:
        return None
    best = None
    best_dist = float("inf")
    arc = ship.beam_arc_deg
    for enemy in world.enemies:
        if getattr(enemy, "scan_state", None) != "scanned":
            continue
        dist = distance(ship.x, ship.y, enemy.x, enemy.y)
        if dist > BEAM_PLAYER_RANGE:
            continue
        brg = bearing_to(ship.x, ship.y, enemy.x, enemy.y)
        if not beam_in_arc(ship.heading, brg, arc):
            continue
        if dist < best_dist:
            best = enemy
            best_dist = dist
    return best


def _classify_target(world: World, entity_id: str | None) -> str:
    """Return the classification of a potential target entity.

    Returns one of: 'hostile', 'friendly', 'neutral', 'unknown'.
    """
    if entity_id is None:
        return "unknown"
    if any(e.id == entity_id for e in world.enemies):
        return "hostile"
    if any(c.id == entity_id for c in world.creatures):
        return "unknown"
    station = _find_station_by_id(world, entity_id)
    if station is not None:
        if station.faction == "hostile":
            return "hostile"
        if station.faction == "friendly":
            return "friendly"
        return "neutral"    # neutral or none (derelict)
    comp_result = _find_station_component(world, entity_id)
    if comp_result is not None:
        s, _ = comp_result
        if s.faction == "friendly":
            return "friendly"
        if s.faction == "hostile":
            return "hostile"
        return "neutral"
    return "unknown"


def try_select_target(entity_id: str | None, world: World) -> dict | None:
    """Validate and apply a target selection request.

    Returns a denial payload dict if the target is a friendly contact
    (Weapons cannot lock onto friendly contacts), or None on success
    (target has been set via set_target()).
    """
    if entity_id is None:
        set_target(None)
        return None
    cls = _classify_target(world, entity_id)
    if cls == "friendly":
        denial = {
            "denied": True,
            "entity_id": entity_id,
            "reason": "TARGETING DENIED — friendly contact",
        }
        _pending_targeting_denials.append(denial)
        return denial
    set_target(entity_id)
    return None


def tick_cooldowns(dt: float) -> None:
    global _beam_cooldown
    for i in range(len(_tube_cooldowns)):
        _tube_cooldowns[i] = max(0.0, _tube_cooldowns[i] - dt)
    _beam_cooldown = max(0.0, _beam_cooldown - dt)


def tick_tube_loading(dt: float) -> None:
    """Advance per-tube loading timers; apply type when loading completes."""
    for idx in range(len(_tube_types)):
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
    """Begin loading *torpedo_type* into a tube (1-based index).

    Returns a broadcast event tuple or None if tube is busy or invalid.
    """
    if torpedo_type not in TORPEDO_TYPES:
        return None

    tube_idx = tube - 1
    if tube_idx < 0 or tube_idx >= len(_tube_types):
        return None  # tube index out of range for this ship class
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
    if (_torpedo_ammo.get("nuclear", 0) <= 0
            or _tube_cooldowns[tube_idx] > 0.0
            or _tube_loading[tube_idx] > 0.0):
        # Tube no longer ready.
        return [result_event]

    fire_event = _do_fire(ship, world, tube_idx, "nuclear")
    if fire_event is None:
        return [result_event]
    return [result_event, fire_event]


# ---------------------------------------------------------------------------
# Firing helpers
# ---------------------------------------------------------------------------


def _find_station_component(
    world: World,
    entity_id: str,
) -> "tuple[Station, object] | None":
    """Return (station, component) for a component entity_id, or None."""
    from server.models.world import Station  # already imported indirectly, but keep explicit
    for station in world.stations:
        if station.defenses is None:
            continue
        for comp in station.defenses.all_components():
            if comp.id == entity_id:
                return station, comp
    return None


def _find_station_by_id(world: World, entity_id: str) -> "Station | None":
    """Return a Station with the matching id, or None."""
    return next((s for s in world.stations if s.id == entity_id), None)


def fire_player_beams(ship: Ship, world: World, beam_frequency: str = "") -> tuple[str, dict] | None:
    """Fire player beam weapons at the selected target. Returns broadcast event or None.

    Targets can be:
      - Enemy entity_id  → existing enemy damage logic
      - Component ID     → damage that specific station component
      - Station ID       → damage station hull (with shield-arc absorption)

    *beam_frequency* — alpha/beta/gamma/delta; frequency matching gives ±50% dmg vs enemies.
    """
    global _weapons_target, _beam_cooldown

    if _weapons_target is None:
        return None

    # v0.07: beam cooldown — cannot fire faster than ship.beam_fire_rate.
    if _beam_cooldown > 0.0:
        return None

    # v0.07: no beams if beam_count is 0 (medical ship).
    if ship.beam_count <= 0:
        return None

    dmg = ship.beam_damage_base * ship.systems["beams"].efficiency
    arc = ship.beam_arc_deg

    # ── Enemy target (existing behaviour) ─────────────────────────────────
    target = next((e for e in world.enemies if e.id == _weapons_target), None)
    if target is not None:
        dist = distance(ship.x, ship.y, target.x, target.y)
        if dist > BEAM_PLAYER_RANGE:
            return None
        brg = bearing_to(ship.x, ship.y, target.x, target.y)
        if not beam_in_arc(ship.heading, brg, arc):
            return None

        # v0.07: target profile affects hit chance (spec 1.2.5).
        hit_chance = min(1.0, getattr(target, "target_profile", 1.0))
        if hit_chance < 1.0 and _rng.random() > hit_chance:
            _beam_cooldown = ship.beam_fire_rate
            return ("weapons.beam_miss", {"target_id": target.id})

        apply_hit_to_enemy(target, dmg, ship.x, ship.y, beam_frequency=beam_frequency)
        if target.hull <= 0.0:
            glsalv.spawn_wreck("enemy", target.id, target.type, target.x, target.y)
            world.enemies = [e for e in world.enemies if e.id != target.id]
            if _weapons_target == target.id:
                _weapons_target = None
            gl.log_event("combat", "enemy_destroyed", {"enemy_id": target.id, "cause": "beam"})

        _beam_cooldown = ship.beam_fire_rate
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

    # ── Creature target ────────────────────────────────────────────────────
    creature = next((c for c in world.creatures if c.id == _weapons_target), None)
    if creature is not None:
        dist = distance(ship.x, ship.y, creature.x, creature.y)
        if dist > BEAM_PLAYER_RANGE:
            return None
        brg = bearing_to(ship.x, ship.y, creature.x, creature.y)
        if not beam_in_arc(ship.heading, brg, arc):
            return None
        creature.hull = max(0.0, creature.hull - dmg)
        if creature.hull <= 0.0:
            world.creatures = [c for c in world.creatures if c.id != creature.id]
            if _weapons_target == creature.id:
                _weapons_target = None
            gl.log_event("combat", "creature_destroyed", {
                "creature_id": creature.id, "cause": "beam",
            })
        _beam_cooldown = ship.beam_fire_rate
        return (
            "weapons.beam_fired",
            {
                "target_id": creature.id,
                "target_x": creature.x,
                "target_y": creature.y,
                "damage": round(dmg, 2),
                "beam_frequency": beam_frequency,
            },
        )

    # ── Station component target ───────────────────────────────────────────
    comp_result = _find_station_component(world, _weapons_target)
    if comp_result is not None:
        station, comp = comp_result
        dist = distance(ship.x, ship.y, station.x, station.y)
        if dist > BEAM_PLAYER_RANGE:
            return None
        brg = bearing_to(ship.x, ship.y, station.x, station.y)
        if not beam_in_arc(ship.heading, brg, arc):
            return None

        comp.hp = max(0.0, comp.hp - dmg)
        _stations_attacked_this_tick.add(station.id)
        if comp.hp <= 0.0 and comp.hp_max > 0.0:
            # First time hp hits 0 — emit destroyed event.
            _pending_component_destroyed.append({
                "station_id": station.id,
                "component_id": comp.id,
                "component_type": _component_type(comp),
            })
            comp.hp_max = 0.0  # sentinel: prevents re-emitting
            if _weapons_target == comp.id:
                _weapons_target = None

        _beam_cooldown = ship.beam_fire_rate
        return (
            "weapons.beam_fired",
            {
                "target_id": comp.id,
                "target_x": station.x,
                "target_y": station.y,
                "damage": round(dmg, 2),
                "beam_frequency": beam_frequency,
            },
        )

    # ── Station hull target (hostile / neutral / derelict — friendly rejected at select) ─
    station = _find_station_by_id(world, _weapons_target)
    if station is not None and station.faction != "friendly":
        dist = distance(ship.x, ship.y, station.x, station.y)
        if dist > BEAM_PLAYER_RANGE:
            return None
        brg = bearing_to(ship.x, ship.y, station.x, station.y)
        if not beam_in_arc(ship.heading, brg, arc):
            return None

        # Shield arc absorption: if a generator covers this bearing, 80% absorbed.
        if station.defenses is not None:
            if station.defenses.arc_is_shielded(bearing_to(station.x, station.y, ship.x, ship.y)):
                dmg *= 0.2
        station.hull = max(0.0, station.hull - dmg)
        _stations_attacked_this_tick.add(station.id)
        # Diplomatic incident when firing on a non-hostile station.
        if station.faction in ("neutral", "none"):
            station.faction = "hostile"   # target retaliates
            _pending_diplomatic_events.append({
                "station_id": station.id,
                "station_name": station.name,
            })

        _beam_cooldown = ship.beam_fire_rate
        return (
            "weapons.beam_fired",
            {
                "target_id": station.id,
                "target_x": station.x,
                "target_y": station.y,
                "damage": round(dmg, 2),
                "beam_frequency": beam_frequency,
            },
        )

    return None


def _component_type(comp: object) -> str:
    """Return a short string label for a component object."""
    from server.models.world import ShieldArc, Turret, TorpedoLauncher, FighterBay, SensorArray, StationReactor
    if isinstance(comp, ShieldArc):
        return "shield_arc"
    if isinstance(comp, Turret):
        return "turret"
    if isinstance(comp, TorpedoLauncher):
        return "launcher"
    if isinstance(comp, FighterBay):
        return "fighter_bay"
    if isinstance(comp, SensorArray):
        return "sensor_array"
    if isinstance(comp, StationReactor):
        return "reactor"
    return "unknown"


def fire_torpedo(ship: Ship, world: World, tube: int) -> list[tuple[str, dict]]:
    """Launch a torpedo from the specified tube.

    Returns a list of broadcast event tuples.
    For nuclear torpedoes, returns an authorisation request instead of a fire event.
    """
    tube_idx = tube - 1
    if tube_idx < 0 or tube_idx >= len(_tube_types):
        return []  # tube index out of range for this ship class

    if _tube_cooldowns[tube_idx] > 0.0:
        return []
    if _tube_loading[tube_idx] > 0.0:
        return []

    torpedo_type = _tube_types[tube_idx]

    if _torpedo_ammo.get(torpedo_type, 0) <= 0:
        return []

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
    if _torpedo_ammo.get(torpedo_type, 0) <= 0:
        return None

    eff = max(0.01, ship.systems["torpedoes"].efficiency)
    base_reload = TORPEDO_RELOAD_BY_TYPE.get(torpedo_type, 3.0)
    reload_time = base_reload / eff

    _torpedo_ammo[torpedo_type] -= 1
    _tube_cooldowns[tube_idx] = reload_time
    _tube_reload_times[tube_idx] = reload_time

    velocity = TORPEDO_VELOCITY_BY_TYPE.get(torpedo_type, 500.0)

    torp = Torpedo(
        id=next_entity_id("torpedo"),
        owner="player",
        x=ship.x,
        y=ship.y,
        heading=ship.heading,
        torpedo_type=torpedo_type,
        velocity=velocity,
        homing_target=_weapons_target if torpedo_type == "homing" else None,
    )
    world.torpedoes.append(torp)

    return (
        "weapons.torpedo_fired",
        {"torpedo_id": torp.id, "tube": tube_idx + 1, "torpedo_type": torpedo_type},
    )


# ---------------------------------------------------------------------------
# Per-tick helpers
# ---------------------------------------------------------------------------


def _steer_homing(torp: Torpedo, world: World, dt: float) -> None:
    """Rotate a homing torpedo toward its target."""
    if not torp.homing_target:
        return
    tgt = next((e for e in world.enemies if e.id == torp.homing_target), None)
    if tgt is None:
        return
    target_brg = math.degrees(
        math.atan2(tgt.x - torp.x, -(tgt.y - torp.y))
    ) % 360.0
    diff = angle_diff(torp.heading, target_brg)
    max_turn = HOMING_TURN_RATE * dt
    turn = max(-max_turn, min(max_turn, diff))
    torp.heading = wrap_angle(torp.heading + turn)


def tick_torpedoes(world: World, ship: Ship | None = None) -> list[dict]:
    """Move all torpedoes and check for collisions. Returns hit event dicts.

    *ship* — when provided, the point_defence system may intercept incoming
    (non-player-owned) torpedoes before they can impact.
    """
    from server.game_loop_physics import TICK_DT

    dead_torpedo_ids: list[str] = []
    events: list[dict] = []

    for torp in world.torpedoes:
        # Homing guidance — steer before moving.
        if torp.torpedo_type == "homing" and torp.homing_target:
            _steer_homing(torp, world, TICK_DT)

        h_rad = math.radians(torp.heading)
        torp.x += torp.velocity * math.sin(h_rad) * TICK_DT
        torp.y -= torp.velocity * math.cos(h_rad) * TICK_DT
        torp.distance_travelled += torp.velocity * TICK_DT

        if torp.distance_travelled >= Torpedo.MAX_RANGE:
            dead_torpedo_ids.append(torp.id)
            continue

        # Point defence: passive intercept of incoming (non-player) torpedoes.
        # Intercept chance scales with turret count (v0.07 §1.5).
        # Legacy: 0.3 at efficiency=1.0, 2 turrets → 0.15 per turret.
        if torp.owner != "player" and ship is not None:
            pd = ship.systems.get("point_defence")
            turret_count = getattr(ship, "pd_turret_count", 2)
            if pd is not None and pd.efficiency > 0.0 and turret_count > 0:
                intercept_chance = min(pd.efficiency * 0.15 * turret_count, 0.95)
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
            torp_type = torp.torpedo_type
            damage = TORPEDO_DAMAGE_BY_TYPE.get(torp_type, 50.0)

            if torp_type == "proximity":
                # Proximity: detonate when any enemy enters blast radius.
                if any(distance(torp.x, torp.y, e.x, e.y) < PROXIMITY_BLAST_RADIUS
                       for e in world.enemies):
                    hit_enemies = [
                        e for e in world.enemies
                        if distance(torp.x, torp.y, e.x, e.y) < PROXIMITY_BLAST_RADIUS
                    ]
                    destroyed_ids: list[str] = []
                    for h_enemy in hit_enemies:
                        apply_hit_to_enemy(h_enemy, damage, torp.x, torp.y)
                        if h_enemy.hull <= 0.0:
                            glsalv.spawn_wreck("enemy", h_enemy.id, h_enemy.type, h_enemy.x, h_enemy.y)
                            destroyed_ids.append(h_enemy.id)
                            gl.log_event("combat", "enemy_destroyed", {
                                "enemy_id": h_enemy.id,
                                "cause": "torpedo",
                                "torpedo_type": "proximity",
                            })
                    if destroyed_ids:
                        world.enemies = [e for e in world.enemies
                                         if e.id not in destroyed_ids]
                    events.append({
                        "torpedo_id": torp.id,
                        "target_id": ",".join(e.id for e in hit_enemies),
                        "damage": damage,
                        "torpedo_type": "proximity",
                        "hit_count": len(hit_enemies),
                    })
                    dead_torpedo_ids.append(torp.id)

            else:
                # Direct hit: 200 unit collision radius.
                hit_enemy = None
                for enemy in world.enemies:
                    if distance(torp.x, torp.y, enemy.x, enemy.y) < 200.0:
                        hit_enemy = enemy
                        break

                if hit_enemy is not None:
                    if torp_type == "piercing":
                        # Ignores 75% of shield absorption (only 25% absorbed).
                        apply_hit_to_enemy(hit_enemy, damage, torp.x, torp.y,
                                           shield_absorption_mult=0.25)
                    else:
                        apply_hit_to_enemy(hit_enemy, damage, torp.x, torp.y)

                    event: dict = {
                        "torpedo_id": torp.id,
                        "target_id": hit_enemy.id,
                        "damage": damage,
                        "torpedo_type": torp_type,
                    }

                    # Type-specific effects on enemies that survive the hit.
                    if hit_enemy.hull > 0.0:
                        if torp_type == "ion":
                            hit_enemy.shield_front = 0.0
                            hit_enemy.shield_rear = 0.0
                            hit_enemy.stun_ticks = ION_STUN_TICKS
                            event["shield_drained"] = True
                            event["stun_duration"] = ION_STUN_TICKS / 10.0

                    if hit_enemy.hull <= 0.0:
                        glsalv.spawn_wreck("enemy", hit_enemy.id, hit_enemy.type, hit_enemy.x, hit_enemy.y)
                        world.enemies = [e for e in world.enemies
                                         if e.id != hit_enemy.id]
                        gl.log_event("combat", "enemy_destroyed", {
                            "enemy_id": hit_enemy.id,
                            "cause": "torpedo",
                            "torpedo_type": torp_type,
                        })

                    events.append(event)
                    dead_torpedo_ids.append(torp.id)

                # If no enemy hit, check station hull (not friendly stations).
                if hit_enemy is None and torp.id not in dead_torpedo_ids:
                    for station in world.stations:
                        if station.faction == "friendly":
                            continue
                        if distance(torp.x, torp.y, station.x, station.y) >= 500.0:
                            continue
                        # Shield arc absorption.
                        eff_dmg = damage
                        if station.defenses is not None:
                            atk_brg = bearing_to(station.x, station.y, torp.x, torp.y)
                            if station.defenses.arc_is_shielded(atk_brg):
                                eff_dmg *= 0.2
                        station.hull = max(0.0, station.hull - eff_dmg)
                        _stations_attacked_this_tick.add(station.id)
                        # Diplomatic incident for non-hostile station hits.
                        if station.faction in ("neutral", "none"):
                            station.faction = "hostile"
                            _pending_diplomatic_events.append({
                                "station_id": station.id,
                                "station_name": station.name,
                            })
                        events.append({
                            "torpedo_id": torp.id,
                            "target_id": station.id,
                            "damage": round(eff_dmg, 2),
                            "torpedo_type": torp_type,
                        })
                        dead_torpedo_ids.append(torp.id)
                        break

    world.torpedoes = [t for t in world.torpedoes if t.id not in dead_torpedo_ids]
    return events


async def handle_enemy_beam_hits(
    beam_hit_events: list,
    world: World,
    manager: object,
) -> tuple[list[tuple[str, float]], list]:
    """Apply enemy beam hits to player or stations.

    Returns (combat_damage_events, combat_casualties) where casualties
    is a list of CombatCasualty objects from apply_hit_to_player.
    """
    combat_damage_events: list[tuple[str, float]] = []
    combat_casualties: list = []

    for ev in beam_hit_events:
        if ev.target == "player":
            hit_result = apply_hit_to_player(
                world.ship, ev.damage, ev.attacker_x, ev.attacker_y,
                shield_bypass=getattr(ev, "shield_bypass", 0.0),
            )
            combat_damage_events.extend(hit_result.damaged_systems)
            combat_casualties.extend(hit_result.casualties)
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
                            "fore":      world.ship.shields.fore,
                            "aft":       world.ship.shields.aft,
                            "port":      world.ship.shields.port,
                            "starboard": world.ship.shields.starboard,
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

    return combat_damage_events, combat_casualties
