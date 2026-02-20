"""Flight Operations message payload schemas."""
from __future__ import annotations

from pydantic import BaseModel


class FlightOpsLaunchDronePayload(BaseModel):
    drone_id: str
    target_x: float
    target_y: float


class FlightOpsRecallDronePayload(BaseModel):
    drone_id: str


class FlightOpsDeployProbePayload(BaseModel):
    target_x: float
    target_y: float
