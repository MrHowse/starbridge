"""
Flight Operations — Drone and Probe management.

Manages autonomous drone craft and expendable probe buoys deployed by the
Flight Operations Officer station.

Drones:
  hangar    — aboard ship; fuel slowly recharges.
  transit   — flying toward target_x/target_y at DRONE_SPEED.
  deployed  — hovering at target; sensors active; fuel draining.
  returning — flying back to ship; lands when within DRONE_RECOVERY_DIST.

Probes:
  Expendable stationary buoys deployed from probe_stock.
  Create a permanent sensor detection bubble; not recoverable.
"""
from __future__ import annotations

import math

from server.models.flight_ops import (
    DEFAULT_DRONE_COUNT,
    DEFAULT_PROBE_STOCK,
    DRONE_FUEL_DRAIN_DEPLOYED,
    DRONE_FUEL_DRAIN_TRANSIT,
    DRONE_FUEL_REFILL_RATE,
    DRONE_LOW_FUEL,
    DRONE_RECOVERY_DIST,
    DRONE_SENSOR_RANGE_BASE,
    DRONE_SPEED,
    PROBE_SENSOR_RANGE,
    Drone,
    Probe,
)
from server.models.ship import Ship

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_drones: list[Drone] = []
_probes: list[Probe] = []
_probe_stock: int = DEFAULT_PROBE_STOCK


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset(
    drone_count: int = DEFAULT_DRONE_COUNT,
    probe_stock: int = DEFAULT_PROBE_STOCK,
) -> None:
    """Initialise flight ops state. Call at game start."""
    global _drones, _probes, _probe_stock
    _drones = [Drone(id=f"drone_{i + 1}") for i in range(drone_count)]
    _probes = []
    _probe_stock = probe_stock


def get_drones() -> list[Drone]:
    """Return current drone list (read-only intent)."""
    return _drones


def get_probes() -> list[Probe]:
    """Return current probe list (read-only intent)."""
    return _probes


def get_probe_stock() -> int:
    return _probe_stock


def launch_drone(drone_id: str, target_x: float, target_y: float, ship: Ship) -> bool:
    """Launch a hangar drone toward a world target.

    Places the drone at the ship's current position and sets it to transit.
    Returns False if no matching drone or drone is not in hangar.
    """
    drone = next((d for d in _drones if d.id == drone_id), None)
    if drone is None or drone.state != "hangar":
        return False
    drone.x = ship.x
    drone.y = ship.y
    drone.target_x = target_x
    drone.target_y = target_y
    drone.state = "transit"
    return True


def recall_drone(drone_id: str) -> bool:
    """Set a transit or deployed drone to returning.

    Returns False if the drone is in hangar or returning already,
    or does not exist.
    """
    drone = next((d for d in _drones if d.id == drone_id), None)
    if drone is None or drone.state not in ("transit", "deployed"):
        return False
    drone.state = "returning"
    return True


def deploy_probe(target_x: float, target_y: float) -> bool:
    """Consume one probe from stock and place it at the world position.

    Returns False if probe_stock is zero.
    """
    global _probe_stock
    if _probe_stock <= 0:
        return False
    _probe_stock -= 1
    probe_num = len(_probes) + 1
    _probes.append(Probe(id=f"probe_{probe_num}", x=target_x, y=target_y))
    return True


def tick(ship: Ship, dt: float) -> None:
    """Advance all drone states by dt seconds."""
    for drone in _drones:
        _tick_drone(drone, ship, dt)


def get_detection_bubbles(deck_efficiency: float) -> list[tuple[float, float, float]]:
    """Return (x, y, range) tuples for all active drone / probe sensor bubbles.

    Deployed drones scale their range by flight_deck efficiency.
    Probes have a fixed range independent of power.
    """
    bubbles: list[tuple[float, float, float]] = []
    drone_range = DRONE_SENSOR_RANGE_BASE * max(0.01, deck_efficiency)
    for drone in _drones:
        if drone.state == "deployed":
            bubbles.append((drone.x, drone.y, drone_range))
    for probe in _probes:
        bubbles.append((probe.x, probe.y, PROBE_SENSOR_RANGE))
    return bubbles


def build_state(ship: Ship) -> dict:
    """Build the flight_ops.state payload for the Flight Ops client."""
    return {
        "drones": [
            {
                "id": d.id,
                "state": d.state,
                "x": round(d.x, 1),
                "y": round(d.y, 1),
                "target_x": round(d.target_x, 1),
                "target_y": round(d.target_y, 1),
                "fuel": round(d.fuel, 1),
            }
            for d in _drones
        ],
        "probes": [
            {"id": p.id, "x": round(p.x, 1), "y": round(p.y, 1)}
            for p in _probes
        ],
        "probe_stock": _probe_stock,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _tick_drone(drone: Drone, ship: Ship, dt: float) -> None:
    """Update a single drone for one timestep."""
    if drone.state == "hangar":
        drone.fuel = min(100.0, drone.fuel + DRONE_FUEL_REFILL_RATE * dt)

    elif drone.state == "transit":
        drone.fuel = max(0.0, drone.fuel - DRONE_FUEL_DRAIN_TRANSIT * dt)
        dist = _dist(drone.x, drone.y, drone.target_x, drone.target_y)
        if dist <= DRONE_RECOVERY_DIST:
            drone.x = drone.target_x
            drone.y = drone.target_y
            drone.state = "deployed"
        else:
            _move_toward(drone, drone.target_x, drone.target_y, dt)
        # Low-fuel auto-recall (check after potential state change).
        if drone.state == "transit" and drone.fuel <= DRONE_LOW_FUEL:
            drone.state = "returning"

    elif drone.state == "deployed":
        drone.fuel = max(0.0, drone.fuel - DRONE_FUEL_DRAIN_DEPLOYED * dt)
        if drone.fuel <= DRONE_LOW_FUEL:
            drone.state = "returning"

    elif drone.state == "returning":
        dist = _dist(drone.x, drone.y, ship.x, ship.y)
        if dist <= DRONE_RECOVERY_DIST:
            drone.x = ship.x
            drone.y = ship.y
            drone.state = "hangar"
        else:
            _move_toward(drone, ship.x, ship.y, dt)


def _dist(x1: float, y1: float, x2: float, y2: float) -> float:
    dx = x2 - x1
    dy = y2 - y1
    return math.sqrt(dx * dx + dy * dy)


def _move_toward(drone: Drone, tx: float, ty: float, dt: float) -> None:
    """Step the drone toward (tx, ty) by at most DRONE_SPEED * dt."""
    dx = tx - drone.x
    dy = ty - drone.y
    dist = math.sqrt(dx * dx + dy * dy)
    if dist == 0.0:
        return
    step = min(DRONE_SPEED * dt, dist)
    drone.x += dx / dist * step
    drone.y += dy / dist * step
