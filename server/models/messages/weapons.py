"""Weapons message payload schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

VALID_TORPEDO_TYPES = ("standard", "emp", "probe", "nuclear")


class WeaponsSelectTargetPayload(BaseModel):
    entity_id: str | None = None  # None to deselect


class WeaponsFireBeamsPayload(BaseModel):
    pass


class WeaponsFireTorpedoPayload(BaseModel):
    tube: int = Field(ge=1, le=2, default=1)


class WeaponsLoadTubePayload(BaseModel):
    tube: int = Field(ge=1, le=2, default=1)
    torpedo_type: Literal["standard", "emp", "probe", "nuclear"] = "standard"


class WeaponsSetShieldsPayload(BaseModel):
    front: float = Field(ge=0.0, le=100.0)
    rear: float = Field(ge=0.0, le=100.0)
