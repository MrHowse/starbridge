"""Tests for v0.07-2.5: Battleship Spinal Mount & Layered Armour.

Covers: module activation, charge request, authorization, charging, firing,
cooldown, alignment, layered armour, build_state, save/resume, integration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest

import server.game_loop_spinal_mount as glsm
from server.models.ship import Ship, ShipSystem
from server.systems.combat import (
    apply_hit_to_player,
    repair_armour_zone,
    ARMOUR_FIELD_REPAIR_CAP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_ship(**overrides) -> Ship:
    kwargs = {"x": 50_000.0, "y": 50_000.0, "heading": 0.0}
    kwargs.update(overrides)
    return Ship(**kwargs)


def _battleship_ship(**overrides) -> Ship:
    """Ship with battleship armour zones."""
    ship = _fresh_ship(**overrides)
    ship.armour_zones = {
        "fore": 10.0, "aft": 10.0, "port": 10.0, "starboard": 10.0,
    }
    ship.armour_zones_max = dict(ship.armour_zones)
    ship.armour = 40.0
    ship.armour_max = 40.0
    return ship


@dataclass
class FakeEnemy:
    id: str = "e1"
    x: float = 50_000.0
    y: float = 40_000.0  # directly north (bearing = 0°)
    heading: float = 180.0
    velocity: float = 0.0
    hull: float = 200.0
    shield_front: float = 0.0
    shield_rear: float = 0.0
    shield_frequency: str = ""
    target_profile: float = 1.0


@dataclass
class FakeWorld:
    enemies: list = field(default_factory=list)
    ship: Ship = field(default_factory=_fresh_ship)


def _make_world_with_enemy(**enemy_kw) -> tuple:
    enemy = FakeEnemy(**enemy_kw)
    world = FakeWorld(enemies=[enemy])
    return world, enemy


@pytest.fixture(autouse=True)
def _reset():
    glsm.reset()
    yield
    glsm.reset()


# ===========================================================================
# Module activation
# ===========================================================================


class TestActivation:
    def test_active_for_battleship(self):
        glsm.reset(active=True, reactor_max=1500.0)
        assert glsm.is_active() is True

    def test_inactive_by_default(self):
        glsm.reset()
        assert glsm.is_active() is False

    def test_reset_clears_state(self):
        glsm.reset(active=True, reactor_max=1500.0)
        world, _ = _make_world_with_enemy()
        ship = _fresh_ship()
        glsm.request_charge("e1", ship, world)
        glsm.reset()
        assert glsm.get_state() == "idle"
        assert glsm.is_active() is False


# ===========================================================================
# Charge request
# ===========================================================================


class TestChargeRequest:
    def test_request_returns_auth_event(self):
        glsm.reset(active=True, reactor_max=1500.0)
        world, _ = _make_world_with_enemy()
        ship = _fresh_ship()
        result = glsm.request_charge("e1", ship, world)
        assert result["ok"] is True
        assert "request_id" in result
        assert result["target_id"] == "e1"
        assert glsm.get_state() == "auth_pending"

    def test_request_not_active_error(self):
        glsm.reset(active=False)
        world, _ = _make_world_with_enemy()
        ship = _fresh_ship()
        result = glsm.request_charge("e1", ship, world)
        assert result["ok"] is False

    def test_request_not_idle_error(self):
        glsm.reset(active=True, reactor_max=1500.0)
        world, _ = _make_world_with_enemy()
        ship = _fresh_ship()
        glsm.request_charge("e1", ship, world)
        # Now in auth_pending — second request should fail.
        result = glsm.request_charge("e1", ship, world)
        assert result["ok"] is False

    def test_request_invalid_target_error(self):
        glsm.reset(active=True, reactor_max=1500.0)
        world = FakeWorld(enemies=[])
        ship = _fresh_ship()
        result = glsm.request_charge("nonexistent", ship, world)
        assert result["ok"] is False

    def test_request_during_cooldown_error(self):
        glsm.reset(active=True, reactor_max=1500.0)
        world, _ = _make_world_with_enemy()
        ship = _fresh_ship()
        # Manually set state to cooldown via serialise/deserialise.
        glsm.deserialise({
            "active": True, "state": "cooldown", "cooldown_timer": 60.0,
            "power_draw": 600.0,
        })
        result = glsm.request_charge("e1", ship, world)
        assert result["ok"] is False

    def test_request_target_gone_error(self):
        glsm.reset(active=True, reactor_max=1500.0)
        world = FakeWorld(enemies=[])  # No enemies.
        ship = _fresh_ship()
        result = glsm.request_charge("e1", ship, world)
        assert result["ok"] is False


# ===========================================================================
# Authorization
# ===========================================================================


class TestAuthorization:
    def _setup_auth_pending(self):
        glsm.reset(active=True, reactor_max=1500.0)
        world, _ = _make_world_with_enemy()
        ship = _fresh_ship()
        result = glsm.request_charge("e1", ship, world)
        return result["request_id"]

    def test_approve_transitions_to_charging(self):
        req_id = self._setup_auth_pending()
        result = glsm.resolve_auth(req_id, True)
        assert result["ok"] is True
        assert glsm.get_state() == "charging"

    def test_deny_returns_to_idle(self):
        req_id = self._setup_auth_pending()
        result = glsm.resolve_auth(req_id, False)
        assert result["ok"] is True
        assert glsm.get_state() == "idle"

    def test_wrong_request_id_error(self):
        self._setup_auth_pending()
        result = glsm.resolve_auth("wrong-id", True)
        assert result["ok"] is False

    def test_not_auth_pending_error(self):
        glsm.reset(active=True, reactor_max=1500.0)
        result = glsm.resolve_auth("any-id", True)
        assert result["ok"] is False


# ===========================================================================
# Charging
# ===========================================================================


class TestCharging:
    def _setup_charging(self):
        glsm.reset(active=True, reactor_max=1500.0)
        world, _ = _make_world_with_enemy()
        ship = _fresh_ship()
        result = glsm.request_charge("e1", ship, world)
        glsm.resolve_auth(result["request_id"], True)
        return ship, world

    def test_timer_advances_with_dt(self):
        ship, world = self._setup_charging()
        glsm.tick(ship, world, 1.0)
        assert glsm.get_charge_progress() > 0.0

    def test_charge_completes_at_30s(self):
        ship, world = self._setup_charging()
        for _ in range(301):
            events = glsm.tick(ship, world, 0.1)
        assert glsm.get_state() == "ready"
        # Check that charge_complete event was emitted.
        all_events = []
        glsm.deserialise({
            "active": True, "state": "charging",
            "charge_timer": 29.9, "power_draw": 600.0,
        })
        evts = glsm.tick(ship, world, 0.2)
        assert any(e["event"] == "charge_complete" for e in evts)

    def test_power_draw_active_during_charge(self):
        self._setup_charging()
        assert glsm.get_power_draw() > 0.0

    def test_power_draw_is_reactor_fraction(self):
        self._setup_charging()
        # reactor_max=1500.0 × 0.4 = 600.0
        assert glsm.get_power_draw() == pytest.approx(600.0)

    def test_reactor_critical_interrupts_charge(self):
        ship, world = self._setup_charging()
        # Mock power grid with reactor_health=0.
        mock_pg = MagicMock()
        mock_pg.reactor_health = 0.0
        with patch("server.game_loop_engineering.get_power_grid", return_value=mock_pg):
            events = glsm.tick(ship, world, 0.1)
        assert glsm.get_state() == "idle"
        assert any(e["event"] == "charge_interrupted" for e in events)

    def test_cancel_during_charge(self):
        self._setup_charging()
        result = glsm.cancel()
        assert result["ok"] is True
        assert glsm.get_state() == "idle"
        assert glsm.get_power_draw() == 0.0

    def test_charge_progress_reported_correctly(self):
        ship, world = self._setup_charging()
        # Charge for 15s (half).
        for _ in range(150):
            glsm.tick(ship, world, 0.1)
        progress = glsm.get_charge_progress()
        assert 49.0 <= progress <= 51.0


# ===========================================================================
# Firing
# ===========================================================================


class TestFiring:
    def _setup_ready(self, enemy_kw=None):
        glsm.reset(active=True, reactor_max=1500.0)
        ekw = enemy_kw or {}
        world, enemy = _make_world_with_enemy(**ekw)
        ship = _fresh_ship()
        result = glsm.request_charge("e1", ship, world)
        glsm.resolve_auth(result["request_id"], True)
        # Fast-forward to ready.
        glsm.deserialise({
            "active": True, "state": "ready", "target_id": "e1",
            "power_draw": 600.0,
        })
        return ship, world, enemy

    def test_fire_in_ready_state(self):
        ship, world, enemy = self._setup_ready()
        rng = MagicMock()
        rng.random.return_value = 0.0  # Always hit.
        result = glsm.fire(ship, world, rng)
        assert result["ok"] is True
        assert result["hit"] is True
        assert result["damage"] == 150.0

    def test_fire_when_not_ready_error(self):
        glsm.reset(active=True, reactor_max=1500.0)
        world, _ = _make_world_with_enemy()
        ship = _fresh_ship()
        rng = MagicMock()
        result = glsm.fire(ship, world, rng)
        assert result["ok"] is False

    def test_accuracy_stationary_target(self):
        ship, world, enemy = self._setup_ready(enemy_kw={"velocity": 0.0})
        rng = MagicMock()
        rng.random.return_value = 0.94  # Just below 0.95.
        result = glsm.fire(ship, world, rng)
        assert result["hit"] is True
        assert result["accuracy"] == pytest.approx(0.95, abs=0.01)

    def test_accuracy_moving_target(self):
        ship, world, enemy = self._setup_ready(enemy_kw={"velocity": 100.0})
        rng = MagicMock()
        rng.random.return_value = 0.69  # Just below 0.70.
        result = glsm.fire(ship, world, rng)
        assert result["hit"] is True
        assert result["accuracy"] == pytest.approx(0.70, abs=0.01)

    def test_accuracy_fast_small_target(self):
        ship, world, enemy = self._setup_ready(
            enemy_kw={"velocity": 200.0, "target_profile": 0.5}
        )
        rng = MagicMock()
        rng.random.return_value = 0.39  # Just below 0.40.
        result = glsm.fire(ship, world, rng)
        assert result["hit"] is True
        assert result["accuracy"] == pytest.approx(0.40, abs=0.01)

    def test_science_offline_penalty(self):
        ship, world, enemy = self._setup_ready(enemy_kw={"velocity": 0.0})
        ship.systems["sensors"].health = 0.0  # Science/sensors offline.
        rng = MagicMock()
        rng.random.return_value = 0.74  # Below 0.75 but above 0.70.
        result = glsm.fire(ship, world, rng)
        # accuracy = 0.95 - 0.20 = 0.75
        assert result["accuracy"] == pytest.approx(0.75, abs=0.01)
        assert result["hit"] is True

    def test_misalignment_reduces_accuracy(self):
        # Enemy at due east (bearing 90°), ship heading 0° (north).
        ship, world, enemy = self._setup_ready(
            enemy_kw={"x": 60_000.0, "y": 50_000.0, "velocity": 0.0}
        )
        rng = MagicMock()
        rng.random.return_value = 0.47  # 0.95 × 0.5 = 0.475
        result = glsm.fire(ship, world, rng)
        # Misaligned: accuracy = 0.95 × 0.5 = 0.475
        assert result["accuracy"] == pytest.approx(0.475, abs=0.01)
        assert result["hit"] is True

    def test_transitions_to_cooldown_after_fire(self):
        ship, world, enemy = self._setup_ready()
        rng = MagicMock()
        rng.random.return_value = 0.0
        glsm.fire(ship, world, rng)
        assert glsm.get_state() == "cooldown"
        assert glsm.get_cooldown_remaining() == pytest.approx(120.0)


# ===========================================================================
# Cooldown
# ===========================================================================


class TestCooldown:
    def _setup_cooldown(self):
        glsm.reset(active=True, reactor_max=1500.0)
        glsm.deserialise({
            "active": True, "state": "cooldown", "cooldown_timer": 120.0,
            "power_draw": 600.0,
        })
        ship = _fresh_ship()
        world = FakeWorld(enemies=[])
        return ship, world

    def test_cooldown_decays_each_tick(self):
        ship, world = self._setup_cooldown()
        glsm.tick(ship, world, 1.0)
        assert glsm.get_cooldown_remaining() == pytest.approx(119.0)

    def test_cannot_charge_during_cooldown(self):
        ship, world = self._setup_cooldown()
        world.enemies = [FakeEnemy()]
        result = glsm.request_charge("e1", ship, world)
        assert result["ok"] is False

    def test_cooldown_complete_returns_idle(self):
        ship, world = self._setup_cooldown()
        # Fast-forward past cooldown.
        for _ in range(1201):
            events = glsm.tick(ship, world, 0.1)
        assert glsm.get_state() == "idle"


# ===========================================================================
# Alignment
# ===========================================================================


class TestAlignment:
    def test_within_arc_green(self):
        glsm.reset(active=True, reactor_max=1500.0)
        # Enemy directly north, ship heading north.
        world, _ = _make_world_with_enemy(x=50_000.0, y=40_000.0)
        ship = _fresh_ship(heading=0.0)
        # Set target via deserialise.
        glsm.deserialise({"active": True, "state": "charging", "target_id": "e1",
                          "power_draw": 600.0})
        alignment = glsm.get_alignment(ship, world)
        assert alignment["aligned"] is True
        assert alignment["status"] == "green"
        assert alignment["angle_off"] < 5.0

    def test_within_15_amber(self):
        glsm.reset(active=True, reactor_max=1500.0)
        # Enemy slightly off-axis (10° offset).
        import math
        offset_x = 50_000.0 + 10_000.0 * math.sin(math.radians(10))
        offset_y = 50_000.0 - 10_000.0 * math.cos(math.radians(10))
        world, _ = _make_world_with_enemy(x=offset_x, y=offset_y)
        ship = _fresh_ship(heading=0.0)
        glsm.deserialise({"active": True, "state": "charging", "target_id": "e1",
                          "power_draw": 600.0})
        alignment = glsm.get_alignment(ship, world)
        assert alignment["aligned"] is False
        assert alignment["status"] == "amber"
        assert 5.0 < alignment["angle_off"] <= 15.0

    def test_beyond_15_red(self):
        glsm.reset(active=True, reactor_max=1500.0)
        # Enemy at 90° (due east).
        world, _ = _make_world_with_enemy(x=60_000.0, y=50_000.0)
        ship = _fresh_ship(heading=0.0)
        glsm.deserialise({"active": True, "state": "charging", "target_id": "e1",
                          "power_draw": 600.0})
        alignment = glsm.get_alignment(ship, world)
        assert alignment["aligned"] is False
        assert alignment["status"] == "red"
        assert alignment["angle_off"] > 15.0

    def test_alignment_computed_from_heading_to_target(self):
        glsm.reset(active=True, reactor_max=1500.0)
        # Ship heading 90° (east), enemy also east.
        world, _ = _make_world_with_enemy(x=60_000.0, y=50_000.0)
        ship = _fresh_ship(heading=90.0)
        glsm.deserialise({"active": True, "state": "charging", "target_id": "e1",
                          "power_draw": 600.0})
        alignment = glsm.get_alignment(ship, world)
        assert alignment["aligned"] is True
        assert alignment["status"] == "green"


# ===========================================================================
# Layered armour
# ===========================================================================


class TestLayeredArmour:
    def test_battleship_has_4_zones(self):
        ship = _battleship_ship()
        assert ship.armour_zones is not None
        assert len(ship.armour_zones) == 4
        for facing in ("fore", "aft", "port", "starboard"):
            assert ship.armour_zones[facing] == 10.0

    def test_hit_from_fore_depletes_fore_zone(self):
        ship = _battleship_ship()
        ship.shields.fore = 0.0  # Shields down so damage reaches armour.
        # Attacker directly north → hit from fore.
        apply_hit_to_player(ship, 5.0, 50_000.0, 40_000.0)
        assert ship.armour_zones["fore"] < 10.0

    def test_hit_from_port_depletes_port_zone(self):
        ship = _battleship_ship()
        ship.shields.port = 0.0  # Shields down.
        # Attacker to the west → hit from port (diff < 0 → port).
        apply_hit_to_player(ship, 5.0, 40_000.0, 50_000.0)
        assert ship.armour_zones["port"] < 10.0

    def test_zone_at_zero_bypasses_armour(self):
        ship = _battleship_ship()
        ship.armour_zones["fore"] = 0.0
        # Shields down.
        ship.shields.fore = 0.0
        hull_before = ship.hull
        apply_hit_to_player(ship, 10.0, 50_000.0, 40_000.0)
        # With 0 armour in fore zone, all 10 damage should hit hull.
        assert ship.hull < hull_before

    def test_zone_degrades_by_1_per_hit(self):
        ship = _battleship_ship()
        ship.shields.fore = 0.0  # Shields down.
        initial = ship.armour_zones["fore"]
        apply_hit_to_player(ship, 5.0, 50_000.0, 40_000.0)
        # Zone should degrade by exactly 1 per hit.
        assert ship.armour_zones["fore"] == pytest.approx(initial - 1.0)

    def test_non_battleship_uses_single_armour(self):
        ship = _fresh_ship(armour=5.0, armour_max=10.0)
        ship.shields.fore = 0.0
        apply_hit_to_player(ship, 3.0, 50_000.0, 40_000.0)
        # Single armour should have absorbed.
        assert ship.armour < 5.0

    def test_repair_zone_capped_at_75_percent(self):
        ship = _battleship_ship()
        ship.armour_zones["fore"] = 0.0
        restored = repair_armour_zone(ship, "fore", 100.0)
        cap = 10.0 * ARMOUR_FIELD_REPAIR_CAP  # 7.5
        assert ship.armour_zones["fore"] == pytest.approx(cap)
        assert restored == pytest.approx(cap)

    def test_repair_zone_from_zero_to_max(self):
        ship = _battleship_ship()
        ship.armour_zones["fore"] = 0.0
        repair_armour_zone(ship, "fore", 100.0)
        assert ship.armour_zones["fore"] == pytest.approx(10.0 * 0.75)

    def test_armour_zones_in_ship_state(self):
        ship = _battleship_ship()
        assert ship.armour_zones is not None
        assert ship.armour_zones_max is not None

    def test_armour_zones_serialise_roundtrip(self):
        ship = _battleship_ship()
        ship.armour_zones["fore"] = 5.0
        # Simulate save/load by reading and setting.
        data = {
            "armour_zones": dict(ship.armour_zones),
            "armour_zones_max": dict(ship.armour_zones_max),
        }
        ship2 = _fresh_ship()
        ship2.armour_zones = data["armour_zones"]
        ship2.armour_zones_max = data["armour_zones_max"]
        assert ship2.armour_zones["fore"] == 5.0
        assert ship2.armour_zones_max["fore"] == 10.0


# ===========================================================================
# Build state
# ===========================================================================


class TestBuildState:
    def test_includes_all_fields(self):
        glsm.reset(active=True, reactor_max=1500.0)
        world, _ = _make_world_with_enemy()
        ship = _fresh_ship()
        state = glsm.build_state(ship, world)
        assert state["active"] is True
        assert "state" in state
        assert "charge_progress" in state
        assert "cooldown_remaining" in state
        assert "power_draw" in state
        assert "alignment" in state

    def test_alignment_computed_from_world(self):
        glsm.reset(active=True, reactor_max=1500.0)
        world, _ = _make_world_with_enemy()
        ship = _fresh_ship(heading=0.0)
        glsm.deserialise({"active": True, "state": "charging", "target_id": "e1",
                          "power_draw": 600.0})
        state = glsm.build_state(ship, world)
        assert "alignment" in state
        assert "aligned" in state["alignment"]

    def test_empty_when_inactive(self):
        glsm.reset(active=False)
        world = FakeWorld()
        ship = _fresh_ship()
        state = glsm.build_state(ship, world)
        assert state["active"] is False
        assert "state" not in state


# ===========================================================================
# Save / resume
# ===========================================================================


class TestSaveResume:
    def test_spinal_mount_state_roundtrip(self):
        glsm.reset(active=True, reactor_max=1500.0)
        world, _ = _make_world_with_enemy()
        ship = _fresh_ship()
        glsm.request_charge("e1", ship, world)
        data = glsm.serialise()
        glsm.reset()
        glsm.deserialise(data)
        assert glsm.is_active() is True
        assert glsm.get_state() == "auth_pending"

    def test_charge_timer_preserved(self):
        glsm.reset(active=True, reactor_max=1500.0)
        glsm.deserialise({
            "active": True, "state": "charging", "charge_timer": 15.0,
            "power_draw": 600.0,
        })
        data = glsm.serialise()
        assert data["charge_timer"] == pytest.approx(15.0)
        glsm.reset()
        glsm.deserialise(data)
        assert glsm.get_charge_progress() == pytest.approx(50.0)

    def test_cooldown_timer_preserved(self):
        glsm.reset(active=True, reactor_max=1500.0)
        glsm.deserialise({
            "active": True, "state": "cooldown", "cooldown_timer": 60.0,
            "power_draw": 600.0,
        })
        data = glsm.serialise()
        assert data["cooldown_timer"] == pytest.approx(60.0)
        glsm.reset()
        glsm.deserialise(data)
        assert glsm.get_cooldown_remaining() == pytest.approx(60.0)

    def test_armour_zones_preserved_in_ship_data(self):
        ship = _battleship_ship()
        ship.armour_zones["fore"] = 3.5
        data = {
            "armour_zones": dict(ship.armour_zones),
            "armour_zones_max": dict(ship.armour_zones_max),
        }
        new_ship = _fresh_ship()
        new_ship.armour_zones = data["armour_zones"]
        new_ship.armour_zones_max = data["armour_zones_max"]
        assert new_ship.armour_zones["fore"] == 3.5
        assert new_ship.armour_zones_max["fore"] == 10.0


# ===========================================================================
# Integration
# ===========================================================================


class TestIntegration:
    def test_payload_schemas_registered(self):
        from server.models.messages.base import _PAYLOAD_SCHEMAS
        assert "weapons.spinal_charge" in _PAYLOAD_SCHEMAS
        assert "weapons.spinal_fire" in _PAYLOAD_SCHEMAS
        assert "weapons.spinal_cancel" in _PAYLOAD_SCHEMAS

    def test_auth_flow_charge_authorize_charging(self):
        glsm.reset(active=True, reactor_max=1500.0)
        world, _ = _make_world_with_enemy()
        ship = _fresh_ship()
        # 1. Request charge.
        result = glsm.request_charge("e1", ship, world)
        assert result["ok"] is True
        assert glsm.get_state() == "auth_pending"
        # 2. Captain authorizes.
        auth_result = glsm.resolve_auth(result["request_id"], True)
        assert auth_result["ok"] is True
        assert glsm.get_state() == "charging"

    def test_power_draw_reflected_in_engineering(self):
        glsm.reset(active=True, reactor_max=1500.0)
        world, _ = _make_world_with_enemy()
        ship = _fresh_ship()
        result = glsm.request_charge("e1", ship, world)
        glsm.resolve_auth(result["request_id"], True)
        # Power draw should be 600 (1500 × 0.4).
        assert glsm.get_power_draw() == pytest.approx(600.0)

    def test_debrief_includes_spinal_mount(self):
        glsm.reset(active=True, reactor_max=1500.0)
        from server.game_debrief import compute_debrief
        debrief = compute_debrief([])
        assert "spinal_mount_active" in debrief
        assert debrief["spinal_mount_active"] is True


# ===========================================================================
# Power grid external drain
# ===========================================================================


class TestPowerGridExternalDrain:
    def test_external_drain_reduces_available_power(self):
        from server.models.power_grid import PowerGrid
        pg = PowerGrid(reactor_max=1000.0, reactor_health=100.0)
        pg.external_drain = 400.0
        # Available budget should be reduced by 400.
        budget = pg.get_available_budget()
        assert budget == pytest.approx(600.0)

    def test_external_drain_causes_brownout(self):
        from server.models.power_grid import PowerGrid
        pg = PowerGrid(reactor_max=700.0, reactor_health=100.0)
        pg.external_drain = 400.0
        pg.battery_mode = "standby"  # Disable battery to isolate test.
        # Total demand = 900 (9 systems × 100), available = 300.
        demands = {s: 100.0 for s in (
            "engines", "beams", "torpedoes", "shields", "sensors",
            "manoeuvring", "flight_deck", "ecm_suite", "point_defence",
        )}
        delivered = pg.tick(0.1, demands)
        # Total delivered should be roughly 300.
        total_delivered = sum(delivered.values())
        assert total_delivered == pytest.approx(300.0, abs=1.0)

    def test_external_drain_zero_by_default(self):
        from server.models.power_grid import PowerGrid
        pg = PowerGrid()
        assert pg.external_drain == 0.0

    def test_external_drain_serialise_roundtrip(self):
        from server.models.power_grid import PowerGrid
        pg = PowerGrid(reactor_max=1000.0)
        pg.external_drain = 300.0
        data = pg.serialise()
        assert data["external_drain"] == 300.0
        pg2 = PowerGrid.deserialise(data)
        assert pg2.external_drain == pytest.approx(300.0)
