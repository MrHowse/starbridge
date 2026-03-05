"""Tests for server/telemetry.py — Sections 1.6-1.7: UI Quality + Phase Tracking."""
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


def _init() -> None:
    tel.init({"weapons": "Alice"})


# ---------------------------------------------------------------------------
# Tests: UI interaction quality (1.6)
# ---------------------------------------------------------------------------


class TestUIQuality:

    def test_rapid_click_logged(self):
        _init()
        with _LogCapture() as cap:
            tel.record_rapid_click("weapons", "fire_button", 10, 2.5)
        events = cap.find("rapid_click")
        assert len(events) == 1
        assert events[0]["station"] == "weapons"
        assert events[0]["click_count"] == 10
        assert events[0]["duration_seconds"] == 2.5

    def test_station_hopping_logged(self):
        _init()
        with _LogCapture() as cap:
            tel.record_station_hopping("Alice", 5, ["weapons", "helm", "weapons", "helm", "weapons"])
        events = cap.find("station_hopping")
        assert len(events) == 1
        assert events[0]["player"] == "Alice"
        assert events[0]["switches_last_60s"] == 5


# ---------------------------------------------------------------------------
# Tests: game phase tracking (1.7)
# ---------------------------------------------------------------------------


class TestPhaseTracking:

    def test_initial_phase_is_all_clear(self):
        _init()
        assert tel.get_current_phase() == "all_clear"

    def test_first_contact_on_enemy_appear(self):
        _init()
        with _LogCapture() as cap:
            tel.tick(1, 0.1, enemy_count=1)
        changes = cap.find("phase_change")
        assert len(changes) == 1
        assert changes[0]["phase"] == "first_contact"
        assert tel.get_current_phase() == "first_contact"

    def test_combat_engaged_after_first_contact(self):
        _init()
        tel.tick(1, 0.1, enemy_count=1)  # first_contact
        with _LogCapture() as cap:
            tel.tick(2, 0.1, enemy_count=1)  # combat_engaged
        changes = cap.find("phase_change")
        assert len(changes) == 1
        assert changes[0]["phase"] == "combat_engaged"

    def test_crisis_on_low_hull(self):
        _init()
        tel.tick(1, 0.1, enemy_count=1)
        with _LogCapture() as cap:
            tel.tick(2, 0.1, enemy_count=1, hull_pct=40.0)
        changes = cap.find("phase_change")
        crisis = [c for c in changes if c["phase"] == "crisis"]
        assert len(crisis) == 1
        assert crisis[0]["trigger"] == "hull_below_50"

    def test_all_clear_after_60s_no_enemies(self):
        _init()
        tel.tick(1, 0.1, enemy_count=1)  # first_contact
        tel.tick(2, 0.1, enemy_count=1)  # combat_engaged
        # Enemies disappear — need 600 ticks (60s) for all_clear
        with _LogCapture() as cap:
            for i in range(3, 610):
                tel.tick(i, 0.1, enemy_count=0)
        changes = cap.find("phase_change")
        all_clear = [c for c in changes if c["phase"] == "all_clear"]
        assert len(all_clear) == 1

    def test_no_all_clear_before_60s(self):
        _init()
        tel.tick(1, 0.1, enemy_count=1)
        tel.tick(2, 0.1, enemy_count=1)
        with _LogCapture() as cap:
            for i in range(3, 500):
                tel.tick(i, 0.1, enemy_count=0)
        changes = cap.find("phase_change")
        all_clear = [c for c in changes if c["phase"] == "all_clear"]
        assert len(all_clear) == 0

    def test_mission_active_phase(self):
        _init()
        with _LogCapture() as cap:
            tel.tick(1, 0.1, mission_active=True)
        changes = cap.find("phase_change")
        assert len(changes) == 1
        assert changes[0]["phase"] == "mission_active"

    def test_reset_clears_phase(self):
        _init()
        tel.tick(1, 0.1, enemy_count=1)
        tel.reset()
        assert tel.get_current_phase() == "all_clear"
