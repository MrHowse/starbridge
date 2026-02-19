"""Tests for server/science.py — the Science station handler.

Mirrors the pattern of test_weapons.py:
  - Valid payloads are queued.
  - Invalid payloads return error.validation.
  - Unknown message types are silently ignored (no queue entry, no error).
"""
from __future__ import annotations

import asyncio

import pytest

from server import science
from server.models.messages import Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockSender:
    """Captures messages sent back to the client."""

    def __init__(self) -> None:
        self.sent: list[Message] = []

    async def send(self, connection_id: str, message: Message) -> None:
        self.sent.append(message)


def _setup() -> tuple[MockSender, asyncio.Queue]:  # type: ignore[type-arg]
    sender = MockSender()
    queue: asyncio.Queue = asyncio.Queue()  # type: ignore[type-arg]
    science.init(sender, queue)
    return sender, queue


def _msg(type_: str, payload: dict | None = None) -> Message:
    return Message(type=type_, payload=payload or {}, tick=None, timestamp=0.0)


# ---------------------------------------------------------------------------
# science.start_scan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_scan_valid_enqueues():
    sender, queue = _setup()
    await science.handle_science_message("conn1", _msg("science.start_scan", {"entity_id": "enemy_1"}))
    assert not queue.empty()
    msg_type, payload = queue.get_nowait()
    assert msg_type == "science.start_scan"
    assert payload.entity_id == "enemy_1"


@pytest.mark.asyncio
async def test_start_scan_missing_entity_id_returns_error():
    sender, queue = _setup()
    await science.handle_science_message("conn1", _msg("science.start_scan", {}))
    assert sender.sent
    assert sender.sent[0].type == "error.validation"
    assert queue.empty()


@pytest.mark.asyncio
async def test_start_scan_empty_entity_id_returns_error():
    sender, queue = _setup()
    await science.handle_science_message("conn1", _msg("science.start_scan", {"entity_id": ""}))
    assert sender.sent
    assert sender.sent[0].type == "error.validation"
    assert queue.empty()


# ---------------------------------------------------------------------------
# science.cancel_scan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_scan_enqueues():
    sender, queue = _setup()
    await science.handle_science_message("conn1", _msg("science.cancel_scan"))
    assert not queue.empty()
    msg_type, payload = queue.get_nowait()
    assert msg_type == "science.cancel_scan"


# ---------------------------------------------------------------------------
# Unknown message type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_type_not_queued_no_error():
    sender, queue = _setup()
    await science.handle_science_message("conn1", _msg("science.teleport"))
    assert queue.empty()
    assert not sender.sent
