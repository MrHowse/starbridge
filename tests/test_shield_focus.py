"""Tests for the 2D shield focus system.

Covers:
  calculate_shield_distribution — geometry, sum=1, clamping
  get_hit_facing — 8-direction tests + boundary cases
  apply_hit_to_player — per-facing depletion, others unchanged
  regenerate_shields — per-facing cap based on distribution
  weapons.set_shield_focus — valid/invalid payloads
  save round-trip — shield_focus + shield_distribution preserved
"""
from __future__ import annotations

import asyncio

import pytest

from server import weapons as weapons_handler
from server.models.messages import Message
from server.models.ship import Ship, Shields, TOTAL_SHIELD_CAPACITY, calculate_shield_distribution
from server.systems.combat import (
    SHIELD_REGEN_PER_TICK,
    apply_hit_to_player,
    get_hit_facing,
    regenerate_shields,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ship(x: float = 0.0, y: float = 0.0, heading: float = 0.0) -> Ship:
    s = Ship()
    s.x = x
    s.y = y
    s.heading = heading
    return s


# ---------------------------------------------------------------------------
# calculate_shield_distribution
# ---------------------------------------------------------------------------


def test_centre_distribution_all_equal():
    d = calculate_shield_distribution(0.0, 0.0)
    assert d["fore"]      == pytest.approx(0.25)
    assert d["aft"]       == pytest.approx(0.25)
    assert d["port"]      == pytest.approx(0.25)
    assert d["starboard"] == pytest.approx(0.25)


def test_centre_distribution_sums_to_one():
    d = calculate_shield_distribution(0.0, 0.0)
    assert sum(d.values()) == pytest.approx(1.0)


def test_full_fore_focus():
    d = calculate_shield_distribution(0.0, 1.0)
    assert d["fore"] > d["aft"]
    assert sum(d.values()) == pytest.approx(1.0)
    # fore should be largest, aft smallest
    assert d["fore"] == pytest.approx(0.5)
    assert d["aft"]  == pytest.approx(0.0, abs=1e-9)


def test_full_aft_focus():
    d = calculate_shield_distribution(0.0, -1.0)
    assert d["aft"] > d["fore"]
    assert sum(d.values()) == pytest.approx(1.0)


def test_full_starboard_focus():
    d = calculate_shield_distribution(1.0, 0.0)
    assert d["starboard"] > d["port"]
    assert sum(d.values()) == pytest.approx(1.0)


def test_full_port_focus():
    d = calculate_shield_distribution(-1.0, 0.0)
    assert d["port"] > d["starboard"]
    assert sum(d.values()) == pytest.approx(1.0)


def test_diagonal_focus_sums_to_one():
    d = calculate_shield_distribution(1.0, 1.0)
    assert sum(d.values()) == pytest.approx(1.0)
    # fore and starboard should be dominant
    assert d["fore"] > d["aft"]
    assert d["starboard"] > d["port"]


def test_partial_focus_sums_to_one():
    d = calculate_shield_distribution(0.3, -0.7)
    assert sum(d.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# get_hit_facing
# ---------------------------------------------------------------------------


def test_facing_fore_north():
    # Ship at origin, heading 0° (N). Attacker due north → bearing 0° → fore.
    assert get_hit_facing(0.0, 0.0, 0.0, 0.0, -1000.0) == "fore"


def test_facing_aft_south():
    # Ship heading 0°. Attacker due south → bearing 180° → aft.
    assert get_hit_facing(0.0, 0.0, 0.0, 0.0, 1000.0) == "aft"


def test_facing_starboard_east():
    # Ship heading 0°. Attacker due east → bearing 90° → diff=90° → 45<90<135 → starboard.
    assert get_hit_facing(0.0, 0.0, 0.0, 1000.0, 0.0) == "starboard"


def test_facing_port_west():
    # Ship heading 0°. Attacker due west → bearing 270° → diff=-90° → port.
    assert get_hit_facing(0.0, 0.0, 0.0, -1000.0, 0.0) == "port"


def test_facing_fore_northeast():
    # NE of ship → bearing ~45° → diff=45° → exactly at boundary → fore.
    assert get_hit_facing(0.0, 0.0, 0.0, 707.0, -707.0) == "fore"


def test_facing_starboard_southeast():
    # SE of ship → bearing ~135° → diff=135° → exactly at aft boundary → aft.
    result = get_hit_facing(0.0, 0.0, 0.0, 707.0, 707.0)
    assert result == "aft"


def test_facing_port_northwest():
    # NW of ship → bearing ~315° → diff=-45° → fore (abs=45).
    assert get_hit_facing(0.0, 0.0, 0.0, -707.0, -707.0) == "fore"


def test_facing_aft_southwest():
    # SW of ship → bearing ~225° → diff=-135° → aft (abs=135).
    assert get_hit_facing(0.0, 0.0, 0.0, -707.0, 707.0) == "aft"


def test_facing_respects_ship_heading():
    # Ship heading 90° (east). Attacker due east of ship → bearing 90° → diff=0 → fore.
    assert get_hit_facing(90.0, 0.0, 0.0, 1000.0, 0.0) == "fore"


# ---------------------------------------------------------------------------
# apply_hit_to_player — per-facing
# ---------------------------------------------------------------------------


def test_fore_hit_depletes_only_fore():
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    initial = {f: getattr(ship.shields, f) for f in ("fore", "aft", "port", "starboard")}
    apply_hit_to_player(ship, 10.0, 0.0, -1000.0)  # attacker north → fore
    assert ship.shields.fore < initial["fore"]
    assert ship.shields.aft       == initial["aft"]
    assert ship.shields.port      == initial["port"]
    assert ship.shields.starboard == initial["starboard"]


def test_aft_hit_depletes_only_aft():
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    initial = {f: getattr(ship.shields, f) for f in ("fore", "aft", "port", "starboard")}
    apply_hit_to_player(ship, 10.0, 0.0, 1000.0)   # attacker south → aft
    assert ship.shields.aft < initial["aft"]
    assert ship.shields.fore      == initial["fore"]
    assert ship.shields.port      == initial["port"]
    assert ship.shields.starboard == initial["starboard"]


def test_port_hit_depletes_only_port():
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    initial = {f: getattr(ship.shields, f) for f in ("fore", "aft", "port", "starboard")}
    apply_hit_to_player(ship, 10.0, -1000.0, 0.0)  # attacker west → port
    assert ship.shields.port < initial["port"]
    assert ship.shields.fore      == initial["fore"]
    assert ship.shields.aft       == initial["aft"]
    assert ship.shields.starboard == initial["starboard"]


def test_starboard_hit_depletes_only_starboard():
    ship = make_ship(x=0.0, y=0.0, heading=0.0)
    initial = {f: getattr(ship.shields, f) for f in ("fore", "aft", "port", "starboard")}
    apply_hit_to_player(ship, 10.0, 1000.0, 0.0)   # attacker east → starboard
    assert ship.shields.starboard < initial["starboard"]
    assert ship.shields.fore == initial["fore"]
    assert ship.shields.aft  == initial["aft"]
    assert ship.shields.port == initial["port"]


# ---------------------------------------------------------------------------
# regenerate_shields — per-facing cap
# ---------------------------------------------------------------------------


def test_regen_centred_caps_at_50():
    ship = make_ship()
    cap = TOTAL_SHIELD_CAPACITY * 0.25  # 50.0
    ship.shields.fore = cap - 0.1
    ship.systems["shields"].power = 100.0
    ship.systems["shields"].health = 100.0

    regenerate_shields(ship)

    assert ship.shields.fore == pytest.approx(cap)


def test_regen_fore_biased_cap():
    # Focus full fore: distribution fore≈0.5, aft≈0.0
    ship = make_ship()
    ship.shield_distribution = calculate_shield_distribution(0.0, 1.0)
    fore_max = TOTAL_SHIELD_CAPACITY * ship.shield_distribution["fore"]  # ~100
    # Start just below the cap so a single regen tick would overshoot without capping.
    ship.shields.fore = fore_max - 0.1
    ship.systems["shields"].power = 100.0
    ship.systems["shields"].health = 100.0

    regenerate_shields(ship)

    assert ship.shields.fore == pytest.approx(fore_max)


def test_regen_does_not_exceed_cap():
    ship = make_ship()
    cap = TOTAL_SHIELD_CAPACITY * 0.25
    ship.shields.fore = cap  # already at max
    ship.systems["shields"].power = 100.0
    ship.systems["shields"].health = 100.0

    regenerate_shields(ship)

    assert ship.shields.fore == pytest.approx(cap)


# ---------------------------------------------------------------------------
# weapons.set_shield_focus — handler tests
# ---------------------------------------------------------------------------


class MockSender:
    def __init__(self) -> None:
        self.sent: list = []

    async def send(self, connection_id: str, message) -> None:
        self.sent.append(message)


def fresh_handler():
    """Create a fresh weapons handler with a real asyncio queue."""
    sender = MockSender()
    queue: asyncio.Queue = asyncio.Queue()
    weapons_handler.init(sender, queue)
    return sender, queue


async def test_set_shield_focus_valid_enqueues():
    _, queue = fresh_handler()
    msg = Message.build("weapons.set_shield_focus", {"x": 0.5, "y": -0.3})
    await weapons_handler.handle_weapons_message("conn1", msg)
    assert queue.qsize() == 1
    msg_type, payload = await queue.get()
    assert msg_type == "weapons.set_shield_focus"
    assert payload.x == pytest.approx(0.5)
    assert payload.y == pytest.approx(-0.3)


async def test_set_shield_focus_x_out_of_range():
    sender, queue = fresh_handler()
    msg = Message.build("weapons.set_shield_focus", {"x": 1.5, "y": 0.0})
    await weapons_handler.handle_weapons_message("conn1", msg)
    assert queue.empty()
    assert sender.sent[0].type == "error.validation"


async def test_set_shield_focus_y_out_of_range():
    sender, queue = fresh_handler()
    msg = Message.build("weapons.set_shield_focus", {"x": 0.0, "y": -2.0})
    await weapons_handler.handle_weapons_message("conn1", msg)
    assert queue.empty()
    assert sender.sent[0].type == "error.validation"


# ---------------------------------------------------------------------------
# Save round-trip — shield_focus + shield_distribution preserved
# ---------------------------------------------------------------------------


def test_shield_focus_save_round_trip():
    """shield_focus and shield_distribution survive serialise/deserialise."""
    import json
    from server.save_system import _serialise_ship, _deserialise_ship

    ship = make_ship()
    ship.shield_focus        = {"x": 0.7, "y": -0.3}
    ship.shield_distribution = calculate_shield_distribution(0.7, -0.3)
    ship.shields.fore      = 60.0
    ship.shields.aft       = 15.0
    ship.shields.port      = 40.0
    ship.shields.starboard = 55.0

    data = _serialise_ship(ship)
    # JSON round-trip to simulate real save/load.
    data = json.loads(json.dumps(data))

    ship2 = make_ship()
    _deserialise_ship(data, ship2)

    assert ship2.shield_focus["x"]              == pytest.approx(0.7)
    assert ship2.shield_focus["y"]              == pytest.approx(-0.3)
    assert ship2.shield_distribution["fore"]    == pytest.approx(ship.shield_distribution["fore"])
    assert ship2.shield_distribution["aft"]     == pytest.approx(ship.shield_distribution["aft"])
    assert ship2.shield_distribution["port"]    == pytest.approx(ship.shield_distribution["port"])
    assert ship2.shield_distribution["starboard"] == pytest.approx(ship.shield_distribution["starboard"])
    assert ship2.shields.fore      == pytest.approx(60.0)
    assert ship2.shields.aft       == pytest.approx(15.0)
    assert ship2.shields.port      == pytest.approx(40.0)
    assert ship2.shields.starboard == pytest.approx(55.0)
