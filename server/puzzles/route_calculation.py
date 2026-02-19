"""
Route Calculation Puzzle — Helm station.

The player is shown a sector grid with known hazards and unknown (hidden)
cells. They must plot a continuous path from the top-left (start) to the
bottom-right (end) without passing through any hazardous cells.

Generation guarantees a valid all-safe path exists. Hidden cells may be safe
or hazardous — the player can choose to risk them or use the Science assist
to reveal their true nature.

Difficulty controls grid size, hazard count, and hidden cell count:
  1 → 5×5 grid,  4 hazards,  2 hidden  (easiest)
  2 → 6×6 grid,  6 hazards,  3 hidden
  3 → 7×7 grid,  9 hazards,  4 hidden
  4 → 8×8 grid, 12 hazards,  5 hidden
  5 → 9×9 grid, 15 hazards,  6 hidden

Science → Helm assist:
  reveal_hazard — Science sensors scan one hidden cell and reveal its true
                  nature (safe or hazardous).
"""
from __future__ import annotations

import random
from collections import deque
from typing import Any

from server.puzzles.base import PuzzleInstance
from server.puzzles.engine import register_puzzle_type

# ---------------------------------------------------------------------------
# Difficulty parameters: (grid_size, hazard_count, hidden_count)
# ---------------------------------------------------------------------------

_DIFFICULTY_PARAMS: dict[int, tuple[int, int, int]] = {
    1: (5, 4,  2),
    2: (6, 6,  3),
    3: (7, 9,  4),
    4: (8, 12, 5),
    5: (9, 15, 6),
}


# ---------------------------------------------------------------------------
# BFS helper
# ---------------------------------------------------------------------------


def _bfs_path(
    grid: list[list[str]],
    size: int,
    start: tuple[int, int],
    end: tuple[int, int],
) -> list[tuple[int, int]] | None:
    """BFS through safe cells only. Returns path or None if no path exists."""
    visited: set[tuple[int, int]] = {start}
    queue: deque[list[tuple[int, int]]] = deque([[start]])

    while queue:
        path = queue.popleft()
        r, c = path[-1]
        if (r, c) == end:
            return path  # type: ignore[return-value]
        for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < size and 0 <= nc < size and (nr, nc) not in visited:
                if grid[nr][nc] == "safe":
                    visited.add((nr, nc))
                    queue.append(path + [(nr, nc)])

    return None


# ---------------------------------------------------------------------------
# Puzzle class
# ---------------------------------------------------------------------------


class RouteCalculationPuzzle(PuzzleInstance):
    """Helm station route calculation puzzle."""

    def generate(self, **kwargs: Any) -> dict:
        size, hazard_count, hidden_count = _DIFFICULTY_PARAMS.get(
            self.difficulty, (5, 4, 2)
        )
        self._size = size
        start = (0, 0)
        end = (size - 1, size - 1)

        # Retry until a valid path exists (avoid degenerate layouts).
        for _ in range(30):
            # Build all-safe grid.
            true_grid = [["safe"] * size for _ in range(size)]

            # Place hazards on random non-start, non-end cells.
            candidates = [
                (r, c)
                for r in range(size)
                for c in range(size)
                if (r, c) not in {start, end}
            ]
            hazard_positions = random.sample(
                candidates, min(hazard_count, len(candidates))
            )
            for r, c in hazard_positions:
                true_grid[r][c] = "hazard"

            # Confirm a valid path exists.
            path = _bfs_path(true_grid, size, start, end)
            if path:
                break
        else:
            # Fallback: clear all hazards (shouldn't normally happen).
            true_grid = [["safe"] * size for _ in range(size)]
            path = _bfs_path(true_grid, size, start, end)

        assert path is not None
        self._true_grid: list[list[str]] = true_grid
        self._guaranteed_path: list[tuple[int, int]] = path

        # Build display grid (starts as a copy of true grid).
        display_grid = [row[:] for row in true_grid]

        # Mark some off-path non-terminal cells as "hidden".
        path_set = set(path)
        off_path = [
            (r, c)
            for r in range(size)
            for c in range(size)
            if (r, c) not in path_set and (r, c) not in {start, end}
        ]
        hidden_positions = random.sample(off_path, min(hidden_count, len(off_path)))
        for r, c in hidden_positions:
            display_grid[r][c] = "hidden"

        self._display_grid: list[list[str]] = display_grid
        self._hidden_cells: list[tuple[int, int]] = hidden_positions
        self._revealed_cells: set[tuple[int, int]] = set()

        # Build cell data for client.
        cells = [
            [{"type": display_grid[r][c]} for c in range(size)]
            for r in range(size)
        ]

        return {
            "grid_size": size,
            "cells":     cells,
            "start":     list(start),
            "end":       list(end),
        }

    def validate_submission(self, data: dict) -> bool:
        """Return True iff the submitted path is valid.

        ``data = {"path": [[row, col], ...]}``

        Validity rules:
        - Starts at (0, 0).
        - Ends at (size-1, size-1).
        - Each step moves exactly one cell in a cardinal direction.
        - No cell in the path has true type "hazard".
        """
        path = data.get("path")
        if not isinstance(path, list) or len(path) < 2:
            return False

        size = self._size
        start = [0, 0]
        end   = [size - 1, size - 1]

        if path[0] != start or path[-1] != end:
            return False

        # Validate each step.
        for i in range(len(path) - 1):
            r1, c1 = path[i]
            r2, c2 = path[i + 1]
            # Must be within bounds.
            if not (0 <= r1 < size and 0 <= c1 < size):
                return False
            # Must be exactly one step in a cardinal direction.
            if abs(r2 - r1) + abs(c2 - c1) != 1:
                return False
            # True type must not be "hazard".
            if self._true_grid[r1][c1] == "hazard":
                return False

        # Check final cell.
        r_last, c_last = path[-1]
        if not (0 <= r_last < size and 0 <= c_last < size):
            return False
        if self._true_grid[r_last][c_last] == "hazard":
            return False

        return True

    def apply_assist(self, assist_type: str, data: dict) -> dict:
        """Apply a Science sensor-scan assist.

        ``reveal_hazard`` — Science scans one unrevealed hidden cell and
            returns its true nature.
            Returns ``{"row": int, "col": int, "safe": bool}`` or ``{}``
            when all hidden cells have already been revealed.
        """
        if assist_type == "reveal_hazard":
            for r, c in self._hidden_cells:
                if (r, c) not in self._revealed_cells:
                    self._revealed_cells.add((r, c))
                    is_safe = self._true_grid[r][c] == "safe"
                    return {"row": r, "col": c, "safe": is_safe}
            return {}  # All hidden cells already revealed.

        return {}


register_puzzle_type("route_calculation", RouteCalculationPuzzle)
