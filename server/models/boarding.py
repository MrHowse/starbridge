"""
Boarding Party Model.

BoardingParty represents an enemy boarding force that enters the ship,
advances toward an objective, and attempts sabotage or capture.

Boarding events are generated from sandbox events, enemy actions, or
mission triggers. Each party has an objective, path through the interior,
morale, and combat stats.
"""
from __future__ import annotations

import random as _random
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADVANCE_TIME_PER_ROOM: float = 4.0   # seconds to move between rooms
BREACH_TIME: float = 15.0            # seconds to breach a locked door
SABOTAGE_RATE: float = 1.0 / 30.0    # progress per second (30s to complete)
MORALE_LOSS_PER_CASUALTY: float = 0.10
MORALE_RETREAT_THRESHOLD: float = 0.20
LEADER_COMBAT_BONUS: float = 1.2
MIN_BOARDING_SIZE: int = 4
MAX_BOARDING_SIZE: int = 8

OBJECTIVES = frozenset({"bridge", "reactor", "medical", "cargo", "sabotage"})

# Map objectives to target rooms on the default interior.
OBJECTIVE_ROOMS: dict[str, str] = {
    "bridge":  "bridge",
    "reactor": "engine_room",
    "medical": "medbay",
    "cargo":   "cargo_hold",
    "sabotage": "shields_control",  # default; can be overridden
}

# Map entry points to likely objectives.
ENTRY_OBJECTIVE_WEIGHTS: dict[str, dict[str, float]] = {
    "cargo_hold":      {"cargo": 0.4, "reactor": 0.3, "sabotage": 0.2, "bridge": 0.1},
    "auxiliary_power":  {"reactor": 0.4, "sabotage": 0.3, "cargo": 0.2, "bridge": 0.1},
    "observation":     {"bridge": 0.5, "medical": 0.2, "sabotage": 0.2, "cargo": 0.1},
    "conn":            {"bridge": 0.5, "medical": 0.2, "sabotage": 0.2, "cargo": 0.1},
}

# Default weights when entry point not in map.
DEFAULT_OBJECTIVE_WEIGHTS: dict[str, float] = {
    "bridge": 0.2, "reactor": 0.3, "medical": 0.1, "cargo": 0.2, "sabotage": 0.2,
}

STATUSES = frozenset({
    "advancing", "engaging", "held", "sabotaging",
    "retreating", "eliminated",
})

# Sabotage consequence constants.
SABOTAGE_BRIDGE_HOLD_TIME: float = 60.0     # seconds to capture bridge
SABOTAGE_REACTOR_HOLD_TIME: float = 30.0    # seconds to sabotage reactor
SABOTAGE_MEDICAL_HOLD_TIME: float = 30.0    # seconds to ransack medical
SABOTAGE_CARGO_HOLD_TIME: float = 45.0      # seconds to loot cargo
SABOTAGE_SYSTEM_HOLD_TIME: float = 30.0     # seconds to plant explosives


# ---------------------------------------------------------------------------
# BoardingParty
# ---------------------------------------------------------------------------


@dataclass
class BoardingParty:
    """An enemy boarding force advancing through the ship interior."""

    id: str
    source: str = "enemy_ship"     # "enemy_ship", "docking", "shuttle"
    faction: str = "hostile"

    entry_point: str = "cargo_hold"
    entry_deck: int = 5

    # Composition
    members: int = 6
    max_members: int = 6
    leader_alive: bool = True

    # Position and objective
    location: str = "cargo_hold"
    objective: str = "bridge"
    objective_room: str = "bridge"
    path: list[str] = field(default_factory=list)
    path_index: int = 0

    # Status
    status: str = "advancing"
    engaged_by: str | None = None        # marine_team_id
    sabotage_progress: float = 0.0       # 0-1.0
    morale: float = 1.0                  # 0-1.0

    # Movement
    advance_progress: float = 0.0        # 0 to ADVANCE_TIME_PER_ROOM
    breach_progress: float = 0.0         # 0 to BREACH_TIME

    # Combat stats
    firepower: float = 0.8              # per-member base damage output
    armour: float = 0.3                 # damage reduction fraction

    @property
    def combat_power(self) -> float:
        """Total combat output for the party."""
        if self.members <= 0:
            return 0.0
        leader_bonus = LEADER_COMBAT_BONUS if self.leader_alive else 1.0
        morale_factor = 0.5 + (self.morale * 0.5)
        return self.members * self.firepower * leader_bonus * morale_factor

    @property
    def is_eliminated(self) -> bool:
        return self.members <= 0 or self.status == "eliminated"

    @property
    def is_at_objective(self) -> bool:
        return self.location == self.objective_room

    @property
    def damage_reduction(self) -> float:
        """Fraction of incoming damage absorbed by armour."""
        return min(self.armour, 0.8)  # cap at 80%

    # ---- Combat ----

    def apply_casualties(self, losses: int) -> int:
        """Remove members. Returns actual losses. Updates morale."""
        actual = min(losses, self.members)
        self.members -= actual
        self.morale = max(0.0, self.morale - actual * MORALE_LOSS_PER_CASUALTY)
        # Leader dies last (first casualty if only 1 left)
        if self.members <= 1 and actual > 0 and self.members == 0:
            self.leader_alive = False
        if self.members <= 0:
            self.status = "eliminated"
            self.leader_alive = False
        return actual

    def check_morale(self) -> bool:
        """Check if party should retreat. Returns True if retreating."""
        if self.morale <= MORALE_RETREAT_THRESHOLD and self.status != "retreating":
            self.status = "retreating"
            return True
        if self.members <= max(1, int(self.max_members * 0.3)):
            self.morale = max(0.0, self.morale - 0.05)
        return False

    # ---- Serialise ----

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "faction": self.faction,
            "entry_point": self.entry_point,
            "entry_deck": self.entry_deck,
            "members": self.members,
            "max_members": self.max_members,
            "leader_alive": self.leader_alive,
            "location": self.location,
            "objective": self.objective,
            "objective_room": self.objective_room,
            "path": list(self.path),
            "path_index": self.path_index,
            "status": self.status,
            "engaged_by": self.engaged_by,
            "sabotage_progress": round(self.sabotage_progress, 3),
            "morale": round(self.morale, 3),
            "advance_progress": round(self.advance_progress, 3),
            "breach_progress": round(self.breach_progress, 3),
            "firepower": round(self.firepower, 3),
            "armour": round(self.armour, 3),
        }

    @classmethod
    def from_dict(cls, data: dict) -> BoardingParty:
        return cls(
            id=data["id"],
            source=data.get("source", "enemy_ship"),
            faction=data.get("faction", "hostile"),
            entry_point=data.get("entry_point", "cargo_hold"),
            entry_deck=data.get("entry_deck", 5),
            members=data.get("members", 6),
            max_members=data.get("max_members", 6),
            leader_alive=data.get("leader_alive", True),
            location=data.get("location", "cargo_hold"),
            objective=data.get("objective", "bridge"),
            objective_room=data.get("objective_room", "bridge"),
            path=data.get("path", []),
            path_index=data.get("path_index", 0),
            status=data.get("status", "advancing"),
            engaged_by=data.get("engaged_by"),
            sabotage_progress=data.get("sabotage_progress", 0.0),
            morale=data.get("morale", 1.0),
            advance_progress=data.get("advance_progress", 0.0),
            breach_progress=data.get("breach_progress", 0.0),
            firepower=data.get("firepower", 0.8),
            armour=data.get("armour", 0.3),
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def select_objective(
    entry_point: str,
    rng: _random.Random | None = None,
) -> str:
    """Choose a boarding objective based on entry point."""
    if rng is None:
        rng = _random.Random()
    weights = ENTRY_OBJECTIVE_WEIGHTS.get(entry_point, DEFAULT_OBJECTIVE_WEIGHTS)
    objectives = list(weights.keys())
    probs = list(weights.values())
    return rng.choices(objectives, weights=probs, k=1)[0]


def generate_boarding_party(
    party_id: str,
    entry_point: str = "cargo_hold",
    difficulty_scale: float = 1.0,
    rng: _random.Random | None = None,
    objective_override: str | None = None,
    interior: object | None = None,
    boarding_config: dict | None = None,
) -> BoardingParty:
    """Create a new boarding party.

    *difficulty_scale* multiplies the member count (1.0 = normal).
    *interior* if provided, calculates the path from entry to objective.
    *boarding_config* overrides objective_rooms and deck mapping (per ship class).
    """
    if rng is None:
        rng = _random.Random()

    # Use class-specific objective rooms if provided.
    obj_rooms = OBJECTIVE_ROOMS
    if boarding_config and "objective_rooms" in boarding_config:
        obj_rooms = boarding_config["objective_rooms"]

    # Determine objective
    objective = objective_override or select_objective(entry_point, rng)
    objective_room = obj_rooms.get(objective, "bridge")

    # Determine size
    base_size = rng.randint(MIN_BOARDING_SIZE, MAX_BOARDING_SIZE)
    size = max(MIN_BOARDING_SIZE, round(base_size * difficulty_scale))

    # Entry deck: use interior room.deck_number if available, else fallback map.
    _fallback_deck_map = {
        "bridge": 1, "conn": 1, "ready_room": 1, "observation": 1,
        "sensor_array": 2, "science_lab": 2, "comms_center": 2, "astrometrics": 2,
        "weapons_bay": 3, "torpedo_room": 3, "shields_control": 3, "combat_info": 3,
        "medbay": 4, "surgery": 4, "quarantine": 4, "pharmacy": 4,
        "main_engineering": 5, "engine_room": 5, "auxiliary_power": 5, "cargo_hold": 5,
    }
    if interior is not None and hasattr(interior, "rooms"):
        room_obj = interior.rooms.get(entry_point)  # type: ignore[union-attr]
        entry_deck = getattr(room_obj, "deck_number", 0) if room_obj else 0
        if entry_deck == 0:
            entry_deck = _fallback_deck_map.get(entry_point, 5)
    else:
        entry_deck = _fallback_deck_map.get(entry_point, 5)

    # Calculate path if interior available
    path: list[str] = []
    if interior is not None and hasattr(interior, "find_path"):
        full_path = interior.find_path(entry_point, objective_room, ignore_sealed=True)
        if full_path:
            path = full_path

    party = BoardingParty(
        id=party_id,
        entry_point=entry_point,
        entry_deck=entry_deck,
        members=size,
        max_members=size,
        location=entry_point,
        objective=objective,
        objective_room=objective_room,
        path=path,
        path_index=0,
    )
    return party
