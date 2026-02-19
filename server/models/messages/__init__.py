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
    EngineeringSetPowerPayload,
    EngineeringSetRepairPayload,
)

# Weapons
from server.models.messages.weapons import (
    WeaponsFireBeamsPayload,
    WeaponsFireTorpedoPayload,
    WeaponsSelectTargetPayload,
    WeaponsSetShieldsPayload,
)

# Science
from server.models.messages.science import ScienceCancelScanPayload, ScienceStartScanPayload

# Captain
from server.models.messages.captain import CaptainSetAlertPayload

# Medical
from server.models.messages.medical import MedicalCancelTreatmentPayload, MedicalTreatCrewPayload

# Puzzle
from server.models.messages.puzzle import PuzzleAssistPayload, PuzzleCancelPayload, PuzzleSubmitPayload

# Game lifecycle
from server.models.messages.game import (
    ErrorPermissionPayload,
    ErrorStatePayload,
    ErrorValidationPayload,
    GameOverPayload,
    GameStartedPayload,
    GameTickPayload,
)

# World entities
from server.models.messages.world import ShipStatePayload

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
    # weapons
    "WeaponsSelectTargetPayload",
    "WeaponsFireBeamsPayload",
    "WeaponsFireTorpedoPayload",
    "WeaponsSetShieldsPayload",
    # science
    "ScienceStartScanPayload",
    "ScienceCancelScanPayload",
    # captain
    "CaptainSetAlertPayload",
    # medical
    "MedicalTreatCrewPayload",
    "MedicalCancelTreatmentPayload",
    # puzzle
    "PuzzleSubmitPayload",
    "PuzzleAssistPayload",
    "PuzzleCancelPayload",
    # game
    "ErrorValidationPayload",
    "ErrorPermissionPayload",
    "ErrorStatePayload",
    "GameStartedPayload",
    "GameTickPayload",
    "GameOverPayload",
    # world
    "ShipStatePayload",
]
