"""Tests for v0.07-2.3: Frigate Modular Equipment Bays.

Covers: module registry, validation, stat application, has_module queries,
cloaking device, mining equipment, subsystem integrations, save/resume, debrief.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import server.equipment_modules as gleq
import server.game_loop_ew as glew
import server.game_loop_mining as glmn
from server.models.ship import Ship
from server.systems import sensors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_ship(**overrides) -> Ship:
    """Create a Ship with sensible defaults for testing."""
    kwargs = {"x": 50_000.0, "y": 50_000.0}
    kwargs.update(overrides)
    return Ship(**kwargs)


@dataclass
class FakeAsteroid:
    id: str = "ast_1"
    x: float = 50_500.0
    y: float = 50_500.0
    radius: float = 500.0


@dataclass
class FakeWorld:
    asteroids: list = field(default_factory=list)
    enemies: list = field(default_factory=list)
    torpedoes: list = field(default_factory=list)
    stations: list = field(default_factory=list)
    hazards: list = field(default_factory=list)
    creatures: list = field(default_factory=list)


# ===========================================================================
# Registry tests
# ===========================================================================


class TestRegistry:
    def test_nine_modules_defined(self):
        assert len(gleq.MODULES) == 9

    def test_all_modules_have_required_fields(self):
        for mid, m in gleq.MODULES.items():
            assert "id" in m
            assert "name" in m
            assert "description" in m
            assert "station_benefit" in m
            assert m["id"] == mid

    def test_valid_ids_match_module_keys(self):
        assert gleq.VALID_MODULE_IDS == frozenset(gleq.MODULES.keys())

    def test_max_modules_frigate_is_two(self):
        assert gleq.get_max_modules("frigate") == 2

    def test_max_modules_other_classes_zero(self):
        for cls in ("scout", "corvette", "cruiser", "battleship", "medical_ship", "carrier"):
            assert gleq.get_max_modules(cls) == 0


# ===========================================================================
# Validation tests
# ===========================================================================


class TestValidation:
    def test_valid_two_modules(self):
        ok, err = gleq.validate_modules("frigate", ["armour_plating", "cargo_hold"])
        assert ok
        assert err == ""

    def test_empty_valid(self):
        ok, err = gleq.validate_modules("frigate", [])
        assert ok

    def test_non_frigate_empty_ok(self):
        ok, err = gleq.validate_modules("scout", [])
        assert ok

    def test_too_many_rejected(self):
        ok, err = gleq.validate_modules("frigate", ["armour_plating", "cargo_hold", "cloaking_device"])
        assert not ok
        assert "Too many" in err

    def test_duplicate_rejected(self):
        ok, err = gleq.validate_modules("frigate", ["armour_plating", "armour_plating"])
        assert not ok
        assert "Duplicate" in err

    def test_invalid_id_rejected(self):
        ok, err = gleq.validate_modules("frigate", ["nonexistent_module"])
        assert not ok
        assert "Unknown" in err

    def test_non_frigate_with_modules_rejected(self):
        ok, err = gleq.validate_modules("scout", ["armour_plating"])
        assert not ok
        assert "cannot equip" in err


# ===========================================================================
# Apply modules — stat changes
# ===========================================================================


class TestApplyModules:
    def setup_method(self):
        gleq.reset()

    def test_extra_torpedo_magazine_adds_tube(self):
        ship = _fresh_ship()
        original = ship.torpedo_tube_count
        gleq.apply_modules(ship, ["extra_torpedo_magazine"])
        assert ship.torpedo_tube_count == original + 1

    def test_enhanced_sensor_array_increases_range(self):
        ship = _fresh_ship()
        original = ship.sensor_range_base
        gleq.apply_modules(ship, ["enhanced_sensor_array"])
        assert ship.sensor_range_base == pytest.approx(original * 1.3, rel=1e-6)

    def test_armour_plating_stats(self):
        ship = _fresh_ship()
        orig_armour = ship.armour
        orig_hull = ship.hull
        orig_speed = ship.max_speed_base
        gleq.apply_modules(ship, ["armour_plating"])
        assert ship.armour == orig_armour + 15.0
        assert ship.armour_max == orig_armour + 15.0
        assert ship.hull == orig_hull + 20.0
        assert ship.hull_max == orig_hull + 20.0
        assert ship.max_speed_base == pytest.approx(orig_speed * 0.9, rel=1e-6)

    def test_cargo_hold(self):
        ship = _fresh_ship()
        orig_fuel = ship.fuel_multiplier
        gleq.apply_modules(ship, ["cargo_hold"])
        assert ship.cargo_capacity == 100.0
        assert ship.fuel_multiplier == pytest.approx(orig_fuel * 1.5, rel=1e-6)

    def test_cloaking_no_direct_stat_change(self):
        ship = _fresh_ship()
        orig_hull = ship.hull
        gleq.apply_modules(ship, ["cloaking_device"])
        assert ship.hull == orig_hull  # no stat changes

    def test_marine_barracks_no_direct_stat_change(self):
        ship = _fresh_ship()
        orig_hull = ship.hull
        gleq.apply_modules(ship, ["marine_barracks"])
        assert ship.hull == orig_hull

    def test_drone_hangar_no_direct_stat_change(self):
        ship = _fresh_ship()
        orig_hull = ship.hull
        gleq.apply_modules(ship, ["drone_hangar_expansion"])
        assert ship.hull == orig_hull

    def test_medical_ward_no_direct_stat_change(self):
        ship = _fresh_ship()
        orig_hull = ship.hull
        gleq.apply_modules(ship, ["medical_ward_upgrade"])
        assert ship.hull == orig_hull

    def test_mining_no_direct_stat_change(self):
        ship = _fresh_ship()
        orig_hull = ship.hull
        gleq.apply_modules(ship, ["mining_equipment"])
        assert ship.hull == orig_hull


# ===========================================================================
# has_module
# ===========================================================================


class TestHasModule:
    def setup_method(self):
        gleq.reset()

    def test_has_module_after_apply(self):
        ship = _fresh_ship()
        gleq.apply_modules(ship, ["armour_plating", "cargo_hold"])
        assert gleq.has_module("armour_plating")
        assert gleq.has_module("cargo_hold")

    def test_has_module_not_applied(self):
        ship = _fresh_ship()
        gleq.apply_modules(ship, ["armour_plating"])
        assert not gleq.has_module("cargo_hold")

    def test_reset_clears_modules(self):
        ship = _fresh_ship()
        gleq.apply_modules(ship, ["armour_plating"])
        assert gleq.has_module("armour_plating")
        gleq.reset()
        assert not gleq.has_module("armour_plating")


# ===========================================================================
# Cloaking Device
# ===========================================================================


class TestCloakingDevice:
    def setup_method(self):
        glew.reset("frigate")

    def test_enable_cloak_makes_stealth_capable(self):
        assert not glew.is_stealth_capable()
        glew.enable_cloak_module()
        assert glew.is_stealth_capable()
        assert glew.is_cloak_module()

    def test_cloak_activates_like_stealth(self):
        glew.enable_cloak_module()
        result = glew.toggle_stealth(True)
        assert result["ok"]
        assert glew.get_stealth_state() == "activating"

    def test_cloak_max_duration_breaks(self):
        glew.enable_cloak_module()
        ship = _fresh_ship()
        world = FakeWorld()
        # Activate stealth
        glew.toggle_stealth(True)
        # Tick through activation (5s)
        for _ in range(51):
            glew.tick(world, ship, 0.1)
        assert glew.get_stealth_state() == "active"
        # Tick for 60s (600 ticks at 0.1s)
        for _ in range(601):
            glew.tick(world, ship, 0.1)
        assert glew.get_stealth_state() == "deactivating"
        reason = glew.pop_stealth_break_reason()
        assert reason == "overheat"

    def test_overheat_sets_cooldown(self):
        glew.enable_cloak_module()
        ship = _fresh_ship()
        world = FakeWorld()
        glew.toggle_stealth(True)
        # Activate
        for _ in range(51):
            glew.tick(world, ship, 0.1)
        # Run to overheat
        for _ in range(601):
            glew.tick(world, ship, 0.1)
        assert glew.get_cloak_cooldown() > 0.0

    def test_overheat_rejects_reactivation(self):
        glew.enable_cloak_module()
        ship = _fresh_ship()
        world = FakeWorld()
        glew.toggle_stealth(True)
        for _ in range(51):
            glew.tick(world, ship, 0.1)
        for _ in range(601):
            glew.tick(world, ship, 0.1)
        # Finish deactivation
        for _ in range(31):
            glew.tick(world, ship, 0.1)
        assert glew.get_stealth_state() == "inactive"
        # Try to re-engage — should be rejected
        result = glew.toggle_stealth(True)
        assert not result["ok"]
        assert result["reason"] == "overheated"

    def test_cooldown_decays(self):
        glew.enable_cloak_module()
        ship = _fresh_ship()
        world = FakeWorld()
        glew.toggle_stealth(True)
        for _ in range(51):
            glew.tick(world, ship, 0.1)
        for _ in range(601):
            glew.tick(world, ship, 0.1)
        initial_cd = glew.get_cloak_cooldown()
        assert initial_cd > 0.0
        # Tick to decay cooldown
        for _ in range(100):
            glew.tick(world, ship, 0.1)
        assert glew.get_cloak_cooldown() < initial_cd

    def test_cloak_remaining_while_active(self):
        glew.enable_cloak_module()
        ship = _fresh_ship()
        world = FakeWorld()
        glew.toggle_stealth(True)
        for _ in range(51):
            glew.tick(world, ship, 0.1)
        assert glew.get_stealth_state() == "active"
        remaining = glew.get_cloak_remaining()
        assert remaining is not None
        assert remaining > 0.0

    def test_cloak_serialise_round_trip(self):
        glew.enable_cloak_module()
        ship = _fresh_ship()
        world = FakeWorld()
        glew.toggle_stealth(True)
        for _ in range(51):
            glew.tick(world, ship, 0.1)
        state = glew.serialise()
        assert state["cloak_module"] is True
        # Reset and restore
        glew.reset("frigate")
        assert not glew.is_cloak_module()
        glew.deserialise(state)
        assert glew.is_cloak_module()
        assert glew.is_stealth_capable()
        assert glew.get_stealth_state() == "active"


# ===========================================================================
# Mining Equipment
# ===========================================================================


class TestMiningEquipment:
    def setup_method(self):
        glmn.reset(active=False)

    def test_inactive_by_default(self):
        assert not glmn.is_active()

    def test_active_with_module(self):
        glmn.reset(active=True)
        assert glmn.is_active()

    def test_start_rejects_without_module(self):
        ship = _fresh_ship()
        world = FakeWorld(asteroids=[FakeAsteroid()])
        result = glmn.start_mining("ast_1", ship, world)
        assert not result["ok"]
        assert result["reason"] == "not_equipped"

    def test_start_validates_range(self):
        glmn.reset(active=True)
        ship = _fresh_ship()
        # Asteroid far away
        world = FakeWorld(asteroids=[FakeAsteroid(x=90_000.0, y=90_000.0)])
        result = glmn.start_mining("ast_1", ship, world)
        assert not result["ok"]
        assert result["reason"] == "out_of_range"

    def test_start_success(self):
        glmn.reset(active=True)
        ship = _fresh_ship()
        # Asteroid within range (500 units away)
        world = FakeWorld(asteroids=[FakeAsteroid(x=50_300.0, y=50_400.0)])
        result = glmn.start_mining("ast_1", ship, world)
        assert result["ok"]
        assert result["target"] == "ast_1"

    def test_progress_advances(self):
        glmn.reset(active=True)
        ship = _fresh_ship()
        world = FakeWorld(asteroids=[FakeAsteroid(x=50_300.0, y=50_400.0)])
        glmn.start_mining("ast_1", ship, world)
        glmn.tick(ship, world, 1.0)
        state = glmn.build_state()
        assert state["mining_progress"] > 0.0

    def test_completion_yields_resources(self):
        glmn.reset(active=True)
        ship = _fresh_ship(cargo_capacity=100.0)
        world = FakeWorld(asteroids=[FakeAsteroid(x=50_300.0, y=50_400.0)])
        glmn.start_mining("ast_1", ship, world)
        # Tick for 10s (mining beam duration)
        events = []
        for _ in range(101):
            events.extend(glmn.tick(ship, world, 0.1))
        complete_events = [e for e in events if e.get("event") == "mining.complete"]
        assert len(complete_events) == 1
        assert complete_events[0]["fuel"] == glmn.MINING_YIELD_FUEL
        assert complete_events[0]["materials"] == glmn.MINING_YIELD_MATERIALS

    def test_cooldown_after_completion(self):
        glmn.reset(active=True)
        ship = _fresh_ship(cargo_capacity=100.0)
        world = FakeWorld(asteroids=[FakeAsteroid(x=50_300.0, y=50_400.0)])
        glmn.start_mining("ast_1", ship, world)
        for _ in range(101):
            glmn.tick(ship, world, 0.1)
        state = glmn.build_state()
        assert state["mining_cooldown"] > 0.0
        # Can't start again during cooldown
        result = glmn.start_mining("ast_1", ship, world)
        assert not result["ok"]
        assert result["reason"] == "cooldown"

    def test_cargo_filled_on_completion(self):
        glmn.reset(active=True)
        ship = _fresh_ship(cargo_capacity=100.0)
        world = FakeWorld(asteroids=[FakeAsteroid(x=50_300.0, y=50_400.0)])
        glmn.start_mining("ast_1", ship, world)
        for _ in range(101):
            glmn.tick(ship, world, 0.1)
        assert ship.cargo.get("fuel", 0) > 0
        assert ship.cargo.get("materials", 0) > 0

    def test_cancel_mining(self):
        glmn.reset(active=True)
        ship = _fresh_ship()
        world = FakeWorld(asteroids=[FakeAsteroid(x=50_300.0, y=50_400.0)])
        glmn.start_mining("ast_1", ship, world)
        result = glmn.cancel_mining()
        assert result["ok"]
        state = glmn.build_state()
        assert state["target_asteroid_id"] is None

    def test_mining_serialise_round_trip(self):
        glmn.reset(active=True)
        ship = _fresh_ship(cargo_capacity=100.0)
        world = FakeWorld(asteroids=[FakeAsteroid(x=50_300.0, y=50_400.0)])
        glmn.start_mining("ast_1", ship, world)
        glmn.tick(ship, world, 1.0)
        state = glmn.serialise()
        assert state["mining_active"] is True
        assert state["target_asteroid_id"] == "ast_1"
        # Reset and restore
        glmn.reset()
        assert not glmn.is_active()
        glmn.deserialise(state)
        assert glmn.is_active()
        new_state = glmn.build_state()
        assert new_state["target_asteroid_id"] == "ast_1"
        assert new_state["mining_progress"] > 0.0

    def test_out_of_range_cancels(self):
        glmn.reset(active=True)
        ship = _fresh_ship()
        world = FakeWorld(asteroids=[FakeAsteroid(x=50_300.0, y=50_400.0)])
        glmn.start_mining("ast_1", ship, world)
        # Move asteroid far away
        world.asteroids[0].x = 90_000.0
        world.asteroids[0].y = 90_000.0
        events = glmn.tick(ship, world, 0.1)
        cancel_events = [e for e in events if e.get("event") == "mining.cancelled"]
        assert len(cancel_events) == 1
        assert cancel_events[0]["reason"] == "out_of_range"

    def test_target_lost_cancels(self):
        glmn.reset(active=True)
        ship = _fresh_ship()
        world = FakeWorld(asteroids=[FakeAsteroid(x=50_300.0, y=50_400.0)])
        glmn.start_mining("ast_1", ship, world)
        # Remove asteroid
        world.asteroids.clear()
        events = glmn.tick(ship, world, 0.1)
        cancel_events = [e for e in events if e.get("event") == "mining.cancelled"]
        assert len(cancel_events) == 1
        assert cancel_events[0]["reason"] == "target_lost"


# ===========================================================================
# Sensor scan speed modifier
# ===========================================================================


class TestSensorScanSpeed:
    def setup_method(self):
        sensors.reset()

    def test_default_modifier_is_one(self):
        assert sensors.get_scan_speed_modifier() == 1.0

    def test_set_modifier(self):
        sensors.set_scan_speed_modifier(0.8)
        assert sensors.get_scan_speed_modifier() == 0.8

    def test_reset_clears_modifier(self):
        sensors.set_scan_speed_modifier(0.5)
        sensors.reset()
        assert sensors.get_scan_speed_modifier() == 1.0

    def test_faster_scan_with_modifier(self):
        """Enhanced sensor array (0.8 modifier) should complete scans 20% faster."""
        from server.models.world import Enemy, World, ENEMY_TYPE_PARAMS

        ship = _fresh_ship()
        enemy = Enemy(id="e1", type="scout", x=50_100.0, y=50_100.0,
                      heading=0.0, velocity=0.0, hull=40.0,
                      shield_front=20.0, shield_rear=20.0)
        world = World(width=100_000, height=100_000)
        world.enemies.append(enemy)

        # Normal scan time
        sensors.reset()
        sensors.start_scan("e1")
        normal_ticks = 0
        while True:
            completed = sensors.tick(world, ship, 0.1)
            normal_ticks += 1
            if completed:
                break

        # Fast scan time (0.8 modifier)
        sensors.reset()
        sensors.set_scan_speed_modifier(0.8)
        sensors.start_scan("e1")
        fast_ticks = 0
        while True:
            completed = sensors.tick(world, ship, 0.1)
            fast_ticks += 1
            if completed:
                break

        # Fast should complete in fewer ticks
        assert fast_ticks < normal_ticks


# ===========================================================================
# Medical ward upgrade integration
# ===========================================================================


class TestMedicalWardUpgrade:
    def test_set_get_quarantine_slots(self):
        import server.game_loop_medical_v2 as glmed
        glmed.reset()
        assert glmed.get_quarantine_slots() == 2  # default
        glmed.set_quarantine_slots(5)
        assert glmed.get_quarantine_slots() == 5


# ===========================================================================
# Marine barracks integration
# ===========================================================================


class TestMarineBarracks:
    def test_add_extra_marine_squad(self):
        import server.game_loop_security as gls
        gls.reset()
        gls.init_marine_teams("frigate")
        initial_count = len(gls.get_marine_teams())
        team = gls.add_extra_marine_squad()
        assert team is not None
        assert len(gls.get_marine_teams()) == initial_count + 1
        assert team.name == "Charlie Squad"

    def test_add_extra_marine_squad_max_capped(self):
        """Cannot exceed 3 teams (TEAM_NAMES limit)."""
        import server.game_loop_security as gls
        gls.reset()
        # Frigate has 2 teams by default
        gls.init_marine_teams("frigate")
        # Add one more (Charlie) — should succeed
        team1 = gls.add_extra_marine_squad()
        assert team1 is not None
        # Try to add a 4th — should fail
        team2 = gls.add_extra_marine_squad()
        assert team2 is None
        assert len(gls.get_marine_teams()) == 3


# ===========================================================================
# Drone hangar expansion integration
# ===========================================================================


class TestDroneHangarExpansion:
    def test_apply_hangar_expansion(self):
        import server.game_loop_flight_ops as glfo
        glfo.reset("frigate")
        initial_slots = glfo.get_flight_deck().hangar_slots
        initial_drones = len(glfo.get_drones())
        glfo.apply_hangar_expansion()
        assert glfo.get_flight_deck().hangar_slots == initial_slots + 2
        assert len(glfo.get_drones()) == initial_drones + 1
        # New drone should be combat type
        new_drone = glfo.get_drones()[-1]
        assert new_drone.drone_type == "combat"


# ===========================================================================
# Lobby validation integration
# ===========================================================================


class TestLobbyPayload:
    def test_lobby_payload_includes_modules(self):
        from server.models.messages.lobby import LobbyStartGamePayload
        payload = LobbyStartGamePayload(
            mission_id="sandbox",
            equipment_modules=["armour_plating", "cargo_hold"],
        )
        assert payload.equipment_modules == ["armour_plating", "cargo_hold"]

    def test_lobby_payload_defaults_empty(self):
        from server.models.messages.lobby import LobbyStartGamePayload
        payload = LobbyStartGamePayload(mission_id="sandbox")
        assert payload.equipment_modules == []


# ===========================================================================
# Save / Resume
# ===========================================================================


class TestSaveResume:
    def test_equipment_modules_serialise_round_trip(self):
        gleq.reset()
        ship = _fresh_ship()
        gleq.apply_modules(ship, ["armour_plating", "cargo_hold"])
        state = gleq.serialise()
        assert state["active_modules"] == ["armour_plating", "cargo_hold"]
        gleq.reset()
        assert not gleq.has_module("armour_plating")
        gleq.deserialise(state)
        assert gleq.has_module("armour_plating")
        assert gleq.has_module("cargo_hold")

    def test_cargo_round_trip(self):
        ship = _fresh_ship(cargo_capacity=100.0)
        ship.cargo = {"fuel": 30.0, "materials": 15.0}
        # Simulate serialise
        data = {
            "cargo_capacity": ship.cargo_capacity,
            "cargo": dict(ship.cargo),
        }
        # Restore
        ship2 = _fresh_ship()
        ship2.cargo_capacity = float(data["cargo_capacity"])
        ship2.cargo = dict(data["cargo"])
        assert ship2.cargo_capacity == 100.0
        assert ship2.cargo == {"fuel": 30.0, "materials": 15.0}

    def test_mining_serialise_round_trip(self):
        glmn.reset(active=True)
        ship = _fresh_ship(cargo_capacity=100.0)
        world = FakeWorld(asteroids=[FakeAsteroid(x=50_300.0, y=50_400.0)])
        glmn.start_mining("ast_1", ship, world)
        glmn.tick(ship, world, 2.0)
        state = glmn.serialise()
        glmn.reset()
        glmn.deserialise(state)
        restored = glmn.build_state()
        assert restored["mining_active"] is True
        assert restored["mining_progress"] > 0.0

    def test_cloak_state_round_trip(self):
        glew.reset("frigate")
        glew.enable_cloak_module()
        ship = _fresh_ship()
        world = FakeWorld()
        glew.toggle_stealth(True)
        for _ in range(51):
            glew.tick(world, ship, 0.1)
        state = glew.serialise()
        glew.reset("frigate")
        glew.deserialise(state)
        assert glew.is_cloak_module()
        assert glew.get_stealth_state() == "active"

    def test_module_names_in_debrief(self):
        gleq.reset()
        ship = _fresh_ship()
        gleq.apply_modules(ship, ["armour_plating", "mining_equipment"])
        names = gleq.get_module_names()
        assert "Armour Plating" in names
        assert "Mining Equipment" in names


# ===========================================================================
# EW build_state includes cloak fields
# ===========================================================================


class TestEWBuildState:
    def test_build_state_includes_cloak_fields(self):
        glew.reset("frigate")
        glew.enable_cloak_module()
        ship = _fresh_ship()
        world = FakeWorld()
        state = glew.build_state(world, ship)
        assert "cloak_module" in state
        assert state["cloak_module"] is True
        assert "cloak_remaining" in state
        assert "cloak_cooldown" in state

    def test_build_state_cloak_remaining_none_when_inactive(self):
        glew.reset("frigate")
        glew.enable_cloak_module()
        ship = _fresh_ship()
        world = FakeWorld()
        state = glew.build_state(world, ship)
        assert state["cloak_remaining"] is None

    def test_build_state_cloak_remaining_set_when_active(self):
        glew.reset("frigate")
        glew.enable_cloak_module()
        ship = _fresh_ship()
        world = FakeWorld()
        glew.toggle_stealth(True)
        for _ in range(51):
            glew.tick(world, ship, 0.1)
        state = glew.build_state(world, ship)
        assert state["cloak_remaining"] is not None
        assert state["cloak_remaining"] > 0


# ===========================================================================
# Module get_active_modules
# ===========================================================================


class TestGetActiveModules:
    def test_get_active_modules_returns_copy(self):
        gleq.reset()
        ship = _fresh_ship()
        gleq.apply_modules(ship, ["armour_plating"])
        mods = gleq.get_active_modules()
        mods.append("fake")
        assert "fake" not in gleq.get_active_modules()


# ===========================================================================
# Multiple modules combined
# ===========================================================================


class TestCombinedModules:
    def test_two_modules_both_apply(self):
        gleq.reset()
        ship = _fresh_ship()
        orig_armour = ship.armour
        orig_fuel = ship.fuel_multiplier
        gleq.apply_modules(ship, ["armour_plating", "cargo_hold"])
        assert ship.armour == orig_armour + 15.0
        assert ship.cargo_capacity == 100.0
        assert ship.fuel_multiplier == pytest.approx(orig_fuel * 1.5, rel=1e-6)
        assert gleq.has_module("armour_plating")
        assert gleq.has_module("cargo_hold")
