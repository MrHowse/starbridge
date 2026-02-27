"""Tests for Resource Rationing System — v0.07 Phase 6.6."""
from __future__ import annotations

import pytest

from server.models.rationing import (
    RATION_LEVELS,
    AllocationRequest,
    ResourceForecast,
)
from server.models.ship import Ship
from server.models.resources import ResourceStore
import server.game_loop_rationing as glrat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ship(
    fuel: float = 500.0,
    fuel_max: float = 1000.0,
    provisions: float = 200.0,
    provisions_max: float = 400.0,
) -> Ship:
    """Create a Ship with resources for testing."""
    ship = Ship()
    ship.resources = ResourceStore(
        fuel=fuel, fuel_max=fuel_max,
        medical_supplies=30.0, medical_supplies_max=60.0,
        repair_materials=25.0, repair_materials_max=50.0,
        drone_fuel=100.0, drone_fuel_max=200.0,
        drone_parts=6.0, drone_parts_max=12.0,
        ammunition=25.0, ammunition_max=50.0,
        provisions=provisions, provisions_max=provisions_max,
    )
    return ship


@pytest.fixture(autouse=True)
def _reset_rationing():
    """Reset rationing module state before each test."""
    glrat.reset()
    yield
    glrat.reset()


# ===========================================================================
# 1. Model — AllocationRequest (3 tests)
# ===========================================================================


class TestAllocationRequestModel:
    """AllocationRequest dataclass creation and serialisation."""

    def test_creation_defaults(self):
        req = AllocationRequest(
            id="alloc_1", source_station="engineering",
            resource_type="fuel", quantity=50.0, reason="Low fuel",
        )
        assert req.status == "pending"
        assert req.denial_reason == ""
        assert req.created_tick == 0

    def test_to_dict(self):
        req = AllocationRequest(
            id="alloc_1", source_station="medical",
            resource_type="medical_supplies", quantity=10.0,
            reason="Triage", status="approved", created_tick=42,
        )
        d = req.to_dict()
        assert d["id"] == "alloc_1"
        assert d["source_station"] == "medical"
        assert d["status"] == "approved"
        assert d["created_tick"] == 42

    def test_from_dict_round_trip(self):
        req = AllocationRequest(
            id="alloc_2", source_station="security",
            resource_type="ammunition", quantity=15.0,
            reason="Combat", status="denied", denial_reason="Low stock",
            created_tick=100, impact_preview=0.35,
        )
        d = req.to_dict()
        restored = AllocationRequest.from_dict(d)
        assert restored.id == req.id
        assert restored.status == "denied"
        assert restored.denial_reason == "Low stock"
        assert restored.impact_preview == pytest.approx(0.35)


# ===========================================================================
# 2. Model — ResourceForecast (1 test)
# ===========================================================================


class TestResourceForecastModel:
    """ResourceForecast dataclass and serialisation."""

    def test_to_dict(self):
        fc = ResourceForecast(
            resource_type="fuel", current=250.0, capacity=1000.0,
            burn_rate=0.5, seconds_to_depletion=500.0,
            colour="green", projected_at_destination=100.0,
        )
        d = fc.to_dict()
        assert d["resource_type"] == "fuel"
        assert d["burn_rate"] == pytest.approx(0.5, abs=0.001)
        assert d["seconds_to_depletion"] == pytest.approx(500.0)
        assert d["projected_at_destination"] == pytest.approx(100.0)


# ===========================================================================
# 3. Rationing Levels (5 tests)
# ===========================================================================


class TestRationingLevels:
    """Setting and querying ration levels."""

    def test_default_unrestricted(self):
        assert glrat.get_ration_level("fuel") == "unrestricted"

    def test_set_level_conserve(self):
        result = glrat.set_ration_level("fuel", "conserve")
        assert result["ok"]
        assert glrat.get_ration_level("fuel") == "conserve"

    def test_set_all_levels(self):
        for level in RATION_LEVELS:
            glrat.reset()
            if level != "unrestricted":
                result = glrat.set_ration_level("fuel", level)
                assert result["ok"]
                assert glrat.get_ration_level("fuel") == level

    def test_invalid_level_rejected(self):
        result = glrat.set_ration_level("fuel", "extreme")
        assert not result["ok"]
        assert result["error"] == "invalid_level"

    def test_invalid_resource_rejected(self):
        result = glrat.set_ration_level("unobtanium", "conserve")
        assert not result["ok"]
        assert result["error"] == "invalid_resource_type"


# ===========================================================================
# 4. Consumption Multipliers (5 tests)
# ===========================================================================


class TestConsumptionMultipliers:
    """Consumption and effectiveness multipliers per ration level."""

    def test_unrestricted_multiplier_is_one(self):
        assert glrat.get_consumption_multiplier("fuel") == 1.0
        assert glrat.get_effectiveness_multiplier("fuel") == 1.0

    def test_conserve_fuel_075(self):
        glrat.set_ration_level("fuel", "conserve")
        assert glrat.get_consumption_multiplier("fuel") == pytest.approx(0.75)

    def test_ration_provisions_050(self):
        glrat.set_ration_level("provisions", "ration")
        assert glrat.get_consumption_multiplier("provisions") == pytest.approx(0.50)

    def test_emergency_025(self):
        glrat.set_ration_level("ammunition", "emergency")
        assert glrat.get_consumption_multiplier("ammunition") == pytest.approx(0.25)

    def test_effectiveness_penalty_at_ration(self):
        glrat.set_ration_level("repair_materials", "ration")
        assert glrat.get_effectiveness_multiplier("repair_materials") == pytest.approx(0.75)

    def test_captain_override_restores_one(self):
        glrat.set_ration_level("fuel", "emergency")
        assert glrat.get_consumption_multiplier("fuel") == pytest.approx(0.25)
        result = glrat.captain_override("fuel")
        assert result["ok"]
        assert glrat.get_consumption_multiplier("fuel") == 1.0
        assert glrat.get_effectiveness_multiplier("fuel") == 1.0

    def test_captain_override_emits_event(self):
        glrat.set_ration_level("fuel", "ration")
        glrat.pop_pending_events()  # clear set_level event
        glrat.captain_override("fuel")
        events = glrat.pop_pending_events()
        assert len(events) == 1
        assert events[0]["type"] == "captain_override"
        assert events[0]["resource_type"] == "fuel"
        assert events[0]["old_level"] == "ration"


# ===========================================================================
# 5. Allocation Requests (6 tests)
# ===========================================================================


class TestAllocationRequests:
    """Cross-station resource allocation request queue."""

    def test_submit_request(self):
        result = glrat.submit_request("engineering", "fuel", 50.0, "Low fuel", 10)
        assert result["ok"]
        assert "request_id" in result
        pending = glrat.get_pending_requests()
        assert len(pending) == 1
        assert pending[0].resource_type == "fuel"

    def test_approve_request_transfers(self):
        ship = _make_ship(fuel=500.0)
        glrat.submit_request("engineering", "fuel", 50.0, "Low fuel", 10, ship)
        pending = glrat.get_pending_requests()
        req_id = pending[0].id

        result = glrat.approve_request(req_id, ship)
        assert result["ok"]
        assert ship.resources.fuel == pytest.approx(450.0)

    def test_deny_request_with_reason(self):
        glrat.submit_request("security", "ammunition", 10.0, "Combat", 5)
        pending = glrat.get_pending_requests()
        req_id = pending[0].id

        result = glrat.deny_request(req_id, "Reserves too low")
        assert result["ok"]
        assert len(glrat.get_pending_requests()) == 0

    def test_approve_insufficient_stock(self):
        ship = _make_ship(fuel=10.0)
        glrat.submit_request("engineering", "fuel", 50.0, "Low fuel", 10, ship)
        pending = glrat.get_pending_requests()

        result = glrat.approve_request(pending[0].id, ship)
        assert not result["ok"]
        assert result["error"] == "insufficient_stock"

    def test_auto_approve_uncrewed_above_threshold(self):
        ship = _make_ship(fuel=800.0, fuel_max=1000.0)  # 80% > 50%
        glrat.submit_request("engineering", "fuel", 50.0, "Refuel", 10, ship)
        glrat.auto_process_requests(ship, is_crewed=False)
        assert len(glrat.get_pending_requests()) == 0

    def test_auto_approve_queued_below_threshold(self):
        ship = _make_ship(fuel=100.0, fuel_max=1000.0)  # 10% < 50%
        glrat.submit_request("engineering", "fuel", 50.0, "Refuel", 10, ship)
        glrat.auto_process_requests(ship, is_crewed=False)
        # Still pending because stock is below threshold
        assert len(glrat.get_pending_requests()) == 1

    def test_multiple_pending_requests(self):
        glrat.submit_request("engineering", "fuel", 50.0, "Refuel", 1)
        glrat.submit_request("medical", "medical_supplies", 10.0, "Triage", 2)
        glrat.submit_request("security", "ammunition", 5.0, "Combat", 3)
        assert len(glrat.get_pending_requests()) == 3


# ===========================================================================
# 6. Forecasting (5 tests)
# ===========================================================================


class TestForecasting:
    """Resource burn-rate forecasting."""

    def test_burn_rate_smoothing(self):
        ship = _make_ship(fuel=500.0)
        # Record consumption spread over time
        for i in range(10):
            glrat.record_consumption("fuel", 1.0, float(i))
        glrat.update_forecasts(ship, -1.0, 10.0)
        forecasts = glrat.get_forecasts()
        assert "fuel" in forecasts
        assert forecasts["fuel"].burn_rate > 0

    def test_depletion_estimate(self):
        ship = _make_ship(fuel=100.0)
        # 10 units consumed over 10 seconds = 1 unit/sec
        for i in range(10):
            glrat.record_consumption("fuel", 1.0, float(i))
        glrat.update_forecasts(ship, -1.0, 10.0)
        fc = glrat.get_forecasts()["fuel"]
        # At 1 unit/sec, 100 units = ~100 seconds to depletion
        assert fc.seconds_to_depletion > 0
        assert fc.seconds_to_depletion == pytest.approx(100.0, rel=0.5)

    def test_colour_thresholds(self):
        # Low fuel = red
        ship = _make_ship(fuel=50.0, fuel_max=1000.0)  # 5%
        glrat.record_consumption("fuel", 1.0, 0.0)
        glrat.update_forecasts(ship, -1.0, 10.0)
        fc = glrat.get_forecasts()["fuel"]
        assert fc.colour in ("red", "flashing_red")

    def test_no_route_projected_minus_one(self):
        ship = _make_ship(fuel=500.0)
        glrat.record_consumption("fuel", 1.0, 0.0)
        glrat.update_forecasts(ship, -1.0, 10.0)
        fc = glrat.get_forecasts()["fuel"]
        assert fc.projected_at_destination == -1.0

    def test_projected_at_destination(self):
        ship = _make_ship(fuel=500.0)
        ship.velocity = 100.0  # 100 units/sec
        # 10 units consumed over 10 seconds = 1 unit/sec
        for i in range(10):
            glrat.record_consumption("fuel", 1.0, float(i))
        # Route distance 1000, velocity 100 → 10 seconds travel
        # Burn rate ~1 unit/sec → projected = 500 - 1*10 = 490
        glrat.update_forecasts(ship, 1000.0, 10.0)
        fc = glrat.get_forecasts()["fuel"]
        assert fc.projected_at_destination > 0
        assert fc.projected_at_destination < 500.0


# ===========================================================================
# 7. Save/Restore (2 tests)
# ===========================================================================


class TestSaveRestore:
    """Save and restore round-trip preserves rationing state."""

    def test_round_trip_levels_and_overrides(self):
        glrat.set_ration_level("fuel", "conserve")
        glrat.set_ration_level("provisions", "ration")
        glrat.captain_override("fuel")

        data = glrat.serialise()
        glrat.reset()
        assert glrat.get_ration_level("fuel") == "unrestricted"

        glrat.deserialise(data)
        assert glrat.get_ration_level("fuel") == "unrestricted"  # overridden
        assert glrat.get_ration_level("provisions") == "ration"
        # Captain override preserved
        assert glrat.get_consumption_multiplier("fuel") == 1.0

    def test_round_trip_requests(self):
        ship = _make_ship()
        glrat.submit_request("engineering", "fuel", 50.0, "Refuel", 10, ship)
        glrat.submit_request("medical", "medical_supplies", 10.0, "Triage", 20, ship)

        data = glrat.serialise()
        glrat.reset()
        assert len(glrat.get_pending_requests()) == 0

        glrat.deserialise(data)
        pending = glrat.get_pending_requests()
        assert len(pending) == 2
        assert pending[0].source_station == "engineering"


# ===========================================================================
# 8. Edge Cases (4 tests)
# ===========================================================================


class TestEdgeCases:
    """Edge cases and integration details."""

    def test_already_at_level(self):
        glrat.set_ration_level("fuel", "conserve")
        result = glrat.set_ration_level("fuel", "conserve")
        assert not result["ok"]
        assert result["error"] == "already_at_level"

    def test_approve_nonexistent_request(self):
        ship = _make_ship()
        result = glrat.approve_request("alloc_999", ship)
        assert not result["ok"]
        assert result["error"] == "request_not_found"

    def test_record_with_no_ration(self):
        """Recording consumption with no ration level set doesn't crash."""
        glrat.record_consumption("fuel", 10.0, 0.0)
        # No error, consumption still tracked for forecasting

    def test_set_level_emits_event(self):
        result = glrat.set_ration_level("fuel", "emergency")
        assert result["ok"]
        events = glrat.pop_pending_events()
        level_events = [e for e in events if e["type"] == "ration_level_changed"]
        assert len(level_events) == 1
        assert level_events[0]["new_level"] == "emergency"
        assert level_events[0]["old_level"] == "unrestricted"

    def test_deny_already_approved(self):
        ship = _make_ship(fuel=800.0)
        glrat.submit_request("engineering", "fuel", 50.0, "Refuel", 10, ship)
        req_id = glrat.get_pending_requests()[0].id
        glrat.approve_request(req_id, ship)
        result = glrat.deny_request(req_id, "Too late")
        assert not result["ok"]
        assert result["error"] == "request_not_pending"

    def test_tick_calls_forecasts(self):
        """tick() updates forecasts."""
        ship = _make_ship(fuel=500.0)
        glrat.record_consumption("fuel", 5.0, 0.0)
        glrat.tick(ship, 0.1, -1.0, True, 15.0)
        forecasts = glrat.get_forecasts()
        assert "fuel" in forecasts

    def test_crewed_does_not_auto_approve(self):
        """When crewed, auto_process_requests does nothing."""
        ship = _make_ship(fuel=800.0, fuel_max=1000.0)
        glrat.submit_request("engineering", "fuel", 50.0, "Refuel", 10, ship)
        glrat.auto_process_requests(ship, is_crewed=True)
        assert len(glrat.get_pending_requests()) == 1

    def test_submit_request_invalid_quantity(self):
        result = glrat.submit_request("engineering", "fuel", -10.0, "Neg", 0)
        assert not result["ok"]
        assert result["error"] == "invalid_quantity"

    def test_submit_request_impact_preview(self):
        ship = _make_ship(fuel=500.0, fuel_max=1000.0)
        result = glrat.submit_request("engineering", "fuel", 200.0, "Big request", 10, ship)
        assert result["ok"]
        req = glrat.get_pending_requests()[0]
        # (500 - 200) / 1000 = 0.3
        assert req.impact_preview == pytest.approx(0.3, abs=0.01)
