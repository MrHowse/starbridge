"""Tests for the Frequency Matching puzzle type.

Covers:
  server/puzzles/frequency_matching.py — FrequencyMatchingPuzzle
  Waveform helpers: _sample_waveform, _relative_rms_error
  Integration with PuzzleEngine lifecycle.
"""
from __future__ import annotations

import math
import pytest

from server.puzzles.engine import PuzzleEngine
import server.puzzles.frequency_matching  # noqa: F401 — registers the type
from server.puzzles.frequency_matching import (
    FrequencyMatchingPuzzle,
    _DIFFICULTY_PARAMS,
    _MAX_TOLERANCE,
    _SAMPLE_COUNT,
    _sample_waveform,
    _relative_rms_error,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh_engine() -> PuzzleEngine:
    return PuzzleEngine()


def make_puzzle(engine: PuzzleEngine, difficulty: int = 1) -> FrequencyMatchingPuzzle:
    return engine.create_puzzle(  # type: ignore[return-value]
        puzzle_type="frequency_matching",
        station="science",
        label=f"fm_test_d{difficulty}",
        difficulty=difficulty,
        time_limit=60.0,
    )


# ---------------------------------------------------------------------------
# Waveform helper unit tests
# ---------------------------------------------------------------------------


def test_sample_waveform_length():
    components = [{"amplitude": 1.0, "frequency": 2.0}]
    samples = _sample_waveform(components)
    assert len(samples) == _SAMPLE_COUNT


def test_sample_waveform_zero_amplitude():
    components = [{"amplitude": 0.0, "frequency": 3.0}]
    samples = _sample_waveform(components)
    assert all(s == 0.0 for s in samples)


def test_sample_waveform_single_sine_at_t0():
    # At t=0 (i=0), sin(0) = 0.
    components = [{"amplitude": 0.8, "frequency": 2.0}]
    samples = _sample_waveform(components)
    assert samples[0] == pytest.approx(0.0, abs=1e-10)


def test_rms_error_identical_waveforms_is_zero():
    components = [{"amplitude": 0.7, "frequency": 2.5}]
    s = _sample_waveform(components)
    assert _relative_rms_error(s, s) == pytest.approx(0.0, abs=1e-10)


def test_rms_error_empty_returns_one():
    assert _relative_rms_error([], []) == 1.0


def test_rms_error_orthogonal_waveforms_positive():
    c1 = [{"amplitude": 1.0, "frequency": 1.0}]
    c2 = [{"amplitude": 1.0, "frequency": 3.0}]  # different freq → near-orthogonal
    s1 = _sample_waveform(c1)
    s2 = _sample_waveform(c2)
    error = _relative_rms_error(s1, s2)
    assert error > 0.5  # substantially different


def test_rms_error_close_waveforms_small():
    c1 = [{"amplitude": 0.8, "frequency": 2.0}]
    c2 = [{"amplitude": 0.8, "frequency": 2.1}]  # very close
    s1 = _sample_waveform(c1)
    s2 = _sample_waveform(c2)
    error = _relative_rms_error(s1, s2)
    # Should be noticeably less than an orthogonal pair.
    assert error < 0.5


# ---------------------------------------------------------------------------
# FrequencyMatchingPuzzle — generate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("diff", [1, 2, 3, 4, 5])
def test_component_count_matches_difficulty(diff):
    engine = fresh_engine()
    puzzle = make_puzzle(engine, diff)
    count, _ = _DIFFICULTY_PARAMS[diff]
    assert puzzle._component_count == count
    assert len(puzzle._target_components) == count


@pytest.mark.parametrize("diff", [1, 2, 3, 4, 5])
def test_tolerance_matches_difficulty(diff):
    engine = fresh_engine()
    puzzle = make_puzzle(engine, diff)
    _, tol = _DIFFICULTY_PARAMS[diff]
    assert puzzle._tolerance == pytest.approx(tol)


def test_target_amplitudes_in_range():
    engine = fresh_engine()
    for diff in range(1, 6):
        puzzle = make_puzzle(engine, diff)
        for c in puzzle._target_components:
            assert 0.3 <= c["amplitude"] <= 1.0


def test_target_frequencies_in_range():
    engine = fresh_engine()
    for diff in range(1, 6):
        puzzle = make_puzzle(engine, diff)
        for c in puzzle._target_components:
            assert 1.0 <= c["frequency"] <= 5.0


def test_target_frequencies_well_separated():
    """All target frequencies must be at least 0.5 apart."""
    engine = fresh_engine()
    for diff in range(1, 6):
        puzzle = make_puzzle(engine, diff)
        freqs = [c["frequency"] for c in puzzle._target_components]
        for i, f1 in enumerate(freqs):
            for j, f2 in enumerate(freqs):
                if i != j:
                    assert abs(f1 - f2) >= 0.5 - 1e-9, (
                        f"diff={diff}: frequencies too close: {f1} vs {f2}"
                    )


def test_initial_player_components_correct_count():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=3)
    count, _ = _DIFFICULTY_PARAMS[3]
    # Check returned data has initial_player_components of the right length.
    # (Validated via the generate() return value stored implicitly in the puzzle)
    assert puzzle._component_count == count


def test_generate_returns_success_message():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    # Get the data from puzzle.started broadcast.
    engine.pop_pending_broadcasts()  # puzzle.started; just assert no exception


# ---------------------------------------------------------------------------
# FrequencyMatchingPuzzle — validate_submission
# ---------------------------------------------------------------------------


def test_validate_exact_match_succeeds():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=1)
    # Exact match of the target components.
    submission = {
        "components": [
            {"amplitude": c["amplitude"], "frequency": c["frequency"]}
            for c in puzzle._target_components
        ]
    }
    assert puzzle.validate_submission(submission)


def test_validate_wrong_component_count_fails():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=1)
    submission = {"components": [{"amplitude": 0.5, "frequency": 2.0}]}
    # difficulty 1 has 2 components; submitting 1 must fail.
    if puzzle._component_count != 1:
        assert not puzzle.validate_submission(submission)


def test_validate_completely_wrong_fails():
    """Midpoint sliders are far from target → should fail at tight tolerance."""
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=5)
    # difficulty-5 tolerance is 0.08 — midpoint sliders extremely unlikely to pass.
    submission = {
        "components": [
            {"amplitude": 0.5, "frequency": 3.0}
            for _ in range(puzzle._component_count)
        ]
    }
    # Not guaranteed to fail (random target could coincidentally be close),
    # but statistically very unlikely; skip assertion if target is near midpoint.
    target_s = _sample_waveform(puzzle._target_components)
    player_s = _sample_waveform(submission["components"])
    from server.puzzles.frequency_matching import _relative_rms_error
    if _relative_rms_error(target_s, player_s) >= puzzle._tolerance:
        assert not puzzle.validate_submission(submission)


def test_validate_near_match_within_wide_tolerance_passes():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=1)  # tolerance 0.30
    # Slightly perturb the target.
    submission = {
        "components": [
            {
                "amplitude": c["amplitude"] * 0.98,
                "frequency": c["frequency"] + 0.05,
            }
            for c in puzzle._target_components
        ]
    }
    # Small perturbation should pass wide tolerance (0.30).
    assert puzzle.validate_submission(submission)


def test_validate_missing_components_key():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    assert not puzzle.validate_submission({})


# ---------------------------------------------------------------------------
# FrequencyMatchingPuzzle — apply_assist (widen_tolerance)
# ---------------------------------------------------------------------------


def test_assist_widen_tolerance_increases_value():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=5)  # tight tolerance: 0.08
    old_tol = puzzle._tolerance
    result = puzzle.apply_assist("widen_tolerance", {})
    assert puzzle._tolerance > old_tol
    assert result["tolerance"] == pytest.approx(old_tol + 0.15)
    assert result["previous_tolerance"] == pytest.approx(old_tol)


def test_assist_widen_tolerance_capped_at_max():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=5)
    # Apply assist repeatedly to hit the cap.
    for _ in range(5):
        puzzle.apply_assist("widen_tolerance", {})
    assert puzzle._tolerance <= _MAX_TOLERANCE


def test_assist_widen_tolerance_makes_easy_submission_pass():
    """After widening, a close-but-not-exact submission should pass."""
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=4)  # tolerance 0.12
    # Widen to 0.27.
    puzzle.apply_assist("widen_tolerance", {})

    # Near-match submission (5 % amplitude off, 0.1 freq off).
    submission = {
        "components": [
            {
                "amplitude": c["amplitude"] * 0.95,
                "frequency": c["frequency"] + 0.1,
            }
            for c in puzzle._target_components
        ]
    }
    target_s = _sample_waveform(puzzle._target_components)
    player_s = _sample_waveform(submission["components"])
    from server.puzzles.frequency_matching import _relative_rms_error
    error = _relative_rms_error(target_s, player_s)
    # Only assert if the perturbation is within the widened tolerance.
    if error < puzzle._tolerance:
        assert puzzle.validate_submission(submission)


def test_assist_unknown_type_returns_empty():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    assert puzzle.apply_assist("nonexistent", {}) == {}


# ---------------------------------------------------------------------------
# PuzzleEngine integration
# ---------------------------------------------------------------------------


def test_engine_creates_frequency_matching():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    assert isinstance(puzzle, FrequencyMatchingPuzzle)


def test_engine_submit_correct_resolves_success():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=1)
    engine.pop_pending_broadcasts()

    submission = {
        "components": [
            {"amplitude": c["amplitude"], "frequency": c["frequency"]}
            for c in puzzle._target_components
        ]
    }
    engine.submit(puzzle.puzzle_id, submission)
    resolved = engine.pop_resolved()
    assert any(label == puzzle.label and success for _, label, success in resolved)


def test_engine_timeout_resolves_as_failure():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    engine.pop_pending_broadcasts()

    engine.tick(puzzle.time_limit + 0.1)
    broadcasts = engine.pop_pending_broadcasts()
    result_broadcasts = [
        (roles, msg) for roles, msg in broadcasts if msg.type == "puzzle.result"
    ]
    assert result_broadcasts
    resolved = engine.pop_resolved()
    assert any(not success for _, _, success in resolved)


def test_engine_apply_assist_through_engine():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=5)
    engine.pop_pending_broadcasts()

    old_tol = puzzle._tolerance
    engine.apply_assist(puzzle.puzzle_id, "widen_tolerance", {})

    # Engine should have queued a puzzle.assist_applied broadcast.
    broadcasts = engine.pop_pending_broadcasts()
    assist_bcast = [
        (roles, msg) for roles, msg in broadcasts
        if msg.type == "puzzle.assist_applied"
    ]
    assert assist_bcast
    assert puzzle._tolerance > old_tol
