"""Captain message payload schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class CaptainSetAlertPayload(BaseModel):
    level: Literal["green", "yellow", "red"]
