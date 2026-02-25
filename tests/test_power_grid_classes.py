"""Tests for v0.07 per-class power grids (spec §1.4).

Covers:
  - Per-class JSON power grid values match spec
  - PowerGrid.from_ship_class initialises correctly
  - game_loop.start wires class power grid into engineering
  - Reactor output spread (5x between scout and battleship)
  - Battery capacity spread
  - Emergency reserve values
  - Default frigate matches existing defaults
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from server.models.ship_class import load_ship_class, SHIP_CLASS_ORDER
from server.models.power_grid import PowerGrid


# ---------------------------------------------------------------------------
# 1. Per-class power grid values from spec (§1.4.X)
# ---------------------------------------------------------------------------


class TestScoutPowerGrid:
    def test_reactor_max(self):
        sc = load_ship_class("scout")
        assert sc.power_grid["reactor_max"] == 300

    def test_battery_capacity(self):
        sc = load_ship_class("scout")
        assert sc.power_grid["battery_capacity"] == 150

    def test_battery_charge_rate(self):
        sc = load_ship_class("scout")
        assert sc.power_grid["battery_charge_rate"] == 30

    def test_battery_discharge_rate(self):
        sc = load_ship_class("scout")
        assert sc.power_grid["battery_discharge_rate"] == 60

    def test_emergency_reserve(self):
        sc = load_ship_class("scout")
        assert sc.power_grid["emergency_reserve"] == 60


class TestCorvettePowerGrid:
    def test_reactor_max(self):
        sc = load_ship_class("corvette")
        assert sc.power_grid["reactor_max"] == 450

    def test_battery_capacity(self):
        sc = load_ship_class("corvette")
        assert sc.power_grid["battery_capacity"] == 250

    def test_emergency_reserve(self):
        sc = load_ship_class("corvette")
        assert sc.power_grid["emergency_reserve"] == 80


class TestFrigatePowerGrid:
    def test_reactor_max(self):
        sc = load_ship_class("frigate")
        assert sc.power_grid["reactor_max"] == 700

    def test_battery_capacity(self):
        sc = load_ship_class("frigate")
        assert sc.power_grid["battery_capacity"] == 500

    def test_battery_charge_rate(self):
        sc = load_ship_class("frigate")
        assert sc.power_grid["battery_charge_rate"] == 50

    def test_battery_discharge_rate(self):
        sc = load_ship_class("frigate")
        assert sc.power_grid["battery_discharge_rate"] == 100

    def test_emergency_reserve(self):
        sc = load_ship_class("frigate")
        assert sc.power_grid["emergency_reserve"] == 100


class TestCruiserPowerGrid:
    def test_reactor_max(self):
        sc = load_ship_class("cruiser")
        assert sc.power_grid["reactor_max"] == 1000

    def test_battery_capacity(self):
        sc = load_ship_class("cruiser")
        assert sc.power_grid["battery_capacity"] == 750

    def test_emergency_reserve(self):
        sc = load_ship_class("cruiser")
        assert sc.power_grid["emergency_reserve"] == 150


class TestBattleshipPowerGrid:
    def test_reactor_max(self):
        sc = load_ship_class("battleship")
        assert sc.power_grid["reactor_max"] == 1500

    def test_battery_capacity(self):
        sc = load_ship_class("battleship")
        assert sc.power_grid["battery_capacity"] == 1200

    def test_battery_charge_rate(self):
        sc = load_ship_class("battleship")
        assert sc.power_grid["battery_charge_rate"] == 100

    def test_battery_discharge_rate(self):
        sc = load_ship_class("battleship")
        assert sc.power_grid["battery_discharge_rate"] == 200

    def test_emergency_reserve(self):
        sc = load_ship_class("battleship")
        assert sc.power_grid["emergency_reserve"] == 250


class TestCarrierPowerGrid:
    def test_reactor_max(self):
        sc = load_ship_class("carrier")
        assert sc.power_grid["reactor_max"] == 900

    def test_battery_capacity(self):
        sc = load_ship_class("carrier")
        assert sc.power_grid["battery_capacity"] == 800

    def test_emergency_reserve(self):
        sc = load_ship_class("carrier")
        assert sc.power_grid["emergency_reserve"] == 120


class TestMedicalShipPowerGrid:
    def test_reactor_max(self):
        sc = load_ship_class("medical_ship")
        assert sc.power_grid["reactor_max"] == 500

    def test_battery_capacity(self):
        """Medical ship has oversized battery for emergencies."""
        sc = load_ship_class("medical_ship")
        assert sc.power_grid["battery_capacity"] == 600

    def test_emergency_reserve(self):
        """Medical ship has oversized emergency reserve."""
        sc = load_ship_class("medical_ship")
        assert sc.power_grid["emergency_reserve"] == 150


# ---------------------------------------------------------------------------
# 2. PowerGrid.from_ship_class initialisation
# ---------------------------------------------------------------------------


class TestPowerGridFromShipClass:
    def test_from_scout_config(self):
        sc = load_ship_class("scout")
        pg = PowerGrid.from_ship_class(sc.power_grid)
        assert pg.reactor_max == 300.0
        assert pg.battery_capacity == 150.0
        assert pg.battery_charge_rate == 30.0
        assert pg.battery_discharge_rate == 60.0
        assert pg.emergency_reserve == 60.0

    def test_battery_starts_at_half(self):
        sc = load_ship_class("scout")
        pg = PowerGrid.from_ship_class(sc.power_grid)
        assert pg.battery_charge == pytest.approx(75.0)  # 150 / 2

    def test_from_battleship_config(self):
        sc = load_ship_class("battleship")
        pg = PowerGrid.from_ship_class(sc.power_grid)
        assert pg.reactor_max == 1500.0
        assert pg.battery_capacity == 1200.0
        assert pg.battery_charge == pytest.approx(600.0)  # 1200 / 2

    def test_all_classes_produce_valid_power_grid(self):
        for cid in SHIP_CLASS_ORDER:
            sc = load_ship_class(cid)
            assert sc.power_grid is not None, f"{cid} missing power_grid"
            pg = PowerGrid.from_ship_class(sc.power_grid)
            assert pg.reactor_max > 0, f"{cid} has zero reactor"
            assert pg.battery_capacity > 0, f"{cid} has zero battery"
            assert pg.emergency_reserve > 0, f"{cid} has zero emergency"


# ---------------------------------------------------------------------------
# 3. Spread / balance properties
# ---------------------------------------------------------------------------


class TestPowerGridSpread:
    def test_reactor_spread_at_least_3x(self):
        """Battleship reactor (1500) vs scout (300) = 5x spread."""
        reactors = [load_ship_class(cid).power_grid["reactor_max"]
                    for cid in SHIP_CLASS_ORDER]
        ratio = max(reactors) / min(reactors)
        assert ratio >= 3.0

    def test_battery_spread_at_least_3x(self):
        batteries = [load_ship_class(cid).power_grid["battery_capacity"]
                     for cid in SHIP_CLASS_ORDER]
        ratio = max(batteries) / min(batteries)
        assert ratio >= 3.0

    def test_combat_line_reactor_increases(self):
        """Scout → corvette → frigate → cruiser → battleship reactor increases."""
        combat_ids = ["scout", "corvette", "frigate", "cruiser", "battleship"]
        reactors = [load_ship_class(cid).power_grid["reactor_max"]
                    for cid in combat_ids]
        assert reactors == sorted(reactors)

    def test_combat_line_battery_increases(self):
        combat_ids = ["scout", "corvette", "frigate", "cruiser", "battleship"]
        batteries = [load_ship_class(cid).power_grid["battery_capacity"]
                     for cid in combat_ids]
        assert batteries == sorted(batteries)

    def test_no_class_has_zero_reactor(self):
        for cid in SHIP_CLASS_ORDER:
            sc = load_ship_class(cid)
            assert sc.power_grid["reactor_max"] > 0


# ---------------------------------------------------------------------------
# 4. game_loop wires class power grid (integration)
# ---------------------------------------------------------------------------


from server import game_loop
from server.models.world import World
import server.game_loop_engineering as gle


class MockManager:
    def __init__(self):
        self.broadcasts = []

    async def broadcast(self, msg):
        self.broadcasts.append(msg)

    async def broadcast_to_roles(self, roles, msg):
        self.broadcasts.append(msg)

    def get_by_role(self, role):
        return []


def fresh():
    manager = MockManager()
    world = World()
    queue: asyncio.Queue = asyncio.Queue()
    game_loop.init(world, manager, queue)
    return manager, world, queue


@pytest.fixture(autouse=True)
async def stop_loop_after_test():
    yield
    await game_loop.stop()


async def test_game_loop_wires_scout_power_grid():
    _, world, _ = fresh()
    await game_loop.start("sandbox", ship_class="scout")
    pg = gle.get_power_grid()
    assert pg is not None
    assert pg.reactor_max == 300.0


async def test_game_loop_wires_battleship_power_grid():
    _, world, _ = fresh()
    await game_loop.start("sandbox", ship_class="battleship")
    pg = gle.get_power_grid()
    assert pg is not None
    assert pg.reactor_max == 1500.0


async def test_game_loop_wires_frigate_power_grid():
    _, world, _ = fresh()
    await game_loop.start("sandbox", ship_class="frigate")
    pg = gle.get_power_grid()
    assert pg is not None
    assert pg.reactor_max == 700.0
    assert pg.battery_capacity == 500.0


async def test_game_loop_default_class_uses_frigate_grid():
    """Default ship class (frigate) should use frigate power grid."""
    _, world, _ = fresh()
    await game_loop.start("sandbox")
    pg = gle.get_power_grid()
    assert pg is not None
    assert pg.reactor_max == 700.0


# ---------------------------------------------------------------------------
# 5. Brownout occurs on scout at full power demand
# ---------------------------------------------------------------------------


class TestScoutBrownout:
    def test_scout_full_demand_exceeds_reactor(self):
        """Scout reactor (300) can't sustain 9 systems × 100 = 900 demand."""
        sc = load_ship_class("scout")
        pg = PowerGrid.from_ship_class(sc.power_grid)
        # All 9 systems at 100%
        demands = {
            "engines": 100, "beams": 100, "torpedoes": 100,
            "shields": 100, "sensors": 100, "manoeuvring": 100,
            "flight_deck": 100, "ecm_suite": 100, "point_defence": 100,
        }
        delivered = pg.tick(0.1, demands)
        total_delivered = sum(delivered.values())
        # Should be proportionally reduced (brownout)
        assert total_delivered < 900.0

    def test_battleship_handles_more_demand(self):
        """Battleship reactor (1500) can sustain 9×100=900 at full."""
        sc = load_ship_class("battleship")
        pg = PowerGrid.from_ship_class(sc.power_grid)
        demands = {
            "engines": 100, "beams": 100, "torpedoes": 100,
            "shields": 100, "sensors": 100, "manoeuvring": 100,
            "flight_deck": 100, "ecm_suite": 100, "point_defence": 100,
        }
        delivered = pg.tick(0.1, demands)
        total_delivered = sum(delivered.values())
        assert total_delivered == pytest.approx(900.0)
