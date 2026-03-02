"""
Tests for Operations station Enemy Analysis System (v0.08 A.2).

Covers:
  A.2.1 Battle Assessment (lifecycle, speed modifiers, persistence)
  A.2.2 Shield Harmonics (per-facing data, vulnerable facing bonus)
  A.2.3 System Vulnerability (subsystem health, priority subsystem, cooldown)
  A.2.4 Behaviour Prediction (linear extrapolation, confidence, accuracy bonus)
  A.2.5 Threat Assessment (levels, propagation)
  Combat integration (real bonuses wired into damage pipeline)
  Serialise / deserialise round-trip

Target: 30+ tests (spec D.1).
"""
from __future__ import annotations

import math
from unittest.mock import patch

import pytest

import server.game_loop_operations as glops
from server.game_loop_operations import (
    ASSESSMENT_BASE_DURATION,
    ASSESSMENT_BASIC_SCAN_MODIFIER,
    ASSESSMENT_EW_JAM_MODIFIER,
    ASSESSMENT_OUT_OF_RANGE_EXPIRY,
    PREDICTION_ACCURACY_BONUS,
    PREDICTION_REFRESH_INTERVAL,
    PRIORITY_SUBSYSTEM_COOLDOWN,
    SHIELD_HARMONICS_REFRESH,
    VULNERABLE_FACING_ARC,
    VULNERABLE_FACING_BONUS,
    BattleAssessment,
)
from server.models.ship import Ship
from server.models.world import Enemy, World, spawn_enemy
from server.systems.combat import (
    ENEMY_SYSTEM_DAMAGE_CHANCE,
    ENEMY_SYSTEM_DAMAGE_FRACTION,
    ENEMY_SYSTEM_DAMAGE_PRIORITY_BONUS,
    apply_hit_to_enemy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _world_with_enemy(
    enemy_id: str = "e1",
    enemy_type: str = "cruiser",
    x: float = 5000.0,
    y: float = 5000.0,
    scanned: bool = True,
) -> tuple[World, Ship, Enemy]:
    world = World()
    ship = world.ship
    ship.x, ship.y = 50000.0, 50000.0
    enemy = spawn_enemy(enemy_type, x, y, enemy_id)
    if scanned:
        enemy.scan_state = "scanned"
    world.enemies.append(enemy)
    return world, ship, enemy


def _tick(world: World, ship: Ship, seconds: float, dt: float = 0.1) -> None:
    """Tick operations for *seconds* at *dt* step."""
    ticks = round(seconds / dt)
    for _ in range(ticks):
        glops.tick(world, ship, dt)


# ═══════════════════════════════════════════════════════════════════════════
# A.2.1 — Battle Assessment
# ═══════════════════════════════════════════════════════════════════════════


class TestBattleAssessment:
    """A.2.1: assessment lifecycle."""

    def test_start_assessment_on_scanned_contact(self):
        """A.2.1.1: can assess a scanned contact."""
        world, ship, enemy = _world_with_enemy(scanned=True)
        result = glops.start_assessment("e1", world, ship)
        assert result["ok"] is True

    def test_cannot_assess_unscanned_contact(self):
        """A.2.1.1: unscanned → rejection with Science message."""
        world, ship, enemy = _world_with_enemy(scanned=False)
        result = glops.start_assessment("e1", world, ship)
        assert result["ok"] is False
        assert "Science" in result["reason"]

    def test_cannot_assess_nonexistent_contact(self):
        world, ship, _ = _world_with_enemy()
        result = glops.start_assessment("no_such_enemy", world, ship)
        assert result["ok"] is False

    def test_assessment_progress_to_completion(self):
        """A.2.1.2: 15-second base assessment completes."""
        world, ship, enemy = _world_with_enemy()
        glops.start_assessment("e1", world, ship)
        # Effective speed with basic scan: 1.0 + (-0.25) = 0.75.
        # At 0.75× speed, need 15 / 0.75 = 20 seconds.
        _tick(world, ship, 20.5)
        state = glops.build_state(world, ship)
        assert state["assessments"]["e1"]["complete"] is True

    def test_assessment_incomplete_before_duration(self):
        """Assessment should still be in progress before completion."""
        world, ship, enemy = _world_with_enemy()
        glops.start_assessment("e1", world, ship)
        _tick(world, ship, 10.0)
        state = glops.build_state(world, ship)
        assert state["assessments"]["e1"]["complete"] is False

    def test_only_one_assessment_at_a_time(self):
        """A.2.1.2: starting new assessment cancels the old one."""
        world, ship, _ = _world_with_enemy()
        e2 = spawn_enemy("scout", 6000.0, 6000.0, "e2")
        e2.scan_state = "scanned"
        world.enemies.append(e2)

        glops.start_assessment("e1", world, ship)
        _tick(world, ship, 5.0)
        glops.start_assessment("e2", world, ship)

        state = glops.build_state(world, ship)
        # e1 should have been removed (was incomplete when cancelled).
        assert "e1" not in state["assessments"]
        assert "e2" in state["assessments"]

    def test_cancel_assessment(self):
        """A.2.1.2: explicit cancellation."""
        world, ship, _ = _world_with_enemy()
        glops.start_assessment("e1", world, ship)
        result = glops.cancel_assessment()
        assert result["ok"] is True
        state = glops.build_state(world, ship)
        assert "e1" not in state["assessments"]

    def test_cancel_with_nothing_in_progress(self):
        result = glops.cancel_assessment()
        assert result["ok"] is False

    def test_assessment_speed_with_ew_jamming(self):
        """A.2.1.3: EW jamming gives +15% speed boost."""
        world, ship, enemy = _world_with_enemy()
        enemy.jam_factor = 0.5  # being jammed
        glops.start_assessment("e1", world, ship)
        # Speed = (1.0 - 0.25 + 0.15) * sensor_eff = 0.9 * 1.0 = 0.9
        # Duration = 15 / 0.9 ≈ 16.67s
        _tick(world, ship, 17.0)
        state = glops.build_state(world, ship)
        assert state["assessments"]["e1"]["complete"] is True

    def test_assessment_speed_scales_with_sensor_efficiency(self):
        """A.2.1.3: sensor health reduces assessment speed."""
        world, ship, enemy = _world_with_enemy()
        ship.systems["sensors"].power = 50.0  # 50% power → ~0.5 efficiency
        glops.start_assessment("e1", world, ship)
        # Speed ≈ 0.75 * 0.5 = 0.375; Duration ≈ 15 / 0.375 = 40s
        _tick(world, ship, 30.0)
        state = glops.build_state(world, ship)
        assert state["assessments"]["e1"]["complete"] is False
        _tick(world, ship, 15.0)
        state = glops.build_state(world, ship)
        assert state["assessments"]["e1"]["complete"] is True

    def test_assessment_persists_after_completion(self):
        """A.2.1.4: completed assessment stays valid."""
        world, ship, _ = _world_with_enemy()
        glops.start_assessment("e1", world, ship)
        _tick(world, ship, 21.0)
        state = glops.build_state(world, ship)
        assert state["assessments"]["e1"]["complete"] is True
        # Tick more — should still be there.
        _tick(world, ship, 30.0)
        state = glops.build_state(world, ship)
        assert "e1" in state["assessments"]

    def test_assessment_expires_when_out_of_range(self):
        """A.2.1.4: contact out of sensor range for >60s → expired."""
        world, ship, enemy = _world_with_enemy()
        glops.start_assessment("e1", world, ship)
        _tick(world, ship, 21.0)
        assert glops.build_state(world, ship)["assessments"]["e1"]["complete"]

        # Move enemy far away (out of default 35000 sensor range from ship at 50000,50000).
        enemy.x, enemy.y = 99000.0, 99000.0
        _tick(world, ship, ASSESSMENT_OUT_OF_RANGE_EXPIRY + 1.0)
        state = glops.build_state(world, ship)
        assert "e1" not in state["assessments"]

    def test_assessment_survives_brief_out_of_range(self):
        """A.2.1.4: contact returns within 60s → assessment preserved."""
        world, ship, enemy = _world_with_enemy()
        glops.start_assessment("e1", world, ship)
        _tick(world, ship, 21.0)

        enemy.x, enemy.y = 99000.0, 99000.0
        _tick(world, ship, 30.0)  # out for 30s (< 60s)
        enemy.x, enemy.y = 5000.0, 5000.0  # back in range
        _tick(world, ship, 5.0)
        state = glops.build_state(world, ship)
        assert "e1" in state["assessments"]

    def test_assessment_removed_when_enemy_destroyed(self):
        """A.2.1.4: destroyed contact → assessment removed."""
        world, ship, enemy = _world_with_enemy()
        glops.start_assessment("e1", world, ship)
        _tick(world, ship, 21.0)
        # Remove enemy from world (destroyed).
        world.enemies.clear()
        _tick(world, ship, 1.0)
        state = glops.build_state(world, ship)
        assert "e1" not in state["assessments"]


# ═══════════════════════════════════════════════════════════════════════════
# A.2.2 — Shield Harmonics
# ═══════════════════════════════════════════════════════════════════════════


class TestShieldHarmonics:
    """A.2.2: shield harmonics analysis."""

    def _complete_assessment(self, world, ship, enemy_id="e1"):
        glops.start_assessment(enemy_id, world, ship)
        _tick(world, ship, 21.0)

    def test_harmonics_populated_on_completion(self):
        """A.2.2.1: shield data per facing on assessment completion."""
        world, ship, enemy = _world_with_enemy()
        self._complete_assessment(world, ship)
        state = glops.build_state(world, ship)
        harmonics = state["assessments"]["e1"]["shield_harmonics"]
        assert "fore" in harmonics
        assert "aft" in harmonics
        assert "port" in harmonics
        assert "starboard" in harmonics

    def test_harmonics_reflect_enemy_shields(self):
        """A.2.2.1: fore/aft match enemy shield_front/shield_rear."""
        world, ship, enemy = _world_with_enemy()
        enemy.shield_front = 80.0
        enemy.shield_rear = 30.0
        self._complete_assessment(world, ship)
        harmonics = glops.build_state(world, ship)["assessments"]["e1"]["shield_harmonics"]
        assert harmonics["fore"] == pytest.approx(80.0, abs=1.0)
        assert harmonics["aft"] == pytest.approx(30.0, abs=1.0)

    def test_set_vulnerable_facing(self):
        """A.2.2.2: designate weakest facing."""
        world, ship, enemy = _world_with_enemy()
        self._complete_assessment(world, ship)
        result = glops.set_vulnerable_facing("e1", "aft")
        assert result["ok"] is True
        state = glops.build_state(world, ship)
        assert state["assessments"]["e1"]["vulnerable_facing"] == "aft"

    def test_set_vulnerable_facing_rejects_unassessed(self):
        result = glops.set_vulnerable_facing("no_such", "fore")
        assert result["ok"] is False

    def test_set_vulnerable_facing_invalid(self):
        world, ship, _ = _world_with_enemy()
        self._complete_assessment(world, ship)
        result = glops.set_vulnerable_facing("e1", "top")
        assert result["ok"] is False

    def test_vulnerable_facing_broadcasts_to_stations(self):
        """A.2.2.2: pushed to weapons, helm, captain."""
        world, ship, _ = _world_with_enemy()
        self._complete_assessment(world, ship)
        glops.pop_pending_broadcasts()  # clear completion broadcast
        glops.set_vulnerable_facing("e1", "aft")
        broadcasts = glops.pop_pending_broadcasts()
        assert len(broadcasts) >= 1
        roles, data = broadcasts[0]
        assert "weapons" in roles
        assert "helm" in roles
        assert "captain" in roles
        assert data["facing"] == "aft"

    def test_harmonics_refresh_every_30s(self):
        """A.2.2.3: shield harmonics update periodically."""
        world, ship, enemy = _world_with_enemy()
        self._complete_assessment(world, ship)
        # Change shields after assessment.
        enemy.shield_front = 10.0
        _tick(world, ship, SHIELD_HARMONICS_REFRESH + 1.0)
        harmonics = glops.build_state(world, ship)["assessments"]["e1"]["shield_harmonics"]
        assert harmonics["fore"] == pytest.approx(10.0, abs=1.0)


# ═══════════════════════════════════════════════════════════════════════════
# A.2.3 — System Vulnerability
# ═══════════════════════════════════════════════════════════════════════════


class TestSystemVulnerability:
    """A.2.3: system vulnerability scan."""

    def _complete_assessment(self, world, ship, enemy_id="e1"):
        glops.start_assessment(enemy_id, world, ship)
        _tick(world, ship, 21.0)

    def test_system_health_in_state(self):
        """A.2.3.1: system health shown after assessment."""
        world, ship, enemy = _world_with_enemy()
        self._complete_assessment(world, ship)
        state = glops.build_state(world, ship)
        health = state["assessments"]["e1"]["system_health"]
        assert set(health.keys()) == {"engines", "weapons", "shields", "sensors", "propulsion"}
        # All should be 100% on a fresh enemy.
        for v in health.values():
            assert v == pytest.approx(100.0)

    def test_set_priority_subsystem(self):
        """A.2.3.2: designate a priority subsystem."""
        world, ship, _ = _world_with_enemy()
        self._complete_assessment(world, ship)
        result = glops.set_priority_subsystem("e1", "engines")
        assert result["ok"] is True
        assert glops.get_priority_subsystem("e1") == "engines"

    def test_priority_subsystem_rejects_unassessed(self):
        result = glops.set_priority_subsystem("no_such", "engines")
        assert result["ok"] is False

    def test_priority_subsystem_cooldown(self):
        """A.2.3.3: 10-second cooldown on redesignation."""
        world, ship, _ = _world_with_enemy()
        self._complete_assessment(world, ship)
        glops.set_priority_subsystem("e1", "engines")
        result = glops.set_priority_subsystem("e1", "weapons")
        assert result["ok"] is False
        assert "Cooldown" in result["reason"]

    def test_priority_subsystem_cooldown_expires(self):
        """A.2.3.3: cooldown expires after 10s, can redesignate."""
        world, ship, _ = _world_with_enemy()
        self._complete_assessment(world, ship)
        glops.set_priority_subsystem("e1", "engines")
        _tick(world, ship, PRIORITY_SUBSYSTEM_COOLDOWN + 1.0)
        result = glops.set_priority_subsystem("e1", "weapons")
        assert result["ok"] is True
        assert glops.get_priority_subsystem("e1") == "weapons"

    def test_priority_subsystem_broadcasts_to_stations(self):
        """A.2.3.2: pushed to weapons and flight_ops."""
        world, ship, _ = _world_with_enemy()
        self._complete_assessment(world, ship)
        glops.pop_pending_broadcasts()
        glops.set_priority_subsystem("e1", "shields")
        broadcasts = glops.pop_pending_broadcasts()
        assert len(broadcasts) >= 1
        roles, data = broadcasts[0]
        assert "weapons" in roles
        assert "flight_ops" in roles
        assert data["subsystem"] == "shields"


# ═══════════════════════════════════════════════════════════════════════════
# A.2.4 — Behaviour Prediction
# ═══════════════════════════════════════════════════════════════════════════


class TestBehaviourPrediction:
    """A.2.4: movement prediction."""

    def _complete_assessment(self, world, ship, enemy_id="e1"):
        glops.start_assessment(enemy_id, world, ship)
        _tick(world, ship, 21.0)

    def test_toggle_prediction_on(self):
        """A.2.4.4: enable prediction on assessed contact."""
        world, ship, _ = _world_with_enemy()
        self._complete_assessment(world, ship)
        result = glops.toggle_prediction("e1", True)
        assert result["ok"] is True

    def test_toggle_prediction_rejects_unassessed(self):
        result = glops.toggle_prediction("no_such", True)
        assert result["ok"] is False

    def test_prediction_computes_after_refresh(self):
        """A.2.4.1: after refresh interval, prediction positions are set."""
        world, ship, enemy = _world_with_enemy()
        enemy.heading = 0.0
        enemy.velocity = 100.0
        self._complete_assessment(world, ship)
        glops.toggle_prediction("e1", True)
        _tick(world, ship, PREDICTION_REFRESH_INTERVAL + 1.0)
        state = glops.build_state(world, ship)
        pred = state["assessments"]["e1"]["prediction"]
        assert pred["active"] is True
        # Heading 0 = north (y decreasing). predicted_y should be south of current.
        assert pred["predicted_y"] < enemy.y

    def test_prediction_confidence_high_for_straight_line(self):
        """A.2.4.3: straight-line movement → high confidence."""
        world, ship, enemy = _world_with_enemy()
        enemy.heading = 90.0  # east
        enemy.velocity = 200.0
        self._complete_assessment(world, ship)
        glops.toggle_prediction("e1", True)
        # Tick enough for history + refresh.
        _tick(world, ship, PREDICTION_REFRESH_INTERVAL + 2.0)
        state = glops.build_state(world, ship)
        assert state["assessments"]["e1"]["prediction"]["confidence"] == "high"

    def test_prediction_confidence_low_for_evasive_movement(self):
        """A.2.4.3: erratic heading changes → low confidence."""
        world, ship, enemy = _world_with_enemy()
        enemy.velocity = 200.0
        self._complete_assessment(world, ship)
        glops.toggle_prediction("e1", True)
        # Simulate erratic heading changes every tick (0.1s each).
        headings = [0, 90, 180, 270, 45, 135, 225, 315] * 15
        for heading in headings:
            enemy.heading = float(heading)
            glops.tick(world, ship, 0.1)
        # Force a refresh by ticking past the interval.
        _tick(world, ship, PREDICTION_REFRESH_INTERVAL + 1.0)
        state = glops.build_state(world, ship)
        assert state["assessments"]["e1"]["prediction"]["confidence"] == "low"

    def test_prediction_toggle_off(self):
        """A.2.4.4: toggle off clears prediction data."""
        world, ship, enemy = _world_with_enemy()
        self._complete_assessment(world, ship)
        glops.toggle_prediction("e1", True)
        _tick(world, ship, PREDICTION_REFRESH_INTERVAL + 1.0)
        glops.toggle_prediction("e1", False)
        state = glops.build_state(world, ship)
        assert state["assessments"]["e1"]["prediction"]["active"] is False


# ═══════════════════════════════════════════════════════════════════════════
# A.2.5 — Threat Assessment
# ═══════════════════════════════════════════════════════════════════════════


class TestThreatAssessment:
    """A.2.5: manual threat level assignment."""

    def test_set_threat_level(self):
        """A.2.5.1: set threat on a contact."""
        world, ship, _ = _world_with_enemy()
        result = glops.set_threat_level("e1", "high")
        assert result["ok"] is True
        assert glops.get_threat_level("e1") == "high"

    def test_invalid_threat_level(self):
        result = glops.set_threat_level("e1", "mega")
        assert result["ok"] is False

    def test_threat_level_default_is_low(self):
        assert glops.get_threat_level("nonexistent") == "low"

    def test_threat_level_broadcasts(self):
        """A.2.5.2-A.2.5.3: threat broadcasts to relevant stations."""
        world, ship, _ = _world_with_enemy()
        result = glops.set_threat_level("e1", "critical")
        broadcasts = glops.pop_pending_broadcasts()
        assert len(broadcasts) >= 1
        roles, data = broadcasts[0]
        assert "captain" in roles
        assert "weapons" in roles
        # CRITICAL goes to all stations.
        assert "flight_ops" in roles
        assert data["level"] == "critical"

    def test_threat_level_can_be_changed(self):
        """A.2.5.3: threat level can be updated anytime."""
        world, ship, _ = _world_with_enemy()
        glops.set_threat_level("e1", "high")
        glops.set_threat_level("e1", "low")
        assert glops.get_threat_level("e1") == "low"

    def test_threat_on_unassessed_contact_creates_entry(self):
        """A.2.5.1: threat can be set on non-assessed contacts."""
        world, ship, _ = _world_with_enemy()
        glops.set_threat_level("e1", "medium")
        state = glops.build_state(world, ship)
        assert "e1" in state["assessments"]
        assert state["assessments"]["e1"]["threat_level"] == "medium"


# ═══════════════════════════════════════════════════════════════════════════
# Combat Integration — REAL bonuses
# ═══════════════════════════════════════════════════════════════════════════


class TestCombatIntegration:
    """Verify Ops bonuses are wired into actual combat calculations."""

    def _complete_assessment(self, world, ship, enemy_id="e1"):
        glops.start_assessment(enemy_id, world, ship)
        _tick(world, ship, 21.0)

    def test_vulnerable_facing_bonus_applied(self):
        """A.2.2.2: +25% damage when attacking from designated facing."""
        world, ship, enemy = _world_with_enemy()
        enemy.heading = 0.0  # facing north
        # Place ship behind enemy (south) to attack aft.
        ship.x, ship.y = enemy.x, enemy.y + 1000.0
        self._complete_assessment(world, ship)
        glops.set_vulnerable_facing("e1", "aft")

        bonus = glops.check_vulnerable_facing_bonus("e1", enemy, ship.x, ship.y)
        assert bonus == pytest.approx(VULNERABLE_FACING_BONUS)

    def test_vulnerable_facing_no_bonus_wrong_angle(self):
        """No bonus when attacking from opposite side."""
        world, ship, enemy = _world_with_enemy()
        enemy.heading = 0.0
        # Ship in front (north).
        ship.x, ship.y = enemy.x, enemy.y - 1000.0
        self._complete_assessment(world, ship)
        glops.set_vulnerable_facing("e1", "aft")

        bonus = glops.check_vulnerable_facing_bonus("e1", enemy, ship.x, ship.y)
        assert bonus == 0.0

    def test_priority_subsystem_increases_damage_chance(self):
        """A.2.3.2: priority subsystem increases system damage probability."""
        world, ship, enemy = _world_with_enemy()
        self._complete_assessment(world, ship)
        glops.set_priority_subsystem("e1", "engines")

        # With priority: chance = ENEMY_SYSTEM_DAMAGE_CHANCE + PRIORITY_BONUS = 0.40
        # Without: chance = 0.20
        # Run many trials and check that priority has higher damage rate.
        hits_with = 0
        hits_without = 0
        trials = 2000

        for _ in range(trials):
            e_with = spawn_enemy("cruiser", 100.0, 100.0, "test_w")
            e_with.scan_state = "scanned"
            e_with.shield_front = 0.0
            e_with.shield_rear = 0.0
            apply_hit_to_enemy(e_with, 10.0, 100.0, 200.0, priority_subsystem="engines")
            if e_with.system_engines < 100.0:
                hits_with += 1

            e_without = spawn_enemy("cruiser", 100.0, 100.0, "test_wo")
            e_without.shield_front = 0.0
            e_without.shield_rear = 0.0
            apply_hit_to_enemy(e_without, 10.0, 100.0, 200.0)
            # Any system damaged counts.
            any_damaged = any(
                getattr(e_without, f"system_{s}") < 100.0
                for s in ("engines", "weapons", "shields", "sensors", "propulsion")
            )
            if any_damaged:
                hits_without += 1

        # With priority: ~40% should hit; without: ~20%.
        # Allow generous margins for randomness.
        assert hits_with > trials * 0.10  # at least 10% of priority hit engines
        assert hits_without < hits_with   # without should generally have fewer total hits

    def test_enemy_system_damage_roll_basic(self):
        """Combat: hull damage can cause subsystem damage."""
        damaged = False
        for _ in range(200):
            enemy = spawn_enemy("cruiser", 100.0, 100.0, "test")
            enemy.shield_front = 0.0
            enemy.shield_rear = 0.0
            apply_hit_to_enemy(enemy, 20.0, 100.0, 200.0)
            any_sys = any(
                getattr(enemy, f"system_{s}") < 100.0
                for s in ("engines", "weapons", "shields", "sensors", "propulsion")
            )
            if any_sys:
                damaged = True
                break
        assert damaged, "Expected at least one system to take damage in 200 trials"

    def test_prediction_accuracy_bonus_when_accurate(self):
        """A.2.4.2: +10% bonus when enemy near predicted position."""
        world, ship, enemy = _world_with_enemy()
        enemy.heading = 90.0
        enemy.velocity = 0.5  # very slow — barely moves in prediction window
        self._complete_assessment(world, ship)
        glops.toggle_prediction("e1", True)
        # Tick enough for 2 refreshes so prediction has good history.
        _tick(world, ship, PREDICTION_REFRESH_INTERVAL * 2 + 2.0)

        # With velocity ~0, prediction is very close to current position.
        # travel_dist < 100 → always returns bonus.
        bonus = glops.get_prediction_accuracy_bonus("e1", enemy.x, enemy.y)
        assert bonus == pytest.approx(PREDICTION_ACCURACY_BONUS)


# ═══════════════════════════════════════════════════════════════════════════
# Serialise / Deserialise
# ═══════════════════════════════════════════════════════════════════════════


class TestSerialise:
    """Save and restore round-trip."""

    def _complete_assessment(self, world, ship, enemy_id="e1"):
        glops.start_assessment(enemy_id, world, ship)
        _tick(world, ship, 21.0)

    def test_serialise_empty(self):
        data = glops.serialise()
        assert data["assessments"] == {}

    def test_round_trip_preserves_assessment(self):
        world, ship, enemy = _world_with_enemy()
        self._complete_assessment(world, ship)
        glops.set_vulnerable_facing("e1", "aft")
        glops.set_threat_level("e1", "high")

        data = glops.serialise()
        glops.reset()
        glops.deserialise(data)

        assert glops.get_vulnerable_facing("e1") == "aft"
        assert glops.get_threat_level("e1") == "high"
        state = glops.build_state(world, ship)
        assert state["assessments"]["e1"]["complete"] is True

    def test_round_trip_preserves_active_id(self):
        world, ship, _ = _world_with_enemy()
        glops.start_assessment("e1", world, ship)
        _tick(world, ship, 5.0)

        data = glops.serialise()
        glops.reset()
        glops.deserialise(data)

        state = glops.build_state(world, ship)
        assert state["active_assessment_id"] == "e1"

    def test_deserialise_handles_empty_data(self):
        glops.deserialise({})
        assert glops.serialise()["assessments"] == {}


# ═══════════════════════════════════════════════════════════════════════════
# Query functions
# ═══════════════════════════════════════════════════════════════════════════


class TestQueryFunctions:
    """Public query functions used by other modules."""

    def _complete_assessment(self, world, ship, enemy_id="e1"):
        glops.start_assessment(enemy_id, world, ship)
        _tick(world, ship, 21.0)

    def test_get_vulnerable_facing_none_by_default(self):
        assert glops.get_vulnerable_facing("e1") is None

    def test_get_priority_subsystem_none_by_default(self):
        assert glops.get_priority_subsystem("e1") is None

    def test_get_threat_level_default(self):
        assert glops.get_threat_level("e1") == "low"

    def test_get_prediction_bonus_no_prediction(self):
        assert glops.get_prediction_accuracy_bonus("e1", 0.0, 0.0) == 0.0
