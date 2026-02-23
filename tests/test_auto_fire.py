"""Tests for the auto-fire targeting computer (game_loop_weapons.py).

When no player occupies the Weapons station, the auto-fire system
engages after a 3-second delay and fires beams at the nearest scanned
hostile — with reduced accuracy and cadence.
"""
from __future__ import annotations

from unittest.mock import patch

import server.game_loop_weapons as glw
from server.models.ship import Ship
from server.models.world import World, spawn_enemy
from server.systems.combat import BEAM_PLAYER_RANGE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_ship() -> Ship:
    """Return a Ship at the origin heading north with full beams."""
    ship = Ship()
    ship.x = 0.0
    ship.y = 0.0
    ship.heading = 0.0
    return ship


def _fresh_world(ship: Ship | None = None) -> World:
    world = World()
    if ship is not None:
        world.ship = ship
    return world


def _scanned_enemy(entity_id: str, x: float, y: float, hull: float = 100.0):
    """Create a scanned enemy at the given position."""
    enemy = spawn_enemy("fighter", x, y, entity_id)
    enemy.scan_state = "scanned"
    enemy.hull = hull
    return enemy


def _activate_auto_fire():
    """Set weapons as uncrewed and tick past the activation delay."""
    glw.reset()
    glw.set_weapons_crewed(False)
    # Tick past the 3-second delay.
    glw.tick_auto_fire(_fresh_ship(), _fresh_world(), 3.1)
    assert glw.is_auto_fire_active()


# ---------------------------------------------------------------------------
# 1. Constants
# ---------------------------------------------------------------------------


def test_constants():
    assert glw.AUTO_FIRE_INTERVAL == 1.0
    assert glw.AUTO_FIRE_ACCURACY == 0.75
    assert glw.AUTO_FIRE_DELAY == 3.0


# ---------------------------------------------------------------------------
# 2. Activation delay
# ---------------------------------------------------------------------------


def test_activation_delay():
    glw.reset()
    ship = _fresh_ship()
    world = _fresh_world(ship)
    glw.set_weapons_crewed(False)

    # Tick 2.9 seconds — not yet active.
    glw.tick_auto_fire(ship, world, 2.9)
    assert not glw.is_auto_fire_active()

    # Tick 0.2 more seconds (total ≥3.0) — now active.
    glw.tick_auto_fire(ship, world, 0.2)
    assert glw.is_auto_fire_active()


# ---------------------------------------------------------------------------
# 3. Immediate deactivation on crew
# ---------------------------------------------------------------------------


def test_immediate_deactivation_on_crew():
    _activate_auto_fire()
    glw.set_weapons_crewed(True)
    assert not glw.is_auto_fire_active()


# ---------------------------------------------------------------------------
# 4. Fires at scanned enemy
# ---------------------------------------------------------------------------


def test_fires_at_scanned_enemy():
    glw.reset()
    ship = _fresh_ship()
    world = _fresh_world(ship)

    # Place scanned enemy ahead, within range.
    enemy = _scanned_enemy("e1", 0.0, -1000.0)
    world.enemies.append(enemy)

    glw.set_weapons_crewed(False)
    # Activate (tick past delay).
    glw.tick_auto_fire(ship, world, 3.1)

    # Now fire — mock rng to always hit (return value ≤ 0.75).
    with patch.object(glw._rng, "random", return_value=0.5):
        events = glw.tick_auto_fire(ship, world, 1.0)

    assert len(events) == 1
    etype, payload = events[0]
    assert etype == "weapons.beam_fired"
    assert payload["target_id"] == "e1"
    assert payload["source"] == "auto"


# ---------------------------------------------------------------------------
# 5. Ignores unscanned enemy
# ---------------------------------------------------------------------------


def test_ignores_unscanned_enemy():
    glw.reset()
    ship = _fresh_ship()
    world = _fresh_world(ship)

    enemy = spawn_enemy("fighter", 0.0, -1000.0, "e1")
    enemy.scan_state = "unknown"
    world.enemies.append(enemy)

    glw.set_weapons_crewed(False)
    glw.tick_auto_fire(ship, world, 3.1)

    with patch.object(glw._rng, "random", return_value=0.5):
        events = glw.tick_auto_fire(ship, world, 1.0)

    assert events == []


# ---------------------------------------------------------------------------
# 6. Ignores out-of-range
# ---------------------------------------------------------------------------


def test_ignores_out_of_range():
    glw.reset()
    ship = _fresh_ship()
    world = _fresh_world(ship)

    # Place enemy beyond BEAM_PLAYER_RANGE.
    enemy = _scanned_enemy("e1", 0.0, -(BEAM_PLAYER_RANGE + 1000))
    world.enemies.append(enemy)

    glw.set_weapons_crewed(False)
    glw.tick_auto_fire(ship, world, 3.1)

    with patch.object(glw._rng, "random", return_value=0.5):
        events = glw.tick_auto_fire(ship, world, 1.0)

    assert events == []


# ---------------------------------------------------------------------------
# 7. Ignores out-of-arc (behind ship)
# ---------------------------------------------------------------------------


def test_ignores_out_of_arc():
    glw.reset()
    ship = _fresh_ship()
    ship.heading = 0.0  # North
    world = _fresh_world(ship)

    # Place enemy directly behind the ship (south).
    enemy = _scanned_enemy("e1", 0.0, 1000.0)
    world.enemies.append(enemy)

    glw.set_weapons_crewed(False)
    glw.tick_auto_fire(ship, world, 3.1)

    with patch.object(glw._rng, "random", return_value=0.5):
        events = glw.tick_auto_fire(ship, world, 1.0)

    assert events == []


# ---------------------------------------------------------------------------
# 8. Nearest target selection
# ---------------------------------------------------------------------------


def test_nearest_target_selection():
    glw.reset()
    ship = _fresh_ship()
    world = _fresh_world(ship)

    far = _scanned_enemy("far", 0.0, -3000.0)
    near = _scanned_enemy("near", 0.0, -1000.0)
    world.enemies.extend([far, near])

    glw.set_weapons_crewed(False)
    glw.tick_auto_fire(ship, world, 3.1)

    with patch.object(glw._rng, "random", return_value=0.5):
        events = glw.tick_auto_fire(ship, world, 1.0)

    assert len(events) == 1
    assert events[0][1]["target_id"] == "near"


# ---------------------------------------------------------------------------
# 9. Accuracy miss
# ---------------------------------------------------------------------------


def test_accuracy_miss():
    glw.reset()
    ship = _fresh_ship()
    world = _fresh_world(ship)

    enemy = _scanned_enemy("e1", 0.0, -1000.0, hull=100.0)
    world.enemies.append(enemy)

    glw.set_weapons_crewed(False)
    glw.tick_auto_fire(ship, world, 3.1)

    # rng returns > 0.75 → miss.
    with patch.object(glw._rng, "random", return_value=0.9):
        events = glw.tick_auto_fire(ship, world, 1.0)

    assert events == []
    assert enemy.hull == 100.0  # no damage


# ---------------------------------------------------------------------------
# 10. No frequency matching
# ---------------------------------------------------------------------------


def test_no_frequency_matching():
    glw.reset()
    ship = _fresh_ship()
    world = _fresh_world(ship)

    enemy = _scanned_enemy("e1", 0.0, -1000.0)
    world.enemies.append(enemy)

    glw.set_weapons_crewed(False)
    glw.tick_auto_fire(ship, world, 3.1)

    with patch.object(glw._rng, "random", return_value=0.5):
        events = glw.tick_auto_fire(ship, world, 1.0)

    assert events[0][1]["beam_frequency"] == ""


# ---------------------------------------------------------------------------
# 11. Cooldown interval
# ---------------------------------------------------------------------------


def test_cooldown_interval():
    glw.reset()
    ship = _fresh_ship()
    world = _fresh_world(ship)

    enemy = _scanned_enemy("e1", 0.0, -1000.0, hull=500.0)
    world.enemies.append(enemy)

    glw.set_weapons_crewed(False)
    glw.tick_auto_fire(ship, world, 3.1)

    # First shot.
    with patch.object(glw._rng, "random", return_value=0.5):
        events1 = glw.tick_auto_fire(ship, world, 1.0)
    assert len(events1) == 1

    # 0.5s later — still on cooldown.
    with patch.object(glw._rng, "random", return_value=0.5):
        events2 = glw.tick_auto_fire(ship, world, 0.5)
    assert events2 == []

    # 0.6s later (total 1.1s > 1.0s cooldown) — fires again.
    with patch.object(glw._rng, "random", return_value=0.5):
        events3 = glw.tick_auto_fire(ship, world, 0.6)
    assert len(events3) == 1


# ---------------------------------------------------------------------------
# 12. Preserves manual target
# ---------------------------------------------------------------------------


def test_preserves_manual_target():
    glw.reset()
    glw.set_target("manual_tgt")
    ship = _fresh_ship()
    world = _fresh_world(ship)

    enemy = _scanned_enemy("e1", 0.0, -1000.0)
    world.enemies.append(enemy)

    glw.set_weapons_crewed(False)
    glw.tick_auto_fire(ship, world, 3.1)

    with patch.object(glw._rng, "random", return_value=0.5):
        glw.tick_auto_fire(ship, world, 1.0)

    # Manual target is untouched.
    assert glw.get_target() == "manual_tgt"


# ---------------------------------------------------------------------------
# 13. Serialise / deserialise round-trip
# ---------------------------------------------------------------------------


def test_serialise_deserialise():
    glw.reset()
    glw.set_weapons_crewed(False)
    ship = _fresh_ship()
    world = _fresh_world(ship)
    glw.tick_auto_fire(ship, world, 3.1)
    assert glw.is_auto_fire_active()

    data = glw.serialise()
    assert data["auto_fire_active"] is True
    assert data["auto_fire_delay"] == 0.0

    # Reset and restore.
    glw.reset()
    assert not glw.is_auto_fire_active()
    glw.deserialise(data)
    assert glw.is_auto_fire_active()


# ---------------------------------------------------------------------------
# 14. Status-changed flag
# ---------------------------------------------------------------------------


def test_status_changed_flag():
    glw.reset()
    ship = _fresh_ship()
    world = _fresh_world(ship)

    # Initially no change.
    assert glw.pop_auto_fire_status_changed() is None

    # Activate → True.
    glw.set_weapons_crewed(False)
    glw.tick_auto_fire(ship, world, 3.1)
    assert glw.pop_auto_fire_status_changed() is True
    # Consumed.
    assert glw.pop_auto_fire_status_changed() is None

    # Deactivate → False.
    glw.set_weapons_crewed(True)
    assert glw.pop_auto_fire_status_changed() is False
    assert glw.pop_auto_fire_status_changed() is None


# ---------------------------------------------------------------------------
# 15. No fire when crewed
# ---------------------------------------------------------------------------


def test_no_fire_when_crewed():
    glw.reset()
    ship = _fresh_ship()
    world = _fresh_world(ship)

    enemy = _scanned_enemy("e1", 0.0, -1000.0)
    world.enemies.append(enemy)

    glw.set_weapons_crewed(True)
    events = glw.tick_auto_fire(ship, world, 10.0)
    assert events == []
    assert not glw.is_auto_fire_active()


# ---------------------------------------------------------------------------
# 16. Enemy destroyed and removed
# ---------------------------------------------------------------------------


def test_enemy_destroyed_removal():
    glw.reset()
    ship = _fresh_ship()
    world = _fresh_world(ship)

    # Low-hull enemy — will die from one beam hit.
    enemy = _scanned_enemy("e1", 0.0, -1000.0, hull=1.0)
    world.enemies.append(enemy)

    glw.set_weapons_crewed(False)
    glw.tick_auto_fire(ship, world, 3.1)

    with patch.object(glw._rng, "random", return_value=0.5):
        events = glw.tick_auto_fire(ship, world, 1.0)

    assert len(events) == 1
    assert len(world.enemies) == 0  # removed


# ---------------------------------------------------------------------------
# 17. No fire at zero beam efficiency
# ---------------------------------------------------------------------------


def test_no_fire_zero_beam_efficiency():
    glw.reset()
    ship = _fresh_ship()
    ship.systems["beams"].health = 0.0
    world = _fresh_world(ship)

    enemy = _scanned_enemy("e1", 0.0, -1000.0, hull=100.0)
    world.enemies.append(enemy)

    glw.set_weapons_crewed(False)
    glw.tick_auto_fire(ship, world, 3.1)

    with patch.object(glw._rng, "random", return_value=0.5):
        events = glw.tick_auto_fire(ship, world, 1.0)

    # Fires but with 0 damage (0 efficiency × base damage = 0).
    assert len(events) == 1
    assert events[0][1]["damage"] == 0.0
    assert enemy.hull == 100.0  # unchanged
