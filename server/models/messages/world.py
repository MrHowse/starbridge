"""World entity message payload schemas."""
from __future__ import annotations

from pydantic import BaseModel


class ShipStatePayload(BaseModel):
    """Shape of the ship.state payload broadcast each game tick."""

    position: dict[str, float]            # {"x": float, "y": float}
    heading: float
    velocity: float
    throttle: float
    hull: float
    shields: dict[str, float]             # {"front": float, "rear": float}
    systems: dict[str, dict[str, float]]  # {name: {"power", "health", "efficiency"}}
    alert_level: str
