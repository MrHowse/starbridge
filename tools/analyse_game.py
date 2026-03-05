#!/usr/bin/env python3
"""Post-game analysis tool — reads JSONL game logs and produces reports.

Usage:
    python tools/analyse_game.py logs/game_20260305_194300.jsonl
    python tools/analyse_game.py logs/game_20260305_194300.jsonl --html report.html

Modules:
    A. Overview     — mission, duration, outcome, player count
    B. Engagement   — per-player action counts, idle time, station visits
    C. Heatmap      — per-station action distribution over time
    D. Coordination — chain response times, timeouts, success rates
    E. Combat       — torpedo/beam stats, damage dealt/taken, kill count
    F. Resources    — ammo/fuel consumption curves
    G. Hazards      — fires, breaches, structural events
    H. Missions     — mission graph node activations and completions
    I. Frustration  — rapid clicks, station hopping, idle patterns
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


# ===================================================================
# Data structures
# ===================================================================


@dataclass
class GameReport:
    """Aggregated analysis of a single game session."""

    # A: Overview
    mission_id: str = "unknown"
    duration_seconds: float = 0.0
    players: dict[str, str] = field(default_factory=dict)  # role → player
    outcome: str = "unknown"
    total_ticks: int = 0

    # B: Engagement (per-player)
    engagement: list[dict] = field(default_factory=list)

    # C: Heatmap (station → list of (time_bucket, action_count))
    heatmap: dict[str, list[tuple[float, int]]] = field(default_factory=dict)

    # D: Coordination
    coordination_checks: list[dict] = field(default_factory=list)
    coordination_timeouts: list[dict] = field(default_factory=list)

    # E: Combat
    combat_summaries: list[dict] = field(default_factory=list)
    torpedo_outcomes: list[dict] = field(default_factory=list)
    total_enemies_destroyed: int = 0
    total_damage_taken: float = 0.0
    total_damage_dealt: float = 0.0

    # F: Resources
    resource_snapshots: list[dict] = field(default_factory=list)

    # G: Hazards
    environment_snapshots: list[dict] = field(default_factory=list)

    # H: Missions
    mission_events: list[dict] = field(default_factory=list)

    # I: Frustration
    rapid_clicks: list[dict] = field(default_factory=list)
    station_hops: list[dict] = field(default_factory=list)
    idle_events: list[dict] = field(default_factory=list)


# ===================================================================
# Log parsing
# ===================================================================


def parse_log(path: str | Path) -> tuple[list[dict], GameReport]:
    """Parse a JSONL log file and produce a GameReport.

    Returns (raw_events, report).  Gracefully skips malformed lines.
    """
    events: list[dict] = []
    path = Path(path)
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    report = _analyse(events)
    return events, report


def _analyse(events: list[dict]) -> GameReport:
    """Build a GameReport from raw log events."""
    r = GameReport()

    # Track per-station action counts per 30 s bucket for heatmap.
    heatmap_buckets: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    # Track per-player engagement summaries (last wins per player).
    engagement_last: dict[str, dict] = {}

    for ev in events:
        cat = ev.get("cat", "")
        event = ev.get("event", "")
        data = ev.get("data") or {}
        tick = ev.get("tick", 0)
        ts = ev.get("ts", 0.0)

        # A: Overview
        if event == "started" and cat == "session":
            r.mission_id = data.get("mission_id", "unknown")
            r.players = data.get("players", {})
        elif event == "stopped" and cat == "session":
            r.duration_seconds = ts
            r.total_ticks = tick
        elif event == "mission_complete":
            r.outcome = data.get("outcome", "completed")
        elif event == "mission_failed":
            r.outcome = "failed"
        elif event == "game_over":
            r.outcome = data.get("reason", "game_over")

        # B: Engagement
        elif event == "player_engagement":
            engagement_last[data.get("player", "?")] = {
                "player": data.get("player"),
                "station": data.get("current_station"),
                "total_actions": data.get("total_actions_this_game", 0),
                "actions_last_30s": data.get("actions_last_30s", 0),
                "station_visit_count": data.get("station_visit_count", 0),
                "stations_visited": data.get("stations_visited", []),
                "seconds_since_last_action": data.get("seconds_since_last_action", 0),
                "ts": ts,
            }

        # C: Heatmap — derive from action events
        elif cat in ("weapons", "helm", "engineering", "science", "comms",
                      "medical", "security", "operations", "flight_ops",
                      "hazard_control", "captain", "quartermaster"):
            bucket = int(ts // 30)
            heatmap_buckets[cat][bucket] += 1

        # D: Coordination
        elif event == "coordination_check":
            r.coordination_checks.append({**data, "ts": ts})
        elif event == "coordination_timeout":
            r.coordination_timeouts.append({**data, "ts": ts})

        # E: Combat
        elif event == "combat_summary":
            r.combat_summaries.append({**data, "ts": ts})
            r.total_enemies_destroyed += data.get("enemies_destroyed", 0)
            r.total_damage_taken += data.get("damage_taken_hull", 0)
            r.total_damage_dealt += data.get("beam_damage_dealt", 0)
        elif event == "torpedo_outcome":
            r.torpedo_outcomes.append({**data, "ts": ts})
        elif event == "enemy_destroyed":
            r.total_enemies_destroyed += 1

        # F: Resources
        elif event == "resource_snapshot":
            r.resource_snapshots.append({**data, "ts": ts})

        # G: Hazards
        elif event == "environment_snapshot":
            r.environment_snapshots.append({**data, "ts": ts})

        # H: Missions
        elif cat == "mission":
            r.mission_events.append({"event": event, **data, "ts": ts})

        # I: Frustration
        elif event == "rapid_click":
            r.rapid_clicks.append({**data, "ts": ts})
        elif event == "station_hopping":
            r.station_hops.append({**data, "ts": ts})
        elif event == "player_idle":
            r.idle_events.append({**data, "ts": ts})

    # Finalise engagement — collect last summary per player.
    r.engagement = list(engagement_last.values())

    # Finalise heatmap.
    for station, buckets in heatmap_buckets.items():
        r.heatmap[station] = sorted(
            [(b * 30.0, count) for b, count in buckets.items()]
        )

    # If no session stop event, estimate duration from last event.
    if r.duration_seconds == 0.0 and events:
        r.duration_seconds = events[-1].get("ts", 0.0)
        r.total_ticks = events[-1].get("tick", 0)

    return r


# ===================================================================
# Terminal output
# ===================================================================


def format_terminal(report: GameReport) -> str:
    """Format a GameReport for terminal display."""
    lines: list[str] = []
    w = 60

    # A: Overview
    lines.append("=" * w)
    lines.append("POST-GAME ANALYSIS REPORT")
    lines.append("=" * w)
    lines.append(f"Mission:   {report.mission_id}")
    lines.append(f"Duration:  {_fmt_time(report.duration_seconds)}")
    lines.append(f"Outcome:   {report.outcome}")
    lines.append(f"Players:   {len(report.players)}")
    for role, player in report.players.items():
        lines.append(f"  {role:20s} {player}")
    lines.append("")

    # B: Engagement
    if report.engagement:
        lines.append("-" * w)
        lines.append("PLAYER ENGAGEMENT")
        lines.append("-" * w)
        for e in report.engagement:
            lines.append(f"  {e.get('player', '?'):12s}  "
                         f"actions={e.get('total_actions', 0):4d}  "
                         f"stations={e.get('station_visit_count', 0)}  "
                         f"idle={e.get('seconds_since_last_action', 0):.0f}s ago")
        lines.append("")

    # C: Heatmap
    if report.heatmap:
        lines.append("-" * w)
        lines.append("STATION ACTIVITY HEATMAP (actions per 30s bucket)")
        lines.append("-" * w)
        for station, buckets in sorted(report.heatmap.items()):
            total = sum(c for _, c in buckets)
            peak = max(c for _, c in buckets) if buckets else 0
            lines.append(f"  {station:20s} total={total:4d}  peak={peak}")
        lines.append("")

    # D: Coordination
    if report.coordination_checks or report.coordination_timeouts:
        lines.append("-" * w)
        lines.append("CROSS-STATION COORDINATION")
        lines.append("-" * w)
        total_checks = len(report.coordination_checks)
        responded = sum(1 for c in report.coordination_checks if c.get("responded"))
        timed_out = len(report.coordination_timeouts)
        if total_checks > 0:
            pct = responded / total_checks * 100
            avg_time = (sum(c.get("response_time_seconds", 0) for c in report.coordination_checks if c.get("responded"))
                        / max(1, responded))
            lines.append(f"  Coordination checks: {total_checks}")
            lines.append(f"  Responded: {responded} ({pct:.0f}%)")
            lines.append(f"  Avg response time: {avg_time:.1f}s")
        lines.append(f"  Timeouts: {timed_out}")
        for t in report.coordination_timeouts:
            lines.append(f"    {t.get('chain', '?'):30s} at {_fmt_time(t.get('ts', 0))}")
        lines.append("")

    # E: Combat
    if report.combat_summaries:
        lines.append("-" * w)
        lines.append("COMBAT EFFECTIVENESS")
        lines.append("-" * w)
        total_torps = sum(s.get("torpedoes_fired", 0) for s in report.combat_summaries)
        total_hits = sum(s.get("torpedoes_hit", 0) for s in report.combat_summaries)
        total_beams = sum(s.get("beam_shots_fired", 0) for s in report.combat_summaries)
        hit_rate = total_hits / total_torps * 100 if total_torps > 0 else 0
        lines.append(f"  Torpedoes fired: {total_torps}  hit: {total_hits}  ({hit_rate:.0f}%)")
        lines.append(f"  Beam volleys: {total_beams}")
        lines.append(f"  Enemies destroyed: {report.total_enemies_destroyed}")
        lines.append(f"  Damage dealt: {report.total_damage_dealt:.0f}")
        lines.append(f"  Damage taken: {report.total_damage_taken:.0f}")
        lines.append("")

    # F: Resources
    if report.resource_snapshots:
        lines.append("-" * w)
        lines.append("RESOURCE TRACKING")
        lines.append("-" * w)
        last = report.resource_snapshots[-1]
        lines.append(f"  Final fuel: {last.get('fuel_percent', 0):.0f}%")
        below = last.get("systems_below_80", [])
        if below:
            lines.append(f"  Systems below 80%: {', '.join(below)}")
        lines.append(f"  Snapshots: {len(report.resource_snapshots)}")
        lines.append("")

    # G: Hazards
    if report.environment_snapshots:
        lines.append("-" * w)
        lines.append("HAZARD/ENVIRONMENT")
        lines.append("-" * w)
        max_fires = max(len(s.get("active_fires", [])) for s in report.environment_snapshots)
        max_breaches = max(len(s.get("breaches", [])) for s in report.environment_snapshots)
        lines.append(f"  Peak concurrent fires: {max_fires}")
        lines.append(f"  Peak concurrent breaches: {max_breaches}")
        lines.append(f"  Snapshots: {len(report.environment_snapshots)}")
        lines.append("")

    # H: Missions
    if report.mission_events:
        lines.append("-" * w)
        lines.append("MISSION EVENTS")
        lines.append("-" * w)
        for me in report.mission_events[:20]:  # limit display
            lines.append(f"  [{_fmt_time(me.get('ts', 0))}] {me.get('event', '?')}")
        if len(report.mission_events) > 20:
            lines.append(f"  ... and {len(report.mission_events) - 20} more")
        lines.append("")

    # I: Frustration
    frustration_count = len(report.rapid_clicks) + len(report.station_hops) + len(report.idle_events)
    if frustration_count > 0:
        lines.append("-" * w)
        lines.append("FRUSTRATION SIGNALS")
        lines.append("-" * w)
        lines.append(f"  Rapid click events: {len(report.rapid_clicks)}")
        lines.append(f"  Station hopping events: {len(report.station_hops)}")
        lines.append(f"  Player idle events: {len(report.idle_events)}")
        for rc in report.rapid_clicks[:5]:
            lines.append(f"    rapid-click: {rc.get('station', '?')} "
                         f"{rc.get('element', '?')} ×{rc.get('click_count', 0)}")
        lines.append("")

    lines.append("=" * w)
    return "\n".join(lines)


def _fmt_time(seconds: float) -> str:
    """Format seconds as MM:SS."""
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


# ===================================================================
# HTML output
# ===================================================================


def format_html(report: GameReport) -> str:
    """Format a GameReport as a standalone HTML page."""
    sections: list[str] = []

    # Header
    sections.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Game Report — {_esc(report.mission_id)}</title>
<style>
body {{ font-family: 'Courier New', monospace; background: #1a1a2e; color: #e0e0e0;
       max-width: 900px; margin: 2em auto; padding: 1em; }}
h1 {{ color: #00d4ff; border-bottom: 2px solid #00d4ff; padding-bottom: 0.3em; }}
h2 {{ color: #ffa500; margin-top: 1.5em; }}
table {{ border-collapse: collapse; width: 100%; margin: 0.5em 0; }}
th, td {{ border: 1px solid #444; padding: 6px 10px; text-align: left; }}
th {{ background: #2a2a4e; color: #00d4ff; }}
tr:nth-child(even) {{ background: #222244; }}
.stat {{ color: #00ff88; font-weight: bold; }}
.warn {{ color: #ff4444; }}
.bar {{ display: inline-block; height: 14px; background: #00d4ff; }}
</style>
</head>
<body>
<h1>Post-Game Analysis: {_esc(report.mission_id)}</h1>
""")

    # A: Overview
    sections.append(f"""<h2>Overview</h2>
<table>
<tr><th>Mission</th><td>{_esc(report.mission_id)}</td></tr>
<tr><th>Duration</th><td>{_fmt_time(report.duration_seconds)}</td></tr>
<tr><th>Outcome</th><td class="stat">{_esc(report.outcome)}</td></tr>
<tr><th>Players</th><td>{len(report.players)}</td></tr>
</table>""")

    if report.players:
        sections.append("<table><tr><th>Role</th><th>Player</th></tr>")
        for role, player in report.players.items():
            sections.append(f"<tr><td>{_esc(role)}</td><td>{_esc(player)}</td></tr>")
        sections.append("</table>")

    # B: Engagement
    if report.engagement:
        sections.append("<h2>Player Engagement</h2><table>")
        sections.append("<tr><th>Player</th><th>Actions</th><th>Stations</th><th>Idle (s ago)</th></tr>")
        for e in report.engagement:
            sections.append(f"<tr><td>{_esc(str(e.get('player', '?')))}</td>"
                            f"<td class='stat'>{e.get('total_actions', 0)}</td>"
                            f"<td>{e.get('station_visit_count', 0)}</td>"
                            f"<td>{e.get('seconds_since_last_action', 0):.0f}</td></tr>")
        sections.append("</table>")

    # C: Heatmap
    if report.heatmap:
        sections.append("<h2>Station Activity Heatmap</h2><table>")
        sections.append("<tr><th>Station</th><th>Total</th><th>Peak</th><th>Distribution</th></tr>")
        global_max = max(
            (c for buckets in report.heatmap.values() for _, c in buckets),
            default=1,
        )
        for station, buckets in sorted(report.heatmap.items()):
            total = sum(c for _, c in buckets)
            peak = max(c for _, c in buckets) if buckets else 0
            bar_width = int(total / max(1, global_max) * 200)
            sections.append(f"<tr><td>{_esc(station)}</td><td>{total}</td><td>{peak}</td>"
                            f"<td><span class='bar' style='width:{bar_width}px'></span></td></tr>")
        sections.append("</table>")

    # D: Coordination
    if report.coordination_checks or report.coordination_timeouts:
        sections.append("<h2>Cross-Station Coordination</h2>")
        responded = sum(1 for c in report.coordination_checks if c.get("responded"))
        total_c = len(report.coordination_checks)
        pct = responded / total_c * 100 if total_c > 0 else 0
        sections.append(f"<p>Checks: <span class='stat'>{total_c}</span> "
                        f"| Responded: <span class='stat'>{responded} ({pct:.0f}%)</span> "
                        f"| Timeouts: <span class='warn'>{len(report.coordination_timeouts)}</span></p>")
        if report.coordination_timeouts:
            sections.append("<table><tr><th>Chain</th><th>Time</th></tr>")
            for t in report.coordination_timeouts:
                sections.append(f"<tr><td>{_esc(t.get('chain', '?'))}</td>"
                                f"<td>{_fmt_time(t.get('ts', 0))}</td></tr>")
            sections.append("</table>")

    # E: Combat
    if report.combat_summaries:
        sections.append("<h2>Combat Effectiveness</h2>")
        total_torps = sum(s.get("torpedoes_fired", 0) for s in report.combat_summaries)
        total_hits = sum(s.get("torpedoes_hit", 0) for s in report.combat_summaries)
        total_beams = sum(s.get("beam_shots_fired", 0) for s in report.combat_summaries)
        hit_rate = total_hits / total_torps * 100 if total_torps > 0 else 0
        sections.append(f"""<table>
<tr><th>Torpedoes</th><td>{total_torps} fired / {total_hits} hit ({hit_rate:.0f}%)</td></tr>
<tr><th>Beam Volleys</th><td>{total_beams}</td></tr>
<tr><th>Enemies Destroyed</th><td class="stat">{report.total_enemies_destroyed}</td></tr>
<tr><th>Damage Dealt</th><td>{report.total_damage_dealt:.0f}</td></tr>
<tr><th>Damage Taken</th><td class="warn">{report.total_damage_taken:.0f}</td></tr>
</table>""")

    # F: Resources
    if report.resource_snapshots:
        sections.append("<h2>Resource Tracking</h2>")
        last = report.resource_snapshots[-1]
        fuel = last.get("fuel_percent", 0)
        fuel_class = "warn" if fuel < 25 else "stat"
        sections.append(f"<p>Final fuel: <span class='{fuel_class}'>{fuel:.0f}%</span></p>")
        below = last.get("systems_below_80", [])
        if below:
            sections.append(f"<p class='warn'>Systems below 80%: {', '.join(_esc(s) for s in below)}</p>")

    # G: Hazards
    if report.environment_snapshots:
        sections.append("<h2>Hazard/Environment</h2>")
        max_fires = max(len(s.get("active_fires", [])) for s in report.environment_snapshots)
        max_breaches = max(len(s.get("breaches", [])) for s in report.environment_snapshots)
        sections.append(f"""<table>
<tr><th>Peak Fires</th><td class="{'warn' if max_fires > 0 else ''}">{max_fires}</td></tr>
<tr><th>Peak Breaches</th><td class="{'warn' if max_breaches > 0 else ''}">{max_breaches}</td></tr>
<tr><th>Snapshots</th><td>{len(report.environment_snapshots)}</td></tr>
</table>""")

    # I: Frustration
    frustration_count = len(report.rapid_clicks) + len(report.station_hops) + len(report.idle_events)
    if frustration_count > 0:
        sections.append("<h2>Frustration Signals</h2>")
        sections.append(f"""<table>
<tr><th>Rapid Clicks</th><td class="warn">{len(report.rapid_clicks)}</td></tr>
<tr><th>Station Hops</th><td>{len(report.station_hops)}</td></tr>
<tr><th>Idle Events</th><td>{len(report.idle_events)}</td></tr>
</table>""")

    sections.append("</body></html>")
    return "\n".join(sections)


def _esc(s: str) -> str:
    """Escape HTML special characters."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ===================================================================
# CLI entrypoint
# ===================================================================


def main() -> None:
    """CLI entrypoint."""
    if len(sys.argv) < 2:
        print("Usage: python tools/analyse_game.py <logfile.jsonl> [--html output.html]")
        sys.exit(1)

    log_path = sys.argv[1]
    html_out = None
    if "--html" in sys.argv:
        idx = sys.argv.index("--html")
        if idx + 1 < len(sys.argv):
            html_out = sys.argv[idx + 1]

    _, report = parse_log(log_path)

    # Terminal output always printed.
    print(format_terminal(report))

    # HTML output if requested.
    if html_out:
        Path(html_out).write_text(format_html(report))
        print(f"\nHTML report written to {html_out}")


if __name__ == "__main__":
    main()
