"""Science message payload schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ScienceStartScanPayload(BaseModel):
    entity_id: str = Field(min_length=1)


class ScienceCancelScanPayload(BaseModel):
    pass


# --- v0.05d: sector-scale scan payloads ------------------------------------


class ScienceStartSectorScanPayload(BaseModel):
    """Begin a sector sweep or long-range scan.

    ``scale`` must be ``"sector"`` (30–60 s sweep of current sector) or
    ``"long_range"`` (120–180 s scan of adjacent sectors).
    ``mode`` must be ``"em"``, ``"grav"``, ``"bio"``, or ``"sub"``.
    """
    scale: str = Field(pattern=r"^(sector|long_range)$")
    mode: str = Field(pattern=r"^(em|grav|bio|sub)$")


class ScienceCancelSectorScanPayload(BaseModel):
    """Abort the current sector-scale scan."""
    model_config = {"extra": "allow"}


class ScienceScanInterruptResponsePayload(BaseModel):
    """Player response to a combat-interrupt warning during a sector scan."""
    continue_scan: bool
