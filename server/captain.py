"""
Captain Station Handler.

Receives captain.* messages from the Captain client, validates them, and
handles them directly (not via the game loop queue). Alert level changes are
broadcast immediately to all connected clients — this is intentional: the
Captain's colour-shift command must feel instant.

Call init(manager, ship) from main.py before the game starts.
"""
from __future__ import annotations

import logging
from typing import Protocol

from pydantic import ValidationError

from server.game_logger import log_event as _log
from server.models.messages import CaptainSaveGamePayload, CaptainSetAlertPayload, CaptainSystemOverridePayload, Message, VALID_SYSTEMS, validate_payload
from server.models.ship import Ship

logger = logging.getLogger("starbridge.captain")


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init(manager: _ManagerProtocol, ship: Ship) -> None:
    """Inject manager and ship reference. Call once from main.py on startup."""
    global _manager, _ship
    _manager = manager
    _ship = ship


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
