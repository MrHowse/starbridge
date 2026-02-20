"""
Mission graph validator.

validate_mission(dict) -> list[str]

Returns a list of human-readable error strings.  Empty list means the mission
is structurally valid.  The check is purely structural — it does not execute
triggers or verify that referenced assets exist on disk.
"""
from __future__ import annotations

from collections import deque
from typing import Any


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_mission(mission: dict) -> list[str]:
    """Return a list of error strings describing structural problems.

    An empty list means the mission is valid.
    """
    errors: list[str] = []

    # 1. Top-level required fields
    if not mission.get("id") or not str(mission.get("id", "")).strip():
        errors.append("Mission 'id' field is required and must be non-empty.")
    if not mission.get("name") or not str(mission.get("name", "")).strip():
        errors.append("Mission 'name' field is required and must be non-empty.")

    # Build flat node registry {id: node_dict}
    node_registry = _collect_nodes(mission)

    # 2. start_node
    start_node = mission.get("start_node")
    if not start_node:
        errors.append("Mission 'start_node' is required.")
    elif start_node not in node_registry:
        errors.append(
            f"'start_node' references '{start_node}' which does not exist in nodes."
        )

    # 3. victory_nodes
    victory_nodes: list[str] = mission.get("victory_nodes") or []
    if not victory_nodes:
        errors.append("Mission must have at least one 'victory_nodes' entry.")
    else:
        for vn in victory_nodes:
            if vn not in node_registry:
                errors.append(
                    f"'victory_nodes' references '{vn}' which does not exist in nodes."
                )

    edges: list[dict] = mission.get("edges") or []

    # 4. Edge from/to references
    for i, edge in enumerate(edges):
        src = edge.get("from")
        tgt = edge.get("to")
        if src and src not in node_registry:
            errors.append(
                f"Edge #{i}: 'from' references '{src}' which does not exist in nodes."
            )
        if tgt and tgt not in node_registry:
            errors.append(
                f"Edge #{i}: 'to' references '{tgt}' which does not exist in nodes."
            )

    # 5. Branch nodes: ≥ 2 outgoing branch_trigger edges
    branch_trigger_edges: dict[str, list[dict]] = {}
    for edge in edges:
        if edge.get("type") == "branch_trigger":
            src = edge.get("from", "")
            branch_trigger_edges.setdefault(src, []).append(edge)

    for node_id, node in node_registry.items():
        if node.get("type") == "branch":
            bt_count = len(branch_trigger_edges.get(node_id, []))
            if bt_count < 2:
                errors.append(
                    f"Branch node '{node_id}' requires at least 2 outgoing "
                    f"'branch_trigger' edges (found {bt_count})."
                )

    # 6. Parallel nodes: ≥ 2 children
    for node_id, node in node_registry.items():
        if node.get("type") == "parallel":
            children = node.get("children") or []
            if len(children) < 2:
                errors.append(
                    f"Parallel node '{node_id}' requires at least 2 children "
                    f"(found {len(children)})."
                )

    # 7. Reachability — BFS over sequence/branch_trigger edges + parallel→children
    #    Conditional nodes are exempt (they live on independent tracks).
    if start_node and start_node in node_registry:
        reachable = _bfs_reachable(start_node, node_registry, edges)
        for node_id, node in node_registry.items():
            if node.get("type") == "conditional":
                continue  # exempted
            if node_id not in reachable:
                errors.append(
                    f"Node '{node_id}' (type={node.get('type')}) is not reachable "
                    f"from start_node '{start_node}'."
                )

    # 8. Unique puzzle labels across edges (on_complete) and node on_activate fields
    label_errors = _check_puzzle_labels(mission, node_registry, edges)
    errors.extend(label_errors)

    return errors


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _collect_nodes(mission: dict) -> dict[str, dict]:
    """Return flat {id: node_dict} including parallel children."""
    registry: dict[str, dict] = {}
    top_nodes: list[dict] = mission.get("nodes") or []
    for node in top_nodes:
        _register_node(node, registry)
    return registry


def _register_node(node: dict, registry: dict[str, dict]) -> None:
    node_id = node.get("id")
    if node_id:
        registry[node_id] = node
    # Recurse into parallel children
    for child in node.get("children") or []:
        _register_node(child, registry)


def _bfs_reachable(
    start: str,
    node_registry: dict[str, dict],
    edges: list[dict],
) -> set[str]:
    """BFS from start over sequence/branch_trigger edges + parallel→children."""
    visited: set[str] = set()
    queue: deque[str] = deque([start])
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)

        # Traverse outgoing edges
        for edge in edges:
            if edge.get("from") == current:
                tgt = edge.get("to")
                if tgt and tgt not in visited:
                    queue.append(tgt)

        # Include parallel children
        node = node_registry.get(current)
        if node and node.get("type") == "parallel":
            for child in node.get("children") or []:
                child_id = child.get("id")
                if child_id and child_id not in visited:
                    queue.append(child_id)

    return visited


def _check_puzzle_labels(
    mission: dict,
    node_registry: dict[str, dict],
    edges: list[dict],
) -> list[str]:
    """Return error strings for duplicate start_puzzle labels."""
    labels: list[str] = []
    seen: dict[str, str] = {}  # label -> first source description
    errors: list[str] = []

    # From edge on_complete actions
    for i, edge in enumerate(edges):
        on_complete = edge.get("on_complete")
        if on_complete:
            _collect_from_action(
                on_complete,
                f"edge #{i} ({edge.get('from')}→{edge.get('to')})",
                labels,
            )

    # From node on_activate fields
    for node_id, node in node_registry.items():
        on_activate = node.get("on_activate")
        if on_activate:
            _collect_from_action(on_activate, f"node '{node_id}' on_activate", labels)

    # Check for duplicates
    seen_labels: dict[str, int] = {}
    for label in labels:
        seen_labels[label] = seen_labels.get(label, 0) + 1

    for label, count in seen_labels.items():
        if count > 1:
            errors.append(
                f"Puzzle label '{label}' is used {count} times — start_puzzle labels "
                f"must be unique across the mission."
            )

    return errors


def _collect_from_action(action: Any, source: str, out: list[str]) -> None:
    """Recursively collect start_puzzle labels from an action or list of actions."""
    if isinstance(action, list):
        for item in action:
            _collect_from_action(item, source, out)
        return
    if not isinstance(action, dict):
        return
    if action.get("action") == "start_puzzle":
        label = action.get("label")
        if label:
            out.append(label)
    # on_complete may contain nested lists
    nested = action.get("on_complete")
    if nested:
        _collect_from_action(nested, source, out)
