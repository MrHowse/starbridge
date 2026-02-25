"""
Admin module — v0.04h.

Tracks per-station engagement (last interaction time) and provides the state
snapshot used by the admin dashboard REST endpoint.

Engagement status:
  "active"  — interaction within the last IDLE_SECS seconds
  "idle"    — no interaction for IDLE_SECS–AWAY_SECS seconds
  "away"    — no interaction for more than AWAY_SECS seconds
  "offline" — no interaction recorded (role never connected)
"""
from __future__ import annotations

import time
from typing import Literal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IDLE_SECS: float = 30.0   # after 30 s with no action → amber
AWAY_SECS: float = 60.0   # after 60 s with no action → red

ALL_STATION_ROLES: list[str] = [
    "captain", "helm", "weapons", "engineering", "science",
    "medical", "security", "comms", "flight_ops",
    "electronic_warfare", "tactical", "damage_control",
]

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_last_interaction: dict[str, float] = {}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

EngagementStatus = Literal["active", "idle", "away", "offline"]


def reset() -> None:
    """Clear engagement history.  Call when a game ends."""
    _last_interaction.clear()


def update_interaction(role: str) -> None:
    """Record that *role* sent a message right now.

    Called from main.py._handle_message for every inbound station message.
    """
    _last_interaction[role] = time.monotonic()


def get_engagement_status(role: str) -> EngagementStatus:
    """Return the engagement status for *role*."""
    if role not in _last_interaction:
        return "offline"
    elapsed = time.monotonic() - _last_interaction[role]
    if elapsed < IDLE_SECS:
        return "active"
    if elapsed < AWAY_SECS:
        return "idle"
    return "away"


def build_engagement_report() -> dict[str, dict]:
    """Return engagement status for all station roles.

    If the janitor role has engagement data, it is redacted as
    '███████████' with status 'CLASSIFIED'.
    """
    now = time.monotonic()
    report: dict[str, dict] = {}
    for role in ALL_STATION_ROLES:
        if role in _last_interaction:
            elapsed = round(now - _last_interaction[role], 1)
            status: EngagementStatus = get_engagement_status(role)
        else:
            elapsed = -1.0
            status = "offline"
        report[role] = {
            "status": status,
            "seconds_since_last_action": elapsed if elapsed >= 0 else None,
        }
    # Redact janitor if present.
    if "janitor" in _last_interaction:
        report["\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588"] = {
            "status": "CLASSIFIED",
            "seconds_since_last_action": None,
        }
    return report
