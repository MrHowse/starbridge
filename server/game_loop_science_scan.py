"""
Science sector scanning — v0.05d.

Manages sector-sweep and long-range scan states.  Targeted entity scans are
handled by server/systems/sensors.py; this module adds the area-scan scales.

Scan scales
-----------
sector      — sector sweep (SECTOR_SWEEP_DURATION seconds).
              Reveals the current sector progressively → Surveyed.
long_range  — multi-sector scan (LONG_RANGE_DURATION seconds).
              Reveals adjacent sectors → Scanned.

Scan mode affects what is revealed in earlier phases:
    em   — energy signatures: stations, power sources
    grav — mass concentrations: asteroids, gravity wells, debris
    bio  — life signs: inhabited, creatures
    sub  — subspace phenomena: anomalies, cloaked, relays

Phase reveal schedule (progress %):
    Phase 0 (0–25 %)  : Large features (mode-affinity priority)
    Phase 1 (25–50 %) : Medium features
    Phase 2 (50–75 %) : Small features / individual contacts
    Phase 3 (75–100 %): Full detail / all feature types

Public API
----------
    reset()
    is_active() -> bool
    start_scan(scale, mode, sector_id, adjacent_ids) -> bool
    cancel_scan() -> bool
    set_interrupt_response(continue_scan) -> None
    tick(dt, world) -> list[dict]
    build_progress() -> dict
    get_scan_indicator() -> str | None
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.models.world import World

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Total duration for a full sector sweep (seconds).
SECTOR_SWEEP_DURATION: float = 30.0

#: Total duration for a long-range scan (seconds).
LONG_RANGE_DURATION: float = 90.0

#: Progress thresholds (%) that trigger each reveal phase.
PHASE_THRESHOLDS: list[float] = [0.0, 25.0, 50.0, 75.0]

#: Enemy distance (world units) that triggers a combat interrupt.
COMBAT_INTERRUPT_RANGE: float = 15_000.0

#: Feature types associated with each scan mode (for early-phase priority).
MODE_FEATURE_AFFINITY: dict[str, frozenset[str]] = {
    "em":   frozenset({"friendly_station", "enemy_station", "transponder", "outpost"}),
    "grav": frozenset({"asteroid_field", "gravity_well", "derelict", "debris"}),
    "bio":  frozenset({"creature", "life_sign", "inhabited", "organic"}),
    "sub":  frozenset({"anomaly", "subspace_relay", "cloaked", "distortion"}),
}


# ---------------------------------------------------------------------------
# Internal state dataclass
# ---------------------------------------------------------------------------


@dataclass
class _SectorScanState:
    scale: str                             # "sector" | "long_range"
    mode: str                              # "em" | "grav" | "bio" | "sub"
    sector_id: str                         # primary sector (for sweep: current sector)
    adjacent_ids: list[str] = field(default_factory=list)  # targets for long_range
    elapsed: float = 0.0
    interrupted: bool = False              # awaiting continue/abort from Science player
    cancelled: bool = False
    complete: bool = False
    _revealed_phase: int = -1             # highest phase whose reveals were applied
    scan_time_multiplier: float = 1.0     # from difficulty preset (>1 = slower)

    @property
    def duration(self) -> float:
        base = SECTOR_SWEEP_DURATION if self.scale == "sector" else LONG_RANGE_DURATION
        return base * max(0.1, self.scan_time_multiplier)

    @property
    def progress(self) -> float:
        return min(100.0, (self.elapsed / self.duration) * 100.0)

    @property
    def phase(self) -> int:
        """Current reveal phase 0–3 based on elapsed progress."""
        p = self.progress
        for i in range(len(PHASE_THRESHOLDS) - 1, -1, -1):
            if p >= PHASE_THRESHOLDS[i]:
                return i
        return 0


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_state: _SectorScanState | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset() -> None:
    """Clear all scan state.  Called from game_loop.start() and resume()."""
    global _state
    _state = None


def is_active() -> bool:
    """True if a sector or long-range scan is currently in progress."""
    return (
        _state is not None
        and not _state.cancelled
        and not _state.complete
    )


def start_scan(
    scale: str,
    mode: str,
    sector_id: str,
    adjacent_ids: list[str] | None = None,
    scan_time_multiplier: float = 1.0,
) -> bool:
    """Begin a new sector sweep or long-range scan.

    Returns False if a scan is already active (caller should cancel first).
    ``scale`` must be ``"sector"`` or ``"long_range"``.
    ``mode`` must be ``"em"``, ``"grav"``, ``"bio"``, or ``"sub"``.
    ``sector_id`` is the ID of the current sector (sector sweep target).
    ``adjacent_ids`` lists adjacent sector IDs (used for long_range scale).
    ``scan_time_multiplier`` scales duration (>1 = slower, from difficulty).
    """
    global _state
    if is_active():
        return False
    _state = _SectorScanState(
        scale=scale,
        mode=mode,
        sector_id=sector_id,
        adjacent_ids=list(adjacent_ids or []),
        scan_time_multiplier=scan_time_multiplier,
    )
    return True


def cancel_scan() -> bool:
    """Abort the current scan.  Partial visibility reveals already applied persist.

    Returns True if there was an active scan to cancel.
    """
    global _state
    if _state is None:
        return False
    _state.cancelled = True
    return True


def set_interrupt_response(continue_scan: bool) -> None:
    """Player responded to the combat-interrupt warning.

    ``continue_scan=True``  → resume the paused sweep.
    ``continue_scan=False`` → cancel the scan.
    """
    if _state is not None and _state.interrupted:
        if continue_scan:
            _state.interrupted = False
        else:
            _state.cancelled = True


def build_progress() -> dict:
    """Return the current scan progress as a serialisable dict.

    When no scan is active returns ``{"active": False}``.
    """
    if _state is None or _state.cancelled or _state.complete:
        return {"active": False}
    return {
        "active": True,
        "scale": _state.scale,
        "mode": _state.mode,
        "progress": round(_state.progress, 1),
        "phase": _state.phase,
        "sector_id": _state.sector_id,
        "interrupted": _state.interrupted,
    }


def get_scan_indicator() -> str | None:
    """Short status text for Captain/Helm map overlays.

    Returns None when no scan is active.
    Example: ``"SCIENCE: Sector sweep — 42%"``
    """
    if not is_active() or _state is None:
        return None
    label = "Sector sweep" if _state.scale == "sector" else "Long-range scan"
    return f"SCIENCE: {label} — {int(_state.progress)}%"


def get_active_mode() -> str | None:
    """Return the current scan mode, or None if no scan is active.

    Modes: ``"em"``, ``"grav"``, ``"bio"``, ``"sub"``.
    Used by game_loop_creatures to advance creature study during BIO scans.
    """
    if _state is None or _state.cancelled or _state.complete:
        return None
    return _state.mode


def tick(dt: float, world: "World") -> list[dict]:
    """Advance the scan by *dt* seconds and apply visibility reveals.

    Returns a list of event dicts for the game loop to act on:

    ``{"type": "progress"}``
        Emitted every tick while the scan is running (use ``build_progress()``
        to get the current data).

    ``{"type": "sector_visibility_changed"}``
        One or more sector visibility states were updated; the sector-grid
        broadcast should be triggered on this tick.

    ``{"type": "interrupted", "reason": str}``
        Combat detected — scan is paused awaiting player response.
        No further ticks are processed until ``set_interrupt_response()``
        is called.

    ``{"type": "complete", "scale": str, "sector_id": str, "mode": str}``
        Scan finished successfully.
    """
    global _state

    if _state is None or _state.cancelled or _state.complete or _state.interrupted:
        return []

    events: list[dict] = []

    # --- Combat interrupt check -------------------------------------------
    if _check_combat_interrupt(world):
        _state.interrupted = True
        events.append({"type": "interrupted", "reason": "combat"})
        return events

    # --- Advance elapsed time ---------------------------------------------
    _state.elapsed += dt

    # --- Phase reveal (applied once per phase crossing) -------------------
    current_phase = _state.phase
    if current_phase > _state._revealed_phase:
        for ph in range(_state._revealed_phase + 1, current_phase + 1):
            changed = _reveal_features_for_phase(ph, world)
            if changed:
                events.append({"type": "sector_visibility_changed"})
        _state._revealed_phase = current_phase

    # --- Progress event (always emitted while running) --------------------
    events.append({"type": "progress"})

    # --- Completion -------------------------------------------------------
    if _state.progress >= 100.0:
        _state.complete = True
        changed = _finalize_scan(world)
        if changed:
            events.append({"type": "sector_visibility_changed"})
        events.append({
            "type": "complete",
            "scale": _state.scale,
            "sector_id": _state.sector_id,
            "mode": _state.mode,
        })

    return events


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _check_combat_interrupt(world: "World") -> bool:
    """True when at least one enemy is within combat-interrupt range."""
    if not world.enemies:
        return False
    ship = world.ship
    for enemy in world.enemies:
        if math.hypot(enemy.x - ship.x, enemy.y - ship.y) < COMBAT_INTERRUPT_RANGE:
            return True
    return False


def _reveal_features_for_phase(phase: int, world: "World") -> bool:
    """Apply sector-visibility updates for the given reveal phase.

    Returns True if any sector visibility actually changed.
    """
    from server.models.sector import SectorVisibility

    if world.sector_grid is None or _state is None:
        return False

    grid = world.sector_grid
    changed = False

    if _state.scale == "sector":
        sid = _state.sector_id
        if sid in grid.sectors:
            sector = grid.sectors[sid]
            if phase < 3:
                # Phases 0-2: Scanned (if not already better).
                _NOT_BETTER = {
                    SectorVisibility.SCANNED,
                    SectorVisibility.SURVEYED,
                    SectorVisibility.ACTIVE,
                    SectorVisibility.VISITED,
                }
                if sector.visibility not in _NOT_BETTER:
                    grid.set_visibility(sid, SectorVisibility.SCANNED)
                    changed = True
            else:
                # Phase 3: Surveyed (unless ship is in-sector = Active).
                if sector.visibility != SectorVisibility.ACTIVE:
                    old = sector.visibility
                    grid.set_visibility(sid, SectorVisibility.SURVEYED)
                    if sector.visibility != old:
                        changed = True

    elif _state.scale == "long_range":
        for sid in _state.adjacent_ids:
            if sid in grid.sectors:
                sector = grid.sectors[sid]
                if sector.visibility == SectorVisibility.UNKNOWN:
                    grid.set_visibility(sid, SectorVisibility.SCANNED)
                    changed = True

    return changed


def _finalize_scan(world: "World") -> bool:
    """Apply final visibility updates on scan completion.

    Returns True if any state changed.
    """
    from server.models.sector import SectorVisibility

    if world.sector_grid is None or _state is None:
        return False

    grid = world.sector_grid
    changed = False

    if _state.scale == "sector":
        sid = _state.sector_id
        if sid in grid.sectors:
            sector = grid.sectors[sid]
            if sector.visibility != SectorVisibility.ACTIVE:
                old = sector.visibility
                grid.set_visibility(sid, SectorVisibility.SURVEYED)
                if sector.visibility != old:
                    changed = True

    elif _state.scale == "long_range":
        for sid in _state.adjacent_ids:
            if sid in grid.sectors:
                sector = grid.sectors[sid]
                if sector.visibility == SectorVisibility.UNKNOWN:
                    grid.set_visibility(sid, SectorVisibility.SCANNED)
                    changed = True

    return changed
