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
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from server import captain, comms, damage_control, engineering, ew, flight_ops, game_loop, helm, lobby, medical, science, security, tactical, weapons
from server.mission_validator import validate_mission as _validate_mission
from server.connections import ConnectionManager
from server.models.messages import Message, VALID_SYSTEMS
from server.models.world import World, spawn_enemy
import server.save_system as _ss
from server.missions.loader import load_mission as _load_mission
from server.models.interior import make_default_interior as _make_default_interior
from server.models.ship_class import list_ship_classes as _list_ship_classes

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
flight_ops.init(manager, input_queue)
ew.init(manager, input_queue)
tactical.init(manager, input_queue)
damage_control.init(manager, input_queue)
game_loop.init(world, manager, input_queue)

# When the host starts a game the lobby calls this to kick off the loop.
lobby.register_game_start_callback(game_loop.start)
# When the game ends the loop calls this to reset lobby state.
game_loop.register_game_end_callback(lobby.on_game_end)

# Serve client files
CLIENT_DIR = Path(__file__).parent.parent / "client"
app.mount("/client", StaticFiles(directory=str(CLIENT_DIR), html=True), name="client")

MISSIONS_DIR = Path(__file__).parent.parent / "missions"

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
    "flight_ops": flight_ops.handle_flight_ops_message,
    "ew": ew.handle_ew_message,
    "tactical": tactical.handle_tactical_message,
    "damage_control": damage_control.handle_damage_control_message,
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
        "phase": "v0.04",
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
# Mission Editor endpoints
# ---------------------------------------------------------------------------


@app.get("/editor")
async def editor_page() -> RedirectResponse:
    """Redirect browser to the mission editor client page."""
    return RedirectResponse(url="/client/editor/", status_code=302)


@app.get("/editor/missions")
async def list_missions() -> dict:
    """Return list of all mission JSON files in MISSIONS_DIR."""
    missions = []
    if MISSIONS_DIR.exists():
        for path in sorted(MISSIONS_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                missions.append({
                    "id": data.get("id", path.stem),
                    "name": data.get("name", path.stem),
                    "file": path.name,
                })
            except (json.JSONDecodeError, OSError):
                missions.append({"id": path.stem, "name": path.stem, "file": path.name})
    return {"missions": missions}


@app.get("/editor/mission/{mission_id}")
async def get_mission(mission_id: str) -> dict:
    """Return a mission JSON by ID (file stem).  404 if missing, 422 if invalid JSON."""
    path = MISSIONS_DIR / f"{mission_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' not found.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid JSON: {exc}") from exc
    return data


@app.post("/editor/validate")
async def validate_mission_endpoint(mission: dict) -> dict:
    """Validate mission structure.  Returns {valid, errors}."""
    errors = _validate_mission(mission)
    return {"valid": len(errors) == 0, "errors": errors}


@app.post("/editor/save")
async def save_mission_endpoint(payload: dict) -> dict:
    """Save a mission JSON to MISSIONS_DIR/{id}.json.

    Requires 'id' field with only alphanumeric/underscore characters.
    Saves despite validation errors, returning warnings instead.
    """
    mission_id = payload.get("id", "")
    if not mission_id:
        raise HTTPException(status_code=400, detail="Mission 'id' field is required.")
    import re
    if not re.match(r"^[a-zA-Z0-9_]+$", str(mission_id)):
        raise HTTPException(
            status_code=400,
            detail="Mission 'id' must contain only alphanumeric characters and underscores.",
        )
    errors = _validate_mission(payload)
    MISSIONS_DIR.mkdir(parents=True, exist_ok=True)
    dest = MISSIONS_DIR / f"{mission_id}.json"
    dest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"saved": True, "file": dest.name, "warnings": errors}


# ---------------------------------------------------------------------------
# Save / Resume endpoints
# ---------------------------------------------------------------------------


@app.get("/saves")
async def list_saves() -> dict:
    """Return list of available save files, newest first."""
    return {"saves": _ss.list_saves()}


@app.get("/saves/{save_id}")
async def get_save(save_id: str) -> dict:
    """Return metadata for a specific save. 404 if not found."""
    try:
        data = _ss.load_save(save_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Save '{save_id}' not found.")
    return {
        "save_id": data.get("save_id", save_id),
        "saved_at": data.get("saved_at", ""),
        "mission_id": data.get("mission_id", ""),
        "ship_class": data.get("ship_class", ""),
        "difficulty_preset": data.get("difficulty_preset", ""),
        "tick_count": data.get("tick_count", 0),
    }


@app.post("/saves/resume/{save_id}")
async def resume_game(save_id: str) -> dict:
    """Restore a saved game and restart the game loop from the saved state."""
    if game_loop.is_running():
        raise HTTPException(status_code=409, detail="A game is already in progress.")
    try:
        restored = _ss.restore_game(save_id, world)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Save '{save_id}' not found.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Restore failed: {exc}") from exc

    mission_id       = restored["mission_id"]
    difficulty_preset = restored["difficulty_preset"]
    ship_class       = restored["ship_class"]
    tick_count       = restored["tick_count"]
    game_state       = restored.get("game_state", {})

    # Build game.started payload (mirrors _start_game in lobby.py).
    try:
        mission_data = _load_mission(mission_id)
    except FileNotFoundError:
        mission_data = {}
    sig = mission_data.get("signal_location")
    default_interior = _make_default_interior()
    interior_layout = {
        room_id: {
            "name": room.name,
            "deck": room.deck,
            "col": room.position[0],
            "row": room.position[1],
            "connections": list(room.connections),
        }
        for room_id, room in default_interior.rooms.items()
    }
    ship_classes = [
        {
            "id": sc.id, "name": sc.name, "description": sc.description,
            "max_hull": sc.max_hull, "min_crew": sc.min_crew, "max_crew": sc.max_crew,
        }
        for sc in _list_ship_classes()
    ]
    game_payload = {
        "mission_id": mission_id,
        "mission_name": mission_data.get("name", "Saved Mission"),
        "briefing_text": mission_data.get("briefing", "Resuming saved mission."),
        "signal_location": {"x": sig["x"], "y": sig["y"]} if sig else None,
        "interior_layout": interior_layout,
        "difficulty": difficulty_preset,
        "ship_class": ship_class,
        "ship_classes": ship_classes,
        "players": {},
        "resumed": True,
    }

    lobby.activate_game(game_payload)
    await game_loop.resume(
        mission_id=mission_id,
        difficulty_preset=difficulty_preset,
        ship_class=ship_class,
        tick_count=tick_count,
        game_state=game_state,
    )
    await manager.broadcast(Message.build("game.started", game_payload))
    logger.info("Game resumed from save '%s' (mission=%s)", save_id, mission_id)
    return {"status": "resumed", "mission_id": mission_id, "save_id": save_id}


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
