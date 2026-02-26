"""
Spinal Mount Weapon — Battleship-only (v0.07 §2.5.1).

A devastating forward-firing weapon requiring whole-crew coordination:
  Weapons requests charge → Captain authorizes → 30 s charge (40 % reactor
  drain) → Weapons fires → 120 s cooldown.

State machine: idle → auth_pending → charging → ready → cooldown → idle.

Module-level state pattern: call reset() before use.
"""
from __future__ import annotations

import uuid
from typing import Any

from server.utils.math_helpers import bearing_to, angle_diff

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SPINAL_DAMAGE: float = 150.0
SPINAL_ARC: float = 5.0               # degrees — forward only
SPINAL_CHARGE_TIME: float = 30.0      # seconds
SPINAL_COOLDOWN: float = 120.0        # seconds after firing
SPINAL_POWER_FRACTION: float = 0.4    # fraction of reactor_max drawn during charge

SPINAL_ACCURACY_STATIONARY: float = 0.95
SPINAL_ACCURACY_MOVING: float = 0.70
SPINAL_ACCURACY_FAST_SMALL: float = 0.40
SPINAL_SCIENCE_PENALTY: float = 0.20  # accuracy drop when science offline

FAST_SPEED_THRESHOLD: float = 150.0   # enemy speed threshold for "fast-moving"
SMALL_PROFILE_THRESHOLD: float = 0.6  # target_profile threshold for "small"

STATES = frozenset({"idle", "auth_pending", "charging", "ready", "cooldown"})

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_spinal_active: bool = False
_state: str = "idle"
_charge_timer: float = 0.0
_cooldown_timer: float = 0.0
_target_id: str | None = None
_auth_request_id: str | None = None
_auth_counter: int = 0
_power_draw: float = 0.0   # reactor_max × SPINAL_POWER_FRACTION


# ---------------------------------------------------------------------------
# Public API — lifecycle
# ---------------------------------------------------------------------------


def reset(active: bool = False, reactor_max: float = 0.0) -> None:
    """Initialise (or clear) spinal mount state."""
    global _spinal_active, _state, _charge_timer, _cooldown_timer
    global _target_id, _auth_request_id, _auth_counter, _power_draw
    _spinal_active = active
    _state = "idle"
    _charge_timer = 0.0
    _cooldown_timer = 0.0
    _target_id = None
    _auth_request_id = None
    _auth_counter = 0
    _power_draw = reactor_max * SPINAL_POWER_FRACTION


def is_active() -> bool:
    return _spinal_active


def get_state() -> str:
    return _state


def get_charge_progress() -> float:
    """0–100 %."""
    if _state != "charging" or SPINAL_CHARGE_TIME <= 0:
        return 0.0
    return min(100.0, (_charge_timer / SPINAL_CHARGE_TIME) * 100.0)


def get_cooldown_remaining() -> float:
    return _cooldown_timer


def get_power_draw() -> float:
    """Current power draw (non-zero only while charging or ready)."""
    if _state in ("charging", "ready"):
        return _power_draw
    return 0.0


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------


def get_alignment(ship: Any, world: Any) -> dict:
    """Compute alignment between ship heading and the locked target.

    Returns {aligned: bool, angle_off: float, status: 'green'|'amber'|'red'}.
    """
    if _target_id is None:
        return {"aligned": False, "angle_off": 180.0, "status": "red"}

    enemy = _find_enemy(world, _target_id)
    if enemy is None:
        return {"aligned": False, "angle_off": 180.0, "status": "red"}

    brg = bearing_to(ship.x, ship.y, enemy.x, enemy.y)
    off = abs(angle_diff(ship.heading, brg))

    if off <= SPINAL_ARC:
        return {"aligned": True, "angle_off": round(off, 2), "status": "green"}
    elif off <= 15.0:
        return {"aligned": False, "angle_off": round(off, 2), "status": "amber"}
    else:
        return {"aligned": False, "angle_off": round(off, 2), "status": "red"}


# ---------------------------------------------------------------------------
# Request charge → auth_pending
# ---------------------------------------------------------------------------


def request_charge(target_id: str, ship: Any, world: Any) -> dict:
    """Weapons officer requests a spinal mount charge on *target_id*.

    Returns dict with 'ok' key. On success, includes 'request_id' for the
    Captain authorisation broadcast.
    """
    global _state, _target_id, _auth_request_id, _auth_counter

    if not _spinal_active:
        return {"ok": False, "error": "Spinal mount not available on this ship class."}
    if _state != "idle":
        return {"ok": False, "error": f"Cannot charge: state is '{_state}'."}

    enemy = _find_enemy(world, target_id)
    if enemy is None:
        return {"ok": False, "error": f"Target '{target_id}' not found."}

    _auth_counter += 1
    _auth_request_id = f"spinal-{uuid.uuid4().hex[:8]}"
    _target_id = target_id
    _state = "auth_pending"

    return {
        "ok": True,
        "request_id": _auth_request_id,
        "target_id": target_id,
    }


# ---------------------------------------------------------------------------
# Captain authorisation resolve
# ---------------------------------------------------------------------------


def resolve_auth(request_id: str, approved: bool) -> dict:
    """Captain approves or denies the spinal mount charge.

    Returns dict with 'ok' key.
    """
    global _state, _charge_timer, _auth_request_id, _target_id

    if _state != "auth_pending":
        return {"ok": False, "error": "No pending authorisation."}
    if request_id != _auth_request_id:
        return {"ok": False, "error": "Request ID mismatch."}

    if approved:
        _state = "charging"
        _charge_timer = 0.0
        _auth_request_id = None
        return {"ok": True, "state": "charging"}
    else:
        _state = "idle"
        _auth_request_id = None
        _target_id = None
        return {"ok": True, "state": "idle"}


# ---------------------------------------------------------------------------
# Fire
# ---------------------------------------------------------------------------


def fire(ship: Any, world: Any, rng: Any) -> dict:
    """Fire the spinal mount. Must be in 'ready' state.

    Returns dict with 'ok', 'hit', 'damage', 'accuracy' keys.
    """
    global _state, _cooldown_timer, _target_id

    if not _spinal_active:
        return {"ok": False, "error": "Spinal mount not available."}
    if _state != "ready":
        return {"ok": False, "error": f"Cannot fire: state is '{_state}'."}

    enemy = _find_enemy(world, _target_id)
    if enemy is None:
        # Target destroyed/gone — still go to cooldown.
        _state = "cooldown"
        _cooldown_timer = SPINAL_COOLDOWN
        _target_id = None
        return {"ok": True, "hit": False, "damage": 0.0, "accuracy": 0.0,
                "reason": "Target lost."}

    # --- Accuracy calculation ---
    accuracy = _compute_accuracy(ship, world, enemy)

    # --- Roll ---
    hit = rng.random() < accuracy

    if hit:
        from server.systems.combat import apply_hit_to_enemy
        apply_hit_to_enemy(enemy, SPINAL_DAMAGE, ship.x, ship.y)

    _state = "cooldown"
    _cooldown_timer = SPINAL_COOLDOWN
    old_target = _target_id
    _target_id = None

    return {
        "ok": True,
        "hit": hit,
        "damage": SPINAL_DAMAGE if hit else 0.0,
        "accuracy": round(accuracy, 3),
        "target_id": old_target,
    }


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


def cancel() -> dict:
    """Cancel a charge/auth at any point. Returns to idle."""
    global _state, _charge_timer, _auth_request_id, _target_id

    prev = _state
    if _state in ("auth_pending", "charging", "ready"):
        _state = "idle"
        _charge_timer = 0.0
        _auth_request_id = None
        _target_id = None
        return {"ok": True, "previous_state": prev}
    return {"ok": False, "error": f"Nothing to cancel (state='{_state}')."}


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


def tick(ship: Any, world: Any, dt: float) -> list[dict]:
    """Advance timers. Returns list of event dicts.

    Possible events:
      - {event: 'charge_complete'}
      - {event: 'charge_interrupted', reason: ...}
      - {event: 'cooldown_complete'}
    """
    global _state, _charge_timer, _cooldown_timer, _target_id, _auth_request_id

    events: list[dict] = []

    if _state == "charging":
        # Check reactor critical → interrupt.
        reactor_dead = False
        import server.game_loop_engineering as gle
        pg = gle.get_power_grid()
        if pg is not None and pg.reactor_health <= 0.0:
            reactor_dead = True

        if reactor_dead:
            _state = "idle"
            _charge_timer = 0.0
            _target_id = None
            _auth_request_id = None
            events.append({"event": "charge_interrupted", "reason": "Reactor critical failure."})
            return events

        _charge_timer += dt
        if _charge_timer >= SPINAL_CHARGE_TIME:
            _state = "ready"
            _charge_timer = SPINAL_CHARGE_TIME
            events.append({"event": "charge_complete"})

    elif _state == "cooldown":
        _cooldown_timer -= dt
        if _cooldown_timer <= 0.0:
            _cooldown_timer = 0.0
            _state = "idle"
            events.append({"event": "cooldown_complete"})

    return events


# ---------------------------------------------------------------------------
# Build state for broadcast
# ---------------------------------------------------------------------------


def build_state(ship: Any, world: Any) -> dict:
    """Full spinal mount state for broadcast."""
    if not _spinal_active:
        return {"active": False}

    alignment = get_alignment(ship, world)
    return {
        "active": True,
        "state": _state,
        "target_id": _target_id,
        "charge_progress": round(get_charge_progress(), 1),
        "cooldown_remaining": round(_cooldown_timer, 1),
        "power_draw": round(get_power_draw(), 1),
        "alignment": alignment,
    }


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def serialise() -> dict:
    return {
        "active": _spinal_active,
        "state": _state,
        "charge_timer": round(_charge_timer, 3),
        "cooldown_timer": round(_cooldown_timer, 3),
        "target_id": _target_id,
        "auth_request_id": _auth_request_id,
        "auth_counter": _auth_counter,
        "power_draw": _power_draw,
    }


def deserialise(data: dict) -> None:
    global _spinal_active, _state, _charge_timer, _cooldown_timer
    global _target_id, _auth_request_id, _auth_counter, _power_draw

    _spinal_active = data.get("active", False)
    _state = data.get("state", "idle")
    _charge_timer = data.get("charge_timer", 0.0)
    _cooldown_timer = data.get("cooldown_timer", 0.0)
    _target_id = data.get("target_id")
    _auth_request_id = data.get("auth_request_id")
    _auth_counter = data.get("auth_counter", 0)
    _power_draw = data.get("power_draw", 0.0)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_enemy(world: Any, target_id: str | None) -> Any:
    """Look up an enemy by ID. Returns the enemy object or None."""
    if target_id is None or world is None:
        return None
    for e in world.enemies:
        if e.id == target_id:
            return e
    return None


def _compute_accuracy(ship: Any, world: Any, enemy: Any) -> float:
    """Compute hit probability based on target speed, profile, science, alignment."""
    # 1. Base accuracy from target speed + profile.
    vel = getattr(enemy, "velocity", 0.0)
    profile = getattr(enemy, "target_profile", 1.0)

    if vel <= 0.0:
        accuracy = SPINAL_ACCURACY_STATIONARY
    elif vel >= FAST_SPEED_THRESHOLD and profile <= SMALL_PROFILE_THRESHOLD:
        accuracy = SPINAL_ACCURACY_FAST_SMALL
    else:
        accuracy = SPINAL_ACCURACY_MOVING

    # 2. Science offline penalty (sensors system).
    if hasattr(ship, "systems") and "sensors" in ship.systems:
        sci = ship.systems["sensors"]
        if sci.health <= 0.0 or sci._captain_offline:
            accuracy -= SPINAL_SCIENCE_PENALTY

    # 3. Alignment penalty.
    alignment = get_alignment(ship, world)
    if not alignment["aligned"]:
        accuracy *= 0.5

    return max(0.0, min(1.0, accuracy))
