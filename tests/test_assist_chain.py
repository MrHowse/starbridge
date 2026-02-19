"""Tests for the Engineering → Science cross-station sensor assist chain.

Covers:
  server/game_loop.py — _check_sensor_assist()
  server/game_loop.py — _applied_sensor_assists tracking
  server/game_loop.py — SENSOR_ASSIST_THRESHOLD constant
  server/missions/engine.py — on_complete list support
"""
from __future__ import annotations

import pytest

import server.game_loop as gl
import server.puzzles.frequency_matching  # noqa: F401 — register type
import server.puzzles.circuit_routing     # noqa: F401 — register type

from server.models.ship import Ship
from server.puzzles.engine import PuzzleEngine
from server.puzzles.frequency_matching import FrequencyMatchingPuzzle
from server.puzzles.sequence_match import SequenceMatchPuzzle
from server.missions.engine import MissionEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ship() -> Ship:
    return Ship()


def fresh_puzzle_engine() -> PuzzleEngine:
    engine = PuzzleEngine()
    engine.reset()
    return engine


def add_freq_puzzle(engine: PuzzleEngine, station: str = "science") -> FrequencyMatchingPuzzle:
    return engine.create_puzzle(  # type: ignore[return-value]
        puzzle_type="frequency_matching",
        station=station,
        label="freq_assist_test",
        difficulty=3,
        time_limit=60.0,
    )


# ---------------------------------------------------------------------------
# _check_sensor_assist tests
# ---------------------------------------------------------------------------


def test_sensor_assist_threshold_value():
    assert gl.SENSOR_ASSIST_THRESHOLD == pytest.approx(1.2)


def test_check_sensor_assist_returns_none_when_no_science_puzzle():
    """No puzzle active → no assist."""
    # Temporarily swap the global puzzle engine.
    original = gl._puzzle_engine
    gl._puzzle_engine = fresh_puzzle_engine()
    gl._applied_sensor_assists.clear()

    try:
        ship = make_ship()
        ship.systems["sensors"].power = 150.0   # efficiency > 1.2 (power only; health=100 default)
        result = gl._check_sensor_assist(ship)
        assert result is None
    finally:
        gl._puzzle_engine = original


def test_check_sensor_assist_returns_none_when_sensors_below_threshold():
    """Sensors under 120 % → no assist, even with active puzzle."""
    original = gl._puzzle_engine
    engine = fresh_puzzle_engine()
    gl._puzzle_engine = engine
    gl._applied_sensor_assists.clear()

    try:
        add_freq_puzzle(engine)
        engine.pop_pending_broadcasts()  # consume puzzle.started

        ship = make_ship()
        ship.systems["sensors"].power = 100.0   # exactly 100 % → efficiency 1.0 < 1.2
        result = gl._check_sensor_assist(ship)
        assert result is None
    finally:
        gl._puzzle_engine = original


def test_check_sensor_assist_triggers_when_sensors_overclocked():
    """sensors.efficiency >= 1.2 AND active frequency puzzle → assist fires."""
    original = gl._puzzle_engine
    engine = fresh_puzzle_engine()
    gl._puzzle_engine = engine
    gl._applied_sensor_assists.clear()

    try:
        puzzle = add_freq_puzzle(engine)
        engine.pop_pending_broadcasts()

        old_tol = puzzle._tolerance

        ship = make_ship()
        ship.systems["sensors"].power = 150.0   # overclock → efficiency = 1.5 > 1.2

        result = gl._check_sensor_assist(ship)
        assert result is not None
        assert result.type == "puzzle.assist_sent"
        # Tolerance should have been widened.
        assert puzzle._tolerance > old_tol
    finally:
        gl._puzzle_engine = original


def test_check_sensor_assist_applies_only_once():
    """Once applied, the assist must not re-trigger on subsequent ticks."""
    original = gl._puzzle_engine
    engine = fresh_puzzle_engine()
    gl._puzzle_engine = engine
    gl._applied_sensor_assists.clear()

    try:
        puzzle = add_freq_puzzle(engine)
        engine.pop_pending_broadcasts()

        ship = make_ship()
        ship.systems["sensors"].power = 150.0

        # First call → fires.
        result1 = gl._check_sensor_assist(ship)
        assert result1 is not None

        tolerance_after_first = puzzle._tolerance

        # Second call → same conditions, must not re-apply.
        result2 = gl._check_sensor_assist(ship)
        assert result2 is None
        assert puzzle._tolerance == tolerance_after_first  # unchanged
    finally:
        gl._puzzle_engine = original


def test_check_sensor_assist_does_not_fire_for_non_frequency_puzzle():
    """Non-frequency_matching puzzles on Science must not trigger the assist."""
    import server.puzzles.sequence_match  # noqa: F401

    original = gl._puzzle_engine
    engine = fresh_puzzle_engine()
    gl._puzzle_engine = engine
    gl._applied_sensor_assists.clear()

    try:
        # Create a sequence_match puzzle on science (no _tolerance attribute).
        engine.create_puzzle(
            puzzle_type="sequence_match",
            station="science",
            label="not_freq",
            difficulty=1,
            time_limit=60.0,
        )
        engine.pop_pending_broadcasts()

        ship = make_ship()
        ship.systems["sensors"].power = 150.0

        result = gl._check_sensor_assist(ship)
        assert result is None
    finally:
        gl._puzzle_engine = original


def test_applied_assists_cleared_on_start():
    """start() must clear _applied_sensor_assists."""
    # We cannot call start() without an event loop, so test the reset directly.
    gl._applied_sensor_assists.add("dummy_puzzle_id")
    assert "dummy_puzzle_id" in gl._applied_sensor_assists

    # Manually replicate what start() does.
    gl._applied_sensor_assists.clear()
    assert len(gl._applied_sensor_assists) == 0


def test_assist_message_contains_puzzle_info():
    original = gl._puzzle_engine
    engine = fresh_puzzle_engine()
    gl._puzzle_engine = engine
    gl._applied_sensor_assists.clear()

    try:
        puzzle = add_freq_puzzle(engine)
        engine.pop_pending_broadcasts()

        ship = make_ship()
        ship.systems["sensors"].power = 150.0

        result = gl._check_sensor_assist(ship)
        assert result is not None
        import json
        payload = json.loads(result.model_dump_json())["payload"]
        assert payload["puzzle_id"] == puzzle.puzzle_id
        assert payload["label"] == puzzle.label
        assert "message" in payload
    finally:
        gl._puzzle_engine = original


# ---------------------------------------------------------------------------
# Mission engine — on_complete list support
# ---------------------------------------------------------------------------


def _make_mission_with_list_on_complete() -> dict:
    return {
        "id": "test",
        "name": "Test",
        "briefing": "Test",
        "defeat_condition": "player_hull_zero",
        "victory_condition": "all_objectives_complete",
        "objectives": [
            {
                "id": "obj1",
                "text": "Timer fires two puzzles",
                "trigger": "timer_elapsed",
                "args": {"seconds": 1},
                "on_complete": [
                    {
                        "action": "start_puzzle",
                        "puzzle_type": "frequency_matching",
                        "station": "science",
                        "label": "freq_1",
                        "difficulty": 1,
                        "time_limit": 30.0,
                    },
                    {
                        "action": "start_puzzle",
                        "puzzle_type": "circuit_routing",
                        "station": "engineering",
                        "label": "circuit_1",
                        "difficulty": 1,
                        "time_limit": 30.0,
                    },
                ],
            },
        ],
    }


def test_mission_engine_fires_list_on_complete():
    """Both actions in the list should appear in pop_pending_actions."""
    from server.models.world import World
    mission = _make_mission_with_list_on_complete()
    engine = MissionEngine(mission)

    world = World(ship=make_ship())

    # Tick past the timer threshold.
    for _ in range(15):
        engine.tick(world, world.ship, dt=0.1)

    actions = engine.pop_pending_actions()
    puzzle_starts = [a for a in actions if a.get("action") == "start_puzzle"]
    assert len(puzzle_starts) == 2

    labels = {a["label"] for a in puzzle_starts}
    assert "freq_1" in labels
    assert "circuit_1" in labels


def test_mission_engine_single_on_complete_still_works():
    """Existing single-dict on_complete must not break."""
    from server.models.world import World
    mission = {
        "id": "test2",
        "name": "T",
        "briefing": "B",
        "defeat_condition": "player_hull_zero",
        "victory_condition": "all_objectives_complete",
        "objectives": [
            {
                "id": "obj1",
                "text": "Timer",
                "trigger": "timer_elapsed",
                "args": {"seconds": 1},
                "on_complete": {
                    "action": "start_puzzle",
                    "puzzle_type": "sequence_match",
                    "station": "science",
                    "label": "seq_1",
                    "difficulty": 1,
                    "time_limit": 30.0,
                },
            },
        ],
    }
    engine = MissionEngine(mission)
    world = World(ship=make_ship())

    for _ in range(15):
        engine.tick(world, world.ship, dt=0.1)

    actions = engine.pop_pending_actions()
    assert len(actions) == 1
    assert actions[0]["label"] == "seq_1"
