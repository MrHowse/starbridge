"""Tests for the game loop module.

Covers: init(), start(), stop(), _drain_queue(), _build_ship_state().

The tests that actually run the loop use asyncio.sleep to wait for ticks to
fire.  At 10 Hz (TICK_DT = 0.1 s) a 0.15 s sleep guarantees at least one
tick; 0.25 s guarantees at least two.  These tests add ~0.4 s to the suite.
"""
from __future__ import annotations

import asyncio

import pytest

from server import game_loop
from server.models.messages import (
    HelmSetHeadingPayload,
    HelmSetThrottlePayload,
    Message,
)
from server.models.ship import Ship
from server.models.world import World


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockManager:
    """Minimal broadcast sink for game-loop tests."""

    def __init__(self) -> None:
        self.broadcasts: list[Message] = []

    async def broadcast(self, message: Message) -> None:
        self.broadcasts.append(message)

    async def broadcast_to_roles(self, roles: list[str], message: Message) -> None:
        self.broadcasts.append(message)


def fresh() -> tuple[MockManager, World, asyncio.Queue]:  # type: ignore[type-arg]
    """Reset game_loop state with fresh dependencies and return them."""
    manager = MockManager()
    world = World()
    queue: asyncio.Queue = asyncio.Queue()  # type: ignore[type-arg]
    game_loop.init(world, manager, queue)
    return manager, world, queue


@pytest.fixture(autouse=True)
async def stop_loop_after_test():
    """Ensure the game loop is always stopped between tests."""
    yield
    await game_loop.stop()


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


async def test_init_stores_world():
    _, world, _ = fresh()
    assert game_loop._world is world


async def test_init_stores_manager():
    manager, _, _ = fresh()
    assert game_loop._manager is manager


async def test_init_stores_queue():
    _, _, queue = fresh()
    assert game_loop._queue is queue


# ---------------------------------------------------------------------------
# start / stop lifecycle
# ---------------------------------------------------------------------------


async def test_start_creates_running_task():
    fresh()
    await game_loop.start("sandbox")
    assert game_loop._task is not None
    assert not game_loop._task.done()


async def test_stop_clears_task():
    fresh()
    await game_loop.start("sandbox")
    await game_loop.stop()
    assert game_loop._task is None


async def test_stop_when_not_running_does_not_raise():
    fresh()
    await game_loop.stop()  # _task is None — must not raise


async def test_start_when_already_running_replaces_task():
    fresh()
    await game_loop.start("sandbox")
    task_first = game_loop._task

    await game_loop.start("sandbox")
    task_second = game_loop._task

    assert task_first is not task_second
    assert task_first.done()
    assert not task_second.done()


async def test_start_resets_tick_count():
    fresh()
    await game_loop.start("sandbox")
    await asyncio.sleep(0.15)  # let a tick fire so _tick_count > 0
    await game_loop.stop()

    fresh()
    await game_loop.start("sandbox")
    # After restart tick count starts from 0 again.
    assert game_loop._tick_count == 0 or game_loop._tick_count == 1
    # (May have already fired one tick before we check — that's fine.)


# ---------------------------------------------------------------------------
# Loop behaviour — at least one tick fires
# ---------------------------------------------------------------------------


async def test_loop_broadcasts_ship_state():
    manager, _, _ = fresh()
    await game_loop.start("sandbox")
    await asyncio.sleep(0.15)  # 10 Hz → at least 1 tick in 150 ms
    await game_loop.stop()

    assert len(manager.broadcasts) >= 1
    assert manager.broadcasts[0].type == "ship.state"


async def test_loop_increments_tick_count():
    fresh()
    await game_loop.start("sandbox")
    await asyncio.sleep(0.25)  # at least 2 ticks at 10 Hz
    await game_loop.stop()

    assert game_loop._tick_count >= 2


async def test_loop_sets_tick_on_broadcast():
    manager, _, _ = fresh()
    await game_loop.start("sandbox")
    await asyncio.sleep(0.15)
    await game_loop.stop()

    assert manager.broadcasts[0].tick == 1


# ---------------------------------------------------------------------------
# _drain_queue
# ---------------------------------------------------------------------------


async def test_drain_queue_applies_set_heading():
    _, _, queue = fresh()
    ship = Ship()
    await queue.put(("helm.set_heading", HelmSetHeadingPayload(heading=90.0)))
    game_loop._drain_queue(ship)
    assert ship.target_heading == 90.0


async def test_drain_queue_applies_set_throttle():
    _, _, queue = fresh()
    ship = Ship()
    await queue.put(("helm.set_throttle", HelmSetThrottlePayload(throttle=75.0)))
    game_loop._drain_queue(ship)
    assert ship.throttle == 75.0


async def test_drain_queue_processes_all_items():
    _, _, queue = fresh()
    ship = Ship()
    for heading in (45.0, 90.0, 135.0):
        await queue.put(("helm.set_heading", HelmSetHeadingPayload(heading=heading)))
    game_loop._drain_queue(ship)
    # Last value wins.
    assert ship.target_heading == 135.0
    assert queue.empty()


async def test_drain_queue_empty_does_not_raise():
    _, _, queue = fresh()
    ship = Ship()
    game_loop._drain_queue(ship)  # empty queue — must not raise


async def test_drain_queue_leaves_ship_unchanged_when_empty():
    _, _, queue = fresh()
    ship = Ship()
    game_loop._drain_queue(ship)
    assert ship.target_heading == 0.0
    assert ship.throttle == 0.0


# ---------------------------------------------------------------------------
# _build_ship_state
# ---------------------------------------------------------------------------


def test_build_ship_state_type():
    ship = Ship()
    msg = game_loop._build_ship_state(ship, tick=1)
    assert msg.type == "ship.state"


def test_build_ship_state_tick_field():
    ship = Ship()
    msg = game_loop._build_ship_state(ship, tick=42)
    assert msg.tick == 42


def test_build_ship_state_has_position():
    ship = Ship()
    msg = game_loop._build_ship_state(ship, tick=1)
    assert "position" in msg.payload
    assert "x" in msg.payload["position"]
    assert "y" in msg.payload["position"]


def test_build_ship_state_position_values():
    ship = Ship()
    ship.x = 25_000.0
    ship.y = 75_000.0
    msg = game_loop._build_ship_state(ship, tick=1)
    assert msg.payload["position"]["x"] == 25_000.0
    assert msg.payload["position"]["y"] == 75_000.0


def test_build_ship_state_heading():
    ship = Ship()
    ship.heading = 270.0
    msg = game_loop._build_ship_state(ship, tick=1)
    assert msg.payload["heading"] == 270.0


def test_build_ship_state_velocity():
    ship = Ship()
    ship.velocity = 123.45
    msg = game_loop._build_ship_state(ship, tick=1)
    assert msg.payload["velocity"] == round(123.45, 2)


def test_build_ship_state_throttle():
    ship = Ship()
    ship.throttle = 80.0
    msg = game_loop._build_ship_state(ship, tick=1)
    assert msg.payload["throttle"] == 80.0


def test_build_ship_state_has_nine_systems():
    ship = Ship()
    msg = game_loop._build_ship_state(ship, tick=1)
    expected = {"engines", "beams", "torpedoes", "shields", "sensors", "manoeuvring", "flight_deck", "ecm_suite", "point_defence"}
    assert set(msg.payload["systems"].keys()) == expected


def test_build_ship_state_system_fields():
    ship = Ship()
    msg = game_loop._build_ship_state(ship, tick=1)
    engines = msg.payload["systems"]["engines"]
    assert "power" in engines
    assert "health" in engines
    assert "efficiency" in engines


def test_build_ship_state_hull():
    ship = Ship()
    msg = game_loop._build_ship_state(ship, tick=1)
    assert msg.payload["hull"] == 100.0


def test_build_ship_state_shields():
    ship = Ship()
    msg = game_loop._build_ship_state(ship, tick=1)
    assert "shields" in msg.payload
    assert msg.payload["shields"]["front"] == 100.0
    assert msg.payload["shields"]["rear"] == 100.0


def test_build_ship_state_alert_level_present():
    ship = Ship()
    msg = game_loop._build_ship_state(ship, tick=1)
    assert "alert_level" in msg.payload
