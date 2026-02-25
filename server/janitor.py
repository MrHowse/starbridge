"""
Janitor Station Handler.

Receives janitor control messages from the client, validates them against
their Pydantic schemas, and queues them for the game loop to apply.

Same pattern as ew.py:
  init(sender, queue) — inject dependencies from main.py
  handle_janitor_message(connection_id, message) — validate and enqueue
"""
from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from pydantic import BaseModel, ValidationError

from server.models.messages import Message, validate_payload

logger = logging.getLogger("starbridge.janitor")


class _SenderProtocol(Protocol):
    async def send(self, connection_id: str, message: Message) -> None: ...


_sender: _SenderProtocol | None = None
_queue: asyncio.Queue[tuple[str, BaseModel]] | None = None


def init(
    sender: _SenderProtocol,
    queue: asyncio.Queue[tuple[str, BaseModel]],
) -> None:
    """Inject sender and input queue. Call once from main.py on startup."""
    global _sender, _queue
    _sender = sender
    _queue = queue


async def handle_janitor_message(connection_id: str, message: Message) -> None:
    """Validate and queue a Janitor control message for the game loop."""
    assert _sender is not None and _queue is not None

    try:
        payload = validate_payload(message)
    except ValidationError as exc:
        await _sender.send(
            connection_id,
            Message.build(
                "error.validation",
                {"message": str(exc), "original_type": message.type},
            ),
        )
        logger.warning("Janitor validation error from %s: %s", connection_id, exc)
        return

    if payload is None:
        logger.warning(
            "Unhandled janitor message type '%s' from %s", message.type, connection_id
        )
        return

    await _queue.put((message.type, payload))
    logger.debug("Queued %s from %s", message.type, connection_id)
