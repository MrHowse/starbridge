"""Medical station message payload schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class MedicalTreatCrewPayload(BaseModel):
    deck: str
    injury_type: Literal["injured", "critical"]


class MedicalCancelTreatmentPayload(BaseModel):
    deck: str
