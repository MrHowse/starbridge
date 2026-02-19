"""
Ship Interior Model — Room layout and BFS pathfinding.

Defines the physical layout of the ship as a graph of rooms. Used by
Engineering (repair routing), Medical (crew location), and Security
(marine deployment) in v0.02+.

The static 5-deck, 20-room layout is defined in make_default_interior().
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from server.models.security import Intruder, MarineSquad


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

    def find_path(self, from_id: str, to_id: str) -> list[str]:
        """BFS shortest path between two rooms.

        Returns list of room IDs (inclusive of start and end).
        Returns empty list if no path exists or rooms are unknown.
        Sealed rooms and decompressed rooms block traversal.
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

            for next_id in room.connections:
                if next_id in visited:
                    continue
                next_room = self.rooms.get(next_id)
                if next_room is None:
                    continue
                if next_room.door_sealed or next_room.state == "decompressed":
                    continue
                new_path = path + [next_id]
                if next_id == to_id:
                    return new_path
                visited.add(next_id)
                queue.append(new_path)

        return []


# ---------------------------------------------------------------------------
# Static ship layout (5 decks, 20 rooms)
# ---------------------------------------------------------------------------


def make_default_interior() -> ShipInterior:
    """Return the standard TSS Endeavour interior layout.

    Layout — 5 physical decks, 4 rooms each, 20 rooms total:

      Deck 1 — Bridge      (crew: bridge)      bridge, conn, ready_room, observation
      Deck 2 — Operations  (crew: sensors)     sensor_array, science_lab, comms_center, astrometrics
      Deck 3 — Combat      (crew: weapons/shields) weapons_bay, torpedo_room, shields_control, combat_info
      Deck 4 — Medical     (crew: medical)     medbay, surgery, quarantine, pharmacy
      Deck 5 — Engineering (crew: engineering) main_engineering, engine_room, auxiliary_power, cargo_hold

    Horizontal connections: rooms on the same physical deck connect left→right.
    Vertical corridor at column 1: conn → science_lab → torpedo_room → surgery → engine_room.
    """
    rooms: dict[str, Room] = {
        # ---- Deck 1: Bridge ----
        "bridge":      Room("bridge",      "Bridge",             "bridge",      (0, 0),
                            ["conn"]),
        "conn":        Room("conn",        "Conn",               "bridge",      (1, 0),
                            ["bridge", "ready_room", "science_lab"]),
        "ready_room":  Room("ready_room",  "Ready Room",         "bridge",      (2, 0),
                            ["conn", "observation"]),
        "observation": Room("observation", "Observation Lounge", "bridge",      (3, 0),
                            ["ready_room"]),

        # ---- Deck 2: Operations ----
        "sensor_array":  Room("sensor_array",  "Sensor Array",  "sensors", (0, 1),
                              ["science_lab"]),
        "science_lab":   Room("science_lab",   "Science Lab",   "sensors", (1, 1),
                              ["sensor_array", "comms_center", "conn", "torpedo_room"]),
        "comms_center":  Room("comms_center",  "Comms Center",  "sensors", (2, 1),
                              ["science_lab", "astrometrics"]),
        "astrometrics":  Room("astrometrics",  "Astrometrics",  "sensors", (3, 1),
                              ["comms_center"]),

        # ---- Deck 3: Combat (weapons bay + torpedo room belong to weapons crew deck;
        #              shields control + combat info belong to shields crew deck) ----
        "weapons_bay":     Room("weapons_bay",     "Weapons Bay",     "weapons", (0, 2),
                               ["torpedo_room"]),
        "torpedo_room":    Room("torpedo_room",    "Torpedo Room",    "weapons", (1, 2),
                               ["weapons_bay", "shields_control", "science_lab", "surgery"]),
        "shields_control": Room("shields_control", "Shields Control", "shields", (2, 2),
                               ["torpedo_room", "combat_info"]),
        "combat_info":     Room("combat_info",     "Combat Info Ctr", "shields", (3, 2),
                               ["shields_control"]),

        # ---- Deck 4: Medical ----
        "medbay":     Room("medbay",     "Medbay",     "medical", (0, 3),
                           ["surgery"]),
        "surgery":    Room("surgery",    "Surgery",    "medical", (1, 3),
                           ["medbay", "quarantine", "torpedo_room", "engine_room"]),
        "quarantine": Room("quarantine", "Quarantine", "medical", (2, 3),
                           ["surgery", "pharmacy"]),
        "pharmacy":   Room("pharmacy",   "Pharmacy",   "medical", (3, 3),
                           ["quarantine"]),

        # ---- Deck 5: Engineering ----
        "main_engineering": Room("main_engineering", "Main Engineering", "engineering", (0, 4),
                                 ["engine_room"]),
        "engine_room":      Room("engine_room",      "Engine Room",      "engineering", (1, 4),
                                 ["main_engineering", "auxiliary_power", "surgery"]),
        "auxiliary_power":  Room("auxiliary_power",  "Auxiliary Power",  "engineering", (2, 4),
                                 ["engine_room", "cargo_hold"]),
        "cargo_hold":       Room("cargo_hold",       "Cargo Hold",       "engineering", (3, 4),
                                 ["auxiliary_power"]),
    }
    return ShipInterior(rooms=rooms)
