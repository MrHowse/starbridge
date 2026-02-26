"""Tests for Carrier Flight Control Centre (v0.07 §2.6).

Covers: module activation, squadron management, CAP zones, scramble,
turnaround speed, recovery slots, build state, save/resume, integration.
"""
from __future__ import annotations

import pytest
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import server.game_loop_carrier_ops as glcar
import server.game_loop_flight_ops as glfo
from server.game_loop_carrier_ops import (
    CAP_FUEL_RTB_THRESHOLD,
    CAP_ZONE_MAX_DRONES,
    CAP_ZONE_MIN_DRONES,
    MAX_SQUADRON_SIZE,
    MAX_SQUADRONS,
    SCRAMBLE_LAUNCH_INTERVAL,
    Squadron,
    CAPZone,
)
from server.models.flight_deck import (
    FlightDeck,
    TurnaroundState,
    create_flight_deck,
    serialise_flight_deck,
    deserialise_flight_deck,
    REFUEL_TIME,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeShip:
    x: float = 0.0
    y: float = 0.0
    heading: float = 0.0


def _reset_carrier():
    """Reset both flight ops and carrier ops for carrier class."""
    glfo.reset("carrier")
    glcar.reset(active=True)


def _reset_non_carrier():
    """Reset for a non-carrier ship."""
    glfo.reset("frigate")
    glcar.reset(active=False)


# ---------------------------------------------------------------------------
# Module Activation
# ---------------------------------------------------------------------------


class TestModuleActivation:
    def test_active_for_carrier(self):
        _reset_carrier()
        assert glcar.is_active() is True

    def test_inactive_for_non_carrier(self):
        _reset_non_carrier()
        assert glcar.is_active() is False

    def test_reset_clears_state(self):
        _reset_carrier()
        glcar.create_squadron("Alpha", [glfo.get_drones()[0].id])
        glcar.reset(active=True)
        assert glcar.get_squadrons() == {}
        assert glcar.get_cap_zone() is None
        assert glcar.get_scramble_active() is False


# ---------------------------------------------------------------------------
# Squadron Management
# ---------------------------------------------------------------------------


class TestSquadronManagement:
    def test_create_squadron_ok(self):
        _reset_carrier()
        drones = glfo.get_drones()
        result = glcar.create_squadron("Alpha", [drones[0].id, drones[1].id])
        assert result["ok"] is True
        assert "squadron_id" in result
        assert len(glcar.get_squadrons()) == 1

    def test_create_squadron_not_active(self):
        _reset_non_carrier()
        result = glcar.create_squadron("Alpha", ["drone_s1"])
        assert result["ok"] is False
        assert "not available" in result["error"]

    def test_create_squadron_too_many_drones(self):
        _reset_carrier()
        drones = glfo.get_drones()
        # Try to create with more than MAX_SQUADRON_SIZE drones
        ids = [d.id for d in drones[:MAX_SQUADRON_SIZE + 1]] if len(drones) > MAX_SQUADRON_SIZE else []
        if ids:
            result = glcar.create_squadron("Big", ids)
            assert result["ok"] is False

    def test_create_squadron_invalid_drone(self):
        _reset_carrier()
        result = glcar.create_squadron("Bad", ["nonexistent_drone"])
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_disband_squadron(self):
        _reset_carrier()
        drones = glfo.get_drones()
        res = glcar.create_squadron("Alpha", [drones[0].id])
        sq_id = res["squadron_id"]
        result = glcar.disband_squadron(sq_id)
        assert result["ok"] is True
        assert len(glcar.get_squadrons()) == 0

    def test_disband_nonexistent(self):
        _reset_carrier()
        result = glcar.disband_squadron("sq-999")
        assert result["ok"] is False

    def test_squadron_order_recall(self):
        _reset_carrier()
        ship = FakeShip()
        drones = glfo.get_drones()
        # Launch two drones manually.
        d0, d1 = drones[0], drones[1]
        d0.status = "active"
        d1.status = "active"
        res = glcar.create_squadron("Alpha", [d0.id, d1.id])
        sq_id = res["squadron_id"]
        result = glcar.squadron_order(sq_id, "recall")
        assert result["ok"] is True
        # Both drones should have been recalled (ai_behaviour = "rtb").
        assert d0.ai_behaviour == "rtb"
        assert d1.ai_behaviour == "rtb"

    def test_squadron_order_launch(self):
        _reset_carrier()
        ship = FakeShip()
        drones = glfo.get_drones()
        d0, d1 = drones[0], drones[1]
        assert d0.status == "hangar"
        assert d1.status == "hangar"
        res = glcar.create_squadron("Alpha", [d0.id, d1.id])
        sq_id = res["squadron_id"]
        result = glcar.squadron_order(sq_id, "launch", ship=ship)
        assert result["ok"] is True
        # Drones should be in launching state.
        assert d0.status == "launching"
        assert d1.status == "launching"

    def test_max_squadrons(self):
        _reset_carrier()
        drones = glfo.get_drones()
        for i in range(MAX_SQUADRONS):
            res = glcar.create_squadron(f"Sq{i}", [drones[i % len(drones)].id])
            assert res["ok"] is True
        # One more should fail.
        result = glcar.create_squadron("Extra", [drones[0].id])
        assert result["ok"] is False
        assert "Maximum" in result["error"]


# ---------------------------------------------------------------------------
# CAP Zone
# ---------------------------------------------------------------------------


class TestCAPZone:
    def test_set_cap_zone_ok(self):
        _reset_carrier()
        drones = glfo.get_drones()
        d0, d1 = drones[0], drones[1]
        d0.status = "active"
        d1.status = "active"
        result = glcar.set_cap_zone(10000.0, 20000.0, 5000.0, [d0.id, d1.id])
        assert result["ok"] is True
        cap = glcar.get_cap_zone()
        assert cap is not None
        assert cap.centre_x == 10000.0
        assert len(cap.assigned_drone_ids) == 2

    def test_set_cap_too_few_drones(self):
        _reset_carrier()
        drones = glfo.get_drones()
        d0 = drones[0]
        d0.status = "active"
        result = glcar.set_cap_zone(0.0, 0.0, 5000.0, [d0.id])
        assert result["ok"] is False
        assert str(CAP_ZONE_MIN_DRONES) in result["error"]

    def test_set_cap_too_many_drones(self):
        _reset_carrier()
        drones = glfo.get_drones()
        ids = []
        for i in range(CAP_ZONE_MAX_DRONES + 1):
            drones[i].status = "active"
            ids.append(drones[i].id)
        result = glcar.set_cap_zone(0.0, 0.0, 5000.0, ids)
        assert result["ok"] is False

    def test_set_cap_not_active(self):
        _reset_non_carrier()
        result = glcar.set_cap_zone(0.0, 0.0, 5000.0, ["d1", "d2"])
        assert result["ok"] is False

    def test_cap_drone_low_fuel_triggers_rtb(self):
        _reset_carrier()
        ship = FakeShip()
        drones = glfo.get_drones()
        d0, d1 = drones[0], drones[1]
        d0.status = "active"
        d0.fuel = CAP_FUEL_RTB_THRESHOLD - 1.0  # Below threshold
        d1.status = "active"
        d1.fuel = 100.0
        glcar.set_cap_zone(0.0, 0.0, 5000.0, [d0.id, d1.id])
        events = glcar.tick(ship, 0.1)
        rotating_events = [e for e in events if e["type"] == "cap_drone_rotating"]
        assert len(rotating_events) == 1
        assert rotating_events[0]["drone_id"] == d0.id

    def test_cap_drone_relaunch_from_hangar(self):
        _reset_carrier()
        ship = FakeShip()
        drones = glfo.get_drones()
        d0, d1 = drones[0], drones[1]
        d0.status = "hangar"  # Back in hangar after turnaround
        d1.status = "active"
        d1.fuel = 100.0
        glcar.set_cap_zone(0.0, 0.0, 5000.0, [d0.id, d1.id])
        events = glcar.tick(ship, 0.1)
        relaunch_events = [e for e in events if e["type"] == "cap_drone_relaunched"]
        assert len(relaunch_events) == 1
        assert relaunch_events[0]["drone_id"] == d0.id
        # Drone should now be launching.
        assert d0.status == "launching"

    def test_cancel_cap(self):
        _reset_carrier()
        drones = glfo.get_drones()
        d0, d1 = drones[0], drones[1]
        d0.status = "active"
        d1.status = "active"
        glcar.set_cap_zone(0.0, 0.0, 5000.0, [d0.id, d1.id])
        result = glcar.cancel_cap()
        assert result["ok"] is True
        assert glcar.get_cap_zone() is None

    def test_cancel_cap_no_zone(self):
        _reset_carrier()
        result = glcar.cancel_cap()
        assert result["ok"] is False

    def test_cap_zone_in_build_state(self):
        _reset_carrier()
        drones = glfo.get_drones()
        d0, d1 = drones[0], drones[1]
        d0.status = "active"
        d1.status = "active"
        glcar.set_cap_zone(10000.0, 20000.0, 5000.0, [d0.id, d1.id])
        state = glcar.build_state()
        assert state["cap_zone"] is not None
        assert state["cap_zone"]["centre_x"] == 10000.0

    def test_cap_zone_serialise_roundtrip(self):
        _reset_carrier()
        drones = glfo.get_drones()
        d0, d1 = drones[0], drones[1]
        d0.status = "active"
        d1.status = "active"
        glcar.set_cap_zone(10000.0, 20000.0, 5000.0, [d0.id, d1.id])
        data = glcar.serialise()
        glcar.reset(active=True)
        assert glcar.get_cap_zone() is None
        glcar.deserialise(data)
        cap = glcar.get_cap_zone()
        assert cap is not None
        assert cap.centre_x == 10000.0
        assert len(cap.assigned_drone_ids) == 2


# ---------------------------------------------------------------------------
# Scramble
# ---------------------------------------------------------------------------


class TestScramble:
    def test_scramble_queues_all_hangar_drones(self):
        _reset_carrier()
        ship = FakeShip()
        hangar_count = sum(1 for d in glfo.get_drones() if d.status == "hangar")
        result = glcar.scramble(ship)
        assert result["ok"] is True
        assert result["queued"] == hangar_count
        assert glcar.get_scramble_active() is True

    def test_scramble_not_active(self):
        _reset_non_carrier()
        ship = FakeShip()
        result = glcar.scramble(ship)
        assert result["ok"] is False

    def test_scramble_launches_at_intervals(self):
        _reset_carrier()
        ship = FakeShip()
        glcar.scramble(ship)
        # First drone launches immediately (timer starts at 0).
        events = glcar.tick(ship, 0.1)
        scramble_launches = [e for e in events if e["type"] == "scramble_launch"]
        assert len(scramble_launches) >= 1

    def test_scramble_no_ready_drones(self):
        _reset_carrier()
        ship = FakeShip()
        # Mark all drones as non-hangar.
        for d in glfo.get_drones():
            d.status = "active"
        result = glcar.scramble(ship)
        assert result["ok"] is False

    def test_cancel_scramble(self):
        _reset_carrier()
        ship = FakeShip()
        glcar.scramble(ship)
        result = glcar.cancel_scramble()
        assert result["ok"] is True
        assert glcar.get_scramble_active() is False

    def test_scramble_completes_when_queue_empty(self):
        _reset_carrier()
        ship = FakeShip()
        glcar.scramble(ship)
        # Tick enough to drain the entire queue.
        total_drones = sum(1 for d in glfo.get_drones() if d.status in ("hangar", "launching"))
        for _ in range(total_drones * 100):
            glcar.tick(ship, SCRAMBLE_LAUNCH_INTERVAL + 0.1)
        assert glcar.get_scramble_active() is False

    def test_scramble_uses_reduced_launch_time(self):
        _reset_carrier()
        ship = FakeShip()
        glcar.scramble(ship)
        # scramble_mode should be active in flight ops.
        assert glfo.get_scramble_mode() is True

    def test_scramble_idempotent(self):
        _reset_carrier()
        ship = FakeShip()
        glcar.scramble(ship)
        result = glcar.scramble(ship)
        assert result["ok"] is False
        assert "already in progress" in result["error"]


# ---------------------------------------------------------------------------
# Turnaround Speed
# ---------------------------------------------------------------------------


class TestTurnaroundSpeed:
    def test_carrier_turnaround_multiplier(self):
        fd = create_flight_deck("carrier")
        assert fd.turnaround_multiplier == 0.5

    def test_non_carrier_turnaround_multiplier(self):
        fd = create_flight_deck("frigate")
        assert fd.turnaround_multiplier == 1.0

    def test_carrier_turnaround_completes_in_half_time(self):
        fd = create_flight_deck("carrier")
        # Add a turnaround that needs refuel only (15s normally).
        fd.turnarounds["d1"] = TurnaroundState(
            drone_id="d1",
            needs_refuel=True,
            refuel_remaining=REFUEL_TIME,
            total_remaining=REFUEL_TIME,
        )
        # Tick for 8 seconds (> half of 15s) — should complete with 0.5 multiplier.
        for _ in range(80):
            fd.tick(0.1)
        assert fd.turnarounds.get("d1") is None or fd.turnarounds["d1"].total_remaining <= 1e-6

    def test_non_carrier_turnaround_normal_time(self):
        fd = create_flight_deck("frigate")
        fd.turnarounds["d1"] = TurnaroundState(
            drone_id="d1",
            needs_refuel=True,
            refuel_remaining=REFUEL_TIME,
            total_remaining=REFUEL_TIME,
        )
        # Tick for 7.5 seconds — should NOT be complete with 1.0 multiplier.
        for _ in range(75):
            fd.tick(0.1)
        ta = fd.turnarounds.get("d1")
        assert ta is not None
        assert ta.total_remaining > 0

    def test_turnaround_multiplier_serialise_roundtrip(self):
        fd = create_flight_deck("carrier")
        data = serialise_flight_deck(fd)
        fd2 = deserialise_flight_deck(data)
        assert fd2.turnaround_multiplier == 0.5


# ---------------------------------------------------------------------------
# Recovery Slots
# ---------------------------------------------------------------------------


class TestRecoverySlots:
    def test_carrier_has_two_recovery_slots(self):
        fd = create_flight_deck("carrier")
        assert fd.recovery_slots == 2

    def test_carrier_can_recover_two_simultaneously(self):
        fd = create_flight_deck("carrier")
        fd.queue_recovery("d1")
        fd.queue_recovery("d2")
        assert fd.clear_to_land("d1") is True
        assert fd.clear_to_land("d2") is True
        assert len(fd.recovery_in_progress) == 2

    def test_non_carrier_has_one_recovery_slot(self):
        fd = create_flight_deck("scout")
        assert fd.recovery_slots == 1


# ---------------------------------------------------------------------------
# Build State
# ---------------------------------------------------------------------------


class TestBuildState:
    def test_includes_all_fields_when_active(self):
        _reset_carrier()
        state = glcar.build_state()
        assert state["active"] is True
        assert "squadrons" in state
        assert "cap_zone" in state
        assert "scramble_active" in state

    def test_inactive_state(self):
        _reset_non_carrier()
        state = glcar.build_state()
        assert state["active"] is False

    def test_all_fields_populated(self):
        _reset_carrier()
        drones = glfo.get_drones()
        glcar.create_squadron("Alpha", [drones[0].id])
        state = glcar.build_state()
        assert len(state["squadrons"]) == 1
        sq_id = list(state["squadrons"].keys())[0]
        assert state["squadrons"][sq_id]["name"] == "Alpha"


# ---------------------------------------------------------------------------
# Save/Resume
# ---------------------------------------------------------------------------


class TestSaveResume:
    def test_carrier_ops_roundtrip(self):
        _reset_carrier()
        drones = glfo.get_drones()
        glcar.create_squadron("Alpha", [drones[0].id, drones[1].id])
        data = glcar.serialise()
        glcar.reset(active=True)
        glcar.deserialise(data)
        assert glcar.is_active() is True
        assert len(glcar.get_squadrons()) == 1

    def test_squadrons_preserved(self):
        _reset_carrier()
        drones = glfo.get_drones()
        glcar.create_squadron("Bravo", [drones[2].id])
        data = glcar.serialise()
        glcar.reset(active=True)
        glcar.deserialise(data)
        sqs = glcar.get_squadrons()
        assert len(sqs) == 1
        sq = list(sqs.values())[0]
        assert sq.name == "Bravo"

    def test_cap_zone_preserved(self):
        _reset_carrier()
        drones = glfo.get_drones()
        d0, d1 = drones[0], drones[1]
        d0.status = "active"
        d1.status = "active"
        glcar.set_cap_zone(5000.0, 6000.0, 3000.0, [d0.id, d1.id])
        data = glcar.serialise()
        glcar.reset(active=True)
        glcar.deserialise(data)
        cap = glcar.get_cap_zone()
        assert cap is not None
        assert cap.centre_x == 5000.0
        assert cap.radius == 3000.0

    def test_scramble_state_preserved(self):
        _reset_carrier()
        ship = FakeShip()
        glcar.scramble(ship)
        data = glcar.serialise()
        assert data["scramble_active"] is True
        assert len(data["scramble_queue"]) > 0


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_payload_schemas_registered(self):
        from server.models.messages.base import _PAYLOAD_SCHEMAS
        carrier_types = [
            "carrier.create_squadron",
            "carrier.disband_squadron",
            "carrier.squadron_order",
            "carrier.set_cap",
            "carrier.cancel_cap",
            "carrier.scramble",
            "carrier.cancel_scramble",
        ]
        for mt in carrier_types:
            assert mt in _PAYLOAD_SCHEMAS, f"Missing schema for {mt}"

    def test_create_squadron_in_build_state(self):
        _reset_carrier()
        drones = glfo.get_drones()
        glcar.create_squadron("Delta", [drones[0].id])
        state = glcar.build_state()
        assert len(state["squadrons"]) == 1

    def test_scramble_launches_drones(self):
        _reset_carrier()
        ship = FakeShip()
        hangar_before = sum(1 for d in glfo.get_drones() if d.status == "hangar")
        glcar.scramble(ship)
        # Tick to launch first batch.
        events = glcar.tick(ship, 0.1)
        scramble_launches = [e for e in events if e["type"] == "scramble_launch"]
        assert len(scramble_launches) >= 1

    def test_cap_fuel_rotation_triggers_recall(self):
        _reset_carrier()
        ship = FakeShip()
        drones = glfo.get_drones()
        d0, d1 = drones[0], drones[1]
        d0.status = "active"
        d0.fuel = CAP_FUEL_RTB_THRESHOLD - 5.0
        d1.status = "active"
        d1.fuel = 100.0
        glcar.set_cap_zone(0.0, 0.0, 5000.0, [d0.id, d1.id])
        events = glcar.tick(ship, 0.1)
        assert any(e["type"] == "cap_drone_rotating" for e in events)

    def test_carrier_state_includes_all_data(self):
        _reset_carrier()
        drones = glfo.get_drones()
        glcar.create_squadron("Echo", [drones[0].id])
        state = glcar.build_state()
        assert state["active"] is True
        assert state["scramble_active"] is False
        assert state["cap_zone"] is None
        assert "Echo" in [s["name"] for s in state["squadrons"].values()]
