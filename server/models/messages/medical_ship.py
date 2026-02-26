"""Medical Ship message payloads (v0.07 §2.7)."""
from __future__ import annotations

from pydantic import BaseModel


class MedicalSurgicalProcedurePayload(BaseModel):
    """Request a surgical theatre procedure on a crew member's injury."""
    crew_id: str
    injury_id: str
