"""Tests for server/models/crew.py — DeckCrew and CrewRoster.

Covers:
  DeckCrew.crew_factor — fully staffed, with injuries, all injured, zero total, capped
  CrewRoster defaults — all decks present, all fully staffed
  CrewRoster.apply_casualties — basic, overflow to critical, unknown deck, zero count
  CrewRoster.treat_injured — basic, capped at available, unknown deck
  CrewRoster.treat_critical — basic, unknown deck
  CrewRoster.get_deck_for_system — various systems, unknown
  Ship.update_crew_factors — efficiency drops when crew is injured, unrelated systems unaffected
"""
from __future__ import annotations

import pytest

from server.models.crew import (
    DECK_DEFAULT_CREW,
    DECK_SYSTEM_MAP,
    CrewRoster,
    DeckCrew,
)


# ---------------------------------------------------------------------------
# DeckCrew.crew_factor
# ---------------------------------------------------------------------------


def test_deck_crew_factor_fully_staffed():
    deck = DeckCrew(deck_name="engineering", total=6, active=6)
    assert deck.crew_factor == pytest.approx(1.0)


def test_deck_crew_factor_with_injured():
    # 8 active, 2 injured of 10 total → effective = 8 + 1.0 = 9.0 → factor = 0.9
    deck = DeckCrew(deck_name="sensors", total=10, active=8, injured=2)
    assert deck.crew_factor == pytest.approx(0.9)


def test_deck_crew_factor_all_injured():
    # 0 active, 4 injured of 4 total → effective = 2.0 → factor = 0.5
    deck = DeckCrew(deck_name="weapons", total=4, active=0, injured=4)
    assert deck.crew_factor == pytest.approx(0.5)


def test_deck_crew_factor_zero_total_returns_one():
    deck = DeckCrew(deck_name="medical", total=0, active=0)
    assert deck.crew_factor == pytest.approx(1.0)


def test_deck_crew_factor_capped_at_one():
    # Effective > total (e.g. bug in accounting) should still return 1.0 at most
    deck = DeckCrew(deck_name="bridge", total=3, active=5)
    assert deck.crew_factor == pytest.approx(1.0)


def test_deck_crew_factor_partial_critical_ignored():
    # Critical crew contribute 0 — only active (1.0) and injured (0.5) count
    deck = DeckCrew(deck_name="shields", total=4, active=2, injured=0, critical=2)
    assert deck.crew_factor == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# CrewRoster defaults
# ---------------------------------------------------------------------------


def test_crew_roster_default_has_all_decks():
    roster = CrewRoster()
    assert set(roster.decks.keys()) == set(DECK_DEFAULT_CREW.keys())


def test_crew_roster_default_fully_staffed():
    roster = CrewRoster()
    for name, deck in roster.decks.items():
        assert deck.active == DECK_DEFAULT_CREW[name]
        assert deck.injured == 0
        assert deck.critical == 0
        assert deck.dead == 0
        assert deck.crew_factor == pytest.approx(1.0)


def test_crew_roster_decks_are_independent():
    """Each call to CrewRoster() produces independent deck instances."""
    r1 = CrewRoster()
    r2 = CrewRoster()
    r1.apply_casualties("engineering", 3)
    assert r2.decks["engineering"].injured == 0


# ---------------------------------------------------------------------------
# CrewRoster.apply_casualties
# ---------------------------------------------------------------------------


def test_apply_casualties_moves_active_to_injured():
    roster = CrewRoster()
    roster.apply_casualties("engineering", 2)
    deck = roster.decks["engineering"]
    assert deck.injured == 2
    assert deck.active == DECK_DEFAULT_CREW["engineering"] - 2


def test_apply_casualties_overflow_to_critical():
    # Engineering has 6 active, 0 injured.
    # Apply 8 casualties: 6 active → injured (pool = 6), then 2 overflow escalate
    # from the injured pool → critical.  Final: active=0, injured=4, critical=2.
    roster = CrewRoster()
    roster.apply_casualties("engineering", 8)
    deck = roster.decks["engineering"]
    assert deck.active == 0
    assert deck.injured == 4
    assert deck.critical == 2


def test_apply_casualties_unknown_deck_is_noop():
    roster = CrewRoster()
    roster.apply_casualties("nonexistent", 5)  # must not raise
    for deck in roster.decks.values():
        assert deck.injured == 0


def test_apply_casualties_zero_count_is_noop():
    roster = CrewRoster()
    roster.apply_casualties("engineering", 0)
    assert roster.decks["engineering"].injured == 0


def test_apply_casualties_cumulative():
    """Successive casualty calls accumulate correctly."""
    roster = CrewRoster()
    roster.apply_casualties("bridge", 2)
    roster.apply_casualties("bridge", 2)
    deck = roster.decks["bridge"]
    assert deck.injured == 4
    assert deck.active == DECK_DEFAULT_CREW["bridge"] - 4


# ---------------------------------------------------------------------------
# CrewRoster.treat_injured
# ---------------------------------------------------------------------------


def test_treat_injured_moves_to_active():
    roster = CrewRoster()
    roster.apply_casualties("bridge", 3)
    treated = roster.treat_injured("bridge", 2)
    deck = roster.decks["bridge"]
    assert treated == 2
    assert deck.injured == 1
    assert deck.active == DECK_DEFAULT_CREW["bridge"] - 1


def test_treat_injured_capped_at_available():
    roster = CrewRoster()
    roster.apply_casualties("bridge", 2)
    treated = roster.treat_injured("bridge", 10)  # only 2 injured
    assert treated == 2
    assert roster.decks["bridge"].injured == 0


def test_treat_injured_unknown_deck_returns_zero():
    roster = CrewRoster()
    assert roster.treat_injured("nonexistent", 5) == 0


# ---------------------------------------------------------------------------
# CrewRoster.treat_critical
# ---------------------------------------------------------------------------


def test_treat_critical_moves_to_injured():
    # weapons deck has 4 active, 0 injured.
    # Apply 8 casualties: 4 active → injured (pool=4), 4 overflow escalate injured → critical.
    # Final after casualties: active=0, injured=0, critical=4.
    # Treat 2 critical → injured: critical=2, injured=2.
    roster = CrewRoster()
    roster.apply_casualties("weapons", 8)
    deck = roster.decks["weapons"]
    assert deck.critical == 4  # sanity-check precondition
    stabilised = roster.treat_critical("weapons", 2)
    assert stabilised == 2
    assert deck.critical == 2
    assert deck.injured == 2


def test_treat_critical_capped_at_available():
    # weapons has 4 total → after 8 casualties: active=0, injured=0, critical=4
    roster = CrewRoster()
    roster.apply_casualties("weapons", 8)
    stabilised = roster.treat_critical("weapons", 100)
    assert stabilised == 4  # only 4 critical were available


def test_treat_critical_unknown_deck_returns_zero():
    roster = CrewRoster()
    assert roster.treat_critical("nonexistent", 5) == 0


# ---------------------------------------------------------------------------
# CrewRoster.get_deck_for_system
# ---------------------------------------------------------------------------


def test_get_deck_for_system_engines():
    roster = CrewRoster()
    assert roster.get_deck_for_system("engines") == "engineering"


def test_get_deck_for_system_beams():
    roster = CrewRoster()
    assert roster.get_deck_for_system("beams") == "weapons"


def test_get_deck_for_system_torpedoes():
    roster = CrewRoster()
    assert roster.get_deck_for_system("torpedoes") == "weapons"


def test_get_deck_for_system_shields():
    roster = CrewRoster()
    assert roster.get_deck_for_system("shields") == "shields"


def test_get_deck_for_system_sensors():
    roster = CrewRoster()
    assert roster.get_deck_for_system("sensors") == "sensors"


def test_get_deck_for_system_manoeuvring():
    roster = CrewRoster()
    assert roster.get_deck_for_system("manoeuvring") == "bridge"


def test_get_deck_for_system_unknown_returns_none():
    roster = CrewRoster()
    assert roster.get_deck_for_system("nonexistent") is None


# ---------------------------------------------------------------------------
# Ship.update_crew_factors — integration with ShipSystem.efficiency
# ---------------------------------------------------------------------------


def test_crew_factor_reduces_engine_efficiency():
    """Injuring all engineering crew should halve engine efficiency."""
    from server.models.ship import Ship

    ship = Ship()
    # Injure all engineering crew: 6 total, all → injured → effective=3, factor=0.5
    ship.crew.apply_casualties("engineering", DECK_DEFAULT_CREW["engineering"])
    ship.update_crew_factors()
    assert ship.systems["engines"].efficiency == pytest.approx(0.5)


def test_crew_factor_does_not_affect_unrelated_systems():
    """Crew casualties on one deck must not change efficiency of unrelated systems."""
    from server.models.ship import Ship

    ship = Ship()
    ship.crew.apply_casualties("engineering", DECK_DEFAULT_CREW["engineering"])
    ship.update_crew_factors()
    assert ship.systems["beams"].efficiency == pytest.approx(1.0)
    assert ship.systems["shields"].efficiency == pytest.approx(1.0)
    assert ship.systems["sensors"].efficiency == pytest.approx(1.0)
    assert ship.systems["manoeuvring"].efficiency == pytest.approx(1.0)


def test_crew_factor_default_leaves_efficiency_unchanged():
    """Calling update_crew_factors() with full crew must not alter efficiency."""
    from server.models.ship import Ship

    ship = Ship()
    ship.update_crew_factors()
    for name, sys_obj in ship.systems.items():
        assert sys_obj.efficiency == pytest.approx(1.0), f"{name} efficiency changed unexpectedly"


def test_crew_factor_weapons_deck_affects_beams_and_torpedoes():
    """The weapons crew deck controls both the beams and torpedoes systems."""
    from server.models.ship import Ship

    ship = Ship()
    # Injure all weapons crew: 4 total → factor = 0.5
    ship.crew.apply_casualties("weapons", DECK_DEFAULT_CREW["weapons"])
    ship.update_crew_factors()
    assert ship.systems["beams"].efficiency == pytest.approx(0.5)
    assert ship.systems["torpedoes"].efficiency == pytest.approx(0.5)
