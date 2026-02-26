"""
Pre-Mission Loadout Configuration (v0.07 §3.1–3.6).

Validates, stores, and applies player-configured loadout options:
  - Torpedo loadout (point-based magazine distribution)
  - Power profile (reactor tuning affecting system efficiency)
  - Crew complement bias (department crew allocation)
  - Drone loadout (hangar slot distribution)

Equipment modules (§3.6) are handled separately by equipment_modules.py.

Module-level state pattern: reset() / set_loadout() / get_loadout() /
build_state() / serialise() / deserialise().
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from server.models.drones import DRONE_COMPLEMENT, HANGAR_SLOTS
from server.models.ship_class import load_ship_class

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class TorpedoLoadout(BaseModel):
    """Per-type torpedo counts.  sum(count * cost) must be <= magazine capacity."""
    standard: int = 0
    homing: int = 0
    ion: int = 0
    piercing: int = 0
    heavy: int = 0
    proximity: int = 0
    nuclear: int = 0
    experimental: int = 0

    def to_dict(self) -> dict[str, int]:
        return self.model_dump()

    def total_points(self) -> int:
        d = self.to_dict()
        return sum(d[k] * TORPEDO_COSTS[k] for k in d)

    def total_count(self) -> int:
        return sum(self.to_dict().values())


class CrewBias(BaseModel):
    """Department bias adjustments.  Each value ±2, must sum to 0."""
    engineering: int = 0
    security: int = 0
    medical: int = 0
    science: int = 0
    weapons: int = 0
    flight_ops: int = 0

    def to_dict(self) -> dict[str, int]:
        return self.model_dump()


class DroneLoadout(BaseModel):
    """Per-type drone counts.  Sum must be <= hangar slots."""
    scout: int = 0
    combat: int = 0
    rescue: int = 0
    survey: int = 0
    ecm_drone: int = 0

    def to_dict(self) -> dict[str, int]:
        return self.model_dump()

    def total(self) -> int:
        return sum(self.to_dict().values())


class LoadoutConfig(BaseModel):
    """Full loadout sent from the lobby."""
    torpedo_loadout: TorpedoLoadout | None = None
    power_profile: str = "balanced"
    crew_bias: CrewBias | None = None
    drone_loadout: DroneLoadout | None = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# §3.2: Torpedo point costs per type.
TORPEDO_COSTS: dict[str, int] = {
    "standard": 1, "homing": 2, "ion": 2, "piercing": 2,
    "heavy": 3, "proximity": 2, "nuclear": 5, "experimental": 4,
}

# §3.3: Power profile definitions.
POWER_PROFILES: dict[str, dict[str, Any]] = {
    "balanced": {},
    "combat": {
        "weapons": 1.15, "shields": 1.15,
        "sensors": 0.85, "engines": 0.85,
    },
    "exploration": {
        "sensors": 1.15, "engines": 1.15,
        "weapons": 0.85, "shields": 0.85,
    },
    "emergency": {
        "emergency_reserve_mult": 1.5,
        "reactor_output_mult": 0.90,
    },
    "overclocked": {
        "reactor_output_mult": 1.10,
        "battery_capacity_mult": 0.75,
        "coolant_start_health": 80.0,
    },
}

VALID_POWER_PROFILES: frozenset[str] = frozenset(POWER_PROFILES.keys())

# §3.4: Crew bias limits.
CREW_BIAS_MAX = 2
CREW_BIAS_MIN = -2
CREW_BIAS_DEPARTMENTS: tuple[str, ...] = (
    "engineering", "security", "medical", "science", "weapons", "flight_ops",
)

# System name mapping: power profile keys → ShipSystem names.
# "weapons" = beams + torpedoes, "shields" = shields, "sensors" = sensors, "engines" = engines.
_PROFILE_SYSTEM_MAP: dict[str, list[str]] = {
    "weapons": ["beams", "torpedoes", "point_defence"],
    "shields": ["shields"],
    "sensors": ["sensors"],
    "engines": ["engines", "manoeuvring"],
}

# §3.2: Torpedo preset ratios (point-weighted distribution).
TORPEDO_PRESETS: dict[str, dict[str, float]] = {
    "balanced":   {"standard": 0.40, "homing": 0.20, "piercing": 0.15, "proximity": 0.15, "heavy": 0.10},
    "aggressive":  {"standard": 0.20, "homing": 0.15, "heavy": 0.25, "nuclear": 0.15, "piercing": 0.15, "proximity": 0.10},
    "defensive":   {"standard": 0.50, "proximity": 0.25, "ion": 0.15, "homing": 0.10},
    "stealth":     {"standard": 0.30, "homing": 0.30, "ion": 0.20, "piercing": 0.20},
}

# §3.4: Crew presets (absolute bias values, must sum to 0).
CREW_PRESETS: dict[str, dict[str, int]] = {
    "balanced": {},
    "combat":  {"weapons": 2, "security": 1, "science": -1, "medical": -2},
    "science": {"science": 2, "medical": 1, "weapons": -2, "security": -1},
    "repair":  {"engineering": 2, "medical": -1, "science": -1},
}

# §3.5: Drone preset ratios.
DRONE_PRESETS: dict[str, dict[str, float]] = {
    "balanced": {"scout": 0.25, "combat": 0.50, "rescue": 0.25},
    "recon":    {"scout": 0.60, "combat": 0.20, "survey": 0.20},
    "assault":  {"combat": 0.75, "scout": 0.25},
    "support":  {"rescue": 0.40, "survey": 0.30, "scout": 0.30},
}

# Crew bias department → deck mapping for _distribute_decks_with_bias.
_BIAS_DEPT_TO_DECK: dict[str, int] = {
    "engineering": 5,
    "security": 3,
    "medical": 4,
    "science": 2,
    "weapons": 3,
    "flight_ops": 1,
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_torpedo_loadout(
    loadout: TorpedoLoadout, ship_class: str,
) -> tuple[bool, str]:
    """Validate torpedo loadout against ship magazine capacity."""
    d = loadout.to_dict()
    for k, v in d.items():
        if v < 0:
            return False, f"Negative torpedo count for {k}: {v}"
    try:
        sc = load_ship_class(ship_class)
    except FileNotFoundError:
        return False, f"Unknown ship class: {ship_class}"
    capacity = sc.torpedo_ammo
    points = loadout.total_points()
    if points > capacity:
        return False, f"Torpedo loadout uses {points} points but capacity is {capacity}"
    return True, ""


def validate_power_profile(profile: str) -> tuple[bool, str]:
    """Validate power profile name."""
    if profile not in VALID_POWER_PROFILES:
        return False, f"Unknown power profile: {profile!r}. Valid: {sorted(VALID_POWER_PROFILES)}"
    return True, ""


def validate_crew_bias(bias: CrewBias) -> tuple[bool, str]:
    """Validate crew bias — each ±2, zero-sum."""
    d = bias.to_dict()
    for dept, val in d.items():
        if val < CREW_BIAS_MIN or val > CREW_BIAS_MAX:
            return False, f"Crew bias for {dept} is {val}, must be between {CREW_BIAS_MIN} and {CREW_BIAS_MAX}"
    total = sum(d.values())
    if total != 0:
        return False, f"Crew bias must sum to 0, got {total}"
    return True, ""


def validate_drone_loadout(
    loadout: DroneLoadout, ship_class: str,
) -> tuple[bool, str]:
    """Validate drone loadout against hangar capacity and available types."""
    d = loadout.to_dict()
    for k, v in d.items():
        if v < 0:
            return False, f"Negative drone count for {k}: {v}"
    capacity = HANGAR_SLOTS.get(ship_class, 0)
    total = loadout.total()
    if total > capacity:
        return False, f"Drone loadout uses {total} slots but hangar has {capacity}"
    # Check that non-zero counts are valid drone types.
    all_types = {"scout", "combat", "rescue", "survey", "ecm_drone"}
    for k, v in d.items():
        if v > 0 and k not in all_types:
            return False, f"Unknown drone type: {k}"
    return True, ""


def validate_loadout(
    config: LoadoutConfig, ship_class: str,
) -> tuple[bool, str]:
    """Validate an entire loadout configuration."""
    if config.torpedo_loadout is not None:
        ok, err = validate_torpedo_loadout(config.torpedo_loadout, ship_class)
        if not ok:
            return False, err
    ok, err = validate_power_profile(config.power_profile)
    if not ok:
        return False, err
    if config.crew_bias is not None:
        ok, err = validate_crew_bias(config.crew_bias)
        if not ok:
            return False, err
    if config.drone_loadout is not None:
        ok, err = validate_drone_loadout(config.drone_loadout, ship_class)
        if not ok:
            return False, err
    return True, ""


# ---------------------------------------------------------------------------
# Preset generators
# ---------------------------------------------------------------------------


def generate_torpedo_preset(
    preset_name: str, ship_class: str,
) -> TorpedoLoadout:
    """Generate a torpedo loadout from a named preset, fitted to ship capacity."""
    ratios = TORPEDO_PRESETS.get(preset_name, TORPEDO_PRESETS["balanced"])
    try:
        sc = load_ship_class(ship_class)
    except FileNotFoundError:
        sc = load_ship_class("frigate")
    capacity = sc.torpedo_ammo
    return _distribute_points(ratios, capacity)


def _distribute_points(
    ratios: dict[str, float], capacity: int,
) -> TorpedoLoadout:
    """Distribute magazine capacity points across types by ratio.

    Each type gets floor(ratio * capacity / cost) torpedoes.
    Remaining points distributed to cheapest types first.
    """
    # Normalise ratios.
    total_ratio = sum(ratios.values())
    if total_ratio == 0:
        return TorpedoLoadout()
    norm = {k: v / total_ratio for k, v in ratios.items()}

    counts: dict[str, int] = {}
    used = 0
    # First pass: floor allocation.
    for ttype, ratio in norm.items():
        cost = TORPEDO_COSTS.get(ttype, 1)
        # Allocate points proportionally, then convert to torpedo count.
        points_for_type = ratio * capacity
        count = int(points_for_type / cost)
        counts[ttype] = count
        used += count * cost

    # Second pass: distribute remaining capacity, cheapest first.
    remaining = capacity - used
    sorted_types = sorted(norm.keys(), key=lambda t: TORPEDO_COSTS.get(t, 1))
    for ttype in sorted_types:
        cost = TORPEDO_COSTS.get(ttype, 1)
        while remaining >= cost:
            counts[ttype] = counts.get(ttype, 0) + 1
            remaining -= cost

    return TorpedoLoadout(**{k: counts.get(k, 0) for k in TorpedoLoadout.model_fields})


def generate_crew_preset(preset_name: str) -> CrewBias:
    """Generate a crew bias from a named preset."""
    vals = CREW_PRESETS.get(preset_name, {})
    return CrewBias(**{dept: vals.get(dept, 0) for dept in CREW_BIAS_DEPARTMENTS})


def generate_drone_preset(
    preset_name: str, ship_class: str,
) -> DroneLoadout:
    """Generate a drone loadout from a named preset, fitted to hangar capacity."""
    ratios = DRONE_PRESETS.get(preset_name, DRONE_PRESETS["balanced"])
    capacity = HANGAR_SLOTS.get(ship_class, 4)
    return _distribute_drones(ratios, capacity)


def _distribute_drones(
    ratios: dict[str, float], capacity: int,
) -> DroneLoadout:
    """Distribute hangar slots across drone types by ratio."""
    total_ratio = sum(ratios.values())
    if total_ratio == 0 or capacity == 0:
        return DroneLoadout()
    norm = {k: v / total_ratio for k, v in ratios.items()}

    counts: dict[str, int] = {}
    used = 0
    # Floor allocation.
    for dtype, ratio in norm.items():
        count = int(ratio * capacity)
        counts[dtype] = count
        used += count

    # Distribute remainder.
    remaining = capacity - used
    sorted_types = sorted(norm.keys(), key=lambda t: -norm[t])
    for dtype in sorted_types:
        if remaining <= 0:
            break
        counts[dtype] = counts.get(dtype, 0) + 1
        remaining -= 1

    return DroneLoadout(**{k: counts.get(k, 0) for k in DroneLoadout.model_fields})


def get_default_loadout(ship_class: str) -> LoadoutConfig:
    """Return the balanced default loadout for a ship class."""
    return LoadoutConfig(
        torpedo_loadout=generate_torpedo_preset("balanced", ship_class),
        power_profile="balanced",
        crew_bias=generate_crew_preset("balanced"),
        drone_loadout=generate_drone_preset("balanced", ship_class),
    )


# ---------------------------------------------------------------------------
# Application functions (called during game_loop.start())
# ---------------------------------------------------------------------------


def apply_torpedo_loadout(
    loadout: TorpedoLoadout,
    difficulty_multiplier: float = 1.0,
) -> dict[str, int]:
    """Convert TorpedoLoadout to a torpedo count dict with difficulty scaling.

    Returns the dict suitable for glw.reset().
    """
    d = loadout.to_dict()
    if difficulty_multiplier != 1.0:
        d = {
            k: max(0, int(v * difficulty_multiplier + 0.5))
            for k, v in d.items()
        }
    return d


def apply_power_profile(
    profile: str,
    ship: Any,
    power_grid: Any | None = None,
) -> None:
    """Apply power profile modifiers to ship systems and power grid.

    For combat/exploration profiles: sets _power_profile_modifier on affected systems.
    For emergency: modifies power grid emergency_reserve and reactor_max.
    For overclocked: modifies reactor_max, battery_capacity, and coolant health.
    """
    defn = POWER_PROFILES.get(profile, {})
    if not defn:
        return

    # System efficiency modifiers.
    for profile_key, modifier in defn.items():
        if profile_key in _PROFILE_SYSTEM_MAP:
            for sys_name in _PROFILE_SYSTEM_MAP[profile_key]:
                sys_obj = ship.systems.get(sys_name)
                if sys_obj is not None:
                    sys_obj._power_profile_modifier = modifier

    # Power grid modifiers.
    if power_grid is not None:
        if "reactor_output_mult" in defn:
            power_grid.reactor_max = round(
                power_grid.reactor_max * defn["reactor_output_mult"], 1,
            )
        if "emergency_reserve_mult" in defn:
            power_grid.emergency_reserve = round(
                power_grid.emergency_reserve * defn["emergency_reserve_mult"], 1,
            )
        if "battery_capacity_mult" in defn:
            power_grid.battery_capacity = round(
                power_grid.battery_capacity * defn["battery_capacity_mult"], 1,
            )
            # Clamp current charge to new capacity.
            power_grid.battery_charge = min(
                power_grid.battery_charge, power_grid.battery_capacity,
            )
        if "coolant_start_health" in defn:
            power_grid.reactor_health = defn["coolant_start_health"]


def compute_crew_bias_deck_adjustments(
    bias: CrewBias, base_crew_count: int, num_decks: int = 5,
) -> dict[int, int]:
    """Compute per-deck crew count adjustments from a crew bias.

    Returns {deck_number: adjusted_count}.  Total is always base_crew_count.
    """
    per_deck = base_crew_count // num_decks
    remainder = base_crew_count % num_decks
    base: dict[int, int] = {}
    for dk in range(1, num_decks + 1):
        base[dk] = per_deck + (1 if dk <= remainder else 0)

    d = bias.to_dict()
    for dept, adj in d.items():
        if adj == 0:
            continue
        deck = _BIAS_DEPT_TO_DECK.get(dept)
        if deck is None:
            continue
        base[deck] = max(0, base[deck] + adj)

    # Re-balance to preserve total crew count.
    total = sum(base.values())
    diff = total - base_crew_count
    if diff > 0:
        # Remove excess from largest decks.
        for _ in range(diff):
            largest = max(base, key=lambda dk: base[dk])
            base[largest] -= 1
    elif diff < 0:
        # Add shortfall to smallest decks.
        for _ in range(-diff):
            smallest = min(base, key=lambda dk: base[dk])
            base[smallest] += 1

    return base


def apply_drone_loadout(loadout: DroneLoadout) -> dict[str, int]:
    """Convert DroneLoadout to complement dict for create_ship_drones()."""
    return {k: v for k, v in loadout.to_dict().items() if v > 0}


# ---------------------------------------------------------------------------
# REST endpoint helpers
# ---------------------------------------------------------------------------


def get_loadout_defaults(ship_class: str) -> dict:
    """Return loadout constraints and presets for a ship class."""
    try:
        sc = load_ship_class(ship_class)
    except FileNotFoundError:
        sc = load_ship_class("frigate")
    hangar = HANGAR_SLOTS.get(ship_class, 0)
    complement = DRONE_COMPLEMENT.get(ship_class, {})
    return {
        "torpedo_capacity": sc.torpedo_ammo,
        "torpedo_costs": TORPEDO_COSTS,
        "torpedo_presets": {
            name: generate_torpedo_preset(name, ship_class).to_dict()
            for name in TORPEDO_PRESETS
        },
        "power_profiles": sorted(VALID_POWER_PROFILES),
        "crew_bias_departments": list(CREW_BIAS_DEPARTMENTS),
        "crew_presets": CREW_PRESETS,
        "hangar_slots": hangar,
        "drone_presets": {
            name: generate_drone_preset(name, ship_class).to_dict()
            for name in DRONE_PRESETS
        },
        "available_drone_types": sorted(complement.keys()),
        "default_loadout": get_default_loadout(ship_class).model_dump(),
    }


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_active_loadout: LoadoutConfig | None = None


def reset() -> None:
    """Clear loadout state."""
    global _active_loadout
    _active_loadout = None


def set_loadout(config: LoadoutConfig) -> None:
    """Store the active loadout configuration."""
    global _active_loadout
    _active_loadout = config


def get_loadout() -> LoadoutConfig | None:
    """Return the active loadout, or None if using defaults."""
    return _active_loadout


def get_power_profile() -> str:
    """Return the active power profile name."""
    if _active_loadout is not None:
        return _active_loadout.power_profile
    return "balanced"


def build_state() -> dict:
    """Return loadout state for broadcast/debrief."""
    if _active_loadout is None:
        return {"power_profile": "balanced"}
    return _active_loadout.model_dump()


def serialise() -> dict:
    """Serialise loadout state for save system."""
    if _active_loadout is None:
        return {}
    return _active_loadout.model_dump()


def deserialise(data: dict) -> None:
    """Restore loadout state from save data."""
    global _active_loadout
    if not data:
        _active_loadout = None
        return
    _active_loadout = LoadoutConfig(**data)
