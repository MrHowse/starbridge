"""Weapons message payload schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class WeaponsSelectTargetPayload(BaseModel):
    entity_id: str | None = None  # None to deselect


class WeaponsFireBeamsPayload(BaseModel):
    pass


class WeaponsFireTorpedoPayload(BaseModel):
    tube: int = Field(ge=1, le=2, default=1)


class WeaponsSetShieldsPayload(BaseModel):
    front: float = Field(ge=0.0, le=100.0)
    rear: float = Field(ge=0.0, le=100.0)
