"""
Medical sub-module for the game loop.

Manages per-deck treatment-in-progress state and applies per-tick healing.
Starting a treatment session costs supplies immediately; healing is gradual.

Treatment auto-cancels when no more crew of the target type remain on the deck.

Disease mechanics (v0.02e):
  start_outbreak(deck, pathogen) — mark a deck as infected.
  tick_disease(interior, dt)     — spread infection each SPREAD_INTERVAL seconds;
                                   blocked by sealed doors between decks.
  get_disease_state()            — current infection map for broadcast.
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

SPREAD_INTERVAL: float = 30.0     # seconds between disease spread checks

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_active_treatments: dict[str, str] = {}   # deck_name → "injured" | "critical"
_heal_timers: dict[str, float] = {}       # deck_name → seconds since last heal

_active_outbreak: dict[str, str] = {}     # deck_name → pathogen name
_spread_timer: float = 0.0


def reset() -> None:
    """Clear all treatment and disease state. Called at game start."""
    global _active_treatments, _heal_timers, _active_outbreak, _spread_timer
    _active_treatments = {}
    _heal_timers = {}
    _active_outbreak = {}
    _spread_timer = 0.0




def serialise() -> dict:
    return {
        "active_treatments": dict(_active_treatments),
        "heal_timers": dict(_heal_timers),
        "active_outbreak": dict(_active_outbreak),
        "spread_timer": _spread_timer,
    }


def deserialise(data: dict) -> None:
    global _spread_timer
    _active_treatments.clear()
    _active_treatments.update(data.get("active_treatments", {}))
    _heal_timers.clear()
    _heal_timers.update(data.get("heal_timers", {}))
    _active_outbreak.clear()
    _active_outbreak.update(data.get("active_outbreak", {}))
    _spread_timer = data.get("spread_timer", 0.0)


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


# ---------------------------------------------------------------------------
# Disease / outbreak mechanics (v0.02e)
# ---------------------------------------------------------------------------


def start_outbreak(deck_name: str, pathogen: str) -> None:
    """Mark a deck as infected with the given pathogen.

    Has no effect if the deck is already infected.
    """
    if deck_name not in _active_outbreak:
        _active_outbreak[deck_name] = pathogen


def tick_disease(interior: object, dt: float) -> list[dict]:
    """Advance the disease spread timer and spread infection if due.

    Infection spreads from an infected deck to an adjacent deck when:
      - The spread timer reaches SPREAD_INTERVAL.
      - At least one room on the infected deck shares an unsealed connection
        with a room on the target deck.

    Returns a list of spread-event dicts::

        {"from_deck": str, "to_deck": str, "pathogen": str}
    """
    global _spread_timer
    if not _active_outbreak:
        return []

    _spread_timer += dt
    if _spread_timer < SPREAD_INTERVAL:
        return []

    _spread_timer = 0.0
    return _try_spread(interior)


def _try_spread(interior: object) -> list[dict]:
    """Attempt to spread infection through unsealed cross-deck connections."""
    events: list[dict] = []
    new_infections: dict[str, str] = {}

    rooms = interior.rooms  # type: ignore[attr-defined]

    for deck, pathogen in list(_active_outbreak.items()):
        infected_rooms = [r for r in rooms.values() if r.deck == deck]
        for room in infected_rooms:
            for conn_id in room.connections:
                conn_room = rooms.get(conn_id)
                if conn_room is None or conn_room.deck == deck:
                    continue
                # Spread blocked if either room has a sealed door
                if room.door_sealed or conn_room.door_sealed:
                    continue
                target_deck = conn_room.deck
                if target_deck not in _active_outbreak and target_deck not in new_infections:
                    new_infections[target_deck] = pathogen
                    events.append({
                        "from_deck": deck,
                        "to_deck":   target_deck,
                        "pathogen":  pathogen,
                    })

    _active_outbreak.update(new_infections)
    return events


def get_disease_state() -> dict:
    """Return a snapshot of the current disease state for broadcast."""
    return {
        "infected_decks":  dict(_active_outbreak),
        "spread_timer":    round(_spread_timer, 2),
        "spread_interval": SPREAD_INTERVAL,
    }
