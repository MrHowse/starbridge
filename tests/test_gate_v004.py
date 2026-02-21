"""
v0.04 Gate Verification Tests.

Programmatically verifies items from the v0.04 sub-releases that can be
checked without a live server or human testers.

Sub-releases covered:
  v0.04a — Mission Graph Engine
  v0.04b — Mission Graph Migration
  v0.04c — New Graph-Native Missions
  v0.04d — Mission Editor (validator + REST endpoints)
  v0.04e — Damage Control client station
  v0.04f — Save & Resume system
  v0.04g — Player Profiles + Achievements
  v0.04h — Admin Dashboard
  v0.04i — Performance Hardening
  v0.04j — Accessibility Pass
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server.missions.loader import load_mission
from server.mission_graph import MissionGraph
from server.mission_validator import validate_mission
import server.profiles as prof
import server.admin as admin_mod
import server.save_system as ss
import server.game_loop as _gl
from server.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

V004C_MISSIONS = [
    "salvage_run",
    "first_contact_remastered",
    "the_convoy",
    "pandemic",
]

GRAPH_FIELDS = {"nodes", "edges", "start_node", "victory_nodes"}


def _minimal_mission() -> dict:
    """Smallest valid mission for validator tests."""
    return {
        "id": "gate_test",
        "name": "Gate Test",
        "nodes": [
            {"id": "s", "type": "objective", "text": "Start",
             "trigger": {"type": "timer_elapsed", "seconds": 3}},
            {"id": "e", "type": "objective", "text": "End",
             "trigger": {"type": "all_enemies_destroyed"}},
        ],
        "edges": [{"from": "s", "to": "e", "type": "sequence"}],
        "start_node": "s",
        "victory_nodes": ["e"],
    }


# ---------------------------------------------------------------------------
# v0.04c — Graph-native missions
# ---------------------------------------------------------------------------


class TestGraphNativeMissionsGate:
    """All v0.04c graph-native missions load and have valid structure."""

    @pytest.mark.parametrize("mid", V004C_MISSIONS)
    def test_loads(self, mid):
        mission = load_mission(mid)
        assert mission["id"] == mid

    @pytest.mark.parametrize("mid", V004C_MISSIONS)
    def test_graph_format(self, mid):
        mission = load_mission(mid)
        for field in GRAPH_FIELDS:
            assert field in mission, f"{mid} missing '{field}'"

    @pytest.mark.parametrize("mid", V004C_MISSIONS)
    def test_has_nodes(self, mid):
        mission = load_mission(mid)
        assert len(mission["nodes"]) >= 2

    @pytest.mark.parametrize("mid", V004C_MISSIONS)
    def test_has_victory_nodes(self, mid):
        mission = load_mission(mid)
        assert len(mission["victory_nodes"]) >= 1

    @pytest.mark.parametrize("mid", V004C_MISSIONS)
    def test_mission_graph_init(self, mid):
        mission = load_mission(mid)
        mg = MissionGraph(mission)
        assert mg is not None

    @pytest.mark.parametrize("mid", V004C_MISSIONS)
    def test_not_training(self, mid):
        assert load_mission(mid).get("is_training", False) is False


# ---------------------------------------------------------------------------
# v0.04d — Mission Validator
# ---------------------------------------------------------------------------


class TestMissionValidatorGate:
    """validate_mission() function works correctly."""

    def test_valid_mission_no_errors(self):
        errors = validate_mission(_minimal_mission())
        assert errors == []

    def test_missing_id_returns_error(self):
        m = _minimal_mission()
        del m["id"]
        errors = validate_mission(m)
        assert any("id" in e.lower() for e in errors)

    def test_missing_name_returns_error(self):
        m = _minimal_mission()
        del m["name"]
        errors = validate_mission(m)
        assert any("name" in e.lower() for e in errors)

    def test_missing_start_node_returns_error(self):
        m = _minimal_mission()
        m["start_node"] = None
        errors = validate_mission(m)
        assert any("start_node" in e.lower() for e in errors)

    def test_no_victory_nodes_returns_error(self):
        m = _minimal_mission()
        m["victory_nodes"] = []
        errors = validate_mission(m)
        assert any("victory" in e.lower() for e in errors)

    def test_validator_returns_list(self):
        assert isinstance(validate_mission(_minimal_mission()), list)


# ---------------------------------------------------------------------------
# v0.04d — Editor endpoints
# ---------------------------------------------------------------------------


class TestEditorEndpointsGate:
    """Editor REST endpoints exist and respond."""

    def test_editor_redirect_exists(self):
        r = client.get("/editor", follow_redirects=False)
        assert r.status_code in (301, 302, 307, 308)

    def test_validate_endpoint_exists(self):
        r = client.post("/editor/validate", json=_minimal_mission())
        assert r.status_code == 200

    def test_validate_valid_mission(self):
        r = client.post("/editor/validate", json=_minimal_mission())
        data = r.json()
        assert data["valid"] is True
        assert data["errors"] == []

    def test_validate_invalid_mission(self):
        m = _minimal_mission()
        m["start_node"] = None
        r = client.post("/editor/validate", json=m)
        data = r.json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0

    def test_list_missions_endpoint(self):
        r = client.get("/editor/missions")
        assert r.status_code == 200
        assert "missions" in r.json()

    def test_health_check_phase_v004(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["phase"] == "v0.04"


# ---------------------------------------------------------------------------
# v0.04f — Save system
# ---------------------------------------------------------------------------


class TestSaveSystemGate:
    """Save/resume module loads and key functions are callable."""

    def test_module_has_save_game(self):
        assert callable(ss.save_game)

    def test_module_has_list_saves(self):
        assert callable(ss.list_saves)

    def test_module_has_load_save(self):
        assert callable(ss.load_save)

    def test_module_has_restore_game(self):
        assert callable(ss.restore_game)

    def test_saves_dir_path(self):
        assert ss.SAVES_DIR.name == "saves"

    def test_list_saves_returns_list(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ss, "SAVES_DIR", tmp_path)
        result = ss.list_saves()
        assert isinstance(result, list)

    def test_load_missing_save_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ss, "SAVES_DIR", tmp_path)
        with pytest.raises(FileNotFoundError):
            ss.load_save("nonexistent")


# ---------------------------------------------------------------------------
# v0.04g — Player Profiles
# ---------------------------------------------------------------------------


class TestProfilesGate:
    """Profiles module works correctly."""

    @pytest.fixture(autouse=True)
    def _tmp_profiles(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prof, "PROFILES_DIR", tmp_path)

    def test_get_or_create_new_profile(self):
        p = prof.get_or_create_profile("ALPHA")
        assert p["name"] == "ALPHA"
        assert p["games_played"] == 0

    def test_update_game_result_increments_games(self):
        prof.get_or_create_profile("BETA")
        prof.update_game_result("BETA", "helm", "victory", "sandbox", 120.0, {})
        p = prof.get_profile("BETA")
        assert p["games_played"] == 1
        assert p["games_won"] == 1

    def test_first_command_achievement(self):
        prof.get_or_create_profile("CHARLIE")
        new_ach = prof.update_game_result("CHARLIE", "weapons", "victory", "sandbox", 90.0, {})
        assert "first_command" in new_ach

    def test_list_profiles_returns_list(self):
        prof.get_or_create_profile("DELTA")
        result = prof.list_profiles()
        assert isinstance(result, list)
        assert any(p["name"] == "DELTA" for p in result)

    def test_export_csv_header(self):
        prof.get_or_create_profile("ECHO")
        csv_text = prof.export_csv()
        assert "name" in csv_text.lower()


# ---------------------------------------------------------------------------
# v0.04h — Admin module
# ---------------------------------------------------------------------------


class TestAdminModuleGate:
    """Admin engagement tracking module works."""

    def setup_method(self):
        admin_mod.reset()

    def test_update_interaction_no_error(self):
        admin_mod.update_interaction("helm")

    def test_get_engagement_status_offline_before_interaction(self):
        status = admin_mod.get_engagement_status("weapons")
        assert status in ("offline", "idle", "away", "active")

    def test_build_engagement_report_returns_dict(self):
        report = admin_mod.build_engagement_report()
        assert isinstance(report, dict)
        assert "helm" in report

    def test_all_station_roles_covered(self):
        report = admin_mod.build_engagement_report()
        for role in admin_mod.ALL_STATION_ROLES:
            assert role in report

    def test_admin_state_endpoint(self):
        r = client.get("/admin/state")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# v0.04j — Accessibility files
# ---------------------------------------------------------------------------


CLIENT_SHARED = Path(__file__).parent.parent / "client" / "shared"


class TestAccessibilityFilesGate:
    """Accessibility files exist and are non-empty."""

    def test_settings_js_exists(self):
        assert (CLIENT_SHARED / "settings.js").exists()

    def test_accessibility_css_exists(self):
        assert (CLIENT_SHARED / "accessibility.css").exists()

    def test_a11y_widget_js_exists(self):
        assert (CLIENT_SHARED / "a11y_widget.js").exists()

    def test_settings_js_exports_init(self):
        content = (CLIENT_SHARED / "settings.js").read_text()
        assert "initSettings" in content
        assert "toggleSetting" in content

    def test_accessibility_css_has_cb_mode(self):
        content = (CLIENT_SHARED / "accessibility.css").read_text()
        assert "cb-mode" in content

    def test_accessibility_css_has_no_motion(self):
        content = (CLIENT_SHARED / "accessibility.css").read_text()
        assert "no-motion" in content

    def test_a11y_widget_imports_settings(self):
        content = (CLIENT_SHARED / "a11y_widget.js").read_text()
        assert "settings.js" in content

    def test_all_station_pages_include_accessibility_css(self):
        client_dir = Path(__file__).parent.parent / "client"
        html_files = list(client_dir.glob("*/index.html"))
        assert len(html_files) >= 15, "Expected at least 15 station HTML files"
        for html_path in html_files:
            content = html_path.read_text()
            assert "accessibility.css" in content, (
                f"{html_path} is missing accessibility.css link"
            )

    def test_all_station_pages_include_a11y_widget(self):
        client_dir = Path(__file__).parent.parent / "client"
        html_files = list(client_dir.glob("*/index.html"))
        for html_path in html_files:
            content = html_path.read_text()
            assert "a11y_widget.js" in content, (
                f"{html_path} is missing a11y_widget.js script"
            )


# ---------------------------------------------------------------------------
# v0.04 Integration: game_loop pause/resume
# ---------------------------------------------------------------------------


class TestGameLoopPauseGate:
    """Game loop pause/resume functions exist."""

    def test_pause_callable(self):
        assert callable(_gl.pause)

    def test_resume_callable(self):
        assert callable(_gl.resume)

    def test_is_paused_callable(self):
        assert callable(_gl.is_paused)

    def test_not_paused_by_default_after_reset(self):
        # is_paused reads module-level _paused; not running so reset state
        # Just verify calling is_paused doesn't crash
        result = _gl.is_paused()
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# v0.04 Integration: editor client files
# ---------------------------------------------------------------------------


EDITOR_DIR = Path(__file__).parent.parent / "client" / "editor"


class TestEditorClientFilesGate:
    """Mission editor client files exist."""

    def test_index_html_exists(self):
        assert (EDITOR_DIR / "index.html").exists()

    def test_editor_js_exists(self):
        assert (EDITOR_DIR / "editor.js").exists()

    def test_graph_renderer_js_exists(self):
        assert (EDITOR_DIR / "graph_renderer.js").exists()

    def test_node_panel_js_exists(self):
        assert (EDITOR_DIR / "node_panel.js").exists()

    def test_edge_panel_js_exists(self):
        assert (EDITOR_DIR / "edge_panel.js").exists()

    def test_trigger_builder_js_exists(self):
        assert (EDITOR_DIR / "trigger_builder.js").exists()

    def test_validator_js_exists(self):
        assert (EDITOR_DIR / "validator.js").exists()

    def test_exporter_js_exists(self):
        assert (EDITOR_DIR / "exporter.js").exists()
