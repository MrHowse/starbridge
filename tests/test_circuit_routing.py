"""Tests for the Circuit Routing puzzle type.

Covers:
  server/puzzles/circuit_routing.py — CircuitRoutingPuzzle
  Integration with PuzzleEngine lifecycle.
"""
from __future__ import annotations

import pytest

from server.puzzles.engine import PuzzleEngine
import server.puzzles.circuit_routing  # noqa: F401 — registers the type
from server.puzzles.circuit_routing import (
    CircuitRoutingPuzzle,
    _GRID_SIZES,
    _SLACK,
    _bfs_path,
    _node_id,
    _parse_node_id,
    _are_adjacent,
    _canon_edge,
    _build_all_edges,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh_engine() -> PuzzleEngine:
    return PuzzleEngine()


def make_puzzle(engine: PuzzleEngine, difficulty: int = 1) -> CircuitRoutingPuzzle:
    return engine.create_puzzle(  # type: ignore[return-value]
        puzzle_type="circuit_routing",
        station="engineering",
        label=f"cr_test_d{difficulty}",
        difficulty=difficulty,
        time_limit=60.0,
    )


# ---------------------------------------------------------------------------
# Unit tests for grid helpers
# ---------------------------------------------------------------------------


def test_node_id_format():
    assert _node_id(0, 0) == "r0c0"
    assert _node_id(3, 2) == "r3c2"


def test_parse_node_id_roundtrip():
    for r in range(6):
        for c in range(6):
            nid = _node_id(r, c)
            assert _parse_node_id(nid) == (r, c)


def test_are_adjacent_nsew():
    assert _are_adjacent("r0c0", "r1c0")   # south
    assert _are_adjacent("r1c0", "r0c0")   # north
    assert _are_adjacent("r0c0", "r0c1")   # east
    assert _are_adjacent("r0c1", "r0c0")   # west


def test_are_adjacent_diagonal_false():
    assert not _are_adjacent("r0c0", "r1c1")


def test_bfs_path_finds_simple():
    nodes = {"r0c0", "r1c0", "r2c0"}
    edges = {
        _canon_edge("r0c0", "r1c0"),
        _canon_edge("r1c0", "r2c0"),
    }
    path = _bfs_path("r0c0", "r2c0", edges, nodes)
    assert path is not None
    assert path[0] == "r0c0"
    assert path[-1] == "r2c0"


def test_bfs_path_no_path():
    nodes = {"r0c0", "r1c0", "r2c0"}
    edges = {_canon_edge("r0c0", "r1c0")}  # missing r1c0 → r2c0
    assert _bfs_path("r0c0", "r2c0", edges, nodes) is None


def test_bfs_path_ignores_damaged():
    nodes = {"r0c0", "r1c0", "r2c0"}
    edges = {
        _canon_edge("r0c0", "r1c0"),
        _canon_edge("r1c0", "r2c0"),
    }
    # Remove r1c0 from valid_nodes (simulating damage)
    valid = {"r0c0", "r2c0"}
    assert _bfs_path("r0c0", "r2c0", edges, valid) is None


# ---------------------------------------------------------------------------
# CircuitRoutingPuzzle — generate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("diff", [1, 2, 3, 4, 5])
def test_generate_grid_size(diff):
    engine = fresh_engine()
    engine.reset()
    puzzle = make_puzzle(engine, diff)
    rows, cols = _GRID_SIZES[diff]
    assert puzzle._grid_rows == rows
    assert puzzle._grid_cols == cols


@pytest.mark.parametrize("diff", [1, 2, 3, 4, 5])
def test_source_and_target_positions(diff):
    engine = fresh_engine()
    puzzle = make_puzzle(engine, diff)
    rows, cols = _GRID_SIZES[diff]
    mid = cols // 2
    assert puzzle._source_id == _node_id(0, mid)
    assert puzzle._target_id == _node_id(rows - 1, mid)


@pytest.mark.parametrize("diff", [1, 2, 3, 4, 5])
def test_valid_path_exists_in_existing_plus_available(diff):
    """The puzzle is always solvable: existing ∪ available ⊇ solution."""
    engine = fresh_engine()
    puzzle = make_puzzle(engine, diff)
    all_edges = puzzle._existing | set(puzzle._available)
    path = _bfs_path(puzzle._source_id, puzzle._target_id, all_edges, puzzle._valid_nodes)
    assert path is not None, f"No solution possible at difficulty {diff}"


@pytest.mark.parametrize("diff", [1, 2, 3, 4, 5])
def test_solution_path_is_valid(diff):
    """The stored solution path must trace a connected route."""
    engine = fresh_engine()
    puzzle = make_puzzle(engine, diff)
    path = puzzle._solution_path
    assert len(path) >= 2
    assert path[0] == puzzle._source_id
    assert path[-1] == puzzle._target_id
    # Each consecutive pair must be adjacent.
    for i in range(len(path) - 1):
        assert _are_adjacent(path[i], path[i + 1])


def test_node_types_are_valid():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=3)
    valid = {"source", "target", "junction", "damaged"}
    for nid, t in puzzle._node_types.items():
        assert t in valid, f"Node {nid} has unexpected type {t!r}"


def test_damaged_count_scales_with_difficulty():
    for diff in range(1, 6):
        engine = fresh_engine()
        puzzle = make_puzzle(engine, diff)
        damaged = sum(1 for t in puzzle._node_types.values() if t == "damaged")
        assert damaged <= diff - 1, f"diff={diff}: too many damaged ({damaged})"


@pytest.mark.parametrize("diff", [1, 2, 3, 4, 5])
def test_spare_conduits_includes_slack(diff):
    engine = fresh_engine()
    puzzle = make_puzzle(engine, diff)
    # At minimum, spare_conduits >= slack (even if no edges are broken).
    assert puzzle._spare_conduits >= _SLACK[diff - 1]


def test_available_connections_non_empty():
    for diff in range(1, 6):
        engine = fresh_engine()
        puzzle = make_puzzle(engine, diff)
        # Must have some placeable edges for the player to use.
        assert len(puzzle._available) > 0


# ---------------------------------------------------------------------------
# CircuitRoutingPuzzle — validate_submission
# ---------------------------------------------------------------------------


def test_validate_correct_solution():
    engine = fresh_engine()
    engine.reset()
    puzzle = make_puzzle(engine, difficulty=1)

    # Use the solution path to construct a valid submission.
    placed = []
    for i in range(len(puzzle._solution_path) - 1):
        a = puzzle._solution_path[i]
        b = puzzle._solution_path[i + 1]
        edge = _canon_edge(a, b)
        if edge in set(puzzle._available):
            placed.append([a, b])

    assert puzzle.validate_submission({"placed_connections": placed})


def test_validate_empty_submission_fails_if_path_broken():
    """Submitting nothing should fail when the existing edges don't form a path."""
    engine = fresh_engine()
    # Use difficulty 3 (more damage, more broken edges) for a reliable test.
    puzzle = make_puzzle(engine, difficulty=3)

    # Only submit existing connections — should fail when path is broken.
    existing_path = _bfs_path(
        puzzle._source_id, puzzle._target_id,
        puzzle._existing, puzzle._valid_nodes,
    )
    if existing_path is None:
        # Good — the existing edges alone are not enough.
        assert not puzzle.validate_submission({"placed_connections": []})


def test_validate_too_many_conduits_fails():
    # Use difficulty 5 (slack=0, larger grid, more available edges than spare).
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=5)

    # Verify the pool is large enough for this test to be meaningful.
    all_avail = [[sorted(e)[0], sorted(e)[1]] for e in puzzle._available]
    if len(all_avail) <= puzzle._spare_conduits:
        pytest.skip("Available pool ≤ spare_conduits; can't test over-limit at this seed")

    too_many = all_avail[:puzzle._spare_conduits + 1]
    assert not puzzle.validate_submission({"placed_connections": too_many})


def test_validate_ignores_non_available_edges():
    """Edges not in available_connections must be silently rejected."""
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=1)

    # Fabricate an edge that doesn't exist in available.
    fake_edge = [["r99c99", "r98c99"]]
    # Shouldn't crash, and shouldn't count toward spare conduits.
    result = puzzle.validate_submission({"placed_connections": fake_edge})
    # Result may be True or False depending on existing edges; just must not crash.
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# CircuitRoutingPuzzle — apply_assist
# ---------------------------------------------------------------------------


def test_assist_highlight_nodes_returns_solution_path():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=2)
    result = puzzle.apply_assist("highlight_nodes", {})
    assert "highlighted_nodes" in result
    # Highlighted nodes should contain source and target.
    highlights = set(result["highlighted_nodes"])
    assert puzzle._source_id in highlights
    assert puzzle._target_id in highlights


def test_assist_unknown_type_returns_empty():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    result = puzzle.apply_assist("nonexistent_assist", {})
    assert result == {}


# ---------------------------------------------------------------------------
# PuzzleEngine integration
# ---------------------------------------------------------------------------


def test_engine_creates_circuit_routing():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    assert puzzle is not None
    assert isinstance(puzzle, CircuitRoutingPuzzle)


def test_engine_submit_valid_solution_resolves():
    engine = fresh_engine()
    puzzle = make_puzzle(engine, difficulty=1)
    engine.pop_pending_broadcasts()  # consume puzzle.started

    # Build a valid placed set from the solution path.
    placed = []
    for i in range(len(puzzle._solution_path) - 1):
        a = puzzle._solution_path[i]
        b = puzzle._solution_path[i + 1]
        if _canon_edge(a, b) in set(puzzle._available):
            placed.append([a, b])

    engine.submit(puzzle.puzzle_id, {"placed_connections": placed})
    resolved = engine.pop_resolved()
    assert any(label == puzzle.label and success for _, label, success in resolved)


def test_engine_timeout_resolves_as_failure():
    engine = fresh_engine()
    puzzle = make_puzzle(engine)
    engine.pop_pending_broadcasts()

    engine.tick(puzzle.time_limit + 0.1)
    broadcasts = engine.pop_pending_broadcasts()
    assert any(
        msg.type == "puzzle.result"
        for _, msg in broadcasts
    )
    resolved = engine.pop_resolved()
    assert any(not success for _, _, success in resolved)
