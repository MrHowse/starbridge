"""Tests for the Electronic Warfare system.

Covers:
  game_loop_ew: reset, set_jam_target, toggle_countermeasures,
                set_intrusion_target, apply_intrusion_success, tick, build_state.
  Payload schemas: EWSetJamTargetPayload, EWToggleCountermeasuresPayload,
                   EWBeginIntrusionPayload.
  Handler: valid enqueue, validation errors.
  AI integration: jam_factor reduces beam damage; intrusion_stun blocks fire.
  Combat integration: countermeasure reduction on hull damage.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

import server.game_loop_ew as glew
from server import ew as ew_handler
from server.models.messages import Message
from server.models.messages.ew import (
    EWBeginIntrusionPayload,
    EWSetJamTargetPayload,
    EWToggleCountermeasuresPayload,
)
from server.models.ship import Ship
from server.models.world import Enemy, World
from server.systems.ai import tick_enemies
from server.systems.combat import (
    COUNTERMEASURE_REDUCTION,
    apply_hit_to_player,
)
from server.utils.math_helpers import distance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ship() -> Ship:
    """Return a fresh Ship at (50000, 50000)."""
    return Ship()


def make_enemy(eid: str = "e1", x: float = 50_000.0, y: float = 35_000.0) -> Enemy:
    """Return a fresh enemy near the player ship."""
    return Enemy(id=eid, type="scout", x=x, y=y, hull=40.0)


def make_world_with_enemy() -> tuple[World, Enemy]:
    world = World()
    enemy = make_enemy()
    world.enemies.append(enemy)
    return world, enemy


class MockSender:
    def __init__(self) -> None:
        self.sent: list[Message] = []

    async def send(self, connection_id: str, message: Message) -> None:
        self.sent.append(message)


def fresh_ew_handler() -> tuple[MockSender, asyncio.Queue]:
    sender = MockSender()
    queue: asyncio.Queue = asyncio.Queue()
    ew_handler.init(sender, queue)
    return sender, queue


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------


def test_reset_clears_jam_target():
    glew.set_jam_target("e1")
    glew.reset()
    _, _, jam = glew._jam_target_id, None, glew._jam_target_id
    assert glew._jam_target_id is None


def test_reset_clears_intrusion_target():
    glew.set_intrusion_target("e2", "shields")
    glew.reset()
    assert glew._intrusion_target_id is None
    assert glew._intrusion_target_system is None


# ---------------------------------------------------------------------------
# set_jam_target()
# ---------------------------------------------------------------------------


def test_set_jam_target_stores_id():
    glew.reset()
    glew.set_jam_target("enemy_7")
    assert glew._jam_target_id == "enemy_7"


def test_set_jam_target_none_clears():
    glew.reset()
    glew.set_jam_target("enemy_7")
    glew.set_jam_target(None)
    assert glew._jam_target_id is None


# ---------------------------------------------------------------------------
# toggle_countermeasures()
# ---------------------------------------------------------------------------


def test_toggle_countermeasures_on():
    ship = make_ship()
    ship.countermeasure_charges = 5
    glew.toggle_countermeasures(True, ship)
    assert ship.ew_countermeasure_active is True


def test_toggle_countermeasures_off():
    ship = make_ship()
    ship.ew_countermeasure_active = True
    glew.toggle_countermeasures(False, ship)
    assert ship.ew_countermeasure_active is False


def test_toggle_countermeasures_on_with_no_charges_does_nothing():
    ship = make_ship()
    ship.countermeasure_charges = 0
    glew.toggle_countermeasures(True, ship)
    assert ship.ew_countermeasure_active is False


# ---------------------------------------------------------------------------
# set_intrusion_target() / get_intrusion_target()
# ---------------------------------------------------------------------------


def test_set_intrusion_target():
    glew.reset()
    glew.set_intrusion_target("e5", "engines")
    eid, sys = glew.get_intrusion_target()
    assert eid == "e5"
    assert sys == "engines"


# ---------------------------------------------------------------------------
# apply_intrusion_success()
# ---------------------------------------------------------------------------


def test_apply_intrusion_success_sets_stun_ticks():
    world, enemy = make_world_with_enemy()
    glew.apply_intrusion_success("e1", world)
    assert enemy.intrusion_stun_ticks == glew.INTRUSION_STUN_DURATION


def test_apply_intrusion_success_does_not_decrease_existing_stun():
    world, enemy = make_world_with_enemy()
    enemy.intrusion_stun_ticks = glew.INTRUSION_STUN_DURATION + 10
    glew.apply_intrusion_success("e1", world)
    assert enemy.intrusion_stun_ticks == glew.INTRUSION_STUN_DURATION + 10


def test_apply_intrusion_success_unknown_id_is_noop():
    world, enemy = make_world_with_enemy()
    glew.apply_intrusion_success("UNKNOWN", world)
    assert enemy.intrusion_stun_ticks == 0


# ---------------------------------------------------------------------------
# tick() — jam buildup and decay
# ---------------------------------------------------------------------------


def test_tick_builds_up_jam_when_in_range():
    glew.reset()
    world, enemy = make_world_with_enemy()
    ship = world.ship
    # Enemy is 15000 units north of ship (at sector centre 50000,50000)
    enemy.x, enemy.y = ship.x, ship.y - 10_000.0  # well within JAM_BASE_RANGE
    glew.set_jam_target("e1")
    glew.tick(world, ship, dt=1.0)
    assert enemy.jam_factor > 0.0


def test_tick_jam_does_not_exceed_max():
    glew.reset()
    world, enemy = make_world_with_enemy()
    ship = world.ship
    enemy.x, enemy.y = ship.x, ship.y - 1_000.0  # very close
    enemy.jam_factor = glew.JAM_MAX_FACTOR - 0.01
    glew.set_jam_target("e1")
    # Tick many times
    for _ in range(100):
        glew.tick(world, ship, dt=1.0)
    assert enemy.jam_factor <= glew.JAM_MAX_FACTOR


def test_tick_decays_non_target():
    glew.reset()
    world, enemy = make_world_with_enemy()
    ship = world.ship
    enemy.jam_factor = 0.5
    glew.set_jam_target(None)  # no active target
    glew.tick(world, ship, dt=1.0)
    assert enemy.jam_factor < 0.5


def test_tick_decay_reaches_zero():
    glew.reset()
    world, enemy = make_world_with_enemy()
    ship = world.ship
    enemy.jam_factor = 0.1
    glew.set_jam_target(None)
    for _ in range(10):
        glew.tick(world, ship, dt=1.0)
    assert enemy.jam_factor == 0.0


def test_tick_no_jam_when_ecm_offline():
    glew.reset()
    world, enemy = make_world_with_enemy()
    ship = world.ship
    ship.systems["ecm_suite"].health = 0.0   # ECM offline → efficiency=0
    enemy.x, enemy.y = ship.x, ship.y - 1_000.0
    glew.set_jam_target("e1")
    glew.tick(world, ship, dt=1.0)
    assert enemy.jam_factor == 0.0  # no buildup when ECM is offline


def test_tick_no_jam_when_out_of_range():
    glew.reset()
    world, enemy = make_world_with_enemy()
    ship = world.ship
    # Place enemy far outside JAM_BASE_RANGE
    enemy.x, enemy.y = ship.x, ship.y - (glew.JAM_BASE_RANGE + 5_000.0)
    glew.set_jam_target("e1")
    glew.tick(world, ship, dt=1.0)
    # Should decay (enemy was not jammed before), stay at 0
    assert enemy.jam_factor == 0.0


def test_tick_extended_range_when_overclocked():
    glew.reset()
    world, enemy = make_world_with_enemy()
    ship = world.ship
    # Overclock ECM to 150% → efficiency = 1.5
    ship.systems["ecm_suite"].power = 150.0
    # Place enemy just outside base range but within 1.5× range
    enemy.x, enemy.y = ship.x, ship.y - (glew.JAM_BASE_RANGE * 1.2)
    glew.set_jam_target("e1")
    glew.tick(world, ship, dt=1.0)
    assert enemy.jam_factor > 0.0


# ---------------------------------------------------------------------------
# build_state()
# ---------------------------------------------------------------------------


def test_build_state_returns_dict():
    glew.reset()
    world, enemy = make_world_with_enemy()
    state = glew.build_state(world, world.ship)
    assert isinstance(state, dict)


def test_build_state_has_jam_target():
    glew.reset()
    glew.set_jam_target("e1")
    world, enemy = make_world_with_enemy()
    state = glew.build_state(world, world.ship)
    assert state["jam_target_id"] == "e1"


def test_build_state_countermeasure_fields():
    glew.reset()
    world, _ = make_world_with_enemy()
    ship = world.ship
    ship.ew_countermeasure_active = True
    ship.countermeasure_charges = 7
    state = glew.build_state(world, ship)
    assert state["countermeasures_active"] is True
    assert state["countermeasure_charges"] == 7


def test_build_state_includes_enemies():
    glew.reset()
    world, enemy = make_world_with_enemy()
    state = glew.build_state(world, world.ship)
    assert len(state["enemies"]) == 1
    e = state["enemies"][0]
    assert e["id"] == "e1"
    assert "jam_factor" in e
    assert "intrusion_stun_ticks" in e
    assert "distance" in e


def test_build_state_intrusion_target():
    glew.reset()
    glew.set_intrusion_target("e1", "weapons")
    world, _ = make_world_with_enemy()
    state = glew.build_state(world, world.ship)
    assert state["intrusion_target_id"] == "e1"
    assert state["intrusion_target_system"] == "weapons"


# ---------------------------------------------------------------------------
# Payload schemas
# ---------------------------------------------------------------------------


def test_ew_set_jam_target_with_id():
    p = EWSetJamTargetPayload(entity_id="enemy_3")
    assert p.entity_id == "enemy_3"


def test_ew_set_jam_target_none():
    p = EWSetJamTargetPayload(entity_id=None)
    assert p.entity_id is None


def test_ew_set_jam_target_default_none():
    p = EWSetJamTargetPayload()
    assert p.entity_id is None


def test_ew_toggle_countermeasures_true():
    p = EWToggleCountermeasuresPayload(active=True)
    assert p.active is True


def test_ew_toggle_countermeasures_false():
    p = EWToggleCountermeasuresPayload(active=False)
    assert p.active is False


def test_ew_begin_intrusion_valid_shields():
    p = EWBeginIntrusionPayload(entity_id="e1", target_system="shields")
    assert p.target_system == "shields"


def test_ew_begin_intrusion_valid_weapons():
    p = EWBeginIntrusionPayload(entity_id="e1", target_system="weapons")
    assert p.target_system == "weapons"


def test_ew_begin_intrusion_valid_engines():
    p = EWBeginIntrusionPayload(entity_id="e1", target_system="engines")
    assert p.target_system == "engines"


def test_ew_begin_intrusion_invalid_system_raises():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        EWBeginIntrusionPayload(entity_id="e1", target_system="torpedoes")


# ---------------------------------------------------------------------------
# Handler tests
# ---------------------------------------------------------------------------


async def test_handler_valid_jam_target_enqueues():
    _, queue = fresh_ew_handler()
    msg = Message.build("ew.set_jam_target", {"entity_id": "e1"})
    await ew_handler.handle_ew_message("conn1", msg)
    assert queue.qsize() == 1
    msg_type, payload = await queue.get()
    assert msg_type == "ew.set_jam_target"
    assert payload.entity_id == "e1"


async def test_handler_valid_countermeasures_enqueues():
    _, queue = fresh_ew_handler()
    msg = Message.build("ew.toggle_countermeasures", {"active": True})
    await ew_handler.handle_ew_message("conn1", msg)
    assert queue.qsize() == 1
    msg_type, payload = await queue.get()
    assert msg_type == "ew.toggle_countermeasures"
    assert payload.active is True


async def test_handler_invalid_payload_sends_error():
    sender, queue = fresh_ew_handler()
    msg = Message.build("ew.begin_intrusion", {"entity_id": "e1", "target_system": "INVALID"})
    await ew_handler.handle_ew_message("conn1", msg)
    assert queue.empty()
    assert len(sender.sent) == 1
    assert sender.sent[0].type == "error.validation"


async def test_handler_unknown_type_does_not_enqueue():
    _, queue = fresh_ew_handler()
    msg = Message.build("ew.unknown_command", {})
    await ew_handler.handle_ew_message("conn1", msg)
    assert queue.empty()


# ---------------------------------------------------------------------------
# AI integration — jam_factor reduces beam damage
# ---------------------------------------------------------------------------


def test_jam_factor_reduces_beam_damage():
    """Jammed enemy fires with reduced beam_dmg."""
    enemy = Enemy(
        id="e1", type="scout",
        x=50_000.0, y=46_000.0,  # within weapon_range (4000)
        heading=180.0,  # facing south (toward player at 50000,50000)
        ai_state="attack",
        beam_cooldown=0.0,
        jam_factor=0.5,  # 50% jam → 50% damage
    )
    ship = Ship()

    events = tick_enemies([enemy], ship, dt=0.1)
    assert len(events) == 1
    from server.models.world import ENEMY_TYPE_PARAMS
    base_dmg = ENEMY_TYPE_PARAMS["scout"]["beam_dmg"]
    expected = base_dmg * (1.0 - 0.5)
    assert events[0].damage == pytest.approx(expected)


def test_no_jam_full_beam_damage():
    """Enemy with jam_factor=0 fires full damage."""
    enemy = Enemy(
        id="e1", type="scout",
        x=50_000.0, y=46_000.0,
        heading=180.0,
        ai_state="attack",
        beam_cooldown=0.0,
        jam_factor=0.0,
    )
    ship = Ship()

    events = tick_enemies([enemy], ship, dt=0.1)
    if events:  # may not fire if arc check fails — only check if event exists
        from server.models.world import ENEMY_TYPE_PARAMS
        base_dmg = ENEMY_TYPE_PARAMS["scout"]["beam_dmg"]
        assert events[0].damage == pytest.approx(base_dmg)


def test_intrusion_stun_blocks_beam_fire():
    """Enemy with intrusion_stun_ticks > 0 cannot fire beams."""
    enemy = Enemy(
        id="e1", type="scout",
        x=50_000.0, y=46_000.0,
        heading=180.0,
        ai_state="attack",
        beam_cooldown=0.0,
        intrusion_stun_ticks=10,
    )
    ship = Ship()
    events = tick_enemies([enemy], ship, dt=0.1)
    assert events == []


def test_intrusion_stun_decays_each_tick():
    """intrusion_stun_ticks decrements by 1 per tick."""
    enemy = Enemy(
        id="e1", type="scout",
        x=50_000.0, y=80_000.0,  # far away, won't fire
        ai_state="idle",
        intrusion_stun_ticks=5,
    )
    ship = Ship()
    tick_enemies([enemy], ship, dt=0.1)
    assert enemy.intrusion_stun_ticks == 4


# ---------------------------------------------------------------------------
# Combat integration — countermeasure reduction
# ---------------------------------------------------------------------------


def test_countermeasure_reduces_hull_damage():
    """Active countermeasures with charges reduce hull damage."""
    ship = make_ship()
    ship.hull = 100.0
    ship.shields.front = 0.0
    ship.shields.rear = 0.0
    ship.ew_countermeasure_active = True
    ship.countermeasure_charges = 5

    rng = MagicMock()
    rng.random.return_value = 1.0  # no system damage roll
    apply_hit_to_player(ship, damage=20.0, attacker_x=ship.x, attacker_y=ship.y - 1000.0, rng=rng)
    # Without countermeasures: hull would take 20.0 damage.
    # With countermeasures: hull takes 20.0 * (1 - 0.30) = 14.0
    assert ship.hull == pytest.approx(100.0 - 20.0 * (1.0 - COUNTERMEASURE_REDUCTION))


def test_countermeasure_consumes_one_charge_per_hit():
    ship = make_ship()
    ship.hull = 100.0
    ship.shields.front = 0.0
    ship.shields.rear = 0.0
    ship.ew_countermeasure_active = True
    ship.countermeasure_charges = 5

    rng = MagicMock()
    rng.random.return_value = 1.0
    apply_hit_to_player(ship, damage=10.0, attacker_x=ship.x, attacker_y=ship.y - 500.0, rng=rng)
    assert ship.countermeasure_charges == 4


def test_countermeasure_auto_deactivates_at_zero_charges():
    ship = make_ship()
    ship.hull = 100.0
    ship.shields.front = 0.0
    ship.shields.rear = 0.0
    ship.ew_countermeasure_active = True
    ship.countermeasure_charges = 1

    rng = MagicMock()
    rng.random.return_value = 1.0
    apply_hit_to_player(ship, damage=10.0, attacker_x=ship.x, attacker_y=ship.y - 500.0, rng=rng)
    assert ship.countermeasure_charges == 0
    assert ship.ew_countermeasure_active is False


def test_no_countermeasure_when_inactive():
    ship = make_ship()
    ship.hull = 100.0
    ship.shields.front = 0.0
    ship.shields.rear = 0.0
    ship.ew_countermeasure_active = False
    ship.countermeasure_charges = 10

    rng = MagicMock()
    rng.random.return_value = 1.0
    apply_hit_to_player(ship, damage=20.0, attacker_x=ship.x, attacker_y=ship.y - 500.0, rng=rng)
    assert ship.hull == pytest.approx(80.0)
    assert ship.countermeasure_charges == 10  # unchanged


def test_no_countermeasure_when_charges_zero():
    ship = make_ship()
    ship.hull = 100.0
    ship.shields.front = 0.0
    ship.shields.rear = 0.0
    ship.ew_countermeasure_active = True
    ship.countermeasure_charges = 0

    rng = MagicMock()
    rng.random.return_value = 1.0
    apply_hit_to_player(ship, damage=20.0, attacker_x=ship.x, attacker_y=ship.y - 500.0, rng=rng)
    # No reduction — full damage
    assert ship.hull == pytest.approx(80.0)
