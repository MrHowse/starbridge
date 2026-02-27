"""
Salvage Game Loop — v0.07 Phase 6.5.

Module-level state machine for wreck management, assessment scanning, and
salvage extraction.  Wrecks spawn when enemies die; the player assesses them
(scan), selects items, and extracts salvage with risk mechanics (booby traps,
unstable reactors).

Public API:
  reset(), serialise(), deserialise()
  spawn_wreck(), remove_wreck(), get_wrecks(), get_wreck()
  assess_salvage(), cancel_assessment()
  select_items(), begin_salvage(), cancel_salvage()
  tick(), pop_pending_events()
  is_salvaging(), get_active_wreck_id()
"""
from __future__ import annotations

import math
import random

from server.models.salvage import (
    BOOBY_TRAP_CHANCE,
    DIRECT_USE_EFFICIENCY,
    REACTOR_BLAST_RANGE,
    REACTOR_DAMAGE_MAX,
    REACTOR_DAMAGE_MIN,
    REACTOR_TIMER,
    SALVAGE_MAX_SPEED,
    SALVAGE_RANGE,
    SCAN_DURATION,
    TRAP_TEAM_DAMAGE,
    UNSTABLE_REACTOR_CHANCE,
    WRECK_DESPAWN_TIME,
    SalvageItem,
    Wreck,
    generate_salvage_manifest,
)
from server.models.ship import Ship

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_wrecks: list[Wreck] = []
_wreck_counter: int = 0
_pending_events: list[dict] = []
_active_salvage_wreck_id: str | None = None
_rng: random.Random = random.Random()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def reset() -> None:
    """Clear all salvage state for a new game."""
    global _wreck_counter, _active_salvage_wreck_id
    _wrecks.clear()
    _wreck_counter = 0
    _pending_events.clear()
    _active_salvage_wreck_id = None


def serialise() -> dict:
    """Serialise salvage state for save system."""
    return {
        "wrecks": [w.to_dict() for w in _wrecks],
        "wreck_counter": _wreck_counter,
        "active_salvage_wreck_id": _active_salvage_wreck_id,
    }


def deserialise(data: dict) -> None:
    """Restore salvage state from save data."""
    global _wreck_counter, _active_salvage_wreck_id
    _wrecks.clear()
    _pending_events.clear()
    for wd in data.get("wrecks", []):
        _wrecks.append(Wreck.from_dict(wd))
    _wreck_counter = data.get("wreck_counter", 0)
    _active_salvage_wreck_id = data.get("active_salvage_wreck_id")


def pop_pending_events() -> list[dict]:
    """Return and clear pending events for broadcast."""
    events = list(_pending_events)
    _pending_events.clear()
    return events


# ---------------------------------------------------------------------------
# Wreck management
# ---------------------------------------------------------------------------


def spawn_wreck(
    source_type: str,
    source_id: str,
    enemy_type: str,
    x: float,
    y: float,
    tick: int = 0,
) -> Wreck:
    """Create a new wreck at the given position.

    Rolls booby_trapped (10%) and unstable_reactor (15%) at creation time.
    """
    global _wreck_counter
    _wreck_counter += 1
    wreck = Wreck(
        id=f"wreck_{_wreck_counter}",
        x=x,
        y=y,
        source_type=source_type,
        source_id=source_id,
        enemy_type=enemy_type,
        booby_trapped=_rng.random() < BOOBY_TRAP_CHANCE,
        unstable_reactor=_rng.random() < UNSTABLE_REACTOR_CHANCE,
        despawn_timer=WRECK_DESPAWN_TIME,
        created_tick=tick,
    )
    _wrecks.append(wreck)
    _pending_events.append({
        "type": "wreck_spawned",
        "wreck_id": wreck.id,
        "x": round(wreck.x, 1),
        "y": round(wreck.y, 1),
        "enemy_type": wreck.enemy_type,
        "source_type": wreck.source_type,
    })
    return wreck


def remove_wreck(wreck_id: str) -> bool:
    """Remove a wreck by ID. Returns True if found and removed."""
    global _active_salvage_wreck_id
    for i, w in enumerate(_wrecks):
        if w.id == wreck_id:
            _wrecks.pop(i)
            if _active_salvage_wreck_id == wreck_id:
                _active_salvage_wreck_id = None
            return True
    return False


def get_wrecks() -> list[Wreck]:
    """Return all active wrecks."""
    return list(_wrecks)


def get_wreck(wreck_id: str) -> Wreck | None:
    """Return a single wreck by ID, or None."""
    for w in _wrecks:
        if w.id == wreck_id:
            return w
    return None


# ---------------------------------------------------------------------------
# Assessment (scanning)
# ---------------------------------------------------------------------------


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    dx = x1 - x2
    dy = y1 - y2
    return math.sqrt(dx * dx + dy * dy)


def assess_salvage(wreck_id: str, ship: Ship) -> dict:
    """Begin scanning a wreck to reveal its salvage manifest.

    Validates: range <= 2000, speed < 10, wreck is unscanned, no other active op.
    """
    wreck = get_wreck(wreck_id)
    if wreck is None:
        return {"ok": False, "error": "wreck_not_found"}

    dist = _distance(ship.x, ship.y, wreck.x, wreck.y)
    if dist > SALVAGE_RANGE:
        return {"ok": False, "error": "out_of_range"}

    if ship.velocity > SALVAGE_MAX_SPEED:
        return {"ok": False, "error": "too_fast"}

    if wreck.scan_state != "unscanned":
        return {"ok": False, "error": "already_scanned"}

    if _active_salvage_wreck_id is not None:
        return {"ok": False, "error": "salvage_op_active"}

    wreck.scan_state = "scanning"
    wreck.scan_progress = 0.0

    _pending_events.append({
        "type": "assessment_started",
        "wreck_id": wreck.id,
    })
    return {"ok": True}


def cancel_assessment(wreck_id: str) -> dict:
    """Cancel an in-progress scan."""
    wreck = get_wreck(wreck_id)
    if wreck is None:
        return {"ok": False, "error": "wreck_not_found"}

    if wreck.scan_state != "scanning":
        return {"ok": False, "error": "not_scanning"}

    wreck.scan_state = "unscanned"
    wreck.scan_progress = 0.0

    _pending_events.append({
        "type": "assessment_cancelled",
        "wreck_id": wreck.id,
    })
    return {"ok": True}


# ---------------------------------------------------------------------------
# Salvage execution
# ---------------------------------------------------------------------------


def select_items(wreck_id: str, item_ids: list[str]) -> dict:
    """Select items from a scanned wreck for extraction."""
    wreck = get_wreck(wreck_id)
    if wreck is None:
        return {"ok": False, "error": "wreck_not_found"}

    if wreck.scan_state != "scanned":
        return {"ok": False, "error": "not_scanned"}

    manifest_ids = {item.id for item in wreck.salvage_manifest}
    for item_id in item_ids:
        if item_id not in manifest_ids:
            return {"ok": False, "error": "item_not_found"}

    wreck.salvage_queue = list(item_ids)
    return {"ok": True}


def begin_salvage(wreck_id: str, ship: Ship) -> dict:
    """Begin extracting selected items from a wreck.

    Re-validates range/speed.  Booby trap check on begin.
    Arms reactor if unstable & undetected.
    """
    global _active_salvage_wreck_id
    wreck = get_wreck(wreck_id)
    if wreck is None:
        return {"ok": False, "error": "wreck_not_found"}

    if wreck.scan_state != "scanned":
        return {"ok": False, "error": "not_scanned"}

    if not wreck.salvage_queue:
        return {"ok": False, "error": "no_items_selected"}

    dist = _distance(ship.x, ship.y, wreck.x, wreck.y)
    if dist > SALVAGE_RANGE:
        return {"ok": False, "error": "out_of_range"}

    if ship.velocity > SALVAGE_MAX_SPEED:
        return {"ok": False, "error": "too_fast"}

    if _active_salvage_wreck_id is not None and _active_salvage_wreck_id != wreck_id:
        return {"ok": False, "error": "salvage_op_active"}

    # Booby trap check: if trapped & undetected, trigger on begin.
    if wreck.booby_trapped and not wreck.trap_detected:
        ship.hull = max(0.0, ship.hull - TRAP_TEAM_DAMAGE)
        _pending_events.append({
            "type": "trap_triggered",
            "wreck_id": wreck.id,
            "damage": TRAP_TEAM_DAMAGE,
            "hull_remaining": round(ship.hull, 1),
        })

    # Arm reactor if unstable & undetected.
    if wreck.unstable_reactor and not wreck.reactor_detected:
        wreck.reactor_armed = True
        wreck.reactor_timer = REACTOR_TIMER

    wreck.salvage_state = "salvaging"
    _active_salvage_wreck_id = wreck.id

    # Start first item.
    _start_next_item(wreck)

    _pending_events.append({
        "type": "salvage_started",
        "wreck_id": wreck.id,
        "item_count": len(wreck.salvage_queue),
    })
    return {"ok": True}


def cancel_salvage(wreck_id: str) -> dict:
    """Cancel an in-progress salvage operation.  Keeps already-salvaged items."""
    global _active_salvage_wreck_id
    wreck = get_wreck(wreck_id)
    if wreck is None:
        return {"ok": False, "error": "wreck_not_found"}

    if wreck.salvage_state != "salvaging":
        return {"ok": False, "error": "not_salvaging"}

    wreck.salvage_state = "aborted"
    wreck.current_item_id = None
    wreck.salvage_timer = 0.0
    wreck.salvage_queue.clear()
    if _active_salvage_wreck_id == wreck.id:
        _active_salvage_wreck_id = None

    _pending_events.append({
        "type": "salvage_cancelled",
        "wreck_id": wreck.id,
    })
    return {"ok": True}


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def is_salvaging() -> bool:
    """True if a salvage operation is in progress."""
    return _active_salvage_wreck_id is not None


def get_active_wreck_id() -> str | None:
    """Return the ID of the wreck currently being salvaged, or None."""
    return _active_salvage_wreck_id


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


def tick(ship: Ship, dt: float) -> list[dict]:
    """Advance salvage state by *dt* seconds.

    - Despawn timers (remove expired wrecks)
    - Scan progress (advance scanning wrecks -> generate manifest at 100%)
    - Range/speed validation (cancel if ship moves away)
    - Salvage item timer (complete item -> apply to ship -> next item or done)
    - Reactor countdown (if armed, decrement -> detonate at 0)

    Returns list of events (also appended to pending).
    """
    tick_events: list[dict] = []

    # 1. Despawn timers.
    expired: list[str] = []
    for wreck in _wrecks:
        wreck.despawn_timer -= dt
        if wreck.despawn_timer <= 0.0:
            expired.append(wreck.id)

    for wid in expired:
        _cancel_active_if_needed(wid)
        remove_wreck(wid)
        evt = {"type": "wreck_despawned", "wreck_id": wid}
        _pending_events.append(evt)
        tick_events.append(evt)

    # 2. Scan progress.
    for wreck in _wrecks:
        if wreck.scan_state == "scanning":
            # Range/speed check during scanning.
            dist = _distance(ship.x, ship.y, wreck.x, wreck.y)
            if dist > SALVAGE_RANGE or ship.velocity > SALVAGE_MAX_SPEED:
                wreck.scan_state = "unscanned"
                wreck.scan_progress = 0.0
                evt = {"type": "assessment_cancelled", "wreck_id": wreck.id, "reason": "moved_away"}
                _pending_events.append(evt)
                tick_events.append(evt)
                continue

            wreck.scan_progress += dt / SCAN_DURATION
            if wreck.scan_progress >= 1.0:
                wreck.scan_progress = 1.0
                wreck.scan_state = "scanned"
                # Generate manifest.
                wreck.salvage_manifest = generate_salvage_manifest(wreck.enemy_type, _rng)
                # Full scan reveals all risks.
                wreck.trap_detected = wreck.booby_trapped
                wreck.reactor_detected = wreck.unstable_reactor
                evt = {
                    "type": "assessment_complete",
                    "wreck_id": wreck.id,
                    "manifest": [item.to_dict() for item in wreck.salvage_manifest],
                    "booby_trapped": wreck.trap_detected,
                    "unstable_reactor": wreck.reactor_detected,
                }
                _pending_events.append(evt)
                tick_events.append(evt)

    # 3. Active salvage tick.
    if _active_salvage_wreck_id is not None:
        wreck = get_wreck(_active_salvage_wreck_id)
        if wreck is not None and wreck.salvage_state == "salvaging":
            # Range/speed check.
            dist = _distance(ship.x, ship.y, wreck.x, wreck.y)
            if dist > SALVAGE_RANGE or ship.velocity > SALVAGE_MAX_SPEED:
                evts = _force_cancel_salvage(wreck, reason="moved_away")
                tick_events.extend(evts)
            else:
                # Advance item timer; cascade completions within a single tick.
                remaining_dt = dt
                while wreck.current_item_id is not None and remaining_dt > 0:
                    if wreck.salvage_timer <= remaining_dt:
                        remaining_dt -= wreck.salvage_timer
                        wreck.salvage_timer = 0.0
                        evts = _complete_current_item(wreck, ship)
                        tick_events.extend(evts)
                    else:
                        wreck.salvage_timer -= remaining_dt
                        remaining_dt = 0

    # 4. Reactor countdowns.
    for wreck in list(_wrecks):
        if wreck.reactor_armed:
            wreck.reactor_timer -= dt
            if wreck.reactor_timer <= 0.0:
                evts = _detonate_reactor(wreck, ship)
                tick_events.extend(evts)

    return tick_events


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _start_next_item(wreck: Wreck) -> None:
    """Pop next item from salvage_queue and start its timer."""
    if not wreck.salvage_queue:
        wreck.current_item_id = None
        wreck.salvage_timer = 0.0
        return

    item_id = wreck.salvage_queue[0]
    item = _find_item(wreck, item_id)
    if item is None:
        # Skip invalid item.
        wreck.salvage_queue.pop(0)
        _start_next_item(wreck)
        return

    wreck.current_item_id = item_id
    wreck.salvage_timer = item.salvage_time


def _find_item(wreck: Wreck, item_id: str) -> SalvageItem | None:
    for item in wreck.salvage_manifest:
        if item.id == item_id:
            return item
    return None


def _complete_current_item(wreck: Wreck, ship: Ship) -> list[dict]:
    """Complete extraction of the current item and apply to ship."""
    global _active_salvage_wreck_id
    events: list[dict] = []

    item = _find_item(wreck, wreck.current_item_id)  # type: ignore[arg-type]
    if item is None:
        return events

    item.salvaged = True

    # Apply to ship.
    if item.is_direct_use:
        amount = item.quantity * DIRECT_USE_EFFICIENCY
        ship.resources.add(item.item_type, round(amount, 1))
    else:
        # Check cargo capacity.
        current_cargo = sum(ship.cargo.values())
        if current_cargo + item.cargo_size <= ship.cargo_capacity:
            ship.cargo[item.item_type] = ship.cargo.get(item.item_type, 0.0) + item.quantity
        else:
            # Cargo full — still mark salvaged but emit warning.
            evt = {
                "type": "cargo_full",
                "wreck_id": wreck.id,
                "item_id": item.id,
                "item_name": item.name,
            }
            _pending_events.append(evt)
            events.append(evt)

    evt = {
        "type": "item_recovered",
        "wreck_id": wreck.id,
        "item_id": item.id,
        "item_name": item.name,
        "item_type": item.item_type,
        "quantity": item.quantity,
        "is_direct_use": item.is_direct_use,
    }
    _pending_events.append(evt)
    events.append(evt)

    # Remove from queue and start next.
    if wreck.salvage_queue and wreck.salvage_queue[0] == item.id:
        wreck.salvage_queue.pop(0)

    if wreck.salvage_queue:
        _start_next_item(wreck)
    else:
        # Salvage complete.
        wreck.salvage_state = "complete"
        wreck.current_item_id = None
        wreck.salvage_timer = 0.0
        _active_salvage_wreck_id = None
        evt = {"type": "salvage_complete", "wreck_id": wreck.id}
        _pending_events.append(evt)
        events.append(evt)

    return events


def _force_cancel_salvage(wreck: Wreck, reason: str = "") -> list[dict]:
    """Force-cancel an active salvage (e.g. ship moved away)."""
    global _active_salvage_wreck_id
    wreck.salvage_state = "aborted"
    wreck.current_item_id = None
    wreck.salvage_timer = 0.0
    wreck.salvage_queue.clear()
    if _active_salvage_wreck_id == wreck.id:
        _active_salvage_wreck_id = None

    evt = {"type": "salvage_cancelled", "wreck_id": wreck.id, "reason": reason}
    _pending_events.append(evt)
    return [evt]


def _cancel_active_if_needed(wreck_id: str) -> None:
    """If this wreck is the active salvage target, cancel it."""
    global _active_salvage_wreck_id
    if _active_salvage_wreck_id == wreck_id:
        wreck = get_wreck(wreck_id)
        if wreck is not None and wreck.salvage_state == "salvaging":
            _force_cancel_salvage(wreck, reason="wreck_removed")
        _active_salvage_wreck_id = None


def _detonate_reactor(wreck: Wreck, ship: Ship) -> list[dict]:
    """Detonate an armed reactor — damage ship if within blast range."""
    events: list[dict] = []

    dist = _distance(ship.x, ship.y, wreck.x, wreck.y)
    damage = 0.0
    if dist <= REACTOR_BLAST_RANGE:
        damage = _rng.uniform(REACTOR_DAMAGE_MIN, REACTOR_DAMAGE_MAX)
        damage = round(damage, 1)
        ship.hull = max(0.0, ship.hull - damage)

    evt = {
        "type": "reactor_detonation",
        "wreck_id": wreck.id,
        "distance": round(dist, 1),
        "damage": damage,
        "hull_remaining": round(ship.hull, 1),
    }
    _pending_events.append(evt)
    events.append(evt)

    # Cancel any active salvage on this wreck first.
    _cancel_active_if_needed(wreck.id)

    # Destroy the wreck.
    remove_wreck(wreck.id)

    return events
