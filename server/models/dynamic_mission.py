"""Dynamic mission data models — v0.06.4 missions Part 2.

DynamicMission, MissionObjective, and MissionRewards dataclasses for
missions generated from Comms intelligence events.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MISSION_TYPES = (
    "rescue", "escort", "investigate", "trade", "diplomatic",
    "intercept", "patrol", "salvage",
)

MISSION_STATUSES = (
    "offered", "accepted", "active", "completed", "failed",
    "declined", "expired",
)

OBJECTIVE_TYPES = (
    "navigate_to", "destroy", "scan", "dock", "negotiate",
    "survive", "escort_to", "retrieve", "deliver",
)

DIFFICULTY_ESTIMATES = ("easy", "moderate", "hard", "dangerous", "unknown")

# Default deadlines (seconds)
DEFAULT_ACCEPT_DEADLINE: float = 60.0
DEFAULT_COMPLETION_DEADLINE: float = 300.0

# Navigate-to completion radius (world units)
NAVIGATE_COMPLETION_RADIUS: float = 5000.0

# Maximum simultaneous active missions
MAX_ACTIVE_MISSIONS: int = 3


# ---------------------------------------------------------------------------
# MissionObjective
# ---------------------------------------------------------------------------

@dataclass
class MissionObjective:
    """A single objective within a dynamic mission."""

    id: str
    description: str                  # "Reach ISS Valiant's position"
    objective_type: str               # One of OBJECTIVE_TYPES
    target_id: str | None = None      # Entity to interact with
    target_position: tuple[float, float] | None = None
    completed: bool = False
    optional: bool = False            # Optional objectives are bonus
    order: int = 1                    # Sequence (1 = first)
    target_tick: int | None = None    # For "survive" type — tick to reach

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "objective_type": self.objective_type,
            "target_id": self.target_id,
            "target_position": list(self.target_position) if self.target_position else None,
            "completed": self.completed,
            "optional": self.optional,
            "order": self.order,
            "target_tick": self.target_tick,
        }

    @staticmethod
    def from_dict(d: dict) -> MissionObjective:
        tp = d.get("target_position")
        return MissionObjective(
            id=d["id"],
            description=d.get("description", ""),
            objective_type=d.get("objective_type", "navigate_to"),
            target_id=d.get("target_id"),
            target_position=(float(tp[0]), float(tp[1])) if tp else None,
            completed=d.get("completed", False),
            optional=d.get("optional", False),
            order=d.get("order", 1),
            target_tick=d.get("target_tick"),
        )


# ---------------------------------------------------------------------------
# MissionRewards
# ---------------------------------------------------------------------------

@dataclass
class MissionRewards:
    """Rewards granted on mission completion."""

    faction_standing: dict[str, float] = field(default_factory=dict)
    supplies: dict[str, int] = field(default_factory=dict)
    intel: list[str] = field(default_factory=list)
    crew: int = 0                     # Replacement crew gained
    reputation: int = 0               # General reputation score
    description: str = ""             # Human-readable summary

    def to_dict(self) -> dict:
        return {
            "faction_standing": dict(self.faction_standing),
            "supplies": dict(self.supplies),
            "intel": list(self.intel),
            "crew": self.crew,
            "reputation": self.reputation,
            "description": self.description,
        }

    @staticmethod
    def from_dict(d: dict) -> MissionRewards:
        return MissionRewards(
            faction_standing=d.get("faction_standing", {}),
            supplies=d.get("supplies", {}),
            intel=d.get("intel", []),
            crew=d.get("crew", 0),
            reputation=d.get("reputation", 0),
            description=d.get("description", ""),
        )


# ---------------------------------------------------------------------------
# DynamicMission
# ---------------------------------------------------------------------------

@dataclass
class DynamicMission:
    """A mission generated from a Comms intelligence event."""

    id: str
    source_signal_id: str             # Signal that spawned this
    source_contact_id: str            # CommsContact associated

    # Description
    title: str                        # "Rescue ISS Valiant"
    briefing: str                     # Full situation description
    mission_type: str                 # One of MISSION_TYPES

    # Objectives
    objectives: list[MissionObjective] = field(default_factory=list)

    # Location
    waypoint: tuple[float, float] = (0.0, 0.0)
    waypoint_name: str = ""

    # Timing
    offered_tick: int = 0
    deadline_tick: int | None = None  # Accept before this or it expires
    completion_deadline_tick: int | None = None  # Complete before this
    accept_deadline: float | None = None   # Seconds remaining to accept
    completion_deadline: float | None = None  # Seconds remaining to complete

    # Rewards and consequences
    rewards: MissionRewards = field(default_factory=MissionRewards)
    decline_consequences: dict = field(default_factory=dict)
    failure_consequences: dict = field(default_factory=dict)

    # Status
    status: str = "offered"           # One of MISSION_STATUSES

    # Difficulty assessment
    estimated_difficulty: str = "unknown"
    comms_assessment: str = ""        # Comms officer's analysis

    # Trap flag (server-side — never sent to client)
    _is_trap: bool = field(default=False, repr=False)

    @property
    def is_active(self) -> bool:
        return self.status in ("accepted", "active")

    @property
    def required_objectives(self) -> list[MissionObjective]:
        return [o for o in self.objectives if not o.optional]

    @property
    def all_required_complete(self) -> bool:
        return all(o.completed for o in self.required_objectives)

    def to_dict(self) -> dict:
        """Serialise for broadcast or save."""
        return {
            "id": self.id,
            "source_signal_id": self.source_signal_id,
            "source_contact_id": self.source_contact_id,
            "title": self.title,
            "briefing": self.briefing,
            "mission_type": self.mission_type,
            "objectives": [o.to_dict() for o in self.objectives],
            "waypoint": list(self.waypoint),
            "waypoint_name": self.waypoint_name,
            "offered_tick": self.offered_tick,
            "deadline_tick": self.deadline_tick,
            "completion_deadline_tick": self.completion_deadline_tick,
            "accept_deadline": (
                round(self.accept_deadline, 1)
                if self.accept_deadline is not None else None
            ),
            "completion_deadline": (
                round(self.completion_deadline, 1)
                if self.completion_deadline is not None else None
            ),
            "rewards": self.rewards.to_dict(),
            "decline_consequences": self.decline_consequences,
            "failure_consequences": self.failure_consequences,
            "status": self.status,
            "estimated_difficulty": self.estimated_difficulty,
            "comms_assessment": self.comms_assessment,
        }

    @staticmethod
    def from_dict(d: dict) -> DynamicMission:
        wp = d.get("waypoint", [0.0, 0.0])
        return DynamicMission(
            id=d["id"],
            source_signal_id=d.get("source_signal_id", ""),
            source_contact_id=d.get("source_contact_id", ""),
            title=d.get("title", "Unknown Mission"),
            briefing=d.get("briefing", ""),
            mission_type=d.get("mission_type", "rescue"),
            objectives=[
                MissionObjective.from_dict(o)
                for o in d.get("objectives", [])
            ],
            waypoint=(float(wp[0]), float(wp[1])),
            waypoint_name=d.get("waypoint_name", ""),
            offered_tick=d.get("offered_tick", 0),
            deadline_tick=d.get("deadline_tick"),
            completion_deadline_tick=d.get("completion_deadline_tick"),
            accept_deadline=d.get("accept_deadline"),
            completion_deadline=d.get("completion_deadline"),
            rewards=MissionRewards.from_dict(d.get("rewards", {})),
            decline_consequences=d.get("decline_consequences", {}),
            failure_consequences=d.get("failure_consequences", {}),
            status=d.get("status", "offered"),
            estimated_difficulty=d.get("estimated_difficulty", "unknown"),
            comms_assessment=d.get("comms_assessment", ""),
            _is_trap=d.get("_is_trap", False),
        )


# ---------------------------------------------------------------------------
# Mission templates — generate missions from signal/contact data
# ---------------------------------------------------------------------------

def generate_rescue_mission(
    mission_id: str,
    signal_id: str,
    contact_id: str,
    vessel_name: str,
    position: tuple[float, float],
    faction: str,
    tick: int,
    is_trap: bool = False,
    comms_assessment: str = "",
) -> DynamicMission:
    """Generate a rescue mission from a distress signal."""
    x, y = position
    return DynamicMission(
        id=mission_id,
        source_signal_id=signal_id,
        source_contact_id=contact_id,
        title=f"Rescue {vessel_name}",
        briefing=(
            f"{vessel_name} is under attack at coordinates "
            f"{int(x)}, {int(y)}. Requesting immediate assistance."
        ),
        mission_type="rescue",
        objectives=[
            MissionObjective(
                id=f"{mission_id}_nav",
                description=f"Navigate to {vessel_name}'s position",
                objective_type="navigate_to",
                target_position=position,
                order=1,
            ),
            MissionObjective(
                id=f"{mission_id}_clear",
                description="Neutralise hostile vessels",
                objective_type="destroy",
                target_id=f"{mission_id}_hostiles",
                order=2,
            ),
            MissionObjective(
                id=f"{mission_id}_dock",
                description=f"Dock with {vessel_name} for medical transfer",
                objective_type="dock",
                target_id=contact_id,
                optional=True,
                order=3,
            ),
        ],
        waypoint=position,
        waypoint_name=vessel_name,
        offered_tick=tick,
        deadline_tick=tick + 600,  # 60s accept deadline at 10Hz
        completion_deadline_tick=tick + 3000,  # 5min completion
        accept_deadline=DEFAULT_ACCEPT_DEADLINE,
        completion_deadline=DEFAULT_COMPLETION_DEADLINE,
        rewards=MissionRewards(
            faction_standing={faction: 15.0} if faction != "unknown" else {},
            crew=2,
            intel=["Sector chart data"],
            reputation=10,
            description=(
                f"Faction standing +15, 2 replacement crew, sector chart data"
            ),
        ),
        decline_consequences={
            "faction_standing": {faction: -5.0} if faction != "unknown" else {},
            "description": (
                f"{vessel_name} destroyed. "
                f"{'Standing with ' + faction + ' -5.' if faction != 'unknown' else ''} "
                f"Nearby factions note our non-response."
            ),
        },
        failure_consequences={
            "faction_standing": {faction: -2.0} if faction != "unknown" else {},
            "description": "Arrived too late. Slight standing loss (they tried).",
        },
        estimated_difficulty="moderate",
        comms_assessment=comms_assessment,
        _is_trap=is_trap,
    )


def generate_escort_mission(
    mission_id: str,
    signal_id: str,
    contact_id: str,
    vessel_name: str,
    position: tuple[float, float],
    faction: str,
    tick: int,
    comms_assessment: str = "",
) -> DynamicMission:
    """Generate an escort mission from a civilian hail."""
    return DynamicMission(
        id=mission_id,
        source_signal_id=signal_id,
        source_contact_id=contact_id,
        title=f"Escort {vessel_name}",
        briefing=(
            f"The civilian vessel {vessel_name} is requesting escort "
            f"through a hazardous area. They report hostile activity nearby."
        ),
        mission_type="escort",
        objectives=[
            MissionObjective(
                id=f"{mission_id}_nav",
                description=f"Rendezvous with {vessel_name}",
                objective_type="navigate_to",
                target_position=position,
                order=1,
            ),
            MissionObjective(
                id=f"{mission_id}_escort",
                description=f"Escort {vessel_name} through the area",
                objective_type="survive",
                target_tick=tick + 1800,  # 3 min
                order=2,
            ),
            MissionObjective(
                id=f"{mission_id}_defend",
                description="Defend against hostile contacts",
                objective_type="destroy",
                target_id=f"{mission_id}_hostiles",
                order=3,
            ),
        ],
        waypoint=position,
        waypoint_name=vessel_name,
        offered_tick=tick,
        accept_deadline=90.0,
        completion_deadline=360.0,
        rewards=MissionRewards(
            faction_standing={faction: 8.0} if faction != "unknown" else {"civilian": 8.0},
            supplies={"torpedoes": 4},
            reputation=5,
            description="Faction standing +8, 4 standard torpedoes",
        ),
        decline_consequences={
            "description": "No penalty — civilian request, not obligation.",
        },
        failure_consequences={
            "faction_standing": {faction: -3.0} if faction != "unknown" else {},
            "description": f"{vessel_name} destroyed. Standing loss.",
        },
        estimated_difficulty="moderate",
        comms_assessment=comms_assessment,
    )


def generate_investigation_mission(
    mission_id: str,
    signal_id: str,
    contact_id: str,
    position: tuple[float, float],
    tick: int,
    comms_assessment: str = "",
) -> DynamicMission:
    """Generate an investigation mission from an anomalous signal."""
    x, y = position
    return DynamicMission(
        id=mission_id,
        source_signal_id=signal_id,
        source_contact_id=contact_id,
        title="Investigate Unknown Signal Source",
        briefing=(
            f"Comms has detected an unusual signal at coordinates "
            f"{int(x)}, {int(y)}. The signal doesn't match any known "
            f"communication protocol. Source is stationary."
        ),
        mission_type="investigate",
        objectives=[
            MissionObjective(
                id=f"{mission_id}_nav",
                description="Navigate to signal source",
                objective_type="navigate_to",
                target_position=position,
                order=1,
            ),
            MissionObjective(
                id=f"{mission_id}_scan",
                description="Scan the source",
                objective_type="scan",
                target_id=contact_id,
                order=2,
            ),
        ],
        waypoint=position,
        waypoint_name="Unknown Signal Source",
        offered_tick=tick,
        accept_deadline=120.0,
        rewards=MissionRewards(
            intel=["Unknown — could be valuable tech or nothing"],
            reputation=5,
            description="Unknown rewards — mystery mission",
        ),
        decline_consequences={
            "description": "No penalty — exploration opportunity missed.",
        },
        failure_consequences={
            "description": "Unable to reach or scan the source.",
        },
        estimated_difficulty="unknown",
        comms_assessment=comms_assessment,
    )


def generate_intercept_mission(
    mission_id: str,
    signal_id: str,
    contact_id: str,
    position: tuple[float, float],
    faction: str,
    tick: int,
    comms_assessment: str = "",
) -> DynamicMission:
    """Generate an intercept mission from decoded enemy comms."""
    return DynamicMission(
        id=mission_id,
        source_signal_id=signal_id,
        source_contact_id=contact_id,
        title="Intercept Enemy Supply Line",
        briefing=(
            f"Decoded enemy communications reveal a supply convoy "
            f"passing through the area. Convoy is lightly escorted."
        ),
        mission_type="intercept",
        objectives=[
            MissionObjective(
                id=f"{mission_id}_nav",
                description="Navigate to intercept point",
                objective_type="navigate_to",
                target_position=position,
                order=1,
            ),
            MissionObjective(
                id=f"{mission_id}_engage",
                description="Engage escort vessels",
                objective_type="destroy",
                target_id=f"{mission_id}_escort",
                order=2,
            ),
            MissionObjective(
                id=f"{mission_id}_board",
                description="Board supply ship for cargo",
                objective_type="dock",
                target_id=f"{mission_id}_supply",
                optional=True,
                order=3,
            ),
        ],
        waypoint=position,
        waypoint_name="Intercept Point",
        offered_tick=tick,
        accept_deadline=45.0,
        completion_deadline=240.0,
        rewards=MissionRewards(
            faction_standing={faction: -10.0},
            supplies={"torpedoes": 3, "fuel": 10},
            reputation=8,
            description=(
                f"Torpedo supplies, fuel, {faction} standing -10, "
                f"allied standing +5"
            ),
        ),
        decline_consequences={
            "description": "Convoy passes safely. Opportunity missed.",
        },
        failure_consequences={
            "description": "Convoy escaped or player destroyed.",
        },
        estimated_difficulty="hard",
        comms_assessment=comms_assessment,
    )


def generate_patrol_mission(
    mission_id: str,
    signal_id: str,
    contact_id: str,
    position: tuple[float, float],
    faction: str,
    tick: int,
    comms_assessment: str = "",
) -> DynamicMission:
    """Generate a patrol mission from an allied faction request."""
    return DynamicMission(
        id=mission_id,
        source_signal_id=signal_id,
        source_contact_id=contact_id,
        title="Patrol Sector",
        briefing=(
            f"Command requests a patrol sweep of the area. "
            f"Recent hostile activity reported."
        ),
        mission_type="patrol",
        objectives=[
            MissionObjective(
                id=f"{mission_id}_nav",
                description="Navigate to patrol area",
                objective_type="navigate_to",
                target_position=position,
                order=1,
            ),
            MissionObjective(
                id=f"{mission_id}_scan",
                description="Complete area scan",
                objective_type="scan",
                target_id=f"{mission_id}_area",
                order=2,
            ),
            MissionObjective(
                id=f"{mission_id}_clear",
                description="Neutralise any hostile contacts",
                objective_type="destroy",
                target_id=f"{mission_id}_hostiles",
                optional=True,
                order=3,
            ),
        ],
        waypoint=position,
        waypoint_name="Patrol Area",
        offered_tick=tick,
        accept_deadline=90.0,
        rewards=MissionRewards(
            faction_standing={faction: 10.0},
            crew=1,
            intel=["Sector chart data"],
            reputation=5,
            description=f"{faction.title()} standing +10, 1 crew, intel",
        ),
        decline_consequences={
            "description": "No penalty — request noted.",
        },
        failure_consequences={
            "faction_standing": {faction: -3.0},
            "description": "Patrol incomplete. Slight standing loss.",
        },
        estimated_difficulty="easy",
        comms_assessment=comms_assessment,
    )


def generate_salvage_mission(
    mission_id: str,
    signal_id: str,
    contact_id: str,
    position: tuple[float, float],
    tick: int,
    comms_assessment: str = "",
) -> DynamicMission:
    """Generate a salvage mission from a detected derelict."""
    return DynamicMission(
        id=mission_id,
        source_signal_id=signal_id,
        source_contact_id=contact_id,
        title="Salvage Derelict Vessel",
        briefing=(
            "Comms has decoded an automated distress beacon from "
            "what appears to be an abandoned vessel. No life signs. "
            "May contain useful salvage."
        ),
        mission_type="salvage",
        objectives=[
            MissionObjective(
                id=f"{mission_id}_nav",
                description="Navigate to derelict",
                objective_type="navigate_to",
                target_position=position,
                order=1,
            ),
            MissionObjective(
                id=f"{mission_id}_scan",
                description="Scan for hazards",
                objective_type="scan",
                target_id=contact_id,
                order=2,
            ),
            MissionObjective(
                id=f"{mission_id}_dock",
                description="Dock and salvage",
                objective_type="dock",
                target_id=contact_id,
                optional=True,
                order=3,
            ),
        ],
        waypoint=position,
        waypoint_name="Derelict Vessel",
        offered_tick=tick,
        accept_deadline=120.0,
        rewards=MissionRewards(
            supplies={"medical": 5, "torpedoes": 2},
            intel=["Ship logs"],
            reputation=3,
            description="Random salvage, ship logs, possible rare components",
        ),
        decline_consequences={
            "description": "No penalty — exploration opportunity missed.",
        },
        failure_consequences={
            "description": "Unable to reach or salvage the derelict.",
        },
        estimated_difficulty="easy",
        comms_assessment=comms_assessment,
    )


def generate_trade_mission(
    mission_id: str,
    signal_id: str,
    contact_id: str,
    vessel_name: str,
    position: tuple[float, float],
    faction: str,
    tick: int,
    comms_assessment: str = "",
) -> DynamicMission:
    """Generate a trade mission from a merchant contact."""
    return DynamicMission(
        id=mission_id,
        source_signal_id=signal_id,
        source_contact_id=contact_id,
        title=f"Trade with {vessel_name}",
        briefing=(
            f"The merchant vessel {vessel_name} is offering supplies "
            f"in exchange for sensor sweep data."
        ),
        mission_type="trade",
        objectives=[
            MissionObjective(
                id=f"{mission_id}_nav",
                description=f"Rendezvous with {vessel_name}",
                objective_type="navigate_to",
                target_position=position,
                order=1,
            ),
            MissionObjective(
                id=f"{mission_id}_negotiate",
                description="Negotiate trade terms",
                objective_type="negotiate",
                target_id=contact_id,
                order=2,
            ),
        ],
        waypoint=position,
        waypoint_name=vessel_name,
        offered_tick=tick,
        accept_deadline=90.0,
        rewards=MissionRewards(
            faction_standing={faction: 5.0} if faction != "unknown" else {"civilian": 5.0},
            supplies={"medical": 10, "torpedoes": 2},
            reputation=3,
            description="Medical supplies, torpedoes, faction standing +5",
        ),
        decline_consequences={
            "description": "No penalty — trade opportunity missed.",
        },
        failure_consequences={
            "description": "Trade fell through.",
        },
        estimated_difficulty="easy",
        comms_assessment=comms_assessment,
    )


def generate_diplomatic_mission(
    mission_id: str,
    signal_id: str,
    contact_id: str,
    faction: str,
    position: tuple[float, float],
    tick: int,
    comms_assessment: str = "",
) -> DynamicMission:
    """Generate a diplomatic mission from a faction communication."""
    return DynamicMission(
        id=mission_id,
        source_signal_id=signal_id,
        source_contact_id=contact_id,
        title=f"{faction.title()} Peace Talks",
        briefing=(
            f"The {faction.title()} has proposed a meeting to discuss "
            f"a cease-fire in this sector."
        ),
        mission_type="diplomatic",
        objectives=[
            MissionObjective(
                id=f"{mission_id}_nav",
                description="Navigate to meeting point",
                objective_type="navigate_to",
                target_position=position,
                order=1,
            ),
            MissionObjective(
                id=f"{mission_id}_negotiate",
                description="Conduct diplomatic dialogue",
                objective_type="negotiate",
                target_id=contact_id,
                order=2,
            ),
        ],
        waypoint=position,
        waypoint_name="Meeting Point",
        offered_tick=tick,
        accept_deadline=90.0,
        completion_deadline=300.0,
        rewards=MissionRewards(
            faction_standing={faction: 20.0},
            intel=["Fleet movement intel"],
            reputation=15,
            description=f"{faction.title()} standing +20, cease-fire, intel",
        ),
        decline_consequences={
            "faction_standing": {faction: -5.0},
            "description": f"{faction.title()} offended by refusal. Standing -5.",
        },
        failure_consequences={
            "faction_standing": {faction: -10.0},
            "description": "Talks collapsed. Standing -10, possible attack.",
        },
        estimated_difficulty="moderate",
        comms_assessment=comms_assessment,
    )


# ---------------------------------------------------------------------------
# Service contract generator (§6.3.3.4)
# ---------------------------------------------------------------------------

_CONTRACT_TYPE_TO_OBJECTIVE: dict[str, str] = {
    "escort": "escort_to",
    "delivery": "deliver",
    "scan": "scan",
    "patrol": "navigate_to",
}

_CONTRACT_TYPE_DESCRIPTIONS: dict[str, str] = {
    "escort": "Escort the vendor's convoy through hostile space",
    "delivery": "Deliver cargo to the specified location",
    "scan": "Perform a sensor sweep of the designated area",
    "patrol": "Patrol the designated sector and report contacts",
}


def generate_service_contract_mission(
    mission_id: str,
    contract_type: str,
    vendor_id: str,
    vendor_name: str,
    target_position: tuple[float, float],
    deadline: float,
    credit_value: float,
) -> DynamicMission:
    """Generate a service contract mission from negotiation (§6.3.3.4).

    Args:
        contract_type: escort | delivery | scan | patrol
        credit_value: the trade value being covered by this contract
    """
    obj_type = _CONTRACT_TYPE_TO_OBJECTIVE.get(contract_type, "navigate_to")
    description = _CONTRACT_TYPE_DESCRIPTIONS.get(contract_type, "Complete the assigned task")

    return DynamicMission(
        id=mission_id,
        source_signal_id="",
        source_contact_id="",
        title=f"Service Contract: {contract_type.title()} for {vendor_name}",
        briefing=(
            f"{vendor_name} requires a {contract_type} service in exchange "
            f"for goods valued at {credit_value:.0f} credits. "
            f"Failure to complete will result in reputation and standing penalties."
        ),
        mission_type="trade",
        objectives=[
            MissionObjective(
                id=f"{mission_id}_task",
                description=description,
                objective_type=obj_type,
                target_position=target_position,
                order=1,
            ),
        ],
        waypoint=target_position,
        waypoint_name=vendor_name,
        completion_deadline=deadline,
        rewards=MissionRewards(
            reputation=5,
            description=f"Contract fulfilled — goods already received ({credit_value:.0f}cr value)",
        ),
        decline_consequences={
            "description": "No penalty — contract not accepted.",
        },
        failure_consequences={
            "reputation": -15,
            "faction_standing": {"vendor": -10.0},
            "description": (
                f"Contract failed. Reputation -15, standing -10. "
                f"Goods valued at {credit_value:.0f}cr must be returned or paid for."
            ),
        },
        estimated_difficulty="moderate",
    )
