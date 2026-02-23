"""
Crew Roster — Individual named crew members with injuries, ranks, and duty stations.

v0.06.1: Replaces the old deck-level crew tracking (server/models/crew.py)
with individual crew member tracking. Each crew member has a name, rank,
deck assignment, duty station, status, injuries, and location.

The old CrewRoster in crew.py is kept for backward compatibility during
migration. This module provides the new individual-level roster.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from server.models.crew_names import FIRST_NAMES, SURNAMES

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RANKS: list[dict] = [
    {"title": "Commander",           "level": 7},
    {"title": "Lt. Commander",       "level": 6},
    {"title": "Lieutenant",          "level": 5},
    {"title": "Sub-Lieutenant",      "level": 4},
    {"title": "Chief Petty Officer", "level": 3},
    {"title": "Petty Officer",       "level": 2},
    {"title": "Crewman",             "level": 1},
]

# Rank distribution fractions for crew generation.
# Applied to total crew count; remainder fills Crewman.
RANK_FRACTIONS: list[tuple[int, float]] = [
    (7, 0.04),   # Commander: ~4% (0-1 per ship)
    (6, 0.08),   # Lt. Commander: ~8% (1-2)
    (5, 0.12),   # Lieutenant: ~12% (2-4)
    (4, 0.12),   # Sub-Lieutenant: ~12% (2-4)
    (3, 0.16),   # Chief Petty Officer: ~16% (3-5)
    (2, 0.20),   # Petty Officer: ~20% (4-8)
    # Crewman gets the remainder
]

# Duty stations mapped to physical decks.
# Deck 1 (bridge): manoeuvring
# Deck 2 (sensors): sensors
# Deck 3 (weapons+shields): beams, torpedoes, shields
# Deck 4 (medical): medical_bay
# Deck 5 (engineering): engines
DECK_DUTY_STATIONS: dict[int, list[str]] = {
    1: ["manoeuvring"],
    2: ["sensors"],
    3: ["beams", "torpedoes", "shields"],
    4: ["medical_bay"],
    5: ["engines"],
}

# Map duty stations to ship system names for crew_factor calculation.
DUTY_STATION_TO_SYSTEM: dict[str, list[str]] = {
    "manoeuvring":  ["manoeuvring"],
    "sensors":      ["sensors"],
    "beams":        ["beams"],
    "torpedoes":    ["torpedoes"],
    "shields":      ["shields"],
    "engines":      ["engines"],
    "medical_bay":  [],  # Medical bay doesn't map to a ship system
}

# Map from old crew deck names to new duty stations.
DECK_NAME_TO_DUTY_STATIONS: dict[str, list[str]] = {
    "bridge":      ["manoeuvring"],
    "sensors":     ["sensors"],
    "weapons":     ["beams", "torpedoes"],
    "shields":     ["shields"],
    "engineering": ["engines"],
    "medical":     ["medical_bay"],
}

# Map from ship system names to expected duty stations.
SYSTEM_TO_DUTY_STATION: dict[str, str] = {
    "engines":       "engines",
    "beams":         "beams",
    "torpedoes":     "torpedoes",
    "shields":       "shields",
    "sensors":       "sensors",
    "manoeuvring":   "manoeuvring",
    "flight_deck":   "manoeuvring",   # bridge crew handles flight ops
    "ecm_suite":     "sensors",       # sensor crew handles EW
    "point_defence": "shields",       # shield crew handles PD
}


# ---------------------------------------------------------------------------
# Injury dataclass (forward declaration for CrewMember)
# ---------------------------------------------------------------------------

@dataclass
class Injury:
    """A single injury on a crew member."""

    id: str
    type: str
    body_region: str         # "head", "torso", "left_arm", "right_arm",
                             # "left_leg", "right_leg", "whole_body"
    severity: str            # "critical", "serious", "moderate", "minor"
    description: str
    caused_by: str           # "hull_breach", "explosion", "fire", etc.
    tick_received: int = 0
    degrade_timer: float = 0.0
    death_timer: float | None = None
    treatment_type: str = "first_aid"
    treatment_duration: float = 10.0
    treated: bool = False
    treating: bool = False

    def to_dict(self) -> dict:
        """Serialise injury to dict for broadcast/save."""
        return {
            "id": self.id,
            "type": self.type,
            "body_region": self.body_region,
            "severity": self.severity,
            "description": self.description,
            "caused_by": self.caused_by,
            "tick_received": self.tick_received,
            "degrade_timer": round(self.degrade_timer, 2),
            "death_timer": round(self.death_timer, 2) if self.death_timer is not None else None,
            "treatment_type": self.treatment_type,
            "treatment_duration": self.treatment_duration,
            "treated": self.treated,
            "treating": self.treating,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Injury:
        """Deserialise injury from dict."""
        return cls(
            id=data["id"],
            type=data["type"],
            body_region=data["body_region"],
            severity=data["severity"],
            description=data["description"],
            caused_by=data["caused_by"],
            tick_received=data.get("tick_received", 0),
            degrade_timer=data.get("degrade_timer", 0.0),
            death_timer=data.get("death_timer"),
            treatment_type=data.get("treatment_type", "first_aid"),
            treatment_duration=data.get("treatment_duration", 10.0),
            treated=data.get("treated", False),
            treating=data.get("treating", False),
        )


# Severity ordering for sorting
SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "serious": 1,
    "moderate": 2,
    "minor": 3,
}


# ---------------------------------------------------------------------------
# CrewMember dataclass
# ---------------------------------------------------------------------------

@dataclass
class CrewMember:
    """A single crew member aboard the ship."""

    id: str
    first_name: str
    surname: str
    rank: str
    rank_level: int
    deck: int
    duty_station: str
    status: str = "active"           # "active", "injured", "critical", "dead"
    injuries: list[Injury] = field(default_factory=list)
    location: str = "deck_1"         # "deck_N", "medical_bay", "quarantine", "morgue"
    treatment_bed: int | None = None

    @property
    def display_name(self) -> str:
        """Short display name: 'Rank Surname' (e.g. 'Lt. Chen')."""
        # Abbreviate ranks for display
        abbrev = {
            "Commander": "Cmdr.",
            "Lt. Commander": "Lt. Cmdr.",
            "Lieutenant": "Lt.",
            "Sub-Lieutenant": "Sub-Lt.",
            "Chief Petty Officer": "CPO",
            "Petty Officer": "PO",
            "Crewman": "Crw.",
        }
        return f"{abbrev.get(self.rank, self.rank)} {self.surname}"

    @property
    def full_name(self) -> str:
        """Full name: 'First Surname'."""
        return f"{self.first_name} {self.surname}"

    @property
    def worst_severity(self) -> str | None:
        """Return the worst severity among all untreated injuries, or None."""
        untreated = [i for i in self.injuries if not i.treated]
        if not untreated:
            return None
        return min(untreated, key=lambda i: SEVERITY_ORDER.get(i.severity, 99)).severity

    def update_status(self) -> None:
        """Update status based on current injuries."""
        if self.status == "dead":
            return
        untreated = [i for i in self.injuries if not i.treated]
        if not untreated:
            self.status = "active"
            return
        worst = self.worst_severity
        if worst == "critical":
            self.status = "critical"
        elif worst in ("serious", "moderate"):
            self.status = "injured"
        else:
            self.status = "injured"  # minor injuries still count as injured

    def to_dict(self) -> dict:
        """Serialise crew member for broadcast/save."""
        return {
            "id": self.id,
            "first_name": self.first_name,
            "surname": self.surname,
            "rank": self.rank,
            "rank_level": self.rank_level,
            "deck": self.deck,
            "duty_station": self.duty_station,
            "status": self.status,
            "injuries": [i.to_dict() for i in self.injuries],
            "location": self.location,
            "treatment_bed": self.treatment_bed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CrewMember:
        """Deserialise crew member from dict."""
        injuries = [Injury.from_dict(i) for i in data.get("injuries", [])]
        return cls(
            id=data["id"],
            first_name=data["first_name"],
            surname=data["surname"],
            rank=data["rank"],
            rank_level=data["rank_level"],
            deck=data["deck"],
            duty_station=data["duty_station"],
            status=data.get("status", "active"),
            injuries=injuries,
            location=data.get("location", f"deck_{data['deck']}"),
            treatment_bed=data.get("treatment_bed"),
        )


# ---------------------------------------------------------------------------
# CrewRoster
# ---------------------------------------------------------------------------


def _rank_title(level: int) -> str:
    """Get rank title from rank level."""
    for r in RANKS:
        if r["level"] == level:
            return r["title"]
    return "Crewman"


def _distribute_ranks(crew_count: int) -> list[tuple[str, int]]:
    """Distribute ranks for a crew of given size.

    Returns list of (rank_title, rank_level) for each crew member.
    Higher ranks are rarer. Commander only appears on ships with 8+ crew.
    """
    ranks_out: list[tuple[str, int]] = []

    for level, fraction in RANK_FRACTIONS:
        # Skip Commander on small crews
        if level == 7 and crew_count < 8:
            continue
        count = max(0, round(crew_count * fraction))
        # Cap Commander at 1
        if level == 7:
            count = min(count, 1)
        for _ in range(count):
            ranks_out.append((_rank_title(level), level))

    # Fill remainder with Crewman
    while len(ranks_out) < crew_count:
        ranks_out.append(("Crewman", 1))

    # Trim if we overshot
    ranks_out = ranks_out[:crew_count]

    # Sort by level descending (highest rank first)
    ranks_out.sort(key=lambda r: -r[1])
    return ranks_out


def _distribute_decks(crew_count: int, num_decks: int = 5) -> list[int]:
    """Distribute crew roughly evenly across decks.

    Returns list of deck assignments (1-based).
    """
    decks: list[int] = []
    per_deck = crew_count // num_decks
    remainder = crew_count % num_decks

    for deck_num in range(1, num_decks + 1):
        count = per_deck + (1 if deck_num <= remainder else 0)
        decks.extend([deck_num] * count)

    return decks


@dataclass
class IndividualCrewRoster:
    """Full crew roster with individual named crew members.

    Replaces the old deck-level CrewRoster for v0.06.1.
    """

    members: dict[str, CrewMember] = field(default_factory=dict)
    _next_injury_id: int = 0

    def next_injury_id(self) -> str:
        """Generate the next unique injury ID."""
        self._next_injury_id += 1
        return f"inj_{self._next_injury_id:04d}"

    @classmethod
    def generate(cls, crew_count: int, ship_class: str = "frigate",
                 rng: random.Random | None = None) -> IndividualCrewRoster:
        """Generate a full crew roster for the given ship class.

        Args:
            crew_count: Total number of crew members to generate.
            ship_class: Ship class name (for future specialisation).
            rng: Optional random.Random instance for deterministic generation.
        """
        if rng is None:
            rng = random.Random()

        roster = cls()

        # Pick unique name pairs
        firsts = list(FIRST_NAMES)
        surs = list(SURNAMES)
        rng.shuffle(firsts)
        rng.shuffle(surs)

        # Generate rank assignments
        ranks = _distribute_ranks(crew_count)

        # Generate deck assignments
        decks = _distribute_decks(crew_count)
        rng.shuffle(decks)

        # Build crew members
        used_full_names: set[str] = set()
        for i in range(crew_count):
            crew_id = f"crew_{i + 1:03d}"
            first = firsts[i % len(firsts)]
            sur = surs[i % len(surs)]

            # Ensure unique full names
            full = f"{first} {sur}"
            attempt = 0
            while full in used_full_names and attempt < 20:
                # Swap surname with another unused one
                alt_idx = (i + attempt + crew_count) % len(surs)
                sur = surs[alt_idx]
                full = f"{first} {sur}"
                attempt += 1
            used_full_names.add(full)

            rank_title, rank_level = ranks[i]
            deck = decks[i]

            # Assign duty station based on deck
            stations = DECK_DUTY_STATIONS.get(deck, ["manoeuvring"])
            duty_station = rng.choice(stations)

            member = CrewMember(
                id=crew_id,
                first_name=first,
                surname=sur,
                rank=rank_title,
                rank_level=rank_level,
                deck=deck,
                duty_station=duty_station,
                location=f"deck_{deck}",
            )
            roster.members[crew_id] = member

        return roster

    # ---- Query methods ----

    def get_by_deck(self, deck: int) -> list[CrewMember]:
        """Get all crew members assigned to a physical deck."""
        return [m for m in self.members.values() if m.deck == deck]

    def get_by_status(self, status: str) -> list[CrewMember]:
        """Get all crew members with the given status."""
        return [m for m in self.members.values() if m.status == status]

    def get_by_duty_station(self, station: str) -> list[CrewMember]:
        """Get all crew members assigned to a duty station."""
        return [m for m in self.members.values() if m.duty_station == station]

    def get_injured(self) -> list[CrewMember]:
        """All crew with at least one untreated injury, sorted by worst severity."""
        injured = [
            m for m in self.members.values()
            if m.status in ("injured", "critical")
            and any(not i.treated for i in m.injuries)
        ]
        injured.sort(
            key=lambda m: SEVERITY_ORDER.get(m.worst_severity or "minor", 99)
        )
        return injured

    def get_active_count(self) -> int:
        """Count of crew members with 'active' status."""
        return sum(1 for m in self.members.values() if m.status == "active")

    def get_dead_count(self) -> int:
        """Count of crew members with 'dead' status."""
        return sum(1 for m in self.members.values() if m.status == "dead")

    def crew_factor_for_duty_station(self, duty_station: str) -> float:
        """Calculate crew factor (0.0-1.0) for a duty station.

        Based on active crew assigned to the station. Injured crew at their
        station count at 50% effectiveness. Crew in medical bay or dead don't
        count.

        Returns 1.0 if no crew are assigned to the station.
        """
        assigned = self.get_by_duty_station(duty_station)
        if not assigned:
            return 1.0

        total = len(assigned)
        effective = 0.0
        for m in assigned:
            if m.status == "dead":
                continue
            if m.location in ("medical_bay", "quarantine", "morgue"):
                continue  # In medical bay, don't count
            if m.status == "active":
                effective += 1.0
            elif m.status in ("injured", "critical"):
                # Minor injuries: 50% effectiveness
                worst = m.worst_severity
                if worst == "minor":
                    effective += 0.5
                elif worst == "moderate":
                    effective += 0.5
                # Serious/critical at station still count at 50%
                else:
                    effective += 0.5

        return min(effective / total, 1.0)

    def crew_factor_for_system(self, system: str) -> float:
        """Calculate crew factor (0.0-1.0) for a ship system.

        Looks up the duty station for the system and delegates to
        crew_factor_for_duty_station(). Returns 1.0 if no mapping exists.
        """
        duty_station = SYSTEM_TO_DUTY_STATION.get(system)
        if duty_station is None:
            return 1.0
        return self.crew_factor_for_duty_station(duty_station)

    def get_crew_on_deck(self, deck: int, exclude_medical: bool = True) -> list[CrewMember]:
        """Get crew physically on a deck (by location, not assignment).

        If exclude_medical, skip crew in medical_bay/quarantine/morgue.
        """
        results = []
        deck_loc = f"deck_{deck}"
        for m in self.members.values():
            if m.status == "dead" and m.location == "morgue":
                continue
            if exclude_medical and m.location in ("medical_bay", "quarantine"):
                continue
            if m.location == deck_loc:
                results.append(m)
        return results

    # ---- Serialisation ----

    def serialise(self) -> dict:
        """Serialise the full roster for save/resume."""
        return {
            "members": {mid: m.to_dict() for mid, m in self.members.items()},
            "next_injury_id": self._next_injury_id,
        }

    @classmethod
    def deserialise(cls, data: dict) -> IndividualCrewRoster:
        """Deserialise a roster from saved data."""
        roster = cls()
        roster._next_injury_id = data.get("next_injury_id", 0)
        for mid, mdata in data.get("members", {}).items():
            roster.members[mid] = CrewMember.from_dict(mdata)
        return roster
