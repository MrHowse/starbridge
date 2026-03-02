"""
Engineering Game Loop Module — unit tests.

Covers init/reset, power distribution via PowerGrid, overclock damage
through DamageModel, repair teams, health sync, player commands,
build_state, and serialisation round-trips.
"""
from __future__ import annotations

import random

import pytest

from server.models.damage_model import COMPONENT_SPECS
from server.models.interior import ShipInterior, make_default_interior
from server.models.power_grid import ALL_BUS_SYSTEMS
from server.models.repair_teams import SYSTEM_ROOMS
from server.models.ship import Ship

import server.game_loop_engineering as gle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ship() -> Ship:
    return Ship()


def _interior() -> ShipInterior:
    return make_default_interior()


def _crew_ids(n: int = 9) -> list[str]:
    return [f"crew_{i}" for i in range(n)]


@pytest.fixture(autouse=True)
def reset_module():
    """Reset module state between tests."""
    gle.reset()
    yield
    gle.reset()


# ---------------------------------------------------------------------------
# Init and reset
# ---------------------------------------------------------------------------


class TestInitReset:
    def test_reset_clears_state(self):
        ship = _ship()
        gle.init(ship, _crew_ids())
        assert gle.get_power_grid() is not None
        gle.reset()
        assert gle.get_power_grid() is None
        assert gle.get_damage_model() is None
        assert gle.get_repair_manager() is None

    def test_init_creates_all_subsystems(self):
        ship = _ship()
        gle.init(ship, _crew_ids())
        assert gle.get_power_grid() is not None
        assert gle.get_damage_model() is not None
        assert gle.get_repair_manager() is not None

    def test_init_seeds_requested_power_from_ship(self):
        ship = _ship()
        ship.systems["engines"].power = 120.0
        gle.init(ship, _crew_ids())
        # After init, requested power should match ship state
        assert gle._requested_power["engines"] == 120.0

    def test_init_with_power_grid_config(self):
        ship = _ship()
        config = {"reactor_max": 800.0, "battery_capacity": 600.0}
        gle.init(ship, _crew_ids(), power_grid_config=config)
        pg = gle.get_power_grid()
        assert pg is not None
        assert pg.reactor_max == 800.0
        assert pg.battery_capacity == 600.0

    def test_init_without_crew(self):
        ship = _ship()
        gle.init(ship)
        mgr = gle.get_repair_manager()
        assert mgr is not None
        assert len(mgr.teams) == 0

    def test_init_with_crew_creates_teams(self):
        ship = _ship()
        gle.init(ship, _crew_ids(9))
        mgr = gle.get_repair_manager()
        assert mgr is not None
        assert len(mgr.teams) == 3  # 9 crew / 3 per team


# ---------------------------------------------------------------------------
# Power distribution
# ---------------------------------------------------------------------------


class TestPowerDistribution:
    def test_tick_delivers_requested_power(self):
        ship = _ship()
        gle.init(ship, _crew_ids())
        # Set all systems low so total is within reactor budget (700)
        for sys_name in ALL_BUS_SYSTEMS:
            gle.set_power(sys_name, 50.0)
        gle.set_power("engines", 80.0)
        # Total: 8*50 + 80 = 480, well within 700 reactor
        result = gle.tick(ship, _interior(), 0.1)
        assert ship.systems["engines"].power == pytest.approx(80.0)

    def test_tick_delivers_to_all_systems(self):
        ship = _ship()
        gle.init(ship)
        result = gle.tick(ship, _interior(), 0.1)
        # All systems should have power values in delivered
        for sys_name in ALL_BUS_SYSTEMS:
            assert sys_name in result.power_delivered

    def test_set_power_clamps_range(self):
        ship = _ship()
        gle.init(ship)
        gle.set_power("engines", 200.0)
        assert gle._requested_power["engines"] == 150.0
        gle.set_power("engines", -10.0)
        assert gle._requested_power["engines"] == 0.0

    def test_set_power_ignores_invalid_system(self):
        ship = _ship()
        gle.init(ship)
        gle.set_power("warp_core", 100.0)
        assert "warp_core" not in gle._requested_power

    def test_brownout_reduces_power(self):
        ship = _ship()
        # Use a low reactor to force brownout
        gle.init(ship, power_grid_config={"reactor_max": 200.0})
        # Request way more than reactor can deliver
        for sys_name in ALL_BUS_SYSTEMS:
            gle.set_power(sys_name, 100.0)
        result = gle.tick(ship, _interior(), 0.1)
        # Total delivered should not exceed available budget
        total = sum(result.power_delivered.values())
        pg = gle.get_power_grid()
        assert pg is not None
        # Allow some margin for battery contribution
        assert total <= pg.reactor_output + pg.battery_discharge_rate + 1.0

    def test_bus_offline_zeroes_systems(self):
        ship = _ship()
        gle.init(ship)
        pg = gle.get_power_grid()
        assert pg is not None
        pg.secondary_bus_online = False
        gle.set_power("beams", 100.0)
        result = gle.tick(ship, _interior(), 0.1)
        assert result.power_delivered["beams"] == 0.0
        assert ship.systems["beams"].power == 0.0

    def test_reroute_zeroes_target_bus_during(self):
        ship = _ship()
        gle.init(ship)
        gle.start_reroute("secondary")
        gle.set_power("beams", 100.0)
        result = gle.tick(ship, _interior(), 0.1)
        assert result.power_delivered["beams"] == 0.0

    def test_battery_mode_change(self):
        ship = _ship()
        gle.init(ship)
        assert gle.set_battery_mode("discharging") is True
        pg = gle.get_power_grid()
        assert pg is not None
        assert pg.battery_mode == "discharging"

    def test_battery_mode_invalid(self):
        ship = _ship()
        gle.init(ship)
        assert gle.set_battery_mode("exploding") is False


# ---------------------------------------------------------------------------
# Overclock damage
# ---------------------------------------------------------------------------


class TestOverclockDamage:
    def _tick_to_check(self, ship, interior, n=None):
        """Tick enough times to reach the first overclock check.

        The first overclocked tick sets next_check = tick + INTERVAL,
        so we need INTERVAL + 1 ticks total to reach it.
        Returns the result from the check tick.
        """
        ticks = n or (gle.OVERCLOCK_CHECK_INTERVAL + 1)
        result = None
        for _ in range(ticks):
            result = gle.tick(ship, interior, 0.1)
        return result

    def test_overclock_damages_component(self):
        ship = _ship()
        # High reactor so overclock power is actually delivered
        gle.init(ship, power_grid_config={"reactor_max": 1500.0})
        dm = gle.get_damage_model()
        assert dm is not None

        # Set rng to always trigger overclock
        gle._rng = random.Random(42)
        gle._rng.random = lambda: 0.0  # always below chance
        gle._rng.uniform = lambda a, b: 10.0  # fixed damage

        # Only overclock engines; keep others low
        for sys_name in ALL_BUS_SYSTEMS:
            gle.set_power(sys_name, 50.0)
        gle.set_power("engines", 150.0)

        # Tick through the check interval to reach a damage check
        result = self._tick_to_check(ship, _interior())
        assert result is not None
        engine_events = [e for e in result.overclock_events
                         if e["system"] == "engines"]
        assert len(engine_events) >= 1
        assert engine_events[0]["damage"] == 10.0

    def test_no_overclock_at_threshold(self):
        ship = _ship()
        gle.init(ship, power_grid_config={"reactor_max": 1500.0})
        gle._rng = random.Random(42)
        gle._rng.random = lambda: 0.0  # always triggers if above threshold

        # Set all power to exactly threshold
        for name in ALL_BUS_SYSTEMS:
            gle.set_power(name, gle.OVERCLOCK_THRESHOLD)

        result = self._tick_to_check(ship, _interior())
        assert result is not None
        assert len(result.overclock_events) == 0

    def test_overclock_skips_destroyed_system(self):
        ship = _ship()
        gle.init(ship, power_grid_config={"reactor_max": 1500.0})

        for sys_name in ALL_BUS_SYSTEMS:
            gle.set_power(sys_name, 50.0)
        gle.set_power("engines", 150.0)

        # Destroy engines in damage model
        dm = gle.get_damage_model()
        assert dm is not None
        for comp in dm.components["engines"].values():
            comp.health = 0.0

        # First tick syncs health to 0 on ship
        gle.tick(ship, _interior(), 0.1)
        assert ship.systems["engines"].health == pytest.approx(0.0)

        # Now set rng and tick through interval — overclock should skip
        gle._rng = random.Random(42)
        gle._rng.random = lambda: 0.0
        result = self._tick_to_check(ship, _interior())
        assert result is not None
        engine_events = [e for e in result.overclock_events
                         if e["system"] == "engines"]
        assert len(engine_events) == 0

    def test_overclock_no_damage_when_lucky(self):
        ship = _ship()
        gle.init(ship, power_grid_config={"reactor_max": 1500.0})
        gle._rng = random.Random(42)
        gle._rng.random = lambda: 0.99  # above all chance brackets

        for sys_name in ALL_BUS_SYSTEMS:
            gle.set_power(sys_name, 50.0)
        gle.set_power("engines", 150.0)
        result = self._tick_to_check(ship, _interior())
        assert result is not None
        engine_events = [e for e in result.overclock_events
                         if e["system"] == "engines"]
        assert len(engine_events) == 0

    def test_overclock_rate_is_manageable(self):
        """120% overclock for 120 seconds → ~12-15 damage events, not 60+."""
        ship = _ship()
        gle.init(ship, power_grid_config={"reactor_max": 1500.0})

        for sys_name in ALL_BUS_SYSTEMS:
            gle.set_power(sys_name, 50.0)
        gle.set_power("engines", 120.0)

        total_events = 0
        interior = _interior()
        for _ in range(1200):  # 120 seconds at 10 Hz
            result = gle.tick(ship, interior, 0.1)
            total_events += len([e for e in result.overclock_events
                                 if e["system"] == "engines"])
        # At 120% (10% chance bracket), checks every 8s → 15 checks in 120s
        # 10% of 15 = ~1.5 expected, but with randomness allow up to 15
        assert total_events <= 15, f"Got {total_events} events, expected <=15"

    def test_overclock_grace_period(self):
        """After repair, system is immune to overclock damage for 30 seconds."""
        ship = _ship()
        gle.init(ship, power_grid_config={"reactor_max": 1500.0})

        for sys_name in ALL_BUS_SYSTEMS:
            gle.set_power(sys_name, 50.0)
        gle.set_power("engines", 150.0)

        gle._rng = random.Random(42)
        gle._rng.random = lambda: 0.0  # always triggers
        gle._rng.uniform = lambda a, b: 10.0

        # Simulate a repair event by setting grace period
        gle._overclock_grace_until["engines"] = (
            gle._tick_count + gle.OVERCLOCK_GRACE_TICKS
        )

        # Tick for 30 seconds (300 ticks) — no damage should occur
        interior = _interior()
        events_during_grace = 0
        for _ in range(300):
            result = gle.tick(ship, interior, 0.1)
            events_during_grace += len([e for e in result.overclock_events
                                        if e["system"] == "engines"])
        assert events_during_grace == 0, (
            f"Got {events_during_grace} events during grace period"
        )

        # After grace expires, force next check to happen soon
        gle._overclock_next_check["engines"] = gle._tick_count + 1
        result = gle.tick(ship, interior, 0.1)
        engine_events = [e for e in result.overclock_events
                         if e["system"] == "engines"]
        assert len(engine_events) >= 1

    def test_overclock_chance_scales_with_power(self):
        """Higher overclock levels should have higher damage probability."""
        ship = _ship()
        # Test the bracket function directly
        assert gle._get_overclock_chance(105.0) == 0.10
        assert gle._get_overclock_chance(115.0) == 0.25
        assert gle._get_overclock_chance(130.0) == 0.50
        assert gle._get_overclock_chance(145.0) == 0.80
        assert gle._get_overclock_chance(100.0) == 0.0  # at threshold, no risk

    def test_overheat_warning_before_damage(self):
        """Warning should be emitted ~5 seconds before damage check."""
        ship = _ship()
        gle.init(ship, power_grid_config={"reactor_max": 1500.0})

        for sys_name in ALL_BUS_SYSTEMS:
            gle.set_power(sys_name, 50.0)
        gle.set_power("engines", 150.0)

        interior = _interior()
        warning_tick = None
        # Tick until we see a warning
        for i in range(gle.OVERCLOCK_CHECK_INTERVAL):
            result = gle.tick(ship, interior, 0.1)
            eng_warnings = [w for w in result.overclock_warnings
                            if w["system"] == "engines"]
            if eng_warnings and warning_tick is None:
                warning_tick = i + 1  # 1-based tick count

        assert warning_tick is not None, "No overheat warning emitted"
        # next_check is set on tick 1 to (1 + INTERVAL) = 81
        # warning fires at tick >= 81 - 50 = 31 → that's the 31st tick
        expected = gle.OVERCLOCK_CHECK_INTERVAL - gle.OVERCLOCK_WARNING_TICKS + 1
        assert warning_tick == expected

    def test_max_simultaneous_damage(self):
        """At most OVERCLOCK_MAX_SIMULTANEOUS systems take damage per tick."""
        ship = _ship()
        gle.init(ship, power_grid_config={"reactor_max": 5000.0})

        gle._rng = random.Random(42)
        gle._rng.random = lambda: 0.0  # always triggers
        gle._rng.uniform = lambda a, b: 5.0

        # Overclock ALL systems
        for sys_name in ALL_BUS_SYSTEMS:
            gle.set_power(sys_name, 150.0)

        # Tick to first check
        result = self._tick_to_check(ship, _interior())
        assert result is not None
        assert len(result.overclock_events) <= gle.OVERCLOCK_MAX_SIMULTANEOUS

    def test_overheat_warning_in_build_state(self):
        """build_state includes overheat_warning flag per system."""
        ship = _ship()
        gle.init(ship, power_grid_config={"reactor_max": 1500.0})

        for sys_name in ALL_BUS_SYSTEMS:
            gle.set_power(sys_name, 50.0)
        gle.set_power("engines", 150.0)

        interior = _interior()
        # Tick past the warning threshold
        for _ in range(gle.OVERCLOCK_CHECK_INTERVAL - gle.OVERCLOCK_WARNING_TICKS + 1):
            gle.tick(ship, interior, 0.1)

        state = gle.build_state(ship)
        assert state["systems"]["engines"]["overheat_warning"] is True
        assert state["systems"]["beams"]["overheat_warning"] is False


# ---------------------------------------------------------------------------
# Health sync
# ---------------------------------------------------------------------------


class TestHealthSync:
    def test_damage_syncs_to_ship_system(self):
        ship = _ship()
        gle.init(ship)
        dm = gle.get_damage_model()
        assert dm is not None

        # Directly damage a component
        dm.components["engines"]["fuel_injectors"].health = 50.0

        # Tick to trigger sync
        gle.tick(ship, _interior(), 0.1)

        # Ship system health should reflect weighted component health
        expected = dm.get_system_health("engines")
        assert ship.systems["engines"].health == pytest.approx(expected)

    def test_full_health_stays_at_100(self):
        ship = _ship()
        gle.init(ship)
        gle.tick(ship, _interior(), 0.1)
        for name in ship.systems:
            assert ship.systems[name].health == pytest.approx(100.0)

    def test_all_components_destroyed_gives_zero_health(self):
        ship = _ship()
        gle.init(ship)
        dm = gle.get_damage_model()
        assert dm is not None

        for comp in dm.components["beams"].values():
            comp.health = 0.0

        gle.tick(ship, _interior(), 0.1)
        assert ship.systems["beams"].health == pytest.approx(0.0)

    def test_partial_damage_weighted_correctly(self):
        ship = _ship()
        gle.init(ship)
        dm = gle.get_damage_model()
        assert dm is not None

        # Damage emitter_array (weight=0.4) to 50%
        dm.components["beams"]["emitter_array"].health = 50.0
        gle.tick(ship, _interior(), 0.1)

        # Expected: 0.4*50/100 + 0.3*100/100 + 0.3*100/100 = 0.2+0.3+0.3 = 0.8 → 80%
        assert ship.systems["beams"].health == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# Repair teams
# ---------------------------------------------------------------------------


class TestRepairTeams:
    def test_dispatch_team(self):
        ship = _ship()
        interior = _interior()
        gle.init(ship, _crew_ids(9))
        mgr = gle.get_repair_manager()
        assert mgr is not None
        team_id = list(mgr.teams.keys())[0]
        assert gle.dispatch_team(team_id, "engines", interior) is True
        team = mgr.teams[team_id]
        assert team.target_system == "engines"

    def test_recall_team(self):
        ship = _ship()
        interior = _interior()
        gle.init(ship, _crew_ids(9))
        mgr = gle.get_repair_manager()
        assert mgr is not None
        team_id = list(mgr.teams.keys())[0]
        gle.dispatch_team(team_id, "engines", interior)
        assert gle.recall_team(team_id, interior) is True

    def test_repair_team_events_in_tick(self):
        ship = _ship()
        interior = _interior()
        gle.init(ship, _crew_ids(9))
        mgr = gle.get_repair_manager()
        assert mgr is not None
        team_id = list(mgr.teams.keys())[0]
        team = mgr.teams[team_id]

        # Place team directly at target room to start repairing
        target_room = SYSTEM_ROOMS["engines"]
        team.room_id = target_room
        team.target_system = "engines"
        team.target_room_id = target_room
        team.status = "repairing"

        result = gle.tick(ship, interior, 0.1)
        repair_events = [e for e in result.repair_team_events
                         if e["type"] == "repair_hp"]
        assert len(repair_events) >= 1
        assert repair_events[0]["system"] == "engines"

    def test_repair_heals_damage_model(self):
        ship = _ship()
        interior = _interior()
        gle.init(ship, _crew_ids(9))
        dm = gle.get_damage_model()
        mgr = gle.get_repair_manager()
        assert dm is not None and mgr is not None

        # Damage a component
        dm.components["engines"]["fuel_injectors"].health = 50.0

        # Set up team at repair location
        team_id = list(mgr.teams.keys())[0]
        team = mgr.teams[team_id]
        target_room = SYSTEM_ROOMS["engines"]
        team.room_id = target_room
        team.target_system = "engines"
        team.target_room_id = target_room
        team.status = "repairing"

        # Tick multiple times to accumulate repair
        for _ in range(10):
            gle.tick(ship, interior, 0.1)

        # Fuel injectors should have healed (it's the worst component)
        assert dm.components["engines"]["fuel_injectors"].health > 50.0

    def test_request_escort(self):
        ship = _ship()
        gle.init(ship, _crew_ids(9))
        mgr = gle.get_repair_manager()
        assert mgr is not None
        team_id = list(mgr.teams.keys())[0]
        assert gle.request_escort(team_id, "squad_1") is True
        assert mgr.teams[team_id].escort_squad_id == "squad_1"

    def test_clear_escort(self):
        ship = _ship()
        gle.init(ship, _crew_ids(9))
        mgr = gle.get_repair_manager()
        assert mgr is not None
        team_id = list(mgr.teams.keys())[0]
        gle.request_escort(team_id, "squad_1")
        gle.clear_escort(team_id)
        assert mgr.teams[team_id].escort_squad_id is None


# ---------------------------------------------------------------------------
# Repair orders
# ---------------------------------------------------------------------------


class TestRepairOrders:
    def test_add_order(self):
        ship = _ship()
        gle.init(ship, _crew_ids(9))
        oid = gle.add_repair_order("engines", priority=2)
        assert oid is not None
        mgr = gle.get_repair_manager()
        assert mgr is not None
        assert len(mgr.order_queue) == 1

    def test_cancel_order(self):
        ship = _ship()
        gle.init(ship, _crew_ids(9))
        oid = gle.add_repair_order("engines")
        assert oid is not None
        assert gle.cancel_repair_order(oid) is True
        mgr = gle.get_repair_manager()
        assert mgr is not None
        assert len(mgr.order_queue) == 0

    def test_cancel_nonexistent_order(self):
        ship = _ship()
        gle.init(ship, _crew_ids(9))
        assert gle.cancel_repair_order("order_999") is False


# ---------------------------------------------------------------------------
# External damage
# ---------------------------------------------------------------------------


class TestExternalDamage:
    def test_apply_system_damage(self):
        ship = _ship()
        gle.init(ship)
        events = gle.apply_system_damage("engines", 20.0, "beam_hit", tick=5)
        assert len(events) >= 1
        dm = gle.get_damage_model()
        assert dm is not None
        assert dm.get_system_health("engines") < 100.0

    def test_apply_targeted_damage(self):
        ship = _ship()
        gle.init(ship)
        events = gle.apply_system_damage(
            "engines", 15.0, "fire",
            component_id="coolant_system")
        assert len(events) >= 1
        dm = gle.get_damage_model()
        assert dm is not None
        assert dm.components["engines"]["coolant_system"].health == 85.0

    def test_apply_damage_syncs_on_tick(self):
        ship = _ship()
        gle.init(ship)
        gle.apply_system_damage("beams", 30.0, "torpedo")
        gle.tick(ship, _interior(), 0.1)
        assert ship.systems["beams"].health < 100.0

    def test_apply_damage_without_init(self):
        events = gle.apply_system_damage("engines", 10.0, "test")
        assert events == []


# ---------------------------------------------------------------------------
# Build state
# ---------------------------------------------------------------------------


class TestBuildState:
    def test_build_state_has_systems(self):
        ship = _ship()
        gle.init(ship, _crew_ids())
        state = gle.build_state(ship)
        assert "systems" in state
        assert "engines" in state["systems"]

    def test_build_state_has_power_grid(self):
        ship = _ship()
        gle.init(ship)
        state = gle.build_state(ship)
        pg = state["power_grid"]
        assert "reactor_max" in pg
        assert "reactor_output" in pg
        assert "battery_charge" in pg
        assert "available_budget" in pg

    def test_build_state_has_components(self):
        ship = _ship()
        gle.init(ship)
        state = gle.build_state(ship)
        engines = state["systems"]["engines"]
        assert "components" in engines
        assert len(engines["components"]) == len(COMPONENT_SPECS["engines"])

    def test_build_state_has_repair_teams(self):
        ship = _ship()
        gle.init(ship, _crew_ids(9))
        state = gle.build_state(ship)
        assert "repair_teams" in state
        assert len(state["repair_teams"]) == 3

    def test_build_state_has_repair_orders(self):
        ship = _ship()
        gle.init(ship, _crew_ids(9))
        gle.add_repair_order("engines")
        state = gle.build_state(ship)
        assert "repair_orders" in state
        assert len(state["repair_orders"]) == 1

    def test_build_state_has_recent_events(self):
        ship = _ship()
        gle.init(ship)
        gle.apply_system_damage("engines", 10.0, "test")
        state = gle.build_state(ship)
        assert "recent_damage_events" in state
        assert len(state["recent_damage_events"]) >= 1

    def test_build_state_requested_power(self):
        ship = _ship()
        gle.init(ship)
        gle.set_power("engines", 120.0)
        state = gle.build_state(ship)
        assert state["systems"]["engines"]["requested_power"] == 120.0


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


class TestSerialisation:
    def test_round_trip(self):
        ship = _ship()
        gle.init(ship, _crew_ids(9))
        gle.set_power("engines", 120.0)
        gle.apply_system_damage("beams", 15.0, "test")
        gle.tick(ship, _interior(), 0.1)

        data = gle.serialise()
        gle.reset()

        ship2 = _ship()
        gle.deserialise(data, ship2)

        assert gle.get_power_grid() is not None
        assert gle.get_damage_model() is not None
        assert gle.get_repair_manager() is not None
        assert gle._requested_power.get("engines") == 120.0

    def test_serialise_preserves_damage(self):
        ship = _ship()
        gle.init(ship)
        gle.apply_system_damage("engines", 25.0, "fire")
        gle.tick(ship, _interior(), 0.1)
        original_health = ship.systems["engines"].health

        data = gle.serialise()
        gle.reset()
        ship2 = _ship()
        gle.deserialise(data, ship2)

        assert ship2.systems["engines"].health == pytest.approx(original_health)

    def test_serialise_preserves_power_grid(self):
        ship = _ship()
        gle.init(ship, power_grid_config={"reactor_max": 800.0})
        pg = gle.get_power_grid()
        assert pg is not None
        pg.damage_reactor(20.0)

        data = gle.serialise()
        gle.reset()
        gle.deserialise(data, _ship())

        pg2 = gle.get_power_grid()
        assert pg2 is not None
        assert pg2.reactor_max == 800.0
        assert pg2.reactor_health == pytest.approx(80.0)

    def test_serialise_preserves_teams(self):
        ship = _ship()
        gle.init(ship, _crew_ids(9))
        data = gle.serialise()
        gle.reset()
        gle.deserialise(data, _ship())

        mgr = gle.get_repair_manager()
        assert mgr is not None
        assert len(mgr.teams) == 3

    def test_deserialise_empty(self):
        ship = _ship()
        gle.deserialise({}, ship)
        assert gle.get_power_grid() is not None
        assert gle.get_damage_model() is not None
        assert gle.get_repair_manager() is not None

    def test_serialise_preserves_tick_count(self):
        ship = _ship()
        gle.init(ship)
        gle.tick(ship, _interior(), 0.1)
        gle.tick(ship, _interior(), 0.1)
        data = gle.serialise()
        assert data["tick_count"] == 2
        gle.reset()
        gle.deserialise(data, _ship())
        assert gle._tick_count == 2


# ---------------------------------------------------------------------------
# Guard: uninitialised calls
# ---------------------------------------------------------------------------


class TestGuards:
    def test_tick_without_init(self):
        ship = _ship()
        result = gle.tick(ship, _interior(), 0.1)
        assert result.power_delivered == {}
        assert result.overclock_events == []
        assert result.repair_team_events == []

    def test_dispatch_without_init(self):
        assert gle.dispatch_team("t", "engines", _interior()) is False

    def test_recall_without_init(self):
        assert gle.recall_team("t", _interior()) is False

    def test_battery_mode_without_init(self):
        assert gle.set_battery_mode("auto") is False

    def test_reroute_without_init(self):
        assert gle.start_reroute("primary") is False

    def test_escort_without_init(self):
        assert gle.request_escort("t", "s") is False

    def test_add_order_without_init(self):
        assert gle.add_repair_order("engines") is None

    def test_cancel_order_without_init(self):
        assert gle.cancel_repair_order("x") is False

    def test_build_state_without_full_init(self):
        ship = _ship()
        # Should not crash even without init
        state = gle.build_state(ship)
        assert "systems" in state

    def test_serialise_without_init(self):
        data = gle.serialise()
        assert "requested_power" in data
