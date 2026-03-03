"""
Lobby and Session Manager.

Handles game session lifecycle: role assignment and game launch.
There is one LobbySession per server process (single-session design, Phase 1).

Call init(manager) from main.py on startup to inject the ConnectionManager.
Call on_connect / on_disconnect from the WebSocket endpoint in main.py.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import ValidationError

from server.game_logger import log_event as _log, start_logging
from server.game_loop_janitor import is_janitor_name
from server.missions.loader import load_mission
from server.models.interior import make_default_interior
from server.models.ship_class import list_ship_classes
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
            for r in ("captain", "helm", "weapons", "engineering", "science", "medical", "security", "comms", "flight_ops", "electronic_warfare", "operations", "hazard_control", "janitor", "quartermaster")
        }
    )
    host_connection_id: str | None = None


# ---------------------------------------------------------------------------
# Module-level state (set by init() / register_game_start_callback())
# ---------------------------------------------------------------------------

_manager: _ManagerProtocol | None = None
_session: LobbySession = LobbySession()
_on_game_start: Callable[[str, str, str, list[str]], Awaitable[None]] | None = None
# Stored once game.started is broadcast; re-sent to any client that joins later.
_game_payload: dict[str, str] | None = None
# True from game.started until game.over; controls whether new joins get replay.
_game_active: bool = False

# Reserved roles: role → (player_name, disconnect_timestamp)
# Within ROLE_RESERVE_SECS of disconnect the role is held for the player.
_reserved_roles: dict[str, tuple[str, float]] = {}
ROLE_RESERVE_SECS: float = 60.0


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init(manager: _ManagerProtocol) -> None:
    """Store the manager reference and reset lobby state.

    Called once from main.py on server startup with the real ConnectionManager.
    Calling again (e.g. in tests) resets the session to a clean state.
    """
    global _manager, _session, _game_payload, _game_active, _reserved_roles
    _manager = manager
    _session = LobbySession()
    _game_payload = None
    _game_active = False
    _reserved_roles = {}


def register_game_start_callback(callback: Callable[..., Awaitable[None]]) -> None:
    """Register a coroutine to call when the host starts a game.

    Called from main.py to wire game_loop.start into the lobby flow.
    The callback receives (mission_id, difficulty, ship_class, equipment_modules, loadout).
    """
    global _on_game_start
    _on_game_start = callback


async def on_game_end() -> None:
    """Called by game_loop when the game ends.

    Clears the stored game.started payload so reconnecting clients receive a
    fresh lobby view rather than being replayed into the finished game.
    """
    global _game_payload, _game_active, _reserved_roles
    _game_payload = None
    _game_active = False
    _reserved_roles = {}  # Release all reservations — game is over.
    logger.info("Game ended — lobby reset to pre-game state")


def occupied_role_count() -> int:
    """Return the number of roles currently occupied by a player."""
    return sum(1 for v in _session.roles.values() if v is not None)


def activate_game(payload: dict) -> None:
    """Activate a resumed game session without calling _on_game_start.

    Called by main.py's /saves/resume endpoint after save_system.restore_game()
    and game_loop.resume() have been invoked.  Ensures that late-joining clients
    receive the stored game.started payload when they connect.
    """
    global _game_payload, _game_active
    _game_payload = payload
    _game_active = True
    logger.info("Game activated via save/resume")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _roles_for_broadcast() -> dict[str, str | None]:
    """Return {role: player_name | None} for the lobby.state payload.

    Reserved (disconnected) roles are shown as 'DISCONNECTED:<player_name>'
    so the lobby UI can distinguish them from empty slots.
    The janitor role is never shown in the public lobby state.
    """
    result: dict[str, str | None] = {}
    for role, occupant in _session.roles.items():
        if role == "janitor":
            continue  # Secret — never broadcast.
        if occupant is not None:
            result[role] = occupant[1]
        elif role in _reserved_roles:
            result[role] = f"DISCONNECTED:{_reserved_roles[role][0]}"
        else:
            result[role] = None
    return result


def _find_connection_role(connection_id: str) -> str | None:
    """Return the first role held by connection_id, or None."""
    for role, occupant in _session.roles.items():
        if occupant is not None and occupant[0] == connection_id:
            return role
    return None


def _find_connection_roles(connection_id: str) -> list[str]:
    """Return all roles currently held by connection_id."""
    return [
        role
        for role, occupant in _session.roles.items()
        if occupant is not None and occupant[0] == connection_id
    ]


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

    During an active game, reserves the role for ROLE_RESERVE_SECS seconds so
    the player can reconnect. After the window, the role is released automatically.
    Outside of a game, releases the role immediately.
    """
    assert _manager is not None

    held_roles = _find_connection_roles(connection_id)
    for role in held_roles:
        player_name = _session.roles[role][1]  # type: ignore[index]
        _session.roles[role] = None
        if _game_active:
            # Reserve the role for 60 s.
            _reserved_roles[role] = (player_name, time.monotonic())
            asyncio.get_event_loop().call_later(
                ROLE_RESERVE_SECS, _expire_reserved_role, role, player_name
            )
            logger.info(
                "Role '%s' reserved for %.0fs (player '%s' disconnected mid-game)",
                role, ROLE_RESERVE_SECS, player_name,
            )
        else:
            logger.info("Role '%s' released by disconnected connection %s", role, connection_id)

    if _session.host_connection_id == connection_id:
        remaining = _manager.all_ids()  # already excludes disconnected connection
        _session.host_connection_id = remaining[0] if remaining else None
        if _session.host_connection_id:
            _manager.tag(_session.host_connection_id, is_host=True)
            logger.info("Host reassigned to %s", _session.host_connection_id)

    await _broadcast_lobby_state()


def _expire_reserved_role(role: str, player_name: str) -> None:
    """Release a reserved role if it hasn't been reclaimed.

    Called by asyncio.call_later() after ROLE_RESERVE_SECS seconds.
    """
    if _reserved_roles.get(role, (None,))[0] == player_name:
        _reserved_roles.pop(role, None)
        logger.info("Reserved role '%s' expired for player '%s'", role, player_name)
        # Schedule async broadcast since call_later can't await.
        loop = asyncio.get_event_loop()
        if _manager and loop.is_running():
            loop.create_task(_broadcast_lobby_state())


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

    # Janitor role requires a matching callsign.
    if role == "janitor" and not is_janitor_name(payload.player_name):
        await _manager.send(
            connection_id,
            Message.build("lobby.error", {
                "message": "Access denied.",
                "code": "role_restricted",
            }),
        )
        return

    occupant = _session.roles[role]
    if occupant is not None and occupant[0] != connection_id:
        # Another connection holds the role.
        other_player = occupant[1]
        await _manager.send(
            connection_id,
            Message.build("lobby.error", {
                "message": f"Role '{role}' is already taken.",
                "code": "role_occupied",
                "occupant": other_player,
            }),
        )
        return

    # Check if the role is reserved (mid-game reconnect scenario).
    reserved = _reserved_roles.get(role)
    if reserved is not None:
        res_player, _ts = reserved
        if res_player == payload.player_name:
            # Same player reclaiming their reserved slot — allow silently.
            _reserved_roles.pop(role, None)
            logger.info(
                "Connection %s reclaimed reserved role '%s' as '%s'",
                connection_id, role, payload.player_name,
            )
        else:
            # Different player trying to claim a reserved role during the reserve window.
            await _manager.send(
                connection_id,
                Message.build("lobby.error", {
                    "message": f"Role '{role}' is temporarily reserved for '{res_player}'.",
                    "code": "role_reserved",
                    "occupant": res_player,
                }),
            )
            return

    # In single-role mode (default), release any other role this connection holds.
    # In additional mode, the connection keeps its existing roles.
    if not payload.additional:
        for held in _find_connection_roles(connection_id):
            if held != role:
                _session.roles[held] = None

    _session.roles[role] = (connection_id, payload.player_name)
    _manager.tag(connection_id, role=role, player_name=payload.player_name)
    _log("lobby", "role_claimed", {
        "role": role,
        "player": payload.player_name,
        "additional": payload.additional,
    })
    logger.info(
        "Connection %s claimed role '%s' as '%s' (additional=%s)",
        connection_id, role, payload.player_name, payload.additional,
    )
    await _broadcast_lobby_state()

    # If this player qualifies for the janitor role, unicast a hint.
    if role != "janitor" and is_janitor_name(payload.player_name):
        await _manager.send(
            connection_id,
            Message.build("lobby.janitor_available", {}),
        )


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

    _default_interior = make_default_interior(payload.ship_class)
    interior_layout = {
        room_id: {
            "name": room.name,
            "deck": room.deck,
            "deck_number": room.deck_number,
            "col": room.position[0],
            "row": room.position[1],
            "connections": list(room.connections),
        }
        for room_id, room in _default_interior.rooms.items()
    }

    # Build available ship classes list for client display.
    ship_classes = [
        {
            "id": sc.id, "name": sc.name, "description": sc.description,
            "max_hull": sc.max_hull, "min_crew": sc.min_crew, "max_crew": sc.max_crew,
        }
        for sc in list_ship_classes()
    ]

    players = {role: occ[1] for role, occ in _session.roles.items() if occ is not None}

    # Validate equipment modules (if any).
    from server.equipment_modules import validate_modules
    modules_ok, modules_err = validate_modules(payload.ship_class, payload.equipment_modules)
    if not modules_ok:
        await _manager.send(
            connection_id,
            Message.build("error.validation", {"message": modules_err, "original_type": "lobby.start_game"}),
        )
        return

    # v0.07 §3: Validate loadout configuration (if any).
    _loadout_dict = payload.loadout
    if _loadout_dict:
        from server.loadout import LoadoutConfig, validate_loadout
        try:
            _lc = LoadoutConfig(**_loadout_dict)
            _lo_ok, _lo_err = validate_loadout(_lc, payload.ship_class)
            if not _lo_ok:
                await _manager.send(
                    connection_id,
                    Message.build("error.validation", {"message": _lo_err, "original_type": "lobby.start_game"}),
                )
                return
        except Exception as _lo_exc:
            await _manager.send(
                connection_id,
                Message.build("error.validation", {"message": str(_lo_exc), "original_type": "lobby.start_game"}),
            )
            return

    _game_payload = {
        "mission_id": payload.mission_id,
        "mission_name": mission_data.get("name", "Awaiting Orders"),
        "briefing_text": mission_data.get("briefing", "All stations report ready."),
        "signal_location": {"x": sig["x"], "y": sig["y"]} if sig else None,
        "interior_layout": interior_layout,
        "difficulty": payload.difficulty,
        "ship_class": payload.ship_class,
        "ship_classes": ship_classes,
        "players": players,
        "equipment_modules": payload.equipment_modules,
        "loadout": _loadout_dict,
    }
    _game_active = True
    start_logging(payload.mission_id, players)
    _log("lobby", "game_started", {
        "mission_id": payload.mission_id,
        "ship_class": payload.ship_class,
        "players": players,
    })
    await _manager.broadcast(Message.build("game.started", _game_payload))
    logger.info(
        "Game started by host %s, mission: %s, ship: %s",
        connection_id, payload.mission_id, payload.ship_class,
    )

    if _on_game_start is not None:
        await _on_game_start(payload.mission_id, payload.difficulty, payload.ship_class, payload.equipment_modules, _loadout_dict)


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
