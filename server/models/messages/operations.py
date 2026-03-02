"""Operations station message payload schemas (v0.08 A.2)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class OperationsPingPayload(BaseModel):
    """Keep-alive / heartbeat."""
    pass


class OpsStartAssessmentPayload(BaseModel):
    """Begin a battle assessment on a contact (A.2.1)."""
    contact_id: str


class OpsCancelAssessmentPayload(BaseModel):
    """Cancel the current in-progress assessment (A.2.1.2)."""
    pass


class OpsSetVulnerableFacingPayload(BaseModel):
    """Designate a vulnerable shield facing (A.2.2.2)."""
    contact_id: str
    facing: Literal["fore", "aft", "port", "starboard"]


class OpsSetPrioritySubsystemPayload(BaseModel):
    """Designate a priority enemy subsystem (A.2.3.2)."""
    contact_id: str
    subsystem: Literal["engines", "weapons", "shields", "sensors", "propulsion"]


class OpsTogglePredictionPayload(BaseModel):
    """Toggle behaviour prediction on a contact (A.2.4.4)."""
    contact_id: str
    active: bool


class OpsSetThreatLevelPayload(BaseModel):
    """Set threat level on a contact (A.2.5.1)."""
    contact_id: str
    level: Literal["low", "medium", "high", "critical"]


# --- A.3 Coordination Bonuses ---


class OpsSetWeaponsHelmSyncPayload(BaseModel):
    """Set weapons-helm sync on a contact (A.3.1.1)."""
    contact_id: str


class OpsCancelWeaponsHelmSyncPayload(BaseModel):
    """Cancel weapons-helm sync (A.3.1.4)."""
    pass


class OpsSetSensorFocusPayload(BaseModel):
    """Set sensor focus zone (A.3.2.1)."""
    center_x: float
    center_y: float
    radius: float


class OpsCancelSensorFocusPayload(BaseModel):
    """Cancel sensor focus zone (A.3.2.4)."""
    pass


class OpsStartDamageCoordinationPayload(BaseModel):
    """Start damage coordination assessment (A.3.3.1)."""
    pass


class OpsIssueEvasionAlertPayload(BaseModel):
    """Issue evasion alert with recommended heading (A.3.4.1)."""
    bearing: float
