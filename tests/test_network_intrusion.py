"""Tests for the NetworkIntrusionPuzzle type.

Covers: generate(), validate_submission(), apply_assist("reveal_path"),
        graph structure invariants, difficulty scaling, and edge cases.
"""
from __future__ import annotations

import pytest

from server.puzzles.engine import PuzzleEngine, register_puzzle_type
from server.puzzles.network_intrusion import NetworkIntrusionPuzzle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_puzzle(difficulty: int = 1, target_id: str = "e1", target_system: str = "weapons") -> NetworkIntrusionPuzzle:
    """Construct and generate a NetworkIntrusionPuzzle."""
    p = NetworkIntrusionPuzzle(
        puzzle_id=f"test_{difficulty}",
        label=f"intrusion_{target_id}",
        station="electronic_warfare",
        difficulty=difficulty,
        time_limit=30.0,
        target_id=target_id,
        target_system=target_system,
    )
    p.generate()
    return p


def find_valid_path(puzzle: NetworkIntrusionPuzzle) -> list[str]:
    """Return the safe path (always valid) from the puzzle's _safe_path."""
    return list(puzzle._safe_path)


# ---------------------------------------------------------------------------
# Structure invariants
# ---------------------------------------------------------------------------


def test_generate_returns_type_field():
    p = make_puzzle()
    data = p.generate()
    assert data["type"] == "network_intrusion"


def test_generate_has_start_node():
    p = make_puzzle()
    data = p.generate()
    node_ids = {n["id"] for n in data["nodes"]}
    assert "start" in node_ids


def test_generate_has_target_node():
    p = make_puzzle()
    data = p.generate()
    node_ids = {n["id"] for n in data["nodes"]}
    assert "target" in node_ids


def test_generate_start_is_layer_0():
    p = make_puzzle()
    data = p.generate()
    start = next(n for n in data["nodes"] if n["id"] == "start")
    assert start["layer"] == 0


def test_generate_target_is_last_layer():
    p = make_puzzle()
    data = p.generate()
    target = next(n for n in data["nodes"] if n["id"] == "target")
    max_layer = max(n["layer"] for n in data["nodes"])
    assert target["layer"] == max_layer


def test_generate_all_edges_reference_valid_nodes():
    p = make_puzzle()
    data = p.generate()
    node_ids = {n["id"] for n in data["nodes"]}
    for edge in data["edges"]:
        assert edge[0] in node_ids
        assert edge[1] in node_ids


def test_generate_stores_target_id():
    p = make_puzzle(target_id="enemy_5")
    data = p.generate()
    assert data["target_id"] == "enemy_5"


def test_generate_stores_target_system():
    p = make_puzzle(target_system="shields")
    data = p.generate()
    assert data["target_system"] == "shields"


# ---------------------------------------------------------------------------
# Difficulty scaling
# ---------------------------------------------------------------------------


def test_difficulty_1_has_correct_node_count():
    p = make_puzzle(difficulty=1)
    # start + 2+2 middle + target = 6 nodes
    assert len(p._nodes) == 6


def test_difficulty_2_has_correct_node_count():
    p = make_puzzle(difficulty=2)
    # start + 2+3+2 middle + target = 9 nodes
    assert len(p._nodes) == 9


def test_difficulty_3_has_correct_node_count():
    p = make_puzzle(difficulty=3)
    # start + 3+3+3 middle + target = 11 nodes
    assert len(p._nodes) == 11


def test_difficulty_1_has_two_firewalls():
    p = make_puzzle(difficulty=1)
    fw = [n for n in p._nodes if n["type"] == "firewall"]
    assert len(fw) == 2


def test_difficulty_2_has_three_firewalls():
    p = make_puzzle(difficulty=2)
    fw = [n for n in p._nodes if n["type"] == "firewall"]
    assert len(fw) == 3


def test_difficulty_3_has_four_firewalls():
    p = make_puzzle(difficulty=3)
    fw = [n for n in p._nodes if n["type"] == "firewall"]
    assert len(fw) == 4


# ---------------------------------------------------------------------------
# Safe path invariant
# ---------------------------------------------------------------------------


def test_safe_path_starts_with_start():
    p = make_puzzle()
    assert p._safe_path[0] == "start"


def test_safe_path_ends_with_target():
    p = make_puzzle()
    assert p._safe_path[-1] == "target"


def test_safe_path_contains_no_firewalls():
    p = make_puzzle()
    fw_ids = {n["id"] for n in p._nodes if n["type"] == "firewall"}
    for nid in p._safe_path:
        assert nid not in fw_ids, f"Safe path contains firewall node {nid!r}"


# ---------------------------------------------------------------------------
# validate_submission
# ---------------------------------------------------------------------------


def test_valid_submission_on_safe_path():
    p = make_puzzle()
    safe = find_valid_path(p)
    assert p.validate_submission({"path": safe}) is True


def test_submission_through_firewall_fails():
    p = make_puzzle()
    fw = next(n for n in p._nodes if n["type"] == "firewall")
    # Build a fake path that passes through the firewall node.
    bad_path = ["start", fw["id"], "target"]
    assert p.validate_submission({"path": bad_path}) is False


def test_submission_wrong_start_fails():
    p = make_puzzle()
    safe = find_valid_path(p)
    bad = ["WRONG"] + safe[1:]
    assert p.validate_submission({"path": bad}) is False


def test_submission_wrong_end_fails():
    p = make_puzzle()
    safe = find_valid_path(p)
    bad = safe[:-1] + ["WRONG"]
    assert p.validate_submission({"path": bad}) is False


def test_submission_empty_fails():
    p = make_puzzle()
    assert p.validate_submission({"path": []}) is False


def test_submission_too_short_fails():
    p = make_puzzle()
    assert p.validate_submission({"path": ["start"]}) is False


def test_submission_missing_path_key_fails():
    p = make_puzzle()
    assert p.validate_submission({}) is False


def test_submission_invalid_edge_fails():
    p = make_puzzle()
    # "start" connects to layer-1 nodes, not directly to "target".
    assert p.validate_submission({"path": ["start", "target"]}) is False


def test_submission_unknown_node_fails():
    p = make_puzzle()
    safe = find_valid_path(p)
    bad = safe[:1] + ["UNKNOWN"] + safe[1:]
    assert p.validate_submission({"path": bad}) is False


# ---------------------------------------------------------------------------
# apply_assist
# ---------------------------------------------------------------------------


def test_reveal_path_assist_un_firewalls_one_node():
    p = make_puzzle(difficulty=1)
    firewalls_before = [n for n in p._nodes if n["type"] == "firewall"]
    p.apply_assist("reveal_path", {})
    firewalls_after = [n for n in p._nodes if n["type"] == "firewall"]
    assert len(firewalls_after) == len(firewalls_before) - 1


def test_reveal_path_assist_returns_revealed_node_key():
    p = make_puzzle(difficulty=1)
    result = p.apply_assist("reveal_path", {})
    assert "revealed_node" in result
    nid = result["revealed_node"]
    node = next(n for n in p._nodes if n["id"] == nid)
    assert node["type"] == "open"


def test_reveal_path_assist_no_firewalls_left_returns_empty():
    """If all firewalls already cleared, assist returns {}."""
    p = make_puzzle(difficulty=1)
    for n in p._nodes:
        if n["type"] == "firewall":
            n["type"] = "open"
    result = p.apply_assist("reveal_path", {})
    assert result == {}


def test_unknown_assist_type_returns_empty():
    p = make_puzzle()
    result = p.apply_assist("do_magic", {})
    assert result == {}


# ---------------------------------------------------------------------------
# Puzzle engine integration
# ---------------------------------------------------------------------------


def test_puzzle_registers_in_engine():
    engine = PuzzleEngine()
    inst = engine.create_puzzle(
        puzzle_type="network_intrusion",
        station="electronic_warfare",
        label="test_intrusion",
        difficulty=1,
        time_limit=30.0,
        target_id="e1",
        target_system="weapons",
    )
    assert inst is not None
    assert inst.is_active()


def test_puzzle_engine_resolve_on_correct_submission():
    engine = PuzzleEngine()
    inst = engine.create_puzzle(
        puzzle_type="network_intrusion",
        station="electronic_warfare",
        label="test_intrusion2",
        difficulty=1,
        time_limit=30.0,
        target_id="e1",
        target_system="engines",
    )
    engine.pop_pending_broadcasts()  # clear puzzle.started
    safe_path = inst._safe_path  # type: ignore[attr-defined]
    engine.submit(inst.puzzle_id, {"path": safe_path})
    resolved = engine.pop_resolved()
    assert len(resolved) == 1
    _pid, label, success = resolved[0]
    assert success is True
