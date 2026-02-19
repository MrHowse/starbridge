"""Puzzle type: Frequency Matching (Science).

The player adjusts N frequency components to match a composite target
waveform.  Each component has amplitude (0–1) and frequency (1–5 cycles per
display window) sliders.  The server validates by comparing relative RMS
error against a difficulty-scaled tolerance threshold.

Difficulty controls:
  - Component count: 2 (diff 1) → 5 (diff 5)
  - Tolerance: 0.30 (diff 1, wide) → 0.08 (diff 5, tight)

Assist:
  - widen_tolerance (Engineering sensor boost): tolerance += 0.15, capped at
    0.45.  Returns new tolerance and previous tolerance.
"""
from __future__ import annotations

import math
import random
from typing import Any

from server.puzzles.base import PuzzleInstance
from server.puzzles.engine import register_puzzle_type

_SAMPLE_COUNT = 100  # waveform sample points for comparison
_MAX_TOLERANCE = 0.45  # upper cap after assists

# (component_count, tolerance) indexed by difficulty 1–5.
_DIFFICULTY_PARAMS: dict[int, tuple[int, float]] = {
    1: (2, 0.30),
    2: (2, 0.22),
    3: (3, 0.16),
    4: (4, 0.12),
    5: (5, 0.08),
}


# ---------------------------------------------------------------------------
# Waveform helpers
# ---------------------------------------------------------------------------


def _sample_waveform(components: list[dict[str, float]]) -> list[float]:
    """Sample a composite waveform at _SAMPLE_COUNT points in [0, 1)."""
    return [
        sum(
            c["amplitude"] * math.sin(2.0 * math.pi * c["frequency"] * i / _SAMPLE_COUNT)
            for c in components
        )
        for i in range(_SAMPLE_COUNT)
    ]


def _relative_rms_error(target: list[float], player: list[float]) -> float:
    """RMS error normalised by the target's own RMS (relative error measure)."""
    n = len(target)
    if n == 0:
        return 1.0
    rms_error = math.sqrt(sum((a - b) ** 2 for a, b in zip(target, player)) / n)
    target_rms = math.sqrt(sum(x * x for x in target) / n)
    return rms_error / max(target_rms, 1e-6)


# ---------------------------------------------------------------------------
# Puzzle class
# ---------------------------------------------------------------------------


class FrequencyMatchingPuzzle(PuzzleInstance):
    """Tune amplitude and frequency sliders to match a composite target waveform."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._target_components: list[dict[str, float]] = []
        self._component_count: int = 2
        self._tolerance: float = 0.30

    def generate(self) -> dict[str, Any]:
        count, tol = _DIFFICULTY_PARAMS.get(self.difficulty, (2, 0.30))
        self._component_count = count
        self._tolerance = tol

        # Generate target components with well-separated frequencies.
        self._target_components = []
        used_freqs: list[float] = []
        for _ in range(count):
            for _ in range(30):  # retry until spacing satisfied
                freq = round(random.uniform(1.0, 5.0), 1)
                if all(abs(freq - f) >= 0.5 for f in used_freqs):
                    break
            used_freqs.append(freq)
            amp = round(random.uniform(0.3, 1.0), 2)
            self._target_components.append({"amplitude": amp, "frequency": freq})

        initial_player = [
            {"amplitude": 0.5, "frequency": 3.0} for _ in range(count)
        ]

        return {
            "component_count": count,
            "target_components": [
                {"amplitude": c["amplitude"], "frequency": c["frequency"]}
                for c in self._target_components
            ],
            "tolerance": self._tolerance,
            "initial_player_components": initial_player,
            "success_message": "FREQUENCY LOCKED",
        }

    def validate_submission(self, submission: dict[str, Any]) -> bool:
        """Return True if player waveform is within tolerance of the target."""
        player = submission.get("components", [])
        if len(player) != self._component_count:
            return False
        target_samples = _sample_waveform(self._target_components)
        player_samples = _sample_waveform(player)
        error = _relative_rms_error(target_samples, player_samples)
        return error < self._tolerance

    def apply_assist(self, assist_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Apply an assist to the frequency matching puzzle.

        widen_tolerance (Engineering sensor boost):
            Increase matching tolerance by 0.15, capped at 0.45.

        relay_frequency (Comms decoded transmission):
            Reveal exact values for the target component whose frequency
            is closest to the relayed frequency.
        """
        if assist_type == "widen_tolerance":
            prev = self._tolerance
            self._tolerance = min(prev + 0.15, _MAX_TOLERANCE)
            return {"tolerance": self._tolerance, "previous_tolerance": prev}
        if assist_type == "relay_frequency":
            relay_freq = float(data.get("frequency", 3.0))
            if not self._target_components:
                return {}
            # Find target component with frequency closest to the relayed value
            idx = min(
                range(len(self._target_components)),
                key=lambda i: abs(self._target_components[i]["frequency"] - relay_freq),
            )
            target = self._target_components[idx]
            return {
                "component_index": idx,
                "amplitude": target["amplitude"],
                "frequency": target["frequency"],
            }
        return {}


# Self-register at import time.
register_puzzle_type("frequency_matching", FrequencyMatchingPuzzle)
