"""Rationing message payload schemas — v0.07 Phase 6.6."""
from __future__ import annotations

from pydantic import BaseModel, Field


class RationingSetLevelPayload(BaseModel):
    """Set a rationing level for a resource type."""
    resource_type: str
    level: str


class RationingCaptainOverridePayload(BaseModel):
    """Captain override: reset resource to unrestricted."""
    resource_type: str


class RationingSubmitRequestPayload(BaseModel):
    """Submit an allocation request from a station."""
    source_station: str
    resource_type: str
    quantity: float = Field(gt=0)
    reason: str = ""


class RationingApproveRequestPayload(BaseModel):
    """Approve a pending allocation request."""
    request_id: str


class RationingDenyRequestPayload(BaseModel):
    """Deny a pending allocation request."""
    request_id: str
    reason: str = ""
