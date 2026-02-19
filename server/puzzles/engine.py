"""Puzzle Engine — creates, ticks, and resolves puzzle instances.

Responsibilities:
  - Instantiate puzzle types from a string registry.
  - Tick all active puzzles each game loop tick.
  - Route submit / apply_assist / cancel commands to the correct puzzle.
  - Collect pending broadcasts from all puzzles for the game loop to send.
  - Report resolved puzzles (id, label, success) for mission engine notification.

Integration pattern (game_loop.py):
    _puzzle_engine.tick(TICK_DT)
    for roles, msg in _puzzle_engine.pop_pending_broadcasts():
        await _manager.broadcast_to_roles(roles, msg)
    for puzzle_id, label, success in _puzzle_engine.pop_resolved():
        mission_engine.notify_puzzle_result(label, success)
"""
from __future__ import annotations

import logging

from server.models.messages import Message
from server.puzzles.base import PuzzleInstance

logger = logging.getLogger("starbridge.puzzle_engine")

# Registry: puzzle_type string → PuzzleInstance subclass.
# Populated by puzzle type modules calling register_puzzle_type() at import time.
_PUZZLE_REGISTRY: dict[str, type[PuzzleInstance]] = {}


def register_puzzle_type(name: str, cls: type[PuzzleInstance]) -> None:
    """Register a puzzle type by name. Called by each puzzle module at import."""
    _PUZZLE_REGISTRY[name] = cls


class PuzzleEngine:
    """Manages active puzzle instances across all stations."""

    def __init__(self) -> None:
        self._puzzles: dict[str, PuzzleInstance] = {}  # puzzle_id → instance
        self._label_to_id: dict[str, str] = {}          # label → puzzle_id
        self._pending: list[tuple[list[str], Message]] = []
        self._resolved: list[tuple[str, str, bool]] = []  # (puzzle_id, label, success)
        self._relay_data: list[tuple[str, dict]] = []    # (station, relay_component)
        self._counter: int = 0

    def reset(self) -> None:
        """Clear all state. Called by the game loop on game start."""
        self._puzzles.clear()
        self._label_to_id.clear()
        self._pending.clear()
        self._resolved.clear()
        self._relay_data.clear()
        self._counter = 0

    # ------------------------------------------------------------------
    # Puzzle lifecycle
    # ------------------------------------------------------------------

    def create_puzzle(
        self,
        puzzle_type: str,
        station: str,
        label: str,
        difficulty: int = 1,
        time_limit: float = 30.0,
        **params: object,
    ) -> PuzzleInstance | None:
        """Instantiate a puzzle and broadcast puzzle.started to the station role.

        Returns the new PuzzleInstance, or None if the puzzle_type is unknown.
        """
        cls = _PUZZLE_REGISTRY.get(puzzle_type)
        if cls is None:
            logger.error("Unknown puzzle type: %s", puzzle_type)
            return None

        self._counter += 1
        puzzle_id = f"puzzle_{self._counter}"

        instance = cls(
            puzzle_id=puzzle_id,
            label=label,
            station=station,
            difficulty=difficulty,
            time_limit=time_limit,
            **params,
        )
        data = instance.generate()

        self._puzzles[puzzle_id] = instance
        self._label_to_id[label] = puzzle_id

        # Broadcast puzzle.started to the target station role immediately.
        self._pending.append((
            [station],
            Message.build("puzzle.started", {
                "puzzle_id": puzzle_id,
                "label": label,
                "type": puzzle_type,
                "difficulty": difficulty,
                "time_limit": time_limit,
                "data": data,
            }),
        ))
        return instance

    def tick(self, dt: float) -> None:
        """Tick all active puzzles, collect their broadcasts, detect resolutions."""
        for puzzle in list(self._puzzles.values()):
            puzzle.tick(dt)
            self._pending.extend(puzzle.pop_pending_broadcasts())

        # Detect newly resolved puzzles and collect for mission engine notification.
        already_reported = {pid for pid, _, _ in self._resolved}
        for puzzle_id, puzzle in list(self._puzzles.items()):
            if puzzle._resolved and puzzle_id not in already_reported:
                self._resolved.append((puzzle_id, puzzle.label, puzzle._success))
                # Capture relay data from puzzles that provide it on success.
                if puzzle._success and hasattr(puzzle, "_relay_component") and puzzle._relay_component:  # type: ignore[union-attr]
                    self._relay_data.append((puzzle.station, puzzle._relay_component))  # type: ignore[union-attr]

        # Prune resolved puzzles.
        self._puzzles = {
            pid: p for pid, p in self._puzzles.items() if not p._resolved
        }

    def submit(self, puzzle_id: str, submission: dict) -> None:
        """Validate a player submission and queue the result broadcast."""
        puzzle = self._puzzles.get(puzzle_id)
        if puzzle is None or not puzzle.is_active():
            return
        success = puzzle.validate_submission(submission)
        puzzle._resolve(success)
        # Report resolution immediately (before tick() runs).
        self._resolved.append((puzzle_id, puzzle.label, puzzle._success))
        # Capture relay data if present.
        if success and hasattr(puzzle, "_relay_component") and puzzle._relay_component:  # type: ignore[union-attr]
            self._relay_data.append((puzzle.station, puzzle._relay_component))  # type: ignore[union-attr]
        # Prune now so tick() doesn't double-report.
        del self._puzzles[puzzle_id]
        # Collect broadcasts immediately so they go out this tick.
        self._pending.extend(puzzle.pop_pending_broadcasts())

    def apply_assist(self, puzzle_id: str, assist_type: str, data: dict) -> None:
        """Apply an assist to a puzzle and broadcast puzzle.assist_applied."""
        puzzle = self._puzzles.get(puzzle_id)
        if puzzle is None or not puzzle.is_active():
            return
        result_data = puzzle.apply_assist(assist_type, data)
        self._pending.append((
            [puzzle.station],
            Message.build("puzzle.assist_applied", {
                "puzzle_id": puzzle_id,
                "label": puzzle.label,
                "assist_type": assist_type,
                "data": result_data,
            }),
        ))

    def cancel(self, puzzle_id: str) -> None:
        """Cancel a puzzle silently (no result broadcast)."""
        puzzle = self._puzzles.get(puzzle_id)
        if puzzle is None or not puzzle.is_active():
            return
        puzzle._active = False
        puzzle._resolved = True
        puzzle._success = False

    # ------------------------------------------------------------------
    # Drain helpers (called by game loop each tick)
    # ------------------------------------------------------------------

    def pop_pending_broadcasts(self) -> list[tuple[list[str], Message]]:
        """Return and clear all pending role-filtered broadcasts."""
        broadcasts = list(self._pending)
        self._pending.clear()
        return broadcasts

    def pop_resolved(self) -> list[tuple[str, str, bool]]:
        """Return and clear (puzzle_id, label, success) for all newly-resolved puzzles."""
        resolved = list(self._resolved)
        self._resolved.clear()
        return resolved

    def pop_relay_data(self) -> list[tuple[str, dict]]:
        """Return and clear (station, relay_component) for resolved puzzles with relay data.

        Used by the game loop to implement cross-station assist chains
        (e.g., Comms transmission_decoding → Science relay_frequency).
        """
        data = list(self._relay_data)
        self._relay_data.clear()
        return data

    def get_active_for_station(self, station: str) -> PuzzleInstance | None:
        """Return the active puzzle for a station, or None."""
        for puzzle in self._puzzles.values():
            if puzzle.station == station and puzzle.is_active():
                return puzzle
        return None
