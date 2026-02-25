"""Flight Operations message payload schemas — v0.06.5."""
from __future__ import annotations

from pydantic import BaseModel


class FlightOpsLaunchDronePayload(BaseModel):
    drone_id: str


class FlightOpsRecallDronePayload(BaseModel):
    drone_id: str


class FlightOpsSetWaypointPayload(BaseModel):
    drone_id: str
    x: float
    y: float


class FlightOpsSetWaypointsPayload(BaseModel):
    drone_id: str
    waypoints: list[list[float]]


class FlightOpsSetEngagementRulesPayload(BaseModel):
    drone_id: str
    rules: str


class FlightOpsSetBehaviourPayload(BaseModel):
    drone_id: str
    behaviour: str


class FlightOpsDesignateTargetPayload(BaseModel):
    drone_id: str
    target_id: str


class FlightOpsDeployDecoyPayload(BaseModel):
    direction: float


class FlightOpsDeployBuoyPayload(BaseModel):
    drone_id: str


class FlightOpsEscortAssignPayload(BaseModel):
    drone_id: str
    escort_target: str


class FlightOpsClearToLandPayload(BaseModel):
    drone_id: str


class FlightOpsRushTurnaroundPayload(BaseModel):
    drone_id: str
    skip: list[str] = []


class FlightOpsAbortLandingPayload(BaseModel):
    drone_id: str


class FlightOpsCancelLaunchPayload(BaseModel):
    drone_id: str


class FlightOpsPrioritiseRecoveryPayload(BaseModel):
    order: list[str]
