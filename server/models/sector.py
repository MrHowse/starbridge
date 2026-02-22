"""
Sector System — v0.05b.

Divides the game world into a named sector grid with fog-of-war visibility
states, sector properties, and strategic features.

Each sector covers a rectangular region of world space.  Entity coordinates
remain in global world space; sectors are an overlay labelling system.

Key types:
    SectorVisibility  — 6-level fog-of-war enum
    Rect              — axis-aligned bounding rectangle
    SectorProperties  — gameplay modifiers for a sector
    SectorFeature     — named strategic feature within a sector
    PatrolRoute       — NPC patrol path within a sector
    Sector            — single grid cell with all its data
    SectorGrid        — full grid; spatial lookup, adjacency, FoW management

Public API:
    load_sector_grid(layout_id) → SectorGrid
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger("starbridge.sector")

# Sector data files live at the project root.
SECTORS_DIR = Path(__file__).parent.parent.parent / "sectors"


# ---------------------------------------------------------------------------
# Fog-of-war visibility enum
# ---------------------------------------------------------------------------


class SectorVisibility(str, Enum):
    """Six-level fog-of-war for sector map awareness.

    Progression:
        UNKNOWN      → TRANSPONDER (auto-reveal from friendly beacons)
        UNKNOWN      → SCANNED     (multi-sector Science scan)
        SCANNED      → SURVEYED    (sector-sweep scan while adjacent)
        SURVEYED     → ACTIVE      (ship enters sector)
        ACTIVE       → VISITED     (ship leaves sector)
    """
    UNKNOWN     = "unknown"
    TRANSPONDER = "transponder"
    SCANNED     = "scanned"
    SURVEYED    = "surveyed"
    ACTIVE      = "active"
    VISITED     = "visited"


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass
class Rect:
    """An axis-aligned bounding rectangle in world coordinates."""
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def contains(self, x: float, y: float) -> bool:
        """Return True if (x, y) is inside or on the left/top edge."""
        return self.min_x <= x < self.max_x and self.min_y <= y < self.max_y


@dataclass
class SectorProperties:
    """Gameplay modifiers applied while the ship is in this sector."""
    type: str = "deep_space"
    sensor_modifier: float = 1.0
    navigation_hazard: str = "none"
    faction: str = "unclaimed"
    threat_level: str = "low"


@dataclass
class SectorFeature:
    """A named strategic feature visible on the sector or strategic map."""
    id: str
    type: str
    position: tuple[float, float]
    name: str = ""
    visible_without_scan: bool = False


@dataclass
class PatrolRoute:
    """A repeating NPC patrol path defined by waypoints."""
    faction: str
    waypoints: list[tuple[float, float]] = field(default_factory=list)
    ship_count: int = 1
    ship_type: str = "scout"


# ---------------------------------------------------------------------------
# Sector and SectorGrid
# ---------------------------------------------------------------------------


@dataclass
class Sector:
    """A single cell in the sector grid."""
    id: str
    name: str
    grid_position: tuple[int, int]   # (col, row), zero-indexed
    world_bounds: Rect
    properties: SectorProperties = field(default_factory=SectorProperties)
    features: list[SectorFeature] = field(default_factory=list)
    patrol_routes: list[PatrolRoute] = field(default_factory=list)
    visibility: SectorVisibility = SectorVisibility.UNKNOWN


@dataclass
class SectorGrid:
    """The complete multi-sector grid for a mission.

    Sectors are keyed by their ID string (e.g. ``"A1"``).
    ``grid_size`` is ``(columns, rows)`` — purely informational.
    ``layout_id`` records the source JSON file so saves can reload the grid.
    """
    sectors: dict[str, Sector]
    grid_size: tuple[int, int]
    layout_id: str = ""

    # ------------------------------------------------------------------
    # Spatial queries
    # ------------------------------------------------------------------

    def sector_at_position(self, x: float, y: float) -> Sector | None:
        """Return the sector whose world_bounds contain (x, y), or None."""
        for sector in self.sectors.values():
            if sector.world_bounds.contains(x, y):
                return sector
        return None

    def adjacent_sectors(self, sector_id: str) -> list[Sector]:
        """Return all sectors sharing a border or corner with *sector_id*.

        Returns up to 8 neighbours (cardinal + diagonal).
        """
        base = self.sectors.get(sector_id)
        if base is None:
            return []
        col, row = base.grid_position
        result: list[Sector] = []
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if dc == 0 and dr == 0:
                    continue
                nc, nr = col + dc, row + dr
                for s in self.sectors.values():
                    if s.grid_position == (nc, nr):
                        result.append(s)
        return result

    # ------------------------------------------------------------------
    # Visibility management
    # ------------------------------------------------------------------

    def set_visibility(self, sector_id: str, level: SectorVisibility) -> None:
        """Directly set the visibility of a sector."""
        sector = self.sectors.get(sector_id)
        if sector is not None:
            sector.visibility = level

    def update_ship_position(self, x: float, y: float) -> str | None:
        """Mark the sector containing (x, y) as Active.  Returns its ID.

        Only updates visibility if the sector is not already Active, so
        calling this every tick is cheap.
        """
        sector = self.sector_at_position(x, y)
        if sector is None:
            return None
        if sector.visibility != SectorVisibility.ACTIVE:
            sector.visibility = SectorVisibility.ACTIVE
        return sector.id

    def on_sector_leave(self, sector_id: str) -> None:
        """Transition the given sector from Active → Visited when the ship departs."""
        sector = self.sectors.get(sector_id)
        if sector is not None and sector.visibility == SectorVisibility.ACTIVE:
            sector.visibility = SectorVisibility.VISITED

    def apply_transponder_reveals(self) -> None:
        """Auto-reveal Unknown sectors that contain transponder-broadcasting features.

        Any feature whose type is ``"friendly_station"`` or ``"transponder"``
        and whose ``visible_without_scan`` is True causes the sector to jump
        from UNKNOWN to TRANSPONDER.
        """
        TRANSPONDER_TYPES = {"friendly_station", "transponder"}
        for sector in self.sectors.values():
            if sector.visibility != SectorVisibility.UNKNOWN:
                continue
            for feature in sector.features:
                if feature.visible_without_scan and feature.type in TRANSPONDER_TYPES:
                    sector.visibility = SectorVisibility.TRANSPONDER
                    break

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def serialise(self) -> dict:
        """Return a ``{sector_id: visibility_value}`` dict for save/resume."""
        return {sid: s.visibility.value for sid, s in self.sectors.items()}

    def deserialise_visibility(self, data: dict) -> None:
        """Restore visibility states from a ``{sector_id: value}`` dict.

        Unknown sector IDs and invalid values are silently ignored so old saves
        don't crash when sector definitions change.
        """
        for sid, vis_str in data.items():
            if sid in self.sectors:
                try:
                    self.sectors[sid].visibility = SectorVisibility(vis_str)
                except ValueError:
                    logger.warning("Unknown visibility value %r for sector %r", vis_str, sid)


# ---------------------------------------------------------------------------
# JSON loading
# ---------------------------------------------------------------------------


def load_sector_grid(layout_id: str) -> SectorGrid:
    """Load a sector grid from ``sectors/<layout_id>.json``.

    Raises FileNotFoundError if the layout file does not exist.
    """
    path = SECTORS_DIR / f"{layout_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Sector layout not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    grid = _sector_grid_from_dict(data)
    grid.layout_id = layout_id
    return grid


def _sector_grid_from_dict(data: dict) -> SectorGrid:
    """Parse a SectorGrid from its JSON representation."""
    cols, rows = int(data["grid_size"][0]), int(data["grid_size"][1])
    sectors: dict[str, Sector] = {}

    for s in data["sectors"]:
        wb = s["world_bounds"]
        bounds = Rect(
            min_x=float(wb["min_x"]),
            min_y=float(wb["min_y"]),
            max_x=float(wb["max_x"]),
            max_y=float(wb["max_y"]),
        )

        props_d = s.get("properties", {})
        props = SectorProperties(
            type=props_d.get("type", "deep_space"),
            sensor_modifier=float(props_d.get("sensor_modifier", 1.0)),
            navigation_hazard=props_d.get("navigation_hazard", "none"),
            faction=props_d.get("faction", "unclaimed"),
            threat_level=props_d.get("threat_level", "low"),
        )

        features = [
            SectorFeature(
                id=f["id"],
                type=f["type"],
                position=(float(f["position"][0]), float(f["position"][1])),
                name=f.get("name", ""),
                visible_without_scan=bool(f.get("visible_without_scan", False)),
            )
            for f in s.get("features", [])
        ]

        patrol_routes = [
            PatrolRoute(
                faction=p["faction"],
                waypoints=[(float(w[0]), float(w[1])) for w in p["waypoints"]],
                ship_count=int(p.get("ship_count", 1)),
                ship_type=p.get("ship_type", "scout"),
            )
            for p in s.get("patrol_routes", [])
        ]

        sector = Sector(
            id=s["id"],
            name=s["name"],
            grid_position=(int(s["grid_position"][0]), int(s["grid_position"][1])),
            world_bounds=bounds,
            properties=props,
            features=features,
            patrol_routes=patrol_routes,
        )
        sectors[sector.id] = sector

    return SectorGrid(sectors=sectors, grid_size=(cols, rows))
