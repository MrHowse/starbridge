"""Tests for the Medical station server-side code.

Covers:
  game_loop_medical — reset, start_treatment, cancel_treatment, tick_treatments
  server/medical.py — handle_medical_message validates and queues correctly
  Integration: medical messages reach _drain_queue and mutate crew state
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

import server.game_loop_medical_v2 as glmed
from server import medical
from server.models.crew import DECK_DEFAULT_CREW
from server.models.messages import Message
from server.models.ship import Ship


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ship_with_casualties(deck: str, count: int) -> Ship:
    ship = Ship()
    ship.crew.apply_casualties(deck, count)
    return ship


def fresh_handler():
    """Return a sender mock and queue; initialise the medical handler."""
    sender = AsyncMock()
    queue: asyncio.Queue = asyncio.Queue()
    medical.init(sender, queue)
    return sender, queue


def build_message(type_: str, payload: dict) -> Message:
    return Message.build(type_, payload)


# ---------------------------------------------------------------------------
# game_loop_medical.reset
# ---------------------------------------------------------------------------


def test_reset_clears_active_treatments():
    glmed.reset()
    ship = Ship()
    ship.crew.apply_casualties("engineering", 3)
    glmed.start_treatment("engineering", "injured", ship)
    glmed.reset()
    assert glmed.get_active_treatments() == {}


# ---------------------------------------------------------------------------
# game_loop_medical.start_treatment
# ---------------------------------------------------------------------------


def test_start_treatment_deducts_supplies():
    glmed.reset()
    ship = Ship()
    ship.crew.apply_casualties("engineering", 2)
    initial = ship.medical_supplies
    glmed.start_treatment("engineering", "injured", ship)
    assert ship.medical_supplies == initial - glmed.TREATMENT_COST


def test_start_treatment_records_active():
    glmed.reset()
    ship = Ship()
    ship.crew.apply_casualties("engineering", 2)
    glmed.start_treatment("engineering", "injured", ship)
    assert glmed.get_active_treatments() == {"engineering": "injured"}


def test_start_treatment_returns_true_on_success():
    glmed.reset()
    ship = Ship()
    ship.crew.apply_casualties("engineering", 2)
    assert glmed.start_treatment("engineering", "injured", ship) is True


def test_start_treatment_fails_when_no_supplies():
    glmed.reset()
    ship = Ship()
    ship.medical_supplies = 0
    ship.crew.apply_casualties("engineering", 2)
    assert glmed.start_treatment("engineering", "injured", ship) is False
    assert glmed.get_active_treatments() == {}


def test_start_treatment_fails_for_unknown_deck():
    glmed.reset()
    ship = Ship()
    assert glmed.start_treatment("nonexistent", "injured", ship) is False


def test_start_treatment_replaces_existing_treatment():
    """Calling start_treatment on a deck already under treatment replaces it."""
    glmed.reset()
    ship = Ship()
    ship.crew.apply_casualties("bridge", 3)
    glmed.start_treatment("bridge", "injured", ship)
    glmed.start_treatment("bridge", "critical", ship)
    assert glmed.get_active_treatments()["bridge"] == "critical"


# ---------------------------------------------------------------------------
# game_loop_medical.cancel_treatment
# ---------------------------------------------------------------------------


def test_cancel_treatment_removes_deck():
    glmed.reset()
    ship = Ship()
    ship.crew.apply_casualties("engineering", 2)
    glmed.start_treatment("engineering", "injured", ship)
    glmed.cancel_treatment("engineering")
    assert "engineering" not in glmed.get_active_treatments()


def test_cancel_treatment_unknown_deck_does_not_raise():
    glmed.reset()
    glmed.cancel_treatment("nonexistent")  # must not raise


# ---------------------------------------------------------------------------
# game_loop_medical.tick_treatments
# ---------------------------------------------------------------------------


def test_tick_treatments_heals_after_interval():
    glmed.reset()
    ship = make_ship_with_casualties("engineering", 3)
    glmed.start_treatment("engineering", "injured", ship)
    initial_injured = ship.crew.decks["engineering"].injured

    # Tick short of HEAL_INTERVAL → no heal yet
    glmed.tick_treatments(ship, glmed.HEAL_INTERVAL - 0.1)
    assert ship.crew.decks["engineering"].injured == initial_injured

    # Tick past the interval → exactly 1 heal
    glmed.tick_treatments(ship, 0.2)
    assert ship.crew.decks["engineering"].injured == initial_injured - 1


def test_tick_treatments_heals_injured_to_active():
    glmed.reset()
    ship = make_ship_with_casualties("bridge", 2)
    glmed.start_treatment("bridge", "injured", ship)
    # Accumulate enough time for one heal
    glmed.tick_treatments(ship, glmed.HEAL_INTERVAL + 0.1)
    deck = ship.crew.decks["bridge"]
    assert deck.active == DECK_DEFAULT_CREW["bridge"] - 1
    assert deck.injured == 1


def test_tick_treatments_critical_to_injured():
    """Treating critical crew moves them to injured, not directly to active."""
    glmed.reset()
    # Create a ship where engineering has only critical crew (all escalated)
    ship = Ship()
    # Force critical state: apply more casualties than active+injured to force escalation
    total = DECK_DEFAULT_CREW["engineering"]  # 6
    ship.crew.apply_casualties("engineering", total * 2)  # force all through to critical
    assert ship.crew.decks["engineering"].critical > 0
    glmed.start_treatment("engineering", "critical", ship)
    before_critical = ship.crew.decks["engineering"].critical
    before_injured = ship.crew.decks["engineering"].injured

    glmed.tick_treatments(ship, glmed.HEAL_INTERVAL + 0.1)

    assert ship.crew.decks["engineering"].critical == before_critical - 1
    assert ship.crew.decks["engineering"].injured == before_injured + 1


def test_tick_treatments_auto_cancels_when_no_crew():
    """Treatment auto-cancels when the target crew type is exhausted."""
    glmed.reset()
    ship = make_ship_with_casualties("sensors", 1)  # 1 injured
    glmed.start_treatment("sensors", "injured", ship)

    # First interval — heals the one injured crew
    glmed.tick_treatments(ship, glmed.HEAL_INTERVAL + 0.1)
    assert ship.crew.decks["sensors"].injured == 0

    # Second interval — no crew left, treatment should be auto-cancelled
    glmed.tick_treatments(ship, glmed.HEAL_INTERVAL + 0.1)
    assert "sensors" not in glmed.get_active_treatments()


def test_tick_treatments_returns_healed_deck_names():
    glmed.reset()
    ship = make_ship_with_casualties("bridge", 3)
    ship.crew.apply_casualties("sensors", 2)
    glmed.start_treatment("bridge", "injured", ship)
    glmed.start_treatment("sensors", "injured", ship)

    healed = glmed.tick_treatments(ship, glmed.HEAL_INTERVAL + 0.1)
    assert "bridge" in healed
    assert "sensors" in healed


def test_tick_treatments_no_heals_before_interval():
    glmed.reset()
    ship = make_ship_with_casualties("engineering", 3)
    glmed.start_treatment("engineering", "injured", ship)
    healed = glmed.tick_treatments(ship, 0.05)
    assert healed == []


# ---------------------------------------------------------------------------
# medical.handle_medical_message — validation and queuing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_treat_crew_valid_queues_message():
    sender, queue = fresh_handler()
    msg = build_message("medical.treat_crew", {"deck": "engineering", "injury_type": "injured"})
    await medical.handle_medical_message("conn1", msg)
    assert not queue.empty()
    msg_type, payload = queue.get_nowait()
    assert msg_type == "medical.treat_crew"
    assert payload.deck == "engineering"
    assert payload.injury_type == "injured"


@pytest.mark.asyncio
async def test_handle_cancel_treatment_valid_queues_message():
    sender, queue = fresh_handler()
    msg = build_message("medical.cancel_treatment", {"deck": "bridge"})
    await medical.handle_medical_message("conn1", msg)
    assert not queue.empty()
    msg_type, payload = queue.get_nowait()
    assert msg_type == "medical.cancel_treatment"
    assert payload.deck == "bridge"


@pytest.mark.asyncio
async def test_handle_invalid_injury_type_sends_error():
    sender, queue = fresh_handler()
    msg = build_message("medical.treat_crew", {"deck": "engineering", "injury_type": "dead"})
    await medical.handle_medical_message("conn1", msg)
    assert queue.empty()
    sender.send.assert_called_once()
    _, error_msg = sender.send.call_args[0]
    assert error_msg.type == "error.validation"


@pytest.mark.asyncio
async def test_handle_unknown_message_type_drops_silently():
    sender, queue = fresh_handler()
    msg = build_message("medical.unknown_action", {})
    await medical.handle_medical_message("conn1", msg)
    assert queue.empty()
    sender.send.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: medical supplies in Ship defaults
# ---------------------------------------------------------------------------


def test_ship_default_medical_supplies():
    ship = Ship()
    assert ship.medical_supplies == 20


def test_medical_supplies_depleted_by_treatments():
    glmed.reset()
    ship = Ship()
    ship.crew.apply_casualties("engineering", 3)
    ship.crew.apply_casualties("bridge", 2)
    glmed.start_treatment("engineering", "injured", ship)
    glmed.start_treatment("bridge", "injured", ship)
    assert ship.medical_supplies == 20 - (2 * glmed.TREATMENT_COST)
