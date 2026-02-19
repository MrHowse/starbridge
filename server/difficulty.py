"""
Difficulty presets for Starbridge.

Provides DifficultySettings dataclass and named presets that scale
combat damage, puzzle timers, spawn rates, and crew casualties.

Usage (in game_loop.py):
    from server.difficulty import get_preset, DifficultySettings
    ship.difficulty = get_preset("cadet")
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DifficultySettings:
    """Multipliers applied at game start to scale challenge level.

    All multipliers are positive floats where 1.0 = default (Officer) difficulty.
    """

    enemy_damage_mult: float = 1.0   # Scales incoming beam/torpedo damage
    puzzle_time_mult: float = 1.0    # Scales puzzle time limits (>1 = more time)
    spawn_rate_mult: float = 1.0     # Scales enemy wave spawn rates
    crew_casualty_mult: float = 1.0  # Scales crew casualties per hull damage
    hints_enabled: bool = False      # Cadet mode: show suggested targets / actions


PRESETS: dict[str, DifficultySettings] = {
    "cadet":     DifficultySettings(0.5,  1.5, 0.75, 0.5,  hints_enabled=True),
    "officer":   DifficultySettings(1.0,  1.0, 1.0,  1.0,  hints_enabled=False),
    "commander": DifficultySettings(1.3,  0.8, 1.2,  1.3,  hints_enabled=False),
    "admiral":   DifficultySettings(1.6,  0.6, 1.5,  1.6,  hints_enabled=False),
}


def get_preset(name: str) -> DifficultySettings:
    """Return the named preset. Unknown names fall back to 'officer'."""
    return PRESETS.get(name, PRESETS["officer"])
