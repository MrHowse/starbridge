"""Spinal Mount weapon message payloads (Battleship, v0.07 §2.5)."""
from __future__ import annotations

from pydantic import BaseModel


class WeaponsSpinalChargePayload(BaseModel):
    """Weapons officer requests spinal mount charge on a target."""
    target_id: str


class WeaponsSpinalFirePayload(BaseModel):
    """Weapons officer fires the charged spinal mount."""
    pass


class WeaponsSpinalCancelPayload(BaseModel):
    """Weapons officer cancels the current spinal mount charge."""
    pass
