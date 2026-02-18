"""
WebSocket Message Schemas.

Pydantic models for all WebSocket messages. Defines the envelope format,
payload schemas for each message type, and validation logic.
See docs/MESSAGE_PROTOCOL.md for the full protocol reference.
"""
from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Client → Server payload schemas
# ---------------------------------------------------------------------------

Role = Literal["captain", "helm", "weapons", "engineering", "science"]

VALID_ROLES: frozenset[str] = frozenset(
    {"captain", "helm", "weapons", "engineering", "science"}
)


class LobbyClaimRolePayload(BaseModel):
    role: Role
    player_name: str = Field(min_length=1, max_length=20)

    @field_validator("player_name")
    @classmethod
    def player_name_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("player_name cannot be blank")
        return stripped


class LobbyReleaseRolePayload(BaseModel):
    pass


class LobbyStartGamePayload(BaseModel):
    mission_id: str


# Phase 2 — Helm control inputs
class HelmSetHeadingPayload(BaseModel):
    heading: float = Field(ge=0.0, lt=360.0)


class HelmSetThrottlePayload(BaseModel):
    throttle: float = Field(ge=0.0, le=100.0)


# Phase 3 — Engineering control inputs
VALID_SYSTEMS: frozenset[str] = frozenset(
    {"engines", "beams", "torpedoes", "shields", "sensors", "manoeuvring"}
)


class EngineeringSetPowerPayload(BaseModel):
    system: str
    level: float = Field(ge=0.0, le=150.0)

    @field_validator("system")
    @classmethod
    def system_must_be_valid(cls, v: str) -> str:
        if v not in VALID_SYSTEMS:
            raise ValueError(f"Unknown system: {v!r}")
        return v


class EngineeringSetRepairPayload(BaseModel):
    system: str

    @field_validator("system")
    @classmethod
    def system_must_be_valid(cls, v: str) -> str:
        if v not in VALID_SYSTEMS:
            raise ValueError(f"Unknown system: {v!r}")
        return v


# ---------------------------------------------------------------------------
# Server → Client payload schemas (Phase 1)
# ---------------------------------------------------------------------------


class LobbyStatePayload(BaseModel):
    roles: dict[str, str | None]  # role → player_name | None
    host: str
    session_id: str


class LobbyErrorPayload(BaseModel):
    message: str


class ErrorValidationPayload(BaseModel):
    message: str
    original_type: str


class ErrorPermissionPayload(BaseModel):
    message: str
    original_type: str


class ErrorStatePayload(BaseModel):
    message: str
    original_type: str


class GameStartedPayload(BaseModel):
    mission_id: str
    mission_name: str
    briefing_text: str


class GameTickPayload(BaseModel):
    tick: int
    timestamp: float


class GameOverPayload(BaseModel):
    result: Literal["victory", "defeat"]
    stats: dict[str, Any]


# Phase 2 — server → client (documentation schema; not used for inbound validation)
class ShipStatePayload(BaseModel):
    """Shape of the ship.state payload broadcast each game tick."""

    position: dict[str, float]        # {"x": float, "y": float}
    heading: float
    velocity: float
    throttle: float
    hull: float
    shields: dict[str, float]         # {"front": float, "rear": float}
    systems: dict[str, dict[str, float]]  # {name: {"power", "health", "efficiency"}}
    alert_level: str


# ---------------------------------------------------------------------------
# Payload validation dispatcher
# ---------------------------------------------------------------------------

_PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    # Phase 1 — Lobby
    "lobby.claim_role": LobbyClaimRolePayload,
    "lobby.release_role": LobbyReleaseRolePayload,
    "lobby.start_game": LobbyStartGamePayload,
    # Phase 2 — Helm
    "helm.set_heading": HelmSetHeadingPayload,
    "helm.set_throttle": HelmSetThrottlePayload,
    # Phase 3 — Engineering
    "engineering.set_power": EngineeringSetPowerPayload,
    "engineering.set_repair": EngineeringSetRepairPayload,
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
