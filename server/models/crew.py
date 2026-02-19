"""
Crew Model — Deck crew assignments and health states.

DeckCrew tracks the health distribution of crew on one deck.
CrewRoster aggregates all decks and exposes treatment methods.
DECK_SYSTEM_MAP links crew decks to ship systems for efficiency integration.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DECK_SYSTEM_MAP: dict[str, list[str]] = {
    "bridge":      ["manoeuvring"],
    "sensors":     ["sensors"],
    "weapons":     ["beams", "torpedoes"],
    "shields":     ["shields"],
    "engineering": ["engines"],
    "medical":     [],
}

DECK_DEFAULT_CREW: dict[str, int] = {
    "bridge":      5,
    "sensors":     3,
    "weapons":     4,
    "shields":     3,
    "engineering": 6,
    "medical":     4,
}


# ---------------------------------------------------------------------------
# DeckCrew
# ---------------------------------------------------------------------------


@dataclass
class DeckCrew:
    """Health distribution of crew assigned to one deck."""

    deck_name: str
    total: int           # Total crew assigned to this deck
    active: int          # Healthy and working
    injured: int = 0     # Impaired, partial contribution (0.5 effective)
    critical: int = 0    # Incapacitated, zero contribution; will die without treatment
    dead: int = 0        # Permanently lost

    @property
    def crew_factor(self) -> float:
        """Ratio of effective crew to required crew. 1.0 = fully staffed."""
        if self.total == 0:
            return 1.0
        effective = self.active + (self.injured * 0.5)
        return min(effective / self.total, 1.0)


# ---------------------------------------------------------------------------
# CrewRoster
# ---------------------------------------------------------------------------


def _default_decks() -> dict[str, DeckCrew]:
    """Initialise all decks fully staffed with default crew counts."""
    return {
        name: DeckCrew(deck_name=name, total=count, active=count)
        for name, count in DECK_DEFAULT_CREW.items()
    }


@dataclass
class CrewRoster:
    """Full crew roster for the ship, organised by deck."""

    decks: dict[str, DeckCrew] = field(default_factory=_default_decks)

    def apply_casualties(self, deck_name: str, count: int) -> None:
        """Apply crew casualties to a deck: active → injured → critical."""
        deck = self.decks.get(deck_name)
        if deck is None or count <= 0:
            return
        # Move active → injured first
        from_active = min(count, deck.active)
        deck.active -= from_active
        deck.injured += from_active
        count -= from_active
        # Overflow: move injured → critical
        if count > 0:
            from_injured = min(count, deck.injured)
            deck.injured -= from_injured
            deck.critical += from_injured

    def treat_injured(self, deck_name: str, count: int) -> int:
        """Treat injured crew: injured → active. Returns number treated."""
        deck = self.decks.get(deck_name)
        if deck is None:
            return 0
        treated = min(count, deck.injured)
        deck.injured -= treated
        deck.active += treated
        return treated

    def treat_critical(self, deck_name: str, count: int) -> int:
        """Stabilise critical crew: critical → injured. Returns number stabilised."""
        deck = self.decks.get(deck_name)
        if deck is None:
            return 0
        stabilised = min(count, deck.critical)
        deck.critical -= stabilised
        deck.injured += stabilised
        return stabilised

    def get_deck_for_system(self, system_name: str) -> str | None:
        """Return the crew deck name that maps to the given ship system, or None."""
        for deck_name, systems in DECK_SYSTEM_MAP.items():
            if system_name in systems:
                return deck_name
        return None
