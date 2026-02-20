"""Puzzle type: Network Intrusion.

The Electronic Warfare officer must route a data payload through an enemy
ship's firewall topology to disable a targeted system. The puzzle presents
a layered directed graph: nodes are either open data paths or active
firewalls. The player plots a path from the start node to the target node,
passing through only open nodes and valid connections.

Graph structure (by difficulty):
  Difficulty 1: start → [2 nodes] → [2 nodes] → target  (2 firewalls)
  Difficulty 2: start → [2] → [3] → [2] → target         (3 firewalls)
  Difficulty 3+: start → [3] → [3] → [3] → target        (4 firewalls)

Edges: each node in a layer connects to every node in the next layer
(fully-connected between adjacent layers). This gives the player many
potential paths; firewalls block most of them.

Assist: "reveal_path" — un-firewalls one node on the guaranteed-safe path,
opening at least one clear route to the target.
"""
from __future__ import annotations

import random
from typing import Any

from server.puzzles.base import PuzzleInstance
from server.puzzles.engine import register_puzzle_type

# Node IDs — unambiguous letters (no I/O which look like 1/0).
_NODE_IDS: list[str] = list("ABCDEFGHJKLMNPQRSTUVWXYZ")


class NetworkIntrusionPuzzle(PuzzleInstance):
    """Route a data path through the enemy network to disable a system."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._target_id: str = str(kwargs.get("target_id", ""))
        self._target_system: str = str(kwargs.get("target_system", "weapons"))
        self._nodes: list[dict[str, Any]] = []
        self._edges: list[list[str]] = []
        self._layer_nodes: list[list[str]] = []
        self._safe_path: list[str] = []  # guaranteed valid path through the network

    def generate(self) -> dict[str, Any]:
        """Build a random layered network with at least one open path."""
        d = max(1, min(self.difficulty, 3))
        if d == 1:
            mid_layers = [2, 2]
            fw_count = 2
        elif d == 2:
            mid_layers = [2, 3, 2]
            fw_count = 3
        else:
            mid_layers = [3, 3, 3]
            fw_count = 4

        # Build node list — start node, middle layers, target node.
        self._nodes = [{"id": "start", "layer": 0, "type": "start"}]
        self._layer_nodes = [["start"]]
        id_idx = 0

        for layer_idx, count in enumerate(mid_layers, start=1):
            layer: list[str] = []
            for _ in range(count):
                nid = _NODE_IDS[id_idx % len(_NODE_IDS)]
                id_idx += 1
                self._nodes.append({"id": nid, "layer": layer_idx, "type": "open"})
                layer.append(nid)
            self._layer_nodes.append(layer)

        target_layer = len(mid_layers) + 1
        self._nodes.append({"id": "target", "layer": target_layer, "type": "target"})
        self._layer_nodes.append(["target"])

        # Build edges: each node connects to all nodes in the next layer.
        self._edges = []
        for i in range(len(self._layer_nodes) - 1):
            for from_id in self._layer_nodes[i]:
                for to_id in self._layer_nodes[i + 1]:
                    self._edges.append([from_id, to_id])

        # Pick one guaranteed safe path (one node per middle layer).
        self._safe_path = ["start"]
        for layer in self._layer_nodes[1:-1]:
            self._safe_path.append(random.choice(layer))
        self._safe_path.append("target")
        safe_set = set(self._safe_path)

        # Place firewalls on open nodes NOT in the safe path.
        candidates = [
            n["id"] for n in self._nodes
            if n["type"] == "open" and n["id"] not in safe_set
        ]
        random.shuffle(candidates)
        for nid in candidates[:fw_count]:
            node = next(n for n in self._nodes if n["id"] == nid)
            node["type"] = "firewall"

        return {
            "type": "network_intrusion",
            "target_id": self._target_id,
            "target_system": self._target_system,
            "nodes": [
                {"id": n["id"], "layer": n["layer"], "type": n["type"]}
                for n in self._nodes
            ],
            "edges": self._edges,
        }

    def validate_submission(self, submission: dict[str, Any]) -> bool:
        """Accept a path that connects start to target through only open nodes."""
        path: list[str] = submission.get("path", [])
        if len(path) < 2:
            return False
        if path[0] != "start" or path[-1] != "target":
            return False

        edge_set = {(e[0], e[1]) for e in self._edges}
        node_types = {n["id"]: n["type"] for n in self._nodes}

        for i, nid in enumerate(path):
            if nid not in node_types:
                return False
            if node_types[nid] == "firewall":
                return False
            if i > 0 and (path[i - 1], nid) not in edge_set:
                return False

        return True

    def apply_assist(self, assist_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Support 'reveal_path' — un-firewall one firewall node, opening a path."""
        if assist_type == "reveal_path":
            for node in self._nodes:
                if node["type"] == "firewall":
                    node["type"] = "open"
                    return {
                        "revealed_node": node["id"],
                        "updated_nodes": [{"id": node["id"], "type": "open"}],
                    }
        return {}


# Self-register when this module is imported.
register_puzzle_type("network_intrusion", NetworkIntrusionPuzzle)
