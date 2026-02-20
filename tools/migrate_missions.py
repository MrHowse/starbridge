#!/usr/bin/env python3
"""migrate_missions.py — Convert mission JSON files to graph format.

Reads missions/*.json files in old sequential format (objectives array)
and writes them back as new-format graph missions (nodes/edges/start_node/
victory_nodes/defeat_condition).

Missions that already have a "nodes" key are skipped (already migrated).

Usage:
    python tools/migrate_missions.py [--dry-run]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MISSIONS_DIR = Path(__file__).parent.parent / "missions"

# Extra per-objective keys that should be promoted to the node dict.
_NODE_EXTRA_KEYS = ("hint", "station", "difficulty", "intruder_specs")

# Top-level mission keys preserved verbatim.
_TOP_PRESERVE = (
    "id",
    "name",
    "briefing",
    "signal_location",
    "spawn",
    "spawn_initial_wave",
    "asteroids",
    "hazards",
    "entities",
    "is_training",
    "target_role",
    "auto_roles",
)


def _convert_trigger(trigger_str: str | None, args: dict | None) -> dict | None:
    """Merge a trigger name string + args dict into a single trigger dict."""
    if not trigger_str:
        return None
    result: dict = {"type": trigger_str}
    if args:
        result.update(args)
    return result


def _convert_defeat_condition(mission: dict) -> dict | None:
    """Convert old defeat_condition string (+ optional alt) to a trigger dict."""
    dc_str = mission.get("defeat_condition")
    if dc_str is None:
        return None

    primary: dict = {"type": dc_str}

    alt = mission.get("defeat_condition_alt")
    if alt:
        alt_trigger = _convert_trigger(alt.get("trigger"), alt.get("args"))
        if alt_trigger:
            return {"type": "any_of", "triggers": [primary, alt_trigger]}

    return primary


def migrate_mission(mission: dict) -> dict:
    """Convert a single mission dict from old sequential to new graph format."""
    if "nodes" in mission:
        return mission  # already migrated — return unchanged

    objectives = mission.get("objectives", [])
    nodes: list[dict] = []
    edges: list[dict] = []

    for i, obj in enumerate(objectives):
        trigger = _convert_trigger(obj.get("trigger"), obj.get("args"))

        node: dict = {
            "id": obj["id"],
            "type": "objective",
            "text": obj.get("text", ""),
        }
        if trigger:
            node["trigger"] = trigger
        for key in _NODE_EXTRA_KEYS:
            if key in obj:
                node[key] = obj[key]
        nodes.append(node)

        # Outgoing sequence edge to the next objective.
        if i < len(objectives) - 1:
            edge: dict = {
                "from": obj["id"],
                "to": objectives[i + 1]["id"],
                "type": "sequence",
            }
            on_complete = obj.get("on_complete")
            if on_complete:
                edge["on_complete"] = on_complete
            edges.append(edge)

    result: dict = {}
    for key in _TOP_PRESERVE:
        if key in mission:
            result[key] = mission[key]

    result["nodes"] = nodes
    result["edges"] = edges
    result["start_node"] = objectives[0]["id"] if objectives else None
    result["victory_nodes"] = [objectives[-1]["id"]] if objectives else []
    result["defeat_condition"] = _convert_defeat_condition(mission)

    return result


def main(dry_run: bool = False) -> None:
    files = sorted(MISSIONS_DIR.glob("*.json"))
    print(f"Found {len(files)} mission files in {MISSIONS_DIR}\n")

    converted_count = 0
    skipped_count = 0

    for path in files:
        with path.open("r", encoding="utf-8") as f:
            mission = json.load(f)

        if "nodes" in mission:
            print(f"  SKIP  {path.name}  (already graph format)")
            skipped_count += 1
            continue

        original_obj_count = len(mission.get("objectives", []))
        converted = migrate_mission(mission)
        node_count = len(converted["nodes"])
        edge_count = len(converted["edges"])
        print(
            f"  OK    {path.name}  "
            f"({original_obj_count} objectives → {node_count} nodes, {edge_count} edges)"
        )

        if not dry_run:
            with path.open("w", encoding="utf-8") as f:
                json.dump(converted, f, indent=2)
                f.write("\n")

        converted_count += 1

    print(f"\nMigrated: {converted_count}  Skipped: {skipped_count}")
    if dry_run:
        print("Dry run — no files written.")
    else:
        print("Done.")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
