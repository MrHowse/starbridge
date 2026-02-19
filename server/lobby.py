"""
Lobby and Session Manager.

Handles game session lifecycle: role assignment and game launch.
There is one LobbySession per server process (single-session design, Phase 1).

Call init(manager) from main.py on startup to inject the ConnectionManager.
Call on_connect / on_disconnect from the WebSocket endpoint in main.py.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import ValidationError

from server.game_logger import log_event as _log, start_logging
from server.missions.loader import load_mission
from server.models.interior import make_default_interior
from server.models.messages import (
    LobbyClaimRolePayload,
    LobbyStartGamePayload,
    Message,
    validate_payload,
)

logger = logging.getLogger("starbridge.lobby")


# ---------------------------------------------------------------------------
# Manager protocol
# ---------------------------------------------------------------------------


class _ManagerProtocol(Protocol):
    """The subset of ConnectionManager's interface that lobby.py requires.

    Using a Protocol rather than a concrete import keeps the lobby module
    decoupled from ConnectionManager and allows MockManager in tests.
    """

    async def send(self, connection_id: str, message: Message) -> None: ...
    async def broadcast(self, message: Message) -> None: ...
    def tag(self, connection_id: str, **kwargs: object) -> None: ...
    def all_ids(self) -> list[str]: ...


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class LobbySession:
    """State for the single active lobby session."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # role → (connection_id, player_name) | None
    roles: dict[str, tuple[str, str] | None] = field(
        default_factory=lambda: {
            r: None
            for r in ("captain", "helm", "weapons", "engineering", "science", "medical", "security", "comms")
        }
    )
    host_connection_id: str | None = None


# ---------------------------------------------------------------------------
# Module-level state (set by init() / register_game_start_callback())
# ---------------------------------------------------------------------------

_manager: _ManagerProtocol | None = None
_session: LobbySession = LobbySession()
_on_game_start: Callable[[str], Awaitable[None]] | None = None
# Stored once game.started is broadcast; re-sent to any client that joins later.
_game_payload: dict[str, str] | None = None
# True from game.started until game.over; controls whether new joins get replay.
_game_active: bool = False


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init(manager: _ManagerProtocol) -> None:
    """Store the manager reference and reset lobby state.

    Called once from main.py on server startup with the real ConnectionManager.
    Calling again (e.g. in tests) resets the session to a clean state.
    """
    global _manager, _session, _game_payload, _game_active
    _manager = manager
    _session = LobbySession()
    _game_payload = None
    _game_active = False


def register_game_start_callback(callback: Callable[[str], Awaitable[None]]) -> None:
    """Register a coroutine to call when the host starts a game.

    Called from main.py to wire game_loop.start into the lobby flow.
    The callback receives the mission_id string.
    """
    global _on_game_start
    _on_game_start = callback


async def on_game_end() -> None:
    """Called by game_loop when the game ends.

    Clears the stored game.started payload so reconnecting clients receive a
    fresh lobby view rather than being replayed into the finished game.
    """
    global _game_payload, _game_active
    _game_payload = None
    _game_active = False
    logger.info("Game ended — lobby reset to pre-game state")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _roles_for_broadcast() -> dict[str, str | None]:
    """Return {role: player_name | None} for the lobby.state payload."""
    return {
        role: occupant[1] if occupant is not None else None
        for role, occupant in _session.roles.items()
    }


def _find_connection_role(connection_id: str) -> str | None:
    """Return the role currently held by connection_id, or None."""
    for role, occupant in _session.roles.items():
        if occupant is not None and occupant[0] == connection_id:
            return role
    return None


async def _broadcast_lobby_state() -> None:
    """Send current lobby.state to every connected client."""
    assert _manager is not None
    msg = Message.build(
        "lobby.state",
        {
            "roles": _roles_for_broadcast(),
            "host": _session.host_connection_id or "",
            "session_id": _session.session_id,
        },
    )
    await _manager.broadcast(msg)


# ---------------------------------------------------------------------------
# Connection lifecycle (called from main.py)
# ---------------------------------------------------------------------------


async def on_connect(connection_id: str) -> None:
    """Called from main.py after a new WebSocket connection is accepted.

    Sets this connection as host if it is the first, sends lobby.welcome,
    then broadcasts lobby.state to all connections.
    """
    assert _manager is not None

    if _session.host_connection_id is None:
        _session.host_connection_id = connection_id
        _manager.tag(connection_id, is_host=True)

    is_host = connection_id == _session.host_connection_id
    await _manager.send(
        connection_id,
        Message.build(
            "lobby.welcome",
            {"connection_id": connection_id, "is_host": is_host},
        ),
    )

    # If a game is currently in progress, catch up the late-joining client.
    if _game_payload is not None and _game_active:
        await _manager.send(connection_id, Message.build("game.started", _game_payload))
        return  # Skip lobby.state — game is in progress, not in lobby.

    await _broadcast_lobby_state()


async def on_disconnect(connection_id: str) -> None:
    """Called from main.py after manager.disconnect() has removed the connection.

    Releases the departing player's role (if any), reassigns host to the next
    connection if needed, then broadcasts lobby.state to remaining clients.
    """
    assert _manager is not None

    role = _find_connection_role(connection_id)
    if role is not None:
        _session.roles[role] = None
        logger.info("Role '%s' released by disconnected connection %s", role, connection_id)

    if _session.host_connection_id == connection_id:
        remaining = _manager.all_ids()  # already excludes disconnected connection
        _session.host_connection_id = remaining[0] if remaining else None
        if _session.host_connection_id:
            _manager.tag(_session.host_connection_id, is_host=True)
            logger.info("Host reassigned to %s", _session.host_connection_id)

    await _broadcast_lobby_state()


# ---------------------------------------------------------------------------
# Message sub-handlers (private)
# ---------------------------------------------------------------------------


async def _claim_role(connection_id: str, payload: LobbyClaimRolePayload) -> None:
    assert _manager is not None
    role = payload.role

    # Observer roles (display-only) are not tracked in session.roles —
    # just tag the connection so broadcast_to_roles can target them.
    if role not in _session.roles:
        _manager.tag(connection_id, role=role)
        return

    occupant = _session.roles[role]
    if occupant is not None and occupant[0] != connection_id:
        await _manager.send(
            connection_id,
            Message.build("lobby.error", {"message": f"Role '{role}' is already taken."}),
        )
        return

    # Release any role this connection currently holds before claiming the new one
    current_role = _find_connection_role(connection_id)
    if current_role is not None and current_role != role:
        _session.roles[current_role] = None

    _session.roles[role] = (connection_id, payload.player_name)
    _manager.tag(connection_id, role=role, player_name=payload.player_name)
    _log("lobby", "role_claimed", {"role": role, "player": payload.player_name})
    logger.info(
        "Connection %s claimed role '%s' as '%s'",
        connection_id, role, payload.player_name,
    )
    await _broadcast_lobby_state()


async def _release_role(connection_id: str) -> None:
    assert _manager is not None
    role = _find_connection_role(connection_id)
    if role is None:
        return

    _session.roles[role] = None
    _manager.tag(connection_id, role=None, player_name=None)
    _log("lobby", "role_released", {"role": role})
    logger.info("Connection %s released role '%s'", connection_id, role)
    await _broadcast_lobby_state()


async def _start_game(connection_id: str, payload: LobbyStartGamePayload) -> None:
    assert _manager is not None

    if connection_id != _session.host_connection_id:
        await _manager.send(
            connection_id,
            Message.build(
                "error.permission",
                {"message": "Only the host can start the game.", "original_type": "lobby.start_game"},
            ),
        )
        return

    global _game_payload, _game_active
    try:
        mission_data = load_mission(payload.mission_id)
    except FileNotFoundError:
        mission_data = {}
    sig = mission_data.get("signal_location")

    _default_interior = make_default_interior()
    interior_layout = {
        room_id: {
            "name": room.name,
            "deck": room.deck,
            "col": room.position[0],
            "row": room.position[1],
            "connections": list(room.connections),
        }
        for room_id, room in _default_interior.rooms.items()
    }

    _game_payload = {
        "mission_id": payload.mission_id,
        "mission_name": mission_data.get("name", "Awaiting Orders"),
        "briefing_text": mission_data.get("briefing", "All stations report ready."),
        "signal_location": {"x": sig["x"], "y": sig["y"]} if sig else None,
        "interior_layout": interior_layout,
    }
    _game_active = True
    players = {role: occ[1] for role, occ in _session.roles.items() if occ is not None}
    start_logging(payload.mission_id, players)
    _log("lobby", "game_started", {"mission_id": payload.mission_id, "players": players})
    await _manager.broadcast(Message.build("game.started", _game_payload))
    logger.info("Game started by host %s, mission: %s", connection_id, payload.mission_id)

    if _on_game_start is not None:
        await _on_game_start(payload.mission_id)


# ---------------------------------------------------------------------------
# Public message handler (registered in main.py routing table)
# ---------------------------------------------------------------------------


async def handle_lobby_message(connection_id: str, message: Message) -> None:
    """Validate the payload and dispatch to the appropriate sub-handler."""
    assert _manager is not None

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
        logger.warning("Payload validation error from %s: %s", connection_id, exc)
        return

    if message.type == "lobby.claim_role":
        assert isinstance(payload, LobbyClaimRolePayload)
        await _claim_role(connection_id, payload)
    elif message.type == "lobby.release_role":
        await _release_role(connection_id)
    elif message.type == "lobby.start_game":
        assert isinstance(payload, LobbyStartGamePayload)
        await _start_game(connection_id, payload)
    else:
        logger.warning("Unhandled lobby message type: %s", message.type)
