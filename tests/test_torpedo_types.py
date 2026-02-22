"""Tests for torpedo types, magazine system, and new v0.05g type behaviours.

v0.05g adds 8 torpedo types (standard, homing, ion, piercing, heavy, proximity,
nuclear, experimental) with per-type magazine tracking and type-specific
in-flight effects.
"""
from __future__ import annotations

import pytest

import server.game_loop_weapons as glw
from server.models.world import Enemy, Torpedo, World, spawn_enemy
from server.models.ship import Ship
from server.systems.ai import tick_enemies


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh_world() -> World:
    world = World()
    world.ship = Ship()
    world.ship.x = 50_000.0
    world.ship.y = 50_000.0
    return world


def make_enemy(*, x: float = 55_000.0, y: float = 50_000.0, type_: str = "cruiser") -> Enemy:
    e = spawn_enemy(type_, x, y, "e1")
    e.ai_state = "attack"
    e.beam_cooldown = 0.0
    return e


def fresh_weapons() -> None:
    glw.reset()


# ---------------------------------------------------------------------------
# TestTorpedoConstants — type list, damage, velocity, reload constants
# ---------------------------------------------------------------------------


class TestTorpedoConstants:
    def test_all_eight_types_present(self):
        types = glw.TORPEDO_TYPES
        assert set(types) == {"standard", "homing", "ion", "piercing",
                              "heavy", "proximity", "nuclear", "experimental"}

    def test_standard_damage(self):
        assert glw.TORPEDO_DAMAGE_BY_TYPE["standard"] == 50.0

    def test_homing_damage(self):
        assert glw.TORPEDO_DAMAGE_BY_TYPE["homing"] == 35.0

    def test_ion_damage(self):
        assert glw.TORPEDO_DAMAGE_BY_TYPE["ion"] == 10.0

    def test_piercing_damage(self):
        assert glw.TORPEDO_DAMAGE_BY_TYPE["piercing"] == 40.0

    def test_heavy_damage(self):
        assert glw.TORPEDO_DAMAGE_BY_TYPE["heavy"] == 100.0

    def test_proximity_damage(self):
        assert glw.TORPEDO_DAMAGE_BY_TYPE["proximity"] == 30.0

    def test_nuclear_damage(self):
        assert glw.TORPEDO_DAMAGE_BY_TYPE["nuclear"] == 200.0

    def test_heavy_slower_than_standard(self):
        assert glw.TORPEDO_VELOCITY_BY_TYPE["heavy"] < glw.TORPEDO_VELOCITY_BY_TYPE["standard"]

    def test_nuclear_slower_than_standard(self):
        assert glw.TORPEDO_VELOCITY_BY_TYPE["nuclear"] < glw.TORPEDO_VELOCITY_BY_TYPE["standard"]

    def test_nuclear_longest_reload(self):
        assert glw.TORPEDO_RELOAD_BY_TYPE["nuclear"] == max(glw.TORPEDO_RELOAD_BY_TYPE.values())

    def test_heavy_second_longest_reload(self):
        reloads = sorted(glw.TORPEDO_RELOAD_BY_TYPE.values())
        assert glw.TORPEDO_RELOAD_BY_TYPE["heavy"] >= reloads[-2]

    def test_standard_shortest_reload(self):
        assert glw.TORPEDO_RELOAD_BY_TYPE["standard"] == min(glw.TORPEDO_RELOAD_BY_TYPE.values())

    def test_ion_stun_ticks_100(self):
        assert glw.ION_STUN_TICKS == 100

    def test_proximity_blast_radius_2000(self):
        assert glw.PROXIMITY_BLAST_RADIUS == 2_000.0

    def test_default_loadout_has_all_types(self):
        for t in glw.TORPEDO_TYPES:
            assert t in glw.DEFAULT_TORPEDO_LOADOUT

    def test_torpedo_dataclass_new_homing_target_field(self):
        t = Torpedo(id="t1", owner="player", x=0.0, y=0.0, heading=0.0)
        assert t.homing_target is None


# ---------------------------------------------------------------------------
# TestMagazineManagement
# ---------------------------------------------------------------------------


class TestMagazineManagement:
    def setup_method(self):
        fresh_weapons()

    def test_get_ammo_returns_dict(self):
        ammo = glw.get_ammo()
        assert isinstance(ammo, dict)

    def test_get_ammo_max_matches_default(self):
        assert glw.get_ammo_max() == dict(glw.DEFAULT_TORPEDO_LOADOUT)

    def test_get_ammo_for_type_standard(self):
        assert glw.get_ammo_for_type("standard") == glw.DEFAULT_TORPEDO_LOADOUT["standard"]

    def test_get_ammo_for_type_nuclear(self):
        assert glw.get_ammo_for_type("nuclear") == glw.DEFAULT_TORPEDO_LOADOUT["nuclear"]

    def test_set_ammo_for_type(self):
        glw.set_ammo_for_type("standard", 3)
        assert glw.get_ammo_for_type("standard") == 3

    def test_set_ammo_for_type_clamps_negative(self):
        glw.set_ammo_for_type("standard", -5)
        assert glw.get_ammo_for_type("standard") == 0

    def test_reset_with_custom_loadout(self):
        loadout = {"standard": 2, "homing": 1, "ion": 0, "piercing": 0,
                   "heavy": 0, "proximity": 0, "nuclear": 0, "experimental": 0}
        glw.reset(loadout)
        assert glw.get_ammo_for_type("standard") == 2
        assert glw.get_ammo_for_type("homing") == 1
        assert glw.get_ammo_max()["standard"] == 2

    def test_fire_decrements_per_type_ammo(self):
        world = fresh_world()
        initial_std = glw.get_ammo_for_type("standard")
        glw.fire_torpedo(world.ship, world, 1)
        assert glw.get_ammo_for_type("standard") == initial_std - 1

    def test_fire_blocked_when_type_empty(self):
        glw.set_ammo_for_type("standard", 0)
        world = fresh_world()
        events = glw.fire_torpedo(world.ship, world, 1)
        assert events == []

    def test_other_types_not_affected_by_standard_fire(self):
        world = fresh_world()
        initial_hom = glw.get_ammo_for_type("homing")
        glw.fire_torpedo(world.ship, world, 1)  # fires standard
        assert glw.get_ammo_for_type("homing") == initial_hom

    def test_fire_ion_decrements_ion_count(self):
        glw._tube_types[0] = "ion"
        world = fresh_world()
        initial_ion = glw.get_ammo_for_type("ion")
        glw.fire_torpedo(world.ship, world, 1)
        assert glw.get_ammo_for_type("ion") == initial_ion - 1

    def test_fire_blocked_ion_when_empty(self):
        glw._tube_types[0] = "ion"
        glw.set_ammo_for_type("ion", 0)
        world = fresh_world()
        events = glw.fire_torpedo(world.ship, world, 1)
        assert events == []

    def test_experimental_zero_ammo_by_default_frigate(self):
        # Default loadout (frigate) has 0 experimental.
        assert glw.get_ammo_for_type("experimental") == 0


# ---------------------------------------------------------------------------
# TestTorpedoDataclass
# ---------------------------------------------------------------------------


class TestTorpedoDataclass:
    def test_default_type_standard(self):
        t = Torpedo(id="t1", owner="player", x=0.0, y=0.0, heading=0.0)
        assert t.torpedo_type == "standard"

    def test_custom_type_homing(self):
        t = Torpedo(id="t1", owner="player", x=0.0, y=0.0, heading=0.0,
                    torpedo_type="homing", homing_target="e1")
        assert t.torpedo_type == "homing"
        assert t.homing_target == "e1"

    def test_heavy_has_slow_velocity(self):
        world = fresh_world()
        glw._tube_types[0] = "heavy"
        glw.fire_torpedo(world.ship, world, 1)
        assert world.torpedoes[0].velocity == pytest.approx(
            glw.TORPEDO_VELOCITY_BY_TYPE["heavy"])


# ---------------------------------------------------------------------------
# TestTubeLoading — tube loading system (unchanged from v0.02g behaviour)
# ---------------------------------------------------------------------------


class TestTubeLoading:
    def setup_method(self):
        fresh_weapons()

    def test_initial_tube_types_standard(self):
        assert glw.get_tube_types() == ["standard", "standard"]

    def test_load_same_type_instant(self):
        evt = glw.load_tube(1, "standard")
        assert evt is not None
        assert evt[0] == "weapons.tube_loaded"

    def test_load_new_type_starts_timer(self):
        evt = glw.load_tube(1, "homing")
        assert evt[0] == "weapons.tube_loading"
        assert glw.get_tube_loading()[0] == glw.TUBE_LOAD_TIME

    def test_load_invalid_type_returns_none(self):
        evt = glw.load_tube(1, "emp")   # old type — no longer valid
        assert evt is None

    def test_load_blocked_while_loading(self):
        glw.load_tube(1, "homing")
        evt = glw.load_tube(1, "ion")
        assert evt is None

    def test_tick_tube_loading_completes(self):
        glw.load_tube(1, "ion")
        glw.tick_tube_loading(glw.TUBE_LOAD_TIME)
        assert glw.get_tube_loading()[0] == 0.0
        assert glw.get_tube_types()[0] == "ion"

    def test_tube2_independent(self):
        glw.load_tube(2, "nuclear")
        assert glw.get_tube_loading()[1] == glw.TUBE_LOAD_TIME
        assert glw.get_tube_loading()[0] == 0.0

    def test_reset_clears_loading(self):
        glw.load_tube(1, "heavy")
        glw.reset()
        assert glw.get_tube_loading() == [0.0, 0.0]
        assert glw.get_tube_types() == ["standard", "standard"]


# ---------------------------------------------------------------------------
# TestFireTorpedoTypes
# ---------------------------------------------------------------------------


class TestFireTorpedoTypes:
    def setup_method(self):
        fresh_weapons()

    def test_fire_standard(self):
        world = fresh_world()
        events = glw.fire_torpedo(world.ship, world, 1)
        assert len(events) == 1
        assert events[0][1]["torpedo_type"] == "standard"

    def test_fire_homing_sets_homing_target(self):
        glw._tube_types[0] = "homing"
        glw.set_target("e1")
        world = fresh_world()
        glw.fire_torpedo(world.ship, world, 1)
        assert world.torpedoes[0].homing_target == "e1"

    def test_fire_homing_without_target_has_no_homing_target(self):
        glw._tube_types[0] = "homing"
        glw.set_target(None)
        world = fresh_world()
        glw.fire_torpedo(world.ship, world, 1)
        assert world.torpedoes[0].homing_target is None

    def test_fire_ion(self):
        glw._tube_types[0] = "ion"
        world = fresh_world()
        events = glw.fire_torpedo(world.ship, world, 1)
        assert events[0][1]["torpedo_type"] == "ion"

    def test_fire_heavy_has_slow_velocity(self):
        glw._tube_types[0] = "heavy"
        world = fresh_world()
        glw.fire_torpedo(world.ship, world, 1)
        assert world.torpedoes[0].velocity == pytest.approx(
            glw.TORPEDO_VELOCITY_BY_TYPE["heavy"])

    def test_fire_nuclear_returns_auth_request(self):
        glw._tube_types[0] = "nuclear"
        world = fresh_world()
        events = glw.fire_torpedo(world.ship, world, 1)
        assert events[0][0] == "captain.authorization_request"
        assert events[0][1]["action"] == "nuclear_torpedo"
        assert len(world.torpedoes) == 0
        # Nuclear ammo unchanged.
        assert glw.get_ammo_for_type("nuclear") == glw.DEFAULT_TORPEDO_LOADOUT["nuclear"]

    def test_fire_sets_tube_reload_time(self):
        world = fresh_world()
        glw.fire_torpedo(world.ship, world, 1)
        ref_times = glw.get_tube_reload_times()
        expected = glw.TORPEDO_RELOAD_BY_TYPE["standard"]  # at full efficiency
        assert ref_times[0] == pytest.approx(expected, rel=0.01)

    def test_heavy_reload_longer_than_standard(self):
        world = fresh_world()
        # Fire standard from tube 1
        glw.fire_torpedo(world.ship, world, 1)
        std_reload = glw.get_tube_reload_times()[0]

        glw.reset()
        world2 = fresh_world()
        glw._tube_types[0] = "heavy"
        glw.fire_torpedo(world2.ship, world2, 1)
        hvy_reload = glw.get_tube_reload_times()[0]

        assert hvy_reload > std_reload


# ---------------------------------------------------------------------------
# TestNuclearAuth
# ---------------------------------------------------------------------------


class TestNuclearAuth:
    def setup_method(self):
        fresh_weapons()
        glw._tube_types[0] = "nuclear"

    def test_auth_request_creates_pending(self):
        world = fresh_world()
        events = glw.fire_torpedo(world.ship, world, 1)
        request_id = events[0][1]["request_id"]
        assert request_id in glw._pending_nuclear_auths

    def test_approve_fires_torpedo(self):
        world = fresh_world()
        events = glw.fire_torpedo(world.ship, world, 1)
        request_id = events[0][1]["request_id"]
        result_events = glw.resolve_nuclear_auth(request_id, True, world.ship, world)
        type_names = [e[0] for e in result_events]
        assert "weapons.authorization_result" in type_names
        assert "weapons.torpedo_fired" in type_names
        assert len(world.torpedoes) == 1
        assert world.torpedoes[0].torpedo_type == "nuclear"
        assert glw.get_ammo_for_type("nuclear") == glw.DEFAULT_TORPEDO_LOADOUT["nuclear"] - 1

    def test_deny_does_not_fire(self):
        world = fresh_world()
        events = glw.fire_torpedo(world.ship, world, 1)
        request_id = events[0][1]["request_id"]
        result_events = glw.resolve_nuclear_auth(request_id, False, world.ship, world)
        type_names = [e[0] for e in result_events]
        assert "weapons.authorization_result" in type_names
        assert "weapons.torpedo_fired" not in type_names
        assert len(world.torpedoes) == 0
        assert glw.get_ammo_for_type("nuclear") == glw.DEFAULT_TORPEDO_LOADOUT["nuclear"]

    def test_resolve_unknown_request_empty(self):
        world = fresh_world()
        result = glw.resolve_nuclear_auth("nonexistent", True, world.ship, world)
        assert result == []

    def test_approve_clears_pending(self):
        world = fresh_world()
        events = glw.fire_torpedo(world.ship, world, 1)
        request_id = events[0][1]["request_id"]
        glw.resolve_nuclear_auth(request_id, True, world.ship, world)
        assert request_id not in glw._pending_nuclear_auths

    def test_nuclear_damage_200(self):
        assert glw.TORPEDO_DAMAGE_BY_TYPE["nuclear"] == 200.0


# ---------------------------------------------------------------------------
# TestTorpedoHitEffects — tick_torpedoes type-specific effects
# ---------------------------------------------------------------------------


class TestTorpedoHitEffects:
    def setup_method(self):
        fresh_weapons()

    def _place_torp(self, world: World, enemy: Enemy, torp_type: str) -> None:
        """Place a torpedo at the enemy's position so it hits on the next tick."""
        velocity = glw.TORPEDO_VELOCITY_BY_TYPE.get(torp_type, 500.0)
        torp = Torpedo(
            id="test_torp",
            owner="player",
            x=enemy.x,
            y=enemy.y,
            heading=0.0,
            torpedo_type=torp_type,
            velocity=velocity,
        )
        world.torpedoes.append(torp)

    # --- standard ---
    def test_standard_hits_enemy(self):
        world = fresh_world()
        enemy = make_enemy()
        world.enemies.append(enemy)
        initial_shields = enemy.shield_front
        self._place_torp(world, enemy, "standard")
        glw.tick_torpedoes(world)
        assert enemy.shield_front < initial_shields

    def test_standard_damage_50_with_no_shields(self):
        world = fresh_world()
        enemy = make_enemy(type_="destroyer")
        enemy.shield_front = 0.0
        enemy.shield_rear = 0.0
        world.enemies.append(enemy)
        initial_hull = enemy.hull
        self._place_torp(world, enemy, "standard")
        glw.tick_torpedoes(world)
        assert enemy.hull == pytest.approx(initial_hull - 50.0, abs=0.01)

    # --- homing ---
    def test_homing_torpedo_steers_toward_target(self):
        world = fresh_world()
        enemy = make_enemy(x=50_000.0, y=40_000.0)
        world.enemies.append(enemy)
        # Place homing torpedo south of enemy (heading=180 = south, enemy is north)
        torp = Torpedo(
            id="homing_torp", owner="player",
            x=50_000.0, y=60_000.0, heading=180.0,
            torpedo_type="homing", velocity=500.0, homing_target=enemy.id,
        )
        world.torpedoes.append(torp)
        initial_heading = torp.heading
        glw.tick_torpedoes(world)
        # Torpedo should have turned toward enemy (north = heading 0/360)
        # heading should decrease from 180 toward 0
        new_heading = torp.heading
        # 180 → 0 going counterclockwise: new heading should be < 180
        # (or > 270 if going clockwise, but HOMING_TURN_RATE limits turn)
        assert new_heading != initial_heading  # heading changed

    def test_homing_torpedo_hits_enemy_on_collision(self):
        world = fresh_world()
        enemy = make_enemy()
        world.enemies.append(enemy)
        # Place homing torpedo at enemy position — immediate hit
        torp = Torpedo(
            id="homing_torp", owner="player",
            x=enemy.x, y=enemy.y, heading=0.0,
            torpedo_type="homing", velocity=500.0, homing_target=enemy.id,
        )
        world.torpedoes.append(torp)
        events = glw.tick_torpedoes(world)
        assert len(events) == 1
        assert events[0]["torpedo_type"] == "homing"
        assert events[0]["damage"] == glw.TORPEDO_DAMAGE_BY_TYPE["homing"]

    # --- ion ---
    def test_ion_drains_shields_on_hit(self):
        world = fresh_world()
        enemy = make_enemy()
        enemy.shield_front = 50.0
        enemy.shield_rear = 50.0
        world.enemies.append(enemy)
        self._place_torp(world, enemy, "ion")
        events = glw.tick_torpedoes(world)
        assert len(events) == 1
        if enemy.hull > 0.0:  # enemy survived
            assert enemy.shield_front == 0.0
            assert enemy.shield_rear == 0.0
            assert events[0].get("shield_drained") is True

    def test_ion_stuns_surviving_enemy(self):
        world = fresh_world()
        enemy = make_enemy(type_="destroyer")  # high hull — survives 10 damage
        enemy.shield_front = 0.0
        enemy.shield_rear = 0.0
        world.enemies.append(enemy)
        self._place_torp(world, enemy, "ion")
        events = glw.tick_torpedoes(world)
        assert enemy.stun_ticks == glw.ION_STUN_TICKS
        assert events[0]["stun_duration"] == pytest.approx(glw.ION_STUN_TICKS / 10.0)

    def test_ion_stun_is_10_seconds(self):
        assert glw.ION_STUN_TICKS / 10.0 == pytest.approx(10.0)

    def test_ion_stun_decays_via_ai(self):
        world = fresh_world()
        enemy = make_enemy()
        enemy.stun_ticks = 3
        tick_enemies([enemy], world.ship, 0.1)
        assert enemy.stun_ticks == 2

    # --- piercing ---
    def test_piercing_bypasses_most_shields(self):
        world = fresh_world()
        enemy = make_enemy()
        enemy.shield_front = 100.0
        enemy.shield_rear = 0.0
        world.enemies.append(enemy)
        initial_hull = enemy.hull
        self._place_torp(world, enemy, "piercing")
        glw.tick_torpedoes(world)
        # Standard 50-dmg torpedo with full shields: all absorbed → hull 0.
        # Piercing 40-dmg with 25% absorption: absorbed = min(100*0.2, 40)=8 → hull -32.
        # Verify hull dropped more than it would with full shield absorption.
        assert enemy.hull < initial_hull

    def test_piercing_deals_hull_damage_through_shields(self):
        world = fresh_world()
        enemy = make_enemy(type_="destroyer")
        enemy.shield_front = 100.0
        enemy.shield_rear = 0.0
        world.enemies.append(enemy)
        initial_hull = enemy.hull
        self._place_torp(world, enemy, "piercing")
        glw.tick_torpedoes(world)
        # piercing damage=40, eff_coeff = 0.8 * 0.25 = 0.2
        # absorbed = min(100 * 0.2, 40) = min(20, 40) = 20
        # hull_damage = 40 - 20 = 20
        assert enemy.hull == pytest.approx(initial_hull - 20.0, abs=0.5)

    def test_standard_fully_absorbed_by_full_shields(self):
        world = fresh_world()
        enemy = make_enemy()
        # Standard damage=50 vs shield_front=100: absorbed = min(100*0.8, 50)=50 → hull unchanged
        enemy.shield_front = 100.0
        enemy.shield_rear = 0.0
        initial_hull = enemy.hull
        world.enemies.append(enemy)
        self._place_torp(world, enemy, "standard")
        glw.tick_torpedoes(world)
        # All 50 damage absorbed by shields, hull unchanged
        assert enemy.hull == pytest.approx(initial_hull, abs=0.01)

    # --- heavy ---
    def test_heavy_deals_100_damage_unshielded(self):
        world = fresh_world()
        enemy = make_enemy(type_="destroyer")  # 100 HP
        enemy.shield_front = 0.0
        enemy.shield_rear = 0.0
        world.enemies.append(enemy)
        initial_hull = enemy.hull
        self._place_torp(world, enemy, "heavy")
        glw.tick_torpedoes(world)
        assert enemy.hull == pytest.approx(initial_hull - 100.0, abs=0.01)

    # --- proximity ---
    def test_proximity_hits_multiple_enemies(self):
        world = fresh_world()
        e1 = spawn_enemy("scout", 50_000.0, 50_000.0, "e1")
        e2 = spawn_enemy("scout", 50_300.0, 50_000.0, "e2")  # 300 units away
        world.enemies.extend([e1, e2])
        # Place torpedo between both enemies.
        torp = Torpedo(
            id="prx_torp", owner="player",
            x=50_150.0, y=50_000.0, heading=0.0,
            torpedo_type="proximity", velocity=500.0,
        )
        world.torpedoes.append(torp)
        events = glw.tick_torpedoes(world)
        assert len(events) == 1
        assert events[0]["torpedo_type"] == "proximity"
        assert events[0]["hit_count"] == 2

    def test_proximity_does_not_hit_far_enemies(self):
        world = fresh_world()
        e1 = spawn_enemy("scout", 50_000.0, 50_000.0, "e1")
        # e2 is 5000 units away — outside PROXIMITY_BLAST_RADIUS
        e2 = spawn_enemy("scout", 55_000.0, 50_000.0, "e2")
        world.enemies.extend([e1, e2])
        torp = Torpedo(
            id="prx_torp", owner="player",
            x=50_000.0, y=50_000.0, heading=0.0,
            torpedo_type="proximity", velocity=500.0,
        )
        world.torpedoes.append(torp)
        events = glw.tick_torpedoes(world)
        assert events[0]["hit_count"] == 1

    def test_proximity_detonates_once(self):
        world = fresh_world()
        enemy = make_enemy()
        world.enemies.append(enemy)
        torp = Torpedo(
            id="prx_torp", owner="player",
            x=enemy.x, y=enemy.y, heading=0.0,
            torpedo_type="proximity", velocity=500.0,
        )
        world.torpedoes.append(torp)
        events = glw.tick_torpedoes(world)
        # Torpedo removed after detonation.
        assert len(world.torpedoes) == 0
        assert len(events) == 1

    # --- nuclear ---
    def test_nuclear_deals_200_damage_unshielded(self):
        world = fresh_world()
        # Place nuclear directly — bypass auth for this test.
        enemy = make_enemy(type_="destroyer")
        enemy.shield_front = 0.0
        enemy.shield_rear = 0.0
        world.enemies.append(enemy)
        torp = Torpedo(
            id="nuc_torp", owner="player",
            x=enemy.x, y=enemy.y, heading=0.0,
            torpedo_type="nuclear", velocity=400.0,
        )
        world.torpedoes.append(torp)
        # Destroyer has 100 HP — nuclear 200 damage kills it.
        initial_hull = enemy.hull
        events = glw.tick_torpedoes(world)
        assert enemy.hull <= 0.0
        assert events[0]["torpedo_type"] == "nuclear"

    # --- experimental ---
    def test_experimental_deals_direct_damage(self):
        # balanced in v0.05o: experimental now deals 60.0 damage (was 0.0)
        world = fresh_world()
        enemy = make_enemy()
        enemy.shield_front = 0.0
        enemy.shield_rear = 0.0
        world.enemies.append(enemy)
        initial_hull = enemy.hull
        torp = Torpedo(
            id="exp_torp", owner="player",
            x=enemy.x, y=enemy.y, heading=0.0,
            torpedo_type="experimental", velocity=500.0,
        )
        world.torpedoes.append(torp)
        glw.tick_torpedoes(world)
        assert enemy.hull < initial_hull  # experimental now deals real damage


# ---------------------------------------------------------------------------
# TestSerialisation — save/resume round-trip
# ---------------------------------------------------------------------------


class TestSerialisation:
    def setup_method(self):
        fresh_weapons()

    def test_serialise_returns_dict_ammo(self):
        data = glw.serialise()
        assert isinstance(data["torpedo_ammo"], dict)
        assert isinstance(data["torpedo_ammo_max"], dict)

    def test_deserialise_round_trip(self):
        glw.set_ammo_for_type("homing", 2)
        glw._tube_types[0] = "heavy"
        data = glw.serialise()

        glw.reset()
        glw.deserialise(data)
        assert glw.get_ammo_for_type("homing") == 2
        assert glw.get_tube_types()[0] == "heavy"

    def test_deserialise_backward_compat_int_ammo(self):
        """Old saves stored torpedo_ammo as int — should deserialise gracefully."""
        data = {"torpedo_ammo": 10, "tube_types": ["standard", "standard"],
                "tube_loading": [0.0, 0.0], "tube_type_loading": ["standard", "standard"],
                "tube_cooldowns": [0.0, 0.0], "tube_reload_times": [3.0, 3.0],
                "entity_counter": 0}
        glw.deserialise(data)
        # Should fall back to default loadout.
        assert isinstance(glw.get_ammo(), dict)
        assert "standard" in glw.get_ammo()

    def test_tube_reload_times_serialised(self):
        world = fresh_world()
        glw.fire_torpedo(world.ship, world, 1)
        data = glw.serialise()
        glw.reset()
        glw.deserialise(data)
        # Reload times should be non-default (i.e. match what was set on fire).
        assert glw.get_tube_reload_times()[0] > 0.0


# ---------------------------------------------------------------------------
# TestShipClassLoadout
# ---------------------------------------------------------------------------


class TestShipClassLoadout:
    def test_load_frigate_has_torpedo_loadout(self):
        from server.models.ship_class import load_ship_class
        sc = load_ship_class("frigate")
        loadout = sc.get_torpedo_loadout()
        assert isinstance(loadout, dict)
        assert "standard" in loadout
        assert "nuclear" in loadout

    def test_load_battleship_more_ammo_than_scout(self):
        from server.models.ship_class import load_ship_class
        bs = load_ship_class("battleship")
        sc = load_ship_class("scout")
        bs_total = sum(bs.get_torpedo_loadout().values())
        sc_total = sum(sc.get_torpedo_loadout().values())
        assert bs_total > sc_total

    def test_fallback_to_default_when_no_loadout(self):
        from server.models.ship_class import ShipClass, DEFAULT_TORPEDO_LOADOUT
        sc = ShipClass(id="test", name="Test", description="test",
                       max_hull=100.0, torpedo_ammo=12)
        loadout = sc.get_torpedo_loadout()
        assert loadout == DEFAULT_TORPEDO_LOADOUT


# ---------------------------------------------------------------------------
# TestDeepStrikeMission — unchanged from v0.02g
# ---------------------------------------------------------------------------


class TestDeepStrikeMission:
    def test_loadable(self):
        from server.missions.loader import load_mission
        m = load_mission("deep_strike")
        assert m["id"] == "deep_strike"

    def test_has_destroyer(self):
        from server.missions.loader import load_mission
        m = load_mission("deep_strike")
        assert any(s["type"] == "destroyer" for s in m["spawn"])

    def test_has_firing_solution_puzzle(self):
        from server.missions.loader import load_mission
        m = load_mission("deep_strike")
        actions = []
        for edge in m.get("edges", []):
            oc = edge.get("on_complete", [])
            if isinstance(oc, list):
                actions.extend(oc)
            elif isinstance(oc, dict):
                actions.append(oc)
        puzzle_actions = [a for a in actions if a.get("action") == "start_puzzle"]
        types = [a["puzzle_type"] for a in puzzle_actions]
        assert "firing_solution" in types

    def test_spawn_creates_destroyer(self):
        from server.missions.loader import load_mission, spawn_from_mission
        world = World()
        world.ship = Ship()
        m = load_mission("deep_strike")
        spawn_from_mission(m, world, entity_counter=0)
        assert any(e.type == "destroyer" for e in world.enemies)
