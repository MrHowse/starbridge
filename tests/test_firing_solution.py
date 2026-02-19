"""Tests for the Firing Solution puzzle (c.8 / v0.02g)."""
from __future__ import annotations

import math
import pytest

from server.puzzles.firing_solution import (
    FiringSolutionPuzzle,
    _compute_intercept_bearing,
    _DIFFICULTY_PARAMS,
    TORPEDO_SPEED,
    _ASSIST_TOLERANCE_BONUS,
)
from server.puzzles.engine import PuzzleEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_puzzle(difficulty: int = 2) -> FiringSolutionPuzzle:
    p = FiringSolutionPuzzle(
        puzzle_id="fs_test",
        label="fs_label",
        station="weapons",
        difficulty=difficulty,
        time_limit=90.0,
    )
    p.generate()
    return p


def fresh_engine() -> PuzzleEngine:
    return PuzzleEngine()


# ---------------------------------------------------------------------------
# _compute_intercept_bearing
# ---------------------------------------------------------------------------


class TestComputeInterceptBearing:
    def test_stationary_target_returns_direct_bearing(self):
        # Target directly north (bearing 0), not moving.
        brg = _compute_intercept_bearing(0.0, -5000.0, 0.0, 0.0, TORPEDO_SPEED)
        assert brg == pytest.approx(0.0, abs=1.0)

    def test_target_east_returns_bearing_90(self):
        # Target directly east (bearing 90).
        brg = _compute_intercept_bearing(5000.0, 0.0, 0.0, 0.0, TORPEDO_SPEED)
        assert brg == pytest.approx(90.0, abs=1.0)

    def test_moving_target_leads_ahead(self):
        # Target is north, moving east (heading 90°).
        # Intercept bearing should be slightly east of north (> 0° and < 90°).
        brg = _compute_intercept_bearing(0.0, -5000.0, 90.0, 150.0, TORPEDO_SPEED)
        assert 0.0 < brg < 90.0

    def test_result_in_range(self):
        brg = _compute_intercept_bearing(3000.0, -3000.0, 135.0, 100.0, TORPEDO_SPEED)
        assert 0.0 <= brg < 360.0

    def test_target_moving_away_fast_fallback(self):
        # Target moving directly away from player at torpedo speed — discriminant negative.
        # Should fall back to direct bearing without crashing.
        brg = _compute_intercept_bearing(0.0, -5000.0, 180.0, TORPEDO_SPEED * 2, TORPEDO_SPEED)
        assert 0.0 <= brg < 360.0


# ---------------------------------------------------------------------------
# TestGenerate
# ---------------------------------------------------------------------------


class TestGenerate:
    def test_returns_expected_keys(self):
        p = make_puzzle()
        data = p.generate()
        assert "target_bearing" in data
        assert "target_distance" in data
        assert "target_heading" in data
        assert "target_velocity" in data
        assert "torp_velocity" in data
        assert "tolerance" in data

    def test_target_velocity_hidden_initially(self):
        p = make_puzzle()
        data = p.generate()
        assert data["target_velocity"] is None

    def test_torp_velocity_correct(self):
        p = make_puzzle()
        data = p.generate()
        assert data["torp_velocity"] == TORPEDO_SPEED

    def test_target_bearing_in_range(self):
        for _ in range(10):
            p = make_puzzle()
            data = p.generate()
            assert 0.0 <= data["target_bearing"] < 360.0

    def test_tolerance_matches_difficulty(self):
        for diff, (_, _, _, _, tol) in _DIFFICULTY_PARAMS.items():
            p = make_puzzle(difficulty=diff)
            data = p.generate()
            assert data["tolerance"] == pytest.approx(tol)

    def test_has_correct_bearing_attribute(self):
        p = make_puzzle()
        assert hasattr(p, "_correct_bearing")
        assert 0.0 <= p._correct_bearing < 360.0

    def test_has_assist_applied_attribute(self):
        p = make_puzzle()
        assert hasattr(p, "_assist_applied")
        assert p._assist_applied is False

    def test_distance_within_difficulty_range(self):
        diff = 3
        dist_min, dist_max, _, _, _ = _DIFFICULTY_PARAMS[diff]
        for _ in range(10):
            p = FiringSolutionPuzzle(
                puzzle_id="t", label="l", station="weapons", difficulty=diff, time_limit=30.0
            )
            p.generate()
            assert dist_min <= p._target_distance <= dist_max


# ---------------------------------------------------------------------------
# TestValidateSubmission
# ---------------------------------------------------------------------------


class TestValidateSubmission:
    def test_correct_bearing_accepted(self):
        p = make_puzzle()
        assert p.validate_submission({"bearing": p._correct_bearing}) is True

    def test_within_tolerance_accepted(self):
        p = make_puzzle()
        offset = p._tolerance - 0.5
        bearing = (p._correct_bearing + offset) % 360.0
        assert p.validate_submission({"bearing": bearing}) is True

    def test_outside_tolerance_rejected(self):
        p = make_puzzle()
        # Offset by more than tolerance.
        offset = p._tolerance + 2.0
        bearing = (p._correct_bearing + offset) % 360.0
        assert p.validate_submission({"bearing": bearing}) is False

    def test_missing_bearing_rejected(self):
        p = make_puzzle()
        assert p.validate_submission({}) is False

    def test_invalid_bearing_type_rejected(self):
        p = make_puzzle()
        assert p.validate_submission({"bearing": "north"}) is False

    def test_bearing_wraps_correctly(self):
        p = make_puzzle()
        # 360 should be treated the same as 0.
        bearing_0 = p._correct_bearing
        p._correct_bearing = 0.0
        p._tolerance = 10.0
        assert p.validate_submission({"bearing": 355.0}) is True   # 5° off
        assert p.validate_submission({"bearing": 11.0}) is False   # 11° off


# ---------------------------------------------------------------------------
# TestApplyAssist
# ---------------------------------------------------------------------------


class TestApplyAssist:
    def test_velocity_data_reveals_velocity(self):
        p = make_puzzle()
        result = p.apply_assist("velocity_data", {})
        assert result["target_velocity"] == pytest.approx(p._target_velocity)

    def test_velocity_data_reveals_heading(self):
        p = make_puzzle()
        result = p.apply_assist("velocity_data", {})
        assert result["target_heading"] == pytest.approx(p._target_heading)

    def test_velocity_data_widens_tolerance(self):
        p = make_puzzle()
        original_tol = p._tolerance
        result = p.apply_assist("velocity_data", {})
        assert result["tolerance"] > original_tol
        assert p._tolerance == pytest.approx(original_tol + _ASSIST_TOLERANCE_BONUS)

    def test_velocity_data_applied_once(self):
        p = make_puzzle()
        tol_after_first = p.apply_assist("velocity_data", {})["tolerance"]
        result_second = p.apply_assist("velocity_data", {})
        assert result_second == {}
        assert p._tolerance == pytest.approx(tol_after_first)

    def test_unknown_assist_type_returns_empty(self):
        p = make_puzzle()
        result = p.apply_assist("telekinesis", {})
        assert result == {}

    def test_tolerance_capped_at_25(self):
        p = make_puzzle(difficulty=1)   # tolerance=15.0; +8 → 23, not capped
        p.apply_assist("velocity_data", {})
        assert p._tolerance <= 25.0


# ---------------------------------------------------------------------------
# TestPuzzleEngineIntegration
# ---------------------------------------------------------------------------


class TestPuzzleEngineIntegration:
    def test_create_firing_solution(self):
        eng = fresh_engine()
        inst = eng.create_puzzle(
            puzzle_type="firing_solution",
            station="weapons",
            label="test",
            difficulty=1,
            time_limit=60.0,
        )
        assert inst is not None
        assert inst.is_active()

    def test_submit_correct_bearing(self):
        eng = fresh_engine()
        inst = eng.create_puzzle(
            puzzle_type="firing_solution",
            station="weapons",
            label="test",
            difficulty=1,
            time_limit=60.0,
        )
        eng.pop_pending_broadcasts()  # consume puzzle.started
        eng.submit(inst.puzzle_id, {"bearing": inst._correct_bearing})
        resolved = eng.pop_resolved()
        assert any(label == "test" and success for _, label, success in resolved)

    def test_submit_wrong_bearing(self):
        eng = fresh_engine()
        inst = eng.create_puzzle(
            puzzle_type="firing_solution",
            station="weapons",
            label="test",
            difficulty=1,
            time_limit=60.0,
        )
        eng.pop_pending_broadcasts()
        wrong_bearing = (inst._correct_bearing + inst._tolerance + 5.0) % 360.0
        eng.submit(inst.puzzle_id, {"bearing": wrong_bearing})
        resolved = eng.pop_resolved()
        assert any(label == "test" and not success for _, label, success in resolved)

    def test_assist_applies_via_engine(self):
        eng = fresh_engine()
        inst = eng.create_puzzle(
            puzzle_type="firing_solution",
            station="weapons",
            label="test",
            difficulty=2,
            time_limit=60.0,
        )
        eng.pop_pending_broadcasts()
        original_tol = inst._tolerance
        eng.apply_assist(inst.puzzle_id, "velocity_data", {})
        assert inst._tolerance > original_tol

    def test_get_active_for_station(self):
        eng = fresh_engine()
        inst = eng.create_puzzle(
            puzzle_type="firing_solution",
            station="weapons",
            label="test",
            difficulty=1,
            time_limit=60.0,
        )
        found = eng.get_active_for_station("weapons")
        assert found is inst

    def test_timeout_resolves_as_failure(self):
        eng = fresh_engine()
        inst = eng.create_puzzle(
            puzzle_type="firing_solution",
            station="weapons",
            label="test",
            difficulty=1,
            time_limit=0.1,
        )
        eng.pop_pending_broadcasts()
        eng.tick(0.2)  # exceed time limit
        resolved = eng.pop_resolved()
        assert any(label == "test" and not success for _, label, success in resolved)


# ---------------------------------------------------------------------------
# TestCaptainLog
# ---------------------------------------------------------------------------


class TestCaptainLog:
    def test_add_entry(self):
        import server.game_loop_captain as glcap
        glcap.reset()
        entry = glcap.add_log_entry("First contact confirmed.")
        assert entry["text"] == "First contact confirmed."
        assert "timestamp" in entry

    def test_get_log_returns_entries(self):
        import server.game_loop_captain as glcap
        glcap.reset()
        glcap.add_log_entry("Entry one.")
        glcap.add_log_entry("Entry two.")
        log = glcap.get_log()
        assert len(log) == 2
        assert log[0]["text"] == "Entry one."
        assert log[1]["text"] == "Entry two."

    def test_reset_clears_log(self):
        import server.game_loop_captain as glcap
        glcap.reset()
        glcap.add_log_entry("Before reset.")
        glcap.reset()
        assert glcap.get_log() == []

    def test_get_log_returns_copy(self):
        import server.game_loop_captain as glcap
        glcap.reset()
        glcap.add_log_entry("Test entry.")
        log = glcap.get_log()
        log.append({"text": "injected", "timestamp": 0})
        # Original should be unchanged.
        assert len(glcap.get_log()) == 1
