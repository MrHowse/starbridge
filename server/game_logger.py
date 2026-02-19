"""Game Event Logger.

Writes one JSON record per line to logs/game_YYYYMMDD_HHMMSS.jsonl.
Format: {"tick": N, "ts": float, "cat": "...", "event": "...", "data": {...}}

Enable / disable via environment variable:
  STARBRIDGE_LOGGING=false  →  logging disabled
  STARBRIDGE_LOGGING=true   →  logging enabled (default)

Never raises: all I/O is wrapped in try/except to protect the game loop.
"""
from __future__ import annotations

import json
import os
import sys
import time as _time
from datetime import datetime
from pathlib import Path
from typing import TextIO


class GameLogger:
    """Logs significant game events to a JSONL file for post-session analysis."""

    def __init__(self) -> None:
        self._log_file: Path | None = None
        self._fh: TextIO | None = None
        self._active: bool = False
        self._tick: int = 0
        self._start_ts: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, mission_id: str, players: dict[str, str]) -> None:
        """Open a new log file and write the session header."""
        if os.environ.get("STARBRIDGE_LOGGING", "true").lower() == "false":
            return
        try:
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._log_file = log_dir / f"game_{ts}.jsonl"
            self._fh = self._log_file.open("a", encoding="utf-8")
            self._active = True
            self._tick = 0
            self._start_ts = _time.monotonic()
            self._write({"tick": 0, "ts": 0.0, "cat": "session", "event": "started",
                         "data": {"mission_id": mission_id, "players": players}})
        except Exception as exc:
            print(f"[game_logger] WARNING: could not open log file: {exc}", file=sys.stderr)
            self._active = False

    def log(self, category: str, event: str, data: dict | None = None) -> None:
        """Write one event to the log. Never raises."""
        if not self._active:
            return
        try:
            self._write({
                "tick": self._tick,
                "ts": round(_time.monotonic() - self._start_ts, 3),
                "cat": category,
                "event": event,
                "data": data or {},
            })
        except Exception as exc:
            print(f"[game_logger] WARNING: log write failed: {exc}", file=sys.stderr)

    def set_tick(self, tick: int) -> None:
        """Update the current tick counter. Called each game tick."""
        self._tick = tick

    def stop(self, result: str, stats: dict | None = None) -> None:
        """Write session footer and close the log file."""
        if not self._active:
            return
        try:
            self._write({
                "tick": self._tick,
                "ts": round(_time.monotonic() - self._start_ts, 3),
                "cat": "session",
                "event": "ended",
                "data": {"result": result, "stats": stats or {}},
            })
            if self._fh is not None:
                self._fh.flush()
                self._fh.close()
        except Exception as exc:
            print(f"[game_logger] WARNING: could not close log file: {exc}", file=sys.stderr)
        self._active = False
        self._fh = None
        if self._log_file is not None:
            print(f"[game_logger] Session log written: {self._log_file.resolve()}", file=sys.stderr)
        self._log_file = None

    def is_active(self) -> bool:
        return self._active

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write(self, record: dict) -> None:
        """Write one record. Caller is responsible for catching exceptions."""
        assert self._fh is not None
        self._fh.write(json.dumps(record) + "\n")
        self._fh.flush()


# ---------------------------------------------------------------------------
# Module-level singleton and convenience functions
# ---------------------------------------------------------------------------

_logger = GameLogger()


def start_logging(mission_id: str, players: dict[str, str]) -> None:
    """Open a new log session. Called from lobby when the game starts."""
    _logger.start(mission_id, players)


def log_event(category: str, event: str, data: dict | None = None) -> None:
    """Log a game event. No-op when logging is disabled or inactive."""
    _logger.log(category, event, data)


def set_tick(tick: int) -> None:
    """Update the current tick counter."""
    _logger.set_tick(tick)


def stop_logging(result: str, stats: dict | None = None) -> None:
    """Close the log session."""
    _logger.stop(result, stats)


def is_logging() -> bool:
    """Return True if an active log session is open."""
    return _logger.is_active()
