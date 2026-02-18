"""Tests for the WebSocket connection manager."""
from __future__ import annotations

from unittest.mock import AsyncMock

from server.connections import ConnectionManager
from server.models.messages import Message


def make_mock_ws() -> AsyncMock:
    """Return a mock WebSocket with accept() and send_text() as AsyncMocks."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------


async def test_connect_calls_accept():
    manager = ConnectionManager()
    ws = make_mock_ws()
    await manager.connect(ws)
    ws.accept.assert_called_once()


async def test_connect_returns_non_empty_id():
    manager = ConnectionManager()
    cid = await manager.connect(make_mock_ws())
    assert cid and isinstance(cid, str)


async def test_connect_increments_count():
    manager = ConnectionManager()
    assert manager.count() == 0
    await manager.connect(make_mock_ws())
    assert manager.count() == 1
    await manager.connect(make_mock_ws())
    assert manager.count() == 2


async def test_connect_returns_unique_ids():
    manager = ConnectionManager()
    ids = [await manager.connect(make_mock_ws()) for _ in range(5)]
    assert len(set(ids)) == 5


async def test_disconnect_removes_connection():
    manager = ConnectionManager()
    cid = await manager.connect(make_mock_ws())
    manager.disconnect(cid)
    assert manager.count() == 0


def test_disconnect_unknown_id_is_safe():
    manager = ConnectionManager()
    manager.disconnect("no-such-id")  # must not raise


# ---------------------------------------------------------------------------
# get / tag
# ---------------------------------------------------------------------------


async def test_get_returns_connection_info():
    manager = ConnectionManager()
    cid = await manager.connect(make_mock_ws())
    info = manager.get(cid)
    assert info is not None
    assert info.connection_id == cid


def test_get_unknown_id_returns_none():
    manager = ConnectionManager()
    assert manager.get("nonexistent") is None


async def test_tag_updates_player_name_and_role():
    manager = ConnectionManager()
    cid = await manager.connect(make_mock_ws())
    manager.tag(cid, player_name="Alice", role="helm")
    info = manager.get(cid)
    assert info is not None
    assert info.player_name == "Alice"
    assert info.role == "helm"


async def test_tag_updates_is_host():
    manager = ConnectionManager()
    cid = await manager.connect(make_mock_ws())
    manager.tag(cid, is_host=True)
    info = manager.get(cid)
    assert info is not None
    assert info.is_host is True


def test_tag_unknown_connection_does_not_raise():
    manager = ConnectionManager()
    manager.tag("nonexistent", role="helm")  # must log warning, not raise


async def test_tag_unknown_field_does_not_raise():
    manager = ConnectionManager()
    cid = await manager.connect(make_mock_ws())
    manager.tag(cid, nonexistent_field="value")  # must log warning, not raise


# ---------------------------------------------------------------------------
# get_by_role
# ---------------------------------------------------------------------------


async def test_get_by_role_returns_matching_connections():
    manager = ConnectionManager()
    cid_h1 = await manager.connect(make_mock_ws())
    cid_h2 = await manager.connect(make_mock_ws())
    cid_w = await manager.connect(make_mock_ws())
    manager.tag(cid_h1, role="helm")
    manager.tag(cid_h2, role="helm")
    manager.tag(cid_w, role="weapons")

    helm = manager.get_by_role("helm")
    assert len(helm) == 2
    assert all(c.role == "helm" for c in helm)


async def test_get_by_role_empty_when_no_match():
    manager = ConnectionManager()
    cid = await manager.connect(make_mock_ws())
    manager.tag(cid, role="captain")
    assert manager.get_by_role("helm") == []


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------


async def test_send_writes_json_to_websocket():
    manager = ConnectionManager()
    ws = make_mock_ws()
    cid = await manager.connect(ws)
    msg = Message.build("lobby.error", {"message": "test"})
    await manager.send(cid, msg)
    ws.send_text.assert_called_once()
    sent = ws.send_text.call_args[0][0]
    assert "lobby.error" in sent


async def test_send_omits_null_tick_in_json():
    manager = ConnectionManager()
    ws = make_mock_ws()
    cid = await manager.connect(ws)
    msg = Message.build("lobby.state")
    await manager.send(cid, msg)
    sent = ws.send_text.call_args[0][0]
    assert "tick" not in sent


async def test_send_unknown_connection_does_not_raise():
    manager = ConnectionManager()
    msg = Message.build("lobby.error", {"message": "x"})
    await manager.send("nonexistent", msg)  # must log warning, not raise


# ---------------------------------------------------------------------------
# broadcast
# ---------------------------------------------------------------------------


async def test_broadcast_sends_to_all():
    manager = ConnectionManager()
    mocks = [make_mock_ws() for _ in range(3)]
    for ws in mocks:
        await manager.connect(ws)
    msg = Message.build("game.tick", tick=1)
    await manager.broadcast(msg)
    for ws in mocks:
        ws.send_text.assert_called_once()


async def test_broadcast_empty_manager_does_not_raise():
    manager = ConnectionManager()
    await manager.broadcast(Message.build("game.tick", tick=1))  # must not raise


# ---------------------------------------------------------------------------
# broadcast_to_roles
# ---------------------------------------------------------------------------


async def test_broadcast_to_roles_sends_only_to_matching_roles():
    manager = ConnectionManager()
    ws_helm = make_mock_ws()
    ws_weapons = make_mock_ws()
    ws_captain = make_mock_ws()

    cid_h = await manager.connect(ws_helm)
    cid_w = await manager.connect(ws_weapons)
    cid_c = await manager.connect(ws_captain)

    manager.tag(cid_h, role="helm")
    manager.tag(cid_w, role="weapons")
    manager.tag(cid_c, role="captain")

    msg = Message.build("game.tick", tick=1)
    await manager.broadcast_to_roles(["helm", "weapons"], msg)

    ws_helm.send_text.assert_called_once()
    ws_weapons.send_text.assert_called_once()
    ws_captain.send_text.assert_not_called()


async def test_broadcast_to_roles_skips_untagged_connections():
    manager = ConnectionManager()
    ws_tagged = make_mock_ws()
    ws_untagged = make_mock_ws()

    cid_t = await manager.connect(ws_tagged)
    await manager.connect(ws_untagged)
    manager.tag(cid_t, role="science")

    await manager.broadcast_to_roles(["science"], Message.build("game.tick", tick=1))

    ws_tagged.send_text.assert_called_once()
    ws_untagged.send_text.assert_not_called()
