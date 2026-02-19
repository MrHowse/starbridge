"""
Weapons Station Handler.

Receives weapons.* messages from the Weapons client, validates them against
their Pydantic schemas, and queues them for the game loop to apply at the
start of the next tick.

Call init(sender, queue) from main.py before the game starts.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from pydantic import BaseModel, ValidationError

from server.models.messages import Message, validate_payload

logger = logging.getLogger("starbridge.weapons")


# ---------------------------------------------------------------------------
# Sender protocol — same decoupling pattern as engineering.py
# ---------------------------------------------------------------------------


class _SenderProtocol(Protocol):
    async def send(self, connection_id: str, message: Message) -> None: ...


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_sender: _SenderProtocol | None = None
_queue: asyncio.Queue[tuple[str, BaseModel]] | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init(
    sender: _SenderProtocol,
    queue: asyncio.Queue[tuple[str, BaseModel]],
) -> None:
    """Inject sender and input queue. Call once from main.py on startup."""
    global _sender, _queue
    _sender = sender
    _queue = queue


async def handle_weapons_message(connection_id: str, message: Message) -> None:
    """Validate and queue a Weapons control message for the game loop."""
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
        logger.warning("Weapons validation error from %s: %s", connection_id, exc)
        return

    if payload is None:
        logger.warning(
            "Unhandled weapons message type '%s' from %s", message.type, connection_id
        )
        return

    await _queue.put((message.type, payload))
    logger.debug("Queued %s from %s", message.type, connection_id)
