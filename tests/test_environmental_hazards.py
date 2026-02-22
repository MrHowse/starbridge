"""Tests for v0.05h Environmental Hazards.

Covers:
  - Constants (all hazard thresholds, damage rates, modifiers)
  - reset_state() clears module-level modifier state
  - Entity hazards: minefield damage, gravity well cap, radiation damage,
    nebula sensor/shield modifiers
  - Sector-type nebula: sensor_modifier from sector properties, shield regen modifier
  - Sector-type asteroid_field: hull damage above throttle threshold, none below
  - Sector-type gravity_well: velocity capped at GRAVITY_WELL_SECTOR_VEL_CAP
  - Sector-type radiation_zone: hull damage with and without shield absorption
  - Modifier getters (get_sensor_modifier, get_shield_regen_modifier, etc.)
  - sensors.sensor_range() hazard_modifier parameter
  - sensors.build_sensor_contacts() hazard_modifier reduces visible range
  - combat.regenerate_shields() hazard_modifier reduces regen
  - ai.tick_enemies() sensor_modifier reduces enemy detect_range
"""
from __future__ import annotations

import pytest

from server.systems import hazards as hz_mod
from server.systems.hazards import (
    ASTEROID_DAMAGE_PER_SEC,
    ASTEROID_THROTTLE_THRESHOLD,
    GRAVITY_WELL_MAX_VEL,
    GRAVITY_WELL_SECTOR_VEL_CAP,
    MINEFIELD_DAMAGE_PER_SEC,
    NEBULA_ENTITY_SENSOR_MODIFIER,
    NEBULA_SHIELD_REGEN_MODIFIER,
    RADIATION_DAMAGE_PER_SEC,
    RADIATION_SECTOR_DAMAGE_PER_SEC,
    RADIATION_SENSOR_MODIFIER,
    RADIATION_SHIELD_ABSORPTION_FRAC,
    RADIATION_SHIELD_THRESHOLD,
    ship_in_hazard,
    tick_hazards,
)
from server.models.ship import Ship
from server.models.world import Hazard, World, spawn_hazard
from server.systems import sensors
from server.systems.sensors import BASE_SENSOR_RANGE
from server.systems.combat import regenerate_shields, SHIELD_REGEN_PER_TICK
from server.systems.ai import tick_enemies
from server.models.world import Enemy, ENEMY_TYPE_PARAMS, spawn_enemy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ship(**kwargs) -> Ship:
    return Ship(**kwargs)


def _world_no_hazards() -> World:
    w = World()
    w.hazards.clear()
    w.enemies.clear()
    w.torpedoes.clear()
    w.stations.clear()
    w.sector_grid = None
    return w


def _world_with_hazard(hz: Hazard) -> World:
    w = _world_no_hazards()
    w.hazards.append(hz)
    return w


def _make_sector_world(sector_type: str, sensor_modifier: float = 1.0, nav_hazard: str = "none") -> World:
    """Build a World with a single-sector grid of the given type."""
    from server.models.sector import (
        Sector, SectorGrid, SectorProperties, Rect, SectorVisibility,
    )
    props = SectorProperties(
        type=sector_type,
        sensor_modifier=sensor_modifier,
        navigation_hazard=nav_hazard,
    )
    sector = Sector(
        id="T1",
        name="Test Sector",
        grid_position=(0, 0),
        world_bounds=Rect(min_x=0.0, min_y=0.0, max_x=100_000.0, max_y=100_000.0),
        properties=props,
        visibility=SectorVisibility.ACTIVE,
    )
    grid = SectorGrid(sectors={"T1": sector}, grid_size=(1, 1))
    w = _world_no_hazards()
    w.sector_grid = grid
    return w


# ---------------------------------------------------------------------------
# TestHazardConstants
# ---------------------------------------------------------------------------


class TestHazardConstants:

    def test_minefield_damage_per_sec(self):
        assert MINEFIELD_DAMAGE_PER_SEC == pytest.approx(4.0)  # balanced from 5.0 in v0.05o

    def test_radiation_entity_damage_per_sec(self):
        assert RADIATION_DAMAGE_PER_SEC == pytest.approx(2.0)

    def test_gravity_well_max_vel(self):
        assert GRAVITY_WELL_MAX_VEL == pytest.approx(100.0)

    def test_nebula_entity_sensor_modifier(self):
        assert NEBULA_ENTITY_SENSOR_MODIFIER == pytest.approx(0.5)

    def test_nebula_shield_regen_modifier(self):
        assert NEBULA_SHIELD_REGEN_MODIFIER == pytest.approx(0.5)

    def test_asteroid_throttle_threshold(self):
        assert ASTEROID_THROTTLE_THRESHOLD == pytest.approx(30.0)

    def test_asteroid_damage_per_sec(self):
        assert ASTEROID_DAMAGE_PER_SEC == pytest.approx(2.0)

    def test_gravity_well_sector_vel_cap(self):
        assert GRAVITY_WELL_SECTOR_VEL_CAP == pytest.approx(200.0)

    def test_radiation_sector_damage_per_sec(self):
        assert RADIATION_SECTOR_DAMAGE_PER_SEC == pytest.approx(1.5)

    def test_radiation_shield_absorption_frac(self):
        assert RADIATION_SHIELD_ABSORPTION_FRAC == pytest.approx(0.6)

    def test_radiation_shield_threshold(self):
        assert RADIATION_SHIELD_THRESHOLD == pytest.approx(50.0)

    def test_radiation_sensor_modifier(self):
        assert RADIATION_SENSOR_MODIFIER == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# TestResetState
# ---------------------------------------------------------------------------


class TestResetState:

    def setup_method(self):
        hz_mod.reset_state()

    def test_sensor_modifier_defaults_to_one(self):
        assert hz_mod.get_sensor_modifier() == pytest.approx(1.0)

    def test_shield_regen_modifier_defaults_to_one(self):
        assert hz_mod.get_shield_regen_modifier() == pytest.approx(1.0)

    def test_velocity_cap_defaults_to_none(self):
        assert hz_mod.get_velocity_cap() is None

    def test_active_hazard_types_defaults_to_empty(self):
        assert hz_mod.get_active_hazard_types() == []

    def test_reset_clears_after_tick(self):
        ship = _ship(x=500.0, y=500.0)
        w = _world_with_hazard(spawn_hazard("n1", 500.0, 500.0, 1000.0, "nebula"))
        tick_hazards(w, ship, 0.1)
        assert hz_mod.get_sensor_modifier() < 1.0
        hz_mod.reset_state()
        assert hz_mod.get_sensor_modifier() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# TestEntityHazards
# ---------------------------------------------------------------------------


class TestEntityHazards:

    def setup_method(self):
        hz_mod.reset_state()

    def test_minefield_deals_hull_damage(self):
        ship = _ship(x=500.0, y=500.0, hull=100.0)
        w = _world_with_hazard(spawn_hazard("m1", 500.0, 500.0, 2000.0, "minefield"))
        events = tick_hazards(w, ship, 1.0)
        expected = MINEFIELD_DAMAGE_PER_SEC * 1.0
        assert ship.hull == pytest.approx(100.0 - expected, abs=0.01)
        assert len(events) == 1
        assert events[0]["hazard_type"] == "minefield"

    def test_minefield_outside_range_no_damage(self):
        ship = _ship(x=0.0, y=0.0, hull=100.0)
        w = _world_with_hazard(spawn_hazard("m1", 5000.0, 5000.0, 100.0, "minefield"))
        events = tick_hazards(w, ship, 1.0)
        assert ship.hull == pytest.approx(100.0)
        assert events == []

    def test_gravity_well_entity_caps_velocity(self):
        ship = _ship(x=500.0, y=500.0, velocity=500.0)
        w = _world_with_hazard(spawn_hazard("g1", 500.0, 500.0, 2000.0, "gravity_well"))
        tick_hazards(w, ship, 0.1)
        assert ship.velocity == pytest.approx(GRAVITY_WELL_MAX_VEL)

    def test_gravity_well_entity_in_active_types(self):
        ship = _ship(x=500.0, y=500.0, velocity=500.0)
        w = _world_with_hazard(spawn_hazard("g1", 500.0, 500.0, 2000.0, "gravity_well"))
        tick_hazards(w, ship, 0.1)
        assert "gravity_well" in hz_mod.get_active_hazard_types()

    def test_radiation_entity_deals_hull_damage(self):
        ship = _ship(x=500.0, y=500.0, hull=100.0)
        w = _world_with_hazard(spawn_hazard("r1", 500.0, 500.0, 2000.0, "radiation_zone"))
        events = tick_hazards(w, ship, 1.0)
        expected = RADIATION_DAMAGE_PER_SEC * 1.0
        assert ship.hull == pytest.approx(100.0 - expected, abs=0.01)
        assert events[0]["hazard_type"] == "radiation_zone"

    def test_radiation_entity_reduces_sensor_modifier(self):
        ship = _ship(x=500.0, y=500.0)
        w = _world_with_hazard(spawn_hazard("r1", 500.0, 500.0, 2000.0, "radiation_zone"))
        tick_hazards(w, ship, 0.1)
        assert hz_mod.get_sensor_modifier() == pytest.approx(RADIATION_SENSOR_MODIFIER)

    def test_nebula_entity_sets_sensor_modifier(self):
        ship = _ship(x=500.0, y=500.0)
        w = _world_with_hazard(spawn_hazard("nb1", 500.0, 500.0, 2000.0, "nebula"))
        tick_hazards(w, ship, 0.1)
        assert hz_mod.get_sensor_modifier() == pytest.approx(NEBULA_ENTITY_SENSOR_MODIFIER)

    def test_nebula_entity_sets_shield_regen_modifier(self):
        ship = _ship(x=500.0, y=500.0)
        w = _world_with_hazard(spawn_hazard("nb1", 500.0, 500.0, 2000.0, "nebula"))
        tick_hazards(w, ship, 0.1)
        assert hz_mod.get_shield_regen_modifier() == pytest.approx(NEBULA_SHIELD_REGEN_MODIFIER)

    def test_nebula_entity_in_active_types(self):
        ship = _ship(x=500.0, y=500.0)
        w = _world_with_hazard(spawn_hazard("nb1", 500.0, 500.0, 2000.0, "nebula"))
        tick_hazards(w, ship, 0.1)
        assert "nebula" in hz_mod.get_active_hazard_types()

    def test_ship_in_hazard_true_inside(self):
        ship = _ship(x=100.0, y=100.0)
        hz = Hazard(id="h1", x=0.0, y=0.0, radius=200.0, hazard_type="nebula")
        assert ship_in_hazard(ship, hz) is True

    def test_ship_in_hazard_false_outside(self):
        ship = _ship(x=500.0, y=500.0)
        hz = Hazard(id="h1", x=0.0, y=0.0, radius=10.0, hazard_type="nebula")
        assert ship_in_hazard(ship, hz) is False


# ---------------------------------------------------------------------------
# TestNebulaSectorHazard
# ---------------------------------------------------------------------------


class TestNebulaSectorHazard:

    def setup_method(self):
        hz_mod.reset_state()

    def _ship_in_sector(self) -> Ship:
        return _ship(x=50_000.0, y=50_000.0)  # inside T1 (0–100k × 0–100k)

    def test_nebula_sector_sets_sensor_modifier_from_props(self):
        w = _make_sector_world("nebula", sensor_modifier=0.6)
        ship = self._ship_in_sector()
        tick_hazards(w, ship, 0.1)
        assert hz_mod.get_sensor_modifier() == pytest.approx(0.6)

    def test_nebula_sector_sets_shield_regen_modifier(self):
        w = _make_sector_world("nebula", sensor_modifier=0.6)
        ship = self._ship_in_sector()
        tick_hazards(w, ship, 0.1)
        assert hz_mod.get_shield_regen_modifier() == pytest.approx(NEBULA_SHIELD_REGEN_MODIFIER)

    def test_non_nebula_sector_no_modifier(self):
        w = _make_sector_world("deep_space", sensor_modifier=1.0)
        ship = self._ship_in_sector()
        tick_hazards(w, ship, 0.1)
        assert hz_mod.get_sensor_modifier() == pytest.approx(1.0)
        assert hz_mod.get_shield_regen_modifier() == pytest.approx(1.0)

    def test_nebula_sector_in_active_types(self):
        w = _make_sector_world("nebula", sensor_modifier=0.6)
        ship = self._ship_in_sector()
        tick_hazards(w, ship, 0.1)
        assert "nebula" in hz_mod.get_active_hazard_types()

    def test_nebula_entity_plus_sector_uses_most_restrictive(self):
        # Entity nebula modifier = 0.5; sector modifier = 0.4 → result should be 0.4
        w = _make_sector_world("nebula", sensor_modifier=0.4)
        w.hazards.append(spawn_hazard("nb_entity", 50_000.0, 50_000.0, 10_000.0, "nebula"))
        ship = self._ship_in_sector()
        tick_hazards(w, ship, 0.1)
        assert hz_mod.get_sensor_modifier() == pytest.approx(0.4)

    def test_no_sector_grid_entity_hazard_only(self):
        # Without sector_grid, only entity hazards apply
        w = _world_no_hazards()
        w.sector_grid = None
        ship = _ship(x=50_000.0, y=50_000.0)
        tick_hazards(w, ship, 0.1)
        assert hz_mod.get_sensor_modifier() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# TestAsteroidFieldSectorHazard
# ---------------------------------------------------------------------------


class TestAsteroidFieldSectorHazard:

    def setup_method(self):
        hz_mod.reset_state()

    def _ship_in_sector(self, throttle: float = 0.0) -> Ship:
        return _ship(x=50_000.0, y=50_000.0, throttle=throttle)

    def test_asteroid_field_throttle_above_threshold_deals_damage(self):
        w = _make_sector_world("asteroid_field", sensor_modifier=0.8)
        ship = self._ship_in_sector(throttle=ASTEROID_THROTTLE_THRESHOLD + 10.0)
        initial_hull = ship.hull
        events = tick_hazards(w, ship, 1.0)
        assert ship.hull < initial_hull
        assert len(events) == 1
        assert events[0]["hazard_type"] == "asteroid_field"

    def test_asteroid_field_throttle_at_threshold_no_damage(self):
        w = _make_sector_world("asteroid_field", sensor_modifier=0.8)
        ship = self._ship_in_sector(throttle=ASTEROID_THROTTLE_THRESHOLD)
        initial_hull = ship.hull
        events = tick_hazards(w, ship, 1.0)
        assert ship.hull == pytest.approx(initial_hull)
        assert events == []

    def test_asteroid_field_throttle_below_threshold_no_damage(self):
        w = _make_sector_world("asteroid_field", sensor_modifier=0.8)
        ship = self._ship_in_sector(throttle=10.0)
        initial_hull = ship.hull
        tick_hazards(w, ship, 1.0)
        assert ship.hull == pytest.approx(initial_hull)

    def test_asteroid_field_damage_value(self):
        w = _make_sector_world("asteroid_field", sensor_modifier=0.8)
        ship = self._ship_in_sector(throttle=50.0)
        initial_hull = ship.hull
        tick_hazards(w, ship, 1.0)
        expected_damage = ASTEROID_DAMAGE_PER_SEC * 1.0
        assert ship.hull == pytest.approx(initial_hull - expected_damage, abs=0.01)

    def test_asteroid_field_in_active_types(self):
        w = _make_sector_world("asteroid_field", sensor_modifier=0.8)
        ship = self._ship_in_sector(throttle=0.0)
        tick_hazards(w, ship, 0.1)
        assert "asteroid_field" in hz_mod.get_active_hazard_types()

    def test_asteroid_field_applies_sector_sensor_modifier(self):
        w = _make_sector_world("asteroid_field", sensor_modifier=0.8)
        ship = self._ship_in_sector(throttle=0.0)
        tick_hazards(w, ship, 0.1)
        assert hz_mod.get_sensor_modifier() == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# TestGravityWellSectorHazard
# ---------------------------------------------------------------------------


class TestGravityWellSectorHazard:

    def setup_method(self):
        hz_mod.reset_state()

    def _ship_in_sector(self, velocity: float = 300.0) -> Ship:
        return _ship(x=50_000.0, y=50_000.0, velocity=velocity)

    def test_gravity_well_caps_velocity(self):
        w = _make_sector_world("gravity_well", sensor_modifier=0.9)
        ship = self._ship_in_sector(velocity=500.0)
        tick_hazards(w, ship, 0.1)
        assert ship.velocity <= GRAVITY_WELL_SECTOR_VEL_CAP

    def test_gravity_well_velocity_cap_stored(self):
        w = _make_sector_world("gravity_well", sensor_modifier=0.9)
        ship = self._ship_in_sector(velocity=500.0)
        tick_hazards(w, ship, 0.1)
        assert hz_mod.get_velocity_cap() == pytest.approx(GRAVITY_WELL_SECTOR_VEL_CAP)

    def test_gravity_well_not_active_no_cap(self):
        w = _make_sector_world("deep_space", sensor_modifier=1.0)
        ship = self._ship_in_sector(velocity=500.0)
        tick_hazards(w, ship, 0.1)
        assert hz_mod.get_velocity_cap() is None
        assert ship.velocity == pytest.approx(500.0)

    def test_gravity_well_in_active_types(self):
        w = _make_sector_world("gravity_well", sensor_modifier=0.9)
        ship = self._ship_in_sector()
        tick_hazards(w, ship, 0.1)
        assert "gravity_well" in hz_mod.get_active_hazard_types()

    def test_gravity_well_sector_cap_gentler_than_entity(self):
        assert GRAVITY_WELL_SECTOR_VEL_CAP > GRAVITY_WELL_MAX_VEL

    def test_gravity_well_applies_sector_sensor_modifier(self):
        w = _make_sector_world("gravity_well", sensor_modifier=0.9)
        ship = self._ship_in_sector()
        tick_hazards(w, ship, 0.1)
        assert hz_mod.get_sensor_modifier() == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# TestRadiationZoneSectorHazard
# ---------------------------------------------------------------------------


class TestRadiationZoneSectorHazard:

    def setup_method(self):
        hz_mod.reset_state()

    def _ship_in_sector(self, shields_front: float = 0.0, shields_rear: float = 0.0) -> Ship:
        s = _ship(x=50_000.0, y=50_000.0)
        # Set all 4 facings to the same values for radiation absorption check.
        total = shields_front + shields_rear
        per_facing = total / 4.0
        s.shields.fore = s.shields.aft = s.shields.port = s.shields.starboard = per_facing
        return s

    def test_radiation_sector_deals_hull_damage(self):
        w = _make_sector_world("radiation_zone", sensor_modifier=0.7)
        ship = self._ship_in_sector()
        initial = ship.hull
        events = tick_hazards(w, ship, 1.0)
        assert ship.hull < initial
        assert len(events) == 1
        assert events[0]["hazard_type"] == "radiation_zone"

    def test_radiation_no_shields_full_damage(self):
        w = _make_sector_world("radiation_zone", sensor_modifier=0.7)
        ship = self._ship_in_sector(shields_front=0.0, shields_rear=0.0)
        initial = ship.hull
        tick_hazards(w, ship, 1.0)
        expected = RADIATION_SECTOR_DAMAGE_PER_SEC * 1.0
        assert ship.hull == pytest.approx(initial - expected, abs=0.01)

    def test_radiation_with_adequate_shields_reduced_damage(self):
        w = _make_sector_world("radiation_zone", sensor_modifier=0.7)
        # Combined shields above RADIATION_SHIELD_THRESHOLD (50).
        ship = self._ship_in_sector(shields_front=30.0, shields_rear=30.0)
        initial = ship.hull
        tick_hazards(w, ship, 1.0)
        raw = RADIATION_SECTOR_DAMAGE_PER_SEC * 1.0
        expected = raw * (1.0 - RADIATION_SHIELD_ABSORPTION_FRAC)
        assert ship.hull == pytest.approx(initial - expected, abs=0.01)

    def test_radiation_shields_below_threshold_no_reduction(self):
        w = _make_sector_world("radiation_zone", sensor_modifier=0.7)
        # Combined shields below threshold (40 < 50)
        ship = self._ship_in_sector(shields_front=20.0, shields_rear=20.0)
        initial = ship.hull
        tick_hazards(w, ship, 1.0)
        expected = RADIATION_SECTOR_DAMAGE_PER_SEC * 1.0
        assert ship.hull == pytest.approx(initial - expected, abs=0.01)

    def test_radiation_in_active_types(self):
        w = _make_sector_world("radiation_zone", sensor_modifier=0.7)
        ship = self._ship_in_sector()
        tick_hazards(w, ship, 0.1)
        assert "radiation_zone" in hz_mod.get_active_hazard_types()

    def test_radiation_sector_reduces_sensor_modifier(self):
        w = _make_sector_world("radiation_zone", sensor_modifier=0.7)
        ship = self._ship_in_sector()
        tick_hazards(w, ship, 0.1)
        assert hz_mod.get_sensor_modifier() == pytest.approx(0.7)

    def test_radiation_no_damage_outside_sector(self):
        # Ship far outside the 0–100k sector bounds
        w = _make_sector_world("radiation_zone", sensor_modifier=0.7)
        ship = _ship(x=200_000.0, y=200_000.0)  # outside T1
        initial = ship.hull
        tick_hazards(w, ship, 1.0)
        assert ship.hull == pytest.approx(initial)


# ---------------------------------------------------------------------------
# TestModifierGetters
# ---------------------------------------------------------------------------


class TestModifierGetters:

    def setup_method(self):
        hz_mod.reset_state()

    def test_get_sensor_modifier_default(self):
        assert hz_mod.get_sensor_modifier() == pytest.approx(1.0)

    def test_get_shield_regen_modifier_default(self):
        assert hz_mod.get_shield_regen_modifier() == pytest.approx(1.0)

    def test_get_velocity_cap_default(self):
        assert hz_mod.get_velocity_cap() is None

    def test_get_active_hazard_types_default(self):
        assert hz_mod.get_active_hazard_types() == []

    def test_getters_return_fresh_list(self):
        result = hz_mod.get_active_hazard_types()
        result.append("fake")
        assert hz_mod.get_active_hazard_types() == []


# ---------------------------------------------------------------------------
# TestSensorRangeModifier
# ---------------------------------------------------------------------------


class TestSensorRangeModifier:

    def test_sensor_range_default_modifier(self):
        ship = _ship()
        ship.systems["sensors"].power = 100.0
        expected = BASE_SENSOR_RANGE * ship.systems["sensors"].efficiency
        assert sensors.sensor_range(ship) == pytest.approx(expected)

    def test_sensor_range_half_modifier(self):
        ship = _ship()
        ship.systems["sensors"].power = 100.0
        full_range = sensors.sensor_range(ship)
        halved_range = sensors.sensor_range(ship, hazard_modifier=0.5)
        assert halved_range == pytest.approx(full_range * 0.5)

    def test_sensor_range_nebula_modifier(self):
        ship = _ship()
        full_range = sensors.sensor_range(ship, hazard_modifier=1.0)
        nebula_range = sensors.sensor_range(ship, hazard_modifier=NEBULA_ENTITY_SENSOR_MODIFIER)
        assert nebula_range < full_range

    def test_build_sensor_contacts_excludes_out_of_hazard_range(self):
        """Enemy inside normal range but outside nebula-reduced range is hidden."""
        from server.models.world import World
        w = World()
        w.enemies.clear()
        w.torpedoes.clear()
        # Place ship at origin; enemy at 20k units (inside 30k normal range).
        w.ship.x = 0.0
        w.ship.y = 0.0
        w.ship.systems["sensors"].power = 100.0
        enemy = spawn_enemy("scout", 20_000.0, 0.0, "e1")
        w.enemies.append(enemy)

        full_contacts = sensors.build_sensor_contacts(w, w.ship, hazard_modifier=1.0)
        assert any(c["id"] == "e1" for c in full_contacts)

        # With 0.5 modifier: range = 15k; enemy at 20k is now outside range.
        reduced_contacts = sensors.build_sensor_contacts(w, w.ship, hazard_modifier=0.5)
        assert not any(c["id"] == "e1" for c in reduced_contacts)


# ---------------------------------------------------------------------------
# TestShieldRegenModifier
# ---------------------------------------------------------------------------


class TestShieldRegenModifier:

    def test_regen_default_modifier(self):
        ship = _ship()
        ship.shields.fore = 0.0
        ship.shields.aft  = 0.0
        ship.systems["shields"].power = 100.0
        regenerate_shields(ship, hazard_modifier=1.0)
        expected = SHIELD_REGEN_PER_TICK * ship.systems["shields"].efficiency
        assert ship.shields.fore == pytest.approx(expected)
        assert ship.shields.aft  == pytest.approx(expected)

    def test_regen_half_modifier(self):
        ship = _ship()
        ship.shields.fore = 0.0
        ship.shields.aft  = 0.0
        ship.systems["shields"].power = 100.0
        regenerate_shields(ship, hazard_modifier=1.0)
        regen_full = ship.shields.fore

        ship.shields.fore = 0.0
        ship.shields.aft  = 0.0
        regenerate_shields(ship, hazard_modifier=0.5)
        assert ship.shields.fore == pytest.approx(regen_full * 0.5)

    def test_regen_nebula_modifier(self):
        ship = _ship()
        ship.shields.fore = 0.0
        ship.systems["shields"].power = 100.0
        regenerate_shields(ship, hazard_modifier=NEBULA_SHIELD_REGEN_MODIFIER)
        expected = SHIELD_REGEN_PER_TICK * ship.systems["shields"].efficiency * NEBULA_SHIELD_REGEN_MODIFIER
        assert ship.shields.fore == pytest.approx(expected)


# ---------------------------------------------------------------------------
# TestEnemySensorModifier
# ---------------------------------------------------------------------------


class TestEnemySensorModifier:

    def test_enemy_detects_player_without_modifier(self):
        """Enemy just inside detect_range transitions to chase with modifier=1.0."""
        enemy = spawn_enemy("scout", 0.0, 0.0, "e1")
        scout_detect = ENEMY_TYPE_PARAMS["scout"]["detect_range"]
        ship = _ship(x=scout_detect * 0.9, y=0.0)
        tick_enemies([enemy], ship, 0.1, sensor_modifier=1.0)
        assert enemy.ai_state == "chase"

    def test_enemy_cannot_detect_player_in_nebula(self):
        """Enemy at same distance cannot detect with 0.5 modifier (range halved)."""
        enemy = spawn_enemy("scout", 0.0, 0.0, "e2")
        scout_detect = ENEMY_TYPE_PARAMS["scout"]["detect_range"]
        # Ship is at 0.9 × full detect range — inside full range but outside 0.5×.
        ship = _ship(x=scout_detect * 0.9, y=0.0)
        tick_enemies([enemy], ship, 0.1, sensor_modifier=0.5)
        # Half the range: 0.5 × scout_detect < 0.9 × scout_detect → still idle.
        assert enemy.ai_state == "idle"

    def test_enemy_detects_player_at_close_range_despite_modifier(self):
        """Enemy very close detects player even with 0.5 modifier."""
        enemy = spawn_enemy("scout", 0.0, 0.0, "e3")
        scout_detect = ENEMY_TYPE_PARAMS["scout"]["detect_range"]
        ship = _ship(x=scout_detect * 0.2, y=0.0)  # very close
        tick_enemies([enemy], ship, 0.1, sensor_modifier=0.5)
        # 0.2 × full range < 0.5 × full range → should detect.
        assert enemy.ai_state == "chase"

    def test_sensor_modifier_default_1_backward_compatible(self):
        """tick_enemies() with default sensor_modifier=1.0 behaves as before."""
        enemy = spawn_enemy("scout", 0.0, 0.0, "e4")
        scout_detect = ENEMY_TYPE_PARAMS["scout"]["detect_range"]
        ship = _ship(x=scout_detect * 0.5, y=0.0)
        tick_enemies([enemy], ship, 0.1)   # no sensor_modifier arg
        assert enemy.ai_state == "chase"
