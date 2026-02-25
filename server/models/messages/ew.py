"""Electronic Warfare message payload schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class EWSetJamTargetPayload(BaseModel):
    entity_id: str | None = None  # None = stop jamming


class EWToggleCountermeasuresPayload(BaseModel):
    active: bool


class EWToggleStealthPayload(BaseModel):
    active: bool


class EWDeployGhostPayload(BaseModel):
    x: float
    y: float
    mimic_class: str


class EWRecallGhostPayload(BaseModel):
    ghost_id: str


class EWSetGhostClassPayload(BaseModel):
    ship_class: str | None = None  # None = reveal true identity


class EWSetFreqLockPayload(BaseModel):
    entity_id: str | None = None   # None = cancel lock
    frequency: str | None = None


class EWBeginIntrusionPayload(BaseModel):
    entity_id: str
    target_system: Literal["shields", "weapons", "engines"]
