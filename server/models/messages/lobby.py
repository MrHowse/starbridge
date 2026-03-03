"""Lobby message payload schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Role = Literal["captain", "helm", "weapons", "engineering", "science", "medical", "security", "comms", "viewscreen", "flight_ops", "electronic_warfare", "operations", "hazard_control", "janitor", "quartermaster"]

VALID_ROLES: frozenset[str] = frozenset(
    {"captain", "helm", "weapons", "engineering", "science", "medical", "security", "comms", "viewscreen", "flight_ops", "electronic_warfare", "operations", "hazard_control", "janitor", "quartermaster"}
)

STATION_CALLSIGNS: dict[str, str] = {
    "captain": "CAP",
    "helm": "HELM",
    "weapons": "WEPS",
    "engineering": "ENG",
    "science": "SCI",
    "comms": "COMMS",
    "electronic_warfare": "EW",
    "security": "SEC",
    "medical": "MED",
    "flight_ops": "FOPS",
    "quartermaster": "QM",
    "operations": "OPS",
    "hazard_control": "HAZCON",
}


class LobbyClaimRolePayload(BaseModel):
    role: Role
    player_name: str = Field(min_length=1, max_length=20)
    additional: bool = False  # If True, keep any existing roles (multi-role mode)

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
    difficulty: str = "officer"
    ship_class: str = "frigate"
    equipment_modules: list[str] = []
    loadout: dict | None = None  # v0.07 §3: Pre-mission loadout configuration


class LobbyStatePayload(BaseModel):
    roles: dict[str, str | None]  # role → player_name | None
    host: str
    session_id: str


class LobbyErrorPayload(BaseModel):
    message: str
