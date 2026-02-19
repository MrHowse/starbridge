"""Tests for puzzle engine integration with the mission engine and game loop mission.

Covers:
  server/missions/engine.py     — puzzle_completed / puzzle_failed trigger types,
                                   notify_puzzle_result()
  server/game_loop_mission.py   — start_puzzle on_complete action handling,
                                   pop_pending_puzzle_starts()
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from server.missions.engine import MissionEngine
import server.game_loop_mission as glm
from server.models.world import World
from server.models.ship import Ship


def _mock_manager():
    m = AsyncMock()
    m.broadcast = AsyncMock()
    return m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_world() -> World:
    return World()


def make_ship() -> Ship:
    return Ship()


def make_mission_engine(objectives: list[dict], **kwargs) -> MissionEngine:
    mission = {
        "defeat_condition": "player_hull_zero",
        "victory_condition": "all_objectives_complete",
        "objectives": objectives,
        **kwargs,
    }
    return MissionEngine(mission)


# ---------------------------------------------------------------------------
# MissionEngine — notify_puzzle_result + puzzle_completed trigger
# ---------------------------------------------------------------------------


def test_puzzle_completed_trigger_not_met_before_notify():
    engine = make_mission_engine([{
        "id": "solve",
        "text": "Solve the puzzle",
        "trigger": "puzzle_completed",
        "args": {"puzzle_label": "my_puzzle"},
    }])
    world = make_world()
    ship = make_ship()

    completed = engine.tick(world, ship, dt=0.1)
    assert "solve" not in completed


def test_puzzle_completed_trigger_met_after_notify_success():
    engine = make_mission_engine([{
        "id": "solve",
        "text": "Solve the puzzle",
        "trigger": "puzzle_completed",
        "args": {"puzzle_label": "my_puzzle"},
    }])
    world = make_world()
    ship = make_ship()

    engine.notify_puzzle_result("my_puzzle", success=True)
    completed = engine.tick(world, ship, dt=0.1)
    assert "solve" in completed


def test_puzzle_completed_trigger_not_met_after_notify_failure():
    engine = make_mission_engine([{
        "id": "solve",
        "text": "Solve the puzzle",
        "trigger": "puzzle_completed",
        "args": {"puzzle_label": "my_puzzle"},
    }])
    world = make_world()
    ship = make_ship()

    engine.notify_puzzle_result("my_puzzle", success=False)
    completed = engine.tick(world, ship, dt=0.1)
    assert "solve" not in completed


def test_puzzle_completed_wrong_label_not_met():
    engine = make_mission_engine([{
        "id": "solve",
        "text": "Solve the puzzle",
        "trigger": "puzzle_completed",
        "args": {"puzzle_label": "my_puzzle"},
    }])
    world = make_world()
    ship = make_ship()

    engine.notify_puzzle_result("other_puzzle", success=True)
    completed = engine.tick(world, ship, dt=0.1)
    assert "solve" not in completed


# ---------------------------------------------------------------------------
# MissionEngine — puzzle_failed trigger
# ---------------------------------------------------------------------------


def test_puzzle_failed_trigger_met_after_notify_failure():
    engine = make_mission_engine([{
        "id": "failed",
        "text": "Puzzle failed",
        "trigger": "puzzle_failed",
        "args": {"puzzle_label": "hard_puzzle"},
    }])
    world = make_world()
    ship = make_ship()

    engine.notify_puzzle_result("hard_puzzle", success=False)
    completed = engine.tick(world, ship, dt=0.1)
    assert "failed" in completed


def test_puzzle_failed_trigger_not_met_after_success():
    engine = make_mission_engine([{
        "id": "failed",
        "text": "Puzzle failed",
        "trigger": "puzzle_failed",
        "args": {"puzzle_label": "hard_puzzle"},
    }])
    world = make_world()
    ship = make_ship()

    engine.notify_puzzle_result("hard_puzzle", success=True)
    completed = engine.tick(world, ship, dt=0.1)
    assert "failed" not in completed


# ---------------------------------------------------------------------------
# game_loop_mission — pop_pending_puzzle_starts
# ---------------------------------------------------------------------------


def test_pop_pending_puzzle_starts_empty_initially():
    glm.reset()
    assert glm.pop_pending_puzzle_starts() == []


@pytest.mark.asyncio
async def test_pop_pending_puzzle_starts_after_on_complete_action():
    """tick_mission() with a start_puzzle on_complete should populate pending starts."""
    glm.reset()
    # Build a minimal mission that immediately fires start_puzzle on_complete.
    from server.missions.engine import MissionEngine
    engine = MissionEngine({
        "defeat_condition": "player_hull_zero",
        "victory_condition": "all_objectives_complete",
        "objectives": [{
            "id": "obj",
            "text": "always true",
            "trigger": "timer_elapsed",
            "args": {"seconds": 0},
            "on_complete": {
                "action": "start_puzzle",
                "puzzle_type": "sequence_match",
                "station": "science",
                "label": "oc_puzzle",
                "difficulty": 2,
                "time_limit": 45.0,
            },
        }],
    })
    # Manually inject the mission engine into glm to simulate init_mission.
    glm._mission_engine = engine  # type: ignore[attr-defined]

    world = make_world()
    ship = make_ship()

    await glm.tick_mission(world, ship, _mock_manager(), dt=0.2)

    starts = glm.pop_pending_puzzle_starts()
    assert len(starts) == 1
    assert starts[0]["action"] == "start_puzzle"
    assert starts[0]["puzzle_type"] == "sequence_match"
    assert starts[0]["label"] == "oc_puzzle"
    assert starts[0]["station"] == "science"
    assert starts[0]["difficulty"] == 2
    assert starts[0]["time_limit"] == 45.0


@pytest.mark.asyncio
async def test_pop_pending_puzzle_starts_clears_after_call():
    glm.reset()
    from server.missions.engine import MissionEngine
    engine = MissionEngine({
        "defeat_condition": "player_hull_zero",
        "victory_condition": "all_objectives_complete",
        "objectives": [{
            "id": "obj",
            "text": "always true",
            "trigger": "timer_elapsed",
            "args": {"seconds": 0},
            "on_complete": {
                "action": "start_puzzle",
                "puzzle_type": "sequence_match",
                "station": "science",
                "label": "oc_puzzle",
            },
        }],
    })
    glm._mission_engine = engine  # type: ignore[attr-defined]

    world = make_world()
    ship = make_ship()

    await glm.tick_mission(world, ship, _mock_manager(), dt=0.2)

    glm.pop_pending_puzzle_starts()  # consume
    assert glm.pop_pending_puzzle_starts() == []


def test_reset_clears_pending_puzzle_starts():
    glm.reset()
    glm._pending_puzzle_starts.append({"action": "start_puzzle"})  # type: ignore[attr-defined]
    glm.reset()
    assert glm.pop_pending_puzzle_starts() == []


# ---------------------------------------------------------------------------
# Integration: mission_engine + puzzle_engine notify flow
# ---------------------------------------------------------------------------


def test_full_puzzle_lifecycle_in_mission():
    """Timer fires start_puzzle → puzzle resolves → mission objective completes."""
    import server.puzzles.sequence_match  # ensure registered
    from server.puzzles.engine import PuzzleEngine

    puzzle_engine = PuzzleEngine()

    mission_engine = make_mission_engine([
        {
            "id": "wait",
            "text": "Wait",
            "trigger": "timer_elapsed",
            "args": {"seconds": 0},
            "on_complete": {
                "action": "start_puzzle",
                "puzzle_type": "sequence_match",
                "station": "science",
                "label": "int_puzzle",
                "difficulty": 1,
                "time_limit": 30.0,
            },
        },
        {
            "id": "solve",
            "text": "Solve puzzle",
            "trigger": "puzzle_completed",
            "args": {"puzzle_label": "int_puzzle"},
        },
    ])

    world = make_world()
    ship = make_ship()

    # Tick 1: timer fires, on_complete queued.
    newly_done = mission_engine.tick(world, ship, dt=0.2)
    assert "wait" in newly_done

    # Process the on_complete action (start_puzzle) via puzzle engine.
    actions = mission_engine.pop_pending_actions()
    assert len(actions) == 1
    action = actions[0]
    puzzle_instance = puzzle_engine.create_puzzle(
        puzzle_type=action["puzzle_type"],
        station=action["station"],
        label=action["label"],
        difficulty=action.get("difficulty", 1),
        time_limit=action.get("time_limit", 30.0),
    )
    assert puzzle_instance is not None
    puzzle_engine.pop_pending_broadcasts()  # consume puzzle.started

    # "Solve" the puzzle.
    puzzle_engine.submit(puzzle_instance.puzzle_id, {"sequence": puzzle_instance._sequence})
    puzzle_engine.tick(0.0)  # trigger resolution detection
    for _pid, label, success in puzzle_engine.pop_resolved():
        mission_engine.notify_puzzle_result(label, success)

    # Tick 2: puzzle_completed trigger now satisfied.
    newly_done = mission_engine.tick(world, ship, dt=0.1)
    assert "solve" in newly_done
    assert mission_engine.is_over() == (True, "victory")
