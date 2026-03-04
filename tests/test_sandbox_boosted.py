"""Tests for boosted sandbox event generators (EW, Flight Ops, Captain).

Validates the new event types added to reduce idle time for Electronic Warfare,
Flight Ops, and Captain stations.
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
    return w


@pytest.fixture(autouse=True)
def _reset():
    glsb.reset(active=False)
    yield
    glsb.reset(active=False)


# ===========================================================================
# EW Intercept
# ===========================================================================


class TestSandboxEWIntercept:
    def test_ew_intercept_timer_exists(self) -> None:
        glsb.reset(active=True)
        assert "sandbox_ew_intercept" in glsb._timers

    def test_ew_intercept_fires(self) -> None:
        glsb.reset(active=True)
        glsb._timers["sandbox_ew_intercept"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        intc = [e for e in events if e["type"] == "sandbox_ew_intercept"]
        assert len(intc) == 1
        assert "faction" in intc[0]
        assert intc[0]["faction"] in ("imperial", "rebel", "pirate")
        assert "intel" in intc[0]
        assert len(intc[0]["intel"]) > 0

    def test_ew_intercept_interval_constant(self) -> None:
        assert glsb.SANDBOX_EW_INTERCEPT_INTERVAL == (120.0, 180.0)

    def test_ew_jamming_interval_reduced(self) -> None:
        """EW jamming interval should be reduced from (180,240) to (90,120)."""
        assert glsb.ENEMY_JAMMING_INTERVAL == (90.0, 120.0)

    def test_ew_intercept_timer_resets(self) -> None:
        glsb.reset(active=True)
        glsb._timers["sandbox_ew_intercept"] = 0.05
        world = _make_world()
        glsb.tick(world, 0.1)
        assert glsb._timers["sandbox_ew_intercept"] > 10.0


# ===========================================================================
# Flight Contact
# ===========================================================================


class TestSandboxFlightContact:
    def test_flight_contact_timer_exists(self) -> None:
        glsb.reset(active=True)
        assert "sandbox_flight_contact" in glsb._timers

    def test_flight_contact_fires(self) -> None:
        glsb.reset(active=True)
        glsb._timers["sandbox_flight_contact"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        fcs = [e for e in events if e["type"] == "sandbox_flight_contact"]
        assert len(fcs) == 1
        assert "x" in fcs[0]
        assert "y" in fcs[0]
        assert "id" in fcs[0]
        assert "label" in fcs[0]
        assert fcs[0]["id"].startswith("sb_fc")

    def test_flight_contact_in_bounds(self) -> None:
        """Contact position should be within world bounds."""
        glsb.reset(active=True)
        glsb._timers["sandbox_flight_contact"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        fcs = [e for e in events if e["type"] == "sandbox_flight_contact"]
        assert len(fcs) == 1
        assert 0.0 <= fcs[0]["x"] <= world.width
        assert 0.0 <= fcs[0]["y"] <= world.height

    def test_flight_contact_interval_constant(self) -> None:
        assert glsb.SANDBOX_FLIGHT_CONTACT_INTERVAL == (90.0, 120.0)

    def test_drone_opportunity_interval_reduced(self) -> None:
        """Drone opportunity interval should be reduced from (120,180) to (75,120)."""
        assert glsb.DRONE_OPPORTUNITY_INTERVAL == (75.0, 120.0)

    def test_flight_contact_labels(self) -> None:
        """FLIGHT_CONTACT_LABELS should have at least 4 entries."""
        assert len(glsb.FLIGHT_CONTACT_LABELS) >= 4


# ===========================================================================
# Captain Decision
# ===========================================================================


class TestSandboxCaptainDecision:
    def test_captain_decision_timer_exists(self) -> None:
        glsb.reset(active=True)
        assert "sandbox_captain_decision" in glsb._timers

    def test_captain_decision_fires(self) -> None:
        glsb.reset(active=True)
        glsb._timers["sandbox_captain_decision"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        decs = [e for e in events if e["type"] == "sandbox_captain_decision"]
        assert len(decs) == 1
        assert "decision_id" in decs[0]
        assert decs[0]["decision_id"].startswith("sb_dec_")
        assert "prompt" in decs[0]
        assert "options" in decs[0]
        assert isinstance(decs[0]["options"], list)
        assert len(decs[0]["options"]) >= 2

    def test_captain_decision_interval_constant(self) -> None:
        assert glsb.SANDBOX_CAPTAIN_DECISION_INTERVAL == (90.0, 120.0)

    def test_captain_decision_counter_increments(self) -> None:
        glsb.reset(active=True)
        world = _make_world()
        glsb._timers["sandbox_captain_decision"] = 0.05
        events1 = glsb.tick(world, 0.1)
        d1 = [e for e in events1 if e["type"] == "sandbox_captain_decision"]
        glsb._timers["sandbox_captain_decision"] = 0.05
        events2 = glsb.tick(world, 0.1)
        d2 = [e for e in events2 if e["type"] == "sandbox_captain_decision"]
        assert d1[0]["decision_id"] != d2[0]["decision_id"]
