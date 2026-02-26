"""Carrier Operations message payloads (v0.07 §2.6)."""
from __future__ import annotations

from pydantic import BaseModel


class CarrierCreateSquadronPayload(BaseModel):
    name: str
    drone_ids: list[str]


class CarrierDisbandSquadronPayload(BaseModel):
    squadron_id: str


class CarrierSquadronOrderPayload(BaseModel):
    squadron_id: str
    order: str  # "launch"|"recall"|"set_waypoint"|"set_behaviour"|"set_engagement_rules"
    x: float | None = None
    y: float | None = None
    behaviour: str | None = None
    rules: str | None = None


class CarrierSetCAPPayload(BaseModel):
    centre_x: float
    centre_y: float
    radius: float
    drone_ids: list[str]


class CarrierCancelCAPPayload(BaseModel):
    pass


class CarrierScramblePayload(BaseModel):
    pass


class CarrierCancelScramblePayload(BaseModel):
    pass
