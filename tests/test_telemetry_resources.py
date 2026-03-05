"""Tests for server/telemetry.py — Section 1.4: Resource Tracking."""
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


def _mock_ship():
    """Create a mock ship with systems and resources."""
    ship = MagicMock()
    ship.systems = {
        "beams": MagicMock(power=100, health=95),
        "shields": MagicMock(power=100, health=100),
        "engines": MagicMock(power=100, health=70),
    }
    res = MagicMock()
    res.fuel = 80.0
    res.fuel_max = 100.0
    ship.resources = res
    ship.interior = None
    return ship


def _init() -> None:
    tel.init({"weapons": "Alice"})


# ---------------------------------------------------------------------------
# Tests: resource snapshots
# ---------------------------------------------------------------------------


class TestResourceSnapshot:

    def test_snapshot_at_600_ticks(self):
        _init()
        ship = _mock_ship()
        with _LogCapture() as cap:
            for i in range(1, 601):
                tel.tick(i, 0.1, ship=ship)
        snaps = cap.find("resource_snapshot")
        assert len(snaps) == 1

    def test_no_snapshot_before_600(self):
        _init()
        ship = _mock_ship()
        with _LogCapture() as cap:
            for i in range(1, 500):
                tel.tick(i, 0.1, ship=ship)
        assert cap.find("resource_snapshot") == []

    def test_snapshot_has_fuel(self):
        _init()
        ship = _mock_ship()
        with _LogCapture() as cap:
            for i in range(1, 601):
                tel.tick(i, 0.1, ship=ship)
        snap = cap.find("resource_snapshot")[0]
        assert snap["fuel_percent"] == 80.0

    def test_snapshot_tracks_power_allocation(self):
        _init()
        ship = _mock_ship()
        with _LogCapture() as cap:
            for i in range(1, 601):
                tel.tick(i, 0.1, ship=ship)
        snap = cap.find("resource_snapshot")[0]
        assert "beams" in snap["power_allocation"]
        assert snap["power_allocation"]["beams"] == 100

    def test_systems_below_80_listed(self):
        _init()
        ship = _mock_ship()
        with _LogCapture() as cap:
            for i in range(1, 601):
                tel.tick(i, 0.1, ship=ship)
        snap = cap.find("resource_snapshot")[0]
        assert "engines" in snap["systems_below_80"]
        assert "beams" not in snap["systems_below_80"]

    def test_no_crash_without_resources(self):
        _init()
        ship = MagicMock()
        ship.systems = {"beams": MagicMock(power=100, health=100)}
        ship.resources = None
        ship.interior = None
        with _LogCapture() as cap:
            for i in range(1, 601):
                tel.tick(i, 0.1, ship=ship)
        snap = cap.find("resource_snapshot")[0]
        assert snap["fuel_percent"] == 0.0
