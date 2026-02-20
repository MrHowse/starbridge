"""
Tests for v0.03n — Mission Debrief.

Covers:
  - game_logger: get_log_path() before and after stop()
  - game_debrief: parse_log(), compute_debrief(), compute_from_log()
  - per-station stats accumulation
  - awards assignment
  - key moments detection
  - timeline extraction from tick_summary events
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from server import game_logger as gl
from server import game_debrief as gdb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def make_events(*extras: dict) -> list[dict]:
    """Return a minimal valid session log with optional extra events."""
    base = [
        {"tick": 0,  "ts": 0.0,   "cat": "session", "event": "started",    "data": {"mission_id": "test"}},
        {"tick": 10, "ts": 10.0,  "cat": "session", "event": "ended",      "data": {"result": "victory"}},
    ]
    return list(extras) + base


# ---------------------------------------------------------------------------
# game_logger: get_log_path
# ---------------------------------------------------------------------------


class TestGameLoggerGetLogPath:
    def setup_method(self):
        # Reset singleton to a clean state.
        gl._logger = gl.GameLogger()

    def test_returns_none_before_start(self):
        assert gl.get_log_path() is None

    def test_returns_path_while_active(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        gl._logger.start("test_mission", {"p1": "helm"})
        assert gl._logger.get_log_path() is not None
        gl._logger.stop("victory")

    def test_returns_last_path_after_stop(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        gl._logger.start("test_mission", {"p1": "helm"})
        gl._logger.stop("victory")
        # After stop, _log_file is None but _last_log_file should be set.
        assert gl._logger.get_log_path() is not None

    def test_module_level_get_log_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        gl._logger.start("test_mission", {"p1": "helm"})
        path_during = gl.get_log_path()
        gl._logger.stop("victory")
        path_after  = gl.get_log_path()
        assert path_during is not None
        assert path_after  is not None


# ---------------------------------------------------------------------------
# game_debrief: parse_log
# ---------------------------------------------------------------------------


class TestParseLog:
    def test_parses_valid_jsonl(self, tmp_path):
        records = [
            {"tick": 0, "ts": 0.0, "cat": "session", "event": "started", "data": {}},
            {"tick": 5, "ts": 5.0, "cat": "helm",    "event": "heading_changed", "data": {}},
        ]
        p = tmp_path / "test.jsonl"
        _write_jsonl(p, records)
        result = gdb.parse_log(p)
        assert len(result) == 2
        assert result[1]["event"] == "heading_changed"

    def test_skips_blank_lines(self, tmp_path):
        p = tmp_path / "test.jsonl"
        p.write_text('{"tick":0,"ts":0,"cat":"a","event":"b","data":{}}\n\n\n', encoding="utf-8")
        result = gdb.parse_log(p)
        assert len(result) == 1

    def test_skips_malformed_lines(self, tmp_path):
        p = tmp_path / "test.jsonl"
        p.write_text('{"tick":0}\n{bad json\n', encoding="utf-8")
        result = gdb.parse_log(p)
        assert len(result) == 1

    def test_missing_file_returns_empty(self, tmp_path):
        p = tmp_path / "missing.jsonl"
        result = gdb.parse_log(p)
        assert result == []


# ---------------------------------------------------------------------------
# game_debrief: compute_debrief — per-station stats
# ---------------------------------------------------------------------------


class TestComputeDebriefPerStation:
    def test_helm_actions_counted(self):
        events = [
            {"tick": 1, "ts": 1.0, "cat": "helm", "event": "heading_changed", "data": {}},
            {"tick": 2, "ts": 2.0, "cat": "helm", "event": "heading_changed", "data": {}},
            {"tick": 3, "ts": 3.0, "cat": "helm", "event": "throttle_changed", "data": {}},
        ]
        d = gdb.compute_debrief(events)
        assert d["per_station_stats"]["helm"]["total"] == 3
        assert d["per_station_stats"]["helm"]["events"]["heading_changed"] == 2
        assert d["per_station_stats"]["helm"]["events"]["throttle_changed"] == 1

    def test_weapons_actions_counted(self):
        events = [
            {"tick": 1, "ts": 1.0, "cat": "weapons", "event": "beam_fired",      "data": {}},
            {"tick": 2, "ts": 2.0, "cat": "weapons", "event": "beam_fired",      "data": {}},
            {"tick": 3, "ts": 3.0, "cat": "weapons", "event": "torpedo_fired",   "data": {}},
        ]
        d = gdb.compute_debrief(events)
        assert d["per_station_stats"]["weapons"]["total"] == 3
        assert d["per_station_stats"]["weapons"]["events"]["beam_fired"] == 2

    def test_ew_maps_to_electronic_warfare(self):
        events = [
            {"tick": 1, "ts": 1.0, "cat": "ew", "event": "jam_target_set", "data": {}},
        ]
        d = gdb.compute_debrief(events)
        assert "electronic_warfare" in d["per_station_stats"]

    def test_unknown_cat_ignored(self):
        events = [
            {"tick": 1, "ts": 1.0, "cat": "game", "event": "tick_summary", "data": {
                "hull": 80, "x": 50000, "y": 50000,
            }},
        ]
        d = gdb.compute_debrief(events)
        assert "game" not in d["per_station_stats"]

    def test_multiple_stations(self):
        events = [
            {"tick": 1, "ts": 1.0, "cat": "helm",    "event": "heading_changed", "data": {}},
            {"tick": 2, "ts": 2.0, "cat": "weapons",  "event": "beam_fired",     "data": {}},
            {"tick": 3, "ts": 3.0, "cat": "science",  "event": "scan_completed", "data": {}},
        ]
        d = gdb.compute_debrief(events)
        assert len(d["per_station_stats"]) == 3


# ---------------------------------------------------------------------------
# game_debrief: compute_debrief — awards
# ---------------------------------------------------------------------------


class TestComputeDebriefAwards:
    def test_sharpshooter_at_threshold(self):
        events = [
            {"tick": i, "ts": float(i), "cat": "weapons", "event": "beam_fired", "data": {}}
            for i in range(5)
        ]
        d = gdb.compute_debrief(events)
        award_names = [a["award"] for a in d["awards"]]
        assert "Sharpshooter" in award_names

    def test_sharpshooter_below_threshold(self):
        events = [
            {"tick": i, "ts": float(i), "cat": "weapons", "event": "beam_fired", "data": {}}
            for i in range(4)  # only 4, threshold is 5
        ]
        d = gdb.compute_debrief(events)
        award_names = [a["award"] for a in d["awards"]]
        assert "Sharpshooter" not in award_names

    def test_life_saver_at_threshold(self):
        events = [
            {"tick": 1, "ts": 1.0, "cat": "medical", "event": "treatment_started", "data": {}},
        ]
        d = gdb.compute_debrief(events)
        award_names = [a["award"] for a in d["awards"]]
        assert "Life Saver" in award_names

    def test_quick_fix_at_threshold(self):
        events = [
            {"tick": 1, "ts": 1.0, "cat": "engineering", "event": "dct_dispatched", "data": {}},
        ]
        d = gdb.compute_debrief(events)
        award_names = [a["award"] for a in d["awards"]]
        assert "Quick Fix" in award_names

    def test_no_awards_for_empty_log(self):
        d = gdb.compute_debrief([])
        assert d["awards"] == []

    def test_award_has_expected_keys(self):
        events = [
            {"tick": i, "ts": float(i), "cat": "weapons", "event": "beam_fired", "data": {}}
            for i in range(5)
        ]
        d = gdb.compute_debrief(events)
        award = next(a for a in d["awards"] if a["award"] == "Sharpshooter")
        assert "role" in award
        assert "award" in award
        assert "description" in award

    def test_mastermind_award(self):
        events = [
            {"tick": 1, "ts": 1.0, "cat": "tactical", "event": "strike_plan_created", "data": {}},
        ]
        d = gdb.compute_debrief(events)
        award_names = [a["award"] for a in d["awards"]]
        assert "Mastermind" in award_names

    def test_ghost_award(self):
        events = [
            {"tick": 1, "ts": 1.0, "cat": "ew", "event": "jam_target_set", "data": {}},
        ]
        d = gdb.compute_debrief(events)
        award_names = [a["award"] for a in d["awards"]]
        assert "Ghost" in award_names


# ---------------------------------------------------------------------------
# game_debrief: compute_debrief — key moments
# ---------------------------------------------------------------------------


class TestComputeDebriefKeyMoments:
    def test_objective_completed_logged(self):
        events = [
            {"tick": 1, "ts": 15.0, "cat": "mission", "event": "objective_completed",
             "data": {"objective_id": "obj_1"}},
        ]
        d = gdb.compute_debrief(events)
        texts = [m["text"] for m in d["key_moments"]]
        assert any("obj_1" in t for t in texts)

    def test_hull_milestone_75(self):
        events = [
            {"tick": 100, "ts": 10.0, "cat": "game", "event": "tick_summary",
             "data": {"hull": 74.0, "x": 50000, "y": 50000}},
        ]
        d = gdb.compute_debrief(events)
        texts = [m["text"] for m in d["key_moments"]]
        assert any("75%" in t for t in texts)

    def test_hull_milestone_50(self):
        events = [
            {"tick": 100, "ts": 10.0, "cat": "game", "event": "tick_summary",
             "data": {"hull": 49.0, "x": 50000, "y": 50000}},
        ]
        d = gdb.compute_debrief(events)
        texts = [m["text"] for m in d["key_moments"]]
        assert any("50%" in t for t in texts)

    def test_hull_milestone_25(self):
        events = [
            {"tick": 100, "ts": 10.0, "cat": "game", "event": "tick_summary",
             "data": {"hull": 24.0, "x": 50000, "y": 50000}},
        ]
        d = gdb.compute_debrief(events)
        texts = [m["text"] for m in d["key_moments"]]
        assert any("25%" in t for t in texts)

    def test_hull_milestone_not_repeated(self):
        # Two consecutive summaries both below 75% — milestone should appear once.
        events = [
            {"tick": 100, "ts": 10.0, "cat": "game", "event": "tick_summary",
             "data": {"hull": 74.0, "x": 50000, "y": 50000}},
            {"tick": 200, "ts": 20.0, "cat": "game", "event": "tick_summary",
             "data": {"hull": 70.0, "x": 51000, "y": 50000}},
        ]
        d = gdb.compute_debrief(events)
        texts = [m["text"] for m in d["key_moments"]]
        assert texts.count("Hull dropped below 75%") == 1

    def test_boarding_logged(self):
        events = [
            {"tick": 50, "ts": 5.0, "cat": "security", "event": "boarding_started",
             "data": {"intruder_count": 4}},
        ]
        d = gdb.compute_debrief(events)
        texts = [m["text"] for m in d["key_moments"]]
        assert any("Boarding" in t for t in texts)

    def test_session_ended_victory(self):
        events = [
            {"tick": 999, "ts": 120.0, "cat": "session", "event": "ended",
             "data": {"result": "victory"}},
        ]
        d = gdb.compute_debrief(events)
        texts = [m["text"] for m in d["key_moments"]]
        assert any("complete" in t.lower() for t in texts)

    def test_moments_sorted_by_ts(self):
        events = [
            {"tick": 200, "ts": 20.0, "cat": "mission", "event": "objective_completed",
             "data": {"objective_id": "obj_2"}},
            {"tick": 100, "ts": 10.0, "cat": "mission", "event": "objective_completed",
             "data": {"objective_id": "obj_1"}},
        ]
        d = gdb.compute_debrief(events)
        ts_list = [m["ts"] for m in d["key_moments"]]
        assert ts_list == sorted(ts_list)

    def test_no_moments_for_empty_log(self):
        d = gdb.compute_debrief([])
        assert d["key_moments"] == []


# ---------------------------------------------------------------------------
# game_debrief: compute_debrief — timeline
# ---------------------------------------------------------------------------


class TestComputeDebriefTimeline:
    def test_tick_summary_with_xy_added_to_timeline(self):
        events = [
            {"tick": 100, "ts": 10.0, "cat": "game", "event": "tick_summary",
             "data": {"hull": 90.0, "x": 50000, "y": 48000}},
        ]
        d = gdb.compute_debrief(events)
        assert len(d["timeline"]) == 1
        pt = d["timeline"][0]
        assert pt["x"] == 50000
        assert pt["y"] == 48000
        assert pt["ts"] == 10.0
        assert pt["hull"] == 90.0

    def test_tick_summary_without_xy_excluded(self):
        events = [
            {"tick": 100, "ts": 10.0, "cat": "game", "event": "tick_summary",
             "data": {"hull": 90.0}},  # no x/y
        ]
        d = gdb.compute_debrief(events)
        assert d["timeline"] == []

    def test_multiple_snapshots(self):
        events = [
            {"tick": 100, "ts": 10.0, "cat": "game", "event": "tick_summary",
             "data": {"hull": 90.0, "x": 50000, "y": 50000}},
            {"tick": 200, "ts": 20.0, "cat": "game", "event": "tick_summary",
             "data": {"hull": 80.0, "x": 51000, "y": 49000}},
        ]
        d = gdb.compute_debrief(events)
        assert len(d["timeline"]) == 2
        assert d["timeline"][0]["x"] == 50000
        assert d["timeline"][1]["x"] == 51000


# ---------------------------------------------------------------------------
# game_debrief: compute_from_log — end-to-end
# ---------------------------------------------------------------------------


class TestComputeFromLog:
    def test_integration_victory_with_actions(self, tmp_path):
        records = [
            {"tick": 0,   "ts": 0.0,  "cat": "session", "event": "started",  "data": {"mission_id": "t1"}},
            {"tick": 5,   "ts": 5.0,  "cat": "helm",    "event": "heading_changed", "data": {}},
            {"tick": 10,  "ts": 10.0, "cat": "weapons",  "event": "beam_fired",     "data": {}},
            {"tick": 10,  "ts": 10.0, "cat": "weapons",  "event": "beam_fired",     "data": {}},
            {"tick": 10,  "ts": 10.0, "cat": "weapons",  "event": "beam_fired",     "data": {}},
            {"tick": 10,  "ts": 10.0, "cat": "weapons",  "event": "beam_fired",     "data": {}},
            {"tick": 10,  "ts": 10.0, "cat": "weapons",  "event": "beam_fired",     "data": {}},
            {"tick": 100, "ts": 10.0, "cat": "game",     "event": "tick_summary",   "data": {
                "hull": 80.0, "x": 52000, "y": 49000,
            }},
            {"tick": 200, "ts": 99.0, "cat": "mission",  "event": "objective_completed",
             "data": {"objective_id": "obj_final"}},
            {"tick": 999, "ts": 120.0,"cat": "session",  "event": "ended",     "data": {"result": "victory"}},
        ]
        p = tmp_path / "game.jsonl"
        _write_jsonl(p, records)
        d = gdb.compute_from_log(p)

        assert "helm" in d["per_station_stats"]
        assert "weapons" in d["per_station_stats"]
        assert any(a["award"] == "Sharpshooter" for a in d["awards"])
        assert len(d["timeline"]) == 1
        assert any("obj_final" in m["text"] for m in d["key_moments"])
        assert any("complete" in m["text"].lower() for m in d["key_moments"])

    def test_missing_file_returns_empty_structure(self, tmp_path):
        p = tmp_path / "missing.jsonl"
        d = gdb.compute_from_log(p)
        assert d["per_station_stats"] == {}
        assert d["awards"] == []
        assert d["key_moments"] == []
        assert d["timeline"] == []
