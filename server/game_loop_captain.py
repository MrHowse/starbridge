"""
Captain sub-module for the game loop.

Manages the Captain's log state.  Nuclear authorisation state lives in
game_loop_weapons (the requester) and is routed through the game loop.
"""
from __future__ import annotations

import time as _time

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_captain_log: list[dict] = []   # [{"text": str, "timestamp": float}, ...]


def reset() -> None:
    """Reset captain state. Call at game start."""
    global _captain_log
    _captain_log = []


def add_log_entry(text: str) -> dict:
    """Append a log entry and return it."""
    entry = {"text": text, "timestamp": round(_time.time(), 2)}
    _captain_log.append(entry)
    return entry


def get_log() -> list[dict]:
    """Return a copy of all log entries."""
    return list(_captain_log)


def serialise() -> dict:
    return {
        "captain_log": list(_captain_log),
    }


def deserialise(data: dict) -> None:
    _captain_log.clear()
    _captain_log.extend(data.get("captain_log", []))
