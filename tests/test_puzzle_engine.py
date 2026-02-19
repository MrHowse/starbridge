"""Tests for the puzzle engine framework.

Covers:
  server/puzzles/base.py        — PuzzleInstance lifecycle, timeout, _resolve
  server/puzzles/engine.py      — PuzzleEngine create/tick/submit/assist/cancel
  server/puzzles/sequence_match — SequenceMatchPuzzle generate/validate/assist
"""
from __future__ import annotations

import pytest

from server.puzzles.engine import PuzzleEngine
import server.puzzles.sequence_match  # noqa: F401 — registers the type
from server.puzzles.sequence_match import SequenceMatchPuzzle, COLOURS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh_engine() -> PuzzleEngine:
    engine = PuzzleEngine()
    return engine


def make_puzzle(engine: PuzzleEngine, **kwargs) -> SequenceMatchPuzzle:
    """Create a sequence_match puzzle with sensible defaults."""
    defaults = dict(
        puzzle_type="sequence_match",
        station="science",
        label="test_seq",
        difficulty=1,
        time_limit=30.0,
    )
    defaults.update(kwargs)
    return engine.create_puzzle(**defaults)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# SequenceMatchPuzzle — generate
# ---------------------------------------------------------------------------


def test_generate_returns_correct_length_difficulty_1():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=1)
    assert len(puzzle._sequence) == 4  # 3 + difficulty


def test_generate_returns_correct_length_difficulty_5():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=5)
    assert len(puzzle._sequence) == 8


def test_generate_sequence_uses_valid_colours():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    assert all(c in COLOURS for c in puzzle._sequence)


def test_generate_data_includes_length_and_colours():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    # generate() was called by create_puzzle; check its result via the started broadcast
    engine.pop_pending_broadcasts()  # consume
    # Re-call generate to inspect return value directly
    puzzle2 = SequenceMatchPuzzle(
        puzzle_id="x", label="y", station="science", difficulty=2, time_limit=10.0
    )
    data = puzzle2.generate()
    assert data["length"] == 5  # 3 + 2
    assert set(data["colours"]) == set(COLOURS)
    assert data["revealed"] == 0
    assert data["revealed_sequence"] == []


# ---------------------------------------------------------------------------
# SequenceMatchPuzzle — validate_submission
# ---------------------------------------------------------------------------


def test_validate_submission_correct():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    assert puzzle.validate_submission({"sequence": puzzle._sequence}) is True


def test_validate_submission_wrong_sequence():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    wrong = [c for c in COLOURS if c != puzzle._sequence[0]] * 10
    wrong = wrong[: len(puzzle._sequence)]
    # Only wrong if sequence actually differs (may coincidentally match for small cases)
    if wrong != puzzle._sequence:
        assert puzzle.validate_submission({"sequence": wrong}) is False


def test_validate_submission_empty():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    assert puzzle.validate_submission({"sequence": []}) is False


def test_validate_submission_missing_key():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    assert puzzle.validate_submission({}) is False


# ---------------------------------------------------------------------------
# SequenceMatchPuzzle — apply_assist
# ---------------------------------------------------------------------------


def test_apply_assist_reveal_start_returns_prefix():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    result = puzzle.apply_assist("reveal_start", {"count": 2})
    assert result["revealed"] == 2
    assert result["revealed_sequence"] == puzzle._sequence[:2]


def test_apply_assist_reveal_start_caps_at_length_minus_one():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=1)  # length 4
    result = puzzle.apply_assist("reveal_start", {"count": 10})
    # Must not reveal the whole answer
    assert result["revealed"] == 3  # max = length - 1 = 3


def test_apply_assist_reveal_does_not_decrease():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    puzzle.apply_assist("reveal_start", {"count": 2})
    result = puzzle.apply_assist("reveal_start", {"count": 1})
    # Second assist with smaller count should not reduce revealed
    assert result["revealed"] == 2


def test_apply_assist_unknown_type_returns_empty():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    result = puzzle.apply_assist("invalid_assist", {})
    assert result == {}


# ---------------------------------------------------------------------------
# PuzzleEngine — create_puzzle
# ---------------------------------------------------------------------------


def test_create_puzzle_returns_instance():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    assert puzzle is not None
    assert isinstance(puzzle, SequenceMatchPuzzle)


def test_create_puzzle_assigns_sequential_id():
    engine = fresh_engine()
    p1 = make_puzzle(engine, label="a")
    p2 = make_puzzle(engine, label="b")
    assert p1.puzzle_id == "puzzle_1"
    assert p2.puzzle_id == "puzzle_2"


def test_create_puzzle_queues_started_broadcast():
    engine = fresh_engine()
    make_puzzle(engine, station="science")
    broadcasts = engine.pop_pending_broadcasts()
    assert len(broadcasts) == 1
    roles, msg = broadcasts[0]
    assert roles == ["science"]
    assert msg.type == "puzzle.started"
    assert msg.payload["type"] == "sequence_match"


def test_create_puzzle_started_includes_label():
    engine = fresh_engine()
    make_puzzle(engine, label="my_label")
    broadcasts = engine.pop_pending_broadcasts()
    _, msg = broadcasts[0]
    assert msg.payload["label"] == "my_label"


def test_create_puzzle_unknown_type_returns_none():
    engine = fresh_engine()
    result = engine.create_puzzle("nonexistent_type", "science", "x")
    assert result is None
    assert engine.pop_pending_broadcasts() == []


# ---------------------------------------------------------------------------
# PuzzleEngine — tick (timeout)
# ---------------------------------------------------------------------------


def test_tick_no_timeout_before_time_limit():
    engine = fresh_engine()
    make_puzzle(engine, time_limit=5.0)
    engine.pop_pending_broadcasts()  # consume started
    engine.tick(4.9)
    assert engine.pop_pending_broadcasts() == []
    assert engine.pop_resolved() == []


def test_tick_timeout_queues_failure_result():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, time_limit=2.0)
    engine.pop_pending_broadcasts()  # consume started

    engine.tick(2.1)
    broadcasts = engine.pop_pending_broadcasts()
    assert len(broadcasts) == 1
    roles, msg = broadcasts[0]
    assert roles == ["science"]
    assert msg.type == "puzzle.result"
    assert msg.payload["success"] is False
    assert msg.payload["reason"] == "timeout"


def test_tick_timeout_reports_to_pop_resolved():
    engine = fresh_engine()
    make_puzzle(engine, label="my_seq", time_limit=1.0)
    engine.pop_pending_broadcasts()

    engine.tick(1.1)
    engine.pop_pending_broadcasts()
    resolved = engine.pop_resolved()
    assert len(resolved) == 1
    puzzle_id, label, success = resolved[0]
    assert label == "my_seq"
    assert success is False


def test_tick_timeout_prunes_puzzle_from_active():
    engine = fresh_engine()
    make_puzzle(engine, time_limit=1.0)
    engine.pop_pending_broadcasts()

    engine.tick(1.5)
    engine.pop_pending_broadcasts()
    engine.pop_resolved()
    # A second tick should produce no broadcasts (puzzle is gone).
    engine.tick(1.0)
    assert engine.pop_pending_broadcasts() == []


def test_tick_only_fires_timeout_once():
    engine = fresh_engine()
    make_puzzle(engine, time_limit=1.0)
    engine.pop_pending_broadcasts()

    engine.tick(2.0)
    engine.pop_pending_broadcasts()
    engine.pop_resolved()
    # Third tick — puzzle already pruned, no broadcasts.
    engine.tick(1.0)
    assert engine.pop_pending_broadcasts() == []


# ---------------------------------------------------------------------------
# PuzzleEngine — submit
# ---------------------------------------------------------------------------


def test_submit_correct_queues_success():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    engine.pop_pending_broadcasts()

    engine.submit(puzzle.puzzle_id, {"sequence": puzzle._sequence})
    broadcasts = engine.pop_pending_broadcasts()
    assert len(broadcasts) == 1
    roles, msg = broadcasts[0]
    assert msg.payload["success"] is True


def test_submit_incorrect_queues_failure():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    engine.pop_pending_broadcasts()

    engine.submit(puzzle.puzzle_id, {"sequence": []})
    broadcasts = engine.pop_pending_broadcasts()
    assert len(broadcasts) == 1
    _, msg = broadcasts[0]
    assert msg.payload["success"] is False


def test_submit_marks_puzzle_inactive():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    engine.pop_pending_broadcasts()

    engine.submit(puzzle.puzzle_id, {"sequence": puzzle._sequence})
    assert not puzzle.is_active()


def test_submit_reports_to_pop_resolved():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, label="solve_me")
    engine.pop_pending_broadcasts()

    engine.submit(puzzle.puzzle_id, {"sequence": puzzle._sequence})
    engine.tick(0.0)  # trigger resolution detection
    resolved = engine.pop_resolved()
    assert len(resolved) == 1
    _, label, success = resolved[0]
    assert label == "solve_me"
    assert success is True


def test_submit_unknown_puzzle_id_silently_ignored():
    engine = fresh_engine()
    engine.submit("puzzle_999", {"sequence": ["red"]})  # must not raise
    assert engine.pop_pending_broadcasts() == []


def test_submit_on_resolved_puzzle_ignored():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    engine.pop_pending_broadcasts()

    engine.submit(puzzle.puzzle_id, {"sequence": puzzle._sequence})
    engine.pop_pending_broadcasts()
    # Submitting again should not produce another broadcast.
    engine.submit(puzzle.puzzle_id, {"sequence": puzzle._sequence})
    assert engine.pop_pending_broadcasts() == []


# ---------------------------------------------------------------------------
# PuzzleEngine — apply_assist
# ---------------------------------------------------------------------------


def test_apply_assist_queues_assist_applied():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    engine.pop_pending_broadcasts()

    engine.apply_assist(puzzle.puzzle_id, "reveal_start", {"count": 1})
    broadcasts = engine.pop_pending_broadcasts()
    assert len(broadcasts) == 1
    roles, msg = broadcasts[0]
    assert roles == ["science"]
    assert msg.type == "puzzle.assist_applied"
    assert msg.payload["assist_type"] == "reveal_start"
    assert "revealed_sequence" in msg.payload["data"]


def test_apply_assist_unknown_puzzle_silently_ignored():
    engine = fresh_engine()
    engine.apply_assist("puzzle_999", "reveal_start", {})  # must not raise


# ---------------------------------------------------------------------------
# PuzzleEngine — cancel
# ---------------------------------------------------------------------------


def test_cancel_marks_puzzle_inactive():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    engine.pop_pending_broadcasts()

    engine.cancel(puzzle.puzzle_id)
    assert not puzzle.is_active()


def test_cancel_produces_no_broadcast():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    engine.pop_pending_broadcasts()

    engine.cancel(puzzle.puzzle_id)
    assert engine.pop_pending_broadcasts() == []


def test_cancel_unknown_puzzle_silently_ignored():
    engine = fresh_engine()
    engine.cancel("puzzle_999")  # must not raise


# ---------------------------------------------------------------------------
# PuzzleEngine — get_active_for_station
# ---------------------------------------------------------------------------


def test_get_active_for_station_finds_puzzle():
    engine = fresh_engine()
    make_puzzle(engine, station="science")
    puzzle = engine.get_active_for_station("science")
    assert puzzle is not None


def test_get_active_for_station_wrong_station_returns_none():
    engine = fresh_engine()
    make_puzzle(engine, station="science")
    assert engine.get_active_for_station("engineering") is None


def test_get_active_for_station_after_resolve_returns_none():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, time_limit=1.0)
    engine.pop_pending_broadcasts()
    engine.tick(2.0)
    engine.pop_pending_broadcasts()
    engine.pop_resolved()
    assert engine.get_active_for_station("science") is None


# ---------------------------------------------------------------------------
# PuzzleEngine — multiple simultaneous puzzles
# ---------------------------------------------------------------------------


def test_multiple_puzzles_different_stations_independent():
    engine = fresh_engine()
    p1 = make_puzzle(engine, station="science", label="sci_puzzle", time_limit=10.0)
    p2 = make_puzzle(engine, station="engineering", label="eng_puzzle", time_limit=20.0)
    engine.pop_pending_broadcasts()

    # Submit science puzzle correctly.
    engine.submit(p1.puzzle_id, {"sequence": p1._sequence})
    # Engineering puzzle unaffected.
    assert engine.get_active_for_station("engineering") is p2
    broadcasts = engine.pop_pending_broadcasts()
    assert len(broadcasts) == 1
    roles, _ = broadcasts[0]
    assert roles == ["science"]


def test_multiple_puzzles_timeout_independent():
    engine = fresh_engine()
    p1 = make_puzzle(engine, station="science",      label="a", time_limit=1.0)
    p2 = make_puzzle(engine, station="engineering",  label="b", time_limit=100.0)
    engine.pop_pending_broadcasts()

    engine.tick(1.5)  # only p1 should time out
    broadcasts = engine.pop_pending_broadcasts()
    assert len(broadcasts) == 1
    roles, msg = broadcasts[0]
    assert roles == ["science"]
    assert msg.payload["label"] == "a"
    # p2 still active.
    assert engine.get_active_for_station("engineering") is p2


# ---------------------------------------------------------------------------
# PuzzleEngine — reset
# ---------------------------------------------------------------------------


def test_reset_clears_all_state():
    engine = fresh_engine()
    make_puzzle(engine, label="a")
    make_puzzle(engine, label="b")
    engine.pop_pending_broadcasts()

    engine.reset()
    assert engine.pop_pending_broadcasts() == []
    assert engine.pop_resolved() == []
    assert engine.get_active_for_station("science") is None
    # Counter resets — new puzzle gets puzzle_1 again.
    p = make_puzzle(engine)
    assert p.puzzle_id == "puzzle_1"
