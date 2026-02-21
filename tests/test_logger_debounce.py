"""Tests for the game_logger debounce feature (log_debounced / _flush_debounced)."""
from __future__ import annotations

import pytest

from server.game_logger import GameLogger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def logger(tmp_path, monkeypatch):
    """Return an active GameLogger writing to a temp directory."""
    monkeypatch.setenv("STARBRIDGE_LOGGING", "true")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    lg = GameLogger()
    lg.start("test_mission", {"helm": "Tester"})
    yield lg
    if lg.is_active():
        lg.stop("victory", {})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoggerDebounce:

    def test_debounced_not_written_immediately(self, logger: GameLogger) -> None:
        """log_debounced should hold the event in _debounce_pending, not write it."""
        writes_before = getattr(logger, "_pending_writes", 0)
        logger.log_debounced("helm", "heading_changed", {"from": 0.0, "to": 90.0})
        assert logger._pending_writes == writes_before
        assert "helm.heading_changed" in logger._debounce_pending

    def test_debounced_flushed_by_set_tick_after_window(self, logger: GameLogger) -> None:
        """After the window elapses, set_tick() should flush the pending event."""
        logger.log_debounced("helm", "heading_changed", {"from": 0.0, "to": 45.0}, window_s=0.0)
        writes_before = logger._pending_writes
        logger.set_tick(5)   # triggers _flush_debounced()
        assert logger._pending_writes > writes_before
        assert "helm.heading_changed" not in logger._debounce_pending

    def test_debounced_preserves_from_updates_to(self, logger: GameLogger) -> None:
        """Repeated log_debounced calls should keep the original 'from' and update 'to'."""
        logger.log_debounced("helm", "throttle_changed", {"from": 0,  "to": 20})
        logger.log_debounced("helm", "throttle_changed", {"from": 20, "to": 50})
        logger.log_debounced("helm", "throttle_changed", {"from": 50, "to": 100})
        _, _, _, data = logger._debounce_pending["helm.throttle_changed"]
        assert data["from"] == 0       # original pre-drag value preserved
        assert data["to"]   == 100     # latest drag value

    def test_debounced_different_keys_independent(self, logger: GameLogger) -> None:
        """heading_changed and throttle_changed should be buffered independently."""
        logger.log_debounced("helm", "heading_changed",  {"from": 0.0, "to": 90.0})
        logger.log_debounced("helm", "throttle_changed", {"from": 0,   "to": 50})
        assert "helm.heading_changed"  in logger._debounce_pending
        assert "helm.throttle_changed" in logger._debounce_pending

    def test_debounced_noop_when_inactive(self) -> None:
        """log_debounced on an inactive logger should silently do nothing."""
        lg = GameLogger()
        lg.log_debounced("helm", "heading_changed", {"from": 0.0, "to": 45.0})
        assert not lg.is_active()
        assert len(lg._debounce_pending) == 0

    def test_debounced_flushed_on_stop(self, logger: GameLogger) -> None:
        """stop() should force-flush all pending debounced events before closing."""
        logger.log_debounced("helm", "throttle_changed", {"from": 0, "to": 75}, window_s=999.0)
        assert "helm.throttle_changed" in logger._debounce_pending
        writes_before = logger._pending_writes
        logger.stop("victory", {})
        # After stop, pending dict is empty and at least one extra write happened.
        assert "helm.throttle_changed" not in logger._debounce_pending
        assert logger._pending_writes > writes_before  # force-flush + session-end record

    def test_set_tick_flushes_elapsed_but_not_pending(self, logger: GameLogger) -> None:
        """set_tick() flushes elapsed events only; events with future deadlines are kept."""
        logger.log_debounced("helm", "heading_changed",  {"from": 0.0, "to": 90.0}, window_s=0.0)
        logger.log_debounced("helm", "throttle_changed", {"from": 0,   "to": 50},   window_s=999.0)
        logger.set_tick(1)
        # Elapsed (window=0) should be flushed; far-future should remain.
        assert "helm.heading_changed"  not in logger._debounce_pending
        assert "helm.throttle_changed" in logger._debounce_pending
