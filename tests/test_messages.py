"""Tests for WebSocket message models and envelope validation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.models.messages import (
    GameOverPayload,
    GameStartedPayload,
    LobbyClaimRolePayload,
    LobbyStartGamePayload,
    Message,
    validate_payload,
)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def test_envelope_valid():
    msg = Message(type="lobby.claim_role", payload={}, timestamp=1_700_000_000.0)
    assert msg.type == "lobby.claim_role"
    assert msg.tick is None
    assert msg.payload == {}


def test_envelope_with_tick():
    msg = Message(type="game.tick", payload={}, tick=42, timestamp=1_700_000_000.0)
    assert msg.tick == 42


def test_envelope_missing_type():
    with pytest.raises(ValidationError):
        Message(payload={}, timestamp=1_700_000_000.0)  # type: ignore[call-arg]


def test_envelope_missing_timestamp():
    with pytest.raises(ValidationError):
        Message(type="lobby.claim_role", payload={})  # type: ignore[call-arg]


def test_envelope_payload_defaults_to_empty_dict():
    msg = Message(type="lobby.release_role", timestamp=1_700_000_000.0)
    assert msg.payload == {}


# ---------------------------------------------------------------------------
# Message.build()
# ---------------------------------------------------------------------------


def test_build_sets_timestamp():
    msg = Message.build("lobby.state", {"roles": {}})
    assert msg.type == "lobby.state"
    assert msg.tick is None
    assert msg.timestamp > 0


def test_build_with_tick():
    msg = Message.build("game.tick", tick=99)
    assert msg.tick == 99


def test_build_empty_payload_when_none_given():
    msg = Message.build("lobby.release_role")
    assert msg.payload == {}


# ---------------------------------------------------------------------------
# Message.to_json()
# ---------------------------------------------------------------------------


def test_to_json_omits_null_tick():
    msg = Message.build("lobby.state")
    json_str = msg.to_json()
    assert "tick" not in json_str


def test_to_json_includes_tick_when_set():
    msg = Message.build("game.tick", tick=5)
    json_str = msg.to_json()
    assert '"tick":5' in json_str


def test_to_json_includes_type():
    msg = Message.build("lobby.error", {"message": "oops"})
    assert "lobby.error" in msg.to_json()


# ---------------------------------------------------------------------------
# Payload schemas
# ---------------------------------------------------------------------------


def test_lobby_claim_role_valid():
    p = LobbyClaimRolePayload(role="helm", player_name="Alice")
    assert p.role == "helm"
    assert p.player_name == "Alice"


def test_lobby_claim_role_invalid_role():
    with pytest.raises(ValidationError):
        LobbyClaimRolePayload(role="navigator", player_name="Bob")  # type: ignore[arg-type]


def test_lobby_claim_role_all_valid_roles():
    for role in ("captain", "helm", "weapons", "engineering", "science"):
        p = LobbyClaimRolePayload(role=role, player_name="X")  # type: ignore[arg-type]
        assert p.role == role


def test_lobby_claim_role_empty_player_name_invalid():
    with pytest.raises(ValidationError):
        LobbyClaimRolePayload(role="helm", player_name="")


def test_lobby_claim_role_blank_player_name_invalid():
    with pytest.raises(ValidationError):
        LobbyClaimRolePayload(role="helm", player_name="   ")


def test_lobby_claim_role_player_name_stripped():
    p = LobbyClaimRolePayload(role="helm", player_name="  Alice  ")
    assert p.player_name == "Alice"


def test_lobby_claim_role_player_name_too_long_invalid():
    with pytest.raises(ValidationError):
        LobbyClaimRolePayload(role="helm", player_name="A" * 21)


def test_lobby_claim_role_player_name_max_length_valid():
    p = LobbyClaimRolePayload(role="helm", player_name="A" * 20)
    assert len(p.player_name) == 20


def test_lobby_start_game_valid():
    p = LobbyStartGamePayload(mission_id="tutorial_01")
    assert p.mission_id == "tutorial_01"


def test_game_over_valid_victory():
    p = GameOverPayload(result="victory", stats={})
    assert p.result == "victory"


def test_game_over_valid_defeat():
    p = GameOverPayload(result="defeat", stats={"kills": 3})
    assert p.result == "defeat"


def test_game_over_invalid_result():
    with pytest.raises(ValidationError):
        GameOverPayload(result="draw", stats={})  # type: ignore[arg-type]


def test_game_started_valid():
    p = GameStartedPayload(
        mission_id="m1", mission_name="First Contact", briefing_text="Good luck."
    )
    assert p.mission_id == "m1"


# ---------------------------------------------------------------------------
# validate_payload()
# ---------------------------------------------------------------------------


def test_validate_payload_known_type_returns_model():
    msg = Message.build("lobby.claim_role", {"role": "helm", "player_name": "Alice"})
    result = validate_payload(msg)
    assert isinstance(result, LobbyClaimRolePayload)
    assert result.role == "helm"


def test_validate_payload_unknown_type_returns_none():
    msg = Message.build("unknown.type", {"foo": "bar"})
    assert validate_payload(msg) is None


def test_validate_payload_invalid_payload_raises():
    msg = Message.build("lobby.claim_role", {"role": "invalid_role", "player_name": "X"})
    with pytest.raises(ValidationError):
        validate_payload(msg)


def test_validate_payload_release_role_no_fields():
    msg = Message.build("lobby.release_role", {})
    result = validate_payload(msg)
    assert result is not None
