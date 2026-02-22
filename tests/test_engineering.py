"""Tests for the engineering station handler and game loop engineering integration.

Covers:
  Handler:    validate payload, reject unknown systems, reject out-of-range levels,
              enqueue valid commands, return error.validation on bad input.
  Drain queue: apply set_power (with and without budget clamping), set_repair,
               dispatch_team, recall_team, set_battery_mode, start_reroute,
               cancel_repair_order.
  Engineering tick: repair healing per tick, overclock damage (mocked random),
                    edge cases (no focus, full health, offline system).
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from server import engineering, game_loop
import server.game_loop_engineering as gle
from server.models.messages import (
    EngineeringCancelRepairOrderPayload,
    EngineeringDispatchTeamPayload,
    EngineeringRecallTeamPayload,
    EngineeringRequestEscortPayload,
    EngineeringSetBatteryModePayload,
    EngineeringSetPowerPayload,
    EngineeringSetRepairPayload,
    EngineeringStartReroutePayload,
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
    # Reduce two systems to create headroom; 9 systems × 100 = 900 budget.
    # beams=50, point_defence=50, 7 others at 100 → other_total for engines = 750 → headroom: 150
    ship.systems["beams"].power = 50.0
    ship.systems["point_defence"].power = 50.0
    await queue.put(("engineering.set_power", EngineeringSetPowerPayload(system="engines", level=130.0)))
    game_loop._drain_queue(ship)
    assert ship.systems["engines"].power == 130.0


async def test_drain_queue_clamps_power_to_budget():
    _, world, queue = fresh_loop()
    ship = world.ship
    # All 9 systems at 100 = 900 total. No headroom for engines to exceed 100.
    await queue.put(("engineering.set_power", EngineeringSetPowerPayload(system="engines", level=150.0)))
    game_loop._drain_queue(ship)
    # other_total = 800. available = 900 - 800 = 100. 150 → clamped to 100.
    assert ship.systems["engines"].power == 100.0


async def test_drain_queue_does_not_clamp_within_budget():
    _, world, queue = fresh_loop()
    ship = world.ship
    # engines=50, point_defence=50, 7 others at 100 → other_total for beams = 750 → headroom: 150
    ship.systems["engines"].power = 50.0
    ship.systems["point_defence"].power = 50.0
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


# ---------------------------------------------------------------------------
# _drain_queue — new v0.06.2 engineering message types
# ---------------------------------------------------------------------------


_TEST_CREW_IDS = [f"crew_{i}" for i in range(6)]


def _init_gle_for_test(world: World) -> None:
    """Initialise the gle module with enough crew to form repair teams."""
    gle.reset()
    gle.init(world.ship, crew_member_ids=_TEST_CREW_IDS)


async def test_drain_queue_dispatch_team():
    """engineering.dispatch_team calls gle.dispatch_team."""
    _, world, queue = fresh_loop()
    _init_gle_for_test(world)
    ship = world.ship

    state = gle.build_state(ship)
    teams = state.get("repair_teams", [])
    assert len(teams) > 0, "Expected at least one repair team"
    team = teams[0]

    payload = EngineeringDispatchTeamPayload(team_id=team["id"], system="engines")
    await queue.put(("engineering.dispatch_team", payload))
    game_loop._drain_queue(ship)

    new_state = gle.build_state(ship)
    updated_team = [t for t in new_state["repair_teams"] if t["id"] == team["id"]]
    assert len(updated_team) == 1
    assert updated_team[0]["status"] in ("travelling", "repairing")


async def test_drain_queue_recall_team():
    """engineering.recall_team calls gle.recall_team."""
    _, world, queue = fresh_loop()
    _init_gle_for_test(world)
    ship = world.ship

    state = gle.build_state(ship)
    teams = state.get("repair_teams", [])
    assert len(teams) > 0, "Expected at least one repair team"
    team = teams[0]

    # First dispatch the team
    gle.dispatch_team(team["id"], "engines", ship.interior)
    dispatched = [t for t in gle.build_state(ship)["repair_teams"] if t["id"] == team["id"]][0]
    assert dispatched["status"] != "idle"

    # Now recall via drain_queue
    payload = EngineeringRecallTeamPayload(team_id=team["id"])
    await queue.put(("engineering.recall_team", payload))
    game_loop._drain_queue(ship)

    recalled = [t for t in gle.build_state(ship)["repair_teams"] if t["id"] == team["id"]][0]
    assert recalled["status"] in ("idle", "travelling")


async def test_drain_queue_set_battery_mode():
    """engineering.set_battery_mode calls gle.set_battery_mode."""
    _, world, queue = fresh_loop()
    _init_gle_for_test(world)
    ship = world.ship

    payload = EngineeringSetBatteryModePayload(mode="charging")
    await queue.put(("engineering.set_battery_mode", payload))
    game_loop._drain_queue(ship)

    state = gle.build_state(ship)
    assert state["power_grid"]["battery_mode"] == "charging"


async def test_drain_queue_start_reroute():
    """engineering.start_reroute calls gle.start_reroute."""
    _, world, queue = fresh_loop()
    _init_gle_for_test(world)
    ship = world.ship

    payload = EngineeringStartReroutePayload(target_bus="secondary")
    await queue.put(("engineering.start_reroute", payload))
    game_loop._drain_queue(ship)

    state = gle.build_state(ship)
    assert state["power_grid"]["reroute_active"] is True
    assert state["power_grid"]["reroute_target_bus"] == "secondary"


async def test_drain_queue_cancel_repair_order():
    """engineering.cancel_repair_order calls gle.cancel_repair_order."""
    _, world, queue = fresh_loop()
    _init_gle_for_test(world)
    ship = world.ship

    # Add an order — returns auto-generated order ID
    order_id = gle.add_repair_order("engines")
    assert order_id is not None
    state = gle.build_state(ship)
    order_ids = [o["id"] for o in state.get("repair_orders", [])]
    assert order_id in order_ids

    payload = EngineeringCancelRepairOrderPayload(order_id=order_id)
    await queue.put(("engineering.cancel_repair_order", payload))
    game_loop._drain_queue(ship)

    state = gle.build_state(ship)
    order_ids = [o["id"] for o in state.get("repair_orders", [])]
    assert order_id not in order_ids


async def test_drain_queue_set_power_also_calls_gle():
    """engineering.set_power should update both old system and gle requested power."""
    _, world, queue = fresh_loop()
    _init_gle_for_test(world)
    ship = world.ship

    ship.systems["beams"].power = 50.0
    ship.systems["point_defence"].power = 50.0
    await queue.put(("engineering.set_power", EngineeringSetPowerPayload(system="engines", level=130.0)))
    game_loop._drain_queue(ship)

    # Old system updated
    assert ship.systems["engines"].power == 130.0

    # gle should also have the requested power tracked
    state = gle.build_state(ship)
    assert state["systems"]["engines"]["requested_power"] == 130.0


async def test_handler_dispatch_team_valid_enqueues():
    """Handler should validate and enqueue engineering.dispatch_team."""
    _, queue = fresh_handler()
    msg = Message.build("engineering.dispatch_team", {"team_id": "alpha", "system": "engines"})
    await engineering.handle_engineering_message("conn1", msg)
    assert queue.qsize() == 1
    msg_type, payload = await queue.get()
    assert msg_type == "engineering.dispatch_team"
    assert payload.team_id == "alpha"
    assert payload.system == "engines"


async def test_handler_dispatch_team_invalid_system_returns_error():
    """Handler should reject dispatch_team with unknown system."""
    sender, queue = fresh_handler()
    msg = Message.build("engineering.dispatch_team", {"team_id": "alpha", "system": "warpcore"})
    await engineering.handle_engineering_message("conn1", msg)
    assert queue.empty()
    assert len(sender.sent) == 1
    assert sender.sent[0].type == "error.validation"


async def test_handler_set_battery_mode_valid_enqueues():
    """Handler should validate and enqueue engineering.set_battery_mode."""
    _, queue = fresh_handler()
    msg = Message.build("engineering.set_battery_mode", {"mode": "discharging"})
    await engineering.handle_engineering_message("conn1", msg)
    assert queue.qsize() == 1
    msg_type, payload = await queue.get()
    assert msg_type == "engineering.set_battery_mode"
    assert payload.mode == "discharging"


async def test_handler_set_battery_mode_invalid_returns_error():
    """Handler should reject unknown battery mode."""
    sender, queue = fresh_handler()
    msg = Message.build("engineering.set_battery_mode", {"mode": "turbo"})
    await engineering.handle_engineering_message("conn1", msg)
    assert queue.empty()
    assert sender.sent[0].type == "error.validation"


async def test_handler_start_reroute_valid_enqueues():
    """Handler should validate and enqueue engineering.start_reroute."""
    _, queue = fresh_handler()
    msg = Message.build("engineering.start_reroute", {"target_bus": "primary"})
    await engineering.handle_engineering_message("conn1", msg)
    assert queue.qsize() == 1
    msg_type, payload = await queue.get()
    assert msg_type == "engineering.start_reroute"
    assert payload.target_bus == "primary"


async def test_handler_start_reroute_invalid_bus_returns_error():
    """Handler should reject unknown bus name."""
    sender, queue = fresh_handler()
    msg = Message.build("engineering.start_reroute", {"target_bus": "tertiary"})
    await engineering.handle_engineering_message("conn1", msg)
    assert queue.empty()
    assert sender.sent[0].type == "error.validation"


async def test_handler_recall_team_valid_enqueues():
    """Handler should validate and enqueue engineering.recall_team."""
    _, queue = fresh_handler()
    msg = Message.build("engineering.recall_team", {"team_id": "bravo"})
    await engineering.handle_engineering_message("conn1", msg)
    assert queue.qsize() == 1
    msg_type, payload = await queue.get()
    assert msg_type == "engineering.recall_team"
    assert payload.team_id == "bravo"


async def test_handler_request_escort_valid_enqueues():
    """Handler should validate and enqueue engineering.request_escort."""
    _, queue = fresh_handler()
    msg = Message.build("engineering.request_escort", {"team_id": "alpha"})
    await engineering.handle_engineering_message("conn1", msg)
    assert queue.qsize() == 1
    msg_type, payload = await queue.get()
    assert msg_type == "engineering.request_escort"
    assert payload.team_id == "alpha"


async def test_handler_cancel_repair_order_valid_enqueues():
    """Handler should validate and enqueue engineering.cancel_repair_order."""
    _, queue = fresh_handler()
    msg = Message.build("engineering.cancel_repair_order", {"order_id": "ord_1"})
    await engineering.handle_engineering_message("conn1", msg)
    assert queue.qsize() == 1
    msg_type, payload = await queue.get()
    assert msg_type == "engineering.cancel_repair_order"
    assert payload.order_id == "ord_1"
