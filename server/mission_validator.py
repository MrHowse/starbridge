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

    # 9. Action field validation (v0.08)
    action_errors = _check_actions(edges, node_registry)
    errors.extend(action_errors)

    # 10. Entity/spawn validation
    entity_errors = _check_entities(mission)
    errors.extend(entity_errors)

    # 11. Metadata validation
    meta_errors = _check_metadata(mission)
    errors.extend(meta_errors)

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


# ---------------------------------------------------------------------------
# v0.08 action field validation
# ---------------------------------------------------------------------------

_VALID_SYSTEMS = frozenset(
    {"engines", "beams", "torpedoes", "shields", "sensors", "manoeuvring",
     "flight_deck", "ecm_suite", "point_defence"}
)

_VALID_CONTAMINANTS = frozenset({"toxic_gas", "smoke", "biological", "chemical"})

_VALID_SEVERITIES = frozenset({"minor", "moderate", "major"})

_VALID_ENTITY_TYPES = frozenset(
    {"station", "scout", "corvette", "frigate", "cruiser", "destroyer",
     "battleship", "enemy_station", "creature",
     "hazard_nebula", "hazard_minefield", "hazard_radiation"}
)

_VALID_SHIP_CLASSES = frozenset(
    {"any", "scout", "corvette", "frigate", "medical_ship",
     "cruiser", "carrier", "battleship"}
)


def _collect_all_actions(edges: list[dict], node_registry: dict[str, dict]) -> list[tuple[str, dict]]:
    """Collect all action dicts from edges and nodes. Returns (source_desc, action) tuples."""
    results: list[tuple[str, dict]] = []

    def _walk(action: Any, source: str) -> None:
        if isinstance(action, list):
            for item in action:
                _walk(item, source)
            return
        if not isinstance(action, dict):
            return
        if "action" in action:
            results.append((source, action))
        nested = action.get("on_complete")
        if nested:
            _walk(nested, source)

    for i, edge in enumerate(edges):
        oc = edge.get("on_complete")
        if oc:
            _walk(oc, f"edge #{i} ({edge.get('from')}→{edge.get('to')})")

    for node_id, node in node_registry.items():
        oa = node.get("on_activate")
        if oa:
            _walk(oa, f"node '{node_id}' on_activate")
        od = node.get("on_deactivate")
        if od:
            _walk(od, f"node '{node_id}' on_deactivate")

    return results


def _check_actions(edges: list[dict], node_registry: dict[str, dict]) -> list[str]:
    """Validate required fields and value ranges for all action types."""
    errors: list[str] = []

    for source, action in _collect_all_actions(edges, node_registry):
        atype = action.get("action", "")

        if atype == "start_fire":
            if not action.get("room_id"):
                errors.append(f"{source}: start_fire requires 'room_id'.")
            intensity = action.get("intensity")
            if intensity is not None and (not isinstance(intensity, (int, float)) or intensity < 1 or intensity > 5):
                errors.append(f"{source}: start_fire 'intensity' must be 1-5.")

        elif atype == "create_breach":
            if not action.get("room_id"):
                errors.append(f"{source}: create_breach requires 'room_id'.")
            sev = action.get("severity", "minor")
            if sev not in _VALID_SEVERITIES:
                errors.append(f"{source}: create_breach 'severity' must be one of {sorted(_VALID_SEVERITIES)}.")

        elif atype == "apply_radiation":
            if not action.get("room_id"):
                errors.append(f"{source}: apply_radiation requires 'room_id'.")
            if not action.get("source"):
                errors.append(f"{source}: apply_radiation requires 'source'.")
            tier = action.get("tier")
            if tier is not None and (not isinstance(tier, (int, float)) or tier < 1 or tier > 4):
                errors.append(f"{source}: apply_radiation 'tier' must be 1-4.")

        elif atype == "structural_damage":
            if not action.get("section"):
                errors.append(f"{source}: structural_damage requires 'section'.")
            amount = action.get("amount")
            if amount is not None and (not isinstance(amount, (int, float)) or amount < 1 or amount > 100):
                errors.append(f"{source}: structural_damage 'amount' must be 1-100.")

        elif atype == "contaminate_atmosphere":
            if not action.get("room_id"):
                errors.append(f"{source}: contaminate_atmosphere requires 'room_id'.")
            cont = action.get("contaminant", "smoke")
            if cont not in _VALID_CONTAMINANTS:
                errors.append(f"{source}: contaminate_atmosphere 'contaminant' must be one of {sorted(_VALID_CONTAMINANTS)}.")
            conc = action.get("concentration")
            if conc is not None and (not isinstance(conc, (int, float)) or conc < 0 or conc > 1):
                errors.append(f"{source}: contaminate_atmosphere 'concentration' must be 0-1.")

        elif atype == "system_damage":
            sys_name = action.get("system", "")
            if sys_name not in _VALID_SYSTEMS:
                errors.append(f"{source}: system_damage 'system' must be one of {sorted(_VALID_SYSTEMS)}.")
            amount = action.get("amount")
            if amount is not None and (not isinstance(amount, (int, float)) or amount < 1 or amount > 100):
                errors.append(f"{source}: system_damage 'amount' must be 1-100.")

        elif atype == "crew_casualty":
            if not action.get("room_id"):
                errors.append(f"{source}: crew_casualty requires 'room_id'.")
            count = action.get("count")
            if count is not None and (not isinstance(count, (int, float)) or count < 1 or count > 10):
                errors.append(f"{source}: crew_casualty 'count' must be 1-10.")

        elif atype == "send_transmission":
            if not action.get("faction"):
                errors.append(f"{source}: send_transmission requires 'faction'.")
            if not action.get("message"):
                errors.append(f"{source}: send_transmission requires 'message'.")

    return errors


def _check_entities(mission: dict) -> list[str]:
    """Validate spawn array entries."""
    errors: list[str] = []
    spawn = mission.get("spawn") or []

    for i, entity in enumerate(spawn):
        if not isinstance(entity, dict):
            errors.append(f"spawn[{i}]: must be a dict.")
            continue
        if not entity.get("id"):
            errors.append(f"spawn[{i}]: requires 'id'.")
        if not entity.get("type"):
            errors.append(f"spawn[{i}]: requires 'type'.")
        elif entity["type"] not in _VALID_ENTITY_TYPES:
            errors.append(f"spawn[{i}]: unknown type '{entity['type']}'.")

        for coord in ("x", "y"):
            val = entity.get(coord)
            if val is not None and not isinstance(val, (int, float)):
                errors.append(f"spawn[{i}]: '{coord}' must be numeric.")

        if entity.get("type") == "creature" and not entity.get("creature_type"):
            errors.append(f"spawn[{i}]: creature requires 'creature_type'.")

    return errors


def _check_metadata(mission: dict) -> list[str]:
    """Validate optional metadata fields: ship_class, start_position."""
    errors: list[str] = []

    sc = mission.get("ship_class")
    if sc is not None and sc not in _VALID_SHIP_CLASSES:
        errors.append(f"'ship_class' must be one of {sorted(_VALID_SHIP_CLASSES)}, got '{sc}'.")

    sp = mission.get("start_position")
    if sp is not None:
        if not isinstance(sp, dict):
            errors.append("'start_position' must be a dict with x/y keys.")
        else:
            for key in ("x", "y"):
                val = sp.get(key)
                if val is not None and not isinstance(val, (int, float)):
                    errors.append(f"'start_position.{key}' must be numeric.")

    return errors
