"""
Game Loop — Fixed Timestep Simulation.

Runs as an asyncio background task at TICK_RATE Hz. Each tick:
  1. Drains the input queue and applies inputs to the ship.
  2. Runs the physics simulation step.
  3. Applies engineering effects (repair healing, overclock damage).
  4. Broadcasts ship.state to all connected clients.
  5. Broadcasts ship.system_damaged for any overclock damage events.

Call init(world, manager, queue) once from main.py on startup.
Call start(mission_id) when the host launches a game.
Call stop() to halt the loop (game over, server shutdown).
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Protocol

from pydantic import BaseModel

from server.models.messages import (
    EngineeringSetPowerPayload,
    EngineeringSetRepairPayload,
    HelmSetHeadingPayload,
    HelmSetThrottlePayload,
    Message,
)
from server.models.ship import Ship
from server.models.world import World
from server.systems import physics

logger = logging.getLogger("starbridge.game_loop")

TICK_RATE: int = 10             # simulation ticks per second
TICK_DT: float = 1.0 / TICK_RATE  # seconds per tick (0.1 s)

# ---------------------------------------------------------------------------
# Engineering constants — tunable for gameplay feel
# ---------------------------------------------------------------------------

POWER_BUDGET: float = 600.0           # Total available power (6 systems × 100%)
OVERCLOCK_THRESHOLD: float = 100.0    # Power above this risks damage each tick
OVERCLOCK_DAMAGE_CHANCE: float = 0.10 # Probability of damage per tick while overclocked
OVERCLOCK_DAMAGE_HP: float = 3.0      # HP deducted per overclock damage event
REPAIR_HP_PER_TICK: float = 1.0       # HP restored per tick to the focused system


# ---------------------------------------------------------------------------
# Manager protocol — same decoupling pattern as lobby.py
# ---------------------------------------------------------------------------


class _ManagerProtocol(Protocol):
    async def broadcast(self, message: Message) -> None: ...


# ---------------------------------------------------------------------------
# Module-level state (set by init)
# ---------------------------------------------------------------------------

_world: World | None = None
_manager: _ManagerProtocol | None = None
_queue: asyncio.Queue[tuple[str, BaseModel]] | None = None

_task: asyncio.Task[None] | None = None
_tick_count: int = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init(
    world: World,
    manager: _ManagerProtocol,
    queue: asyncio.Queue[tuple[str, BaseModel]],
) -> None:
    """Inject dependencies. Call once from main.py before starting the game."""
    global _world, _manager, _queue
    _world = world
    _manager = manager
    _queue = queue


async def start(mission_id: str) -> None:
    """Begin the game loop. Called when the host launches a game."""
    global _task, _tick_count
    _tick_count = 0
    if _task is not None and not _task.done():
        logger.warning("Game loop already running — stopping before restart")
        await stop()
    _task = asyncio.create_task(_loop(), name="game_loop")
    logger.info("Game loop started (mission: %s, %d Hz)", mission_id, TICK_RATE)


async def stop() -> None:
    """Stop the game loop task."""
    global _task
    if _task is not None and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
    logger.info("Game loop stopped")


# ---------------------------------------------------------------------------
# Loop internals
# ---------------------------------------------------------------------------


async def _loop() -> None:
    global _tick_count
    assert _world is not None and _manager is not None and _queue is not None

    while True:
        tick_start = asyncio.get_event_loop().time()

        # 1. Apply all queued inputs before the physics step.
        _drain_queue(_world.ship)

        # 2. Physics step.
        physics.tick(_world.ship, TICK_DT, _world.width, _world.height)
        _tick_count += 1

        # 3. Engineering effects: repair healing and overclock damage.
        damaged_systems = _apply_engineering(_world.ship)

        # 4. Broadcast ship state.
        # TODO (Phase 5): role-filter this broadcast — not all roles need all
        #                 ship data. Captain gets full state; others get subsets.
        await _manager.broadcast(_build_ship_state(_world.ship, _tick_count))

        # 5. Broadcast damage events produced by overclock this tick.
        for system_name, new_health in damaged_systems:
            await _manager.broadcast(
                Message.build(
                    "ship.system_damaged",
                    {"system": system_name, "new_health": new_health, "cause": "overclock"},
                )
            )

        # 6. Sleep for the remainder of the tick budget.
        elapsed = asyncio.get_event_loop().time() - tick_start
        await asyncio.sleep(max(0.0, TICK_DT - elapsed))


def _drain_queue(ship: Ship) -> None:
    """Apply all pending input messages to the ship before physics runs."""
    assert _queue is not None
    while True:
        try:
            msg_type, payload = _queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        if msg_type == "helm.set_heading" and isinstance(payload, HelmSetHeadingPayload):
            ship.target_heading = payload.heading
        elif msg_type == "helm.set_throttle" and isinstance(payload, HelmSetThrottlePayload):
            ship.throttle = payload.throttle
        elif msg_type == "engineering.set_power" and isinstance(payload, EngineeringSetPowerPayload):
            _apply_power(ship, payload.system, payload.level)
        elif msg_type == "engineering.set_repair" and isinstance(payload, EngineeringSetRepairPayload):
            ship.repair_focus = payload.system
        else:
            logger.warning("Unrecognised queued input type: %s", msg_type)


def _apply_power(ship: Ship, system_name: str, requested: float) -> None:
    """Set a system's power level, clamped to the remaining budget.

    If the requested level would push total power above POWER_BUDGET, the
    level is silently reduced to whatever headroom remains. The client UI
    shows this constraint in real time so the clamp is expected rather than
    surprising.
    """
    sys_obj = ship.systems[system_name]
    other_total = sum(s.power for name, s in ship.systems.items() if name != system_name)
    available = POWER_BUDGET - other_total
    sys_obj.power = max(0.0, min(requested, available))


def _apply_engineering(ship: Ship) -> list[tuple[str, float]]:
    """Apply repair healing and overclock damage for this tick.

    Returns a list of (system_name, new_health) tuples for each system that
    took overclock damage this tick. The caller broadcasts ship.system_damaged
    for each entry.
    """
    damaged: list[tuple[str, float]] = []

    # Repair: heal the focused system by REPAIR_HP_PER_TICK, capped at 100.
    if ship.repair_focus is not None:
        sys_obj = ship.systems.get(ship.repair_focus)
        if sys_obj is not None and sys_obj.health < 100.0:
            sys_obj.health = min(100.0, sys_obj.health + REPAIR_HP_PER_TICK)

    # Overclock damage: each overclocked system has a chance to take damage.
    for name, sys_obj in ship.systems.items():
        if sys_obj.power > OVERCLOCK_THRESHOLD and sys_obj.health > 0.0:
            if random.random() < OVERCLOCK_DAMAGE_CHANCE:
                sys_obj.health = max(0.0, sys_obj.health - OVERCLOCK_DAMAGE_HP)
                damaged.append((name, sys_obj.health))

    return damaged


def _build_ship_state(ship: Ship, tick: int) -> Message:
    """Serialise the ship into a ship.state envelope ready to broadcast."""
    return Message.build(
        "ship.state",
        {
            "position": {"x": round(ship.x, 1), "y": round(ship.y, 1)},
            "heading": round(ship.heading, 2),
            "velocity": round(ship.velocity, 2),
            "throttle": ship.throttle,
            "hull": ship.hull,
            "shields": {
                "front": ship.shields.front,
                "rear": ship.shields.rear,
            },
            "systems": {
                name: {
                    "power": s.power,
                    "health": s.health,
                    "efficiency": round(s.efficiency, 3),
                }
                for name, s in ship.systems.items()
            },
            "repair_focus": ship.repair_focus,
            "alert_level": "green",  # TODO (Phase 6): use captain's alert level
        },
        tick=tick,
    )
