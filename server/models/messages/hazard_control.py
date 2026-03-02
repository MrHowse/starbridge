"""Hazard Control message payloads — v0.08 B.2–B.6."""
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


# --- B.4: Radiation System ---


class HazConDispatchDeconTeamPayload(BaseModel):
    room_id: str


class HazConCancelDeconTeamPayload(BaseModel):
    room_id: str


# --- B.5: Structural Integrity System ---


class HazConReinforceSectionPayload(BaseModel):
    section_id: str


class HazConCancelReinforcementPayload(BaseModel):
    section_id: str


# --- B.6: Emergency Systems ---


class HazConSealConnectionPayload(BaseModel):
    room_a: str
    room_b: str


class HazConUnsealConnectionPayload(BaseModel):
    room_a: str
    room_b: str


class HazConOverrideSecurityLockPayload(BaseModel):
    room_id: str


class HazConRedirectBatteryPayload(BaseModel):
    from_deck: int
    to_deck: int


class HazConSetEvacuationOrderPayload(BaseModel):
    deck_order: list[int]


class HazConLaunchPodPayload(BaseModel):
    pod_id: str


class AbandonShipPayload(BaseModel):
    pass
