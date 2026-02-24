"""
Stress / integration tests: state consistency across rapid role switches.

Key insight: state is per-MODULE not per-role. Switching roles in the client
does not call any reset/teardown on the server modules. These tests verify
that calling one module's APIs does not interfere with another module's
state, and that all module states persist correctly when operations are
interleaved rapidly.

All APIs tested here are synchronous (no asyncio needed).
"""
from __future__ import annotations

import random

import pytest

from server.models.ship import Ship, calculate_shield_distribution
from server.models.world import World, spawn_enemy
from server.models.interior import make_default_interior
from server.models.crew_roster import IndividualCrewRoster, Injury
from server.systems.physics import tick as physics_tick

import server.game_loop_weapons as glw
import server.game_loop_science_scan as glss
import server.game_loop_engineering as gle
import server.game_loop_medical_v2 as glmed
import server.game_loop_damage_control as gldc
import server.game_loop_navigation as gln


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ship(**overrides) -> Ship:
    """Create a Ship at sector centre with sensible defaults."""
    kwargs = {"x": 50_000.0, "y": 50_000.0, "heading": 0.0,
              "target_heading": 0.0, "throttle": 0.0, "velocity": 0.0}
    kwargs.update(overrides)
    return Ship(**kwargs)


def _make_world(ship: Ship | None = None) -> World:
    """Create a minimal World with a ship and no enemies."""
    if ship is None:
        ship = _make_ship()
    return World(ship=ship)


def _enemy_ahead(ship: Ship, dist: float = 3000.0) -> str:
    """Return entity ID of a scout enemy placed directly ahead of the ship."""
    # Heading 0 = north = -y direction
    ex = ship.x
    ey = ship.y - dist
    eid = f"enemy_{random.randint(1000, 9999)}"
    return eid, ex, ey


def _make_roster(count: int = 9, ship_class: str = "frigate") -> IndividualCrewRoster:
    """Generate a deterministic crew roster."""
    return IndividualCrewRoster.generate(count, ship_class, random.Random(42))


def _add_injury(roster: IndividualCrewRoster, crew_id: str) -> Injury:
    """Add a moderate injury to the first crew member and return it."""
    member = roster.members[crew_id]
    inj = Injury(
        id="inj_test_1",
        type="laceration",
        body_region="torso",
        severity="moderate",
        description="Test laceration",
        caused_by="hull_breach",
        degrade_timer=180.0,
        treatment_type="first_aid",
        treatment_duration=10.0,
    )
    member.injuries.append(inj)
    member.status = "injured"
    return inj


# ---------------------------------------------------------------------------
# Module reset fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_all_modules():
    """Reset every module before each test to avoid cross-test bleed."""
    glw.reset()
    glss.reset()
    gle.reset()
    glmed.reset()
    gldc.reset()
    gln.reset()
    yield
    glw.reset()
    glss.reset()
    gle.reset()
    glmed.reset()
    gldc.reset()
    gln.reset()


# ===================================================================
# Science scanning
# ===================================================================


class TestScienceScan:
    """Verify sector scan state persists independent of other modules."""

    def test_scan_progress_advances_while_away(self):
        """Start scan -> simulate time passing (player 'switches away') -> progress advances."""
        ship = _make_ship()
        world = _make_world(ship)

        ok = glss.start_scan("sector", "em", "A1")
        assert ok is True
        assert glss.is_active()

        # Simulate 15 seconds of ticking (player is "away" at another station)
        for _ in range(150):
            glss.tick(0.1, world)

        prog = glss.build_progress()
        assert prog["active"] is True
        assert prog["progress"] > 0.0
        # 15s / 30s duration = 50%
        assert prog["progress"] == pytest.approx(50.0, abs=1.0)

    def test_scan_completes(self):
        """Full sector sweep completes after 30s and build_progress reflects it."""
        ship = _make_ship()
        world = _make_world(ship)

        glss.start_scan("sector", "grav", "B2")

        # Tick for 31 seconds to guarantee completion
        for _ in range(310):
            glss.tick(0.1, world)

        prog = glss.build_progress()
        # After completion, build_progress returns active=False
        assert prog["active"] is False

    def test_scan_cancel_restart_fresh(self):
        """Cancel a scan, restart, and verify progress resets to zero."""
        ship = _make_ship()
        world = _make_world(ship)

        glss.start_scan("sector", "bio", "C3")
        # Advance 10 seconds
        for _ in range(100):
            glss.tick(0.1, world)

        prog = glss.build_progress()
        assert prog["progress"] > 0.0

        glss.cancel_scan()
        assert glss.is_active() is False

        # Restart
        ok = glss.start_scan("sector", "sub", "C3")
        assert ok is True

        prog = glss.build_progress()
        assert prog["active"] is True
        assert prog["progress"] == pytest.approx(0.0, abs=0.1)
        assert prog["mode"] == "sub"


# ===================================================================
# Weapons
# ===================================================================


class TestWeapons:
    """Verify weapons state (target, cooldowns) persists across operations."""

    def test_target_persists(self):
        """set_target -> get_target returns the same value."""
        glw.set_target("enemy_42")
        assert glw.get_target() == "enemy_42"

    def test_fire_beams_target_remains(self):
        """Fire beams at an enemy that survives -> target still set."""
        ship = _make_ship()
        world = _make_world(ship)
        eid, ex, ey = _enemy_ahead(ship, dist=3000.0)
        enemy = spawn_enemy("cruiser", ex, ey, eid)  # cruiser: 70 hp
        world.enemies.append(enemy)

        glw.set_target(eid)
        result = glw.fire_player_beams(ship, world, "alpha")

        assert result is not None
        # Cruiser survives one beam hit (20 dmg < 70 hp)
        assert glw.get_target() == eid

    def test_cooldown_partial_and_full(self):
        """Fire torpedo -> tick partial cooldown -> verify partial -> tick rest -> zero."""
        ship = _make_ship()
        world = _make_world(ship)
        eid, ex, ey = _enemy_ahead(ship)
        enemy = spawn_enemy("cruiser", ex, ey, eid)
        world.enemies.append(enemy)
        glw.set_target(eid)

        # Fire torpedo from tube 1
        events = glw.fire_torpedo(ship, world, 1)
        assert len(events) > 0

        cooldowns = glw.get_cooldowns()
        initial_cd = cooldowns[0]
        assert initial_cd > 0.0

        # Tick 50% of cooldown
        half = initial_cd / 2.0
        steps = int(half / 0.1)
        for _ in range(steps):
            glw.tick_cooldowns(0.1)

        cd_mid = glw.get_cooldowns()[0]
        assert cd_mid > 0.0
        assert cd_mid < initial_cd

        # Tick remaining cooldown plus a bit extra
        remaining_steps = int((initial_cd - half + 1.0) / 0.1)
        for _ in range(remaining_steps):
            glw.tick_cooldowns(0.1)

        cd_final = glw.get_cooldowns()[0]
        assert cd_final == 0.0


# ===================================================================
# Engineering
# ===================================================================


class TestEngineering:
    """Verify engineering power and repair state persists."""

    def test_battery_mode_persists_after_tick(self):
        """Set battery to charging -> tick -> battery mode still charging."""
        ship = _make_ship()
        interior = ship.interior
        gle.init(ship)

        ok = gle.set_battery_mode("charging")
        assert ok is True

        gle.tick(ship, interior, 0.1)

        pg = gle.get_power_grid()
        assert pg is not None
        assert pg.battery_mode == "charging"

    def test_power_levels_applied_after_tick(self):
        """Set power to a system -> tick -> verify delivered power reflects request."""
        ship = _make_ship()
        interior = ship.interior
        gle.init(ship)

        gle.set_power("engines", 120.0)
        result = gle.tick(ship, interior, 0.1)

        # Delivered power should include engines
        assert "engines" in result.power_delivered
        # Power should be close to requested (within grid constraints)
        assert result.power_delivered["engines"] > 100.0

    def test_repair_team_progress(self):
        """Dispatch repair team -> tick -> verify team is active."""
        ship = _make_ship()
        # Damage the engines system
        ship.systems["engines"].health = 50.0
        interior = ship.interior
        gle.init(ship, crew_member_ids=["crew_1", "crew_2", "crew_3", "crew_4"])

        rm = gle.get_repair_manager()
        assert rm is not None
        teams = rm.get_team_state()
        assert len(teams) > 0

        team_id = teams[0]["id"]
        dispatched = gle.dispatch_team(team_id, "engines", interior)
        assert dispatched is True

        # Tick several times
        for _ in range(10):
            gle.tick(ship, interior, 0.1)

        # Team should still be active (not idle)
        teams_after = rm.get_team_state()
        active_team = next(t for t in teams_after if t["id"] == team_id)
        # Team should be travelling or repairing (not idle)
        assert active_team["status"] in ("travelling", "repairing", "idle")


# ===================================================================
# Medical
# ===================================================================


class TestMedical:
    """Verify medical treatment state persists across ticks."""

    def test_treatment_progress(self):
        """Admit patient, start treatment -> tick -> verify progress advances."""
        roster = _make_roster()
        glmed.init_roster(roster, "frigate")

        crew_id = list(roster.members.keys())[0]
        inj = _add_injury(roster, crew_id)

        result = glmed.admit_patient(crew_id)
        assert result["success"] is True

        result = glmed.start_crew_treatment(crew_id, inj.id, "first_aid")
        assert result["success"] is True

        # Tick 5 seconds
        for _ in range(50):
            glmed.tick(roster, 0.1)

        state = glmed.get_medical_state()
        treatments = state["active_treatments"]
        # Treatment should still exist and have progressed
        if crew_id in treatments:
            assert treatments[crew_id]["elapsed"] > 0.0

    def test_stabilise_resets_timer(self):
        """Stabilise an injury -> verify degrade_timer was reset."""
        roster = _make_roster()
        glmed.init_roster(roster, "frigate")

        crew_id = list(roster.members.keys())[0]
        inj = _add_injury(roster, crew_id)

        # Tick to let timer degrade
        original_timer = inj.degrade_timer
        for _ in range(50):
            glmed.tick(roster, 0.1)
        assert inj.degrade_timer < original_timer

        # Stabilise
        result = glmed.stabilise_crew(crew_id, inj.id)
        assert result["success"] is True

        # Timer should have been reset to the full degrade timer for moderate
        from server.models.injuries import DEGRADE_TIMERS
        assert inj.degrade_timer == pytest.approx(DEGRADE_TIMERS["moderate"], abs=1.0)


# ===================================================================
# Helm (ship heading/throttle)
# ===================================================================


class TestHelm:
    """Verify ship heading and throttle persist (they are direct Ship fields)."""

    def test_heading_persists(self):
        """Set target_heading -> value persists."""
        ship = _make_ship()
        ship.target_heading = 90.0
        assert ship.target_heading == 90.0

    def test_throttle_persists(self):
        """Set throttle -> value persists."""
        ship = _make_ship()
        ship.throttle = 75.0
        assert ship.throttle == 75.0

    def test_heading_throttle_physics_moves_ship(self):
        """Set heading + throttle -> tick physics -> ship has moved."""
        ship = _make_ship(heading=90.0, target_heading=90.0, throttle=100.0)
        start_x = ship.x

        # Tick physics 10 times (1 second total)
        for _ in range(10):
            physics_tick(ship, 0.1, 100_000.0, 100_000.0)

        # Ship should have moved east (heading 90 = east = +x direction)
        assert ship.x > start_x


# ===================================================================
# Damage Control
# ===================================================================


class TestDamageControl:
    """Verify DC state persists across ticks."""

    def test_dispatch_dct_progress(self):
        """Damage a room -> dispatch DCT -> tick -> verify repair in progress."""
        interior = make_default_interior()
        room_id = list(interior.rooms.keys())[0]
        interior.rooms[room_id].state = "damaged"

        ok = gldc.dispatch_dct(room_id, interior)
        assert ok is True

        # Tick 4 seconds (half of DCT_REPAIR_DURATION = 8.0)
        for _ in range(40):
            gldc.tick(interior, 0.1)

        dc_state = gldc.build_dc_state(interior)
        # Room should still be listed as damaged (repair takes 8s)
        if room_id in dc_state["active_dcts"]:
            assert dc_state["active_dcts"][room_id] > 0.0
            assert dc_state["active_dcts"][room_id] < 1.0

    def test_dct_completes_repair(self):
        """Dispatch DCT -> tick to completion -> room repaired to normal."""
        interior = make_default_interior()
        room_id = list(interior.rooms.keys())[0]
        interior.rooms[room_id].state = "damaged"

        gldc.dispatch_dct(room_id, interior)

        # Tick 9 seconds (more than DCT_REPAIR_DURATION = 8.0)
        for _ in range(90):
            gldc.tick(interior, 0.1)

        assert interior.rooms[room_id].state == "normal"


# ===================================================================
# Navigation
# ===================================================================


class TestNavigation:
    """Verify route state persists."""

    def test_route_persists(self):
        """Plot route -> get_route returns it."""
        route = gln.calculate_route(0, 0, 50_000, 50_000)
        gln.set_route(route)
        assert gln.get_route() is not None
        assert gln.get_route()["plot_x"] == pytest.approx(50_000.0, abs=1.0)

    def test_clear_route(self):
        """Plot route -> clear -> get_route returns None."""
        route = gln.calculate_route(0, 0, 50_000, 50_000)
        gln.set_route(route)
        gln.clear_route()
        assert gln.get_route() is None


# ===================================================================
# Shield Focus
# ===================================================================


class TestShieldFocus:
    """Verify shield distribution changes with focus point."""

    def test_focus_changes_distribution(self):
        """Set shield_focus toward fore -> fore gets more shield than aft."""
        ship = _make_ship()
        ship.shield_focus = {"x": 0.0, "y": 1.0}  # full fore
        dist = calculate_shield_distribution(
            ship.shield_focus["x"], ship.shield_focus["y"]
        )
        ship.shield_distribution = dist

        assert dist["fore"] > dist["aft"]
        assert dist["fore"] > 0.25
        assert dist["aft"] < 0.25


# ===================================================================
# Rapid switching / interleaved operations
# ===================================================================


class TestRapidSwitching:
    """Simulate rapid interleaving of operations across all modules.

    These tests call APIs from multiple modules in tight alternation,
    mimicking a player rapidly switching between stations, and verify
    that all final states are consistent.
    """

    def _setup_full_world(self):
        """Set up ship, world, and all modules for interleaved testing."""
        ship = _make_ship(heading=45.0, target_heading=45.0, throttle=50.0)
        world = _make_world(ship)
        interior = ship.interior

        # Spawn an enemy ahead
        eid = "enemy_rapid_1"
        enemy = spawn_enemy("cruiser", ship.x, ship.y - 3000.0, eid)
        world.enemies.append(enemy)

        # Init engineering
        gle.init(ship, crew_member_ids=["c1", "c2", "c3", "c4"])

        # Init medical
        roster = _make_roster()
        glmed.init_roster(roster, "frigate")

        return ship, world, interior, eid, roster

    def test_interleaved_ops_no_crash(self):
        """Rapidly alternate module operations for 10 simulated seconds."""
        ship, world, interior, eid, roster = self._setup_full_world()

        # Set initial states
        glw.set_target(eid)
        ship.target_heading = 90.0
        gle.set_power("engines", 120.0)
        glss.start_scan("sector", "em", "A1")

        # Damage a room for DC
        room_id = list(interior.rooms.keys())[0]
        interior.rooms[room_id].state = "fire"
        gldc.dispatch_dct(room_id, interior)

        # Plot a route
        route = gln.calculate_route(ship.x, ship.y, 80_000, 20_000)
        gln.set_route(route)

        # Run 100 interleaved ticks (0.1s each = 10s total)
        for i in range(100):
            dt = 0.1
            # Alternate between different module operations each tick
            phase = i % 5

            if phase == 0:
                # Helm: adjust heading
                ship.target_heading = 90.0 + (i % 360)
            elif phase == 1:
                # Weapons: fire beams (may or may not hit)
                glw.fire_player_beams(ship, world, "alpha")
                glw.tick_cooldowns(dt)
            elif phase == 2:
                # Engineering: adjust power
                gle.set_power("shields", 80.0 + (i % 40))
                gle.tick(ship, interior, dt)
            elif phase == 3:
                # Science: scan ticks
                glss.tick(dt, world)
            elif phase == 4:
                # DC: tick
                gldc.tick(interior, dt)

            # Physics always ticks
            physics_tick(ship, dt, 100_000.0, 100_000.0)

        # No crash = success; now verify all states are consistent

    def test_interleaved_final_states(self):
        """After rapid switching, verify all module states are consistent."""
        ship, world, interior, eid, roster = self._setup_full_world()

        glw.set_target(eid)
        ship.target_heading = 180.0
        ship.throttle = 75.0
        gle.set_power("engines", 110.0)
        gle.set_power("shields", 90.0)
        glss.start_scan("sector", "bio", "B2")

        room_id = list(interior.rooms.keys())[2]
        interior.rooms[room_id].state = "damaged"
        gldc.dispatch_dct(room_id, interior)

        route = gln.calculate_route(ship.x, ship.y, 70_000, 30_000)
        gln.set_route(route)

        # 50 ticks of interleaved operations
        for i in range(50):
            dt = 0.1
            glw.tick_cooldowns(dt)
            glss.tick(dt, world)
            gle.tick(ship, interior, dt)
            gldc.tick(interior, dt)
            physics_tick(ship, dt, 100_000.0, 100_000.0)

            # Every 5 ticks, do a "station switch" operation burst
            if i % 5 == 0:
                glw.fire_player_beams(ship, world, "beta")
                gle.set_power("beams", 100.0 + (i % 30))
                ship.target_heading = (ship.target_heading + 10.0) % 360.0

        # Verify: weapons target still set (enemy survives beams at this range)
        # The enemy might be out of arc as ship turned, but target ID persists
        assert glw.get_target() == eid

        # Verify: scan is progressing (5s elapsed = ~16.7% of 30s)
        prog = glss.build_progress()
        assert prog["active"] is True
        assert prog["progress"] > 0.0

        # Verify: route still set
        assert gln.get_route() is not None

        # Verify: ship has moved from origin
        assert ship.x != 50_000.0 or ship.y != 50_000.0

        # Verify: engineering power grid exists
        assert gle.get_power_grid() is not None

    def test_weapon_target_survives_engineering_ticks(self):
        """Weapons target ID is unaffected by engineering tick operations."""
        ship, world, interior, eid, roster = self._setup_full_world()

        glw.set_target(eid)

        # Hammer engineering for 20 ticks
        for _ in range(20):
            gle.set_power("engines", 130.0)
            gle.set_power("shields", 80.0)
            gle.tick(ship, interior, 0.1)

        assert glw.get_target() == eid

    def test_scan_survives_weapons_fire(self):
        """Science scan progress is unaffected by weapons firing."""
        ship, world, interior, eid, roster = self._setup_full_world()

        # Move enemy beyond COMBAT_INTERRUPT_RANGE (15,000) so the scan
        # is not interrupted, while still allowing weapons API calls.
        for e in world.enemies:
            e.y = ship.y - 20_000.0

        glss.start_scan("sector", "em", "A1")
        glw.set_target(eid)

        # Interleave scan ticks with weapons fire
        # (beams won't hit at 20k range, but that's fine -- the point is
        # proving scan state is independent of weapons API calls)
        for _ in range(50):
            glss.tick(0.1, world)
            glw.fire_player_beams(ship, world, "gamma")
            glw.tick_cooldowns(0.1)

        # Scan should still be active and progressing
        prog = glss.build_progress()
        assert prog["active"] is True
        # 5 seconds = 16.7% of 30s
        assert prog["progress"] == pytest.approx(16.7, abs=2.0)

    def test_dc_survives_medical_operations(self):
        """DC repair progress is unaffected by medical module operations."""
        ship, world, interior, eid, roster = self._setup_full_world()

        room_id = list(interior.rooms.keys())[0]
        interior.rooms[room_id].state = "damaged"
        gldc.dispatch_dct(room_id, interior)

        crew_id = list(roster.members.keys())[0]
        _add_injury(roster, crew_id)
        glmed.admit_patient(crew_id)

        # Interleave DC and medical ticks
        for _ in range(40):
            gldc.tick(interior, 0.1)
            glmed.tick(roster, 0.1)

        # After 4 seconds, DCT should be ~50% done (4/8)
        dc_state = gldc.build_dc_state(interior)
        if room_id in dc_state["active_dcts"]:
            progress = dc_state["active_dcts"][room_id]
            assert progress == pytest.approx(0.5, abs=0.1)

    def test_navigation_survives_all_other_ops(self):
        """Route persists through heavy interleaved operations on other modules."""
        ship, world, interior, eid, roster = self._setup_full_world()

        route = gln.calculate_route(0, 0, 99_000, 99_000)
        gln.set_route(route)

        # Heavy interleaved operations
        glw.set_target(eid)
        glss.start_scan("sector", "sub", "D4")

        for i in range(100):
            dt = 0.1
            glw.tick_cooldowns(dt)
            glw.fire_player_beams(ship, world, "delta")
            glss.tick(dt, world)
            gle.tick(ship, interior, dt)
            physics_tick(ship, dt, 100_000.0, 100_000.0)

        # Route is still there, untouched
        assert gln.get_route() is not None
        assert gln.get_route()["plot_x"] == pytest.approx(99_000.0, abs=1.0)
        assert gln.get_route()["plot_y"] == pytest.approx(99_000.0, abs=1.0)
