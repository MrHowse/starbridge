"""Message envelope and payload validation dispatcher."""
from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from server.models.messages.captain import CaptainAddLogPayload, CaptainAuthorizePayload, CaptainSetAlertPayload, CaptainSystemOverridePayload
from server.models.messages.comms import CommsHailPayload, CommsTuneFrequencyPayload
from server.models.messages.medical import MedicalCancelTreatmentPayload, MedicalTreatCrewPayload
from server.models.messages.puzzle import PuzzleAssistPayload, PuzzleCancelPayload, PuzzleSubmitPayload
from server.models.messages.security import SecurityMoveSquadPayload, SecurityToggleDoorPayload
from server.models.messages.flight_ops import (
    FlightOpsDeployProbePayload,
    FlightOpsLaunchDronePayload,
    FlightOpsRecallDronePayload,
)
from server.models.messages.ew import (
    EWSetJamTargetPayload,
    EWToggleCountermeasuresPayload,
    EWBeginIntrusionPayload,
)
from server.models.messages.tactical import (
    TacticalSetEngagementPriorityPayload,
    TacticalSetInterceptTargetPayload,
    TacticalAddAnnotationPayload,
    TacticalRemoveAnnotationPayload,
    TacticalCreateStrikePlanPayload,
    TacticalExecuteStrikePlanPayload,
)
from server.models.messages.engineering import (
    EngineeringCancelDCTPayload,
    EngineeringDispatchDCTPayload,
    EngineeringSetPowerPayload,
    EngineeringSetRepairPayload,
)
from server.models.messages.helm import HelmSetHeadingPayload, HelmSetThrottlePayload
from server.models.messages.lobby import LobbyClaimRolePayload, LobbyReleaseRolePayload, LobbyStartGamePayload
from server.models.messages.science import ScienceCancelScanPayload, ScienceStartScanPayload
from server.models.messages.weapons import (
    WeaponsFireBeamsPayload,
    WeaponsFireTorpedoPayload,
    WeaponsLoadTubePayload,
    WeaponsSelectTargetPayload,
    WeaponsSetShieldsPayload,
)


class Message(BaseModel):
    """Standard WebSocket message envelope. All messages use this format.

    tick is None for client→server messages and lobby messages.
    It is populated by the server for in-game state updates.
    Serialise outbound messages with to_json() to omit null fields.
    """

    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    tick: int | None = None
    timestamp: float

    @classmethod
    def build(
        cls,
        type_: str,
        payload: dict[str, Any] | None = None,
        tick: int | None = None,
    ) -> Message:
        """Construct an outbound message stamped with the current time."""
        return cls(
            type=type_,
            payload=payload or {},
            tick=tick,
            timestamp=time.time(),
        )

    def to_json(self) -> str:
        """Serialise to JSON, omitting fields whose value is None."""
        return self.model_dump_json(exclude_none=True)


_PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    # Lobby
    "lobby.claim_role": LobbyClaimRolePayload,
    "lobby.release_role": LobbyReleaseRolePayload,
    "lobby.start_game": LobbyStartGamePayload,
    # Helm
    "helm.set_heading": HelmSetHeadingPayload,
    "helm.set_throttle": HelmSetThrottlePayload,
    # Engineering
    "engineering.set_power":    EngineeringSetPowerPayload,
    "engineering.set_repair":   EngineeringSetRepairPayload,
    "engineering.dispatch_dct": EngineeringDispatchDCTPayload,
    "engineering.cancel_dct":   EngineeringCancelDCTPayload,
    # Weapons
    "weapons.select_target": WeaponsSelectTargetPayload,
    "weapons.fire_beams": WeaponsFireBeamsPayload,
    "weapons.fire_torpedo": WeaponsFireTorpedoPayload,
    "weapons.load_tube": WeaponsLoadTubePayload,
    "weapons.set_shields": WeaponsSetShieldsPayload,
    # Science
    "science.start_scan": ScienceStartScanPayload,
    "science.cancel_scan": ScienceCancelScanPayload,
    # Captain
    "captain.set_alert": CaptainSetAlertPayload,
    "captain.authorize": CaptainAuthorizePayload,
    "captain.add_log": CaptainAddLogPayload,
    "captain.system_override": CaptainSystemOverridePayload,
    # Medical
    "medical.treat_crew": MedicalTreatCrewPayload,
    "medical.cancel_treatment": MedicalCancelTreatmentPayload,
    # Security
    "security.move_squad": SecurityMoveSquadPayload,
    "security.toggle_door": SecurityToggleDoorPayload,
    # Comms
    "comms.tune_frequency": CommsTuneFrequencyPayload,
    "comms.hail": CommsHailPayload,
    # Puzzle
    "puzzle.submit": PuzzleSubmitPayload,
    "puzzle.request_assist": PuzzleAssistPayload,
    "puzzle.cancel": PuzzleCancelPayload,
    # Flight Ops
    "flight_ops.launch_drone":  FlightOpsLaunchDronePayload,
    "flight_ops.recall_drone":  FlightOpsRecallDronePayload,
    "flight_ops.deploy_probe":  FlightOpsDeployProbePayload,
    # Electronic Warfare
    "ew.set_jam_target":         EWSetJamTargetPayload,
    "ew.toggle_countermeasures": EWToggleCountermeasuresPayload,
    "ew.begin_intrusion":        EWBeginIntrusionPayload,
    # Tactical Officer
    "tactical.set_engagement_priority": TacticalSetEngagementPriorityPayload,
    "tactical.set_intercept_target":    TacticalSetInterceptTargetPayload,
    "tactical.add_annotation":          TacticalAddAnnotationPayload,
    "tactical.remove_annotation":       TacticalRemoveAnnotationPayload,
    "tactical.create_strike_plan":      TacticalCreateStrikePlanPayload,
    "tactical.execute_strike_plan":     TacticalExecuteStrikePlanPayload,
    # Damage Control (aliases engineering DCT payloads)
    "damage_control.dispatch_dct": EngineeringDispatchDCTPayload,
    "damage_control.cancel_dct":   EngineeringCancelDCTPayload,
}


def validate_payload(message: Message) -> BaseModel | None:
    """Validate the payload of an inbound message against its type-specific schema.

    Returns the validated payload model if the type has a registered schema.
    Returns None if the type is unrecognised (unknown types are logged elsewhere).
    Raises pydantic.ValidationError if the payload is structurally invalid.
    """
    schema = _PAYLOAD_SCHEMAS.get(message.type)
    if schema is None:
        return None
    return schema.model_validate(message.payload)
