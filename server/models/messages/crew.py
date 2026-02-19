"""Crew inter-station notification payload schema."""
from __future__ import annotations

from pydantic import BaseModel


class CrewNotifyPayload(BaseModel):
    """Sent by any station to broadcast a short notification to all crew."""
    message: str               # text content — max 120 chars enforced in handler
    from_role: str = 'crew'    # sender role label (e.g. 'captain', 'helm')
