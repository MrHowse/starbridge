"""Tests for v0.07 §2.2 — Corvette Advanced ECM Suite.

Covers:
  - Capability gating (corvette-only)
  - Signal spoofing (ghost contacts)
  - Comm interception
  - Sensor ghosting (identity disguise)
  - Frequency lock
  - AI integration (ghost targeting, ghost class behaviour, freq lock debuff)
  - Station AI integration (freq lock blocks reinforcements)
  - Sensor contact injection
  - Serialisation round-trip
  - Build state includes corvette ECM fields
"""
from __future__ import annotations

import pytest
from unittest.mock import patch

import server.game_loop_ew as glew
from server.game_loop_ew import (
    FREQ_LOCK_ENGAGE_TIME,
    FREQ_LOCK_RANGE,
    GHOST_CLASS_OPTIONS,
    GHOST_LIFETIME,
    GHOST_MAX_COUNT,
    INTERCEPT_CHANCE,
    INTERCEPT_SCAN_INTERVAL,
)
from server.models.ship import Ship
from server.models.world import Enemy, Station, World, ENEMY_TYPE_PARAMS, spawn_enemy
from server.systems.ai import BeamHitEvent, tick_enemies
from server.systems.station_ai import tick_station_ai
from server.systems.sensors import build_sensor_contacts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DT = 0.1  # 10 Hz tick


def _make_ship(**overrides) -> Ship:
    ship = Ship()
    for k, v in overrides.items():
        setattr(ship, k, v)
    return ship


def _make_world(ship: Ship | None = None) -> World:
    w = World()
    if ship is not None:
        w.ship = ship
    return w


def _tick_n(world: World, ship: Ship, n: int) -> None:
    for _ in range(n):
        glew.tick(world, ship, DT)


# ---------------------------------------------------------------------------
# §2.2.0 — Capability gating
# ---------------------------------------------------------------------------


class TestCorvetteCapability:
    def test_corvette_is_ecm_capable(self):
        glew.reset("corvette")
        assert glew.is_corvette_ecm() is True

    def test_non_corvette_not_capable(self):
        for cls in ("scout", "frigate", "cruiser", "battleship", "carrier", "medical_ship"):
            glew.reset(cls)
            assert glew.is_corvette_ecm() is False, f"{cls} should not have corvette ECM"

    def test_default_reset_not_capable(self):
        glew.reset()
        assert glew.is_corvette_ecm() is False

    def test_deploy_ghost_rejected_non_corvette(self):
        glew.reset("frigate")
        result = glew.deploy_ghost(100.0, 200.0, "cruiser")
        assert result["ok"] is False
        assert result["reason"] == "not_capable"

    def test_set_ghost_class_rejected_non_corvette(self):
        glew.reset("scout")
        result = glew.set_ghost_class("battleship")
        assert result["ok"] is False

    def test_set_freq_lock_rejected_non_corvette(self):
        glew.reset("frigate")
        result = glew.set_freq_lock_target("enemy_1")
        assert result["ok"] is False

    def test_build_state_includes_ecm_flag(self):
        glew.reset("corvette")
        ship = _make_ship()
        world = _make_world(ship)
        state = glew.build_state(world, ship)
        assert state["corvette_ecm"] is True

    def test_build_state_non_corvette(self):
        glew.reset("frigate")
        ship = _make_ship()
        world = _make_world(ship)
        state = glew.build_state(world, ship)
        assert state["corvette_ecm"] is False


# ---------------------------------------------------------------------------
# §2.2.2 — Signal Spoofing (ghost contacts)
# ---------------------------------------------------------------------------


class TestSignalSpoofing:
    def test_deploy_creates_ghost(self):
        glew.reset("corvette")
        result = glew.deploy_ghost(1000.0, 2000.0, "cruiser")
        assert result["ok"] is True
        assert result["id"].startswith("ghost_")
        assert len(glew.get_ghosts()) == 1

    def test_max_ghosts_enforced(self):
        glew.reset("corvette")
        for i in range(GHOST_MAX_COUNT):
            r = glew.deploy_ghost(float(i * 100), 0.0, "cruiser")
            assert r["ok"] is True
        result = glew.deploy_ghost(999.0, 999.0, "cruiser")
        assert result["ok"] is False
        assert result["reason"] == "max_ghosts"

    def test_invalid_class_rejected(self):
        glew.reset("corvette")
        result = glew.deploy_ghost(0.0, 0.0, "invalid_class")
        assert result["ok"] is False
        assert result["reason"] == "invalid_class"

    def test_recall_by_id(self):
        glew.reset("corvette")
        r = glew.deploy_ghost(100.0, 200.0, "scout")
        gid = r["id"]
        result = glew.recall_ghost(gid)
        assert result["ok"] is True
        assert len(glew.get_ghosts()) == 0

    def test_recall_not_found(self):
        glew.reset("corvette")
        result = glew.recall_ghost("ghost_999")
        assert result["ok"] is False
        assert result["reason"] == "not_found"

    def test_recall_all(self):
        glew.reset("corvette")
        glew.deploy_ghost(0.0, 0.0, "cruiser")
        glew.deploy_ghost(100.0, 0.0, "scout")
        glew.recall_all_ghosts()
        assert len(glew.get_ghosts()) == 0

    def test_ghosts_expire_after_lifetime(self):
        glew.reset("corvette")
        ship = _make_ship()
        world = _make_world(ship)
        glew.deploy_ghost(100.0, 200.0, "cruiser")
        assert len(glew.get_ghosts()) == 1
        # Tick through full lifetime
        ticks_needed = int(GHOST_LIFETIME / DT) + 1
        _tick_n(world, ship, ticks_needed)
        assert len(glew.get_ghosts()) == 0

    def test_ghosts_in_build_state(self):
        glew.reset("corvette")
        ship = _make_ship()
        world = _make_world(ship)
        glew.deploy_ghost(500.0, 600.0, "destroyer")
        state = glew.build_state(world, ship)
        assert len(state["ghosts"]) == 1
        assert state["ghosts"][0]["mimic_class"] == "destroyer"

    def test_ghost_contacts_format(self):
        glew.reset("corvette")
        glew.deploy_ghost(100.0, 200.0, "cruiser")
        contacts = glew.get_ghost_contacts()
        assert len(contacts) == 1
        c = contacts[0]
        assert c["kind"] == "enemy"
        assert c["classification"] == "unknown"
        assert c["scan_state"] == "unknown"
        assert c["type"] == "cruiser"
        assert c["x"] == 100.0
        assert c["y"] == 200.0

    def test_ghosts_cleared_on_reset(self):
        glew.reset("corvette")
        glew.deploy_ghost(0.0, 0.0, "cruiser")
        glew.reset("corvette")
        assert len(glew.get_ghosts()) == 0


# ---------------------------------------------------------------------------
# §2.2.3 — Comm Interception
# ---------------------------------------------------------------------------


class TestCommInterception:
    def test_timer_counts_down(self):
        glew.reset("corvette")
        ship = _make_ship()
        world = _make_world(ship)
        # Tick a few times — timer should decrease
        _tick_n(world, ship, 10)
        state = glew.build_state(world, ship)
        assert state["intercept_timer"] < INTERCEPT_SCAN_INTERVAL

    def test_generates_signal_on_timer(self):
        glew.reset("corvette")
        ship = _make_ship()
        world = _make_world(ship)
        # Place an enemy within sensor range
        enemy = spawn_enemy("scout", ship.x + 1000, ship.y, "enemy_1")
        world.enemies.append(enemy)
        # Force intercept chance to 1.0
        with patch("server.game_loop_ew._rng") as mock_rng:
            mock_rng.random.return_value = 0.0  # < INTERCEPT_CHANCE
            ticks = int(INTERCEPT_SCAN_INTERVAL / DT) + 1
            _tick_n(world, ship, ticks)
        signals = glew.pop_intercepted_signals()
        assert len(signals) >= 1
        assert signals[0]["signal_type"] == "encrypted"

    def test_requires_enemy_in_range(self):
        glew.reset("corvette")
        ship = _make_ship()
        world = _make_world(ship)
        # No enemies → no interceptions
        with patch("server.game_loop_ew._rng") as mock_rng:
            mock_rng.random.return_value = 0.0
            ticks = int(INTERCEPT_SCAN_INTERVAL / DT) + 1
            _tick_n(world, ship, ticks)
        signals = glew.pop_intercepted_signals()
        assert len(signals) == 0

    def test_pop_drains_list(self):
        glew.reset("corvette")
        ship = _make_ship()
        world = _make_world(ship)
        enemy = spawn_enemy("scout", ship.x + 1000, ship.y, "enemy_1")
        world.enemies.append(enemy)
        with patch("server.game_loop_ew._rng") as mock_rng:
            mock_rng.random.return_value = 0.0
            ticks = int(INTERCEPT_SCAN_INTERVAL / DT) + 1
            _tick_n(world, ship, ticks)
        first = glew.pop_intercepted_signals()
        assert len(first) >= 1
        second = glew.pop_intercepted_signals()
        assert len(second) == 0

    def test_not_active_for_non_corvette(self):
        glew.reset("frigate")
        ship = _make_ship()
        world = _make_world(ship)
        enemy = spawn_enemy("scout", ship.x + 1000, ship.y, "enemy_1")
        world.enemies.append(enemy)
        with patch("server.game_loop_ew._rng") as mock_rng:
            mock_rng.random.return_value = 0.0
            ticks = int(INTERCEPT_SCAN_INTERVAL / DT) + 2
            _tick_n(world, ship, ticks)
        signals = glew.pop_intercepted_signals()
        assert len(signals) == 0

    def test_ecm_offline_no_intercept(self):
        glew.reset("corvette")
        ship = _make_ship()
        # ECM suite offline (0 power)
        ship.systems["ecm_suite"].power = 0
        world = _make_world(ship)
        enemy = spawn_enemy("scout", ship.x + 1000, ship.y, "enemy_1")
        world.enemies.append(enemy)
        with patch("server.game_loop_ew._rng") as mock_rng:
            mock_rng.random.return_value = 0.0
            ticks = int(INTERCEPT_SCAN_INTERVAL / DT) + 2
            _tick_n(world, ship, ticks)
        signals = glew.pop_intercepted_signals()
        assert len(signals) == 0

    def test_timer_resets(self):
        glew.reset("corvette")
        ship = _make_ship()
        world = _make_world(ship)
        # Tick past the first timer cycle
        ticks = int(INTERCEPT_SCAN_INTERVAL / DT) + 1
        _tick_n(world, ship, ticks)
        state = glew.build_state(world, ship)
        # Timer should have reset to roughly INTERCEPT_SCAN_INTERVAL
        assert state["intercept_timer"] > 0.0


# ---------------------------------------------------------------------------
# §2.2.4 — Sensor Ghosting
# ---------------------------------------------------------------------------


class TestSensorGhosting:
    def test_set_stores_value(self):
        glew.reset("corvette")
        result = glew.set_ghost_class("battleship")
        assert result["ok"] is True
        assert glew.get_ghost_class() == "battleship"

    def test_none_clears(self):
        glew.reset("corvette")
        glew.set_ghost_class("cruiser")
        result = glew.set_ghost_class(None)
        assert result["ok"] is True
        assert glew.get_ghost_class() is None

    def test_invalid_class_rejected(self):
        glew.reset("corvette")
        result = glew.set_ghost_class("starbase")
        assert result["ok"] is False
        assert result["reason"] == "invalid_class"

    def test_in_build_state(self):
        glew.reset("corvette")
        ship = _make_ship()
        world = _make_world(ship)
        glew.set_ghost_class("freighter")
        state = glew.build_state(world, ship)
        assert state["ghost_class"] == "freighter"

    def test_enemy_flees_from_battleship_ghost(self):
        """Ghost class 'battleship' causes idle enemies to flee on detection."""
        glew.reset("corvette")
        ship = _make_ship(x=0.0, y=0.0)
        # Place enemy in idle state within detect range
        enemy = spawn_enemy("scout", 5000.0, 0.0, "enemy_1")
        enemy.ai_state = "idle"
        tick_enemies([enemy], ship, DT, ghost_class="battleship")
        assert enemy.ai_state == "flee"

    def test_enemy_flees_from_destroyer_ghost(self):
        glew.reset("corvette")
        ship = _make_ship(x=0.0, y=0.0)
        enemy = spawn_enemy("scout", 5000.0, 0.0, "enemy_1")
        enemy.ai_state = "idle"
        tick_enemies([enemy], ship, DT, ghost_class="destroyer")
        assert enemy.ai_state == "flee"

    def test_freighter_ghost_increases_detect_threshold(self):
        """Ghost class 'freighter' makes enemies detect at 1.5× range — effectively
        they are *less* alert (higher threshold = farther detection, meaning the
        enemy transitions to chase later since the player appears civilian)."""
        glew.reset("corvette")
        ship = _make_ship(x=0.0, y=0.0)
        params = ENEMY_TYPE_PARAMS["scout"]
        base_detect = params["detect_range"]
        # Place enemy just beyond normal detect range but within 1.5×
        far_dist = base_detect * 1.3
        enemy = spawn_enemy("scout", far_dist, 0.0, "enemy_1")
        enemy.ai_state = "idle"
        # Without ghost class: shouldn't detect
        tick_enemies([enemy], ship, DT, ghost_class=None)
        assert enemy.ai_state == "idle"
        # With freighter ghost class: detect range is 1.5× so now detects
        enemy.ai_state = "idle"
        tick_enemies([enemy], ship, DT, ghost_class="freighter")
        assert enemy.ai_state == "chase"

    def test_serialise_round_trip(self):
        glew.reset("corvette")
        glew.set_ghost_class("transport")
        data = glew.serialise()
        glew.reset()
        glew.deserialise(data)
        assert glew.get_ghost_class() == "transport"


# ---------------------------------------------------------------------------
# §2.2.5 — Frequency Lock
# ---------------------------------------------------------------------------


class TestFrequencyLock:
    def test_set_stores_target(self):
        glew.reset("corvette")
        result = glew.set_freq_lock_target("enemy_1")
        assert result["ok"] is True
        assert result["state"] == "engaging"

    def test_progress_increases(self):
        glew.reset("corvette")
        ship = _make_ship(x=0.0, y=0.0)
        world = _make_world(ship)
        enemy = spawn_enemy("scout", 5000.0, 0.0, "enemy_1")
        world.enemies.append(enemy)
        glew.set_freq_lock_target("enemy_1")
        _tick_n(world, ship, 10)
        state = glew.build_state(world, ship)
        assert state["freq_lock_progress"] > 0.0

    def test_activates_at_full(self):
        glew.reset("corvette")
        ship = _make_ship(x=0.0, y=0.0)
        world = _make_world(ship)
        enemy = spawn_enemy("scout", 5000.0, 0.0, "enemy_1")
        world.enemies.append(enemy)
        glew.set_freq_lock_target("enemy_1")
        ticks = int(FREQ_LOCK_ENGAGE_TIME / DT) + 1
        _tick_n(world, ship, ticks)
        assert glew.is_freq_lock_active() is True
        assert glew.is_freq_locked("enemy_1") is True

    def test_cancels_when_target_gone(self):
        glew.reset("corvette")
        ship = _make_ship(x=0.0, y=0.0)
        world = _make_world(ship)
        enemy = spawn_enemy("scout", 5000.0, 0.0, "enemy_1")
        world.enemies.append(enemy)
        glew.set_freq_lock_target("enemy_1")
        _tick_n(world, ship, 10)
        # Remove enemy
        world.enemies.clear()
        _tick_n(world, ship, 1)
        assert glew.is_freq_lock_active() is False
        state = glew.build_state(world, ship)
        assert state["freq_lock_target_id"] is None

    def test_decays_out_of_range(self):
        glew.reset("corvette")
        ship = _make_ship(x=0.0, y=0.0)
        world = _make_world(ship)
        # Place enemy well beyond lock range
        far = FREQ_LOCK_RANGE * 3
        enemy = spawn_enemy("scout", far, 0.0, "enemy_1")
        world.enemies.append(enemy)
        glew.set_freq_lock_target("enemy_1")
        _tick_n(world, ship, 20)
        state = glew.build_state(world, ship)
        # Should still be at 0 progress (decaying)
        assert state["freq_lock_progress"] == 0.0
        assert glew.is_freq_lock_active() is False

    def test_cancel_resets_progress(self):
        glew.reset("corvette")
        ship = _make_ship(x=0.0, y=0.0)
        world = _make_world(ship)
        enemy = spawn_enemy("scout", 5000.0, 0.0, "enemy_1")
        world.enemies.append(enemy)
        glew.set_freq_lock_target("enemy_1")
        _tick_n(world, ship, 10)
        result = glew.set_freq_lock_target(None)
        assert result["state"] == "cancelled"
        assert glew.is_freq_lock_active() is False

    def test_only_one_target(self):
        glew.reset("corvette")
        glew.set_freq_lock_target("enemy_1")
        glew.set_freq_lock_target("enemy_2")
        ids = glew.get_freq_locked_ids()
        # Not locked yet (just engaging) but target changed
        assert "enemy_1" not in ids

    def test_freq_locked_ids(self):
        glew.reset("corvette")
        ship = _make_ship(x=0.0, y=0.0)
        world = _make_world(ship)
        enemy = spawn_enemy("scout", 5000.0, 0.0, "enemy_1")
        world.enemies.append(enemy)
        glew.set_freq_lock_target("enemy_1")
        ticks = int(FREQ_LOCK_ENGAGE_TIME / DT) + 1
        _tick_n(world, ship, ticks)
        ids = glew.get_freq_locked_ids()
        assert "enemy_1" in ids

    def test_serialise_round_trip(self):
        glew.reset("corvette")
        ship = _make_ship(x=0.0, y=0.0)
        world = _make_world(ship)
        enemy = spawn_enemy("scout", 5000.0, 0.0, "enemy_1")
        world.enemies.append(enemy)
        glew.set_freq_lock_target("enemy_1")
        ticks = int(FREQ_LOCK_ENGAGE_TIME / DT) + 1
        _tick_n(world, ship, ticks)
        data = glew.serialise()
        glew.reset()
        glew.deserialise(data)
        assert glew.is_freq_lock_active() is True
        assert glew.is_freq_locked("enemy_1") is True

    def test_blocks_station_reinforcements(self):
        """Frequency-locked station cannot send distress calls."""
        from server.models.world import (
            Station as _St,
            EnemyStationDefenses,
            SensorArray,
            StationReactor,
        )

        glew.reset("corvette")
        sa = SensorArray(id="station_1_sensor", hp=100.0, hp_max=100.0)
        reactor = StationReactor(id="station_1_reactor", hp=100.0, hp_max=100.0)
        defenses = EnemyStationDefenses(
            shield_arcs=[], turrets=[], launchers=[], fighter_bays=[],
            sensor_array=sa, reactor=reactor,
        )
        station = _St(id="station_1", x=1000.0, y=0.0, hull=500.0, hull_max=500.0,
                       station_type="outpost", faction="hostile")
        station.defenses = defenses

        ship = _make_ship(x=0.0, y=0.0)
        world = _make_world(ship)
        world.stations.append(station)

        # Without freq lock — reinforcement should fire
        _, _, calls_no_lock = tick_station_ai(
            [station], ship, world, DT, {"station_1"},
        )
        assert len(calls_no_lock) == 1
        # Reset distress_sent
        sa.distress_sent = False

        # With freq lock — reinforcement blocked
        _, _, calls_locked = tick_station_ai(
            [station], ship, world, DT, {"station_1"},
            freq_locked_ids={"station_1"},
        )
        assert len(calls_locked) == 0


# ---------------------------------------------------------------------------
# AI Integration — Ghost targeting
# ---------------------------------------------------------------------------


class TestGhostTargeting:
    def test_enemy_targets_nearest_ghost(self):
        """When ghost is closer than player, enemy targets the ghost."""
        ship = _make_ship(x=0.0, y=0.0)
        # Enemy at x=5000, ghost at x=4000 (closer to enemy than player)
        enemy = spawn_enemy("scout", 5000.0, 0.0, "enemy_1")
        enemy.ai_state = "attack"
        enemy.beam_cooldown = 0.0
        ghosts = [{"id": "ghost_1", "x": 4000.0, "y": 0.0, "mimic_class": "cruiser"}]
        events = tick_enemies([enemy], ship, DT, ghosts=ghosts)
        # If enemy fired, it should target the ghost (id != "player")
        for ev in events:
            assert ev.target == "ghost_1"

    def test_beam_at_ghost_no_player_damage(self):
        """Beam hits targeting ghosts have target != 'player'."""
        ship = _make_ship(x=50000.0, y=0.0)  # player far away
        enemy = spawn_enemy("scout", 5000.0, 0.0, "enemy_1")
        enemy.ai_state = "attack"
        enemy.beam_cooldown = 0.0
        ghosts = [{"id": "ghost_1", "x": 5100.0, "y": 0.0, "mimic_class": "cruiser"}]
        events = tick_enemies([enemy], ship, DT, ghosts=ghosts)
        for ev in events:
            assert ev.target != "player"


# ---------------------------------------------------------------------------
# AI Integration — Frequency lock accuracy debuff
# ---------------------------------------------------------------------------


class TestFreqLockAccuracy:
    def test_freq_lock_reduces_accuracy(self):
        """Frequency-locked enemies have a 15% accuracy penalty."""
        ship = _make_ship(x=0.0, y=0.0)
        hits_normal = 0
        hits_locked = 0
        trials = 2000

        for _ in range(trials):
            enemy = spawn_enemy("scout", 3000.0, 0.0, "enemy_1")
            enemy.ai_state = "attack"
            enemy.beam_cooldown = 0.0
            enemy.heading = 180.0  # facing player
            events = tick_enemies([enemy], ship, DT)
            hits_normal += len(events)

        for _ in range(trials):
            enemy = spawn_enemy("scout", 3000.0, 0.0, "enemy_1")
            enemy.ai_state = "attack"
            enemy.beam_cooldown = 0.0
            enemy.heading = 180.0
            events = tick_enemies([enemy], ship, DT, freq_lock_target_ids={"enemy_1"})
            hits_locked += len(events)

        # Locked should have fewer hits (15% penalty)
        if hits_normal > 0:
            ratio = hits_locked / hits_normal
            assert ratio < 1.0, f"Expected fewer hits when locked, ratio={ratio}"


# ---------------------------------------------------------------------------
# Sensor contact injection
# ---------------------------------------------------------------------------


class TestGhostSensorContacts:
    def test_ghost_contacts_injected(self):
        world = _make_world()
        ship = _make_ship()
        ghost_contacts = [
            {"id": "ghost_1", "x": 100.0, "y": 200.0, "heading": 0.0,
             "kind": "enemy", "classification": "unknown", "scan_state": "unknown",
             "type": "cruiser"},
        ]
        contacts = build_sensor_contacts(world, ship, ghost_contacts=ghost_contacts)
        ghost_ids = [c["id"] for c in contacts if c["id"].startswith("ghost_")]
        assert "ghost_1" in ghost_ids

    def test_ghost_contacts_none_safe(self):
        world = _make_world()
        ship = _make_ship()
        contacts = build_sensor_contacts(world, ship, ghost_contacts=None)
        ghost_ids = [c["id"] for c in contacts if c["id"].startswith("ghost_")]
        assert len(ghost_ids) == 0


# ---------------------------------------------------------------------------
# Serialisation round-trip
# ---------------------------------------------------------------------------


class TestCorvetteECMSerialise:
    def test_full_round_trip(self):
        glew.reset("corvette")
        ship = _make_ship(x=0.0, y=0.0)
        world = _make_world(ship)
        enemy = spawn_enemy("scout", 5000.0, 0.0, "enemy_1")
        world.enemies.append(enemy)
        glew.deploy_ghost(100.0, 200.0, "cruiser")
        glew.set_ghost_class("freighter")
        glew.set_freq_lock_target("enemy_1")
        _tick_n(world, ship, 10)
        data = glew.serialise()
        # Reset and restore
        glew.reset()
        glew.deserialise(data)
        assert glew.is_corvette_ecm() is True
        assert len(glew.get_ghosts()) == 1
        assert glew.get_ghost_class() == "freighter"

    def test_defaults_for_missing_keys(self):
        glew.reset("corvette")
        glew.deserialise({})
        assert glew.is_corvette_ecm() is False
        assert len(glew.get_ghosts()) == 0
        assert glew.get_ghost_class() is None

    def test_ghosts_restored(self):
        glew.reset("corvette")
        glew.deploy_ghost(100.0, 200.0, "scout")
        glew.deploy_ghost(300.0, 400.0, "destroyer")
        data = glew.serialise()
        glew.reset()
        glew.deserialise(data)
        ghosts = glew.get_ghosts()
        assert len(ghosts) == 2
        classes = {g["mimic_class"] for g in ghosts}
        assert "scout" in classes
        assert "destroyer" in classes
