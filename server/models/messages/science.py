"""Science message payload schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ScienceStartScanPayload(BaseModel):
    entity_id: str = Field(min_length=1)


class ScienceCancelScanPayload(BaseModel):
    pass
