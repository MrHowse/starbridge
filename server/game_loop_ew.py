"""
Electronic Warfare — Game Loop Integration.

Handles:
  - Sensor jamming: enemy.jam_factor buildup/decay based on ECM suite power
  - Countermeasure charge management (toggle/auto-off when charges exhaust)
  - System intrusion state tracking (puzzle creation handled by game_loop.py)
  - EW state payload construction for the electronic_warfare station

ECM suite power (Engineering allocation) scales jamming effectiveness and
range. At full power (efficiency=1.0) and full health: base values apply.
Overclocking to 150% gives efficiency=1.5 → extended range and faster buildup.

Constants are tuned for a 10 Hz game loop (TICK_DT = 0.1 s).
"""
from __future__ import annotations

from server.models.ship import Ship
from server.models.world import World
from server.utils.math_helpers import distance

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: jam_factor increase per second when an enemy is within range and targeted.
JAM_BUILDUP_RATE: float = 0.25
#: jam_factor decrease per second when an enemy is NOT the active target.
JAM_DECAY_RATE: float = 0.15
#: Maximum achievable jam_factor (80% damage reduction at full ECM efficiency).
JAM_MAX_FACTOR: float = 0.80
#: Base jamming range in world units; scales with ECM efficiency.
JAM_BASE_RANGE: float = 15_000.0

#: Default countermeasure charges on game start.
COUNTERMEASURE_DEFAULT_CHARGES: int = 10

#: How long a successful network intrusion stuns enemy beam fire (ticks at 10 Hz).
INTRUSION_STUN_DURATION: int = 30  # 3 seconds


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_jam_target_id: str | None = None
_intrusion_target_id: str | None = None
_intrusion_target_system: str | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset() -> None:
    """Reset EW state to defaults. Called at game start."""
    global _jam_target_id, _intrusion_target_id, _intrusion_target_system
    _jam_target_id = None
    _intrusion_target_id = None
    _intrusion_target_system = None


def set_jam_target(entity_id: str | None) -> None:
    """Set the enemy to jam. Pass None to stop active jamming."""
    global _jam_target_id
    _jam_target_id = entity_id


def toggle_countermeasures(active: bool, ship: Ship) -> None:
    """Enable or disable countermeasures.

    Enabling is silently ignored if countermeasure_charges are exhausted.
    """
    if active and ship.countermeasure_charges <= 0:
        return
    ship.ew_countermeasure_active = active


def set_intrusion_target(entity_id: str, target_system: str) -> None:
    """Record intrusion target. Called before the network_intrusion puzzle is created."""
    global _intrusion_target_id, _intrusion_target_system
    _intrusion_target_id = entity_id
    _intrusion_target_system = target_system


def get_intrusion_target() -> tuple[str | None, str | None]:
    """Return (entity_id, target_system) of the current intrusion target."""
    return _intrusion_target_id, _intrusion_target_system


def apply_intrusion_success(entity_id: str, world: World) -> None:
    """On intrusion puzzle success: stun enemy beam fire for INTRUSION_STUN_DURATION ticks."""
    for enemy in world.enemies:
        if enemy.id == entity_id:
            enemy.intrusion_stun_ticks = max(enemy.intrusion_stun_ticks, INTRUSION_STUN_DURATION)
            break


def tick(world: World, ship: Ship, dt: float) -> None:
    """Update jam_factor on all enemies each tick.

    The active jam target builds up toward JAM_MAX_FACTOR; all other enemies
    decay toward 0. Both the buildup rate and effective range scale with the
    ECM suite's efficiency (power × health).
    """
    ecm_eff = ship.systems["ecm_suite"].efficiency  # 0.0–1.5
    # Effective range and buildup both scale with ECM efficiency.
    # Use at least 0.01 guard so ecm_eff=0 gives zero effective range.
    effective_range = JAM_BASE_RANGE * ecm_eff
    buildup_rate = JAM_BUILDUP_RATE * ecm_eff

    for enemy in world.enemies:
        if enemy.id == _jam_target_id and effective_range > 0.0:
            dist = distance(ship.x, ship.y, enemy.x, enemy.y)
            if dist <= effective_range:
                enemy.jam_factor = min(JAM_MAX_FACTOR, enemy.jam_factor + buildup_rate * dt)
            else:
                # Out of jam range — decay even while targeted.
                enemy.jam_factor = max(0.0, enemy.jam_factor - JAM_DECAY_RATE * dt)
        else:
            # Not targeted (or ECM offline) — decay toward 0.
            enemy.jam_factor = max(0.0, enemy.jam_factor - JAM_DECAY_RATE * dt)

    # v0.05i — station sensor array jamming.
    # If the jam target is a station sensor component ("*_sensor"), mark it jammed.
    if _jam_target_id and _jam_target_id.endswith("_sensor") and effective_range > 0.0:
        for station in world.stations:
            if station.defenses is None:
                continue
            sa = station.defenses.sensor_array
            if sa.id == _jam_target_id:
                dist = distance(ship.x, ship.y, station.x, station.y)
                sa.jammed = dist <= effective_range
                break
    else:
        # Clear jammed flag when the sensor is no longer actively targeted.
        for station in world.stations:
            if station.defenses is not None:
                sa = station.defenses.sensor_array
                if sa.jammed and (_jam_target_id is None or sa.id != _jam_target_id):
                    sa.jammed = False


def build_state(world: World, ship: Ship) -> dict:
    """Serialise EW state for broadcast to the electronic_warfare role."""
    ecm_eff = ship.systems["ecm_suite"].efficiency
    enemies_data = []
    for enemy in world.enemies:
        dist = distance(ship.x, ship.y, enemy.x, enemy.y)
        enemies_data.append({
            "id": enemy.id,
            "type": enemy.type,
            "x": round(enemy.x, 1),
            "y": round(enemy.y, 1),
            "jam_factor": round(enemy.jam_factor, 3),
            "intrusion_stun_ticks": enemy.intrusion_stun_ticks,
            "distance": round(dist, 1),
        })
    return {
        "jam_target_id": _jam_target_id,
        "countermeasures_active": ship.ew_countermeasure_active,
        "countermeasure_charges": ship.countermeasure_charges,
        "ecm_efficiency": round(ecm_eff, 3),
        "jam_base_range": JAM_BASE_RANGE,
        "effective_jam_range": round(JAM_BASE_RANGE * ecm_eff, 1),
        "enemies": enemies_data,
        "intrusion_target_id": _intrusion_target_id,
        "intrusion_target_system": _intrusion_target_system,
    }


def serialise() -> dict:
    return {
        "jam_target_id": _jam_target_id,
        "intrusion_target_id": _intrusion_target_id,
        "intrusion_target_system": _intrusion_target_system,
    }


def deserialise(data: dict) -> None:
    global _jam_target_id, _intrusion_target_id, _intrusion_target_system
    _jam_target_id           = data.get("jam_target_id")
    _intrusion_target_id     = data.get("intrusion_target_id")
    _intrusion_target_system = data.get("intrusion_target_system")
