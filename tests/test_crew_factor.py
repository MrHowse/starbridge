"""Tests for crew factor → system effectiveness pipeline.

Covers:
  1. Crew factor calculation (IndividualCrewRoster.crew_factor_for_duty_station)
  2. System effectiveness (ShipSystem.efficiency with _crew_factor)
  3. Per-system application (Ship.update_crew_factors with individual roster)
  4. Captain's staff / reassignment
  5. Reassignment mechanics (timer, effectiveness, max count, validation)
  6. Notifications (threshold crossing at 75/50/25%)
  7. Medical feedback loop (treatment speed scaled by medical crew factor)
  8. Serialisation round-trip (reassignment fields)
  9. Integration (crew factor broadcast + roster data flow)
"""
from __future__ import annotations

import pytest

from server.models.crew_roster import (
    CrewMember,
    Injury,
    IndividualCrewRoster,
    SYSTEM_TO_DUTY_STATION,
)
from server.models.ship import Ship, ShipSystem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_member(
    id: str = "c1",
    duty_station: str = "engines",
    status: str = "active",
    deck: int = 5,
    location: str | None = None,
    injuries: list | None = None,
) -> CrewMember:
    m = CrewMember(
        id=id,
        first_name="Test",
        surname="Crew",
        rank="Crewman",
        rank_level=1,
        deck=deck,
        duty_station=duty_station,
        status=status,
        location=location or f"deck_{deck}",
    )
    if injuries:
        m.injuries = injuries
    return m


def _make_roster(*members: CrewMember) -> IndividualCrewRoster:
    roster = IndividualCrewRoster()
    for m in members:
        roster.members[m.id] = m
    return roster


def _make_injury(severity: str = "minor", treated: bool = False) -> Injury:
    return Injury(
        id="inj1",
        type="burn",
        body_region="torso",
        severity=severity,
        description="test injury",
        caused_by="fire",
        treated=treated,
    )


# ===========================================================================
# 1. Crew factor calculation
# ===========================================================================


class TestCrewFactorCalculation:
    """crew_factor_for_duty_station basic calculation."""

    def test_all_active_returns_one(self):
        r = _make_roster(
            _make_member("c1", "engines"),
            _make_member("c2", "engines"),
        )
        assert r.crew_factor_for_duty_station("engines") == pytest.approx(1.0)

    def test_empty_station_returns_one(self):
        r = _make_roster(_make_member("c1", "sensors"))
        assert r.crew_factor_for_duty_station("engines") == 1.0

    def test_one_dead_of_two(self):
        r = _make_roster(
            _make_member("c1", "engines", status="active"),
            _make_member("c2", "engines", status="dead"),
        )
        assert r.crew_factor_for_duty_station("engines") == pytest.approx(0.5)

    def test_all_dead_returns_zero(self):
        r = _make_roster(
            _make_member("c1", "engines", status="dead"),
            _make_member("c2", "engines", status="dead"),
        )
        assert r.crew_factor_for_duty_station("engines") == pytest.approx(0.0)

    def test_injured_counts_at_half(self):
        m = _make_member("c1", "engines", status="injured")
        m.injuries = [_make_injury("minor")]
        r = _make_roster(m)
        assert r.crew_factor_for_duty_station("engines") == pytest.approx(0.5)

    def test_crew_in_medical_bay_not_counted(self):
        r = _make_roster(
            _make_member("c1", "engines", location="medical_bay"),
            _make_member("c2", "engines"),
        )
        assert r.crew_factor_for_duty_station("engines") == pytest.approx(0.5)

    def test_crew_in_quarantine_not_counted(self):
        r = _make_roster(
            _make_member("c1", "engines", location="quarantine"),
            _make_member("c2", "engines"),
        )
        assert r.crew_factor_for_duty_station("engines") == pytest.approx(0.5)

    def test_mixed_crew_factor(self):
        """2 active + 1 injured + 1 dead = (2 + 0.5 + 0) / 4 = 0.625."""
        m_inj = _make_member("c3", "engines", status="injured")
        m_inj.injuries = [_make_injury("serious")]
        r = _make_roster(
            _make_member("c1", "engines"),
            _make_member("c2", "engines"),
            m_inj,
            _make_member("c4", "engines", status="dead"),
        )
        assert r.crew_factor_for_duty_station("engines") == pytest.approx(0.625)


# ===========================================================================
# 2. System effectiveness
# ===========================================================================


class TestSystemEfficiency:
    """ShipSystem.efficiency with _crew_factor."""

    def test_full_crew_full_power_full_health(self):
        s = ShipSystem("engines")
        s._crew_factor = 1.0
        assert s.efficiency == pytest.approx(1.0)

    def test_half_crew_factor(self):
        s = ShipSystem("engines")
        s._crew_factor = 0.5
        assert s.efficiency == pytest.approx(0.5)

    def test_crew_factor_with_overclocked_power(self):
        s = ShipSystem("engines", power=150.0)
        s._crew_factor = 1.0
        assert s.efficiency == pytest.approx(1.5)

    def test_crew_factor_with_damaged_health(self):
        s = ShipSystem("engines", health=50.0)
        s._crew_factor = 0.8
        assert s.efficiency == pytest.approx(0.4)

    def test_zero_crew_factor(self):
        s = ShipSystem("engines")
        s._crew_factor = 0.0
        assert s.efficiency == pytest.approx(0.0)

    def test_captain_offline_overrides_crew_factor(self):
        s = ShipSystem("engines")
        s._crew_factor = 1.0
        s._captain_offline = True
        assert s.efficiency == 0.0


# ===========================================================================
# 3. Per-system application (Ship.update_crew_factors)
# ===========================================================================


class TestUpdateCrewFactors:
    """Ship.update_crew_factors with IndividualCrewRoster."""

    def test_individual_roster_sets_factors(self):
        r = _make_roster(
            _make_member("c1", "engines"),
            _make_member("c2", "sensors"),
        )
        ship = Ship()
        ship.update_crew_factors(individual_roster=r)
        assert ship.systems["engines"]._crew_factor == pytest.approx(1.0)
        assert ship.systems["sensors"]._crew_factor == pytest.approx(1.0)

    def test_minimum_floor_10_percent(self):
        """Even if all crew dead, system gets 10% minimum."""
        r = _make_roster(
            _make_member("c1", "engines", status="dead"),
        )
        ship = Ship()
        ship.update_crew_factors(individual_roster=r)
        assert ship.systems["engines"]._crew_factor == pytest.approx(0.10)

    def test_no_roster_uses_legacy(self):
        """Without individual roster, falls back to deck-level factors."""
        ship = Ship()
        ship.update_crew_factors(individual_roster=None)
        # Legacy default = 1.0 for all systems (default CrewRoster)
        for sys_obj in ship.systems.values():
            assert sys_obj._crew_factor == pytest.approx(1.0)

    def test_system_mapping_ecm_uses_sensors(self):
        """ecm_suite maps to sensors duty station."""
        assert SYSTEM_TO_DUTY_STATION["ecm_suite"] == "sensors"
        r = _make_roster(
            _make_member("c1", "sensors"),
            _make_member("c2", "sensors", status="dead"),
        )
        ship = Ship()
        ship.update_crew_factors(individual_roster=r)
        # sensors and ecm_suite should have the same factor
        assert ship.systems["sensors"]._crew_factor == ship.systems["ecm_suite"]._crew_factor

    def test_system_mapping_point_defence_uses_shields(self):
        assert SYSTEM_TO_DUTY_STATION["point_defence"] == "shields"

    def test_system_mapping_flight_deck_uses_manoeuvring(self):
        assert SYSTEM_TO_DUTY_STATION["flight_deck"] == "manoeuvring"

    def test_all_systems_get_factors(self):
        """All 9 systems should have non-default factors after update."""
        r = _make_roster(
            _make_member("c1", "engines"),
            _make_member("c2", "sensors"),
            _make_member("c3", "beams"),
            _make_member("c4", "torpedoes"),
            _make_member("c5", "shields"),
            _make_member("c6", "manoeuvring", deck=1),
        )
        ship = Ship()
        ship.update_crew_factors(individual_roster=r)
        for sys_name, sys_obj in ship.systems.items():
            assert sys_obj._crew_factor >= 0.10


# ===========================================================================
# 4. Crew factor for duty station (via crew_factor_for_system)
# ===========================================================================


class TestCrewFactorForSystem:
    """crew_factor_for_system delegates correctly."""

    def test_engines_maps_to_engines_station(self):
        r = _make_roster(_make_member("c1", "engines"))
        assert r.crew_factor_for_system("engines") == pytest.approx(1.0)

    def test_unmapped_system_returns_one(self):
        r = _make_roster(_make_member("c1", "engines"))
        assert r.crew_factor_for_system("nonexistent_system") == 1.0

    def test_medical_bay_crew_factor(self):
        """Medical bay is a duty station, accessible via crew_factor_for_duty_station."""
        r = _make_roster(
            _make_member("c1", "medical_bay", deck=4),
            _make_member("c2", "medical_bay", deck=4),
        )
        assert r.crew_factor_for_duty_station("medical_bay") == pytest.approx(1.0)

    def test_medical_bay_half_dead(self):
        r = _make_roster(
            _make_member("c1", "medical_bay", deck=4),
            _make_member("c2", "medical_bay", deck=4, status="dead"),
        )
        assert r.crew_factor_for_duty_station("medical_bay") == pytest.approx(0.5)


# ===========================================================================
# 5. Reassignment mechanics
# ===========================================================================


class TestReassignment:
    """IndividualCrewRoster.reassign_crew mechanics."""

    def test_basic_reassignment(self):
        r = _make_roster(_make_member("c1", "engines"))
        result = r.reassign_crew("c1", "sensors")
        assert result["ok"] is True
        assert r.members["c1"].duty_station == "sensors"
        assert r.members["c1"].original_duty_station == "engines"
        assert r.members["c1"].reassignment_timer == 30.0
        assert r.members["c1"].reassignment_effectiveness == pytest.approx(0.6)

    def test_reassignment_count_increments(self):
        r = _make_roster(_make_member("c1", "engines"))
        r.reassign_crew("c1", "sensors")
        assert r.members["c1"].reassignment_count == 1

    def test_max_reassignments_rejected(self):
        r = _make_roster(_make_member("c1", "engines"))
        r.members["c1"].reassignment_count = 2
        result = r.reassign_crew("c1", "sensors")
        assert result["ok"] is False
        assert "Maximum" in result["error"]

    def test_dead_crew_rejected(self):
        r = _make_roster(_make_member("c1", "engines", status="dead"))
        result = r.reassign_crew("c1", "sensors")
        assert result["ok"] is False
        assert "dead" in result["error"].lower()

    def test_medical_bay_crew_rejected(self):
        r = _make_roster(_make_member("c1", "engines", location="medical_bay"))
        result = r.reassign_crew("c1", "sensors")
        assert result["ok"] is False
        assert "medical" in result["error"].lower()

    def test_same_station_rejected(self):
        r = _make_roster(_make_member("c1", "engines"))
        result = r.reassign_crew("c1", "engines")
        assert result["ok"] is False
        assert "Already" in result["error"]

    def test_nonexistent_crew_rejected(self):
        r = _make_roster(_make_member("c1", "engines"))
        result = r.reassign_crew("nonexistent", "sensors")
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_in_transition_rejected(self):
        r = _make_roster(_make_member("c1", "engines"))
        r.members["c1"].reassignment_timer = 15.0
        result = r.reassign_crew("c1", "sensors")
        assert result["ok"] is False
        assert "transition" in result["error"].lower()

    def test_return_to_original_restores_effectiveness(self):
        r = _make_roster(_make_member("c1", "engines"))
        r.reassign_crew("c1", "sensors")
        r.members["c1"].reassignment_timer = 0.0  # skip transition
        r.reassign_crew("c1", "engines")
        assert r.members["c1"].reassignment_effectiveness == pytest.approx(1.0)
        assert r.members["c1"].original_duty_station is None

    def test_transition_timer_prevents_contribution(self):
        """Crew member with active timer doesn't contribute to crew factor."""
        r = _make_roster(
            _make_member("c1", "engines"),
            _make_member("c2", "engines"),
        )
        r.reassign_crew("c1", "sensors")
        # c1 now at sensors with timer > 0 — no effective contribution (0/1 = 0)
        assert r.crew_factor_for_duty_station("sensors") == pytest.approx(0.0)
        # engines only has c2 now (fully effective)
        assert r.crew_factor_for_duty_station("engines") == pytest.approx(1.0)

    def test_reassigned_crew_reduced_effectiveness(self):
        """After timer expires, reassigned crew contributes at 60%."""
        m = _make_member("c1", "engines")
        r = _make_roster(m)
        r.reassign_crew("c1", "sensors")
        m.reassignment_timer = 0.0  # timer expired
        # Now the only person at sensors, contributing at 0.6
        assert r.crew_factor_for_duty_station("sensors") == pytest.approx(0.6)


# ===========================================================================
# 6. Reassignment timer tick
# ===========================================================================


class TestReassignmentTimer:
    """tick_reassignments decrements timer and generates events."""

    def test_timer_decrements(self):
        r = _make_roster(_make_member("c1", "engines"))
        r.reassign_crew("c1", "sensors")
        r.tick_reassignments(10.0)
        assert r.members["c1"].reassignment_timer == pytest.approx(20.0)

    def test_timer_completes(self):
        r = _make_roster(_make_member("c1", "engines"))
        r.reassign_crew("c1", "sensors")
        events = r.tick_reassignments(30.0)
        assert len(events) == 1
        assert events[0]["event"] == "reassignment_complete"
        assert events[0]["crew_id"] == "c1"
        assert r.members["c1"].reassignment_timer == 0.0

    def test_timer_does_not_go_negative(self):
        r = _make_roster(_make_member("c1", "engines"))
        r.reassign_crew("c1", "sensors")
        r.tick_reassignments(100.0)
        assert r.members["c1"].reassignment_timer == 0.0

    def test_no_events_when_no_timers(self):
        r = _make_roster(_make_member("c1", "engines"))
        events = r.tick_reassignments(1.0)
        assert events == []


# ===========================================================================
# 7. Notifications (threshold crossing)
# ===========================================================================


class TestThresholdNotifications:
    """_check_crew_factor_thresholds detects crossings."""

    def test_drop_below_75(self):
        from server.game_loop import _check_crew_factor_thresholds, _prev_crew_factors
        _prev_crew_factors.clear()
        ship = Ship()
        ship.systems["engines"]._crew_factor = 0.70
        events = _check_crew_factor_thresholds(ship)
        engine_events = [e for e in events if e["system"] == "engines"]
        assert len(engine_events) == 1
        assert engine_events[0]["threshold"] == 0.75
        assert engine_events[0]["level"] == "caution"

    def test_drop_below_50(self):
        from server.game_loop import _check_crew_factor_thresholds, _prev_crew_factors
        _prev_crew_factors.clear()
        ship = Ship()
        ship.systems["engines"]._crew_factor = 0.40
        events = _check_crew_factor_thresholds(ship)
        engine_events = [e for e in events if e["system"] == "engines"]
        # Should cross both 75 and 50
        thresholds = {e["threshold"] for e in engine_events}
        assert 0.75 in thresholds
        assert 0.50 in thresholds

    def test_drop_below_25(self):
        from server.game_loop import _check_crew_factor_thresholds, _prev_crew_factors
        _prev_crew_factors.clear()
        ship = Ship()
        ship.systems["engines"]._crew_factor = 0.20
        events = _check_crew_factor_thresholds(ship)
        engine_events = [e for e in events if e["system"] == "engines"]
        thresholds = {e["threshold"] for e in engine_events}
        assert 0.25 in thresholds
        crit = [e for e in engine_events if e["threshold"] == 0.25]
        assert crit[0]["level"] == "critical"

    def test_recovery_above_threshold(self):
        from server.game_loop import _check_crew_factor_thresholds, _prev_crew_factors
        _prev_crew_factors.clear()
        ship = Ship()
        # First, drop below 75
        ship.systems["engines"]._crew_factor = 0.50
        _check_crew_factor_thresholds(ship)
        # Now recover above 75
        ship.systems["engines"]._crew_factor = 0.80
        events = _check_crew_factor_thresholds(ship)
        engine_events = [e for e in events if e["system"] == "engines"]
        recovery = [e for e in engine_events if e["level"] == "recovery"]
        assert len(recovery) >= 1

    def test_no_event_when_stable(self):
        from server.game_loop import _check_crew_factor_thresholds, _prev_crew_factors
        _prev_crew_factors.clear()
        ship = Ship()
        ship.systems["engines"]._crew_factor = 0.80
        _check_crew_factor_thresholds(ship)
        # Same value — no crossing
        events = _check_crew_factor_thresholds(ship)
        engine_events = [e for e in events if e["system"] == "engines"]
        assert len(engine_events) == 0

    def test_threshold_events_include_roles(self):
        from server.game_loop import _check_crew_factor_thresholds, _prev_crew_factors
        _prev_crew_factors.clear()
        ship = Ship()
        ship.systems["beams"]._crew_factor = 0.70
        events = _check_crew_factor_thresholds(ship)
        beam_events = [e for e in events if e["system"] == "beams"]
        assert "weapons" in beam_events[0]["roles"]
        assert "captain" in beam_events[0]["roles"]


# ===========================================================================
# 8. Medical feedback loop
# ===========================================================================


class TestMedicalFeedbackLoop:
    """Medical crew factor scales treatment speed."""

    def test_full_medical_crew_normal_speed(self):
        r = _make_roster(
            _make_member("c1", "medical_bay", deck=4),
            _make_member("c2", "medical_bay", deck=4),
        )
        med_factor = max(r.crew_factor_for_duty_station("medical_bay"), 0.10)
        assert med_factor == pytest.approx(1.0)

    def test_half_medical_crew_half_speed(self):
        r = _make_roster(
            _make_member("c1", "medical_bay", deck=4),
            _make_member("c2", "medical_bay", deck=4, status="dead"),
        )
        med_factor = max(r.crew_factor_for_duty_station("medical_bay"), 0.10)
        assert med_factor == pytest.approx(0.5)

    def test_no_medical_crew_minimum_floor(self):
        r = _make_roster(
            _make_member("c1", "medical_bay", deck=4, status="dead"),
        )
        med_factor = max(r.crew_factor_for_duty_station("medical_bay"), 0.10)
        assert med_factor == pytest.approx(0.10)


# ===========================================================================
# 9. Serialisation round-trip
# ===========================================================================


class TestSerialisation:
    """Reassignment fields survive serialise/deserialise."""

    def test_member_round_trip_no_reassignment(self):
        m = _make_member("c1", "engines")
        d = m.to_dict()
        m2 = CrewMember.from_dict(d)
        assert m2.original_duty_station is None
        assert m2.reassignment_count == 0
        assert m2.reassignment_timer == 0.0
        assert m2.reassignment_effectiveness == 1.0

    def test_member_round_trip_with_reassignment(self):
        m = _make_member("c1", "engines")
        m.original_duty_station = "engines"
        m.reassignment_count = 1
        m.reassignment_timer = 15.5
        m.reassignment_effectiveness = 0.6
        m.duty_station = "sensors"
        d = m.to_dict()
        assert "original_duty_station" in d
        m2 = CrewMember.from_dict(d)
        assert m2.original_duty_station == "engines"
        assert m2.reassignment_count == 1
        assert m2.reassignment_timer == pytest.approx(15.5)
        assert m2.reassignment_effectiveness == pytest.approx(0.6)
        assert m2.duty_station == "sensors"

    def test_no_reassignment_fields_omitted_in_dict(self):
        """When not reassigned, reassignment fields should be absent from dict."""
        m = _make_member("c1", "engines")
        d = m.to_dict()
        assert "original_duty_station" not in d
        assert "reassignment_count" not in d

    def test_roster_serialise_round_trip(self):
        r = _make_roster(
            _make_member("c1", "engines"),
            _make_member("c2", "sensors"),
        )
        r.reassign_crew("c1", "sensors")
        data = r.serialise()
        r2 = IndividualCrewRoster.deserialise(data)
        assert r2.members["c1"].duty_station == "sensors"
        assert r2.members["c1"].original_duty_station == "engines"
        assert r2.members["c1"].reassignment_count == 1


# ===========================================================================
# 10. Message payload validation
# ===========================================================================


class TestMessagePayload:
    """CaptainReassignCrewPayload validation."""

    def test_valid_payload(self):
        from server.models.messages import CaptainReassignCrewPayload
        p = CaptainReassignCrewPayload(crew_id="c1", new_duty_station="sensors")
        assert p.crew_id == "c1"
        assert p.new_duty_station == "sensors"

    def test_payload_in_dispatch_map(self):
        from server.models.messages.base import _PAYLOAD_SCHEMAS
        assert "captain.reassign_crew" in _PAYLOAD_SCHEMAS
