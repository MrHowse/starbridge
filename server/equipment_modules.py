"""
Equipment Modules — Frigate Modular Equipment Bays (v0.07 §2.3).

Data-driven registry of 9 equippable modules for the frigate class.
Modules are validated in the lobby, passed through to game_loop.start(),
and applied after ship class stats are loaded.

Each module either modifies ship stats directly (armour, sensors, cargo) or
enables subsystem-specific features handled by their respective modules.

Lifecycle: validate_modules() in lobby → apply_modules() in game_loop.start()
→ has_module() queries from subsystems → serialise()/deserialise() for save.
"""
from __future__ import annotations

from server.models.ship import Ship

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum equippable modules per ship class (only frigate has bays).
MAX_MODULES_BY_CLASS: dict[str, int] = {
    "frigate": 2,
}

#: Module registry — 9 modules, each with id, name, description, station_benefit.
MODULES: dict[str, dict] = {
    "extra_torpedo_magazine": {
        "id": "extra_torpedo_magazine",
        "name": "Extra Torpedo Magazine",
        "description": "Adds +1 torpedo tube and +8 torpedo capacity (+1 per type).",
        "station_benefit": "weapons",
    },
    "enhanced_sensor_array": {
        "id": "enhanced_sensor_array",
        "name": "Enhanced Sensor Array",
        "description": "Increases sensor range by 30% and scan speed by 20%.",
        "station_benefit": "science",
    },
    "marine_barracks": {
        "id": "marine_barracks",
        "name": "Marine Barracks",
        "description": "Adds an extra marine squad (4 marines).",
        "station_benefit": "security",
    },
    "drone_hangar_expansion": {
        "id": "drone_hangar_expansion",
        "name": "Drone Hangar Expansion",
        "description": "Adds +2 hangar slots and +1 combat drone.",
        "station_benefit": "flight_ops",
    },
    "medical_ward_upgrade": {
        "id": "medical_ward_upgrade",
        "name": "Medical Ward Upgrade",
        "description": "Adds +2 treatment beds, +1 quarantine slot, +20% medical supplies.",
        "station_benefit": "medical",
    },
    "cargo_hold": {
        "id": "cargo_hold",
        "name": "Cargo Hold",
        "description": "Enables cargo capacity (100 units) and +50% fuel efficiency.",
        "station_benefit": "engineering",
    },
    "armour_plating": {
        "id": "armour_plating",
        "name": "Armour Plating",
        "description": "Adds +15 armour, +20 hull, but -10% max speed.",
        "station_benefit": "hazard_control",
    },
    "cloaking_device": {
        "id": "cloaking_device",
        "name": "Cloaking Device",
        "description": "Scout-style stealth with 60s max duration and overheat cooldown.",
        "station_benefit": "electronic_warfare",
    },
    "mining_equipment": {
        "id": "mining_equipment",
        "name": "Mining Equipment",
        "description": "Harvest asteroids for fuel and materials.",
        "station_benefit": "engineering",
    },
}

VALID_MODULE_IDS: frozenset[str] = frozenset(MODULES.keys())

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_active_modules: list[str] = []

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset() -> None:
    """Clear active modules. Called at game start."""
    _active_modules.clear()


def get_max_modules(ship_class: str) -> int:
    """Return the maximum number of equippable modules for a ship class."""
    return MAX_MODULES_BY_CLASS.get(ship_class, 0)


def validate_modules(ship_class: str, module_ids: list[str]) -> tuple[bool, str]:
    """Validate a module selection.

    Returns (ok, error_message). error_message is empty on success.
    """
    max_count = get_max_modules(ship_class)
    if not module_ids:
        return True, ""
    if max_count == 0:
        return False, f"Ship class '{ship_class}' cannot equip modules"
    if len(module_ids) > max_count:
        return False, f"Too many modules: {len(module_ids)} > {max_count}"
    if len(set(module_ids)) != len(module_ids):
        return False, "Duplicate modules not allowed"
    for mid in module_ids:
        if mid not in VALID_MODULE_IDS:
            return False, f"Unknown module: {mid!r}"
    return True, ""


def apply_modules(ship: Ship, module_ids: list[str]) -> list[str]:
    """Apply stat-based module effects to the ship.

    Stores the active module list and applies direct ship stat changes.
    Subsystem-specific effects (marines, drones, medical, cloaking, mining)
    are handled by their respective modules using has_module() queries.

    Returns the list of applied module IDs.
    """
    _active_modules.clear()
    _active_modules.extend(module_ids)

    for mid in module_ids:
        if mid == "extra_torpedo_magazine":
            ship.torpedo_tube_count += 1
        elif mid == "enhanced_sensor_array":
            ship.sensor_range_base *= 1.3
        elif mid == "armour_plating":
            ship.armour += 15.0
            ship.armour_max += 15.0
            ship.hull += 20.0
            ship.hull_max += 20.0
            ship.max_speed_base *= 0.9
        elif mid == "cargo_hold":
            ship.cargo_capacity = 100.0
            ship.fuel_multiplier *= 1.5
        # Other modules: no direct stat changes on Ship.

    return list(_active_modules)


def has_module(module_id: str) -> bool:
    """Return True if the given module is currently active."""
    return module_id in _active_modules


def get_active_modules() -> list[str]:
    """Return the list of active module IDs."""
    return list(_active_modules)


def get_module_names() -> list[str]:
    """Return human-readable names for active modules."""
    return [MODULES[mid]["name"] for mid in _active_modules if mid in MODULES]


def serialise() -> dict:
    """Capture module state for save/resume."""
    return {
        "active_modules": list(_active_modules),
    }


def deserialise(data: dict) -> None:
    """Restore module state from save data."""
    _active_modules.clear()
    _active_modules.extend(data.get("active_modules", []))
