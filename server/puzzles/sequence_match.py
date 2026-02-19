"""Puzzle type: Sequence Match (proof-of-concept).

The server generates a random colour sequence. The player must click the
colours in the correct order and submit. An assist reveals the first N
elements of the sequence.

This puzzle has no direct gameplay value — it exists to exercise every
lifecycle path of the puzzle framework: generate, render, timed interaction,
assist application, submission, validation, and success/failure broadcast.
"""
from __future__ import annotations

import random
from typing import Any

from server.puzzles.base import PuzzleInstance
from server.puzzles.engine import register_puzzle_type

COLOURS: list[str] = ["red", "blue", "green", "yellow"]


class SequenceMatchPuzzle(PuzzleInstance):
    """Click the generated colour sequence in order."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._sequence: list[str] = []
        self._revealed: int = 0  # elements pre-revealed by assist

    def generate(self) -> dict[str, Any]:
        """Generate a random colour sequence. Length scales with difficulty (4–8)."""
        length = 3 + self.difficulty  # difficulty 1 → 4, difficulty 5 → 8
        self._sequence = [random.choice(COLOURS) for _ in range(length)]
        return {
            "type": "sequence_match",
            "length": len(self._sequence),
            "colours": COLOURS,
            "revealed": self._revealed,
            "revealed_sequence": self._sequence[: self._revealed],
        }

    def validate_submission(self, submission: dict[str, Any]) -> bool:
        return submission.get("sequence") == self._sequence

    def apply_assist(self, assist_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Support 'reveal_start' assist — reveal the first N sequence elements."""
        if assist_type == "reveal_start":
            n = int(data.get("count", 1))
            # Reveal at most (length - 1) elements — don't give away the whole answer.
            self._revealed = min(max(self._revealed, n), len(self._sequence) - 1)
            return {
                "revealed": self._revealed,
                "revealed_sequence": self._sequence[: self._revealed],
            }
        return {}


# Self-register when this module is imported.
register_puzzle_type("sequence_match", SequenceMatchPuzzle)
