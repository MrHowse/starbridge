"""Engineering message payload schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

VALID_SYSTEMS: frozenset[str] = frozenset(
    {"engines", "beams", "torpedoes", "shields", "sensors", "manoeuvring",
     "flight_deck", "ecm_suite", "point_defence"}
)

VALID_BATTERY_MODES: frozenset[str] = frozenset(
    {"charging", "discharging", "standby", "auto"}
)

VALID_BUSES: frozenset[str] = frozenset({"primary", "secondary"})


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


# --- v0.06.2 new payloads ---


class EngineeringDispatchTeamPayload(BaseModel):
    team_id: str
    system: str

    @field_validator("system")
    @classmethod
    def system_must_be_valid(cls, v: str) -> str:
        if v not in VALID_SYSTEMS:
            raise ValueError(f"Unknown system: {v!r}")
        return v


class EngineeringRecallTeamPayload(BaseModel):
    team_id: str


class EngineeringSetBatteryModePayload(BaseModel):
    mode: str

    @field_validator("mode")
    @classmethod
    def mode_must_be_valid(cls, v: str) -> str:
        if v not in VALID_BATTERY_MODES:
            raise ValueError(f"Unknown battery mode: {v!r}")
        return v


class EngineeringStartReroutePayload(BaseModel):
    target_bus: str

    @field_validator("target_bus")
    @classmethod
    def bus_must_be_valid(cls, v: str) -> str:
        if v not in VALID_BUSES:
            raise ValueError(f"Unknown bus: {v!r}")
        return v


class EngineeringRequestEscortPayload(BaseModel):
    team_id: str


class EngineeringCancelRepairOrderPayload(BaseModel):
    order_id: str
