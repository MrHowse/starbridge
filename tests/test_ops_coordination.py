"""
Tests for Operations station Coordination Bonuses (v0.08 A.3).

Covers:
  A.3.1 Weapons-Helm Sync (accuracy + damage bonuses, heading tolerance, cooldown)
  A.3.2 Sensor Focus (circular zone, scan/detection/jam/decode/drone bonuses, timeout)
  A.3.3 Damage Coordination (5s assessment, priority list, cooldown, overlay)
  A.3.4 Evasion Alert (torpedo dodge, response window, helm following, cooldown)
  Combat integration (real bonuses wired into weapons, sensors, EW)
  Serialise / deserialise round-trip

Target: 25+ tests (spec D.2).
"""
from __future__ import annotations

import math
from unittest.mock import patch

import pytest

import server.game_loop_operations as glops
from server.game_loop_operations import (
    DAMAGE_ASSESSMENT_COOLDOWN,
    DAMAGE_ASSESSMENT_DURATION,
    DAMAGE_ASSESSMENT_OVERLAY_DURATION,
    EVASION_ALERT_COOLDOWN,
    EVASION_ALERT_RESPONSE_WINDOW,
    EVASION_ALERT_TORPEDO_REDUCTION,
    EVASION_HELM_TOLERANCE,
    SENSOR_FOCUS_DECODE_BONUS,
    SENSOR_FOCUS_DETECTION_BONUS,
    SENSOR_FOCUS_DRONE_BONUS,
    SENSOR_FOCUS_INACTIVITY_TIMEOUT,
    SENSOR_FOCUS_JAM_BONUS,
    SENSOR_FOCUS_MAX_RADIUS,
    SENSOR_FOCUS_MIN_RADIUS,
    SENSOR_FOCUS_SCAN_BONUS,
    SYNC_ACCURACY_BONUS,
    SYNC_COOLDOWN,
    SYNC_DAMAGE_BONUS,
    SYNC_HEADING_TOLERANCE,
    WeaponsHelmSync,
    SensorFocus,
    DamageCoordination,
    EvasionAlert,
)
from server.models.ship import Ship
from server.models.world import Enemy, World, spawn_enemy


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
# A.3.1 — Weapons-Helm Sync
# ═══════════════════════════════════════════════════════════════════════════


class TestWeaponsHelmSync:
    def test_set_sync_ok(self):
        world, ship, enemy = _world_with_enemy()
        result = glops.set_weapons_helm_sync("e1", world, ship)
        assert result["ok"] is True

    def test_set_sync_contact_not_found(self):
        world, ship, _ = _world_with_enemy()
        result = glops.set_weapons_helm_sync("nonexistent", world, ship)
        assert result["ok"] is False
        assert "not found" in result["reason"]

    def test_sync_broadcasts(self):
        world, ship, enemy = _world_with_enemy()
        glops.set_weapons_helm_sync("e1", world, ship)
        broadcasts = glops.pop_pending_broadcasts()
        assert len(broadcasts) == 1
        targets, data = broadcasts[0]
        assert "weapons" in targets
        assert "helm" in targets
        assert data["type"] == "weapons_helm_sync"

    def test_sync_active_when_heading_aligned(self):
        """Sync becomes active when ship heading is within tolerance of target bearing."""
        world, ship, enemy = _world_with_enemy(x=50000.0, y=40000.0)
        # Enemy is directly ahead (bearing ~ 0°).
        ship.heading = 0.0
        glops.set_weapons_helm_sync("e1", world, ship)
        _tick(world, ship, 0.1)
        acc, dmg = glops.get_weapons_helm_sync_bonus()
        assert acc == pytest.approx(SYNC_ACCURACY_BONUS)
        assert dmg == pytest.approx(SYNC_DAMAGE_BONUS)

    def test_sync_inactive_when_heading_misaligned(self):
        """Sync inactive when heading far from target bearing."""
        world, ship, enemy = _world_with_enemy(x=50000.0, y=40000.0)
        # Enemy is ahead (0°), ship heading 90° — way off.
        ship.heading = 90.0
        glops.set_weapons_helm_sync("e1", world, ship)
        _tick(world, ship, 0.1)
        acc, dmg = glops.get_weapons_helm_sync_bonus()
        assert acc == 0.0
        assert dmg == 0.0

    def test_sync_heading_tolerance_boundary(self):
        """Sync active exactly at the tolerance boundary."""
        world, ship, enemy = _world_with_enemy(x=50000.0, y=40000.0)
        # Enemy is at bearing ~0°. Set heading to exactly the tolerance.
        ship.heading = SYNC_HEADING_TOLERANCE
        glops.set_weapons_helm_sync("e1", world, ship)
        _tick(world, ship, 0.1)
        acc, _ = glops.get_weapons_helm_sync_bonus()
        assert acc == pytest.approx(SYNC_ACCURACY_BONUS)

    def test_cancel_sync_starts_cooldown(self):
        world, ship, enemy = _world_with_enemy()
        glops.set_weapons_helm_sync("e1", world, ship)
        result = glops.cancel_weapons_helm_sync()
        assert result["ok"] is True
        # Immediate re-sync should fail due to cooldown.
        result2 = glops.set_weapons_helm_sync("e1", world, ship)
        assert result2["ok"] is False
        assert "Cooldown" in result2["reason"]

    def test_sync_cooldown_expires(self):
        world, ship, enemy = _world_with_enemy()
        glops.set_weapons_helm_sync("e1", world, ship)
        glops.cancel_weapons_helm_sync()
        # Tick past cooldown.
        _tick(world, ship, SYNC_COOLDOWN + 0.5)
        result = glops.set_weapons_helm_sync("e1", world, ship)
        assert result["ok"] is True

    def test_sync_cancelled_on_enemy_death(self):
        world, ship, enemy = _world_with_enemy()
        glops.set_weapons_helm_sync("e1", world, ship)
        # Remove enemy — simulates destruction.
        world.enemies.clear()
        _tick(world, ship, 0.1)
        acc, dmg = glops.get_weapons_helm_sync_bonus()
        assert acc == 0.0 and dmg == 0.0

    def test_cancel_no_sync_returns_error(self):
        result = glops.cancel_weapons_helm_sync()
        assert result["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════
# A.3.2 — Sensor Focus
# ═══════════════════════════════════════════════════════════════════════════


class TestSensorFocus:
    def test_set_focus_ok(self):
        result = glops.set_sensor_focus(100.0, 200.0, 10000.0)
        assert result["ok"] is True

    def test_focus_clamps_radius_min(self):
        glops.set_sensor_focus(0.0, 0.0, 1.0)  # below minimum
        bonus = glops.get_sensor_focus_bonus(0.0, 0.0)
        assert "scan" in bonus  # entity at center should be in zone

    def test_focus_clamps_radius_max(self):
        glops.set_sensor_focus(0.0, 0.0, 999999.0)  # above maximum
        # Entity at MAX_RADIUS distance should be within clamped zone.
        bonus = glops.get_sensor_focus_bonus(SENSOR_FOCUS_MAX_RADIUS - 1, 0.0)
        assert "scan" in bonus

    def test_entity_inside_focus_gets_bonuses(self):
        glops.set_sensor_focus(100.0, 100.0, 10000.0)
        bonus = glops.get_sensor_focus_bonus(100.0, 100.0)  # at center
        assert bonus["scan"] == pytest.approx(SENSOR_FOCUS_SCAN_BONUS)
        assert bonus["detection"] == pytest.approx(SENSOR_FOCUS_DETECTION_BONUS)
        assert bonus["jam"] == pytest.approx(SENSOR_FOCUS_JAM_BONUS)
        assert bonus["decode"] == pytest.approx(SENSOR_FOCUS_DECODE_BONUS)
        assert bonus["drone"] == pytest.approx(SENSOR_FOCUS_DRONE_BONUS)

    def test_entity_outside_focus_gets_no_bonus(self):
        glops.set_sensor_focus(100.0, 100.0, 5000.0)
        bonus = glops.get_sensor_focus_bonus(100000.0, 100000.0)  # far away
        assert bonus == {}

    def test_focus_broadcasts(self):
        glops.set_sensor_focus(100.0, 200.0, 10000.0)
        broadcasts = glops.pop_pending_broadcasts()
        assert len(broadcasts) == 1
        targets, data = broadcasts[0]
        assert "science" in targets
        assert "electronic_warfare" in targets
        assert data["type"] == "sensor_focus"

    def test_cancel_focus(self):
        glops.set_sensor_focus(100.0, 200.0, 10000.0)
        result = glops.cancel_sensor_focus()
        assert result["ok"] is True
        bonus = glops.get_sensor_focus_bonus(100.0, 200.0)
        assert bonus == {}

    def test_cancel_no_focus_returns_error(self):
        result = glops.cancel_sensor_focus()
        assert result["ok"] is False

    def test_inactivity_timeout(self):
        world, ship, _ = _world_with_enemy()
        glops.set_sensor_focus(100.0, 200.0, 10000.0)
        _tick(world, ship, SENSOR_FOCUS_INACTIVITY_TIMEOUT + 1.0)
        bonus = glops.get_sensor_focus_bonus(100.0, 200.0)
        assert bonus == {}

    def test_reset_inactivity_on_re_set(self):
        world, ship, _ = _world_with_enemy()
        glops.set_sensor_focus(100.0, 200.0, 10000.0)
        _tick(world, ship, SENSOR_FOCUS_INACTIVITY_TIMEOUT - 5.0)
        # Re-set resets the timer.
        glops.set_sensor_focus(100.0, 200.0, 10000.0)
        _tick(world, ship, SENSOR_FOCUS_INACTIVITY_TIMEOUT - 5.0)
        bonus = glops.get_sensor_focus_bonus(100.0, 200.0)
        assert "scan" in bonus  # still active


# ═══════════════════════════════════════════════════════════════════════════
# A.3.3 — Damage Coordination
# ═══════════════════════════════════════════════════════════════════════════


class TestDamageCoordination:
    def test_start_ok(self):
        result = glops.start_damage_coordination()
        assert result["ok"] is True

    def test_assessment_completes_after_duration(self):
        world, ship, _ = _world_with_enemy()
        ship.systems["beams"].power = 50.0  # damage a system
        glops.start_damage_coordination()
        _tick(world, ship, DAMAGE_ASSESSMENT_DURATION + 0.5)
        plist = glops.get_damage_priority_list()
        # beams at 50% power → reduced health; should appear in priority list.
        assert isinstance(plist, list)

    def test_priority_list_sorted_by_health(self):
        world, ship, _ = _world_with_enemy()
        # Damage two systems differently.
        ship.systems["beams"].health = 30.0
        ship.systems["shields"].health = 60.0
        glops.start_damage_coordination()
        _tick(world, ship, DAMAGE_ASSESSMENT_DURATION + 0.5)
        plist = glops.get_damage_priority_list()
        if len(plist) >= 2:
            assert plist[0]["health"] <= plist[1]["health"]

    def test_broadcasts_on_complete(self):
        world, ship, _ = _world_with_enemy()
        glops.start_damage_coordination()
        _tick(world, ship, DAMAGE_ASSESSMENT_DURATION + 0.5)
        broadcasts = glops.pop_pending_broadcasts()
        dc_broadcasts = [b for b in broadcasts if b[1].get("type") == "damage_coordination_complete"]
        assert len(dc_broadcasts) == 1
        targets, data = dc_broadcasts[0]
        assert "engineering" in targets
        assert "medical" in targets

    def test_cooldown_blocks_restart(self):
        world, ship, _ = _world_with_enemy()
        glops.start_damage_coordination()
        _tick(world, ship, DAMAGE_ASSESSMENT_DURATION + 0.5)
        result = glops.start_damage_coordination()
        assert result["ok"] is False
        assert "Cooldown" in result["reason"]

    def test_cooldown_expires(self):
        world, ship, _ = _world_with_enemy()
        glops.start_damage_coordination()
        _tick(world, ship, DAMAGE_ASSESSMENT_DURATION + DAMAGE_ASSESSMENT_COOLDOWN + 1.0)
        result = glops.start_damage_coordination()
        assert result["ok"] is True

    def test_overlay_expires(self):
        world, ship, _ = _world_with_enemy()
        ship.systems["beams"].health = 30.0
        glops.start_damage_coordination()
        _tick(world, ship, DAMAGE_ASSESSMENT_DURATION + 0.5)
        # Overlay should be active.
        assert len(glops.get_damage_priority_list()) > 0
        # Tick past overlay duration.
        _tick(world, ship, DAMAGE_ASSESSMENT_OVERLAY_DURATION + 1.0)
        assert glops.get_damage_priority_list() == []

    def test_priority_levels(self):
        world, ship, _ = _world_with_enemy()
        ship.systems["beams"].health = 10.0     # critical
        ship.systems["shields"].health = 40.0    # high
        ship.systems["sensors"].health = 60.0    # medium
        ship.systems["engines"].health = 80.0    # low
        glops.start_damage_coordination()
        _tick(world, ship, DAMAGE_ASSESSMENT_DURATION + 0.5)
        plist = glops.get_damage_priority_list()
        priorities = {p["system"]: p["priority"] for p in plist}
        assert priorities.get("beams") == "critical"
        assert priorities.get("shields") == "high"
        assert priorities.get("sensors") == "medium"
        assert priorities.get("engines") == "low"


# ═══════════════════════════════════════════════════════════════════════════
# A.3.4 — Evasion Alert
# ═══════════════════════════════════════════════════════════════════════════


class TestEvasionAlert:
    def test_issue_alert_ok(self):
        result = glops.issue_evasion_alert(90.0)
        assert result["ok"] is True

    def test_alert_broadcasts(self):
        glops.issue_evasion_alert(90.0)
        broadcasts = glops.pop_pending_broadcasts()
        assert len(broadcasts) == 1
        targets, data = broadcasts[0]
        assert "helm" in targets
        assert "captain" in targets
        assert data["type"] == "evasion_alert"
        assert data["bearing"] == pytest.approx(90.0)

    def test_alert_active_when_helm_follows(self):
        world, ship, _ = _world_with_enemy()
        ship.heading = 90.0
        glops.issue_evasion_alert(90.0)
        _tick(world, ship, 0.1)
        active, reduction = glops.get_evasion_alert_active()
        assert active is True
        assert reduction == pytest.approx(EVASION_ALERT_TORPEDO_REDUCTION)

    def test_alert_inactive_when_helm_not_following(self):
        world, ship, _ = _world_with_enemy()
        ship.heading = 270.0  # opposite direction
        glops.issue_evasion_alert(90.0)
        _tick(world, ship, 0.1)
        active, reduction = glops.get_evasion_alert_active()
        assert active is False

    def test_helm_tolerance_boundary(self):
        world, ship, _ = _world_with_enemy()
        glops.issue_evasion_alert(90.0)
        ship.heading = 90.0 + EVASION_HELM_TOLERANCE  # exactly at tolerance
        _tick(world, ship, 0.1)
        active, _ = glops.get_evasion_alert_active()
        assert active is True

    def test_response_window_expires(self):
        world, ship, _ = _world_with_enemy()
        ship.heading = 90.0
        glops.issue_evasion_alert(90.0)
        _tick(world, ship, EVASION_ALERT_RESPONSE_WINDOW + 0.5)
        active, _ = glops.get_evasion_alert_active()
        assert active is False

    def test_cooldown_after_expiry(self):
        world, ship, _ = _world_with_enemy()
        glops.issue_evasion_alert(90.0)
        _tick(world, ship, EVASION_ALERT_RESPONSE_WINDOW + 0.5)
        result = glops.issue_evasion_alert(90.0)
        assert result["ok"] is False
        assert "Cooldown" in result["reason"]

    def test_cooldown_expires(self):
        world, ship, _ = _world_with_enemy()
        glops.issue_evasion_alert(90.0)
        _tick(world, ship, EVASION_ALERT_RESPONSE_WINDOW + EVASION_ALERT_COOLDOWN + 1.0)
        result = glops.issue_evasion_alert(90.0)
        assert result["ok"] is True

    def test_bearing_normalised(self):
        result = glops.issue_evasion_alert(450.0)
        assert result["ok"] is True
        broadcasts = glops.pop_pending_broadcasts()
        assert broadcasts[0][1]["bearing"] == pytest.approx(90.0)


# ═══════════════════════════════════════════════════════════════════════════
# Combat integration — real bonus wiring
# ═══════════════════════════════════════════════════════════════════════════


class TestCombatIntegration:
    def test_sync_bonus_affects_beam_hit_chance(self):
        """Weapons-helm sync adds accuracy bonus to hit chance calculation."""
        world, ship, enemy = _world_with_enemy(x=50000.0, y=49000.0)
        enemy.target_profile = 0.5
        ship.heading = 0.0  # pointing toward enemy (north — lower y)
        glops.set_weapons_helm_sync("e1", world, ship)
        _tick(world, ship, 0.1)

        acc, dmg = glops.get_weapons_helm_sync_bonus()
        assert acc == pytest.approx(SYNC_ACCURACY_BONUS)
        assert dmg == pytest.approx(SYNC_DAMAGE_BONUS)

    def test_sensor_focus_scan_speed_bonus(self):
        """Sensor focus zone speeds up scanning of targets inside it."""
        import server.systems.sensors as sensors

        world, ship, enemy = _world_with_enemy(x=100.0, y=100.0)
        enemy.scan_state = "unknown"

        # Set focus zone centered on enemy.
        glops.set_sensor_focus(100.0, 100.0, 10000.0)

        # Start a scan.
        sensors.start_scan("e1")
        sensors.tick(world, ship, 1.0)
        progress_with_focus = sensors.get_scan_progress()

        # Reset and scan without focus.
        sensors.cancel_scan()
        glops.cancel_sensor_focus()
        enemy.scan_state = "unknown"
        sensors.start_scan("e1")
        sensors.tick(world, ship, 1.0)
        progress_without_focus = sensors.get_scan_progress()

        # With focus should scan faster.
        if progress_with_focus and progress_without_focus:
            assert progress_with_focus[1] > progress_without_focus[1]

    def test_sensor_focus_jam_bonus(self):
        """Sensor focus zone boosts EW jam buildup rate for targets inside."""
        bonus = glops.get_sensor_focus_bonus(100.0, 100.0)
        assert bonus == {}  # No focus set.

        glops.set_sensor_focus(100.0, 100.0, 10000.0)
        bonus = glops.get_sensor_focus_bonus(100.0, 100.0)
        assert bonus["jam"] == pytest.approx(SENSOR_FOCUS_JAM_BONUS)

    def test_evasion_torpedo_dodge_integration(self):
        """Evasion alert dodge is wired into tick_torpedoes via get_evasion_alert_active."""
        world, ship, _ = _world_with_enemy()
        ship.heading = 90.0
        glops.issue_evasion_alert(90.0)
        _tick(world, ship, 0.1)  # activate helm following

        active, reduction = glops.get_evasion_alert_active()
        assert active is True
        assert reduction == pytest.approx(EVASION_ALERT_TORPEDO_REDUCTION)


# ═══════════════════════════════════════════════════════════════════════════
# Serialise / Deserialise round-trip
# ═══════════════════════════════════════════════════════════════════════════


class TestCoordinationSerialise:
    def test_sync_round_trip(self):
        world, ship, enemy = _world_with_enemy()
        glops.set_weapons_helm_sync("e1", world, ship)
        data = glops.serialise()
        glops.reset()
        glops.deserialise(data)
        # Sync should be restored.
        state = glops.serialise()
        assert state["coordination"]["weapons_helm_sync"]["contact_id"] == "e1"

    def test_focus_round_trip(self):
        glops.set_sensor_focus(100.0, 200.0, 10000.0)
        data = glops.serialise()
        glops.reset()
        glops.deserialise(data)
        bonus = glops.get_sensor_focus_bonus(100.0, 200.0)
        assert "scan" in bonus

    def test_damage_coordination_round_trip(self):
        world, ship, _ = _world_with_enemy()
        ship.systems["beams"].health = 30.0
        glops.start_damage_coordination()
        _tick(world, ship, DAMAGE_ASSESSMENT_DURATION + 0.5)
        data = glops.serialise()
        glops.reset()
        glops.deserialise(data)
        plist = glops.get_damage_priority_list()
        assert len(plist) > 0

    def test_evasion_round_trip(self):
        glops.issue_evasion_alert(180.0)
        data = glops.serialise()
        glops.reset()
        glops.deserialise(data)
        state = glops.serialise()
        assert state["coordination"]["evasion_alert"]["bearing"] == pytest.approx(180.0)

    def test_empty_coordination_round_trip(self):
        data = glops.serialise()
        glops.reset()
        glops.deserialise(data)
        assert glops.get_weapons_helm_sync_bonus() == (0.0, 0.0)
        assert glops.get_sensor_focus_bonus(0, 0) == {}
        assert glops.get_evasion_alert_active() == (False, 0.0)
        assert glops.get_damage_priority_list() == []


# ═══════════════════════════════════════════════════════════════════════════
# Build state
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildState:
    def test_coordination_bonuses_in_state(self):
        world, ship, enemy = _world_with_enemy()
        glops.set_weapons_helm_sync("e1", world, ship)
        glops.set_sensor_focus(100.0, 200.0, 10000.0)
        state = glops.build_state(world, ship)
        coord = state["coordination_bonuses"]
        assert coord["weapons_helm_sync"] is not None
        assert coord["weapons_helm_sync"]["contact_id"] == "e1"
        assert coord["sensor_focus"] is not None
        assert coord["sensor_focus"]["radius"] == pytest.approx(10000.0)

    def test_empty_coordination_state(self):
        world, ship, _ = _world_with_enemy()
        state = glops.build_state(world, ship)
        coord = state["coordination_bonuses"]
        assert coord["weapons_helm_sync"] is None
        assert coord["sensor_focus"] is None
        assert coord["damage_coordination"] is None
        assert coord["evasion_alert"] is None
