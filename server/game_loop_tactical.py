"""
Tactical Officer — Game Loop Integration.

Handles:
  - Threat assessment: auto-rates enemies by danger level (low/medium/high/critical)
    using distance, AI state, and type. Overrideable by the Tactical player.
  - Engagement priorities: designates targets as primary/secondary/ignore.
    Broadcasts designations to Weapons station.
  - Intercept plotting: calculates intercept course suggestions for Helm.
  - Tactical annotations: stores markers and notes visible on the map.
  - Coordinated strikes: timed countdown cards broadcast to relevant stations.

Broadcasts emitted each tick:
  tactical.state        → ["tactical"]  full state payload
  tactical.designations → ["weapons"]   engagement priority dict
  tactical.intercept    → ["helm"]      suggested bearing + ETA (or null)
  tactical.strike_countdown → [role]    per-step countdown during execution

Constants tuned for 10 Hz game loop (TICK_DT = 0.1 s).
"""
from __future__ import annotations

import time as _time

from server.models.ship import Ship
from server.models.world import World
from server.utils.math_helpers import bearing_to, distance

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Distance threshold for "critical" threat (enemy actively attacking, very close).
THREAT_CRITICAL_RANGE: float = 5_000.0
#: Distance threshold for "high" threat (enemy attacking, or very close).
THREAT_HIGH_RANGE: float = 10_000.0
#: Distance threshold for "medium" threat (enemy chasing or nearby).
THREAT_MEDIUM_RANGE: float = 18_000.0

#: Countdown window: broadcast per-step countdown when within this many seconds.
COUNTDOWN_WINDOW: float = 10.0

#: Auto-expire executing plan this many seconds after the last step offset.
PLAN_EXPIRE_AFTER: float = 5.0

#: Base max ship speed used for ETA estimation (world units/s).
_BASE_SHIP_SPEED: float = 80.0


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_engagement_priorities: dict[str, str | None] = {}   # entity_id → priority
_threat_overrides: dict[str, str] = {}                # entity_id → threat level
_intercept_target_id: str | None = None
_annotations: list[dict] = []
_annotation_counter: int = 0
_strike_plans: list[dict] = []
_plan_counter: int = 0
_pending_broadcasts: list[tuple[list[str], dict]] = []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset() -> None:
    """Reset all tactical state. Called at game start."""
    global _engagement_priorities, _threat_overrides, _intercept_target_id
    global _annotations, _annotation_counter, _strike_plans, _plan_counter
    global _pending_broadcasts
    _engagement_priorities = {}
    _threat_overrides = {}
    _intercept_target_id = None
    _annotations = []
    _annotation_counter = 0
    _strike_plans = []
    _plan_counter = 0
    _pending_broadcasts = []


def auto_threat_level(enemy, ship_x: float, ship_y: float) -> str:
    """Compute automatic threat rating for an enemy contact."""
    dist = distance(ship_x, ship_y, enemy.x, enemy.y)
    ai = enemy.ai_state
    if ai == "attack" and dist < THREAT_CRITICAL_RANGE:
        return "critical"
    if ai == "attack" or dist < THREAT_HIGH_RANGE:
        return "high"
    if ai == "chase" or dist < THREAT_MEDIUM_RANGE:
        return "medium"
    return "low"


def get_threat_level(enemy, ship_x: float, ship_y: float) -> str:
    """Return the effective threat level (override > auto)."""
    override = _threat_overrides.get(enemy.id)
    return override if override else auto_threat_level(enemy, ship_x, ship_y)


def set_threat_override(entity_id: str, threat_level: str | None) -> None:
    """Manually override the threat level for an entity. Pass None to clear."""
    if threat_level is None:
        _threat_overrides.pop(entity_id, None)
    else:
        _threat_overrides[entity_id] = threat_level


def set_engagement_priority(entity_id: str, priority: str | None) -> None:
    """Set engagement priority for an entity. Pass None to clear designation."""
    if priority is None:
        _engagement_priorities.pop(entity_id, None)
    else:
        _engagement_priorities[entity_id] = priority


def get_designations() -> dict:
    """Return engagement priority dict for broadcast to Weapons station."""
    return dict(_engagement_priorities)


def set_intercept_target(entity_id: str | None) -> None:
    """Set (or clear) the intercept target for Helm suggestions."""
    global _intercept_target_id
    _intercept_target_id = entity_id


def calc_intercept(world: World, ship: Ship) -> dict | None:
    """Calculate intercept bearing + ETA for the current intercept target.

    Returns None if no target is set or the target no longer exists.
    """
    if _intercept_target_id is None:
        return None
    enemy = next((e for e in world.enemies if e.id == _intercept_target_id), None)
    if enemy is None:
        return None
    brg = bearing_to(ship.x, ship.y, enemy.x, enemy.y)
    dist = distance(ship.x, ship.y, enemy.x, enemy.y)
    eta_s = dist / max(1.0, _BASE_SHIP_SPEED)
    return {
        "target_id": _intercept_target_id,
        "bearing": round(brg, 1),
        "eta_s": round(eta_s, 1),
    }


def add_annotation(
    annotation_type: str,
    x: float,
    y: float,
    label: str = "",
    text: str = "",
) -> str:
    """Add an annotation to the tactical plot. Returns the annotation ID."""
    global _annotation_counter
    _annotation_counter += 1
    ann_id = f"ann_{_annotation_counter}"
    _annotations.append({
        "id": ann_id,
        "type": annotation_type,
        "x": round(x, 1),
        "y": round(y, 1),
        "label": label,
        "text": text,
    })
    return ann_id


def remove_annotation(annotation_id: str) -> None:
    """Remove an annotation by ID."""
    _annotations[:] = [a for a in _annotations if a["id"] != annotation_id]


def create_strike_plan(steps: list[dict]) -> str:
    """Create a new coordinated strike plan. Returns the plan ID."""
    global _plan_counter
    _plan_counter += 1
    plan_id = f"plan_{_plan_counter}"
    _strike_plans.append({
        "plan_id": plan_id,
        "steps": [dict(s) for s in steps],
        "executing": False,
        "execute_start_t": None,
    })
    return plan_id


def execute_strike_plan(plan_id: str) -> bool:
    """Start executing a strike plan. Returns True if found and started."""
    for plan in _strike_plans:
        if plan["plan_id"] == plan_id and not plan["executing"]:
            plan["executing"] = True
            plan["execute_start_t"] = _time.monotonic()
            return True
    return False


def tick(world: World, ship: Ship, dt: float) -> None:
    """Advance strike plan countdowns and queue countdown broadcasts."""
    now = _time.monotonic()
    for plan in _strike_plans:
        if not plan["executing"] or plan["execute_start_t"] is None:
            continue
        elapsed = now - plan["execute_start_t"]
        for i, step in enumerate(plan["steps"]):
            offset_s = float(step.get("offset_s", 0.0))
            seconds_remaining = offset_s - elapsed
            if 0.0 <= seconds_remaining <= COUNTDOWN_WINDOW:
                floor_sr = int(seconds_remaining)
                if step.get("_last_floor", -1) != floor_sr:
                    step["_last_floor"] = floor_sr
                    role = step.get("role", "")
                    if role:
                        _pending_broadcasts.append((
                            [role],
                            {
                                "plan_id": plan["plan_id"],
                                "step_index": i,
                                "action": step.get("action", ""),
                                "seconds_remaining": floor_sr,
                            },
                        ))
        last_offset = max(
            (float(s.get("offset_s", 0.0)) for s in plan["steps"]),
            default=0.0,
        )
        if elapsed > last_offset + PLAN_EXPIRE_AFTER:
            plan["executing"] = False
            plan["execute_start_t"] = None


def pop_pending_broadcasts() -> list[tuple[list[str], dict]]:
    """Return and clear pending strike countdown broadcasts."""
    result = list(_pending_broadcasts)
    _pending_broadcasts.clear()
    return result


def build_state(world: World, ship: Ship) -> dict:
    """Serialise full tactical state for broadcast to the tactical station."""
    enemies_data = []
    for enemy in world.enemies:
        dist = distance(ship.x, ship.y, enemy.x, enemy.y)
        enemies_data.append({
            "id": enemy.id,
            "type": enemy.type,
            "x": round(enemy.x, 1),
            "y": round(enemy.y, 1),
            "distance": round(dist, 1),
            "ai_state": enemy.ai_state,
            "threat_level": get_threat_level(enemy, ship.x, ship.y),
            "engagement_priority": _engagement_priorities.get(enemy.id),
        })
    intercept = calc_intercept(world, ship)
    return {
        "enemies": enemies_data,
        "engagement_priorities": get_designations(),
        "intercept_target_id": _intercept_target_id,
        "intercept_bearing": intercept["bearing"] if intercept else None,
        "intercept_eta_s": intercept["eta_s"] if intercept else None,
        "annotations": list(_annotations),
        "strike_plans": [
            {
                "plan_id": p["plan_id"],
                "steps": [
                    {k: v for k, v in s.items() if not k.startswith("_")}
                    for s in p["steps"]
                ],
                "executing": p["executing"],
            }
            for p in _strike_plans
        ],
    }
