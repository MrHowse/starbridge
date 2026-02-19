"""
Mission Model — Mission, Objective, Trigger, Event.

Pydantic models documenting the schema of mission definition files loaded
from missions/<id>.json by server/missions/loader.py.

These models are NOT used to validate the live dicts passed around at
runtime (the mission engine works with raw dicts for performance). They
serve as the canonical schema reference and can be used for authoring-time
validation of new mission JSON files.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

TriggerType = Literal[
    "player_in_area",
    "scan_completed",
    "entity_destroyed",
    "all_enemies_destroyed",
    "player_hull_zero",
    "timer_elapsed",
    "wave_defeated",
    "station_hull_below",
    "signal_located",
    "proximity_with_shields",
]


class TriggerDefinition(BaseModel):
    """A trigger condition checked each tick to complete an objective."""

    type: TriggerType
    args: dict[str, Any] = {}   # type-specific arguments (x/y/r, entity_id, seconds, etc.)


class EventDefinition(BaseModel):
    """An on_complete side-effect action triggered when an objective completes."""

    action: Literal["spawn_wave"]
    enemies: list[dict[str, Any]] = []   # list of spawn entries with type/x/y/id


class ObjectiveDefinition(BaseModel):
    """A single mission objective as read from the JSON file."""

    id: str
    text: str
    trigger: TriggerType | None = None
    args: dict[str, Any] = {}
    on_complete: EventDefinition | None = None


class SpawnEntry(BaseModel):
    """An entity to spawn at mission start."""

    id: str
    type: str   # "scout", "cruiser", "destroyer", "station"
    x: float
    y: float


class AsteroidEntry(BaseModel):
    """An asteroid in the mission's asteroid field."""

    id: str = ""
    x: float
    y: float
    radius: float = 1_000.0


class MissionDefinition(BaseModel):
    """Complete mission definition as loaded from a JSON file."""

    id: str
    name: str
    briefing: str = ""
    spawn: list[SpawnEntry] = []
    spawn_initial_wave: list[SpawnEntry] = []
    objectives: list[ObjectiveDefinition] = []
    victory_condition: Literal["all_objectives_complete"] | None = None
    defeat_condition: Literal["player_hull_zero"] | None = None
    defeat_condition_alt: dict[str, Any] | None = None
    signal_location: dict[str, float] | None = None   # {"x": float, "y": float}
    asteroids: list[AsteroidEntry] = []
