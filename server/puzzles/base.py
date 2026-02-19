"""Puzzle system — base class for all puzzle instances.

Every puzzle type subclasses PuzzleInstance and implements three abstract methods:
  generate()            — return puzzle-specific data dict sent to the client
  validate_submission() — return True if the player's answer is correct
  apply_assist()        — apply external help; return data for puzzle.assist_applied

The base tick() handles timeout detection and queues puzzle.result automatically.
Subclasses may override tick() to add degradation or decay effects, but must
call super().tick(dt) first.
"""
from __future__ import annotations

import abc
from typing import Any

from server.models.messages import Message


class PuzzleInstance(abc.ABC):
    """Abstract base class for all puzzle types."""

    def __init__(
        self,
        puzzle_id: str,
        label: str,
        station: str,
        difficulty: int,
        time_limit: float,
        **_kwargs: Any,
    ) -> None:
        self.puzzle_id = puzzle_id
        self.label = label
        self.station = station          # role that receives this puzzle
        self.difficulty = difficulty    # 1–5
        self.time_limit = time_limit    # seconds until auto-timeout

        self._elapsed: float = 0.0
        self._active: bool = True       # False once resolved (success/fail/timeout)
        self._resolved: bool = False    # True once _resolve() has been called
        self._success: bool = False     # set by _resolve(); read by PuzzleEngine
        self._pending: list[tuple[list[str], Message]] = []

    # ------------------------------------------------------------------
    # Abstract interface — subclasses implement these
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def generate(self) -> dict[str, Any]:
        """Generate and return puzzle-specific data for the client.

        Called once immediately after construction. The returned dict is sent
        as the ``data`` field of the ``puzzle.started`` message.
        """

    @abc.abstractmethod
    def validate_submission(self, submission: dict[str, Any]) -> bool:
        """Return True if the player's answer is correct."""

    @abc.abstractmethod
    def apply_assist(self, assist_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Apply an external assist. Return data sent in puzzle.assist_applied."""

    # ------------------------------------------------------------------
    # Base behaviour
    # ------------------------------------------------------------------

    def tick(self, dt: float) -> None:
        """Advance the puzzle timer. Auto-resolves as failure on timeout."""
        if not self._active:
            return
        self._elapsed += dt
        if self._elapsed >= self.time_limit and not self._resolved:
            self._resolve(success=False, reason="timeout")

    def is_active(self) -> bool:
        return self._active

    def time_remaining(self) -> float:
        return max(0.0, self.time_limit - self._elapsed)

    def pop_pending_broadcasts(self) -> list[tuple[list[str], Message]]:
        """Return and clear pending broadcasts."""
        broadcasts = list(self._pending)
        self._pending.clear()
        return broadcasts

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve(self, success: bool, reason: str = "") -> None:
        """Mark as resolved and queue a puzzle.result broadcast to the station role."""
        if self._resolved:
            return
        self._resolved = True
        self._active = False
        self._success = success

        payload: dict[str, Any] = {
            "puzzle_id": self.puzzle_id,
            "label": self.label,
            "success": success,
            "time_taken": round(self._elapsed, 1),
        }
        if reason:
            payload["reason"] = reason

        self._pending.append((
            [self.station],
            Message.build("puzzle.result", payload),
        ))
