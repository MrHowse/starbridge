"""Docking system message payload schemas — v0.05f."""
from __future__ import annotations

from pydantic import BaseModel


class DockingRequestClearancePayload(BaseModel):
    station_id: str


class DockingStartServicePayload(BaseModel):
    service: str


class DockingCancelServicePayload(BaseModel):
    service: str


class CaptainUndockPayload(BaseModel):
    emergency: bool = False
