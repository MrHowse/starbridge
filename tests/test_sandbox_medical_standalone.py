"""Tests for standalone sandbox medical event generator.

Validates the sandbox_medical_event timer that produces injury events
independent of other side-effect triggers.
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
# Standalone Medical Event
# ===========================================================================


class TestSandboxMedicalEvent:
    def test_medical_event_timer_exists(self) -> None:
        glsb.reset(active=True)
        assert "sandbox_medical_event" in glsb._timers

    def test_medical_event_fires(self) -> None:
        glsb.reset(active=True)
        glsb._timers["sandbox_medical_event"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        meds = [e for e in events if e["type"] == "sandbox_medical_event"]
        assert len(meds) == 1
        assert "cause" in meds[0]
        assert "deck" in meds[0]
        assert "severity_scale" in meds[0]
        assert "label" in meds[0]
        assert meds[0]["severity_scale"] > 0.0

    def test_medical_event_interval_constant(self) -> None:
        assert glsb.SANDBOX_MEDICAL_EVENT_INTERVAL == (90.0, 120.0)

    def test_medical_event_cause_valid(self) -> None:
        """Cause should come from _MEDICAL_EVENT_CAUSES."""
        glsb.reset(active=True)
        glsb._timers["sandbox_medical_event"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        meds = [e for e in events if e["type"] == "sandbox_medical_event"]
        assert len(meds) == 1
        valid_causes = [m["cause"] for m in glsb._MEDICAL_EVENT_CAUSES]
        assert meds[0]["cause"] in valid_causes

    def test_medical_event_deck_valid(self) -> None:
        """Deck should come from CREW_DECKS."""
        glsb.reset(active=True)
        glsb._timers["sandbox_medical_event"] = 0.05
        world = _make_world()
        events = glsb.tick(world, 0.1)
        meds = [e for e in events if e["type"] == "sandbox_medical_event"]
        assert len(meds) == 1
        assert meds[0]["deck"] in glsb.CREW_DECKS

    def test_medical_event_timer_resets(self) -> None:
        glsb.reset(active=True)
        glsb._timers["sandbox_medical_event"] = 0.05
        world = _make_world()
        glsb.tick(world, 0.1)
        assert glsb._timers["sandbox_medical_event"] > 10.0


# ===========================================================================
# Medical Side-Effect Probability Constants
# ===========================================================================


class TestMedicalSideEffectProbabilities:
    def test_system_damage_injury_chance_boosted(self) -> None:
        """System damage injury chance raised to 20%."""
        assert glsb.CREW_INJURY_FROM_SYSTEM_DAMAGE_CHANCE == 0.20

    def test_overclock_injury_chance_boosted(self) -> None:
        """Overclock injury chance raised to 35%."""
        assert glsb.CREW_INJURY_FROM_OVERCLOCK_CHANCE == 0.35

    def test_altercation_injury_chance_boosted(self) -> None:
        """Altercation injury chance raised to 40%."""
        assert glsb.ALTERCATION_INJURY_CHANCE == 0.40

    def test_env_sickness_interval_unchanged(self) -> None:
        """ENV_SICKNESS_CHECK_INTERVAL should still be (90, 120)."""
        assert glsb.ENV_SICKNESS_CHECK_INTERVAL == (90.0, 120.0)
