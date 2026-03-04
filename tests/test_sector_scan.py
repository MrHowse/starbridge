"""Tests for server/game_loop_science_scan.py — v0.05d."""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

import server.game_loop_science_scan as glss
from server.game_loop_science_scan import (
    COMBAT_INTERRUPT_RANGE,
    INTERRUPT_COOLDOWN,
    LONG_RANGE_DURATION,
    PHASE_THRESHOLDS,
    SECTOR_SWEEP_DURATION,
)
from server.models.sector import Rect, Sector, SectorFeature, SectorGrid, SectorProperties, SectorVisibility


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_world(enemies=None, sector_grid=None, ship_x=50_000.0, ship_y=50_000.0,
                torpedoes=None, hull=120.0):
    """Build a minimal mock World for scan tests."""
    ship = MagicMock()
    ship.x = ship_x
    ship.y = ship_y
    ship.hull = hull

    world = MagicMock()
    world.ship = ship
    world.enemies = enemies or []
    world.creatures = []
    world.stations = []
    world.torpedoes = torpedoes or []
    world.sector_grid = sector_grid
    return world


def _torpedo(owner="enemy1"):
    """Build a minimal mock torpedo."""
    t = MagicMock()
    t.owner = owner
    return t


def _make_grid_2x1() -> SectorGrid:
    """Two-sector 2×1 grid: A1 (left) and B1 (right)."""
    sectors = {
        "A1": Sector(
            id="A1", name="Alpha One",
            grid_position=(0, 0),
            world_bounds=Rect(0, 0, 100_000, 100_000),
        ),
        "B1": Sector(
            id="B1", name="Bravo One",
            grid_position=(1, 0),
            world_bounds=Rect(100_000, 0, 200_000, 100_000),
        ),
    }
    return SectorGrid(sectors=sectors, grid_size=(2, 1))


def _enemy_at(x: float, y: float):
    e = MagicMock()
    e.x = x
    e.y = y
    return e


# ---------------------------------------------------------------------------
# Auto-reset between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset():
    glss.reset()
    yield
    glss.reset()


# ---------------------------------------------------------------------------
# TestReset
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_clears_state(self) -> None:
        glss.start_scan("sector", "em", "A1")
        glss.reset()
        assert glss.is_active() is False

    def test_initial_not_active(self) -> None:
        assert glss.is_active() is False

    def test_reset_clears_build_progress(self) -> None:
        glss.start_scan("sector", "em", "A1")
        glss.reset()
        assert glss.build_progress() == {"active": False}


# ---------------------------------------------------------------------------
# TestStartScan
# ---------------------------------------------------------------------------

class TestStartScan:
    def test_returns_true_on_first_start(self) -> None:
        assert glss.start_scan("sector", "em", "A1") is True

    def test_is_active_after_start(self) -> None:
        glss.start_scan("sector", "em", "A1")
        assert glss.is_active() is True

    def test_returns_false_if_already_active(self) -> None:
        glss.start_scan("sector", "em", "A1")
        assert glss.start_scan("long_range", "grav", "A1") is False

    def test_sector_scale_stored(self) -> None:
        glss.start_scan("sector", "grav", "X1")
        p = glss.build_progress()
        assert p["scale"] == "sector"
        assert p["mode"] == "grav"
        assert p["sector_id"] == "X1"

    def test_long_range_scale_stored(self) -> None:
        glss.start_scan("long_range", "bio", "A1", ["B1", "C1"])
        p = glss.build_progress()
        assert p["scale"] == "long_range"
        assert p["mode"] == "bio"

    def test_adjacent_ids_stored(self) -> None:
        glss.start_scan("long_range", "em", "A1", ["B1", "C1"])
        # Internal state — verify via tick visibility change rather than peeking
        assert glss.is_active() is True

    def test_progress_zero_at_start(self) -> None:
        glss.start_scan("sector", "em", "A1")
        assert glss.build_progress()["progress"] == 0.0


# ---------------------------------------------------------------------------
# TestCancelScan
# ---------------------------------------------------------------------------

class TestCancelScan:
    def test_cancel_when_active_returns_true(self) -> None:
        glss.start_scan("sector", "em", "A1")
        assert glss.cancel_scan() is True

    def test_cancel_deactivates(self) -> None:
        glss.start_scan("sector", "em", "A1")
        glss.cancel_scan()
        assert glss.is_active() is False

    def test_cancel_when_inactive_returns_false(self) -> None:
        assert glss.cancel_scan() is False

    def test_can_start_after_cancel(self) -> None:
        glss.start_scan("sector", "em", "A1")
        glss.cancel_scan()
        assert glss.start_scan("sector", "em", "B1") is True


# ---------------------------------------------------------------------------
# TestInterruptResponse
# ---------------------------------------------------------------------------

class TestInterruptResponse:
    def test_continue_resumes_scan(self) -> None:
        glss.start_scan("sector", "em", "A1")
        # Advance past 1s grace period before injecting torpedo
        glss.tick(1.1, _make_world())
        world = _make_world(torpedoes=[_torpedo()])
        glss.tick(0.1, world)
        assert glss.build_progress().get("interrupted") is True
        glss.set_interrupt_response(True)
        assert glss.build_progress().get("interrupted") is False
        assert glss.is_active() is True

    def test_abort_cancels_scan(self) -> None:
        glss.start_scan("sector", "em", "A1")
        glss.tick(1.1, _make_world())
        world = _make_world(torpedoes=[_torpedo()])
        glss.tick(0.1, world)
        glss.set_interrupt_response(False)
        assert glss.is_active() is False

    def test_no_interrupt_during_grace_period(self) -> None:
        """Combat detected within the 1s grace period should not interrupt."""
        glss.start_scan("sector", "em", "A1")
        world = _make_world(torpedoes=[_torpedo()])
        glss.tick(0.5, world)
        assert glss.build_progress().get("interrupted") is False
        assert glss.is_active() is True

    def test_response_no_op_when_not_interrupted(self) -> None:
        glss.start_scan("sector", "em", "A1")
        # No enemy — not interrupted
        glss.set_interrupt_response(False)
        assert glss.is_active() is True

    def test_response_no_op_when_inactive(self) -> None:
        # Should not raise
        glss.set_interrupt_response(True)


# ---------------------------------------------------------------------------
# TestBuildProgress
# ---------------------------------------------------------------------------

class TestBuildProgress:
    def test_inactive_returns_active_false(self) -> None:
        p = glss.build_progress()
        assert p == {"active": False}

    def test_active_returns_all_fields(self) -> None:
        glss.start_scan("sector", "em", "A1")
        p = glss.build_progress()
        assert p["active"] is True
        assert "scale" in p
        assert "mode" in p
        assert "progress" in p
        assert "phase" in p
        assert "sector_id" in p
        assert "interrupted" in p

    def test_progress_advances(self) -> None:
        glss.start_scan("sector", "em", "A1")
        world = _make_world()
        glss.tick(10.0, world)
        p = glss.build_progress()
        assert p["progress"] > 0.0

    def test_phase_advances_at_threshold(self) -> None:
        glss.start_scan("sector", "em", "A1")
        world = _make_world()
        # Advance to just past 25%
        dt = SECTOR_SWEEP_DURATION * 0.27
        glss.tick(dt, world)
        p = glss.build_progress()
        assert p["phase"] >= 1

    def test_after_cancel_returns_active_false(self) -> None:
        glss.start_scan("sector", "em", "A1")
        glss.cancel_scan()
        assert glss.build_progress() == {"active": False}


# ---------------------------------------------------------------------------
# TestGetScanIndicator
# ---------------------------------------------------------------------------

class TestGetScanIndicator:
    def test_none_when_inactive(self) -> None:
        assert glss.get_scan_indicator() is None

    def test_sector_sweep_label(self) -> None:
        glss.start_scan("sector", "em", "A1")
        ind = glss.get_scan_indicator()
        assert ind is not None
        assert "Sector sweep" in ind

    def test_long_range_label(self) -> None:
        glss.start_scan("long_range", "em", "A1")
        ind = glss.get_scan_indicator()
        assert ind is not None
        assert "Long-range scan" in ind

    def test_contains_progress_percent(self) -> None:
        glss.start_scan("sector", "em", "A1")
        world = _make_world()
        glss.tick(10.0, world)
        ind = glss.get_scan_indicator()
        assert "%" in ind

    def test_none_after_cancel(self) -> None:
        glss.start_scan("sector", "em", "A1")
        glss.cancel_scan()
        assert glss.get_scan_indicator() is None


# ---------------------------------------------------------------------------
# TestTick
# ---------------------------------------------------------------------------

class TestTick:
    def test_empty_when_inactive(self) -> None:
        world = _make_world()
        events = glss.tick(1.0, world)
        assert events == []

    def test_progress_event_every_tick(self) -> None:
        glss.start_scan("sector", "em", "A1")
        world = _make_world()
        events = glss.tick(1.0, world)
        types = [e["type"] for e in events]
        assert "progress" in types

    def test_complete_event_at_end(self) -> None:
        glss.start_scan("sector", "em", "A1")
        world = _make_world()
        # Run to completion
        events = glss.tick(SECTOR_SWEEP_DURATION + 1.0, world)
        types = [e["type"] for e in events]
        assert "complete" in types

    def test_complete_event_carries_metadata(self) -> None:
        glss.start_scan("sector", "grav", "A1")
        world = _make_world()
        events = glss.tick(SECTOR_SWEEP_DURATION + 1.0, world)
        complete_evt = next(e for e in events if e["type"] == "complete")
        assert complete_evt["scale"] == "sector"
        assert complete_evt["sector_id"] == "A1"
        assert complete_evt["mode"] == "grav"

    def test_no_tick_after_complete(self) -> None:
        glss.start_scan("sector", "em", "A1")
        world = _make_world()
        glss.tick(SECTOR_SWEEP_DURATION + 1.0, world)
        events = glss.tick(1.0, world)
        assert events == []

    def test_no_tick_when_interrupted(self) -> None:
        glss.start_scan("sector", "em", "A1")
        glss.tick(1.1, _make_world())  # past grace period
        world = _make_world(torpedoes=[_torpedo()])
        glss.tick(0.1, world)  # triggers interrupt
        events = glss.tick(1.0, world)
        assert events == []

    def test_interrupted_event_when_torpedo_incoming(self) -> None:
        glss.start_scan("sector", "em", "A1")
        glss.tick(1.1, _make_world())  # past grace period
        world = _make_world(torpedoes=[_torpedo()])
        events = glss.tick(0.1, world)
        types = [e["type"] for e in events]
        assert "interrupted" in types

    def test_no_interrupt_when_enemy_nearby_but_no_threat(self) -> None:
        """Proximity alone no longer triggers interrupt."""
        glss.start_scan("sector", "em", "A1")
        glss.tick(1.1, _make_world())
        enemy = _enemy_at(50_000, 50_000)  # close but no torpedoes/damage/boarding
        world = _make_world(enemies=[enemy])
        events = glss.tick(0.1, world)
        types = [e["type"] for e in events]
        assert "interrupted" not in types

    def test_no_interrupt_when_no_threats(self) -> None:
        glss.start_scan("sector", "em", "A1")
        world = _make_world()
        events = glss.tick(0.1, world)
        types = [e["type"] for e in events]
        assert "interrupted" not in types

    def test_sector_visibility_changed_emitted_on_phase_cross(self) -> None:
        grid = _make_grid_2x1()
        world = _make_world(sector_grid=grid)
        glss.start_scan("sector", "em", "A1")
        # Advance past first phase threshold (25%)
        events = glss.tick(SECTOR_SWEEP_DURATION * 0.3, world)
        types = [e["type"] for e in events]
        assert "sector_visibility_changed" in types

    def test_empty_when_cancelled(self) -> None:
        glss.start_scan("sector", "em", "A1")
        glss.cancel_scan()
        world = _make_world()
        events = glss.tick(1.0, world)
        assert events == []


# ---------------------------------------------------------------------------
# TestSectorVisibility — sector sweep
# ---------------------------------------------------------------------------

class TestSectorSweepVisibility:
    def test_sector_goes_to_scanned_at_phase_0(self) -> None:
        grid = _make_grid_2x1()
        assert grid.sectors["A1"].visibility == SectorVisibility.UNKNOWN
        world = _make_world(sector_grid=grid)
        glss.start_scan("sector", "em", "A1")
        glss.tick(SECTOR_SWEEP_DURATION * 0.3, world)
        # Phase 0 should have been applied → at least Scanned
        assert grid.sectors["A1"].visibility in (
            SectorVisibility.SCANNED, SectorVisibility.SURVEYED,
        )

    def test_sector_goes_to_surveyed_at_phase_3(self) -> None:
        grid = _make_grid_2x1()
        world = _make_world(sector_grid=grid)
        glss.start_scan("sector", "em", "A1")
        glss.tick(SECTOR_SWEEP_DURATION * 0.8, world)
        assert grid.sectors["A1"].visibility == SectorVisibility.SURVEYED

    def test_active_sector_not_downgraded(self) -> None:
        grid = _make_grid_2x1()
        grid.sectors["A1"].visibility = SectorVisibility.ACTIVE
        world = _make_world(sector_grid=grid)
        glss.start_scan("sector", "em", "A1")
        glss.tick(SECTOR_SWEEP_DURATION, world)
        # Should remain Active, not downgraded to Surveyed
        assert grid.sectors["A1"].visibility == SectorVisibility.ACTIVE

    def test_visited_upgraded_to_surveyed(self) -> None:
        grid = _make_grid_2x1()
        grid.sectors["A1"].visibility = SectorVisibility.VISITED
        world = _make_world(sector_grid=grid)
        glss.start_scan("sector", "em", "A1")
        glss.tick(SECTOR_SWEEP_DURATION, world)
        assert grid.sectors["A1"].visibility == SectorVisibility.SURVEYED

    def test_adjacent_sector_unaffected_by_sweep(self) -> None:
        grid = _make_grid_2x1()
        world = _make_world(sector_grid=grid)
        glss.start_scan("sector", "em", "A1")
        glss.tick(SECTOR_SWEEP_DURATION, world)
        # B1 should remain Unknown — only A1 was swept
        assert grid.sectors["B1"].visibility == SectorVisibility.UNKNOWN


# ---------------------------------------------------------------------------
# TestLongRangeVisibility
# ---------------------------------------------------------------------------

class TestLongRangeVisibility:
    def test_adjacent_goes_to_scanned(self) -> None:
        grid = _make_grid_2x1()
        world = _make_world(sector_grid=grid)
        glss.start_scan("long_range", "em", "A1", ["B1"])
        # Advance to first phase
        glss.tick(LONG_RANGE_DURATION * 0.3, world)
        assert grid.sectors["B1"].visibility == SectorVisibility.SCANNED

    def test_current_sector_unaffected_by_long_range(self) -> None:
        grid = _make_grid_2x1()
        world = _make_world(sector_grid=grid)
        glss.start_scan("long_range", "em", "A1", ["B1"])
        glss.tick(LONG_RANGE_DURATION, world)
        # A1 is the "current sector" — long_range doesn't survey it
        assert grid.sectors["A1"].visibility == SectorVisibility.UNKNOWN

    def test_long_range_complete_sets_scanned(self) -> None:
        grid = _make_grid_2x1()
        world = _make_world(sector_grid=grid)
        glss.start_scan("long_range", "sub", "A1", ["B1"])
        glss.tick(LONG_RANGE_DURATION + 1.0, world)
        assert grid.sectors["B1"].visibility == SectorVisibility.SCANNED

    def test_already_scanned_not_downgraded(self) -> None:
        grid = _make_grid_2x1()
        grid.sectors["B1"].visibility = SectorVisibility.SURVEYED
        world = _make_world(sector_grid=grid)
        glss.start_scan("long_range", "em", "A1", ["B1"])
        glss.tick(LONG_RANGE_DURATION, world)
        # SURVEYED should not be downgraded to SCANNED
        assert grid.sectors["B1"].visibility == SectorVisibility.SURVEYED


# ---------------------------------------------------------------------------
# TestDuration
# ---------------------------------------------------------------------------

class TestDuration:
    def test_sector_duration(self) -> None:
        glss.start_scan("sector", "em", "A1")
        assert glss.build_progress()["progress"] == 0.0
        world = _make_world()
        glss.tick(SECTOR_SWEEP_DURATION - 0.5, world)
        assert glss.build_progress()["progress"] < 100.0

    def test_long_range_duration(self) -> None:
        glss.start_scan("long_range", "em", "A1")
        assert glss.build_progress()["progress"] == 0.0
        world = _make_world()
        glss.tick(LONG_RANGE_DURATION - 0.5, world)
        assert glss.build_progress()["progress"] < 100.0

    def test_sector_completes_at_full_duration(self) -> None:
        glss.start_scan("sector", "em", "A1")
        world = _make_world()
        events = glss.tick(SECTOR_SWEEP_DURATION + 1.0, world)
        assert any(e["type"] == "complete" for e in events)

    def test_long_range_completes_at_full_duration(self) -> None:
        glss.start_scan("long_range", "em", "A1")
        world = _make_world()
        events = glss.tick(LONG_RANGE_DURATION + 1.0, world)
        assert any(e["type"] == "complete" for e in events)


# ---------------------------------------------------------------------------
# Scan results summary
# ---------------------------------------------------------------------------


class TestScanResults:
    def test_sector_scan_complete_includes_results(self) -> None:
        """Completion event should contain a results dict."""
        grid = _make_grid_2x1()
        enemy = _enemy_at(50_000, 50_000)
        world = _make_world(enemies=[enemy], sector_grid=grid)
        glss.start_scan("sector", "em", "A1")
        events = glss.tick(SECTOR_SWEEP_DURATION + 1.0, world)
        complete = next(e for e in events if e["type"] == "complete")
        assert "results" in complete
        assert complete["results"]["contacts"] == 1
        assert "1 contact detected" in complete["results"]["details"]

    def test_sector_scan_results_counts_features(self) -> None:
        """Features in the sector should be counted."""
        grid = _make_grid_2x1()
        feat = SectorFeature(id="f1", type="anomaly", position=(50_000, 50_000))
        grid.sectors["A1"].features.append(feat)
        world = _make_world(sector_grid=grid)
        glss.start_scan("sector", "em", "A1")
        events = glss.tick(SECTOR_SWEEP_DURATION + 1.0, world)
        complete = next(e for e in events if e["type"] == "complete")
        assert complete["results"]["features"] == 1
        assert "1 feature found" in complete["results"]["details"]

    def test_sector_scan_results_empty_sector(self) -> None:
        """Empty sector reports no contacts or features."""
        grid = _make_grid_2x1()
        world = _make_world(sector_grid=grid)
        glss.start_scan("sector", "em", "A1")
        events = glss.tick(SECTOR_SWEEP_DURATION + 1.0, world)
        complete = next(e for e in events if e["type"] == "complete")
        assert complete["results"]["contacts"] == 0
        assert complete["results"]["features"] == 0
        assert "no contacts or features detected" in complete["results"]["details"]

    def test_sector_scan_results_ignores_out_of_bounds(self) -> None:
        """Enemy outside the scanned sector is not counted."""
        grid = _make_grid_2x1()
        # Place enemy in B1, scan A1.
        enemy = _enemy_at(150_000, 50_000)
        world = _make_world(enemies=[enemy], sector_grid=grid)
        glss.start_scan("sector", "em", "A1")
        events = glss.tick(SECTOR_SWEEP_DURATION + 1.0, world)
        complete = next(e for e in events if e["type"] == "complete")
        assert complete["results"]["contacts"] == 0


# ---------------------------------------------------------------------------
# TestInterruptCooldown
# ---------------------------------------------------------------------------


class TestInterruptCooldown:
    def test_no_reinterrupt_during_cooldown(self) -> None:
        """After clicking continue, no interrupt fires for 10s."""
        glss.start_scan("sector", "em", "A1")
        glss.tick(1.1, _make_world())
        # Trigger first interrupt
        world = _make_world(torpedoes=[_torpedo()])
        glss.tick(0.1, world)
        assert glss.build_progress().get("interrupted") is True
        # Continue — starts cooldown
        glss.set_interrupt_response(True)
        # Tick during cooldown — should NOT interrupt even with torpedo
        events = glss.tick(0.1, world)
        types = [e["type"] for e in events]
        assert "interrupted" not in types

    def test_interrupt_fires_after_cooldown_expires(self) -> None:
        """After cooldown expires, torpedo triggers interrupt again."""
        glss.start_scan("sector", "em", "A1")
        glss.tick(1.1, _make_world())
        world = _make_world(torpedoes=[_torpedo()])
        glss.tick(0.1, world)
        glss.set_interrupt_response(True)
        # Advance past cooldown
        events = glss.tick(INTERRUPT_COOLDOWN + 0.1, world)
        types = [e["type"] for e in events]
        assert "interrupted" in types

    def test_cooldown_resets_on_each_continue(self) -> None:
        """Each continue click resets the cooldown timer."""
        glss.start_scan("sector", "em", "A1")
        glss.tick(1.1, _make_world())
        world = _make_world(torpedoes=[_torpedo()])
        # First interrupt + continue
        glss.tick(0.1, world)
        glss.set_interrupt_response(True)
        # Wait 5s (half cooldown), no interrupt
        events = glss.tick(5.0, world)
        assert "interrupted" not in [e["type"] for e in events]
        # Wait 6s more (past original 10s) — triggers second interrupt
        events = glss.tick(6.0, world)
        assert "interrupted" in [e["type"] for e in events]
        # Continue again — cooldown resets
        glss.set_interrupt_response(True)
        events = glss.tick(5.0, world)
        assert "interrupted" not in [e["type"] for e in events]

    def test_continue_count_increments(self) -> None:
        glss.start_scan("sector", "em", "A1")
        glss.tick(1.1, _make_world())
        world = _make_world(torpedoes=[_torpedo()])
        glss.tick(0.1, world)
        glss.set_interrupt_response(True)
        assert glss.build_progress()["continue_count"] == 1
        # Wait for cooldown, trigger again
        glss.tick(INTERRUPT_COOLDOWN + 0.1, world)
        glss.set_interrupt_response(True)
        assert glss.build_progress()["continue_count"] == 2


# ---------------------------------------------------------------------------
# TestAutoContinue
# ---------------------------------------------------------------------------


class TestAutoContinue:
    def test_auto_continue_emits_auto_continued(self) -> None:
        """When auto_continue is on, torpedo yields auto_continued not interrupted."""
        glss.start_scan("sector", "em", "A1")
        glss.set_auto_continue(True)
        glss.tick(1.1, _make_world())
        world = _make_world(torpedoes=[_torpedo()])
        events = glss.tick(0.1, world)
        types = [e["type"] for e in events]
        assert "auto_continued" in types
        assert "interrupted" not in types

    def test_auto_continue_sets_cooldown(self) -> None:
        """Auto-continue should set cooldown to prevent rapid events."""
        glss.start_scan("sector", "em", "A1")
        glss.set_auto_continue(True)
        glss.tick(1.1, _make_world())
        world = _make_world(torpedoes=[_torpedo()])
        # First auto_continued
        events = glss.tick(0.1, world)
        assert "auto_continued" in [e["type"] for e in events]
        # Immediately tick again — cooldown active, no auto_continued
        events = glss.tick(0.1, world)
        assert "auto_continued" not in [e["type"] for e in events]

    def test_auto_continue_does_not_pause_scan(self) -> None:
        """Scan should keep running when auto_continue fires."""
        glss.start_scan("sector", "em", "A1")
        glss.set_auto_continue(True)
        glss.tick(1.1, _make_world())
        world = _make_world(torpedoes=[_torpedo()])
        glss.tick(0.1, world)
        assert glss.is_active() is True
        assert glss.build_progress().get("interrupted") is False

    def test_set_auto_continue_works(self) -> None:
        glss.start_scan("sector", "em", "A1")
        assert glss.build_progress()["auto_continue"] is False
        glss.set_auto_continue(True)
        assert glss.build_progress()["auto_continue"] is True
        glss.set_auto_continue(False)
        assert glss.build_progress()["auto_continue"] is False

    def test_set_auto_continue_noop_when_no_scan(self) -> None:
        """Should not raise when no scan is active."""
        glss.set_auto_continue(True)  # no crash


# ---------------------------------------------------------------------------
# TestThreatFiltering
# ---------------------------------------------------------------------------


class TestThreatFiltering:
    def test_no_interrupt_for_nearby_enemy_alone(self) -> None:
        """Enemy proximity without torpedo/damage/boarding does not interrupt."""
        glss.start_scan("sector", "em", "A1")
        glss.tick(1.1, _make_world())
        enemy = _enemy_at(50_000, 50_000)
        world = _make_world(enemies=[enemy])
        events = glss.tick(0.1, world)
        assert "interrupted" not in [e["type"] for e in events]

    def test_interrupt_for_incoming_torpedo(self) -> None:
        """Enemy torpedo in flight triggers interrupt."""
        glss.start_scan("sector", "em", "A1")
        glss.tick(1.1, _make_world())
        world = _make_world(torpedoes=[_torpedo("enemy1")])
        events = glss.tick(0.1, world)
        assert "interrupted" in [e["type"] for e in events]

    def test_no_interrupt_for_player_torpedo(self) -> None:
        """Player's own torpedo does not trigger interrupt."""
        glss.start_scan("sector", "em", "A1")
        glss.tick(1.1, _make_world())
        world = _make_world(torpedoes=[_torpedo("player")])
        events = glss.tick(0.1, world)
        assert "interrupted" not in [e["type"] for e in events]

    def test_interrupt_for_hull_damage(self) -> None:
        """Hull damage between ticks triggers interrupt."""
        glss.start_scan("sector", "em", "A1")
        # First tick sets _last_hull
        glss.tick(1.1, _make_world(hull=120.0))
        # Next tick with lower hull
        world = _make_world(hull=110.0)
        events = glss.tick(0.1, world)
        assert "interrupted" in [e["type"] for e in events]

    def test_no_interrupt_when_hull_unchanged(self) -> None:
        """No hull drop → no interrupt."""
        glss.start_scan("sector", "em", "A1")
        glss.tick(1.1, _make_world(hull=120.0))
        world = _make_world(hull=120.0)
        events = glss.tick(0.1, world)
        assert "interrupted" not in [e["type"] for e in events]

    def test_interrupt_for_boarding(self) -> None:
        """Active boarding triggers interrupt."""
        import server.game_loop_security as gls
        old = gls._boarding_active
        try:
            gls._boarding_active = True
            glss.start_scan("sector", "em", "A1")
            glss.tick(1.1, _make_world())
            events = glss.tick(0.1, _make_world())
            assert "interrupted" in [e["type"] for e in events]
        finally:
            gls._boarding_active = old
