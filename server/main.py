"""
Starbridge — Main server application.

FastAPI app with WebSocket endpoint, message routing, and static file serving.
The connection manager (manager) is a module-level singleton shared across
all WebSocket connections within a single server process.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from server import game_loop, helm, lobby
from server.connections import ConnectionManager
from server.models.messages import Message
from server.models.world import World

logger = logging.getLogger("starbridge")

app = FastAPI(title="Starbridge", version="0.0.1")

# Single connection manager for the process lifetime.
manager = ConnectionManager()

# Shared input queue: helm (and future stations) enqueue commands here;
# the game loop drains it at the start of each tick.
input_queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

# World state — one sector, one ship.
world = World()

# Inject dependencies into each module.
lobby.init(manager)
helm.init(manager, input_queue)
game_loop.init(world, manager, input_queue)

# When the host starts a game the lobby calls this to kick off the loop.
lobby.register_game_start_callback(game_loop.start)

# Serve client files
CLIENT_DIR = Path(__file__).parent.parent / "client"
app.mount("/client", StaticFiles(directory=str(CLIENT_DIR), html=True), name="client")

# ---------------------------------------------------------------------------
# Message routing
# ---------------------------------------------------------------------------

# Maps the category prefix of a message type (e.g. "lobby") to its handler.
# Handlers have signature: async (connection_id: str, message: Message) -> None
_MessageHandler = Callable[[str, Message], Awaitable[None]]

_HANDLERS: dict[str, _MessageHandler] = {
    "lobby": lobby.handle_lobby_message,
    "helm": helm.handle_helm_message,
}


async def _handle_message(connection_id: str, raw: str) -> None:
    """Parse, validate, and route one inbound WebSocket message.

    On JSON or schema errors, sends an error.validation message back to the
    originating client and returns — does not crash the connection loop.
    """
    # 1. Parse JSON
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        error = Message.build(
            "error.validation",
            {"message": f"JSON parse error: {exc}", "original_type": ""},
        )
        await manager.send(connection_id, error)
        logger.warning("JSON parse error from %s: %s", connection_id, exc)
        return

    original_type = data.get("type", "") if isinstance(data, dict) else ""

    # 2. Validate envelope
    try:
        message = Message.model_validate(data)
    except ValidationError as exc:
        error = Message.build(
            "error.validation",
            {"message": str(exc), "original_type": original_type},
        )
        await manager.send(connection_id, error)
        logger.warning("Envelope validation error from %s: %s", connection_id, exc)
        return

    # 3. Route by category prefix
    category = message.type.split(".")[0]
    handler = _HANDLERS.get(category)
    if handler is None:
        logger.warning(
            "No handler for message type '%s' from %s", message.type, connection_id
        )
        return

    await handler(connection_id, message)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/")
async def root() -> dict[str, str]:
    """Health check and server status."""
    return {
        "name": "Starbridge",
        "version": "0.0.1",
        "status": "online",
        "phase": "2 — Ship Physics & Helm",
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Accept WebSocket connections and handle the message loop."""
    connection_id = await manager.connect(websocket)
    await lobby.on_connect(connection_id)
    try:
        while True:
            raw = await websocket.receive_text()
            await _handle_message(connection_id, raw)
    except WebSocketDisconnect:
        manager.disconnect(connection_id)
        await lobby.on_disconnect(connection_id)
