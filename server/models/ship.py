"""
Ship Model.

Dataclasses representing the player-controlled vessel and its subsystems.
All fields are mutable game state — the physics system updates them each tick.

Ship is the single player vessel for v0.01. In Phase 3, Engineering controls
power allocation; in Phase 4, shield and weapon fields become active.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from server.difficulty import DifficultySettings, get_preset
from server.models.crew import CrewRoster, DECK_SYSTEM_MAP
from server.models.interior import ShipInterior, make_default_interior


# ---------------------------------------------------------------------------
# Subsystem
# ---------------------------------------------------------------------------


@dataclass
class ShipSystem:
    """One of the six ship subsystems, each with independent power and health.

    power  — Engineering's allocation, 0-150 (percentage of base draw).
    health — Structural integrity, 0-100. Reaches 0 when destroyed.
    efficiency — Derived: (power / 100) * (health / 100). Ranges 0.0-1.5.
                 At full power (100%) and full health (100%) efficiency = 1.0.
                 Overclock to 150% gives efficiency 1.5 (Phase 3 risk mechanic).
    """

    name: str
    power: float = 100.0         # 0-150 (%)
    health: float = 100.0        # 0-100 (%)
    _crew_factor: float = 1.0    # Updated each tick by Ship.update_crew_factors()
    _captain_offline: bool = False   # True = Captain has taken this system offline
    _maintenance_buff: float = 0.0   # Additive bonus from janitor maintenance tasks

    @property
    def efficiency(self) -> float:
        """Effective output fraction. 0.0 (offline) to 1.5 (overclocked, healthy).

        Multiplied by _crew_factor (0.0–1.0) so crew casualties reduce system output.
        _crew_factor defaults to 1.0 — existing behaviour is unchanged when crew is full.
        Returns 0.0 when _captain_offline is True (Captain has disabled the system).
        _maintenance_buff is additive — janitor maintenance tasks can boost efficiency.
        """
        if self._captain_offline:
            return 0.0
        base = (self.power / 100.0) * (self.health / 100.0) * self._crew_factor
        return base + self._maintenance_buff


# ---------------------------------------------------------------------------
# Shields
# ---------------------------------------------------------------------------

TOTAL_SHIELD_CAPACITY: float = 200.0  # HP pool distributed across 4 facings


def calculate_shield_distribution(focus_x: float, focus_y: float) -> dict[str, float]:
    """Compute per-facing shield distribution from a 2D focus point.

    focus_x: -1 = full port, +1 = full starboard.
    focus_y: -1 = full aft,  +1 = full fore.
    Returns a dict with 'fore', 'aft', 'port', 'starboard' fractions summing to 1.0.
    """
    base = 0.25
    bias = 0.25
    fore = base + focus_y * bias
    aft  = base - focus_y * bias
    star = base + focus_x * bias
    port = base - focus_x * bias
    total = fore + aft + star + port
    return {
        "fore":      fore / total,
        "aft":       aft  / total,
        "starboard": star / total,
        "port":      port / total,
    }


@dataclass
class Shields:
    """Four-facing shield charge levels (HP, not %). 0 = down, max set by distribution."""

    fore:      float = 50.0   # default = TOTAL_SHIELD_CAPACITY × 0.25 (centre focus)
    aft:       float = 50.0
    port:      float = 50.0
    starboard: float = 50.0


# ---------------------------------------------------------------------------
# Ship
# ---------------------------------------------------------------------------


def _default_systems() -> dict[str, ShipSystem]:
    """Return the nine default ship systems at full power and health."""
    return {
        name: ShipSystem(name)
        for name in ("engines", "beams", "torpedoes", "shields", "sensors", "manoeuvring", "flight_deck", "ecm_suite", "point_defence")
    }


@dataclass
class Ship:
    """Complete mutable state of the player-controlled vessel.

    Movement fields (heading, velocity, throttle, target_heading) are updated
    by the physics system each tick. In Phase 2, only engines and manoeuvring
    systems actively affect physics; the others default to 100% power and wait
    for Engineering (Phase 3) and Weapons (Phase 4).
    """

    name: str = "TSS Endeavour"

    # --- Position (world units, origin = top-left corner of sector) ---
    x: float = 50_000.0   # starts at sector centre
    y: float = 50_000.0

    # --- Movement ---
    heading: float = 0.0         # current actual heading, degrees (0 = north/up, clockwise)
    target_heading: float = 0.0  # desired heading set by Helm (physics turns ship toward it)
    velocity: float = 0.0        # current speed, world units/sec
    throttle: float = 0.0        # desired speed fraction, 0-100 (%)

    # --- Hull ---
    hull: float = 100.0      # current HP; 0 = destroyed
    hull_max: float = 100.0  # maximum HP (set from ship class at game start)

    # --- Docking ---
    docked_at: str | None = None  # station ID while docked, None otherwise

    # --- Shields ---
    shields: Shields = field(default_factory=Shields)
    shield_focus:        dict = field(default_factory=lambda: {"x": 0.0, "y": 0.0})
    shield_distribution: dict = field(default_factory=lambda: {
        "fore": 0.25, "aft": 0.25, "port": 0.25, "starboard": 0.25})

    # --- Subsystems ---
    systems: dict[str, ShipSystem] = field(default_factory=_default_systems)

    # --- Engineering ---
    repair_focus: str | None = None  # System currently receiving repair attention

    # --- Alert level (set by Captain station) ---
    alert_level: str = "green"  # "green" | "yellow" | "red"

    # --- Crew (added v0.02a) ---
    crew: CrewRoster = field(default_factory=CrewRoster)
    medical_supplies: int = 20   # finite treatment resource; replenished by docking

    # --- Ship interior (added v0.02c) ---
    interior: ShipInterior = field(default_factory=make_default_interior)

    # --- Difficulty (set at game start by game_loop.start()) ---
    difficulty: DifficultySettings = field(default_factory=lambda: get_preset("officer"))

    # --- Electronic Warfare (v0.03k) ---
    countermeasure_charges: int = 10       # finite charges; each absorbed hit costs 1
    ew_countermeasure_active: bool = False  # True when EW station has deployed countermeasures

    def update_crew_factors(self, individual_roster: object | None = None) -> None:
        """Propagate crew_factors into the corresponding ship systems.

        Called once per tick (after engineering). When an IndividualCrewRoster is
        provided, uses per-duty-station crew factors with a 10% minimum floor.
        Falls back to the old deck-level CrewRoster otherwise.

        Args:
            individual_roster: IndividualCrewRoster instance (v0.06.1+), or None.
        """
        if individual_roster is not None:
            # v0.06.1+: per-system crew factor from individual crew roster
            for sys_name, sys_obj in self.systems.items():
                factor = individual_roster.crew_factor_for_system(sys_name)
                # 10% minimum floor — basic automation keeps the ship limping
                sys_obj._crew_factor = max(factor, 0.10)
        else:
            # Legacy: deck-level crew factor
            for deck_name, system_names in DECK_SYSTEM_MAP.items():
                deck = self.crew.decks.get(deck_name)
                factor = deck.crew_factor if deck is not None else 1.0
                for sys_name in system_names:
                    sys_obj = self.systems.get(sys_name)
                    if sys_obj is not None:
                        sys_obj._crew_factor = factor
