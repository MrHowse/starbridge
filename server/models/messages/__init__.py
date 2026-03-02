"""
WebSocket Message Schemas.

Pydantic models for all WebSocket messages. Defines the envelope format,
payload schemas for each message type, and validation logic.
See docs/MESSAGE_PROTOCOL.md for the full protocol reference.

All symbols are re-exported from this package so that existing imports of
the form ``from server.models.messages import X`` continue to work unchanged.
"""
from __future__ import annotations

# Base envelope and dispatcher
from server.models.messages.base import Message, validate_payload

# Lobby
from server.models.messages.lobby import (
    VALID_ROLES,
    LobbyClaimRolePayload,
    LobbyErrorPayload,
    LobbyReleaseRolePayload,
    LobbyStartGamePayload,
    LobbyStatePayload,
    Role,
)

# Helm
from server.models.messages.helm import HelmSetHeadingPayload, HelmSetThrottlePayload

# Engineering
from server.models.messages.engineering import (
    VALID_SYSTEMS,
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

# Weapons
from server.models.messages.weapons import (
    WeaponsFireBeamsPayload,
    WeaponsFireTorpedoPayload,
    WeaponsLoadTubePayload,
    WeaponsSelectTargetPayload,
    WeaponsSetShieldFocusPayload,
)

# Science
from server.models.messages.science import (
    ScienceCancelScanPayload,
    ScienceStartScanPayload,
    ScienceStartSectorScanPayload,
    ScienceCancelSectorScanPayload,
    ScienceScanInterruptResponsePayload,
)

# Captain
from server.models.messages.captain import CaptainAcceptMissionPayload, CaptainAddLogPayload, CaptainAuthorizePayload, CaptainDeclineMissionPayload, CaptainReassignCrewPayload, CaptainSaveGamePayload, CaptainSetAlertPayload, CaptainSystemOverridePayload

# Docking
from server.models.messages.docking import (
    CaptainUndockPayload,
    DockingCancelServicePayload,
    DockingRequestClearancePayload,
    DockingStartServicePayload,
)

# Medical
from server.models.messages.medical import (
    MedicalAdmitPayload,
    MedicalCancelTreatmentPayload,
    MedicalDischargePayload,
    MedicalQuarantinePayload,
    MedicalStabilisePayload,
    MedicalTreatCrewPayload,
    MedicalTreatPayload,
)

# Security
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

# Crew
from server.models.messages.crew import CrewNotifyPayload

# Comms
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

# Puzzle
from server.models.messages.puzzle import PuzzleAssistPayload, PuzzleCancelPayload, PuzzleSubmitPayload

# Flight Ops
from server.models.messages.flight_ops import (
    FlightOpsAbortLandingPayload,
    FlightOpsCancelLaunchPayload,
    FlightOpsClearToLandPayload,
    FlightOpsDeployBuoyPayload,
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

# Electronic Warfare
from server.models.messages.ew import (
    EWBeginIntrusionPayload,
    EWDeployGhostPayload,
    EWRecallGhostPayload,
    EWSetFreqLockPayload,
    EWSetGhostClassPayload,
    EWSetJamTargetPayload,
    EWToggleCountermeasuresPayload,
    EWToggleStealthPayload,
)

# Operations (replaces Tactical Officer — v0.08)
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
)

# Hazard Control (v0.08 B.2 + B.3 + B.4)
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
)

# Game lifecycle
from server.models.messages.game import (
    ErrorPermissionPayload,
    ErrorStatePayload,
    ErrorValidationPayload,
    GameBriefingLaunchPayload,
    GameOverPayload,
    GameStartedPayload,
    GameTickPayload,
)

# World entities
from server.models.messages.world import ShipStatePayload

# Navigation
from server.models.messages.navigation import MapClearRoutePayload, MapPlotRoutePayload

# Creatures (v0.05k)
from server.models.messages.creatures import (
    CreatureSedatePayload,
    CreatureEWDisruptPayload,
    CreatureCommProgressPayload,
    CreatureLeeechRemovePayload,
)

# Janitor (secret station)
from server.models.messages.janitor import (
    JanitorPerformTaskPayload,
    JanitorDismissStickyPayload,
)

# Flag Bridge (Cruiser Captain)
from server.models.messages.flag_bridge import (
    FlagBridgeAddDrawingPayload,
    FlagBridgeRemoveDrawingPayload,
    FlagBridgeClearDrawingsPayload,
    FlagBridgeSetPriorityPayload,
    FlagBridgeClearPriorityPayload,
    FlagBridgeWeaponsOverridePayload,
    FlagBridgeFleetOrderPayload,
)

# Spinal Mount (Battleship)
from server.models.messages.spinal_mount import (
    WeaponsSpinalChargePayload,
    WeaponsSpinalFirePayload,
    WeaponsSpinalCancelPayload,
)

# Medical Ship (v0.07 §2.7)
from server.models.messages.medical_ship import MedicalSurgicalProcedurePayload

# Negotiation (v0.07 §6.3)
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

# Salvage (v0.07 §6.5)
from server.models.messages.salvage import (
    SalvageAssessPayload,
    SalvageCancelAssessmentPayload,
    SalvageSelectItemsPayload,
    SalvageBeginPayload,
    SalvageCancelPayload,
)

# Rationing (v0.07 §6.6)
from server.models.messages.rationing import (
    RationingSetLevelPayload,
    RationingCaptainOverridePayload,
    RationingSubmitRequestPayload,
    RationingApproveRequestPayload,
    RationingDenyRequestPayload,
)

# Carrier Ops
from server.models.messages.carrier_ops import (
    CarrierCancelCAPPayload,
    CarrierCancelScramblePayload,
    CarrierCreateSquadronPayload,
    CarrierDisbandSquadronPayload,
    CarrierScramblePayload,
    CarrierSetCAPPayload,
    CarrierSquadronOrderPayload,
)

__all__ = [
    # base
    "Message",
    "validate_payload",
    # lobby
    "Role",
    "VALID_ROLES",
    "LobbyClaimRolePayload",
    "LobbyReleaseRolePayload",
    "LobbyStartGamePayload",
    "LobbyStatePayload",
    "LobbyErrorPayload",
    # helm
    "HelmSetHeadingPayload",
    "HelmSetThrottlePayload",
    # engineering
    "VALID_SYSTEMS",
    "EngineeringSetPowerPayload",
    "EngineeringSetRepairPayload",
    "EngineeringDispatchDCTPayload",
    "EngineeringCancelDCTPayload",
    "EngineeringDispatchTeamPayload",
    "EngineeringRecallTeamPayload",
    "EngineeringSetBatteryModePayload",
    "EngineeringStartReroutePayload",
    "EngineeringRequestEscortPayload",
    "EngineeringCancelRepairOrderPayload",
    # weapons
    "WeaponsSelectTargetPayload",
    "WeaponsFireBeamsPayload",
    "WeaponsFireTorpedoPayload",
    "WeaponsLoadTubePayload",
    "WeaponsSetShieldFocusPayload",
    # science
    "ScienceStartScanPayload",
    "ScienceCancelScanPayload",
    "ScienceStartSectorScanPayload",
    "ScienceCancelSectorScanPayload",
    "ScienceScanInterruptResponsePayload",
    # captain
    "CaptainSetAlertPayload",
    "CaptainAuthorizePayload",
    "CaptainAddLogPayload",
    "CaptainSystemOverridePayload",
    "CaptainSaveGamePayload",
    "CaptainReassignCrewPayload",
    "CaptainAcceptMissionPayload",
    "CaptainDeclineMissionPayload",
    # docking
    "DockingRequestClearancePayload",
    "DockingStartServicePayload",
    "DockingCancelServicePayload",
    "CaptainUndockPayload",
    # medical
    "MedicalTreatCrewPayload",
    "MedicalCancelTreatmentPayload",
    "MedicalAdmitPayload",
    "MedicalTreatPayload",
    "MedicalStabilisePayload",
    "MedicalDischargePayload",
    "MedicalQuarantinePayload",
    # security
    "SecurityMoveSquadPayload",
    "SecurityToggleDoorPayload",
    "SecuritySendTeamPayload",
    "SecuritySetPatrolPayload",
    "SecurityStationTeamPayload",
    "SecurityDisengageTeamPayload",
    "SecurityAssignEscortPayload",
    "SecurityLockDoorPayload",
    "SecurityUnlockDoorPayload",
    "SecurityLockdownDeckPayload",
    "SecurityLiftLockdownPayload",
    "SecuritySealBulkheadPayload",
    "SecurityUnsealBulkheadPayload",
    "SecuritySetDeckAlertPayload",
    "SecurityArmCrewPayload",
    "SecurityDisarmCrewPayload",
    "SecurityQuarantineRoomPayload",
    "SecurityLiftQuarantinePayload",
    # crew
    "CrewNotifyPayload",
    # comms
    "CommsTuneFrequencyPayload",
    "CommsHailPayload",
    "CommsDecodeSignalPayload",
    "CommsRespondPayload",
    "CommsRouteIntelPayload",
    "CommsSetChannelPayload",
    "CommsProbePayload",
    "CommsAssessDistressPayload",
    "CommsDismissSignalPayload",
    # puzzle
    "PuzzleSubmitPayload",
    "PuzzleAssistPayload",
    "PuzzleCancelPayload",
    # flight ops
    "FlightOpsLaunchDronePayload",
    "FlightOpsRecallDronePayload",
    "FlightOpsSetLoiterPointPayload",
    "FlightOpsSetWaypointPayload",
    "FlightOpsSetWaypointsPayload",
    "FlightOpsSetEngagementRulesPayload",
    "FlightOpsSetBehaviourPayload",
    "FlightOpsDesignateTargetPayload",
    "FlightOpsDeployDecoyPayload",
    "FlightOpsDeployBuoyPayload",
    "FlightOpsEscortAssignPayload",
    "FlightOpsClearToLandPayload",
    "FlightOpsRushTurnaroundPayload",
    "FlightOpsAbortLandingPayload",
    "FlightOpsCancelLaunchPayload",
    "FlightOpsPrioritiseRecoveryPayload",
    # electronic warfare
    "EWSetJamTargetPayload",
    "EWToggleCountermeasuresPayload",
    "EWToggleStealthPayload",
    "EWDeployGhostPayload",
    "EWRecallGhostPayload",
    "EWSetGhostClassPayload",
    "EWSetFreqLockPayload",
    "EWBeginIntrusionPayload",
    # operations (replaces tactical officer — v0.08)
    "OperationsPingPayload",
    "OpsStartAssessmentPayload",
    "OpsCancelAssessmentPayload",
    "OpsSetVulnerableFacingPayload",
    "OpsSetPrioritySubsystemPayload",
    "OpsTogglePredictionPayload",
    "OpsSetThreatLevelPayload",
    "OpsSetWeaponsHelmSyncPayload",
    "OpsCancelWeaponsHelmSyncPayload",
    "OpsSetSensorFocusPayload",
    "OpsCancelSensorFocusPayload",
    "OpsStartDamageCoordinationPayload",
    "OpsIssueEvasionAlertPayload",
    "OpsMarkObjectivePayload",
    "OpsStationAdvisoryPayload",
    # hazard control (v0.08 B.2 + B.3 + B.4)
    "HazConSuppressLocalPayload",
    "HazConSuppressDeckPayload",
    "HazConVentRoomPayload",
    "HazConCancelVentPayload",
    "HazConDispatchFireTeamPayload",
    "HazConCancelFireTeamPayload",
    "HazConForceFieldPayload",
    "HazConSealBulkheadPayload",
    "HazConUnsealBulkheadPayload",
    "HazConOrderEvacuationPayload",
    "HazConCycleVentPayload",
    "HazConSetVentPayload",
    "HazConEmergencyVentSpacePayload",
    "HazConCancelSpaceVentPayload",
    "HazConDispatchDeconTeamPayload",
    "HazConCancelDeconTeamPayload",
    "HazConReinforceSectionPayload",
    "HazConCancelReinforcementPayload",
    # game
    "ErrorValidationPayload",
    "ErrorPermissionPayload",
    "ErrorStatePayload",
    "GameBriefingLaunchPayload",
    "GameStartedPayload",
    "GameTickPayload",
    "GameOverPayload",
    # world
    "ShipStatePayload",
    # navigation
    "MapPlotRoutePayload",
    "MapClearRoutePayload",
    # creatures
    "CreatureSedatePayload",
    "CreatureEWDisruptPayload",
    "CreatureCommProgressPayload",
    "CreatureLeeechRemovePayload",
    # janitor
    "JanitorPerformTaskPayload",
    "JanitorDismissStickyPayload",
    # flag bridge (cruiser captain)
    "FlagBridgeAddDrawingPayload",
    "FlagBridgeRemoveDrawingPayload",
    "FlagBridgeClearDrawingsPayload",
    "FlagBridgeSetPriorityPayload",
    "FlagBridgeClearPriorityPayload",
    "FlagBridgeWeaponsOverridePayload",
    "FlagBridgeFleetOrderPayload",
    # spinal mount (battleship)
    "WeaponsSpinalChargePayload",
    "WeaponsSpinalFirePayload",
    "WeaponsSpinalCancelPayload",
    # carrier ops
    "CarrierCreateSquadronPayload",
    "CarrierDisbandSquadronPayload",
    "CarrierSquadronOrderPayload",
    "CarrierSetCAPPayload",
    "CarrierCancelCAPPayload",
    "CarrierScramblePayload",
    "CarrierCancelScramblePayload",
    # medical ship
    "MedicalSurgicalProcedurePayload",
    # negotiation
    "NegotiationOpenChannelPayload",
    "NegotiationCloseChannelPayload",
    "NegotiationStartPayload",
    "NegotiationAcceptPayload",
    "NegotiationCounterPayload",
    "NegotiationWalkAwayPayload",
    "NegotiationAcceptCallbackPayload",
    "NegotiationInspectPayload",
    "NegotiationBluffPayload",
    "NegotiationBarterPayload",
    "NegotiationServiceContractPayload",
    # salvage
    "SalvageAssessPayload",
    "SalvageCancelAssessmentPayload",
    "SalvageSelectItemsPayload",
    "SalvageBeginPayload",
    "SalvageCancelPayload",
    # rationing
    "RationingSetLevelPayload",
    "RationingCaptainOverridePayload",
    "RationingSubmitRequestPayload",
    "RationingApproveRequestPayload",
    "RationingDenyRequestPayload",
]
