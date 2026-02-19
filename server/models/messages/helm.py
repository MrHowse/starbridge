"""Helm message payload schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class HelmSetHeadingPayload(BaseModel):
    heading: float = Field(ge=0.0, lt=360.0)


class HelmSetThrottlePayload(BaseModel):
    throttle: float = Field(ge=0.0, le=100.0)
