"""Tests for server/missions/engine.py and server/missions/loader.py.

Covers:
  - All trigger types (player_in_area, scan_completed, entity_destroyed,
    all_enemies_destroyed, player_hull_zero)
  - Sequential objective evaluation
  - Victory / defeat detection
  - Mission loader (first_contact, sandbox, missing)
"""
from __future__ import annotations

import pytest

from server.missions.engine import MissionEngine, Objective
from server.missions.loader import load_mission, spawn_from_mission, spawn_wave
from server.models.ship import Ship
from server.models.world import Enemy, Station, World, spawn_enemy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_world(enemies: list[Enemy] | None = None, stations: list[Station] | None = None) -> World:
    w = World()
    w.enemies = enemies or []
    w.stations = stations or []
    return w


def _make_ship(x: float = 50_000, y: float = 50_000, hull: float = 100.0) -> Ship:
    s = Ship()
    s.x = x
    s.y = y
    s.hull = hull
    return s


def _make_enemy(entity_id: str = "enemy_1", scan_state: str = "unknown") -> Enemy:
    e = spawn_enemy("scout", 70_000, 30_000, entity_id)
    e.scan_state = scan_state  # type: ignore[assignment]
    return e


def _single_obj_mission(trigger: str, args: dict | None = None) -> dict:
    """Build a minimal mission with one objective."""
    obj_def: dict = {"id": "obj_1", "text": "Test objective", "trigger": trigger}
    if args:
        obj_def["args"] = args
    return {
        "id": "test",
        "name": "Test",
        "briefing": "",
        "spawn": [],
        "objectives": [obj_def],
        "victory_condition": "all_objectives_complete",
        "defeat_condition": "player_hull_zero",
    }


# ---------------------------------------------------------------------------
# player_in_area trigger
# ---------------------------------------------------------------------------


def test_player_in_area_inside_radius_completes():
    mission = _single_obj_mission("player_in_area", {"x": 50_000, "y": 50_000, "r": 5_000})
    engine = MissionEngine(mission)
    world = _make_world()
    ship = _make_ship(50_000, 50_000)
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_player_in_area_outside_radius_pending():
    mission = _single_obj_mission("player_in_area", {"x": 50_000, "y": 50_000, "r": 5_000})
    engine = MissionEngine(mission)
    world = _make_world()
    ship = _make_ship(60_000, 60_000)  # > 5000 away
    completed = engine.tick(world, ship)
    assert completed == []
    assert engine.get_objectives()[0].status == "pending"


# ---------------------------------------------------------------------------
# scan_completed trigger
# ---------------------------------------------------------------------------


def test_scan_completed_scanned_completes():
    mission = _single_obj_mission("scan_completed", {"entity_id": "enemy_1"})
    engine = MissionEngine(mission)
    enemy = _make_enemy("enemy_1", scan_state="scanned")
    world = _make_world([enemy])
    ship = _make_ship()
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_scan_completed_unscanned_pending():
    mission = _single_obj_mission("scan_completed", {"entity_id": "enemy_1"})
    engine = MissionEngine(mission)
    enemy = _make_enemy("enemy_1", scan_state="unknown")
    world = _make_world([enemy])
    ship = _make_ship()
    completed = engine.tick(world, ship)
    assert completed == []


def test_scan_completed_enemy_absent_pending():
    """If the enemy is gone (destroyed), scan_completed stays pending."""
    mission = _single_obj_mission("scan_completed", {"entity_id": "enemy_1"})
    engine = MissionEngine(mission)
    world = _make_world([])  # enemy_1 not present
    ship = _make_ship()
    completed = engine.tick(world, ship)
    assert completed == []


# ---------------------------------------------------------------------------
# entity_destroyed trigger
# ---------------------------------------------------------------------------


def test_entity_destroyed_absent_completes():
    mission = _single_obj_mission("entity_destroyed", {"entity_id": "enemy_1"})
    engine = MissionEngine(mission)
    world = _make_world([])  # enemy_1 already gone
    ship = _make_ship()
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_entity_destroyed_present_pending():
    mission = _single_obj_mission("entity_destroyed", {"entity_id": "enemy_1"})
    engine = MissionEngine(mission)
    enemy = _make_enemy("enemy_1")
    world = _make_world([enemy])
    ship = _make_ship()
    completed = engine.tick(world, ship)
    assert completed == []


# ---------------------------------------------------------------------------
# all_enemies_destroyed trigger
# ---------------------------------------------------------------------------


def test_all_enemies_destroyed_empty_completes():
    mission = _single_obj_mission("all_enemies_destroyed")
    engine = MissionEngine(mission)
    world = _make_world([])
    ship = _make_ship()
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_all_enemies_destroyed_has_enemies_pending():
    mission = _single_obj_mission("all_enemies_destroyed")
    engine = MissionEngine(mission)
    world = _make_world([_make_enemy("enemy_1")])
    ship = _make_ship()
    completed = engine.tick(world, ship)
    assert completed == []


# ---------------------------------------------------------------------------
# player_hull_zero (defeat)
# ---------------------------------------------------------------------------


def test_player_hull_zero_triggers_defeat():
    mission = _single_obj_mission("all_enemies_destroyed")
    engine = MissionEngine(mission)
    world = _make_world([_make_enemy("e1")])
    ship = _make_ship(hull=0.0)
    engine.tick(world, ship)
    over, result = engine.is_over()
    assert over is True
    assert result == "defeat"


def test_player_hull_below_zero_triggers_defeat():
    mission = _single_obj_mission("all_enemies_destroyed")
    engine = MissionEngine(mission)
    world = _make_world()
    ship = _make_ship(hull=-5.0)
    engine.tick(world, ship)
    over, result = engine.is_over()
    assert over is True
    assert result == "defeat"


# ---------------------------------------------------------------------------
# Sequential objective evaluation
# ---------------------------------------------------------------------------


def test_sequential_later_objectives_not_checked_before_earlier():
    """Second objective must not complete while first is still pending."""
    mission = {
        "id": "seq_test",
        "name": "Sequential",
        "briefing": "",
        "spawn": [],
        "objectives": [
            # First: ship must reach far-away area (won't be triggered)
            {"id": "obj_first", "text": "Go far", "trigger": "player_in_area",
             "args": {"x": 0, "y": 0, "r": 100}},
            # Second: all enemies destroyed (would be true right now)
            {"id": "obj_second", "text": "Destroy all", "trigger": "all_enemies_destroyed"},
        ],
        "victory_condition": "all_objectives_complete",
        "defeat_condition": "player_hull_zero",
    }
    engine = MissionEngine(mission)
    world = _make_world([])  # no enemies — second trigger would fire
    ship = _make_ship(50_000, 50_000)  # not near (0,0)
    completed = engine.tick(world, ship)
    # Neither should complete — first is pending, second not yet checked
    assert completed == []
    objs = engine.get_objectives()
    assert objs[0].status == "pending"
    assert objs[1].status == "pending"


def test_sequential_second_completes_after_first():
    """After first objective clears, second should complete on the next tick."""
    mission = {
        "id": "seq_test",
        "name": "Sequential",
        "briefing": "",
        "spawn": [],
        "objectives": [
            {"id": "obj_first", "text": "Arrive", "trigger": "player_in_area",
             "args": {"x": 50_000, "y": 50_000, "r": 5_000}},
            {"id": "obj_second", "text": "Destroy all", "trigger": "all_enemies_destroyed"},
        ],
        "victory_condition": "all_objectives_complete",
        "defeat_condition": "player_hull_zero",
    }
    engine = MissionEngine(mission)
    world = _make_world([])
    ship = _make_ship(50_000, 50_000)

    # Tick 1: first completes
    completed = engine.tick(world, ship)
    assert "obj_first" in completed

    # Tick 2: second completes
    completed = engine.tick(world, ship)
    assert "obj_second" in completed


# ---------------------------------------------------------------------------
# is_over — normal progress
# ---------------------------------------------------------------------------


def test_is_over_returns_false_while_in_progress():
    mission = _single_obj_mission("player_in_area", {"x": 0, "y": 0, "r": 100})
    engine = MissionEngine(mission)
    over, result = engine.is_over()
    assert over is False
    assert result is None


def test_is_over_returns_victory_after_all_objectives():
    mission = _single_obj_mission("all_enemies_destroyed")
    engine = MissionEngine(mission)
    world = _make_world([])
    ship = _make_ship()
    engine.tick(world, ship)
    over, result = engine.is_over()
    assert over is True
    assert result == "victory"


def test_is_over_returns_defeat_on_hull_zero():
    mission = _single_obj_mission("all_enemies_destroyed")
    engine = MissionEngine(mission)
    world = _make_world([_make_enemy()])
    ship = _make_ship(hull=0.0)
    engine.tick(world, ship)
    over, result = engine.is_over()
    assert over is True
    assert result == "defeat"


def test_tick_no_op_after_game_over():
    """No new completions after the game has ended."""
    mission = _single_obj_mission("all_enemies_destroyed")
    engine = MissionEngine(mission)
    world = _make_world([])
    ship = _make_ship()
    engine.tick(world, ship)  # completes + victory
    completed = engine.tick(world, ship)  # should be empty
    assert completed == []


# ---------------------------------------------------------------------------
# Mission loader
# ---------------------------------------------------------------------------


def test_load_mission_first_contact_parses():
    mission = load_mission("first_contact")
    assert mission["id"] == "first_contact"
    assert len(mission["objectives"]) == 4
    assert len(mission["spawn"]) == 2


def test_load_mission_sandbox_returns_dict():
    mission = load_mission("sandbox")
    assert mission["id"] == "sandbox"
    assert mission["spawn"] == []
    assert mission["objectives"] == []


def test_load_mission_missing_raises():
    with pytest.raises(FileNotFoundError):
        load_mission("nonexistent_mission_xyz")


def test_spawn_from_mission_adds_enemies():
    mission = load_mission("first_contact")
    world = World()
    world.enemies.clear()
    entity_counter = spawn_from_mission(mission, world, 0)
    assert len(world.enemies) == 2
    ids = {e.id for e in world.enemies}
    assert "enemy_1" in ids
    assert "enemy_2" in ids


# ---------------------------------------------------------------------------
# timer_elapsed trigger
# ---------------------------------------------------------------------------


def test_timer_elapsed_fires_after_threshold():
    mission = _single_obj_mission("timer_elapsed", {"seconds": 5.0})
    engine = MissionEngine(mission)
    world = _make_world()
    ship = _make_ship()

    # 5 ticks × dt=1.0 = 5 seconds
    for _ in range(4):
        result = engine.tick(world, ship, dt=1.0)
        assert result == [], "Should not complete before 5s"

    result = engine.tick(world, ship, dt=1.0)
    assert "obj_1" in result


def test_timer_elapsed_not_fire_before_threshold():
    mission = _single_obj_mission("timer_elapsed", {"seconds": 10.0})
    engine = MissionEngine(mission)
    world = _make_world()
    ship = _make_ship()
    result = engine.tick(world, ship, dt=1.0)
    assert result == []


# ---------------------------------------------------------------------------
# wave_defeated trigger
# ---------------------------------------------------------------------------


def test_wave_defeated_no_matching_enemies_completes():
    mission = _single_obj_mission("wave_defeated", {"enemy_prefix": "w1_"})
    engine = MissionEngine(mission)
    # No w1_ enemies
    world = _make_world([_make_enemy("w2_1"), _make_enemy("w2_2")])
    ship = _make_ship()
    result = engine.tick(world, ship)
    assert "obj_1" in result


def test_wave_defeated_matching_enemies_pending():
    mission = _single_obj_mission("wave_defeated", {"enemy_prefix": "w1_"})
    engine = MissionEngine(mission)
    world = _make_world([_make_enemy("w1_1"), _make_enemy("w1_2")])
    ship = _make_ship()
    result = engine.tick(world, ship)
    assert result == []


def test_wave_defeated_partial_wave_pending():
    """Only one w1_ enemy remaining → wave not yet defeated."""
    mission = _single_obj_mission("wave_defeated", {"enemy_prefix": "w1_"})
    engine = MissionEngine(mission)
    world = _make_world([_make_enemy("w1_1")])
    ship = _make_ship()
    result = engine.tick(world, ship)
    assert result == []


# ---------------------------------------------------------------------------
# station_hull_below trigger
# ---------------------------------------------------------------------------


def test_station_hull_below_threshold_completes():
    mission = _single_obj_mission(
        "station_hull_below", {"station_id": "kepler", "threshold": 0}
    )
    engine = MissionEngine(mission)
    station = Station(id="kepler", x=50_000, y=35_000, hull=0.0)
    world = _make_world(stations=[station])
    ship = _make_ship()
    result = engine.tick(world, ship)
    assert "obj_1" in result


def test_station_hull_above_threshold_pending():
    mission = _single_obj_mission(
        "station_hull_below", {"station_id": "kepler", "threshold": 0}
    )
    engine = MissionEngine(mission)
    station = Station(id="kepler", x=50_000, y=35_000, hull=50.0)
    world = _make_world(stations=[station])
    ship = _make_ship()
    result = engine.tick(world, ship)
    assert result == []


def test_station_hull_below_missing_station_pending():
    """If the station isn't in the world, trigger returns False (not pending)."""
    mission = _single_obj_mission(
        "station_hull_below", {"station_id": "kepler", "threshold": 0}
    )
    engine = MissionEngine(mission)
    world = _make_world()  # no stations
    ship = _make_ship()
    result = engine.tick(world, ship)
    assert result == []


# ---------------------------------------------------------------------------
# defeat_condition_alt (station destroyed = mission defeat)
# ---------------------------------------------------------------------------


def test_defeat_condition_alt_station_destroyed():
    """Mission ends in defeat when station hull hits 0 (defeat_condition_alt)."""
    mission = {
        "id": "test",
        "name": "Test",
        "briefing": "",
        "spawn": [],
        "objectives": [
            {"id": "obj_1", "text": "Destroy all enemies", "trigger": "all_enemies_destroyed"},
        ],
        "victory_condition": "all_objectives_complete",
        "defeat_condition": "player_hull_zero",
        "defeat_condition_alt": {
            "trigger": "station_hull_below",
            "args": {"station_id": "kepler", "threshold": 0},
        },
    }
    engine = MissionEngine(mission)
    station = Station(id="kepler", x=50_000, y=35_000, hull=0.0)
    world = _make_world([_make_enemy("e1")], stations=[station])
    ship = _make_ship()

    engine.tick(world, ship)
    over, result = engine.is_over()
    assert over is True
    assert result == "defeat"


# ---------------------------------------------------------------------------
# on_complete / pop_pending_actions
# ---------------------------------------------------------------------------


def test_on_complete_action_queued_on_objective_complete():
    """Completing an objective with on_complete queues the action."""
    mission = {
        "id": "test",
        "name": "Test",
        "briefing": "",
        "spawn": [],
        "objectives": [
            {
                "id": "obj_1",
                "text": "Wave 1",
                "trigger": "all_enemies_destroyed",
                "on_complete": {"action": "spawn_wave", "enemies": [
                    {"type": "scout", "x": 10000, "y": 10000, "id": "w2_1"},
                ]},
            },
        ],
        "victory_condition": "all_objectives_complete",
        "defeat_condition": "player_hull_zero",
    }
    engine = MissionEngine(mission)
    world = _make_world([])  # no enemies — triggers immediately
    ship = _make_ship()

    completed = engine.tick(world, ship)
    assert "obj_1" in completed

    actions = engine.pop_pending_actions()
    assert len(actions) == 1
    assert actions[0]["action"] == "spawn_wave"
    assert len(actions[0]["enemies"]) == 1

    # Second pop returns empty
    assert engine.pop_pending_actions() == []


# ---------------------------------------------------------------------------
# Mission loader — defend_station
# ---------------------------------------------------------------------------


def test_load_mission_defend_station_parses():
    mission = load_mission("defend_station")
    assert mission["id"] == "defend_station"
    assert len(mission["objectives"]) == 3
    assert mission["objectives"][0]["trigger"] == "wave_defeated"


def test_spawn_from_mission_defend_station_creates_station_and_enemies():
    mission = load_mission("defend_station")
    world = World()
    spawn_from_mission(mission, world, 0)
    # Station in spawn
    assert len(world.stations) == 1
    assert world.stations[0].id == "kepler"
    # Initial wave in spawn_initial_wave
    assert len(world.enemies) == 3
    ids = {e.id for e in world.enemies}
    assert "w1_1" in ids and "w1_2" in ids and "w1_3" in ids


def test_spawn_wave_adds_enemies():
    world = World()
    wave = [
        {"type": "cruiser", "x": 20000, "y": 50000, "id": "w2_1"},
        {"type": "cruiser", "x": 80000, "y": 50000, "id": "w2_2"},
    ]
    spawn_wave(wave, world)
    assert len(world.enemies) == 2
    assert {e.id for e in world.enemies} == {"w2_1", "w2_2"}


# ---------------------------------------------------------------------------
# signal_located trigger + record_signal_scan
# ---------------------------------------------------------------------------


def test_signal_located_requires_two_scans():
    mission = _single_obj_mission("signal_located")
    engine = MissionEngine(mission)
    world = _make_world()
    ship = _make_ship()

    # First scan — not yet complete
    result = engine.tick(world, ship)
    assert result == []


def test_signal_located_completes_after_two_distinct_scans():
    mission = _single_obj_mission("signal_located")
    engine = MissionEngine(mission)
    world = _make_world()

    # Scan from position 1
    engine.record_signal_scan(50_000, 50_000)
    # Scan from position 2 (>8000 units away)
    engine.record_signal_scan(60_000, 60_000)

    ship = _make_ship()
    result = engine.tick(world, ship)
    assert "obj_1" in result


def test_record_signal_scan_rejects_duplicate_position():
    """Second scan too close to first should not count."""
    mission = _single_obj_mission("signal_located")
    engine = MissionEngine(mission)

    engine.record_signal_scan(50_000, 50_000)
    # Same position — should not advance count
    engine.record_signal_scan(50_000, 50_000)

    assert engine._triangulation_count == 1


def test_record_signal_scan_rejects_nearby_position():
    """Second scan within 8000 units of first is rejected."""
    mission = _single_obj_mission("signal_located")
    engine = MissionEngine(mission)

    engine.record_signal_scan(50_000, 50_000)
    # Only 1000 units away
    engine.record_signal_scan(51_000, 50_000)

    assert engine._triangulation_count == 1


def test_record_signal_scan_accepts_distant_position():
    """Second scan ≥ 8000 units away is accepted."""
    mission = _single_obj_mission("signal_located")
    engine = MissionEngine(mission)

    complete = engine.record_signal_scan(50_000, 50_000)
    assert complete is False

    complete = engine.record_signal_scan(58_001, 50_000)
    assert complete is True
    assert engine._triangulation_count == 2


def test_record_signal_scan_returns_true_when_complete():
    mission = _single_obj_mission("signal_located")
    engine = MissionEngine(mission)

    result = engine.record_signal_scan(50_000, 50_000)
    assert result is False

    result = engine.record_signal_scan(60_000, 60_000)
    assert result is True


# ---------------------------------------------------------------------------
# proximity_with_shields trigger
# ---------------------------------------------------------------------------


def test_proximity_with_shields_completes_after_duration():
    """Ship in range with sufficient shields for required duration completes."""
    mission = _single_obj_mission(
        "proximity_with_shields",
        {"x": 72_000, "y": 68_000, "radius": 2_000, "min_shield": 80, "duration": 10},
    )
    engine = MissionEngine(mission)
    # Ship inside radius
    ship = _make_ship(x=72_000, y=68_000)
    ship.shields.front = 90.0
    ship.shields.rear = 90.0
    world = _make_world()

    # 9 ticks of dt=1.0 — not yet done
    for _ in range(9):
        result = engine.tick(world, ship, dt=1.0)
        assert result == []

    # 10th tick pushes timer to 10s
    result = engine.tick(world, ship, dt=1.0)
    assert "obj_1" in result


def test_proximity_with_shields_resets_timer_when_leaving_range():
    """Moving out of range resets the proximity timer."""
    mission = _single_obj_mission(
        "proximity_with_shields",
        {"x": 72_000, "y": 68_000, "radius": 2_000, "min_shield": 80, "duration": 5},
    )
    engine = MissionEngine(mission)
    world = _make_world()

    # 3 ticks inside range
    ship_in = _make_ship(x=72_000, y=68_000)
    ship_in.shields.front = 90.0
    ship_in.shields.rear = 90.0
    for _ in range(3):
        engine.tick(world, ship_in, dt=1.0)

    # 1 tick outside range — timer resets
    ship_out = _make_ship(x=80_000, y=80_000)
    ship_out.shields.front = 90.0
    ship_out.shields.rear = 90.0
    engine.tick(world, ship_out, dt=1.0)

    # 4 more ticks inside — total valid = 4, not yet 5
    for _ in range(4):
        result = engine.tick(world, ship_in, dt=1.0)
        if _ < 3:
            assert result == []

    # 5th tick after reset completes it
    result = engine.tick(world, ship_in, dt=1.0)
    assert "obj_1" in result


def test_proximity_with_shields_fails_if_shields_too_low():
    """Low shields prevent proximity timer from advancing."""
    mission = _single_obj_mission(
        "proximity_with_shields",
        {"x": 72_000, "y": 68_000, "radius": 2_000, "min_shield": 80, "duration": 2},
    )
    engine = MissionEngine(mission)
    ship = _make_ship(x=72_000, y=68_000)
    ship.shields.front = 50.0  # below min_shield
    ship.shields.rear = 50.0
    world = _make_world()

    for _ in range(5):
        result = engine.tick(world, ship, dt=1.0)
        assert result == []


def test_proximity_timer_resets_on_low_shield():
    """Timer resets when shields drop below minimum while in range."""
    mission = _single_obj_mission(
        "proximity_with_shields",
        {"x": 72_000, "y": 68_000, "radius": 2_000, "min_shield": 80, "duration": 5},
    )
    engine = MissionEngine(mission)
    world = _make_world()

    # 3 ticks with good shields
    ship = _make_ship(x=72_000, y=68_000)
    ship.shields.front = 90.0
    ship.shields.rear = 90.0
    for _ in range(3):
        engine.tick(world, ship, dt=1.0)

    # Shields drop — timer resets to 0
    ship.shields.front = 30.0
    engine.tick(world, ship, dt=1.0)
    assert engine._proximity_timer == 0.0


# ---------------------------------------------------------------------------
# Mission loader — search_rescue
# ---------------------------------------------------------------------------


def test_load_mission_search_rescue_parses():
    mission = load_mission("search_rescue")
    assert mission["id"] == "search_rescue"
    assert len(mission["objectives"]) == 4
    assert mission["objectives"][0]["trigger"] == "signal_located"
    assert mission["objectives"][2]["trigger"] == "proximity_with_shields"


def test_spawn_from_mission_search_rescue_creates_stations_and_asteroids():
    from server.models.world import Asteroid
    mission = load_mission("search_rescue")
    world = World()
    spawn_from_mission(mission, world, 0)
    # Two stations: base + rescue_target
    assert len(world.stations) == 2
    station_ids = {s.id for s in world.stations}
    assert "base" in station_ids
    assert "rescue_target" in station_ids
    # 6 asteroids in the field
    assert len(world.asteroids) == 6
    # No enemy spawns in search_rescue
    assert len(world.enemies) == 0
