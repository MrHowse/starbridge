"""
Player Profile Manager — v0.04g.

Profiles are stored as individual JSON files in PROFILES_DIR (profiles/ at the
repo root).  Each profile accumulates cross-session statistics and unlocks
career achievements.

Public API
----------
get_or_create_profile(name)          → dict
update_game_result(name, role, …)    → list[str]  (newly unlocked achievement IDs)
get_profile(name)                    → dict | None
list_profiles()                      → list[dict]  (sorted by games_won desc)
export_csv()                         → str
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("starbridge.profiles")

PROFILES_DIR = Path(__file__).parent.parent / "profiles"

# ---------------------------------------------------------------------------
# Achievement definitions
# ---------------------------------------------------------------------------

# Each entry: (id, human-readable description, threshold-check key)
# Checks are evaluated in check_achievements() against the profile dict.
ACHIEVEMENTS: list[tuple[str, str]] = [
    ("first_command",  "Complete your first mission"),
    ("bridge_regular", "Play 5 or more games"),
    ("veteran",        "Play 20 or more games"),
    ("sharpshooter",   "Fire 50 beam shots across your career"),
    ("life_saver",     "Administer 20 treatments across your career"),
    ("explorer",       "Play 5 different missions"),
]


def _check_achievements(profile: dict) -> list[str]:
    """Return list of achievement IDs that *should* be unlocked for this profile.

    Called after each stat update so newly earned achievements are detected.
    """
    games    = profile.get("games_played", 0)
    career   = profile.get("career_events", {})
    missions = profile.get("missions_played", [])

    checks: dict[str, bool] = {
        "first_command":  games >= 1,
        "bridge_regular": games >= 5,
        "veteran":        games >= 20,
        "sharpshooter":   career.get("beam_fired", 0) >= 50,
        "life_saver":     career.get("treatment_started", 0) >= 20,
        "explorer":       len(missions) >= 5,
    }
    return [ach_id for ach_id, _ in ACHIEVEMENTS if checks.get(ach_id, False)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _profile_path(name: str) -> Path:
    return PROFILES_DIR / f"{name}.json"


def _save_profile(profile: dict) -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    _profile_path(profile["name"]).write_text(
        json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_or_create_profile(name: str) -> dict:
    """Return the profile for *name*, creating it if it does not exist yet."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = _profile_path(name)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Corrupted profile for %r — recreating. (%s)", name, exc)

    profile: dict = {
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "games_played": 0,
        "games_won": 0,
        "games_lost": 0,
        "total_duration_s": 0.0,
        "missions_played": [],   # unique mission IDs
        "career_events": {},     # event_name → cumulative count
        "achievements": [],      # list of unlocked achievement IDs
        "last_played_at": None,
    }
    _save_profile(profile)
    return profile


def update_game_result(
    name: str,
    role: str,
    result: str,          # "victory" | "defeat"
    mission_id: str,
    duration_s: float,
    station_stats: dict,  # per_station_stats from game_debrief: {role: {events: {evt: n}}}
) -> list[str]:
    """Record the outcome of a completed game and return newly unlocked achievements."""
    profile = get_or_create_profile(name)

    # Basic counters.
    profile["games_played"] = profile.get("games_played", 0) + 1
    if result == "victory":
        profile["games_won"] = profile.get("games_won", 0) + 1
    else:
        profile["games_lost"] = profile.get("games_lost", 0) + 1
    profile["total_duration_s"] = profile.get("total_duration_s", 0.0) + duration_s
    profile["last_played_at"] = datetime.now(timezone.utc).isoformat()

    # Mission variety.
    missions: list[str] = profile.setdefault("missions_played", [])
    if mission_id and mission_id not in missions:
        missions.append(mission_id)

    # Career event accumulation from this session's station stats.
    career: dict = profile.setdefault("career_events", {})
    role_stats = station_stats.get(role, {})
    for evt, count in role_stats.get("events", {}).items():
        career[evt] = career.get(evt, 0) + int(count)

    # Achievement check.
    prev: list[str] = profile.get("achievements", [])
    now_unlocked = _check_achievements(profile)
    newly_unlocked = [a for a in now_unlocked if a not in prev]
    profile["achievements"] = now_unlocked

    _save_profile(profile)
    return newly_unlocked


def get_profile(name: str) -> dict | None:
    """Return the full profile dict, or None if the profile does not exist."""
    path = _profile_path(name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read profile %r: %s", name, exc)
        return None


def list_profiles() -> list[dict]:
    """Return summary dicts for all profiles, sorted by games_won descending."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    summaries: list[dict] = []
    for path in PROFILES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            summaries.append({
                "name":          data.get("name", path.stem),
                "games_played":  data.get("games_played", 0),
                "games_won":     data.get("games_won", 0),
                "games_lost":    data.get("games_lost", 0),
                "achievements":  data.get("achievements", []),
                "last_played_at": data.get("last_played_at"),
            })
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping unreadable profile %r: %s", path.name, exc)
    summaries.sort(key=lambda p: (-p["games_won"], -p["games_played"]))
    return summaries


def export_csv() -> str:
    """Return all profile summaries as a CSV-formatted string."""
    profiles = list_profiles()
    out = io.StringIO()
    fieldnames = ["name", "games_played", "games_won", "games_lost", "achievements", "last_played_at"]
    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for p in profiles:
        row = dict(p)
        row["achievements"] = "|".join(p.get("achievements", []))
        writer.writerow(row)
    return out.getvalue()
