"""
Dynamic mission lifecycle manager — v0.06.4 missions Part 2.

Module-level state following the same pattern as game_loop_comms, game_loop_weapons, etc.
Manages offered/accepted/active/completed/failed missions generated from Comms intelligence.

Public API:
    reset(), offer_mission(), accept_mission(), decline_mission(),
    tick_missions(), get_missions(), get_active_missions(), get_offered_missions(),
    pop_pending_mission_events(), serialise(), deserialise()
"""
from __future__ import annotations

import logging
from typing import Any

from server.models.dynamic_mission import (
    DEFAULT_ACCEPT_DEADLINE,
    DEFAULT_COMPLETION_DEADLINE,
    DynamicMission,
    MAX_ACTIVE_MISSIONS,
    MissionRewards,
    NAVIGATE_COMPLETION_RADIUS,
)

logger = logging.getLogger("starbridge.dynamic_missions")

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_missions: list[DynamicMission] = []
_mission_counter: int = 0

# Events consumed by game_loop for broadcast
_pending_mission_events: list[dict] = []

# Completed/failed mission IDs — kept for debrief
_completed_mission_ids: list[str] = []
_failed_mission_ids: list[str] = []

# Current tick (set externally)
_tick: int = 0


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

def reset() -> None:
    """Clear all dynamic mission state. Called at game start."""
    global _mission_counter, _tick
    _mission_counter = 0
    _tick = 0
    _missions.clear()
    _pending_mission_events.clear()
    _completed_mission_ids.clear()
    _failed_mission_ids.clear()


# ---------------------------------------------------------------------------
# Tick counter
# ---------------------------------------------------------------------------

def set_tick(tick: int) -> None:
    global _tick
    _tick = tick


# ---------------------------------------------------------------------------
# Mission ID generation
# ---------------------------------------------------------------------------

def _next_mission_id() -> str:
    global _mission_counter
    _mission_counter += 1
    return f"dm_{_mission_counter}"


def next_mission_id() -> str:
    """Public accessor for generating mission IDs (used by comms pipeline)."""
    return _next_mission_id()


# ---------------------------------------------------------------------------
# Offer / Accept / Decline
# ---------------------------------------------------------------------------

def offer_mission(mission: DynamicMission) -> bool:
    """Add a mission to the offered list.

    Returns False if max active missions reached or duplicate ID.
    """
    if len(get_active_missions()) >= MAX_ACTIVE_MISSIONS:
        logger.info("Max active missions reached — declining offer %s", mission.id)
        return False

    if any(m.id == mission.id for m in _missions):
        logger.warning("Duplicate mission ID: %s", mission.id)
        return False

    mission.status = "offered"
    if mission.offered_tick == 0:
        mission.offered_tick = _tick
    if mission.deadline_tick is None and mission.accept_deadline is not None:
        mission.deadline_tick = _tick + int(mission.accept_deadline * 10)  # 10Hz ticks
    _missions.append(mission)

    _pending_mission_events.append({
        "event": "mission_offered",
        "mission": mission.to_dict(),
    })

    logger.info("Mission offered: %s (%s)", mission.title, mission.id)
    return True


def accept_mission(mission_id: str) -> dict:
    """Accept an offered mission. Returns result dict."""
    mission = get_mission(mission_id)
    if mission is None:
        return {"ok": False, "error": "Mission not found."}
    if mission.status != "offered":
        return {"ok": False, "error": f"Mission is {mission.status}, not offered."}

    # Check deadline
    if mission.deadline_tick is not None and _tick > mission.deadline_tick:
        mission.status = "expired"
        _pending_mission_events.append({
            "event": "mission_expired",
            "mission_id": mission.id,
        })
        return {"ok": False, "error": "Mission offer has expired."}

    # Check active limit
    if len(get_active_missions()) >= MAX_ACTIVE_MISSIONS:
        return {"ok": False, "error": "Maximum active missions reached."}

    mission.status = "active"
    mission.accept_deadline = None  # No longer ticking

    # Set completion deadline
    if mission.completion_deadline is not None and mission.completion_deadline_tick is None:
        mission.completion_deadline_tick = _tick + int(mission.completion_deadline * 10)

    _pending_mission_events.append({
        "event": "mission_accepted",
        "mission": mission.to_dict(),
    })

    logger.info("Mission accepted: %s (%s)", mission.title, mission.id)
    return {"ok": True, "mission": mission.to_dict()}


def decline_mission(mission_id: str) -> dict:
    """Decline an offered mission. Returns result dict."""
    mission = get_mission(mission_id)
    if mission is None:
        return {"ok": False, "error": "Mission not found."}
    if mission.status != "offered":
        return {"ok": False, "error": f"Mission is {mission.status}, not offered."}

    mission.status = "declined"

    _pending_mission_events.append({
        "event": "mission_declined",
        "mission_id": mission.id,
        "consequences": mission.decline_consequences,
    })

    logger.info("Mission declined: %s (%s)", mission.title, mission.id)
    return {"ok": True, "consequences": mission.decline_consequences}


# ---------------------------------------------------------------------------
# Completion / Failure
# ---------------------------------------------------------------------------

def complete_mission(mission_id: str) -> dict:
    """Mark a mission as completed. Returns result with rewards."""
    mission = get_mission(mission_id)
    if mission is None:
        return {"ok": False, "error": "Mission not found."}
    if not mission.is_active:
        return {"ok": False, "error": f"Mission is {mission.status}, not active."}

    mission.status = "completed"
    _completed_mission_ids.append(mission.id)

    _pending_mission_events.append({
        "event": "mission_completed",
        "mission_id": mission.id,
        "title": mission.title,
        "rewards": mission.rewards.to_dict(),
    })

    logger.info("Mission completed: %s (%s)", mission.title, mission.id)
    return {"ok": True, "rewards": mission.rewards.to_dict()}


def fail_mission(mission_id: str, reason: str = "") -> dict:
    """Mark a mission as failed. Returns result with consequences."""
    mission = get_mission(mission_id)
    if mission is None:
        return {"ok": False, "error": "Mission not found."}
    if not mission.is_active:
        return {"ok": False, "error": f"Mission is {mission.status}, not active."}

    mission.status = "failed"
    _failed_mission_ids.append(mission.id)

    _pending_mission_events.append({
        "event": "mission_failed",
        "mission_id": mission.id,
        "title": mission.title,
        "reason": reason,
        "consequences": mission.failure_consequences,
    })

    logger.info("Mission failed: %s (%s) — %s", mission.title, mission.id, reason)
    return {"ok": True, "consequences": mission.failure_consequences}


# ---------------------------------------------------------------------------
# Objective completion
# ---------------------------------------------------------------------------

def complete_objective(mission_id: str, objective_id: str) -> bool:
    """Mark a specific objective as completed.

    Returns True if found and marked. Auto-completes mission if all required done.
    """
    mission = get_mission(mission_id)
    if mission is None or not mission.is_active:
        return False

    for obj in mission.objectives:
        if obj.id == objective_id and not obj.completed:
            obj.completed = True
            _pending_mission_events.append({
                "event": "objective_completed",
                "mission_id": mission.id,
                "objective_id": obj.id,
                "description": obj.description,
            })

            # Check if all required objectives are now complete
            if mission.all_required_complete:
                complete_mission(mission.id)
            return True

    return False


# ---------------------------------------------------------------------------
# Tick — auto-check objectives and deadlines
# ---------------------------------------------------------------------------

def tick_missions(
    ship_x: float,
    ship_y: float,
    dt: float,
    *,
    enemy_ids: frozenset[str] | None = None,
    docked_station_id: str | None = None,
) -> None:
    """Advance mission state each tick.

    Checks navigate_to proximity, destroy targets, accept deadlines,
    completion deadlines.

    Args:
        enemy_ids: set of alive enemy IDs (for destroy objective checks).
        docked_station_id: station ID currently docked with (for dock objectives).
    """
    for mission in _missions:
        # Skip terminal states
        if mission.status in ("completed", "failed", "declined", "expired"):
            continue

        # --- Accept deadline (offered missions) ---
        if mission.status == "offered":
            if mission.accept_deadline is not None:
                mission.accept_deadline -= dt
                if mission.accept_deadline <= 0:
                    mission.status = "expired"
                    _pending_mission_events.append({
                        "event": "mission_expired",
                        "mission_id": mission.id,
                        "title": mission.title,
                    })
                    logger.info("Mission expired: %s (%s)", mission.title, mission.id)
            continue  # Don't check objectives on non-active missions

        # --- Active missions: check objectives ---
        if mission.is_active:
            # Completion deadline
            if mission.completion_deadline is not None:
                mission.completion_deadline -= dt
                if mission.completion_deadline <= 0:
                    fail_mission(mission.id, "Time expired")
                    continue

            # Auto-check navigate_to objectives
            _check_navigate_objectives(mission, ship_x, ship_y)

            # Auto-check survive objectives
            _check_survive_objectives(mission)

            # Auto-check destroy objectives (target absent from alive enemies)
            if enemy_ids is not None:
                _check_destroy_objectives(mission, enemy_ids)

            # Auto-check dock objectives
            if docked_station_id is not None:
                _check_dock_objectives(mission, docked_station_id)


def _check_navigate_objectives(mission: DynamicMission, ship_x: float, ship_y: float) -> None:
    """Complete navigate_to objectives when ship is close enough."""
    for obj in mission.objectives:
        if obj.completed or obj.objective_type != "navigate_to":
            continue
        if obj.target_position is None:
            continue

        tx, ty = obj.target_position
        dist = ((ship_x - tx) ** 2 + (ship_y - ty) ** 2) ** 0.5
        if dist <= NAVIGATE_COMPLETION_RADIUS:
            complete_objective(mission.id, obj.id)


def _check_survive_objectives(mission: DynamicMission) -> None:
    """Complete survive objectives when target tick reached."""
    for obj in mission.objectives:
        if obj.completed or obj.objective_type != "survive":
            continue
        if obj.target_tick is not None and _tick >= obj.target_tick:
            complete_objective(mission.id, obj.id)


def _check_destroy_objectives(mission: DynamicMission, alive_enemy_ids: frozenset[str]) -> None:
    """Complete destroy objectives when target is no longer alive."""
    for obj in mission.objectives:
        if obj.completed or obj.objective_type != "destroy":
            continue
        if obj.target_id and obj.target_id not in alive_enemy_ids:
            complete_objective(mission.id, obj.id)


def _check_dock_objectives(mission: DynamicMission, docked_station_id: str) -> None:
    """Complete dock objectives when docked with target station."""
    for obj in mission.objectives:
        if obj.completed or obj.objective_type != "dock":
            continue
        if obj.target_id and obj.target_id == docked_station_id:
            complete_objective(mission.id, obj.id)


# ---------------------------------------------------------------------------
# Notification-based objective completion
# ---------------------------------------------------------------------------

def notify_scan_completed(entity_id: str) -> None:
    """Called when a science scan finishes on an entity.

    Completes any active 'scan' objective targeting that entity.
    """
    for mission in _missions:
        if not mission.is_active:
            continue
        for obj in mission.objectives:
            if obj.completed or obj.objective_type != "scan":
                continue
            if obj.target_id == entity_id:
                complete_objective(mission.id, obj.id)


def notify_signal_responded(signal_id: str) -> None:
    """Called when a diplomatic response is sent to a signal.

    Completes any active 'negotiate' objective targeting that signal.
    """
    for mission in _missions:
        if not mission.is_active:
            continue
        for obj in mission.objectives:
            if obj.completed or obj.objective_type != "negotiate":
                continue
            if obj.target_id == signal_id:
                complete_objective(mission.id, obj.id)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_mission(mission_id: str) -> DynamicMission | None:
    """Find a mission by ID."""
    for m in _missions:
        if m.id == mission_id:
            return m
    return None


def get_missions() -> list[DynamicMission]:
    """Return all missions."""
    return list(_missions)


def get_active_missions() -> list[DynamicMission]:
    """Return missions with status accepted or active."""
    return [m for m in _missions if m.is_active]


def get_offered_missions() -> list[DynamicMission]:
    """Return missions with status offered."""
    return [m for m in _missions if m.status == "offered"]


def get_completed_mission_ids() -> list[str]:
    """Return IDs of completed missions (for debrief)."""
    return list(_completed_mission_ids)


def get_failed_mission_ids() -> list[str]:
    """Return IDs of failed missions (for debrief)."""
    return list(_failed_mission_ids)


def get_missions_for_broadcast() -> list[dict]:
    """Return all non-terminal missions as dicts for captain broadcast."""
    return [
        m.to_dict() for m in _missions
        if m.status in ("offered", "accepted", "active")
    ]


# ---------------------------------------------------------------------------
# Event queue
# ---------------------------------------------------------------------------

def pop_pending_mission_events() -> list[dict]:
    """Drain and return pending mission events."""
    events = list(_pending_mission_events)
    _pending_mission_events.clear()
    return events


# ---------------------------------------------------------------------------
# Reward application helpers
# ---------------------------------------------------------------------------

def apply_rewards(rewards: MissionRewards, faction_standings: dict[str, Any]) -> dict:
    """Apply mission rewards to game state. Returns summary dict.

    faction_standings: reference to the comms faction standing dict.
    Standing changes are applied directly; other rewards are returned for
    the caller (game_loop) to apply to the appropriate systems.
    """
    summary: dict[str, Any] = {}

    # Faction standing changes
    if rewards.faction_standing:
        for faction_id, amount in rewards.faction_standing.items():
            summary.setdefault("standing_changes", []).append({
                "faction": faction_id,
                "amount": amount,
            })

    # Supplies
    if rewards.supplies:
        summary["supplies"] = dict(rewards.supplies)

    # Crew
    if rewards.crew > 0:
        summary["crew_gained"] = rewards.crew

    # Intel
    if rewards.intel:
        summary["intel"] = list(rewards.intel)

    # Reputation
    if rewards.reputation > 0:
        summary["reputation"] = rewards.reputation

    return summary


# ---------------------------------------------------------------------------
# Serialise / Deserialise
# ---------------------------------------------------------------------------

def serialise() -> dict:
    """Serialise dynamic mission state for save system."""
    return {
        "missions": [m.to_dict() for m in _missions],
        "mission_counter": _mission_counter,
        "completed_ids": list(_completed_mission_ids),
        "failed_ids": list(_failed_mission_ids),
        # Include _is_trap in save data (not broadcast to clients)
        "trap_flags": {m.id: m._is_trap for m in _missions if m._is_trap},
    }


def deserialise(data: dict) -> None:
    """Restore dynamic mission state from save."""
    global _mission_counter

    _missions.clear()
    _pending_mission_events.clear()
    _completed_mission_ids.clear()
    _failed_mission_ids.clear()

    trap_flags = data.get("trap_flags", {})
    for md in data.get("missions", []):
        mission = DynamicMission.from_dict(md)
        # Restore trap flag from save
        if mission.id in trap_flags:
            mission._is_trap = trap_flags[mission.id]
        _missions.append(mission)

    _mission_counter = data.get("mission_counter", 0)
    _completed_mission_ids.extend(data.get("completed_ids", []))
    _failed_mission_ids.extend(data.get("failed_ids", []))
