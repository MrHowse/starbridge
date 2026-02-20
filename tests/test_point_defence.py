"""
Tests for the point defence system (P4 — Gap Closure).

point_defence is a passive system that intercepts incoming (non-player) torpedoes.
At efficiency 1.0 the intercept chance is 30%; at 0.0 there is no intercept.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from server.models.ship import Ship
from server.models.world import Torpedo, World


# ---------------------------------------------------------------------------
# System exists in default ship
# ---------------------------------------------------------------------------


class TestPointDefenceSystemExists:
    """point_defence is a standard ship system."""

    def test_point_defence_in_default_ship(self):
        ship = Ship()
        assert "point_defence" in ship.systems

    def test_point_defence_starts_at_full_power(self):
        ship = Ship()
        assert ship.systems["point_defence"].power == pytest.approx(100.0)

    def test_point_defence_starts_at_full_health(self):
        ship = Ship()
        assert ship.systems["point_defence"].health == pytest.approx(100.0)

    def test_point_defence_efficiency_at_full_power(self):
        ship = Ship()
        assert ship.systems["point_defence"].efficiency == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Intercept chance
# ---------------------------------------------------------------------------


def _make_incoming_torpedo(owner: str = "enemy_1") -> Torpedo:
    return Torpedo(
        id="torp_incoming",
        owner=owner,
        x=50_000.0,
        y=50_000.0,
        heading=0.0,
    )


class TestPointDefenceIntercept:
    """tick_torpedoes uses point_defence to intercept non-player torpedoes."""

    def _run_tick(self, ship: Ship, torp: Torpedo, rng_value: float) -> list[dict]:
        """Helper: add torp to world, tick once with mocked rng."""
        from server.game_loop_weapons import tick_torpedoes

        world = World(ship=ship)
        world.torpedoes.append(torp)

        with patch("server.game_loop_weapons._rng") as mock_rng:
            mock_rng.random.return_value = rng_value
            events = tick_torpedoes(world, ship)

        return events, world

    def test_intercept_chance_is_30_pct_at_full_efficiency(self):
        """At efficiency 1.0, intercept_chance = 1.0 × 0.3 = 0.3."""
        ship = Ship()
        assert ship.systems["point_defence"].efficiency == pytest.approx(1.0)
        # rng < 0.3 → intercept
        torp = _make_incoming_torpedo()
        events, world = self._run_tick(ship, torp, rng_value=0.29)
        pd_events = [e for e in events if e.get("type") == "pd_intercept"]
        assert len(pd_events) == 1

    def test_no_intercept_above_threshold(self):
        """rng ≥ 0.3 → no intercept at full efficiency."""
        ship = Ship()
        torp = _make_incoming_torpedo()
        events, world = self._run_tick(ship, torp, rng_value=0.31)
        pd_events = [e for e in events if e.get("type") == "pd_intercept"]
        assert len(pd_events) == 0

    def test_no_intercept_at_zero_efficiency(self):
        """At efficiency 0.0, intercept_chance = 0 → no intercept."""
        ship = Ship()
        ship.systems["point_defence"].power = 0.0
        assert ship.systems["point_defence"].efficiency == pytest.approx(0.0)
        torp = _make_incoming_torpedo()
        events, world = self._run_tick(ship, torp, rng_value=0.0)
        pd_events = [e for e in events if e.get("type") == "pd_intercept"]
        assert len(pd_events) == 0

    def test_intercepted_torpedo_removed_from_world(self):
        """Intercepted torpedo is pruned from world.torpedoes."""
        ship = Ship()
        torp = _make_incoming_torpedo()
        _, world = self._run_tick(ship, torp, rng_value=0.0)  # guaranteed intercept at full eff
        assert len(world.torpedoes) == 0

    def test_player_torpedo_not_intercepted(self):
        """point_defence only targets non-player torpedoes."""
        ship = Ship()
        torp = _make_incoming_torpedo(owner="player")
        # Even with rng=0.0 (would intercept anything), player torps are exempt
        events, world = self._run_tick(ship, torp, rng_value=0.0)
        pd_events = [e for e in events if e.get("type") == "pd_intercept"]
        assert len(pd_events) == 0

    def test_no_ship_no_intercept(self):
        """When ship is None, no intercept occurs (backward compat)."""
        from server.game_loop_weapons import tick_torpedoes

        torp = _make_incoming_torpedo()
        world = World()
        world.torpedoes.append(torp)
        events = tick_torpedoes(world, ship=None)
        pd_events = [e for e in events if isinstance(e, dict) and e.get("type") == "pd_intercept"]
        assert len(pd_events) == 0
