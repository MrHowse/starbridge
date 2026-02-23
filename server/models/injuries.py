"""
Injury System — Injury catalogue, generation, degradation, and treatment.

v0.06.1 Part 2: Defines all possible injuries by cause, generates injuries
for crew on affected decks, manages degradation timers and severity
progression, and handles death mechanics.

Each injury type has a cause, possible body regions, severity, treatment
type, treatment duration, and description template.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from server.models.crew_roster import (
    CrewMember,
    IndividualCrewRoster,
    Injury,
    SEVERITY_ORDER,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BODY_REGIONS: list[str] = [
    "head", "torso", "left_arm", "right_arm", "left_leg", "right_leg",
]

LIMB_REGIONS: list[str] = [
    "left_arm", "right_arm", "left_leg", "right_leg",
]

# Base chance of injury per crew member on affected deck
BASE_INJURY_CHANCE: float = 0.4

# Degradation timers by severity (seconds until worsening)
DEGRADE_TIMERS: dict[str, float] = {
    "minor":    300.0,   # 5 min → moderate
    "moderate": 180.0,   # 3 min → serious
    "serious":  120.0,   # 2 min → critical
}

# Death timer for critical injuries (seconds until death)
CRITICAL_DEATH_TIMER: float = 240.0  # 4 min

# Severity progression order
SEVERITY_PROGRESSION: dict[str, str] = {
    "minor":    "moderate",
    "moderate": "serious",
    "serious":  "critical",
}

# Treatment supply costs (percentage of medical supply)
TREATMENT_SUPPLY_COSTS: dict[str, float] = {
    "first_aid":      2.0,
    "stabilise":      3.0,
    "surgery":        8.0,
    "intensive_care": 10.0,
    "quarantine":     5.0,
}

# Contagion spread interval and chance
CONTAGION_SPREAD_INTERVAL: float = 60.0
CONTAGION_SPREAD_CHANCE: float = 0.3

# Radiation delayed onset intervals (seconds between auto-degradation)
RADIATION_DEGRADE_INTERVALS: dict[str, float] = {
    "minor":    60.0,
    "moderate": 60.0,
    "serious":  60.0,
}


# ---------------------------------------------------------------------------
# Injury Definition Templates
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InjuryTemplate:
    """Template for generating a specific injury type."""

    type: str
    body_region: str    # Specific region or "random_limb", "random", "whole_body"
    severity: str
    treatment_type: str
    treatment_duration: float
    description: str    # Template — [region] replaced at generation


# Injury templates by cause
INJURY_TEMPLATES: dict[str, list[InjuryTemplate]] = {
    "hull_breach": [
        InjuryTemplate("decompression_syndrome", "torso", "critical", "surgery", 45.0,
                        "Rapid decompression — loss of consciousness, tissue damage"),
        InjuryTemplate("barotrauma", "torso", "serious", "intensive_care", 40.0,
                        "Pressure differential injury to lungs"),
        InjuryTemplate("impact_fracture", "random_limb", "serious", "surgery", 35.0,
                        "Bone fracture from debris impact"),
        InjuryTemplate("lacerations", "random", "moderate", "first_aid", 15.0,
                        "Multiple cuts from flying debris"),
        InjuryTemplate("hypothermia", "torso", "moderate", "stabilise", 20.0,
                        "Core temperature drop from vacuum exposure"),
        InjuryTemplate("concussion", "head", "moderate", "stabilise", 15.0,
                        "Head impact during decompression event"),
    ],
    "explosion": [
        InjuryTemplate("severe_burns", "random", "critical", "intensive_care", 50.0,
                        "Third-degree burns covering [region]"),
        InjuryTemplate("shrapnel_wound", "random", "serious", "surgery", 35.0,
                        "Embedded shrapnel fragments in [region]"),
        InjuryTemplate("blast_concussion", "head", "serious", "stabilise", 25.0,
                        "Traumatic brain injury from blast wave"),
        InjuryTemplate("internal_bleeding", "torso", "critical", "surgery", 45.0,
                        "Blunt force trauma causing internal haemorrhage"),
        InjuryTemplate("ruptured_eardrum", "head", "moderate", "first_aid", 10.0,
                        "Tympanic membrane rupture from overpressure"),
        InjuryTemplate("flash_burns", "random", "moderate", "first_aid", 15.0,
                        "Superficial burns from flash heat"),
    ],
    "fire": [
        InjuryTemplate("severe_burns", "random", "critical", "intensive_care", 50.0,
                        "Third-degree burns from sustained fire exposure"),
        InjuryTemplate("moderate_burns", "random", "serious", "surgery", 30.0,
                        "Second-degree burns to [region]"),
        InjuryTemplate("smoke_inhalation", "torso", "serious", "stabilise", 25.0,
                        "Toxic smoke damage to airways"),
        InjuryTemplate("minor_burns", "random", "moderate", "first_aid", 15.0,
                        "First-degree burns to [region]"),
        InjuryTemplate("heat_exhaustion", "torso", "minor", "first_aid", 10.0,
                        "Overheating and dehydration from fire proximity"),
    ],
    "boarding": [
        InjuryTemplate("ballistic_wound_critical", "random", "critical", "surgery", 45.0,
                        "Projectile wound to [region] — severe tissue damage"),
        InjuryTemplate("ballistic_wound_serious", "random", "serious", "surgery", 35.0,
                        "Projectile wound to [region] — controlled bleeding"),
        InjuryTemplate("blunt_trauma", "random", "serious", "stabilise", 25.0,
                        "Blunt force injury to [region]"),
        InjuryTemplate("blade_wound", "random", "serious", "surgery", 30.0,
                        "Deep laceration to [region] from edged weapon"),
        InjuryTemplate("combat_concussion", "head", "moderate", "stabilise", 15.0,
                        "Head impact during close combat"),
        InjuryTemplate("bruising", "random", "minor", "first_aid", 10.0,
                        "Multiple contusions from physical combat"),
    ],
    "radiation": [
        InjuryTemplate("acute_radiation_syndrome", "whole_body", "minor", "intensive_care", 60.0,
                        "High-dose radiation exposure — nausea, immune suppression"),
        InjuryTemplate("radiation_burns", "random", "moderate", "stabilise", 20.0,
                        "Localised radiation burn to [region]"),
        InjuryTemplate("radiation_sickness", "torso", "moderate", "stabilise", 20.0,
                        "Nausea, fatigue from moderate radiation exposure"),
    ],
    "contagion": [
        InjuryTemplate("infection_stage_1", "torso", "moderate", "quarantine", 50.0,
                        "Pathogen detected — early stage infection"),
        InjuryTemplate("infection_stage_2", "torso", "serious", "quarantine", 70.0,
                        "Advanced infection — organ involvement"),
        InjuryTemplate("infection_stage_3", "torso", "critical", "quarantine", 90.0,
                        "Systemic infection — multi-organ compromise"),
    ],
    "system_malfunction": [
        InjuryTemplate("electrical_burn", "random_limb", "moderate", "first_aid", 15.0,
                        "Electrical discharge burn to [region]"),
        InjuryTemplate("crush_injury", "random_limb", "serious", "surgery", 35.0,
                        "Limb caught in failed mechanism"),
        InjuryTemplate("electrical_shock", "torso", "serious", "stabilise", 25.0,
                        "Cardiac involvement from electrical shock"),
    ],
}


# ---------------------------------------------------------------------------
# Injury Generation
# ---------------------------------------------------------------------------


def _resolve_body_region(region_spec: str, rng: random.Random) -> str:
    """Resolve a body region specification to a concrete region."""
    if region_spec == "random":
        return rng.choice(BODY_REGIONS)
    elif region_spec == "random_limb":
        return rng.choice(LIMB_REGIONS)
    elif region_spec == "whole_body":
        return "whole_body"
    else:
        return region_spec


def _resolve_description(template_desc: str, body_region: str) -> str:
    """Replace [region] placeholder with actual body region."""
    region_display = body_region.replace("_", " ")
    return template_desc.replace("[region]", region_display)


def generate_injuries(
    cause: str,
    deck: int,
    roster: IndividualCrewRoster,
    severity_scale: float = 1.0,
    rng: random.Random | None = None,
    tick: int = 0,
    difficulty: object | None = None,
) -> list[tuple[str, Injury]]:
    """Generate injuries for crew on the affected deck.

    Returns list of (crew_member_id, Injury) tuples.

    Not everyone gets hurt. Roll for each crew member on the deck:
    - Base chance: difficulty.injury_chance * severity_scale
    - Roll for specific injury from the cause's injury pool
    - Roll for body region where "random" is specified
    - Assign severity, description, timers (scaled by difficulty)

    Args:
        cause: Injury cause type (key into INJURY_TEMPLATES).
        deck: Physical deck number (1-5).
        roster: The crew roster to generate injuries for.
        severity_scale: Multiplier for injury chance (difficulty scaling).
        rng: Optional random instance for deterministic generation.
        tick: Current game tick for injury timestamp.
        difficulty: DifficultyPreset for scaling (optional).
    """
    if rng is None:
        rng = random.Random()

    templates = INJURY_TEMPLATES.get(cause, [])
    if not templates:
        return []

    crew_on_deck = roster.get_crew_on_deck(deck)
    if not crew_on_deck:
        return []

    # Difficulty scaling
    base_chance = getattr(difficulty, "injury_chance", BASE_INJURY_CHANCE) if difficulty else BASE_INJURY_CHANCE
    severity_bias = getattr(difficulty, "injury_severity_bias", 0.5) if difficulty else 0.5
    degrade_mult = getattr(difficulty, "degradation_timer_multiplier", 1.0) if difficulty else 1.0
    death_mult = getattr(difficulty, "death_timer_multiplier", 1.0) if difficulty else 1.0

    results: list[tuple[str, Injury]] = []
    injury_chance = min(base_chance * severity_scale, 1.0)

    # Sort templates by severity for bias weighting
    severity_rank = {"minor": 0, "moderate": 1, "serious": 2, "critical": 3}

    for member in crew_on_deck:
        if member.status == "dead":
            continue

        if rng.random() > injury_chance:
            continue

        # Number of injuries: 1-2
        num_injuries = 1 if rng.random() < 0.7 else 2

        for _ in range(num_injuries):
            # Severity bias: higher bias weights toward more severe templates.
            if severity_bias != 0.5 and len(templates) > 1:
                weights = []
                for t in templates:
                    rank = severity_rank.get(t.severity, 1)
                    w = 1.0 + (rank * severity_bias * 2.0)
                    weights.append(w)
                total = sum(weights)
                r = rng.random() * total
                cumulative = 0.0
                template = templates[0]
                for i, w in enumerate(weights):
                    cumulative += w
                    if r <= cumulative:
                        template = templates[i]
                        break
            else:
                template = rng.choice(templates)
            body_region = _resolve_body_region(template.body_region, rng)
            description = _resolve_description(template.description, body_region)

            severity = template.severity
            degrade = DEGRADE_TIMERS.get(severity, 0.0) * degrade_mult
            death = CRITICAL_DEATH_TIMER * death_mult if severity == "critical" else None

            injury = Injury(
                id=roster.next_injury_id(),
                type=template.type,
                body_region=body_region,
                severity=severity,
                description=description,
                caused_by=cause,
                tick_received=tick,
                degrade_timer=degrade,
                death_timer=death,
                treatment_type=template.treatment_type,
                treatment_duration=template.treatment_duration,
            )
            results.append((member.id, injury))

    return results


# ---------------------------------------------------------------------------
# Injury Degradation
# ---------------------------------------------------------------------------


def upgrade_severity(injury: Injury) -> bool:
    """Upgrade injury severity by one level.

    Returns True if the severity was upgraded, False if already at critical.
    Resets the degrade timer for the new severity level.
    """
    next_severity = SEVERITY_PROGRESSION.get(injury.severity)
    if next_severity is None:
        return False  # Already critical

    injury.severity = next_severity
    injury.degrade_timer = DEGRADE_TIMERS.get(next_severity, 0.0)

    # If now critical, set death timer
    if next_severity == "critical":
        injury.death_timer = CRITICAL_DEATH_TIMER

    return True


def stabilise_injury(injury: Injury) -> None:
    """Reset the degrade timer for this injury (buys time, doesn't fix it).

    If the injury is critical, also resets the death timer.
    """
    degrade = DEGRADE_TIMERS.get(injury.severity)
    if degrade is not None:
        injury.degrade_timer = degrade
    if injury.severity == "critical" and injury.death_timer is not None:
        injury.death_timer = CRITICAL_DEATH_TIMER


def complete_treatment(injury: Injury) -> None:
    """Mark an injury as fully treated."""
    injury.treated = True
    injury.treating = False


def is_radiation_injury(injury: Injury) -> bool:
    """Check if this injury is acute radiation syndrome (delayed onset)."""
    return injury.type == "acute_radiation_syndrome"


def is_contagion_injury(injury: Injury) -> bool:
    """Check if this is a contagion/infection injury."""
    return injury.type.startswith("infection_stage")


def tick_injury_timers(
    member: CrewMember,
    dt: float,
) -> list[dict]:
    """Tick all injury timers for a crew member.

    Returns list of event dicts for any state changes:
    - {"event": "severity_changed", "crew_id": ..., "injury_id": ..., "new_severity": ...}
    - {"event": "crew_death", "crew_id": ..., "injury_id": ...}
    """
    events: list[dict] = []

    for injury in member.injuries:
        if injury.treated or injury.treating:
            continue

        # Degrade timer
        if injury.severity in DEGRADE_TIMERS:
            injury.degrade_timer -= dt
            if injury.degrade_timer <= 0:
                old_severity = injury.severity
                if upgrade_severity(injury):
                    events.append({
                        "event": "severity_changed",
                        "crew_id": member.id,
                        "injury_id": injury.id,
                        "old_severity": old_severity,
                        "new_severity": injury.severity,
                    })

        # Death timer (critical only)
        if injury.severity == "critical" and injury.death_timer is not None:
            injury.death_timer -= dt
            if injury.death_timer <= 0:
                member.status = "dead"
                member.location = "morgue"
                member.treatment_bed = None
                events.append({
                    "event": "crew_death",
                    "crew_id": member.id,
                    "injury_id": injury.id,
                    "crew_name": member.display_name,
                })
                return events  # Dead, no more processing

    # Update member status based on current injuries
    member.update_status()

    return events


def tick_contagion_spread(
    roster: IndividualCrewRoster,
    dt: float,
    spread_timer: float,
    rng: random.Random | None = None,
    difficulty: object | None = None,
) -> tuple[float, list[dict]]:
    """Tick contagion spread logic.

    Infected crew who are NOT quarantined can spread to adjacent crew
    on the same deck.

    Args:
        roster: The crew roster.
        dt: Delta time in seconds.
        spread_timer: Current spread timer (accumulated).
        rng: Random instance for determinism.
        difficulty: DifficultyPreset for scaling contagion_spread_chance.

    Returns:
        (new_spread_timer, list of spread events)
    """
    if rng is None:
        rng = random.Random()

    spread_timer += dt
    if spread_timer < CONTAGION_SPREAD_INTERVAL:
        return spread_timer, []

    spread_timer = 0.0
    events: list[dict] = []
    spread_chance = getattr(difficulty, "contagion_spread_chance", CONTAGION_SPREAD_CHANCE) if difficulty else CONTAGION_SPREAD_CHANCE

    # Find infected crew not in quarantine
    infected = [
        m for m in roster.members.values()
        if m.status != "dead"
        and m.location not in ("quarantine", "morgue")
        and any(is_contagion_injury(i) and not i.treated for i in m.injuries)
    ]

    for inf_member in infected:
        # Find crew on same deck (by location) who are NOT infected
        deck_loc = inf_member.location
        targets = [
            m for m in roster.members.values()
            if m.id != inf_member.id
            and m.location == deck_loc
            and m.status != "dead"
            and not any(is_contagion_injury(i) and not i.treated for i in m.injuries)
        ]

        for target in targets:
            if rng.random() < spread_chance:
                # Spread infection
                injury = Injury(
                    id=roster.next_injury_id(),
                    type="infection_stage_1",
                    body_region="torso",
                    severity="moderate",
                    description="Pathogen detected — early stage infection",
                    caused_by="contagion",
                    degrade_timer=DEGRADE_TIMERS["moderate"],
                    treatment_type="quarantine",
                    treatment_duration=50.0,
                )
                target.injuries.append(injury)
                target.update_status()
                events.append({
                    "event": "contagion_spread",
                    "from_crew_id": inf_member.id,
                    "to_crew_id": target.id,
                    "deck": deck_loc,
                })

    return spread_timer, events
