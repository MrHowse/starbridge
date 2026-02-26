"""Tests for server/game_loop_medical_v2.py — New medical game loop.

v0.06.1 Part 3: Medical Game Loop.

Covers:
  - Damage event generates casualties
  - Casualties appear in correct severity
  - Injury timers degrade correctly
  - Critical timer leads to death
  - Stabilise resets timers
  - Treatment starts and completes
  - Puzzle integration (treatment waits for puzzle)
  - Bed management (admit, queue when full, discharge)
  - Quarantine prevents contagion spread
  - Supply consumption
  - Cannot treat at 0% supplies (except stabilise)
  - Crew factor updates when crew injured/treated/killed
  - Death removes crew permanently
  - Multiple simultaneous injuries
  - Treatment priority queue reordering
  - Serialise/deserialise round-trip
  - Radiation delayed onset
  - Contagion spread mechanics
  - Legacy interface compatibility
"""
from __future__ import annotations

import random

import pytest

import server.game_loop_medical_v2 as glmed
from server.models.crew_roster import (
    CrewMember,
    IndividualCrewRoster,
    Injury,
)
from server.models.injuries import (
    CRITICAL_DEATH_TIMER,
    DEGRADE_TIMERS,
    TREATMENT_SUPPLY_COSTS,
    generate_injuries,
)
from server.models.ship import Ship


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_roster(count: int = 9) -> IndividualCrewRoster:
    return IndividualCrewRoster.generate(count, "frigate", random.Random(42))


def make_member(
    crew_id: str = "c1",
    deck: int = 3,
    duty_station: str = "engines",
    status: str = "active",
    location: str | None = None,
) -> CrewMember:
    return CrewMember(
        id=crew_id, first_name="Test", surname="Crew",
        rank="Crewman", rank_level=1, deck=deck,
        duty_station=duty_station, status=status,
        location=location or f"deck_{deck}",
    )


def make_injury_obj(
    injury_id: str = "inj_0001",
    severity: str = "moderate",
    treated: bool = False,
    treating: bool = False,
    treatment_type: str = "surgery",
    caused_by: str = "explosion",
) -> Injury:
    return Injury(
        id=injury_id, type="fracture", body_region="torso",
        severity=severity, description="Test injury",
        caused_by=caused_by,
        degrade_timer=DEGRADE_TIMERS.get(severity, 0.0),
        death_timer=CRITICAL_DEATH_TIMER if severity == "critical" else None,
        treatment_type=treatment_type,
        treatment_duration=35.0,
        treated=treated, treating=treating,
    )


def setup_medical(beds: int = 4) -> IndividualCrewRoster:
    """Reset medical and return a roster."""
    glmed.reset()
    roster = make_roster()
    glmed.init_roster(roster, "frigate")
    glmed.set_bed_count(beds)
    return roster


# ---------------------------------------------------------------------------
# Damage event generates casualties
# ---------------------------------------------------------------------------


def test_damage_generates_injuries():
    roster = setup_medical()
    injuries = generate_injuries("explosion", 3, roster, severity_scale=2.0,
                                  rng=random.Random(42))
    assert len(injuries) > 0


def test_injuries_applied_to_crew():
    roster = setup_medical()
    injuries = generate_injuries("explosion", 3, roster, severity_scale=2.0,
                                  rng=random.Random(42))
    for crew_id, injury in injuries:
        roster.members[crew_id].injuries.append(injury)
        roster.members[crew_id].update_status()

    injured = roster.get_injured()
    assert len(injured) > 0


# ---------------------------------------------------------------------------
# Injury timer degradation
# ---------------------------------------------------------------------------


def test_tick_degrades_injury_timers():
    roster = setup_medical()
    member = make_member()
    member.injuries.append(make_injury_obj(severity="moderate"))
    member.update_status()
    roster.members[member.id] = member

    initial = member.injuries[0].degrade_timer
    glmed.tick(roster, 10.0)
    assert member.injuries[0].degrade_timer < initial


def test_tick_upgrades_severity():
    roster = setup_medical()
    member = make_member()
    member.injuries.append(make_injury_obj(severity="minor"))
    member.update_status()
    roster.members[member.id] = member

    events = glmed.tick(roster, DEGRADE_TIMERS["minor"] + 1.0)
    severity_events = [e for e in events if e["event"] == "severity_changed"]
    assert len(severity_events) == 1
    assert severity_events[0]["new_severity"] == "moderate"


# ---------------------------------------------------------------------------
# Critical timer leads to death
# ---------------------------------------------------------------------------


def test_critical_timer_causes_death():
    roster = setup_medical()
    member = make_member()
    member.injuries.append(make_injury_obj(severity="critical"))
    member.status = "critical"
    roster.members[member.id] = member

    events = glmed.tick(roster, CRITICAL_DEATH_TIMER + 1.0)
    death_events = [e for e in events if e["event"] == "crew_death"]
    assert len(death_events) == 1
    assert member.status == "dead"
    assert member.location == "morgue"


def test_death_adds_to_morgue():
    roster = setup_medical()
    member = make_member()
    member.injuries.append(make_injury_obj(severity="critical"))
    member.status = "critical"
    roster.members[member.id] = member

    glmed.tick(roster, CRITICAL_DEATH_TIMER + 1.0)
    state = glmed.get_medical_state()
    assert member.id in state["morgue"]


# ---------------------------------------------------------------------------
# Stabilise
# ---------------------------------------------------------------------------


def test_stabilise_resets_timer():
    roster = setup_medical()
    member = make_member()
    inj = make_injury_obj(severity="moderate")
    inj.degrade_timer = 10.0
    member.injuries.append(inj)
    member.update_status()
    roster.members[member.id] = member

    result = glmed.stabilise_crew(member.id, inj.id)
    assert result["success"] is True
    assert inj.degrade_timer == DEGRADE_TIMERS["moderate"]


def test_stabilise_works_at_zero_supplies():
    roster = setup_medical()
    glmed.set_supplies(0.0)
    member = make_member()
    inj = make_injury_obj(severity="serious")
    member.injuries.append(inj)
    member.update_status()
    roster.members[member.id] = member

    result = glmed.stabilise_crew(member.id, inj.id)
    assert result["success"] is True


# ---------------------------------------------------------------------------
# Treatment starts and completes
# ---------------------------------------------------------------------------


def test_admit_patient():
    roster = setup_medical()
    member = make_member()
    member.injuries.append(make_injury_obj())
    member.update_status()
    roster.members[member.id] = member

    result = glmed.admit_patient(member.id)
    assert result["success"] is True
    assert result["bed"] is not None
    assert member.location == "medical_bay"


def test_start_treatment():
    roster = setup_medical()
    member = make_member()
    inj = make_injury_obj(treatment_type="first_aid")
    member.injuries.append(inj)
    member.update_status()
    roster.members[member.id] = member

    glmed.admit_patient(member.id)
    result = glmed.start_crew_treatment(member.id, inj.id, "first_aid")
    assert result["success"] is True
    assert inj.treating is True


def test_treatment_completes_after_duration():
    roster = setup_medical()
    member = make_member()
    inj = make_injury_obj(treatment_type="first_aid")
    inj.treatment_duration = 10.0
    member.injuries.append(inj)
    member.update_status()
    roster.members[member.id] = member

    glmed.admit_patient(member.id)
    glmed.start_crew_treatment(member.id, inj.id, "first_aid")
    events = glmed.tick(roster, 11.0)
    complete_events = [e for e in events if e["event"] == "treatment_complete"]
    assert len(complete_events) == 1
    assert inj.treated is True


# ---------------------------------------------------------------------------
# Puzzle integration
# ---------------------------------------------------------------------------


def test_surgery_requires_puzzle():
    roster = setup_medical()
    member = make_member()
    inj = make_injury_obj(treatment_type="surgery")
    member.injuries.append(inj)
    member.update_status()
    roster.members[member.id] = member

    glmed.admit_patient(member.id)
    result = glmed.start_crew_treatment(member.id, inj.id, "surgery")
    assert result["puzzle_required"] is True


def test_treatment_waits_for_puzzle():
    roster = setup_medical()
    member = make_member()
    inj = make_injury_obj(treatment_type="surgery")
    inj.treatment_duration = 10.0
    member.injuries.append(inj)
    member.update_status()
    roster.members[member.id] = member

    glmed.admit_patient(member.id)
    glmed.start_crew_treatment(member.id, inj.id, "surgery")

    # Tick without puzzle completion — treatment shouldn't progress
    glmed.tick(roster, 20.0)
    assert not inj.treated

    # Complete puzzle
    glmed.notify_puzzle_complete(member.id, True)
    glmed.tick(roster, 11.0)
    assert inj.treated is True


def test_failed_puzzle_increases_duration():
    roster = setup_medical()
    member = make_member()
    inj = make_injury_obj(treatment_type="surgery")
    inj.treatment_duration = 10.0
    member.injuries.append(inj)
    member.update_status()
    roster.members[member.id] = member

    glmed.admit_patient(member.id)
    glmed.start_crew_treatment(member.id, inj.id, "surgery")
    glmed.notify_puzzle_complete(member.id, False)

    # Duration should be 50% longer
    treatment = glmed._active_treatments[member.id]
    assert treatment.duration == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# Bed management
# ---------------------------------------------------------------------------


def test_queue_when_beds_full():
    roster = setup_medical(beds=1)
    m1 = make_member(crew_id="c1")
    m1.injuries.append(make_injury_obj(injury_id="i1"))
    m1.update_status()
    m2 = make_member(crew_id="c2")
    m2.injuries.append(make_injury_obj(injury_id="i2"))
    m2.update_status()
    roster.members["c1"] = m1
    roster.members["c2"] = m2

    r1 = glmed.admit_patient("c1")
    assert r1["bed"] is not None
    r2 = glmed.admit_patient("c2")
    assert r2["bed"] is None  # Queued, no bed
    assert "c2" in glmed._treatment_queue


def test_discharge_frees_bed():
    roster = setup_medical(beds=1)
    member = make_member()
    inj = make_injury_obj(treated=True)
    member.injuries.append(inj)
    roster.members[member.id] = member

    glmed.admit_patient(member.id)
    assert len(glmed._occupied_beds) == 1
    glmed.discharge_patient(member.id)
    assert len(glmed._occupied_beds) == 0


def test_discharge_requires_all_treated():
    roster = setup_medical()
    member = make_member()
    member.injuries.append(make_injury_obj(treated=False))
    member.update_status()
    roster.members[member.id] = member

    glmed.admit_patient(member.id)
    result = glmed.discharge_patient(member.id)
    assert result["success"] is False
    assert "Untreated" in result["message"]


def test_auto_admit_from_queue():
    roster = setup_medical(beds=1)
    m1 = make_member(crew_id="c1")
    m1.injuries.append(make_injury_obj(injury_id="i1", treated=False))
    m1.update_status()
    m2 = make_member(crew_id="c2")
    m2.injuries.append(make_injury_obj(injury_id="i2"))
    m2.update_status()
    roster.members["c1"] = m1
    roster.members["c2"] = m2

    glmed.admit_patient("c1")
    glmed.admit_patient("c2")  # Goes to queue
    assert "c2" in glmed._treatment_queue

    # Make all c1's injuries treated and discharge
    m1.injuries[0].treated = True
    glmed.discharge_patient("c1")

    # Tick should auto-admit c2
    events = glmed.tick(roster, 0.1)
    admitted = [e for e in events if e["event"] == "patient_admitted"]
    assert len(admitted) == 1
    assert admitted[0]["crew_id"] == "c2"


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------


def test_quarantine_crew():
    roster = setup_medical()
    member = make_member()
    member.injuries.append(Injury(
        id="i1", type="infection_stage_1", body_region="torso",
        severity="moderate", description="Infection",
        caused_by="contagion", degrade_timer=180.0,
        treatment_type="quarantine", treatment_duration=50.0,
    ))
    member.update_status()
    roster.members[member.id] = member

    result = glmed.quarantine_crew(member.id)
    assert result["success"] is True
    assert member.location == "quarantine"


def test_quarantine_full():
    roster = setup_medical()
    glmed._quarantine_slots = 1

    m1 = make_member(crew_id="c1")
    m1.injuries.append(Injury(
        id="i1", type="infection_stage_1", body_region="torso",
        severity="moderate", description="Infection",
        caused_by="contagion", degrade_timer=180.0,
        treatment_type="quarantine", treatment_duration=50.0,
    ))
    m1.update_status()
    roster.members["c1"] = m1
    glmed.quarantine_crew("c1")

    m2 = make_member(crew_id="c2")
    m2.injuries.append(Injury(
        id="i2", type="infection_stage_1", body_region="torso",
        severity="moderate", description="Infection",
        caused_by="contagion", degrade_timer=180.0,
        treatment_type="quarantine", treatment_duration=50.0,
    ))
    m2.update_status()
    roster.members["c2"] = m2

    result = glmed.quarantine_crew("c2")
    assert result["success"] is False
    assert "No quarantine" in result["message"]


def test_quarantine_not_infected():
    roster = setup_medical()
    member = make_member()
    member.injuries.append(make_injury_obj())  # Not contagion
    member.update_status()
    roster.members[member.id] = member

    result = glmed.quarantine_crew(member.id)
    assert result["success"] is False


# ---------------------------------------------------------------------------
# Supply consumption
# ---------------------------------------------------------------------------


def test_treatment_consumes_supplies():
    roster = setup_medical()
    glmed.set_supplies(100.0)
    member = make_member()
    inj = make_injury_obj(treatment_type="surgery")  # severity="moderate"
    member.injuries.append(inj)
    member.update_status()
    roster.members[member.id] = member

    glmed.admit_patient(member.id)
    glmed.start_crew_treatment(member.id, inj.id, "surgery")
    # v0.07 §6.1.1.3: Cost is now severity-based (moderate=3.0), not treatment-type.
    from server.models.injuries import SEVERITY_SUPPLY_COSTS
    expected_cost = SEVERITY_SUPPLY_COSTS.get(inj.severity, TREATMENT_SUPPLY_COSTS["surgery"])
    assert glmed.get_supplies() == pytest.approx(100.0 - expected_cost)


def test_cannot_treat_at_zero_supplies():
    roster = setup_medical()
    glmed.set_supplies(0.0)
    member = make_member()
    inj = make_injury_obj(treatment_type="surgery")
    member.injuries.append(inj)
    member.update_status()
    roster.members[member.id] = member

    glmed.admit_patient(member.id)
    result = glmed.start_crew_treatment(member.id, inj.id, "surgery")
    assert result["success"] is False
    assert "Insufficient" in result["message"]


def test_first_aid_cheaper_than_surgery():
    roster = setup_medical()
    glmed.set_supplies(100.0)
    member = make_member()
    inj = make_injury_obj(treatment_type="first_aid")
    member.injuries.append(inj)
    member.update_status()
    roster.members[member.id] = member

    glmed.admit_patient(member.id)
    glmed.start_crew_treatment(member.id, inj.id, "first_aid")
    assert glmed.get_supplies() > 100.0 - TREATMENT_SUPPLY_COSTS["surgery"]


# ---------------------------------------------------------------------------
# Crew factor
# ---------------------------------------------------------------------------


def test_crew_factor_drops_when_injured():
    roster = setup_medical()
    member = make_member(duty_station="engines")
    member.injuries.append(make_injury_obj(severity="serious"))
    member.update_status()
    roster.members[member.id] = member

    factor = roster.crew_factor_for_system("engines")
    assert factor < 1.0


def test_crew_factor_drops_more_in_medical_bay():
    roster = setup_medical()
    member = make_member(crew_id="c1", duty_station="engines")
    member.injuries.append(make_injury_obj())
    member.update_status()
    roster.members["c1"] = member

    factor_on_deck = roster.crew_factor_for_system("engines")

    glmed.admit_patient("c1")
    factor_in_bay = roster.crew_factor_for_system("engines")

    assert factor_in_bay <= factor_on_deck


def test_crew_factor_restored_after_discharge():
    roster = setup_medical()
    member = make_member(crew_id="c1", duty_station="engines")
    inj = make_injury_obj(treated=True)
    member.injuries.append(inj)
    roster.members["c1"] = member

    glmed.admit_patient("c1")
    glmed.discharge_patient("c1")
    assert member.status == "active"
    assert member.location == f"deck_{member.deck}"


# ---------------------------------------------------------------------------
# Death
# ---------------------------------------------------------------------------


def test_death_removes_from_active():
    roster = setup_medical()
    member = make_member()
    member.injuries.append(make_injury_obj(severity="critical"))
    member.status = "critical"
    roster.members[member.id] = member

    glmed.admit_patient(member.id)
    glmed.tick(roster, CRITICAL_DEATH_TIMER + 1.0)

    assert member.status == "dead"
    assert member.id not in glmed._occupied_beds.values()


def test_dead_crew_factor_zero():
    roster = setup_medical()
    # Add exactly one crew member as engine crew
    member = make_member(crew_id="eng1", duty_station="engines")
    roster.members["eng1"] = member
    # Remove all other engine crew
    for mid in list(roster.members.keys()):
        if mid != "eng1" and roster.members[mid].duty_station == "engines":
            del roster.members[mid]

    member.status = "dead"
    member.location = "morgue"
    factor = roster.crew_factor_for_system("engines")
    assert factor < 1.0


# ---------------------------------------------------------------------------
# Multiple injuries
# ---------------------------------------------------------------------------


def test_multiple_injuries_on_one_member():
    roster = setup_medical()
    member = make_member()
    member.injuries.append(make_injury_obj(injury_id="i1", severity="minor"))
    member.injuries.append(make_injury_obj(injury_id="i2", severity="serious"))
    member.update_status()
    roster.members[member.id] = member

    assert member.worst_severity == "serious"
    assert member.status in ("injured", "critical")


def test_treat_one_injury_leaves_others():
    roster = setup_medical()
    member = make_member()
    inj1 = make_injury_obj(injury_id="i1", severity="moderate", treatment_type="first_aid")
    inj1.treatment_duration = 5.0
    inj2 = make_injury_obj(injury_id="i2", severity="serious", treatment_type="surgery")
    member.injuries = [inj1, inj2]
    member.update_status()
    roster.members[member.id] = member

    glmed.admit_patient(member.id)
    glmed.start_crew_treatment(member.id, "i1", "first_aid")
    glmed.tick(roster, 6.0)

    assert inj1.treated is True
    assert inj2.treated is False


# ---------------------------------------------------------------------------
# Treatment priority queue
# ---------------------------------------------------------------------------


def test_set_triage_priority():
    roster = setup_medical(beds=0)  # No beds to force queue
    m1 = make_member(crew_id="c1")
    m1.injuries.append(make_injury_obj(injury_id="i1"))
    m1.update_status()
    m2 = make_member(crew_id="c2")
    m2.injuries.append(make_injury_obj(injury_id="i2"))
    m2.update_status()
    m3 = make_member(crew_id="c3")
    m3.injuries.append(make_injury_obj(injury_id="i3"))
    m3.update_status()
    roster.members.update({"c1": m1, "c2": m2, "c3": m3})

    glmed.admit_patient("c1")
    glmed.admit_patient("c2")
    glmed.admit_patient("c3")

    assert glmed._treatment_queue == ["c1", "c2", "c3"]
    glmed.set_triage_priority(["c3", "c1", "c2"])
    assert glmed._treatment_queue == ["c3", "c1", "c2"]


# ---------------------------------------------------------------------------
# Serialise/deserialise
# ---------------------------------------------------------------------------


def test_serialise_round_trip():
    roster = setup_medical()
    member = make_member()
    inj = make_injury_obj(treatment_type="first_aid")
    inj.treatment_duration = 20.0
    member.injuries.append(inj)
    member.update_status()
    roster.members[member.id] = member

    glmed.admit_patient(member.id)
    glmed.start_crew_treatment(member.id, inj.id, "first_aid")
    glmed.tick(roster, 5.0)

    data = glmed.serialise()
    glmed.reset()
    glmed.deserialise(data)

    # Verify state restored
    assert "v2" in data
    assert data["v2"]["treatment_beds"] == 4


def test_serialise_includes_morgue():
    roster = setup_medical()
    member = make_member()
    member.injuries.append(make_injury_obj(severity="critical"))
    member.status = "critical"
    roster.members[member.id] = member

    glmed.tick(roster, CRITICAL_DEATH_TIMER + 1.0)
    data = glmed.serialise()
    assert member.id in data["v2"]["morgue"]


def test_serialise_includes_quarantine():
    roster = setup_medical()
    member = make_member()
    member.injuries.append(Injury(
        id="i1", type="infection_stage_1", body_region="torso",
        severity="moderate", description="Infection",
        caused_by="contagion", degrade_timer=180.0,
        treatment_type="quarantine", treatment_duration=50.0,
    ))
    member.update_status()
    roster.members[member.id] = member

    glmed.quarantine_crew(member.id)
    data = glmed.serialise()
    assert member.id in data["v2"]["quarantine_occupied"].values()


# ---------------------------------------------------------------------------
# Legacy interface compatibility
# ---------------------------------------------------------------------------


def test_legacy_start_treatment():
    glmed.reset()
    ship = Ship()
    ship.crew.apply_casualties("engineering", 3)
    assert glmed.start_treatment("engineering", "injured", ship) is True
    assert ship.medical_supplies == 20 - glmed.TREATMENT_COST


def test_legacy_start_treatment_no_supplies():
    glmed.reset()
    ship = Ship()
    ship.medical_supplies = 0
    ship.crew.apply_casualties("engineering", 2)
    assert glmed.start_treatment("engineering", "injured", ship) is False


def test_legacy_cancel_treatment():
    glmed.reset()
    ship = Ship()
    ship.crew.apply_casualties("engineering", 2)
    glmed.start_treatment("engineering", "injured", ship)
    glmed.cancel_treatment("engineering")
    assert "engineering" not in glmed.get_active_treatments()


def test_legacy_tick_treatments():
    glmed.reset()
    ship = Ship()
    ship.crew.apply_casualties("engineering", 3)
    glmed.start_treatment("engineering", "injured", ship)
    healed = glmed.tick_treatments(ship, glmed.HEAL_INTERVAL + 0.1)
    assert "engineering" in healed


def test_legacy_disease_state():
    glmed.reset()
    state = glmed.get_disease_state()
    assert "infected_decks" in state
    assert "spread_timer" in state


def test_legacy_outbreak():
    glmed.reset()
    glmed.start_outbreak("medical", "test_pathogen")
    state = glmed.get_disease_state()
    assert "medical" in state["infected_decks"]


def test_legacy_serialise():
    glmed.reset()
    data = glmed.serialise()
    assert "active_treatments" in data
    assert "v2" in data


def test_legacy_deserialise():
    glmed.reset()
    data = {
        "active_treatments": {"engineering": "injured"},
        "heal_timers": {"engineering": 1.0},
        "active_outbreak": {"medical": "pathogen"},
        "spread_timer": 5.0,
    }
    glmed.deserialise(data)
    assert glmed.get_active_treatments() == {"engineering": "injured"}
    assert glmed.get_disease_state()["infected_decks"] == {"medical": "pathogen"}


# ---------------------------------------------------------------------------
# get_medical_state
# ---------------------------------------------------------------------------


def test_get_medical_state():
    setup_medical()
    state = glmed.get_medical_state()
    assert "beds_total" in state
    assert "beds_occupied" in state
    assert "queue" in state
    assert "supplies" in state
    assert "quarantine_total" in state
    assert "morgue" in state


def test_get_medical_state_after_admit():
    roster = setup_medical()
    member = make_member()
    member.injuries.append(make_injury_obj())
    member.update_status()
    roster.members[member.id] = member
    glmed.admit_patient(member.id)

    state = glmed.get_medical_state()
    assert member.id in state["beds_occupied"].values()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_admit_dead_crew_fails():
    roster = setup_medical()
    member = make_member(status="dead")
    roster.members[member.id] = member
    result = glmed.admit_patient(member.id)
    assert result["success"] is False


def test_admit_already_in_bay():
    roster = setup_medical()
    member = make_member()
    member.injuries.append(make_injury_obj())
    member.update_status()
    roster.members[member.id] = member

    glmed.admit_patient(member.id)
    result = glmed.admit_patient(member.id)
    assert result["success"] is False
    assert "Already" in result["message"]


def test_treat_without_bed_fails():
    roster = setup_medical()
    member = make_member()
    inj = make_injury_obj()
    member.injuries.append(inj)
    member.update_status()
    roster.members[member.id] = member
    # Don't admit — no bed
    result = glmed.start_crew_treatment(member.id, inj.id, "surgery")
    assert result["success"] is False
    assert "Not in a bed" in result["message"]


def test_treat_already_treated_fails():
    roster = setup_medical()
    member = make_member()
    inj = make_injury_obj(treated=True)
    member.injuries.append(inj)
    roster.members[member.id] = member

    glmed.admit_patient(member.id)
    result = glmed.start_crew_treatment(member.id, inj.id, "surgery")
    assert result["success"] is False


def test_two_treatments_on_same_member_fails():
    roster = setup_medical()
    member = make_member()
    inj1 = make_injury_obj(injury_id="i1", treatment_type="first_aid")
    inj2 = make_injury_obj(injury_id="i2", treatment_type="surgery")
    member.injuries = [inj1, inj2]
    member.update_status()
    roster.members[member.id] = member

    glmed.admit_patient(member.id)
    glmed.start_crew_treatment(member.id, "i1", "first_aid")
    result = glmed.start_crew_treatment(member.id, "i2", "surgery")
    assert result["success"] is False
    assert "Another treatment" in result["message"]


def test_supplies_set_and_get():
    glmed.reset()
    glmed.set_supplies(75.5)
    assert glmed.get_supplies() == pytest.approx(75.5)


def test_supplies_capped_at_max():
    glmed.reset()
    glmed.set_supplies(999.0)
    assert glmed.get_supplies() == glmed.MAX_MEDICAL_SUPPLIES


def test_stabilise_serious_resets_degrade_timer():
    roster = setup_medical()
    member = make_member()
    inj = make_injury_obj(severity="serious")
    inj.degrade_timer = 30.0  # Partially degraded
    member.injuries.append(inj)
    member.update_status()
    roster.members[member.id] = member

    result = glmed.stabilise_crew(member.id, inj.id)
    assert result["success"] is True
    assert inj.degrade_timer == DEGRADE_TIMERS["serious"]  # 120.0


def test_stabilise_critical_resets_death_timer():
    roster = setup_medical()
    member = make_member()
    inj = make_injury_obj(severity="critical")
    inj.death_timer = 50.0  # Partially degraded
    member.injuries.append(inj)
    member.status = "critical"
    roster.members[member.id] = member

    result = glmed.stabilise_crew(member.id, inj.id)
    assert result["success"] is True
    assert inj.death_timer == CRITICAL_DEATH_TIMER  # 240.0


def test_stabilise_moderate_resets_degrade_timer():
    roster = setup_medical()
    member = make_member()
    inj = make_injury_obj(severity="moderate")
    inj.degrade_timer = 60.0  # Partially degraded
    member.injuries.append(inj)
    member.update_status()
    roster.members[member.id] = member

    result = glmed.stabilise_crew(member.id, inj.id)
    assert result["success"] is True
    assert inj.degrade_timer == DEGRADE_TIMERS["moderate"]  # 180.0


def test_stabilise_deducts_supplies():
    roster = setup_medical()
    glmed.set_supplies(100.0)
    member = make_member()
    inj = make_injury_obj(severity="moderate")
    inj.degrade_timer = 60.0
    member.injuries.append(inj)
    member.update_status()
    roster.members[member.id] = member

    glmed.stabilise_crew(member.id, inj.id)
    assert glmed.get_supplies() == pytest.approx(100.0 - TREATMENT_SUPPLY_COSTS["stabilise"])


def test_stabilise_works_at_zero_supplies_deducts_nothing_extra():
    roster = setup_medical()
    glmed.set_supplies(0.0)
    member = make_member()
    inj = make_injury_obj(severity="serious")
    inj.degrade_timer = 30.0
    member.injuries.append(inj)
    member.update_status()
    roster.members[member.id] = member

    result = glmed.stabilise_crew(member.id, inj.id)
    assert result["success"] is True
    assert glmed.get_supplies() == pytest.approx(0.0)
    assert inj.degrade_timer == DEGRADE_TIMERS["serious"]


def test_reset_clears_everything():
    roster = setup_medical()
    member = make_member()
    member.injuries.append(make_injury_obj())
    member.update_status()
    roster.members[member.id] = member
    glmed.admit_patient(member.id)

    glmed.reset()
    state = glmed.get_medical_state()
    assert state["beds_occupied"] == {}
    assert state["queue"] == []
    assert state["morgue"] == []
