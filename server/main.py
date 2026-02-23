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

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import ValidationError

from server import captain, comms, damage_control, engineering, ew, flight_ops, game_loop, helm, lobby, medical, science, security, tactical, weapons
from server.mission_validator import validate_mission as _validate_mission
from server.connections import ConnectionManager
from server.models.messages import Message, VALID_SYSTEMS
from server.models.world import World, spawn_enemy
import server.save_system as _ss
import server.profiles as _prof
import server.admin as _admin
from server.difficulty import get_preset as _get_preset
from server.missions.loader import load_mission as _load_mission
from server.models.interior import make_default_interior as _make_default_interior
from server.models.ship_class import list_ship_classes as _list_ship_classes

logger = logging.getLogger("starbridge")

# Debug endpoints are enabled by default in development.
# Set STARBRIDGE_DEBUG=false to disable before deploying.
DEBUG: bool = os.getenv("STARBRIDGE_DEBUG", "true").lower() == "true"

app = FastAPI(title="Starbridge", version="0.0.1")


class NoCacheMiddleware(BaseHTTPMiddleware):
    """Prevent browsers from serving stale JS/CSS during development."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)
        ct = response.headers.get("content-type", "")
        if any(t in ct for t in ("javascript", "text/css", "text/html")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


app.add_middleware(NoCacheMiddleware)

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

# When the host starts a game the lobby calls this wrapper, which captures the
# player roster for profile updates before delegating to game_loop.start.
async def _on_game_start(mission_id: str, difficulty: str = "officer", ship_class: str = "frigate") -> None:
    players = {
        role: occ[1]
        for role, occ in lobby._session.roles.items()
        if occ is not None
    }
    game_loop.set_session_players(players)
    await game_loop.start(mission_id, difficulty, ship_class)

lobby.register_game_start_callback(_on_game_start)
# When the game ends the loop calls this to reset lobby state.
game_loop.register_game_end_callback(lobby.on_game_end)

# Serve client files
CLIENT_DIR = Path(__file__).parent.parent / "client"
app.mount("/client", StaticFiles(directory=str(CLIENT_DIR), html=True), name="client")

MISSIONS_DIR = Path(__file__).parent.parent / "missions"
SITE_DIR     = Path(__file__).parent.parent / "client" / "site"

# ---------------------------------------------------------------------------
# Message routing
# ---------------------------------------------------------------------------

# Maps the category prefix of a message type (e.g. "lobby") to its handler.
# Handlers have signature: async (connection_id: str, message: Message) -> None
_MessageHandler = Callable[[str, Message], Awaitable[None]]

async def _handle_game_message(connection_id: str, message: Message) -> None:
    """Handle 'game.*' messages sent from the briefing page."""
    if message.type == "game.briefing_launch":
        await manager.broadcast(Message.build("game.all_ready", {}))
        logger.info("Captain launched from briefing — broadcasting game.all_ready")


_HANDLERS: dict[str, _MessageHandler] = {
    "lobby": lobby.handle_lobby_message,
    "game": _handle_game_message,
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

    # Track last interaction per station role for admin engagement monitoring.
    if category in _admin.ALL_STATION_ROLES:
        _admin.update_interaction(category)

    await handler(connection_id, message)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/")
async def landing_page() -> FileResponse:
    """Serve the Starbridge landing page."""
    return FileResponse(SITE_DIR / "index.html")


@app.get("/health")
async def health_check() -> dict[str, str]:
    """JSON health check and server status."""
    return {
        "name": "Starbridge",
        "version": "0.0.1",
        "status": "online",
        "phase": "v0.04",
    }


@app.get("/api/status")
async def api_status() -> dict:
    """Return current game/server status for the landing page."""
    running = game_loop.is_running()
    player_count = 0
    mission_name = None
    if running:
        try:
            player_count = sum(
                1 for v in lobby._session.roles.values() if v is not None
            )
        except Exception:
            pass
        try:
            mid = game_loop.get_mission_id()
            if mid and mid != "sandbox":
                md = _load_mission(mid)
                mission_name = md.get("name")
        except Exception:
            pass
    return {
        "running": running,
        "player_count": player_count,
        "mission_name": mission_name,
        "version": "0.0.1",
        "phase": "v0.04",
    }


@app.get("/api/difficulty_presets")
async def api_difficulty_presets() -> dict:
    """Return all difficulty presets with descriptions for lobby UI."""
    from server.difficulty import PRESETS as _PRESETS, preset_summary
    return {
        "presets": {
            key: {
                "name": p.name,
                "description": p.description,
                "summary": preset_summary(p),
                "hints_enabled": p.hints_enabled,
            }
            for key, p in _PRESETS.items()
        }
    }


@app.get("/manual")
@app.get("/manual/")
async def manual_page() -> FileResponse:
    """Serve the user manual page."""
    return FileResponse(SITE_DIR / "manual" / "index.html")


@app.get("/faq")
@app.get("/faq/")
async def faq_page() -> FileResponse:
    """Serve the FAQ page."""
    return FileResponse(SITE_DIR / "faq" / "index.html")


@app.get("/about")
@app.get("/about/")
async def about_page() -> FileResponse:
    """Serve the about page."""
    return FileResponse(SITE_DIR / "about" / "index.html")


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
# Admin Dashboard endpoints (v0.04h)
# ---------------------------------------------------------------------------


@app.get("/admin")
async def admin_page() -> RedirectResponse:
    """Redirect browser to the admin dashboard client page."""
    return RedirectResponse(url="/client/admin/", status_code=302)


@app.get("/admin/state")
async def admin_state() -> dict:
    """Return engagement report + ship snapshot for the admin dashboard."""
    engagement = _admin.build_engagement_report()
    ship = world.ship
    ship_snapshot: dict = {
        "hull":       round(ship.hull, 1),
        "alert_level": ship.alert_level,
        "velocity":   round(ship.velocity, 1),
        "heading":    round(ship.heading, 1),
        "systems": {
            name: {"power": round(s.power, 1), "health": round(s.health, 1)}
            for name, s in ship.systems.items()
        },
        "enemy_count": len(world.enemies),
    }
    return {
        "paused":     game_loop.is_paused(),
        "running":    game_loop.is_running(),
        "tick_count": game_loop.get_tick_count(),
        "engagement": engagement,
        "ship":       ship_snapshot,
    }


@app.post("/admin/pause")
async def admin_pause() -> dict:
    """Pause the game loop.  All clients see a 'PAUSED' overlay."""
    if not game_loop.is_running():
        raise HTTPException(status_code=409, detail="No game is currently running.")
    game_loop.pause()
    await manager.broadcast(Message.build("game.paused", {"paused_by": "admin"}))
    return {"paused": True}


@app.post("/admin/resume")
async def admin_resume() -> dict:
    """Resume the game loop after an admin pause."""
    if not game_loop.is_running():
        raise HTTPException(status_code=409, detail="No game is currently running.")
    game_loop.resume()
    await manager.broadcast(Message.build("game.resumed", {}))
    return {"paused": False}


@app.post("/admin/annotate")
async def admin_annotate(payload: dict) -> dict:
    """Send an annotation message to a specific station role."""
    role    = str(payload.get("role", "")).strip()
    message = str(payload.get("message", "")).strip()
    if not role:
        raise HTTPException(status_code=400, detail="'role' is required.")
    if not message:
        raise HTTPException(status_code=400, detail="'message' is required.")
    await manager.broadcast_to_roles(
        [role],
        Message.build("admin.annotation", {"role": role, "message": message}),
    )
    return {"sent": True, "role": role}


@app.post("/admin/broadcast")
async def admin_broadcast_msg(payload: dict) -> dict:
    """Broadcast an admin message to all connected clients."""
    message = str(payload.get("message", "")).strip()
    if not message:
        raise HTTPException(status_code=400, detail="'message' is required.")
    await manager.broadcast(Message.build("admin.broadcast", {"message": message}))
    return {"sent": True}


@app.post("/admin/difficulty")
async def admin_set_difficulty(payload: dict) -> dict:
    """Change the difficulty preset mid-game and broadcast to all clients."""
    from server.difficulty import PRESETS as _PRESETS, preset_summary
    from server.models.messages import Message
    preset = str(payload.get("preset", "")).strip()
    if not preset:
        raise HTTPException(status_code=400, detail="'preset' is required.")
    if preset not in _PRESETS:
        raise HTTPException(status_code=400, detail=f"Unknown difficulty preset: '{preset}'.")
    new_preset = _get_preset(preset)
    world.ship.difficulty = new_preset
    logger.info("[ADMIN] Difficulty changed to '%s'", preset)
    # Broadcast to all clients so UI can update.
    await manager.broadcast(Message.build("game.difficulty_changed", {
        "preset": preset,
        "name": new_preset.name,
        "description": new_preset.description,
        "summary": preset_summary(new_preset),
    }))
    return {"difficulty": preset}


@app.post("/admin/save")
async def admin_save_game() -> dict:
    """Trigger a game save from the admin dashboard."""
    if not game_loop.is_running():
        raise HTTPException(status_code=409, detail="No game is currently running.")
    save_id = _ss.save_game(
        world=world,
        mission_id=game_loop.get_mission_id(),
        difficulty_preset=game_loop.get_difficulty_preset(),
        ship_class=game_loop.get_ship_class_id(),
        tick_count=game_loop.get_tick_count(),
    )
    logger.info("[ADMIN] Game saved as '%s'", save_id)
    return {"save_id": save_id}


# ---------------------------------------------------------------------------
# Profile endpoints
# ---------------------------------------------------------------------------


@app.post("/profiles/login")
async def profiles_login(payload: dict) -> dict:
    """Create or retrieve a player profile by name.  Returns a profile summary."""
    name = str(payload.get("name", "")).strip()
    if not name or len(name) > 30:
        raise HTTPException(status_code=400, detail="name must be 1–30 characters.")
    profile = _prof.get_or_create_profile(name)
    return {
        "name":         profile["name"],
        "games_played": profile.get("games_played", 0),
        "games_won":    profile.get("games_won", 0),
        "games_lost":   profile.get("games_lost", 0),
        "achievements": profile.get("achievements", []),
        "last_played_at": profile.get("last_played_at"),
    }


@app.get("/profiles/leaderboard")
async def profiles_leaderboard() -> dict:
    """Return the top profiles sorted by games won."""
    return {"profiles": _prof.list_profiles()[:20]}


@app.get("/profiles/export")
async def profiles_export() -> Any:
    """Download all profiles as a CSV file."""
    from fastapi.responses import Response
    csv_data = _prof.export_csv()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=profiles.csv"},
    )


@app.get("/profiles")
async def list_profiles_endpoint() -> dict:
    """Return summary dicts for all profiles, sorted by games won."""
    return {"profiles": _prof.list_profiles()}


@app.get("/profiles/{name}")
async def get_profile_endpoint(name: str) -> dict:
    """Return the full profile for a player.  404 if not found."""
    profile = _prof.get_profile(name)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found.")
    return profile


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
