"""
v0.05m — Sandbox Overhaul.

Tests cover:
  - CREATURE_SPAWN_INTERVAL, MAX_SANDBOX_CREATURES, CREATURE_TYPE_POOL constants
  - creature_spawn timer added by reset(active=True)
  - tick() emits spawn_creature event when timer fires and under cap
  - tick() suppresses spawn_creature when MAX_SANDBOX_CREATURES reached
  - spawn_creature event has correct fields (type, creature_type, x, y, id)
  - creature_type from CREATURE_TYPE_POOL; leviathan excluded
  - setup_world() no-op when inactive
  - setup_world() adds friendly station (sb_port): faction, services, transponder
  - setup_world() adds derelict station (sb_derelict): faction, requires_scan, no services
  - setup_world() adds 2 hazard zones (nebula + asteroid_field)
  - sandbox creature_spawn handler populates world.creatures
"""
from __future__ import annotations

import pytest

import server.game_loop_sandbox as glsb
from server.models.world import Ship, World


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_world() -> World:
    w = World()
    w.ship = Ship()
    return w


def _tick_until(world: World, key: str, max_ticks: int = 10000) -> list[dict]:
    """Tick world until the given event key fires, return accumulated events."""
    all_events: list[dict] = []
    for _ in range(max_ticks):
        evts = glsb.tick(world, 1.0)
        all_events.extend(evts)
        if any(e["type"] == key for e in evts):
            return all_events
    return all_events


# ---------------------------------------------------------------------------
# 1. Constants
# ---------------------------------------------------------------------------


class TestSandboxConstants:
    def test_creature_spawn_interval_min(self):
        assert glsb.CREATURE_SPAWN_INTERVAL[0] == 240.0  # balanced from 300.0 in v0.05o

    def test_creature_spawn_interval_max(self):
        assert glsb.CREATURE_SPAWN_INTERVAL[1] == 360.0  # balanced from 480.0 in v0.05o

    def test_max_sandbox_creatures(self):
        assert glsb.MAX_SANDBOX_CREATURES == 3

    def test_creature_type_pool_non_empty(self):
        assert len(glsb.CREATURE_TYPE_POOL) > 0

    def test_leviathan_excluded_from_pool(self):
        assert "leviathan" not in glsb.CREATURE_TYPE_POOL

    def test_void_whale_in_pool(self):
        assert "void_whale" in glsb.CREATURE_TYPE_POOL

    def test_rift_stalker_in_pool(self):
        assert "rift_stalker" in glsb.CREATURE_TYPE_POOL

    def test_hull_leech_in_pool(self):
        assert "hull_leech" in glsb.CREATURE_TYPE_POOL

    def test_swarm_in_pool(self):
        assert "swarm" in glsb.CREATURE_TYPE_POOL


# ---------------------------------------------------------------------------
# 2. Creature spawn timer
# ---------------------------------------------------------------------------


class TestCreatureSpawnTimer:
    def setup_method(self):
        glsb.reset(active=True)

    def teardown_method(self):
        glsb.reset(active=False)

    def test_creature_spawn_timer_exists_after_reset(self):
        glsb.reset(active=True)
        assert "creature_spawn" in glsb._timers

    def test_creature_spawn_timer_positive_after_reset(self):
        glsb.reset(active=True)
        assert glsb._timers["creature_spawn"] > 0.0

    def test_creature_spawn_initial_timer_sooner_than_interval(self):
        """First spawn timer is staggered lower than the ongoing interval."""
        glsb.reset(active=True)
        initial = glsb._timers["creature_spawn"]
        assert initial <= glsb.CREATURE_SPAWN_INTERVAL[0]

    def test_creature_spawn_not_in_timers_when_inactive(self):
        glsb.reset(active=False)
        # Timer dict is cleared; creature_spawn should not be present.
        assert "creature_spawn" not in glsb._timers

    def test_spawn_creature_event_fires(self):
        """tick() emits spawn_creature when timer expires."""
        glsb.reset(active=True)
        # Force the timer to zero.
        glsb._timers["creature_spawn"] = 0.0
        world = _make_world()
        events = glsb.tick(world, 0.0)
        assert any(e["type"] == "spawn_creature" for e in events)

    def test_spawn_creature_event_has_required_fields(self):
        glsb.reset(active=True)
        glsb._timers["creature_spawn"] = 0.0
        world = _make_world()
        events = glsb.tick(world, 0.0)
        evt = next(e for e in events if e["type"] == "spawn_creature")
        assert "creature_type" in evt
        assert "x" in evt
        assert "y" in evt
        assert "id" in evt

    def test_spawn_creature_type_in_pool(self):
        glsb.reset(active=True)
        glsb._timers["creature_spawn"] = 0.0
        world = _make_world()
        events = glsb.tick(world, 0.0)
        evt = next(e for e in events if e["type"] == "spawn_creature")
        assert evt["creature_type"] in glsb.CREATURE_TYPE_POOL

    def test_spawn_creature_id_has_sb_prefix(self):
        glsb.reset(active=True)
        glsb._timers["creature_spawn"] = 0.0
        world = _make_world()
        events = glsb.tick(world, 0.0)
        evt = next(e for e in events if e["type"] == "spawn_creature")
        assert evt["id"].startswith("sb_c")

    def test_timer_resets_after_spawn(self):
        glsb.reset(active=True)
        glsb._timers["creature_spawn"] = 0.0
        world = _make_world()
        glsb.tick(world, 0.0)
        assert glsb._timers["creature_spawn"] >= glsb.CREATURE_SPAWN_INTERVAL[0]

    def test_max_creatures_suppresses_spawn(self):
        """spawn_creature event suppressed when world.creatures >= MAX_SANDBOX_CREATURES."""
        glsb.reset(active=True)
        glsb._timers["creature_spawn"] = 0.0
        world = _make_world()
        # Fill world.creatures to cap.
        from server.models.world import spawn_creature
        for i in range(glsb.MAX_SANDBOX_CREATURES):
            world.creatures.append(spawn_creature(f"c{i}", "void_whale", 0.0, 0.0))
        events = glsb.tick(world, 0.0)
        assert not any(e["type"] == "spawn_creature" for e in events)

    def test_max_creatures_timer_still_resets_when_suppressed(self):
        """Timer resets even when spawn is suppressed by the cap."""
        glsb.reset(active=True)
        glsb._timers["creature_spawn"] = 0.0
        world = _make_world()
        from server.models.world import spawn_creature
        for i in range(glsb.MAX_SANDBOX_CREATURES):
            world.creatures.append(spawn_creature(f"c{i}", "void_whale", 0.0, 0.0))
        glsb.tick(world, 0.0)
        assert glsb._timers["creature_spawn"] >= glsb.CREATURE_SPAWN_INTERVAL[0]

    def test_spawn_allowed_below_cap(self):
        """spawn_creature event fires when creature count is one below cap."""
        glsb.reset(active=True)
        glsb._timers["creature_spawn"] = 0.0
        world = _make_world()
        from server.models.world import spawn_creature
        for i in range(glsb.MAX_SANDBOX_CREATURES - 1):
            world.creatures.append(spawn_creature(f"c{i}", "void_whale", 0.0, 0.0))
        events = glsb.tick(world, 0.0)
        assert any(e["type"] == "spawn_creature" for e in events)

    def test_no_spawn_when_inactive(self):
        glsb.reset(active=False)
        world = _make_world()
        events = glsb.tick(world, 0.0)
        assert not any(e["type"] == "spawn_creature" for e in events)


# ---------------------------------------------------------------------------
# 3. setup_world — world entity population
# ---------------------------------------------------------------------------


class TestSetupWorld:
    def setup_method(self):
        glsb.reset(active=True)

    def teardown_method(self):
        glsb.reset(active=False)

    def test_no_op_when_inactive(self):
        glsb.reset(active=False)
        world = _make_world()
        glsb.setup_world(world)
        assert len(world.stations) == 0
        assert len(world.hazards) == 0

    def test_adds_two_stations(self):
        world = _make_world()
        glsb.setup_world(world)
        assert len(world.stations) == 2

    def test_friendly_station_present(self):
        world = _make_world()
        glsb.setup_world(world)
        station_ids = {s.id for s in world.stations}
        assert "sb_port" in station_ids

    def test_friendly_station_faction(self):
        world = _make_world()
        glsb.setup_world(world)
        port = next(s for s in world.stations if s.id == "sb_port")
        assert port.faction == "friendly"

    def test_friendly_station_has_services(self):
        world = _make_world()
        glsb.setup_world(world)
        port = next(s for s in world.stations if s.id == "sb_port")
        assert len(port.services) > 0

    def test_friendly_station_transponder_active(self):
        world = _make_world()
        glsb.setup_world(world)
        port = next(s for s in world.stations if s.id == "sb_port")
        assert port.transponder_active is True

    def test_friendly_station_type(self):
        world = _make_world()
        glsb.setup_world(world)
        port = next(s for s in world.stations if s.id == "sb_port")
        assert port.station_type == "repair_dock"

    def test_derelict_station_present(self):
        world = _make_world()
        glsb.setup_world(world)
        station_ids = {s.id for s in world.stations}
        assert "sb_derelict" in station_ids

    def test_derelict_faction_is_none(self):
        world = _make_world()
        glsb.setup_world(world)
        derelict = next(s for s in world.stations if s.id == "sb_derelict")
        assert derelict.faction == "none"

    def test_derelict_requires_scan(self):
        world = _make_world()
        glsb.setup_world(world)
        derelict = next(s for s in world.stations if s.id == "sb_derelict")
        assert derelict.requires_scan is True

    def test_derelict_no_services(self):
        world = _make_world()
        glsb.setup_world(world)
        derelict = next(s for s in world.stations if s.id == "sb_derelict")
        assert derelict.services == []

    def test_derelict_transponder_inactive(self):
        world = _make_world()
        glsb.setup_world(world)
        derelict = next(s for s in world.stations if s.id == "sb_derelict")
        assert derelict.transponder_active is False

    def test_derelict_station_type(self):
        world = _make_world()
        glsb.setup_world(world)
        derelict = next(s for s in world.stations if s.id == "sb_derelict")
        assert derelict.station_type == "derelict"

    def test_adds_two_hazards(self):
        world = _make_world()
        glsb.setup_world(world)
        assert len(world.hazards) == 2

    def test_nebula_hazard_present(self):
        world = _make_world()
        glsb.setup_world(world)
        hazard_types = {h.hazard_type for h in world.hazards}
        assert "nebula" in hazard_types

    def test_asteroid_field_hazard_present(self):
        world = _make_world()
        glsb.setup_world(world)
        hazard_types = {h.hazard_type for h in world.hazards}
        assert "asteroid_field" in hazard_types

    def test_nebula_has_stable_id(self):
        world = _make_world()
        glsb.setup_world(world)
        ids = {h.id for h in world.hazards}
        assert "sb_nebula_1" in ids

    def test_asteroid_field_has_stable_id(self):
        world = _make_world()
        glsb.setup_world(world)
        ids = {h.id for h in world.hazards}
        assert "sb_asteroids_1" in ids
