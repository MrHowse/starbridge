"""Puzzle type: Tactical Positioning.

The server reveals incoming intruder boarding paths and spawn locations.
The Security officer repositions marine squads to intercept them before
the boarding action begins.

  generate()               — returns intruder threat list (spawn + objective)
  validate_submission()    — {"confirmed": True} runs a 300-tick mini-simulation
                             of the boarding with current squad positions; returns
                             True if all intruders are defeated within 300 ticks
  apply_assist()           — "reveal_interception_points" returns the midpoint
                             rooms on each intruder's path to its objective

The puzzle receives the live ShipInterior reference and intruder_specs via
kwargs forwarded by PuzzleEngine.create_puzzle(). These are stored and used
only during validate_submission() and apply_assist() — never during generate().
"""
from __future__ import annotations

import copy
from typing import Any

from server.models.interior import ShipInterior
from server.models.security import (
    INTRUDER_DAMAGE_PER_TICK,
    MARINE_DAMAGE_PER_TICK,
    Intruder,
)
from server.puzzles.base import PuzzleInstance
from server.puzzles.engine import register_puzzle_type

# Maximum ticks to simulate when validating a submission (300 = 30 s game-time).
_SIM_TICKS: int = 300


class TacticalPositioningPuzzle(PuzzleInstance):
    """Security station puzzle — position squads to intercept boarders."""

    def __init__(
        self,
        interior: ShipInterior,
        intruder_specs: list[dict],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._interior = interior          # live reference — NOT copied; used for pathfinding
        self._intruder_specs = intruder_specs

    def generate(self) -> dict[str, Any]:
        """Return intruder threat data for the Security client to display."""
        return {
            "intruder_threats": [
                {
                    "id": s["id"],
                    "room_id": s["room_id"],
                    "objective_id": s["objective_id"],
                }
                for s in self._intruder_specs
            ],
        }

    def validate_submission(self, submission: dict[str, Any]) -> bool:
        """Run a mini-simulation; return True if all intruders are defeated.

        Snapshots the current interior (room states, door seals, squad positions)
        at the moment of submission and runs a simplified boarding simulation.
        Returns True if all intruders are defeated within _SIM_TICKS ticks.
        """
        if not submission.get("confirmed"):
            return False

        # Deep-copy the interior so the live game state is unaffected.
        interior_snap = copy.deepcopy(self._interior)

        # Squads are already positioned on the interior (via deploy_squads + player moves).
        squads = interior_snap.marine_squads  # already deep-copied

        # Fresh intruders from specs stored at puzzle creation time.
        intruders: list[Intruder] = [
            Intruder(
                id=s["id"],
                room_id=s["room_id"],
                objective_id=s["objective_id"],
            )
            for s in self._intruder_specs
        ]
        interior_snap.intruders = intruders

        for _ in range(_SIM_TICKS):
            if not intruders:
                return True

            # Tick intruder move timers; move when ready.
            for intruder in intruders:
                intruder.tick_move_timer()
                if not intruder.is_ready_to_move():
                    continue
                if intruder.room_id == intruder.objective_id:
                    intruder.reset_move_timer()
                    continue
                path = interior_snap.find_path(intruder.room_id, intruder.objective_id)
                if path and len(path) >= 2:
                    intruder.room_id = path[1]
                intruder.reset_move_timer()

            # Combat: squads fight intruders in the same room.
            for squad in squads:
                if squad.is_eliminated():
                    continue
                room_intruders = [
                    i for i in intruders
                    if i.room_id == squad.room_id and not i.is_defeated()
                ]
                for intruder in room_intruders:
                    intruder.take_damage(MARINE_DAMAGE_PER_TICK * squad.count)
                    squad.take_damage(INTRUDER_DAMAGE_PER_TICK)

            # Remove defeated intruders.
            intruders = [i for i in intruders if not i.is_defeated()]

        return len(intruders) == 0

    def apply_assist(self, assist_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """reveal_interception_points — return midpoint rooms on intruder paths."""
        if assist_type == "reveal_interception_points":
            points: list[str] = []
            seen: set[str] = set()
            for spec in self._intruder_specs:
                path = self._interior.find_path(spec["room_id"], spec["objective_id"])
                if path and len(path) >= 2:
                    mid = path[len(path) // 2]
                    if mid not in seen:
                        seen.add(mid)
                        points.append(mid)
            return {"interception_points": points}
        return {}


# Self-register when this module is imported.
register_puzzle_type("tactical_positioning", TacticalPositioningPuzzle)
