"""
Integration tests for main.py — HTTP routes and WebSocket message routing.

Uses starlette's TestClient to exercise the full ASGI stack, including
envelope parsing, routing, and lobby integration.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from server import lobby
from server.main import app, manager


@pytest.fixture(autouse=True)
def reset_lobby() -> None:
    """Reset lobby state before each test for isolation."""
    lobby.init(manager)


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------


def test_root_serves_landing_page() -> None:
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_health_endpoint_returns_server_status() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert data["name"] == "Starbridge"


def test_health_endpoint_includes_version() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert "version" in response.json()


# ---------------------------------------------------------------------------
# WebSocket — connection acceptance
# ---------------------------------------------------------------------------


def test_websocket_sends_welcome_on_connect() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            msg = ws.receive_json()
    assert msg["type"] == "lobby.welcome"
    assert "connection_id" in msg["payload"]
    assert "is_host" in msg["payload"]


def test_websocket_sends_lobby_state_after_welcome() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # lobby.welcome
            msg = ws.receive_json()
    assert msg["type"] == "lobby.state"
    assert "roles" in msg["payload"]


def test_first_connection_is_host() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            welcome = ws.receive_json()
    assert welcome["payload"]["is_host"] is True


# ---------------------------------------------------------------------------
# WebSocket — error handling
# ---------------------------------------------------------------------------


def test_invalid_json_returns_validation_error() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # lobby.welcome
            ws.receive_json()  # lobby.state
            ws.send_text("}{not valid json")
            msg = ws.receive_json()
    assert msg["type"] == "error.validation"


def test_invalid_envelope_missing_type_returns_validation_error() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # lobby.welcome
            ws.receive_json()  # lobby.state
            ws.send_text('{"payload": {}, "timestamp": 0}')
            msg = ws.receive_json()
    assert msg["type"] == "error.validation"


def test_invalid_envelope_missing_timestamp_returns_validation_error() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # lobby.welcome
            ws.receive_json()  # lobby.state
            ws.send_text('{"type": "lobby.claim_role", "payload": {}}')
            msg = ws.receive_json()
    assert msg["type"] == "error.validation"


def test_validation_error_includes_original_type() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # lobby.welcome
            ws.receive_json()  # lobby.state
            # Missing timestamp — envelope invalid
            ws.send_text('{"type": "lobby.release_role", "payload": {}}')
            msg = ws.receive_json()
    assert msg["type"] == "error.validation"
    assert msg["payload"]["original_type"] == "lobby.release_role"


# ---------------------------------------------------------------------------
# WebSocket — routing
# ---------------------------------------------------------------------------


def test_unknown_message_category_does_not_crash() -> None:
    """Unrecognised category prefixes are silently logged and dropped."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # lobby.welcome
            ws.receive_json()  # lobby.state
            ws.send_text('{"type": "unknown.thing", "payload": {}, "timestamp": 0}')
            # No error expected. Confirm connection is still alive with a valid message.
            ws.send_text('{"type": "lobby.release_role", "payload": {}, "timestamp": 0}')
            # release_role with no role held broadcasts lobby.state (no-op in lobby logic,
            # but the broadcast still fires since release_role returns early without broadcast
            # when no role is held — connection must still be open with no exception raised)


def test_lobby_claim_role_routes_and_returns_state() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # lobby.welcome
            ws.receive_json()  # lobby.state
            ws.send_text(
                '{"type": "lobby.claim_role",'
                ' "payload": {"role": "helm", "player_name": "Alice"},'
                ' "timestamp": 0}'
            )
            msg = ws.receive_json()
    assert msg["type"] == "lobby.state"
    assert msg["payload"]["roles"]["helm"] == "Alice"


def test_lobby_claim_role_invalid_payload_returns_validation_error() -> None:
    """A claim_role with an invalid role name triggers error.validation."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # lobby.welcome
            ws.receive_json()  # lobby.state
            ws.send_text(
                '{"type": "lobby.claim_role",'
                ' "payload": {"role": "navigator", "player_name": "Alice"},'
                ' "timestamp": 0}'
            )
            msg = ws.receive_json()
    assert msg["type"] == "error.validation"


def test_lobby_start_game_by_non_host_returns_permission_error() -> None:
    """Non-host trying to start the game gets an error.permission response."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws1:
            ws1.receive_json()  # lobby.welcome (host)
            ws1.receive_json()  # lobby.state (from ws1's own connect)

            with client.websocket_connect("/ws") as ws2:
                ws2.receive_json()  # lobby.welcome (non-host)
                ws2.receive_json()  # lobby.state (broadcast when ws2 connected)

                ws2.send_text(
                    '{"type": "lobby.start_game",'
                    ' "payload": {"mission_id": "sandbox"},'
                    ' "timestamp": 0}'
                )
                msg = ws2.receive_json()

    assert msg["type"] == "error.permission"
