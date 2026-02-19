"""Tests for the crew.notify → crew.notification broadcast pipeline.

crew.notify:  { message: str, from_role: str }  (sent by any station)
crew.notification: { message, from_role }        (broadcast to all)

The handler lives in game_loop._drain_queue — synchronous, returns events
which the loop broadcasts at end of tick.
"""
from __future__ import annotations

import asyncio

import pytest

from server import game_loop
from server.models.messages import CrewNotifyPayload, Message
from server.models.ship import Ship
from server.models.world import World


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockManager:
    def __init__(self) -> None:
        self.broadcasts: list[Message] = []

    async def broadcast(self, msg: Message) -> None:
        self.broadcasts.append(msg)

    async def broadcast_to_roles(self, roles: list[str], msg: Message) -> None:
        self.broadcasts.append(msg)


def fresh() -> tuple[MockManager, World, asyncio.Queue]:  # type: ignore[type-arg]
    manager = MockManager()
    world = World()
    queue: asyncio.Queue = asyncio.Queue()  # type: ignore[type-arg]
    game_loop.init(world, manager, queue)
    return manager, world, queue


@pytest.fixture(autouse=True)
async def stop_loop_after_test():
    yield
    await game_loop.stop()


# ---------------------------------------------------------------------------
# crew.notify — dispatch to event list
# ---------------------------------------------------------------------------


async def test_crew_notify_returns_notification_event():
    _, _, queue = fresh()
    ship = Ship()
    await queue.put(("crew.notify", CrewNotifyPayload(message="SHIELDS CRITICAL")))
    events = game_loop._drain_queue(ship)
    assert any(t == "crew.notification" for t, _ in events)


async def test_crew_notify_event_contains_message():
    _, _, queue = fresh()
    ship = Ship()
    await queue.put(("crew.notify", CrewNotifyPayload(message="BRACE FOR IMPACT")))
    events = game_loop._drain_queue(ship)
    notif = next((d for t, d in events if t == "crew.notification"), None)
    assert notif is not None
    assert notif["message"] == "BRACE FOR IMPACT"


async def test_crew_notify_event_contains_from_role():
    _, _, queue = fresh()
    ship = Ship()
    await queue.put(("crew.notify", CrewNotifyPayload(message="standby", from_role="captain")))
    events = game_loop._drain_queue(ship)
    notif = next((d for t, d in events if t == "crew.notification"), None)
    assert notif is not None
    assert notif["from_role"] == "captain"


async def test_crew_notify_default_from_role_is_crew():
    _, _, queue = fresh()
    ship = Ship()
    await queue.put(("crew.notify", CrewNotifyPayload(message="test")))
    events = game_loop._drain_queue(ship)
    notif = next((d for t, d in events if t == "crew.notification"), None)
    assert notif is not None
    assert notif["from_role"] == "crew"


async def test_crew_notify_whitespace_only_message_ignored():
    _, _, queue = fresh()
    ship = Ship()
    await queue.put(("crew.notify", CrewNotifyPayload(message="   ")))
    events = game_loop._drain_queue(ship)
    assert not any(t == "crew.notification" for t, _ in events)


async def test_crew_notify_long_message_truncated_to_120():
    _, _, queue = fresh()
    ship = Ship()
    long_msg = "X" * 200
    await queue.put(("crew.notify", CrewNotifyPayload(message=long_msg)))
    events = game_loop._drain_queue(ship)
    notif = next((d for t, d in events if t == "crew.notification"), None)
    assert notif is not None
    assert len(notif["message"]) == 120


async def test_crew_notify_strips_leading_trailing_whitespace():
    _, _, queue = fresh()
    ship = Ship()
    await queue.put(("crew.notify", CrewNotifyPayload(message="  ALL STOP  ")))
    events = game_loop._drain_queue(ship)
    notif = next((d for t, d in events if t == "crew.notification"), None)
    assert notif is not None
    assert notif["message"] == "ALL STOP"


async def test_crew_notify_multiple_messages_all_emitted():
    _, _, queue = fresh()
    ship = Ship()
    await queue.put(("crew.notify", CrewNotifyPayload(message="msg one", from_role="helm")))
    await queue.put(("crew.notify", CrewNotifyPayload(message="msg two", from_role="weapons")))
    events = game_loop._drain_queue(ship)
    notifs = [(t, d) for t, d in events if t == "crew.notification"]
    assert len(notifs) == 2
    messages = {d["message"] for _, d in notifs}
    assert messages == {"msg one", "msg two"}
