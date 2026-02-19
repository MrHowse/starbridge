"""Puzzle message payloads — inbound client→server messages."""
from __future__ import annotations

from pydantic import BaseModel


class PuzzleSubmitPayload(BaseModel):
    puzzle_id: str
    submission: dict


class PuzzleAssistPayload(BaseModel):
    puzzle_id: str
    assist_type: str
    data: dict = {}


class PuzzleCancelPayload(BaseModel):
    puzzle_id: str
