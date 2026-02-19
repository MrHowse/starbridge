"""Tests for the weapons station handler.

Mirrors the pattern of test_engineering.py:
  - Valid messages enqueue correctly.
  - Invalid payloads return error.validation.
  - Unknown types are logged but not queued and return no error.
"""
from __future__ import annotations

import asyncio

import pytest

from server import weapons
from server.models.messages import Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockSender:
    def __init__(self) -> None:
        self.sent: list[Message] = []

    async def send(self, connection_id: str, message: Message) -> None:
        self.sent.append(message)


def fresh_handler() -> tuple[MockSender, asyncio.Queue]:  # type: ignore[type-arg]
    sender = MockSender()
    queue: asyncio.Queue = asyncio.Queue()  # type: ignore[type-arg]
    weapons.init(sender, queue)
    return sender, queue


# ---------------------------------------------------------------------------
# weapons.select_target
# ---------------------------------------------------------------------------


async def test_select_target_valid_enqueues():
    _, queue = fresh_handler()
    msg = Message.build("weapons.select_target", {"entity_id": "enemy_1"})
    await weapons.handle_weapons_message("conn1", msg)
    assert queue.qsize() == 1
    msg_type, payload = await queue.get()
    assert msg_type == "weapons.select_target"
    assert payload.entity_id == "enemy_1"


async def test_select_target_none_deselects():
    _, queue = fresh_handler()
    msg = Message.build("weapons.select_target", {"entity_id": None})
    await weapons.handle_weapons_message("conn1", msg)
    assert queue.qsize() == 1
    _, payload = await queue.get()
    assert payload.entity_id is None


# ---------------------------------------------------------------------------
# weapons.fire_beams
# ---------------------------------------------------------------------------


async def test_fire_beams_enqueues():
    _, queue = fresh_handler()
    msg = Message.build("weapons.fire_beams", {})
    await weapons.handle_weapons_message("conn1", msg)
    assert queue.qsize() == 1
    msg_type, _ = await queue.get()
    assert msg_type == "weapons.fire_beams"


# ---------------------------------------------------------------------------
# weapons.fire_torpedo
# ---------------------------------------------------------------------------


async def test_fire_torpedo_tube1_enqueues():
    _, queue = fresh_handler()
    msg = Message.build("weapons.fire_torpedo", {"tube": 1})
    await weapons.handle_weapons_message("conn1", msg)
    assert queue.qsize() == 1
    msg_type, payload = await queue.get()
    assert msg_type == "weapons.fire_torpedo"
    assert payload.tube == 1


async def test_fire_torpedo_tube2_enqueues():
    _, queue = fresh_handler()
    msg = Message.build("weapons.fire_torpedo", {"tube": 2})
    await weapons.handle_weapons_message("conn1", msg)
    assert queue.qsize() == 1
    _, payload = await queue.get()
    assert payload.tube == 2


async def test_fire_torpedo_invalid_tube_returns_error():
    sender, queue = fresh_handler()
    msg = Message.build("weapons.fire_torpedo", {"tube": 3})
    await weapons.handle_weapons_message("conn1", msg)
    assert queue.empty()
    assert len(sender.sent) == 1
    assert sender.sent[0].type == "error.validation"


# ---------------------------------------------------------------------------
# weapons.set_shields
# ---------------------------------------------------------------------------


async def test_set_shields_valid_enqueues():
    _, queue = fresh_handler()
    msg = Message.build("weapons.set_shields", {"front": 80.0, "rear": 20.0})
    await weapons.handle_weapons_message("conn1", msg)
    assert queue.qsize() == 1
    msg_type, payload = await queue.get()
    assert msg_type == "weapons.set_shields"
    assert payload.front == 80.0
    assert payload.rear == 20.0


async def test_set_shields_front_out_of_range_returns_error():
    sender, queue = fresh_handler()
    msg = Message.build("weapons.set_shields", {"front": 110.0, "rear": 50.0})
    await weapons.handle_weapons_message("conn1", msg)
    assert queue.empty()
    assert sender.sent[0].type == "error.validation"


async def test_set_shields_rear_out_of_range_returns_error():
    sender, queue = fresh_handler()
    msg = Message.build("weapons.set_shields", {"front": 50.0, "rear": -10.0})
    await weapons.handle_weapons_message("conn1", msg)
    assert queue.empty()
    assert sender.sent[0].type == "error.validation"


async def test_set_shields_zero_values_valid():
    _, queue = fresh_handler()
    msg = Message.build("weapons.set_shields", {"front": 0.0, "rear": 0.0})
    await weapons.handle_weapons_message("conn1", msg)
    assert queue.qsize() == 1


async def test_set_shields_max_values_valid():
    _, queue = fresh_handler()
    msg = Message.build("weapons.set_shields", {"front": 100.0, "rear": 100.0})
    await weapons.handle_weapons_message("conn1", msg)
    assert queue.qsize() == 1


# ---------------------------------------------------------------------------
# Unknown message type
# ---------------------------------------------------------------------------


async def test_unknown_type_not_queued_no_error():
    sender, queue = fresh_handler()
    msg = Message.build("weapons.self_destruct", {})
    await weapons.handle_weapons_message("conn1", msg)
    assert queue.empty()
    assert len(sender.sent) == 0
