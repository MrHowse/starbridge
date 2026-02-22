"""
Medical sub-module v2 — Individual crew injury management.

v0.06.1 Part 3: Replaces the old deck-level treatment system with
individual crew member tracking, bed management, treatment queue,
quarantine, and per-injury treatment.

Maintains the same public interface as game_loop_medical.py for
drop-in replacement in game_loop.py.

Public API:
    reset()
    tick(roster, dt) -> list[dict]           # NEW: tick all medical logic
    tick_treatments(ship, dt) -> list[str]   # COMPAT: old interface adapter
    tick_disease(interior, dt) -> list[dict] # COMPAT: old interface adapter
    start_treatment(deck, injury_type, ship) -> bool  # COMPAT
    cancel_treatment(deck) -> None           # COMPAT
    start_outbreak(deck, pathogen) -> None   # COMPAT
    get_active_treatments() -> dict          # COMPAT
    get_disease_state() -> dict              # COMPAT
    serialise() -> dict
    deserialise(data) -> None

New API (used by updated game_loop.py):
    init_roster(roster)
    get_roster() -> IndividualCrewRoster | None
    admit_patient(crew_id) -> dict
    start_crew_treatment(crew_id, injury_id, treatment_type) -> dict
    stabilise_crew(crew_id, injury_id) -> dict
    quarantine_crew(crew_id) -> dict
    discharge_patient(crew_id) -> dict
    set_triage_priority(crew_ids) -> None
    get_medical_state() -> dict
    get_bed_count() -> int
    set_bed_count(n) -> None
"""
from __future__ import annotations

import random

from server.models.crew_roster import (
    CrewMember,
    IndividualCrewRoster,
    Injury,
)
from server.models.injuries import (
    CONTAGION_SPREAD_INTERVAL,
    CRITICAL_DEATH_TIMER,
    DEGRADE_TIMERS,
    TREATMENT_SUPPLY_COSTS,
    complete_treatment,
    generate_injuries,
    is_contagion_injury,
    stabilise_injury,
    tick_contagion_spread,
    tick_injury_timers,
)
from server.models.ship import Ship

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Legacy compat
TREATMENT_COST: int = 2
HEAL_INTERVAL: float = 2.0
SPREAD_INTERVAL: float = 30.0
RESUPPLY_AMOUNT: int = 5
RESUPPLY_MAX: int = 20

# New constants
MAX_MEDICAL_SUPPLIES: float = 100.0

# Bed counts by ship class
BEDS_BY_SHIP_CLASS: dict[str, int] = {
    "scout": 2,
    "corvette": 3,
    "frigate": 4,
    "cruiser": 5,
    "battleship": 6,
    "medical_ship": 8,
    "carrier": 5,
}

QUARANTINE_SLOTS_BY_SHIP_CLASS: dict[str, int] = {
    "scout": 1,
    "corvette": 2,
    "frigate": 2,
    "cruiser": 2,
    "battleship": 3,
    "medical_ship": 4,
    "carrier": 2,
}

# Treatment types that require puzzles
PUZZLE_TREATMENTS: set[str] = {"surgery", "intensive_care"}

# ---------------------------------------------------------------------------
# Treatment dataclass
# ---------------------------------------------------------------------------

class Treatment:
    """Active treatment on a crew member."""

    __slots__ = (
        "crew_member_id", "injury_id", "treatment_type",
        "duration", "elapsed", "puzzle_required", "puzzle_completed",
    )

    def __init__(
        self,
        crew_member_id: str,
        injury_id: str,
        treatment_type: str,
        duration: float,
        puzzle_required: bool = False,
        puzzle_completed: bool = False,
    ):
        self.crew_member_id = crew_member_id
        self.injury_id = injury_id
        self.treatment_type = treatment_type
        self.duration = duration
        self.elapsed = 0.0
        self.puzzle_required = puzzle_required
        self.puzzle_completed = puzzle_completed

    def to_dict(self) -> dict:
        return {
            "crew_member_id": self.crew_member_id,
            "injury_id": self.injury_id,
            "treatment_type": self.treatment_type,
            "duration": self.duration,
            "elapsed": round(self.elapsed, 2),
            "puzzle_required": self.puzzle_required,
            "puzzle_completed": self.puzzle_completed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Treatment:
        t = cls(
            crew_member_id=data["crew_member_id"],
            injury_id=data["injury_id"],
            treatment_type=data["treatment_type"],
            duration=data["duration"],
            puzzle_required=data.get("puzzle_required", False),
            puzzle_completed=data.get("puzzle_completed", False),
        )
        t.elapsed = data.get("elapsed", 0.0)
        return t


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_roster: IndividualCrewRoster | None = None
_treatment_beds: int = 4
_occupied_beds: dict[int, str] = {}          # bed_number → crew_member_id
_treatment_queue: list[str] = []             # crew_member_ids waiting
_active_treatments: dict[str, Treatment] = {}  # crew_id → Treatment
_medical_supplies: float = MAX_MEDICAL_SUPPLIES
_quarantine_slots: int = 2
_quarantine_occupied: dict[int, str] = {}    # slot → crew_member_id
_morgue: list[str] = []
_contagion_spread_timer: float = 0.0
_rng: random.Random = random.Random()

# Legacy compat state
_legacy_treatments: dict[str, str] = {}
_legacy_heal_timers: dict[str, float] = {}
_legacy_outbreak: dict[str, str] = {}


def reset() -> None:
    """Clear all medical state. Called at game start."""
    global _roster, _treatment_beds, _medical_supplies
    global _quarantine_slots, _contagion_spread_timer
    _roster = None
    _treatment_beds = 4
    _occupied_beds.clear()
    _treatment_queue.clear()
    _active_treatments.clear()
    _medical_supplies = MAX_MEDICAL_SUPPLIES
    _quarantine_slots = 2
    _quarantine_occupied.clear()
    _morgue.clear()
    _contagion_spread_timer = 0.0
    # Legacy
    _legacy_treatments.clear()
    _legacy_heal_timers.clear()
    _legacy_outbreak.clear()


def init_roster(roster: IndividualCrewRoster, ship_class: str = "frigate") -> None:
    """Initialise medical with a crew roster and ship class."""
    global _roster, _treatment_beds, _quarantine_slots
    _roster = roster
    _treatment_beds = BEDS_BY_SHIP_CLASS.get(ship_class, 4)
    _quarantine_slots = QUARANTINE_SLOTS_BY_SHIP_CLASS.get(ship_class, 2)


def get_roster() -> IndividualCrewRoster | None:
    """Return the current crew roster."""
    return _roster


def set_bed_count(n: int) -> None:
    """Set the number of treatment beds."""
    global _treatment_beds
    _treatment_beds = n


def get_bed_count() -> int:
    """Return the number of treatment beds."""
    return _treatment_beds


# ---------------------------------------------------------------------------
# Patient Management
# ---------------------------------------------------------------------------


def admit_patient(crew_id: str) -> dict:
    """Move crew member to medical bay, assign bed if available.

    Returns status dict: {"success": bool, "message": str, "bed": int|None}
    """
    if _roster is None:
        return {"success": False, "message": "No roster", "bed": None}

    member = _roster.members.get(crew_id)
    if member is None:
        return {"success": False, "message": "Unknown crew member", "bed": None}

    if member.status == "dead":
        return {"success": False, "message": "Crew member is dead", "bed": None}

    if member.location == "medical_bay":
        return {"success": False, "message": "Already in medical bay", "bed": None}

    # Assign bed if available
    bed = _find_free_bed()
    if bed is not None:
        _occupied_beds[bed] = crew_id
        member.treatment_bed = bed
        member.location = "medical_bay"
        return {"success": True, "message": "Admitted", "bed": bed}
    else:
        # Add to queue
        if crew_id not in _treatment_queue:
            _treatment_queue.append(crew_id)
        member.location = "medical_bay"
        return {"success": True, "message": "Queued for bed", "bed": None}


def _find_free_bed() -> int | None:
    """Find the first free bed number, or None."""
    for bed_num in range(1, _treatment_beds + 1):
        if bed_num not in _occupied_beds:
            return bed_num
    return None


def start_crew_treatment(
    crew_id: str,
    injury_id: str,
    treatment_type: str,
) -> dict:
    """Start treating a specific injury on a crew member.

    Crew member must be in a bed. Consumes medical supplies.
    Returns status dict.
    """
    global _medical_supplies

    if _roster is None:
        return {"success": False, "message": "No roster"}

    member = _roster.members.get(crew_id)
    if member is None:
        return {"success": False, "message": "Unknown crew member"}

    if member.treatment_bed is None:
        return {"success": False, "message": "Not in a bed"}

    # Find the injury
    injury = None
    for inj in member.injuries:
        if inj.id == injury_id:
            injury = inj
            break

    if injury is None:
        return {"success": False, "message": "Unknown injury"}

    if injury.treated:
        return {"success": False, "message": "Already treated"}

    if injury.treating:
        return {"success": False, "message": "Already being treated"}

    # Check another treatment isn't active on this crew member
    if crew_id in _active_treatments:
        return {"success": False, "message": "Another treatment in progress"}

    # Check supplies
    cost = TREATMENT_SUPPLY_COSTS.get(treatment_type, 5.0)
    if _medical_supplies < cost:
        return {"success": False, "message": "Insufficient supplies"}

    # Deduct supplies
    _medical_supplies -= cost

    # Determine if puzzle needed
    puzzle_required = treatment_type in PUZZLE_TREATMENTS

    # Create treatment
    treatment = Treatment(
        crew_member_id=crew_id,
        injury_id=injury_id,
        treatment_type=treatment_type,
        duration=injury.treatment_duration,
        puzzle_required=puzzle_required,
    )

    injury.treating = True
    _active_treatments[crew_id] = treatment

    return {
        "success": True,
        "message": "Treatment started",
        "puzzle_required": puzzle_required,
    }


def stabilise_crew(crew_id: str, injury_id: str) -> dict:
    """Quick stabilise: reset degrade timer without resolving.

    Does NOT require a bed. Can be done on deck. Costs 3% supplies.
    Stabilise still works at 0% supplies (emergency measure).
    """
    global _medical_supplies

    if _roster is None:
        return {"success": False, "message": "No roster"}

    member = _roster.members.get(crew_id)
    if member is None:
        return {"success": False, "message": "Unknown crew member"}

    injury = None
    for inj in member.injuries:
        if inj.id == injury_id:
            injury = inj
            break

    if injury is None:
        return {"success": False, "message": "Unknown injury"}

    if injury.treated:
        return {"success": False, "message": "Already treated"}

    # Stabilise works even at 0 supplies (emergency measure)
    cost = TREATMENT_SUPPLY_COSTS.get("stabilise", 3.0)
    _medical_supplies = max(0.0, _medical_supplies - cost)

    stabilise_injury(injury)

    return {"success": True, "message": "Stabilised"}


def quarantine_crew(crew_id: str) -> dict:
    """Move infected crew member to quarantine slot."""
    if _roster is None:
        return {"success": False, "message": "No roster"}

    member = _roster.members.get(crew_id)
    if member is None:
        return {"success": False, "message": "Unknown crew member"}

    # Check they have a contagion injury
    has_contagion = any(
        is_contagion_injury(i) and not i.treated
        for i in member.injuries
    )
    if not has_contagion:
        return {"success": False, "message": "Not infected"}

    if member.location == "quarantine":
        return {"success": False, "message": "Already quarantined"}

    # Find free quarantine slot
    slot = _find_free_quarantine_slot()
    if slot is None:
        return {"success": False, "message": "No quarantine slots available"}

    # Free bed if they were in one
    if member.treatment_bed is not None:
        _occupied_beds.pop(member.treatment_bed, None)
        member.treatment_bed = None

    # Remove from queue if present
    if crew_id in _treatment_queue:
        _treatment_queue.remove(crew_id)

    _quarantine_occupied[slot] = crew_id
    member.location = "quarantine"

    # Quarantine costs supplies (one-time)
    global _medical_supplies
    cost = TREATMENT_SUPPLY_COSTS.get("quarantine", 5.0)
    _medical_supplies = max(0.0, _medical_supplies - cost)

    return {"success": True, "message": "Quarantined", "slot": slot}


def _find_free_quarantine_slot() -> int | None:
    """Find a free quarantine slot."""
    for slot in range(1, _quarantine_slots + 1):
        if slot not in _quarantine_occupied:
            return slot
    return None


def discharge_patient(crew_id: str) -> dict:
    """Discharge treated crew member back to their deck.

    Only if all injuries are treated.
    """
    if _roster is None:
        return {"success": False, "message": "No roster"}

    member = _roster.members.get(crew_id)
    if member is None:
        return {"success": False, "message": "Unknown crew member"}

    # Check all injuries are treated
    untreated = [i for i in member.injuries if not i.treated]
    if untreated:
        return {"success": False, "message": "Untreated injuries remain"}

    # Free bed
    if member.treatment_bed is not None:
        _occupied_beds.pop(member.treatment_bed, None)
        member.treatment_bed = None

    # Free quarantine slot
    for slot, cid in list(_quarantine_occupied.items()):
        if cid == crew_id:
            del _quarantine_occupied[slot]
            break

    # Remove from active treatments
    _active_treatments.pop(crew_id, None)

    # Return to deck
    member.location = f"deck_{member.deck}"
    member.status = "active"

    return {"success": True, "message": "Discharged"}


def set_triage_priority(crew_ids: list[str]) -> None:
    """Reorder the treatment queue."""
    global _treatment_queue
    # Only include valid IDs that are actually in the queue
    valid = [cid for cid in crew_ids if cid in _treatment_queue]
    # Add any remaining queued IDs not in the new order
    remaining = [cid for cid in _treatment_queue if cid not in valid]
    _treatment_queue = valid + remaining


def notify_puzzle_complete(crew_id: str, success: bool) -> None:
    """Notify that a treatment puzzle has been completed."""
    treatment = _active_treatments.get(crew_id)
    if treatment is None:
        return
    treatment.puzzle_completed = True
    if not success:
        # Failed puzzle: treatment takes 50% longer
        treatment.duration *= 1.5


# ---------------------------------------------------------------------------
# Per-tick Processing
# ---------------------------------------------------------------------------


def tick(roster: IndividualCrewRoster, dt: float) -> list[dict]:
    """Tick all medical logic for one frame.

    Returns list of event dicts for broadcasts.
    """
    global _contagion_spread_timer
    events: list[dict] = []

    # 1. Tick all injury timers
    for member in list(roster.members.values()):
        if member.status == "dead":
            continue
        member_events = tick_injury_timers(member, dt)
        for ev in member_events:
            if ev["event"] == "crew_death":
                _handle_death(ev["crew_id"])
            events.append(ev)

    # 2. Tick contagion spread
    _contagion_spread_timer, spread_events = tick_contagion_spread(
        roster, dt, _contagion_spread_timer, _rng
    )
    events.extend(spread_events)

    # 3. Tick active treatments
    completed: list[str] = []
    for crew_id, treatment in list(_active_treatments.items()):
        if treatment.puzzle_required and not treatment.puzzle_completed:
            continue
        treatment.elapsed += dt
        if treatment.elapsed >= treatment.duration:
            _complete_treatment(crew_id, treatment, roster)
            completed.append(crew_id)
            events.append({
                "event": "treatment_complete",
                "crew_id": crew_id,
                "injury_id": treatment.injury_id,
            })

    for crew_id in completed:
        _active_treatments.pop(crew_id, None)

    # 4. Auto-admit from queue if beds available
    while _treatment_queue and len(_occupied_beds) < _treatment_beds:
        next_id = _treatment_queue.pop(0)
        member = roster.members.get(next_id)
        if member is None or member.status == "dead":
            continue
        bed = _find_free_bed()
        if bed is not None:
            _occupied_beds[bed] = next_id
            member.treatment_bed = bed
            member.location = "medical_bay"
            events.append({
                "event": "patient_admitted",
                "crew_id": next_id,
                "bed": bed,
            })

    return events


def _handle_death(crew_id: str) -> None:
    """Handle crew member death — clean up medical state."""
    if crew_id not in _morgue:
        _morgue.append(crew_id)

    # Free bed
    for bed, cid in list(_occupied_beds.items()):
        if cid == crew_id:
            del _occupied_beds[bed]
            break

    # Free quarantine slot
    for slot, cid in list(_quarantine_occupied.items()):
        if cid == crew_id:
            del _quarantine_occupied[slot]
            break

    # Remove from queue
    if crew_id in _treatment_queue:
        _treatment_queue.remove(crew_id)

    # Remove active treatment
    _active_treatments.pop(crew_id, None)


def _complete_treatment(
    crew_id: str,
    treatment: Treatment,
    roster: IndividualCrewRoster,
) -> None:
    """Complete a treatment — mark injury as treated."""
    member = roster.members.get(crew_id)
    if member is None:
        return
    for injury in member.injuries:
        if injury.id == treatment.injury_id:
            complete_treatment(injury)
            break
    member.update_status()


# ---------------------------------------------------------------------------
# State Queries
# ---------------------------------------------------------------------------


def get_medical_state() -> dict:
    """Return full medical state for broadcast to Medical client."""
    return {
        "beds_total": _treatment_beds,
        "beds_occupied": {k: v for k, v in _occupied_beds.items()},
        "queue": list(_treatment_queue),
        "active_treatments": {
            cid: t.to_dict() for cid, t in _active_treatments.items()
        },
        "supplies": round(_medical_supplies, 1),
        "supplies_max": MAX_MEDICAL_SUPPLIES,
        "quarantine_total": _quarantine_slots,
        "quarantine_occupied": {k: v for k, v in _quarantine_occupied.items()},
        "morgue": list(_morgue),
    }


def get_supplies() -> float:
    """Return current medical supply level."""
    return _medical_supplies


def set_supplies(amount: float) -> None:
    """Set medical supply level (e.g., from docking resupply)."""
    global _medical_supplies
    _medical_supplies = min(amount, MAX_MEDICAL_SUPPLIES)


# ---------------------------------------------------------------------------
# Legacy compatibility interface
# (Maintains the same API as game_loop_medical.py for drop-in replacement)
# ---------------------------------------------------------------------------


def start_treatment(deck_name: str, injury_type: str, ship: Ship) -> bool:
    """LEGACY: Start treatment on a deck. Deducts TREATMENT_COST supplies.

    This is the backward-compatible interface for the old medical system.
    """
    if ship.medical_supplies < TREATMENT_COST:
        return False
    if deck_name not in ship.crew.decks:
        return False
    ship.medical_supplies -= TREATMENT_COST
    _legacy_treatments[deck_name] = injury_type
    _legacy_heal_timers[deck_name] = 0.0
    return True


def cancel_treatment(deck_name: str) -> None:
    """LEGACY: Cancel treatment on a deck."""
    _legacy_treatments.pop(deck_name, None)
    _legacy_heal_timers.pop(deck_name, None)


def get_active_treatments() -> dict[str, str]:
    """LEGACY: Return current deck treatments for ship.state broadcast."""
    return dict(_legacy_treatments)


def tick_treatments(ship: Ship, dt: float) -> list[str]:
    """LEGACY: Tick the old deck-level treatment system."""
    healed: list[str] = []
    to_cancel: list[str] = []

    for deck_name, injury_type in list(_legacy_treatments.items()):
        _legacy_heal_timers[deck_name] = _legacy_heal_timers.get(deck_name, 0.0) + dt
        if _legacy_heal_timers[deck_name] < HEAL_INTERVAL:
            continue
        _legacy_heal_timers[deck_name] = 0.0

        if injury_type == "injured":
            treated = ship.crew.treat_injured(deck_name, 1)
        else:
            treated = ship.crew.treat_critical(deck_name, 1)

        if treated > 0:
            healed.append(deck_name)
        else:
            to_cancel.append(deck_name)

    for deck_name in to_cancel:
        cancel_treatment(deck_name)

    return healed


def start_outbreak(deck_name: str, pathogen: str) -> None:
    """LEGACY: Mark a deck as infected."""
    if deck_name not in _legacy_outbreak:
        _legacy_outbreak[deck_name] = pathogen


def tick_disease(interior: object, dt: float) -> list[dict]:
    """LEGACY: Tick disease spread."""
    global _contagion_spread_timer
    if not _legacy_outbreak:
        return []
    _contagion_spread_timer += dt
    if _contagion_spread_timer < SPREAD_INTERVAL:
        return []
    _contagion_spread_timer = 0.0
    return _try_spread(interior)


def _try_spread(interior: object) -> list[dict]:
    """LEGACY: Spread infection through unsealed connections."""
    events: list[dict] = []
    new_infections: dict[str, str] = {}
    rooms = interior.rooms  # type: ignore[attr-defined]
    for deck, pathogen in list(_legacy_outbreak.items()):
        infected_rooms = [r for r in rooms.values() if r.deck == deck]
        for room in infected_rooms:
            for conn_id in room.connections:
                conn_room = rooms.get(conn_id)
                if conn_room is None or conn_room.deck == deck:
                    continue
                if room.door_sealed or conn_room.door_sealed:
                    continue
                target_deck = conn_room.deck
                if target_deck not in _legacy_outbreak and target_deck not in new_infections:
                    new_infections[target_deck] = pathogen
                    events.append({
                        "from_deck": deck,
                        "to_deck": target_deck,
                        "pathogen": pathogen,
                    })
    _legacy_outbreak.update(new_infections)
    return events


def get_disease_state() -> dict:
    """LEGACY: Return disease state for broadcast."""
    return {
        "infected_decks": dict(_legacy_outbreak),
        "spread_timer": round(_contagion_spread_timer, 2),
        "spread_interval": SPREAD_INTERVAL,
    }


# ---------------------------------------------------------------------------
# Serialise / Deserialise
# ---------------------------------------------------------------------------


def serialise() -> dict:
    """Serialise all medical state for save/resume."""
    return {
        # Legacy state (for backward compat with saves)
        "active_treatments": dict(_legacy_treatments),
        "heal_timers": dict(_legacy_heal_timers),
        "active_outbreak": dict(_legacy_outbreak),
        "spread_timer": _contagion_spread_timer,
        # New v2 state
        "v2": {
            "treatment_beds": _treatment_beds,
            "occupied_beds": dict(_occupied_beds),
            "treatment_queue": list(_treatment_queue),
            "active_crew_treatments": {
                cid: t.to_dict() for cid, t in _active_treatments.items()
            },
            "medical_supplies": _medical_supplies,
            "quarantine_slots": _quarantine_slots,
            "quarantine_occupied": dict(_quarantine_occupied),
            "morgue": list(_morgue),
        },
    }


def deserialise(data: dict) -> None:
    """Deserialise medical state from saved data."""
    global _contagion_spread_timer, _treatment_beds
    global _medical_supplies, _quarantine_slots

    # Legacy state
    _legacy_treatments.clear()
    _legacy_treatments.update(data.get("active_treatments", {}))
    _legacy_heal_timers.clear()
    _legacy_heal_timers.update(data.get("heal_timers", {}))
    _legacy_outbreak.clear()
    _legacy_outbreak.update(data.get("active_outbreak", {}))
    _contagion_spread_timer = data.get("spread_timer", 0.0)

    # New v2 state
    v2 = data.get("v2", {})
    if v2:
        _treatment_beds = v2.get("treatment_beds", 4)
        _occupied_beds.clear()
        for k, v in v2.get("occupied_beds", {}).items():
            _occupied_beds[int(k)] = v
        _treatment_queue.clear()
        _treatment_queue.extend(v2.get("treatment_queue", []))
        _active_treatments.clear()
        for cid, tdata in v2.get("active_crew_treatments", {}).items():
            _active_treatments[cid] = Treatment.from_dict(tdata)
        _medical_supplies = v2.get("medical_supplies", MAX_MEDICAL_SUPPLIES)
        _quarantine_slots = v2.get("quarantine_slots", 2)
        _quarantine_occupied.clear()
        for k, v in v2.get("quarantine_occupied", {}).items():
            _quarantine_occupied[int(k)] = v
        _morgue.clear()
        _morgue.extend(v2.get("morgue", []))
