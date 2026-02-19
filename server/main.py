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
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from server import captain, comms, engineering, game_loop, helm, lobby, medical, science, security, weapons
from server.connections import ConnectionManager
from server.models.messages import Message, VALID_SYSTEMS
from server.models.world import World, spawn_enemy

logger = logging.getLogger("starbridge")

# Debug endpoints are enabled by default in development.
# Set STARBRIDGE_DEBUG=false to disable before deploying.
DEBUG: bool = os.getenv("STARBRIDGE_DEBUG", "true").lower() == "true"

app = FastAPI(title="Starbridge", version="0.0.1")

# Single connection manager for the process lifetime.
manager = ConnectionManager()

# Shared input queue: all stations enqueue commands here;
# the game loop drains it at the start of each tick.
input_queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

# World state — one sector, one ship.
world = World()

# Inject dependencies into each module.
lobby.init(manager)
helm.init(manager, input_queue)
engineering.init(manager, input_queue)
weapons.init(manager, input_queue)
science.init(manager, input_queue)
medical.init(manager, input_queue)
security.init(manager, input_queue)
comms.init(manager, input_queue)
captain.init(manager, world.ship)
game_loop.init(world, manager, input_queue)

# When the host starts a game the lobby calls this to kick off the loop.
lobby.register_game_start_callback(game_loop.start)
# When the game ends the loop calls this to reset lobby state.
game_loop.register_game_end_callback(lobby.on_game_end)

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
    "engineering": engineering.handle_engineering_message,
    "weapons": weapons.handle_weapons_message,
    "science": science.handle_science_message,
    "medical": medical.handle_medical_message,
    "security": security.handle_security_message,
    "comms": comms.handle_comms_message,
    "captain": captain.handle_captain_message,
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
        "phase": "4 — Weapons Station + Combat",
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


# ---------------------------------------------------------------------------
# Debug endpoints (disabled when STARBRIDGE_DEBUG != "true")
# ---------------------------------------------------------------------------


@app.post("/debug/damage")
async def debug_damage(
    system: str = Query(..., description="System name to damage"),
    amount: float = Query(20.0, description="HP to remove (default 20)"),
) -> dict[str, Any]:
    """[DEBUG] Deal damage to a named ship system.

    Example: POST /debug/damage?system=engines&amount=40
    """
    if not DEBUG:
        raise HTTPException(status_code=404, detail="Not found")
    if system not in VALID_SYSTEMS:
        raise HTTPException(status_code=400, detail=f"Unknown system: {system!r}")
    sys_obj = world.ship.systems[system]
    old_health = sys_obj.health
    sys_obj.health = max(0.0, sys_obj.health - amount)
    logger.info("[DEBUG] Damaged %s: %.1f → %.1f HP", system, old_health, sys_obj.health)
    return {"system": system, "old_health": old_health, "new_health": sys_obj.health}


@app.post("/debug/spawn_enemy")
async def debug_spawn_enemy(
    type_: str = Query("scout", alias="type", description="Enemy type: scout, cruiser, destroyer"),
) -> dict[str, Any]:
    """[DEBUG] Spawn an enemy near the player ship.

    Example: POST /debug/spawn_enemy?type=cruiser
    """
    if not DEBUG:
        raise HTTPException(status_code=404, detail="Not found")
    valid_types = {"scout", "cruiser", "destroyer"}
    if type_ not in valid_types:
        raise HTTPException(status_code=400, detail=f"Unknown enemy type: {type_!r}")
    # Place enemy 5000 units north of the player.
    ship = world.ship
    x = ship.x
    y = ship.y - 5_000.0
    entity_id = f"enemy_{len(world.enemies) + 1}"
    enemy = spawn_enemy(type_, x, y, entity_id)  # type: ignore[arg-type]
    world.enemies.append(enemy)
    logger.info("[DEBUG] Spawned %s %s at (%.0f, %.0f)", type_, entity_id, x, y)
    return {"entity_id": entity_id, "type": type_, "x": x, "y": y}


@app.post("/debug/start_game")
async def debug_start_game(
    mission_id: str = Query("debug_mission", description="Mission ID to start"),
) -> dict[str, Any]:
    """[DEBUG] Force-start the game without the host check.

    Useful for automated integration testing when a browser connection holds
    the host role.  Broadcasts game.started to all connected clients and
    starts the game loop.
    """
    if not DEBUG:
        raise HTTPException(status_code=404, detail="Not found")
    game_payload = {
        "mission_id": mission_id,
        "mission_name": "Debug Mission",
        "briefing_text": "All stations report ready. (debug start)",
    }
    # Bypass lobby host check — update the stored payload directly.
    import server.lobby as _lobby_module
    _lobby_module._game_payload = game_payload
    _lobby_module._game_active = True
    await game_loop.stop()   # no-op if not running; resets state if it is
    await manager.broadcast(Message.build("game.started", game_payload))
    await game_loop.start(mission_id)
    logger.info("[DEBUG] Force-started game: %s", mission_id)
    return {"status": "started", "mission_id": mission_id}


@app.get("/debug/ship_status")
async def debug_ship_status() -> dict[str, Any]:
    """[DEBUG] Return the current ship state as JSON.

    Useful for verifying server state without a client connected.
    """
    if not DEBUG:
        raise HTTPException(status_code=404, detail="Not found")
    ship = world.ship
    return {
        "name": ship.name,
        "position": {"x": round(ship.x, 1), "y": round(ship.y, 1)},
        "heading": round(ship.heading, 2),
        "velocity": round(ship.velocity, 2),
        "throttle": ship.throttle,
        "hull": ship.hull,
        "repair_focus": ship.repair_focus,
        "systems": {
            name: {
                "power": s.power,
                "health": s.health,
                "efficiency": round(s.efficiency, 3),
            }
            for name, s in ship.systems.items()
        },
    }
