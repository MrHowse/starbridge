"""Security station message payload schemas."""
from __future__ import annotations

from pydantic import BaseModel


class SecurityMoveSquadPayload(BaseModel):
    """Move a marine squad one step toward the specified target room."""
    squad_id: str
    room_id: str   # Destination room (squad advances one BFS step per command)


class SecurityToggleDoorPayload(BaseModel):
    """Seal or unseal a door. The acting squad must be in or adjacent to the room."""
    squad_id: str
    room_id: str   # Room whose entry door is toggled
