"""Hazard Control message payloads — v0.08 B.2 + B.3."""
from __future__ import annotations

from pydantic import BaseModel


class HazConSuppressLocalPayload(BaseModel):
    room_id: str


class HazConSuppressDeckPayload(BaseModel):
    deck_name: str


class HazConVentRoomPayload(BaseModel):
    room_id: str


class HazConCancelVentPayload(BaseModel):
    room_id: str


class HazConDispatchFireTeamPayload(BaseModel):
    room_id: str


class HazConCancelFireTeamPayload(BaseModel):
    room_id: str


# --- B.3: Atmosphere System ---


class HazConForceFieldPayload(BaseModel):
    room_id: str


class HazConSealBulkheadPayload(BaseModel):
    room_id: str


class HazConUnsealBulkheadPayload(BaseModel):
    room_id: str


class HazConOrderEvacuationPayload(BaseModel):
    room_id: str


class HazConCycleVentPayload(BaseModel):
    room_a: str
    room_b: str


class HazConSetVentPayload(BaseModel):
    room_a: str
    room_b: str
    state: str


class HazConEmergencyVentSpacePayload(BaseModel):
    room_id: str


class HazConCancelSpaceVentPayload(BaseModel):
    room_id: str
