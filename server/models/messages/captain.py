"""Captain message payload schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CaptainSetAlertPayload(BaseModel):
    level: Literal["green", "yellow", "red"]


class CaptainAuthorizePayload(BaseModel):
    request_id: str
    approved: bool


class CaptainAddLogPayload(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class CaptainSystemOverridePayload(BaseModel):
    system: str
    online: bool  # True = bring online, False = take offline


class CaptainSaveGamePayload(BaseModel):
    """Sent by Captain station to trigger save-and-return-to-lobby."""
    model_config = {"extra": "allow"}  # accepts empty payload {}


class CaptainReassignCrewPayload(BaseModel):
    """Sent by Captain station to reassign a crew member to a new duty station."""
    crew_id: str
    new_duty_station: str


class CaptainAcceptMissionPayload(BaseModel):
    """Sent by Captain station to accept an offered dynamic mission."""
    mission_id: str


class CaptainDeclineMissionPayload(BaseModel):
    """Sent by Captain station to decline an offered dynamic mission."""
    mission_id: str


class CaptainSetPriorityTargetPayload(BaseModel):
    """Mark or clear a priority target visible to all stations."""
    entity_id: str | None = None


class CaptainSetGeneralOrderPayload(BaseModel):
    """Issue a ship-wide general order."""
    order: Literal["battle_stations", "silent_running", "evasive_manoeuvres", "all_stop", "condition_green"]


class CaptainAcknowledgeAllStopPayload(BaseModel):
    """Helm acknowledges ALL STOP to resume control."""
    model_config = {"extra": "allow"}
