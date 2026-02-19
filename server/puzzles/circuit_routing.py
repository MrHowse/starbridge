"""Puzzle type: Circuit Routing (Engineering).

Route power from a source node to a target node by placing conduit
connections on a damaged circuit grid.  Some conduits survive; others are
broken and must be re-routed with a limited supply of spare conduits.

Difficulty controls:
  - Grid size: 3×3 (diff 1) → 5×5 (diff 5)
  - Damaged (impassable) nodes: difficulty − 1
  - Spare conduit slack above the minimum: [2, 2, 1, 1, 0][difficulty − 1]

Assist:
  - highlight_nodes (from Science): returns node IDs on the solution path
"""
from __future__ import annotations

import random
from collections import deque
from typing import Any

from server.puzzles.base import PuzzleInstance
from server.puzzles.engine import register_puzzle_type

# Grid (rows, cols) per difficulty level.
_GRID_SIZES: dict[int, tuple[int, int]] = {
    1: (3, 3),
    2: (4, 3),
    3: (4, 4),
    4: (5, 4),
    5: (5, 5),
}

# Extra spare conduits beyond the minimum needed to solve.
_SLACK: list[int] = [2, 2, 1, 1, 0]  # indexed by (difficulty − 1)


# ---------------------------------------------------------------------------
# Grid helpers
# ---------------------------------------------------------------------------


def _node_id(row: int, col: int) -> str:
    return f"r{row}c{col}"


def _parse_node_id(nid: str) -> tuple[int, int]:
    """'r2c3' → (2, 3)."""
    row_str, col_str = nid[1:].split("c", 1)
    return int(row_str), int(col_str)


def _are_adjacent(a: str, b: str) -> bool:
    r1, c1 = _parse_node_id(a)
    r2, c2 = _parse_node_id(b)
    return abs(r1 - r2) + abs(c1 - c2) == 1


def _canon_edge(a: str, b: str) -> frozenset[str]:
    return frozenset({a, b})


def _build_all_edges(valid_nodes: set[str]) -> set[frozenset[str]]:
    edges: set[frozenset[str]] = set()
    node_list = sorted(valid_nodes)
    for i, n1 in enumerate(node_list):
        for n2 in node_list[i + 1 :]:
            if _are_adjacent(n1, n2):
                edges.add(_canon_edge(n1, n2))
    return edges


def _bfs_path(
    source: str,
    target: str,
    edges: set[frozenset[str]],
    valid_nodes: set[str],
) -> list[str] | None:
    """BFS from source to target. Returns path node-ID list or None."""
    adj: dict[str, list[str]] = {n: [] for n in valid_nodes}
    for edge in edges:
        a, b = tuple(edge)
        if a in adj and b in adj:
            adj[a].append(b)
            adj[b].append(a)

    queue: deque[list[str]] = deque([[source]])
    visited: set[str] = {source}
    while queue:
        path = queue.popleft()
        node = path[-1]
        if node == target:
            return path
        for nbr in adj.get(node, []):
            if nbr not in visited:
                visited.add(nbr)
                queue.append(path + [nbr])
    return None


# ---------------------------------------------------------------------------
# Puzzle class
# ---------------------------------------------------------------------------


class CircuitRoutingPuzzle(PuzzleInstance):
    """Route power from source to target by placing conduit connections."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._grid_rows: int = 0
        self._grid_cols: int = 0
        self._source_id: str = ""
        self._target_id: str = ""
        self._valid_nodes: set[str] = set()
        self._existing: set[frozenset[str]] = set()
        self._available: list[frozenset[str]] = []
        self._spare_conduits: int = 0
        self._solution_path: list[str] = []
        self._node_types: dict[str, str] = {}

    def generate(self) -> dict[str, Any]:
        rows, cols = _GRID_SIZES.get(self.difficulty, (4, 4))
        self._grid_rows = rows
        self._grid_cols = cols
        mid_col = cols // 2
        self._source_id = _node_id(0, mid_col)
        self._target_id = _node_id(rows - 1, mid_col)

        # All nodes start as junctions.
        all_ids: list[str] = [
            _node_id(r, c) for r in range(rows) for c in range(cols)
        ]
        self._node_types = {nid: "junction" for nid in all_ids}
        self._node_types[self._source_id] = "source"
        self._node_types[self._target_id] = "target"

        # Damage up to (difficulty − 1) interior nodes, preserving connectivity.
        interior = [
            n for n in all_ids
            if n not in (self._source_id, self._target_id)
        ]
        damaged: set[str] = set()
        for _ in range(min(self.difficulty - 1, len(interior))):
            candidates = [n for n in interior if n not in damaged]
            random.shuffle(candidates)
            for cand in candidates:
                trial_valid = {n for n in all_ids if n not in damaged | {cand}}
                trial_edges = _build_all_edges(trial_valid)
                if _bfs_path(self._source_id, self._target_id, trial_edges, trial_valid):
                    damaged.add(cand)
                    self._node_types[cand] = "damaged"
                    break

        self._valid_nodes = {n for n in all_ids if n not in damaged}
        all_possible = _build_all_edges(self._valid_nodes)

        # Solution path (shortest route).
        self._solution_path = _bfs_path(
            self._source_id, self._target_id, all_possible, self._valid_nodes
        ) or [self._source_id, self._target_id]

        # Solution edges.
        solution_edges: set[frozenset[str]] = {
            _canon_edge(self._solution_path[i], self._solution_path[i + 1])
            for i in range(len(self._solution_path) - 1)
        }

        # Break `difficulty` solution edges → available for player to re-place.
        sol_list = list(solution_edges)
        random.shuffle(sol_list)
        broken_count = min(self.difficulty, len(sol_list))
        broken: set[frozenset[str]] = set(sol_list[:broken_count])

        # Existing = (solution − broken) ∪ ~30 % of non-solution edges.
        non_solution = list(all_possible - solution_edges)
        random.shuffle(non_solution)
        extra_existing = non_solution[: max(1, len(non_solution) // 3)]
        self._existing = (solution_edges - broken) | set(extra_existing)

        # Available = broken ∪ some decoy edges from the remaining non-solution pool.
        decoys = [e for e in non_solution if e not in set(extra_existing)]
        decoy_count = min(broken_count * 2, len(decoys))
        self._available = list(broken) + decoys[:decoy_count]
        random.shuffle(self._available)

        # Spare conduits = minimum needed + slack.
        self._spare_conduits = broken_count + _SLACK[self.difficulty - 1]

        return {
            "grid_rows": rows,
            "grid_cols": cols,
            "nodes": [
                {
                    "id": nid,
                    "row": _parse_node_id(nid)[0],
                    "col": _parse_node_id(nid)[1],
                    "type": self._node_types[nid],
                }
                for nid in all_ids
            ],
            "existing_connections": [sorted(e) for e in self._existing],
            "available_connections": [sorted(e) for e in self._available],
            "spare_conduits": self._spare_conduits,
            "source_id": self._source_id,
            "target_id": self._target_id,
            "success_message": "ROUTING COMPLETE",
        }

    def validate_submission(self, submission: dict[str, Any]) -> bool:
        """BFS through existing ∪ placed connections; returns True if target reachable."""
        placed_raw: list[list[str]] = submission.get("placed_connections", [])
        available_set = set(self._available)

        placed: set[frozenset[str]] = set()
        for edge in placed_raw:
            if len(edge) == 2:
                fe = _canon_edge(edge[0], edge[1])
                if fe in available_set:
                    placed.add(fe)

        if len(placed) > self._spare_conduits:
            return False

        all_edges = self._existing | placed
        return (
            _bfs_path(self._source_id, self._target_id, all_edges, self._valid_nodes)
            is not None
        )

    def apply_assist(self, assist_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """highlight_nodes — returns the node IDs on the solution path."""
        if assist_type == "highlight_nodes":
            return {"highlighted_nodes": list(self._solution_path)}
        return {}


# Self-register at import time.
register_puzzle_type("circuit_routing", CircuitRoutingPuzzle)
