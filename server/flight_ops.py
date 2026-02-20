"""Flight Operations station — message handler.

Validates and enqueues flight_ops.* messages from the Flight Ops client.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from server.models.messages import Message, validate_payload

logger = logging.getLogger("starbridge.flight_ops")


class _ManagerProtocol(Protocol):
    async def send(self, connection_id: str, message: Message) -> None: ...


_manager: _ManagerProtocol | None = None
_queue: asyncio.Queue | None = None


def init(manager: _ManagerProtocol, queue: asyncio.Queue) -> None:
    """Inject dependencies. Called once from main.py."""
    global _manager, _queue
    _manager = manager
    _queue = queue


async def handle_flight_ops_message(connection_id: str, message: Message) -> None:
    """Route an inbound flight_ops.* WebSocket message."""
    assert _manager is not None and _queue is not None
    try:
        payload = validate_payload(message)
    except Exception as exc:
        await _manager.send(
            connection_id,
            Message.build("error.validation", {"message": str(exc), "original_type": message.type}),
        )
        return

    if payload is None:
        logger.warning("Unrecognised flight_ops message: %s", message.type)
        return

    _queue.put_nowait((message.type, payload))
