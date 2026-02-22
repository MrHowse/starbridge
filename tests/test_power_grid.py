"""
Power Grid Model — unit tests.

Covers reactor output, battery modes, emergency power, bus routing,
brownout distribution, reroute mechanics, and serialisation.
"""
from __future__ import annotations

import pytest

from server.models.power_grid import (
    PowerGrid,
    PRIMARY_BUS_SYSTEMS,
    SECONDARY_BUS_SYSTEMS,
    ALL_BUS_SYSTEMS,
    DEFAULT_REACTOR_MAX,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_BATTERY_CHARGE_RATE,
    DEFAULT_BATTERY_DISCHARGE_RATE,
    DEFAULT_EMERGENCY_RESERVE,
    REROUTE_DURATION,
    BATTERY_MODES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_demands(level: float = 100.0) -> dict[str, float]:
    """Return demands for all 9 systems at the given level."""
    return {s: level for s in ALL_BUS_SYSTEMS}


def _primary_demands(level: float = 100.0) -> dict[str, float]:
    return {s: level for s in PRIMARY_BUS_SYSTEMS}


def _secondary_demands(level: float = 100.0) -> dict[str, float]:
    return {s: level for s in SECONDARY_BUS_SYSTEMS}


DT = 0.1  # standard 10 Hz tick


# ---------------------------------------------------------------------------
# Bus membership
# ---------------------------------------------------------------------------


class TestBusMembership:
    def test_primary_has_four_systems(self):
        assert len(PRIMARY_BUS_SYSTEMS) == 4

    def test_secondary_has_five_systems(self):
        assert len(SECONDARY_BUS_SYSTEMS) == 5

    def test_all_nine_systems(self):
        assert len(ALL_BUS_SYSTEMS) == 9

    def test_no_overlap(self):
        assert PRIMARY_BUS_SYSTEMS & SECONDARY_BUS_SYSTEMS == set()

    def test_primary_systems(self):
        for s in ("engines", "shields", "sensors", "manoeuvring"):
            assert s in PRIMARY_BUS_SYSTEMS

    def test_secondary_systems(self):
        for s in ("beams", "torpedoes", "flight_deck", "ecm_suite", "point_defence"):
            assert s in SECONDARY_BUS_SYSTEMS


# ---------------------------------------------------------------------------
# Reactor output
# ---------------------------------------------------------------------------


class TestReactorOutput:
    def test_full_health(self):
        pg = PowerGrid(reactor_max=700.0, reactor_health=100.0)
        assert pg.reactor_output == 700.0

    def test_half_health(self):
        pg = PowerGrid(reactor_max=700.0, reactor_health=50.0)
        assert pg.reactor_output == 350.0

    def test_zero_health(self):
        pg = PowerGrid(reactor_max=700.0, reactor_health=0.0)
        assert pg.reactor_output == 0.0

    def test_damage_reduces_health(self):
        pg = PowerGrid(reactor_health=100.0)
        pg.damage_reactor(30.0)
        assert pg.reactor_health == 70.0

    def test_damage_clamps_at_zero(self):
        pg = PowerGrid(reactor_health=10.0)
        pg.damage_reactor(50.0)
        assert pg.reactor_health == 0.0

    def test_repair_increases_health(self):
        pg = PowerGrid(reactor_health=50.0)
        pg.repair_reactor(20.0)
        assert pg.reactor_health == 70.0

    def test_repair_clamps_at_100(self):
        pg = PowerGrid(reactor_health=90.0)
        pg.repair_reactor(50.0)
        assert pg.reactor_health == 100.0


# ---------------------------------------------------------------------------
# Battery modes
# ---------------------------------------------------------------------------


class TestBatteryModes:
    def test_valid_modes(self):
        pg = PowerGrid()
        for mode in BATTERY_MODES:
            assert pg.set_battery_mode(mode) is True
            assert pg.battery_mode == mode

    def test_invalid_mode_rejected(self):
        pg = PowerGrid()
        assert pg.set_battery_mode("invalid") is False
        assert pg.battery_mode == "auto"  # unchanged

    def test_standby_no_change(self):
        pg = PowerGrid(battery_charge=250.0, battery_mode="standby")
        demands = _all_demands(50.0)
        pg.tick(DT, demands)
        assert pg.battery_charge == 250.0

    def test_charging_increases_charge(self):
        pg = PowerGrid(reactor_max=1000.0, battery_charge=100.0,
                       battery_mode="charging", battery_charge_rate=50.0)
        demands = _all_demands(50.0)  # 450 demand, 1000 reactor
        pg.tick(DT, demands)
        assert pg.battery_charge > 100.0

    def test_charging_capped_at_capacity(self):
        pg = PowerGrid(battery_charge=499.0, battery_capacity=500.0,
                       battery_mode="charging", battery_charge_rate=50.0,
                       reactor_max=1000.0)
        for _ in range(100):
            pg.tick(DT, _all_demands(50.0))
        assert pg.battery_charge == 500.0

    def test_discharging_decreases_charge(self):
        pg = PowerGrid(battery_charge=250.0, battery_mode="discharging",
                       battery_discharge_rate=100.0)
        pg.tick(DT, _all_demands(100.0))
        assert pg.battery_charge < 250.0

    def test_discharging_capped_at_zero(self):
        pg = PowerGrid(battery_charge=5.0, battery_mode="discharging",
                       battery_discharge_rate=100.0)
        for _ in range(100):
            pg.tick(DT, _all_demands(100.0))
        assert pg.battery_charge == 0.0

    def test_auto_discharges_when_deficit(self):
        # 9 systems × 100 = 900 demand, reactor = 700 → deficit
        pg = PowerGrid(reactor_max=700.0, battery_charge=250.0,
                       battery_mode="auto")
        pg.tick(DT, _all_demands(100.0))
        assert pg.battery_charge < 250.0

    def test_auto_charges_when_surplus(self):
        # 9 systems × 50 = 450 demand, reactor = 700 → surplus
        pg = PowerGrid(reactor_max=700.0, battery_charge=100.0,
                       battery_mode="auto", battery_capacity=500.0)
        pg.tick(DT, _all_demands(50.0))
        assert pg.battery_charge > 100.0

    def test_auto_no_charge_when_balanced(self):
        # Demand exactly equals reactor — no surplus, no deficit
        pg = PowerGrid(reactor_max=450.0, battery_charge=250.0,
                       battery_mode="auto")
        pg.tick(DT, _all_demands(50.0))
        assert pg.battery_charge == 250.0


# ---------------------------------------------------------------------------
# Emergency power
# ---------------------------------------------------------------------------


class TestEmergencyPower:
    def test_activates_when_reactor_offline(self):
        pg = PowerGrid(reactor_health=0.0, emergency_reserve=100.0,
                       battery_mode="standby")
        pg.tick(DT, _all_demands(10.0))
        assert pg.emergency_active is True

    def test_deactivates_when_reactor_online(self):
        pg = PowerGrid(reactor_health=100.0, emergency_reserve=100.0)
        pg.tick(DT, _all_demands(50.0))
        assert pg.emergency_active is False

    def test_provides_power_when_reactor_offline(self):
        pg = PowerGrid(reactor_health=0.0, emergency_reserve=200.0,
                       battery_mode="standby")
        # 2 systems × 100 = 200 demand, emergency = 200 → should deliver full
        demands = {"engines": 100.0, "shields": 100.0}
        result = pg.tick(DT, demands)
        assert result["engines"] == pytest.approx(100.0)
        assert result["shields"] == pytest.approx(100.0)

    def test_brownout_with_emergency(self):
        pg = PowerGrid(reactor_health=0.0, emergency_reserve=100.0,
                       battery_mode="standby")
        # 4 systems × 100 = 400 demand, emergency = 100 → brownout
        demands = _primary_demands(100.0)
        result = pg.tick(DT, demands)
        total = sum(result.values())
        assert total == pytest.approx(100.0)
        # Each system gets proportional share
        for val in result.values():
            assert val == pytest.approx(25.0)

    def test_zero_reserve_no_power(self):
        pg = PowerGrid(reactor_health=0.0, emergency_reserve=0.0,
                       battery_mode="standby")
        result = pg.tick(DT, {"engines": 100.0})
        assert result["engines"] == 0.0
        assert pg.emergency_active is False

    def test_battery_supplements_emergency(self):
        pg = PowerGrid(reactor_health=0.0, emergency_reserve=100.0,
                       battery_charge=250.0, battery_mode="discharging",
                       battery_discharge_rate=100.0)
        # emergency=100 + battery discharge=100 = 200 available
        demands = {"engines": 100.0, "shields": 100.0}
        result = pg.tick(DT, demands)
        assert result["engines"] == pytest.approx(100.0)
        assert result["shields"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Bus routing
# ---------------------------------------------------------------------------


class TestBusRouting:
    def test_both_online_all_powered(self):
        pg = PowerGrid(reactor_max=1000.0, battery_mode="standby")
        result = pg.tick(DT, _all_demands(100.0))
        for val in result.values():
            assert val == pytest.approx(100.0)

    def test_primary_offline_zeroes_primary(self):
        pg = PowerGrid(reactor_max=1000.0, battery_mode="standby")
        pg.set_bus_online("primary", False)
        result = pg.tick(DT, _all_demands(100.0))
        for s in PRIMARY_BUS_SYSTEMS:
            assert result[s] == 0.0
        for s in SECONDARY_BUS_SYSTEMS:
            assert result[s] == pytest.approx(100.0)

    def test_secondary_offline_zeroes_secondary(self):
        pg = PowerGrid(reactor_max=1000.0, battery_mode="standby")
        pg.set_bus_online("secondary", False)
        result = pg.tick(DT, _all_demands(100.0))
        for s in SECONDARY_BUS_SYSTEMS:
            assert result[s] == 0.0
        for s in PRIMARY_BUS_SYSTEMS:
            assert result[s] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Reroute
# ---------------------------------------------------------------------------


class TestReroute:
    def test_start_reroute(self):
        pg = PowerGrid()
        assert pg.start_reroute("primary") is True
        assert pg.reroute_active is True
        assert pg.reroute_timer == pytest.approx(REROUTE_DURATION)

    def test_cannot_double_reroute(self):
        pg = PowerGrid()
        pg.start_reroute("primary")
        assert pg.start_reroute("secondary") is False

    def test_invalid_bus_rejected(self):
        pg = PowerGrid()
        assert pg.start_reroute("invalid") is False
        assert pg.reroute_active is False

    def test_rerouting_systems_get_zero(self):
        pg = PowerGrid(reactor_max=1000.0, battery_mode="standby")
        pg.start_reroute("secondary")
        result = pg.tick(DT, _all_demands(100.0))
        for s in SECONDARY_BUS_SYSTEMS:
            assert result[s] == 0.0
        for s in PRIMARY_BUS_SYSTEMS:
            assert result[s] == pytest.approx(100.0)

    def test_reroute_completes_after_duration(self):
        pg = PowerGrid(reactor_max=1000.0, battery_mode="standby")
        assert pg.primary_bus_online is True
        pg.start_reroute("primary")
        # Tick for REROUTE_DURATION seconds
        ticks = int(REROUTE_DURATION / DT) + 1
        for _ in range(ticks):
            pg.tick(DT, _all_demands(100.0))
        assert pg.reroute_active is False
        # Primary bus should have toggled from True → False
        assert pg.primary_bus_online is False

    def test_reroute_toggles_bus(self):
        pg = PowerGrid()
        pg.set_bus_online("secondary", False)
        pg.start_reroute("secondary")
        ticks = int(REROUTE_DURATION / DT) + 1
        for _ in range(ticks):
            pg.tick(DT, _all_demands(50.0))
        # secondary was offline → reroute toggles to online
        assert pg.secondary_bus_online is True

    def test_reroute_timer_decrements(self):
        pg = PowerGrid()
        pg.start_reroute("primary")
        pg.tick(DT, _all_demands(50.0))
        assert pg.reroute_timer == pytest.approx(REROUTE_DURATION - DT, abs=0.01)


# ---------------------------------------------------------------------------
# Brownout
# ---------------------------------------------------------------------------


class TestBrownout:
    def test_no_brownout_when_sufficient(self):
        pg = PowerGrid(reactor_max=1000.0, battery_mode="standby")
        demands = _all_demands(100.0)  # 900 demand, 1000 available
        result = pg.tick(DT, demands)
        for val in result.values():
            assert val == pytest.approx(100.0)

    def test_brownout_proportional(self):
        pg = PowerGrid(reactor_max=450.0, battery_mode="standby")
        demands = _all_demands(100.0)  # 900 demand, 450 available → 0.5 scale
        result = pg.tick(DT, demands)
        for val in result.values():
            assert val == pytest.approx(50.0)

    def test_brownout_preserves_ratios(self):
        pg = PowerGrid(reactor_max=300.0, battery_mode="standby")
        demands = {"engines": 150.0, "beams": 50.0, "shields": 100.0}
        # total demand = 300, available = 300 → no brownout actually
        result = pg.tick(DT, demands)
        assert result["engines"] == pytest.approx(150.0)
        assert result["beams"] == pytest.approx(50.0)
        assert result["shields"] == pytest.approx(100.0)

    def test_brownout_with_unequal_demands(self):
        pg = PowerGrid(reactor_max=200.0, battery_mode="standby")
        demands = {"engines": 150.0, "beams": 50.0}  # total 200
        result = pg.tick(DT, demands)
        # 200 available / 200 demand = 1.0 → no brownout
        assert result["engines"] == pytest.approx(150.0)
        assert result["beams"] == pytest.approx(50.0)

    def test_severe_brownout(self):
        pg = PowerGrid(reactor_max=100.0, battery_mode="standby")
        demands = _all_demands(100.0)  # 900 demand, 100 available
        result = pg.tick(DT, demands)
        total = sum(result.values())
        assert total == pytest.approx(100.0)

    def test_zero_demand_no_error(self):
        pg = PowerGrid()
        result = pg.tick(DT, {})
        assert result == {}

    def test_negative_demand_clamped(self):
        pg = PowerGrid(reactor_max=1000.0, battery_mode="standby")
        result = pg.tick(DT, {"engines": -50.0})
        assert result["engines"] == 0.0

    def test_zero_dt_all_zero(self):
        pg = PowerGrid()
        result = pg.tick(0.0, _all_demands(100.0))
        for val in result.values():
            assert val == 0.0


# ---------------------------------------------------------------------------
# Serialise / Deserialise
# ---------------------------------------------------------------------------


class TestSerialisation:
    def test_round_trip(self):
        pg = PowerGrid(
            reactor_max=800.0, reactor_health=75.5,
            battery_capacity=600.0, battery_charge=300.0,
            battery_charge_rate=60.0, battery_discharge_rate=120.0,
            battery_mode="discharging",
            emergency_reserve=150.0, emergency_active=True,
            primary_bus_online=False, secondary_bus_online=True,
            reroute_active=True, reroute_timer=5.5,
            reroute_target_bus="primary",
        )
        data = pg.serialise()
        restored = PowerGrid.deserialise(data)

        assert restored.reactor_max == 800.0
        assert restored.reactor_health == 75.5
        assert restored.battery_capacity == 600.0
        assert restored.battery_charge == 300.0
        assert restored.battery_charge_rate == 60.0
        assert restored.battery_discharge_rate == 120.0
        assert restored.battery_mode == "discharging"
        assert restored.emergency_reserve == 150.0
        assert restored.emergency_active is True
        assert restored.primary_bus_online is False
        assert restored.secondary_bus_online is True
        assert restored.reroute_active is True
        assert restored.reroute_timer == 5.5
        assert restored.reroute_target_bus == "primary"

    def test_deserialise_defaults(self):
        restored = PowerGrid.deserialise({})
        assert restored.reactor_max == DEFAULT_REACTOR_MAX
        assert restored.reactor_health == 100.0
        assert restored.battery_mode == "auto"
        assert restored.primary_bus_online is True

    def test_serialise_rounds_floats(self):
        pg = PowerGrid(reactor_health=33.333333, battery_charge=111.111111)
        data = pg.serialise()
        assert data["reactor_health"] == 33.33
        assert data["battery_charge"] == 111.11


# ---------------------------------------------------------------------------
# from_ship_class
# ---------------------------------------------------------------------------


class TestFromShipClass:
    def test_creates_from_config(self):
        config = {
            "reactor_max": 700,
            "battery_capacity": 500,
            "battery_charge_rate": 50,
            "battery_discharge_rate": 100,
            "emergency_reserve": 100,
        }
        pg = PowerGrid.from_ship_class(config)
        assert pg.reactor_max == 700.0
        assert pg.battery_capacity == 500.0
        assert pg.battery_charge == 250.0  # starts at 50%
        assert pg.battery_charge_rate == 50.0
        assert pg.battery_discharge_rate == 100.0
        assert pg.emergency_reserve == 100.0

    def test_defaults_for_missing_keys(self):
        pg = PowerGrid.from_ship_class({})
        assert pg.reactor_max == DEFAULT_REACTOR_MAX
        assert pg.battery_capacity == DEFAULT_BATTERY_CAPACITY
        assert pg.battery_charge == DEFAULT_BATTERY_CAPACITY / 2.0

    def test_battery_starts_half(self):
        pg = PowerGrid.from_ship_class({"battery_capacity": 800})
        assert pg.battery_charge == 400.0

    def test_full_health_at_start(self):
        pg = PowerGrid.from_ship_class({"reactor_max": 500})
        assert pg.reactor_health == 100.0
        assert pg.reactor_output == 500.0


# ---------------------------------------------------------------------------
# get_available_budget
# ---------------------------------------------------------------------------


class TestAvailableBudget:
    def test_full_reactor_standby(self):
        pg = PowerGrid(reactor_max=700.0, battery_mode="standby")
        assert pg.get_available_budget() == 700.0

    def test_damaged_reactor(self):
        pg = PowerGrid(reactor_max=700.0, reactor_health=50.0,
                       battery_mode="standby")
        assert pg.get_available_budget() == 350.0

    def test_discharging_adds_rate(self):
        pg = PowerGrid(reactor_max=700.0, battery_mode="discharging",
                       battery_charge=100.0, battery_discharge_rate=100.0)
        assert pg.get_available_budget() == 800.0

    def test_charging_subtracts_rate(self):
        pg = PowerGrid(reactor_max=700.0, battery_mode="charging",
                       battery_charge_rate=50.0)
        assert pg.get_available_budget() == 650.0

    def test_reactor_offline_emergency(self):
        pg = PowerGrid(reactor_health=0.0, emergency_reserve=100.0,
                       battery_mode="standby")
        assert pg.get_available_budget() == 100.0

    def test_empty_battery_no_discharge(self):
        pg = PowerGrid(reactor_max=700.0, battery_mode="discharging",
                       battery_charge=0.0)
        assert pg.get_available_budget() == 700.0
