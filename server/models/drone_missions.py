"""
Drone Mission Models — v0.06.5 Flight Ops Overhaul.

Drones are assigned missions by Flight Ops.  Each mission type has waypoints,
objectives, and completion criteria.  The game loop ticks missions forward;
this module defines the data structures and factory functions.

Mission types:
  patrol              — fly a waypoint circuit, report contacts
  escort              — fly alongside a target, defend it
  attack_run          — engage a specific enemy entity
  search_and_rescue   — fly to location, pick up survivors, return
  survey              — orbit a target, collect detailed scan data
  buoy_deployment     — fly to locations, drop sensor buoys
  electronic_warfare  — fly to location, jam enemy sensors
  decoy_deployment    — (handled as expendable launch, not a full mission)
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MISSION_TYPES = (
    "patrol", "escort", "attack_run", "search_and_rescue",
    "survey", "buoy_deployment", "electronic_warfare",
)

MISSION_STATUSES = (
    "briefing", "active", "complete", "aborted", "failed",
)

WAYPOINT_TYPES = (
    "navigate", "loiter", "scan", "attack", "pickup", "deploy",
)

# Engagement rules for escort / combat missions.
ENGAGEMENT_RULES = ("weapons_free", "weapons_tight", "weapons_hold")

# Default loiter times at waypoints (seconds).
PATROL_LOITER_TIME = 10.0
SURVEY_LOITER_TIME = 45.0

# Default survey data collection rate (% per second while in loiter).
SURVEY_DATA_RATE = 2.0  # 100% in 50 seconds

# Attack run: break-away distance after strafing pass.
ATTACK_BREAK_DISTANCE = 5_000.0

# Waypoint arrival distance.
WAYPOINT_ARRIVAL_DIST = 500.0

# Search and rescue: pickup time per survivor (seconds).
SAR_PICKUP_TIME = 15.0

# Mission counter for unique IDs.
_mission_counter: int = 0


# ---------------------------------------------------------------------------
# Waypoint
# ---------------------------------------------------------------------------


@dataclass
class DroneMissionWaypoint:
    """A single waypoint in a drone mission route."""

    position: tuple[float, float]
    waypoint_type: str = "navigate"       # navigate | loiter | scan | attack | pickup | deploy
    loiter_time: float | None = None      # seconds to orbit at this point
    action: str | None = None             # what to do on arrival
    completed: bool = False
    time_spent: float = 0.0               # seconds spent at this waypoint so far


# ---------------------------------------------------------------------------
# Objective
# ---------------------------------------------------------------------------


@dataclass
class DroneMissionObjective:
    """A discrete objective within a drone mission."""

    id: str
    description: str
    objective_type: str                   # matches mission waypoint actions
    target_id: str | None = None          # entity ID (enemy, derelict, etc.)
    target_position: tuple[float, float] | None = None
    required: bool = True
    completed: bool = False
    progress: float = 0.0                 # 0-100 %
    data: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Mission
# ---------------------------------------------------------------------------


@dataclass
class DroneMission:
    """A mission assigned to a drone by Flight Ops."""

    id: str
    drone_id: str
    mission_type: str

    # Navigation
    waypoints: list[DroneMissionWaypoint] = field(default_factory=list)
    current_waypoint: int = 0

    # Objectives
    objectives: list[DroneMissionObjective] = field(default_factory=list)

    # Timing
    started_tick: int = 0
    timeout_tick: int | None = None       # auto-recall if exceeded

    # Engagement rules (escort / combat).
    engagement_rules: str = "weapons_tight"

    # Status
    status: str = "briefing"

    # Results
    data_collected: dict = field(default_factory=dict)
    contacts_found: list[str] = field(default_factory=list)
    survivors_rescued: int = 0
    damage_dealt: float = 0.0
    buoys_deployed: int = 0

    # -----------------------------------------------------------------------
    # Status helpers
    # -----------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def is_over(self) -> bool:
        return self.status in ("complete", "aborted", "failed")

    def activate(self, tick: int = 0) -> None:
        """Transition from briefing to active."""
        self.status = "active"
        self.started_tick = tick

    def complete(self) -> None:
        self.status = "complete"

    def abort(self) -> None:
        self.status = "aborted"

    def fail(self) -> None:
        self.status = "failed"

    # -----------------------------------------------------------------------
    # Waypoint helpers
    # -----------------------------------------------------------------------

    @property
    def current_wp(self) -> DroneMissionWaypoint | None:
        if 0 <= self.current_waypoint < len(self.waypoints):
            return self.waypoints[self.current_waypoint]
        return None

    def advance_waypoint(self) -> bool:
        """Mark current waypoint completed and move to next.

        Returns True if there is a next waypoint, False if route is done.
        """
        wp = self.current_wp
        if wp:
            wp.completed = True
        self.current_waypoint += 1
        return self.current_waypoint < len(self.waypoints)

    @property
    def all_waypoints_complete(self) -> bool:
        return all(wp.completed for wp in self.waypoints)

    @property
    def route_complete(self) -> bool:
        return self.current_waypoint >= len(self.waypoints)

    # -----------------------------------------------------------------------
    # Objective helpers
    # -----------------------------------------------------------------------

    def complete_objective(self, obj_id: str) -> bool:
        """Mark an objective as completed.  Returns True if found."""
        for obj in self.objectives:
            if obj.id == obj_id:
                obj.completed = True
                obj.progress = 100.0
                return True
        return False

    @property
    def all_required_complete(self) -> bool:
        return all(
            o.completed for o in self.objectives if o.required
        )

    @property
    def objective_summary(self) -> str:
        done = sum(1 for o in self.objectives if o.completed)
        total = len(self.objectives)
        return f"{done}/{total}"


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------


def _next_mission_id() -> str:
    global _mission_counter
    _mission_counter += 1
    return f"dm_{_mission_counter}"


def reset_mission_counter() -> None:
    """Reset the global mission counter (call at game start)."""
    global _mission_counter
    _mission_counter = 0


# ---------------------------------------------------------------------------
# Factory functions — one per mission type
# ---------------------------------------------------------------------------


def create_patrol_mission(
    drone_id: str,
    waypoints: list[tuple[float, float]],
    loiter_time: float = PATROL_LOITER_TIME,
    timeout_tick: int | None = None,
) -> DroneMission:
    """Create a patrol mission: fly a circuit of waypoints, report contacts."""
    mission_id = _next_mission_id()
    wps = [
        DroneMissionWaypoint(
            position=pos,
            waypoint_type="loiter",
            loiter_time=loiter_time,
            action="scan",
        )
        for pos in waypoints
    ]
    objectives = [
        DroneMissionObjective(
            id=f"{mission_id}_patrol",
            description="Complete patrol circuit",
            objective_type="patrol",
        ),
    ]
    return DroneMission(
        id=mission_id,
        drone_id=drone_id,
        mission_type="patrol",
        waypoints=wps,
        objectives=objectives,
        timeout_tick=timeout_tick,
    )


def create_escort_mission(
    drone_id: str,
    escort_target_id: str,
    escort_position: tuple[float, float],
    engagement_rules: str = "weapons_tight",
    timeout_tick: int | None = None,
) -> DroneMission:
    """Create an escort mission: fly alongside a target, defend it."""
    mission_id = _next_mission_id()
    wps = [
        DroneMissionWaypoint(
            position=escort_position,
            waypoint_type="loiter",
            loiter_time=None,   # indefinite — loiter until recalled
            action="escort",
        ),
    ]
    objectives = [
        DroneMissionObjective(
            id=f"{mission_id}_escort",
            description=f"Escort {escort_target_id}",
            objective_type="escort",
            target_id=escort_target_id,
            target_position=escort_position,
        ),
    ]
    return DroneMission(
        id=mission_id,
        drone_id=drone_id,
        mission_type="escort",
        waypoints=wps,
        objectives=objectives,
        engagement_rules=engagement_rules,
        timeout_tick=timeout_tick,
    )


def create_attack_run_mission(
    drone_id: str,
    target_id: str,
    target_position: tuple[float, float],
    approach_bearing: float = 0.0,
    engagement_rules: str = "weapons_free",
    timeout_tick: int | None = None,
) -> DroneMission:
    """Create an attack run mission: engage a specific enemy entity."""
    mission_id = _next_mission_id()
    wps = [
        DroneMissionWaypoint(
            position=target_position,
            waypoint_type="attack",
            action="attack",
        ),
    ]
    objectives = [
        DroneMissionObjective(
            id=f"{mission_id}_attack",
            description=f"Attack {target_id}",
            objective_type="attack",
            target_id=target_id,
            target_position=target_position,
            data={"approach_bearing": approach_bearing},
        ),
    ]
    return DroneMission(
        id=mission_id,
        drone_id=drone_id,
        mission_type="attack_run",
        waypoints=wps,
        objectives=objectives,
        engagement_rules=engagement_rules,
        timeout_tick=timeout_tick,
    )


def create_sar_mission(
    drone_id: str,
    rescue_position: tuple[float, float],
    expected_survivors: int = 0,
    timeout_tick: int | None = None,
) -> DroneMission:
    """Create a search-and-rescue mission: fly to location, pick up survivors."""
    mission_id = _next_mission_id()
    wps = [
        DroneMissionWaypoint(
            position=rescue_position,
            waypoint_type="pickup",
            action="pickup",
        ),
    ]
    objectives = [
        DroneMissionObjective(
            id=f"{mission_id}_rescue",
            description="Rescue survivors",
            objective_type="rescue",
            target_position=rescue_position,
            data={"expected_survivors": expected_survivors},
        ),
    ]
    return DroneMission(
        id=mission_id,
        drone_id=drone_id,
        mission_type="search_and_rescue",
        waypoints=wps,
        objectives=objectives,
        timeout_tick=timeout_tick,
    )


def create_survey_mission(
    drone_id: str,
    survey_position: tuple[float, float],
    loiter_time: float = SURVEY_LOITER_TIME,
    deploy_buoy: bool = False,
    timeout_tick: int | None = None,
) -> DroneMission:
    """Create a survey mission: orbit a target, collect detailed scan data."""
    mission_id = _next_mission_id()
    wps = [
        DroneMissionWaypoint(
            position=survey_position,
            waypoint_type="scan",
            loiter_time=loiter_time,
            action="survey",
        ),
    ]
    if deploy_buoy:
        wps.append(DroneMissionWaypoint(
            position=survey_position,
            waypoint_type="deploy",
            action="deploy_buoy",
        ))
    objectives = [
        DroneMissionObjective(
            id=f"{mission_id}_survey",
            description="Complete survey",
            objective_type="survey",
            target_position=survey_position,
        ),
    ]
    if deploy_buoy:
        objectives.append(DroneMissionObjective(
            id=f"{mission_id}_buoy",
            description="Deploy sensor buoy",
            objective_type="deploy_buoy",
            target_position=survey_position,
        ))
    return DroneMission(
        id=mission_id,
        drone_id=drone_id,
        mission_type="survey",
        waypoints=wps,
        objectives=objectives,
        timeout_tick=timeout_tick,
    )


def create_buoy_deployment_mission(
    drone_id: str,
    positions: list[tuple[float, float]],
    timeout_tick: int | None = None,
) -> DroneMission:
    """Create a buoy deployment mission: fly to locations, drop sensor buoys."""
    mission_id = _next_mission_id()
    wps = [
        DroneMissionWaypoint(
            position=pos,
            waypoint_type="deploy",
            action="deploy_buoy",
        )
        for pos in positions
    ]
    objectives = [
        DroneMissionObjective(
            id=f"{mission_id}_buoy_{i}",
            description=f"Deploy buoy at position {i + 1}",
            objective_type="deploy_buoy",
            target_position=pos,
        )
        for i, pos in enumerate(positions)
    ]
    return DroneMission(
        id=mission_id,
        drone_id=drone_id,
        mission_type="buoy_deployment",
        waypoints=wps,
        objectives=objectives,
        timeout_tick=timeout_tick,
    )


def create_ew_mission(
    drone_id: str,
    jam_position: tuple[float, float],
    loiter_time: float | None = None,
    timeout_tick: int | None = None,
) -> DroneMission:
    """Create an electronic warfare mission: fly to location, jam enemy sensors."""
    mission_id = _next_mission_id()
    wps = [
        DroneMissionWaypoint(
            position=jam_position,
            waypoint_type="loiter",
            loiter_time=loiter_time,   # None = jam until fuel runs out
            action="jam",
        ),
    ]
    objectives = [
        DroneMissionObjective(
            id=f"{mission_id}_jam",
            description="Jam enemy sensors",
            objective_type="jam",
            target_position=jam_position,
        ),
    ]
    return DroneMission(
        id=mission_id,
        drone_id=drone_id,
        mission_type="electronic_warfare",
        waypoints=wps,
        objectives=objectives,
        timeout_tick=timeout_tick,
    )


# ---------------------------------------------------------------------------
# Mission modification helpers
# ---------------------------------------------------------------------------


def add_waypoint(mission: DroneMission, position: tuple[float, float],
                 waypoint_type: str = "navigate", loiter_time: float | None = None,
                 action: str | None = None) -> None:
    """Add a waypoint to a mission (Flight Ops can modify routes in real-time)."""
    mission.waypoints.append(DroneMissionWaypoint(
        position=position,
        waypoint_type=waypoint_type,
        loiter_time=loiter_time,
        action=action,
    ))


def remove_waypoint(mission: DroneMission, index: int) -> bool:
    """Remove a waypoint by index.  Cannot remove already-completed waypoints."""
    if index < 0 or index >= len(mission.waypoints):
        return False
    if mission.waypoints[index].completed:
        return False
    mission.waypoints.pop(index)
    # Adjust current_waypoint if needed.
    if mission.current_waypoint > index:
        mission.current_waypoint -= 1
    elif mission.current_waypoint >= len(mission.waypoints):
        mission.current_waypoint = len(mission.waypoints)
    return True


def update_objective_progress(mission: DroneMission, obj_id: str,
                              progress: float) -> bool:
    """Update an objective's progress (0-100).  Returns True if found."""
    for obj in mission.objectives:
        if obj.id == obj_id:
            obj.progress = min(100.0, max(0.0, progress))
            if obj.progress >= 100.0:
                obj.completed = True
            return True
    return False


# ---------------------------------------------------------------------------
# Fuel estimation
# ---------------------------------------------------------------------------


def estimate_fuel_for_route(
    waypoints: list[tuple[float, float]],
    start_position: tuple[float, float],
    max_speed: float,
    fuel_consumption: float,
    return_to: tuple[float, float] | None = None,
) -> dict[str, float]:
    """Estimate fuel usage for a planned route.

    Returns:
        route_fuel:   % fuel for the route itself
        return_fuel:  % fuel to return from last waypoint to return_to
        total_fuel:   route_fuel + return_fuel
        reserve:      100 - total_fuel (negative if impossible)
    """
    import math

    if max_speed <= 0 or fuel_consumption <= 0:
        return {"route_fuel": 0.0, "return_fuel": 0.0, "total_fuel": 0.0, "reserve": 100.0}

    total_dist = 0.0
    prev = start_position
    for wp in waypoints:
        dx = wp[0] - prev[0]
        dy = wp[1] - prev[1]
        total_dist += math.sqrt(dx * dx + dy * dy)
        prev = wp

    route_time = total_dist / max_speed
    route_fuel = route_time * fuel_consumption

    return_fuel = 0.0
    if return_to is not None and waypoints:
        last = waypoints[-1]
        dx = return_to[0] - last[0]
        dy = return_to[1] - last[1]
        ret_dist = math.sqrt(dx * dx + dy * dy)
        return_fuel = (ret_dist / max_speed) * fuel_consumption

    total = route_fuel + return_fuel
    return {
        "route_fuel": round(route_fuel, 2),
        "return_fuel": round(return_fuel, 2),
        "total_fuel": round(total, 2),
        "reserve": round(100.0 - total, 2),
    }


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def serialise_waypoint(wp: DroneMissionWaypoint) -> dict:
    return {
        "position": list(wp.position),
        "waypoint_type": wp.waypoint_type,
        "loiter_time": wp.loiter_time,
        "action": wp.action,
        "completed": wp.completed,
        "time_spent": wp.time_spent,
    }


def deserialise_waypoint(data: dict) -> DroneMissionWaypoint:
    return DroneMissionWaypoint(
        position=tuple(data["position"]),
        waypoint_type=data.get("waypoint_type", "navigate"),
        loiter_time=data.get("loiter_time"),
        action=data.get("action"),
        completed=data.get("completed", False),
        time_spent=data.get("time_spent", 0.0),
    )


def serialise_objective(obj: DroneMissionObjective) -> dict:
    return {
        "id": obj.id,
        "description": obj.description,
        "objective_type": obj.objective_type,
        "target_id": obj.target_id,
        "target_position": list(obj.target_position) if obj.target_position else None,
        "required": obj.required,
        "completed": obj.completed,
        "progress": obj.progress,
        "data": obj.data,
    }


def deserialise_objective(data: dict) -> DroneMissionObjective:
    tp = data.get("target_position")
    return DroneMissionObjective(
        id=data["id"],
        description=data.get("description", ""),
        objective_type=data.get("objective_type", ""),
        target_id=data.get("target_id"),
        target_position=tuple(tp) if tp else None,
        required=data.get("required", True),
        completed=data.get("completed", False),
        progress=data.get("progress", 0.0),
        data=data.get("data", {}),
    )


def serialise_mission(m: DroneMission) -> dict:
    return {
        "id": m.id,
        "drone_id": m.drone_id,
        "mission_type": m.mission_type,
        "waypoints": [serialise_waypoint(wp) for wp in m.waypoints],
        "current_waypoint": m.current_waypoint,
        "objectives": [serialise_objective(o) for o in m.objectives],
        "started_tick": m.started_tick,
        "timeout_tick": m.timeout_tick,
        "engagement_rules": m.engagement_rules,
        "status": m.status,
        "data_collected": m.data_collected,
        "contacts_found": m.contacts_found,
        "survivors_rescued": m.survivors_rescued,
        "damage_dealt": m.damage_dealt,
        "buoys_deployed": m.buoys_deployed,
    }


def deserialise_mission(data: dict) -> DroneMission:
    return DroneMission(
        id=data["id"],
        drone_id=data.get("drone_id", ""),
        mission_type=data.get("mission_type", ""),
        waypoints=[deserialise_waypoint(w) for w in data.get("waypoints", [])],
        current_waypoint=data.get("current_waypoint", 0),
        objectives=[deserialise_objective(o) for o in data.get("objectives", [])],
        started_tick=data.get("started_tick", 0),
        timeout_tick=data.get("timeout_tick"),
        engagement_rules=data.get("engagement_rules", "weapons_tight"),
        status=data.get("status", "briefing"),
        data_collected=data.get("data_collected", {}),
        contacts_found=data.get("contacts_found", []),
        survivors_rescued=data.get("survivors_rescued", 0),
        damage_dealt=data.get("damage_dealt", 0.0),
        buoys_deployed=data.get("buoys_deployed", 0),
    )
