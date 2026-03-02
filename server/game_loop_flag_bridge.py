"""
Flag Bridge — Cruiser Captain Enhanced Tactical (v0.07 §2.4).

Active only on a cruiser.  Provides:
  - Tactical drawings (waypoints, arrows, danger zones, objective markers)
    visible to Helm + Tactical as "Captain's Plan".
  - Engagement timeline: predicted ETAs to torpedo/beam range for each enemy.
  - Target priority queue set by Captain, broadcast to Weapons.
  - Fleet coordination stubs for future multi-ship play.

Lifecycle: reset(active) → add_drawing / set_priority_queue from handlers
→ compute_timeline(world, ship) each broadcast → build_state() for broadcast.
"""
from __future__ import annotations

import math

from server.models.ship import Ship
from server.models.world import World
from server.utils.math_helpers import distance

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TORPEDO_RANGE: float = 15_000.0     # estimated torpedo engagement range
BEAM_RANGE_DEFAULT: float = 8_000.0  # fallback beam engagement range
DRAWING_TYPES = frozenset({"waypoint", "arrow", "danger_zone", "objective"})
MAX_DRAWINGS: int = 20
MAX_PRIORITY_TARGETS: int = 10

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_flag_bridge_active: bool = False
_drawings: list[dict] = []
_drawing_counter: int = 0
_priority_queue: list[str] = []       # ordered entity IDs
_weapons_override: bool = False       # True when Weapons overrides Captain's priority
_fleet_ships: list[dict] = []         # stub for fleet coordination
_fleet_orders: list[dict] = []        # stub

# ---------------------------------------------------------------------------
# Public API — lifecycle
# ---------------------------------------------------------------------------


def reset(active: bool = False) -> None:
    """Reset all flag bridge state.  *active* should be True for cruiser."""
    global _flag_bridge_active, _drawing_counter, _weapons_override
    _flag_bridge_active = active
    _drawings.clear()
    _drawing_counter = 0
    _priority_queue.clear()
    _weapons_override = False
    _fleet_ships.clear()
    _fleet_orders.clear()


def is_active() -> bool:
    """True when the flag bridge is enabled (cruiser only)."""
    return _flag_bridge_active

# ---------------------------------------------------------------------------
# Tactical drawings
# ---------------------------------------------------------------------------


def add_drawing(
    drawing_type: str,
    x: float,
    y: float,
    label: str = "",
    x2: float | None = None,
    y2: float | None = None,
    colour: str = "#ffaa00",
) -> dict:
    """Add a tactical drawing to the Captain's Plan.

    Returns ``{ok: True, id: "..."}`` or ``{ok: False, reason: "..."}``."""
    global _drawing_counter
    if not _flag_bridge_active:
        return {"ok": False, "reason": "not_active"}
    if drawing_type not in DRAWING_TYPES:
        return {"ok": False, "reason": "invalid_type"}
    if len(_drawings) >= MAX_DRAWINGS:
        return {"ok": False, "reason": "max_drawings"}
    _drawing_counter += 1
    drawing_id = f"draw_{_drawing_counter}"
    drawing: dict = {
        "id": drawing_id,
        "type": drawing_type,
        "x": round(x, 1),
        "y": round(y, 1),
        "label": label,
        "colour": colour,
    }
    if x2 is not None:
        drawing["x2"] = round(x2, 1)
    if y2 is not None:
        drawing["y2"] = round(y2, 1)
    _drawings.append(drawing)
    return {"ok": True, "id": drawing_id}


def remove_drawing(drawing_id: str) -> dict:
    """Remove a drawing by ID.  Returns ``{ok}`` or ``{ok: False, reason}``."""
    for i, d in enumerate(_drawings):
        if d["id"] == drawing_id:
            _drawings.pop(i)
            return {"ok": True}
    return {"ok": False, "reason": "not_found"}


def clear_drawings() -> dict:
    """Remove all drawings.  Returns ``{ok, cleared}``."""
    n = len(_drawings)
    _drawings.clear()
    return {"ok": True, "cleared": n}


def get_drawings() -> list[dict]:
    """Return a copy of the current drawing list."""
    return list(_drawings)

# ---------------------------------------------------------------------------
# Target priority queue
# ---------------------------------------------------------------------------


def set_priority_queue(entity_ids: list[str]) -> dict:
    """Set the Captain's target priority queue.  Resets weapons override."""
    global _weapons_override
    # Deduplicate while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for eid in entity_ids:
        if eid not in seen:
            seen.add(eid)
            deduped.append(eid)
    _priority_queue.clear()
    _priority_queue.extend(deduped[:MAX_PRIORITY_TARGETS])
    _weapons_override = False
    return {"ok": True}


def clear_priority_queue() -> dict:
    """Clear the priority queue."""
    _priority_queue.clear()
    return {"ok": True}


def get_priority_queue() -> list[str]:
    """Return the current priority queue (ordered entity IDs)."""
    return list(_priority_queue)


def set_weapons_override(override: bool) -> None:
    """Weapons signals it is overriding (or restoring) Captain's priority."""
    global _weapons_override
    _weapons_override = override


def is_weapons_override() -> bool:
    """True when Weapons has overridden the Captain's priority queue."""
    return _weapons_override

# ---------------------------------------------------------------------------
# Engagement timeline
# ---------------------------------------------------------------------------


def compute_timeline(world: World, ship: Ship) -> list[dict]:
    """Compute predicted engagement events sorted by ETA.

    Each entry: ``{type, label, eta_s, entity_id?}``.
    Returns an empty list when the flag bridge is inactive.
    """
    if not _flag_bridge_active:
        return []

    # Ship velocity components from heading + speed.
    ship_rad = math.radians(ship.heading)
    ship_vx = ship.velocity * math.sin(ship_rad)
    ship_vy = -ship.velocity * math.cos(ship_rad)

    entries: list[dict] = []
    for enemy in world.enemies:
        dist = distance(ship.x, ship.y, enemy.x, enemy.y)
        if dist == 0.0:
            # Already overlapping — both ranges at ETA 0.
            for rtype, rng, lbl in _range_defs(ship):
                entries.append({
                    "type": rtype,
                    "label": f"{enemy.type} in {lbl}",
                    "eta_s": 0.0,
                    "entity_id": enemy.id,
                })
            continue

        # Enemy velocity components from heading + speed.
        e_rad = math.radians(enemy.heading)
        e_vx = enemy.velocity * math.sin(e_rad)
        e_vy = -enemy.velocity * math.cos(e_rad)

        # Closing speed: rate at which distance decreases (positive = approaching).
        # d(dist)/dt = ((ex-sx)*(evx-svx) + (ey-sy)*(evy-svy)) / dist
        # Positive means separating, so negate for closing speed.
        rel_vx = e_vx - ship_vx
        rel_vy = e_vy - ship_vy
        sep_rate = ((enemy.x - ship.x) * rel_vx + (enemy.y - ship.y) * rel_vy) / dist
        closing = -sep_rate  # positive = approaching

        for rtype, rng, lbl in _range_defs(ship):
            gap = dist - rng
            if gap <= 0.0:
                entries.append({
                    "type": rtype,
                    "label": f"{enemy.type} in {lbl}",
                    "eta_s": 0.0,
                    "entity_id": enemy.id,
                })
            elif closing > 0.0:
                entries.append({
                    "type": rtype,
                    "label": f"{enemy.type} {lbl}",
                    "eta_s": round(gap / closing, 1),
                    "entity_id": enemy.id,
                })

    entries.sort(key=lambda e: e["eta_s"])
    return entries


def _range_defs(ship) -> list[tuple[str, float, str]]:
    """Per-ship engagement range thresholds for timeline computation."""
    return [
        ("torpedo_range", TORPEDO_RANGE, "torpedo range"),
        ("beam_range", getattr(ship, "beam_range", BEAM_RANGE_DEFAULT), "beam range"),
    ]

# ---------------------------------------------------------------------------
# Fleet coordination stubs (§2.4.5)
# ---------------------------------------------------------------------------


def issue_fleet_order(
    order_type: str,
    target_id: str | None = None,
    position: tuple[float, float] | None = None,
) -> dict:
    """Placeholder for future fleet coordination.  Always returns not_implemented."""
    return {"ok": False, "reason": "not_implemented"}


def get_fleet_ships() -> list[dict]:
    """Return allied fleet ship data.  Stub — always empty."""
    return list(_fleet_ships)

# ---------------------------------------------------------------------------
# State / serialisation
# ---------------------------------------------------------------------------


def build_state(world: World, ship: Ship) -> dict:
    """Build full flag bridge state for broadcast to Captain."""
    return {
        "flag_bridge_active": _flag_bridge_active,
        "drawings": list(_drawings),
        "priority_queue": list(_priority_queue),
        "weapons_override": _weapons_override,
        "timeline": compute_timeline(world, ship),
        "fleet_ships": list(_fleet_ships),
    }


def serialise() -> dict:
    """Capture flag bridge state for save/resume."""
    return {
        "flag_bridge_active": _flag_bridge_active,
        "drawings": list(_drawings),
        "drawing_counter": _drawing_counter,
        "priority_queue": list(_priority_queue),
        "weapons_override": _weapons_override,
    }


def deserialise(data: dict) -> None:
    """Restore flag bridge state from save data."""
    global _flag_bridge_active, _drawing_counter, _weapons_override
    _flag_bridge_active = data.get("flag_bridge_active", False)
    _drawings.clear()
    _drawings.extend(data.get("drawings", []))
    _drawing_counter = data.get("drawing_counter", 0)
    _priority_queue.clear()
    _priority_queue.extend(data.get("priority_queue", []))
    _weapons_override = data.get("weapons_override", False)
    _fleet_ships.clear()
    _fleet_orders.clear()
