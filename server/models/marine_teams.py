"""
Marine Team Model.

MarineTeam represents a squad of shipboard marines that defend against
boarding parties, escort repair teams, and patrol the ship interior.

Teams are generated from the crew roster at game start based on ship class.
Each team has a leader, position on the interior map, and tracks combat
stats like effectiveness, suppression, and ammo.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRAVEL_TIME_PER_ROOM: float = 2.0      # seconds to move between rooms
PATROL_PAUSE_PER_ROOM: float = 5.0     # seconds to hold at each patrol waypoint
AMMO_PER_COMBAT_TICK: float = 2.0      # ammo consumed per tick of combat
AMMO_REARM_RATE: float = 5.0           # ammo recovered per second at armoury
SUPPRESSION_DECAY: float = 0.05        # per tick when not under fire
SUPPRESSION_GAIN: float = 0.10         # per tick under heavy fire
DISENGAGE_DAMAGE_MULT: float = 1.5     # extra damage taken while disengaging

# Marine team allocation by ship class.
# (team_count, team_size)
SHIP_CLASS_MARINES: dict[str, tuple[int, int]] = {
    "scout":        (1, 3),
    "corvette":     (1, 4),
    "frigate":      (2, 4),
    "cruiser":      (2, 5),
    "battleship":   (3, 6),
    "medical_ship": (1, 4),
    "carrier":      (3, 5),
}

DEFAULT_MARINES: tuple[int, int] = (2, 4)  # fallback

TEAM_NAMES: list[dict[str, str]] = [
    {"id": "mt_alpha",   "name": "Alpha Squad",   "callsign": "ALPHA"},
    {"id": "mt_bravo",   "name": "Bravo Squad",   "callsign": "BRAVO"},
    {"id": "mt_charlie", "name": "Charlie Squad",  "callsign": "CHARLIE"},
]

# Starting positions for teams: Alpha at bridge access, Bravo at engineering,
# Charlie (if exists) at combat deck.
DEFAULT_POSITIONS: list[str] = ["conn", "engine_room", "combat_info"]

STATUSES = frozenset({
    "stationed", "patrolling", "responding", "engaging",
    "escorting", "incapacitated",
})


# ---------------------------------------------------------------------------
# MarineTeam
# ---------------------------------------------------------------------------


@dataclass
class MarineTeam:
    """A squad of shipboard marines."""

    id: str
    name: str
    callsign: str
    members: list[str] = field(default_factory=list)  # crew_member_ids
    leader: str = ""                                    # crew_member_id

    size: int = 4
    max_size: int = 4

    # Position and movement
    location: str = "conn"
    destination: str | None = None
    travel_progress: float = 0.0
    patrol_route: list[str] = field(default_factory=list)
    patrol_index: int = 0

    # Status
    status: str = "stationed"
    engagement: str | None = None      # boarding_party_id
    escort_target: str | None = None   # repair_team_id

    # Combat stats
    combat_effectiveness: float = 1.0  # 0-1.0 based on member health
    suppression_level: float = 0.0     # 0-1.0
    ammo: float = 100.0               # 0-100%

    @property
    def firepower(self) -> float:
        """Combat output considering size, health, ammo, suppression."""
        if self.size <= 0 or self.max_size <= 0:
            return 0.0
        base = self.size / self.max_size
        ammo_factor = min(self.ammo / 20.0, 1.0)
        suppression_factor = 1.0 - self.suppression_level * 0.5
        return base * self.combat_effectiveness * suppression_factor * ammo_factor

    @property
    def is_incapacitated(self) -> bool:
        return self.size <= 0 or self.status == "incapacitated"

    @property
    def is_available(self) -> bool:
        """Team can accept new orders."""
        return self.status in ("stationed", "patrolling") and self.size > 0

    # ---- Combat ----

    def apply_casualties(self, losses: int) -> int:
        """Remove members from the team. Returns actual losses applied."""
        actual = min(losses, self.size)
        self.size -= actual
        # Remove member IDs from back of list
        for _ in range(min(actual, len(self.members))):
            self.members.pop()
        # Update effectiveness
        if self.max_size > 0:
            self.combat_effectiveness = self.size / self.max_size
        if self.size <= 0:
            self.status = "incapacitated"
        return actual

    def consume_ammo(self, amount: float = AMMO_PER_COMBAT_TICK) -> None:
        """Reduce ammo by the given amount."""
        self.ammo = max(0.0, self.ammo - amount)

    def rearm(self, dt: float) -> None:
        """Restore ammo (team must be at armoury)."""
        self.ammo = min(100.0, self.ammo + AMMO_REARM_RATE * dt)

    def suppress(self, amount: float = SUPPRESSION_GAIN) -> None:
        """Increase suppression level."""
        self.suppression_level = min(1.0, self.suppression_level + amount)

    def decay_suppression(self, amount: float = SUPPRESSION_DECAY) -> None:
        """Reduce suppression (called when not under fire)."""
        self.suppression_level = max(0.0, self.suppression_level - amount)

    # ---- Orders ----

    def order_respond(self, destination: str) -> None:
        """Send team to a specific room."""
        self.destination = destination
        self.status = "responding"
        self.travel_progress = 0.0
        self.engagement = None

    def order_patrol(self, route: list[str]) -> None:
        """Set a patrol route."""
        self.patrol_route = list(route)
        self.patrol_index = 0
        self.status = "patrolling"
        self.destination = route[0] if route else None
        self.travel_progress = 0.0

    def order_escort(self, repair_team_id: str) -> None:
        """Assign to escort a repair team."""
        self.escort_target = repair_team_id
        self.status = "escorting"

    def order_station(self) -> None:
        """Hold current position."""
        self.status = "stationed"
        self.destination = None
        self.travel_progress = 0.0
        self.engagement = None
        self.escort_target = None

    def engage(self, boarding_party_id: str) -> None:
        """Enter combat with a boarding party."""
        self.status = "engaging"
        self.engagement = boarding_party_id
        self.destination = None

    def disengage(self) -> None:
        """Break contact and retreat."""
        self.status = "responding"  # will be given a retreat destination
        self.engagement = None

    # ---- Serialise ----

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "callsign": self.callsign,
            "members": list(self.members),
            "leader": self.leader,
            "size": self.size,
            "max_size": self.max_size,
            "location": self.location,
            "destination": self.destination,
            "travel_progress": round(self.travel_progress, 3),
            "patrol_route": list(self.patrol_route),
            "patrol_index": self.patrol_index,
            "status": self.status,
            "engagement": self.engagement,
            "escort_target": self.escort_target,
            "combat_effectiveness": round(self.combat_effectiveness, 3),
            "suppression_level": round(self.suppression_level, 3),
            "ammo": round(self.ammo, 2),
        }

    @classmethod
    def from_dict(cls, data: dict) -> MarineTeam:
        return cls(
            id=data["id"],
            name=data["name"],
            callsign=data["callsign"],
            members=data.get("members", []),
            leader=data.get("leader", ""),
            size=data.get("size", 4),
            max_size=data.get("max_size", 4),
            location=data.get("location", "conn"),
            destination=data.get("destination"),
            travel_progress=data.get("travel_progress", 0.0),
            patrol_route=data.get("patrol_route", []),
            patrol_index=data.get("patrol_index", 0),
            status=data.get("status", "stationed"),
            engagement=data.get("engagement"),
            escort_target=data.get("escort_target"),
            combat_effectiveness=data.get("combat_effectiveness", 1.0),
            suppression_level=data.get("suppression_level", 0.0),
            ammo=data.get("ammo", 100.0),
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def generate_marine_teams(
    ship_class: str = "frigate",
    crew_member_ids: list[str] | None = None,
) -> list[MarineTeam]:
    """Create marine teams based on ship class.

    If crew_member_ids are provided, members are assigned to teams.
    Otherwise, teams are created with generic placeholder IDs.
    """
    team_count, team_size = SHIP_CLASS_MARINES.get(ship_class, DEFAULT_MARINES)
    teams: list[MarineTeam] = []

    available_crew = list(crew_member_ids) if crew_member_ids else []

    for i in range(team_count):
        if i >= len(TEAM_NAMES):
            break  # max 3 teams

        meta = TEAM_NAMES[i]
        position = DEFAULT_POSITIONS[i] if i < len(DEFAULT_POSITIONS) else "conn"

        # Assign crew members
        members: list[str] = []
        for _ in range(team_size):
            if available_crew:
                members.append(available_crew.pop(0))
            else:
                members.append(f"{meta['id']}_marine_{len(members)}")

        leader = members[0] if members else ""

        teams.append(MarineTeam(
            id=meta["id"],
            name=meta["name"],
            callsign=meta["callsign"],
            members=members,
            leader=leader,
            size=len(members),
            max_size=team_size,
            location=position,
        ))

    return teams
