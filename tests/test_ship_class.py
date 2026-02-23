"""Tests for server.models.ship_class — ShipClass loader and list."""
from __future__ import annotations

import pytest

from server.models.ship_class import (
    ShipClass,
    load_ship_class,
    list_ship_classes,
    SHIP_CLASS_ORDER,
)


# ---------------------------------------------------------------------------
# load_ship_class
# ---------------------------------------------------------------------------


def test_load_frigate_returns_ship_class():
    sc = load_ship_class("frigate")
    assert isinstance(sc, ShipClass)
    assert sc.id == "frigate"


def test_load_frigate_has_correct_hull():
    sc = load_ship_class("frigate")
    assert sc.max_hull == 100.0


def test_load_scout_has_lower_hull_than_frigate():
    scout   = load_ship_class("scout")
    frigate = load_ship_class("frigate")
    assert scout.max_hull < frigate.max_hull


def test_load_battleship_has_highest_hull():
    battleship = load_ship_class("battleship")
    for cid in SHIP_CLASS_ORDER:
        other = load_ship_class(cid)
        assert battleship.max_hull >= other.max_hull


def test_load_all_classes_have_positive_ammo():
    for cid in SHIP_CLASS_ORDER:
        sc = load_ship_class(cid)
        assert sc.torpedo_ammo > 0, f"{cid} has non-positive torpedo_ammo"


def test_load_all_classes_have_name_and_description():
    for cid in SHIP_CLASS_ORDER:
        sc = load_ship_class(cid)
        assert sc.name, f"{cid} has empty name"
        assert sc.description, f"{cid} has empty description"


def test_load_unknown_class_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_ship_class("dreadnought")


# ---------------------------------------------------------------------------
# list_ship_classes
# ---------------------------------------------------------------------------


def test_list_returns_all_classes():
    # Now 7 classes (5 combat + 2 specialised: medical_ship, carrier).
    classes = list_ship_classes()
    assert len(classes) == 7


def test_list_order_is_canonical():
    classes = list_ship_classes()
    ids = [sc.id for sc in classes]
    assert ids == SHIP_CLASS_ORDER


def test_combat_hull_increases_through_order():
    # Core combat ship line is strictly increasing in hull.
    combat_ids = ["scout", "corvette", "frigate", "cruiser", "battleship"]
    hulls = [load_ship_class(cid).max_hull for cid in combat_ids]
    assert hulls == sorted(hulls), f"Combat hull values not monotonically increasing: {hulls}"


# ---------------------------------------------------------------------------
# Integration: game_loop applies ship class hull
# ---------------------------------------------------------------------------


import asyncio
from server import game_loop
from server.models.world import World


class MockManager:
    def __init__(self) -> None:
        self.broadcasts: list = []

    async def broadcast(self, msg: object) -> None:
        self.broadcasts.append(msg)

    async def broadcast_to_roles(self, roles: list[str], msg: object) -> None:
        self.broadcasts.append(msg)

    def get_by_role(self, role: str) -> list:
        return []


def fresh():
    manager = MockManager()
    world = World()
    queue: asyncio.Queue = asyncio.Queue()  # type: ignore[type-arg]
    game_loop.init(world, manager, queue)
    return manager, world, queue


@pytest.fixture(autouse=True)
async def stop_loop_after_test():
    yield
    await game_loop.stop()


async def test_game_loop_applies_scout_hull():
    _, world, _ = fresh()
    await game_loop.start("sandbox", ship_class="scout")
    assert world.ship.hull == 60.0


async def test_game_loop_applies_battleship_hull():
    _, world, _ = fresh()
    await game_loop.start("sandbox", ship_class="battleship")
    assert world.ship.hull == 200.0


async def test_game_loop_unknown_ship_class_defaults_to_frigate():
    _, world, _ = fresh()
    await game_loop.start("sandbox", ship_class="xyzzy")
    # Falls back to frigate hull (100).
    assert world.ship.hull == 100.0
