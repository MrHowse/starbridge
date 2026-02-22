"""
Tests for Part 4: Medical client UI — message schemas, server integration.

These tests validate:
1. New medical message payload schemas (admit, treat, stabilise, discharge, quarantine)
2. Payload validation through the dispatcher
3. Medical state serialisation for client broadcast
4. Legacy message compatibility
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.models.messages import (
    MedicalAdmitPayload,
    MedicalCancelTreatmentPayload,
    MedicalDischargePayload,
    MedicalQuarantinePayload,
    MedicalStabilisePayload,
    MedicalTreatCrewPayload,
    MedicalTreatPayload,
)
from server.models.messages.base import Message, validate_payload


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestMedicalAdmitPayload:
    def test_valid(self):
        p = MedicalAdmitPayload(crew_id="crew_001")
        assert p.crew_id == "crew_001"

    def test_missing_crew_id(self):
        with pytest.raises(ValidationError):
            MedicalAdmitPayload()

    def test_message_dispatch(self):
        msg = Message.build("medical.admit", {"crew_id": "crew_001"})
        result = validate_payload(msg)
        assert isinstance(result, MedicalAdmitPayload)
        assert result.crew_id == "crew_001"


class TestMedicalTreatPayload:
    def test_valid(self):
        p = MedicalTreatPayload(crew_id="crew_001", injury_id="inj_001")
        assert p.crew_id == "crew_001"
        assert p.injury_id == "inj_001"

    def test_missing_injury_id(self):
        with pytest.raises(ValidationError):
            MedicalTreatPayload(crew_id="crew_001")

    def test_message_dispatch(self):
        msg = Message.build("medical.treat", {"crew_id": "c1", "injury_id": "i1"})
        result = validate_payload(msg)
        assert isinstance(result, MedicalTreatPayload)


class TestMedicalStabilisePayload:
    def test_valid(self):
        p = MedicalStabilisePayload(crew_id="crew_001", injury_id="inj_001")
        assert p.crew_id == "crew_001"
        assert p.injury_id == "inj_001"

    def test_message_dispatch(self):
        msg = Message.build("medical.stabilise", {"crew_id": "c1", "injury_id": "i1"})
        result = validate_payload(msg)
        assert isinstance(result, MedicalStabilisePayload)


class TestMedicalDischargePayload:
    def test_valid(self):
        p = MedicalDischargePayload(crew_id="crew_001")
        assert p.crew_id == "crew_001"

    def test_message_dispatch(self):
        msg = Message.build("medical.discharge", {"crew_id": "c1"})
        result = validate_payload(msg)
        assert isinstance(result, MedicalDischargePayload)


class TestMedicalQuarantinePayload:
    def test_valid(self):
        p = MedicalQuarantinePayload(crew_id="crew_001")
        assert p.crew_id == "crew_001"

    def test_message_dispatch(self):
        msg = Message.build("medical.quarantine", {"crew_id": "c1"})
        result = validate_payload(msg)
        assert isinstance(result, MedicalQuarantinePayload)


# ---------------------------------------------------------------------------
# Legacy message compatibility
# ---------------------------------------------------------------------------


class TestLegacyMessages:
    def test_treat_crew_still_valid(self):
        msg = Message.build("medical.treat_crew", {"deck": "bridge", "injury_type": "injured"})
        result = validate_payload(msg)
        assert isinstance(result, MedicalTreatCrewPayload)
        assert result.deck == "bridge"
        assert result.injury_type == "injured"

    def test_cancel_treatment_still_valid(self):
        msg = Message.build("medical.cancel_treatment", {"deck": "bridge"})
        result = validate_payload(msg)
        assert isinstance(result, MedicalCancelTreatmentPayload)

    def test_treat_crew_invalid_type(self):
        with pytest.raises(ValidationError):
            MedicalTreatCrewPayload(deck="bridge", injury_type="dead")


# ---------------------------------------------------------------------------
# Medical state format tests (ensure get_medical_state output is client-ready)
# ---------------------------------------------------------------------------

import random

from server.models.crew_roster import IndividualCrewRoster, Injury
import server.game_loop_medical_v2 as glmed


def _make_roster(count=6, ship_class="frigate"):
    rng = random.Random(42)
    roster = IndividualCrewRoster.generate(count, ship_class, rng)
    glmed.reset()
    glmed.init_roster(roster, ship_class)
    return roster


class TestMedicalStateFormat:
    def test_state_has_all_fields(self):
        _make_roster()
        state = glmed.get_medical_state()
        expected_keys = {
            "beds_total", "beds_occupied", "queue",
            "active_treatments", "supplies", "supplies_max",
            "quarantine_total", "quarantine_occupied", "morgue",
        }
        assert expected_keys == set(state.keys())

    def test_beds_total_matches_ship_class(self):
        _make_roster(ship_class="scout")
        state = glmed.get_medical_state()
        assert state["beds_total"] == 2

    def test_beds_total_battleship(self):
        _make_roster(ship_class="battleship")
        state = glmed.get_medical_state()
        assert state["beds_total"] == 6

    def test_supplies_default_100(self):
        _make_roster()
        state = glmed.get_medical_state()
        assert state["supplies"] == 100.0
        assert state["supplies_max"] == 100.0

    def test_state_after_admit(self):
        roster = _make_roster()
        member = next(iter(roster.members.values()))
        member.injuries.append(Injury(
            id="inj_t1", type="lacerations", body_region="torso",
            severity="moderate", description="Test", caused_by="test",
            degrade_timer=180.0, treatment_type="first_aid",
            treatment_duration=15.0,
        ))
        member.update_status()
        glmed.admit_patient(member.id)
        state = glmed.get_medical_state()
        assert len(state["beds_occupied"]) == 1
        assert member.id in state["beds_occupied"].values()

    def test_state_after_treatment_start(self):
        roster = _make_roster()
        member = next(iter(roster.members.values()))
        member.injuries.append(Injury(
            id="inj_t2", type="lacerations", body_region="torso",
            severity="moderate", description="Test", caused_by="test",
            degrade_timer=180.0, treatment_type="first_aid",
            treatment_duration=15.0,
        ))
        member.update_status()
        glmed.admit_patient(member.id)
        glmed.start_crew_treatment(member.id, "inj_t2", "first_aid")
        state = glmed.get_medical_state()
        assert member.id in state["active_treatments"]
        t = state["active_treatments"][member.id]
        assert t["treatment_type"] == "first_aid"
        assert t["duration"] == 15.0
        assert t["elapsed"] == 0.0

    def test_state_quarantine(self):
        roster = _make_roster()
        member = next(iter(roster.members.values()))
        member.injuries.append(Injury(
            id="inj_t3", type="infection_stage_1", body_region="torso",
            severity="moderate", description="Infection", caused_by="contagion",
            degrade_timer=180.0, treatment_type="quarantine",
            treatment_duration=50.0,
        ))
        member.update_status()
        glmed.quarantine_crew(member.id)
        state = glmed.get_medical_state()
        assert len(state["quarantine_occupied"]) == 1

    def test_state_morgue(self):
        roster = _make_roster()
        member = next(iter(roster.members.values()))
        member.injuries.append(Injury(
            id="inj_t4", type="internal_bleeding", body_region="torso",
            severity="critical", description="Fatal", caused_by="test",
            degrade_timer=0.0, death_timer=0.1,
            treatment_type="surgery", treatment_duration=45.0,
        ))
        member.update_status()
        # Tick to trigger death
        glmed.tick(roster, 1.0)
        state = glmed.get_medical_state()
        assert len(state["morgue"]) >= 1


# ---------------------------------------------------------------------------
# Crew roster broadcast format
# ---------------------------------------------------------------------------


class TestCrewRosterBroadcast:
    def test_roster_serialise_has_members(self):
        roster = _make_roster(8)
        data = roster.serialise()
        assert "members" in data
        assert len(data["members"]) == 8

    def test_member_dict_has_fields(self):
        roster = _make_roster(4)
        member = next(iter(roster.members.values()))
        d = member.to_dict()
        assert "id" in d
        assert "first_name" in d
        assert "surname" in d
        assert "rank" in d
        assert "deck" in d
        assert "duty_station" in d
        assert "status" in d
        assert "injuries" in d
        assert "location" in d

    def test_injury_dict_has_timer_fields(self):
        roster = _make_roster(4)
        member = next(iter(roster.members.values()))
        member.injuries.append(Injury(
            id="inj_b1", type="lacerations", body_region="left_arm",
            severity="moderate", description="Cuts", caused_by="test",
            degrade_timer=180.0, treatment_type="first_aid",
            treatment_duration=15.0,
        ))
        d = member.to_dict()
        inj = d["injuries"][0]
        assert "degrade_timer" in inj
        assert "death_timer" in inj
        assert "severity" in inj
        assert "body_region" in inj
        assert "treatment_type" in inj
        assert "treatment_duration" in inj
        assert "treated" in inj
        assert "treating" in inj
