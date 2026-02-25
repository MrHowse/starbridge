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


def sensor_range(ship: Ship, hazard_modifier: float = 1.0) -> float:
    """Effective sensor detection range based on sensor system efficiency.

    *hazard_modifier* (0.0–1.0) further reduces range when environmental
    hazards such as nebulae or radiation zones are active.
    """
    diff_mult = getattr(ship.difficulty, "sensor_range_multiplier", 1.0)
    base = getattr(ship, "sensor_range_base", BASE_SENSOR_RANGE)
    return base * ship.systems["sensors"].efficiency * hazard_modifier * diff_mult


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
    scan_time_mult = getattr(ship.difficulty, "scan_time_multiplier", 1.0)
    # Higher efficiency → smaller denominator → larger progress increment.
    # scan_time_multiplier >1 = slower scans (longer duration).
    effective_scan_time = BASE_SCAN_TIME * max(0.1, scan_time_mult)
    progress_per_sec = 100.0 / (effective_scan_time / efficiency)
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


def build_sensor_contacts(
    world: World,
    ship: Ship,
    extra_bubbles: list[tuple[float, float, float]] | None = None,
    hazard_modifier: float = 1.0,
    ghost_contacts: list[dict] | None = None,
) -> list[dict]:
    """Build the sensor.contacts payload for Weapons / Science clients.

    Includes ALL enemies, detected creatures, and visible stations — no
    distance filtering.  Science and Weapons receive the same contacts as
    Helm/Captain so that zooming out reveals the full battlefield.

    For unscanned contacts, type and shield/hull details are omitted —
    the client sees a bearing and position but no identity.
    For scanned contacts, full details plus a computed weakness hint are
    included.

    *extra_bubbles* provides (x, y, range) tuples from drones and sensor buoys.
    Contacts within a bubble are annotated with ``drone_detected: True``.
    *hazard_modifier* is accepted for API compatibility but no longer used
    for contact filtering.  ``sensor_range()`` remains available for the
    sensor-range ring display on the Science client.
    *ghost_contacts* — corvette ECM ghost contacts injected as fake enemies.
    """
    contacts: list[dict] = []

    # Pre-compute detection bubble set for annotation.
    _bubbles = extra_bubbles or []

    for enemy in world.enemies:
        contact: dict = {
            "id": enemy.id,
            "x": round(enemy.x, 1),
            "y": round(enemy.y, 1),
            "heading": round(enemy.heading, 2),
            "scan_state": enemy.scan_state,
            "kind": "enemy",
            # Enemies are "unknown" until Science scans them; then confirmed "hostile".
            "classification": "hostile" if enemy.scan_state == "scanned" else "unknown",
        }

        if enemy.scan_state == "scanned":
            contact.update(build_scan_result(enemy))

        # Annotate if within a drone/buoy detection bubble.
        for bx, by, br in _bubbles:
            dx = enemy.x - bx
            dy = enemy.y - by
            if dx * dx + dy * dy <= br * br:
                contact["drone_detected"] = True
                break

        contacts.append(contact)

    # Creatures (v0.05k) — include all detected creatures (no distance filter).
    for creature in world.creatures:
        if not creature.detected:
            continue
        contacts.append({
            "id": creature.id,
            "x": round(creature.x, 1),
            "y": round(creature.y, 1),
            "heading": round(creature.heading, 2),
            "kind": "creature",
            "creature_type": creature.creature_type,
            "behaviour_state": creature.behaviour_state,
            "scan_state": "scanned",
            "hull": round(creature.hull, 1),
            "hull_max": round(creature.hull_max, 1),
            "study_progress": round(creature.study_progress, 1),
            "communication_progress": round(creature.communication_progress, 1),
            "attached": creature.attached,
            "classification": "unknown",
        })

    # Stations — hostile stations always visible; others require transponder.
    for station in world.stations:
        if station.faction != "hostile" and not station.transponder_active:
            continue
        faction = station.faction
        if faction == "hostile":
            cls = "hostile"
        elif faction == "friendly":
            cls = "friendly"
        else:   # neutral, none (derelict)
            cls = "neutral"
        contacts.append({
            "id": station.id,
            "x": round(station.x, 1),
            "y": round(station.y, 1),
            "heading": 0.0,
            "kind": "station",
            "scan_state": "scanned",
            "classification": cls,
            "station_type": station.station_type,
            "faction": station.faction,
            "name": station.name,
            "hull": round(station.hull, 1),
            "hull_max": round(station.hull_max, 1),
        })

    # Corvette ECM ghost contacts — injected as fake enemy contacts.
    if ghost_contacts:
        contacts.extend(ghost_contacts)

    return contacts


def build_scan_result(enemy: Enemy) -> dict:
    """Return full scan detail for a scanned enemy (computed from live state)."""
    result = {
        "type": enemy.type,
        "hull": round(enemy.hull, 2),
        "hull_max": ENEMY_TYPE_PARAMS[enemy.type]["hull"],
        "shield_front": round(enemy.shield_front, 2),
        "shield_rear": round(enemy.shield_rear, 2),
        "weakness": _compute_weakness(enemy),
    }
    if enemy.shield_frequency:
        result["shield_frequency"] = enemy.shield_frequency
    return result


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
