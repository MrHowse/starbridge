"""Tests for Medical Ship Hospital Systems (v0.07 §2.7).

Covers: module activation, surgical theatre, triage AI, rescue beacon,
medical supplies, beds/quarantine, build state, save/resume, integration.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from unittest.mock import patch

import pytest

import server.game_loop_medical_v2 as glmed
import server.game_loop_medical_ship as glms
from server.game_loop_medical_ship import (
    BEACON_HESITATION_CHANCE,
    BEACON_HESITATION_FACTIONS,
    MEDICAL_SHIP_SUPPLY_MAX,
    SURGICAL_THEATRE_DURATION_LIMB,
    SURGICAL_THEATRE_DURATION_NEURO,
    SURGICAL_THEATRE_DURATION_RADIATION,
    SURGICAL_THEATRE_SUPPLY_COST,
)
from server.models.crew_roster import CrewMember, IndividualCrewRoster, Injury
from server.models.injuries import TREATMENT_SUPPLY_COSTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_roster(
    count: int = 4,
    ship_class: str = "medical_ship",
) -> IndividualCrewRoster:
    """Create a small roster and initialise the medical module."""
    roster = IndividualCrewRoster.generate(count, ship_class=ship_class, rng=random.Random(42))
    glmed.reset()
    glmed.init_roster(roster, ship_class=ship_class)
    return roster


def _make_injury(
    injury_id: str = "inj_test",
    injury_type: str = "lacerations",
    body_region: str = "torso",
    severity: str = "moderate",
    treatment_type: str = "first_aid",
    treatment_duration: float = 15.0,
) -> Injury:
    return Injury(
        id=injury_id,
        type=injury_type,
        body_region=body_region,
        severity=severity,
        description="Test injury",
        caused_by="test",
        treatment_type=treatment_type,
        treatment_duration=treatment_duration,
    )


def _reset_medical_ship():
    """Reset both glms and glmed for medical ship."""
    glms.reset(active=True)
    roster = _make_roster(ship_class="medical_ship")
    glmed.set_surgical_theatre(True)
    glmed.set_triage_ai(True)
    glmed.set_supply_max(MEDICAL_SHIP_SUPPLY_MAX)
    return roster


def _reset_non_medical():
    """Reset for a non-medical ship."""
    glms.reset(active=False)
    roster = _make_roster(count=4, ship_class="frigate")
    return roster


# ---------------------------------------------------------------------------
# Module Activation
# ---------------------------------------------------------------------------


class TestModuleActivation:
    def test_active_for_medical_ship(self):
        glms.reset(active=True)
        assert glms.is_active() is True
        assert glms.is_rescue_beacon_active() is True
        assert glms.is_surgical_theatre_active() is True
        assert glms.is_triage_ai_active() is True

    def test_inactive_for_non_medical(self):
        glms.reset(active=False)
        assert glms.is_active() is False
        assert glms.is_rescue_beacon_active() is False
        assert glms.is_surgical_theatre_active() is False
        assert glms.is_triage_ai_active() is False

    def test_reset_clears_all_flags(self):
        glms.reset(active=True)
        assert glms.is_active() is True
        glms.reset(active=False)
        assert glms.is_active() is False
        assert glms.is_rescue_beacon_active() is False


# ---------------------------------------------------------------------------
# Surgical Theatre
# ---------------------------------------------------------------------------


class TestSurgicalTheatre:
    def test_can_perform_surgery_on_limb(self):
        glms.reset(active=True)
        for region in ("left_arm", "right_arm", "left_leg", "right_leg"):
            inj = _make_injury(body_region=region, severity="serious")
            assert glms.can_perform_surgery(inj) is True

    def test_can_perform_surgery_on_radiation(self):
        glms.reset(active=True)
        inj = _make_injury(
            injury_type="acute_radiation_syndrome",
            body_region="whole_body",
            severity="minor",
            treatment_type="intensive_care",
        )
        assert glms.can_perform_surgery(inj) is True

    def test_can_perform_surgery_on_critical_head(self):
        glms.reset(active=True)
        inj = _make_injury(body_region="head", severity="critical")
        assert glms.can_perform_surgery(inj) is True

    def test_cannot_perform_surgery_when_inactive(self):
        glms.reset(active=False)
        inj = _make_injury(body_region="left_arm", severity="serious")
        assert glms.can_perform_surgery(inj) is False

    def test_cannot_perform_surgery_on_ineligible_injury(self):
        glms.reset(active=True)
        # Torso moderate — not eligible
        inj = _make_injury(body_region="torso", severity="moderate")
        assert glms.can_perform_surgery(inj) is False

    def test_cannot_perform_surgery_on_non_critical_head(self):
        glms.reset(active=True)
        inj = _make_injury(body_region="head", severity="moderate")
        assert glms.can_perform_surgery(inj) is False

    def test_surgical_duration_limb(self):
        glms.reset(active=True)
        inj = _make_injury(body_region="left_arm")
        assert glms.get_surgical_duration(inj) == SURGICAL_THEATRE_DURATION_LIMB

    def test_surgical_duration_radiation(self):
        glms.reset(active=True)
        inj = _make_injury(injury_type="acute_radiation_syndrome", body_region="whole_body")
        assert glms.get_surgical_duration(inj) == SURGICAL_THEATRE_DURATION_RADIATION

    def test_surgical_duration_neuro(self):
        glms.reset(active=True)
        inj = _make_injury(body_region="head", severity="critical")
        assert glms.get_surgical_duration(inj) == SURGICAL_THEATRE_DURATION_NEURO

    def test_perform_surgical_procedure_success(self):
        roster = _reset_medical_ship()
        crew_id = list(roster.members.keys())[0]
        member = roster.members[crew_id]
        inj = _make_injury(injury_id="inj_s1", body_region="left_arm", severity="serious")
        member.injuries.append(inj)
        member.status = "injured"
        # Admit to bed
        result = glmed.admit_patient(crew_id)
        assert result["success"] is True
        # Perform surgical procedure
        result = glmed.perform_surgical_procedure(crew_id, "inj_s1")
        assert result["success"] is True
        assert result["puzzle_required"] is True
        assert inj.treating is True

    def test_surgical_procedure_requires_puzzle(self):
        roster = _reset_medical_ship()
        crew_id = list(roster.members.keys())[0]
        member = roster.members[crew_id]
        inj = _make_injury(injury_id="inj_s2", body_region="right_leg", severity="serious")
        member.injuries.append(inj)
        member.status = "injured"
        glmed.admit_patient(crew_id)
        result = glmed.perform_surgical_procedure(crew_id, "inj_s2")
        assert result["puzzle_required"] is True

    def test_surgical_procedure_deducts_supplies(self):
        roster = _reset_medical_ship()
        crew_id = list(roster.members.keys())[0]
        member = roster.members[crew_id]
        inj = _make_injury(injury_id="inj_s3", body_region="left_leg", severity="serious")
        member.injuries.append(inj)
        member.status = "injured"
        glmed.admit_patient(crew_id)
        before = glmed.get_supplies()
        glmed.perform_surgical_procedure(crew_id, "inj_s3")
        after = glmed.get_supplies()
        assert before - after == TREATMENT_SUPPLY_COSTS["surgical_theatre"]

    def test_surgical_procedure_insufficient_supplies(self):
        roster = _reset_medical_ship()
        crew_id = list(roster.members.keys())[0]
        member = roster.members[crew_id]
        inj = _make_injury(injury_id="inj_s4", body_region="left_arm", severity="serious")
        member.injuries.append(inj)
        member.status = "injured"
        glmed.admit_patient(crew_id)
        glmed.set_supplies(1.0)  # Not enough
        result = glmed.perform_surgical_procedure(crew_id, "inj_s4")
        assert result["success"] is False
        assert "Insufficient" in result["message"]

    def test_surgical_procedure_not_available(self):
        roster = _make_roster(ship_class="frigate")
        glms.reset(active=False)
        crew_id = list(roster.members.keys())[0]
        member = roster.members[crew_id]
        inj = _make_injury(injury_id="inj_s5", body_region="left_arm", severity="serious")
        member.injuries.append(inj)
        member.status = "injured"
        glmed.admit_patient(crew_id)
        result = glmed.perform_surgical_procedure(crew_id, "inj_s5")
        assert result["success"] is False
        assert "not available" in result["message"]

    def test_surgical_procedure_ineligible_injury(self):
        roster = _reset_medical_ship()
        crew_id = list(roster.members.keys())[0]
        member = roster.members[crew_id]
        inj = _make_injury(injury_id="inj_s6", body_region="torso", severity="moderate")
        member.injuries.append(inj)
        member.status = "injured"
        glmed.admit_patient(crew_id)
        result = glmed.perform_surgical_procedure(crew_id, "inj_s6")
        assert result["success"] is False
        assert "not eligible" in result["message"]

    def test_surgical_procedure_completes_via_tick(self):
        roster = _reset_medical_ship()
        crew_id = list(roster.members.keys())[0]
        member = roster.members[crew_id]
        inj = _make_injury(
            injury_id="inj_s7", body_region="left_arm", severity="serious",
            treatment_duration=15.0,
        )
        member.injuries.append(inj)
        member.status = "injured"
        glmed.admit_patient(crew_id)
        glmed.perform_surgical_procedure(crew_id, "inj_s7")
        # Complete the puzzle so treatment can progress
        glmed.notify_puzzle_complete(crew_id, success=True)
        # Tick enough to complete (duration = SURGICAL_THEATRE_DURATION_LIMB = 60s)
        for _ in range(610):
            glmed.tick(roster, 0.1)
        assert inj.treated is True


# ---------------------------------------------------------------------------
# Triage AI
# ---------------------------------------------------------------------------


class TestTriageAI:
    def _make_uncrewed_roster(self):
        """Create a roster with no medical crew assigned."""
        roster = _reset_medical_ship()
        # Set all crew to non-medical duty stations so crew_factor = 0
        for m in roster.members.values():
            m.duty_station = "helm"
            m.location = "deck_1"
            m.status = "active"
        return roster

    def test_triage_ai_auto_admits(self):
        roster = self._make_uncrewed_roster()
        # Injure one crew
        crew_id = list(roster.members.keys())[0]
        member = roster.members[crew_id]
        inj = _make_injury(injury_id="inj_t1")
        member.injuries.append(inj)
        member.status = "injured"
        events = glmed.tick(roster, 0.1)
        triage_admits = [e for e in events if e.get("event") == "triage_ai_admit"]
        assert len(triage_admits) >= 1
        assert member.location == "medical_bay"

    def test_triage_ai_auto_starts_treatment(self):
        roster = self._make_uncrewed_roster()
        crew_id = list(roster.members.keys())[0]
        member = roster.members[crew_id]
        inj = _make_injury(injury_id="inj_t2")
        member.injuries.append(inj)
        member.status = "injured"
        events = glmed.tick(roster, 0.1)
        triage_treats = [e for e in events if e.get("event") == "triage_ai_treat"]
        assert len(triage_treats) >= 1
        assert inj.treating is True

    def test_triage_ai_priority_critical_first(self):
        roster = self._make_uncrewed_roster()
        keys = list(roster.members.keys())
        # Set up two injured crew
        m1 = roster.members[keys[0]]
        m1.injuries.append(_make_injury(injury_id="inj_minor", severity="minor"))
        m1.status = "injured"
        m2 = roster.members[keys[1]]
        m2.injuries.append(_make_injury(injury_id="inj_critical", severity="critical"))
        m2.status = "injured"
        events = glmed.tick(roster, 0.1)
        admits = [e for e in events if e.get("event") == "triage_ai_admit"]
        # Critical should be admitted first (first in list)
        if len(admits) >= 2:
            assert admits[0]["crew_id"] == keys[1]

    def test_triage_ai_does_not_act_with_medical_crew(self):
        roster = _reset_medical_ship()
        # Keep one crew member assigned to medical_bay (default from generate)
        has_medical = False
        for m in roster.members.values():
            if m.duty_station == "medical_bay":
                has_medical = True
                m.location = f"deck_{m.deck}"
                m.status = "active"
                break
        # If no medical crew assigned, assign one
        if not has_medical:
            first_m = list(roster.members.values())[0]
            first_m.duty_station = "medical_bay"
            first_m.location = f"deck_{first_m.deck}"
            first_m.status = "active"

        # Injure another crew member
        others = [m for m in roster.members.values() if m.duty_station != "medical_bay"]
        if others:
            victim = others[0]
            victim.injuries.append(_make_injury(injury_id="inj_t_no"))
            victim.status = "injured"
            victim.location = "deck_1"

        events = glmed.tick(roster, 0.1)
        triage_events = [e for e in events if e.get("event", "").startswith("triage_ai")]
        assert len(triage_events) == 0

    def test_triage_ai_does_not_act_on_non_medical_ship(self):
        roster = _reset_non_medical()
        for m in roster.members.values():
            m.duty_station = "helm"
            m.location = "deck_1"
            m.status = "active"
        crew_id = list(roster.members.keys())[0]
        member = roster.members[crew_id]
        member.injuries.append(_make_injury(injury_id="inj_t_nms"))
        member.status = "injured"
        events = glmed.tick(roster, 0.1)
        triage_events = [e for e in events if e.get("event", "").startswith("triage_ai")]
        assert len(triage_events) == 0

    def test_triage_ai_respects_bed_capacity(self):
        roster = self._make_uncrewed_roster()
        # Injure all crew members (8 beds max for medical ship)
        for m in roster.members.values():
            m.injuries.append(_make_injury(injury_id=f"inj_cap_{m.id}"))
            m.status = "injured"
        events = glmed.tick(roster, 0.1)
        admits = [e for e in events if e.get("event") == "triage_ai_admit"]
        # Should not exceed bed count (8 for medical ship)
        assert len(admits) <= glmed.get_bed_count()

    def test_triage_ai_correct_treatment_type(self):
        roster = self._make_uncrewed_roster()
        crew_id = list(roster.members.keys())[0]
        member = roster.members[crew_id]
        inj = _make_injury(injury_id="inj_t_type", treatment_type="surgery", treatment_duration=35.0)
        member.injuries.append(inj)
        member.status = "injured"
        events = glmed.tick(roster, 0.1)
        treats = [e for e in events if e.get("event") == "triage_ai_treat"]
        assert len(treats) >= 1
        assert treats[0]["treatment_type"] == "surgery"

    def test_triage_ai_multiple_injuries_most_severe_first(self):
        roster = self._make_uncrewed_roster()
        crew_id = list(roster.members.keys())[0]
        member = roster.members[crew_id]
        minor = _make_injury(injury_id="inj_mi", severity="minor", treatment_duration=10.0)
        critical = _make_injury(injury_id="inj_cr", severity="critical", treatment_duration=45.0)
        member.injuries.extend([minor, critical])
        member.status = "injured"
        events = glmed.tick(roster, 0.1)
        treats = [e for e in events if e.get("event") == "triage_ai_treat"]
        if treats:
            # Should treat the critical injury first
            assert treats[0]["injury_id"] == "inj_cr"


# ---------------------------------------------------------------------------
# Rescue Beacon
# ---------------------------------------------------------------------------


class TestRescueBeacon:
    def test_beacon_active_on_medical_ship(self):
        glms.reset(active=True)
        assert glms.is_rescue_beacon_active() is True

    def test_beacon_inactive_on_non_medical(self):
        glms.reset(active=False)
        assert glms.is_rescue_beacon_active() is False

    def test_hesitation_chance_computed(self):
        glms.reset(active=True)
        chance = glms.get_beacon_hesitation("rebel")
        assert chance == BEACON_HESITATION_CHANCE * BEACON_HESITATION_FACTIONS["rebel"]

    def test_faction_multiplier_applied(self):
        glms.reset(active=True)
        for faction, mult in BEACON_HESITATION_FACTIONS.items():
            expected = BEACON_HESITATION_CHANCE * mult
            assert glms.get_beacon_hesitation(faction) == pytest.approx(expected)

    def test_hesitation_zero_when_inactive(self):
        glms.reset(active=False)
        assert glms.get_beacon_hesitation("rebel") == 0.0

    def test_enemy_in_chase_may_flee(self):
        """Enemy in chase state may flee when beacon active (seeded rng)."""
        glms.reset(active=True)
        from server.models.world import Enemy, ENEMY_TYPE_PARAMS
        enemy = Enemy(
            id="e1", type="scout", x=5000, y=5000, heading=0.0,
        )
        enemy.ai_state = "chase"
        params = ENEMY_TYPE_PARAMS["scout"]
        from server.systems.ai import _update_state
        with patch("random.random", return_value=0.0001):
            _update_state(
                enemy, params, dist=3000.0, detect_range=10000.0,
                rescue_beacon_active=True,
            )
        assert enemy.ai_state == "flee"

    def test_enemy_in_idle_may_flee(self):
        """Enemy in idle state may flee when beacon active."""
        glms.reset(active=True)
        from server.models.world import Enemy, ENEMY_TYPE_PARAMS
        enemy = Enemy(
            id="e2", type="scout", x=5000, y=5000, heading=0.0,
        )
        enemy.ai_state = "idle"
        params = ENEMY_TYPE_PARAMS["scout"]
        from server.systems.ai import _update_state
        with patch("random.random", return_value=0.0001):
            _update_state(
                enemy, params, dist=3000.0, detect_range=10000.0,
                rescue_beacon_active=True,
            )
        assert enemy.ai_state == "flee"


# ---------------------------------------------------------------------------
# Medical Supplies
# ---------------------------------------------------------------------------


class TestMedicalSupplies:
    def test_medical_ship_starts_with_200_supplies(self):
        _reset_medical_ship()
        assert glmed.get_supplies() == MEDICAL_SHIP_SUPPLY_MAX

    def test_non_medical_starts_with_100_supplies(self):
        _reset_non_medical()
        assert glmed.get_supplies() == 100.0

    def test_supply_max_set_correctly(self):
        _reset_medical_ship()
        state = glmed.get_medical_state()
        assert state["supplies_max"] == MEDICAL_SHIP_SUPPLY_MAX

    def test_supplies_serialise_correctly(self):
        _reset_medical_ship()
        data = glmed.serialise()
        assert data["v2"]["medical_supplies"] == MEDICAL_SHIP_SUPPLY_MAX


# ---------------------------------------------------------------------------
# Beds & Quarantine
# ---------------------------------------------------------------------------


class TestBedsAndQuarantine:
    def test_medical_ship_has_8_beds(self):
        _reset_medical_ship()
        assert glmed.get_bed_count() == 8

    def test_medical_ship_has_4_quarantine(self):
        _reset_medical_ship()
        assert glmed.get_quarantine_slots() == 4

    def test_frigate_has_4_beds(self):
        _reset_non_medical()
        assert glmed.get_bed_count() == 4

    def test_frigate_has_2_quarantine(self):
        _reset_non_medical()
        assert glmed.get_quarantine_slots() == 2

    def test_beds_by_ship_class_medical(self):
        from server.game_loop_medical_v2 import BEDS_BY_SHIP_CLASS
        assert BEDS_BY_SHIP_CLASS["medical_ship"] == 8

    def test_quarantine_by_ship_class_medical(self):
        from server.game_loop_medical_v2 import QUARANTINE_SLOTS_BY_SHIP_CLASS
        assert QUARANTINE_SLOTS_BY_SHIP_CLASS["medical_ship"] == 4


# ---------------------------------------------------------------------------
# Build State
# ---------------------------------------------------------------------------


class TestBuildState:
    def test_includes_all_flags_when_active(self):
        glms.reset(active=True)
        state = glms.build_state()
        assert state["active"] is True
        assert state["rescue_beacon"] is True
        assert state["surgical_theatre"] is True
        assert state["triage_ai"] is True

    def test_empty_when_inactive(self):
        glms.reset(active=False)
        state = glms.build_state()
        assert state == {}

    def test_state_reflects_current_flags(self):
        glms.reset(active=True)
        state = glms.build_state()
        assert state["rescue_beacon"] is True


# ---------------------------------------------------------------------------
# Save / Resume
# ---------------------------------------------------------------------------


class TestSaveResume:
    def test_round_trip(self):
        glms.reset(active=True)
        data = glms.serialise()
        glms.reset(active=False)
        assert glms.is_active() is False
        glms.deserialise(data)
        assert glms.is_active() is True

    def test_flags_preserved(self):
        glms.reset(active=True)
        data = glms.serialise()
        glms.reset(active=False)
        glms.deserialise(data)
        assert glms.is_rescue_beacon_active() is True
        assert glms.is_surgical_theatre_active() is True
        assert glms.is_triage_ai_active() is True

    def test_all_state_restored(self):
        glms.reset(active=True)
        data = glms.serialise()
        assert data["active"] is True
        assert data["rescue_beacon"] is True
        assert data["surgical_theatre"] is True
        assert data["triage_ai"] is True

    def test_beacon_state_preserved(self):
        glms.reset(active=True)
        data = glms.serialise()
        glms.reset(active=False)
        glms.deserialise(data)
        assert glms.is_rescue_beacon_active() is True


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_payload_schema_registered(self):
        from server.models.messages.base import _PAYLOAD_SCHEMAS
        assert "medical.surgical_procedure" in _PAYLOAD_SCHEMAS

    def test_surgical_theatre_supply_cost_in_injuries(self):
        assert "surgical_theatre" in TREATMENT_SUPPLY_COSTS
        assert TREATMENT_SUPPLY_COSTS["surgical_theatre"] == SURGICAL_THEATRE_SUPPLY_COST

    def test_surgical_theatre_in_puzzle_treatments(self):
        assert "surgical_theatre" in glmed.PUZZLE_TREATMENTS

    def test_debrief_includes_medical_ship_active(self):
        glms.reset(active=True)
        from server.game_debrief import compute_debrief
        result = compute_debrief([])
        assert "medical_ship_active" in result
        assert result["medical_ship_active"] is True

    def test_debrief_medical_ship_inactive(self):
        glms.reset(active=False)
        from server.game_debrief import compute_debrief
        result = compute_debrief([])
        assert result["medical_ship_active"] is False
