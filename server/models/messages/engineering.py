"""Engineering message payload schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

VALID_SYSTEMS: frozenset[str] = frozenset(
    {"engines", "beams", "torpedoes", "shields", "sensors", "manoeuvring", "flight_deck", "ecm_suite"}
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


class EngineeringDispatchDCTPayload(BaseModel):
    room_id: str


class EngineeringCancelDCTPayload(BaseModel):
    room_id: str
