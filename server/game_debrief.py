"""Game Debrief Computation.

Parses a completed JSONL session log and returns structured debrief data:
  - per_station_stats: action counts per station
  - awards: earned awards per station (one per station, threshold-based)
  - key_moments: notable events with timestamps
  - timeline: periodic position snapshots for the Captain's Replay
  - dynamic_missions: mission outcomes (offered/accepted/completed/failed)
  - comms_performance: signals decoded, intel routed, diplomatic outcomes

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
    "helm":             "helm",
    "weapons":          "weapons",
    "engineering":      "engineering",
    "science":          "science",
    "medical":          "medical",
    "security":         "security",
    "comms":            "comms",
    "flight_ops":       "flight_ops",
    "ew":               "electronic_warfare",
    "tactical":         "tactical",
    "captain":          "captain",
    "dynamic_mission":  "captain",  # mission events count toward captain
    "maintenance":      "janitor",
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
    ("janitor",          "Employee of the Month (14 months running)", "Toilets fixed, floors mopped, coffee restocked. {n} task(s) completed. Nobody will ever know.", 1, "general"),
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
          "dynamic_missions": { ... },
          "comms_performance": { ... },
        }
    """
    per_station: dict[str, dict] = {}
    key_moments: list[dict] = []
    timeline: list[dict] = []

    # Track hull thresholds already reported (to avoid repeat messages).
    hull_milestones_hit: set[int] = set()

    # Dynamic mission tracking
    missions_offered: list[dict] = []
    missions_accepted: list[str] = []
    missions_declined: list[str] = []
    missions_expired: list[str] = []
    missions_completed: list[dict] = []
    missions_failed: list[dict] = []
    objectives_completed: int = 0
    objectives_total: int = 0

    # Comms performance tracking
    signals_decoded: int = 0
    decode_started_ts: dict[str, float] = {}  # signal_id → start_ts
    decode_durations: list[float] = []
    intel_routed: int = 0
    intel_destinations: dict[str, int] = {}
    diplomatic_responses: int = 0
    standing_changes: list[dict] = []
    hails_sent: int = 0

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

        # --- dynamic mission events ---
        elif cat == "dynamic_mission":
            if ev == "mission_offered":
                mission_data = data.get("mission", {})
                missions_offered.append({
                    "id": mission_data.get("id", data.get("mission_id", "")),
                    "title": mission_data.get("title", ""),
                    "mission_type": mission_data.get("mission_type", ""),
                    "ts": ts,
                })
                objectives_total += len(mission_data.get("objectives", []))
            elif ev == "mission_accepted":
                mid = data.get("mission", {}).get("id", data.get("mission_id", ""))
                missions_accepted.append(mid)
                key_moments.append({"ts": ts, "text": f"Mission accepted: {data.get('mission', {}).get('title', mid)}"})
            elif ev == "mission_declined":
                missions_declined.append(data.get("mission_id", ""))
            elif ev == "mission_expired":
                missions_expired.append(data.get("mission_id", ""))
            elif ev == "mission_completed":
                missions_completed.append({
                    "mission_id": data.get("mission_id", ""),
                    "title": data.get("title", ""),
                    "rewards": data.get("rewards", {}),
                })
                key_moments.append({"ts": ts, "text": f"Mission completed: {data.get('title', '')}"})
            elif ev == "mission_failed":
                missions_failed.append({
                    "mission_id": data.get("mission_id", ""),
                    "title": data.get("title", ""),
                    "reason": data.get("reason", ""),
                })
                key_moments.append({"ts": ts, "text": f"Mission failed: {data.get('title', '')}"})
            elif ev == "objective_completed":
                objectives_completed += 1

        # --- comms performance events ---
        elif cat == "comms":
            if ev == "decode_started":
                decode_started_ts[data.get("signal_id", "")] = ts
            elif ev == "signal_decoded":
                signals_decoded += 1
                sid = data.get("signal_id", "")
                if sid in decode_started_ts:
                    decode_durations.append(ts - decode_started_ts[sid])
            elif ev == "intel_routed":
                intel_routed += 1
                dest = data.get("target", "")
                intel_destinations[dest] = intel_destinations.get(dest, 0) + 1
            elif ev == "diplomatic_response":
                diplomatic_responses += 1
            elif ev == "standing_changed":
                standing_changes.append({
                    "faction": data.get("faction", ""),
                    "amount": data.get("amount", 0),
                    "reason": data.get("reason", ""),
                })
            elif ev == "hail_sent":
                hails_sent += 1

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

    # --- dynamic missions summary ---
    dynamic_missions = {
        "missions_offered": len(missions_offered),
        "missions_accepted": len(missions_accepted),
        "missions_declined": len(missions_declined),
        "missions_expired": len(missions_expired),
        "missions_completed": len(missions_completed),
        "missions_failed": len(missions_failed),
        "objectives_completed": objectives_completed,
        "objectives_total": objectives_total,
        "mission_details": missions_offered,
        "completion_details": missions_completed,
        "failure_details": missions_failed,
        "total_rewards": _aggregate_rewards(missions_completed),
    }

    # --- comms performance summary ---
    avg_decode_time = (
        round(sum(decode_durations) / len(decode_durations), 1)
        if decode_durations else 0.0
    )
    # Aggregate standing changes per faction
    net_standings: dict[str, float] = {}
    for sc in standing_changes:
        fid = sc["faction"]
        net_standings[fid] = net_standings.get(fid, 0.0) + sc["amount"]

    comms_performance = {
        "signals_decoded": signals_decoded,
        "avg_decode_time": avg_decode_time,
        "intel_routed": intel_routed,
        "intel_destinations": intel_destinations,
        "diplomatic_responses": diplomatic_responses,
        "hails_sent": hails_sent,
        "standing_changes": standing_changes,
        "net_standings": {k: round(v, 1) for k, v in net_standings.items()},
    }

    # v0.07 §2.3: Include active equipment module names.
    import server.equipment_modules as _gleq
    equipment_module_names = _gleq.get_module_names()

    # v0.07 §2.4: Flag bridge active status.
    import server.game_loop_flag_bridge as _glfb
    flag_bridge_active = _glfb.is_active()

    # v0.07 §2.5: Spinal mount active status.
    import server.game_loop_spinal_mount as _glsm
    spinal_mount_active = _glsm.is_active()

    # v0.07 §2.6: Carrier ops active status.
    import server.game_loop_carrier_ops as _glcar
    carrier_ops_active = _glcar.is_active()

    # v0.07 §2.7: Medical ship active status.
    import server.game_loop_medical_ship as _glms
    medical_ship_active = _glms.is_active()

    return {
        "per_station_stats": per_station,
        "awards":            awards,
        "key_moments":       key_moments,
        "timeline":          timeline,
        "dynamic_missions":  dynamic_missions,
        "comms_performance": comms_performance,
        "equipment_modules": equipment_module_names,
        "flag_bridge_active": flag_bridge_active,
        "spinal_mount_active": spinal_mount_active,
        "carrier_ops_active": carrier_ops_active,
        "medical_ship_active": medical_ship_active,
    }


def _aggregate_rewards(completed_missions: list[dict]) -> dict:
    """Sum up rewards from all completed missions."""
    total: dict[str, object] = {
        "crew": 0,
        "reputation": 0,
        "faction_standing": {},
        "supplies": {},
    }
    for m in completed_missions:
        rewards = m.get("rewards", {})
        total["crew"] += rewards.get("crew", 0)  # type: ignore[operator]
        total["reputation"] += rewards.get("reputation", 0)  # type: ignore[operator]
        for fid, amt in rewards.get("faction_standing", {}).items():
            total["faction_standing"][fid] = total["faction_standing"].get(fid, 0.0) + amt  # type: ignore[union-attr]
        for item, qty in rewards.get("supplies", {}).items():
            total["supplies"][item] = total["supplies"].get(item, 0) + qty  # type: ignore[union-attr]
    return total


def compute_from_log(log_path: Path) -> dict:
    """Parse log and compute debrief in one call."""
    events = parse_log(log_path)
    return compute_debrief(events)
