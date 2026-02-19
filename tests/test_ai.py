"""Tests for the enemy AI state machine.

Covers:
  State transitions: idle→chase, chase→attack, attack→flee
  Movement: chase steers toward player, flee steers away
  Enemy-type behaviours: cruiser presses in, destroyer standoff, scout strafe
  Beam fire: fires in arc + range when cooldown=0, blocked when OOA or cooldown>0
  Cooldown decrement each tick
  Despawn condition (flee + dist > 2× detect_range)
"""
from __future__ import annotations

import math

import pytest

from server.models.ship import Ship
from server.models.world import Enemy, ENEMY_TYPE_PARAMS, Station, spawn_enemy, World
from server.systems.ai import tick_enemies, BeamHitEvent, beam_in_arc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ship(x: float = 0.0, y: float = 0.0) -> Ship:
    s = Ship()
    s.x = x
    s.y = y
    return s


def make_enemy(
    type_: str = "cruiser",
    x: float = 0.0,
    y: float = 0.0,
    hull: float | None = None,
    state: str = "idle",
    beam_cooldown: float = 0.0,
) -> Enemy:
    e = spawn_enemy(type_, x, y, f"{type_}_1")  # type: ignore[arg-type]
    e.ai_state = state  # type: ignore[assignment]
    if hull is not None:
        e.hull = hull
    e.beam_cooldown = beam_cooldown
    return e


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


def test_idle_to_chase_when_player_enters_detect_range():
    ship = make_ship(x=0.0, y=0.0)
    params = ENEMY_TYPE_PARAMS["cruiser"]
    # Place enemy just inside detect range.
    enemy = make_enemy("cruiser", x=params["detect_range"] - 100.0, y=0.0, state="idle")
    enemies = [enemy]
    tick_enemies(enemies, ship, dt=0.1)
    assert enemy.ai_state == "chase"


def test_idle_stays_idle_when_player_outside_detect_range():
    ship = make_ship(x=0.0, y=0.0)
    params = ENEMY_TYPE_PARAMS["cruiser"]
    enemy = make_enemy("cruiser", x=params["detect_range"] + 1_000.0, y=0.0, state="idle")
    enemies = [enemy]
    tick_enemies(enemies, ship, dt=0.1)
    assert enemy.ai_state == "idle"


def test_chase_to_attack_when_player_enters_weapon_range():
    ship = make_ship(x=0.0, y=0.0)
    params = ENEMY_TYPE_PARAMS["cruiser"]
    enemy = make_enemy("cruiser", x=params["weapon_range"] - 100.0, y=0.0, state="chase")
    enemies = [enemy]
    tick_enemies(enemies, ship, dt=0.1)
    assert enemy.ai_state == "attack"


def test_chase_stays_chase_when_player_outside_weapon_range():
    ship = make_ship(x=0.0, y=0.0)
    params = ENEMY_TYPE_PARAMS["cruiser"]
    enemy = make_enemy("cruiser", x=params["weapon_range"] + 1_000.0, y=0.0, state="chase")
    enemies = [enemy]
    tick_enemies(enemies, ship, dt=0.1)
    assert enemy.ai_state == "chase"


def test_attack_to_flee_when_hull_below_threshold():
    ship = make_ship(x=0.0, y=0.0)
    params = ENEMY_TYPE_PARAMS["cruiser"]
    max_hull = params["hull"]
    flee_hp = params["flee_threshold"] * max_hull - 1.0  # just below threshold
    enemy = make_enemy("cruiser", x=params["weapon_range"] - 100.0, y=0.0,
                        state="attack", hull=flee_hp)
    enemies = [enemy]
    tick_enemies(enemies, ship, dt=0.1)
    assert enemy.ai_state == "flee"


def test_attack_stays_attack_when_hull_above_threshold():
    ship = make_ship(x=0.0, y=0.0)
    params = ENEMY_TYPE_PARAMS["cruiser"]
    max_hull = params["hull"]
    safe_hp = params["flee_threshold"] * max_hull + 1.0  # just above threshold
    enemy = make_enemy("cruiser", x=params["weapon_range"] - 100.0, y=0.0,
                        state="attack", hull=safe_hp)
    enemies = [enemy]
    tick_enemies(enemies, ship, dt=0.1)
    assert enemy.ai_state == "attack"


# ---------------------------------------------------------------------------
# Flee movement
# ---------------------------------------------------------------------------


def test_flee_movement_is_away_from_player():
    """Enemy in flee state should move away from the player."""
    ship = make_ship(x=0.0, y=0.0)
    # Place enemy directly north of player.
    enemy = make_enemy("cruiser", x=0.0, y=-5_000.0, state="flee")
    enemy.heading = 0.0   # initially pointing north (same direction as flee)
    start_x, start_y = enemy.x, enemy.y
    enemies = [enemy]
    tick_enemies(enemies, ship, dt=1.0)
    # Enemy should have moved further north (negative y) — away from player.
    assert enemy.y < start_y, "Enemy should flee away from player (decrease y)"


# ---------------------------------------------------------------------------
# Cruiser attack movement
# ---------------------------------------------------------------------------


def test_cruiser_presses_toward_player_in_attack():
    ship = make_ship(x=0.0, y=0.0)
    # Place cruiser well within attack range, already facing the player.
    # Enemy is at (0, -3000); bearing to player at (0,0) is 180° (south).
    params = ENEMY_TYPE_PARAMS["cruiser"]
    enemy = make_enemy("cruiser", x=0.0, y=-3_000.0, state="attack")
    enemy.heading = 180.0  # facing south = toward player
    start_dist = math.hypot(enemy.x - ship.x, enemy.y - ship.y)
    enemies = [enemy]
    tick_enemies(enemies, ship, dt=1.0)
    end_dist = math.hypot(enemy.x - ship.x, enemy.y - ship.y)
    assert end_dist < start_dist, "Cruiser should close distance in attack state"


# ---------------------------------------------------------------------------
# Destroyer standoff
# ---------------------------------------------------------------------------


def test_destroyer_approaches_when_too_far():
    ship = make_ship(x=0.0, y=0.0)
    params = ENEMY_TYPE_PARAMS["destroyer"]
    # Just outside weapon range.
    enemy = make_enemy("destroyer", x=0.0, y=-(params["weapon_range"] + 500.0), state="attack")
    enemy.heading = 180.0  # pointing south = toward player
    start_dist = math.hypot(enemy.x - ship.x, enemy.y - ship.y)
    enemies = [enemy]
    tick_enemies(enemies, ship, dt=1.0)
    end_dist = math.hypot(enemy.x - ship.x, enemy.y - ship.y)
    assert end_dist < start_dist, "Destroyer should approach when outside weapon range"


def test_destroyer_backs_away_when_too_close():
    ship = make_ship(x=0.0, y=0.0)
    params = ENEMY_TYPE_PARAMS["destroyer"]
    # Well inside the close threshold (weapon_range * 0.6).
    close = params["weapon_range"] * 0.5
    enemy = make_enemy("destroyer", x=0.0, y=-close, state="attack")
    enemy.heading = 0.0  # pointing north = away from player
    start_dist = math.hypot(enemy.x - ship.x, enemy.y - ship.y)
    enemies = [enemy]
    tick_enemies(enemies, ship, dt=1.0)
    end_dist = math.hypot(enemy.x - ship.x, enemy.y - ship.y)
    assert end_dist > start_dist, "Destroyer should back away when inside min standoff"


# ---------------------------------------------------------------------------
# Scout strafe
# ---------------------------------------------------------------------------


def test_scout_strafe_offset_at_close_range():
    """At dist < 2000, scout should steer 90° offset from bearing, not directly at player."""
    ship = make_ship(x=0.0, y=0.0)
    # Place scout 1500 units due north of player.
    # bearing_to(0, -1500, 0, 0) = 180° (south). Strafe heading = 180+90 = 270°.
    # angle_diff(0, 270) = -90° so shortest turn is LEFT 90°.
    # At AI_TURN_RATE=90°/s, 10 ticks × 0.1s = 1.0s = full 90° turn to reach 270°.
    enemy = make_enemy("scout", x=0.0, y=-1_500.0, state="attack")
    enemy.heading = 0.0
    enemies = [enemy]
    for _ in range(10):
        tick_enemies(enemies, ship, dt=0.1)
    # Scout should now be at heading ~270° (pointing west to strafe the player).
    diff = abs(((enemy.heading - 270.0) + 180) % 360 - 180)
    assert diff < 5.0, f"Scout heading {enemy.heading:.1f}° should be near 270°"


# ---------------------------------------------------------------------------
# Beam fire
# ---------------------------------------------------------------------------


def test_beam_fires_in_arc_and_cooldown_zero():
    ship = make_ship(x=0.0, y=0.0)
    params = ENEMY_TYPE_PARAMS["cruiser"]
    # Place enemy south of player — bearing from enemy to player is 0° (north).
    enemy = make_enemy("cruiser", x=0.0, y=params["weapon_range"] - 100.0, state="attack",
                        beam_cooldown=0.0)
    enemy.heading = 0.0  # facing north = toward player
    enemies = [enemy]
    events = tick_enemies(enemies, ship, dt=0.1)
    assert len(events) == 1
    assert events[0].attacker_id == enemy.id
    assert events[0].damage == params["beam_dmg"]


def test_beam_does_not_fire_when_out_of_arc():
    ship = make_ship(x=0.0, y=0.0)
    params = ENEMY_TYPE_PARAMS["cruiser"]
    # Place enemy south of player (bearing = 0°), but facing east (90°) — out of arc.
    enemy = make_enemy("cruiser", x=0.0, y=params["weapon_range"] - 100.0, state="attack",
                        beam_cooldown=0.0)
    enemy.heading = 90.0  # facing east — player is directly ahead at 0°, diff = 90° > arc 40°
    enemies = [enemy]
    events = tick_enemies(enemies, ship, dt=0.1)
    assert len(events) == 0


def test_beam_does_not_fire_when_cooldown_positive():
    ship = make_ship(x=0.0, y=0.0)
    params = ENEMY_TYPE_PARAMS["cruiser"]
    enemy = make_enemy("cruiser", x=0.0, y=params["weapon_range"] - 100.0, state="attack",
                        beam_cooldown=1.0)
    enemy.heading = 0.0
    enemies = [enemy]
    events = tick_enemies(enemies, ship, dt=0.1)
    assert len(events) == 0


def test_cooldown_decrements_each_tick():
    ship = make_ship(x=0.0, y=0.0)
    enemy = make_enemy("scout", x=0.0, y=0.0, state="attack", beam_cooldown=1.0)
    enemies = [enemy]
    tick_enemies(enemies, ship, dt=0.1)
    assert enemy.beam_cooldown == pytest.approx(0.9)


def test_cooldown_does_not_go_below_zero():
    ship = make_ship(x=0.0, y=0.0)
    enemy = make_enemy("scout", x=0.0, y=0.0, state="attack", beam_cooldown=0.05)
    enemies = [enemy]
    tick_enemies(enemies, ship, dt=0.5)
    assert enemy.beam_cooldown == 0.0


def test_cooldown_reset_after_beam_fires():
    ship = make_ship(x=0.0, y=0.0)
    params = ENEMY_TYPE_PARAMS["cruiser"]
    enemy = make_enemy("cruiser", x=0.0, y=params["weapon_range"] - 100.0, state="attack",
                        beam_cooldown=0.0)
    enemy.heading = 0.0
    enemies = [enemy]
    events = tick_enemies(enemies, ship, dt=0.1)
    assert len(events) == 1
    assert enemy.beam_cooldown == pytest.approx(params["beam_cooldown"])


# ---------------------------------------------------------------------------
# Despawn condition
# ---------------------------------------------------------------------------


def test_enemy_despawns_when_fleeing_and_out_of_range():
    ship = make_ship(x=0.0, y=0.0)
    params = ENEMY_TYPE_PARAMS["scout"]
    # Place enemy at 2× detect_range + 1000 (already beyond despawn threshold).
    far = 2.0 * params["detect_range"] + 1_000.0
    enemy = make_enemy("scout", x=0.0, y=-far, state="flee")
    enemies = [enemy]
    tick_enemies(enemies, ship, dt=0.1)
    assert len(enemies) == 0, "Enemy should be removed when far enough while fleeing"


def test_enemy_does_not_despawn_when_not_fleeing():
    ship = make_ship(x=0.0, y=0.0)
    params = ENEMY_TYPE_PARAMS["scout"]
    far = 2.0 * params["detect_range"] + 1_000.0
    enemy = make_enemy("scout", x=0.0, y=-far, state="idle")
    enemies = [enemy]
    tick_enemies(enemies, ship, dt=0.1)
    assert len(enemies) == 1


# ---------------------------------------------------------------------------
# beam_in_arc helper
# ---------------------------------------------------------------------------


def test_beam_in_arc_target_directly_ahead():
    assert beam_in_arc(0.0, 0.0, 40.0) is True


def test_beam_in_arc_target_at_edge():
    assert beam_in_arc(0.0, 40.0, 40.0) is True


def test_beam_in_arc_target_just_outside():
    assert beam_in_arc(0.0, 41.0, 40.0) is False


def test_beam_in_arc_wrap_around():
    # Shooter heading 350°, target bearing 10° — diff = 20° < 40°.
    assert beam_in_arc(350.0, 10.0, 40.0) is True


# ---------------------------------------------------------------------------
# Station-priority targeting (Mission 2)
# ---------------------------------------------------------------------------


def test_enemy_chases_station_not_ship_when_station_provided():
    """Enemy should move toward station, not toward ship, when stations is provided."""
    # Ship is far south; station is north of enemy.
    ship = make_ship(x=50_000.0, y=90_000.0)
    station = Station(id="kepler", x=50_000.0, y=25_000.0, hull=200.0)

    # Enemy at y=40000 (station is north at y=25000); heading west (270°).
    # Dist to station = 15000 > weapon_range (6000), so stays in chase.
    # angle_diff(270, 0) = 90 → turns CW by 90°/s → heading reaches 0 after 1s.
    # Then moves north (y decreases).
    enemy = make_enemy("cruiser", x=50_000.0, y=40_000.0, state="chase")
    enemy.heading = 270.0  # facing west; needs to turn north to reach station
    start_y = enemy.y

    tick_enemies([enemy], ship, dt=1.0, stations=[station])
    # Enemy should have moved toward station (north = decreasing y).
    assert enemy.y < start_y, "Enemy should move toward station (north, decreasing y)"


def test_beam_hits_station_not_player_when_station_targeted():
    """When station targeting is active, beam hit events should target the station id."""
    # Station is north of enemy; ship is far south.
    ship = make_ship(x=0.0, y=100_000.0)
    station = Station(id="kepler", x=0.0, y=0.0, hull=200.0)

    # Enemy at y=5000 (station at y=0 is north), heading north (0°), in attack range.
    # bearing_to(0, 5000, 0, 0) = atan2(0, 5000-0) = 0° (north) ✓
    params = ENEMY_TYPE_PARAMS["cruiser"]
    enemy = make_enemy("cruiser", x=0.0, y=5_000.0, state="attack")
    enemy.heading = 0.0  # facing north — station is due north at (0, 0)
    enemy.beam_cooldown = 0.0

    events = tick_enemies([enemy], ship, dt=0.1, stations=[station])

    assert len(events) == 1
    assert events[0].target == "kepler"
    assert events[0].attacker_id == enemy.id


def test_beam_event_default_target_is_player():
    """Without stations, beam events should target 'player'."""
    ship = make_ship(x=0.0, y=0.0)
    params = ENEMY_TYPE_PARAMS["scout"]
    enemy = make_enemy("scout", x=0.0, y=params["weapon_range"] - 100.0, state="attack")
    enemy.heading = 0.0
    enemy.beam_cooldown = 0.0

    events = tick_enemies([enemy], ship, dt=0.1)
    assert len(events) == 1
    assert events[0].target == "player"
