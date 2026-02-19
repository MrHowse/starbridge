"""Tests for server/captain.py — the Captain station handler.

The Captain handler is direct (not queued): alert level changes broadcast
immediately to all clients. Validation errors are sent back to the sender.
Unknown message types are silently ignored.
"""
from __future__ import annotations

import asyncio

import pytest

from server import captain
from server.models.messages import Message
from server.models.ship import Ship


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockManager:
    """Captures both individual sends and broadcasts."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, Message]] = []
        self.broadcast_msgs: list[Message] = []

    async def send(self, connection_id: str, message: Message) -> None:
        self.sent.append((connection_id, message))

    async def broadcast(self, message: Message) -> None:
        self.broadcast_msgs.append(message)


def _setup() -> tuple[MockManager, Ship]:
    manager = MockManager()
    ship = Ship()
    captain.init(manager, ship)
    return manager, ship


def _msg(type_: str, payload: dict | None = None) -> Message:
    return Message(type=type_, payload=payload or {}, tick=None, timestamp=0.0)


# ---------------------------------------------------------------------------
# captain.set_alert — valid levels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_alert_green_broadcasts():
    manager, ship = _setup()
    await captain.handle_captain_message("conn1", _msg("captain.set_alert", {"level": "green"}))
    assert len(manager.broadcast_msgs) == 1
    msg = manager.broadcast_msgs[0]
    assert msg.type == "ship.alert_changed"
    assert msg.payload["level"] == "green"


@pytest.mark.asyncio
async def test_set_alert_yellow_broadcasts():
    manager, ship = _setup()
    await captain.handle_captain_message("conn1", _msg("captain.set_alert", {"level": "yellow"}))
    assert len(manager.broadcast_msgs) == 1
    assert manager.broadcast_msgs[0].payload["level"] == "yellow"


@pytest.mark.asyncio
async def test_set_alert_red_broadcasts():
    manager, ship = _setup()
    await captain.handle_captain_message("conn1", _msg("captain.set_alert", {"level": "red"}))
    assert len(manager.broadcast_msgs) == 1
    assert manager.broadcast_msgs[0].payload["level"] == "red"


@pytest.mark.asyncio
async def test_set_alert_updates_ship_alert_level():
    manager, ship = _setup()
    assert ship.alert_level == "green"
    await captain.handle_captain_message("conn1", _msg("captain.set_alert", {"level": "red"}))
    assert ship.alert_level == "red"


# ---------------------------------------------------------------------------
# captain.set_alert — invalid level
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_alert_invalid_level_returns_error():
    manager, ship = _setup()
    await captain.handle_captain_message(
        "conn1", _msg("captain.set_alert", {"level": "orange"})
    )
    # Should send error back to sender, not broadcast
    assert len(manager.sent) == 1
    sent_conn_id, sent_msg = manager.sent[0]
    assert sent_conn_id == "conn1"
    assert sent_msg.type == "error.validation"
    assert len(manager.broadcast_msgs) == 0


@pytest.mark.asyncio
async def test_set_alert_invalid_level_does_not_change_ship():
    manager, ship = _setup()
    ship.alert_level = "yellow"
    await captain.handle_captain_message(
        "conn1", _msg("captain.set_alert", {"level": "orange"})
    )
    assert ship.alert_level == "yellow"  # unchanged


# ---------------------------------------------------------------------------
# Unknown message type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_type_silently_ignored():
    manager, ship = _setup()
    await captain.handle_captain_message("conn1", _msg("captain.unknown"))
    assert len(manager.sent) == 0
    assert len(manager.broadcast_msgs) == 0
