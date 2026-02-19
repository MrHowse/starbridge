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
]


class ShipClass(BaseModel):
    """Stat block for a ship class, loaded from ships/<id>.json."""

    id:          str
    name:        str
    description: str
    max_hull:    float = 100.0
    torpedo_ammo: int  = 12


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
