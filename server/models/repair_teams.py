"""
Repair Team Model.

Named repair teams that physically travel through the ship interior to
repair damaged systems. Teams are formed from crew members, traverse
rooms with time cost, and face hazards in fire-damaged areas. Security
escorts can protect teams from hazard casualties.

Travel uses the ShipInterior BFS graph. Each room transition takes
TRAVEL_TIME_PER_ROOM seconds. Fire rooms have a casualty chance per
entry. Repair rate scales with team size.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from server.models.interior import Room, ShipInterior

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_ROOM: str = "main_engineering"

TRAVEL_TIME_PER_ROOM: float = 3.0      # seconds to traverse one room
REPAIR_RATE_PER_MEMBER: float = 1.5     # HP per second per team member
FIRE_CASUALTY_CHANCE: float = 0.15      # chance per fire-room entry (no escort)
DEFAULT_TEAM_SIZE: int = 3

TEAM_NAMES: tuple[str, ...] = ("Alpha", "Beta", "Gamma", "Delta")

# Map each ship system to the room where it can be physically repaired.
SYSTEM_ROOMS: dict[str, str] = {
    "engines":       "engine_room",
    "beams":         "weapons_bay",
    "torpedoes":     "torpedo_room",
    "shields":       "shields_control",
    "sensors":       "sensor_array",
    "manoeuvring":   "bridge",
    "flight_deck":   "cargo_hold",
    "ecm_suite":     "comms_center",
    "point_defence": "combat_info",
}


# ---------------------------------------------------------------------------
# RepairTeam
# ---------------------------------------------------------------------------


@dataclass
class RepairTeam:
    """A single repair team that travels through the ship and fixes systems."""

    id: str
    name: str
    member_ids: list[str] = field(default_factory=list)
    size: int = DEFAULT_TEAM_SIZE
    room_id: str = BASE_ROOM
    base_room: str = BASE_ROOM

    status: str = "idle"  # idle | travelling | repairing | returning

    target_system: str | None = None
    target_room_id: str | None = None
    path: list[str] = field(default_factory=list)
    travel_progress: float = 0.0
    repair_progress: float = 0.0

    escort_squad_id: str | None = None

    @property
    def repair_rate(self) -> float:
        """Current repair rate in HP per second."""
        return REPAIR_RATE_PER_MEMBER * self.size

    @property
    def is_available(self) -> bool:
        return self.status == "idle" and self.size > 0

    @property
    def is_eliminated(self) -> bool:
        return self.size <= 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "member_ids": list(self.member_ids),
            "size": self.size,
            "room_id": self.room_id,
            "base_room": self.base_room,
            "status": self.status,
            "target_system": self.target_system,
            "target_room_id": self.target_room_id,
            "path": list(self.path),
            "travel_progress": round(self.travel_progress, 2),
            "repair_progress": round(self.repair_progress, 2),
            "escort_squad_id": self.escort_squad_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RepairTeam:
        return cls(
            id=data["id"],
            name=data["name"],
            member_ids=data.get("member_ids", []),
            size=data.get("size", DEFAULT_TEAM_SIZE),
            room_id=data.get("room_id", BASE_ROOM),
            base_room=data.get("base_room", BASE_ROOM),
            status=data.get("status", "idle"),
            target_system=data.get("target_system"),
            target_room_id=data.get("target_room_id"),
            path=data.get("path", []),
            travel_progress=data.get("travel_progress", 0.0),
            repair_progress=data.get("repair_progress", 0.0),
            escort_squad_id=data.get("escort_squad_id"),
        )


# ---------------------------------------------------------------------------
# RepairTeamManager
# ---------------------------------------------------------------------------


@dataclass
class RepairTeamManager:
    """Manages all repair teams, dispatch, travel, repair, and hazard events."""

    teams: dict[str, RepairTeam] = field(default_factory=dict)
    order_queue: list[dict] = field(default_factory=list)
    _next_order_id: int = 0
    _system_rooms: dict[str, str] | None = field(default=None, repr=False)

    # ---- Factory ----

    @classmethod
    def create_teams(cls, crew_member_ids: list[str],
                     team_size: int = DEFAULT_TEAM_SIZE,
                     base_room: str = BASE_ROOM,
                     system_rooms: dict[str, str] | None = None,
                     ) -> RepairTeamManager:
        """Form repair teams from a list of crew member IDs.

        Creates as many teams of team_size as possible (up to 4).
        Extra crew are distributed round-robin to existing teams.

        *base_room* overrides the default starting/return room for teams.
        *system_rooms* overrides the system->room mapping for dispatch.
        """
        mgr = cls(_system_rooms=system_rooms)
        if not crew_member_ids:
            return mgr

        num_teams = max(1, len(crew_member_ids) // team_size)
        num_teams = min(num_teams, len(TEAM_NAMES))

        for i in range(num_teams):
            start = i * team_size
            end = start + team_size
            members = crew_member_ids[start:end]
            if not members:
                break
            team = RepairTeam(
                id=f"team_{TEAM_NAMES[i].lower()}",
                name=f"{TEAM_NAMES[i]} Team",
                member_ids=list(members),
                size=len(members),
                room_id=base_room,
                base_room=base_room,
            )
            mgr.teams[team.id] = team

        # Distribute remaining crew round-robin
        remaining = crew_member_ids[num_teams * team_size:]
        team_list = list(mgr.teams.values())
        for j, cid in enumerate(remaining):
            team = team_list[j % len(team_list)]
            team.member_ids.append(cid)
            team.size += 1

        return mgr

    # ---- Dispatch / Recall ----

    def dispatch(self, team_id: str, system: str,
                 interior: ShipInterior) -> bool:
        """Send a team to repair a system.

        Calculates the BFS path from the team's current room to the
        system's room. Returns False if team/system invalid or no path.
        """
        team = self.teams.get(team_id)
        if team is None or team.is_eliminated:
            return False

        target_room = (self._system_rooms or SYSTEM_ROOMS).get(system)
        if target_room is None or target_room not in interior.rooms:
            return False

        # Calculate path
        if team.room_id == target_room:
            path: list[str] = []
        else:
            full_path = interior.find_path(team.room_id, target_room)
            if not full_path:
                return False
            path = full_path[1:]  # exclude current room

        # Clear any current assignment
        self._clear_team_assignment(team)

        team.target_system = system
        team.target_room_id = target_room
        team.path = path
        team.travel_progress = 0.0
        team.repair_progress = 0.0

        if not path:
            team.status = "repairing"
        else:
            team.status = "travelling"

        return True

    def dispatch_to_room(self, team_id: str, room_id: str,
                         interior: ShipInterior) -> dict:
        """Send a team to a specific room (e.g. breach repair).

        Returns {'ok': True} or {'ok': False, 'reason': ...}.
        Sets target_system = '__breach__' so _tick_repair emits breach event.
        """
        team = self.teams.get(team_id)
        if team is None or team.is_eliminated:
            return {"ok": False, "reason": "Team not found or eliminated."}
        if not team.is_available and team.status != "idle":
            return {"ok": False, "reason": "Team is busy."}
        if room_id not in interior.rooms:
            return {"ok": False, "reason": "Room not found."}

        # Calculate path
        if team.room_id == room_id:
            path: list[str] = []
        else:
            full_path = interior.find_path(team.room_id, room_id)
            if not full_path:
                return {"ok": False, "reason": "No path to room."}
            path = full_path[1:]

        self._clear_team_assignment(team)
        team.target_system = "__breach__"
        team.target_room_id = room_id
        team.path = path
        team.travel_progress = 0.0
        team.repair_progress = 0.0

        if not path:
            team.status = "repairing"
        else:
            team.status = "travelling"

        return {"ok": True}

    def recall(self, team_id: str, interior: ShipInterior) -> bool:
        """Recall a team back to its base room.

        Returns False if team not found or already idle at base.
        """
        team = self.teams.get(team_id)
        if team is None or team.is_eliminated:
            return False
        if team.status == "idle" and team.room_id == team.base_room:
            return False

        self._clear_team_assignment(team)

        if team.room_id == team.base_room:
            team.status = "idle"
            team.path = []
            return True

        full_path = interior.find_path(team.room_id, team.base_room)
        if not full_path:
            team.status = "idle"
            team.path = []
            return True

        team.path = full_path[1:]
        team.status = "returning"
        team.travel_progress = 0.0
        team.target_system = None
        team.target_room_id = team.base_room
        return True

    # ---- Escort ----

    def request_escort(self, team_id: str, squad_id: str) -> bool:
        """Assign a security escort to a repair team."""
        team = self.teams.get(team_id)
        if team is None:
            return False
        team.escort_squad_id = squad_id
        return True

    def clear_escort(self, team_id: str) -> None:
        """Remove the security escort from a team."""
        team = self.teams.get(team_id)
        if team is not None:
            team.escort_squad_id = None

    # ---- Order Queue ----

    def add_order(self, system: str, priority: int = 1) -> str:
        """Queue a repair order. Returns the order ID.

        Idle teams auto-assign from the queue during tick().
        Higher priority orders are assigned first.
        """
        self._next_order_id += 1
        order_id = f"order_{self._next_order_id}"
        self.order_queue.append({
            "id": order_id,
            "system": system,
            "priority": priority,
        })
        self.order_queue.sort(key=lambda o: -o["priority"])
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a queued order. Returns True if found and removed."""
        for i, order in enumerate(self.order_queue):
            if order["id"] == order_id:
                self.order_queue.pop(i)
                return True
        return False

    # ---- Tick ----

    def tick(self, dt: float, interior: ShipInterior,
             rng: random.Random | None = None) -> list[dict]:
        """Advance all teams by one tick. Returns a list of events.

        Event types:
            team_moved     — team advanced to a new room
            team_arrived   — team reached its target system room
            repair_hp      — repair work applied this tick (hp amount)
            team_returned  — team returned to base
            casualty       — team member lost to hazard
            team_eliminated — team lost all members
            entered_hazard — team entered a fire or damaged room
        """
        if rng is None:
            rng = random.Random()

        events: list[dict] = []

        for team in list(self.teams.values()):
            if team.is_eliminated:
                continue
            if team.status in ("travelling", "returning"):
                events.extend(self._tick_travel(team, dt, interior, rng))
            elif team.status == "repairing":
                events.extend(self._tick_repair(team, dt))

        # Auto-assign queued orders to idle teams
        self._process_order_queue(interior)

        return events

    # ---- Internal travel ----

    def _tick_travel(self, team: RepairTeam, dt: float,
                     interior: ShipInterior,
                     rng: random.Random) -> list[dict]:
        events: list[dict] = []

        if not team.path:
            events.extend(self._arrive(team))
            return events

        team.travel_progress += dt

        while team.travel_progress >= TRAVEL_TIME_PER_ROOM and team.path:
            next_room_id = team.path[0]
            room = interior.rooms.get(next_room_id)

            # Block if room became impassable since dispatch
            if room is None or room.door_sealed or room.state == "decompressed":
                team.travel_progress = TRAVEL_TIME_PER_ROOM
                break

            team.travel_progress -= TRAVEL_TIME_PER_ROOM
            team.path.pop(0)
            from_room = team.room_id
            team.room_id = next_room_id

            events.append({
                "type": "team_moved",
                "team_id": team.id,
                "room_id": next_room_id,
                "from_room": from_room,
            })

            # Hazard check
            events.extend(self._check_hazard(team, room, rng))
            if team.is_eliminated:
                events.append({"type": "team_eliminated", "team_id": team.id})
                return events

        # Check arrival after traversal
        if not team.path:
            events.extend(self._arrive(team))

        return events

    def _arrive(self, team: RepairTeam) -> list[dict]:
        """Handle arrival at destination."""
        events: list[dict] = []
        if team.status == "travelling":
            team.status = "repairing"
            events.append({
                "type": "team_arrived",
                "team_id": team.id,
                "system": team.target_system,
                "room_id": team.room_id,
            })
        elif team.status == "returning":
            team.status = "idle"
            team.target_system = None
            team.target_room_id = None
            events.append({
                "type": "team_returned",
                "team_id": team.id,
                "room_id": team.room_id,
            })
        return events

    # ---- Internal repair ----

    def _tick_repair(self, team: RepairTeam, dt: float) -> list[dict]:
        if team.target_system is None:
            return []

        hp = team.repair_rate * dt
        team.repair_progress += hp

        # C.3.2: Breach repair — emit special event when repair completes.
        if team.target_system == "__breach__":
            if team.repair_progress >= 8.0:  # same duration as DCT_REPAIR_DURATION
                room_id = team.target_room_id
                self._clear_team_assignment(team)
                team.status = "idle"
                return [{
                    "type": "breach_repaired",
                    "team_id": team.id,
                    "room_id": room_id,
                }]
            return []

        return [{
            "type": "repair_hp",
            "team_id": team.id,
            "system": team.target_system,
            "hp": hp,
        }]

    # ---- Internal hazard ----

    def _check_hazard(self, team: RepairTeam, room: Room,
                      rng: random.Random) -> list[dict]:
        events: list[dict] = []

        if room.state == "fire":
            events.append({
                "type": "entered_hazard",
                "team_id": team.id,
                "room_id": room.id,
                "hazard": "fire",
            })
            # Escort protects from casualties
            if team.escort_squad_id is None:
                if rng.random() < FIRE_CASUALTY_CHANCE:
                    events.extend(self._apply_casualty(team, room.id, "fire"))
        elif room.state == "damaged":
            events.append({
                "type": "entered_hazard",
                "team_id": team.id,
                "room_id": room.id,
                "hazard": "damaged",
            })

        return events

    def _apply_casualty(self, team: RepairTeam, room_id: str,
                        cause: str) -> list[dict]:
        member_id = team.member_ids.pop() if team.member_ids else None
        team.size = max(0, team.size - 1)
        return [{
            "type": "casualty",
            "team_id": team.id,
            "member_id": member_id,
            "room_id": room_id,
            "cause": cause,
        }]

    # ---- Internal order queue ----

    def _process_order_queue(self, interior: ShipInterior) -> None:
        idle_teams = [t for t in self.teams.values() if t.is_available]
        assigned: list[int] = []

        for i, order in enumerate(self.order_queue):
            if not idle_teams:
                break
            team = idle_teams[0]
            if self.dispatch(team.id, order["system"], interior):
                idle_teams.pop(0)
                assigned.append(i)

        for i in reversed(assigned):
            self.order_queue.pop(i)

    def _clear_team_assignment(self, team: RepairTeam) -> None:
        team.target_system = None
        team.target_room_id = None
        team.path = []
        team.travel_progress = 0.0
        team.repair_progress = 0.0

    # ---- Query ----

    def get_team_state(self) -> list[dict]:
        """Broadcast-ready state for all teams."""
        return [t.to_dict() for t in self.teams.values()]

    # ---- Serialisation ----

    def serialise(self) -> dict:
        return {
            "teams": {tid: t.to_dict() for tid, t in self.teams.items()},
            "order_queue": list(self.order_queue),
            "next_order_id": self._next_order_id,
        }

    @classmethod
    def deserialise(cls, data: dict) -> RepairTeamManager:
        mgr = cls()
        mgr._next_order_id = data.get("next_order_id", 0)
        mgr.order_queue = list(data.get("order_queue", []))
        for tid, tdata in data.get("teams", {}).items():
            mgr.teams[tid] = RepairTeam.from_dict(tdata)
        return mgr
