"""Docking State Machine — v0.05f.

States:
  none → clearance_pending → sequencing → docked → undocking → none

Clearance:
  Friendly stations: auto-granted after CLEARANCE_DELAY_FRIENDLY seconds.
  Neutral stations:  auto-granted after CLEARANCE_DELAY_NEUTRAL seconds.
  Hostile stations:  denied immediately.

While docked:
  - ship.velocity = 0, ship.throttle = 0 (engines offline).
  - ship.shields capped at SHIELDS_DOCKED_CAP.
  - Services run in parallel; each has its own countdown timer.

Services apply effects on completion (hull_repair, system_repair, etc.).
"""
from __future__ import annotations

import logging
import math

logger = logging.getLogger("starbridge.docking")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DOCK_APPROACH_MAX_THROTTLE: float = 10.0    # max throttle % allowed to initiate dock
CLEARANCE_DELAY_FRIENDLY: float = 2.0       # seconds until auto-grant (friendly)
CLEARANCE_DELAY_NEUTRAL: float = 4.0        # seconds until auto-grant (neutral)
DOCKING_SEQUENCE_DURATION: float = 10.0     # seconds for docking animation
UNDOCKING_DURATION: float = 5.0             # seconds for undocking animation
SHIELDS_DOCKED_CAP: float = 50.0            # max shield % while docked

SERVICE_DURATIONS: dict[str, float] = {
    "hull_repair":          45.0,   # reduced: faster pacing during missions
    "torpedo_resupply":     30.0,
    "medical_transfer":     45.0,
    "system_repair":        15.0,   # reduced: quick turnaround in combat
    "atmospheric_resupply": 30.0,
    "sensor_data_package":  30.0,
    "drone_service":        40.0,
    "ew_database_update":   30.0,
    "crew_rest":            60.0,
    "intel_briefing":       30.0,
}

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_state: str = "none"                     # current docking state
_target_station_id: str | None = None    # station being docked with
_sequence_timer: float = 0.0             # countdown for sequencing / undocking
_clearance_timer: float = 0.0            # countdown for clearance grant delay
_active_services: dict[str, float] = {}  # service_name → time_remaining
# Broadcasts queued by synchronous handlers; emitted by tick().
_pending_broadcasts: list[tuple[list[str] | None, str, dict]] = []


# ---------------------------------------------------------------------------
# Reset / serialise
# ---------------------------------------------------------------------------


def reset() -> None:
    """Reset docking state for a new game."""
    global _state, _target_station_id, _sequence_timer, _clearance_timer
    _state = "none"
    _target_station_id = None
    _sequence_timer = 0.0
    _clearance_timer = 0.0
    _active_services.clear()
    _pending_broadcasts.clear()


def serialise() -> dict:
    return {
        "state": _state,
        "target_station_id": _target_station_id,
        "sequence_timer": _sequence_timer,
        "clearance_timer": _clearance_timer,
        "active_services": dict(_active_services),
    }


def deserialise(data: dict) -> None:
    global _state, _target_station_id, _sequence_timer, _clearance_timer
    _state = data.get("state", "none")
    _target_station_id = data.get("target_station_id")
    _sequence_timer = float(data.get("sequence_timer", 0.0))
    _clearance_timer = float(data.get("clearance_timer", 0.0))
    _active_services.clear()
    _active_services.update({k: float(v) for k, v in data.get("active_services", {}).items()})
    _pending_broadcasts.clear()


# ---------------------------------------------------------------------------
# Public accessors
# ---------------------------------------------------------------------------


def is_docked() -> bool:
    return _state == "docked"


def get_state() -> str:
    return _state


def get_docked_station_id() -> str | None:
    return _target_station_id if _state == "docked" else None


def get_active_services() -> dict[str, float]:
    return dict(_active_services)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _emit(roles: list[str] | None, msg_type: str, payload: dict) -> None:
    """Queue a broadcast for tick() to emit."""
    _pending_broadcasts.append((roles, msg_type, payload))


def _find_station(world, station_id: str):
    return next((s for s in world.stations if s.id == station_id), None)


def _apply_service(service: str, world, ship) -> dict:
    """Apply a completed service's effects. Returns effects dict."""
    effects: dict = {}

    if service == "hull_repair":
        restored = ship.hull_max - ship.hull
        ship.hull = ship.hull_max
        effects["hull"] = ship.hull
        effects["hull_restored"] = round(restored, 1)

    elif service == "torpedo_resupply":
        import server.game_loop_weapons as glw
        ammo_max = glw.get_ammo_max()
        for torp_type, max_count in ammo_max.items():
            glw.set_ammo_for_type(torp_type, max_count)
        effects["torpedo_ammo"] = glw.get_ammo()

    elif service == "medical_transfer":
        ship.medical_supplies = min(20, ship.medical_supplies + 10)
        effects["medical_supplies"] = ship.medical_supplies
        # Stabilise up to 2 critical crew per deck (move to injured).
        for deck in ship.crew.decks.values():
            moved = min(deck.critical, 2)
            if moved > 0:
                deck.critical -= moved
                deck.injured += moved
        effects["crew_stabilised"] = True

    elif service == "system_repair":
        import server.game_loop_engineering as gle
        repaired = []
        for name, sys_obj in ship.systems.items():
            if sys_obj.health < 100.0:
                sys_obj.health = 100.0
                gle.repair_all_components(name)
                repaired.append(name)
        effects["systems_repaired"] = repaired

    elif service == "ew_database_update":
        ship.countermeasure_charges = min(20, ship.countermeasure_charges + 5)
        effects["countermeasure_charges"] = ship.countermeasure_charges

    # atmospheric_resupply, sensor_data_package, drone_service,
    # crew_rest, intel_briefing — placeholder (no game effect yet).

    return effects


def _check_approach_proximity(world, ship) -> None:
    """Notify Helm when the ship is in the approach zone of a friendly/neutral station."""
    closest = None
    closest_dist = float("inf")
    for st in world.stations:
        if st.faction == "hostile":
            continue
        dist = math.sqrt((ship.x - st.x) ** 2 + (ship.y - st.y) ** 2)
        approach_zone = st.docking_range * 2.0
        if dist < approach_zone and dist < closest_dist:
            closest = st
            closest_dist = dist

    if closest is not None:
        _emit(["helm"], "docking.approach_info", {
            "station_id": closest.id,
            "station_name": closest.name,
            "distance": round(closest_dist, 0),
            "docking_range": closest.docking_range,
            "in_range": closest_dist <= closest.docking_range,
            "speed_ok": ship.throttle <= DOCK_APPROACH_MAX_THROTTLE,
        })


# ---------------------------------------------------------------------------
# Player action handlers (synchronous — called from _drain_queue)
# ---------------------------------------------------------------------------


def request_clearance(station_id: str, world, ship) -> str | None:
    """Comms requests docking clearance.

    Returns an error string if the request cannot be accepted, None on success.
    The clearance result is broadcast asynchronously in tick().
    """
    global _state, _target_station_id, _clearance_timer

    if _state != "none":
        return "Docking sequence already in progress"

    station = _find_station(world, station_id)
    if station is None:
        return f"Unknown station: {station_id}"

    dist = math.sqrt((ship.x - station.x) ** 2 + (ship.y - station.y) ** 2)
    if dist > station.docking_range:
        return f"Too far from station ({dist:.0f} units, range {station.docking_range:.0f})"

    if ship.throttle > DOCK_APPROACH_MAX_THROTTLE:
        return f"Reduce speed below {DOCK_APPROACH_MAX_THROTTLE:.0f}% throttle to dock"

    if station.faction == "hostile":
        _emit(["comms"], "docking.clearance_denied", {
            "station_id": station_id,
            "reason": "Station is hostile — docking denied",
        })
        return None

    _state = "clearance_pending"
    _target_station_id = station_id
    _clearance_timer = (
        CLEARANCE_DELAY_FRIENDLY if station.faction == "friendly"
        else CLEARANCE_DELAY_NEUTRAL
    )
    _emit(["comms"], "docking.clearance_request", {
        "station_id": station_id,
        "station_name": station.name,
    })
    return None


def start_service(service: str) -> str | None:
    """Request a docking service to begin. Returns error string or None on success."""
    if _state != "docked":
        return "Not docked"
    if service not in SERVICE_DURATIONS:
        return f"Unknown service: {service}"
    if service in _active_services:
        return f"Service already running: {service}"

    _active_services[service] = SERVICE_DURATIONS[service]
    _emit(None, "docking.service_started", {
        "service": service,
        "duration": SERVICE_DURATIONS[service],
    })
    return None


def cancel_service(service: str) -> str | None:
    """Cancel a running service. Returns error string or None on success."""
    if service not in _active_services:
        return f"Service not active: {service}"
    del _active_services[service]
    _emit(None, "docking.service_cancelled", {"service": service})
    return None


def captain_undock(emergency: bool = False) -> str | None:
    """Captain orders undock. Returns error string or None on success."""
    global _state, _sequence_timer, _target_station_id

    if _state not in ("docked", "sequencing"):
        return "Not docked"

    _active_services.clear()
    sid = _target_station_id

    if emergency:
        _state = "none"
        _target_station_id = None
        _sequence_timer = 0.0
        _emit(None, "docking.undocked", {"emergency": True, "station_id": sid})
    else:
        _state = "undocking"
        _sequence_timer = UNDOCKING_DURATION
        _emit(None, "docking.undock_started", {"emergency": False, "station_id": sid})

    return None


# ---------------------------------------------------------------------------
# Tick (called every game tick from game_loop._loop)
# ---------------------------------------------------------------------------


async def tick(world, ship, manager, dt: float) -> None:
    """Advance the docking state machine and apply physics constraints."""
    global _state, _sequence_timer, _clearance_timer, _target_station_id

    from server.models.messages import Message

    # --- Physics constraints while sequencing / docked ---
    if _state in ("sequencing", "docked"):
        ship.velocity = 0.0
        ship.throttle = 0.0
    # Shields capped for all non-flight docking states.
    if _state in ("sequencing", "docked", "undocking"):
        for _facing in ("fore", "aft", "port", "starboard"):
            setattr(ship.shields, _facing, min(getattr(ship.shields, _facing), SHIELDS_DOCKED_CAP))

    # --- State machine transitions ---
    if _state == "clearance_pending":
        _clearance_timer -= dt
        if _clearance_timer <= 0.0:
            station = _find_station(world, _target_station_id)
            if station is None:
                _state = "none"
                _target_station_id = None
            else:
                _state = "sequencing"
                _sequence_timer = DOCKING_SEQUENCE_DURATION
                _emit(None, "docking.clearance_granted", {
                    "station_id": station.id,
                    "station_name": station.name,
                    "services": list(station.services),
                })
                _emit(None, "docking.sequence_started", {
                    "station_id": station.id,
                    "duration": DOCKING_SEQUENCE_DURATION,
                })

    elif _state == "sequencing":
        _sequence_timer -= dt
        if _sequence_timer <= 0.0:
            station = _find_station(world, _target_station_id)
            if station is None:
                _state = "none"
                _target_station_id = None
            else:
                _state = "docked"
                ship.docked_at = station.id
                _emit(None, "docking.complete", {
                    "station_id": station.id,
                    "station_name": station.name,
                    "services": list(station.services),
                })

    elif _state == "docked":
        # Tick active services.
        completed_now = []
        for svc, remaining in list(_active_services.items()):
            remaining -= dt
            if remaining <= 0.0:
                completed_now.append(svc)
            else:
                _active_services[svc] = remaining
        for svc in completed_now:
            del _active_services[svc]
            effects = _apply_service(svc, world, ship)
            _emit(None, "docking.service_complete", {
                "service": svc,
                "effects": effects,
            })

    elif _state == "undocking":
        _sequence_timer -= dt
        if _sequence_timer <= 0.0:
            sid = _target_station_id
            _state = "none"
            _target_station_id = None
            _sequence_timer = 0.0
            ship.docked_at = None
            _emit(None, "docking.undocked", {"emergency": False, "station_id": sid})

    # --- Proximity notification for Helm (approach zone, free state only) ---
    if _state == "none" and world.stations:
        _check_approach_proximity(world, ship)

    # --- Emit all pending broadcasts ---
    broadcasts = list(_pending_broadcasts)
    _pending_broadcasts.clear()
    for roles, msg_type, payload in broadcasts:
        bcast = Message.build(msg_type, payload)
        if roles:
            await manager.broadcast_to_roles(roles, bcast)
        else:
            await manager.broadcast(bcast)
