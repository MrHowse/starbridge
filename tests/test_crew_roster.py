"""Tests for server/models/crew_roster.py — Individual crew member roster.

v0.06.1 Part 1: Crew Roster System.

Covers:
  - Roster generation: correct count, unique names, rank distribution,
    deck distribution, duty station mapping
  - CrewMember: display_name, worst_severity, update_status
  - Injury: to_dict/from_dict round-trip
  - IndividualCrewRoster queries: get_by_deck, get_by_status,
    get_by_duty_station, get_injured, get_active_count, get_dead_count
  - crew_factor_for_system: healthy, injured, dead, in medical bay
  - Serialise/deserialise round-trip
"""
from __future__ import annotations

import random

import pytest

from server.models.crew_roster import (
    CrewMember,
    DECK_DUTY_STATIONS,
    Injury,
    IndividualCrewRoster,
    RANKS,
    SEVERITY_ORDER,
    SYSTEM_TO_DUTY_STATION,
    _distribute_ranks,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_roster(count: int = 9, seed: int = 42) -> IndividualCrewRoster:
    """Generate a deterministic test roster."""
    return IndividualCrewRoster.generate(count, "frigate", random.Random(seed))


def make_injury(
    injury_id: str = "inj_0001",
    severity: str = "moderate",
    treated: bool = False,
    body_region: str = "torso",
    injury_type: str = "fracture",
) -> Injury:
    """Create a test injury."""
    return Injury(
        id=injury_id,
        type=injury_type,
        body_region=body_region,
        severity=severity,
        description="Test injury",
        caused_by="test",
        degrade_timer=180.0,
        death_timer=240.0 if severity == "critical" else None,
        treatment_type="surgery",
        treatment_duration=35.0,
        treated=treated,
    )


# ---------------------------------------------------------------------------
# Roster generation — correct count
# ---------------------------------------------------------------------------


def test_roster_generates_correct_count():
    roster = make_roster(9)
    assert len(roster.members) == 9


def test_roster_generates_correct_count_small():
    roster = make_roster(3)
    assert len(roster.members) == 3


def test_roster_generates_correct_count_large():
    roster = make_roster(12)
    assert len(roster.members) == 12


def test_roster_generates_all_ship_class_sizes():
    for count in [3, 4, 6, 8, 9, 11, 12]:
        roster = make_roster(count)
        assert len(roster.members) == count


# ---------------------------------------------------------------------------
# Roster generation — unique names
# ---------------------------------------------------------------------------


def test_roster_names_are_unique():
    roster = make_roster(12)
    full_names = {m.full_name for m in roster.members.values()}
    assert len(full_names) == 12


def test_roster_ids_are_unique():
    roster = make_roster(12)
    assert len(roster.members) == 12  # dict keys enforce uniqueness


def test_roster_ids_are_sequential():
    roster = make_roster(5)
    ids = sorted(roster.members.keys())
    assert ids == ["crew_001", "crew_002", "crew_003", "crew_004", "crew_005"]


# ---------------------------------------------------------------------------
# Roster generation — rank distribution
# ---------------------------------------------------------------------------


def test_roster_has_valid_ranks():
    roster = make_roster(12)
    valid_ranks = {r["title"] for r in RANKS}
    for m in roster.members.values():
        assert m.rank in valid_ranks, f"Invalid rank: {m.rank}"


def test_roster_rank_levels_match_titles():
    roster = make_roster(12)
    rank_map = {r["title"]: r["level"] for r in RANKS}
    for m in roster.members.values():
        assert m.rank_level == rank_map[m.rank]


def test_roster_has_crewman():
    """At least one Crewman in any roster of 5+ crew."""
    roster = make_roster(9)
    crewmen = [m for m in roster.members.values() if m.rank == "Crewman"]
    assert len(crewmen) > 0


def test_roster_higher_ranks_rarer():
    """Higher ranks should appear less frequently than lower ranks."""
    roster = make_roster(12)
    counts_by_level: dict[int, int] = {}
    for m in roster.members.values():
        counts_by_level[m.rank_level] = counts_by_level.get(m.rank_level, 0) + 1
    # Crewman (level 1) should be the most common
    crewman_count = counts_by_level.get(1, 0)
    for level in [5, 6, 7]:
        assert counts_by_level.get(level, 0) <= crewman_count


def test_small_crew_no_commander():
    """Ships with <8 crew should not have a Commander."""
    roster = make_roster(6)
    commanders = [m for m in roster.members.values() if m.rank_level == 7]
    assert len(commanders) == 0


def test_large_crew_max_one_commander():
    """Even large crews should have at most 1 Commander."""
    roster = make_roster(12)
    commanders = [m for m in roster.members.values() if m.rank_level == 7]
    assert len(commanders) <= 1


# ---------------------------------------------------------------------------
# Roster generation — deck distribution
# ---------------------------------------------------------------------------


def test_roster_decks_roughly_even():
    roster = make_roster(10)
    deck_counts: dict[int, int] = {}
    for m in roster.members.values():
        deck_counts[m.deck] = deck_counts.get(m.deck, 0) + 1
    # With 10 crew across 5 decks, each should have 2
    for deck in range(1, 6):
        assert deck_counts.get(deck, 0) == 2


def test_roster_all_decks_populated():
    """With enough crew, all 5 decks should have at least one member."""
    roster = make_roster(10)
    decks_used = {m.deck for m in roster.members.values()}
    assert decks_used == {1, 2, 3, 4, 5}


def test_roster_decks_in_valid_range():
    roster = make_roster(12)
    for m in roster.members.values():
        assert 1 <= m.deck <= 5


# ---------------------------------------------------------------------------
# Roster generation — duty station mapping
# ---------------------------------------------------------------------------


def test_roster_duty_stations_valid_for_deck():
    roster = make_roster(12)
    for m in roster.members.values():
        valid_stations = DECK_DUTY_STATIONS.get(m.deck, [])
        assert m.duty_station in valid_stations, (
            f"{m.display_name} on deck {m.deck} has invalid station {m.duty_station}"
        )


def test_roster_location_matches_deck():
    roster = make_roster(9)
    for m in roster.members.values():
        assert m.location == f"deck_{m.deck}"


# ---------------------------------------------------------------------------
# CrewMember properties
# ---------------------------------------------------------------------------


def test_crew_member_display_name():
    m = CrewMember(
        id="crew_001", first_name="James", surname="Chen",
        rank="Lieutenant", rank_level=5, deck=1, duty_station="manoeuvring",
    )
    assert m.display_name == "Lt. Chen"


def test_crew_member_display_name_commander():
    m = CrewMember(
        id="crew_001", first_name="Sarah", surname="Williams",
        rank="Commander", rank_level=7, deck=1, duty_station="manoeuvring",
    )
    assert m.display_name == "Cmdr. Williams"


def test_crew_member_full_name():
    m = CrewMember(
        id="crew_001", first_name="Kenji", surname="Tanaka",
        rank="Crewman", rank_level=1, deck=5, duty_station="engines",
    )
    assert m.full_name == "Kenji Tanaka"


def test_crew_member_worst_severity_none_when_healthy():
    m = CrewMember(
        id="crew_001", first_name="A", surname="B",
        rank="Crewman", rank_level=1, deck=1, duty_station="manoeuvring",
    )
    assert m.worst_severity is None


def test_crew_member_worst_severity_single_injury():
    m = CrewMember(
        id="crew_001", first_name="A", surname="B",
        rank="Crewman", rank_level=1, deck=1, duty_station="manoeuvring",
        injuries=[make_injury(severity="serious")],
    )
    assert m.worst_severity == "serious"


def test_crew_member_worst_severity_multiple_injuries():
    m = CrewMember(
        id="crew_001", first_name="A", surname="B",
        rank="Crewman", rank_level=1, deck=1, duty_station="manoeuvring",
        injuries=[
            make_injury(injury_id="inj_0001", severity="minor"),
            make_injury(injury_id="inj_0002", severity="critical"),
            make_injury(injury_id="inj_0003", severity="moderate"),
        ],
    )
    assert m.worst_severity == "critical"


def test_crew_member_worst_severity_ignores_treated():
    m = CrewMember(
        id="crew_001", first_name="A", surname="B",
        rank="Crewman", rank_level=1, deck=1, duty_station="manoeuvring",
        injuries=[
            make_injury(injury_id="inj_0001", severity="critical", treated=True),
            make_injury(injury_id="inj_0002", severity="minor"),
        ],
    )
    assert m.worst_severity == "minor"


def test_crew_member_update_status_active_when_healthy():
    m = CrewMember(
        id="crew_001", first_name="A", surname="B",
        rank="Crewman", rank_level=1, deck=1, duty_station="manoeuvring",
        status="injured",
    )
    m.update_status()
    assert m.status == "active"


def test_crew_member_update_status_critical():
    m = CrewMember(
        id="crew_001", first_name="A", surname="B",
        rank="Crewman", rank_level=1, deck=1, duty_station="manoeuvring",
        injuries=[make_injury(severity="critical")],
    )
    m.update_status()
    assert m.status == "critical"


def test_crew_member_update_status_injured():
    m = CrewMember(
        id="crew_001", first_name="A", surname="B",
        rank="Crewman", rank_level=1, deck=1, duty_station="manoeuvring",
        injuries=[make_injury(severity="moderate")],
    )
    m.update_status()
    assert m.status == "injured"


def test_crew_member_update_status_dead_stays_dead():
    m = CrewMember(
        id="crew_001", first_name="A", surname="B",
        rank="Crewman", rank_level=1, deck=1, duty_station="manoeuvring",
        status="dead",
    )
    m.update_status()
    assert m.status == "dead"


# ---------------------------------------------------------------------------
# Injury serialisation
# ---------------------------------------------------------------------------


def test_injury_to_dict_round_trip():
    inj = make_injury(severity="critical")
    data = inj.to_dict()
    inj2 = Injury.from_dict(data)
    assert inj2.id == inj.id
    assert inj2.severity == "critical"
    assert inj2.death_timer == 240.0
    assert inj2.treated == False


def test_injury_to_dict_no_death_timer():
    inj = make_injury(severity="moderate")
    data = inj.to_dict()
    assert data["death_timer"] is None


# ---------------------------------------------------------------------------
# CrewMember serialisation
# ---------------------------------------------------------------------------


def test_crew_member_to_dict_round_trip():
    m = CrewMember(
        id="crew_001", first_name="Priya", surname="Patel",
        rank="Lieutenant", rank_level=5, deck=2, duty_station="sensors",
        injuries=[make_injury()],
        location="medical_bay",
        treatment_bed=1,
    )
    data = m.to_dict()
    m2 = CrewMember.from_dict(data)
    assert m2.id == "crew_001"
    assert m2.full_name == "Priya Patel"
    assert m2.rank_level == 5
    assert len(m2.injuries) == 1
    assert m2.location == "medical_bay"
    assert m2.treatment_bed == 1


# ---------------------------------------------------------------------------
# Roster queries
# ---------------------------------------------------------------------------


def test_get_by_deck():
    roster = make_roster(10)
    deck_1 = roster.get_by_deck(1)
    assert all(m.deck == 1 for m in deck_1)
    assert len(deck_1) == 2  # 10 crew / 5 decks


def test_get_by_status_active():
    roster = make_roster(9)
    active = roster.get_by_status("active")
    assert len(active) == 9


def test_get_by_status_injured():
    roster = make_roster(9)
    # Injure one crew member
    first = next(iter(roster.members.values()))
    first.injuries.append(make_injury())
    first.update_status()
    injured = roster.get_by_status("injured")
    assert len(injured) == 1


def test_get_by_duty_station():
    roster = make_roster(10)
    sensors = roster.get_by_duty_station("sensors")
    assert all(m.duty_station == "sensors" for m in sensors)


def test_get_injured_sorted_by_severity():
    roster = make_roster(9)
    members = list(roster.members.values())

    # Give two crew members different severity injuries
    members[0].injuries.append(make_injury(injury_id="i1", severity="minor"))
    members[0].update_status()
    members[1].injuries.append(make_injury(injury_id="i2", severity="critical"))
    members[1].update_status()

    injured = roster.get_injured()
    assert len(injured) == 2
    assert injured[0].worst_severity == "critical"
    assert injured[1].worst_severity == "minor"


def test_get_active_count():
    roster = make_roster(9)
    assert roster.get_active_count() == 9


def test_get_active_count_after_injury():
    roster = make_roster(9)
    first = next(iter(roster.members.values()))
    first.injuries.append(make_injury())
    first.update_status()
    assert roster.get_active_count() == 8


def test_get_dead_count():
    roster = make_roster(9)
    assert roster.get_dead_count() == 0


def test_get_dead_count_after_death():
    roster = make_roster(9)
    first = next(iter(roster.members.values()))
    first.status = "dead"
    first.location = "morgue"
    assert roster.get_dead_count() == 1


# ---------------------------------------------------------------------------
# crew_factor_for_system
# ---------------------------------------------------------------------------


def test_crew_factor_full_crew_is_one():
    roster = make_roster(10)
    # All crew active — any system with assigned crew should have factor 1.0
    for system in SYSTEM_TO_DUTY_STATION:
        factor = roster.crew_factor_for_system(system)
        # Systems with no crew assigned return 1.0 anyway
        assert factor == pytest.approx(1.0), f"{system}: {factor}"


def test_crew_factor_drops_when_injured():
    roster = make_roster(10)
    # Find a crew member on the engines duty station
    engine_crew = roster.get_by_duty_station("engines")
    if not engine_crew:
        pytest.skip("No engine crew in this roster seed")
    # Injure them
    engine_crew[0].injuries.append(make_injury(severity="moderate"))
    engine_crew[0].update_status()
    factor = roster.crew_factor_for_system("engines")
    assert factor < 1.0


def test_crew_factor_injured_at_50_percent():
    """A crew member with minor injury at their station counts at 50%."""
    roster = IndividualCrewRoster()
    # Add exactly 2 crew to engines
    roster.members["c1"] = CrewMember(
        id="c1", first_name="A", surname="B",
        rank="Crewman", rank_level=1, deck=5, duty_station="engines",
    )
    roster.members["c2"] = CrewMember(
        id="c2", first_name="C", surname="D",
        rank="Crewman", rank_level=1, deck=5, duty_station="engines",
    )
    # Injure c1 with minor injury, keep at station
    roster.members["c1"].injuries.append(make_injury(severity="minor"))
    roster.members["c1"].update_status()
    # c1 = 0.5 effective, c2 = 1.0 effective → total = 1.5/2 = 0.75
    assert roster.crew_factor_for_system("engines") == pytest.approx(0.75)


def test_crew_factor_medical_bay_not_counted():
    """Crew in medical bay don't contribute to their duty station factor."""
    roster = IndividualCrewRoster()
    roster.members["c1"] = CrewMember(
        id="c1", first_name="A", surname="B",
        rank="Crewman", rank_level=1, deck=5, duty_station="engines",
        location="medical_bay",
    )
    roster.members["c2"] = CrewMember(
        id="c2", first_name="C", surname="D",
        rank="Crewman", rank_level=1, deck=5, duty_station="engines",
    )
    # c1 in medical bay = 0 effective, c2 active = 1.0 → 1.0/2 = 0.5
    assert roster.crew_factor_for_system("engines") == pytest.approx(0.5)


def test_crew_factor_dead_crew_not_counted():
    """Dead crew don't contribute to crew factor."""
    roster = IndividualCrewRoster()
    roster.members["c1"] = CrewMember(
        id="c1", first_name="A", surname="B",
        rank="Crewman", rank_level=1, deck=5, duty_station="engines",
        status="dead", location="morgue",
    )
    roster.members["c2"] = CrewMember(
        id="c2", first_name="C", surname="D",
        rank="Crewman", rank_level=1, deck=5, duty_station="engines",
    )
    # c1 dead = 0 effective, c2 active = 1.0 → 1.0/2 = 0.5
    assert roster.crew_factor_for_system("engines") == pytest.approx(0.5)


def test_crew_factor_unknown_system_returns_one():
    roster = make_roster(9)
    assert roster.crew_factor_for_system("nonexistent") == pytest.approx(1.0)


def test_crew_factor_no_assigned_crew_returns_one():
    """If no crew are assigned to a station, factor is 1.0."""
    roster = IndividualCrewRoster()
    assert roster.crew_factor_for_system("engines") == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Roster serialise/deserialise
# ---------------------------------------------------------------------------


def test_roster_serialise_round_trip():
    roster = make_roster(9)
    # Modify some state
    first = next(iter(roster.members.values()))
    first.injuries.append(make_injury())
    first.update_status()
    first.location = "medical_bay"
    first.treatment_bed = 2

    data = roster.serialise()
    roster2 = IndividualCrewRoster.deserialise(data)

    assert len(roster2.members) == 9
    m2 = roster2.members[first.id]
    assert m2.full_name == first.full_name
    assert m2.location == "medical_bay"
    assert m2.treatment_bed == 2
    assert len(m2.injuries) == 1
    assert m2.injuries[0].severity == "moderate"


def test_roster_serialise_preserves_injury_id_counter():
    roster = make_roster(9)
    roster._next_injury_id = 42
    data = roster.serialise()
    roster2 = IndividualCrewRoster.deserialise(data)
    assert roster2._next_injury_id == 42


def test_roster_serialise_preserves_all_member_fields():
    roster = make_roster(6)
    data = roster.serialise()
    roster2 = IndividualCrewRoster.deserialise(data)
    for mid in roster.members:
        m1 = roster.members[mid]
        m2 = roster2.members[mid]
        assert m1.id == m2.id
        assert m1.first_name == m2.first_name
        assert m1.surname == m2.surname
        assert m1.rank == m2.rank
        assert m1.rank_level == m2.rank_level
        assert m1.deck == m2.deck
        assert m1.duty_station == m2.duty_station


# ---------------------------------------------------------------------------
# Deterministic generation
# ---------------------------------------------------------------------------


def test_roster_same_seed_same_result():
    r1 = make_roster(9, seed=123)
    r2 = make_roster(9, seed=123)
    names1 = [m.full_name for m in r1.members.values()]
    names2 = [m.full_name for m in r2.members.values()]
    assert names1 == names2


def test_roster_different_seeds_different_result():
    r1 = make_roster(9, seed=1)
    r2 = make_roster(9, seed=2)
    names1 = [m.full_name for m in r1.members.values()]
    names2 = [m.full_name for m in r2.members.values()]
    assert names1 != names2


# ---------------------------------------------------------------------------
# next_injury_id
# ---------------------------------------------------------------------------


def test_next_injury_id_increments():
    roster = IndividualCrewRoster()
    assert roster.next_injury_id() == "inj_0001"
    assert roster.next_injury_id() == "inj_0002"
    assert roster.next_injury_id() == "inj_0003"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_roster_single_crew_member():
    roster = make_roster(1)
    assert len(roster.members) == 1
    m = next(iter(roster.members.values()))
    assert m.id == "crew_001"


def test_get_crew_on_deck():
    roster = make_roster(10)
    deck_3 = roster.get_crew_on_deck(3)
    assert all(m.location == "deck_3" for m in deck_3)


def test_get_crew_on_deck_excludes_medical_bay():
    roster = make_roster(10)
    deck_1 = roster.get_by_deck(1)
    if deck_1:
        deck_1[0].location = "medical_bay"
    result = roster.get_crew_on_deck(1, exclude_medical=True)
    assert all(m.location != "medical_bay" for m in result)


def test_distribute_ranks_counts():
    """_distribute_ranks returns exactly the requested count."""
    for count in range(1, 15):
        ranks = _distribute_ranks(count)
        assert len(ranks) == count
