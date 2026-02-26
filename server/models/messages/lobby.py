"""Lobby message payload schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Role = Literal["captain", "helm", "weapons", "engineering", "science", "medical", "security", "comms", "viewscreen", "flight_ops", "electronic_warfare", "tactical", "damage_control", "janitor"]

VALID_ROLES: frozenset[str] = frozenset(
    {"captain", "helm", "weapons", "engineering", "science", "medical", "security", "comms", "viewscreen", "flight_ops", "electronic_warfare", "tactical", "damage_control", "janitor"}
)


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


class LobbyStatePayload(BaseModel):
    roles: dict[str, str | None]  # role → player_name | None
    host: str
    session_id: str


class LobbyErrorPayload(BaseModel):
    message: str
