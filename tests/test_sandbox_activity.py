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
        for key in (
            "enemy_spawn", "system_damage", "crew_casualty", "boarding",
            "incoming_transmission", "hull_micro_damage", "sensor_anomaly",
            "drone_opportunity", "enemy_jamming", "distress_signal",
        ):
            assert key in glsb._timers, f"timer '{key}' missing after activate"

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
        assert 1 <= len(board[0]["intruders"]) <= 3
        for intruder in board[0]["intruders"]:
            assert "id" in intruder
            assert intruder["room_id"] == "cargo_hold"
            assert intruder["objective_id"] is not None

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

    # --- incoming_transmission ---

    def test_incoming_transmission_fires_on_timer(self) -> None:
        glsb.reset(active=True)
        glsb._timers["incoming_transmission"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        txs = [e for e in events if e["type"] == "incoming_transmission"]
        assert len(txs) == 1
        tx = txs[0]
        assert tx["faction"] in glsb.TRANSMISSION_FACTIONS
        assert tx["frequency"] == glsb.TRANSMISSION_FACTIONS[tx["faction"]]
        assert "message_hint" in tx

    def test_incoming_transmission_timer_reset(self) -> None:
        glsb.reset(active=True)
        glsb._timers["incoming_transmission"] = 0.05
        world = _make_world()
        glsb.tick(world, 0.1)
        assert glsb._timers["incoming_transmission"] > 10.0

    # --- hull_micro_damage ---

    def test_hull_micro_damage_fires_on_timer(self) -> None:
        glsb.reset(active=True)
        glsb._timers["hull_micro_damage"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        dmg = [e for e in events if e["type"] == "hull_micro_damage"]
        assert len(dmg) == 1
        assert 2.0 <= dmg[0]["amount"] <= 8.0

    def test_hull_micro_damage_timer_reset(self) -> None:
        glsb.reset(active=True)
        glsb._timers["hull_micro_damage"] = 0.05
        world = _make_world()
        glsb.tick(world, 0.1)
        assert glsb._timers["hull_micro_damage"] > 10.0

    # --- sensor_anomaly ---

    def test_sensor_anomaly_fires_on_timer(self) -> None:
        glsb.reset(active=True)
        glsb._timers["sensor_anomaly"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        anoms = [e for e in events if e["type"] == "sensor_anomaly"]
        assert len(anoms) == 1
        a = anoms[0]
        assert a["anomaly_type"] in glsb.SENSOR_ANOMALY_TYPES
        assert "x" in a and "y" in a and "id" in a
        assert 0 <= a["x"] <= world.width
        assert 0 <= a["y"] <= world.height

    def test_sensor_anomaly_timer_reset(self) -> None:
        glsb.reset(active=True)
        glsb._timers["sensor_anomaly"] = 0.05
        world = _make_world()
        glsb.tick(world, 0.1)
        assert glsb._timers["sensor_anomaly"] > 10.0

    # --- drone_opportunity ---

    def test_drone_opportunity_fires_on_timer(self) -> None:
        glsb.reset(active=True)
        glsb._timers["drone_opportunity"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        ops = [e for e in events if e["type"] == "drone_opportunity"]
        assert len(ops) == 1
        op = ops[0]
        assert op["label"] in glsb.DRONE_OPPORTUNITY_LABELS
        assert "x" in op and "y" in op and "id" in op
        assert 0 <= op["x"] <= world.width
        assert 0 <= op["y"] <= world.height

    def test_drone_opportunity_timer_reset(self) -> None:
        glsb.reset(active=True)
        glsb._timers["drone_opportunity"] = 0.05
        world = _make_world()
        glsb.tick(world, 0.1)
        assert glsb._timers["drone_opportunity"] > 10.0

    # --- enemy_jamming ---

    def test_enemy_jamming_fires_on_timer(self) -> None:
        glsb.reset(active=True)
        glsb._timers["enemy_jamming"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        jams = [e for e in events if e["type"] == "enemy_jamming"]
        assert len(jams) == 1
        assert 0.3 <= jams[0]["strength"] <= 0.7

    def test_enemy_jamming_timer_reset(self) -> None:
        glsb.reset(active=True)
        glsb._timers["enemy_jamming"] = 0.05
        world = _make_world()
        glsb.tick(world, 0.1)
        assert glsb._timers["enemy_jamming"] > 10.0

    # --- distress_signal ---

    def test_distress_signal_fires_on_timer(self) -> None:
        glsb.reset(active=True)
        glsb._timers["distress_signal"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        sigs = [e for e in events if e["type"] == "distress_signal"]
        assert len(sigs) == 1
        sig = sigs[0]
        assert sig["frequency"] == 0.90
        assert "x" in sig and "y" in sig
        assert 0 <= sig["x"] <= world.width
        assert 0 <= sig["y"] <= world.height

    def test_distress_signal_timer_reset(self) -> None:
        glsb.reset(active=True)
        glsb._timers["distress_signal"] = 0.05
        world = _make_world()
        glsb.tick(world, 0.1)
        assert glsb._timers["distress_signal"] > 10.0

    # --- all 10 event types can fire in same tick ---

    def test_all_ten_event_types_can_fire_same_tick(self) -> None:
        glsb.reset(active=True)
        for key in glsb._timers:
            glsb._timers[key] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        types = {e["type"] for e in events}
        assert "spawn_enemy"            in types
        assert "system_damage"          in types
        assert "crew_casualty"          in types
        assert "incoming_transmission"  in types
        assert "hull_micro_damage"      in types
        assert "sensor_anomaly"         in types
        assert "drone_opportunity"      in types
        assert "enemy_jamming"          in types
        assert "distress_signal"        in types
        assert "security_incident"      in types
        # start_boarding may be suppressed if boarding already active; just check others


class TestSecurityIncidents:
    """Playtest Fix 6: Minor security events for Security station."""

    def test_security_incident_fires_on_timer(self) -> None:
        glsb.reset(active=True)
        glsb._timers["security_event"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        incidents = [e for e in events if e["type"] == "security_incident"]
        assert len(incidents) == 1
        inc = incidents[0]
        assert inc["incident"] in [t["incident"] for t in glsb.SECURITY_INCIDENT_TYPES]
        assert "message" in inc
        assert "deck" in inc

    def test_security_incident_timer_resets(self) -> None:
        glsb.reset(active=True)
        glsb._timers["security_event"] = 0.05
        world = _make_world()
        glsb.tick(world, 0.1)
        assert glsb._timers["security_event"] > 10.0

    def test_boarding_party_size_varies(self) -> None:
        """Boarding party size is 1-3 intruders (randomized)."""
        sizes: set[int] = set()
        for _ in range(50):
            glsb.reset(active=True)
            glsb._timers["boarding"] = 0.05
            world = _make_world()
            events = glsb.tick(world, 0.1)
            board = [e for e in events if e["type"] == "start_boarding"]
            if board:
                sizes.add(len(board[0]["intruders"]))
        # Over 50 trials, we should see at least 2 distinct sizes.
        assert len(sizes) >= 2, f"Expected varied sizes, got {sizes}"

    def test_boarding_interval_reduced(self) -> None:
        """Boarding interval is now 75-120s (was 120-180)."""
        assert glsb.BOARDING_INTERVAL == (75.0, 120.0)
