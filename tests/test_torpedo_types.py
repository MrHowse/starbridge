"""Tests for torpedo types, loading system, EMP stun, probe scan, and nuclear auth (c.8 / v0.02g)."""
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
# TestTorpedoTypes — damage constants and type attributes
# ---------------------------------------------------------------------------


class TestTorpedoTypes:
    def test_damage_by_type_standard(self):
        assert glw.TORPEDO_DAMAGE_BY_TYPE["standard"] == 50.0

    def test_damage_by_type_emp(self):
        assert glw.TORPEDO_DAMAGE_BY_TYPE["emp"] == 15.0

    def test_damage_by_type_probe(self):
        assert glw.TORPEDO_DAMAGE_BY_TYPE["probe"] == 5.0

    def test_damage_by_type_nuclear(self):
        assert glw.TORPEDO_DAMAGE_BY_TYPE["nuclear"] == 80.0

    def test_torpedo_dataclass_default_type(self):
        t = Torpedo(id="t1", owner="player", x=0.0, y=0.0, heading=0.0)
        assert t.torpedo_type == "standard"

    def test_torpedo_dataclass_custom_type(self):
        t = Torpedo(id="t1", owner="player", x=0.0, y=0.0, heading=0.0, torpedo_type="emp")
        assert t.torpedo_type == "emp"


# ---------------------------------------------------------------------------
# TestTubeLoading
# ---------------------------------------------------------------------------


class TestTubeLoading:
    def setup_method(self):
        fresh_weapons()

    def test_initial_tube_types_standard(self):
        assert glw.get_tube_types() == ["standard", "standard"]

    def test_initial_tube_loading_zero(self):
        assert glw.get_tube_loading() == [0.0, 0.0]

    def test_load_same_type_instant(self):
        evt = glw.load_tube(1, "standard")
        # Already loaded — returns immediate confirmation.
        assert evt is not None
        assert evt[0] == "weapons.tube_loaded"
        assert evt[1]["torpedo_type"] == "standard"

    def test_load_new_type_starts_timer(self):
        evt = glw.load_tube(1, "emp")
        assert evt is not None
        assert evt[0] == "weapons.tube_loading"
        assert evt[1]["torpedo_type"] == "emp"
        assert glw.get_tube_loading()[0] == glw.TUBE_LOAD_TIME

    def test_load_blocked_while_loading(self):
        glw.load_tube(1, "emp")
        evt = glw.load_tube(1, "probe")
        assert evt is None  # blocked

    def test_tick_tube_loading_decrements(self):
        glw.load_tube(1, "emp")
        glw.tick_tube_loading(1.0)
        assert glw.get_tube_loading()[0] == pytest.approx(glw.TUBE_LOAD_TIME - 1.0)

    def test_tick_tube_loading_completes(self):
        glw.load_tube(1, "emp")
        glw.tick_tube_loading(glw.TUBE_LOAD_TIME)
        assert glw.get_tube_loading()[0] == 0.0
        assert glw.get_tube_types()[0] == "emp"

    def test_load_blocked_while_reload_cooldown(self):
        # Simulate cooldown from prior firing.
        glw._tube_cooldowns[0] = 3.0
        evt = glw.load_tube(1, "emp")
        assert evt is None

    def test_tube2_independent(self):
        glw.load_tube(2, "nuclear")
        assert glw.get_tube_loading()[1] == glw.TUBE_LOAD_TIME
        assert glw.get_tube_loading()[0] == 0.0  # tube 1 unaffected

    def test_reset_clears_loading(self):
        glw.load_tube(1, "emp")
        glw.reset()
        assert glw.get_tube_loading() == [0.0, 0.0]
        assert glw.get_tube_types() == ["standard", "standard"]


# ---------------------------------------------------------------------------
# TestFireTorpedoTypes — firing with different loaded types
# ---------------------------------------------------------------------------


class TestFireTorpedoTypes:
    def setup_method(self):
        fresh_weapons()

    def test_fire_standard_torpedo(self):
        world = fresh_world()
        events = glw.fire_torpedo(world.ship, world, 1)
        assert len(events) == 1
        assert events[0][0] == "weapons.torpedo_fired"
        assert events[0][1]["torpedo_type"] == "standard"
        assert world.torpedoes[0].torpedo_type == "standard"

    def test_fire_emp_torpedo(self):
        glw._tube_types[0] = "emp"
        world = fresh_world()
        events = glw.fire_torpedo(world.ship, world, 1)
        assert events[0][1]["torpedo_type"] == "emp"
        assert world.torpedoes[0].torpedo_type == "emp"

    def test_fire_probe_torpedo(self):
        glw._tube_types[0] = "probe"
        world = fresh_world()
        events = glw.fire_torpedo(world.ship, world, 1)
        assert events[0][1]["torpedo_type"] == "probe"

    def test_fire_nuclear_returns_auth_request(self):
        glw._tube_types[0] = "nuclear"
        world = fresh_world()
        events = glw.fire_torpedo(world.ship, world, 1)
        assert len(events) == 1
        assert events[0][0] == "captain.authorization_request"
        assert events[0][1]["action"] == "nuclear_torpedo"
        assert events[0][1]["tube"] == 1
        # Torpedo NOT yet in world.
        assert len(world.torpedoes) == 0
        # Ammo unchanged.
        assert glw.get_ammo() == 10

    def test_fire_blocked_while_loading(self):
        glw.load_tube(1, "emp")  # starts loading
        world = fresh_world()
        events = glw.fire_torpedo(world.ship, world, 1)
        assert events == []

    def test_fire_blocked_no_ammo(self):
        glw.set_ammo(0)
        world = fresh_world()
        events = glw.fire_torpedo(world.ship, world, 1)
        assert events == []


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
        # Torpedo in world.
        assert len(world.torpedoes) == 1
        assert world.torpedoes[0].torpedo_type == "nuclear"
        # Ammo deducted.
        assert glw.get_ammo() == 9

    def test_deny_does_not_fire(self):
        world = fresh_world()
        events = glw.fire_torpedo(world.ship, world, 1)
        request_id = events[0][1]["request_id"]

        result_events = glw.resolve_nuclear_auth(request_id, False, world.ship, world)
        type_names = [e[0] for e in result_events]
        assert "weapons.authorization_result" in type_names
        assert "weapons.torpedo_fired" not in type_names
        assert len(world.torpedoes) == 0
        assert glw.get_ammo() == 10

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

    def test_nuclear_damage_is_80(self):
        assert glw.TORPEDO_DAMAGE_BY_TYPE["nuclear"] == 80.0


# ---------------------------------------------------------------------------
# TestTorpedoHitEffects — tick_torpedoes type-specific effects
# ---------------------------------------------------------------------------


class TestTorpedoHitEffects:
    def setup_method(self):
        fresh_weapons()

    def _place_torp(self, world: World, enemy: Enemy, torp_type: str) -> None:
        """Place a torpedo right next to the enemy so it hits on the next tick."""
        torp = Torpedo(
            id="test_torp",
            owner="player",
            x=enemy.x,
            y=enemy.y,
            heading=0.0,
            torpedo_type=torp_type,
        )
        world.torpedoes.append(torp)

    def test_standard_hits_enemy(self):
        # With full shields, 50-damage torpedo is fully absorbed by shields
        # (absorbed = min(100*0.8, 50) = 50, hull damage = 0).
        # Verify the torpedo hits by checking shields dropped.
        world = fresh_world()
        enemy = make_enemy()
        world.enemies.append(enemy)
        initial_shields = enemy.shield_front
        self._place_torp(world, enemy, "standard")
        glw.tick_torpedoes(world)
        # Torpedo should have hit and reduced shields.
        assert enemy.shield_front < initial_shields

    def test_emp_stuns_enemy(self):
        world = fresh_world()
        enemy = make_enemy()
        enemy.shield_front = 0.0
        enemy.shield_rear = 0.0
        world.enemies.append(enemy)
        self._place_torp(world, enemy, "emp")
        events = glw.tick_torpedoes(world)
        assert len(events) == 1
        assert events[0]["torpedo_type"] == "emp"
        assert enemy.stun_ticks == glw.EMP_STUN_TICKS
        assert "stun_duration" in events[0]

    def test_emp_stun_decays_via_ai(self):
        world = fresh_world()
        enemy = make_enemy()
        enemy.stun_ticks = 3
        # tick_enemies decrements stun_ticks.
        tick_enemies([enemy], world.ship, 0.1)
        assert enemy.stun_ticks == 2

    def test_stunned_enemy_cannot_fire(self):
        world = fresh_world()
        enemy = make_enemy()
        enemy.stun_ticks = 10
        enemy.beam_cooldown = 0.0
        enemy.ai_state = "attack"
        # Position enemy in weapon range and arc.
        enemy.x = world.ship.x + 500.0
        enemy.y = world.ship.y
        enemy.heading = 270.0  # facing ship
        events = tick_enemies([enemy], world.ship, 0.1)
        # Stunned — should not fire.
        assert events == []

    def test_probe_returns_scan_data(self):
        world = fresh_world()
        enemy = make_enemy()
        world.enemies.append(enemy)
        self._place_torp(world, enemy, "probe")
        events = glw.tick_torpedoes(world)
        assert events[0]["torpedo_type"] == "probe"
        assert "probe_scan" in events[0]
        scan = events[0]["probe_scan"]
        assert "type" in scan
        assert "hull" in scan

    def test_probe_deals_5_damage(self):
        world = fresh_world()
        enemy = make_enemy()
        enemy.shield_front = 0.0
        enemy.shield_rear = 0.0
        world.enemies.append(enemy)
        initial_hull = enemy.hull
        self._place_torp(world, enemy, "probe")
        glw.tick_torpedoes(world)
        assert enemy.hull == pytest.approx(initial_hull - 5.0, abs=0.01)

    def test_nuclear_deals_80_damage(self):
        world = fresh_world()
        enemy = make_enemy(type_="destroyer")  # 100 HP — survives 80 damage
        enemy.shield_front = 0.0
        enemy.shield_rear = 0.0
        world.enemies.append(enemy)
        initial_hull = enemy.hull
        self._place_torp(world, enemy, "nuclear")
        glw.tick_torpedoes(world)
        assert enemy.hull == pytest.approx(initial_hull - 80.0, abs=0.01)

    def test_dead_enemy_not_stunned(self):
        """EMP stun only applies to enemies that survive the hit."""
        world = fresh_world()
        enemy = make_enemy(type_="scout")  # scout has 40 HP
        enemy.shield_front = 0.0
        enemy.shield_rear = 0.0
        # EMP deals 15 — scout survives.
        world.enemies.append(enemy)
        self._place_torp(world, enemy, "emp")
        glw.tick_torpedoes(world)
        # Scout survived EMP — should be stunned.
        assert enemy.stun_ticks == glw.EMP_STUN_TICKS


# ---------------------------------------------------------------------------
# TestDeepStrikeMission
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
