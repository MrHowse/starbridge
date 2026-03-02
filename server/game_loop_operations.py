"""
Operations Station — Game Loop Integration.

The crew's analyst and coordinator. Processes data from Science and other
stations into tactical intelligence, and pushes concrete bonuses to Weapons,
Helm, Flight Ops, and other stations.

This module replaces the old Tactical Officer (game_loop_tactical.py).
Operations is a clean-slate redesign — no legacy Tactical code carried over.

Broadcasts emitted each tick:
  operations.state → ["operations"]  full state payload
  (additional broadcasts added in A.2–A.5 sections)

Constants tuned for 10 Hz game loop (TICK_DT = 0.1 s).
"""
from __future__ import annotations

from server.models.ship import Ship
from server.models.world import World

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_pending_broadcasts: list[tuple[list[str], dict]] = []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset() -> None:
    """Reset all operations state. Called at game start."""
    global _pending_broadcasts
    _pending_broadcasts = []


def tick(world: World, ship: Ship, dt: float) -> None:
    """Advance operations logic by one tick."""
    # Placeholder — A.2–A.5 will add assessment timers, coordination cooldowns, etc.
    pass


def pop_pending_broadcasts() -> list[tuple[list[str], dict]]:
    """Return and clear pending broadcasts."""
    result = list(_pending_broadcasts)
    _pending_broadcasts.clear()
    return result


def build_state(world: World, ship: Ship) -> dict:
    """Serialise full operations state for broadcast to the operations station."""
    # Placeholder — A.2–A.5 will populate assessments, bonuses, mission tracking, etc.
    return {
        "assessments": {},
        "coordination_bonuses": {},
        "mission_tracking": [],
        "feed_events": [],
    }


def serialise() -> dict:
    """Serialise operations state for save system."""
    return {}


def deserialise(data: dict) -> None:
    """Restore operations state from save data."""
    reset()
    # Future: restore assessment, coordination, and mission state from data.
