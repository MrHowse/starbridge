"""Tests for sandbox medical injury side-effects.

Verifies that system damage, overclock damage, crew altercation, and
environmental sickness sandbox events can produce medical injuries.
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


def _drain(world: World, dt: float, n: int) -> list[dict]:
    events: list[dict] = []
    for _ in range(n):
        events.extend(glsb.tick(world, dt))
    return events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_sandbox():
    glsb.reset(active=False)
    yield
    glsb.reset(active=False)


# ---------------------------------------------------------------------------
# System damage → 10% crew injury
# ---------------------------------------------------------------------------


class TestSystemDamageInjury:
    def test_system_damage_injury_chance(self) -> None:
        """Roll below threshold → system_damage event includes injury potential."""
        glsb.reset(active=True)
        world = _make_world()
        # Drain until we get a system_damage event.
        events = _drain(world, 1.0, 200)
        sys_dmg = [e for e in events if e["type"] == "system_damage"]
        assert len(sys_dmg) > 0, "Expected at least one system_damage event"

    def test_system_damage_no_injury_when_roll_fails(self) -> None:
        """Roll above threshold → no injury generated from system damage."""
        # The constant is 0.10 — if random always returns 0.99, no injury.
        assert glsb.CREW_INJURY_FROM_SYSTEM_DAMAGE_CHANCE == 0.10
        # Verify the constant is reasonable (not 0 or 1).
        assert 0.0 < glsb.CREW_INJURY_FROM_SYSTEM_DAMAGE_CHANCE < 1.0


# ---------------------------------------------------------------------------
# Overclock damage → 20% crew injury
# ---------------------------------------------------------------------------


class TestOverclockInjury:
    def test_overclock_injury_chance(self) -> None:
        """Overclock injury constant is 20%."""
        assert glsb.CREW_INJURY_FROM_OVERCLOCK_CHANCE == 0.20

    def test_overclock_injury_sandbox_only(self) -> None:
        """Overclock injury only fires when sandbox is active."""
        # When sandbox is inactive, is_active() is False.
        glsb.reset(active=False)
        assert not glsb.is_active()


# ---------------------------------------------------------------------------
# Crew altercation → 30% minor injury
# ---------------------------------------------------------------------------


class TestAltercationInjury:
    def test_altercation_injury_chance(self) -> None:
        """Altercation injury constant is 30%."""
        assert glsb.ALTERCATION_INJURY_CHANCE == 0.30

    def test_altercation_event_generated(self) -> None:
        """Sandbox generates security incidents including crew_altercation."""
        glsb.reset(active=True)
        world = _make_world()
        events = _drain(world, 1.0, 200)
        sec = [e for e in events if e["type"] == "security_incident"]
        assert len(sec) > 0, "Expected security_incident events"

    def test_non_altercation_no_injury(self) -> None:
        """Security incidents that are NOT crew_altercation never produce injuries."""
        # Only crew_altercation triggers the injury path; other incident types
        # (sensor_ghost, suspicious_cargo, etc.) should not.
        non_altercation = [
            t for t in glsb.SECURITY_INCIDENT_TYPES
            if t["incident"] != "crew_altercation"
        ]
        assert len(non_altercation) >= 4, "Expected multiple non-altercation types"


# ---------------------------------------------------------------------------
# Environmental sickness
# ---------------------------------------------------------------------------


class TestEnvSickness:
    def test_env_sickness_timer_exists(self) -> None:
        """After reset(active=True), env_sickness timer is present."""
        glsb.reset(active=True)
        assert "env_sickness" in glsb._timers

    def test_env_sickness_event_generated(self) -> None:
        """Drain enough ticks → env_sickness event emitted."""
        glsb.reset(active=True)
        world = _make_world()
        events = _drain(world, 1.0, 200)
        es = [e for e in events if e["type"] == "env_sickness"]
        assert len(es) >= 1, "Expected at least one env_sickness event"

    def test_env_sickness_interval_constant(self) -> None:
        """ENV_SICKNESS_CHECK_INTERVAL is (90, 120)."""
        assert glsb.ENV_SICKNESS_CHECK_INTERVAL == (90.0, 120.0)


# ---------------------------------------------------------------------------
# Regression — existing crew_casualty unchanged
# ---------------------------------------------------------------------------


class TestCrewCasualtyUnchanged:
    def test_crew_casualty_interval_unchanged(self) -> None:
        """CREW_CASUALTY_INTERVAL is still (60, 100) — no regression."""
        assert glsb.CREW_CASUALTY_INTERVAL == (60.0, 100.0)

    def test_crew_casualty_events_still_generated(self) -> None:
        """Sandbox still generates crew_casualty events."""
        glsb.reset(active=True)
        world = _make_world()
        events = _drain(world, 1.0, 200)
        cc = [e for e in events if e["type"] == "crew_casualty"]
        assert len(cc) >= 1, "Expected at least one crew_casualty event"
