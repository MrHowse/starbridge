"""Tests for server/telemetry.py — Section 1.1: Player Engagement Metrics."""
from __future__ import annotations

import server.telemetry as tel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_two_players() -> None:
    """Initialise telemetry with two players."""
    tel.init({"helm": "Alice", "weapons": "Bob"})


class _LogCapture:
    """Context manager that captures log_event calls from telemetry."""

    def __init__(self):
        self.events: list[tuple[str, str, dict]] = []

    def __enter__(self):
        self._orig_log = tel._log
        # Replace the telemetry module's _log with our capture function.
        tel._log = lambda cat, event, data: self.events.append((cat, event, data))
        return self

    def __exit__(self, *args):
        tel._log = self._orig_log

    def find(self, event: str) -> list[dict]:
        return [d for _, e, d in self.events if e == event]


# ---------------------------------------------------------------------------
# Tests: init and reset
# ---------------------------------------------------------------------------


class TestTelemetryInit:

    def test_init_creates_player_states(self):
        _init_two_players()
        states = tel.get_player_states()
        assert "Alice" in states
        assert "Bob" in states

    def test_init_sets_station(self):
        _init_two_players()
        assert tel.get_player_states()["Alice"].station == "helm"

    def test_reset_clears_state(self):
        _init_two_players()
        tel.reset()
        assert tel.get_player_states() == {}

    def test_init_deduplicates_player(self):
        """If same player has multiple roles, only one state."""
        tel.init({"helm": "Alice", "weapons": "Alice"})
        assert len(tel.get_player_states()) == 1


# ---------------------------------------------------------------------------
# Tests: record_action
# ---------------------------------------------------------------------------


class TestRecordAction:

    def test_action_increments_count(self):
        _init_two_players()
        tel.record_action("helm.set_heading")
        tel.record_action("helm.set_throttle")
        ps = tel.get_player_states()["Alice"]
        assert ps.total_actions == 2
        assert ps.actions_window == 2

    def test_action_updates_last_action_time(self):
        _init_two_players()
        tel.tick(1, 0.1)  # advance game time
        tel.record_action("weapons.fire_beams")
        ps = tel.get_player_states()["Bob"]
        assert ps.last_action_ts > 0

    def test_station_change_tracked(self):
        tel.init({"helm": "Alice", "weapons": "Alice"})
        tel.record_action("helm.set_heading")
        tel.record_action("weapons.fire_beams")
        ps = tel.get_player_states()["Alice"]
        assert "helm" in ps.stations_visited
        assert "weapons" in ps.stations_visited
        assert ps.station_visit_count >= 2

    def test_ignored_types_not_counted(self):
        _init_two_players()
        tel.record_action("game.briefing_launch")
        ps = tel.get_player_states()["Alice"]
        assert ps.total_actions == 0

    def test_unknown_prefix_ignored(self):
        _init_two_players()
        tel.record_action("unknown.foo")
        for ps in tel.get_player_states().values():
            assert ps.total_actions == 0

    def test_negotiation_maps_to_quartermaster(self):
        tel.init({"quartermaster": "Charlie"})
        tel.record_action("negotiation.start")
        ps = tel.get_player_states()["Charlie"]
        assert ps.total_actions == 1


# ---------------------------------------------------------------------------
# Tests: 30 s engagement summary
# ---------------------------------------------------------------------------


class TestEngagementSummary:

    def test_summary_emitted_at_300_ticks(self):
        _init_two_players()
        with _LogCapture() as cap:
            for i in range(1, 301):
                tel.tick(i, 0.1)
        summaries = cap.find("player_engagement")
        assert len(summaries) == 2  # one per player

    def test_summary_contains_required_fields(self):
        _init_two_players()
        tel.record_action("helm.set_heading")
        with _LogCapture() as cap:
            for i in range(1, 301):
                tel.tick(i, 0.1)
        summaries = cap.find("player_engagement")
        alice_summary = [s for s in summaries if s["player"] == "Alice"][0]
        assert "current_station" in alice_summary
        assert "seconds_on_station" in alice_summary
        assert "actions_last_30s" in alice_summary
        assert "seconds_since_last_action" in alice_summary
        assert "total_actions_this_game" in alice_summary
        assert "stations_visited" in alice_summary
        assert "station_visit_count" in alice_summary

    def test_actions_window_resets_after_summary(self):
        _init_two_players()
        tel.record_action("helm.set_heading")
        for i in range(1, 301):
            tel.tick(i, 0.1)
        # After summary, window should be reset.
        ps = tel.get_player_states()["Alice"]
        assert ps.actions_window == 0

    def test_no_summary_before_interval(self):
        _init_two_players()
        with _LogCapture() as cap:
            for i in range(1, 100):
                tel.tick(i, 0.1)
        summaries = cap.find("player_engagement")
        assert len(summaries) == 0


# ---------------------------------------------------------------------------
# Tests: idle detection
# ---------------------------------------------------------------------------


class TestIdleDetection:

    def test_idle_after_30s_no_input(self):
        _init_two_players()
        tel.record_action("helm.set_heading")  # first action sets last_action_ts
        with _LogCapture() as cap:
            for i in range(1, 350):
                tel.tick(i, 0.1)
        idle_events = cap.find("player_idle")
        alice_idle = [e for e in idle_events if e["player"] == "Alice"]
        assert len(alice_idle) >= 1
        assert alice_idle[0]["station"] == "helm"

    def test_no_idle_before_first_action(self):
        """Player who never acts should not trigger idle (they haven't started yet)."""
        _init_two_players()
        with _LogCapture() as cap:
            for i in range(1, 500):
                tel.tick(i, 0.1)
        idle_events = cap.find("player_idle")
        assert len(idle_events) == 0

    def test_resume_from_idle(self):
        _init_two_players()
        tel.record_action("helm.set_heading")
        # Go idle (30s of ticks without action).
        for i in range(1, 350):
            tel.tick(i, 0.1)
        ps = tel.get_player_states()["Alice"]
        assert ps.is_idle is True

        # Resume with new action.
        with _LogCapture() as cap:
            tel.record_action("helm.set_throttle")
        active_events = cap.find("player_active")
        assert len(active_events) == 1
        assert active_events[0]["player"] == "Alice"
        assert "was_idle_seconds" in active_events[0]

    def test_idle_fires_only_once(self):
        _init_two_players()
        tel.record_action("helm.set_heading")
        with _LogCapture() as cap:
            for i in range(1, 700):
                tel.tick(i, 0.1)
        idle_events = cap.find("player_idle")
        alice_idle = [e for e in idle_events if e["player"] == "Alice"]
        assert len(alice_idle) == 1


# ---------------------------------------------------------------------------
# Tests: station_from_type
# ---------------------------------------------------------------------------


class TestStationFromType:

    def test_helm_prefix(self):
        assert tel._station_from_type("helm.set_heading") == "helm"

    def test_carrier_maps_to_flight_ops(self):
        assert tel._station_from_type("carrier.create_squadron") == "flight_ops"

    def test_salvage_maps_to_quartermaster(self):
        assert tel._station_from_type("salvage.assess") == "quartermaster"

    def test_unknown_returns_none(self):
        assert tel._station_from_type("nonsense.foo") is None

    def test_no_dot_returns_none(self):
        assert tel._station_from_type("nodot") is None
