"""Creature interaction message payloads (v0.05k)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class CreatureSedatePayload(BaseModel):
    """Comms broadcasts sedation frequency to sedate a rift stalker."""
    creature_id: str


class CreatureEWDisruptPayload(BaseModel):
    """EW disrupts swarm communication frequency, causing dispersal."""
    creature_id: str


class CreatureCommProgressPayload(BaseModel):
    """Comms submits communication progress toward redirecting a creature."""
    creature_id: str
    progress: float  # 0.0 – 100.0


class CreatureLeeechRemovePayload(BaseModel):
    """Request to remove a hull leech by one of three methods."""
    creature_id: str
    method: Literal["depressurise", "electrical", "eva"]
