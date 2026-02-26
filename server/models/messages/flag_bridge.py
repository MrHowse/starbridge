"""Flag Bridge (Cruiser Captain) message payload schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class FlagBridgeAddDrawingPayload(BaseModel):
    drawing_type: str  # waypoint, arrow, danger_zone, objective
    x: float
    y: float
    x2: float | None = None  # for arrows: end point
    y2: float | None = None
    label: str = ""
    colour: str = "#ffaa00"


class FlagBridgeRemoveDrawingPayload(BaseModel):
    drawing_id: str


class FlagBridgeClearDrawingsPayload(BaseModel):
    pass


class FlagBridgeSetPriorityPayload(BaseModel):
    entity_ids: list[str] = Field(default_factory=list)


class FlagBridgeClearPriorityPayload(BaseModel):
    pass


class FlagBridgeWeaponsOverridePayload(BaseModel):
    override: bool = True


class FlagBridgeFleetOrderPayload(BaseModel):
    order_type: str
    target_id: str | None = None
    x: float | None = None
    y: float | None = None
