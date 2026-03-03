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


# v0.06.3 — enhanced security message payloads

class SecuritySendTeamPayload(BaseModel):
    """Send a marine team to a destination room."""
    team_id: str
    destination: str


class SecuritySetPatrolPayload(BaseModel):
    """Set a patrol route for a marine team."""
    team_id: str
    route: list[str]


class SecurityStationTeamPayload(BaseModel):
    """Order a marine team to hold position."""
    team_id: str


class SecurityDisengageTeamPayload(BaseModel):
    """Order a marine team to disengage from combat."""
    team_id: str


class SecurityAssignEscortPayload(BaseModel):
    """Assign a marine team to escort a repair team."""
    team_id: str
    repair_team_id: str


class SecurityLockDoorPayload(BaseModel):
    """Lock a room door via security control."""
    room_id: str


class SecurityUnlockDoorPayload(BaseModel):
    """Unlock a room door via security control."""
    room_id: str


class SecurityLockdownDeckPayload(BaseModel):
    """Lock all doors on a deck."""
    deck: int


class SecurityLockdownAllPayload(BaseModel):
    """Lock all doors on all decks."""
    pass


class SecurityLiftLockdownPayload(BaseModel):
    """Lift lockdown on a deck or all decks."""
    deck: int | None = None
    all: bool = False


class SecuritySealBulkheadPayload(BaseModel):
    """Seal an emergency bulkhead between adjacent decks."""
    deck_above: int
    deck_below: int


class SecurityUnsealBulkheadPayload(BaseModel):
    """Start unsealing a bulkhead between adjacent decks."""
    deck_above: int
    deck_below: int


class SecuritySetDeckAlertPayload(BaseModel):
    """Set alert level for a deck."""
    deck: int
    level: str


class SecurityArmCrewPayload(BaseModel):
    """Arm crew on a deck with sidearms."""
    deck: int


class SecurityDisarmCrewPayload(BaseModel):
    """Disarm crew on a deck."""
    deck: int


class SecurityQuarantineRoomPayload(BaseModel):
    """Quarantine a room."""
    room_id: str


class SecurityLiftQuarantinePayload(BaseModel):
    """Lift quarantine on a room."""
    room_id: str
