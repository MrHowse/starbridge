"""
Training mode sub-module for the game loop.

Activated when a mission has "is_training": true.  Provides:
  - Auto-simulation of non-target roles (helm, engineering) so the student
    can focus on their own station without the game grinding to a halt.
  - Per-objective hint tracking so the game loop can broadcast "training.hint"
    messages when the active objective advances.

Auto-behaviours are intentionally simple — the goal is to keep the ship
alive and moving, not to play optimally.
"""
from __future__ import annotations

from server.models.ship import Ship
from server.utils.math_helpers import bearing_to, distance

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AUTO_HELM_SPEED: float = 0.4          # throttle fraction (0–1)
_AUTO_ENG_MIN_POWER: float = 40.0      # below this we raise a system back up
_AUTO_ENG_BASELINE: float = 80.0       # the baseline power level we restore to
_SECTOR_CX: float = 50_000.0           # sector centre X (standard 100k world)
_SECTOR_CY: float = 50_000.0           # sector centre Y

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_training_active: bool = False
_target_role: str = ""
_obj_hints: dict[int, str] = {}        # objective_index → hint text
_last_hint_idx: int = -1               # last objective index for which a hint was sent
_auto_helm_enabled: bool = False
_auto_engineering_enabled: bool = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset() -> None:
    """Reset training state.  Call at game start (before init_training)."""
    global _training_active, _target_role, _obj_hints, _last_hint_idx
    global _auto_helm_enabled, _auto_engineering_enabled
    _training_active = False
    _target_role = ""
    _obj_hints = {}
    _last_hint_idx = -1
    _auto_helm_enabled = False
    _auto_engineering_enabled = False


def init_training(mission_dict: dict) -> None:
    """Initialise training mode from a mission dict.

    If the mission has ``"is_training": true`` this function enables training
    mode, extracts the target role, parses per-objective hint text, and
    decides which roles to auto-simulate.

    The ``"auto_roles"`` key in the mission dict is an optional list of role
    names to auto-simulate (default: ["helm", "engineering"]).  Set it to []
    to disable all auto-simulation.
    """
    global _training_active, _target_role, _obj_hints
    global _auto_helm_enabled, _auto_engineering_enabled

    if not mission_dict.get("is_training", False):
        return

    _training_active = True
    _target_role = mission_dict.get("target_role", "")

    # Parse per-objective hints (stored in objective["hint"]).
    _obj_hints = {}
    for i, obj in enumerate(mission_dict.get("objectives", [])):
        if hint := obj.get("hint", ""):
            _obj_hints[i] = hint

    # Determine which roles to auto-simulate.
    auto_roles: list[str] = mission_dict.get("auto_roles", ["helm", "engineering"])
    _auto_helm_enabled = "helm" in auto_roles and _target_role != "helm"
    _auto_engineering_enabled = (
        "engineering" in auto_roles and _target_role != "engineering"
    )


def is_training_active() -> bool:
    """Return True if a training mission is currently running."""
    return _training_active


def get_target_role() -> str:
    """Return the station role being trained."""
    return _target_role


def get_hint_for_idx(idx: int) -> str | None:
    """Return the hint text for the objective at *idx*, or None if no hint exists."""
    return _obj_hints.get(idx)


def get_last_hint_idx() -> int:
    """Return the last objective index for which a hint was already broadcast."""
    return _last_hint_idx


def set_last_hint_idx(idx: int) -> None:
    """Update the last-broadcast hint index."""
    global _last_hint_idx
    _last_hint_idx = idx


# ---------------------------------------------------------------------------
# Auto-simulation helpers (called from game_loop.py each tick)
# ---------------------------------------------------------------------------


def auto_helm_tick(ship: Ship, dt: float) -> None:
    """Gently steer the ship toward the sector centre at a safe speed.

    Only active when training mode is on, the player is not training helm,
    and the ship is not already at the sector centre.
    """
    if not _auto_helm_enabled:
        return

    dist_to_centre = distance(ship.x, ship.y, _SECTOR_CX, _SECTOR_CY)
    if dist_to_centre > 3_000.0:
        ship.target_heading = bearing_to(ship.x, ship.y, _SECTOR_CX, _SECTOR_CY)
        # Gradually ramp up to the auto speed.
        if ship.throttle < _AUTO_HELM_SPEED:
            ship.throttle = min(ship.throttle + 0.3 * dt, _AUTO_HELM_SPEED)
    else:
        # Near the centre — coast to a stop.
        ship.throttle = max(ship.throttle - 0.5 * dt, 0.0)


def auto_engineering_tick(ship: Ship, dt: float) -> None:  # noqa: ARG001
    """Restore any system that has lost power to a safe baseline.

    We only raise power levels that have dropped below the minimum threshold
    (e.g. due to damage or a fresh game start with zero power).  We never
    lower power — that would conflict with the player's engineering choices on
    other stations.
    """
    if not _auto_engineering_enabled:
        return

    for _name, sys_obj in ship.systems.items():
        if sys_obj.power < _AUTO_ENG_MIN_POWER:
            sys_obj.power = _AUTO_ENG_BASELINE


def serialise() -> dict:
    return {
        "training_active": _training_active,
        "target_role": _target_role,
        "obj_hints": dict(_obj_hints),
        "last_hint_idx": _last_hint_idx,
        "auto_helm_enabled": _auto_helm_enabled,
        "auto_engineering_enabled": _auto_engineering_enabled,
    }


def deserialise(data: dict) -> None:
    global _training_active, _target_role, _last_hint_idx
    global _auto_helm_enabled, _auto_engineering_enabled
    _training_active          = data.get("training_active", False)
    _target_role              = data.get("target_role", "")
    _last_hint_idx            = data.get("last_hint_idx", -1)
    _auto_helm_enabled        = data.get("auto_helm_enabled", False)
    _auto_engineering_enabled = data.get("auto_engineering_enabled", False)
    _obj_hints.clear()
    _obj_hints.update({int(k): v for k, v in data.get("obj_hints", {}).items()})
