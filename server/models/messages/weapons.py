"""Weapons message payload schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

VALID_TORPEDO_TYPES = (
    "standard", "homing", "ion", "piercing",
    "heavy", "proximity", "nuclear", "experimental",
)


class WeaponsSelectTargetPayload(BaseModel):
    entity_id: str | None = None  # None to deselect


class WeaponsFireBeamsPayload(BaseModel):
    beam_frequency: str = ""   # alpha | beta | gamma | delta | "" (no frequency)


class WeaponsFireTorpedoPayload(BaseModel):
    tube: int = Field(ge=1, le=2, default=1)


class WeaponsLoadTubePayload(BaseModel):
    tube: int = Field(ge=1, le=2, default=1)
    torpedo_type: Literal[
        "standard", "homing", "ion", "piercing",
        "heavy", "proximity", "nuclear", "experimental",
    ] = "standard"


class WeaponsSetShieldFocusPayload(BaseModel):
    x: float = Field(ge=-1.0, le=1.0)
    y: float = Field(ge=-1.0, le=1.0)
