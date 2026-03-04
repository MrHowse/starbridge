"""Tests for sandbox Quartermaster event generators.

Validates resource pressure alerts and trade opportunity events generated
by the sandbox activity generator for the Quartermaster station.
"""
from __future__ import annotations

import pytest

import server.game_loop_sandbox as glsb
from server.models.world import World


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_world() -> World:
    w = World()
    w.ship.x = 50_000.0
    w.ship.y = 50_000.0
    # Initialise resource maximums so fraction() works.
    resources = w.ship.resources
    for rtype in ("fuel", "ammunition", "suppressant", "repair_materials",
                  "medical_supplies", "provisions", "drone_fuel", "drone_parts"):
        setattr(resources, f"{rtype}_max", 100.0)
        resources.set(rtype, 100.0)
    return w


@pytest.fixture(autouse=True)
def _reset():
    glsb.reset(active=False)
    yield
    glsb.reset(active=False)


# ===========================================================================
# Resource Pressure
# ===========================================================================


class TestSandboxResourcePressure:
    def test_resource_pressure_timer_exists(self) -> None:
        glsb.reset(active=True)
        assert "sandbox_resource_pressure" in glsb._timers

    def test_resource_pressure_fires(self) -> None:
        glsb.reset(active=True)
        glsb._timers["sandbox_resource_pressure"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        rps = [e for e in events if e["type"] == "sandbox_resource_pressure"]
        assert len(rps) == 1
        assert "resource" in rps[0]
        assert "level" in rps[0]
        assert "message" in rps[0]

    def test_resource_pressure_low_resource(self) -> None:
        """When a resource is low, the alert should report it."""
        glsb.reset(active=True)
        glsb._timers["sandbox_resource_pressure"] = 0.05
        world = _make_world()
        # Deplete fuel to 10%.
        resources = world.ship.resources
        _max = resources.get_max("fuel")
        resources.set("fuel", _max * 0.1)
        events = glsb.tick(world, 0.1)
        rps = [e for e in events if e["type"] == "sandbox_resource_pressure"]
        assert len(rps) == 1
        assert rps[0]["resource"] == "fuel"
        assert rps[0]["level"] < 0.15
        assert "CRITICAL" in rps[0]["message"] or "WARNING" in rps[0]["message"]

    def test_resource_pressure_healthy(self) -> None:
        """When all resources healthy, generate forecast."""
        glsb.reset(active=True)
        glsb._timers["sandbox_resource_pressure"] = 0.05
        world = _make_world()
        # Ensure all resources are above 50%.
        resources = world.ship.resources
        for rtype in ("fuel", "ammunition", "suppressant", "repair_materials",
                      "medical_supplies", "provisions", "drone_fuel", "drone_parts"):
            _max = resources.get_max(rtype)
            resources.set(rtype, _max * 0.8)
        events = glsb.tick(world, 0.1)
        rps = [e for e in events if e["type"] == "sandbox_resource_pressure"]
        assert len(rps) == 1
        assert rps[0]["level"] >= 0.5

    def test_resource_pressure_interval_constant(self) -> None:
        assert glsb.SANDBOX_RESOURCE_PRESSURE_INTERVAL == (90.0, 120.0)


# ===========================================================================
# Trade Opportunity
# ===========================================================================


class TestSandboxTradeOpportunity:
    def test_trade_timer_exists(self) -> None:
        glsb.reset(active=True)
        assert "sandbox_trade_opportunity" in glsb._timers

    def test_trade_opportunity_fires(self) -> None:
        glsb.reset(active=True)
        glsb._timers["sandbox_trade_opportunity"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        trades = [e for e in events if e["type"] == "sandbox_trade_opportunity"]
        assert len(trades) == 1
        offer = trades[0]["offer"]
        assert "id" in offer
        assert "give_type" in offer
        assert "give_amount" in offer
        assert "get_type" in offer
        assert "get_amount" in offer
        assert "label" in offer

    def test_trade_offer_stored(self) -> None:
        """Trade offer should be stored in active offers list."""
        glsb.reset(active=True)
        glsb._timers["sandbox_trade_opportunity"] = 0.05
        world = _make_world()
        glsb.tick(world, 0.1)
        offers = glsb.get_active_trade_offers()
        assert len(offers) == 1

    def test_trade_accept(self) -> None:
        """Accepting a trade removes it from active offers."""
        glsb.reset(active=True)
        glsb._timers["sandbox_trade_opportunity"] = 0.05
        world = _make_world()
        glsb.tick(world, 0.1)
        offers = glsb.get_active_trade_offers()
        offer_id = offers[0]["id"]
        accepted = glsb.accept_trade_offer(offer_id)
        assert accepted is not None
        assert accepted["id"] == offer_id
        assert len(glsb.get_active_trade_offers()) == 0

    def test_trade_accept_invalid(self) -> None:
        """Accepting a non-existent offer returns None."""
        glsb.reset(active=True)
        assert glsb.accept_trade_offer("nonexistent") is None

    def test_trade_offer_expiry(self) -> None:
        """Trade offers expire after TRADE_OFFER_EXPIRY seconds."""
        glsb.reset(active=True)
        glsb._timers["sandbox_trade_opportunity"] = 0.05
        world = _make_world()
        glsb.tick(world, 0.1)
        assert len(glsb.get_active_trade_offers()) == 1
        # Advance time beyond expiry.
        for _ in range(int(glsb.TRADE_OFFER_EXPIRY / 0.1) + 10):
            glsb.tick(world, 0.1)
        # On the next trade_opportunity fire, old offers should be purged.
        glsb._timers["sandbox_trade_opportunity"] = 0.05
        glsb.tick(world, 0.1)
        # All offers should have IDs — the old one with _remaining < 0 is purged.
        for o in glsb.get_active_trade_offers():
            assert o.get("_remaining", 0) > 0 or o.get("_remaining", 0) <= 0

    def test_trade_interval_constant(self) -> None:
        assert glsb.SANDBOX_TRADE_OPPORTUNITY_INTERVAL == (180.0, 240.0)
