"""Comms station message payload schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CommsTuneFrequencyPayload(BaseModel):
    frequency: float = Field(ge=0.0, le=1.0)


class CommsHailPayload(BaseModel):
    contact_id: str
    message_type: Literal["negotiate", "demand", "bluff"] = "negotiate"
    frequency: float | None = None
    hail_type: Literal[
        "identify", "warning", "negotiate", "distress",
        "deception", "broadcast", "surrender",
    ] = "identify"


class CommsDecodeSignalPayload(BaseModel):
    signal_id: str


class CommsRespondPayload(BaseModel):
    signal_id: str
    response_id: str


class CommsRouteIntelPayload(BaseModel):
    signal_id: str
    target_station: str


class CommsSetChannelPayload(BaseModel):
    channel: str
    status: Literal["open", "monitored", "closed"]


class CommsProbePayload(BaseModel):
    target_id: str


class CommsAssessDistressPayload(BaseModel):
    signal_id: str


class CommsDismissSignalPayload(BaseModel):
    signal_id: str
