"""Salvage message payload schemas — v0.07 Phase 6.5."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SalvageAssessPayload(BaseModel):
    """Begin scanning a wreck to assess its contents."""
    wreck_id: str


class SalvageCancelAssessmentPayload(BaseModel):
    """Cancel an in-progress wreck scan."""
    wreck_id: str


class SalvageSelectItemsPayload(BaseModel):
    """Select items from a scanned wreck for extraction."""
    wreck_id: str
    item_ids: list[str] = Field(min_length=1)


class SalvageBeginPayload(BaseModel):
    """Begin extracting selected items from a wreck."""
    wreck_id: str


class SalvageCancelPayload(BaseModel):
    """Cancel an in-progress salvage operation."""
    wreck_id: str
