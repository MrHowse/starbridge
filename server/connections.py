"""
WebSocket Connection Manager.

Tracks active WebSocket connections with metadata (player name, role, session).
Supports role-filtered broadcasting and individual messaging.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket

from server.models.messages import Message

logger = logging.getLogger("starbridge.connections")


# ---------------------------------------------------------------------------
# Connection metadata
# ---------------------------------------------------------------------------


@dataclass
class ConnectionInfo:
    """Metadata attached to a single active WebSocket connection."""

    websocket: WebSocket
    connection_id: str
    player_name: str | None = None
    role: str | None = None
    session_id: str | None = None
    is_host: bool = False
    connected_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Manages all active WebSocket connections.

    Supports individual sends, full broadcast, and role-filtered broadcast.
    Safe within a single asyncio event loop — no locking is required.
    """

    def __init__(self) -> None:
        self._connections: dict[str, ConnectionInfo] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, websocket: WebSocket) -> str:
        """Accept a new WebSocket connection and return its unique ID."""
        await websocket.accept()
        connection_id = str(uuid.uuid4())
        self._connections[connection_id] = ConnectionInfo(
            websocket=websocket,
            connection_id=connection_id,
        )
        logger.info(
            "Connection opened: %s (total: %d)", connection_id, len(self._connections)
        )
        return connection_id

    def disconnect(self, connection_id: str) -> None:
        """Remove a connection. Safe to call even if the ID is unknown."""
        self._connections.pop(connection_id, None)
        logger.info(
            "Connection closed: %s (total: %d)", connection_id, len(self._connections)
        )

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def get(self, connection_id: str) -> ConnectionInfo | None:
        """Return connection info, or None if the ID is not found."""
        return self._connections.get(connection_id)

    def tag(self, connection_id: str, **kwargs: object) -> None:
        """Update metadata fields on a connection by keyword argument.

        Unknown field names are logged as warnings and ignored.
        Unknown connection IDs are also logged and ignored.
        """
        info = self._connections.get(connection_id)
        if info is None:
            logger.warning("tag() called on unknown connection: %s", connection_id)
            return
        for key, value in kwargs.items():
            if hasattr(info, key):
                setattr(info, key, value)
            else:
                logger.warning("tag() unknown field '%s' on ConnectionInfo", key)

    def get_by_role(self, role: str) -> list[ConnectionInfo]:
        """Return all connections with the given role."""
        return [c for c in self._connections.values() if c.role == role]

    def count(self) -> int:
        """Return the number of active connections."""
        return len(self._connections)

    def all_ids(self) -> list[str]:
        """Return the connection IDs of all active connections, in insertion order."""
        return list(self._connections.keys())

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send(self, connection_id: str, message: Message) -> None:
        """Send a message to a single connection. Logs and removes stale connections on error."""
        info = self._connections.get(connection_id)
        if info is None:
            logger.warning("send() called on unknown connection: %s", connection_id)
            return
        try:
            await info.websocket.send_text(message.to_json())
        except Exception as exc:
            logger.error("send() failed for %s: %s", connection_id, exc)
            self._connections.pop(connection_id, None)

    async def broadcast(self, message: Message) -> None:
        """Send a message to all connected clients. Removes stale connections on error."""
        payload = message.to_json()
        for info in list(self._connections.values()):
            try:
                await info.websocket.send_text(payload)
            except Exception as exc:
                logger.error(
                    "broadcast() failed for %s: %s", info.connection_id, exc
                )
                self._connections.pop(info.connection_id, None)

    async def broadcast_to_roles(self, roles: list[str], message: Message) -> None:
        """Send a message to all connections whose role is in `roles`. Removes stale connections on error."""
        payload = message.to_json()
        role_set = set(roles)
        for info in list(self._connections.values()):
            if info.role in role_set:
                try:
                    await info.websocket.send_text(payload)
                except Exception as exc:
                    logger.error(
                        "broadcast_to_roles() failed for %s: %s",
                        info.connection_id,
                        exc,
                    )
                    self._connections.pop(info.connection_id, None)
