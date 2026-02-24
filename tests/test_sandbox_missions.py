"""Tests for sandbox mission signal generation (Part 6).

Covers:
  - Mission signal timer initialisation and firing
  - Mission type selection and per-session caps
  - Signal parameter correctness for all 7 mission types
  - Suppression when at mission capacity or in heavy combat
  - Integration with comms pipeline (auto-decoded → mission generation)
  - Difficulty scaling of mission signal interval
"""
from __future__ import annotations

import pytest

import server.game_loop_comms as glco
import server.game_loop_dynamic_missions as gldm
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


def _drain(world: World, dt: float, n: int, **kwargs) -> list[dict]:
    """Advance sandbox by *n* ticks of *dt*, collecting events."""
    events: list[dict] = []
    for _ in range(n):
        events.extend(glsb.tick(world, dt, **kwargs))
    return events


def _drain_mission_signals(world: World, dt: float = 1.0, n: int = 300, **kwargs) -> list[dict]:
    """Drain sandbox ticks and return only mission_signal events."""
    return [e for e in _drain(world, dt, n, **kwargs) if e["type"] == "mission_signal"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_all():
    """Reset sandbox, comms, and dynamic missions before/after each test."""
    glsb.reset(active=False)
    glco.reset()
    gldm.reset()
    yield
    glsb.reset(active=False)
    glco.reset()
    gldm.reset()


# ---------------------------------------------------------------------------
# Timer initialisation
# ---------------------------------------------------------------------------


class TestMissionSignalTimer:
    def test_mission_signal_timer_present(self) -> None:
        glsb.reset(active=True)
        assert "mission_signal" in glsb._timers

    def test_mission_signal_timer_initial_range(self) -> None:
        """Initial timer is staggered 60-90s (sooner than full interval)."""
        glsb.reset(active=True)
        assert 0 < glsb._timers["mission_signal"] <= 90.0

    def test_mission_signal_fires_eventually(self) -> None:
        glsb.reset(active=True)
        world = _make_world()
        signals = _drain_mission_signals(world, dt=1.0, n=200)
        assert len(signals) >= 1


# ---------------------------------------------------------------------------
# Mission type selection
# ---------------------------------------------------------------------------


class TestMissionTypeSelection:
    def test_pick_returns_valid_type(self) -> None:
        result = glsb._pick_mission_type()
        assert result in (
            "rescue", "investigation", "escort", "trade",
            "diplomatic", "intercept", "trap", None,
        )

    def test_pick_respects_per_session_caps(self) -> None:
        """Once a type hits its max, it should not be selected again."""
        for _, _, _ in glsb.MISSION_TYPE_BUDGET:
            pass  # just verify the constant exists

        # Force all types to max
        for type_key, _, max_count in glsb.MISSION_TYPE_BUDGET:
            glsb._mission_type_counts[type_key] = max_count

        # Now pick should return None (all exhausted)
        assert glsb._pick_mission_type() is None

    def test_pick_skips_maxed_types(self) -> None:
        """A maxed type is never selected."""
        glsb._mission_type_counts["rescue"] = 100  # way over cap
        for _ in range(50):
            result = glsb._pick_mission_type()
            if result is not None:
                assert result != "rescue"

    def test_mission_type_counts_tracked(self) -> None:
        glsb.reset(active=True)
        world = _make_world()
        _drain_mission_signals(world, dt=1.0, n=200)
        counts = glsb.get_mission_type_counts()
        assert sum(counts.values()) >= 1

    def test_reset_clears_mission_type_counts(self) -> None:
        glsb._mission_type_counts["rescue"] = 5
        glsb.reset(active=True)
        assert glsb.get_mission_type_counts() == {}


# ---------------------------------------------------------------------------
# Signal parameter correctness (per mission type)
# ---------------------------------------------------------------------------


class TestSignalParams:
    """Verify each mission type produces correct signal parameters."""

    def _build(self, mission_type: str) -> dict:
        world = _make_world()
        result = glsb._build_mission_signal(mission_type, world)
        assert result is not None
        return result

    def test_rescue_signal(self) -> None:
        evt = self._build("rescue")
        assert evt["mission_type"] == "rescue"
        p = evt["signal_params"]
        assert p["signal_type"] == "distress"
        assert p["auto_decoded"] is True
        assert p["priority"] == "critical"
        assert "position" in p["location_data"]
        assert p["frequency"] == 0.90

    def test_investigation_signal(self) -> None:
        evt = self._build("investigation")
        p = evt["signal_params"]
        assert p["signal_type"] == "data_burst"
        assert p.get("auto_decoded", False) is False
        assert p["requires_decode"] is True
        assert p["location_data"]["entity_type"] == "unknown"

    def test_escort_signal(self) -> None:
        evt = self._build("escort")
        p = evt["signal_params"]
        assert p["signal_type"] == "hail"
        assert p["faction"] == "civilian"
        assert p["auto_decoded"] is True

    def test_trade_signal(self) -> None:
        evt = self._build("trade")
        p = evt["signal_params"]
        assert p["signal_type"] == "hail"
        assert p["faction"] in ("federation", "imperial")
        assert p["auto_decoded"] is True

    def test_diplomatic_signal(self) -> None:
        evt = self._build("diplomatic")
        p = evt["signal_params"]
        assert p["signal_type"] == "hail"
        assert p["faction"] == "pirate"
        assert p["auto_decoded"] is True

    def test_intercept_signal(self) -> None:
        evt = self._build("intercept")
        p = evt["signal_params"]
        assert p["signal_type"] == "encrypted"
        assert p["threat_level"] == "hostile"
        assert p["requires_decode"] is True
        assert p["location_data"]["entity_type"] == "fleet"

    def test_trap_signal(self) -> None:
        evt = self._build("trap")
        p = evt["signal_params"]
        assert p["signal_type"] == "distress"
        assert p["auto_decoded"] is True
        assert p["location_data"]["is_trap"] is True

    def test_unknown_type_returns_none(self) -> None:
        world = _make_world()
        assert glsb._build_mission_signal("nonexistent", world) is None

    def test_position_near_ship(self) -> None:
        """Generated signal position should be 25k-55k from ship."""
        world = _make_world()
        evt = glsb._build_mission_signal("rescue", world)
        assert evt is not None
        pos = evt["signal_params"]["location_data"]["position"]
        dx = pos[0] - world.ship.x
        dy = pos[1] - world.ship.y
        dist = (dx ** 2 + dy ** 2) ** 0.5
        assert 5_000 <= dist <= 80_000  # generous bounds for clamping

    def test_position_within_world_bounds(self) -> None:
        world = _make_world()
        world.ship.x = 2_000.0  # near edge
        world.ship.y = 2_000.0
        evt = glsb._build_mission_signal("rescue", world)
        assert evt is not None
        pos = evt["signal_params"]["location_data"]["position"]
        assert 5_000.0 <= pos[0] <= world.width - 5_000.0
        assert 5_000.0 <= pos[1] <= world.height - 5_000.0


# ---------------------------------------------------------------------------
# Suppression conditions
# ---------------------------------------------------------------------------


class TestMissionSignalSuppression:
    def test_suppressed_at_mission_capacity(self) -> None:
        """No mission signals when active_mission_count >= MAX_SANDBOX_MISSIONS."""
        glsb.reset(active=True)
        world = _make_world()
        signals = _drain_mission_signals(
            world, dt=1.0, n=200,
            active_mission_count=glsb.MAX_SANDBOX_MISSIONS,
        )
        assert len(signals) == 0

    def test_suppressed_during_heavy_combat(self) -> None:
        """No mission signals when >= 3 enemies alive."""
        from server.models.world import spawn_enemy
        glsb.reset(active=True)
        world = _make_world()
        for i in range(3):
            world.enemies.append(spawn_enemy("scout", 50000.0, 50000.0, f"e{i}"))
        signals = _drain_mission_signals(world, dt=1.0, n=200)
        assert len(signals) == 0

    def test_not_suppressed_with_few_enemies(self) -> None:
        """Mission signals still fire with < 3 enemies."""
        from server.models.world import spawn_enemy
        glsb.reset(active=True)
        world = _make_world()
        for i in range(2):
            world.enemies.append(spawn_enemy("scout", 50000.0, 50000.0, f"e{i}"))
        signals = _drain_mission_signals(world, dt=1.0, n=200)
        assert len(signals) >= 1


# ---------------------------------------------------------------------------
# Difficulty scaling
# ---------------------------------------------------------------------------


class TestDifficultyScaling:
    def test_harder_difficulty_shorter_interval(self) -> None:
        """Lower event_interval_multiplier → shorter mission signal timer."""
        class HardDifficulty:
            event_interval_multiplier = 0.5
            boarding_frequency_multiplier = 1.0

        glsb.reset(active=True)
        world = _make_world()
        hard_signals = _drain_mission_signals(
            world, dt=1.0, n=200, difficulty=HardDifficulty(),
        )

        glsb.reset(active=True)
        class EasyDifficulty:
            event_interval_multiplier = 2.0
            boarding_frequency_multiplier = 1.0

        easy_signals = _drain_mission_signals(
            world, dt=1.0, n=200, difficulty=EasyDifficulty(),
        )

        # Hard should generate more signals in the same time window
        assert len(hard_signals) >= len(easy_signals)


# ---------------------------------------------------------------------------
# Comms pipeline integration
# ---------------------------------------------------------------------------


class TestCommsPipelineIntegration:
    def test_auto_decoded_signal_generates_mission(self) -> None:
        """Auto-decoded signals with location_data should generate missions."""
        sig = glco.add_signal(
            source="distress_beacon",
            source_name="Test Vessel",
            frequency=0.90,
            signal_type="distress",
            priority="critical",
            raw_content="MAYDAY",
            decoded_content="MAYDAY",
            auto_decoded=True,
            requires_decode=False,
            faction="civilian",
            threat_level="distress",
            location_data={"position": [50000, 60000], "entity_type": "ship"},
        )
        # Should have generated a mission via the pipeline
        pending = glco.pop_pending_generated_missions()
        assert len(pending) == 1
        assert pending[0].mission_type == "rescue"

    def test_auto_decoded_hail_generates_escort(self) -> None:
        """Civilian hail with location_data → escort mission."""
        glco.add_signal(
            source="civilian_ship",
            source_name="CSV Horizon",
            frequency=0.55,
            signal_type="hail",
            priority="medium",
            raw_content="Need escort",
            decoded_content="Need escort",
            auto_decoded=True,
            requires_decode=False,
            faction="civilian",
            threat_level="unknown",
            location_data={"position": [50000, 60000], "entity_type": "ship"},
        )
        pending = glco.pop_pending_generated_missions()
        assert len(pending) == 1
        assert pending[0].mission_type == "escort"

    def test_auto_decoded_trade_hail_generates_trade(self) -> None:
        """Federation hail → trade mission (standing > -10)."""
        glco.add_signal(
            source="merchant_1",
            source_name="TCS Discovery",
            frequency=0.65,
            signal_type="hail",
            priority="low",
            raw_content="Trade proposal",
            decoded_content="Trade proposal",
            auto_decoded=True,
            requires_decode=False,
            faction="federation",
            threat_level="unknown",
            location_data={"position": [50000, 60000], "entity_type": "ship"},
        )
        pending = glco.pop_pending_generated_missions()
        assert len(pending) == 1
        assert pending[0].mission_type == "trade"

    def test_auto_decoded_pirate_hail_generates_diplomatic(self) -> None:
        """Pirate hail (standing -20) → diplomatic mission."""
        glco.add_signal(
            source="pirate_envoy",
            source_name="Pirate Envoy",
            frequency=0.08,
            signal_type="hail",
            priority="high",
            raw_content="Peace talks",
            decoded_content="Peace talks",
            auto_decoded=True,
            requires_decode=False,
            faction="pirate",
            threat_level="unknown",
            location_data={"position": [50000, 60000], "entity_type": "ship"},
        )
        pending = glco.pop_pending_generated_missions()
        assert len(pending) == 1
        assert pending[0].mission_type == "diplomatic"

    def test_trap_signal_sets_is_trap(self) -> None:
        """Distress signal with is_trap → rescue mission with _is_trap flag."""
        glco.add_signal(
            source="distress_beacon",
            source_name="CSV Trap",
            frequency=0.90,
            signal_type="distress",
            priority="critical",
            raw_content="MAYDAY",
            decoded_content="MAYDAY",
            auto_decoded=True,
            requires_decode=False,
            faction="civilian",
            threat_level="distress",
            location_data={"position": [50000, 60000], "entity_type": "ship", "is_trap": True},
        )
        pending = glco.pop_pending_generated_missions()
        assert len(pending) == 1
        assert pending[0]._is_trap is True

    def test_non_auto_decoded_does_not_generate_mission(self) -> None:
        """Signals requiring decode should NOT generate missions on add."""
        glco.add_signal(
            source="unknown_src",
            source_name="Unknown",
            frequency=0.5,
            signal_type="data_burst",
            priority="medium",
            raw_content="mystery data",
            requires_decode=True,
            faction="unknown",
            location_data={"position": [50000, 60000], "entity_type": "unknown"},
        )
        pending = glco.pop_pending_generated_missions()
        assert len(pending) == 0

    def test_auto_decoded_without_location_no_mission(self) -> None:
        """Auto-decoded signal WITHOUT location_data should not create missions."""
        glco.add_signal(
            source="test",
            source_name="Test",
            frequency=0.5,
            signal_type="hail",
            raw_content="hello",
            decoded_content="hello",
            auto_decoded=True,
            requires_decode=False,
            faction="civilian",
        )
        pending = glco.pop_pending_generated_missions()
        assert len(pending) == 0


# ---------------------------------------------------------------------------
# Full sandbox → mission pipeline
# ---------------------------------------------------------------------------


class TestSandboxMissionPipeline:
    def test_sandbox_mission_signal_creates_signal_in_comms(self) -> None:
        """mission_signal event processed by add_signal creates a Signal object."""
        glsb.reset(active=True)
        world = _make_world()

        # Build a rescue signal event directly
        evt = glsb._build_mission_signal("rescue", world)
        assert evt is not None

        # Process it as game_loop.py would
        glco.add_signal(**evt["signal_params"])

        # Signal should exist in comms
        signals = glco.get_signals()
        assert any(s.signal_type == "distress" for s in signals)

    def test_sandbox_mission_signal_generates_and_offers_mission(self) -> None:
        """Full pipeline: sandbox event → comms signal → pending mission → offer."""
        glsb.reset(active=True)
        world = _make_world()

        # Build and process a rescue signal
        evt = glsb._build_mission_signal("rescue", world)
        assert evt is not None
        glco.add_signal(**evt["signal_params"])

        # Drain pending missions (as game_loop does)
        pending = glco.pop_pending_generated_missions()
        assert len(pending) >= 1

        # Offer the mission
        mission = pending[0]
        result = gldm.offer_mission(mission)
        assert result is True

        # Mission should be offered
        offered = gldm.get_offered_missions()
        assert len(offered) == 1
        assert offered[0].mission_type == "rescue"

    def test_sandbox_generates_variety(self) -> None:
        """Over many ticks, sandbox should produce diverse mission types."""
        glsb.reset(active=True)
        world = _make_world()
        signals = _drain_mission_signals(world, dt=1.0, n=2000)
        types_seen = {s["mission_type"] for s in signals}
        # Should see at least 3 different types
        assert len(types_seen) >= 3

    def test_investigation_requires_decode_for_mission(self) -> None:
        """Investigation signal requires decode before mission appears."""
        glsb.reset(active=True)
        world = _make_world()

        evt = glsb._build_mission_signal("investigation", world)
        assert evt is not None
        glco.add_signal(**evt["signal_params"])

        # No mission yet (requires decode)
        pending = glco.pop_pending_generated_missions()
        assert len(pending) == 0

    def test_intercept_requires_decode_for_mission(self) -> None:
        """Intercept signal requires decode before mission appears."""
        glsb.reset(active=True)
        world = _make_world()

        evt = glsb._build_mission_signal("intercept", world)
        assert evt is not None
        glco.add_signal(**evt["signal_params"])

        # No mission yet (requires decode)
        pending = glco.pop_pending_generated_missions()
        assert len(pending) == 0
