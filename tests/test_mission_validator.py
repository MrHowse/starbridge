"""
Tests for server/mission_validator.py — validate_mission()

Uses only the pure-function interface: no server, no file I/O.
"""
from __future__ import annotations

import pytest

from server.mission_validator import validate_mission


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _minimal() -> dict:
    """Return a structurally valid two-node mission."""
    return {
        "id": "t",
        "name": "T",
        "nodes": [
            {
                "id": "s",
                "type": "objective",
                "text": "Go",
                "trigger": {"type": "timer_elapsed", "seconds": 5},
            },
            {
                "id": "e",
                "type": "objective",
                "text": "Win",
                "trigger": {"type": "all_enemies_destroyed"},
            },
        ],
        "edges": [{"from": "s", "to": "e", "type": "sequence"}],
        "start_node": "s",
        "victory_nodes": ["e"],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_valid_minimal_mission():
    errors = validate_mission(_minimal())
    assert errors == []


def test_missing_id():
    m = _minimal()
    del m["id"]
    errors = validate_mission(m)
    assert any("id" in e.lower() for e in errors)


def test_empty_id():
    m = _minimal()
    m["id"] = "   "
    errors = validate_mission(m)
    assert any("id" in e.lower() for e in errors)


def test_missing_name():
    m = _minimal()
    del m["name"]
    errors = validate_mission(m)
    assert any("name" in e.lower() for e in errors)


def test_empty_name():
    m = _minimal()
    m["name"] = ""
    errors = validate_mission(m)
    assert any("name" in e.lower() for e in errors)


def test_missing_start_node():
    m = _minimal()
    del m["start_node"]
    errors = validate_mission(m)
    assert any("start_node" in e for e in errors)


def test_start_node_not_in_nodes():
    m = _minimal()
    m["start_node"] = "nonexistent"
    errors = validate_mission(m)
    assert any("start_node" in e and "nonexistent" in e for e in errors)


def test_no_victory_nodes():
    m = _minimal()
    m["victory_nodes"] = []
    errors = validate_mission(m)
    assert any("victory" in e.lower() for e in errors)


def test_victory_node_not_in_nodes():
    m = _minimal()
    m["victory_nodes"] = ["missing_node"]
    errors = validate_mission(m)
    assert any("missing_node" in e for e in errors)


def test_branch_zero_trigger_edges():
    m = _minimal()
    m["nodes"].append({"id": "br", "type": "branch", "text": "Choose"})
    # br is reachable via sequence edge from s
    m["edges"].append({"from": "s", "to": "br", "type": "sequence"})
    # No branch_trigger edges at all
    errors = validate_mission(m)
    assert any("branch" in e.lower() and "br" in e for e in errors)


def test_branch_one_trigger_edge():
    m = _minimal()
    m["nodes"].append({"id": "br", "type": "branch", "text": "Choose"})
    m["edges"].append({"from": "s", "to": "br", "type": "sequence"})
    # Only one branch_trigger edge — still an error
    m["edges"].append({
        "from": "br",
        "to": "e",
        "type": "branch_trigger",
        "trigger": {"type": "timer_elapsed", "seconds": 10},
    })
    errors = validate_mission(m)
    assert any("branch" in e.lower() and "br" in e for e in errors)


def test_branch_two_trigger_edges_ok():
    m = _minimal()
    # Add an extra objective to branch to
    m["nodes"].append({"id": "alt", "type": "objective", "text": "Alt",
                       "trigger": {"type": "all_enemies_destroyed"}})
    m["nodes"].append({"id": "br", "type": "branch", "text": "Choose"})
    m["edges"].append({"from": "s", "to": "br", "type": "sequence"})
    m["edges"].append({
        "from": "br", "to": "e", "type": "branch_trigger",
        "trigger": {"type": "timer_elapsed", "seconds": 5},
    })
    m["edges"].append({
        "from": "br", "to": "alt", "type": "branch_trigger",
        "trigger": {"type": "all_enemies_destroyed"},
    })
    # alt must also be a victory node or reachable; add as victory for simplicity
    m["victory_nodes"].append("alt")
    errors = validate_mission(m)
    branch_errors = [e for e in errors if "branch" in e.lower() and "br" in e]
    assert branch_errors == []


def test_parallel_one_child():
    m = _minimal()
    m["nodes"].append({
        "id": "par",
        "type": "parallel",
        "text": "Do both",
        "complete_when": "all",
        "children": [
            {"id": "c1", "type": "objective", "text": "Child 1",
             "trigger": {"type": "timer_elapsed", "seconds": 10}},
        ],
    })
    m["edges"].append({"from": "s", "to": "par", "type": "sequence"})
    m["edges"].append({"from": "par", "to": "e", "type": "sequence"})
    errors = validate_mission(m)
    assert any("parallel" in e.lower() and "par" in e for e in errors)


def test_parallel_two_children_ok():
    m = _minimal()
    m["nodes"].append({
        "id": "par",
        "type": "parallel",
        "text": "Do both",
        "complete_when": "all",
        "children": [
            {"id": "c1", "type": "objective", "text": "Child 1",
             "trigger": {"type": "timer_elapsed", "seconds": 10}},
            {"id": "c2", "type": "objective", "text": "Child 2",
             "trigger": {"type": "all_enemies_destroyed"}},
        ],
    })
    m["edges"].append({"from": "s", "to": "par", "type": "sequence"})
    m["edges"].append({"from": "par", "to": "e", "type": "sequence"})
    errors = validate_mission(m)
    parallel_errors = [e for e in errors if "parallel" in e.lower() and "par" in e]
    assert parallel_errors == []


def test_unreachable_node_errors():
    m = _minimal()
    # Add a node with no path from start_node
    m["nodes"].append({
        "id": "orphan",
        "type": "objective",
        "text": "Orphan",
        "trigger": {"type": "timer_elapsed", "seconds": 99},
    })
    errors = validate_mission(m)
    assert any("orphan" in e for e in errors)


def test_conditional_exempted_from_reachability():
    m = _minimal()
    # Conditional nodes are independent tracks — not reachable via BFS is OK
    m["nodes"].append({
        "id": "cond_track",
        "type": "conditional",
        "text": "Side condition",
        "condition": {"type": "ship_hull_below", "value": 50},
    })
    errors = validate_mission(m)
    reachability_errors = [e for e in errors if "cond_track" in e]
    assert reachability_errors == []


def test_edge_from_missing():
    m = _minimal()
    m["edges"].append({"from": "ghost", "to": "e", "type": "sequence"})
    errors = validate_mission(m)
    assert any("ghost" in e for e in errors)


def test_edge_to_missing():
    m = _minimal()
    m["edges"].append({"from": "s", "to": "ghost", "type": "sequence"})
    errors = validate_mission(m)
    assert any("ghost" in e for e in errors)


def test_duplicate_puzzle_label():
    m = _minimal()
    m["edges"][0]["on_complete"] = {"action": "start_puzzle", "label": "alpha",
                                    "station": "science", "difficulty": 2, "time_limit": 60}
    # Same label on a second edge
    m["edges"].append({
        "from": "e",
        "to": "s",
        "type": "sequence",
        "on_complete": {"action": "start_puzzle", "label": "alpha",
                        "station": "engineering", "difficulty": 1, "time_limit": 60},
    })
    errors = validate_mission(m)
    assert any("alpha" in e and "unique" in e.lower() for e in errors)


def test_unique_puzzle_labels_ok():
    m = _minimal()
    m["edges"][0]["on_complete"] = {"action": "start_puzzle", "label": "beta",
                                    "station": "science", "difficulty": 2, "time_limit": 60}
    m["edges"].append({
        "from": "e",
        "to": "s",
        "type": "sequence",
        "on_complete": {"action": "start_puzzle", "label": "gamma",
                        "station": "engineering", "difficulty": 1, "time_limit": 60},
    })
    errors = validate_mission(m)
    label_errors = [e for e in errors if "unique" in e.lower()]
    assert label_errors == []


def test_parallel_children_reachable_via_parent():
    """Children embedded in a parallel node must not trigger false unreachable errors."""
    m = _minimal()
    m["nodes"].append({
        "id": "par",
        "type": "parallel",
        "text": "Do both",
        "complete_when": "all",
        "children": [
            {"id": "c1", "type": "objective", "text": "Child 1",
             "trigger": {"type": "timer_elapsed", "seconds": 10}},
            {"id": "c2", "type": "objective", "text": "Child 2",
             "trigger": {"type": "all_enemies_destroyed"}},
        ],
    })
    m["edges"].append({"from": "s", "to": "par", "type": "sequence"})
    m["edges"].append({"from": "par", "to": "e", "type": "sequence"})
    errors = validate_mission(m)
    child_errors = [e for e in errors if "c1" in e or "c2" in e]
    assert child_errors == []


def test_on_activate_labels_counted_for_duplicates():
    """start_puzzle in node on_activate fields must be included in duplicate check."""
    m = _minimal()
    # Edge on_complete with label "delta"
    m["edges"][0]["on_complete"] = {"action": "start_puzzle", "label": "delta",
                                    "station": "science", "difficulty": 2, "time_limit": 60}
    # Conditional node on_activate with same label "delta"
    m["nodes"].append({
        "id": "cond",
        "type": "conditional",
        "text": "Conditional",
        "condition": {"type": "ship_hull_below", "value": 50},
        "on_activate": {"action": "start_puzzle", "label": "delta",
                        "station": "medical", "difficulty": 1, "time_limit": 60},
    })
    errors = validate_mission(m)
    assert any("delta" in e for e in errors)


# ---------------------------------------------------------------------------
# v0.08 action validation
# ---------------------------------------------------------------------------


def test_action_start_fire_valid():
    m = _minimal()
    m["edges"][0]["on_complete"] = {"action": "start_fire", "room_id": "bridge_1", "intensity": 3}
    errors = validate_mission(m)
    action_errors = [e for e in errors if "start_fire" in e]
    assert action_errors == []


def test_action_start_fire_missing_room():
    m = _minimal()
    m["edges"][0]["on_complete"] = {"action": "start_fire", "intensity": 3}
    errors = validate_mission(m)
    assert any("start_fire" in e and "room_id" in e for e in errors)


def test_action_start_fire_invalid_intensity():
    m = _minimal()
    m["edges"][0]["on_complete"] = {"action": "start_fire", "room_id": "r1", "intensity": 10}
    errors = validate_mission(m)
    assert any("intensity" in e for e in errors)


def test_action_system_damage_invalid_system():
    m = _minimal()
    m["edges"][0]["on_complete"] = {"action": "system_damage", "system": "warp_drive", "amount": 10}
    errors = validate_mission(m)
    assert any("system_damage" in e and "system" in e for e in errors)


def test_action_system_damage_valid():
    m = _minimal()
    m["edges"][0]["on_complete"] = {"action": "system_damage", "system": "engines", "amount": 25}
    errors = validate_mission(m)
    action_errors = [e for e in errors if "system_damage" in e]
    assert action_errors == []


def test_action_send_transmission_missing_faction():
    m = _minimal()
    m["edges"][0]["on_complete"] = {"action": "send_transmission", "message": "hello"}
    errors = validate_mission(m)
    assert any("send_transmission" in e and "faction" in e for e in errors)


def test_action_contaminate_invalid_contaminant():
    m = _minimal()
    m["edges"][0]["on_complete"] = {"action": "contaminate_atmosphere", "room_id": "r1", "contaminant": "magic_gas"}
    errors = validate_mission(m)
    assert any("contaminant" in e for e in errors)


# ---------------------------------------------------------------------------
# Entity/spawn validation
# ---------------------------------------------------------------------------


def test_entity_valid():
    m = _minimal()
    m["spawn"] = [{"id": "e1", "type": "scout", "x": 50000, "y": 50000}]
    errors = validate_mission(m)
    entity_errors = [e for e in errors if "spawn" in e]
    assert entity_errors == []


def test_entity_unknown_type():
    m = _minimal()
    m["spawn"] = [{"id": "e1", "type": "dragon", "x": 0, "y": 0}]
    errors = validate_mission(m)
    assert any("unknown type" in e for e in errors)


def test_entity_missing_id():
    m = _minimal()
    m["spawn"] = [{"type": "scout", "x": 0, "y": 0}]
    errors = validate_mission(m)
    assert any("id" in e for e in errors)


def test_entity_creature_requires_creature_type():
    m = _minimal()
    m["spawn"] = [{"id": "c1", "type": "creature", "x": 0, "y": 0}]
    errors = validate_mission(m)
    assert any("creature_type" in e for e in errors)


# ---------------------------------------------------------------------------
# Metadata validation
# ---------------------------------------------------------------------------


def test_metadata_valid_ship_class():
    m = _minimal()
    m["ship_class"] = "frigate"
    errors = validate_mission(m)
    meta_errors = [e for e in errors if "ship_class" in e]
    assert meta_errors == []


def test_metadata_invalid_ship_class():
    m = _minimal()
    m["ship_class"] = "dreadnought"
    errors = validate_mission(m)
    assert any("ship_class" in e for e in errors)


def test_metadata_start_position_valid():
    m = _minimal()
    m["start_position"] = {"x": 10000, "y": 20000}
    errors = validate_mission(m)
    meta_errors = [e for e in errors if "start_position" in e]
    assert meta_errors == []
