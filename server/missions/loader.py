"""
Mission Loader — Parse mission JSON files.

Reads mission definition files from the missions/ directory and converts
them into runtime mission dicts for the mission engine.

The "sandbox" mission is a built-in synthetic dict that spawns no enemies
from JSON (the game loop's _spawn_enemies() handles sandbox spawning).
"""
from __future__ import annotations

import json
from pathlib import Path

from server.models.world import Asteroid, Hazard, World, spawn_creature, spawn_enemy, spawn_enemy_station, spawn_hazard, spawn_station

# missions/ directory is at the project root (two levels up from this file).
_MISSIONS_DIR = Path(__file__).parent.parent.parent / "missions"

_SANDBOX_MISSION: dict = {
    "id": "sandbox",
    "name": "Sandbox",
    "briefing": "Free play mode. No objectives.",
    "spawn": [],
    "nodes": [],
    "edges": [],
    "start_node": None,
    "victory_nodes": [],
    "defeat_condition": None,
}


def load_mission(mission_id: str) -> dict:
    """Load a mission by ID.

    Returns the synthetic sandbox dict for mission_id == "sandbox".
    Raises FileNotFoundError if the JSON file does not exist.
    """
    if mission_id == "sandbox":
        return dict(_SANDBOX_MISSION)

    path = _MISSIONS_DIR / f"{mission_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Mission file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def spawn_from_mission(mission: dict, world: World, entity_counter: int) -> int:
    """Spawn entities listed in the mission's 'spawn' and 'spawn_initial_wave' arrays.

    'spawn' entries with type "station" create Station objects added to world.stations.
    All other 'spawn' entries and all 'spawn_initial_wave' entries create Enemy objects.
    Returns the updated entity_counter.
    """
    for entry in mission.get("spawn", []):
        if entry["type"] == "station":
            world.stations.append(
                spawn_station(entry["id"], float(entry["x"]), float(entry["y"]))
            )
        elif entry["type"] == "enemy_station":
            world.stations.append(
                spawn_enemy_station(
                    entry["id"],
                    float(entry["x"]),
                    float(entry["y"]),
                    entry.get("variant", "outpost"),
                )
            )
        elif entry["type"] == "creature":
            world.creatures.append(
                spawn_creature(entry["id"], entry["creature_type"], float(entry["x"]), float(entry["y"]))
            )
        else:
            world.enemies.append(
                spawn_enemy(
                    entry["type"],  # type: ignore[arg-type]
                    float(entry["x"]),
                    float(entry["y"]),
                    entry["id"],
                )
            )

    # Spawn initial enemy wave (used by defend_station to seed wave 1 separately).
    for entry in mission.get("spawn_initial_wave", []):
        world.enemies.append(
            spawn_enemy(
                entry["type"],  # type: ignore[arg-type]
                float(entry["x"]),
                float(entry["y"]),
                entry["id"],
            )
        )

    # Spawn asteroid field (Mission 3).
    for i, entry in enumerate(mission.get("asteroids", [])):
        world.asteroids.append(
            Asteroid(
                id=entry.get("id", f"asteroid_{i}"),
                x=float(entry["x"]),
                y=float(entry["y"]),
                radius=float(entry.get("radius", 1_000.0)),
            )
        )

    # Spawn hazard zones (Session 2c).
    for i, entry in enumerate(mission.get("hazards", [])):
        world.hazards.append(
            spawn_hazard(
                hazard_id=entry.get("id", f"hazard_{i}"),
                x=float(entry["x"]),
                y=float(entry["y"]),
                radius=float(entry.get("radius", 10_000.0)),
                hazard_type=entry.get("hazard_type", "nebula"),
                label=entry.get("label"),
            )
        )

    return entity_counter


def spawn_wave(wave_enemies: list[dict], world: World) -> None:
    """Spawn a list of enemy entries into the world (used by on_complete: spawn_wave)."""
    for entry in wave_enemies:
        world.enemies.append(
            spawn_enemy(
                entry["type"],  # type: ignore[arg-type]
                float(entry["x"]),
                float(entry["y"]),
                entry["id"],
            )
        )
