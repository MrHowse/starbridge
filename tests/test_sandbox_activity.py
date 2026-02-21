"""Tests for the sandbox activity generator (server/game_loop_sandbox.py)."""
from __future__ import annotations

import pytest

import server.game_loop_sandbox as glsb
from server.models.world import World, spawn_enemy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_world() -> World:
    w = World()
    w.ship.x = 50_000.0
    w.ship.y = 50_000.0
    return w


def _drain(world: World, dt: float, n: int) -> list[dict]:
    """Advance the sandbox by *n* ticks of *dt* seconds and collect events."""
    events: list[dict] = []
    for _ in range(n):
        events.extend(glsb.tick(world, dt))
    return events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_sandbox():
    """Ensure sandbox is inactive before and after each test."""
    glsb.reset(active=False)
    yield
    glsb.reset(active=False)


# ---------------------------------------------------------------------------
# Inactive state
# ---------------------------------------------------------------------------


class TestSandboxInactive:
    def test_inactive_by_default(self) -> None:
        assert not glsb.is_active()

    def test_tick_returns_empty_when_inactive(self) -> None:
        world = _make_world()
        assert glsb.tick(world, 1.0) == []

    def test_reset_inactive_clears_timers_and_state(self) -> None:
        glsb.reset(active=True)
        glsb.reset(active=False)
        assert not glsb.is_active()
        world = _make_world()
        # Long advance — should still produce no events.
        assert _drain(world, 1.0, 300) == []


# ---------------------------------------------------------------------------
# Active state basics
# ---------------------------------------------------------------------------


class TestSandboxActive:
    def test_active_after_reset_true(self) -> None:
        glsb.reset(active=True)
        assert glsb.is_active()

    def test_timers_populated_on_activate(self) -> None:
        glsb.reset(active=True)
        assert "enemy_spawn"   in glsb._timers
        assert "system_damage" in glsb._timers
        assert "crew_casualty" in glsb._timers
        assert "boarding"      in glsb._timers

    # --- enemy spawn ---

    def test_enemy_spawn_fires_on_timer(self) -> None:
        glsb.reset(active=True)
        glsb._timers["enemy_spawn"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        spawns = [e for e in events if e["type"] == "spawn_enemy"]
        assert len(spawns) == 1
        e = spawns[0]
        assert e["enemy_type"] in glsb.ENEMY_TYPE_POOL
        assert "x" in e and "y" in e and "id" in e

    def test_enemy_spawn_capped_at_max_enemies(self) -> None:
        glsb.reset(active=True)
        glsb._timers["enemy_spawn"] = 0.05
        world = _make_world()
        for i in range(glsb.MAX_ENEMIES):
            world.enemies.append(spawn_enemy("scout", 10_000.0, 10_000.0, f"e{i}"))
        events = glsb.tick(world, 0.1)
        assert not any(e["type"] == "spawn_enemy" for e in events)

    def test_enemy_spawn_within_world_bounds(self) -> None:
        glsb.reset(active=True)
        world = _make_world()
        for _ in range(10):
            glsb._timers["enemy_spawn"] = 0.05
            for e in glsb.tick(world, 0.1):
                if e["type"] == "spawn_enemy":
                    assert 0 <= e["x"] <= world.width
                    assert 0 <= e["y"] <= world.height

    # --- system damage ---

    def test_system_damage_fires_on_timer(self) -> None:
        glsb.reset(active=True)
        glsb._timers["system_damage"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        dmg = [e for e in events if e["type"] == "system_damage"]
        assert len(dmg) == 1
        assert dmg[0]["system"] in glsb.DAMAGEABLE_SYSTEMS
        assert 8.0 <= dmg[0]["amount"] <= 20.0

    # --- crew casualty ---

    def test_crew_casualty_fires_on_timer(self) -> None:
        glsb.reset(active=True)
        glsb._timers["crew_casualty"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        cas = [e for e in events if e["type"] == "crew_casualty"]
        assert len(cas) == 1
        assert cas[0]["deck"] in glsb.CREW_DECKS
        assert cas[0]["count"] >= 1

    # --- boarding ---

    def test_boarding_fires_on_timer(self) -> None:
        glsb.reset(active=True)
        glsb._timers["boarding"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        board = [e for e in events if e["type"] == "start_boarding"]
        assert len(board) == 1
        assert len(board[0]["intruders"]) == 2
        for intruder in board[0]["intruders"]:
            assert "id" in intruder
            assert intruder["room_id"] == "conn"
            assert intruder["objective_id"] is None

    # --- multiple events ---

    def test_multiple_events_can_fire_same_tick(self) -> None:
        glsb.reset(active=True)
        glsb._timers["enemy_spawn"]   = 0.05
        glsb._timers["system_damage"] = 0.05
        glsb._timers["crew_casualty"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        types = {e["type"] for e in events}
        assert "spawn_enemy"   in types
        assert "system_damage" in types
        assert "crew_casualty" in types

    # --- timer reset ---

    def test_timer_reset_after_firing(self) -> None:
        glsb.reset(active=True)
        glsb._timers["enemy_spawn"] = 0.05
        world = _make_world()
        glsb.tick(world, 0.1)
        # Timer must have been re-armed to a full interval.
        assert glsb._timers["enemy_spawn"] > 10.0

    # --- unique IDs ---

    def test_entity_ids_are_unique_across_ticks(self) -> None:
        glsb.reset(active=True)
        world = _make_world()
        seen_ids: set[str] = set()
        for _ in range(6):
            glsb._timers["enemy_spawn"] = 0.05
            for e in glsb.tick(world, 0.1):
                if e["type"] == "spawn_enemy":
                    assert e["id"] not in seen_ids, f"Duplicate ID: {e['id']}"
                    seen_ids.add(e["id"])
