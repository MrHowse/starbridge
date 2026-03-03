"""
Ship Interior Model — Room layout and BFS pathfinding.

Defines the physical layout of the ship as a graph of rooms. Used by
Engineering (repair routing), Medical (crew location), and Security
(marine deployment) in v0.02+.

v0.07-4.2: Per-ship-class interior layouts loaded from interiors/*.json.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from server.models.security import Intruder, MarineSquad

# Directory containing interior JSON definitions.
_INTERIORS_DIR = Path(__file__).resolve().parent.parent.parent / "interiors"

# Cache of parsed interior data (ship_class -> dict).
_interior_cache: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Room
# ---------------------------------------------------------------------------


@dataclass
class Room:
    """One room aboard the ship."""

    id: str                    # Unique room identifier
    name: str                  # Display name
    deck: str                  # Crew deck this room belongs to
    position: tuple[int, int]  # Grid position (col, row) for rendering
    connections: list[str]     # IDs of adjacent connected rooms
    state: str = "normal"      # "normal" | "damaged" | "decompressed" | "fire" | "hostile"
    door_sealed: bool = False  # Whether the room's entry door is sealed
    # v0.07-4.2: Per-ship-class fields
    deck_number: int = 0                                       # Physical deck number (1-based)
    marine_only_connections: list[str] = field(default_factory=list)  # Corvette secret tunnels
    quarantine_lockable: bool = False                          # Medical ship biohazard rooms
    tags: list[str] = field(default_factory=list)              # Flexible labels


# ---------------------------------------------------------------------------
# ShipInterior
# ---------------------------------------------------------------------------


@dataclass
class ShipInterior:
    """The ship's interior as a graph of connected rooms."""

    rooms: dict[str, Room] = field(default_factory=dict)

    # Security station entities (populated by game_loop_security on boarding events).
    marine_squads: list[MarineSquad] = field(default_factory=list)
    intruders: list[Intruder] = field(default_factory=list)

    # C.2.1: system_name -> room_id mapping (populated from JSON).
    system_rooms: dict[str, str] = field(default_factory=dict)

    def find_path(
        self,
        from_id: str,
        to_id: str,
        ignore_sealed: bool = False,
        use_marine_tunnels: bool = False,
        blocked_connections: set[tuple[str, str]] | None = None,
    ) -> list[str]:
        """BFS shortest path between two rooms.

        Returns list of room IDs (inclusive of start and end).
        Returns empty list if no path exists or rooms are unknown.
        Sealed rooms and decompressed rooms block traversal unless
        *ignore_sealed* is True (used by boarding parties that breach doors).

        *use_marine_tunnels* includes marine_only_connections in the graph
        (corvette secret tunnels that marines can use but intruders can't).

        *blocked_connections* is an optional set of sorted (room_a, room_b) tuples
        representing emergency bulkhead seals that block traversal.
        """
        if from_id not in self.rooms or to_id not in self.rooms:
            return []
        if from_id == to_id:
            return [from_id]

        visited: set[str] = {from_id}
        queue: deque[list[str]] = deque([[from_id]])

        while queue:
            path = queue.popleft()
            current_id = path[-1]
            room = self.rooms[current_id]

            neighbors = list(room.connections)
            if use_marine_tunnels:
                neighbors.extend(room.marine_only_connections)

            for next_id in neighbors:
                if next_id in visited:
                    continue
                next_room = self.rooms.get(next_id)
                if next_room is None:
                    continue
                if next_room.state == "decompressed":
                    continue
                if next_room.door_sealed and not ignore_sealed:
                    continue
                if blocked_connections is not None:
                    key = (min(current_id, next_id), max(current_id, next_id))
                    if key in blocked_connections:
                        continue
                new_path = path + [next_id]
                if next_id == to_id:
                    return new_path
                visited.add(next_id)
                queue.append(new_path)

        return []


# ---------------------------------------------------------------------------
# JSON Loading & Caching
# ---------------------------------------------------------------------------


def _load_interior_data(ship_class: str) -> dict:
    """Load and cache interior JSON for a ship class."""
    if ship_class in _interior_cache:
        return _interior_cache[ship_class]

    path = _INTERIORS_DIR / f"{ship_class}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No interior layout for ship class '{ship_class}': {path}"
        )

    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    _interior_cache[ship_class] = data
    return data


def clear_cache() -> None:
    """Clear the interior data cache (for testing)."""
    _interior_cache.clear()


def load_interior(ship_class: str) -> dict:
    """Public accessor for raw interior data dict."""
    return _load_interior_data(ship_class)


def get_system_rooms(ship_class: str) -> dict[str, str]:
    """Return system->room mapping for a ship class."""
    data = _load_interior_data(ship_class)
    return dict(data["system_rooms"])


def get_deck_rooms(ship_class: str) -> dict[int, list[str]]:
    """Return deck_number->room_id list mapping for a ship class."""
    data = _load_interior_data(ship_class)
    return {int(k): list(v) for k, v in data["deck_rooms"].items()}


def get_boarding_config(ship_class: str) -> dict:
    """Return boarding configuration for a ship class."""
    data = _load_interior_data(ship_class)
    return dict(data["boarding"])


# ---------------------------------------------------------------------------
# Interior construction
# ---------------------------------------------------------------------------


def _build_interior_from_data(data: dict) -> ShipInterior:
    """Build a ShipInterior from parsed JSON data."""
    rooms: dict[str, Room] = {}
    for rd in data["rooms"]:
        rooms[rd["id"]] = Room(
            id=rd["id"],
            name=rd["name"],
            deck=rd["crew_deck"],
            position=tuple(rd["position"]),
            connections=list(rd["connections"]),
            door_sealed=rd.get("default_sealed", False),
            deck_number=rd.get("deck_number", 0),
            marine_only_connections=list(rd.get("marine_only_connections", [])),
            quarantine_lockable=rd.get("quarantine_lockable", False),
            tags=list(rd.get("tags", [])),
        )
    system_rooms = dict(data.get("system_rooms", {}))
    return ShipInterior(rooms=rooms, system_rooms=system_rooms)


def make_default_interior(ship_class: str = "frigate") -> ShipInterior:
    """Return the interior layout for a ship class.

    Loads from interiors/{ship_class}.json. Defaults to frigate for
    backward compatibility (existing callers pass no args).
    """
    data = _load_interior_data(ship_class)
    return _build_interior_from_data(data)


def make_station_interior(station_id: str) -> ShipInterior:
    """Return an 8-room interior layout for a hostile enemy station.

    Layout (sid = station_id prefix):
      {sid}_command   -- Command Centre  (0,0) -- capture objective
      {sid}_bay       -- Fighter Bay     (2,0)
      {sid}_corridor  -- Main Corridor   (1,1)
      {sid}_reactor   -- Reactor Room    (0,1)
      {sid}_armoury   -- Armoury         (2,1)
      {sid}_gen_a     -- Generator Room A (1,2)
      {sid}_gen_b     -- Generator Room B (2,2)
      {sid}_quarters  -- Crew Quarters   (0,2) -- garrison start

    Vertical spine: command <-> corridor <-> gen_a
    Horizontal connections within each row.
    """
    s = station_id
    rooms: dict[str, Room] = {
        f"{s}_command": Room(
            f"{s}_command", "Command Centre", "command", (0, 0),
            [f"{s}_corridor", f"{s}_bay"],
        ),
        f"{s}_bay": Room(
            f"{s}_bay", "Fighter Bay", "bay", (2, 0),
            [f"{s}_command", f"{s}_armoury"],
        ),
        f"{s}_corridor": Room(
            f"{s}_corridor", "Main Corridor", "corridor", (1, 1),
            [f"{s}_command", f"{s}_reactor", f"{s}_armoury", f"{s}_gen_a"],
        ),
        f"{s}_reactor": Room(
            f"{s}_reactor", "Reactor Room", "reactor", (0, 1),
            [f"{s}_corridor", f"{s}_quarters"],
        ),
        f"{s}_armoury": Room(
            f"{s}_armoury", "Armoury", "armoury", (2, 1),
            [f"{s}_corridor", f"{s}_bay", f"{s}_gen_b"],
        ),
        f"{s}_gen_a": Room(
            f"{s}_gen_a", "Generator Room A", "generator", (1, 2),
            [f"{s}_corridor", f"{s}_gen_b", f"{s}_quarters"],
        ),
        f"{s}_gen_b": Room(
            f"{s}_gen_b", "Generator Room B", "generator", (2, 2),
            [f"{s}_gen_a", f"{s}_armoury"],
        ),
        f"{s}_quarters": Room(
            f"{s}_quarters", "Crew Quarters", "quarters", (0, 2),
            [f"{s}_reactor", f"{s}_gen_a"],
        ),
    }
    return ShipInterior(rooms=rooms)
