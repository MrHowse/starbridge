"""Message envelope and payload validation dispatcher."""
from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from server.models.messages.captain import CaptainAcceptMissionPayload, CaptainAddLogPayload, CaptainAuthorizePayload, CaptainDeclineMissionPayload, CaptainReassignCrewPayload, CaptainSaveGamePayload, CaptainSetAlertPayload, CaptainSystemOverridePayload
from server.models.messages.comms import (
    CommsAssessDistressPayload,
    CommsDecodeSignalPayload,
    CommsDismissSignalPayload,
    CommsHailPayload,
    CommsProbePayload,
    CommsRespondPayload,
    CommsRouteIntelPayload,
    CommsSetChannelPayload,
    CommsTuneFrequencyPayload,
)
from server.models.messages.medical import (
    MedicalAdmitPayload,
    MedicalCancelTreatmentPayload,
    MedicalDischargePayload,
    MedicalQuarantinePayload,
    MedicalStabilisePayload,
    MedicalTreatCrewPayload,
    MedicalTreatPayload,
)
from server.models.messages.puzzle import PuzzleAssistPayload, PuzzleCancelPayload, PuzzleSubmitPayload
from server.models.messages.security import (
    SecurityMoveSquadPayload,
    SecurityToggleDoorPayload,
    SecuritySendTeamPayload,
    SecuritySetPatrolPayload,
    SecurityStationTeamPayload,
    SecurityDisengageTeamPayload,
    SecurityAssignEscortPayload,
    SecurityLockDoorPayload,
    SecurityUnlockDoorPayload,
    SecurityLockdownDeckPayload,
    SecurityLiftLockdownPayload,
    SecuritySealBulkheadPayload,
    SecurityUnsealBulkheadPayload,
    SecuritySetDeckAlertPayload,
    SecurityArmCrewPayload,
    SecurityDisarmCrewPayload,
    SecurityQuarantineRoomPayload,
    SecurityLiftQuarantinePayload,
)
from server.models.messages.flight_ops import (
    FlightOpsAbortLandingPayload,
    FlightOpsClearToLandPayload,
    FlightOpsDeployBuoyPayload,
    FlightOpsCancelLaunchPayload,
    FlightOpsDeployDecoyPayload,
    FlightOpsDesignateTargetPayload,
    FlightOpsEscortAssignPayload,
    FlightOpsLaunchDronePayload,
    FlightOpsPrioritiseRecoveryPayload,
    FlightOpsRecallDronePayload,
    FlightOpsRushTurnaroundPayload,
    FlightOpsSetBehaviourPayload,
    FlightOpsSetEngagementRulesPayload,
    FlightOpsSetLoiterPointPayload,
    FlightOpsSetWaypointPayload,
    FlightOpsSetWaypointsPayload,
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
    EngineeringCancelRepairOrderPayload,
    EngineeringDispatchDCTPayload,
    EngineeringDispatchTeamPayload,
    EngineeringRecallTeamPayload,
    EngineeringRequestEscortPayload,
    EngineeringSetBatteryModePayload,
    EngineeringSetPowerPayload,
    EngineeringSetRepairPayload,
    EngineeringStartReroutePayload,
)
from server.models.messages.helm import HelmSetHeadingPayload, HelmSetThrottlePayload
from server.models.messages.lobby import LobbyClaimRolePayload, LobbyReleaseRolePayload, LobbyStartGamePayload
from server.models.messages.science import (
    ScienceCancelScanPayload,
    ScienceCancelSectorScanPayload,
    ScienceScanInterruptResponsePayload,
    ScienceStartScanPayload,
    ScienceStartSectorScanPayload,
)
from server.models.messages.crew import CrewNotifyPayload
from server.models.messages.creatures import (
    CreatureSedatePayload,
    CreatureEWDisruptPayload,
    CreatureCommProgressPayload,
    CreatureLeeechRemovePayload,
)
from server.models.messages.docking import (
    CaptainUndockPayload,
    DockingCancelServicePayload,
    DockingRequestClearancePayload,
    DockingStartServicePayload,
)
from server.models.messages.game import GameBriefingLaunchPayload
from server.models.messages.navigation import MapClearRoutePayload, MapPlotRoutePayload
from server.models.messages.weapons import (
    WeaponsFireBeamsPayload,
    WeaponsFireTorpedoPayload,
    WeaponsLoadTubePayload,
    WeaponsSelectTargetPayload,
    WeaponsSetShieldFocusPayload,
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
    "engineering.set_power":            EngineeringSetPowerPayload,
    "engineering.set_repair":           EngineeringSetRepairPayload,
    "engineering.dispatch_dct":         EngineeringDispatchDCTPayload,
    "engineering.cancel_dct":           EngineeringCancelDCTPayload,
    "engineering.dispatch_team":        EngineeringDispatchTeamPayload,
    "engineering.recall_team":          EngineeringRecallTeamPayload,
    "engineering.set_battery_mode":     EngineeringSetBatteryModePayload,
    "engineering.start_reroute":        EngineeringStartReroutePayload,
    "engineering.request_escort":       EngineeringRequestEscortPayload,
    "engineering.cancel_repair_order":  EngineeringCancelRepairOrderPayload,
    # Weapons
    "weapons.select_target": WeaponsSelectTargetPayload,
    "weapons.fire_beams": WeaponsFireBeamsPayload,
    "weapons.fire_torpedo": WeaponsFireTorpedoPayload,
    "weapons.load_tube": WeaponsLoadTubePayload,
    "weapons.set_shield_focus": WeaponsSetShieldFocusPayload,
    # Science
    "science.start_scan": ScienceStartScanPayload,
    "science.cancel_scan": ScienceCancelScanPayload,
    "science.start_sector_scan": ScienceStartSectorScanPayload,
    "science.cancel_sector_scan": ScienceCancelSectorScanPayload,
    "science.scan_interrupt_response": ScienceScanInterruptResponsePayload,
    # Captain
    "captain.set_alert": CaptainSetAlertPayload,
    "captain.authorize": CaptainAuthorizePayload,
    "captain.add_log": CaptainAddLogPayload,
    "captain.system_override": CaptainSystemOverridePayload,
    "captain.save_game": CaptainSaveGamePayload,
    "captain.reassign_crew": CaptainReassignCrewPayload,
    "captain.accept_mission": CaptainAcceptMissionPayload,
    "captain.decline_mission": CaptainDeclineMissionPayload,
    "captain.undock": CaptainUndockPayload,
    # Medical (legacy)
    "medical.treat_crew": MedicalTreatCrewPayload,
    "medical.cancel_treatment": MedicalCancelTreatmentPayload,
    # Medical (v0.06.1 individual crew)
    "medical.admit": MedicalAdmitPayload,
    "medical.treat": MedicalTreatPayload,
    "medical.stabilise": MedicalStabilisePayload,
    "medical.discharge": MedicalDischargePayload,
    "medical.quarantine": MedicalQuarantinePayload,
    # Security
    "security.move_squad": SecurityMoveSquadPayload,
    "security.toggle_door": SecurityToggleDoorPayload,
    "security.send_team": SecuritySendTeamPayload,
    "security.set_patrol": SecuritySetPatrolPayload,
    "security.station_team": SecurityStationTeamPayload,
    "security.disengage_team": SecurityDisengageTeamPayload,
    "security.assign_escort": SecurityAssignEscortPayload,
    "security.lock_door": SecurityLockDoorPayload,
    "security.unlock_door": SecurityUnlockDoorPayload,
    "security.lockdown_deck": SecurityLockdownDeckPayload,
    "security.lift_lockdown": SecurityLiftLockdownPayload,
    "security.seal_bulkhead": SecuritySealBulkheadPayload,
    "security.unseal_bulkhead": SecurityUnsealBulkheadPayload,
    "security.set_deck_alert": SecuritySetDeckAlertPayload,
    "security.arm_crew": SecurityArmCrewPayload,
    "security.disarm_crew": SecurityDisarmCrewPayload,
    "security.quarantine_room": SecurityQuarantineRoomPayload,
    "security.lift_quarantine": SecurityLiftQuarantinePayload,
    # Comms
    "comms.tune_frequency":    CommsTuneFrequencyPayload,
    "comms.hail":              CommsHailPayload,
    "comms.decode_signal":     CommsDecodeSignalPayload,
    "comms.respond":           CommsRespondPayload,
    "comms.route_intel":       CommsRouteIntelPayload,
    "comms.set_channel":       CommsSetChannelPayload,
    "comms.probe":             CommsProbePayload,
    "comms.assess_distress":   CommsAssessDistressPayload,
    "comms.dismiss_signal":    CommsDismissSignalPayload,
    # Puzzle
    "puzzle.submit": PuzzleSubmitPayload,
    "puzzle.request_assist": PuzzleAssistPayload,
    "puzzle.cancel": PuzzleCancelPayload,
    # Flight Ops
    "flight_ops.launch_drone":          FlightOpsLaunchDronePayload,
    "flight_ops.recall_drone":          FlightOpsRecallDronePayload,
    "flight_ops.set_waypoint":          FlightOpsSetWaypointPayload,
    "flight_ops.set_loiter_point":      FlightOpsSetLoiterPointPayload,
    "flight_ops.set_waypoints":         FlightOpsSetWaypointsPayload,
    "flight_ops.set_engagement_rules":  FlightOpsSetEngagementRulesPayload,
    "flight_ops.set_behaviour":         FlightOpsSetBehaviourPayload,
    "flight_ops.designate_target":      FlightOpsDesignateTargetPayload,
    "flight_ops.deploy_decoy":          FlightOpsDeployDecoyPayload,
    "flight_ops.deploy_buoy":           FlightOpsDeployBuoyPayload,
    "flight_ops.escort_assign":         FlightOpsEscortAssignPayload,
    "flight_ops.clear_to_land":         FlightOpsClearToLandPayload,
    "flight_ops.rush_turnaround":       FlightOpsRushTurnaroundPayload,
    "flight_ops.abort_landing":         FlightOpsAbortLandingPayload,
    "flight_ops.cancel_launch":         FlightOpsCancelLaunchPayload,
    "flight_ops.prioritise_recovery":   FlightOpsPrioritiseRecoveryPayload,
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
    # Creatures (v0.05k)
    "creature.sedate":            CreatureSedatePayload,
    "creature.ew_disrupt":        CreatureEWDisruptPayload,
    "creature.set_comm_progress": CreatureCommProgressPayload,
    "creature.leech_remove":      CreatureLeeechRemovePayload,
    # Docking (v0.05f)
    "docking.request_clearance": DockingRequestClearancePayload,
    "docking.start_service":     DockingStartServicePayload,
    "docking.cancel_service":    DockingCancelServicePayload,
    # Navigation
    "map.plot_route":  MapPlotRoutePayload,
    "map.clear_route": MapClearRoutePayload,
    # Crew
    "crew.notify": CrewNotifyPayload,
    # Game
    "game.briefing_launch": GameBriefingLaunchPayload,
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
