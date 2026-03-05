"""Tests for server/telemetry.py — Section 1.5: Hazard/Environment State Tracking."""
from __future__ import annotations

from unittest.mock import MagicMock

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


def _mock_ship_with_interior():
    """Create a mock ship with interior for environment tracking."""
    ship = MagicMock()
    ship.systems = {"beams": MagicMock(power=100, health=100)}
    ship.resources = None
    interior = MagicMock()
    interior.rooms = {
        "bridge": MagicMock(evacuated=False),
        "engine_room": MagicMock(evacuated=True),
    }
    ship.interior = interior
    return ship


def _init() -> None:
    tel.init({"weapons": "Alice"})


# ---------------------------------------------------------------------------
# Tests: environment snapshots
# ---------------------------------------------------------------------------


class TestEnvironmentSnapshot:

    def test_snapshot_at_300_ticks(self):
        _init()
        ship = _mock_ship_with_interior()
        with _LogCapture() as cap:
            for i in range(1, 301):
                tel.tick(i, 0.1, ship=ship)
        snaps = cap.find("environment_snapshot")
        assert len(snaps) == 1

    def test_no_snapshot_before_300(self):
        _init()
        ship = _mock_ship_with_interior()
        with _LogCapture() as cap:
            for i in range(1, 200):
                tel.tick(i, 0.1, ship=ship)
        assert cap.find("environment_snapshot") == []

    def test_evacuated_rooms_listed(self):
        _init()
        ship = _mock_ship_with_interior()
        with _LogCapture() as cap:
            for i in range(1, 301):
                tel.tick(i, 0.1, ship=ship)
        snap = cap.find("environment_snapshot")[0]
        assert "engine_room" in snap["rooms_evacuated"]
        assert "bridge" not in snap["rooms_evacuated"]

    def test_snapshot_has_required_fields(self):
        _init()
        ship = _mock_ship_with_interior()
        with _LogCapture() as cap:
            for i in range(1, 301):
                tel.tick(i, 0.1, ship=ship)
        snap = cap.find("environment_snapshot")[0]
        assert "active_fires" in snap
        assert "breaches" in snap
        assert "rooms_evacuated" in snap
        assert "structural_integrity" in snap

    def test_no_crash_without_interior(self):
        _init()
        ship = MagicMock()
        ship.systems = {"beams": MagicMock(power=100, health=100)}
        ship.resources = None
        ship.interior = None
        with _LogCapture() as cap:
            for i in range(1, 301):
                tel.tick(i, 0.1, ship=ship)
        # No environment snapshot emitted (needs interior)
        assert cap.find("environment_snapshot") == []
