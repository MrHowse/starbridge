"""Navigation message payload schemas."""
from __future__ import annotations

from pydantic import BaseModel


class MapPlotRoutePayload(BaseModel):
    """Sent by Captain or Helm to plot a route to a destination."""

    to_x: float
    to_y: float


class MapClearRoutePayload(BaseModel):
    """Sent by Captain or Helm to clear the active route."""

    model_config = {"extra": "allow"}  # accepts empty payload {}
