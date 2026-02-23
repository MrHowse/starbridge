"""Game Debrief Computation.

Parses a completed JSONL session log and returns structured debrief data:
  - per_station_stats: action counts per station
  - awards: earned awards per station (one per station, threshold-based)
  - key_moments: notable events with timestamps
  - timeline: periodic position snapshots for the Captain's Replay

Called from game_loop._loop() immediately after stop_logging() writes the
final "session/ended" record to disk.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Event → station mapping (category → role name used in debrief)
# ---------------------------------------------------------------------------

_CAT_TO_ROLE: dict[str, str] = {
    "helm":      "helm",
    "weapons":   "weapons",
    "engineering": "engineering",
    "science":   "science",
    "medical":   "medical",
    "security":  "security",
    "comms":     "comms",
    "flight_ops": "flight_ops",
    "ew":        "electronic_warfare",
    "tactical":  "tactical",
    "captain":   "captain",
}

# Award definitions: (role, award_name, description_template, min_count, event_key)
# event_key matches the "event" field in the log record.
_AWARD_DEFS: list[tuple[str, str, str, int, str]] = [
    ("weapons",          "Sharpshooter",      "Fired {n} beam shot(s)",           5,  "beam_fired"),
    ("helm",             "Ace Navigator",     "Made {n} course correction(s)",    5,  "heading_changed"),
    ("engineering",      "Power Broker",      "Made {n} power adjustment(s)",     5,  "power_changed"),
    ("science",          "Eagle Eye",         "Completed {n} scan(s)",            2,  "scan_completed"),
    ("medical",          "Life Saver",        "Started {n} treatment(s)",         1,  "treatment_started"),
    ("security",         "Gatekeeper",        "Moved squads {n} time(s)",         3,  "squad_moved"),
    ("comms",            "Diplomat",          "Hailed {n} contact(s)",            1,  "hail_sent"),
    ("engineering",      "Quick Fix",         "Dispatched {n} damage team(s)",    1,  "dct_dispatched"),
    ("flight_ops",       "Ace Pilot",         "Launched {n} drone(s)",            1,  "drone_launched"),
    ("electronic_warfare", "Ghost",           "Jammed {n} target(s)",             1,  "jam_target_set"),
    ("tactical",         "Mastermind",        "Created {n} strike plan(s)",       1,  "strike_plan_created"),
    ("captain",          "Decisive Leader",   "Changed alert level {n} time(s)",  1,  "alert_changed"),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_log(log_path: Path) -> list[dict]:
    """Read a JSONL log file and return a list of event dicts. Never raises."""
    events: list[dict] = []
    try:
        with log_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except Exception as exc:
        print(f"[game_debrief] WARNING: could not read log: {exc}", file=sys.stderr)
    return events


def compute_debrief(events: list[dict]) -> dict:
    """Compute debrief data from a list of parsed log events.

    Returns:
        {
          "per_station_stats": { role: {"total": N, "events": {event: count}} },
          "awards": [{"role": ..., "award": ..., "description": ...}],
          "key_moments": [{"ts": float, "text": str}],
          "timeline": [{"ts": float, "x": float, "y": float, "hull": float}],
        }
    """
    per_station: dict[str, dict] = {}
    key_moments: list[dict] = []
    timeline: list[dict] = []

    # Track hull thresholds already reported (to avoid repeat messages).
    hull_milestones_hit: set[int] = set()

    for evt in events:
        cat  = evt.get("cat", "")
        ev   = evt.get("event", "")
        ts   = evt.get("ts", 0.0)
        data = evt.get("data", {})

        # --- per-station counting ---
        role = _CAT_TO_ROLE.get(cat)
        if role:
            entry = per_station.setdefault(role, {"total": 0, "events": {}})
            entry["total"] += 1
            entry["events"][ev] = entry["events"].get(ev, 0) + 1

        # --- key moments ---
        if cat == "mission" and ev == "objective_completed":
            obj_id = data.get("objective_id", "")
            key_moments.append({"ts": ts, "text": f"Objective completed: {obj_id}"})

        elif cat == "game" and ev == "tick_summary":
            hull = data.get("hull", 100.0)
            for threshold in (75, 50, 25):
                if hull <= threshold and threshold not in hull_milestones_hit:
                    hull_milestones_hit.add(threshold)
                    key_moments.append({"ts": ts, "text": f"Hull dropped below {threshold}%"})
            # Collect position for replay timeline.
            x = data.get("x")
            y = data.get("y")
            if x is not None and y is not None:
                timeline.append({"ts": ts, "x": x, "y": y, "hull": hull})

        elif cat == "security" and ev == "boarding_started":
            n = data.get("intruder_count", "?")
            key_moments.append({"ts": ts, "text": f"Boarding party detected! ({n} intruders)"})

        elif cat == "combat" and ev == "system_damaged":
            sys_name = data.get("system", "system")
            comp = data.get("component", "")
            comp_text = f" ({comp})" if comp else ""
            key_moments.append({"ts": ts, "text": f"System damaged: {sys_name}{comp_text}"})

        elif cat == "session" and ev == "ended":
            result = data.get("result", "")
            if result in ("victory", "defeat"):
                label = "Mission complete!" if result == "victory" else "Ship destroyed."
                key_moments.append({"ts": ts, "text": label})

    # Sort key moments by timestamp.
    key_moments.sort(key=lambda m: m["ts"])

    # --- awards ---
    awards: list[dict] = []
    for role, award_name, desc_tmpl, min_count, event_key in _AWARD_DEFS:
        station_data = per_station.get(role, {})
        count = station_data.get("events", {}).get(event_key, 0)
        if count >= min_count:
            awards.append({
                "role":        role,
                "award":       award_name,
                "description": desc_tmpl.format(n=count),
            })

    return {
        "per_station_stats": per_station,
        "awards":            awards,
        "key_moments":       key_moments,
        "timeline":          timeline,
    }


def compute_from_log(log_path: Path) -> dict:
    """Parse log and compute debrief in one call."""
    events = parse_log(log_path)
    return compute_debrief(events)
