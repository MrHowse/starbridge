"""Tests for lobby session logic."""
from __future__ import annotations

from typing import Any

from server import lobby
from server.models.messages import Message


# ---------------------------------------------------------------------------
# Mock ConnectionManager
# ---------------------------------------------------------------------------


class MockManager:
    """Minimal ConnectionManager stand-in for lobby tests.

    Tracks sent/broadcast messages and simulates all_ids() so host reassignment
    can be tested by adding/removing IDs before calling lobby functions.
    """

    def __init__(self, initial_ids: list[str] | None = None) -> None:
        self._ids: list[str] = list(initial_ids or [])
        self.sent: list[tuple[str, Message]] = []
        self.broadcasts: list[Message] = []
        self.tags: dict[str, dict[str, Any]] = {}

    async def send(self, connection_id: str, message: Message) -> None:
        self.sent.append((connection_id, message))

    async def broadcast(self, message: Message) -> None:
        self.broadcasts.append(message)

    def tag(self, connection_id: str, **kwargs: Any) -> None:
        self.tags.setdefault(connection_id, {}).update(kwargs)

    def all_ids(self) -> list[str]:
        return list(self._ids)

    # Test helpers
    def add(self, cid: str) -> None:
        self._ids.append(cid)

    def remove(self, cid: str) -> None:
        self._ids.remove(cid)


def fresh(*connection_ids: str) -> MockManager:
    """Create a MockManager with given IDs and call lobby.init() to reset state."""
    m = MockManager(list(connection_ids))
    lobby.init(m)
    return m


def last_broadcast(m: MockManager) -> Message:
    assert m.broadcasts, "No broadcasts recorded"
    return m.broadcasts[-1]


def last_sent_to(m: MockManager, cid: str) -> Message:
    for c, msg in reversed(m.sent):
        if c == cid:
            return msg
    raise AssertionError(f"No message sent to {cid}")


def broadcasts_of_type(m: MockManager, type_: str) -> list[Message]:
    return [msg for msg in m.broadcasts if msg.type == type_]


# ---------------------------------------------------------------------------
# on_connect
# ---------------------------------------------------------------------------


async def test_on_connect_first_connection_becomes_host():
    _ = fresh("a")
    await lobby.on_connect("a")
    assert lobby._session.host_connection_id == "a"


async def test_on_connect_second_connection_is_not_host():
    _ = fresh("a", "b")
    await lobby.on_connect("a")
    await lobby.on_connect("b")
    assert lobby._session.host_connection_id == "a"


async def test_on_connect_sends_welcome_to_new_client():
    m = fresh("a")
    await lobby.on_connect("a")
    welcome = last_sent_to(m, "a")
    assert welcome.type == "lobby.welcome"
    assert welcome.payload["connection_id"] == "a"
    assert welcome.payload["is_host"] is True


async def test_on_connect_welcome_is_host_false_for_second_connection():
    m = fresh("a", "b")
    await lobby.on_connect("a")
    await lobby.on_connect("b")
    welcome = last_sent_to(m, "b")
    assert welcome.payload["is_host"] is False


async def test_on_connect_broadcasts_lobby_state():
    m = fresh("a")
    await lobby.on_connect("a")
    state = last_broadcast(m)
    assert state.type == "lobby.state"
    assert "roles" in state.payload
    assert state.payload["session_id"] == lobby._session.session_id


async def test_on_connect_lobby_state_all_roles_vacant():
    m = fresh("a")
    await lobby.on_connect("a")
    state = last_broadcast(m)
    assert all(v is None for v in state.payload["roles"].values())


# ---------------------------------------------------------------------------
# on_disconnect
# ---------------------------------------------------------------------------


async def test_on_disconnect_releases_held_role():
    m = fresh("a")
    await lobby.on_connect("a")
    lobby._session.roles["helm"] = ("a", "Alice")
    m.remove("a")
    await lobby.on_disconnect("a")
    assert lobby._session.roles["helm"] is None


async def test_on_disconnect_no_role_held_does_not_raise():
    m = fresh("a", "b")
    await lobby.on_connect("a")
    await lobby.on_connect("b")
    m.remove("b")
    await lobby.on_disconnect("b")  # b has no role — must not raise


async def test_on_disconnect_host_reassigned_to_next_connection():
    m = fresh("a", "b")
    await lobby.on_connect("a")
    await lobby.on_connect("b")
    m.remove("a")
    await lobby.on_disconnect("a")
    assert lobby._session.host_connection_id == "b"


async def test_on_disconnect_last_connection_clears_host():
    m = fresh("a")
    await lobby.on_connect("a")
    m.remove("a")
    await lobby.on_disconnect("a")
    assert lobby._session.host_connection_id is None


async def test_on_disconnect_broadcasts_updated_state():
    m = fresh("a", "b")
    await lobby.on_connect("a")
    await lobby.on_connect("b")
    m.remove("b")
    m.broadcasts.clear()
    await lobby.on_disconnect("b")
    state = last_broadcast(m)
    assert state.type == "lobby.state"


# ---------------------------------------------------------------------------
# claim_role
# ---------------------------------------------------------------------------


async def test_claim_role_success():
    m = fresh("a")
    await lobby.on_connect("a")
    m.broadcasts.clear()

    msg = Message.build("lobby.claim_role", {"role": "helm", "player_name": "Alice"})
    await lobby.handle_lobby_message("a", msg)

    assert lobby._session.roles["helm"] == ("a", "Alice")
    state = last_broadcast(m)
    assert state.type == "lobby.state"
    assert state.payload["roles"]["helm"] == "Alice"


async def test_claim_role_tags_connection():
    m = fresh("a")
    await lobby.on_connect("a")
    msg = Message.build("lobby.claim_role", {"role": "weapons", "player_name": "Bob"})
    await lobby.handle_lobby_message("a", msg)
    assert m.tags.get("a", {}).get("role") == "weapons"
    assert m.tags.get("a", {}).get("player_name") == "Bob"


async def test_claim_role_already_taken_sends_error():
    m = fresh("a", "b")
    await lobby.on_connect("a")
    await lobby.on_connect("b")
    lobby._session.roles["helm"] = ("b", "Bob")

    m.sent.clear()
    msg = Message.build("lobby.claim_role", {"role": "helm", "player_name": "Alice"})
    await lobby.handle_lobby_message("a", msg)

    err = last_sent_to(m, "a")
    assert err.type == "lobby.error"
    assert "helm" in err.payload["message"]


async def test_claim_role_already_taken_does_not_overwrite():
    _ = fresh("a", "b")
    await lobby.on_connect("a")
    await lobby.on_connect("b")
    lobby._session.roles["helm"] = ("b", "Bob")

    msg = Message.build("lobby.claim_role", {"role": "helm", "player_name": "Alice"})
    await lobby.handle_lobby_message("a", msg)
    assert lobby._session.roles["helm"] == ("b", "Bob")


async def test_claim_role_releases_previous_role():
    _ = fresh("a")
    await lobby.on_connect("a")

    msg1 = Message.build("lobby.claim_role", {"role": "helm", "player_name": "Alice"})
    await lobby.handle_lobby_message("a", msg1)

    msg2 = Message.build("lobby.claim_role", {"role": "captain", "player_name": "Alice"})
    await lobby.handle_lobby_message("a", msg2)

    assert lobby._session.roles["helm"] is None
    assert lobby._session.roles["captain"] == ("a", "Alice")


async def test_claim_same_role_again_is_idempotent():
    _ = fresh("a")
    await lobby.on_connect("a")
    msg = Message.build("lobby.claim_role", {"role": "helm", "player_name": "Alice"})
    await lobby.handle_lobby_message("a", msg)
    await lobby.handle_lobby_message("a", msg)
    assert lobby._session.roles["helm"] == ("a", "Alice")


async def test_claim_role_invalid_role_returns_validation_error():
    m = fresh("a")
    await lobby.on_connect("a")
    msg = Message.build("lobby.claim_role", {"role": "navigator", "player_name": "X"})
    m.sent.clear()
    await lobby.handle_lobby_message("a", msg)
    err = last_sent_to(m, "a")
    assert err.type == "error.validation"


async def test_claim_all_five_roles():
    ids = ["a", "b", "c", "d", "e"]
    _ = fresh(*ids)
    for cid in ids:
        await lobby.on_connect(cid)

    roles = ["captain", "helm", "weapons", "engineering", "science"]
    for cid, role in zip(ids, roles):
        msg = Message.build("lobby.claim_role", {"role": role, "player_name": cid})
        await lobby.handle_lobby_message(cid, msg)

    for role, cid in zip(roles, ids):
        assert lobby._session.roles[role] == (cid, cid)


# ---------------------------------------------------------------------------
# release_role
# ---------------------------------------------------------------------------


async def test_release_role_clears_assignment():
    m = fresh("a")
    await lobby.on_connect("a")
    lobby._session.roles["science"] = ("a", "Alice")

    m.broadcasts.clear()
    msg = Message.build("lobby.release_role", {})
    await lobby.handle_lobby_message("a", msg)

    assert lobby._session.roles["science"] is None
    assert last_broadcast(m).type == "lobby.state"


async def test_release_role_tags_connection_with_none():
    m = fresh("a")
    await lobby.on_connect("a")
    lobby._session.roles["science"] = ("a", "Alice")

    msg = Message.build("lobby.release_role", {})
    await lobby.handle_lobby_message("a", msg)
    assert m.tags.get("a", {}).get("role") is None


async def test_release_role_when_none_held_does_not_raise():
    _ = fresh("a")
    await lobby.on_connect("a")
    msg = Message.build("lobby.release_role", {})
    await lobby.handle_lobby_message("a", msg)  # no role held — must not raise


async def test_release_role_does_not_affect_other_roles():
    _ = fresh("a", "b")
    await lobby.on_connect("a")
    await lobby.on_connect("b")
    lobby._session.roles["helm"] = ("a", "Alice")
    lobby._session.roles["weapons"] = ("b", "Bob")

    msg = Message.build("lobby.release_role", {})
    await lobby.handle_lobby_message("a", msg)

    assert lobby._session.roles["helm"] is None
    assert lobby._session.roles["weapons"] == ("b", "Bob")


# ---------------------------------------------------------------------------
# start_game
# ---------------------------------------------------------------------------


async def test_start_game_by_host_broadcasts_game_started():
    m = fresh("a")
    await lobby.on_connect("a")
    m.broadcasts.clear()

    msg = Message.build("lobby.start_game", {"mission_id": "sandbox"})
    await lobby.handle_lobby_message("a", msg)

    game_msg = last_broadcast(m)
    assert game_msg.type == "game.started"
    assert game_msg.payload["mission_id"] == "sandbox"
    assert game_msg.payload["mission_name"] == "Awaiting Orders"
    assert game_msg.payload["briefing_text"] == "All stations report ready."


async def test_start_game_mission_id_is_forwarded():
    m = fresh("a")
    await lobby.on_connect("a")
    m.broadcasts.clear()
    msg = Message.build("lobby.start_game", {"mission_id": "first_contact"})
    await lobby.handle_lobby_message("a", msg)
    assert last_broadcast(m).payload["mission_id"] == "first_contact"


async def test_start_game_by_non_host_returns_permission_error():
    m = fresh("a", "b")
    await lobby.on_connect("a")
    await lobby.on_connect("b")

    m.sent.clear()
    msg = Message.build("lobby.start_game", {"mission_id": "sandbox"})
    await lobby.handle_lobby_message("b", msg)  # b is not host

    err = last_sent_to(m, "b")
    assert err.type == "error.permission"


async def test_start_game_by_non_host_does_not_broadcast():
    m = fresh("a", "b")
    await lobby.on_connect("a")
    await lobby.on_connect("b")
    m.broadcasts.clear()

    msg = Message.build("lobby.start_game", {"mission_id": "sandbox"})
    await lobby.handle_lobby_message("b", msg)

    assert not any(msg.type == "game.started" for msg in m.broadcasts)


# ---------------------------------------------------------------------------
# Late-join: client connects after game has already started
# ---------------------------------------------------------------------------


async def test_late_join_receives_game_started():
    """A client that connects after the game is started gets game.started directly."""
    m = fresh("a")
    await lobby.on_connect("a")
    msg = Message.build("lobby.start_game", {"mission_id": "sandbox"})
    await lobby.handle_lobby_message("a", msg)

    # Simulate a new client (e.g. a station page) connecting after game launch.
    m.add("b")
    m.sent.clear()
    await lobby.on_connect("b")

    sent_types = [t for cid, t_msg in m.sent if cid == "b" for t in [t_msg.type]]
    assert "game.started" in sent_types


async def test_late_join_does_not_receive_lobby_state():
    """A late-joining client skips lobby.state — the game is already in progress."""
    m = fresh("a")
    await lobby.on_connect("a")
    msg = Message.build("lobby.start_game", {"mission_id": "sandbox"})
    await lobby.handle_lobby_message("a", msg)

    m.add("b")
    m.sent.clear()
    m.broadcasts.clear()
    await lobby.on_connect("b")

    assert not any(t_msg.type == "lobby.state" for _, t_msg in m.sent if _ == "b")
