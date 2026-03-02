"""
Integration tests for save/resume fidelity.

Builds complex game state, saves to disk, clears/resets all state,
restores from the save, and verifies every value survived the round trip.

Uses tmp_path + monkeypatch to redirect SAVES_DIR so no real save files
are created.
"""
from __future__ import annotations

import pytest

from server.models.ship import Ship, ShipSystem, Shields, calculate_shield_distribution
from server.models.world import (
    World, Enemy, Station, Hazard, spawn_enemy, spawn_creature,
)
from server.models.interior import make_default_interior
from server.models.sector import load_sector_grid, SectorVisibility
from server.difficulty import DifficultySettings, get_preset

import server.save_system as ss
import server.game_loop_weapons as glw
import server.game_loop_hazard_control as glhc
import server.game_loop_engineering as gle
import server.game_loop_docking as gldo
import server.game_loop_medical_v2 as glmed
import server.game_loop_security as gls


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _redirect_saves(tmp_path, monkeypatch):
    """Redirect SAVES_DIR so tests never touch the real saves/ directory."""
    monkeypatch.setattr(ss, "SAVES_DIR", tmp_path)


@pytest.fixture()
def complex_world():
    """Build a World with rich, non-default state across every subsystem.

    Returns ``(world, save_id, expected_health)`` after saving via
    ``save_game()``.  ``expected_health`` is a dict of system health values
    computed by the DamageModel after applying damage (used by tests that
    verify system health survives the round trip).
    """
    world = World()
    ship = world.ship

    # -- Position / movement --
    ship.x = 23_456.7
    ship.y = 67_890.1
    ship.heading = 137.5
    ship.target_heading = 220.0
    ship.velocity = 185.0
    ship.throttle = 65.0

    # -- Hull --
    ship.hull = 63.0
    ship.hull_max = 100.0

    # -- Shields (non-centre focus) --
    ship.shield_focus = {"x": 0.6, "y": -0.3}
    ship.shield_distribution = calculate_shield_distribution(0.6, -0.3)
    ship.shields.fore = 35.0
    ship.shields.aft = 70.0
    ship.shields.port = 20.0
    ship.shields.starboard = 55.0

    # -- Systems: change power on some, captain offline on one --
    ship.systems["engines"].power = 120.0
    ship.systems["beams"].power = 90.0
    ship.systems["sensors"].power = 110.0
    ship.systems["sensors"]._captain_offline = True

    # -- Alert level --
    ship.alert_level = "yellow"

    # -- Repair focus --
    ship.repair_focus = "beams"

    # -- Medical supplies --
    ship.medical_supplies = 7

    # -- Difficulty (commander preset) --
    ship.difficulty = get_preset("commander")

    # -- Interior room damage --
    ship.interior = make_default_interior()
    rooms = list(ship.interior.rooms.values())
    rooms[0].state = "fire"
    rooms[1].state = "damaged"
    rooms[2].door_sealed = True

    # -- Enemies --
    enemy1 = spawn_enemy("cruiser", 30_000.0, 40_000.0, "e_alpha")
    enemy1.hull = 45.0
    enemy1.shield_front = 60.0
    enemy1.shield_rear = 30.0
    enemy1.shield_frequency = "gamma"
    enemy1.ai_state = "attack"
    world.enemies.append(enemy1)

    enemy2 = spawn_enemy("scout", 55_000.0, 20_000.0, "e_beta")
    enemy2.hull = 25.0
    enemy2.shield_frequency = "delta"
    world.enemies.append(enemy2)

    # -- Station --
    station = Station(
        id="st_harbor",
        x=10_000.0,
        y=10_000.0,
        name="Harbor Prime",
        station_type="trade_hub",
        faction="neutral",
        services=["hull_repair", "torpedo_resupply"],
        hull=350.0,
        hull_max=400.0,
        shields=40.0,
        shields_max=50.0,
        transponder_active=True,
    )
    world.stations.append(station)

    # -- Hazard --
    hazard = Hazard(
        id="hz_neb",
        x=70_000.0,
        y=80_000.0,
        radius=12_000.0,
        hazard_type="nebula",
        label="Sigma Nebula",
    )
    world.hazards.append(hazard)

    # -- Sector grid with mixed visibility --
    grid = load_sector_grid("standard_grid")
    sectors = list(grid.sectors.values())
    sectors[0].visibility = SectorVisibility.VISITED
    sectors[1].visibility = SectorVisibility.SCANNED
    sectors[2].visibility = SectorVisibility.SURVEYED
    world.sector_grid = grid

    # -- Weapons module state --
    glw.reset()
    glw.set_target("e_alpha")
    glw.set_ammo_for_type("standard", 3)
    glw.set_ammo_for_type("homing", 1)
    glw.set_ammo_for_type("nuclear", 0)

    # -- DC module state --
    glhc.reset()
    # Damage a room so we can dispatch a DCT
    rooms[0].state = "fire"
    glhc.dispatch_dct(rooms[0].id, ship.interior)

    # -- Engineering module state --
    gle.reset()
    gle.init(ship)
    # Apply system damage through the DamageModel so health is tracked properly.
    # The DamageModel owns system health; _sync_health_to_ship pushes it to ship
    # on restore. Damage a known component to get predictable reduced health.
    gle.apply_system_damage("engines", 20.0, "test")
    gle.apply_system_damage("beams", 40.0, "test")
    gle.apply_system_damage("shields", 55.0, "test")
    # Read back the actual health values the DamageModel computed.
    dm = gle.get_damage_model()
    _expected_engines_health = dm.get_system_health("engines")
    _expected_beams_health = dm.get_system_health("beams")
    _expected_shields_health = dm.get_system_health("shields")
    pg = gle.get_power_grid()
    pg.battery_mode = "charging"
    pg.battery_charge = 175.5
    pg.primary_bus_online = False

    # -- Docking module state --
    gldo.reset()

    # -- Medical module state --
    glmed.reset()

    # -- Security module state --
    gls.reset()

    # -- Save --
    save_id = ss.save_game(
        world,
        mission_id="deep_space_rescue",
        difficulty_preset="commander",
        ship_class="frigate",
        tick_count=4200,
        game_state={"phase": "mid"},
    )

    return world, save_id, {
        "engines_health": _expected_engines_health,
        "beams_health": _expected_beams_health,
        "shields_health": _expected_shields_health,
    }


# ---------------------------------------------------------------------------
# Comprehensive round-trip test
# ---------------------------------------------------------------------------


def test_full_save_resume_round_trip(complex_world):
    """Save complex state, reset everything, restore, verify every value."""
    _original_world, save_id, expected_health = complex_world

    # Capture expected values BEFORE we reset anything (read from the modules
    # that were set up by the fixture).
    expected_ammo = glw.get_ammo()
    expected_target = glw.get_target()
    expected_dc = glhc.serialise()
    expected_eng = gle.serialise()

    # --- Reset all state to defaults ---
    fresh_world = World()
    glw.reset()
    glhc.reset()
    gle.reset()
    gldo.reset()
    glmed.reset()
    gls.reset()

    # Verify the reset actually zeroed things out.
    assert fresh_world.ship.hull == 100.0
    assert len(fresh_world.enemies) == 0
    assert glw.get_target() is None

    # --- Restore ---
    meta = ss.restore_game(save_id, fresh_world)

    ship = fresh_world.ship

    # -- Metadata --
    assert meta["mission_id"] == "deep_space_rescue"
    assert meta["difficulty_preset"] == "commander"
    assert meta["ship_class"] == "frigate"
    assert meta["tick_count"] == 4200
    assert meta["game_state"] == {"phase": "mid"}

    # -- Position --
    assert ship.x == pytest.approx(23_456.7)
    assert ship.y == pytest.approx(67_890.1)
    assert ship.heading == pytest.approx(137.5)
    assert ship.target_heading == pytest.approx(220.0)
    assert ship.velocity == pytest.approx(185.0)
    assert ship.throttle == pytest.approx(65.0)

    # -- Hull --
    assert ship.hull == pytest.approx(63.0)
    assert ship.hull_max == pytest.approx(100.0)

    # -- Shields --
    assert ship.shields.fore == pytest.approx(35.0)
    assert ship.shields.aft == pytest.approx(70.0)
    assert ship.shields.port == pytest.approx(20.0)
    assert ship.shields.starboard == pytest.approx(55.0)
    assert ship.shield_focus["x"] == pytest.approx(0.6)
    assert ship.shield_focus["y"] == pytest.approx(-0.3)

    # -- Systems --
    assert ship.systems["engines"].power == pytest.approx(120.0)
    assert ship.systems["engines"].health == pytest.approx(expected_health["engines_health"], abs=0.5)
    assert ship.systems["beams"].power == pytest.approx(90.0)
    assert ship.systems["beams"].health == pytest.approx(expected_health["beams_health"], abs=0.5)
    assert ship.systems["sensors"]._captain_offline is True
    assert ship.systems["shields"].health == pytest.approx(expected_health["shields_health"], abs=0.5)
    # Verify damage was actually applied (health should be below 100)
    assert ship.systems["engines"].health < 100.0
    assert ship.systems["beams"].health < 100.0
    assert ship.systems["shields"].health < 100.0

    # -- Alert --
    assert ship.alert_level == "yellow"

    # -- Repair focus --
    assert ship.repair_focus == "beams"

    # -- Medical supplies --
    assert ship.medical_supplies == 7

    # -- Difficulty --
    assert ship.difficulty.enemy_damage_multiplier == pytest.approx(1.3)
    assert ship.difficulty.enemy_accuracy == pytest.approx(1.15)
    assert ship.difficulty.repair_speed_multiplier == pytest.approx(0.8)

    # -- Interior --
    rooms = list(ship.interior.rooms.values())
    assert rooms[0].state == "fire"
    assert rooms[1].state == "damaged"
    assert rooms[2].door_sealed is True

    # -- Enemies --
    assert len(fresh_world.enemies) == 2
    e1 = next(e for e in fresh_world.enemies if e.id == "e_alpha")
    assert e1.hull == pytest.approx(45.0)
    assert e1.shield_front == pytest.approx(60.0)
    assert e1.shield_rear == pytest.approx(30.0)
    assert e1.shield_frequency == "gamma"
    assert e1.ai_state == "attack"
    e2 = next(e for e in fresh_world.enemies if e.id == "e_beta")
    assert e2.hull == pytest.approx(25.0)
    assert e2.shield_frequency == "delta"

    # -- Station --
    assert len(fresh_world.stations) == 1
    st = fresh_world.stations[0]
    assert st.id == "st_harbor"
    assert st.name == "Harbor Prime"
    assert st.hull == pytest.approx(350.0)
    assert st.shields == pytest.approx(40.0)

    # -- Hazard --
    assert len(fresh_world.hazards) == 1
    hz = fresh_world.hazards[0]
    assert hz.hazard_type == "nebula"
    assert hz.label == "Sigma Nebula"

    # -- Sector grid --
    assert fresh_world.sector_grid is not None
    sectors = list(fresh_world.sector_grid.sectors.values())
    assert sectors[0].visibility == SectorVisibility.VISITED
    assert sectors[1].visibility == SectorVisibility.SCANNED
    assert sectors[2].visibility == SectorVisibility.SURVEYED

    # -- Weapons --
    assert glw.get_target() == expected_target
    restored_ammo = glw.get_ammo()
    assert restored_ammo["standard"] == expected_ammo["standard"]
    assert restored_ammo["homing"] == expected_ammo["homing"]
    assert restored_ammo["nuclear"] == expected_ammo["nuclear"]

    # -- DC --
    dc_state = glhc.serialise()
    assert dc_state["active_dcts"] == expected_dc["active_dcts"]

    # -- Engineering --
    eng_state = gle.serialise()
    pg_data = eng_state.get("power_grid", {})
    assert pg_data["battery_mode"] == "charging"
    assert pg_data["battery_charge"] == pytest.approx(175.5, abs=0.1)
    assert pg_data["primary_bus_online"] is False


# ---------------------------------------------------------------------------
# 15 focused sub-tests
# ---------------------------------------------------------------------------


class TestShipPositionPreserved:
    def test_ship_position_preserved(self, complex_world):
        _, save_id, _ = complex_world
        world = World()
        glw.reset(); glhc.reset(); gle.reset(); gldo.reset(); glmed.reset(); gls.reset()
        ss.restore_game(save_id, world)

        assert world.ship.x == pytest.approx(23_456.7)
        assert world.ship.y == pytest.approx(67_890.1)
        assert world.ship.heading == pytest.approx(137.5)
        assert world.ship.target_heading == pytest.approx(220.0)
        assert world.ship.velocity == pytest.approx(185.0)
        assert world.ship.throttle == pytest.approx(65.0)


class TestShipHullPreserved:
    def test_ship_hull_preserved(self, complex_world):
        _, save_id, _ = complex_world
        world = World()
        glw.reset(); glhc.reset(); gle.reset(); gldo.reset(); glmed.reset(); gls.reset()
        ss.restore_game(save_id, world)

        assert world.ship.hull == pytest.approx(63.0)
        assert world.ship.hull_max == pytest.approx(100.0)


class TestShieldsPreserved:
    def test_shields_preserved(self, complex_world):
        _, save_id, _ = complex_world
        world = World()
        glw.reset(); glhc.reset(); gle.reset(); gldo.reset(); glmed.reset(); gls.reset()
        ss.restore_game(save_id, world)

        assert world.ship.shields.fore == pytest.approx(35.0)
        assert world.ship.shields.aft == pytest.approx(70.0)
        assert world.ship.shields.port == pytest.approx(20.0)
        assert world.ship.shields.starboard == pytest.approx(55.0)


class TestShieldFocusPreserved:
    def test_shield_focus_preserved(self, complex_world):
        _, save_id, _ = complex_world
        world = World()
        glw.reset(); glhc.reset(); gle.reset(); gldo.reset(); glmed.reset(); gls.reset()
        ss.restore_game(save_id, world)

        assert world.ship.shield_focus["x"] == pytest.approx(0.6)
        assert world.ship.shield_focus["y"] == pytest.approx(-0.3)
        # Distribution should reflect the focus
        dist = world.ship.shield_distribution
        expected = calculate_shield_distribution(0.6, -0.3)
        for facing in ("fore", "aft", "port", "starboard"):
            assert dist[facing] == pytest.approx(expected[facing], abs=0.01)


class TestSystemsPowerPreserved:
    def test_systems_power_preserved(self, complex_world):
        _, save_id, _ = complex_world
        world = World()
        glw.reset(); glhc.reset(); gle.reset(); gldo.reset(); glmed.reset(); gls.reset()
        ss.restore_game(save_id, world)

        assert world.ship.systems["engines"].power == pytest.approx(120.0)
        assert world.ship.systems["beams"].power == pytest.approx(90.0)
        assert world.ship.systems["sensors"].power == pytest.approx(110.0)


class TestSystemsHealthPreserved:
    def test_systems_health_preserved(self, complex_world):
        _, save_id, expected_health = complex_world
        world = World()
        glw.reset(); glhc.reset(); gle.reset(); gldo.reset(); glmed.reset(); gls.reset()
        ss.restore_game(save_id, world)

        # System health is managed by the DamageModel and synced on restore.
        assert world.ship.systems["engines"].health == pytest.approx(
            expected_health["engines_health"], abs=0.5)
        assert world.ship.systems["beams"].health == pytest.approx(
            expected_health["beams_health"], abs=0.5)
        assert world.ship.systems["shields"].health == pytest.approx(
            expected_health["shields_health"], abs=0.5)
        # Verify damage was actually applied (health below 100)
        assert world.ship.systems["engines"].health < 100.0
        assert world.ship.systems["beams"].health < 100.0
        assert world.ship.systems["shields"].health < 100.0
        # Captain offline flag preserved independently
        assert world.ship.systems["sensors"]._captain_offline is True


class TestAlertLevelPreserved:
    def test_alert_level_preserved(self, complex_world):
        _, save_id, _ = complex_world
        world = World()
        glw.reset(); glhc.reset(); gle.reset(); gldo.reset(); glmed.reset(); gls.reset()
        ss.restore_game(save_id, world)

        assert world.ship.alert_level == "yellow"


class TestWeaponsStatePreserved:
    def test_weapons_state_preserved(self, complex_world):
        _, save_id, _ = complex_world

        # Capture expected values before reset.
        expected_target = glw.get_target()
        expected_ammo = glw.get_ammo()

        # Reset.
        glw.reset(); glhc.reset(); gle.reset(); gldo.reset(); glmed.reset(); gls.reset()
        world = World()
        ss.restore_game(save_id, world)

        assert glw.get_target() == expected_target
        assert glw.get_target() == "e_alpha"

        ammo = glw.get_ammo()
        assert ammo["standard"] == 3
        assert ammo["homing"] == 1
        assert ammo["nuclear"] == 0


class TestEnemyEntitiesPreserved:
    def test_enemy_entities_preserved(self, complex_world):
        _, save_id, _ = complex_world
        world = World()
        glw.reset(); glhc.reset(); gle.reset(); gldo.reset(); glmed.reset(); gls.reset()
        ss.restore_game(save_id, world)

        assert len(world.enemies) == 2

        e1 = next(e for e in world.enemies if e.id == "e_alpha")
        assert e1.type == "cruiser"
        assert e1.x == pytest.approx(30_000.0)
        assert e1.y == pytest.approx(40_000.0)
        assert e1.hull == pytest.approx(45.0)
        assert e1.shield_front == pytest.approx(60.0)
        assert e1.shield_rear == pytest.approx(30.0)
        assert e1.shield_frequency == "gamma"

        e2 = next(e for e in world.enemies if e.id == "e_beta")
        assert e2.type == "scout"
        assert e2.hull == pytest.approx(25.0)
        assert e2.shield_frequency == "delta"


class TestStationEntitiesPreserved:
    def test_station_entities_preserved(self, complex_world):
        _, save_id, _ = complex_world
        world = World()
        glw.reset(); glhc.reset(); gle.reset(); gldo.reset(); glmed.reset(); gls.reset()
        ss.restore_game(save_id, world)

        assert len(world.stations) == 1
        st = world.stations[0]
        assert st.id == "st_harbor"
        assert st.name == "Harbor Prime"
        assert st.station_type == "trade_hub"
        assert st.faction == "neutral"
        assert st.x == pytest.approx(10_000.0)
        assert st.y == pytest.approx(10_000.0)
        assert st.hull == pytest.approx(350.0)
        assert st.hull_max == pytest.approx(400.0)
        assert st.shields == pytest.approx(40.0)
        assert st.shields_max == pytest.approx(50.0)
        assert "hull_repair" in st.services
        assert "torpedo_resupply" in st.services


class TestSectorVisibilityPreserved:
    def test_sector_visibility_preserved(self, complex_world):
        _, save_id, _ = complex_world
        world = World()
        glw.reset(); glhc.reset(); gle.reset(); gldo.reset(); glmed.reset(); gls.reset()
        ss.restore_game(save_id, world)

        assert world.sector_grid is not None
        sectors = list(world.sector_grid.sectors.values())
        assert sectors[0].visibility == SectorVisibility.VISITED
        assert sectors[1].visibility == SectorVisibility.SCANNED
        assert sectors[2].visibility == SectorVisibility.SURVEYED
        # Remaining sectors should still have a valid visibility value
        for s in sectors[3:]:
            assert isinstance(s.visibility, SectorVisibility)


class TestDifficultyPreserved:
    def test_difficulty_preserved(self, complex_world):
        _, save_id, _ = complex_world
        world = World()
        glw.reset(); glhc.reset(); gle.reset(); gldo.reset(); glmed.reset(); gls.reset()
        ss.restore_game(save_id, world)

        d = world.ship.difficulty
        commander = get_preset("commander")
        assert d.enemy_damage_multiplier == pytest.approx(commander.enemy_damage_multiplier)
        assert d.enemy_accuracy == pytest.approx(commander.enemy_accuracy)
        assert d.enemy_health_multiplier == pytest.approx(commander.enemy_health_multiplier)
        assert d.repair_speed_multiplier == pytest.approx(commander.repair_speed_multiplier)
        assert d.injury_chance == pytest.approx(commander.injury_chance)
        assert d.starting_torpedo_multiplier == pytest.approx(commander.starting_torpedo_multiplier)
        assert d.event_overlap_max == commander.event_overlap_max
        assert d.hints_enabled == commander.hints_enabled


class TestDCStatePreserved:
    def test_dc_state_preserved(self, complex_world):
        _, save_id, _ = complex_world

        expected = glhc.serialise()

        # Reset.
        glw.reset(); glhc.reset(); gle.reset(); gldo.reset(); glmed.reset(); gls.reset()
        world = World()
        ss.restore_game(save_id, world)

        restored = glhc.serialise()
        assert restored["active_dcts"] == expected["active_dcts"]
        assert len(restored["active_dcts"]) > 0  # we dispatched a DCT
        assert restored["pending_hull_damage"] == pytest.approx(
            expected["pending_hull_damage"])
        assert restored["fires"] == expected["fires"]
        assert restored["fire_teams"] == expected["fire_teams"]
        assert restored["vent_rooms"] == expected["vent_rooms"]


class TestInteriorStatePreserved:
    def test_interior_state_preserved(self, complex_world):
        _, save_id, _ = complex_world
        world = World()
        glw.reset(); glhc.reset(); gle.reset(); gldo.reset(); glmed.reset(); gls.reset()
        ss.restore_game(save_id, world)

        rooms = list(world.ship.interior.rooms.values())
        assert rooms[0].state == "fire"
        assert rooms[1].state == "damaged"
        assert rooms[2].door_sealed is True
        # Remaining rooms should default to normal
        for r in rooms[3:]:
            assert r.state == "normal"


class TestEngineeringStatePreserved:
    def test_engineering_state_preserved(self, complex_world):
        _, save_id, _ = complex_world

        expected = gle.serialise()

        # Reset.
        glw.reset(); glhc.reset(); gle.reset(); gldo.reset(); glmed.reset(); gls.reset()
        world = World()
        ss.restore_game(save_id, world)

        pg = gle.get_power_grid()
        assert pg is not None
        assert pg.battery_mode == "charging"
        assert pg.battery_charge == pytest.approx(175.5, abs=0.1)
        assert pg.primary_bus_online is False
        assert pg.secondary_bus_online is True


class TestDockingStatePreserved:
    def test_docking_state_preserved(self):
        """Test docking serialise/deserialise directly (no async needed)."""
        gldo.reset()

        # Simulate a mid-docking state by writing directly to module internals
        # through serialise/deserialise rather than async state machine.
        docking_state = {
            "state": "docked",
            "target_station_id": "st_harbor",
            "sequence_timer": 0.0,
            "clearance_timer": 0.0,
            "active_services": {"hull_repair": 22.5, "torpedo_resupply": 15.0},
        }
        gldo.deserialise(docking_state)

        # Verify deserialise worked.
        assert gldo.get_state() == "docked"
        assert gldo.is_docked() is True
        services = gldo.get_active_services()
        assert services["hull_repair"] == pytest.approx(22.5)
        assert services["torpedo_resupply"] == pytest.approx(15.0)

        # Now round-trip through serialise/deserialise.
        saved = gldo.serialise()
        gldo.reset()
        assert gldo.get_state() == "none"

        gldo.deserialise(saved)
        assert gldo.get_state() == "docked"
        assert gldo.is_docked() is True
        services2 = gldo.get_active_services()
        assert services2["hull_repair"] == pytest.approx(22.5)
        assert services2["torpedo_resupply"] == pytest.approx(15.0)
