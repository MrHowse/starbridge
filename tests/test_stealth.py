"""Tests for v0.07 §2.1 — Scout Silent Running (stealth system).

Covers:
  - Stealth capability gating (scout-only)
  - State machine transitions (activate, complete, deactivate, double-toggle)
  - Cost enforcement (shields zeroed, engine limit, sensor modifier)
  - Stealth-breaking triggers (damage, engine power, active scan, comms)
  - Enemy detection modifier values
  - Serialisation round-trip
  - Build state includes stealth fields
"""
from __future__ import annotations

import pytest

import server.game_loop_ew as glew
from server.game_loop_ew import (
    STEALTH_ACTIVATION_TIME,
    STEALTH_DEACTIVATION_TIME,
    STEALTH_DETECT_RANGE_MULT,
    STEALTH_ENGINE_LIMIT,
)
from server.models.ship import Ship, Shields
from server.models.world import World


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DT = 0.1  # 10 Hz tick


def _make_ship(**overrides) -> Ship:
    ship = Ship()
    for k, v in overrides.items():
        setattr(ship, k, v)
    return ship


def _make_world(ship: Ship | None = None) -> World:
    w = World()
    if ship is not None:
        w.ship = ship
    return w


def _tick_n(world: World, ship: Ship, n: int) -> None:
    """Advance n ticks."""
    for _ in range(n):
        glew.tick(world, ship, DT)


# ---------------------------------------------------------------------------
# §2.1.1 — Stealth capability gating
# ---------------------------------------------------------------------------


class TestStealthCapability:
    def test_scout_is_stealth_capable(self):
        glew.reset("scout")
        assert glew.is_stealth_capable() is True

    def test_non_scout_not_capable(self):
        for cls in ("corvette", "frigate", "cruiser", "battleship", "carrier", "medical_ship"):
            glew.reset(cls)
            assert glew.is_stealth_capable() is False, f"{cls} should not be stealth capable"

    def test_default_reset_not_capable(self):
        glew.reset()
        assert glew.is_stealth_capable() is False

    def test_toggle_rejected_for_non_scout(self):
        glew.reset("frigate")
        result = glew.toggle_stealth(True)
        assert result["ok"] is False
        assert result["reason"] == "not_capable"


# ---------------------------------------------------------------------------
# §2.1.2 — State machine transitions
# ---------------------------------------------------------------------------


class TestStealthStateMachine:
    def test_activation_starts_correctly(self):
        glew.reset("scout")
        result = glew.toggle_stealth(True)
        assert result["ok"] is True
        assert result["state"] == "activating"
        assert glew.get_stealth_state() == "activating"
        assert glew.is_stealth_engaged() is True
        assert glew.is_stealth_active() is False

    def test_activation_completes(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        # Tick through activation time (5s = 50 ticks at 10Hz)
        _tick_n(world, ship, 51)
        assert glew.get_stealth_state() == "active"
        assert glew.is_stealth_active() is True

    def test_deactivation_transition(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        _tick_n(world, ship, 51)  # activate
        result = glew.toggle_stealth(False)
        assert result["ok"] is True
        assert result["state"] == "deactivating"
        assert glew.get_stealth_state() == "deactivating"

    def test_deactivation_completes(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        _tick_n(world, ship, 51)  # activate
        glew.toggle_stealth(False)
        _tick_n(world, ship, 31)  # deactivate (3s = 30 ticks)
        assert glew.get_stealth_state() == "inactive"
        assert glew.is_stealth_engaged() is False

    def test_double_toggle_activate_rejected(self):
        glew.reset("scout")
        glew.toggle_stealth(True)
        result = glew.toggle_stealth(True)
        assert result["ok"] is False
        assert result["reason"] == "already_engaged"

    def test_double_toggle_deactivate_rejected(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        _tick_n(world, ship, 51)  # active
        glew.toggle_stealth(False)
        result = glew.toggle_stealth(False)
        assert result["ok"] is False
        assert result["reason"] == "already_deactivating"

    def test_toggle_off_while_inactive(self):
        glew.reset("scout")
        result = glew.toggle_stealth(False)
        assert result["ok"] is False
        assert result["reason"] == "not_engaged"

    def test_toggle_off_during_activation(self):
        """Player can cancel stealth during activation."""
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        _tick_n(world, ship, 10)  # 1 second into activation
        result = glew.toggle_stealth(False)
        assert result["ok"] is True
        assert glew.get_stealth_state() == "deactivating"


# ---------------------------------------------------------------------------
# §2.1.3 — Cost enforcement
# ---------------------------------------------------------------------------


class TestStealthCosts:
    def test_shields_zeroed_during_activation(self):
        glew.reset("scout")
        ship = _make_ship()
        ship.shields = Shields(fore=50, aft=50, port=50, starboard=50)
        world = _make_world(ship)
        glew.toggle_stealth(True)
        glew.tick(world, ship, DT)
        assert ship.shields.fore == 0.0
        assert ship.shields.aft == 0.0
        assert ship.shields.port == 0.0
        assert ship.shields.starboard == 0.0

    def test_shields_zeroed_during_active(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        _tick_n(world, ship, 51)  # activate
        # Set shields to something — should be zeroed on next tick
        ship.shields = Shields(fore=25, aft=25, port=25, starboard=25)
        glew.tick(world, ship, DT)
        assert ship.shields.fore == 0.0

    def test_engine_limit_breaks_stealth(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        _tick_n(world, ship, 51)  # active
        assert glew.is_stealth_active() is True
        ship.throttle = STEALTH_ENGINE_LIMIT + 1
        glew.tick(world, ship, DT)
        assert glew.get_stealth_state() == "deactivating"

    def test_throttle_at_limit_is_ok(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        _tick_n(world, ship, 51)  # active
        ship.throttle = STEALTH_ENGINE_LIMIT
        glew.tick(world, ship, DT)
        assert glew.is_stealth_active() is True  # exactly at limit is OK


# ---------------------------------------------------------------------------
# §2.1.4 — Sensor modifier (enemy detection range)
# ---------------------------------------------------------------------------


class TestStealthSensorModifier:
    def test_inactive_modifier_is_1(self):
        glew.reset("scout")
        assert glew.get_stealth_sensor_modifier() == 1.0

    def test_active_modifier(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        _tick_n(world, ship, 51)  # active
        assert glew.get_stealth_sensor_modifier() == STEALTH_DETECT_RANGE_MULT

    def test_activating_interpolation(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        # At t=0, modifier should be 1.0
        mod_start = glew.get_stealth_sensor_modifier()
        assert mod_start == 1.0
        # After half the activation time
        _tick_n(world, ship, 25)
        mod_mid = glew.get_stealth_sensor_modifier()
        assert 0.3 < mod_mid < 1.0, f"Expected midpoint modifier, got {mod_mid}"

    def test_deactivating_interpolation(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        _tick_n(world, ship, 51)  # active
        glew.toggle_stealth(False)
        # At start of deactivation, modifier should be near STEALTH_DETECT_RANGE_MULT
        mod_start = glew.get_stealth_sensor_modifier()
        assert mod_start == STEALTH_DETECT_RANGE_MULT
        # After half deactivation
        _tick_n(world, ship, 15)
        mod_mid = glew.get_stealth_sensor_modifier()
        assert STEALTH_DETECT_RANGE_MULT < mod_mid < 1.0


# ---------------------------------------------------------------------------
# §2.1.5 — Stealth-breaking triggers
# ---------------------------------------------------------------------------


class TestStealthBreaking:
    def test_break_from_active(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        _tick_n(world, ship, 51)  # active
        glew.break_stealth("damage")
        assert glew.get_stealth_state() == "deactivating"

    def test_break_from_activating(self):
        glew.reset("scout")
        glew.toggle_stealth(True)
        glew.break_stealth("active_scan")
        assert glew.get_stealth_state() == "deactivating"

    def test_break_noop_when_inactive(self):
        glew.reset("scout")
        glew.break_stealth("damage")
        assert glew.get_stealth_state() == "inactive"

    def test_break_noop_when_deactivating(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        _tick_n(world, ship, 51)  # active
        glew.toggle_stealth(False)  # deactivating
        glew.break_stealth("damage")  # should not change state
        assert glew.get_stealth_state() == "deactivating"

    def test_break_reason_tracked(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        _tick_n(world, ship, 51)  # active
        glew.break_stealth("engine_power")
        reason = glew.pop_stealth_break_reason()
        assert reason == "engine_power"

    def test_break_reason_cleared_after_pop(self):
        glew.reset("scout")
        glew.toggle_stealth(True)
        glew.break_stealth("damage")
        glew.pop_stealth_break_reason()
        assert glew.pop_stealth_break_reason() is None

    def test_engine_power_break_sets_reason(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        _tick_n(world, ship, 51)  # active
        ship.throttle = 60.0
        glew.tick(world, ship, DT)
        reason = glew.pop_stealth_break_reason()
        assert reason == "engine_power"


# ---------------------------------------------------------------------------
# §2.1.6 — Serialisation round-trip
# ---------------------------------------------------------------------------


class TestStealthSerialise:
    def test_round_trip(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        _tick_n(world, ship, 25)  # midway through activation
        data = glew.serialise()
        assert data["stealth_state"] == "activating"
        assert data["stealth_capable"] is True
        assert data["stealth_timer"] > 0.0

        # Deserialise and check state restored
        glew.reset()
        glew.deserialise(data)
        assert glew.get_stealth_state() == "activating"
        assert glew.is_stealth_capable() is True

    def test_deserialise_defaults(self):
        """Old saves without stealth data get inactive defaults."""
        glew.reset("scout")
        glew.deserialise({})
        assert glew.get_stealth_state() == "inactive"
        assert glew.is_stealth_capable() is False


# ---------------------------------------------------------------------------
# §2.1.7 — Build state includes stealth fields
# ---------------------------------------------------------------------------


class TestStealthBuildState:
    def test_build_state_includes_stealth(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        state = glew.build_state(world, ship)
        assert "stealth_state" in state
        assert "stealth_capable" in state
        assert "stealth_timer" in state
        assert state["stealth_state"] == "inactive"
        assert state["stealth_capable"] is True

    def test_build_state_during_activation(self):
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)
        glew.toggle_stealth(True)
        _tick_n(world, ship, 10)
        state = glew.build_state(world, ship)
        assert state["stealth_state"] == "activating"
        assert state["stealth_timer"] > 0


# ---------------------------------------------------------------------------
# §2.1.8 — Integration: beam fire blocked during stealth
# ---------------------------------------------------------------------------


class TestStealthBeamBlock:
    def test_beams_blocked_when_stealth_engaged(self):
        """When stealth is engaged, is_stealth_engaged() returns True which blocks beams."""
        glew.reset("scout")
        glew.toggle_stealth(True)
        assert glew.is_stealth_engaged() is True
        # The actual blocking is in _drain_queue — we just verify the flag.

    def test_beams_allowed_when_inactive(self):
        glew.reset("scout")
        assert glew.is_stealth_engaged() is False


# ---------------------------------------------------------------------------
# §2.1.9 — Full activation/deactivation cycle
# ---------------------------------------------------------------------------


class TestStealthFullCycle:
    def test_full_cycle(self):
        """Full activation → active → deactivation → inactive cycle."""
        glew.reset("scout")
        ship = _make_ship()
        world = _make_world(ship)

        assert glew.get_stealth_state() == "inactive"

        # Activate
        glew.toggle_stealth(True)
        assert glew.get_stealth_state() == "activating"
        _tick_n(world, ship, 51)
        assert glew.get_stealth_state() == "active"

        # Deactivate
        glew.toggle_stealth(False)
        assert glew.get_stealth_state() == "deactivating"
        _tick_n(world, ship, 31)
        assert glew.get_stealth_state() == "inactive"

        # Can re-activate
        result = glew.toggle_stealth(True)
        assert result["ok"] is True
