"""Tests for the engineering station handler and game loop engineering integration.

Covers:
  Handler:    validate payload, reject unknown systems, reject out-of-range levels,
              enqueue valid commands, return error.validation on bad input.
  Drain queue: apply set_power (with and without budget clamping), set_repair.
  Engineering tick: repair healing per tick, overclock damage (mocked random),
                    edge cases (no focus, full health, offline system).
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from server import engineering, game_loop
from server.models.messages import (
    EngineeringSetPowerPayload,
    EngineeringSetRepairPayload,
    Message,
)
from server.models.world import World


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


class MockManager:
    """Minimal broadcast sink for game-loop tests."""

    def __init__(self) -> None:
        self.broadcasts: list[Message] = []

    async def broadcast(self, message: Message) -> None:
        self.broadcasts.append(message)

    async def broadcast_to_roles(self, roles: list[str], message: Message) -> None:
        self.broadcasts.append(message)


class MockSender:
    """Minimal send sink for handler tests."""

    def __init__(self) -> None:
        self.sent: list[Message] = []

    async def send(self, connection_id: str, message: Message) -> None:
        self.sent.append(message)


def fresh_handler() -> tuple[MockSender, asyncio.Queue]:  # type: ignore[type-arg]
    """Reset engineering handler state and return fresh sender + queue."""
    sender = MockSender()
    queue: asyncio.Queue = asyncio.Queue()  # type: ignore[type-arg]
    engineering.init(sender, queue)
    return sender, queue


def fresh_loop() -> tuple[MockManager, World, asyncio.Queue]:  # type: ignore[type-arg]
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
# Handler — engineering.set_power
# ---------------------------------------------------------------------------


async def test_handle_set_power_valid_enqueues():
    _, queue = fresh_handler()
    msg = Message.build("engineering.set_power", {"system": "engines", "level": 120.0})
    await engineering.handle_engineering_message("conn1", msg)
    assert queue.qsize() == 1
    msg_type, payload = await queue.get()
    assert msg_type == "engineering.set_power"
    assert payload.system == "engines"
    assert payload.level == 120.0


async def test_handle_set_power_unknown_system_returns_error():
    sender, queue = fresh_handler()
    msg = Message.build("engineering.set_power", {"system": "warpcore", "level": 100.0})
    await engineering.handle_engineering_message("conn1", msg)
    assert queue.empty()
    assert len(sender.sent) == 1
    assert sender.sent[0].type == "error.validation"


async def test_handle_set_power_level_too_high_returns_error():
    sender, queue = fresh_handler()
    msg = Message.build("engineering.set_power", {"system": "engines", "level": 200.0})
    await engineering.handle_engineering_message("conn1", msg)
    assert queue.empty()
    assert sender.sent[0].type == "error.validation"


async def test_handle_set_power_level_negative_returns_error():
    sender, queue = fresh_handler()
    msg = Message.build("engineering.set_power", {"system": "engines", "level": -1.0})
    await engineering.handle_engineering_message("conn1", msg)
    assert queue.empty()
    assert sender.sent[0].type == "error.validation"


# ---------------------------------------------------------------------------
# Handler — engineering.set_repair
# ---------------------------------------------------------------------------


async def test_handle_set_repair_valid_enqueues():
    _, queue = fresh_handler()
    msg = Message.build("engineering.set_repair", {"system": "shields"})
    await engineering.handle_engineering_message("conn1", msg)
    assert queue.qsize() == 1
    msg_type, payload = await queue.get()
    assert msg_type == "engineering.set_repair"
    assert payload.system == "shields"


async def test_handle_set_repair_unknown_system_returns_error():
    sender, queue = fresh_handler()
    msg = Message.build("engineering.set_repair", {"system": "hyperdrive"})
    await engineering.handle_engineering_message("conn1", msg)
    assert queue.empty()
    assert sender.sent[0].type == "error.validation"


# ---------------------------------------------------------------------------
# _drain_queue — engineering inputs
# ---------------------------------------------------------------------------


async def test_drain_queue_applies_set_power():
    _, world, queue = fresh_loop()
    ship = world.ship
    # Reduce a different system to create headroom; 7 systems at 100 = 700 budget.
    # beams=50, others (incl. flight_deck) at 100 → other_total for engines = 550 → headroom: 150
    ship.systems["beams"].power = 50.0
    await queue.put(("engineering.set_power", EngineeringSetPowerPayload(system="engines", level=130.0)))
    game_loop._drain_queue(ship)
    assert ship.systems["engines"].power == 130.0


async def test_drain_queue_clamps_power_to_budget():
    _, world, queue = fresh_loop()
    ship = world.ship
    # All 7 systems at 100 = 700 total. No headroom for engines to exceed 100.
    await queue.put(("engineering.set_power", EngineeringSetPowerPayload(system="engines", level=150.0)))
    game_loop._drain_queue(ship)
    # other_total = 600. available = 700 - 600 = 100. 150 → clamped to 100.
    assert ship.systems["engines"].power == 100.0


async def test_drain_queue_does_not_clamp_within_budget():
    _, world, queue = fresh_loop()
    ship = world.ship
    # engines=50, 5 others at 100, flight_deck=100 → other_total for beams = 550 → headroom: 150
    ship.systems["engines"].power = 50.0
    await queue.put(("engineering.set_power", EngineeringSetPowerPayload(system="beams", level=130.0)))
    game_loop._drain_queue(ship)
    assert ship.systems["beams"].power == 130.0


async def test_drain_queue_set_repair_assigns_focus():
    _, world, queue = fresh_loop()
    ship = world.ship
    await queue.put(("engineering.set_repair", EngineeringSetRepairPayload(system="shields")))
    game_loop._drain_queue(ship)
    assert ship.repair_focus == "shields"


# ---------------------------------------------------------------------------
# _apply_engineering — repair mechanic
# ---------------------------------------------------------------------------


async def test_apply_engineering_heals_focused_system():
    _, world, _ = fresh_loop()
    ship = world.ship
    ship.systems["shields"].health = 60.0
    ship.repair_focus = "shields"
    game_loop._apply_engineering(ship)
    assert ship.systems["shields"].health == pytest.approx(61.0)  # +REPAIR_HP_PER_TICK


async def test_apply_engineering_does_not_exceed_100_health():
    _, world, _ = fresh_loop()
    ship = world.ship
    ship.systems["shields"].health = 99.5
    ship.repair_focus = "shields"
    game_loop._apply_engineering(ship)
    assert ship.systems["shields"].health == 100.0


async def test_apply_engineering_no_heal_without_focus():
    _, world, _ = fresh_loop()
    ship = world.ship
    ship.systems["shields"].health = 60.0
    ship.repair_focus = None
    game_loop._apply_engineering(ship)
    assert ship.systems["shields"].health == 60.0


async def test_apply_engineering_no_heal_at_full_health():
    _, world, _ = fresh_loop()
    ship = world.ship
    ship.systems["shields"].health = 100.0
    ship.repair_focus = "shields"
    game_loop._apply_engineering(ship)
    assert ship.systems["shields"].health == 100.0


# ---------------------------------------------------------------------------
# _apply_engineering — overclock damage
# ---------------------------------------------------------------------------


async def test_apply_engineering_overclock_damages_on_trigger():
    _, world, _ = fresh_loop()
    ship = world.ship
    ship.systems["engines"].power = 150.0  # overclocked
    with patch("server.game_loop.random") as mock_rng:
        mock_rng.random.return_value = 0.0  # always below OVERCLOCK_DAMAGE_CHANCE
        damaged = game_loop._apply_engineering(ship)
    expected_health = 100.0 - game_loop.OVERCLOCK_DAMAGE_HP
    assert ship.systems["engines"].health == pytest.approx(expected_health)
    assert damaged == [("engines", expected_health)]


async def test_apply_engineering_overclock_no_damage_when_lucky():
    _, world, _ = fresh_loop()
    ship = world.ship
    ship.systems["engines"].power = 150.0
    with patch("server.game_loop.random") as mock_rng:
        mock_rng.random.return_value = 0.99  # above OVERCLOCK_DAMAGE_CHANCE (0.10)
        damaged = game_loop._apply_engineering(ship)
    assert ship.systems["engines"].health == 100.0
    assert damaged == []


async def test_apply_engineering_no_overclock_damage_at_threshold():
    _, world, _ = fresh_loop()
    ship = world.ship
    ship.systems["engines"].power = game_loop.OVERCLOCK_THRESHOLD  # exactly at threshold, not above
    with patch("server.game_loop.random") as mock_rng:
        mock_rng.random.return_value = 0.0
        damaged = game_loop._apply_engineering(ship)
    assert ship.systems["engines"].health == 100.0
    assert damaged == []


async def test_apply_engineering_overclock_skips_offline_system():
    _, world, _ = fresh_loop()
    ship = world.ship
    ship.systems["engines"].power = 150.0
    ship.systems["engines"].health = 0.0  # already offline
    with patch("server.game_loop.random") as mock_rng:
        mock_rng.random.return_value = 0.0
        damaged = game_loop._apply_engineering(ship)
    assert ship.systems["engines"].health == 0.0  # unchanged
    assert damaged == []
