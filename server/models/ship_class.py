"""
Ship Class Model.

Defines the configurable stats for each ship class (scout, corvette, frigate,
cruiser, battleship). Stats are loaded from JSON files in the top-level
``ships/`` directory.

Usage:
    from server.models.ship_class import load_ship_class, list_ship_classes

    sc = load_ship_class("frigate")
    ship.hull = sc.max_hull
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

_SHIPS_DIR = Path(__file__).parent.parent.parent / "ships"

# Canonical ordering for lobby display.
SHIP_CLASS_ORDER: list[str] = [
    "scout",
    "corvette",
    "frigate",
    "cruiser",
    "battleship",
    "medical_ship",
    "carrier",
]


DEFAULT_TORPEDO_LOADOUT: dict[str, int] = {
    "standard": 8, "homing": 4, "ion": 4, "piercing": 4,
    "heavy": 2, "proximity": 4, "nuclear": 1, "experimental": 0,
}


VALID_HANDLING_TRAITS: set[str] = {
    "twitchy", "smooth", "clean", "steady", "ponderous", "heavy", "gentle",
}


class ShipClass(BaseModel):
    """Stat block for a ship class, loaded from ships/<id>.json."""

    id:               str
    name:             str
    description:      str
    max_hull:         float = 100.0

    # --- Physical profile (v0.07) ---
    max_speed:        float = 200.0   # world units/sec at 100 % engine efficiency
    acceleration:     float = 50.0    # world units/sec²
    turn_rate:        float = 90.0    # degrees/sec at 100 % manoeuvring efficiency
    target_profile:   float = 1.0     # 0.0-1.0 — hit probability multiplier
    armour:           float = 0.0     # damage absorbed per hit (between shields and hull)
    handling_trait:    str   = "clean" # affects helm feel — see VALID_HANDLING_TRAITS
    decks:            int   = 5       # number of physical decks

    # --- Engines (v0.07 §1.8) ---
    engines:          dict | None = None     # {fuel_multiplier}

    # --- Sensors (v0.07 §1.7) ---
    sensors:          dict | None = None     # {range}

    # --- Shields (v0.07 §1.6) ---
    shields:          dict | None = None     # {capacity, recharge_rate}

    # --- Weapons loadout (v0.07 §1.5) ---
    weapons:          dict | None = None     # {beam_damage, beam_fire_rate, beam_arc, ...}

    # --- Power grid (v0.07 §1.4) ---
    power_grid:       dict | None = None     # {reactor_max, battery_capacity, ...}

    # --- Integration (v0.07 §5) ---
    unique_systems:   list[str] = []    # e.g. ["stealth"], ["advanced_ecm"]
    modular_bays:     int   = 0         # equipment module slots (frigate=2)
    interior_layout:  str   = ""        # reference to interiors/{name}.json

    # --- Legacy / weapons ---
    torpedo_ammo:     int   = 12             # legacy field (kept for save-compat)
    torpedo_loadout:  dict[str, int] | None = None  # per-type magazine (v0.05g)
    min_crew:         int   = 1    # minimum players for a satisfying game
    max_crew:         int   = 12   # maximum designed crew complement

    def get_torpedo_loadout(self) -> dict[str, int]:
        """Return the per-type torpedo loadout for this ship class.

        Uses ``torpedo_loadout`` if defined; otherwise scales ``DEFAULT_TORPEDO_LOADOUT``
        proportionally to ``torpedo_ammo`` (backward compat with legacy JSON).
        """
        if self.torpedo_loadout is not None:
            return dict(self.torpedo_loadout)
        return dict(DEFAULT_TORPEDO_LOADOUT)


def load_ship_class(ship_class_id: str) -> ShipClass:
    """Load a ShipClass from ships/<ship_class_id>.json.

    Raises FileNotFoundError if the class does not exist.
    """
    path = _SHIPS_DIR / f"{ship_class_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Unknown ship class: {ship_class_id!r}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return ShipClass(**data)


def list_ship_classes() -> list[ShipClass]:
    """Return all available ship classes in canonical lobby display order."""
    classes = []
    for cid in SHIP_CLASS_ORDER:
        path = _SHIPS_DIR / f"{cid}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            classes.append(ShipClass(**data))
    return classes
