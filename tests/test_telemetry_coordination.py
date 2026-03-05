"""Tests for server/telemetry.py — Section 1.2: Cross-Station Coordination Tracking."""
from __future__ import annotations

import server.telemetry as tel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _LogCapture:
    """Capture telemetry log calls."""

    def __init__(self):
        self.events: list[tuple[str, str, dict]] = []

    def __enter__(self):
        self._orig_log = tel._log
        tel._log = lambda cat, event, data: self.events.append((cat, event, data))
        return self

    def __exit__(self, *args):
        tel._log = self._orig_log

    def find(self, event: str) -> list[dict]:
        return [d for _, e, d in self.events if e == event]


def _init_players() -> None:
    tel.init({
        "captain": "Alice",
        "weapons": "Bob",
        "science": "Charlie",
        "operations": "Dave",
        "hazard_control": "Eve",
        "medical": "Frank",
        "security": "Grace",
        "comms": "Heidi",
        "helm": "Ivan",
    })


def _advance_time(seconds: float) -> None:
    """Advance game time by ticking."""
    ticks = int(seconds / 0.1)
    # Get current tick count (approximate)
    for _ in range(ticks):
        tel.tick(0, 0.1)  # tick_num doesn't matter for coordination


# ---------------------------------------------------------------------------
# Tests: coordination_initiated + coordination_responded
# ---------------------------------------------------------------------------


class TestCoordinationBasic:

    def test_initiate_creates_pending(self):
        _init_players()
        tel.coordination_initiated("captain_priority_target")
        pending = tel.get_pending_coordinations()
        assert len(pending) == 1
        assert pending[0].chain == "captain_priority_target"

    def test_respond_clears_pending(self):
        _init_players()
        tel.coordination_initiated("captain_priority_target")
        tel.coordination_responded("captain_priority_target")
        assert len(tel.get_pending_coordinations()) == 0

    def test_respond_logs_coordination_check(self):
        _init_players()
        tel.coordination_initiated("captain_priority_target")
        _advance_time(5.0)
        with _LogCapture() as cap:
            tel.coordination_responded("captain_priority_target")
        checks = cap.find("coordination_check")
        assert len(checks) == 1
        assert checks[0]["chain"] == "captain_priority_target"
        assert checks[0]["responded"] is True
        assert checks[0]["response_time_seconds"] >= 4.5

    def test_respond_without_pending_is_noop(self):
        _init_players()
        with _LogCapture() as cap:
            tel.coordination_responded("captain_priority_target")
        assert cap.find("coordination_check") == []

    def test_unknown_chain_ignored(self):
        _init_players()
        tel.coordination_initiated("nonexistent_chain")
        assert len(tel.get_pending_coordinations()) == 0


# ---------------------------------------------------------------------------
# Tests: timeout detection
# ---------------------------------------------------------------------------


class TestCoordinationTimeout:

    def test_timeout_fires_after_deadline(self):
        _init_players()
        tel.coordination_initiated("captain_priority_target")  # 30s timeout
        with _LogCapture() as cap:
            _advance_time(31.0)
        timeouts = cap.find("coordination_timeout")
        assert len(timeouts) == 1
        assert timeouts[0]["chain"] == "captain_priority_target"
        assert timeouts[0]["timeout_seconds"] == 30.0

    def test_timeout_not_before_deadline(self):
        _init_players()
        tel.coordination_initiated("casualty_to_medical")  # 60s timeout
        with _LogCapture() as cap:
            _advance_time(50.0)
        assert cap.find("coordination_timeout") == []

    def test_timeout_includes_manned_status(self):
        _init_players()
        tel.coordination_initiated("captain_priority_target")
        with _LogCapture() as cap:
            _advance_time(31.0)
        timeouts = cap.find("coordination_timeout")
        assert "responder_station_manned" in timeouts[0]
        assert timeouts[0]["responder_station_manned"] is True  # weapons is manned

    def test_timeout_unmanned_station(self):
        # Init with no weapons player
        tel.init({"captain": "Alice", "science": "Charlie"})
        tel.coordination_initiated("captain_priority_target")
        with _LogCapture() as cap:
            _advance_time(31.0)
        timeouts = cap.find("coordination_timeout")
        assert timeouts[0]["responder_station_manned"] is False

    def test_respond_prevents_timeout(self):
        _init_players()
        tel.coordination_initiated("captain_priority_target")
        _advance_time(5.0)
        tel.coordination_responded("captain_priority_target")
        with _LogCapture() as cap:
            _advance_time(30.0)
        assert cap.find("coordination_timeout") == []


# ---------------------------------------------------------------------------
# Tests: multiple pending chains
# ---------------------------------------------------------------------------


class TestMultipleChains:

    def test_multiple_pending(self):
        _init_players()
        tel.coordination_initiated("captain_priority_target")
        tel.coordination_initiated("fire_to_hazcon")
        assert len(tel.get_pending_coordinations()) == 2

    def test_respond_clears_correct_chain(self):
        _init_players()
        tel.coordination_initiated("captain_priority_target")
        tel.coordination_initiated("fire_to_hazcon")
        tel.coordination_responded("fire_to_hazcon")
        pending = tel.get_pending_coordinations()
        assert len(pending) == 1
        assert pending[0].chain == "captain_priority_target"

    def test_duplicate_chains_respond_oldest_first(self):
        _init_players()
        tel.coordination_initiated("fire_to_hazcon")
        _advance_time(5.0)
        tel.coordination_initiated("fire_to_hazcon")
        with _LogCapture() as cap:
            tel.coordination_responded("fire_to_hazcon")
        checks = cap.find("coordination_check")
        assert len(checks) == 1
        # Should respond to the older one (lower initiated_at)
        assert checks[0]["response_time_seconds"] >= 4.5
        # One should remain
        assert len(tel.get_pending_coordinations()) == 1


# ---------------------------------------------------------------------------
# Tests: all chain definitions valid
# ---------------------------------------------------------------------------


class TestChainDefinitions:

    def test_all_chains_have_valid_fields(self):
        for chain, (initiator, responder, timeout) in tel._CHAIN_DEFS.items():
            assert isinstance(chain, str)
            assert isinstance(initiator, str)
            assert isinstance(responder, str)
            assert isinstance(timeout, float)
            assert timeout > 0

    def test_ten_chains_defined(self):
        assert len(tel._CHAIN_DEFS) == 10


# ---------------------------------------------------------------------------
# Tests: reset
# ---------------------------------------------------------------------------


class TestCoordinationReset:

    def test_reset_clears_pending(self):
        _init_players()
        tel.coordination_initiated("captain_priority_target")
        tel.reset()
        assert len(tel.get_pending_coordinations()) == 0
