"""Tests for tools/analyse_game.py — post-game analysis tool."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.analyse_game import GameReport, parse_log, format_terminal, format_html, _analyse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_log(events: list[dict]) -> Path:
    """Write events to a temp JSONL file and return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for ev in events:
        f.write(json.dumps(ev) + "\n")
    f.close()
    return Path(f.name)


def _session_events(mission_id: str = "test_mission",
                    players: dict | None = None,
                    duration: float = 120.0) -> list[dict]:
    """Create minimal session start/stop events."""
    players = players or {"helm": "Alice", "weapons": "Bob"}
    return [
        {"tick": 0, "ts": 0.0, "cat": "session", "event": "started",
         "data": {"mission_id": mission_id, "players": players}},
        {"tick": int(duration * 10), "ts": duration, "cat": "session", "event": "stopped",
         "data": {}},
    ]


# ---------------------------------------------------------------------------
# Module A: Overview
# ---------------------------------------------------------------------------


class TestOverview:

    def test_mission_id_parsed(self):
        events = _session_events("patrol_alpha")
        _, report = parse_log(_write_log(events))
        assert report.mission_id == "patrol_alpha"

    def test_duration_parsed(self):
        events = _session_events(duration=300.0)
        _, report = parse_log(_write_log(events))
        assert report.duration_seconds == 300.0

    def test_players_parsed(self):
        players = {"helm": "Alice", "weapons": "Bob", "science": "Charlie"}
        events = _session_events(players=players)
        _, report = parse_log(_write_log(events))
        assert report.players == players

    def test_outcome_defaults_unknown(self):
        events = _session_events()
        _, report = parse_log(_write_log(events))
        assert report.outcome == "unknown"

    def test_outcome_from_game_over(self):
        events = _session_events() + [
            {"tick": 500, "ts": 50.0, "cat": "game", "event": "game_over",
             "data": {"reason": "hull_destroyed"}},
        ]
        _, report = parse_log(_write_log(events))
        assert report.outcome == "hull_destroyed"

    def test_empty_log(self):
        _, report = parse_log(_write_log([]))
        assert report.mission_id == "unknown"
        assert report.duration_seconds == 0.0

    def test_malformed_lines_skipped(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.write("not json\n")
        f.write(json.dumps({"tick": 0, "ts": 0.0, "cat": "session",
                             "event": "started", "data": {"mission_id": "ok"}}) + "\n")
        f.write("{bad json\n")
        f.close()
        events, report = parse_log(f.name)
        assert len(events) == 1
        assert report.mission_id == "ok"

    def test_duration_estimated_from_last_event(self):
        """When no session stop event, duration estimated from last event."""
        events = [
            {"tick": 0, "ts": 0.0, "cat": "session", "event": "started",
             "data": {"mission_id": "test"}},
            {"tick": 1000, "ts": 100.0, "cat": "weapons", "event": "beam_fired",
             "data": {}},
        ]
        _, report = parse_log(_write_log(events))
        assert report.duration_seconds == 100.0


# ---------------------------------------------------------------------------
# Module B: Engagement
# ---------------------------------------------------------------------------


class TestEngagement:

    def test_engagement_collected(self):
        events = _session_events() + [
            {"tick": 300, "ts": 30.0, "cat": "telemetry", "event": "player_engagement",
             "data": {"player": "Alice", "current_station": "helm",
                      "total_actions_this_game": 15, "actions_last_30s": 8,
                      "station_visit_count": 2, "stations_visited": ["helm", "weapons"],
                      "seconds_since_last_action": 3.0}},
        ]
        _, report = parse_log(_write_log(events))
        assert len(report.engagement) == 1
        assert report.engagement[0]["player"] == "Alice"
        assert report.engagement[0]["total_actions"] == 15

    def test_engagement_last_per_player(self):
        """Multiple engagement summaries → only last per player kept."""
        events = _session_events() + [
            {"tick": 300, "ts": 30.0, "cat": "telemetry", "event": "player_engagement",
             "data": {"player": "Alice", "total_actions_this_game": 5}},
            {"tick": 600, "ts": 60.0, "cat": "telemetry", "event": "player_engagement",
             "data": {"player": "Alice", "total_actions_this_game": 20}},
        ]
        _, report = parse_log(_write_log(events))
        assert len(report.engagement) == 1
        assert report.engagement[0]["total_actions"] == 20


# ---------------------------------------------------------------------------
# Module C: Heatmap
# ---------------------------------------------------------------------------


class TestHeatmap:

    def test_heatmap_buckets(self):
        events = _session_events() + [
            {"tick": 10, "ts": 1.0, "cat": "weapons", "event": "beam_fired", "data": {}},
            {"tick": 20, "ts": 2.0, "cat": "weapons", "event": "torpedo_fired", "data": {}},
            {"tick": 350, "ts": 35.0, "cat": "weapons", "event": "beam_fired", "data": {}},
        ]
        _, report = parse_log(_write_log(events))
        assert "weapons" in report.heatmap
        # First two events in bucket 0 (0-30s), third in bucket 1 (30-60s)
        buckets = dict(report.heatmap["weapons"])
        assert buckets[0.0] == 2
        assert buckets[30.0] == 1

    def test_multiple_stations(self):
        events = _session_events() + [
            {"tick": 10, "ts": 1.0, "cat": "weapons", "event": "x", "data": {}},
            {"tick": 10, "ts": 1.0, "cat": "helm", "event": "y", "data": {}},
        ]
        _, report = parse_log(_write_log(events))
        assert "weapons" in report.heatmap
        assert "helm" in report.heatmap


# ---------------------------------------------------------------------------
# Module D: Coordination
# ---------------------------------------------------------------------------


class TestCoordination:

    def test_coordination_checks(self):
        events = _session_events() + [
            {"tick": 100, "ts": 10.0, "cat": "telemetry", "event": "coordination_check",
             "data": {"chain": "fire_to_hazcon", "responded": True,
                      "response_time_seconds": 5.2}},
        ]
        _, report = parse_log(_write_log(events))
        assert len(report.coordination_checks) == 1
        assert report.coordination_checks[0]["chain"] == "fire_to_hazcon"

    def test_coordination_timeouts(self):
        events = _session_events() + [
            {"tick": 300, "ts": 30.0, "cat": "telemetry", "event": "coordination_timeout",
             "data": {"chain": "captain_priority_target", "timeout_seconds": 30.0}},
        ]
        _, report = parse_log(_write_log(events))
        assert len(report.coordination_timeouts) == 1


# ---------------------------------------------------------------------------
# Module E: Combat
# ---------------------------------------------------------------------------


class TestCombat:

    def test_combat_summary_aggregated(self):
        events = _session_events() + [
            {"tick": 300, "ts": 30.0, "cat": "telemetry", "event": "combat_summary",
             "data": {"torpedoes_fired": 5, "torpedoes_hit": 3, "torpedo_hit_rate": 0.6,
                      "beam_shots_fired": 10, "beam_damage_dealt": 200.0,
                      "enemies_destroyed": 2, "enemies_active": 1,
                      "damage_taken_hull": 50.0, "damage_taken_shields": 30.0,
                      "shield_efficiency": 0.375}},
            {"tick": 600, "ts": 60.0, "cat": "telemetry", "event": "combat_summary",
             "data": {"torpedoes_fired": 3, "torpedoes_hit": 2, "torpedo_hit_rate": 0.67,
                      "beam_shots_fired": 5, "beam_damage_dealt": 100.0,
                      "enemies_destroyed": 1, "enemies_active": 0,
                      "damage_taken_hull": 20.0, "damage_taken_shields": 10.0,
                      "shield_efficiency": 0.33}},
        ]
        _, report = parse_log(_write_log(events))
        assert report.total_enemies_destroyed == 3
        assert report.total_damage_taken == 70.0
        assert report.total_damage_dealt == 300.0

    def test_torpedo_outcomes_tracked(self):
        events = _session_events() + [
            {"tick": 100, "ts": 10.0, "cat": "telemetry", "event": "torpedo_outcome",
             "data": {"torpedo_type": "standard", "hit": True, "target_id": "e1"}},
            {"tick": 200, "ts": 20.0, "cat": "telemetry", "event": "torpedo_outcome",
             "data": {"torpedo_type": "homing", "hit": False, "miss_reason": "evaded"}},
        ]
        _, report = parse_log(_write_log(events))
        assert len(report.torpedo_outcomes) == 2


# ---------------------------------------------------------------------------
# Module F: Resources
# ---------------------------------------------------------------------------


class TestResources:

    def test_resource_snapshots(self):
        events = _session_events() + [
            {"tick": 600, "ts": 60.0, "cat": "telemetry", "event": "resource_snapshot",
             "data": {"fuel_percent": 85.0, "ammo": {"standard": 8},
                      "power_allocation": {"beams": 100}, "systems_below_80": ["engines"]}},
        ]
        _, report = parse_log(_write_log(events))
        assert len(report.resource_snapshots) == 1
        assert report.resource_snapshots[0]["fuel_percent"] == 85.0


# ---------------------------------------------------------------------------
# Module G: Hazards
# ---------------------------------------------------------------------------


class TestHazards:

    def test_environment_snapshots(self):
        events = _session_events() + [
            {"tick": 300, "ts": 30.0, "cat": "telemetry", "event": "environment_snapshot",
             "data": {"active_fires": [{"room": "engine_room", "intensity": 3}],
                      "breaches": [], "rooms_evacuated": ["engine_room"],
                      "structural_integrity": {"s1": 80.0}}},
        ]
        _, report = parse_log(_write_log(events))
        assert len(report.environment_snapshots) == 1
        assert len(report.environment_snapshots[0]["active_fires"]) == 1


# ---------------------------------------------------------------------------
# Module H: Missions
# ---------------------------------------------------------------------------


class TestMissions:

    def test_mission_events_collected(self):
        events = _session_events() + [
            {"tick": 100, "ts": 10.0, "cat": "mission", "event": "node_activated",
             "data": {"node": "escort_phase"}},
            {"tick": 500, "ts": 50.0, "cat": "mission", "event": "node_completed",
             "data": {"node": "escort_phase"}},
        ]
        _, report = parse_log(_write_log(events))
        assert len(report.mission_events) == 2
        assert report.mission_events[0]["event"] == "node_activated"


# ---------------------------------------------------------------------------
# Module I: Frustration
# ---------------------------------------------------------------------------


class TestFrustration:

    def test_rapid_clicks(self):
        events = _session_events() + [
            {"tick": 100, "ts": 10.0, "cat": "telemetry", "event": "rapid_click",
             "data": {"station": "weapons", "element": "fire_btn",
                      "click_count": 12, "duration_seconds": 2.0}},
        ]
        _, report = parse_log(_write_log(events))
        assert len(report.rapid_clicks) == 1
        assert report.rapid_clicks[0]["click_count"] == 12

    def test_station_hopping(self):
        events = _session_events() + [
            {"tick": 600, "ts": 60.0, "cat": "telemetry", "event": "station_hopping",
             "data": {"player": "Alice", "switches_last_60s": 8,
                      "stations_visited": ["helm", "weapons"]}},
        ]
        _, report = parse_log(_write_log(events))
        assert len(report.station_hops) == 1

    def test_idle_events(self):
        events = _session_events() + [
            {"tick": 300, "ts": 30.0, "cat": "telemetry", "event": "player_idle",
             "data": {"player": "Bob", "station": "weapons"}},
        ]
        _, report = parse_log(_write_log(events))
        assert len(report.idle_events) == 1


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


class TestTerminalFormat:

    def test_terminal_has_overview(self):
        events = _session_events("my_mission", {"helm": "Alice"}, 180.0)
        _, report = parse_log(_write_log(events))
        text = format_terminal(report)
        assert "my_mission" in text
        assert "03:00" in text
        assert "Alice" in text

    def test_terminal_empty_report(self):
        report = GameReport()
        text = format_terminal(report)
        assert "POST-GAME ANALYSIS" in text

    def test_terminal_with_combat(self):
        events = _session_events() + [
            {"tick": 300, "ts": 30.0, "cat": "telemetry", "event": "combat_summary",
             "data": {"torpedoes_fired": 5, "torpedoes_hit": 3, "torpedo_hit_rate": 0.6,
                      "beam_shots_fired": 10, "beam_damage_dealt": 200.0,
                      "enemies_destroyed": 2, "enemies_active": 0,
                      "damage_taken_hull": 50.0, "damage_taken_shields": 30.0,
                      "shield_efficiency": 0.375}},
        ]
        _, report = parse_log(_write_log(events))
        text = format_terminal(report)
        assert "COMBAT EFFECTIVENESS" in text
        assert "Torpedoes fired: 5" in text


class TestHTMLFormat:

    def test_html_has_doctype(self):
        report = GameReport(mission_id="test")
        html = format_html(report)
        assert "<!DOCTYPE html>" in html
        assert "test" in html

    def test_html_escapes_special_chars(self):
        report = GameReport(mission_id="<script>alert('xss')</script>")
        html = format_html(report)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_html_with_full_data(self):
        events = _session_events("full_test", {"helm": "Alice"}, 300.0) + [
            {"tick": 300, "ts": 30.0, "cat": "telemetry", "event": "combat_summary",
             "data": {"torpedoes_fired": 5, "torpedoes_hit": 3, "torpedo_hit_rate": 0.6,
                      "beam_shots_fired": 10, "beam_damage_dealt": 200.0,
                      "enemies_destroyed": 2, "enemies_active": 0,
                      "damage_taken_hull": 50.0, "damage_taken_shields": 30.0,
                      "shield_efficiency": 0.375}},
            {"tick": 300, "ts": 30.0, "cat": "telemetry", "event": "environment_snapshot",
             "data": {"active_fires": [{"room": "r1", "intensity": 2}],
                      "breaches": [], "rooms_evacuated": [],
                      "structural_integrity": {}}},
        ]
        _, report = parse_log(_write_log(events))
        html = format_html(report)
        assert "Combat Effectiveness" in html
        assert "Hazard" in html


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompat:

    def test_old_log_without_telemetry(self):
        """Old logs without telemetry events should still produce a report."""
        events = [
            {"tick": 0, "ts": 0.0, "cat": "session", "event": "started",
             "data": {"mission_id": "sandbox", "players": {}}},
            {"tick": 100, "ts": 10.0, "cat": "weapons", "event": "beam_fired",
             "data": {"target_id": "e1", "damage": 25.0}},
            {"tick": 500, "ts": 50.0, "cat": "combat", "event": "enemy_destroyed",
             "data": {"enemy_id": "e1", "cause": "beam"}},
            {"tick": 1200, "ts": 120.0, "cat": "session", "event": "stopped",
             "data": {}},
        ]
        _, report = parse_log(_write_log(events))
        assert report.mission_id == "sandbox"
        assert report.duration_seconds == 120.0
        assert report.total_enemies_destroyed == 1
        assert "weapons" in report.heatmap

    def test_missing_data_field(self):
        """Events with missing data field should not crash."""
        events = [
            {"tick": 0, "ts": 0.0, "cat": "session", "event": "started"},
        ]
        _, report = parse_log(_write_log(events))
        assert report.mission_id == "unknown"
