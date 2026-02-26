"""
Mining Equipment — Game Loop Integration (v0.07 §2.3).

Provides asteroid mining when the Mining Equipment module is installed.
Engineering station targets an asteroid, holds a mining beam for
MINING_BEAM_DURATION seconds, then receives fuel and material resources.

Lifecycle: reset(active) → start_mining() / cancel_mining() from handlers
→ tick() each frame → build_state() for broadcast.
"""
from __future__ import annotations

from server.models.ship import Ship
from server.models.world import World
from server.utils.math_helpers import distance

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MINING_BEAM_RANGE: float = 5_000.0      # world units — must be within range to mine
MINING_BEAM_DURATION: float = 10.0      # seconds to complete one extraction
MINING_COOLDOWN: float = 5.0            # seconds between extractions
MINING_YIELD_FUEL: float = 20.0         # fuel units per extraction
MINING_YIELD_MATERIALS: float = 10.0    # material units per extraction

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_mining_active: bool = False             # True when mining module is installed
_target_asteroid_id: str | None = None
_mining_progress: float = 0.0           # 0.0–100.0
_mining_cooldown: float = 0.0
_mined_resources: dict[str, float] = {"fuel": 0.0, "materials": 0.0}
_total_extractions: int = 0

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset(active: bool = False) -> None:
    """Reset mining state. *active* should be True when the module is installed."""
    global _mining_active, _target_asteroid_id, _mining_progress
    global _mining_cooldown, _mined_resources, _total_extractions
    _mining_active = active
    _target_asteroid_id = None
    _mining_progress = 0.0
    _mining_cooldown = 0.0
    _mined_resources = {"fuel": 0.0, "materials": 0.0}
    _total_extractions = 0


def is_active() -> bool:
    """True when the mining equipment module is installed and active."""
    return _mining_active


def start_mining(asteroid_id: str, ship: Ship, world: World) -> dict:
    """Begin mining an asteroid.

    Validates: module active, not already mining, cooldown clear, asteroid
    exists and is within range.

    Returns status dict with "ok" bool and optional "reason".
    """
    global _target_asteroid_id, _mining_progress
    if not _mining_active:
        return {"ok": False, "reason": "not_equipped"}
    if _target_asteroid_id is not None:
        return {"ok": False, "reason": "already_mining"}
    if _mining_cooldown > 0.0:
        return {"ok": False, "reason": "cooldown", "remaining": round(_mining_cooldown, 1)}

    # Find the asteroid.
    asteroid = None
    for a in world.asteroids:
        if a.id == asteroid_id:
            asteroid = a
            break
    if asteroid is None:
        return {"ok": False, "reason": "not_found"}

    dist = distance(ship.x, ship.y, asteroid.x, asteroid.y)
    if dist > MINING_BEAM_RANGE:
        return {"ok": False, "reason": "out_of_range", "distance": round(dist, 1)}

    _target_asteroid_id = asteroid_id
    _mining_progress = 0.0
    return {"ok": True, "target": asteroid_id}


def cancel_mining() -> dict:
    """Cancel an in-progress mining operation. Progress is lost."""
    global _target_asteroid_id, _mining_progress
    if _target_asteroid_id is None:
        return {"ok": False, "reason": "not_mining"}
    _target_asteroid_id = None
    _mining_progress = 0.0
    return {"ok": True}


def tick(ship: Ship, world: World, dt: float) -> list[dict]:
    """Advance mining state each tick.

    Returns a list of event dicts (0 or 1) when extraction completes.
    Also decays cooldown timer.
    """
    global _mining_cooldown, _mining_progress, _target_asteroid_id
    global _total_extractions

    events: list[dict] = []

    if not _mining_active:
        return events

    # Decay cooldown.
    if _mining_cooldown > 0.0:
        _mining_cooldown = max(0.0, _mining_cooldown - dt)

    if _target_asteroid_id is None:
        return events

    # Verify target still exists and is within range.
    asteroid = None
    for a in world.asteroids:
        if a.id == _target_asteroid_id:
            asteroid = a
            break
    if asteroid is None:
        _target_asteroid_id = None
        _mining_progress = 0.0
        events.append({"event": "mining.cancelled", "reason": "target_lost"})
        return events

    dist = distance(ship.x, ship.y, asteroid.x, asteroid.y)
    if dist > MINING_BEAM_RANGE:
        _target_asteroid_id = None
        _mining_progress = 0.0
        events.append({"event": "mining.cancelled", "reason": "out_of_range"})
        return events

    # Advance mining progress.
    progress_per_sec = 100.0 / MINING_BEAM_DURATION
    _mining_progress = min(100.0, _mining_progress + progress_per_sec * dt)

    if _mining_progress >= 100.0:
        # Extraction complete!
        fuel_yield = MINING_YIELD_FUEL
        materials_yield = MINING_YIELD_MATERIALS

        _mined_resources["fuel"] += fuel_yield
        _mined_resources["materials"] += materials_yield
        _total_extractions += 1

        # Add to ship cargo if it has cargo capacity.
        if ship.cargo_capacity > 0.0:
            current_total = sum(ship.cargo.values())
            space = ship.cargo_capacity - current_total
            if space > 0.0:
                fuel_add = min(fuel_yield, space)
                ship.cargo["fuel"] = ship.cargo.get("fuel", 0.0) + fuel_add
                space -= fuel_add
                if space > 0.0:
                    mat_add = min(materials_yield, space)
                    ship.cargo["materials"] = ship.cargo.get("materials", 0.0) + mat_add

        events.append({
            "event": "mining.complete",
            "asteroid_id": _target_asteroid_id,
            "fuel": fuel_yield,
            "materials": materials_yield,
            "total_extractions": _total_extractions,
        })

        _target_asteroid_id = None
        _mining_progress = 0.0
        _mining_cooldown = MINING_COOLDOWN

    return events


def build_state() -> dict:
    """Build mining state for broadcast."""
    return {
        "mining_active": _mining_active,
        "target_asteroid_id": _target_asteroid_id,
        "mining_progress": round(_mining_progress, 1),
        "mining_cooldown": round(_mining_cooldown, 1),
        "mined_resources": dict(_mined_resources),
        "total_extractions": _total_extractions,
    }


def serialise() -> dict:
    """Capture mining state for save/resume."""
    return {
        "mining_active": _mining_active,
        "target_asteroid_id": _target_asteroid_id,
        "mining_progress": _mining_progress,
        "mining_cooldown": _mining_cooldown,
        "mined_resources": dict(_mined_resources),
        "total_extractions": _total_extractions,
    }


def deserialise(data: dict) -> None:
    """Restore mining state from save data."""
    global _mining_active, _target_asteroid_id, _mining_progress
    global _mining_cooldown, _mined_resources, _total_extractions
    _mining_active = data.get("mining_active", False)
    _target_asteroid_id = data.get("target_asteroid_id")
    _mining_progress = data.get("mining_progress", 0.0)
    _mining_cooldown = data.get("mining_cooldown", 0.0)
    _mined_resources = dict(data.get("mined_resources", {"fuel": 0.0, "materials": 0.0}))
    _total_extractions = data.get("total_extractions", 0)
