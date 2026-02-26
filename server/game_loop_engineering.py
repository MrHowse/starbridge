"""
Engineering Game Loop Module.

Integrates the PowerGrid, RepairTeamManager, and DamageModel into the game
loop tick cycle. Manages power distribution, repair team operations, and
component-level damage tracking.

Module-level state pattern: call reset() or init() before use. The main
game loop calls tick() once per frame (10 Hz).
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from server.models.damage_model import DamageModel
from server.models.interior import ShipInterior
from server.models.power_grid import PowerGrid, ALL_BUS_SYSTEMS
from server.models.repair_teams import RepairTeamManager
from server.models.ship import Ship

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OVERCLOCK_THRESHOLD: float = 100.0
OVERCLOCK_DAMAGE_CHANCE: float = 0.10
OVERCLOCK_DAMAGE_MIN: float = 5.0
OVERCLOCK_DAMAGE_MAX: float = 15.0

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_power_grid: PowerGrid | None = None
_repair_mgr: RepairTeamManager | None = None
_damage_model: DamageModel | None = None
_requested_power: dict[str, float] = {}
_rng: random.Random = random.Random()
_tick_count: int = 0
_ship_class: str = "frigate"


# ---------------------------------------------------------------------------
# Init / Reset
# ---------------------------------------------------------------------------


def reset() -> None:
    """Clear all module state."""
    global _power_grid, _repair_mgr, _damage_model
    global _requested_power, _rng, _tick_count, _ship_class
    _power_grid = None
    _repair_mgr = None
    _damage_model = None
    _requested_power = {}
    _rng = random.Random()
    _tick_count = 0
    _ship_class = "frigate"


def init(ship: Ship,
         crew_member_ids: list[str] | None = None,
         power_grid_config: dict | None = None,
         system_rooms: dict[str, str] | None = None,
         repair_base_room: str | None = None,
         ship_class: str = "frigate") -> None:
    """Initialise engineering subsystems for a new game.

    Args:
        ship: The player ship (systems read for initial power levels).
        crew_member_ids: Crew IDs to form repair teams from.
        power_grid_config: Optional ship-class power_grid JSON section.
        system_rooms: Per-ship-class system->room mapping for repair dispatch.
        repair_base_room: Per-ship-class base room for repair teams.
        ship_class: Ship class ID (for carrier/medical power features).
    """
    global _power_grid, _repair_mgr, _damage_model
    global _requested_power, _rng, _tick_count, _ship_class

    _ship_class = ship_class

    if power_grid_config:
        _power_grid = PowerGrid.from_ship_class(power_grid_config)
    else:
        _power_grid = PowerGrid()

    _repair_mgr = RepairTeamManager.create_teams(
        crew_member_ids or [],
        system_rooms=system_rooms,
        base_room=repair_base_room or "main_engineering",
    )
    _damage_model = DamageModel.create_default()

    # Seed requested power from ship's current levels.
    _requested_power = {name: sys.power for name, sys in ship.systems.items()}
    _rng = random.Random()
    _tick_count = 0


# ---------------------------------------------------------------------------
# Player commands (called from _drain_queue)
# ---------------------------------------------------------------------------


def set_power(system: str, level: float) -> None:
    """Store a power request for a system (applied next tick)."""
    if system in ALL_BUS_SYSTEMS:
        _requested_power[system] = max(0.0, min(150.0, level))


def dispatch_team(team_id: str, system: str,
                  interior: ShipInterior) -> bool:
    """Send a repair team to fix a system."""
    if _repair_mgr is None:
        return False
    return _repair_mgr.dispatch(team_id, system, interior)


def recall_team(team_id: str, interior: ShipInterior) -> bool:
    """Recall a repair team to base."""
    if _repair_mgr is None:
        return False
    return _repair_mgr.recall(team_id, interior)


def set_battery_mode(mode: str) -> bool:
    """Set the battery operating mode."""
    if _power_grid is None:
        return False
    return _power_grid.set_battery_mode(mode)


def start_reroute(target_bus: str) -> bool:
    """Begin a bus reroute (takes REROUTE_DURATION seconds)."""
    if _power_grid is None:
        return False
    return _power_grid.start_reroute(target_bus)


def request_escort(team_id: str, squad_id: str) -> bool:
    """Assign a security escort to a repair team."""
    if _repair_mgr is None:
        return False
    return _repair_mgr.request_escort(team_id, squad_id)


def clear_escort(team_id: str) -> None:
    """Remove escort from a repair team."""
    if _repair_mgr is not None:
        _repair_mgr.clear_escort(team_id)


def add_repair_order(system: str, priority: int = 1) -> str | None:
    """Queue a repair order. Returns order ID."""
    if _repair_mgr is None:
        return None
    return _repair_mgr.add_order(system, priority)


def cancel_repair_order(order_id: str) -> bool:
    """Cancel a queued repair order."""
    if _repair_mgr is None:
        return False
    return _repair_mgr.cancel_order(order_id)


# ---------------------------------------------------------------------------
# External damage entry point (called from combat)
# ---------------------------------------------------------------------------


def apply_system_damage(system: str, damage: float, cause: str,
                        tick: int = 0,
                        component_id: str | None = None) -> list[dict]:
    """Apply damage to a system's components through the DamageModel.

    Returns list of component damage event dicts.
    """
    if _damage_model is None:
        return []
    return _damage_model.apply_damage(
        system, damage, cause, tick=tick,
        component_id=component_id, rng=_rng)


def repair_all_components(system: str) -> None:
    """Reset all components of a system to full health (used by docking repair)."""
    if _damage_model is None:
        return
    sys_comps = _damage_model.components.get(system)
    if sys_comps is None:
        return
    for comp in sys_comps.values():
        comp.health = 100.0


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


@dataclass
class EngineeringTickResult:
    """Collected events from one engineering tick."""
    overclock_events: list[dict]
    repair_team_events: list[dict]
    power_delivered: dict[str, float]


def tick(ship: Ship, interior: ShipInterior, dt: float) -> EngineeringTickResult:
    """Advance engineering subsystems by one tick.

    1. PowerGrid.tick() — distributes power based on requests.
    2. Apply delivered power to ShipSystem.power.
    3. Overclock damage — systems above threshold risk component damage.
    4. RepairTeamManager.tick() — teams travel and repair.
    5. Apply repair HP from team events to DamageModel components.
    6. Sync DamageModel weighted health → ShipSystem.health.

    Returns EngineeringTickResult with events from this tick.
    """
    global _tick_count
    _tick_count += 1

    result = EngineeringTickResult(
        overclock_events=[],
        repair_team_events=[],
        power_delivered={},
    )

    if _power_grid is None or _damage_model is None:
        return result

    # 0. Apply external drain (spinal mount + carrier flight deck power draw).
    import server.game_loop_spinal_mount as glsm
    import server.game_loop_flight_ops as glfo
    _power_grid.external_drain = (
        glsm.get_power_draw()
        + glfo.get_flight_deck_power_draw(
            _power_grid.reactor_max if _ship_class == "carrier" else 0.0
        )
    )

    # 1. Power distribution (medical ships protect sensors + shields in brownout)
    _protected = {"sensors", "shields"} if _ship_class == "medical_ship" else None
    delivered = _power_grid.tick(dt, _requested_power, protected_systems=_protected)
    result.power_delivered = delivered

    # 2. Apply delivered power to ship systems
    for sys_name, power in delivered.items():
        if sys_name in ship.systems:
            ship.systems[sys_name].power = power

    # 3. Overclock damage
    result.overclock_events = _apply_overclock_damage(ship, _tick_count)

    # 4. Repair team travel/repair
    if _repair_mgr is not None:
        team_events = _repair_mgr.tick(dt, interior, _rng)
        result.repair_team_events = team_events

        # 5. Apply repair HP to damage model
        for evt in team_events:
            if evt["type"] == "repair_hp" and evt.get("system"):
                _damage_model.repair_system(evt["system"], evt["hp"])

    # 6. Sync damage model health → ship system health
    _sync_health_to_ship(ship)

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _apply_overclock_damage(ship: Ship, tick: int) -> list[dict]:
    """Check for overclock damage on systems above threshold."""
    if _damage_model is None:
        return []

    events: list[dict] = []
    for name, sys_obj in ship.systems.items():
        if sys_obj.power > OVERCLOCK_THRESHOLD and sys_obj.health > 0.0:
            if _rng.random() < OVERCLOCK_DAMAGE_CHANCE:
                dmg = _rng.uniform(OVERCLOCK_DAMAGE_MIN, OVERCLOCK_DAMAGE_MAX)
                comp_events = _damage_model.apply_damage(
                    name, dmg, "overclock", tick=tick, rng=_rng)
                if comp_events:
                    events.append({
                        "type": "overclock_damage",
                        "system": name,
                        "damage": dmg,
                        "components": comp_events,
                    })
    return events


def _sync_health_to_ship(ship: Ship) -> None:
    """Push DamageModel weighted health into ShipSystem.health."""
    if _damage_model is None:
        return
    for name in ship.systems:
        if name in _damage_model.components:
            ship.systems[name].health = _damage_model.get_system_health(name)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


def get_power_grid() -> PowerGrid | None:
    """Access the PowerGrid instance (for external queries)."""
    return _power_grid


def get_damage_model() -> DamageModel | None:
    """Access the DamageModel instance (for external queries)."""
    return _damage_model


def get_repair_manager() -> RepairTeamManager | None:
    """Access the RepairTeamManager instance."""
    return _repair_mgr


def build_state(ship: Ship) -> dict:
    """Build the full engineering state for broadcasting."""
    pg = _power_grid or PowerGrid()
    dm = _damage_model

    # System details with component-level info
    systems: dict[str, dict] = {}
    for name, sys_obj in ship.systems.items():
        sys_info: dict = {
            "power": sys_obj.power,
            "health": round(sys_obj.health, 2),
            "efficiency": round(sys_obj.efficiency, 3),
            "requested_power": _requested_power.get(name, sys_obj.power),
        }
        if dm and name in dm.components:
            sys_info["components"] = [
                c.to_dict() for c in dm.components[name].values()
            ]
        systems[name] = sys_info

    state: dict = {
        "systems": systems,
        "power_grid": {
            "reactor_max": pg.reactor_max,
            "reactor_health": round(pg.reactor_health, 2),
            "reactor_output": round(pg.reactor_output, 2),
            "battery_charge": round(pg.battery_charge, 2),
            "battery_capacity": pg.battery_capacity,
            "battery_mode": pg.battery_mode,
            "emergency_active": pg.emergency_active,
            "primary_bus_online": pg.primary_bus_online,
            "secondary_bus_online": pg.secondary_bus_online,
            "reroute_active": pg.reroute_active,
            "reroute_timer": round(pg.reroute_timer, 2),
            "reroute_target_bus": pg.reroute_target_bus,
            "available_budget": round(pg.get_available_budget(), 2),
            "spinal_power_draw": round(pg.external_drain, 2),
        },
    }

    if _repair_mgr is not None:
        state["repair_teams"] = _repair_mgr.get_team_state()
        state["repair_orders"] = list(_repair_mgr.order_queue)

    if dm is not None:
        state["recent_damage_events"] = dm.get_recent_events(10)

    return state


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def serialise() -> dict:
    """Serialise all engineering state for save/resume."""
    data: dict = {
        "requested_power": dict(_requested_power),
        "tick_count": _tick_count,
        "ship_class": _ship_class,
    }
    if _power_grid is not None:
        data["power_grid"] = _power_grid.serialise()
    if _repair_mgr is not None:
        data["repair_teams"] = _repair_mgr.serialise()
    if _damage_model is not None:
        data["damage_model"] = _damage_model.serialise()
    return data


def deserialise(data: dict, ship: Ship) -> None:
    """Restore engineering state from saved data."""
    global _power_grid, _repair_mgr, _damage_model
    global _requested_power, _tick_count, _ship_class

    _requested_power = data.get("requested_power", {})
    _tick_count = data.get("tick_count", 0)
    _ship_class = data.get("ship_class", "frigate")

    if "power_grid" in data:
        _power_grid = PowerGrid.deserialise(data["power_grid"])
    else:
        _power_grid = PowerGrid()

    if "repair_teams" in data:
        _repair_mgr = RepairTeamManager.deserialise(data["repair_teams"])
    else:
        _repair_mgr = RepairTeamManager()

    if "damage_model" in data:
        _damage_model = DamageModel.deserialise(data["damage_model"])
    else:
        _damage_model = DamageModel.create_default()

    # Sync health to ship after restoring
    _sync_health_to_ship(ship)
