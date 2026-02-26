"""
Medical Ship — Hospital Systems (v0.07 §2.7).

Adds medical-ship-specific capabilities:
  - Surgical Theatre: advanced procedures (limb reattachment, ARS cure, neurosurgery)
  - Triage AI: autonomous treatment when medical station uncrewed
  - Search & Rescue Beacon: enemy hesitation effect
  - Doubled medical supplies (200%)

Public API:
    reset(active)
    is_active() -> bool
    is_rescue_beacon_active() -> bool
    is_surgical_theatre_active() -> bool
    is_triage_ai_active() -> bool
    get_beacon_hesitation(faction, difficulty) -> float
    can_perform_surgery(injury) -> bool
    get_surgical_duration(injury) -> float
    build_state() -> dict
    serialise() -> dict
    deserialise(data) -> None
"""
from __future__ import annotations

from server.models.crew_roster import Injury

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Rescue beacon: per-tick hesitation chance (10 Hz → ~2% per second).
BEACON_HESITATION_CHANCE: float = 0.002

# Faction multiplier for beacon hesitation.
BEACON_HESITATION_FACTIONS: dict[str, float] = {
    "rebel": 1.0,
    "civilian": 1.5,
    "imperial": 0.5,
    "alien": 0.3,
}

# Surgical theatre durations (seconds).
SURGICAL_THEATRE_DURATION_LIMB: float = 60.0
SURGICAL_THEATRE_DURATION_RADIATION: float = 90.0
SURGICAL_THEATRE_DURATION_NEURO: float = 75.0

# Supply cost per surgical procedure (% of max).
SURGICAL_THEATRE_SUPPLY_COST: float = 15.0

# Medical ship doubled supplies.
MEDICAL_SHIP_SUPPLY_MAX: float = 200.0

# Body regions eligible for limb reattachment.
_LIMB_REGIONS: set[str] = {"left_arm", "right_arm", "left_leg", "right_leg"}

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_medical_ship_active: bool = False
_rescue_beacon_active: bool = False
_surgical_theatre_active: bool = False
_triage_ai_active: bool = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset(active: bool = False) -> None:
    """Reset all medical ship state. All features enabled when active."""
    global _medical_ship_active, _rescue_beacon_active
    global _surgical_theatre_active, _triage_ai_active
    _medical_ship_active = active
    _rescue_beacon_active = active
    _surgical_theatre_active = active
    _triage_ai_active = active


def is_active() -> bool:
    return _medical_ship_active


def is_rescue_beacon_active() -> bool:
    return _rescue_beacon_active


def is_surgical_theatre_active() -> bool:
    return _surgical_theatre_active


def is_triage_ai_active() -> bool:
    return _triage_ai_active


# ---------------------------------------------------------------------------
# Rescue Beacon
# ---------------------------------------------------------------------------


def get_beacon_hesitation(faction: str, difficulty: object | None = None) -> float:
    """Return per-tick hesitation chance for the given enemy faction.

    Returns 0.0 if beacon is not active.
    """
    if not _rescue_beacon_active:
        return 0.0
    faction_mult = BEACON_HESITATION_FACTIONS.get(faction, 1.0)
    return BEACON_HESITATION_CHANCE * faction_mult


# ---------------------------------------------------------------------------
# Surgical Theatre
# ---------------------------------------------------------------------------


def can_perform_surgery(injury: Injury) -> bool:
    """Check if the injury is eligible for surgical theatre treatment.

    Eligible cases:
      - Severed/injured limbs (body_region in left_arm/right_arm/left_leg/right_leg)
      - Acute radiation syndrome (type == "acute_radiation_syndrome")
      - Critical head injuries (body_region == "head" and severity == "critical")
    """
    if not _surgical_theatre_active:
        return False
    if injury.treated:
        return False
    # Limb injuries
    if injury.body_region in _LIMB_REGIONS:
        return True
    # Acute radiation syndrome
    if injury.type == "acute_radiation_syndrome":
        return True
    # Critical head injury
    if injury.body_region == "head" and injury.severity == "critical":
        return True
    return False


def get_surgical_duration(injury: Injury) -> float:
    """Return the surgical procedure duration for an eligible injury."""
    if injury.body_region in _LIMB_REGIONS:
        return SURGICAL_THEATRE_DURATION_LIMB
    if injury.type == "acute_radiation_syndrome":
        return SURGICAL_THEATRE_DURATION_RADIATION
    if injury.body_region == "head" and injury.severity == "critical":
        return SURGICAL_THEATRE_DURATION_NEURO
    return 60.0  # fallback


# ---------------------------------------------------------------------------
# State / Serialisation
# ---------------------------------------------------------------------------


def build_state() -> dict:
    """Build state dict for broadcast to medical client."""
    if not _medical_ship_active:
        return {}
    return {
        "active": True,
        "rescue_beacon": _rescue_beacon_active,
        "surgical_theatre": _surgical_theatre_active,
        "triage_ai": _triage_ai_active,
    }


def serialise() -> dict:
    return {
        "active": _medical_ship_active,
        "rescue_beacon": _rescue_beacon_active,
        "surgical_theatre": _surgical_theatre_active,
        "triage_ai": _triage_ai_active,
    }


def deserialise(data: dict) -> None:
    global _medical_ship_active, _rescue_beacon_active
    global _surgical_theatre_active, _triage_ai_active
    _medical_ship_active = data.get("active", False)
    _rescue_beacon_active = data.get("rescue_beacon", False)
    _surgical_theatre_active = data.get("surgical_theatre", False)
    _triage_ai_active = data.get("triage_ai", False)
