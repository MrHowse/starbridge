"""Tests for the Tactical Positioning puzzle and related infrastructure.

Covers:
  server/puzzles/tactical_positioning.py  — generate, validate_submission, apply_assist
  server/puzzles/base.py                  — **_kwargs forwarding
  server/puzzles/engine.py                — extra params forwarded to constructor
  server/game_loop_security.py            — deploy_squads, start_boarding(empty squads)
  server/game_loop_mission.py             — _pending_deployments, pop_pending_deployments,
                                            deploy_squads action in tick_mission
  server/missions/engine.py               — puzzle_resolved trigger type
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

import server.game_loop_security as gls
import server.game_loop_mission as glm
import server.puzzles.tactical_positioning  # noqa: F401 — registers the type
from server.missions.engine import MissionEngine
from server.models.interior import ShipInterior, make_default_interior
from server.models.security import MarineSquad
from server.models.ship import Ship
from server.models.world import World
from server.puzzles.base import PuzzleInstance
from server.puzzles.engine import PuzzleEngine
from server.puzzles.tactical_positioning import TacticalPositioningPuzzle


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def fresh_interior() -> ShipInterior:
    return make_default_interior()


def fresh_ship() -> Ship:
    return Ship()


def make_tp_puzzle(
    interior: ShipInterior | None = None,
    intruder_specs: list[dict] | None = None,
    **kwargs,
) -> TacticalPositioningPuzzle:
    """Create a TacticalPositioningPuzzle with sensible defaults."""
    if interior is None:
        interior = fresh_interior()
    if intruder_specs is None:
        intruder_specs = [
            {"id": "intruder_1", "room_id": "engine_room", "objective_id": "conn"},
        ]
    defaults = dict(
        puzzle_id="puzzle_test",
        label="position_squads",
        station="security",
        difficulty=2,
        time_limit=60.0,
    )
    defaults.update(kwargs)
    return TacticalPositioningPuzzle(
        interior=interior,
        intruder_specs=intruder_specs,
        **defaults,
    )


TWO_INTRUDER_SPECS = [
    {"id": "intruder_1", "room_id": "engine_room", "objective_id": "conn"},
    {"id": "intruder_2", "room_id": "engine_room", "objective_id": "torpedo_room"},
]


def setup_function():
    """Reset gls and glm state before each test."""
    gls.reset()
    glm.reset()


# ---------------------------------------------------------------------------
# TacticalPositioningPuzzle — generate()
# ---------------------------------------------------------------------------


def test_generate_returns_intruder_threats():
    puzzle = make_tp_puzzle(intruder_specs=TWO_INTRUDER_SPECS)
    data = puzzle.generate()
    assert "intruder_threats" in data
    assert len(data["intruder_threats"]) == 2


def test_generate_threat_fields():
    puzzle = make_tp_puzzle(intruder_specs=TWO_INTRUDER_SPECS)
    data = puzzle.generate()
    threat = data["intruder_threats"][0]
    assert threat["id"] == "intruder_1"
    assert threat["room_id"] == "engine_room"
    assert threat["objective_id"] == "conn"


def test_generate_empty_intruder_specs():
    puzzle = make_tp_puzzle(intruder_specs=[])
    data = puzzle.generate()
    assert data["intruder_threats"] == []


# ---------------------------------------------------------------------------
# TacticalPositioningPuzzle — validate_submission()
# ---------------------------------------------------------------------------


def test_validate_submission_confirmed_false_returns_false():
    puzzle = make_tp_puzzle()
    assert puzzle.validate_submission({"confirmed": False}) is False


def test_validate_submission_missing_confirmed_returns_false():
    puzzle = make_tp_puzzle()
    assert puzzle.validate_submission({}) is False


def test_validate_submission_good_positions_returns_true():
    """squad_1@conn and squad_2@torpedo_room can defeat both intruders."""
    interior = fresh_interior()
    # Pre-position squads as if deploy_squads + player moves were done.
    interior.marine_squads = [
        MarineSquad(id="squad_1", room_id="conn"),
        MarineSquad(id="squad_2", room_id="torpedo_room"),
    ]
    puzzle = make_tp_puzzle(interior=interior, intruder_specs=TWO_INTRUDER_SPECS)
    assert puzzle.validate_submission({"confirmed": True}) is True


def test_validate_submission_bad_positions_returns_false():
    """Both squads at conn: intruder_2 (→torpedo_room) is never intercepted."""
    interior = fresh_interior()
    interior.marine_squads = [
        MarineSquad(id="squad_1", room_id="conn"),
        MarineSquad(id="squad_2", room_id="conn"),
    ]
    puzzle = make_tp_puzzle(interior=interior, intruder_specs=TWO_INTRUDER_SPECS)
    assert puzzle.validate_submission({"confirmed": True}) is False


def test_validate_submission_does_not_mutate_live_interior():
    """validate_submission must use a deep copy — live interior unchanged."""
    interior = fresh_interior()
    interior.marine_squads = [MarineSquad(id="squad_1", room_id="conn")]
    puzzle = make_tp_puzzle(interior=interior, intruder_specs=[
        {"id": "intruder_1", "room_id": "engine_room", "objective_id": "conn"},
    ])
    puzzle.validate_submission({"confirmed": True})
    # Live interior should still have the original squads, no intruders left on it.
    assert len(interior.marine_squads) == 1
    assert interior.marine_squads[0].room_id == "conn"
    assert interior.intruders == []


def test_validate_submission_no_squads_returns_false():
    """No squads → intruder can never be defeated."""
    interior = fresh_interior()
    # No squads placed.
    puzzle = make_tp_puzzle(interior=interior, intruder_specs=TWO_INTRUDER_SPECS)
    assert puzzle.validate_submission({"confirmed": True}) is False


def test_validate_submission_empty_intruder_specs_returns_true():
    """If there are no intruders, the boarding is trivially won."""
    interior = fresh_interior()
    interior.marine_squads = [MarineSquad(id="squad_1", room_id="conn")]
    puzzle = make_tp_puzzle(interior=interior, intruder_specs=[])
    assert puzzle.validate_submission({"confirmed": True}) is True


# ---------------------------------------------------------------------------
# TacticalPositioningPuzzle — apply_assist()
# ---------------------------------------------------------------------------


def test_apply_assist_reveal_interception_points_returns_midpoints():
    interior = fresh_interior()
    # Path engine_room → conn: [engine_room, surgery, torpedo_room, science_lab, conn]
    # Midpoint at index 2: torpedo_room
    puzzle = make_tp_puzzle(interior=interior, intruder_specs=[
        {"id": "intruder_1", "room_id": "engine_room", "objective_id": "conn"},
    ])
    result = puzzle.apply_assist("reveal_interception_points", {})
    assert "interception_points" in result
    assert "torpedo_room" in result["interception_points"]


def test_apply_assist_deduplicates_shared_midpoints():
    """Two intruders sharing the same path midpoint yield one point."""
    interior = fresh_interior()
    puzzle = make_tp_puzzle(interior=interior, intruder_specs=[
        {"id": "intruder_1", "room_id": "engine_room", "objective_id": "conn"},
        {"id": "intruder_2", "room_id": "engine_room", "objective_id": "conn"},
    ])
    result = puzzle.apply_assist("reveal_interception_points", {})
    points = result["interception_points"]
    assert len(points) == len(set(points))  # no duplicates


def test_apply_assist_unknown_type_returns_empty():
    puzzle = make_tp_puzzle()
    result = puzzle.apply_assist("nonexistent_assist", {})
    assert result == {}


# ---------------------------------------------------------------------------
# PuzzleInstance — **_kwargs forwarding
# ---------------------------------------------------------------------------


def test_base_puzzle_init_absorbs_extra_kwargs():
    """PuzzleInstance.__init__ should not raise when given extra kwargs."""
    from server.puzzles.sequence_match import SequenceMatchPuzzle
    import server.puzzles.sequence_match  # noqa: F401

    # SequenceMatchPuzzle uses **kwargs → super().__init__(**kwargs).
    # Extra kwargs should be silently absorbed by the base **_kwargs parameter.
    puzzle = SequenceMatchPuzzle(
        puzzle_id="p1", label="test", station="science",
        difficulty=1, time_limit=30.0, extra_param="ignored",
    )
    assert puzzle.puzzle_id == "p1"


# ---------------------------------------------------------------------------
# PuzzleEngine — extra params forwarded to constructor
# ---------------------------------------------------------------------------


def test_puzzle_engine_forwards_extra_params_to_tactical_puzzle():
    """create_puzzle must pass interior= and intruder_specs= to the constructor."""
    engine = PuzzleEngine()
    interior = fresh_interior()
    interior.marine_squads = [MarineSquad(id="squad_1", room_id="conn")]
    specs = [{"id": "intruder_1", "room_id": "engine_room", "objective_id": "conn"}]

    inst = engine.create_puzzle(
        puzzle_type="tactical_positioning",
        station="security",
        label="pos",
        difficulty=2,
        time_limit=60.0,
        interior=interior,
        intruder_specs=specs,
    )
    assert inst is not None
    assert isinstance(inst, TacticalPositioningPuzzle)
    assert inst._interior is interior
    assert inst._intruder_specs == specs


def test_puzzle_engine_create_tactical_puzzle_has_correct_metadata():
    engine = PuzzleEngine()
    interior = fresh_interior()
    inst = engine.create_puzzle(
        puzzle_type="tactical_positioning",
        station="security",
        label="pos_test",
        difficulty=3,
        time_limit=45.0,
        interior=interior,
        intruder_specs=[],
    )
    assert inst is not None
    assert inst.station == "security"
    assert inst.difficulty == 3
    assert inst.time_limit == 45.0
    assert inst.label == "pos_test"


# ---------------------------------------------------------------------------
# gls.deploy_squads()
# ---------------------------------------------------------------------------


def test_deploy_squads_places_squads_on_interior():
    interior = fresh_interior()
    gls.deploy_squads(interior, [
        {"id": "squad_1", "room_id": "conn"},
        {"id": "squad_2", "room_id": "torpedo_room"},
    ])
    assert len(interior.marine_squads) == 2
    assert interior.marine_squads[0].room_id == "conn"
    assert interior.marine_squads[1].room_id == "torpedo_room"


def test_deploy_squads_does_not_activate_boarding():
    interior = fresh_interior()
    gls.deploy_squads(interior, [{"id": "squad_1", "room_id": "conn"}])
    assert gls.is_boarding_active() is False


def test_deploy_squads_replaces_existing_squads():
    interior = fresh_interior()
    gls.deploy_squads(interior, [{"id": "squad_1", "room_id": "bridge"}])
    gls.deploy_squads(interior, [{"id": "squad_2", "room_id": "conn"}])
    assert len(interior.marine_squads) == 1
    assert interior.marine_squads[0].id == "squad_2"


# ---------------------------------------------------------------------------
# gls.start_boarding() — empty squad_specs preserves existing squads
# ---------------------------------------------------------------------------


def test_start_boarding_empty_squads_preserves_deployed_squads():
    interior = fresh_interior()
    gls.deploy_squads(interior, [
        {"id": "squad_1", "room_id": "conn"},
        {"id": "squad_2", "room_id": "torpedo_room"},
    ])
    # Activate boarding without specifying squads — preserves planning placement.
    gls.start_boarding(interior, [], [
        {"id": "intruder_1", "room_id": "engine_room", "objective_id": "conn"},
    ])
    assert gls.is_boarding_active() is True
    # Squads from deploy_squads should still be in place.
    assert len(interior.marine_squads) == 2
    squad_rooms = {sq.room_id for sq in interior.marine_squads}
    assert "conn" in squad_rooms
    assert "torpedo_room" in squad_rooms


def test_start_boarding_with_squads_replaces_deployed_squads():
    interior = fresh_interior()
    gls.deploy_squads(interior, [{"id": "squad_1", "room_id": "conn"}])
    gls.start_boarding(interior, [{"id": "squad_2", "room_id": "bridge"}], [])
    assert len(interior.marine_squads) == 1
    assert interior.marine_squads[0].id == "squad_2"


# ---------------------------------------------------------------------------
# MissionEngine — puzzle_resolved trigger
# ---------------------------------------------------------------------------


def _make_puzzle_resolved_mission() -> MissionEngine:
    mission = {
        "objectives": [{
            "id": "obj1",
            "text": "Position squads",
            "trigger": "puzzle_resolved",
            "args": {"puzzle_label": "my_puzzle"},
            "on_complete": [],
        }],
        "victory_condition": "all_objectives_complete",
    }
    return MissionEngine(mission)


def test_puzzle_resolved_trigger_false_when_not_resolved():
    engine = _make_puzzle_resolved_mission()
    world = World()
    ship = Ship()
    assert engine._check_trigger(engine._obj_defs[0], world, ship) is False


def test_puzzle_resolved_trigger_true_on_success():
    engine = _make_puzzle_resolved_mission()
    world = World()
    ship = Ship()
    engine.notify_puzzle_result("my_puzzle", True)
    assert engine._check_trigger(engine._obj_defs[0], world, ship) is True


def test_puzzle_resolved_trigger_true_on_failure():
    engine = _make_puzzle_resolved_mission()
    world = World()
    ship = Ship()
    engine.notify_puzzle_result("my_puzzle", False)
    assert engine._check_trigger(engine._obj_defs[0], world, ship) is True


def test_puzzle_resolved_trigger_false_for_different_label():
    engine = _make_puzzle_resolved_mission()
    world = World()
    ship = Ship()
    engine.notify_puzzle_result("other_puzzle", True)
    assert engine._check_trigger(engine._obj_defs[0], world, ship) is False


# ---------------------------------------------------------------------------
# glm.pop_pending_deployments()
# ---------------------------------------------------------------------------


def test_pop_pending_deployments_empty_initially():
    assert glm.pop_pending_deployments() == []


def test_pop_pending_deployments_clears_after_pop():
    # We'll inject via tick_mission by setting up a mission that fires deploy_squads.
    glm._pending_deployments.append({"action": "deploy_squads", "squads": []})
    result = glm.pop_pending_deployments()
    assert len(result) == 1
    assert glm.pop_pending_deployments() == []


# ---------------------------------------------------------------------------
# glm.tick_mission() — handles deploy_squads action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_mission_queues_deploy_squads_action():
    """tick_mission should queue deploy_squads actions to _pending_deployments."""
    mission = {
        "objectives": [{
            "id": "obj1",
            "text": "Deploy",
            "trigger": "timer_elapsed",
            "args": {"seconds": 0},
            "on_complete": [{"action": "deploy_squads", "squads": [
                {"id": "squad_1", "room_id": "conn"},
            ]}],
        }],
        "victory_condition": "all_objectives_complete",
    }
    glm._mission_engine = MissionEngine(mission)
    world = World()
    ship = Ship()
    mock_manager = AsyncMock()
    mock_manager.broadcast = AsyncMock()

    await glm.tick_mission(world, ship, mock_manager, dt=0.1)

    deployments = glm.pop_pending_deployments()
    assert len(deployments) == 1
    assert deployments[0]["action"] == "deploy_squads"
    assert deployments[0]["squads"] == [{"id": "squad_1", "room_id": "conn"}]


@pytest.mark.asyncio
async def test_tick_mission_does_not_queue_deploy_as_boarding():
    """deploy_squads action must NOT appear in pending_boardings."""
    mission = {
        "objectives": [{
            "id": "obj1",
            "text": "Deploy",
            "trigger": "timer_elapsed",
            "args": {"seconds": 0},
            "on_complete": [{"action": "deploy_squads", "squads": []}],
        }],
        "victory_condition": "all_objectives_complete",
    }
    glm._mission_engine = MissionEngine(mission)
    world = World()
    ship = Ship()
    mock_manager = AsyncMock()
    mock_manager.broadcast = AsyncMock()

    await glm.tick_mission(world, ship, mock_manager, dt=0.1)

    assert glm.pop_pending_boardings() == []


# ---------------------------------------------------------------------------
# Integration: deploy_squads + tactical puzzle + boarding chain
# ---------------------------------------------------------------------------


def test_integration_deploy_then_boarding_preserves_squads():
    """End-to-end: deploy squads, then start_boarding with empty list."""
    interior = fresh_interior()

    # Step 1: deploy squads (planning phase)
    gls.deploy_squads(interior, [
        {"id": "squad_1", "room_id": "conn"},
        {"id": "squad_2", "room_id": "torpedo_room"},
    ])
    assert not gls.is_boarding_active()
    assert len(interior.marine_squads) == 2

    # Step 2: puzzle resolves, boarding starts (squads=[])
    gls.start_boarding(interior, [], [
        {"id": "intruder_1", "room_id": "engine_room", "objective_id": "conn"},
    ])
    assert gls.is_boarding_active()
    # Squads preserved from planning phase.
    squad_rooms = {sq.room_id for sq in interior.marine_squads}
    assert squad_rooms == {"conn", "torpedo_room"}
    assert len(interior.intruders) == 1


def test_integration_puzzle_validate_after_player_moves():
    """Simulate player moving a squad then confirming — should be valid."""
    interior = fresh_interior()
    # Deploy squads at default positions.
    gls.deploy_squads(interior, [
        {"id": "squad_1", "room_id": "bridge"},      # suboptimal
        {"id": "squad_2", "room_id": "torpedo_room"},
    ])
    # "Player" moves squad_1 to conn (better position).
    gls.move_squad(interior, "squad_1", "conn")
    assert any(sq.room_id == "conn" for sq in interior.marine_squads)

    # Puzzle validates the final placement.
    puzzle = make_tp_puzzle(interior=interior, intruder_specs=TWO_INTRUDER_SPECS)
    # Both squads now in good positions → should succeed.
    result = puzzle.validate_submission({"confirmed": True})
    assert result is True
