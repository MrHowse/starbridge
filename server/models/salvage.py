"""
Salvage Model — v0.07 Phase 6.5.

Defines Wreck and SalvageItem dataclasses, loot tables, and constants for the
salvage system.  Wrecks spawn when enemies die; the Quartermaster assesses and
extracts salvage with risk mechanics (booby traps, unstable reactors).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SALVAGE_RANGE: float = 2000.0
SALVAGE_MAX_SPEED: float = 10.0
SCAN_DURATION: float = 10.0
BOOBY_TRAP_CHANCE: float = 0.10
UNSTABLE_REACTOR_CHANCE: float = 0.15
REACTOR_TIMER: float = 120.0
REACTOR_DAMAGE_MIN: float = 20.0
REACTOR_DAMAGE_MAX: float = 40.0
REACTOR_BLAST_RANGE: float = 2000.0
DIRECT_USE_EFFICIENCY: float = 0.70
TRAP_TEAM_DAMAGE: float = 25.0
WRECK_DESPAWN_TIME: float = 600.0

SOURCE_TYPES: tuple[str, ...] = ("enemy", "derelict", "debris")
ENEMY_TYPES: tuple[str, ...] = ("fighter", "scout", "cruiser", "destroyer", "derelict", "debris")
SCAN_STATES: tuple[str, ...] = ("unscanned", "scanning", "scanned")
SALVAGE_STATES: tuple[str, ...] = ("idle", "salvaging", "complete", "aborted")


# ---------------------------------------------------------------------------
# Loot tables
# ---------------------------------------------------------------------------

# Per enemy_type -> list of item templates.
# Each template: {name, item_type, qty_min, qty_max, cargo_size, salvage_time, value, is_direct_use}
WRECK_LOOT_TABLES: dict[str, list[dict]] = {
    "fighter": [
        {"name": "Fuel Cells", "item_type": "fuel", "qty_min": 10, "qty_max": 30,
         "cargo_size": 1.0, "salvage_time": 30.0, "value": 20.0, "is_direct_use": True},
        {"name": "Ammunition Crate", "item_type": "ammunition", "qty_min": 5, "qty_max": 15,
         "cargo_size": 1.0, "salvage_time": 30.0, "value": 20.0, "is_direct_use": True},
    ],
    "scout": [
        {"name": "Fuel Cells", "item_type": "fuel", "qty_min": 15, "qty_max": 40,
         "cargo_size": 1.5, "salvage_time": 40.0, "value": 30.0, "is_direct_use": True},
        {"name": "Sensor Components", "item_type": "components", "qty_min": 1, "qty_max": 3,
         "cargo_size": 2.0, "salvage_time": 60.0, "value": 80.0, "is_direct_use": False},
        {"name": "Data Core", "item_type": "data_core", "qty_min": 1, "qty_max": 1,
         "cargo_size": 0.5, "salvage_time": 45.0, "value": 120.0, "is_direct_use": False},
    ],
    "cruiser": [
        {"name": "Fuel Reserves", "item_type": "fuel", "qty_min": 30, "qty_max": 80,
         "cargo_size": 3.0, "salvage_time": 60.0, "value": 60.0, "is_direct_use": True},
        {"name": "Repair Materials", "item_type": "repair_materials", "qty_min": 5, "qty_max": 15,
         "cargo_size": 2.0, "salvage_time": 50.0, "value": 60.0, "is_direct_use": True},
        {"name": "Medical Supplies", "item_type": "medical_supplies", "qty_min": 3, "qty_max": 10,
         "cargo_size": 1.5, "salvage_time": 40.0, "value": 25.0, "is_direct_use": True},
        {"name": "Ship Components", "item_type": "components", "qty_min": 2, "qty_max": 5,
         "cargo_size": 3.0, "salvage_time": 90.0, "value": 150.0, "is_direct_use": False},
        {"name": "Data Core", "item_type": "data_core", "qty_min": 1, "qty_max": 2,
         "cargo_size": 0.5, "salvage_time": 45.0, "value": 120.0, "is_direct_use": False},
    ],
    "destroyer": [
        {"name": "Fuel Reserves", "item_type": "fuel", "qty_min": 40, "qty_max": 100,
         "cargo_size": 4.0, "salvage_time": 70.0, "value": 80.0, "is_direct_use": True},
        {"name": "Repair Materials", "item_type": "repair_materials", "qty_min": 8, "qty_max": 20,
         "cargo_size": 3.0, "salvage_time": 60.0, "value": 80.0, "is_direct_use": True},
        {"name": "Ammunition Cache", "item_type": "ammunition", "qty_min": 10, "qty_max": 25,
         "cargo_size": 2.5, "salvage_time": 50.0, "value": 50.0, "is_direct_use": True},
        {"name": "Advanced Components", "item_type": "components", "qty_min": 3, "qty_max": 8,
         "cargo_size": 4.0, "salvage_time": 120.0, "value": 250.0, "is_direct_use": False},
        {"name": "Encrypted Data Core", "item_type": "data_core", "qty_min": 1, "qty_max": 2,
         "cargo_size": 0.5, "salvage_time": 60.0, "value": 200.0, "is_direct_use": False},
    ],
    "derelict": [
        {"name": "Salvageable Fuel", "item_type": "fuel", "qty_min": 20, "qty_max": 60,
         "cargo_size": 2.0, "salvage_time": 50.0, "value": 40.0, "is_direct_use": True},
        {"name": "Provisions", "item_type": "provisions", "qty_min": 10, "qty_max": 30,
         "cargo_size": 1.5, "salvage_time": 35.0, "value": 15.0, "is_direct_use": True},
        {"name": "Scrap Metal", "item_type": "components", "qty_min": 1, "qty_max": 4,
         "cargo_size": 3.0, "salvage_time": 80.0, "value": 100.0, "is_direct_use": False},
    ],
    "debris": [
        {"name": "Fuel Residue", "item_type": "fuel", "qty_min": 5, "qty_max": 20,
         "cargo_size": 1.0, "salvage_time": 30.0, "value": 10.0, "is_direct_use": True},
        {"name": "Scrap", "item_type": "components", "qty_min": 1, "qty_max": 2,
         "cargo_size": 2.0, "salvage_time": 60.0, "value": 40.0, "is_direct_use": False},
    ],
}


# ---------------------------------------------------------------------------
# SalvageItem
# ---------------------------------------------------------------------------


@dataclass
class SalvageItem:
    """A single salvageable item within a wreck."""

    id: str
    name: str
    item_type: str       # "fuel" | "medical_supplies" | "components" | "data_core" | etc.
    quantity: float
    cargo_size: float    # cargo units occupied
    salvage_time: float  # seconds to extract (30-120)
    value: float         # estimated credit value
    is_direct_use: bool  # True -> ResourceStore at 70%; False -> ship.cargo
    salvaged: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "item_type": self.item_type,
            "quantity": self.quantity,
            "cargo_size": self.cargo_size,
            "salvage_time": self.salvage_time,
            "value": self.value,
            "is_direct_use": self.is_direct_use,
            "salvaged": self.salvaged,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SalvageItem:
        return cls(
            id=data["id"],
            name=data["name"],
            item_type=data["item_type"],
            quantity=data["quantity"],
            cargo_size=data["cargo_size"],
            salvage_time=data["salvage_time"],
            value=data["value"],
            is_direct_use=data["is_direct_use"],
            salvaged=data.get("salvaged", False),
        )


# ---------------------------------------------------------------------------
# Wreck
# ---------------------------------------------------------------------------


@dataclass
class Wreck:
    """A salvageable wreck in the game world."""

    id: str
    x: float
    y: float
    source_type: str           # "enemy" | "derelict" | "debris"
    source_id: str             # original enemy/station ID
    enemy_type: str            # "fighter"/"scout"/"cruiser"/"destroyer"/"derelict"/"debris"
    scan_state: str = "unscanned"   # unscanned | scanning | scanned
    scan_progress: float = 0.0
    salvage_manifest: list[SalvageItem] = field(default_factory=list)
    booby_trapped: bool = False
    trap_detected: bool = False
    unstable_reactor: bool = False
    reactor_detected: bool = False
    reactor_timer: float = 0.0
    reactor_armed: bool = False
    salvage_state: str = "idle"      # idle | salvaging | complete | aborted
    salvage_queue: list[str] = field(default_factory=list)
    current_item_id: str | None = None
    salvage_timer: float = 0.0
    despawn_timer: float = WRECK_DESPAWN_TIME
    created_tick: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "x": self.x,
            "y": self.y,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "enemy_type": self.enemy_type,
            "scan_state": self.scan_state,
            "scan_progress": self.scan_progress,
            "salvage_manifest": [item.to_dict() for item in self.salvage_manifest],
            "booby_trapped": self.booby_trapped,
            "trap_detected": self.trap_detected,
            "unstable_reactor": self.unstable_reactor,
            "reactor_detected": self.reactor_detected,
            "reactor_timer": self.reactor_timer,
            "reactor_armed": self.reactor_armed,
            "salvage_state": self.salvage_state,
            "salvage_queue": list(self.salvage_queue),
            "current_item_id": self.current_item_id,
            "salvage_timer": self.salvage_timer,
            "despawn_timer": self.despawn_timer,
            "created_tick": self.created_tick,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Wreck:
        return cls(
            id=data["id"],
            x=data["x"],
            y=data["y"],
            source_type=data["source_type"],
            source_id=data["source_id"],
            enemy_type=data["enemy_type"],
            scan_state=data.get("scan_state", "unscanned"),
            scan_progress=data.get("scan_progress", 0.0),
            salvage_manifest=[
                SalvageItem.from_dict(i) for i in data.get("salvage_manifest", [])
            ],
            booby_trapped=data.get("booby_trapped", False),
            trap_detected=data.get("trap_detected", False),
            unstable_reactor=data.get("unstable_reactor", False),
            reactor_detected=data.get("reactor_detected", False),
            reactor_timer=data.get("reactor_timer", 0.0),
            reactor_armed=data.get("reactor_armed", False),
            salvage_state=data.get("salvage_state", "idle"),
            salvage_queue=list(data.get("salvage_queue", [])),
            current_item_id=data.get("current_item_id"),
            salvage_timer=data.get("salvage_timer", 0.0),
            despawn_timer=data.get("despawn_timer", WRECK_DESPAWN_TIME),
            created_tick=data.get("created_tick", 0),
        )


# ---------------------------------------------------------------------------
# Loot generation
# ---------------------------------------------------------------------------

_item_counter: int = 0


def generate_salvage_manifest(
    enemy_type: str,
    rng: random.Random | None = None,
) -> list[SalvageItem]:
    """Generate a list of salvageable items for a wreck based on enemy type."""
    global _item_counter
    rng = rng or random.Random()
    templates = WRECK_LOOT_TABLES.get(enemy_type, WRECK_LOOT_TABLES["debris"])
    items: list[SalvageItem] = []
    for tmpl in templates:
        _item_counter += 1
        qty = rng.uniform(tmpl["qty_min"], tmpl["qty_max"])
        qty = round(qty, 1)
        items.append(SalvageItem(
            id=f"salvage_item_{_item_counter}",
            name=tmpl["name"],
            item_type=tmpl["item_type"],
            quantity=qty,
            cargo_size=tmpl["cargo_size"],
            salvage_time=tmpl["salvage_time"],
            value=tmpl["value"],
            is_direct_use=tmpl["is_direct_use"],
        ))
    return items
