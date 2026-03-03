"""Game lifecycle message payload schemas."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


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


class GameBriefingLaunchPayload(BaseModel):
    """Sent by captain from the briefing screen to advance all players to stations."""
    pass


class GameBriefingReadyPayload(BaseModel):
    """Sent by each player from the briefing screen to indicate readiness."""
    pass
