"""Tests for the Transmission Decoding puzzle and Comms station integration.

Covers:
  server/puzzles/transmission_decoding.py   — TransmissionDecodingPuzzle
  server/puzzles/frequency_matching.py      — relay_frequency assist
  server/puzzles/engine.py                  — pop_relay_data
  server/game_loop_comms.py                 — comms state module
  server/comms.py                           — handler wiring
  server/lobby.py                           — comms role
  server/models/messages/comms.py           — payload schemas
  server/main.py                            — comms handler registered
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import server.puzzles.transmission_decoding  # noqa: F401 — registers type
import server.puzzles.frequency_matching     # noqa: F401 — registers type
from server.puzzles.engine import PuzzleEngine
from server.puzzles.transmission_decoding import TransmissionDecodingPuzzle
from server.puzzles.frequency_matching import FrequencyMatchingPuzzle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh_engine() -> PuzzleEngine:
    return PuzzleEngine()


def make_td_puzzle(engine: PuzzleEngine, difficulty: int = 1) -> TransmissionDecodingPuzzle:
    puzzle = engine.create_puzzle(
        puzzle_type="transmission_decoding",
        station="comms",
        label="test_decode",
        difficulty=difficulty,
        time_limit=60.0,
    )
    engine.pop_pending_broadcasts()  # consume puzzle.started
    return puzzle  # type: ignore[return-value]


def make_fm_puzzle(engine: PuzzleEngine) -> FrequencyMatchingPuzzle:
    puzzle = engine.create_puzzle(
        puzzle_type="frequency_matching",
        station="science",
        label="test_freq",
        difficulty=1,
        time_limit=60.0,
    )
    engine.pop_pending_broadcasts()  # consume puzzle.started
    return puzzle  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# TransmissionDecodingPuzzle — generate
# ---------------------------------------------------------------------------


def test_generate_returns_symbols_and_equations():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine)
    assert puzzle._symbol_values  # non-empty
    assert puzzle._equations      # non-empty


def test_generate_difficulty_1_has_1_unknown():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=1)
    assert len(puzzle._unknowns) == 1
    assert len(puzzle._revealed) == 2


def test_generate_difficulty_2_has_2_unknowns():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=2)
    assert len(puzzle._unknowns) == 2


def test_generate_difficulty_3_has_3_unknowns():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=3)
    assert len(puzzle._unknowns) == 3


def test_generate_symbol_values_are_unique_1_to_9():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=3)
    vals = list(puzzle._symbol_values.values())
    assert all(1 <= v <= 9 for v in vals)
    assert len(vals) == len(set(vals))  # unique


def test_generate_equations_sums_are_correct():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=2)
    for eq in puzzle._equations:
        syms = eq["symbols"]
        total = eq["total"]
        assert sum(puzzle._symbol_values[s] for s in syms) == total


def test_generate_relay_component_is_set():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=2)
    assert "amplitude" in puzzle._relay_component
    assert "frequency" in puzzle._relay_component
    assert 0.3 <= puzzle._relay_component["amplitude"] <= 1.0
    assert 1.0 <= puzzle._relay_component["frequency"] <= 5.0


# ---------------------------------------------------------------------------
# TransmissionDecodingPuzzle — validate_submission
# ---------------------------------------------------------------------------


def test_validate_correct_submission():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=1)
    correct = {sym: puzzle._symbol_values[sym] for sym in puzzle._unknowns}
    assert puzzle.validate_submission({"mappings": correct}) is True


def test_validate_wrong_value():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=1)
    sym = puzzle._unknowns[0]
    true_val = puzzle._symbol_values[sym]
    wrong_val = (true_val % 9) + 1  # guaranteed different
    assert puzzle.validate_submission({"mappings": {sym: wrong_val}}) is False


def test_validate_missing_symbol():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=2)
    # Submit only one of two unknowns
    sym = puzzle._unknowns[0]
    correct_partial = {sym: puzzle._symbol_values[sym]}
    assert puzzle.validate_submission({"mappings": correct_partial}) is False


def test_validate_non_integer_value():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=1)
    sym = puzzle._unknowns[0]
    assert puzzle.validate_submission({"mappings": {sym: "banana"}}) is False


def test_validate_empty_submission():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=1)
    assert puzzle.validate_submission({}) is False


# ---------------------------------------------------------------------------
# TransmissionDecodingPuzzle — apply_assist
# ---------------------------------------------------------------------------


def test_apply_assist_reveal_symbol_reveals_one_unknown():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=3)
    initial_revealed_count = len(puzzle._revealed)
    result = puzzle.apply_assist("reveal_symbol", {})
    assert result != {}
    sym = result["revealed_symbol"]
    val = result["value"]
    assert sym in puzzle._unknowns
    assert val == puzzle._symbol_values[sym]
    assert sym in puzzle._revealed  # now revealed
    assert len(puzzle._revealed) == initial_revealed_count + 1


def test_apply_assist_idempotent_when_all_revealed():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=1)  # 1 unknown
    puzzle.apply_assist("reveal_symbol", {})  # reveal the only unknown
    result2 = puzzle.apply_assist("reveal_symbol", {})
    assert result2 == {}  # nothing left to reveal


def test_apply_assist_unknown_type_returns_empty():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine)
    assert puzzle.apply_assist("bad_type", {}) == {}


# ---------------------------------------------------------------------------
# PuzzleEngine — pop_relay_data on successful submission
# ---------------------------------------------------------------------------


def test_relay_data_captured_on_success():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=1)
    puzzle_id = None
    # The puzzle is in engine._puzzles; get its id
    for pid, p in engine._puzzles.items():
        if p is puzzle:
            puzzle_id = pid
            break
    assert puzzle_id is not None

    correct = {sym: puzzle._symbol_values[sym] for sym in puzzle._unknowns}
    engine.submit(puzzle_id, {"mappings": correct})
    engine.pop_resolved()

    relay_data = engine.pop_relay_data()
    assert len(relay_data) == 1
    station, component = relay_data[0]
    assert station == "comms"
    assert "amplitude" in component
    assert "frequency" in component


def test_relay_data_not_captured_on_failure():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=1)
    puzzle_id = next(iter(engine._puzzles))
    # Wrong submission
    engine.submit(puzzle_id, {"mappings": {}})
    engine.pop_resolved()
    relay_data = engine.pop_relay_data()
    assert relay_data == []


def test_relay_data_captured_on_timeout():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=1)
    puzzle._time_limit = 0.1
    engine.tick(0.2)
    engine.pop_pending_broadcasts()
    engine.pop_resolved()
    relay_data = engine.pop_relay_data()
    assert relay_data == []  # timeout = failure → no relay


def test_pop_relay_data_clears_on_pop():
    engine = fresh_engine()
    puzzle = make_td_puzzle(engine, difficulty=1)
    puzzle_id = next(iter(engine._puzzles))
    correct = {sym: puzzle._symbol_values[sym] for sym in puzzle._unknowns}
    engine.submit(puzzle_id, {"mappings": correct})
    engine.pop_relay_data()  # first pop
    assert engine.pop_relay_data() == []  # second pop is empty


# ---------------------------------------------------------------------------
# FrequencyMatchingPuzzle — relay_frequency assist
# ---------------------------------------------------------------------------


def test_relay_frequency_returns_closest_component():
    engine = fresh_engine()
    fm = make_fm_puzzle(engine)
    # Pick a frequency close to the first target component
    target = fm._target_components[0]
    relay_data = {"frequency": target["frequency"], "amplitude": target["amplitude"]}
    result = fm.apply_assist("relay_frequency", relay_data)
    assert result["component_index"] == 0
    assert result["amplitude"] == target["amplitude"]
    assert result["frequency"] == target["frequency"]


def test_relay_frequency_finds_nearest_component():
    engine = fresh_engine()
    fm = make_fm_puzzle(engine)
    # Force known component frequencies for deterministic test
    fm._target_components = [
        {"amplitude": 0.5, "frequency": 1.5},
        {"amplitude": 0.8, "frequency": 4.0},
    ]
    fm._component_count = 2
    # Relay near component 1
    result = fm.apply_assist("relay_frequency", {"frequency": 3.9, "amplitude": 0.8})
    assert result["component_index"] == 1


def test_relay_frequency_empty_components():
    engine = fresh_engine()
    fm = make_fm_puzzle(engine)
    fm._target_components = []
    result = fm.apply_assist("relay_frequency", {"frequency": 2.0, "amplitude": 0.5})
    assert result == {}


# ---------------------------------------------------------------------------
# game_loop_comms module
# ---------------------------------------------------------------------------


def test_comms_reset_clears_state():
    import server.game_loop_comms as glco
    glco.tune(0.5)
    glco.reset()
    assert abs(glco._active_frequency - 0.15) < 0.001


def test_comms_tune_updates_frequency():
    import server.game_loop_comms as glco
    glco.reset()
    glco.tune(0.71)
    assert abs(glco._active_frequency - 0.71) < 0.001


def test_comms_tune_clamps_to_range():
    import server.game_loop_comms as glco
    glco.reset()
    glco.tune(-0.5)
    assert glco._active_frequency == 0.0
    glco.tune(1.5)
    assert glco._active_frequency == 1.0


def test_comms_get_tuned_faction_when_on_band():
    import server.game_loop_comms as glco
    glco.reset()
    glco.tune(0.15)  # imperial band
    assert glco.get_tuned_faction() == "imperial"


def test_comms_get_tuned_faction_alien():
    import server.game_loop_comms as glco
    glco.reset()
    glco.tune(0.71)
    assert glco.get_tuned_faction() == "alien"


def test_comms_get_tuned_faction_returns_none_off_band():
    import server.game_loop_comms as glco
    glco.reset()
    glco.tune(0.30)  # between bands
    assert glco.get_tuned_faction() is None


def test_comms_hail_ignored_when_not_tuned():
    import server.game_loop_comms as glco
    glco.reset()
    glco.tune(0.30)  # no faction
    glco.hail("unknown", "negotiate")
    assert glco._pending_hails == []


def test_comms_hail_queued_when_tuned():
    import server.game_loop_comms as glco
    glco.reset()
    glco.tune(0.15)  # imperial
    glco.hail("contact_01", "negotiate")
    assert len(glco._pending_hails) == 1
    assert glco._pending_hails[0]["faction"] == "imperial"


def test_comms_tick_produces_npc_response():
    import server.game_loop_comms as glco
    glco.reset()
    glco.tune(0.15)  # imperial
    glco.hail("contact_01", "negotiate")
    # Advance past hail delay
    responses = glco.tick_comms(3.0)
    assert len(responses) == 1
    assert responses[0]["faction"] == "imperial"
    assert "response_text" in responses[0]


def test_comms_build_state_includes_frequency():
    import server.game_loop_comms as glco
    glco.reset()
    glco.tune(0.42)
    state = glco.build_comms_state()
    assert abs(state["active_frequency"] - 0.42) < 0.001
    assert state["tuned_faction"] == "rebel"


# ---------------------------------------------------------------------------
# Lobby — comms role exists
# ---------------------------------------------------------------------------


def test_lobby_has_comms_role():
    from server.lobby import LobbySession
    session = LobbySession()
    assert "comms" in session.roles


def test_valid_roles_includes_comms():
    from server.models.messages.lobby import VALID_ROLES
    assert "comms" in VALID_ROLES


# ---------------------------------------------------------------------------
# Comms handler — registered in main.py
# ---------------------------------------------------------------------------


def test_comms_handler_registered_in_main():
    from server.main import _HANDLERS
    assert "comms" in _HANDLERS


# ---------------------------------------------------------------------------
# Message schemas
# ---------------------------------------------------------------------------


def test_comms_tune_frequency_payload_valid():
    from server.models.messages.comms import CommsTuneFrequencyPayload
    p = CommsTuneFrequencyPayload(frequency=0.5)
    assert p.frequency == 0.5


def test_comms_tune_frequency_payload_clamps():
    from server.models.messages.comms import CommsTuneFrequencyPayload
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CommsTuneFrequencyPayload(frequency=1.5)


def test_comms_hail_payload_valid():
    from server.models.messages.comms import CommsHailPayload
    p = CommsHailPayload(contact_id="alien_01", message_type="negotiate")
    assert p.contact_id == "alien_01"
    assert p.message_type == "negotiate"


def test_comms_hail_payload_invalid_message_type():
    from server.models.messages.comms import CommsHailPayload
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CommsHailPayload(contact_id="x", message_type="threaten")
