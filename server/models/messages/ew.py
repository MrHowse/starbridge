"""Electronic Warfare message payload schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class EWSetJamTargetPayload(BaseModel):
    entity_id: str | None = None  # None = stop jamming


class EWToggleCountermeasuresPayload(BaseModel):
    active: bool


class EWBeginIntrusionPayload(BaseModel):
    entity_id: str
    target_system: Literal["shields", "weapons", "engines"]
