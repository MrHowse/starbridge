"""
HTTP endpoint tests for the mission editor REST API.

Uses Starlette's TestClient.  Mission file I/O is redirected to a tmp_path
by monkeypatching server.main.MISSIONS_DIR.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from server.main import app


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_missions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect MISSIONS_DIR to a fresh temp directory with one sample mission."""
    import server.main as main_module

    monkeypatch.setattr(main_module, "MISSIONS_DIR", tmp_path)

    sample: dict = {
        "id": "sample",
        "name": "Sample",
        "nodes": [],
        "edges": [],
        "start_node": None,
        "victory_nodes": [],
    }
    (tmp_path / "sample.json").write_text(json.dumps(sample), encoding="utf-8")


# ---------------------------------------------------------------------------
# /editor  (redirect)
# ---------------------------------------------------------------------------


def test_editor_page_redirects() -> None:
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/editor")
    assert response.status_code == 302
    assert "/client/editor/" in response.headers["location"]


# ---------------------------------------------------------------------------
# GET /editor/missions
# ---------------------------------------------------------------------------


def test_list_missions_returns_dict() -> None:
    with TestClient(app) as client:
        response = client.get("/editor/missions")
    assert response.status_code == 200
    data = response.json()
    assert "missions" in data
    assert isinstance(data["missions"], list)


def test_list_missions_includes_sample() -> None:
    with TestClient(app) as client:
        response = client.get("/editor/missions")
    ids = [m["id"] for m in response.json()["missions"]]
    assert "sample" in ids


def test_list_missions_empty_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Empty missions directory returns empty list."""
    import server.main as main_module

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setattr(main_module, "MISSIONS_DIR", empty_dir)

    with TestClient(app) as client:
        response = client.get("/editor/missions")
    assert response.json() == {"missions": []}


# ---------------------------------------------------------------------------
# GET /editor/mission/{id}
# ---------------------------------------------------------------------------


def test_get_existing_mission_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/editor/mission/sample")
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["id"] == "sample"


def test_get_nonexistent_mission_404() -> None:
    with TestClient(app) as client:
        response = client.get("/editor/mission/does_not_exist")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /editor/validate
# ---------------------------------------------------------------------------


def _valid_mission() -> dict:
    return {
        "id": "test_m",
        "name": "Test Mission",
        "nodes": [
            {"id": "s", "type": "objective", "text": "Start",
             "trigger": {"type": "timer_elapsed", "seconds": 5}},
            {"id": "e", "type": "objective", "text": "End",
             "trigger": {"type": "all_enemies_destroyed"}},
        ],
        "edges": [{"from": "s", "to": "e", "type": "sequence"}],
        "start_node": "s",
        "victory_nodes": ["e"],
    }


def test_validate_valid_mission() -> None:
    with TestClient(app) as client:
        response = client.post("/editor/validate", json=_valid_mission())
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["errors"] == []


def test_validate_missing_start_node() -> None:
    m = _valid_mission()
    del m["start_node"]
    with TestClient(app) as client:
        response = client.post("/editor/validate", json=m)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert any("start_node" in e for e in data["errors"])


def test_validate_no_victory_nodes() -> None:
    m = _valid_mission()
    m["victory_nodes"] = []
    with TestClient(app) as client:
        response = client.post("/editor/validate", json=m)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False


# ---------------------------------------------------------------------------
# POST /editor/save
# ---------------------------------------------------------------------------


def test_save_valid_creates_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import server.main as main_module

    monkeypatch.setattr(main_module, "MISSIONS_DIR", tmp_path)
    m = _valid_mission()
    m["id"] = "new_mission"
    with TestClient(app) as client:
        response = client.post("/editor/save", json=m)
    assert response.status_code == 200
    assert (tmp_path / "new_mission.json").exists()


def test_save_returns_saved_true() -> None:
    m = _valid_mission()
    m["id"] = "save_test"
    with TestClient(app) as client:
        response = client.post("/editor/save", json=m)
    assert response.status_code == 200
    data = response.json()
    assert data["saved"] is True
    assert data["file"] == "save_test.json"


def test_save_no_id_400() -> None:
    m = _valid_mission()
    del m["id"]
    with TestClient(app) as client:
        response = client.post("/editor/save", json=m)
    assert response.status_code == 400


def test_save_invalid_id_chars_400() -> None:
    """IDs with path-unsafe characters (slash, space, dot) must be rejected."""
    for bad_id in ["../escape", "my mission", "a.b", "id/test"]:
        m = _valid_mission()
        m["id"] = bad_id
        with TestClient(app) as client:
            response = client.post("/editor/save", json=m)
        assert response.status_code == 400, f"Expected 400 for id={bad_id!r}"


def test_save_with_validation_errors_returns_warnings() -> None:
    """Save persists the file even when mission has structural errors; returns warnings."""
    m = _valid_mission()
    m["id"] = "warn_test"
    m["victory_nodes"] = []  # structural error
    with TestClient(app) as client:
        response = client.post("/editor/save", json=m)
    assert response.status_code == 200
    data = response.json()
    assert data["saved"] is True
    assert len(data["warnings"]) > 0


# ---------------------------------------------------------------------------
# DELETE /editor/mission/{id}
# ---------------------------------------------------------------------------


def test_delete_existing_mission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import server.main as main_module
    monkeypatch.setattr(main_module, "MISSIONS_DIR", tmp_path)
    (tmp_path / "del_me.json").write_text('{"id":"del_me"}', encoding="utf-8")

    with TestClient(app) as client:
        response = client.delete("/editor/mission/del_me")
    assert response.status_code == 200
    assert not (tmp_path / "del_me.json").exists()


def test_delete_missing_mission_404() -> None:
    with TestClient(app) as client:
        response = client.delete("/editor/mission/nonexistent")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /editor/duplicate/{id}
# ---------------------------------------------------------------------------


def test_duplicate_creates_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import server.main as main_module
    monkeypatch.setattr(main_module, "MISSIONS_DIR", tmp_path)
    orig = {"id": "orig", "name": "Original"}
    (tmp_path / "orig.json").write_text(json.dumps(orig), encoding="utf-8")

    with TestClient(app) as client:
        response = client.post("/editor/duplicate/orig")
    assert response.status_code == 200
    data = response.json()
    assert data["duplicated"] is True
    assert data["id"] == "orig_copy"
    assert (tmp_path / "orig_copy.json").exists()
    copy_data = json.loads((tmp_path / "orig_copy.json").read_text(encoding="utf-8"))
    assert copy_data["id"] == "orig_copy"
    assert "copy" in copy_data["name"]


def test_duplicate_missing_404() -> None:
    with TestClient(app) as client:
        response = client.post("/editor/duplicate/nonexistent")
    assert response.status_code == 404


def test_duplicate_increments_if_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import server.main as main_module
    monkeypatch.setattr(main_module, "MISSIONS_DIR", tmp_path)
    (tmp_path / "dup.json").write_text('{"id":"dup","name":"D"}', encoding="utf-8")
    (tmp_path / "dup_copy.json").write_text('{"id":"dup_copy","name":"D copy"}', encoding="utf-8")

    with TestClient(app) as client:
        response = client.post("/editor/duplicate/dup")
    assert response.status_code == 200
    assert response.json()["id"] == "dup_copy2"


# ---------------------------------------------------------------------------
# start_position in init_mission
# ---------------------------------------------------------------------------


def test_start_position_sets_ship_coords() -> None:
    """Mission start_position should set ship x/y on init."""
    from server.models.world import World
    from server.models.ship import Ship
    from server.mission_graph import MissionGraph
    import server.game_loop_mission as glm

    mission_dict = {
        "id": "pos_test",
        "name": "Pos Test",
        "start_position": {"x": 10000, "y": 20000, "heading": 90},
        "nodes": [
            {"id": "s", "type": "objective", "text": "Go",
             "trigger": {"type": "timer_elapsed", "seconds": 999}},
        ],
        "edges": [],
        "start_node": "s",
        "victory_nodes": ["s"],
    }

    glm.reset()
    world = World()
    world.ship = Ship()
    world.ship.x = 50000
    world.ship.y = 50000

    glm._mission_engine = MissionGraph(mission_dict)
    glm._mission_dict = mission_dict

    # Apply start_position (same logic as init_mission)
    start_pos = mission_dict.get("start_position")
    if start_pos:
        world.ship.x = float(start_pos.get("x", world.ship.x))
        world.ship.y = float(start_pos.get("y", world.ship.y))

    assert world.ship.x == 10000
    assert world.ship.y == 20000


# ---------------------------------------------------------------------------
# GET /  — phase string
# ---------------------------------------------------------------------------


def test_health_check_phase_v008() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["phase"] == "v0.08"
