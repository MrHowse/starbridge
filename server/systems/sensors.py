"""
Sensor System — Scanning and Detection.

Manages the active scan mechanic: target selection, progress tracking, and
scan completion.  Builds the role-filtered sensor.contacts payload that
Weapons and Science clients receive in place of the full world.entities.

Sensor power (from Engineering) scales two independent things:
  - Scan range:  effective_range = BASE_SENSOR_RANGE × sensor_efficiency
  - Scan speed:  progress/sec    = 100 / (BASE_SCAN_TIME / sensor_efficiency)

Call reset() from game_loop.start() to clear scan state between games.
"""
from __future__ import annotations

from dataclasses import dataclass

from server.models.world import ENEMY_TYPE_PARAMS, Enemy, World
from server.models.ship import Ship
from server.utils.math_helpers import distance

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_SENSOR_RANGE: float = 30_000.0   # world units at 100 % sensor efficiency
BASE_SCAN_TIME: float = 5.0           # seconds to complete scan at 100 % efficiency
_MIN_EFFICIENCY: float = 0.01         # guard against division-by-zero


# ---------------------------------------------------------------------------
# Active scan state
# ---------------------------------------------------------------------------


@dataclass
class ActiveScan:
    """Tracks an in-progress scan of a single contact."""

    entity_id: str
    progress: float = 0.0   # 0.0 – 100.0


_active_scan: ActiveScan | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset() -> None:
    """Clear scan state. Call at game start / stop."""
    global _active_scan
    _active_scan = None


def start_scan(entity_id: str) -> None:
    """Begin scanning an entity. Resets any in-progress scan."""
    global _active_scan
    _active_scan = ActiveScan(entity_id=entity_id)


def cancel_scan() -> None:
    """Cancel the current scan. Progress is lost."""
    global _active_scan
    _active_scan = None


def get_scan_progress() -> tuple[str, float] | None:
    """Return (entity_id, progress) for the current scan, or None."""
    if _active_scan is None:
        return None
    return (_active_scan.entity_id, _active_scan.progress)


def sensor_range(ship: Ship) -> float:
    """Effective sensor detection range based on sensor system efficiency."""
    return BASE_SENSOR_RANGE * ship.systems["sensors"].efficiency


def tick(world: World, ship: Ship, dt: float) -> list[str]:
    """Advance the active scan by dt seconds (scaled by sensor efficiency).

    Returns a list of entity_ids whose scan completed this tick (0 or 1 item).
    Marks the enemy's scan_state as 'scanned' on completion and clears the
    active scan so Science can start scanning another contact.
    """
    global _active_scan
    if _active_scan is None:
        return []

    efficiency = max(_MIN_EFFICIENCY, ship.systems["sensors"].efficiency)
    # Higher efficiency → smaller denominator → larger progress increment.
    progress_per_sec = 100.0 / (BASE_SCAN_TIME / efficiency)
    _active_scan.progress = min(100.0, _active_scan.progress + progress_per_sec * dt)

    if _active_scan.progress >= 100.0:
        completed_id = _active_scan.entity_id
        for enemy in world.enemies:
            if enemy.id == completed_id:
                enemy.scan_state = "scanned"
                break
        _active_scan = None
        return [completed_id]

    return []


def build_sensor_contacts(world: World, ship: Ship) -> list[dict]:
    """Build the sensor.contacts payload for Weapons / Science clients.

    Only includes enemies within effective sensor range.
    For unscanned contacts, type and shield/hull details are omitted —
    the client sees a bearing and position but no identity.
    For scanned contacts, full details plus a computed weakness hint are
    included.
    """
    range_ = sensor_range(ship)
    contacts: list[dict] = []

    for enemy in world.enemies:
        dist = distance(ship.x, ship.y, enemy.x, enemy.y)
        if dist > range_:
            continue

        contact: dict = {
            "id": enemy.id,
            "x": round(enemy.x, 1),
            "y": round(enemy.y, 1),
            "heading": round(enemy.heading, 2),
            "scan_state": enemy.scan_state,
        }

        if enemy.scan_state == "scanned":
            contact.update(build_scan_result(enemy))

        contacts.append(contact)

    return contacts


def build_scan_result(enemy: Enemy) -> dict:
    """Return full scan detail for a scanned enemy (computed from live state)."""
    return {
        "type": enemy.type,
        "hull": round(enemy.hull, 2),
        "hull_max": ENEMY_TYPE_PARAMS[enemy.type]["hull"],
        "shield_front": round(enemy.shield_front, 2),
        "shield_rear": round(enemy.shield_rear, 2),
        "weakness": _compute_weakness(enemy),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_weakness(enemy: Enemy) -> str | None:
    """Derive a tactical weakness hint from the enemy's live state."""
    max_hull = ENEMY_TYPE_PARAMS[enemy.type]["hull"]

    if enemy.shield_rear < enemy.shield_front * 0.5:
        return "Rear shields compromised — aft approach recommended"
    if enemy.shield_front < 20.0:
        return "Forward shields critical — press frontal assault"
    if enemy.hull < max_hull * 0.3:
        return f"Hull critically damaged ({round(enemy.hull)} HP) — finish it"
    return None
