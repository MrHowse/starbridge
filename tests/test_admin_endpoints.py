"""
Tests for admin REST endpoints — v0.04h.

Uses fastapi.testclient.TestClient and monkeypatches game_loop functions
so tests don't require a running asyncio event loop.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

import server.admin as _admin
import server.game_loop as _gl


# ---------------------------------------------------------------------------
# Fixture: isolate admin + game_loop state for each test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_admin():
    """Clear engagement tracking between tests."""
    _admin.reset()
    yield
    _admin.reset()


@pytest.fixture()
def client():
    """Return a TestClient wired to the FastAPI app."""
    from server.main import app
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# /admin redirect
# ---------------------------------------------------------------------------


def test_admin_redirect(client):
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 302
    assert "/client/admin/" in r.headers["location"]


# ---------------------------------------------------------------------------
# GET /admin/state
# ---------------------------------------------------------------------------


def test_admin_state_returns_structure(client):
    r = client.get("/admin/state")
    assert r.status_code == 200
    data = r.json()
    assert "engagement" in data
    assert "ship" in data
    assert "paused" in data
    assert "running" in data


def test_admin_state_engagement_has_all_roles(client):
    r = client.get("/admin/state")
    eng = r.json()["engagement"]
    for role in _admin.ALL_STATION_ROLES:
        assert role in eng


def test_admin_state_offline_when_no_interaction(client):
    r = client.get("/admin/state")
    eng = r.json()["engagement"]
    assert eng["helm"]["status"] == "offline"


# ---------------------------------------------------------------------------
# POST /admin/pause  (no game running)
# ---------------------------------------------------------------------------


def test_admin_pause_no_game_returns_409(client):
    r = client.post("/admin/pause")
    assert r.status_code == 409


def test_admin_resume_no_game_returns_409(client):
    r = client.post("/admin/resume")
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# POST /admin/pause / /admin/resume (with running game mock)
# ---------------------------------------------------------------------------


def test_admin_pause_when_running(client):
    with patch.object(_gl, "is_running", return_value=True), \
         patch.object(_gl, "pause") as mock_pause, \
         patch("server.main.manager") as mock_mgr:
        mock_mgr.broadcast = AsyncMock()
        r = client.post("/admin/pause")
    assert r.status_code == 200
    assert r.json()["paused"] is True
    mock_pause.assert_called_once()


def test_admin_resume_when_running(client):
    with patch.object(_gl, "is_running", return_value=True), \
         patch.object(_gl, "resume") as mock_resume, \
         patch("server.main.manager") as mock_mgr:
        mock_mgr.broadcast = AsyncMock()
        r = client.post("/admin/resume")
    assert r.status_code == 200
    assert r.json()["paused"] is False
    mock_resume.assert_called_once()


# ---------------------------------------------------------------------------
# POST /admin/annotate
# ---------------------------------------------------------------------------


def test_admin_annotate_missing_role(client):
    r = client.post("/admin/annotate", json={"message": "hello"})
    assert r.status_code == 400


def test_admin_annotate_missing_message(client):
    r = client.post("/admin/annotate", json={"role": "helm"})
    assert r.status_code == 400


def test_admin_annotate_sends_to_role(client):
    with patch("server.main.manager") as mock_mgr:
        mock_mgr.broadcast_to_roles = AsyncMock()
        r = client.post("/admin/annotate", json={"role": "helm", "message": "Good work"})
    assert r.status_code == 200
    assert r.json()["sent"] is True
    mock_mgr.broadcast_to_roles.assert_called_once()
    args = mock_mgr.broadcast_to_roles.call_args
    assert args[0][0] == ["helm"]


# ---------------------------------------------------------------------------
# POST /admin/broadcast
# ---------------------------------------------------------------------------


def test_admin_broadcast_missing_message(client):
    r = client.post("/admin/broadcast", json={})
    assert r.status_code == 400


def test_admin_broadcast_sends_to_all(client):
    with patch("server.main.manager") as mock_mgr:
        mock_mgr.broadcast = AsyncMock()
        r = client.post("/admin/broadcast", json={"message": "All hands!"})
    assert r.status_code == 200
    assert r.json()["sent"] is True
    mock_mgr.broadcast.assert_called_once()


# ---------------------------------------------------------------------------
# POST /admin/difficulty
# ---------------------------------------------------------------------------


def test_admin_difficulty_missing_preset(client):
    r = client.post("/admin/difficulty", json={})
    assert r.status_code == 400


def test_admin_difficulty_invalid_preset(client):
    r = client.post("/admin/difficulty", json={"preset": "extreme"})
    assert r.status_code == 400


def test_admin_difficulty_valid_preset(client):
    r = client.post("/admin/difficulty", json={"preset": "cadet"})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /admin/save (no game running)
# ---------------------------------------------------------------------------


def test_admin_save_no_game_returns_409(client):
    r = client.post("/admin/save")
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# admin.py unit tests
# ---------------------------------------------------------------------------


def test_update_interaction_marks_active():
    import time
    _admin.update_interaction("helm")
    status = _admin.get_engagement_status("helm")
    assert status == "active"


def test_get_engagement_offline_if_never_interacted():
    assert _admin.get_engagement_status("science") == "offline"


def test_build_engagement_report_all_roles():
    report = _admin.build_engagement_report()
    assert set(report.keys()) == set(_admin.ALL_STATION_ROLES)
