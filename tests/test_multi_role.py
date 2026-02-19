"""Tests for multi-role support in lobby.py.

A single connection can claim multiple roles simultaneously using
LobbyClaimRolePayload(additional=True). Without additional=True, the
previous role is released (existing behaviour).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from server import lobby
from server.models.messages import LobbyClaimRolePayload, Message


# ---------------------------------------------------------------------------
# Helpers (mirrors test_lobby.py setup)
# ---------------------------------------------------------------------------


class MockManager:
    def __init__(self) -> None:
        self.sent: list[tuple[str, Message]] = []
        self.broadcast_msgs: list[Message]   = []
        self.tags: dict[str, dict] = {}

    async def send(self, connection_id: str, message: Message) -> None:
        self.sent.append((connection_id, message))

    async def broadcast(self, message: Message) -> None:
        self.broadcast_msgs.append(message)

    def tag(self, connection_id: str, **kwargs: object) -> None:
        if connection_id not in self.tags:
            self.tags[connection_id] = {}
        self.tags[connection_id].update(kwargs)

    def all_ids(self) -> list[str]:
        return ["conn_a"]


@pytest.fixture(autouse=True)
def fresh_lobby():
    manager = MockManager()
    lobby.init(manager)
    return manager


# ---------------------------------------------------------------------------
# single-role mode (default): releases previous role
# ---------------------------------------------------------------------------


async def test_single_role_releases_previous():
    await lobby.on_connect("conn_a")
    await lobby.handle_lobby_message(
        "conn_a",
        Message.build("lobby.claim_role", {"role": "helm", "player_name": "Alice"}),
    )
    await lobby.handle_lobby_message(
        "conn_a",
        Message.build("lobby.claim_role", {"role": "weapons", "player_name": "Alice"}),
    )
    # helm should be released, weapons should be taken
    assert lobby._session.roles["helm"] is None
    assert lobby._session.roles["weapons"] is not None
    assert lobby._session.roles["weapons"][0] == "conn_a"


# ---------------------------------------------------------------------------
# multi-role mode (additional=True): keeps previous role
# ---------------------------------------------------------------------------


async def test_additional_role_keeps_previous():
    await lobby.on_connect("conn_a")
    await lobby.handle_lobby_message(
        "conn_a",
        Message.build("lobby.claim_role", {"role": "helm", "player_name": "Alice"}),
    )
    await lobby.handle_lobby_message(
        "conn_a",
        Message.build("lobby.claim_role", {
            "role": "weapons",
            "player_name": "Alice",
            "additional": True,
        }),
    )
    # Both roles should be held by conn_a
    assert lobby._session.roles["helm"] is not None
    assert lobby._session.roles["helm"][0] == "conn_a"
    assert lobby._session.roles["weapons"] is not None
    assert lobby._session.roles["weapons"][0] == "conn_a"


async def test_additional_role_three_roles():
    await lobby.on_connect("conn_a")
    for role in ("helm", "weapons", "science"):
        await lobby.handle_lobby_message(
            "conn_a",
            Message.build("lobby.claim_role", {
                "role": role,
                "player_name": "Alice",
                "additional": True,
            }),
        )
    held = lobby._find_connection_roles("conn_a")
    assert set(held) == {"helm", "weapons", "science"}


async def test_find_connection_roles_returns_all_held():
    await lobby.on_connect("conn_a")
    for role in ("helm", "engineering"):
        await lobby.handle_lobby_message(
            "conn_a",
            Message.build("lobby.claim_role", {
                "role": role,
                "player_name": "Bob",
                "additional": True,
            }),
        )
    roles = lobby._find_connection_roles("conn_a")
    assert "helm" in roles
    assert "engineering" in roles


async def test_disconnect_releases_all_held_roles():
    await lobby.on_connect("conn_a")
    for role in ("helm", "weapons"):
        await lobby.handle_lobby_message(
            "conn_a",
            Message.build("lobby.claim_role", {
                "role": role,
                "player_name": "Alice",
                "additional": True,
            }),
        )
    await lobby.on_disconnect("conn_a")
    assert lobby._session.roles["helm"] is None
    assert lobby._session.roles["weapons"] is None


async def test_additional_false_switches_role():
    """additional=False (default) should release old role, claim new one."""
    await lobby.on_connect("conn_a")
    await lobby.handle_lobby_message(
        "conn_a",
        Message.build("lobby.claim_role", {"role": "helm", "player_name": "Alice"}),
    )
    await lobby.handle_lobby_message(
        "conn_a",
        Message.build("lobby.claim_role", {
            "role": "captain",
            "player_name": "Alice",
            "additional": False,
        }),
    )
    assert lobby._session.roles["helm"] is None
    assert lobby._session.roles["captain"][0] == "conn_a"  # type: ignore[index]
