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
