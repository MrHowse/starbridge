"""
Captain Station Handler.

Receives captain.* messages from the Captain client, validates them, and
handles them directly (not via the game loop queue). Alert level changes are
broadcast immediately to all connected clients — this is intentional: the
Captain's colour-shift command must feel instant.

Messages that need game-loop state (authorize, add_log, undock) are forwarded
to the shared input queue for processing during the next tick.

Call init(manager, ship, queue) from main.py before the game starts.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from server.game_logger import log_event as _log
from server.models.messages import CaptainReassignCrewPayload, CaptainSaveGamePayload, CaptainSetAlertPayload, CaptainSystemOverridePayload, Message, VALID_SYSTEMS, validate_payload
from server.models.ship import Ship

logger = logging.getLogger("starbridge.captain")

# Message types that should be forwarded to the game loop queue rather than
# handled directly.  These need access to world state, weapons module, etc.
_QUEUE_FORWARDED_TYPES = frozenset({
    "captain.authorize",
    "captain.add_log",
    "captain.undock",
    "captain.accept_mission",
    "captain.decline_mission",
    # Flag Bridge (v0.07 §2.4)
    "captain.flag_add_drawing",
    "captain.flag_remove_drawing",
    "captain.flag_clear_drawings",
    "captain.flag_set_priority",
    "captain.flag_clear_priority",
    "captain.fleet_order",
    # Emergency Systems (B.6.3)
    "captain.abandon_ship",
})


# ---------------------------------------------------------------------------
# Manager protocol — needs both send (error responses) and broadcast (alerts)
# ---------------------------------------------------------------------------


class _ManagerProtocol(Protocol):
    async def send(self, connection_id: str, message: Message) -> None: ...
    async def broadcast(self, message: Message) -> None: ...


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_manager: _ManagerProtocol | None = None
_ship: Ship | None = None
_queue: asyncio.Queue[tuple[str, Any]] | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init(manager: _ManagerProtocol, ship: Ship, queue: asyncio.Queue[tuple[str, Any]] | None = None) -> None:
    """Inject manager, ship, and optional input queue. Call once from main.py."""
    global _manager, _ship, _queue
    _manager = manager
    _ship = ship
    _queue = queue


async def handle_captain_message(connection_id: str, message: Message) -> None:
    """Validate and handle a Captain control message."""
    assert _manager is not None and _ship is not None

    try:
        payload = validate_payload(message)
    except ValidationError as exc:
        await _manager.send(
            connection_id,
            Message.build(
                "error.validation",
                {"message": str(exc), "original_type": message.type},
            ),
        )
        logger.warning("Captain validation error from %s: %s", connection_id, exc)
        return

    if payload is None:
        logger.warning(
            "Unhandled captain message type '%s' from %s", message.type, connection_id
        )
        return

    # Forward queue-bound messages to the game loop for tick-synchronised handling.
    if message.type in _QUEUE_FORWARDED_TYPES:
        if _queue is not None:
            await _queue.put((message.type, payload))
            logger.debug("Forwarded %s from %s to game loop queue", message.type, connection_id)
        else:
            logger.warning("No queue available to forward %s from %s", message.type, connection_id)
        return

    if message.type == "captain.set_alert" and isinstance(payload, CaptainSetAlertPayload):
        _ship.alert_level = payload.level
        _log("captain", "alert_changed", {"level": payload.level})
        await _manager.broadcast(
            Message.build("ship.alert_changed", {"level": payload.level})
        )
        logger.info("Alert level set to '%s' by %s", payload.level, connection_id)

    elif message.type == "captain.system_override" and isinstance(payload, CaptainSystemOverridePayload):
        system = payload.system
        if system not in _ship.systems:
            await _manager.send(
                connection_id,
                Message.build("error.validation", {"message": f"Unknown system: {system!r}", "original_type": message.type}),
            )
            return
        _ship.systems[system]._captain_offline = not payload.online
        _log("captain", "system_override", {"system": system, "online": payload.online})
        await _manager.broadcast(
            Message.build("captain.override_changed", {"system": system, "online": payload.online})
        )
        logger.info("Captain set system '%s' online=%s from %s", system, payload.online, connection_id)

    elif message.type == "captain.reassign_crew" and isinstance(payload, CaptainReassignCrewPayload):
        import server.game_loop_medical_v2 as _glmed
        _roster = _glmed.get_roster()
        if _roster is None:
            await _manager.send(
                connection_id,
                Message.build("error.state", {"message": "No crew roster available.", "original_type": message.type}),
            )
            return
        result = _roster.reassign_crew(payload.crew_id, payload.new_duty_station)
        if result.get("ok"):
            _log("captain", "crew_reassigned", {
                "crew_id": payload.crew_id,
                "to_station": payload.new_duty_station,
            })
            await _manager.broadcast(
                Message.build("crew.reassignment_started", result),
            )
            logger.info("Crew %s reassigned to %s by %s", payload.crew_id, payload.new_duty_station, connection_id)
        else:
            await _manager.send(
                connection_id,
                Message.build("crew.reassignment_error", {"error": result.get("error", "Unknown error")}),
            )

    elif message.type == "captain.save_game" and isinstance(payload, CaptainSaveGamePayload):
        import server.game_loop as _gl
        import server.save_system as _ss
        world = _gl.get_world()
        if world is None or not _gl.is_running():
            await _manager.send(
                connection_id,
                Message.build("error.state", {"message": "No active game to save.", "original_type": message.type}),
            )
            return
        try:
            save_id = _ss.save_game(
                world=world,
                mission_id=_gl.get_mission_id(),
                difficulty_preset=_gl.get_difficulty_preset(),
                ship_class=_gl.get_ship_class_id(),
                tick_count=_gl.get_tick_count(),
                game_state=_gl.get_game_state(),
            )
            _log("captain", "game_saved", {"save_id": save_id})
            await _manager.broadcast(Message.build("game.saved", {"save_id": save_id}))
            logger.info("Game saved as '%s' by %s", save_id, connection_id)
        except Exception as exc:
            logger.error("Save failed: %s", exc)
            await _manager.send(
                connection_id,
                Message.build("error.state", {"message": f"Save failed: {exc}", "original_type": message.type}),
            )
