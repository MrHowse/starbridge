"""Comms station message payload schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CommsTuneFrequencyPayload(BaseModel):
    frequency: float = Field(ge=0.0, le=1.0)


class CommsHailPayload(BaseModel):
    contact_id: str
    message_type: Literal["negotiate", "demand", "bluff"]
