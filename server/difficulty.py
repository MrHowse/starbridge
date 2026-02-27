"""
Difficulty presets for Starbridge.

Provides DifficultyPreset dataclass and four named presets that scale
every tunable gameplay parameter.  All multipliers are positive floats
where 1.0 = default (Officer).

Usage:
    from server.difficulty import get_preset, DifficultyPreset
    ship.difficulty = get_preset("cadet")
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DifficultyPreset:
    """Multipliers applied at game start to scale challenge level."""

    name: str = "Officer"
    description: str = "Standard experience."

    # --- Combat ---
    enemy_damage_multiplier: float = 1.0       # Scales incoming beam/torpedo damage
    enemy_accuracy: float = 1.0                # Enemy hit-chance multiplier
    enemy_health_multiplier: float = 1.0       # Enemy hull HP multiplier at spawn
    enemy_count_multiplier: float = 1.0        # Scales enemy spawn counts
    enemy_ai_aggression: float = 0.75          # flee_threshold scale (higher = flee later)

    # --- Damage & repair ---
    component_damage_chance: float = 0.5       # Probability of system damage per hull hit
    component_severity_multiplier: float = 1.0 # Scales system damage amount
    cook_off_chance_multiplier: float = 1.0    # Magazine cook-off probability
    repair_speed_multiplier: float = 1.0       # DCT and repair team speed (>1 = faster)

    # --- Crew & medical ---
    injury_chance: float = 0.4                 # Base injury probability per crew member
    injury_severity_bias: float = 0.5          # Bias toward severe injuries (0=mild, 1=severe)
    degradation_timer_multiplier: float = 1.0  # Injury worsen speed (>1 = slower = easier)
    death_timer_multiplier: float = 1.0        # Time before critical → death (>1 = longer = easier)
    contagion_spread_chance: float = 0.3       # Infection spread probability per interval

    # --- Resources ---
    starting_torpedo_multiplier: float = 1.0   # Scales initial torpedo loadout
    medical_supply_multiplier: float = 1.0     # Scales initial medical supplies
    battery_capacity_multiplier: float = 1.0   # Scales battery capacity
    fuel_consumption_multiplier: float = 1.0   # Fuel use rate (not yet applicable)
    starting_credits_multiplier: float = 1.0   # Scales starting credits (v0.07 §6.2)

    # --- Scanning & intel ---
    sensor_range_multiplier: float = 1.0       # Scales base sensor range
    scan_time_multiplier: float = 1.0          # Scales science scan durations (>1 = slower)
    fog_of_war_reveal: float = 0.2             # Fraction of sectors pre-revealed

    # --- Environmental ---
    hazard_damage_multiplier: float = 1.0      # Scales environmental hazard damage

    # --- Sandbox ---
    event_interval_multiplier: float = 1.0     # Time between sandbox events (>1 = longer = easier)
    event_overlap_max: int = 2                 # Max simultaneous sandbox events

    # --- Timers & pacing ---
    docking_service_multiplier: float = 1.0    # Docking service duration (>1 = slower)
    boarding_frequency_multiplier: float = 1.0 # Boarding event frequency (>1 = more frequent)

    # --- Legacy compat ---
    puzzle_time_mult: float = 1.0              # Puzzle time limits (>1 = more time = easier)
    hints_enabled: bool = False                # Cadet mode: show UI hints


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

PRESETS: dict[str, DifficultyPreset] = {
    "cadet": DifficultyPreset(
        name="Cadet",
        description=(
            "Learning mode. Forgiving combat, slower crises, more resources. "
            "Recommended for first-time crews."
        ),
        enemy_damage_multiplier=0.5,
        enemy_accuracy=0.7,
        enemy_health_multiplier=0.7,
        enemy_count_multiplier=0.7,
        enemy_ai_aggression=0.5,
        component_damage_chance=0.3,
        component_severity_multiplier=0.6,
        cook_off_chance_multiplier=0.25,
        repair_speed_multiplier=1.5,
        injury_chance=0.25,
        injury_severity_bias=0.3,
        degradation_timer_multiplier=2.0,
        death_timer_multiplier=2.0,
        contagion_spread_chance=0.15,
        starting_torpedo_multiplier=1.5,
        medical_supply_multiplier=1.5,
        battery_capacity_multiplier=1.25,
        fuel_consumption_multiplier=0.75,
        starting_credits_multiplier=2.0,
        sensor_range_multiplier=1.25,
        scan_time_multiplier=0.75,
        fog_of_war_reveal=0.4,
        hazard_damage_multiplier=0.5,
        event_interval_multiplier=1.5,
        event_overlap_max=1,
        docking_service_multiplier=0.75,
        boarding_frequency_multiplier=0.5,
        puzzle_time_mult=1.5,
        hints_enabled=True,
    ),

    "officer": DifficultyPreset(
        name="Officer",
        description=(
            "Standard experience. Balanced challenge with fair resources. "
            "Recommended for experienced crews."
        ),
        enemy_damage_multiplier=1.0,
        enemy_accuracy=1.0,
        enemy_health_multiplier=1.0,
        enemy_count_multiplier=1.0,
        enemy_ai_aggression=0.75,
        component_damage_chance=0.5,
        component_severity_multiplier=1.0,
        cook_off_chance_multiplier=1.0,
        repair_speed_multiplier=1.0,
        injury_chance=0.4,
        injury_severity_bias=0.5,
        degradation_timer_multiplier=1.0,
        death_timer_multiplier=1.0,
        contagion_spread_chance=0.3,
        starting_torpedo_multiplier=1.0,
        medical_supply_multiplier=1.0,
        battery_capacity_multiplier=1.0,
        fuel_consumption_multiplier=1.0,
        starting_credits_multiplier=1.0,
        sensor_range_multiplier=1.0,
        scan_time_multiplier=1.0,
        fog_of_war_reveal=0.2,
        hazard_damage_multiplier=1.0,
        event_interval_multiplier=1.0,
        event_overlap_max=2,
        docking_service_multiplier=1.0,
        boarding_frequency_multiplier=1.0,
        puzzle_time_mult=1.0,
        hints_enabled=False,
    ),

    "commander": DifficultyPreset(
        name="Commander",
        description=(
            "Tough challenge. Enemies hit hard, resources are tight, "
            "crises overlap. For crews who've mastered Officer."
        ),
        enemy_damage_multiplier=1.3,
        enemy_accuracy=1.15,
        enemy_health_multiplier=1.3,
        enemy_count_multiplier=1.25,
        enemy_ai_aggression=1.0,
        component_damage_chance=0.65,
        component_severity_multiplier=1.3,
        cook_off_chance_multiplier=1.5,
        repair_speed_multiplier=0.8,
        injury_chance=0.5,
        injury_severity_bias=0.65,
        degradation_timer_multiplier=0.75,
        death_timer_multiplier=0.75,
        contagion_spread_chance=0.4,
        starting_torpedo_multiplier=0.8,
        medical_supply_multiplier=0.8,
        battery_capacity_multiplier=0.9,
        fuel_consumption_multiplier=1.25,
        starting_credits_multiplier=0.75,
        sensor_range_multiplier=0.9,
        scan_time_multiplier=1.2,
        fog_of_war_reveal=0.1,
        hazard_damage_multiplier=1.3,
        event_interval_multiplier=0.75,
        event_overlap_max=3,
        docking_service_multiplier=1.25,
        boarding_frequency_multiplier=1.3,
        puzzle_time_mult=0.8,
        hints_enabled=False,
    ),

    "admiral": DifficultyPreset(
        name="Admiral",
        description=(
            "Brutal. Everything is lethal, nothing is free, crises never stop. "
            "Only for crews seeking the ultimate test."
        ),
        enemy_damage_multiplier=1.6,
        enemy_accuracy=1.3,
        enemy_health_multiplier=1.6,
        enemy_count_multiplier=1.5,
        enemy_ai_aggression=1.0,
        component_damage_chance=0.8,
        component_severity_multiplier=1.6,
        cook_off_chance_multiplier=2.0,
        repair_speed_multiplier=0.6,
        injury_chance=0.6,
        injury_severity_bias=0.8,
        degradation_timer_multiplier=0.5,
        death_timer_multiplier=0.5,
        contagion_spread_chance=0.5,
        starting_torpedo_multiplier=0.6,
        medical_supply_multiplier=0.6,
        battery_capacity_multiplier=0.75,
        fuel_consumption_multiplier=1.5,
        starting_credits_multiplier=0.5,
        sensor_range_multiplier=0.8,
        scan_time_multiplier=1.5,
        fog_of_war_reveal=0.0,
        hazard_damage_multiplier=1.6,
        event_interval_multiplier=0.5,
        event_overlap_max=5,
        docking_service_multiplier=1.5,
        boarding_frequency_multiplier=1.75,
        puzzle_time_mult=0.6,
        hints_enabled=False,
    ),
}


def get_preset(name: str) -> DifficultyPreset:
    """Return the named preset. Unknown names fall back to 'officer'."""
    return PRESETS.get(name, PRESETS["officer"])


def preset_summary(preset: DifficultyPreset) -> str:
    """Return a short human-readable summary of key differences from Officer."""
    parts: list[str] = []
    if preset.enemy_damage_multiplier != 1.0:
        parts.append(f"Enemy damage {preset.enemy_damage_multiplier:.0%}")
    if preset.repair_speed_multiplier != 1.0:
        parts.append(f"Repair speed {preset.repair_speed_multiplier:.0%}")
    if preset.starting_torpedo_multiplier != 1.0:
        parts.append(f"Torpedoes {preset.starting_torpedo_multiplier:.0%}")
    if preset.medical_supply_multiplier != 1.0:
        parts.append(f"Supplies {preset.medical_supply_multiplier:.0%}")
    if preset.hints_enabled:
        parts.append("Hints ON")
    return ", ".join(parts) if parts else "Standard"


# Backward compat alias
DifficultySettings = DifficultyPreset
