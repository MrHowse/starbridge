"""Hazard Control message payloads — v0.08 B.2."""
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
