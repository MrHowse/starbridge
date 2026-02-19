"""Tests for the Triage puzzle and Medical expansion (v0.02e).

Covers:
  server/puzzles/triage.py           — TriagePuzzle
  server/game_loop_medical.py        — disease/outbreak mechanics
  server/game_loop_mission.py        — start_outbreak action
  server/game_loop.py                — Science→Medical assist wiring
  missions/plague_ship.json          — mission loadable
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import server.puzzles.triage  # noqa: F401 — registers type
from server.puzzles.engine import PuzzleEngine
from server.puzzles.triage import (
    PATHOGENS,
    SYMPTOM_MAP,
    TREATMENT_MAP,
    TriagePuzzle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh_engine() -> PuzzleEngine:
    return PuzzleEngine()


def make_triage_puzzle(engine: PuzzleEngine, difficulty: int = 2) -> TriagePuzzle:
    puzzle = engine.create_puzzle(
        puzzle_type="triage",
        station="medical",
        label="test_triage",
        difficulty=difficulty,
        time_limit=60.0,
    )
    engine.pop_pending_broadcasts()  # consume puzzle.started
    return puzzle  # type: ignore[return-value]


def correct_diagnoses(puzzle: TriagePuzzle) -> dict:
    return {
        p["id"]: {
            "pathogen":        p["pathogen"],
            "treatment_steps": p["treatment_steps"],
        }
        for p in puzzle._patients
    }


# ---------------------------------------------------------------------------
# TriagePuzzle — generate
# ---------------------------------------------------------------------------


def test_generate_returns_patients_and_options():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=2)
    assert puzzle._patients
    assert len(puzzle._patients) == 2


def test_generate_difficulty_1_has_2_patients_1_prediagnosed():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=1)
    assert len(puzzle._patients) == 2
    prediag = [p for p in puzzle._patients if p["pre_diagnosed"]]
    assert len(prediag) == 1


def test_generate_difficulty_2_has_2_patients_none_prediagnosed():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=2)
    assert len(puzzle._patients) == 2
    prediag = [p for p in puzzle._patients if p["pre_diagnosed"]]
    assert len(prediag) == 0


def test_generate_difficulty_3_has_3_patients():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=3)
    assert len(puzzle._patients) == 3


def test_generate_difficulty_4_has_4_patients():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=4)
    assert len(puzzle._patients) == 4


def test_generate_difficulty_5_has_5_patients():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=5)
    assert len(puzzle._patients) == 5


def test_generate_patients_have_unique_pathogens():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=3)
    pathogens = [p["pathogen"] for p in puzzle._patients]
    assert len(pathogens) == len(set(pathogens))


def test_generate_pathogens_are_valid():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=3)
    for patient in puzzle._patients:
        assert patient["pathogen"] in PATHOGENS


def test_generate_symptoms_match_pathogen():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=3)
    for patient in puzzle._patients:
        assert patient["symptoms"] == SYMPTOM_MAP[patient["pathogen"]]


def test_generate_treatment_steps_match_pathogen():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=3)
    for patient in puzzle._patients:
        assert patient["treatment_steps"] == TREATMENT_MAP[patient["pathogen"]]


def test_generate_prediagnosed_patient_has_pathogen_in_data():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=1)
    # The puzzle data sent to clients: pre-diagnosed patient reveals pathogen
    prediag = next(p for p in puzzle._patients if p["pre_diagnosed"])
    assert puzzle._diagnosed_flags[prediag["id"]] is True


def test_generate_undiagnosed_flag_is_false():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=2)
    for patient in puzzle._patients:
        assert puzzle._diagnosed_flags[patient["id"]] is False


def test_generate_available_pathogens_in_data():
    engine = fresh_engine()
    # Check puzzle.started broadcast contains available_pathogens
    engine2 = fresh_engine()
    engine2.create_puzzle(
        puzzle_type="triage",
        station="medical",
        label="x",
        difficulty=2,
        time_limit=60.0,
    )
    broadcasts = engine2.pop_pending_broadcasts()
    started = next(
        (m for _, m in broadcasts if m.type == "puzzle.started"),
        None,
    )
    assert started is not None
    assert "available_pathogens" in started.payload["data"]
    assert "available_treatments" in started.payload["data"]


# ---------------------------------------------------------------------------
# TriagePuzzle — validate_submission
# ---------------------------------------------------------------------------


def test_validate_correct_submission():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=2)
    assert puzzle.validate_submission({"diagnoses": correct_diagnoses(puzzle)}) is True


def test_validate_correct_submission_difficulty_1():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=1)
    assert puzzle.validate_submission({"diagnoses": correct_diagnoses(puzzle)}) is True


def test_validate_missing_patient_returns_false():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=2)
    diag = correct_diagnoses(puzzle)
    # Remove one patient
    key = list(diag.keys())[0]
    del diag[key]
    assert puzzle.validate_submission({"diagnoses": diag}) is False


def test_validate_wrong_pathogen_returns_false():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=2)
    diag = correct_diagnoses(puzzle)
    first = list(diag.keys())[0]
    # Find a different pathogen
    wrong = next(p for p in PATHOGENS if p != diag[first]["pathogen"])
    diag[first]["pathogen"] = wrong
    assert puzzle.validate_submission({"diagnoses": diag}) is False


def test_validate_wrong_treatment_order_returns_false():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=2)
    diag = correct_diagnoses(puzzle)
    first = list(diag.keys())[0]
    # Reverse the treatment steps
    diag[first]["treatment_steps"] = list(reversed(diag[first]["treatment_steps"]))
    assert puzzle.validate_submission({"diagnoses": diag}) is False


def test_validate_empty_submission_returns_false():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=2)
    assert puzzle.validate_submission({}) is False


def test_validate_non_dict_diagnoses_returns_false():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=2)
    assert puzzle.validate_submission({"diagnoses": "invalid"}) is False


# ---------------------------------------------------------------------------
# TriagePuzzle — apply_assist (reveal_pathogen)
# ---------------------------------------------------------------------------


def test_apply_assist_reveal_pathogen_returns_patient_and_pathogen():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=2)
    result = puzzle.apply_assist("reveal_pathogen", {})
    assert "patient_id" in result
    assert "pathogen" in result
    assert result["pathogen"] in PATHOGENS


def test_apply_assist_reveal_pathogen_matches_actual_pathogen():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=2)
    result = puzzle.apply_assist("reveal_pathogen", {})
    pid = result["patient_id"]
    actual_pathogen = next(p["pathogen"] for p in puzzle._patients if p["id"] == pid)
    assert result["pathogen"] == actual_pathogen


def test_apply_assist_marks_patient_as_diagnosed():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=2)
    result = puzzle.apply_assist("reveal_pathogen", {})
    pid = result["patient_id"]
    assert puzzle._diagnosed_flags[pid] is True


def test_apply_assist_idempotent_when_all_diagnosed():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=1)  # 1 pre-diagnosed, 1 not
    # Reveal the remaining undiagnosed patient
    puzzle.apply_assist("reveal_pathogen", {})
    # All diagnosed — second call returns empty
    result = puzzle.apply_assist("reveal_pathogen", {})
    assert result == {}


def test_apply_assist_unknown_type_returns_empty():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=2)
    assert puzzle.apply_assist("bad_type", {}) == {}


def test_apply_assist_difficulty_1_no_reveal_when_all_prediagnosed_after_one():
    engine = fresh_engine()
    puzzle = make_triage_puzzle(engine, difficulty=1)
    # difficulty=1: patient_0 is pre-diagnosed, patient_1 is not
    first = puzzle.apply_assist("reveal_pathogen", {})
    assert first != {}
    # Now both are diagnosed
    second = puzzle.apply_assist("reveal_pathogen", {})
    assert second == {}


# ---------------------------------------------------------------------------
# game_loop_medical — disease mechanics
# ---------------------------------------------------------------------------


def test_reset_clears_disease_state():
    import server.game_loop_medical as glmed
    glmed.start_outbreak("engineering", "Kessler Plague")
    glmed.reset()
    state = glmed.get_disease_state()
    assert state["infected_decks"] == {}
    assert state["spread_timer"] == 0.0


def test_start_outbreak_sets_deck_infected():
    import server.game_loop_medical as glmed
    glmed.reset()
    glmed.start_outbreak("engineering", "Kessler Plague")
    state = glmed.get_disease_state()
    assert state["infected_decks"]["engineering"] == "Kessler Plague"


def test_start_outbreak_idempotent():
    import server.game_loop_medical as glmed
    glmed.reset()
    glmed.start_outbreak("medical", "Velorian Flu")
    glmed.start_outbreak("medical", "Kessler Plague")  # different pathogen
    state = glmed.get_disease_state()
    # First pathogen wins (idempotent)
    assert state["infected_decks"]["medical"] == "Velorian Flu"


def test_tick_disease_no_outbreak_returns_empty():
    import server.game_loop_medical as glmed
    glmed.reset()
    from server.models.interior import make_default_interior
    interior = make_default_interior()
    events = glmed.tick_disease(interior, 1.0)
    assert events == []


def test_tick_disease_no_spread_before_interval():
    import server.game_loop_medical as glmed
    glmed.reset()
    glmed.start_outbreak("medical", "Kessler Plague")
    from server.models.interior import make_default_interior
    interior = make_default_interior()
    events = glmed.tick_disease(interior, 5.0)  # less than SPREAD_INTERVAL
    assert events == []


def test_tick_disease_spread_after_interval():
    import server.game_loop_medical as glmed
    glmed.reset()
    # Medical deck connects to engineering (surgery ↔ engine_room in default interior)
    glmed.start_outbreak("medical", "Kessler Plague")
    from server.models.interior import make_default_interior
    interior = make_default_interior()
    # Advance past spread interval
    events = glmed.tick_disease(interior, glmed.SPREAD_INTERVAL)
    assert len(events) > 0
    # Check that engineering got infected (medical → engineering via surgery→engine_room)
    to_decks = {e["to_deck"] for e in events}
    assert "engineering" in to_decks


def test_tick_disease_no_spread_with_sealed_door():
    import server.game_loop_medical as glmed
    glmed.reset()
    glmed.start_outbreak("medical", "Kessler Plague")
    from server.models.interior import make_default_interior
    interior = make_default_interior()
    # Seal the surgery room (the cross-deck connector from medical)
    interior.rooms["surgery"].door_sealed = True
    events = glmed.tick_disease(interior, glmed.SPREAD_INTERVAL)
    # medical→weapons (torpedo_room connects to surgery but surgery is sealed) still checked
    # The actual spread: surgery is sealed, so no spread from medical via surgery
    # But engine_room connects to surgery too — sealed is on surgery side
    # Spread checks: room.door_sealed OR conn_room.door_sealed
    # surgery.door_sealed = True, so any connection THROUGH surgery is blocked
    to_decks = {e["to_deck"] for e in events}
    assert "engineering" not in to_decks


def test_tick_disease_spread_event_has_correct_fields():
    import server.game_loop_medical as glmed
    glmed.reset()
    glmed.start_outbreak("medical", "Kessler Plague")
    from server.models.interior import make_default_interior
    interior = make_default_interior()
    events = glmed.tick_disease(interior, glmed.SPREAD_INTERVAL)
    for evt in events:
        assert "from_deck" in evt
        assert "to_deck" in evt
        assert "pathogen" in evt
        assert evt["pathogen"] == "Kessler Plague"


def test_tick_disease_resets_timer_after_spread():
    import server.game_loop_medical as glmed
    glmed.reset()
    glmed.start_outbreak("medical", "Void Rot")
    from server.models.interior import make_default_interior
    interior = make_default_interior()
    glmed.tick_disease(interior, glmed.SPREAD_INTERVAL)
    state = glmed.get_disease_state()
    assert state["spread_timer"] == 0.0


def test_get_disease_state_includes_interval():
    import server.game_loop_medical as glmed
    glmed.reset()
    state = glmed.get_disease_state()
    assert state["spread_interval"] == glmed.SPREAD_INTERVAL


# ---------------------------------------------------------------------------
# game_loop_mission — start_outbreak action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_mission_queues_start_outbreak():
    import server.game_loop_mission as glm
    glm.reset()

    # Build a minimal mission with start_outbreak on_complete
    from server.missions.engine import MissionEngine
    mission = {
        "id": "test",
        "objectives": [{
            "id": "obj1",
            "text": "desc",
            "trigger": "timer_elapsed",
            "args": {"seconds": 0},
            "on_complete": {"action": "start_outbreak", "deck": "engineering", "pathogen": "Void Rot"},
        }],
    }
    glm._mission_engine = MissionEngine(mission)

    from server.models.world import World
    from server.models.ship import Ship
    world = World(ship=Ship())
    manager = AsyncMock()
    manager.broadcast = AsyncMock()

    await glm.tick_mission(world, world.ship, manager, 1.0)
    outbreaks = glm.pop_pending_outbreaks()
    assert len(outbreaks) == 1
    assert outbreaks[0]["deck"] == "engineering"
    assert outbreaks[0]["pathogen"] == "Void Rot"


def test_pop_pending_outbreaks_clears_queue():
    import server.game_loop_mission as glm
    glm.reset()
    glm._pending_outbreaks.append({"deck": "medical", "pathogen": "Nebula Fever"})
    first = glm.pop_pending_outbreaks()
    assert len(first) == 1
    second = glm.pop_pending_outbreaks()
    assert second == []


def test_reset_clears_pending_outbreaks():
    import server.game_loop_mission as glm
    glm._pending_outbreaks.append({"deck": "medical", "pathogen": "Nebula Fever"})
    glm.reset()
    assert glm._pending_outbreaks == []


# ---------------------------------------------------------------------------
# Plague Ship mission loadable
# ---------------------------------------------------------------------------


def test_plague_ship_mission_loadable():
    from server.missions.loader import load_mission
    mission = load_mission("plague_ship")
    assert mission["name"] == "Plague Ship"
    assert len(mission["objectives"]) == 3


def test_plague_ship_mission_has_start_outbreak_action():
    from server.missions.loader import load_mission
    mission = load_mission("plague_ship")
    first_obj = mission["objectives"][0]
    on_complete = first_obj["on_complete"]
    # on_complete is a list
    actions = on_complete if isinstance(on_complete, list) else [on_complete]
    outbreak_actions = [a for a in actions if a.get("action") == "start_outbreak"]
    assert len(outbreak_actions) == 1
    assert outbreak_actions[0]["pathogen"] == "Kessler Plague"


def test_plague_ship_mission_has_triage_puzzle():
    from server.missions.loader import load_mission
    mission = load_mission("plague_ship")
    first_obj = mission["objectives"][0]
    on_complete = first_obj["on_complete"]
    actions = on_complete if isinstance(on_complete, list) else [on_complete]
    puzzle_actions = [a for a in actions if a.get("action") == "start_puzzle"]
    assert len(puzzle_actions) == 1
    assert puzzle_actions[0]["puzzle_type"] == "triage"
