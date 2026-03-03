"""Message envelope and payload validation dispatcher."""
from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from server.models.messages.captain import CaptainAcceptMissionPayload, CaptainAcknowledgeAllStopPayload, CaptainAddLogPayload, CaptainAuthorizePayload, CaptainDeclineMissionPayload, CaptainReassignCrewPayload, CaptainSaveGamePayload, CaptainSetAlertPayload, CaptainSetGeneralOrderPayload, CaptainSetPriorityTargetPayload, CaptainSystemOverridePayload
from server.models.messages.negotiation import (
    NegotiationOpenChannelPayload,
    NegotiationCloseChannelPayload,
    NegotiationStartPayload,
    NegotiationAcceptPayload,
    NegotiationCounterPayload,
    NegotiationWalkAwayPayload,
    NegotiationAcceptCallbackPayload,
    NegotiationInspectPayload,
    NegotiationBluffPayload,
    NegotiationBarterPayload,
    NegotiationServiceContractPayload,
)
from server.models.messages.salvage import (
    SalvageAssessPayload,
    SalvageCancelAssessmentPayload,
    SalvageSelectItemsPayload,
    SalvageBeginPayload,
    SalvageCancelPayload,
)
from server.models.messages.rationing import (
    RationingSetLevelPayload,
    RationingCaptainOverridePayload,
    RationingSubmitRequestPayload,
    RationingApproveRequestPayload,
    RationingDenyRequestPayload,
)
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
    SecurityLockdownAllPayload,
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
    EWToggleStealthPayload,
    EWDeployGhostPayload,
    EWRecallGhostPayload,
    EWSetGhostClassPayload,
    EWSetFreqLockPayload,
    EWBeginIntrusionPayload,
)
from server.models.messages.operations import (
    OperationsPingPayload,
    OpsStartAssessmentPayload,
    OpsCancelAssessmentPayload,
    OpsSetVulnerableFacingPayload,
    OpsSetPrioritySubsystemPayload,
    OpsTogglePredictionPayload,
    OpsSetThreatLevelPayload,
    OpsSetWeaponsHelmSyncPayload,
    OpsCancelWeaponsHelmSyncPayload,
    OpsSetSensorFocusPayload,
    OpsCancelSensorFocusPayload,
    OpsStartDamageCoordinationPayload,
    OpsIssueEvasionAlertPayload,
    OpsMarkObjectivePayload,
    OpsStationAdvisoryPayload,
    OpsRequestScanPayload,
)
from server.models.messages.hazard_control import (
    HazConSuppressLocalPayload,
    HazConSuppressDeckPayload,
    HazConVentRoomPayload,
    HazConCancelVentPayload,
    HazConDispatchFireTeamPayload,
    HazConCancelFireTeamPayload,
    HazConForceFieldPayload,
    HazConSealBulkheadPayload,
    HazConUnsealBulkheadPayload,
    HazConOrderEvacuationPayload,
    HazConCycleVentPayload,
    HazConSetVentPayload,
    HazConEmergencyVentSpacePayload,
    HazConCancelSpaceVentPayload,
    HazConDispatchDeconTeamPayload,
    HazConCancelDeconTeamPayload,
    HazConReinforceSectionPayload,
    HazConCancelReinforcementPayload,
    HazConSealConnectionPayload,
    HazConUnsealConnectionPayload,
    HazConOverrideSecurityLockPayload,
    HazConRedirectBatteryPayload,
    HazConSetEvacuationOrderPayload,
    HazConLaunchPodPayload,
    AbandonShipPayload,
)
from server.models.messages.engineering import (
    EngineeringCancelDCTPayload,
    EngineeringCancelRepairOrderPayload,
    EngineeringDispatchBreachRepairPayload,
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
from server.models.messages.game import GameBriefingLaunchPayload, GameBriefingReadyPayload
from server.models.messages.janitor import JanitorPerformTaskPayload, JanitorDismissStickyPayload
from server.models.messages.flag_bridge import (
    FlagBridgeAddDrawingPayload,
    FlagBridgeRemoveDrawingPayload,
    FlagBridgeClearDrawingsPayload,
    FlagBridgeSetPriorityPayload,
    FlagBridgeClearPriorityPayload,
    FlagBridgeWeaponsOverridePayload,
    FlagBridgeFleetOrderPayload,
)
from server.models.messages.spinal_mount import (
    WeaponsSpinalChargePayload,
    WeaponsSpinalFirePayload,
    WeaponsSpinalCancelPayload,
)
from server.models.messages.medical_ship import MedicalSurgicalProcedurePayload
from server.models.messages.carrier_ops import (
    CarrierCancelCAPPayload,
    CarrierCancelScramblePayload,
    CarrierCreateSquadronPayload,
    CarrierDisbandSquadronPayload,
    CarrierScramblePayload,
    CarrierSetCAPPayload,
    CarrierSquadronOrderPayload,
)
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
    "engineering.dispatch_breach_repair": EngineeringDispatchBreachRepairPayload,
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
    "captain.set_priority_target": CaptainSetPriorityTargetPayload,
    "captain.set_general_order": CaptainSetGeneralOrderPayload,
    "captain.acknowledge_all_stop": CaptainAcknowledgeAllStopPayload,
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
    "security.lockdown_all": SecurityLockdownAllPayload,
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
    "ew.toggle_stealth":         EWToggleStealthPayload,
    "ew.deploy_ghost":           EWDeployGhostPayload,
    "ew.recall_ghost":           EWRecallGhostPayload,
    "ew.set_ghost_class":        EWSetGhostClassPayload,
    "ew.set_freq_lock":          EWSetFreqLockPayload,
    # Operations (replaces Tactical — v0.08)
    "operations.ping": OperationsPingPayload,
    "operations.start_assessment": OpsStartAssessmentPayload,
    "operations.cancel_assessment": OpsCancelAssessmentPayload,
    "operations.set_vulnerable_facing": OpsSetVulnerableFacingPayload,
    "operations.set_priority_subsystem": OpsSetPrioritySubsystemPayload,
    "operations.toggle_prediction": OpsTogglePredictionPayload,
    "operations.set_threat_level": OpsSetThreatLevelPayload,
    "operations.set_weapons_helm_sync": OpsSetWeaponsHelmSyncPayload,
    "operations.cancel_weapons_helm_sync": OpsCancelWeaponsHelmSyncPayload,
    "operations.set_sensor_focus": OpsSetSensorFocusPayload,
    "operations.cancel_sensor_focus": OpsCancelSensorFocusPayload,
    "operations.start_damage_coordination": OpsStartDamageCoordinationPayload,
    "operations.issue_evasion_alert": OpsIssueEvasionAlertPayload,
    "operations.mark_objective": OpsMarkObjectivePayload,
    "operations.station_advisory": OpsStationAdvisoryPayload,
    "operations.request_scan": OpsRequestScanPayload,
    # Hazard Control
    "hazard_control.dispatch_dct":        EngineeringDispatchDCTPayload,
    "hazard_control.cancel_dct":          EngineeringCancelDCTPayload,
    "hazard_control.suppress_local":      HazConSuppressLocalPayload,
    "hazard_control.suppress_deck":       HazConSuppressDeckPayload,
    "hazard_control.vent_room":           HazConVentRoomPayload,
    "hazard_control.cancel_vent":         HazConCancelVentPayload,
    "hazard_control.dispatch_fire_team":  HazConDispatchFireTeamPayload,
    "hazard_control.cancel_fire_team":    HazConCancelFireTeamPayload,
    # Atmosphere (v0.08 B.3)
    "hazard_control.force_field":          HazConForceFieldPayload,
    "hazard_control.seal_bulkhead":        HazConSealBulkheadPayload,
    "hazard_control.unseal_bulkhead":      HazConUnsealBulkheadPayload,
    "hazard_control.order_evacuation":     HazConOrderEvacuationPayload,
    "hazard_control.cycle_vent":           HazConCycleVentPayload,
    "hazard_control.set_vent":             HazConSetVentPayload,
    "hazard_control.emergency_vent_space": HazConEmergencyVentSpacePayload,
    "hazard_control.cancel_space_vent":    HazConCancelSpaceVentPayload,
    # Radiation (v0.08 B.4)
    "hazard_control.dispatch_decon_team":  HazConDispatchDeconTeamPayload,
    "hazard_control.cancel_decon_team":    HazConCancelDeconTeamPayload,
    # Structural Integrity (v0.08 B.5)
    "hazard_control.reinforce_section":    HazConReinforceSectionPayload,
    "hazard_control.cancel_reinforcement": HazConCancelReinforcementPayload,
    # Emergency Systems (v0.08 B.6)
    "hazard_control.seal_connection":        HazConSealConnectionPayload,
    "hazard_control.unseal_connection":      HazConUnsealConnectionPayload,
    "hazard_control.override_security_lock": HazConOverrideSecurityLockPayload,
    "hazard_control.redirect_battery":       HazConRedirectBatteryPayload,
    "hazard_control.set_evacuation_order":   HazConSetEvacuationOrderPayload,
    "hazard_control.launch_pod":             HazConLaunchPodPayload,
    "captain.abandon_ship":                  AbandonShipPayload,
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
    "game.briefing_ready": GameBriefingReadyPayload,
    # Janitor (secret station)
    "janitor.perform_task": JanitorPerformTaskPayload,
    "janitor.dismiss_sticky": JanitorDismissStickyPayload,
    # Flag Bridge (Cruiser Captain)
    "captain.flag_add_drawing":    FlagBridgeAddDrawingPayload,
    "captain.flag_remove_drawing": FlagBridgeRemoveDrawingPayload,
    "captain.flag_clear_drawings": FlagBridgeClearDrawingsPayload,
    "captain.flag_set_priority":   FlagBridgeSetPriorityPayload,
    "captain.flag_clear_priority": FlagBridgeClearPriorityPayload,
    "weapons.override_priority":   FlagBridgeWeaponsOverridePayload,
    "captain.fleet_order":         FlagBridgeFleetOrderPayload,
    # Spinal Mount (Battleship)
    "weapons.spinal_charge":       WeaponsSpinalChargePayload,
    "weapons.spinal_fire":         WeaponsSpinalFirePayload,
    "weapons.spinal_cancel":       WeaponsSpinalCancelPayload,
    # Carrier Ops
    "carrier.create_squadron":     CarrierCreateSquadronPayload,
    "carrier.disband_squadron":    CarrierDisbandSquadronPayload,
    "carrier.squadron_order":      CarrierSquadronOrderPayload,
    "carrier.set_cap":             CarrierSetCAPPayload,
    "carrier.cancel_cap":          CarrierCancelCAPPayload,
    "carrier.scramble":            CarrierScramblePayload,
    "carrier.cancel_scramble":     CarrierCancelScramblePayload,
    # Medical Ship (v0.07 §2.7)
    "medical.surgical_procedure":  MedicalSurgicalProcedurePayload,
    # Negotiation (v0.07 §6.3)
    "negotiation.open_channel":      NegotiationOpenChannelPayload,
    "negotiation.close_channel":     NegotiationCloseChannelPayload,
    "negotiation.start":             NegotiationStartPayload,
    "negotiation.accept":            NegotiationAcceptPayload,
    "negotiation.counter":           NegotiationCounterPayload,
    "negotiation.walk_away":         NegotiationWalkAwayPayload,
    "negotiation.accept_callback":   NegotiationAcceptCallbackPayload,
    "negotiation.inspect":           NegotiationInspectPayload,
    "negotiation.bluff":             NegotiationBluffPayload,
    "negotiation.barter":            NegotiationBarterPayload,
    "negotiation.service_contract":  NegotiationServiceContractPayload,
    # Salvage (v0.07 §6.5)
    "salvage.assess":              SalvageAssessPayload,
    "salvage.cancel_assessment":   SalvageCancelAssessmentPayload,
    "salvage.select_items":        SalvageSelectItemsPayload,
    "salvage.begin_salvage":       SalvageBeginPayload,
    "salvage.cancel_salvage":      SalvageCancelPayload,
    # Rationing (v0.07 §6.6)
    "rationing.set_level":           RationingSetLevelPayload,
    "rationing.captain_override":    RationingCaptainOverridePayload,
    "rationing.submit_request":      RationingSubmitRequestPayload,
    "rationing.approve_request":     RationingApproveRequestPayload,
    "rationing.deny_request":        RationingDenyRequestPayload,
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
