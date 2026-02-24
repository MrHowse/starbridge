"""Tests for ship security systems — v0.06.3 Part 5.

Covers:
  server/game_loop_security.py — door control, lockdowns, internal sensors,
  emergency bulkheads, alert levels, armoury, quarantine zones.
"""
from __future__ import annotations

import pytest

import server.game_loop_security as gls
from server.models.interior import ShipInterior, make_default_interior
from server.models.ship import Ship


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh() -> tuple[ShipInterior, Ship]:
    return make_default_interior(), Ship()


@pytest.fixture(autouse=True)
def _reset_security():
    gls.reset()


# ---------------------------------------------------------------------------
# Door control
# ---------------------------------------------------------------------------


class TestDoorControl:
    def test_lock_door(self):
        interior, _ = fresh()
        assert gls.lock_door(interior, "bridge") is True
        assert interior.rooms["bridge"].door_sealed is True
        assert "bridge" in gls.get_locked_doors()

    def test_unlock_door(self):
        interior, _ = fresh()
        gls.lock_door(interior, "bridge")
        assert gls.unlock_door(interior, "bridge") is True
        assert interior.rooms["bridge"].door_sealed is False
        assert "bridge" not in gls.get_locked_doors()

    def test_lock_unknown_room_fails(self):
        interior, _ = fresh()
        assert gls.lock_door(interior, "nonexistent") is False

    def test_lock_breached_door_fails(self):
        interior, _ = fresh()
        gls.mark_door_breached("bridge")
        assert gls.lock_door(interior, "bridge") is False

    def test_breached_door_tracked(self):
        gls.mark_door_breached("conn")
        assert "conn" in gls.get_breached_doors()

    def test_locked_door_blocks_pathfinding(self):
        interior, _ = fresh()
        gls.lock_door(interior, "auxiliary_power")
        path = interior.find_path("cargo_hold", "engine_room")
        assert path == []  # blocked by sealed door

    def test_locked_door_passable_with_ignore_sealed(self):
        interior, _ = fresh()
        gls.lock_door(interior, "auxiliary_power")
        path = interior.find_path("cargo_hold", "engine_room", ignore_sealed=True)
        assert len(path) >= 2


# ---------------------------------------------------------------------------
# Lockdown
# ---------------------------------------------------------------------------


class TestLockdown:
    def test_lockdown_deck(self):
        interior, _ = fresh()
        count = gls.lockdown_deck(interior, 1)
        assert count == 4  # bridge, conn, ready_room, observation
        for rid in ["bridge", "conn", "ready_room", "observation"]:
            assert interior.rooms[rid].door_sealed is True

    def test_lift_deck_lockdown(self):
        interior, _ = fresh()
        gls.lockdown_deck(interior, 1)
        count = gls.lift_deck_lockdown(interior, 1)
        assert count == 4
        for rid in ["bridge", "conn", "ready_room", "observation"]:
            assert interior.rooms[rid].door_sealed is False

    def test_lockdown_all(self):
        interior, _ = fresh()
        count = gls.lockdown_all(interior)
        assert count == 20  # all rooms
        assert gls.is_ship_lockdown() is True
        for room in interior.rooms.values():
            assert room.door_sealed is True

    def test_lift_lockdown_all(self):
        interior, _ = fresh()
        gls.lockdown_all(interior)
        count = gls.lift_lockdown_all(interior)
        assert count == 20
        assert gls.is_ship_lockdown() is False
        for room in interior.rooms.values():
            assert room.door_sealed is False

    def test_lockdown_skips_breached_doors(self):
        interior, _ = fresh()
        gls.mark_door_breached("bridge")
        count = gls.lockdown_deck(interior, 1)
        assert count == 3  # bridge skipped (breached)

    def test_individual_unlock_within_lockdown(self):
        interior, _ = fresh()
        gls.lockdown_deck(interior, 1)
        gls.unlock_door(interior, "bridge")
        assert interior.rooms["bridge"].door_sealed is False
        assert interior.rooms["conn"].door_sealed is True


# ---------------------------------------------------------------------------
# Internal sensors
# ---------------------------------------------------------------------------


class TestSensors:
    def test_default_sensor_status(self):
        assert gls.get_sensor_status("bridge") == "active"

    def test_set_sensor_damaged(self):
        gls.set_sensor_status("bridge", "damaged")
        assert gls.get_sensor_status("bridge") == "damaged"

    def test_boost_sensor(self):
        assert gls.activate_sensor_boost("bridge") is True
        assert gls.get_sensor_status("bridge") == "boosted"

    def test_boost_damaged_fails(self):
        gls.set_sensor_status("bridge", "damaged")
        assert gls.activate_sensor_boost("bridge") is False

    def test_deactivate_boost(self):
        gls.activate_sensor_boost("bridge")
        gls.deactivate_sensor_boost("bridge")
        assert gls.get_sensor_status("bridge") == "active"

    def test_sensor_coverage_all_active(self):
        interior, _ = fresh()
        assert gls.get_sensor_coverage(interior) == pytest.approx(1.0)

    def test_sensor_coverage_with_damage(self):
        interior, _ = fresh()
        gls.set_sensor_status("bridge", "damaged")
        gls.set_sensor_status("conn", "damaged")
        expected = 18 / 20  # 2 of 20 damaged
        assert gls.get_sensor_coverage(interior) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Emergency bulkheads
# ---------------------------------------------------------------------------


class TestBulkheads:
    def test_seal_bulkhead(self):
        assert gls.seal_bulkhead(1, 2) is True
        assert gls.is_bulkhead_sealed(1, 2) is True

    def test_seal_non_adjacent_fails(self):
        assert gls.seal_bulkhead(1, 3) is False

    def test_seal_normalises_order(self):
        gls.seal_bulkhead(3, 2)
        assert gls.is_bulkhead_sealed(2, 3) is True

    def test_start_unseal(self):
        gls.seal_bulkhead(1, 2)
        assert gls.start_unseal_bulkhead(1, 2) is True

    def test_unseal_not_sealed_fails(self):
        assert gls.start_unseal_bulkhead(1, 2) is False

    def test_bulkhead_unseals_after_timer(self):
        interior, ship = fresh()
        gls.seal_bulkhead(1, 2)
        gls.start_unseal_bulkhead(1, 2)
        # Tick security systems until unseal completes
        all_events = []
        for _ in range(int(gls.BULKHEAD_UNSEAL_TIME * 10) + 5):
            all_events.extend(gls.tick_security_systems(0.1))
        assert gls.is_bulkhead_sealed(1, 2) is False
        unseal_events = [e for e in all_events if e[0] == "security.bulkhead_unsealed"]
        assert len(unseal_events) == 1

    def test_inter_deck_blocked(self):
        gls.seal_bulkhead(4, 5)
        # surgery (deck 4) → engine_room (deck 5)
        assert gls.is_inter_deck_blocked("surgery", "engine_room") is True
        assert gls.is_inter_deck_blocked("medbay", "surgery") is False  # same deck

    def test_get_sealed_bulkheads(self):
        gls.seal_bulkhead(1, 2)
        gls.seal_bulkhead(4, 5)
        bh = gls.get_sealed_bulkheads()
        assert (1, 2) in bh
        assert (4, 5) in bh


# ---------------------------------------------------------------------------
# Alert levels
# ---------------------------------------------------------------------------


class TestAlertLevels:
    def test_set_deck_alert(self):
        assert gls.set_deck_alert(1, "combat") is True
        assert gls.get_deck_alert(1) == "combat"

    def test_default_alert_normal(self):
        assert gls.get_deck_alert(1) == "normal"

    def test_invalid_level_fails(self):
        assert gls.set_deck_alert(1, "panic") is False

    def test_invalid_deck_fails(self):
        assert gls.set_deck_alert(99, "combat") is False

    def test_get_all_deck_alerts(self):
        gls.set_deck_alert(1, "combat")
        gls.set_deck_alert(5, "evacuate")
        alerts = gls.get_all_deck_alerts()
        assert alerts[1] == "combat"
        assert alerts[2] == "normal"
        assert alerts[5] == "evacuate"

    def test_combat_alert_reduces_casualties(self):
        gls.set_deck_alert(1, "combat")
        mult = gls.get_casualty_multiplier("bridge")
        assert mult == pytest.approx(0.5)

    def test_normal_alert_no_casualty_reduction(self):
        mult = gls.get_casualty_multiplier("bridge")
        assert mult == pytest.approx(1.0)

    def test_evacuate_overrides_crew_factor(self):
        gls.set_deck_alert(5, "evacuate")
        override = gls.get_crew_factor_override(5)
        assert override == pytest.approx(0.10)

    def test_normal_no_crew_factor_override(self):
        assert gls.get_crew_factor_override(1) is None


# ---------------------------------------------------------------------------
# Armoury
# ---------------------------------------------------------------------------


class TestArmoury:
    def test_arm_crew(self):
        assert gls.arm_crew(1) is True
        assert gls.is_crew_armed(1) is True

    def test_arm_already_armed(self):
        gls.arm_crew(1)
        assert gls.arm_crew(1) is True  # no-op, succeeds

    def test_arm_max_decks(self):
        gls.arm_crew(1)
        gls.arm_crew(2)
        assert gls.arm_crew(3) is False  # at max

    def test_disarm_frees_slot(self):
        gls.arm_crew(1)
        gls.arm_crew(2)
        gls.disarm_crew(1)
        assert gls.arm_crew(3) is True

    def test_disarm_not_armed_fails(self):
        assert gls.disarm_crew(1) is False

    def test_invalid_deck_fails(self):
        assert gls.arm_crew(99) is False

    def test_armed_crew_firepower(self):
        gls.arm_crew(1)
        fp = gls.get_crew_firepower("bridge")
        assert fp == pytest.approx(gls.ARMED_CREW_FIREPOWER)

    def test_unarmed_crew_firepower(self):
        fp = gls.get_crew_firepower("bridge")
        assert fp == pytest.approx(gls.CREW_FIREPOWER)

    def test_get_armed_decks(self):
        gls.arm_crew(1)
        gls.arm_crew(5)
        assert gls.get_armed_decks() == {1, 5}


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------


class TestQuarantine:
    def test_quarantine_room(self):
        interior, _ = fresh()
        assert gls.quarantine_room(interior, "medbay") is True
        assert gls.is_quarantined("medbay") is True
        assert interior.rooms["medbay"].door_sealed is True

    def test_quarantine_unknown_room_fails(self):
        interior, _ = fresh()
        assert gls.quarantine_room(interior, "nonexistent") is False

    def test_quarantine_deck(self):
        interior, _ = fresh()
        count = gls.quarantine_deck(interior, 4)
        assert count == 4
        for rid in ["medbay", "surgery", "quarantine", "pharmacy"]:
            assert gls.is_quarantined(rid) is True

    def test_lift_quarantine(self):
        interior, _ = fresh()
        gls.quarantine_room(interior, "medbay")
        assert gls.lift_quarantine(interior, "medbay") is True
        assert gls.is_quarantined("medbay") is False
        assert interior.rooms["medbay"].door_sealed is False

    def test_lift_not_quarantined_fails(self):
        interior, _ = fresh()
        assert gls.lift_quarantine(interior, "medbay") is False

    def test_quarantine_blocks_pathfinding(self):
        interior, _ = fresh()
        gls.quarantine_room(interior, "surgery")
        # medbay → surgery → torpedo_room should be blocked
        path = interior.find_path("medbay", "torpedo_room")
        assert path == []

    def test_get_quarantined_rooms(self):
        interior, _ = fresh()
        gls.quarantine_room(interior, "medbay")
        gls.quarantine_room(interior, "surgery")
        qr = gls.get_quarantined_rooms()
        assert "medbay" in qr
        assert "surgery" in qr


# ---------------------------------------------------------------------------
# Serialise / deserialise round-trip
# ---------------------------------------------------------------------------


class TestSecuritySystemsSerialise:
    def test_round_trip_locked_doors(self):
        interior, _ = fresh()
        gls.lock_door(interior, "bridge")
        gls.lock_door(interior, "conn")
        data = gls.serialise()
        gls.reset()
        gls.deserialise(data)
        assert gls.get_locked_doors() == {"bridge", "conn"}

    def test_round_trip_breached_doors(self):
        gls.mark_door_breached("bridge")
        data = gls.serialise()
        gls.reset()
        gls.deserialise(data)
        assert "bridge" in gls.get_breached_doors()

    def test_round_trip_ship_lockdown(self):
        interior, _ = fresh()
        gls.lockdown_all(interior)
        data = gls.serialise()
        gls.reset()
        gls.deserialise(data)
        assert gls.is_ship_lockdown() is True

    def test_round_trip_bulkheads(self):
        gls.seal_bulkhead(1, 2)
        gls.seal_bulkhead(4, 5)
        data = gls.serialise()
        gls.reset()
        gls.deserialise(data)
        assert gls.is_bulkhead_sealed(1, 2) is True
        assert gls.is_bulkhead_sealed(4, 5) is True

    def test_round_trip_deck_alerts(self):
        gls.set_deck_alert(1, "combat")
        gls.set_deck_alert(5, "evacuate")
        data = gls.serialise()
        gls.reset()
        gls.deserialise(data)
        assert gls.get_deck_alert(1) == "combat"
        assert gls.get_deck_alert(5) == "evacuate"

    def test_round_trip_armed_decks(self):
        gls.arm_crew(1)
        gls.arm_crew(2)
        data = gls.serialise()
        gls.reset()
        gls.deserialise(data)
        assert gls.get_armed_decks() == {1, 2}

    def test_round_trip_quarantine(self):
        interior, _ = fresh()
        gls.quarantine_room(interior, "medbay")
        data = gls.serialise()
        gls.reset()
        gls.deserialise(data)
        assert gls.is_quarantined("medbay") is True

    def test_round_trip_sensors(self):
        gls.set_sensor_status("bridge", "damaged")
        data = gls.serialise()
        gls.reset()
        gls.deserialise(data)
        assert gls.get_sensor_status("bridge") == "damaged"


# ---------------------------------------------------------------------------
# build_interior_state includes security systems
# ---------------------------------------------------------------------------


class TestInteriorStateSecuritySystems:
    def test_state_includes_locked_doors(self):
        interior, ship = fresh()
        gls.lock_door(interior, "bridge")
        state = gls.build_interior_state(interior, ship)
        assert "bridge" in state["locked_doors"]

    def test_state_includes_deck_alerts(self):
        interior, ship = fresh()
        gls.set_deck_alert(1, "combat")
        state = gls.build_interior_state(interior, ship)
        assert state["deck_alerts"]["1"] == "combat"

    def test_state_includes_armed_decks(self):
        interior, ship = fresh()
        gls.arm_crew(1)
        state = gls.build_interior_state(interior, ship)
        assert 1 in state["armed_decks"]

    def test_state_includes_quarantine(self):
        interior, ship = fresh()
        gls.quarantine_room(interior, "medbay")
        state = gls.build_interior_state(interior, ship)
        assert "medbay" in state["quarantined_rooms"]

    def test_state_includes_bulkheads(self):
        interior, ship = fresh()
        gls.seal_bulkhead(1, 2)
        state = gls.build_interior_state(interior, ship)
        assert [1, 2] in state["sealed_bulkheads"]
