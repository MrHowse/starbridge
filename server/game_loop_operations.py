"""
Operations Station — Game Loop Integration (v0.08 A.2).

The crew's analyst and coordinator.  Processes data from Science and other
stations into tactical intelligence, and pushes concrete bonuses to Weapons,
Helm, Flight Ops, and other stations.

This module replaces the old Tactical Officer (game_loop_tactical.py).
Operations is a clean-slate redesign — no legacy Tactical code carried over.

A.2 implements the Enemy Analysis System:
  - Battle Assessment (A.2.1): 15s scan with speed modifiers
  - Shield Harmonics  (A.2.2): per-facing shields + vulnerable facing
  - System Vulnerability (A.2.3): subsystem health + priority subsystem
  - Behaviour Prediction (A.2.4): 30s movement forecast + confidence
  - Threat Assessment (A.2.5): manual LOW/MEDIUM/HIGH/CRITICAL levels

Broadcasts emitted each tick:
  operations.state → ["operations"]  full state payload
  operations.event → [varies]        per-station event pushes

Constants tuned for 10 Hz game loop (TICK_DT = 0.1 s).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from server.models.ship import Ship
from server.models.world import Enemy, World
from server.systems.sensors import sensor_range
from server.utils.math_helpers import angle_diff, bearing_to, distance

# ---------------------------------------------------------------------------
# Constants (A.2)
# ---------------------------------------------------------------------------

ASSESSMENT_BASE_DURATION: float = 15.0     # seconds (A.2.1.2)
ASSESSMENT_BASIC_SCAN_MODIFIER: float = -0.25    # -25% speed (A.2.1.3)
ASSESSMENT_DETAILED_SCAN_MODIFIER: float = 0.25  # +25% speed (A.2.1.3)
ASSESSMENT_EW_JAM_MODIFIER: float = 0.15         # +15% speed (A.2.1.3)
ASSESSMENT_OUT_OF_RANGE_EXPIRY: float = 60.0      # seconds (A.2.1.4)
SHIELD_HARMONICS_REFRESH: float = 30.0            # seconds (A.2.2.3)
PRIORITY_SUBSYSTEM_COOLDOWN: float = 10.0         # seconds (A.2.3.3)
PREDICTION_WINDOW: float = 30.0                   # seconds forward (A.2.4.1)
PREDICTION_HISTORY_WINDOW: float = 30.0           # observation seconds (A.2.4.1)
PREDICTION_REFRESH_INTERVAL: float = 10.0         # seconds (A.2.4.4)
VULNERABLE_FACING_BONUS: float = 0.25             # +25% beam damage (A.2.2.2)
VULNERABLE_FACING_ARC: float = 30.0               # degrees (A.2.2.2)
PREDICTION_ACCURACY_BONUS: float = 0.10           # +10% accuracy (A.2.4.2)
PREDICTION_ACCURACY_THRESHOLD: float = 0.10       # 10% of distance (A.2.4.2)

_VALID_FACINGS = ("fore", "aft", "port", "starboard")
_VALID_SUBSYSTEMS = ("engines", "weapons", "shields", "sensors", "propulsion")
_VALID_THREAT_LEVELS = ("low", "medium", "high", "critical")
_FACING_OFFSETS = {"fore": 0.0, "aft": 180.0, "starboard": 90.0, "port": 270.0}


# ---------------------------------------------------------------------------
# Assessment dataclass
# ---------------------------------------------------------------------------


@dataclass
class BattleAssessment:
    """State for a single enemy contact assessment (A.2.1–A.2.5)."""

    enemy_id: str
    progress: float = 0.0       # seconds elapsed toward ASSESSMENT_BASE_DURATION
    complete: bool = False

    # A.2.2 — shield harmonics (populated on completion, refreshed periodically)
    shield_harmonics: dict[str, float] = field(default_factory=dict)
    harmonics_timer: float = 0.0

    # A.2.3 — designations
    vulnerable_facing: str | None = None
    priority_subsystem: str | None = None
    priority_cooldown: float = 0.0

    # A.2.4 — behaviour prediction
    prediction_active: bool = False
    position_history: list[tuple[float, float, float, float, float]] = field(
        default_factory=list
    )  # (x, y, heading, velocity, elapsed_time)
    predicted_x: float = 0.0
    predicted_y: float = 0.0
    prediction_confidence: str = "low"
    prediction_timer: float = 0.0

    # A.2.5 — threat level
    threat_level: str = "low"

    # A.2.1.4 — out-of-range tracking
    out_of_range_timer: float = 0.0


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_assessments: dict[str, BattleAssessment] = {}
_active_id: str | None = None  # enemy_id currently being assessed (in progress)
_pending_broadcasts: list[tuple[list[str], dict]] = []
_elapsed: float = 0.0  # total game time for history tracking


# ---------------------------------------------------------------------------
# Public API — Game loop interface
# ---------------------------------------------------------------------------


def reset() -> None:
    """Reset all operations state.  Called at game start."""
    global _assessments, _active_id, _pending_broadcasts, _elapsed
    _assessments = {}
    _active_id = None
    _pending_broadcasts = []
    _elapsed = 0.0


def tick(world: World, ship: Ship, dt: float) -> None:
    """Advance operations logic by one tick (A.2)."""
    global _active_id, _elapsed
    _elapsed += dt

    sr = sensor_range(ship)

    # Track which enemies are still alive and in range.
    alive_ids = {e.id for e in world.enemies}

    # --- Expire assessments for destroyed contacts ---
    destroyed = [eid for eid in _assessments if eid not in alive_ids]
    for eid in destroyed:
        del _assessments[eid]
        if _active_id == eid:
            _active_id = None

    # --- Range tracking and expiry (A.2.1.4) ---
    for eid, asmt in list(_assessments.items()):
        enemy = _find_enemy(world, eid)
        if enemy is None:
            continue
        dist = distance(ship.x, ship.y, enemy.x, enemy.y)
        if dist > sr:
            asmt.out_of_range_timer += dt
            if asmt.out_of_range_timer >= ASSESSMENT_OUT_OF_RANGE_EXPIRY:
                del _assessments[eid]
                if _active_id == eid:
                    _active_id = None
        else:
            asmt.out_of_range_timer = 0.0

    # --- Advance active assessment timer (A.2.1.2) ---
    if _active_id and _active_id in _assessments:
        asmt = _assessments[_active_id]
        if not asmt.complete:
            enemy = _find_enemy(world, _active_id)
            if enemy is not None:
                speed_mult = _assessment_speed_multiplier(enemy, ship)
                asmt.progress += dt * speed_mult
                if asmt.progress >= ASSESSMENT_BASE_DURATION:
                    asmt.progress = ASSESSMENT_BASE_DURATION
                    asmt.complete = True
                    _populate_assessment(asmt, enemy)
                    _active_id = None
                    _emit_assessment_complete(asmt, world, ship)

    # --- Update completed assessments each tick ---
    for eid, asmt in _assessments.items():
        if not asmt.complete:
            continue
        enemy = _find_enemy(world, eid)
        if enemy is None:
            continue

        # A.2.2.3 — refresh shield harmonics every 30s
        asmt.harmonics_timer += dt
        if asmt.harmonics_timer >= SHIELD_HARMONICS_REFRESH:
            asmt.harmonics_timer = 0.0
            asmt.shield_harmonics = _compute_shield_harmonics(enemy)

        # A.2.3.3 — tick priority subsystem cooldown
        if asmt.priority_cooldown > 0.0:
            asmt.priority_cooldown = max(0.0, asmt.priority_cooldown - dt)

        # A.2.4 — behaviour prediction
        if asmt.prediction_active:
            asmt.position_history.append(
                (enemy.x, enemy.y, enemy.heading, enemy.velocity, _elapsed)
            )
            # Trim history to observation window.
            cutoff = _elapsed - PREDICTION_HISTORY_WINDOW
            asmt.position_history = [
                p for p in asmt.position_history if p[4] >= cutoff
            ]
            # Refresh prediction every PREDICTION_REFRESH_INTERVAL.
            asmt.prediction_timer += dt
            if asmt.prediction_timer >= PREDICTION_REFRESH_INTERVAL:
                asmt.prediction_timer = 0.0
                _recompute_prediction(asmt, enemy)


def pop_pending_broadcasts() -> list[tuple[list[str], dict]]:
    """Return and clear pending broadcasts."""
    result = list(_pending_broadcasts)
    _pending_broadcasts.clear()
    return result


def build_state(world: World, ship: Ship) -> dict:
    """Serialise full operations state for broadcast to the operations station."""
    assessments: dict[str, dict] = {}
    for eid, asmt in _assessments.items():
        entry: dict = {
            "enemy_id": eid,
            "progress": round(asmt.progress, 2),
            "complete": asmt.complete,
            "threat_level": asmt.threat_level,
        }
        if asmt.complete:
            entry["shield_harmonics"] = {
                k: round(v, 2) for k, v in asmt.shield_harmonics.items()
            }
            entry["vulnerable_facing"] = asmt.vulnerable_facing
            entry["priority_subsystem"] = asmt.priority_subsystem
            entry["priority_cooldown"] = round(asmt.priority_cooldown, 2)
            # System health from the actual enemy.
            enemy = _find_enemy(world, eid)
            if enemy:
                entry["system_health"] = _get_system_health(enemy)
            # Prediction data.
            if asmt.prediction_active:
                entry["prediction"] = {
                    "active": True,
                    "predicted_x": round(asmt.predicted_x, 1),
                    "predicted_y": round(asmt.predicted_y, 1),
                    "confidence": asmt.prediction_confidence,
                }
            else:
                entry["prediction"] = {"active": False}
        assessments[eid] = entry

    return {
        "assessments": assessments,
        "active_assessment_id": _active_id,
        "coordination_bonuses": {},   # Stub for A.3
        "mission_tracking": [],       # Stub for A.4
        "feed_events": [],            # Stub for A.5
    }


def serialise() -> dict:
    """Serialise operations state for save system."""
    serialised_assessments = {}
    for eid, asmt in _assessments.items():
        serialised_assessments[eid] = {
            "enemy_id": asmt.enemy_id,
            "progress": asmt.progress,
            "complete": asmt.complete,
            "shield_harmonics": asmt.shield_harmonics,
            "harmonics_timer": asmt.harmonics_timer,
            "vulnerable_facing": asmt.vulnerable_facing,
            "priority_subsystem": asmt.priority_subsystem,
            "priority_cooldown": asmt.priority_cooldown,
            "prediction_active": asmt.prediction_active,
            "predicted_x": asmt.predicted_x,
            "predicted_y": asmt.predicted_y,
            "prediction_confidence": asmt.prediction_confidence,
            "prediction_timer": asmt.prediction_timer,
            "threat_level": asmt.threat_level,
            "out_of_range_timer": asmt.out_of_range_timer,
        }
    return {
        "assessments": serialised_assessments,
        "active_id": _active_id,
        "elapsed": _elapsed,
    }


def deserialise(data: dict) -> None:
    """Restore operations state from save data."""
    global _assessments, _active_id, _elapsed, _pending_broadcasts
    _pending_broadcasts = []
    _assessments = {}
    _active_id = data.get("active_id")
    _elapsed = data.get("elapsed", 0.0)
    for eid, ad in data.get("assessments", {}).items():
        asmt = BattleAssessment(enemy_id=ad["enemy_id"])
        asmt.progress = ad.get("progress", 0.0)
        asmt.complete = ad.get("complete", False)
        asmt.shield_harmonics = ad.get("shield_harmonics", {})
        asmt.harmonics_timer = ad.get("harmonics_timer", 0.0)
        asmt.vulnerable_facing = ad.get("vulnerable_facing")
        asmt.priority_subsystem = ad.get("priority_subsystem")
        asmt.priority_cooldown = ad.get("priority_cooldown", 0.0)
        asmt.prediction_active = ad.get("prediction_active", False)
        asmt.predicted_x = ad.get("predicted_x", 0.0)
        asmt.predicted_y = ad.get("predicted_y", 0.0)
        asmt.prediction_confidence = ad.get("prediction_confidence", "low")
        asmt.prediction_timer = ad.get("prediction_timer", 0.0)
        asmt.threat_level = ad.get("threat_level", "low")
        asmt.out_of_range_timer = ad.get("out_of_range_timer", 0.0)
        _assessments[eid] = asmt


# ---------------------------------------------------------------------------
# Public API — Message handlers (called from game_loop._drain_queue)
# ---------------------------------------------------------------------------


def start_assessment(contact_id: str, world: World, ship: Ship) -> dict:
    """Begin a battle assessment on a contact (A.2.1.1–A.2.1.2).

    Returns a result dict with 'ok' and optional 'reason'.
    """
    global _active_id

    enemy = _find_enemy(world, contact_id)
    if enemy is None:
        return {"ok": False, "reason": "Contact not found."}
    if enemy.scan_state != "scanned":
        return {
            "ok": False,
            "reason": "Insufficient sensor data — request scan from Science.",
        }

    # Cancel any in-progress assessment.
    if _active_id and _active_id in _assessments:
        old = _assessments[_active_id]
        if not old.complete:
            del _assessments[_active_id]

    # Create or re-use existing completed assessment.
    if contact_id not in _assessments:
        _assessments[contact_id] = BattleAssessment(enemy_id=contact_id)
    else:
        # Re-assess: reset progress but keep designations.
        asmt = _assessments[contact_id]
        asmt.progress = 0.0
        asmt.complete = False

    _active_id = contact_id
    return {"ok": True}


def cancel_assessment() -> dict:
    """Cancel the current in-progress assessment (A.2.1.2)."""
    global _active_id
    if _active_id is None:
        return {"ok": False, "reason": "No assessment in progress."}
    if _active_id in _assessments and not _assessments[_active_id].complete:
        del _assessments[_active_id]
    _active_id = None
    return {"ok": True}


def set_vulnerable_facing(contact_id: str, facing: str) -> dict:
    """Designate a vulnerable facing on an assessed contact (A.2.2.2)."""
    if facing not in _VALID_FACINGS:
        return {"ok": False, "reason": f"Invalid facing: {facing}"}
    asmt = _assessments.get(contact_id)
    if asmt is None or not asmt.complete:
        return {"ok": False, "reason": "Contact not assessed."}
    asmt.vulnerable_facing = facing
    _pending_broadcasts.append(
        (
            ["weapons", "helm", "captain"],
            {
                "type": "vulnerable_facing",
                "contact_id": contact_id,
                "facing": facing,
            },
        )
    )
    return {"ok": True}


def set_priority_subsystem(contact_id: str, subsystem: str) -> dict:
    """Designate a priority subsystem on an assessed contact (A.2.3.2)."""
    if subsystem not in _VALID_SUBSYSTEMS:
        return {"ok": False, "reason": f"Invalid subsystem: {subsystem}"}
    asmt = _assessments.get(contact_id)
    if asmt is None or not asmt.complete:
        return {"ok": False, "reason": "Contact not assessed."}
    if asmt.priority_cooldown > 0.0:
        return {
            "ok": False,
            "reason": f"Cooldown active ({asmt.priority_cooldown:.1f}s remaining).",
        }
    asmt.priority_subsystem = subsystem
    asmt.priority_cooldown = PRIORITY_SUBSYSTEM_COOLDOWN
    _pending_broadcasts.append(
        (
            ["weapons", "flight_ops"],
            {
                "type": "priority_subsystem",
                "contact_id": contact_id,
                "subsystem": subsystem,
            },
        )
    )
    return {"ok": True}


def toggle_prediction(contact_id: str, active: bool) -> dict:
    """Toggle behaviour prediction on an assessed contact (A.2.4.4)."""
    asmt = _assessments.get(contact_id)
    if asmt is None or not asmt.complete:
        return {"ok": False, "reason": "Contact not assessed."}
    asmt.prediction_active = active
    if active:
        asmt.prediction_timer = PREDICTION_REFRESH_INTERVAL  # force immediate compute
        asmt.position_history = []
    else:
        asmt.predicted_x = 0.0
        asmt.predicted_y = 0.0
        asmt.prediction_confidence = "low"
    return {"ok": True}


def set_threat_level(contact_id: str, level: str) -> dict:
    """Set threat level on a contact (A.2.5.1).

    Threat level can be set on any contact (assessed or not).
    """
    if level not in _VALID_THREAT_LEVELS:
        return {"ok": False, "reason": f"Invalid threat level: {level}"}

    # Allow setting threat on non-assessed contacts too — create minimal entry.
    if contact_id not in _assessments:
        _assessments[contact_id] = BattleAssessment(enemy_id=contact_id)
    _assessments[contact_id].threat_level = level

    # A.2.5.2–A.2.5.3: push to all stations within 1 tick.
    targets: list[str] = ["captain", "weapons", "helm", "science", "operations"]
    if level in ("high", "critical"):
        targets.extend(["flight_ops", "electronic_warfare", "medical", "engineering"])
    _pending_broadcasts.append(
        (
            targets,
            {"type": "threat_level", "contact_id": contact_id, "level": level},
        )
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Public API — Query functions (used by combat / weapons for REAL bonuses)
# ---------------------------------------------------------------------------


def get_vulnerable_facing(enemy_id: str) -> str | None:
    """Return the designated vulnerable facing for an enemy, or None."""
    asmt = _assessments.get(enemy_id)
    if asmt and asmt.complete:
        return asmt.vulnerable_facing
    return None


def get_priority_subsystem(enemy_id: str) -> str | None:
    """Return the designated priority subsystem for an enemy, or None."""
    asmt = _assessments.get(enemy_id)
    if asmt and asmt.complete:
        return asmt.priority_subsystem
    return None


def get_threat_level(enemy_id: str) -> str:
    """Return the threat level for an enemy (default 'low')."""
    asmt = _assessments.get(enemy_id)
    return asmt.threat_level if asmt else "low"


def get_prediction_accuracy_bonus(
    enemy_id: str, actual_x: float, actual_y: float
) -> float:
    """Return damage bonus multiplier if the enemy is near its predicted position.

    Returns PREDICTION_ACCURACY_BONUS (0.10) if within 10% of distance from
    prediction, else 0.0.  (A.2.4.2)
    """
    asmt = _assessments.get(enemy_id)
    if not asmt or not asmt.complete or not asmt.prediction_active:
        return 0.0
    if asmt.predicted_x == 0.0 and asmt.predicted_y == 0.0:
        return 0.0
    pred_dist = distance(asmt.predicted_x, asmt.predicted_y, actual_x, actual_y)
    # Threshold: 10% of the prediction distance (how far the enemy was predicted to travel).
    # Use distance from last known position to predicted position as reference.
    if len(asmt.position_history) < 2:
        return 0.0
    last_x, last_y = asmt.position_history[-1][0], asmt.position_history[-1][1]
    travel_dist = distance(last_x, last_y, asmt.predicted_x, asmt.predicted_y)
    if travel_dist < 100.0:
        # Enemy barely moved in prediction — always "accurate".
        return PREDICTION_ACCURACY_BONUS
    if pred_dist <= travel_dist * PREDICTION_ACCURACY_THRESHOLD:
        return PREDICTION_ACCURACY_BONUS
    return 0.0


def check_vulnerable_facing_bonus(
    enemy_id: str, enemy: Enemy, attacker_x: float, attacker_y: float
) -> float:
    """Return beam damage multiplier for vulnerable facing (A.2.2.2).

    Returns VULNERABLE_FACING_BONUS (0.25) if the attack angle is within
    VULNERABLE_FACING_ARC degrees of the designated facing, else 0.0.
    """
    facing = get_vulnerable_facing(enemy_id)
    if facing is None:
        return 0.0
    # Compute the world-angle of the designated facing.
    offset = _FACING_OFFSETS.get(facing, 0.0)
    facing_angle = (enemy.heading + offset) % 360.0
    # Bearing from enemy to attacker.
    brg = bearing_to(enemy.x, enemy.y, attacker_x, attacker_y)
    diff = abs(angle_diff(facing_angle, brg))
    if diff <= VULNERABLE_FACING_ARC:
        return VULNERABLE_FACING_BONUS
    return 0.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_enemy(world: World, enemy_id: str) -> Enemy | None:
    """Look up an enemy by ID."""
    return next((e for e in world.enemies if e.id == enemy_id), None)


def _assessment_speed_multiplier(enemy: Enemy, ship: Ship) -> float:
    """Compute assessment speed multiplier from modifiers (A.2.1.3).

    Base speed = 1.0.
    +25% if detailed scan, -25% if basic scan.
    +15% if enemy is being jammed by EW.
    Scales with sensor system efficiency.
    """
    mult = 1.0

    # Scan quality modifier.
    scan_detail = getattr(enemy, "scan_detail", "basic")
    if scan_detail == "detailed":
        mult += ASSESSMENT_DETAILED_SCAN_MODIFIER
    else:
        mult += ASSESSMENT_BASIC_SCAN_MODIFIER

    # EW jamming modifier.
    if enemy.jam_factor > 0.0:
        mult += ASSESSMENT_EW_JAM_MODIFIER

    # Sensor system efficiency.
    sensor_eff = ship.systems["sensors"].efficiency
    mult *= sensor_eff

    return max(0.1, mult)  # floor at 10% to prevent stalling


def _compute_shield_harmonics(enemy: Enemy) -> dict[str, float]:
    """Compute 4-facing shield data from enemy's 2-facing shields (A.2.2.1)."""
    f = enemy.shield_front
    r = enemy.shield_rear
    return {
        "fore": round(f, 2),
        "aft": round(r, 2),
        "port": round((f + r) / 2, 2),
        "starboard": round((f + r) / 2, 2),
    }


def _get_system_health(enemy: Enemy) -> dict[str, float]:
    """Return enemy subsystem health percentages (A.2.3.1)."""
    return {
        "engines": round(enemy.system_engines, 2),
        "weapons": round(enemy.system_weapons, 2),
        "shields": round(enemy.system_shields, 2),
        "sensors": round(enemy.system_sensors, 2),
        "propulsion": round(enemy.system_propulsion, 2),
    }


def _populate_assessment(asmt: BattleAssessment, enemy: Enemy) -> None:
    """Fill in assessment results on completion (A.2.2, A.2.3)."""
    asmt.shield_harmonics = _compute_shield_harmonics(enemy)
    asmt.harmonics_timer = 0.0


def _emit_assessment_complete(
    asmt: BattleAssessment, world: World, ship: Ship
) -> None:
    """Queue broadcasts when an assessment completes."""
    enemy = _find_enemy(world, asmt.enemy_id)
    data: dict = {
        "type": "assessment_complete",
        "contact_id": asmt.enemy_id,
        "shield_harmonics": asmt.shield_harmonics,
    }
    if enemy:
        data["system_health"] = _get_system_health(enemy)
    _pending_broadcasts.append((["operations", "captain"], data))


def _recompute_prediction(asmt: BattleAssessment, enemy: Enemy) -> None:
    """Recompute 30-second behaviour prediction (A.2.4.1–A.2.4.3)."""
    if len(asmt.position_history) < 2:
        asmt.prediction_confidence = "low"
        asmt.predicted_x = enemy.x
        asmt.predicted_y = enemy.y
        return

    # Use current velocity and heading for linear extrapolation.
    heading_rad = math.radians(enemy.heading)
    dx = math.sin(heading_rad) * enemy.velocity * PREDICTION_WINDOW
    dy = -math.cos(heading_rad) * enemy.velocity * PREDICTION_WINDOW
    asmt.predicted_x = enemy.x + dx
    asmt.predicted_y = enemy.y + dy

    # Compute confidence from heading variance over observation window.
    headings = [p[2] for p in asmt.position_history]
    if len(headings) >= 3:
        diffs = [
            abs(angle_diff(headings[i], headings[i + 1]))
            for i in range(len(headings) - 1)
        ]
        avg_change = sum(diffs) / len(diffs)
        if avg_change < 2.0:
            asmt.prediction_confidence = "high"
        elif avg_change < 15.0:
            asmt.prediction_confidence = "medium"
        else:
            asmt.prediction_confidence = "low"
    else:
        asmt.prediction_confidence = "medium"
