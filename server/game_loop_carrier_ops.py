"""
Carrier Flight Control Centre — Carrier-only (v0.07 §2.6).

Squadron management, CAP zones, scramble launch.  Layers on top of
game_loop_flight_ops for carrier-class ships.

Module-level state pattern: call reset() before use.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import server.game_loop_flight_ops as glfo

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRAMBLE_LAUNCH_INTERVAL: float = 3.0   # seconds between scramble launches
CAP_ZONE_MIN_DRONES: int = 2
CAP_ZONE_MAX_DRONES: int = 4
CAP_FUEL_RTB_THRESHOLD: float = 30.0    # % fuel → rotate home
CAP_PATROL_RADIUS_FACTOR: float = 0.7   # orbit at 70 % of zone radius
MAX_SQUADRONS: int = 4
MAX_SQUADRON_SIZE: int = 6

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Squadron:
    id: str
    name: str
    drone_ids: list[str] = field(default_factory=list)


@dataclass
class CAPZone:
    centre_x: float
    centre_y: float
    radius: float
    assigned_drone_ids: list[str] = field(default_factory=list)
    active: bool = True


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_carrier_active: bool = False
_squadrons: dict[str, Squadron] = {}
_squadron_counter: int = 0
_cap_zone: CAPZone | None = None
_scramble_active: bool = False
_scramble_queue: list[str] = []
_scramble_timer: float = 0.0


# ---------------------------------------------------------------------------
# Public API — lifecycle
# ---------------------------------------------------------------------------


def reset(active: bool = False) -> None:
    """Initialise (or clear) carrier ops state."""
    global _carrier_active, _squadrons, _squadron_counter
    global _cap_zone, _scramble_active, _scramble_queue, _scramble_timer
    _carrier_active = active
    _squadrons = {}
    _squadron_counter = 0
    _cap_zone = None
    _scramble_active = False
    _scramble_queue = []
    _scramble_timer = 0.0


def is_active() -> bool:
    return _carrier_active


# ---------------------------------------------------------------------------
# Squadron management
# ---------------------------------------------------------------------------


def create_squadron(name: str, drone_ids: list[str]) -> dict:
    """Create a named squadron from a list of drone IDs."""
    global _squadron_counter

    if not _carrier_active:
        return {"ok": False, "error": "Carrier ops not available on this ship class."}
    if len(_squadrons) >= MAX_SQUADRONS:
        return {"ok": False, "error": f"Maximum {MAX_SQUADRONS} squadrons."}
    if not drone_ids or len(drone_ids) > MAX_SQUADRON_SIZE:
        return {"ok": False, "error": f"Squadron size must be 1–{MAX_SQUADRON_SIZE}."}

    # Validate all drone IDs exist.
    for did in drone_ids:
        if glfo.get_drone_by_id(did) is None:
            return {"ok": False, "error": f"Drone '{did}' not found."}

    _squadron_counter += 1
    sq_id = f"sq-{_squadron_counter}"
    _squadrons[sq_id] = Squadron(id=sq_id, name=name, drone_ids=list(drone_ids))
    return {"ok": True, "squadron_id": sq_id}


def disband_squadron(squadron_id: str) -> dict:
    """Remove a squadron."""
    if not _carrier_active:
        return {"ok": False, "error": "Carrier ops not available on this ship class."}
    if squadron_id not in _squadrons:
        return {"ok": False, "error": f"Squadron '{squadron_id}' not found."}
    del _squadrons[squadron_id]
    return {"ok": True}


def get_squadrons() -> dict[str, Squadron]:
    return _squadrons


def squadron_order(squadron_id: str, order: str, ship: Any = None, **kwargs: Any) -> dict:
    """Issue an order to every drone in a squadron.

    Supported orders: launch, recall, set_waypoint, set_behaviour,
    set_engagement_rules.
    """
    if not _carrier_active:
        return {"ok": False, "error": "Carrier ops not available on this ship class."}
    sq = _squadrons.get(squadron_id)
    if sq is None:
        return {"ok": False, "error": f"Squadron '{squadron_id}' not found."}

    results: list[dict] = []
    for did in sq.drone_ids:
        if order == "launch":
            ok = glfo.launch_drone(did, ship) if ship else False
            results.append({"drone_id": did, "ok": ok})
        elif order == "recall":
            ok = glfo.recall_drone(did)
            results.append({"drone_id": did, "ok": ok})
        elif order == "set_waypoint":
            x = kwargs.get("x", 0.0)
            y = kwargs.get("y", 0.0)
            ok = glfo.set_waypoint(did, x, y)
            results.append({"drone_id": did, "ok": ok})
        elif order == "set_behaviour":
            behaviour = kwargs.get("behaviour", "patrol")
            ok = glfo.set_behaviour(did, behaviour)
            results.append({"drone_id": did, "ok": ok})
        elif order == "set_engagement_rules":
            rules = kwargs.get("rules", "weapons_free")
            ok = glfo.set_engagement_rules(did, rules)
            results.append({"drone_id": did, "ok": ok})
        else:
            return {"ok": False, "error": f"Unknown order '{order}'."}

    return {"ok": True, "results": results}


# ---------------------------------------------------------------------------
# CAP zone
# ---------------------------------------------------------------------------


def set_cap_zone(centre_x: float, centre_y: float, radius: float,
                 drone_ids: list[str]) -> dict:
    """Set a Combat Air Patrol zone."""
    global _cap_zone

    if not _carrier_active:
        return {"ok": False, "error": "Carrier ops not available on this ship class."}
    if len(drone_ids) < CAP_ZONE_MIN_DRONES:
        return {"ok": False, "error": f"CAP requires at least {CAP_ZONE_MIN_DRONES} drones."}
    if len(drone_ids) > CAP_ZONE_MAX_DRONES:
        return {"ok": False, "error": f"CAP allows at most {CAP_ZONE_MAX_DRONES} drones."}
    if radius <= 0:
        return {"ok": False, "error": "CAP zone radius must be positive."}

    # Validate drones exist.
    for did in drone_ids:
        drone = glfo.get_drone_by_id(did)
        if drone is None:
            return {"ok": False, "error": f"Drone '{did}' not found."}
        if drone.status not in ("active", "hangar"):
            return {"ok": False, "error": f"Drone '{did}' is not available (status={drone.status})."}

    _cap_zone = CAPZone(
        centre_x=centre_x,
        centre_y=centre_y,
        radius=radius,
        assigned_drone_ids=list(drone_ids),
    )

    # Set patrol waypoints for active CAP drones.
    _assign_cap_patrol_waypoints()

    return {"ok": True}


def cancel_cap() -> dict:
    """Cancel the CAP zone."""
    global _cap_zone

    if not _carrier_active:
        return {"ok": False, "error": "Carrier ops not available on this ship class."}
    if _cap_zone is None:
        return {"ok": False, "error": "No active CAP zone."}

    _cap_zone = None
    return {"ok": True}


def get_cap_zone() -> CAPZone | None:
    return _cap_zone


def _assign_cap_patrol_waypoints() -> None:
    """Set patrol waypoints for active CAP drones around the zone."""
    if _cap_zone is None:
        return
    patrol_r = _cap_zone.radius * CAP_PATROL_RADIUS_FACTOR
    n = len(_cap_zone.assigned_drone_ids)
    for i, did in enumerate(_cap_zone.assigned_drone_ids):
        drone = glfo.get_drone_by_id(did)
        if drone is None or drone.status != "active":
            continue
        # Distribute waypoints evenly around the zone.
        angles = []
        for j in range(4):
            angle = (2 * math.pi / 4) * j + (2 * math.pi / n) * i
            wx = _cap_zone.centre_x + math.cos(angle) * patrol_r
            wy = _cap_zone.centre_y + math.sin(angle) * patrol_r
            angles.append((wx, wy))
        glfo.set_waypoints(did, angles)
        glfo.set_engagement_rules(did, "weapons_free")


# ---------------------------------------------------------------------------
# Scramble
# ---------------------------------------------------------------------------


def scramble(ship: Any) -> dict:
    """Queue all hangar-ready drones for rapid launch."""
    global _scramble_active, _scramble_queue, _scramble_timer

    if not _carrier_active:
        return {"ok": False, "error": "Carrier ops not available on this ship class."}
    if _scramble_active:
        return {"ok": False, "error": "Scramble already in progress."}

    ready = [d for d in glfo.get_drones() if d.status == "hangar"]
    if not ready:
        return {"ok": False, "error": "No drones ready for launch."}

    _scramble_queue = [d.id for d in ready]
    _scramble_active = True
    _scramble_timer = 0.0  # launch first drone immediately

    # Activate scramble mode in flight ops for reduced launch time.
    glfo.set_scramble_mode(True)

    return {"ok": True, "queued": len(_scramble_queue)}


def cancel_scramble() -> dict:
    """Cancel an in-progress scramble."""
    global _scramble_active, _scramble_queue, _scramble_timer

    if not _carrier_active:
        return {"ok": False, "error": "Carrier ops not available on this ship class."}
    if not _scramble_active:
        return {"ok": False, "error": "No scramble in progress."}

    _scramble_active = False
    _scramble_queue = []
    _scramble_timer = 0.0
    glfo.set_scramble_mode(False)
    return {"ok": True}


def get_scramble_active() -> bool:
    return _scramble_active


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


def tick(ship: Any, dt: float) -> list[dict]:
    """Advance carrier ops by dt seconds. Returns list of event dicts."""
    global _scramble_active, _scramble_timer

    if not _carrier_active:
        return []

    events: list[dict] = []

    # --- Scramble processing ---
    if _scramble_active and _scramble_queue:
        _scramble_timer -= dt
        while _scramble_timer <= 0 and _scramble_queue:
            drone_id = _scramble_queue.pop(0)
            drone = glfo.get_drone_by_id(drone_id)
            if drone is not None and drone.status == "hangar":
                glfo.launch_drone(drone_id, ship)
                events.append({
                    "type": "scramble_launch",
                    "drone_id": drone_id,
                })
            _scramble_timer += SCRAMBLE_LAUNCH_INTERVAL

        if not _scramble_queue:
            _scramble_active = False
            _scramble_timer = 0.0
            glfo.set_scramble_mode(False)
            events.append({"type": "scramble_complete"})

    # --- CAP rotation ---
    if _cap_zone is not None and _cap_zone.active:
        events.extend(_tick_cap(ship))

    return events


def _tick_cap(ship: Any) -> list[dict]:
    """Check CAP drone fuel and rotate as needed."""
    events: list[dict] = []
    if _cap_zone is None:
        return events

    for did in list(_cap_zone.assigned_drone_ids):
        drone = glfo.get_drone_by_id(did)
        if drone is None:
            continue

        # Fuel low → RTB rotation.
        if drone.status == "active" and drone.fuel <= CAP_FUEL_RTB_THRESHOLD:
            glfo.recall_drone(did)
            events.append({
                "type": "cap_drone_rotating",
                "drone_id": did,
                "reason": "low_fuel",
            })

        # If drone is back in hangar after turnaround, relaunch for CAP.
        if drone.status == "hangar":
            if glfo.launch_drone(did, ship):
                events.append({
                    "type": "cap_drone_relaunched",
                    "drone_id": did,
                })

        # Refresh patrol waypoints for active CAP drones periodically.
        if drone.status == "active" and not drone.waypoints:
            _assign_cap_patrol_waypoints()

    return events


# ---------------------------------------------------------------------------
# Build state for broadcast
# ---------------------------------------------------------------------------


def build_state() -> dict:
    """Carrier ops state for broadcast."""
    if not _carrier_active:
        return {"active": False}

    sq_data = {}
    for sq_id, sq in _squadrons.items():
        sq_data[sq_id] = {
            "name": sq.name,
            "drone_ids": list(sq.drone_ids),
        }

    cap_data = None
    if _cap_zone is not None:
        cap_data = {
            "centre_x": round(_cap_zone.centre_x, 1),
            "centre_y": round(_cap_zone.centre_y, 1),
            "radius": round(_cap_zone.radius, 1),
            "assigned_drone_ids": list(_cap_zone.assigned_drone_ids),
            "active": _cap_zone.active,
        }

    return {
        "active": True,
        "squadrons": sq_data,
        "cap_zone": cap_data,
        "scramble_active": _scramble_active,
        "scramble_queue_remaining": len(_scramble_queue),
    }


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def serialise() -> dict:
    sq_data = {}
    for sq_id, sq in _squadrons.items():
        sq_data[sq_id] = {
            "name": sq.name,
            "drone_ids": list(sq.drone_ids),
        }

    cap_data = None
    if _cap_zone is not None:
        cap_data = {
            "centre_x": _cap_zone.centre_x,
            "centre_y": _cap_zone.centre_y,
            "radius": _cap_zone.radius,
            "assigned_drone_ids": list(_cap_zone.assigned_drone_ids),
            "active": _cap_zone.active,
        }

    return {
        "active": _carrier_active,
        "squadrons": sq_data,
        "squadron_counter": _squadron_counter,
        "cap_zone": cap_data,
        "scramble_active": _scramble_active,
        "scramble_queue": list(_scramble_queue),
        "scramble_timer": round(_scramble_timer, 3),
    }


def deserialise(data: dict) -> None:
    global _carrier_active, _squadrons, _squadron_counter
    global _cap_zone, _scramble_active, _scramble_queue, _scramble_timer

    _carrier_active = data.get("active", False)
    _squadron_counter = data.get("squadron_counter", 0)

    _squadrons = {}
    for sq_id, sq_data in data.get("squadrons", {}).items():
        _squadrons[sq_id] = Squadron(
            id=sq_id,
            name=sq_data["name"],
            drone_ids=list(sq_data["drone_ids"]),
        )

    cap_data = data.get("cap_zone")
    if cap_data is not None:
        _cap_zone = CAPZone(
            centre_x=cap_data["centre_x"],
            centre_y=cap_data["centre_y"],
            radius=cap_data["radius"],
            assigned_drone_ids=list(cap_data["assigned_drone_ids"]),
            active=cap_data.get("active", True),
        )
    else:
        _cap_zone = None

    _scramble_active = data.get("scramble_active", False)
    _scramble_queue = list(data.get("scramble_queue", []))
    _scramble_timer = data.get("scramble_timer", 0.0)
