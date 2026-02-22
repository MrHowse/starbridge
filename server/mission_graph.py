"""Mission Graph Engine — Directed graph mission execution.

Replaces the sequential objective model with a state graph that supports
parallel, branching, and emergent objectives. Build alongside the existing
engine.py; do NOT modify engine.py until migration is complete.

Node types:
  objective    — Single objective with a trigger. Completes when trigger fires.
  parallel     — Group of children all active simultaneously. Completes when
                 complete_when threshold is met ("all", "any", {"count": N},
                 {"count": N, "within_seconds": T}).
  branch       — Decision point. Multiple outgoing branch_trigger edges.
                 First trigger to fire wins; others are discarded.
  conditional  — Independent track. Activates/deactivates based on game state.
                 Does not block main graph progression.
  checkpoint   — Completes immediately on activation; suitable for auto-save
                 points and status broadcasts.

Edge types:
  sequence         — Source must complete before target activates (default).
  branch_trigger   — Used with branch nodes. The first such edge whose trigger
                     fires determines which target activates.

Trigger format: all triggers are dicts with a "type" key.
  {"type": "timer_elapsed", "seconds": 30}
  {"type": "all_of",  "triggers": [...]}   — all sub-triggers simultaneously true
  {"type": "any_of",  "triggers": [...]}   — any sub-trigger true
  {"type": "none_of", "triggers": [...]}   — no sub-trigger true
  (compound triggers nest arbitrarily)

Public interface mirrors MissionEngine for drop-in compatibility:
  tick(world, ship, dt) -> list[str]   # newly completed node IDs
  pop_pending_actions() -> list[dict]
  notify_puzzle_result(label, success)
  set_training_flag(flag)
  record_signal_scan(x, y) -> bool
  is_over() -> (bool, str|None)
  get_objectives() -> list[GraphObjective]
  get_active_node_ids() -> list[str]
  get_complete_node_ids() -> list[str]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from server.models.ship import Ship
from server.models.world import World
from server.utils.math_helpers import distance


# ---------------------------------------------------------------------------
# Runtime node object
# ---------------------------------------------------------------------------


@dataclass
class GraphObjective:
    """Runtime state for a single graph node."""

    id: str
    text: str
    status: Literal["pending", "active", "complete", "cancelled", "failed"] = "pending"


# ---------------------------------------------------------------------------
# Mission graph engine
# ---------------------------------------------------------------------------


class MissionGraph:
    """Directed graph mission engine with parallel, branch, and conditional nodes."""

    def __init__(self, mission: dict) -> None:
        self._mission = mission

        # Node registry
        self._all_nodes: dict[str, dict] = {}          # id → raw node def
        self._graph_nodes: dict[str, GraphObjective] = {}  # id → runtime obj
        self._outgoing: dict[str, list[dict]] = {}     # node_id → [edge_defs]
        self._node_order: list[str] = []               # registration order

        # Parallel / child tracking
        self._parallel_children: dict[str, list[str]] = {}  # parent_id → [child_ids]
        self._child_parent: dict[str, str] = {}        # child_id → parent_id

        # Conditional node list (evaluated every tick)
        self._conditional_ids: list[str] = []

        # Active / complete sets
        self._active_set: set[str] = set()
        self._complete_set: set[str] = set()

        # Per-node timers (for proximity_with_shields, parallel within_seconds)
        self._proximity_timers: dict[str, float] = {}
        self._parallel_complete_count: dict[str, int] = {}
        self._parallel_start_elapsed: dict[str, float] = {}

        # Shared state (mirrors MissionEngine)
        self._elapsed: float = 0.0
        self._last_dt: float = 0.1
        self._pending_actions: list[dict] = []

        # Puzzle tracking
        self._completed_puzzle_labels: set[str] = set()
        self._failed_puzzle_labels: set[str] = set()

        # Station capture notifications (set by game_loop via notify_station_captured)
        self._captured_station_ids: set[str] = set()

        # Creature destruction notifications (set by game_loop via notify_creature_destroyed)
        self._destroyed_creature_ids: set[str] = set()

        # Conditional activation count (for max_activations guard)
        self._conditional_activation_count: dict[str, int] = {}

        # Training flag tracking
        self._training_flags: set[str] = set()

        # Triangulation state
        self._triangulation_count: int = 0
        self._triangulation_positions: list[tuple[float, float]] = []

        # Mission end state
        self._over: bool = False
        self._result: str | None = None

        # Per-tick completion accumulator (reset at start of each tick)
        self._tick_completions: list[str] = []

        # Register all nodes from the mission dict
        for node_def in mission.get("nodes", []):
            self._register_node(node_def)

        # Register edges
        for edge in mission.get("edges", []):
            self._outgoing.setdefault(edge["from"], []).append(edge)

        # Victory / defeat config
        self._victory_nodes: list[str] = mission.get("victory_nodes", [])
        self._defeat_condition: dict | None = mission.get("defeat_condition")

        # Activate the start node
        start = mission.get("start_node")
        if start and start in self._all_nodes:
            self._activate_node(start)

    # ------------------------------------------------------------------
    # Graph construction helpers
    # ------------------------------------------------------------------

    def _register_node(self, node_def: dict, parent_id: str | None = None) -> None:
        """Register a node and recursively register its children (for parallel nodes)."""
        nid = node_def["id"]
        ntype = node_def.get("type", "objective")
        text = node_def.get("text", "")

        self._all_nodes[nid] = node_def
        self._graph_nodes[nid] = GraphObjective(id=nid, text=text)
        self._outgoing.setdefault(nid, [])
        self._node_order.append(nid)

        if parent_id is not None:
            self._child_parent[nid] = parent_id

        if ntype == "conditional":
            self._conditional_ids.append(nid)
            self._conditional_activation_count[nid] = 0

        if ntype == "parallel":
            children = node_def.get("children", [])
            self._parallel_children[nid] = [c["id"] for c in children]
            self._parallel_complete_count[nid] = 0
            for child_def in children:
                self._register_node(child_def, parent_id=nid)

    # ------------------------------------------------------------------
    # Node lifecycle
    # ------------------------------------------------------------------

    def _activate_node(self, node_id: str) -> None:
        """Activate a node. Handles type-specific activation logic."""
        if node_id not in self._all_nodes:
            return
        gobj = self._graph_nodes[node_id]
        if gobj.status in ("active", "complete", "cancelled"):
            return

        gobj.status = "active"
        self._active_set.add(node_id)

        ntype = self._all_nodes[node_id].get("type", "objective")

        if ntype == "parallel":
            # Activate all children; initialise per-parallel state
            self._parallel_complete_count[node_id] = 0
            self._parallel_start_elapsed[node_id] = self._elapsed
            children = self._parallel_children.get(node_id, [])
            if not children:
                # Empty parallel group — complete immediately
                self._do_complete_node(node_id)
            else:
                for child_id in children:
                    self._activate_node(child_id)

        elif ntype == "checkpoint":
            # Checkpoints complete immediately on activation
            self._do_complete_node(node_id)

        elif ntype == "conditional":
            self._conditional_activation_count[node_id] = (
                self._conditional_activation_count.get(node_id, 0) + 1
            )
            on_activate = self._all_nodes[node_id].get("on_activate")
            if on_activate:
                self._queue_action(on_activate)

    def _do_complete_node(self, node_id: str) -> None:
        """Mark a node as complete. Follow outgoing sequence edges (for non-children)."""
        gobj = self._graph_nodes[node_id]
        if gobj.status in ("complete", "cancelled", "failed"):
            return

        gobj.status = "complete"
        self._active_set.discard(node_id)
        self._complete_set.add(node_id)
        self._tick_completions.append(node_id)

        # If this node is a child of a parallel, notify the parent.
        parent_id = self._child_parent.get(node_id)
        if parent_id is not None:
            self._on_child_complete(parent_id, node_id)
            return  # Parent handles edge traversal after its own completion

        # Follow outgoing sequence edges from this node
        for edge in self._outgoing.get(node_id, []):
            if edge.get("type", "sequence") == "sequence":
                if on_complete := edge.get("on_complete"):
                    self._queue_action(on_complete)
                self._activate_node(edge["to"])

    def _on_child_complete(self, parent_id: str, child_id: str) -> None:
        """Handle a parallel child completing. Check whether parent's threshold is met."""
        parent_gobj = self._graph_nodes[parent_id]
        # Guard: parent may already be complete (e.g. "any" mode resolved this tick)
        if parent_gobj.status in ("complete", "cancelled", "failed"):
            return

        parent_def = self._all_nodes[parent_id]
        complete_when = parent_def.get("complete_when", "all")
        children = self._parallel_children.get(parent_id, [])
        total = len(children)

        self._parallel_complete_count[parent_id] = (
            self._parallel_complete_count.get(parent_id, 0) + 1
        )
        completed_count = self._parallel_complete_count[parent_id]

        should_complete = False

        if complete_when == "all":
            should_complete = completed_count >= total

        elif complete_when == "any":
            should_complete = True

        elif isinstance(complete_when, dict):
            count_needed = complete_when.get("count", total)
            within_seconds = complete_when.get("within_seconds")

            if completed_count >= count_needed:
                if within_seconds is not None:
                    start_e = self._parallel_start_elapsed.get(parent_id, 0.0)
                    elapsed_in_parallel = self._elapsed - start_e
                    should_complete = elapsed_in_parallel <= within_seconds
                else:
                    should_complete = True

        if should_complete:
            self._cancel_remaining_children(parent_id)
            self._do_complete_node(parent_id)

    def _cancel_remaining_children(self, parent_id: str) -> None:
        """Cancel any children of parent_id that are still active."""
        for cid in self._parallel_children.get(parent_id, []):
            gobj = self._graph_nodes[cid]
            if gobj.status == "active":
                gobj.status = "cancelled"
                self._active_set.discard(cid)

    def _queue_action(self, action: dict | list) -> None:
        """Queue one or more on_complete actions."""
        if isinstance(action, list):
            self._pending_actions.extend(action)
        else:
            self._pending_actions.append(action)

    # ------------------------------------------------------------------
    # Main tick
    # ------------------------------------------------------------------

    def tick(self, world: World, ship: Ship, dt: float = 0.1) -> list[str]:
        """Evaluate triggers for all active nodes.

        Returns a list of node IDs that completed this tick.
        Call pop_pending_actions() after to retrieve queued side effects.
        """
        if self._over:
            return []

        self._elapsed += dt
        self._last_dt = dt
        self._tick_completions = []  # reset for this tick

        # ── 1. Check defeat condition ───────────────────────────────────
        if self._defeat_condition:
            if self._eval_trigger(self._defeat_condition, world, ship, ""):
                self._over = True
                self._result = "defeat"
                return []

        # ── 2. Check conditional nodes (independent track) ─────────────
        for cid in self._conditional_ids:
            gobj = self._graph_nodes[cid]
            node_def = self._all_nodes[cid]
            condition = node_def.get("condition", {})
            deactivate_when = node_def.get("deactivate_when")

            if gobj.status == "pending":
                max_act = node_def.get("max_activations", 0)  # 0 = unlimited
                already_fired = self._conditional_activation_count.get(cid, 0)
                if max_act > 0 and already_fired >= max_act:
                    continue  # one-shot conditional already used up
                if condition and self._eval_trigger(condition, world, ship, cid):
                    self._activate_node(cid)

            elif gobj.status == "active":
                if deactivate_when and self._eval_trigger(deactivate_when, world, ship, cid):
                    on_deactivate = node_def.get("on_deactivate")
                    if on_deactivate:
                        self._queue_action(on_deactivate)
                    # Reset to pending — can re-activate if condition becomes true again
                    gobj.status = "pending"
                    self._active_set.discard(cid)

        # ── 3. Check active objective / branch / parallel nodes ─────────
        # Snapshot active_set to avoid modifying while iterating
        for node_id in list(self._active_set):
            gobj = self._graph_nodes[node_id]
            if gobj.status != "active":
                continue  # may have been cancelled this tick

            ntype = self._all_nodes[node_id].get("type", "objective")

            if ntype == "objective":
                trigger_def = self._all_nodes[node_id].get("trigger", {})
                if trigger_def and self._eval_trigger(trigger_def, world, ship, node_id):
                    self._do_complete_node(node_id)

            elif ntype == "branch":
                # Check outgoing branch_trigger edges — first to fire wins
                for edge in self._outgoing.get(node_id, []):
                    if edge.get("type") != "branch_trigger":
                        continue
                    edge_trigger = edge.get("trigger", {})
                    if edge_trigger and self._eval_trigger(edge_trigger, world, ship, node_id):
                        # This branch wins
                        if on_complete := edge.get("on_complete"):
                            self._queue_action(on_complete)
                        self._activate_node(edge["to"])
                        # Complete the branch node itself (no sequence edges to follow)
                        self._do_complete_node(node_id)
                        break  # Only one branch can fire per tick

            elif ntype == "parallel":
                # Check for within_seconds timeout
                parent_def = self._all_nodes[node_id]
                complete_when = parent_def.get("complete_when", "all")
                if isinstance(complete_when, dict) and "within_seconds" in complete_when:
                    start_e = self._parallel_start_elapsed.get(node_id, 0.0)
                    if self._elapsed - start_e > complete_when["within_seconds"]:
                        count_needed = complete_when.get(
                            "count", len(self._parallel_children.get(node_id, []))
                        )
                        completed_count = self._parallel_complete_count.get(node_id, 0)
                        if completed_count < count_needed:
                            # Timeout with insufficient completions → fail
                            self._cancel_remaining_children(node_id)
                            self._graph_nodes[node_id].status = "failed"
                            self._active_set.discard(node_id)

        # ── 4. Check victory ─────────────────────────────────────────────
        if self._victory_nodes and all(
            self._graph_nodes[nid].status == "complete"
            for nid in self._victory_nodes
            if nid in self._graph_nodes
        ):
            self._over = True
            self._result = "victory"

        return list(self._tick_completions)

    # ------------------------------------------------------------------
    # Trigger evaluation
    # ------------------------------------------------------------------

    def _eval_trigger(self, trigger_def: dict, world: World, ship: Ship, node_id: str) -> bool:
        """Evaluate a trigger dict against the current game state."""
        t = trigger_def.get("type", "")

        # ── Spatial ────────────────────────────────────────────────────
        if t == "player_in_area":
            return (
                distance(ship.x, ship.y, trigger_def["x"], trigger_def["y"]) < trigger_def["r"]
            )

        # ── Entity / enemy ─────────────────────────────────────────────
        if t == "scan_completed":
            entity_id = trigger_def.get("target") or trigger_def.get("entity_id", "")
            enemy = next((e for e in world.enemies if e.id == entity_id), None)
            return enemy is not None and enemy.scan_state == "scanned"

        if t == "entity_destroyed":
            entity_id = trigger_def.get("target") or trigger_def.get("entity_id", "")
            return not any(e.id == entity_id for e in world.enemies)

        if t == "all_enemies_destroyed":
            return len(world.enemies) == 0

        # ── Hull ───────────────────────────────────────────────────────
        if t in ("ship_hull_zero", "player_hull_zero"):
            return ship.hull <= 0

        if t == "ship_hull_below":
            return ship.hull <= trigger_def.get("value", 0)

        if t == "ship_hull_above":
            return ship.hull > trigger_def.get("value", 0)

        # ── Timer ──────────────────────────────────────────────────────
        if t == "timer_elapsed":
            return self._elapsed >= trigger_def["seconds"]

        # ── Wave ───────────────────────────────────────────────────────
        if t == "wave_defeated":
            prefix = trigger_def.get("prefix") or trigger_def.get("enemy_prefix", "")
            return not any(e.id.startswith(prefix) for e in world.enemies)

        # ── Station ────────────────────────────────────────────────────
        if t == "station_hull_below":
            station_id = trigger_def.get("station_id", "")
            threshold = trigger_def.get("threshold", 0)
            station = next((s for s in world.stations if s.id == station_id), None)
            return station is not None and station.hull <= threshold

        if t == "station_destroyed":
            station_id = trigger_def.get("station_id", "")
            station = next((s for s in world.stations if s.id == station_id), None)
            return station is None or station.hull <= 0

        if t == "station_captured":
            station_id = trigger_def.get("station_id", "")
            return station_id in self._captured_station_ids

        if t == "component_destroyed":
            comp_id = trigger_def.get("component_id", "")
            for s in world.stations:
                if s.defenses is not None:
                    for comp in s.defenses.all_components():
                        if comp.id == comp_id:
                            return comp.hp <= 0
            return True  # not found in any active station → station gone → destroyed

        if t == "station_sensor_jammed":
            station_id = trigger_def.get("station_id", "")
            for s in world.stations:
                if s.id == station_id and s.defenses is not None:
                    return s.defenses.sensor_array.jammed
            return False

        if t == "station_reinforcements_called":
            station_id = trigger_def.get("station_id", "")
            for s in world.stations:
                if s.id == station_id and s.defenses is not None:
                    return s.defenses.sensor_array.distress_sent
            return False

        # ── Signal / triangulation ─────────────────────────────────────
        if t == "signal_located":
            return self._triangulation_count >= 2

        # ── Proximity with shields ─────────────────────────────────────
        if t == "proximity_with_shields":
            target_x = trigger_def["x"]
            target_y = trigger_def["y"]
            radius = trigger_def.get("radius") or trigger_def.get("r", 0)
            min_shield = trigger_def.get("min_shield", 0)
            duration = trigger_def.get("duration", 0)

            dist = distance(ship.x, ship.y, target_x, target_y)
            shield_ok = min(ship.shields.fore, ship.shields.aft,
                            ship.shields.port, ship.shields.starboard) >= min_shield
            timer_key = f"prox_{node_id}"

            if dist < radius and shield_ok:
                self._proximity_timers[timer_key] = (
                    self._proximity_timers.get(timer_key, 0.0) + self._last_dt
                )
            else:
                self._proximity_timers[timer_key] = 0.0

            return self._proximity_timers.get(timer_key, 0.0) >= duration

        # ── Puzzle ─────────────────────────────────────────────────────
        if t == "puzzle_completed":
            label = trigger_def.get("label") or trigger_def.get("puzzle_label", "")
            return label in self._completed_puzzle_labels

        if t == "puzzle_failed":
            label = trigger_def.get("label") or trigger_def.get("puzzle_label", "")
            return label in self._failed_puzzle_labels

        if t == "puzzle_resolved":
            label = trigger_def.get("label") or trigger_def.get("puzzle_label", "")
            return (
                label in self._completed_puzzle_labels
                or label in self._failed_puzzle_labels
            )

        # ── Training ───────────────────────────────────────────────────
        if t == "training_flag":
            return trigger_def.get("flag", "") in self._training_flags

        # ── Boarding ───────────────────────────────────────────────────
        if t == "boarding_active":
            interior = getattr(ship, "interior", None)
            return bool(getattr(interior, "intruders", []))

        if t == "no_intruders":
            interior = getattr(ship, "interior", None)
            return not bool(getattr(interior, "intruders", []))

        # ── Creatures (v0.05k) ─────────────────────────────────────────
        if t == "creature_state":
            creature_id = trigger_def.get("creature_id", "")
            state = trigger_def.get("state", "")
            return any(
                c.id == creature_id and c.behaviour_state == state
                for c in getattr(world, "creatures", [])
            )

        if t == "creature_destroyed":
            creature_id = trigger_def.get("creature_id", "")
            return creature_id in self._destroyed_creature_ids

        if t == "creature_study_complete":
            creature_id = trigger_def.get("creature_id", "")
            return any(
                c.id == creature_id and c.study_progress >= 100.0
                for c in getattr(world, "creatures", [])
            )

        if t == "creature_communication_complete":
            creature_id = trigger_def.get("creature_id", "")
            return any(
                c.id == creature_id and c.communication_progress >= 100.0
                for c in getattr(world, "creatures", [])
            )

        if t == "no_creatures_type":
            creature_type = trigger_def.get("creature_type", "")
            return not any(
                c.creature_type == creature_type
                for c in getattr(world, "creatures", [])
            )

        # ── Compound ───────────────────────────────────────────────────
        if t == "all_of":
            return all(
                self._eval_trigger(sub, world, ship, node_id)
                for sub in trigger_def.get("triggers", [])
            )

        if t == "any_of":
            return any(
                self._eval_trigger(sub, world, ship, node_id)
                for sub in trigger_def.get("triggers", [])
            )

        if t == "none_of":
            return not any(
                self._eval_trigger(sub, world, ship, node_id)
                for sub in trigger_def.get("triggers", [])
            )

        # Unknown trigger type — treat as false
        return False

    # ------------------------------------------------------------------
    # Public interface (mirrors MissionEngine)
    # ------------------------------------------------------------------

    def pop_pending_actions(self) -> list[dict]:
        """Return and clear queued on_complete actions since last call."""
        actions = list(self._pending_actions)
        self._pending_actions.clear()
        return actions

    def notify_puzzle_result(self, label: str, success: bool) -> None:
        """Record a puzzle resolution for puzzle_completed / puzzle_failed triggers."""
        if success:
            self._completed_puzzle_labels.add(label)
        else:
            self._failed_puzzle_labels.add(label)

    def set_training_flag(self, flag: str) -> None:
        """Record a player action flag for training_flag triggers."""
        self._training_flags.add(flag)

    def notify_station_captured(self, station_id: str) -> None:
        """Record a station capture for station_captured triggers."""
        self._captured_station_ids.add(station_id)

    def notify_creature_destroyed(self, creature_id: str) -> None:
        """Record a creature destruction for creature_destroyed triggers."""
        self._destroyed_creature_ids.add(creature_id)

    def record_signal_scan(self, ship_x: float, ship_y: float) -> bool:
        """Record a triangulation scan position.

        Requires at least 8 000 world-unit separation from the previous scan.
        Returns True when triangulation is complete (≥ 2 distinct positions).
        """
        MIN_SEPARATION = 8_000.0
        if not self._triangulation_positions or distance(
            ship_x, ship_y,
            self._triangulation_positions[-1][0],
            self._triangulation_positions[-1][1],
        ) >= MIN_SEPARATION:
            self._triangulation_positions.append((ship_x, ship_y))
            self._triangulation_count = len(self._triangulation_positions)
        return self._triangulation_count >= 2

    def is_over(self) -> tuple[bool, str | None]:
        """Return (True, result) when mission has ended, else (False, None)."""
        return self._over, self._result

    def get_objectives(self) -> list[GraphObjective]:
        """Return all registered nodes in registration order."""
        return [self._graph_nodes[nid] for nid in self._node_order]

    def get_active_node_ids(self) -> list[str]:
        """Return IDs of currently active nodes."""
        return list(self._active_set)

    def get_complete_node_ids(self) -> list[str]:
        """Return IDs of completed nodes."""
        return list(self._complete_set)

    def get_active_objective_index(self) -> int:
        """Return the index in node_order of the first active non-conditional node.

        Returns -1 if no active node found. Provided for backward compatibility
        with the training system which uses sequential index-based hints.
        """
        for i, nid in enumerate(self._node_order):
            if nid in self._conditional_ids:
                continue
            if self._graph_nodes[nid].status == "active":
                return i
        return -1

    # ------------------------------------------------------------------
    # Save / resume
    # ------------------------------------------------------------------

    def serialise_state(self) -> dict:
        """Capture runtime state for save/resume. Excludes the static graph structure."""
        return {
            "graph_nodes": {nid: gobj.status for nid, gobj in self._graph_nodes.items()},
            "proximity_timers": dict(self._proximity_timers),
            "parallel_complete_count": dict(self._parallel_complete_count),
            "parallel_start_elapsed": dict(self._parallel_start_elapsed),
            "elapsed": self._elapsed,
            "last_dt": self._last_dt,
            "completed_puzzle_labels": list(self._completed_puzzle_labels),
            "failed_puzzle_labels": list(self._failed_puzzle_labels),
            "training_flags": list(self._training_flags),
            "triangulation_count": self._triangulation_count,
            "triangulation_positions": [list(p) for p in self._triangulation_positions],
            "over": self._over,
            "result": self._result,
            "captured_station_ids": list(self._captured_station_ids),
            "conditional_activation_count": dict(self._conditional_activation_count),
            "destroyed_creature_ids": list(self._destroyed_creature_ids),
        }

    def deserialise_state(self, state: dict) -> None:
        """Restore runtime state from save data (call after __init__)."""
        # Restore per-node statuses first.
        for nid, status in state.get("graph_nodes", {}).items():
            if nid in self._graph_nodes:
                self._graph_nodes[nid].status = status
        # Derive active/complete sets from restored statuses.
        self._active_set = {
            nid for nid, gobj in self._graph_nodes.items() if gobj.status == "active"
        }
        self._complete_set = {
            nid for nid, gobj in self._graph_nodes.items() if gobj.status == "complete"
        }
        # Restore timers and counters.
        self._proximity_timers = dict(state.get("proximity_timers", {}))
        self._parallel_complete_count = {
            k: int(v) for k, v in state.get("parallel_complete_count", {}).items()
        }
        self._parallel_start_elapsed = dict(state.get("parallel_start_elapsed", {}))
        self._elapsed = float(state.get("elapsed", 0.0))
        self._last_dt = float(state.get("last_dt", 0.1))
        # Restore puzzle and training tracking.
        self._completed_puzzle_labels = set(state.get("completed_puzzle_labels", []))
        self._failed_puzzle_labels = set(state.get("failed_puzzle_labels", []))
        self._training_flags = set(state.get("training_flags", []))
        # Restore triangulation.
        self._triangulation_count = int(state.get("triangulation_count", 0))
        self._triangulation_positions = [
            tuple(p) for p in state.get("triangulation_positions", [])  # type: ignore[misc]
        ]
        # Restore mission end state.
        self._over = bool(state.get("over", False))
        self._result = state.get("result")
        # Restore station capture and conditional activation tracking.
        self._captured_station_ids = set(state.get("captured_station_ids", []))
        self._conditional_activation_count = {
            k: int(v) for k, v in state.get("conditional_activation_count", {}).items()
        }
        # Restore creature destruction tracking.
        self._destroyed_creature_ids = set(state.get("destroyed_creature_ids", []))
        # Clear transient per-tick state — no stale actions survive a load.
        self._pending_actions.clear()
        self._tick_completions.clear()
