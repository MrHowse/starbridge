"""Medical station message payload schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


# Legacy (deck-level treatment)
class MedicalTreatCrewPayload(BaseModel):
    deck: str
    injury_type: Literal["injured", "critical"]


class MedicalCancelTreatmentPayload(BaseModel):
    deck: str


# v0.06.1 — Individual crew treatment
class MedicalAdmitPayload(BaseModel):
    crew_id: str


class MedicalTreatPayload(BaseModel):
    crew_id: str
    injury_id: str


class MedicalStabilisePayload(BaseModel):
    crew_id: str
    injury_id: str


class MedicalDischargePayload(BaseModel):
    crew_id: str


class MedicalQuarantinePayload(BaseModel):
    crew_id: str
