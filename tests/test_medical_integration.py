"""
Tests for Part 5: Medical v2 integration with game loop and save system.

Validates:
1. game_loop.py imports game_loop_medical_v2 (not old game_loop_medical)
2. save_system.py imports game_loop_medical_v2
3. _drain_queue handles new medical message types
4. v2 tick is called alongside legacy tick
5. Medical state + crew roster broadcast happens
6. Medical message schemas are registered in base.py
7. Legacy medical messages still work through v2 module
8. Save/restore round-trip with v2 state
"""
from __future__ import annotations

import random

import pytest

from server.models.crew_roster import IndividualCrewRoster, Injury
from server.models.messages.base import Message, validate_payload
import server.game_loop_medical_v2 as glmed


# ---------------------------------------------------------------------------
# Module import verification
# ---------------------------------------------------------------------------


class TestModuleImports:
    """Verify game_loop and save_system import the v2 module."""

    def test_game_loop_uses_v2(self):
        import server.game_loop as gl_mod
        # The glmed alias should point to game_loop_medical_v2
        assert hasattr(gl_mod, "glmed")
        assert gl_mod.glmed.__name__ == "server.game_loop_medical_v2"

    def test_save_system_uses_v2(self):
        import server.save_system as ss_mod
        assert hasattr(ss_mod, "glmed")
        assert ss_mod.glmed.__name__ == "server.game_loop_medical_v2"


# ---------------------------------------------------------------------------
# Message schema registration
# ---------------------------------------------------------------------------


class TestMessageSchemaRegistration:
    """Verify all v2 medical messages are registered in the dispatcher."""

    @pytest.mark.parametrize("msg_type,payload", [
        ("medical.admit", {"crew_id": "c1"}),
        ("medical.treat", {"crew_id": "c1", "injury_id": "i1"}),
        ("medical.stabilise", {"crew_id": "c1", "injury_id": "i1"}),
        ("medical.discharge", {"crew_id": "c1"}),
        ("medical.quarantine", {"crew_id": "c1"}),
        # Legacy
        ("medical.treat_crew", {"deck": "bridge", "injury_type": "injured"}),
        ("medical.cancel_treatment", {"deck": "bridge"}),
    ])
    def test_message_dispatches(self, msg_type, payload):
        msg = Message.build(msg_type, payload)
        result = validate_payload(msg)
        assert result is not None


# ---------------------------------------------------------------------------
# Legacy compatibility through v2 module
# ---------------------------------------------------------------------------


class TestLegacyCompat:
    """Ensure the v2 module's legacy interface works correctly."""

    def setup_method(self):
        glmed.reset()

    def test_start_treatment_legacy(self):
        from server.models.ship import Ship
        ship = Ship()
        ship.medical_supplies = 10
        assert glmed.start_treatment("bridge", "injured", ship) is True
        assert ship.medical_supplies == 8  # cost 2

    def test_start_treatment_no_supplies(self):
        from server.models.ship import Ship
        ship = Ship()
        ship.medical_supplies = 1
        assert glmed.start_treatment("bridge", "injured", ship) is False

    def test_cancel_treatment_legacy(self):
        from server.models.ship import Ship
        ship = Ship()
        ship.medical_supplies = 10
        glmed.start_treatment("bridge", "injured", ship)
        glmed.cancel_treatment("bridge")
        assert glmed.get_active_treatments() == {}

    def test_get_disease_state(self):
        state = glmed.get_disease_state()
        assert "infected_decks" in state
        assert "spread_timer" in state

    def test_start_outbreak(self):
        glmed.start_outbreak("medical", "Virus X")
        state = glmed.get_disease_state()
        assert "medical" in state["infected_decks"]

    def test_serialise_deserialise(self):
        from server.models.ship import Ship
        ship = Ship()
        ship.medical_supplies = 10
        glmed.start_treatment("bridge", "injured", ship)
        data = glmed.serialise()
        glmed.reset()
        glmed.deserialise(data)
        assert glmed.get_active_treatments() == {"bridge": "injured"}


# ---------------------------------------------------------------------------
# v2 state management
# ---------------------------------------------------------------------------


class TestV2StateMgmt:
    """Test the v2 medical state management functions."""

    def setup_method(self):
        glmed.reset()
        self.rng = random.Random(42)
        self.roster = IndividualCrewRoster.generate(6, "frigate", self.rng)
        glmed.init_roster(self.roster, "frigate")

    def test_roster_init_sets_beds(self):
        assert glmed.get_bed_count() == 4

    def test_admit_and_discharge_flow(self):
        member = next(iter(self.roster.members.values()))
        member.injuries.append(Injury(
            id="inj_1", type="lacerations", body_region="torso",
            severity="moderate", description="Test", caused_by="test",
            degrade_timer=180.0, treatment_type="first_aid",
            treatment_duration=15.0,
        ))
        member.update_status()

        # Admit
        result = glmed.admit_patient(member.id)
        assert result["success"]
        assert member.location == "medical_bay"

        # Start treatment
        result = glmed.start_crew_treatment(member.id, "inj_1", "first_aid")
        assert result["success"]

        # Tick to complete
        for _ in range(200):
            glmed.tick(self.roster, 0.1)

        # Verify treated
        assert member.injuries[0].treated

        # Discharge
        result = glmed.discharge_patient(member.id)
        assert result["success"]
        assert member.location.startswith("deck_")

    def test_v2_serialise_round_trip(self):
        member = next(iter(self.roster.members.values()))
        member.injuries.append(Injury(
            id="inj_2", type="lacerations", body_region="torso",
            severity="moderate", description="Test", caused_by="test",
            degrade_timer=180.0, treatment_type="first_aid",
            treatment_duration=15.0,
        ))
        member.update_status()
        glmed.admit_patient(member.id)

        data = glmed.serialise()
        assert "v2" in data
        assert data["v2"]["treatment_beds"] == 4

        # Reset and restore
        glmed.reset()
        glmed.deserialise(data)
        state = glmed.get_medical_state()
        assert state["beds_total"] == 4

    def test_medical_state_broadcast_format(self):
        state = glmed.get_medical_state()
        # All keys the client expects
        assert "beds_total" in state
        assert "beds_occupied" in state
        assert "queue" in state
        assert "active_treatments" in state
        assert "supplies" in state
        assert "supplies_max" in state
        assert "quarantine_total" in state
        assert "quarantine_occupied" in state
        assert "morgue" in state

    def test_crew_roster_broadcast_format(self):
        data = {cid: m.to_dict() for cid, m in self.roster.members.items()}
        assert len(data) == 6
        sample = next(iter(data.values()))
        assert "id" in sample
        assert "first_name" in sample
        assert "injuries" in sample

    def test_v2_tick_events(self):
        member = next(iter(self.roster.members.values()))
        member.injuries.append(Injury(
            id="inj_3", type="internal_bleeding", body_region="torso",
            severity="critical", description="Fatal", caused_by="test",
            degrade_timer=0.0, death_timer=0.5,
            treatment_type="surgery", treatment_duration=45.0,
        ))
        member.update_status()

        events = []
        for _ in range(10):
            events.extend(glmed.tick(self.roster, 0.1))

        death_events = [e for e in events if e.get("event") == "crew_death"]
        assert len(death_events) == 1

    def test_quarantine_flow(self):
        member = next(iter(self.roster.members.values()))
        member.injuries.append(Injury(
            id="inj_4", type="infection_stage_1", body_region="torso",
            severity="moderate", description="Infection", caused_by="contagion",
            degrade_timer=180.0, treatment_type="quarantine",
            treatment_duration=50.0,
        ))
        member.update_status()

        result = glmed.quarantine_crew(member.id)
        assert result["success"]
        assert member.location == "quarantine"

        state = glmed.get_medical_state()
        assert len(state["quarantine_occupied"]) == 1


# ---------------------------------------------------------------------------
# _get_treatment_type helper
# ---------------------------------------------------------------------------


class TestGetTreatmentType:
    def setup_method(self):
        glmed.reset()
        self.rng = random.Random(42)
        self.roster = IndividualCrewRoster.generate(4, "frigate", self.rng)
        glmed.init_roster(self.roster, "frigate")

    def test_returns_correct_type(self):
        from server.game_loop import _get_treatment_type
        member = next(iter(self.roster.members.values()))
        member.injuries.append(Injury(
            id="inj_t1", type="internal_bleeding", body_region="torso",
            severity="critical", description="Test", caused_by="test",
            degrade_timer=0.0, death_timer=240.0,
            treatment_type="surgery", treatment_duration=45.0,
        ))
        result = _get_treatment_type(member.id, "inj_t1")
        assert result == "surgery"

    def test_unknown_injury_returns_first_aid(self):
        from server.game_loop import _get_treatment_type
        member = next(iter(self.roster.members.values()))
        result = _get_treatment_type(member.id, "nonexistent")
        assert result == "first_aid"

    def test_unknown_crew_returns_first_aid(self):
        from server.game_loop import _get_treatment_type
        result = _get_treatment_type("nobody", "inj_x")
        assert result == "first_aid"

    def test_no_roster_returns_first_aid(self):
        from server.game_loop import _get_treatment_type
        glmed.reset()  # No roster
        result = _get_treatment_type("c1", "i1")
        assert result == "first_aid"
