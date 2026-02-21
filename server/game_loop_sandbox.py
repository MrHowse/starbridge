"""Sandbox Activity Generator.

Periodically generates events across all station domains so that every
role has meaningful work during free-play and solo-play sessions.
Only active when mission_id == "sandbox".

Events returned from tick():
  {"type": "spawn_enemy",   "enemy_type": str, "x": float, "y": float, "id": str}
  {"type": "system_damage", "system": str, "amount": float}
  {"type": "crew_casualty", "deck": str, "count": int}
  {"type": "start_boarding","intruders": list[dict]}
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.models.world import World

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

# Seconds between each class of event (min, max).
ENEMY_SPAWN_INTERVAL:   tuple[float, float] = (60.0,  90.0)
SYSTEM_DAMAGE_INTERVAL: tuple[float, float] = (45.0,  75.0)
CREW_CASUALTY_INTERVAL: tuple[float, float] = (60.0, 100.0)
BOARDING_INTERVAL:      tuple[float, float] = (120.0, 180.0)

# Hard cap on simultaneous sandbox enemies (initial 2 + up to 4 spawned).
MAX_ENEMIES: int = 6

# Systems eligible for environmental damage events (Engineering / DC work).
DAMAGEABLE_SYSTEMS: list[str] = [
    "engines", "shields", "beams", "torpedoes", "sensors", "manoeuvring",
    "flight_deck", "ecm_suite",
]

# All crew decks that can receive casualties (Medical work).
CREW_DECKS: list[str] = [
    "bridge", "sensors", "weapons", "shields", "engineering", "medical",
]

# Enemy type pool — scouts more common so combat stays manageable solo.
ENEMY_TYPE_POOL: list[str] = [
    "scout", "scout", "scout", "cruiser",
]

# Spawn distance from the player ship.
SPAWN_DIST_MIN: float = 20_000.0
SPAWN_DIST_MAX: float = 35_000.0

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_active: bool = False
_timers: dict[str, float] = {}
_entity_counter: int = 0   # offset counter for unique IDs

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset(active: bool = False) -> None:
    """Reset sandbox scheduler.  Pass active=True to start the scheduler."""
    global _active, _entity_counter
    _active = active
    _entity_counter = 1000    # offset well above mission-spawned entity IDs
    _timers.clear()
    if active:
        # Stagger initial timers so all events don't fire simultaneously.
        _timers["enemy_spawn"]   = random.uniform(30.0, 60.0)   # first wave sooner
        _timers["system_damage"] = random.uniform(30.0, 50.0)
        _timers["crew_casualty"] = random.uniform(45.0, 75.0)
        _timers["boarding"]      = random.uniform(90.0, 120.0)


def is_active() -> bool:
    """Return True if the sandbox scheduler is running."""
    return _active


def tick(world: "World", dt: float) -> list[dict]:
    """Advance all timers by *dt* seconds.  Return event dicts to process."""
    if not _active:
        return []

    global _entity_counter

    for key in list(_timers):
        _timers[key] -= dt

    events: list[dict] = []

    # --- Enemy spawn (Weapons / Helm / Science / EW / Flight Ops) --------
    if _timers.get("enemy_spawn", 1.0) <= 0.0:
        if len(world.enemies) < MAX_ENEMIES:
            enemy_type = random.choice(ENEMY_TYPE_POOL)
            angle = random.uniform(0.0, 360.0)
            dist  = random.uniform(SPAWN_DIST_MIN, SPAWN_DIST_MAX)
            sx    = world.ship.x + math.cos(math.radians(angle)) * dist
            sy    = world.ship.y + math.sin(math.radians(angle)) * dist
            # Clamp to world bounds with a safe margin.
            sx = max(5_000.0, min(world.width  - 5_000.0, sx))
            sy = max(5_000.0, min(world.height - 5_000.0, sy))
            _entity_counter += 1
            events.append({
                "type":       "spawn_enemy",
                "enemy_type": enemy_type,
                "x":          sx,
                "y":          sy,
                "id":         f"sb_e{_entity_counter}",
            })
        _timers["enemy_spawn"] = random.uniform(*ENEMY_SPAWN_INTERVAL)

    # --- System damage — micrometeorite / power surge (Engineering / DC) --
    if _timers.get("system_damage", 1.0) <= 0.0:
        system = random.choice(DAMAGEABLE_SYSTEMS)
        if system in world.ship.systems:
            amount = round(random.uniform(8.0, 20.0), 1)
            events.append({"type": "system_damage", "system": system, "amount": amount})
        _timers["system_damage"] = random.uniform(*SYSTEM_DAMAGE_INTERVAL)

    # --- Crew casualty — accident on a random deck (Medical) --------------
    if _timers.get("crew_casualty", 1.0) <= 0.0:
        deck = random.choice(CREW_DECKS)
        events.append({"type": "crew_casualty", "deck": deck, "count": 1})
        _timers["crew_casualty"] = random.uniform(*CREW_CASUALTY_INTERVAL)

    # --- Boarding attempt (Security) --------------------------------------
    if _timers.get("boarding", 1.0) <= 0.0:
        _entity_counter += 1
        events.append({
            "type": "start_boarding",
            "intruders": [
                {"id": f"sb_i{_entity_counter}",     "room_id": "conn", "objective_id": None},
                {"id": f"sb_i{_entity_counter + 1}", "room_id": "conn", "objective_id": None},
            ],
        })
        _entity_counter += 1
        _timers["boarding"] = random.uniform(*BOARDING_INTERVAL)

    return events
