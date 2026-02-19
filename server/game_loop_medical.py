"""
Medical sub-module for the game loop.

Manages per-deck treatment-in-progress state and applies per-tick healing.
Starting a treatment session costs supplies immediately; healing is gradual.

Treatment auto-cancels when no more crew of the target type remain on the deck.
"""
from __future__ import annotations

from server.models.ship import Ship

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TREATMENT_COST: int = 2           # medical supplies consumed when treatment starts
HEAL_INTERVAL: float = 2.0        # seconds between each individual crew heal
RESUPPLY_AMOUNT: int = 5          # supplies gained per dock resupply
RESUPPLY_MAX: int = 20            # maximum medical supply cap

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_active_treatments: dict[str, str] = {}   # deck_name → "injured" | "critical"
_heal_timers: dict[str, float] = {}       # deck_name → seconds since last heal


def reset() -> None:
    """Clear all treatment state. Called at game start."""
    global _active_treatments, _heal_timers
    _active_treatments = {}
    _heal_timers = {}


# ---------------------------------------------------------------------------
# Treatment management
# ---------------------------------------------------------------------------


def start_treatment(deck_name: str, injury_type: str, ship: Ship) -> bool:
    """Start treatment on a deck.

    Deducts TREATMENT_COST supplies immediately. Returns True if started,
    False if supplies insufficient or deck is unknown.
    """
    if ship.medical_supplies < TREATMENT_COST:
        return False
    if deck_name not in ship.crew.decks:
        return False
    ship.medical_supplies -= TREATMENT_COST
    _active_treatments[deck_name] = injury_type
    _heal_timers[deck_name] = 0.0
    return True


def cancel_treatment(deck_name: str) -> None:
    """Cancel active treatment on a deck (no supply refund)."""
    _active_treatments.pop(deck_name, None)
    _heal_timers.pop(deck_name, None)


def get_active_treatments() -> dict[str, str]:
    """Return a snapshot of the current treatment assignments."""
    return dict(_active_treatments)


# ---------------------------------------------------------------------------
# Per-tick healing
# ---------------------------------------------------------------------------


def tick_treatments(ship: Ship, dt: float) -> list[str]:
    """Apply healing for this tick.

    Each active treatment advances its timer by dt seconds. When the timer
    reaches HEAL_INTERVAL, one crew member is healed and the timer resets.
    Treatments that have no more crew to heal are auto-cancelled.

    Returns list of deck_names where a heal occurred this tick.
    """
    healed: list[str] = []
    to_cancel: list[str] = []

    for deck_name, injury_type in list(_active_treatments.items()):
        _heal_timers[deck_name] = _heal_timers.get(deck_name, 0.0) + dt
        if _heal_timers[deck_name] < HEAL_INTERVAL:
            continue
        _heal_timers[deck_name] = 0.0

        if injury_type == "injured":
            treated = ship.crew.treat_injured(deck_name, 1)
        else:  # "critical"
            treated = ship.crew.treat_critical(deck_name, 1)

        if treated > 0:
            healed.append(deck_name)
        else:
            # No more crew of that type — auto-cancel
            to_cancel.append(deck_name)

    for deck_name in to_cancel:
        cancel_treatment(deck_name)

    return healed
