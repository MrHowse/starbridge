"""Puzzle type: Transmission Decoding (Comms).

The player decodes an intercepted alien transmission by deducing unknown
cipher symbol values.  Known symbols are provided as hints; sum equations
constrain the unknowns.

Structure:
  - N symbols, each with a hidden integer value 1–9 (unique per puzzle).
  - revealed_count symbols are shown as direct hints.
  - Each unknown symbol appears in at least one sum equation paired with a
    known symbol, guaranteeing a unique solution.
  - Extra equations are generated for realism.

Difficulty controls:
  - (num_symbols, revealed_count) by difficulty 1–5.
  - More unknowns = harder.

Assist:
  - reveal_symbol: reveals one additional unknown symbol's value.

Comms → Science relay chain:
  - _relay_component is set on successful resolution.
  - The game loop reads this via PuzzleEngine.pop_relay_data() and applies
    it as a relay_frequency assist to Science's active frequency_matching
    puzzle.
"""
from __future__ import annotations

import random
from typing import Any

from server.puzzles.base import PuzzleInstance
from server.puzzles.engine import register_puzzle_type

_SYMBOLS = ["ALPHA", "BRAVO", "CHARLIE", "DELTA", "EPSILON", "FOXTROT", "GOLF"]

# (num_symbols, revealed_count) → unknowns = num_symbols - revealed_count
_DIFFICULTY_PARAMS: dict[int, tuple[int, int]] = {
    1: (3, 2),   # 1 unknown
    2: (4, 2),   # 2 unknowns
    3: (4, 1),   # 3 unknowns
    4: (5, 1),   # 4 unknowns
    5: (6, 1),   # 5 unknowns
}


class TransmissionDecodingPuzzle(PuzzleInstance):
    """Deduce cipher symbol values from partial hints and sum equations."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._symbol_values: dict[str, int] = {}   # symbol → true value
        self._revealed: set[str] = set()           # symbols with known values
        self._unknowns: list[str] = []             # symbols player must decode
        self._equations: list[dict[str, Any]] = [] # sum equations as clues
        self._relay_component: dict[str, float] = {}  # for Comms→Science relay

    def generate(self) -> dict[str, Any]:
        num_syms, revealed_count = _DIFFICULTY_PARAMS.get(
            self.difficulty, (3, 2)
        )
        syms = random.sample(_SYMBOLS, num_syms)
        values = random.sample(range(1, 10), num_syms)
        self._symbol_values = dict(zip(syms, values))

        # Split into revealed vs unknown
        revealed_syms = syms[:revealed_count]
        unknown_syms = syms[revealed_count:]
        self._revealed = set(revealed_syms)
        self._unknowns = list(unknown_syms)

        # Generate equations: each unknown gets at least one eq with a known
        equations: list[dict[str, Any]] = []
        for unknown in unknown_syms:
            partner = random.choice(revealed_syms)
            equations.append({
                "symbols": [unknown, partner],
                "total": self._symbol_values[unknown] + self._symbol_values[partner],
            })

        # Add extra cross-pair equations for realism (all pairs we haven't used)
        extra_pairs = [
            (a, b)
            for i, a in enumerate(syms)
            for b in syms[i + 1:]
            if not any(
                set(eq["symbols"]) == {a, b} for eq in equations
            )
        ]
        random.shuffle(extra_pairs)
        for a, b in extra_pairs[:2]:
            equations.append({
                "symbols": [a, b],
                "total": self._symbol_values[a] + self._symbol_values[b],
            })

        random.shuffle(equations)
        self._equations = equations

        # Derive relay component from the first unknown symbol's value
        if unknown_syms:
            v = self._symbol_values[unknown_syms[0]]
            # Map value 1–9 → amplitude 0.30–1.00, frequency 1.0–5.0
            t = (v - 1) / 8.0
            self._relay_component = {
                "amplitude": round(0.30 + t * 0.70, 2),
                "frequency": round(1.0 + t * 4.0, 1),
            }

        return {
            "symbols": [
                {
                    "code": sym,
                    "value": self._symbol_values[sym] if sym in self._revealed else None,
                }
                for sym in syms
            ],
            "equations": [
                {"symbols": eq["symbols"], "total": eq["total"]}
                for eq in self._equations
            ],
            "unknowns": self._unknowns,
            "success_message": "TRANSMISSION DECODED",
        }

    def validate_submission(self, submission: dict[str, Any]) -> bool:
        """Return True if all unknown symbols are correctly decoded."""
        mappings: dict[str, Any] = submission.get("mappings", {})
        for sym in self._unknowns:
            submitted = mappings.get(sym)
            try:
                if int(submitted) != self._symbol_values[sym]:
                    return False
            except (TypeError, ValueError):
                return False
        return True

    def apply_assist(self, assist_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """reveal_symbol: reveal one unrevealed unknown symbol."""
        if assist_type != "reveal_symbol":
            return {}
        # Find the first unknown that hasn't been revealed yet
        hidden = [s for s in self._unknowns if s not in self._revealed]
        if not hidden:
            return {}
        sym = hidden[0]
        self._revealed.add(sym)
        return {"revealed_symbol": sym, "value": self._symbol_values[sym]}


# Self-register at import time.
register_puzzle_type("transmission_decoding", TransmissionDecodingPuzzle)
