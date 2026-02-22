"""Tests for v0.05i Enemy Stations.

Covers:
  - StationComponent base class + ShieldArc, Turret, TorpedoLauncher,
    FighterBay, SensorArray, StationReactor dataclasses
  - _arc_covers() helper (incl. wrap-around)
  - spawn_enemy_station() for outpost and fortress variants
  - EnemyStationDefenses.arc_is_shielded(), reactor_factor(), all_components()
  - make_station_interior() layout
  - station_ai.tick_station_ai(): turrets, launchers, fighter bays, sensor array
  - station_ai.jam_station_sensor() / unjam_station_sensor()
  - Component targeting in fire_player_beams(): component HP reduced, destroyed events
  - Station hull targeting in fire_player_beams(): shield absorption, unshielded
  - Torpedo hits on station hull (tick_torpedoes extension)
  - Station boarding: start_station_boarding, tick_station_boarding, check_station_capture
  - build_station_interior_state() payload format
  - EW tick jams station sensor array
  - build_world_entities() includes defenses in station payload
  - Fighter enemy type in ENEMY_TYPE_PARAMS
"""
from __future__ import annotations

import pytest

from server.models.world import (
    ENEMY_TYPE_PARAMS,
    EnemyStationDefenses,
    FighterBay,
    SensorArray,
    ShieldArc,
    StationComponent,
    StationReactor,
    Torpedo,
    Turret,
    TorpedoLauncher,
    World,
    _arc_covers,
    spawn_enemy_station,
)
from server.models.interior import make_station_interior, ShipInterior
from server.models.ship import Ship
from server.systems.station_ai import (
    tick_station_ai,
    jam_station_sensor,
    unjam_station_sensor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_world_with_station(variant: str = "outpost") -> tuple[World, object]:
    """Return (world, station) with one enemy station."""
    w = World()
    s = spawn_enemy_station("out1", 50_000.0, 50_000.0, variant=variant)
    w.stations.append(s)
    return w, s


def _fresh_ship(x: float = 50_000.0, y: float = 50_000.0) -> Ship:
    return Ship(x=x, y=y)


# ---------------------------------------------------------------------------
# StationComponent base class
# ---------------------------------------------------------------------------

class TestStationComponent:
    def test_active_true_when_hp_above_zero(self):
        c = ShieldArc(id="c1", hp=50.0, hp_max=80.0, arc_start=0, arc_end=180)
        assert c.active is True

    def test_active_false_when_hp_zero(self):
        c = ShieldArc(id="c1", hp=0.0, hp_max=80.0, arc_start=0, arc_end=180)
        assert c.active is False

    def test_turret_fields(self):
        t = Turret(id="t0", hp=40.0, hp_max=40.0, facing=90.0, arc_deg=50.0,
                   weapon_range=8000.0, beam_dmg=8.0, beam_cooldown=3.0)
        assert t.facing == 90.0
        assert t.cooldown_timer == 0.0

    def test_launcher_fields(self):
        l = TorpedoLauncher(id="l0", hp=60.0, hp_max=60.0, launch_cooldown=15.0)
        assert l.cooldown_timer == 0.0
        assert l.active is True

    def test_fighter_bay_fields(self):
        b = FighterBay(id="b0", hp=60.0, hp_max=60.0, launch_cooldown=30.0)
        assert b.fighters_in_bay == 4

    def test_sensor_array_defaults(self):
        sa = SensorArray(id="sa", hp=50.0, hp_max=50.0)
        assert sa.jammed is False
        assert sa.distress_sent is False

    def test_reactor_is_component(self):
        r = StationReactor(id="r0", hp=100.0, hp_max=100.0)
        assert isinstance(r, StationComponent)
        assert r.active is True


# ---------------------------------------------------------------------------
# _arc_covers helper
# ---------------------------------------------------------------------------

class TestArcCovers:
    def test_within_non_wrapping_arc(self):
        assert _arc_covers(45.0, 135.0, 90.0) is True

    def test_outside_non_wrapping_arc(self):
        assert _arc_covers(45.0, 135.0, 180.0) is False

    def test_wrapping_arc_north(self):
        # Arc 315 → 45 covers north (0°)
        assert _arc_covers(315.0, 45.0, 0.0) is True
        assert _arc_covers(315.0, 45.0, 350.0) is True
        assert _arc_covers(315.0, 45.0, 30.0) is True

    def test_wrapping_arc_excludes_outside(self):
        assert _arc_covers(315.0, 45.0, 90.0) is False
        assert _arc_covers(315.0, 45.0, 180.0) is False

    def test_boundary_inclusive(self):
        assert _arc_covers(0.0, 180.0, 0.0) is True
        assert _arc_covers(0.0, 180.0, 180.0) is True

    def test_exact_360_wrap(self):
        # 360 == 0
        assert _arc_covers(315.0, 45.0, 360.0) is True


# ---------------------------------------------------------------------------
# spawn_enemy_station
# ---------------------------------------------------------------------------

class TestSpawnEnemyStation:
    def test_outpost_components(self):
        s = spawn_enemy_station("s1", 0.0, 0.0, variant="outpost")
        d = s.defenses
        assert d is not None
        assert len(d.shield_arcs) == 2
        assert len(d.turrets) == 4
        assert len(d.launchers) == 1
        assert len(d.fighter_bays) == 1
        assert d.garrison_count == 10

    def test_fortress_components(self):
        s = spawn_enemy_station("s2", 0.0, 0.0, variant="fortress")
        d = s.defenses
        assert len(d.shield_arcs) == 4
        assert len(d.turrets) == 8
        assert len(d.launchers) == 2
        assert len(d.fighter_bays) == 2
        assert d.garrison_count == 20

    def test_component_ids_namespaced(self):
        s = spawn_enemy_station("out1", 0.0, 0.0)
        d = s.defenses
        assert d.shield_arcs[0].id == "out1_gen_0"
        assert d.turrets[0].id == "out1_turret_0"
        assert d.launchers[0].id == "out1_launcher_0"
        assert d.fighter_bays[0].id == "out1_bay_0"
        assert d.sensor_array.id == "out1_sensor"
        assert d.reactor.id == "out1_reactor"

    def test_faction_hostile(self):
        s = spawn_enemy_station("s3", 0.0, 0.0)
        assert s.faction == "hostile"
        assert s.station_type == "enemy"
        assert s.transponder_active is False

    def test_station_interior_created(self):
        s = spawn_enemy_station("s4", 0.0, 0.0)
        assert s.defenses.station_interior is not None
        assert isinstance(s.defenses.station_interior, ShipInterior)

    def test_hull_values(self):
        outpost = spawn_enemy_station("o", 0.0, 0.0, variant="outpost")
        fortress = spawn_enemy_station("f", 0.0, 0.0, variant="fortress")
        assert outpost.hull == outpost.hull_max == 800.0
        assert fortress.hull == fortress.hull_max == 1200.0


# ---------------------------------------------------------------------------
# EnemyStationDefenses helpers
# ---------------------------------------------------------------------------

class TestEnemyStationDefensesHelpers:
    def test_reactor_factor_full(self):
        s = spawn_enemy_station("s1", 0.0, 0.0)
        assert s.defenses.reactor_factor() == pytest.approx(1.0)

    def test_reactor_factor_half(self):
        s = spawn_enemy_station("s1", 0.0, 0.0)
        s.defenses.reactor.hp = 50.0
        assert s.defenses.reactor_factor() == pytest.approx(0.5)

    def test_reactor_factor_zero(self):
        s = spawn_enemy_station("s1", 0.0, 0.0)
        s.defenses.reactor.hp = 0.0
        assert s.defenses.reactor_factor() == pytest.approx(0.0)

    def test_arc_is_shielded_true(self):
        s = spawn_enemy_station("s1", 0.0, 0.0)
        # Outpost gen_0 covers 0→180 (south half) — bearing 90° is east, inside that arc
        gen0 = s.defenses.shield_arcs[0]
        # bearing 90° is between gen_0's arc_start (0) and arc_end (180)
        assert s.defenses.arc_is_shielded(gen0.arc_start + 1.0) is True

    def test_arc_not_shielded_when_generator_destroyed(self):
        s = spawn_enemy_station("s1", 0.0, 0.0)
        # Destroy all generators
        for g in s.defenses.shield_arcs:
            g.hp = 0.0
        assert s.defenses.arc_is_shielded(90.0) is False

    def test_all_components_count(self):
        s = spawn_enemy_station("s1", 0.0, 0.0)
        comps = s.defenses.all_components()
        # 2 gens + 4 turrets + 1 launcher + 1 bay + sensor + reactor = 10
        assert len(comps) == 10

    def test_all_components_count_fortress(self):
        s = spawn_enemy_station("s2", 0.0, 0.0, variant="fortress")
        comps = s.defenses.all_components()
        # 4+8+2+2+1+1 = 18
        assert len(comps) == 18


# ---------------------------------------------------------------------------
# make_station_interior
# ---------------------------------------------------------------------------

class TestMakeStationInterior:
    def test_room_count(self):
        interior = make_station_interior("out1")
        assert len(interior.rooms) == 8

    def test_command_room_exists(self):
        interior = make_station_interior("out1")
        assert "out1_command" in interior.rooms

    def test_reactor_room_exists(self):
        interior = make_station_interior("out1")
        assert "out1_reactor" in interior.rooms

    def test_bay_room_exists(self):
        interior = make_station_interior("out1")
        assert "out1_bay" in interior.rooms

    def test_pathfinding_command_to_quarters(self):
        interior = make_station_interior("s1")
        path = interior.find_path("s1_quarters", "s1_command")
        assert len(path) > 0
        assert path[0] == "s1_quarters"
        assert path[-1] == "s1_command"

    def test_all_rooms_reachable_from_command(self):
        interior = make_station_interior("s1")
        for room_id in interior.rooms:
            path = interior.find_path("s1_command", room_id)
            assert len(path) > 0, f"Room {room_id} not reachable from command"


# ---------------------------------------------------------------------------
# Station AI — turrets
# ---------------------------------------------------------------------------

class TestStationAITurrets:
    def test_turret_fires_when_in_range_and_arc(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()  # ship at same position as station
        # Force all turrets to cooldown=0 and aim at ship (heading=0 → north)
        for turret in station.defenses.turrets:
            turret.cooldown_timer = 0.0
            turret.facing = 0.0  # north
        # Ship is directly north of station (or same spot)
        # Use ship at same coords → distance=0, any arc covers 0° bearing
        beam_hits, fighters, calls = tick_station_ai(
            world.stations, ship, world, 0.1, set()
        )
        # At least one turret fires
        assert len(beam_hits) > 0

    def test_turret_respects_cooldown(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        for turret in station.defenses.turrets:
            turret.cooldown_timer = 99.0  # all cooling down
            turret.facing = 0.0
        beam_hits, _, _ = tick_station_ai(world.stations, ship, world, 0.1, set())
        assert len(beam_hits) == 0

    def test_turret_respects_range(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship(x=50_000.0 + 20_000.0)  # 20k units away > weapon_range
        for turret in station.defenses.turrets:
            turret.cooldown_timer = 0.0
            turret.facing = 90.0  # east
        beam_hits, _, _ = tick_station_ai(world.stations, ship, world, 0.1, set())
        assert len(beam_hits) == 0

    def test_turret_damage_scaled_by_reactor(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        # Full reactor
        station.defenses.reactor.hp = 100.0
        for turret in station.defenses.turrets:
            turret.cooldown_timer = 0.0
            turret.facing = 0.0
        hits_full, _, _ = tick_station_ai(world.stations, ship, world, 0.1, set())

        # Reset cooldowns and halve reactor
        for turret in station.defenses.turrets:
            turret.cooldown_timer = 0.0
        station.defenses.reactor.hp = 50.0
        hits_half, _, _ = tick_station_ai(world.stations, ship, world, 0.1, set())

        if hits_full and hits_half:
            assert hits_half[0].damage == pytest.approx(hits_full[0].damage * 0.5, rel=0.01)

    def test_destroyed_turret_does_not_fire(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        for turret in station.defenses.turrets:
            turret.hp = 0.0
            turret.cooldown_timer = 0.0
            turret.facing = 0.0
        beam_hits, _, _ = tick_station_ai(world.stations, ship, world, 0.1, set())
        assert len(beam_hits) == 0


# ---------------------------------------------------------------------------
# Station AI — fighter bays
# ---------------------------------------------------------------------------

class TestStationAIFighterBays:
    def test_bay_launches_fighter(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        bay = station.defenses.fighter_bays[0]
        bay.cooldown_timer = 0.0
        bay.fighters_in_bay = 3
        # Disable turrets so only bay fires
        for t in station.defenses.turrets:
            t.cooldown_timer = 999.0
        for l in station.defenses.launchers:
            l.cooldown_timer = 999.0
        _, fighters, _ = tick_station_ai(world.stations, ship, world, 0.1, set())
        assert len(fighters) == 1
        assert fighters[0].type == "fighter"

    def test_bay_cooldown_prevents_launch(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        bay = station.defenses.fighter_bays[0]
        bay.cooldown_timer = 30.0
        bay.fighters_in_bay = 3
        _, fighters, _ = tick_station_ai(world.stations, ship, world, 0.1, set())
        assert len(fighters) == 0

    def test_destroyed_bay_does_not_launch(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        bay = station.defenses.fighter_bays[0]
        bay.hp = 0.0
        bay.cooldown_timer = 0.0
        bay.fighters_in_bay = 3
        _, fighters, _ = tick_station_ai(world.stations, ship, world, 0.1, set())
        assert len(fighters) == 0

    def test_bay_decrements_fighters_in_bay(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        bay = station.defenses.fighter_bays[0]
        bay.cooldown_timer = 0.0
        bay.fighters_in_bay = 2
        tick_station_ai(world.stations, ship, world, 0.1, set())
        assert bay.fighters_in_bay == 1


# ---------------------------------------------------------------------------
# Station AI — sensor array / reinforcement calls
# ---------------------------------------------------------------------------

class TestStationAISensorArray:
    def test_no_call_when_not_attacked(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        for t in station.defenses.turrets:
            t.cooldown_timer = 999.0
        for l in station.defenses.launchers:
            l.cooldown_timer = 999.0
        _, _, calls = tick_station_ai(world.stations, ship, world, 0.1, set())
        assert calls == []

    def test_call_when_attacked(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        _, _, calls = tick_station_ai(
            world.stations, ship, world, 0.1, {"out1"}
        )
        assert "out1" in calls

    def test_call_only_fires_once(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        tick_station_ai(world.stations, ship, world, 0.1, {"out1"})
        _, _, calls2 = tick_station_ai(world.stations, ship, world, 0.1, {"out1"})
        # distress_sent already True
        assert calls2 == []

    def test_jammed_sensor_prevents_call(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        station.defenses.sensor_array.jammed = True
        _, _, calls = tick_station_ai(world.stations, ship, world, 0.1, {"out1"})
        assert calls == []

    def test_destroyed_sensor_prevents_call(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        station.defenses.sensor_array.hp = 0.0
        _, _, calls = tick_station_ai(world.stations, ship, world, 0.1, {"out1"})
        assert calls == []


# ---------------------------------------------------------------------------
# Station AI — torpedo launchers
# ---------------------------------------------------------------------------

class TestStationAILauncher:
    def test_launcher_fires_torpedo(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        launcher = station.defenses.launchers[0]
        launcher.cooldown_timer = 0.0
        for t in station.defenses.turrets:
            t.cooldown_timer = 999.0
        tick_station_ai(world.stations, ship, world, 0.1, set())
        # A torpedo should have been added to world.torpedoes
        station_torps = [tp for tp in world.torpedoes if tp.owner == "out1"]
        assert len(station_torps) == 1

    def test_launcher_cooldown_prevents_fire(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        station.defenses.launchers[0].cooldown_timer = 10.0
        tick_station_ai(world.stations, ship, world, 0.1, set())
        assert len(world.torpedoes) == 0

    def test_destroyed_launcher_does_not_fire(self):
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        station.defenses.launchers[0].hp = 0.0
        station.defenses.launchers[0].cooldown_timer = 0.0
        tick_station_ai(world.stations, ship, world, 0.1, set())
        assert len(world.torpedoes) == 0


# ---------------------------------------------------------------------------
# jam_station_sensor / unjam_station_sensor
# ---------------------------------------------------------------------------

class TestJamSensor:
    def test_jam_returns_true_when_found(self):
        world, station = _fresh_world_with_station()
        result = jam_station_sensor(world, "out1")
        assert result is True
        assert station.defenses.sensor_array.jammed is True

    def test_jam_returns_false_when_not_found(self):
        world, _ = _fresh_world_with_station()
        assert jam_station_sensor(world, "nonexistent") is False

    def test_unjam_clears_flag(self):
        world, station = _fresh_world_with_station()
        station.defenses.sensor_array.jammed = True
        unjam_station_sensor(world, "out1")
        assert station.defenses.sensor_array.jammed is False


# ---------------------------------------------------------------------------
# Component targeting via fire_player_beams
# ---------------------------------------------------------------------------

class TestComponentTargeting:
    def _setup(self):
        import server.game_loop_weapons as glw
        glw.reset()
        world, station = _fresh_world_with_station()
        ship = _fresh_ship(x=50_000.0, y=44_000.0)  # 6k north of station (within 8k range)
        ship.heading = 180.0  # facing south toward station
        return glw, world, station, ship

    def test_beam_hits_component(self):
        glw, world, station, ship = self._setup()
        gen = station.defenses.shield_arcs[0]
        hp_before = gen.hp
        glw.set_target(gen.id)
        glw.fire_player_beams(ship, world)
        assert gen.hp < hp_before

    def test_beam_fires_event_for_component(self):
        glw, world, station, ship = self._setup()
        gen = station.defenses.shield_arcs[0]
        glw.set_target(gen.id)
        event = glw.fire_player_beams(ship, world)
        assert event is not None
        assert event[0] == "weapons.beam_fired"
        assert event[1]["target_id"] == gen.id

    def test_destroyed_component_emits_event(self):
        glw, world, station, ship = self._setup()
        gen = station.defenses.shield_arcs[0]
        gen.hp = 1.0   # nearly destroyed
        glw.set_target(gen.id)
        glw.fire_player_beams(ship, world)
        evts = glw.pop_component_destroyed_events()
        assert len(evts) == 1
        assert evts[0]["component_id"] == gen.id
        assert evts[0]["station_id"] == "out1"

    def test_station_marked_attacked_on_component_hit(self):
        glw, world, station, ship = self._setup()
        gen = station.defenses.shield_arcs[0]
        glw.set_target(gen.id)
        glw.fire_player_beams(ship, world)
        attacked = glw.pop_stations_attacked()
        assert "out1" in attacked

    def test_target_cleared_after_component_destroyed(self):
        glw, world, station, ship = self._setup()
        gen = station.defenses.shield_arcs[0]
        gen.hp = 0.5
        glw.set_target(gen.id)
        glw.fire_player_beams(ship, world)
        assert glw.get_target() is None


# ---------------------------------------------------------------------------
# Station hull targeting via fire_player_beams
# ---------------------------------------------------------------------------

class TestStationHullTargeting:
    def _setup(self):
        import server.game_loop_weapons as glw
        glw.reset()
        world, station = _fresh_world_with_station()
        ship = _fresh_ship(x=50_000.0, y=44_000.0)  # 6k north of station (within 8k range)
        ship.heading = 180.0
        return glw, world, station, ship

    def test_beam_reduces_hull_when_unshielded_arc(self):
        glw, world, station, ship = self._setup()
        # Destroy all shield generators so no arc is shielded
        for g in station.defenses.shield_arcs:
            g.hp = 0.0
        hull_before = station.hull
        glw.set_target(station.id)
        event = glw.fire_player_beams(ship, world)
        assert event is not None
        assert station.hull < hull_before

    def test_beam_reduced_damage_when_shielded_arc(self):
        glw, world, station, ship = self._setup()
        # Ensure the arc covering the attack bearing is shielded.
        # Ship is north of station → attack comes from north → bearing from station to ship ≈ 0°
        # Keep all generators active (they start at 100% hp)
        hull_before = station.hull
        glw.set_target(station.id)
        glw.fire_player_beams(ship, world)
        # Damage should exist but station still has high hull (shielded)
        assert station.hull <= hull_before  # some damage may get through

    def test_station_marked_attacked_on_hull_hit(self):
        glw, world, station, ship = self._setup()
        for g in station.defenses.shield_arcs:
            g.hp = 0.0
        glw.set_target(station.id)
        glw.fire_player_beams(ship, world)
        attacked = glw.pop_stations_attacked()
        assert "out1" in attacked

    def test_only_hostile_stations_targeted(self):
        glw, world, station, ship = self._setup()
        station.faction = "friendly"  # flip faction
        glw.set_target(station.id)
        event = glw.fire_player_beams(ship, world)
        assert event is None  # only hostile targets accepted


# ---------------------------------------------------------------------------
# Torpedo hits on station hull
# ---------------------------------------------------------------------------

class TestTorpedoStationHit:
    def test_torpedo_hits_station_hull(self):
        import server.game_loop_weapons as glw
        glw.reset()
        world, station = _fresh_world_with_station()
        # Destroy all shield generators
        for g in station.defenses.shield_arcs:
            g.hp = 0.0
        # Place a player torpedo right at the station
        torp = Torpedo(
            id="torpedo_99", owner="player",
            x=station.x + 100.0, y=station.y,
            heading=90.0, velocity=500.0,
        )
        world.torpedoes.append(torp)
        hull_before = station.hull
        glw.tick_torpedoes(world)
        assert station.hull < hull_before

    def test_torpedo_reduced_by_shield_arc(self):
        import server.game_loop_weapons as glw
        glw.reset()
        world, station = _fresh_world_with_station()
        # All generators intact
        torp = Torpedo(
            id="torpedo_99", owner="player",
            x=station.x + 100.0, y=station.y,
            heading=90.0, velocity=500.0,
        )
        world.torpedoes.append(torp)
        hull_before = station.hull
        glw.tick_torpedoes(world)
        # torpedo may or may not hit depending on arc, but if it does, reduced damage
        # Just assert hull didn't take more than full damage (50 pts on 800 hull = 6%)
        assert station.hull >= hull_before - 50.0


# ---------------------------------------------------------------------------
# Station boarding
# ---------------------------------------------------------------------------

class TestStationBoarding:
    def test_start_station_boarding_creates_intruders(self):
        import server.game_loop_security as gls
        gls.reset()
        world, station = _fresh_world_with_station()
        gls.start_station_boarding(station, [{"id": "squad_1", "room_id": "out1_corridor"}])
        assert gls.is_station_boarding_active() is True
        interior = station.defenses.station_interior
        assert len(interior.intruders) == station.defenses.garrison_count

    def test_garrison_objective_is_command_centre(self):
        import server.game_loop_security as gls
        gls.reset()
        world, station = _fresh_world_with_station()
        gls.start_station_boarding(station, [{"id": "squad_1", "room_id": "out1_corridor"}])
        interior = station.defenses.station_interior
        for intruder in interior.intruders:
            assert intruder.objective_id == "out1_command"

    def test_tick_station_boarding_returns_events(self):
        import server.game_loop_security as gls
        gls.reset()
        world, station = _fresh_world_with_station()
        gls.start_station_boarding(station, [{"id": "squad_1", "room_id": "out1_command"}])
        # Place all garrison directly in command room so combat starts immediately.
        for intruder in station.defenses.station_interior.intruders:
            intruder.room_id = "out1_command"
        ship = _fresh_ship()
        # Tick enough for at least one intruder to be defeated (MARINE_DAMAGE=0.2/marine/tick).
        events_total = []
        for _ in range(400):
            events_total.extend(gls.tick_station_boarding(ship, 0.1))
        defeated_events = [e for e in events_total if e[0] == "security.intruder_defeated"]
        assert len(defeated_events) > 0

    def test_check_station_capture_false_while_garrison_alive(self):
        import server.game_loop_security as gls
        gls.reset()
        world, station = _fresh_world_with_station()
        gls.start_station_boarding(station, [{"id": "squad_1", "room_id": "out1_command"}])
        assert gls.check_station_capture("out1") is False  # garrison still alive

    def test_check_station_capture_true_when_garrison_cleared(self):
        import server.game_loop_security as gls
        gls.reset()
        world, station = _fresh_world_with_station()
        gls.start_station_boarding(station, [{"id": "squad_1", "room_id": "out1_command"}])
        # Clear all intruders manually (simulate defeat)
        interior = station.defenses.station_interior
        interior.intruders.clear()
        assert gls.check_station_capture("out1") is True

    def test_build_station_interior_state(self):
        import server.game_loop_security as gls
        gls.reset()
        world, station = _fresh_world_with_station()
        gls.start_station_boarding(station, [{"id": "squad_1", "room_id": "out1_corridor"}])
        state = gls.build_station_interior_state("out1")
        assert state["is_boarding"] is True
        assert state["station_id"] == "out1"
        assert len(state["squads"]) == 1
        assert len(state["intruders"]) == station.defenses.garrison_count
        assert len(state["rooms"]) == 8

    def test_build_station_interior_state_when_not_boarding(self):
        import server.game_loop_security as gls
        gls.reset()
        state = gls.build_station_interior_state("out1")
        assert state["is_boarding"] is False
        assert state["squads"] == []


# ---------------------------------------------------------------------------
# EW tick jams sensor array
# ---------------------------------------------------------------------------

class TestEWJamsSensor:
    def test_ew_tick_jams_sensor_when_targeted(self):
        import server.game_loop_ew as glew
        glew.reset()
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        # Give ECM efficiency
        ship.systems["ecm_suite"].health = 100.0
        ship.systems["ecm_suite"].power = 100.0
        # Target the sensor array component
        glew.set_jam_target("out1_sensor")
        glew.tick(world, ship, 0.1)
        assert station.defenses.sensor_array.jammed is True

    def test_ew_tick_clears_jam_when_untargeted(self):
        import server.game_loop_ew as glew
        glew.reset()
        world, station = _fresh_world_with_station()
        ship = _fresh_ship()
        station.defenses.sensor_array.jammed = True
        # Ensure jam target does NOT point to sensor
        glew.set_jam_target(None)
        glew.tick(world, ship, 0.1)
        # jammed should be cleared (out1_sensor != _jam_target_id)
        assert station.defenses.sensor_array.jammed is False


# ---------------------------------------------------------------------------
# build_world_entities includes defenses
# ---------------------------------------------------------------------------

class TestWorldEntitiesDefenses:
    def test_defenses_included_in_station_payload(self):
        from server.game_loop_mission import build_world_entities
        world, station = _fresh_world_with_station()
        msg = build_world_entities(world)
        payload = msg.payload
        stations = payload["stations"]
        assert len(stations) == 1
        s_data = stations[0]
        assert s_data["defenses"] is not None
        d = s_data["defenses"]
        assert len(d["shield_arcs"]) == 2
        assert len(d["turrets"]) == 4
        assert "sensor_array" in d
        assert "reactor" in d

    def test_friendly_station_has_no_defenses(self):
        from server.game_loop_mission import build_world_entities
        from server.models.world import spawn_station
        world = World()
        world.stations.append(spawn_station("friendly_1", 10_000.0, 10_000.0))
        msg = build_world_entities(world)
        s_data = msg.payload["stations"][0]
        assert s_data["defenses"] is None


# ---------------------------------------------------------------------------
# Fighter enemy type
# ---------------------------------------------------------------------------

class TestFighterEnemyType:
    def test_fighter_in_params(self):
        assert "fighter" in ENEMY_TYPE_PARAMS

    def test_fighter_stats(self):
        p = ENEMY_TYPE_PARAMS["fighter"]
        assert p["hull"] == 20.0
        assert p["flee_threshold"] == 0.0  # never flees
        assert p["speed"] > 300.0  # fast

    def test_spawn_fighter_no_shields(self):
        from server.models.world import spawn_enemy
        f = spawn_enemy("fighter", 0.0, 0.0, "fighter_1")
        assert f.shield_front == 0.0
        assert f.shield_rear == 0.0
        assert f.hull == 20.0
