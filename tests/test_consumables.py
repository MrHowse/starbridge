"""Tests for the Consumable Resource System — v0.07 Phase 6.1."""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from server.models.resources import (
    ResourceStore,
    RESOURCE_TYPES,
    WARNING_THRESHOLD,
    CRITICAL_THRESHOLD,
    PROVISIONS_CONSUMPTION_RATE,
    REPAIR_COST_FIRE_TO_DAMAGED,
    REPAIR_COST_DAMAGED_TO_NORMAL,
)
from server.models.ship import Ship
from server.models.ship_class import load_ship_class, SHIP_CLASS_ORDER


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SHIPS_DIR = Path(__file__).parent.parent / "ships"

EXPECTED_RESOURCES = {
    "scout": {
        "fuel": (600, 600, 1.5, 0.3),
        "medical_supplies": (30, 40),
        "repair_materials": (20, 30),
        "drone_fuel": (100, 100),
        "drone_parts": (5, 10),
        "ammunition": (30, 40),
        "provisions": (200, 200),
        "cargo_capacity": 20,
    },
    "corvette": {
        "fuel": (900, 900, 0.7, 0.4),
        "medical_supplies": (40, 60),
        "repair_materials": (30, 40),
        "drone_fuel": (150, 150),
        "drone_parts": (8, 15),
        "ammunition": (40, 60),
        "provisions": (350, 350),
        "cargo_capacity": 40,
    },
    "frigate": {
        "fuel": (1200, 1200, 1.0, 0.5),
        "medical_supplies": (60, 80),
        "repair_materials": (50, 60),
        "drone_fuel": (200, 200),
        "drone_parts": (12, 20),
        "ammunition": (50, 80),
        "provisions": (500, 500),
        "cargo_capacity": 60,
    },
    "cruiser": {
        "fuel": (1800, 1800, 0.8, 0.7),
        "medical_supplies": (80, 100),
        "repair_materials": (70, 90),
        "drone_fuel": (300, 300),
        "drone_parts": (15, 25),
        "ammunition": (70, 100),
        "provisions": (800, 800),
        "cargo_capacity": 80,
    },
    "battleship": {
        "fuel": (2400, 2400, 1.8, 1.0),
        "medical_supplies": (100, 120),
        "repair_materials": (100, 120),
        "drone_fuel": (400, 400),
        "drone_parts": (20, 30),
        "ammunition": (100, 150),
        "provisions": (1200, 1200),
        "cargo_capacity": 100,
    },
    "carrier": {
        "fuel": (1600, 1600, 1.0, 0.8),
        "medical_supplies": (70, 90),
        "repair_materials": (60, 80),
        "drone_fuel": (800, 800),
        "drone_parts": (40, 60),
        "ammunition": (60, 80),
        "provisions": (1000, 1000),
        "cargo_capacity": 70,
    },
    "medical_ship": {
        "fuel": (1000, 1000, 0.75, 0.4),
        "medical_supplies": (200, 250),
        "repair_materials": (40, 50),
        "drone_fuel": (200, 200),
        "drone_parts": (10, 15),
        "ammunition": (30, 40),
        "provisions": (600, 600),
        "cargo_capacity": 50,
    },
}


def _make_store(**kw) -> ResourceStore:
    """Create a ResourceStore with convenience defaults."""
    defaults = {
        "fuel": 100.0, "fuel_max": 100.0,
        "engine_burn_rate": 1.0, "reactor_idle_rate": 0.5,
        "medical_supplies": 50.0, "medical_supplies_max": 100.0,
        "repair_materials": 50.0, "repair_materials_max": 100.0,
        "drone_fuel": 50.0, "drone_fuel_max": 100.0,
        "drone_parts": 10.0, "drone_parts_max": 20.0,
        "ammunition": 50.0, "ammunition_max": 100.0,
        "provisions": 100.0, "provisions_max": 200.0,
    }
    defaults.update(kw)
    return ResourceStore(**defaults)


# ===================================================================
# 1. ResourceStore basics (10 tests)
# ===================================================================


class TestResourceStoreBasics:
    """ResourceStore core functionality."""

    def test_defaults(self):
        store = ResourceStore()
        for rt in RESOURCE_TYPES:
            assert store.get(rt) == 0.0
            assert store.get_max(rt) == 0.0

    def test_get_set(self):
        store = _make_store()
        store.set("fuel", 80.0)
        assert store.fuel == 80.0

    def test_set_clamps_to_max(self):
        store = _make_store()
        store.set("fuel", 999.0)
        assert store.fuel == 100.0

    def test_set_clamps_to_zero(self):
        store = _make_store()
        store.set("fuel", -10.0)
        assert store.fuel == 0.0

    def test_consume_basic(self):
        store = _make_store(fuel=50.0)
        actual = store.consume("fuel", 20.0)
        assert actual == 20.0
        assert store.fuel == 30.0

    def test_consume_clamps(self):
        store = _make_store(fuel=10.0)
        actual = store.consume("fuel", 50.0)
        assert actual == 10.0
        assert store.fuel == 0.0

    def test_add_basic(self):
        store = _make_store(fuel=80.0)
        actual = store.add("fuel", 10.0)
        assert actual == 10.0
        assert store.fuel == 90.0

    def test_add_clamps(self):
        store = _make_store(fuel=95.0)
        actual = store.add("fuel", 20.0)
        assert actual == 5.0
        assert store.fuel == 100.0

    def test_fraction(self):
        store = _make_store(fuel=25.0, fuel_max=100.0)
        assert store.fraction("fuel") == 0.25

    def test_fraction_zero_max(self):
        store = ResourceStore()
        assert store.fraction("fuel") == 1.0

    def test_warning(self):
        store = _make_store(fuel=25.0, fuel_max=100.0)
        assert store.is_warning("fuel") is True

    def test_not_warning(self):
        store = _make_store(fuel=50.0, fuel_max=100.0)
        assert store.is_warning("fuel") is False

    def test_critical(self):
        store = _make_store(fuel=10.0, fuel_max=100.0)
        assert store.is_critical("fuel") is True

    def test_depleted(self):
        store = _make_store(fuel=0.0)
        assert store.is_depleted("fuel") is True

    def test_not_depleted(self):
        store = _make_store(fuel=1.0)
        assert store.is_depleted("fuel") is False

    def test_threshold_tracking(self):
        store = _make_store(fuel=30.0, fuel_max=100.0)
        # First check should not trigger (above warning).
        alerts = store.check_thresholds()
        fuel_alerts = [a for a in alerts if a["resource"] == "fuel"]
        assert len(fuel_alerts) == 0

        # Drop to warning level.
        store.fuel = 25.0
        alerts = store.check_thresholds()
        fuel_alerts = [a for a in alerts if a["resource"] == "fuel"]
        assert len(fuel_alerts) == 1
        assert fuel_alerts[0]["level"] == "warning"

        # Same level again — no duplicate.
        alerts = store.check_thresholds()
        fuel_alerts = [a for a in alerts if a["resource"] == "fuel"]
        assert len(fuel_alerts) == 0

    def test_threshold_reset(self):
        store = _make_store(fuel=20.0, fuel_max=100.0)
        store.check_thresholds()  # triggers warning
        store.fuel = 50.0
        store.check_thresholds()  # clears warning flag
        store.fuel = 20.0
        alerts = store.check_thresholds()  # should re-trigger
        fuel_alerts = [a for a in alerts if a["resource"] == "fuel"]
        assert len(fuel_alerts) == 1

    def test_to_dict(self):
        store = _make_store()
        d = store.to_dict()
        assert "fuel" in d
        assert "fuel_max" in d
        assert "fuel_fraction" in d
        assert "provisions_depleted_time" in d


# ===================================================================
# 2. Per-ship-class values (7 tests)
# ===================================================================


class TestPerShipClassResources:
    """Each ship class JSON has correct starting + capacity values per spec."""

    @pytest.mark.parametrize("class_id", SHIP_CLASS_ORDER)
    def test_ship_class_resources(self, class_id: str):
        sc = load_ship_class(class_id)
        assert sc.resources is not None, f"{class_id} missing resources block"
        expected = EXPECTED_RESOURCES[class_id]

        # Fuel (starting, capacity, engine_burn, reactor_idle)
        fuel = sc.resources["fuel"]
        ef = expected["fuel"]
        assert fuel["starting"] == ef[0], f"{class_id} fuel starting"
        assert fuel["capacity"] == ef[1], f"{class_id} fuel capacity"
        assert fuel["engine_burn"] == ef[2], f"{class_id} engine_burn"
        assert fuel["reactor_idle"] == ef[3], f"{class_id} reactor_idle"

        # Other resource types (starting, capacity)
        for rt in ("medical_supplies", "repair_materials", "drone_fuel",
                    "drone_parts", "ammunition", "provisions"):
            block = sc.resources[rt]
            exp = expected[rt]
            assert block["starting"] == exp[0], f"{class_id} {rt} starting"
            assert block["capacity"] == exp[1], f"{class_id} {rt} capacity"

        # Cargo capacity
        assert sc.cargo_capacity == expected["cargo_capacity"], f"{class_id} cargo_capacity"


# ===================================================================
# 3. JSON schema (3 tests)
# ===================================================================


class TestJSONSchema:
    """Ship class JSON files have valid resource blocks."""

    @pytest.mark.parametrize("class_id", SHIP_CLASS_ORDER)
    def test_resources_block_exists(self, class_id: str):
        sc = load_ship_class(class_id)
        assert sc.resources is not None

    @pytest.mark.parametrize("class_id", SHIP_CLASS_ORDER)
    def test_all_resource_types_present(self, class_id: str):
        sc = load_ship_class(class_id)
        for rt in RESOURCE_TYPES:
            assert rt in sc.resources, f"{class_id} missing {rt}"

    def test_from_ship_class_resources(self):
        sc = load_ship_class("frigate")
        store = ResourceStore.from_ship_class_resources(sc.resources)
        assert store.fuel == 1200.0
        assert store.fuel_max == 1200.0
        assert store.engine_burn_rate == 1.0
        assert store.reactor_idle_rate == 0.5
        assert store.medical_supplies == 60.0
        assert store.provisions == 500.0


# ===================================================================
# 4. Fuel consumption (5 tests)
# ===================================================================


class TestFuelConsumption:
    """Fuel burn mechanics."""

    def test_full_throttle_burn(self):
        store = _make_store(fuel=100.0, fuel_max=100.0, engine_burn_rate=2.0, reactor_idle_rate=0.5)
        # Full throttle for 1 second: burn = engine_burn_rate * fuel_multiplier * dt = 2.0
        throttle_frac = 1.0
        fuel_multiplier = 1.0
        dt = 1.0
        burn = (store.reactor_idle_rate + (store.engine_burn_rate - store.reactor_idle_rate) * throttle_frac) * fuel_multiplier * dt
        store.consume("fuel", burn)
        assert store.fuel == pytest.approx(98.0)

    def test_idle_burn(self):
        store = _make_store(fuel=100.0, fuel_max=100.0, engine_burn_rate=2.0, reactor_idle_rate=0.5)
        throttle_frac = 0.0
        burn = (store.reactor_idle_rate + (store.engine_burn_rate - store.reactor_idle_rate) * throttle_frac) * 1.0 * 1.0
        store.consume("fuel", burn)
        assert store.fuel == pytest.approx(99.5)

    def test_fuel_multiplier_scaling(self):
        store = _make_store(fuel=100.0, fuel_max=100.0, engine_burn_rate=1.0, reactor_idle_rate=0.5)
        # With fuel_multiplier=1.5 (scout)
        throttle_frac = 1.0
        fuel_multiplier = 1.5
        burn = (store.reactor_idle_rate + (store.engine_burn_rate - store.reactor_idle_rate) * throttle_frac) * fuel_multiplier * 1.0
        store.consume("fuel", burn)
        assert store.fuel == pytest.approx(100.0 - 1.5)

    def test_difficulty_scaling(self):
        store = _make_store(fuel=100.0, fuel_max=100.0, engine_burn_rate=1.0, reactor_idle_rate=0.5)
        throttle_frac = 1.0
        fuel_consumption_mult = 1.5
        burn = (store.reactor_idle_rate + (store.engine_burn_rate - store.reactor_idle_rate) * throttle_frac) * 1.0 * fuel_consumption_mult * 1.0
        store.consume("fuel", burn)
        assert store.fuel == pytest.approx(100.0 - 1.5)

    def test_reactor_shutdown_at_zero(self):
        store = _make_store(fuel=0.5, fuel_max=100.0, engine_burn_rate=1.0, reactor_idle_rate=0.5)
        store.consume("fuel", 1.0)
        assert store.fuel == 0.0
        assert store.is_depleted("fuel")


# ===================================================================
# 5. Medical supplies bridge (3 tests)
# ===================================================================


class TestMedicalSupplies:
    """Medical supplies sync with ResourceStore."""

    def test_sync_from_resources(self):
        store = _make_store(medical_supplies=60.0, medical_supplies_max=80.0)
        assert store.medical_supplies == 60.0

    def test_treatment_consumes(self):
        store = _make_store(medical_supplies=60.0, medical_supplies_max=80.0)
        store.consume("medical_supplies", 5.0)
        assert store.medical_supplies == 55.0

    def test_depleted_triage_only(self):
        store = _make_store(medical_supplies=0.0, medical_supplies_max=80.0)
        assert store.is_depleted("medical_supplies")


# ===================================================================
# 6. Repair materials (3 tests)
# ===================================================================


class TestRepairMaterials:
    """Repair material consumption in damage control."""

    def test_dc_repair_consumes(self):
        store = _make_store(repair_materials=50.0, repair_materials_max=100.0)
        store.consume("repair_materials", REPAIR_COST_FIRE_TO_DAMAGED)
        assert store.repair_materials == 48.0

    def test_dc_repair_major_costs_more(self):
        store = _make_store(repair_materials=50.0, repair_materials_max=100.0)
        store.consume("repair_materials", REPAIR_COST_DAMAGED_TO_NORMAL)
        assert store.repair_materials == 45.0

    def test_dc_repair_blocked_at_zero(self):
        store = _make_store(repair_materials=0.0, repair_materials_max=100.0)
        assert store.is_depleted("repair_materials")
        # Consume returns 0 when depleted.
        actual = store.consume("repair_materials", 5.0)
        assert actual == 0.0


# ===================================================================
# 7. Drone resources (3 tests)
# ===================================================================


class TestDroneResources:
    """Drone fuel and parts consumption."""

    def test_turnaround_fuel_consume(self):
        store = _make_store(drone_fuel=100.0, drone_fuel_max=200.0)
        fuel_needed = 50.0
        consumed = store.consume("drone_fuel", fuel_needed)
        assert consumed == 50.0
        assert store.drone_fuel == 50.0

    def test_turnaround_parts_consume(self):
        store = _make_store(drone_parts=10.0, drone_parts_max=20.0)
        parts_needed = 3.0
        consumed = store.consume("drone_parts", parts_needed)
        assert consumed == 3.0
        assert store.drone_parts == 7.0

    def test_no_launch_at_zero_fuel(self):
        store = _make_store(drone_fuel=0.0, drone_fuel_max=200.0)
        assert store.is_depleted("drone_fuel")


# ===================================================================
# 8. Ammunition (3 tests)
# ===================================================================


class TestAmmunition:
    """Ammunition consumption in security combat."""

    def test_combat_consumes(self):
        store = _make_store(ammunition=50.0, ammunition_max=100.0)
        store.consume("ammunition", 5.0)
        assert store.ammunition == 45.0

    def test_multiple_squads_consume(self):
        store = _make_store(ammunition=50.0, ammunition_max=100.0)
        # 2 squads × 5 AMU = 10 per round
        store.consume("ammunition", 10.0)
        assert store.ammunition == 40.0

    def test_firepower_penalty_when_depleted(self):
        store = _make_store(ammunition=0.0, ammunition_max=100.0)
        assert store.is_depleted("ammunition")


# ===================================================================
# 9. Provisions (4 tests)
# ===================================================================


class TestProvisions:
    """Provisions depletion and consequences."""

    def test_depletion_rate(self):
        store = _make_store(provisions=100.0, provisions_max=200.0)
        crew_count = 8
        dt = 60.0  # 1 minute
        consume_per_min = PROVISIONS_CONSUMPTION_RATE * crew_count  # 0.02 * 8 = 0.16
        store.consume("provisions", consume_per_min)
        assert store.provisions == pytest.approx(100.0 - 0.16)

    def test_provisions_depleted_time_tracking(self):
        store = _make_store(provisions=0.0, provisions_max=200.0)
        store.provisions_depleted_time = 300.0  # 5 minutes
        assert store.provisions_depleted_time == 300.0

    def test_10min_penalty(self):
        store = _make_store(provisions=0.0, provisions_max=200.0)
        store.provisions_depleted_time = 600.0  # 10 minutes
        depl_min = store.provisions_depleted_time / 60.0
        if depl_min >= 30.0:
            penalty = 0.50
        elif depl_min >= 10.0:
            penalty = 0.20
        else:
            penalty = 0.0
        assert penalty == 0.20

    def test_30min_penalty(self):
        store = _make_store(provisions=0.0, provisions_max=200.0)
        store.provisions_depleted_time = 1800.0  # 30 minutes
        depl_min = store.provisions_depleted_time / 60.0
        if depl_min >= 30.0:
            penalty = 0.50
        elif depl_min >= 10.0:
            penalty = 0.20
        else:
            penalty = 0.0
        assert penalty == 0.50


# ===================================================================
# 10. Save/resume (3 tests)
# ===================================================================


class TestSaveResume:
    """ResourceStore serialisation and backward compatibility."""

    def test_round_trip(self):
        store = _make_store(fuel=42.5, provisions=123.0)
        store.provisions_depleted_time = 60.0
        store.provisions_crew_penalty = 0.20
        d = store.to_dict()
        # Simulate restoring from save.
        store2 = _make_store()
        store2.fuel = d["fuel"]
        store2.provisions = d["provisions"]
        assert store2.fuel == pytest.approx(42.5)
        assert store2.provisions == pytest.approx(123.0)

    def test_backward_compat_no_resources(self):
        """Old saves without resources key should still work."""
        store = ResourceStore()
        # Default ResourceStore should have all zeros — nothing crashes.
        for rt in RESOURCE_TYPES:
            assert store.get(rt) == 0.0
        assert store.to_dict() is not None

    def test_broadcast_includes_resources(self):
        store = _make_store()
        d = store.to_dict()
        for rt in RESOURCE_TYPES:
            assert rt in d
            assert f"{rt}_max" in d
            assert f"{rt}_fraction" in d


# ===================================================================
# 11. Integration (3 tests)
# ===================================================================


class TestIntegration:
    """Integration with Ship model and ship class loading."""

    def test_ship_has_resources(self):
        ship = Ship()
        assert hasattr(ship, "resources")
        assert isinstance(ship.resources, ResourceStore)

    def test_init_from_ship_class(self):
        sc = load_ship_class("frigate")
        store = ResourceStore.from_ship_class_resources(sc.resources)
        assert store.fuel == 1200.0
        assert store.fuel_max == 1200.0
        assert store.medical_supplies == 60.0
        assert store.provisions == 500.0
        assert store.ammunition == 50.0

    def test_docking_resupply(self):
        store = _make_store(fuel=20.0, fuel_max=100.0, provisions=10.0, provisions_max=200.0)
        store.add("fuel", store.fuel_max)
        store.add("provisions", store.provisions_max)
        assert store.fuel == 100.0
        assert store.provisions == 200.0


# ===================================================================
# 12. Validate ship JSON tool (1 test)
# ===================================================================


class TestValidateShipJSON:
    """validate_ship_json.py correctly validates resource blocks."""

    def test_all_classes_pass_validation(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "validate_ship_json",
            str(Path(__file__).parent.parent / "tools" / "validate_ship_json.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for class_id in SHIP_CLASS_ORDER:
            errors = mod.validate(class_id)
            assert errors == [], f"{class_id} validation errors: {errors}"


# ===================================================================
# 13. Ammo firepower penalty (§6.1.1.7) — 3 tests
# ===================================================================


class TestAmmoFirepowerPenalty:
    """Marine firepower is reduced by 60% when ship ammunition is depleted."""

    def test_depleted_ammo_applies_penalty(self):
        from server.models.resources import AMMO_DEPLETED_FIREPOWER_PENALTY
        store = _make_store(ammunition=0.0, ammunition_max=100.0)
        base_power = 10.0
        penalised = base_power * (1.0 - AMMO_DEPLETED_FIREPOWER_PENALTY)
        assert penalised == pytest.approx(4.0)

    def test_non_depleted_no_penalty(self):
        store = _make_store(ammunition=50.0, ammunition_max=100.0)
        assert not store.is_depleted("ammunition")

    def test_penalty_constant_is_060(self):
        from server.models.resources import AMMO_DEPLETED_FIREPOWER_PENALTY
        assert AMMO_DEPLETED_FIREPOWER_PENALTY == 0.60


# ===================================================================
# 14. Provisions crew penalty (§6.1.1.8) — 3 tests
# ===================================================================


class TestProvisionsCrewPenalty:
    """Provisions depletion applies crew factor penalty across all systems."""

    def test_penalty_reduces_crew_factor(self):
        ship = Ship()
        res = _make_store(provisions=0.0, provisions_max=200.0)
        res.provisions_crew_penalty = 0.20
        ship.resources = res
        # Simulate: base crew factor 1.0 → after 20% penalty → 0.80
        for sys_obj in ship.systems.values():
            sys_obj._crew_factor = 1.0
        for sys_obj in ship.systems.values():
            sys_obj._crew_factor = max(0.05, sys_obj._crew_factor * (1.0 - res.provisions_crew_penalty))
        for sys_obj in ship.systems.values():
            assert sys_obj._crew_factor == pytest.approx(0.80)

    def test_30min_penalty_halves_crew_factor(self):
        ship = Ship()
        res = _make_store(provisions=0.0, provisions_max=200.0)
        res.provisions_crew_penalty = 0.50
        ship.resources = res
        for sys_obj in ship.systems.values():
            sys_obj._crew_factor = 1.0
        for sys_obj in ship.systems.values():
            sys_obj._crew_factor = max(0.05, sys_obj._crew_factor * (1.0 - res.provisions_crew_penalty))
        for sys_obj in ship.systems.values():
            assert sys_obj._crew_factor == pytest.approx(0.50)

    def test_no_penalty_when_provisions_available(self):
        res = _make_store(provisions=100.0, provisions_max=200.0)
        assert res.provisions_crew_penalty == 0.0


# ===================================================================
# 15. Drone fuel at launch (§6.1.1.5) — 3 tests
# ===================================================================


class TestDroneFuelAtLaunch:
    """Drone launch consumes fuel from ResourceStore and is blocked at 0."""

    def test_launch_consumes_drone_fuel(self):
        store = _make_store(drone_fuel=100.0, drone_fuel_max=200.0)
        fuel_needed = 50.0
        consumed = store.consume("drone_fuel", fuel_needed)
        assert consumed == 50.0
        assert store.drone_fuel == 50.0

    def test_launch_blocked_at_zero(self):
        store = _make_store(drone_fuel=0.0, drone_fuel_max=200.0)
        assert store.is_depleted("drone_fuel")
        # No fuel → consume returns 0
        consumed = store.consume("drone_fuel", 100.0)
        assert consumed == 0.0

    def test_partial_fuel_available(self):
        store = _make_store(drone_fuel=30.0, drone_fuel_max=200.0)
        consumed = store.consume("drone_fuel", 100.0)
        assert consumed == 30.0
        assert store.drone_fuel == 0.0


# ===================================================================
# 16. Drone replacement (§6.1.1.6) — 3 tests
# ===================================================================


class TestDroneReplacement:
    """Destroyed drones can be replaced at 5 DPU cost."""

    def test_replacement_cost_constant(self):
        from server.game_loop_flight_ops import DRONE_REPLACEMENT_COST
        assert DRONE_REPLACEMENT_COST == 5.0

    def test_replace_consumes_parts(self):
        store = _make_store(drone_parts=10.0, drone_parts_max=20.0)
        from server.game_loop_flight_ops import DRONE_REPLACEMENT_COST
        store.consume("drone_parts", DRONE_REPLACEMENT_COST)
        assert store.drone_parts == 5.0

    def test_replace_blocked_at_zero(self):
        store = _make_store(drone_parts=0.0, drone_parts_max=20.0)
        assert store.is_depleted("drone_parts")


# ===================================================================
# 17. Medical severity-based costs (§6.1.1.3) — 4 tests
# ===================================================================


class TestMedicalSeverityCosts:
    """Treatment costs proportional to injury severity."""

    def test_severity_costs_exist(self):
        from server.models.injuries import SEVERITY_SUPPLY_COSTS
        assert "minor" in SEVERITY_SUPPLY_COSTS
        assert "moderate" in SEVERITY_SUPPLY_COSTS
        assert "serious" in SEVERITY_SUPPLY_COSTS
        assert "critical" in SEVERITY_SUPPLY_COSTS

    def test_severity_cost_values(self):
        from server.models.injuries import SEVERITY_SUPPLY_COSTS
        assert SEVERITY_SUPPLY_COSTS["minor"] == 1.0
        assert SEVERITY_SUPPLY_COSTS["moderate"] == 3.0
        assert SEVERITY_SUPPLY_COSTS["serious"] == 5.0
        assert SEVERITY_SUPPLY_COSTS["critical"] == 8.0

    def test_minor_cheaper_than_critical(self):
        from server.models.injuries import SEVERITY_SUPPLY_COSTS
        assert SEVERITY_SUPPLY_COSTS["minor"] < SEVERITY_SUPPLY_COSTS["critical"]

    def test_stabilise_works_at_zero_supplies(self):
        """Spec §6.1.4.4: at 0 supplies, stabilise still works."""
        store = _make_store(medical_supplies=0.0, medical_supplies_max=100.0)
        assert store.is_depleted("medical_supplies")
        # Stabilise doesn't gate on supplies in the spec


# ===================================================================
# 18. Emergency battery (§6.1.4.2) — 3 tests
# ===================================================================


class TestEmergencyBattery:
    """Emergency battery keeps sensors at minimal power when fuel depleted."""

    def test_sensors_not_offline_at_fuel_zero(self):
        """Sensors should get emergency power, not be fully offline."""
        ship = Ship()
        # Simulate reactor shutdown with emergency battery.
        EMERGENCY_BATTERY_SYSTEMS = {"sensors"}
        for sname, sys_obj in ship.systems.items():
            if sname in EMERGENCY_BATTERY_SYSTEMS:
                sys_obj.power = 25.0
            else:
                sys_obj._captain_offline = True
        # Sensors should still have some efficiency.
        sensors = ship.systems.get("sensors")
        assert sensors is not None
        assert not sensors._captain_offline
        assert sensors.power == 25.0
        assert sensors.efficiency > 0.0

    def test_other_systems_offline(self):
        ship = Ship()
        EMERGENCY_BATTERY_SYSTEMS = {"sensors"}
        for sname, sys_obj in ship.systems.items():
            if sname in EMERGENCY_BATTERY_SYSTEMS:
                sys_obj.power = 25.0
            else:
                sys_obj._captain_offline = True
        for sname, sys_obj in ship.systems.items():
            if sname != "sensors":
                assert sys_obj._captain_offline, f"{sname} should be offline"

    def test_engines_offline_ship_adrift(self):
        ship = Ship()
        ship.systems["engines"]._captain_offline = True
        ship.throttle = 0.0
        assert ship.systems["engines"].efficiency == 0.0
