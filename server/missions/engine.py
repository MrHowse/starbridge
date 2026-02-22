"""
Mission Engine — Runtime mission execution.

Evaluates mission triggers each tick, fires events when conditions are met,
tracks objective completion, and determines when a mission is over.

Objectives are evaluated sequentially: objective N only becomes active once
objective N-1 is complete. This enforces the intended mission flow for
tutorial-style missions like First Contact.

Trigger types supported:
  player_in_area        — ship within radius r of (x, y)
  scan_completed        — named enemy has scan_state == "scanned"
  entity_destroyed      — named enemy absent from world.enemies
  all_enemies_destroyed — world.enemies is empty
  player_hull_zero      — ship.hull <= 0 (used as defeat condition)
  timer_elapsed         — mission time elapsed >= args["seconds"]
  wave_defeated         — no enemies with IDs starting with args["enemy_prefix"]
  station_hull_below    — named station hull < args["threshold"]
  signal_located        — triangulation scan count >= 2 from distinct positions
  proximity_with_shields — ship within radius of target with shields >= threshold
                           for a continuous duration
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from server.models.ship import Ship
from server.models.world import World
from server.utils.math_helpers import distance


# ---------------------------------------------------------------------------
# Objective dataclass
# ---------------------------------------------------------------------------


@dataclass
class Objective:
    """A single mission objective with its current status."""

    id: str
    text: str
    status: Literal["pending", "complete", "failed"] = "pending"


# ---------------------------------------------------------------------------
# Mission engine
# ---------------------------------------------------------------------------


class MissionEngine:
    """Evaluates trigger conditions each tick and tracks mission state."""

    def __init__(self, mission: dict) -> None:
        self._mission = mission
        self._objectives: list[Objective] = [
            Objective(id=o["id"], text=o["text"])
            for o in mission.get("objectives", [])
        ]
        self._obj_defs: list[dict] = mission.get("objectives", [])
        self._active_index: int = 0
        self._over: bool = False
        self._result: str | None = None
        self._elapsed: float = 0.0
        self._last_dt: float = 0.1
        self._pending_actions: list[dict] = []

        # Triangulation state (Mission 3)
        self._triangulation_count: int = 0
        self._triangulation_positions: list[tuple[float, float]] = []

        # Proximity timer (proximity_with_shields trigger)
        self._proximity_timer: float = 0.0

        # Puzzle completion tracking (label-based, populated by notify_puzzle_result)
        self._completed_puzzle_labels: set[str] = set()
        self._failed_puzzle_labels: set[str] = set()

        # Training flag tracking (training_flag trigger)
        self._training_flags: set[str] = set()

    def tick(self, world: World, ship: Ship, dt: float = 0.1) -> list[str]:
        """Check triggers. Returns IDs of newly-completed objectives this tick.

        Call pop_pending_actions() after tick() to retrieve on_complete side
        effects (e.g. spawn_wave) from any objectives that completed this tick.
        """
        if self._over:
            return []

        self._elapsed += dt
        self._last_dt = dt

        # Check primary defeat condition (player_hull_zero).
        defeat = self._mission.get("defeat_condition")
        if defeat == "player_hull_zero" and ship.hull <= 0:
            self._over = True
            self._result = "defeat"
            return []

        # Check alternative defeat condition (e.g. station_hull_below).
        defeat_alt = self._mission.get("defeat_condition_alt")
        if defeat_alt and self._check_trigger(defeat_alt, world, ship):
            self._over = True
            self._result = "defeat"
            return []

        newly_completed: list[str] = []

        # Sequential evaluation: only the active objective is checked.
        if self._active_index < len(self._objectives):
            obj = self._objectives[self._active_index]
            obj_def = self._obj_defs[self._active_index]
            if self._check_trigger(obj_def, world, ship):
                obj.status = "complete"
                newly_completed.append(obj.id)
                # Queue any on_complete side effects for game_loop to handle.
                # on_complete may be a single action dict OR a list of dicts.
                if on_complete := obj_def.get("on_complete"):
                    if isinstance(on_complete, list):
                        self._pending_actions.extend(on_complete)
                    else:
                        self._pending_actions.append(on_complete)
                self._active_index += 1
                # Reset per-objective timers when advancing.
                self._proximity_timer = 0.0

        # Check victory condition after updating objectives.
        victory = self._mission.get("victory_condition")
        if victory == "all_objectives_complete" and self._objectives:
            if all(o.status == "complete" for o in self._objectives):
                self._over = True
                self._result = "victory"

        return newly_completed

    def pop_pending_actions(self) -> list[dict]:
        """Return and clear any on_complete actions queued since the last call."""
        actions = list(self._pending_actions)
        self._pending_actions.clear()
        return actions

    def record_signal_scan(self, ship_x: float, ship_y: float) -> bool:
        """Record a triangulation scan position.

        Accepts the position only if it is at least 8 000 world units from the
        most recent recorded position (to enforce genuine movement between scans).

        Returns True if triangulation is now complete (>= 2 distinct positions).
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

    def notify_puzzle_result(self, label: str, success: bool) -> None:
        """Record a puzzle resolution for use by puzzle_completed / puzzle_failed triggers."""
        if success:
            self._completed_puzzle_labels.add(label)
        else:
            self._failed_puzzle_labels.add(label)

    def set_training_flag(self, flag: str) -> None:
        """Record a player action flag for training_flag triggers."""
        self._training_flags.add(flag)

    def get_active_objective_index(self) -> int:
        """Return the index of the currently active objective."""
        return self._active_index

    def get_objectives(self) -> list[Objective]:
        """Return a copy of the current objective list."""
        return list(self._objectives)

    def is_over(self) -> tuple[bool, str | None]:
        """Return (True, result) when the mission has ended, else (False, None)."""
        return self._over, self._result

    # ------------------------------------------------------------------
    # Trigger evaluation
    # ------------------------------------------------------------------

    def _check_trigger(self, obj_def: dict, world: World, ship: Ship) -> bool:
        trigger = obj_def.get("trigger")
        args = obj_def.get("args", {})

        if trigger == "player_in_area":
            return distance(ship.x, ship.y, args["x"], args["y"]) < args["r"]

        if trigger == "scan_completed":
            entity_id = args["entity_id"]
            enemy = next((e for e in world.enemies if e.id == entity_id), None)
            if enemy is None:
                return False
            return enemy.scan_state == "scanned"

        if trigger == "entity_destroyed":
            entity_id = args["entity_id"]
            return not any(e.id == entity_id for e in world.enemies)

        if trigger == "all_enemies_destroyed":
            return len(world.enemies) == 0

        if trigger == "player_hull_zero":
            return ship.hull <= 0

        if trigger == "timer_elapsed":
            return self._elapsed >= args["seconds"]

        if trigger == "wave_defeated":
            prefix = args["enemy_prefix"]
            return not any(e.id.startswith(prefix) for e in world.enemies)

        if trigger == "station_hull_below":
            station_id = args["station_id"]
            threshold = args["threshold"]
            station = next((s for s in world.stations if s.id == station_id), None)
            if station is None:
                return False
            return station.hull <= threshold

        if trigger == "signal_located":
            return self._triangulation_count >= 2

        if trigger == "proximity_with_shields":
            target_x = args["x"]
            target_y = args["y"]
            radius = args["radius"]
            min_shield = args["min_shield"]
            duration = args["duration"]

            dist_to_target = distance(ship.x, ship.y, target_x, target_y)
            shield_ok = min(ship.shields.fore, ship.shields.aft,
                            ship.shields.port, ship.shields.starboard) >= min_shield

            if dist_to_target < radius and shield_ok:
                self._proximity_timer += self._last_dt
            else:
                self._proximity_timer = 0.0

            return self._proximity_timer >= duration

        if trigger == "puzzle_completed":
            return args["puzzle_label"] in self._completed_puzzle_labels

        if trigger == "puzzle_failed":
            return args["puzzle_label"] in self._failed_puzzle_labels

        if trigger == "puzzle_resolved":
            # Fires when label is in either completed or failed (regardless of outcome).
            label = args["puzzle_label"]
            return (
                label in self._completed_puzzle_labels
                or label in self._failed_puzzle_labels
            )

        if trigger == "training_flag":
            return args["flag"] in self._training_flags

        return False
