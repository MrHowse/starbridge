"""Tactical Officer message payload schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TacticalSetEngagementPriorityPayload(BaseModel):
    entity_id: str
    priority: Literal["primary", "secondary", "ignore"] | None = None


class TacticalSetInterceptTargetPayload(BaseModel):
    entity_id: str | None = None


class TacticalAddAnnotationPayload(BaseModel):
    annotation_type: str = Field(default="waypoint")
    x: float
    y: float
    label: str = ""
    text: str = ""


class TacticalRemoveAnnotationPayload(BaseModel):
    annotation_id: str


class TacticalStrikePlanStep(BaseModel):
    role: str
    action: str
    offset_s: float = 0.0


class TacticalCreateStrikePlanPayload(BaseModel):
    steps: list[TacticalStrikePlanStep] = Field(default_factory=list)


class TacticalExecuteStrikePlanPayload(BaseModel):
    plan_id: str
