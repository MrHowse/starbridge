"""
Hazard Control — fire model, DCT dispatch, and environmental hazard management.

v0.08 B.2: Five-level fire intensity model with escalation, four suppression
methods (localised, deck-wide, ventilation cutoff, manual fire team), suppressant
resource, and cross-station effects (equipment damage, crew evacuation, smoke).

Severity order for room.state: normal < damaged < fire < decompressed.
DCT can fix: fire → damaged → normal.  Decompressed rooms require EVA.

When a DCT is assigned to a room that has an active Fire, each DCT repair cycle
reduces fire intensity by 1 instead of changing room.state.  Once intensity
reaches 0 the fire is removed and room.state becomes "damaged".

State is module-level; reset() is called at game start.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field

from server.models.interior import ShipInterior, Room
import server.game_loop_rationing as glrat
import server.game_loop_operations as glops

logger = logging.getLogger("starbridge.hazard_control")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DCT_REPAIR_DURATION: float = 8.0     # seconds to reduce a room by one severity level
FIRE_SPREAD_INTERVAL: float = 20.0   # seconds between automatic fire-spread ticks (legacy, used as fallback)
HULL_DAMAGE_THRESHOLD: float = 5.0   # accumulated hull damage required to trigger a room event
FIRE_CHANCE: float = 0.35            # probability that a new room event results in fire (vs damaged)

# --- Fire intensity model (B.2) ---

ESCALATION_INTERVAL: float = 45.0    # seconds before unsuppressed fire gains +1 intensity

# Spread timer per intensity (seconds until spread attempt).
SPREAD_TIMERS: dict[int, float] = {
    1: 60.0,   # Smouldering — no spread for 60s
    2: 90.0,   # Small fire
    3: 60.0,   # Moderate fire
    4: 30.0,   # Major fire
    5: 15.0,   # Inferno
}

# Crew effectiveness penalty per intensity level on that deck.
CREW_EFF_PENALTY: dict[int, float] = {
    1: 0.05,
    2: 0.15,
    3: 0.30,
    4: 0.60,
    5: 1.00,
}

# Crew HP damage per 30 seconds in the room (intensity 3+).
CREW_HP_DAMAGE: dict[int, float] = {
    3: 1.0,
    4: 3.0,
    5: 5.0,
}

# Equipment damage % per second in the room (intensity 4+).
EQUIP_DAMAGE_PER_SEC: dict[int, float] = {
    4: 0.2,    # 2% per 10s
    5: 0.5,    # 5% per 10s
}

# Adjacent room equipment damage % per second at intensity 5.
ADJACENT_HEAT_DAMAGE_PER_SEC: float = 0.033   # ~1% per 30s

# --- Suppression constants ---

LOCAL_SUPPRESS_TIME: float = 5.0
LOCAL_SUPPRESS_COST: int = 1
LOCAL_SUPPRESS_REDUCTION: int = 2

DECK_SUPPRESS_TIME: float = 15.0
DECK_SUPPRESS_COST: int = 3
DECK_SUPPRESS_REDUCTION: int = 1

VENT_REDUCTION_INTERVAL: float = 20.0
VENT_O2_DAMAGE_DELAY: float = 30.0

MANUAL_TEAM_INTERVAL: float = 20.0
MANUAL_TEAM_INJURY_CHANCE: float = 0.10

# --- Fire cause probabilities ---

COMBAT_FIRE_CHANCE: float = 0.40
COMBAT_FIRE_INTENSITY: int = 2
OVERCLOCK_FIRE_CHANCE: float = 0.15
OVERCLOCK_FIRE_INTENSITY: int = 1
REACTOR_FIRE_CHANCE: float = 0.25
REACTOR_FIRE_INTENSITY: int = 3

# Severity level mapping (legacy, still used for DCT room.state repairs).
_SEVERITY: dict[str, int] = {
    "normal": 0,
    "damaged": 1,
    "fire": 2,
    "decompressed": 3,
}
_SEVERITY_DOWN: dict[int, str] = {3: "fire", 2: "damaged", 1: "normal"}

# --- Structural integrity model (B.5) ---

STRUCT_NORMAL_MIN: float = 76.0
STRUCT_STRESSED_MIN: float = 51.0
STRUCT_WEAKENED_MIN: float = 26.0
STRUCT_CRITICAL_MIN: float = 1.0
STRUCT_WEAKENED_COLLAPSE_CHANCE: float = 0.15
STRUCT_CRITICAL_COLLAPSE_CHANCE: float = 0.40
STRUCT_WEAKENED_CREW_PENALTY: float = 0.10
STRUCT_CRITICAL_CREW_PENALTY: float = 0.30

# Combat structural damage ranges.
STRUCT_BEAM_DMG_MIN: float = 5.0
STRUCT_BEAM_DMG_MAX: float = 10.0
STRUCT_TORPEDO_DMG_MIN: float = 15.0
STRUCT_TORPEDO_DMG_MAX: float = 25.0
STRUCT_BREACH_DMG: float = 10.0
STRUCT_EXPLOSION_DMG_MIN: float = 20.0
STRUCT_EXPLOSION_DMG_MAX: float = 30.0

# Fire structural damage (intensity 4+).
STRUCT_FIRE_DMG_INTERVAL: float = 30.0   # seconds between checks
STRUCT_FIRE_DMG_AMOUNT: float = 2.0      # % per interval

# Reinforcement.
REINFORCE_INTERVAL: float = 30.0
REINFORCE_AMOUNT: float = 10.0
REINFORCE_MAX: float = 80.0
REINFORCE_MIN_CREW: int = 2

# Collapse effects.
COLLAPSE_FIRE_CHANCE: float = 0.80
COLLAPSE_FIRE_INTENSITY: int = 3
COLLAPSE_CASCADE_DMG: float = 15.0

# --- Emergency power (B.6.2) ---

EMERGENCY_BATTERY_CAPACITY: float = 180.0    # seconds per deck
BATTERY_TRANSFER_AMOUNT: float = 60.0        # seconds per redirect action
NO_POWER_CREW_PENALTY: float = 0.80          # crew eff drops to 20%
NO_POWER_CREW_DAMAGE: float = 0.017          # HP/s (~0.5 HP/30s)

# --- Life pods (B.6.3) ---

LIFE_POD_CAPACITY: int = 4
LIFE_POD_LAUNCH_TIME: float = 10.0           # seconds to launch
LIFE_POD_LOAD_RATE: float = 1.0              # crew/second per pod
ABANDON_SHIP_HULL_THRESHOLD: float = 0.15    # fraction of max hull
SMALL_SHIP_PODS_PER_DECK: int = 1
LARGE_SHIP_PODS_PER_DECK: int = 2
LARGE_SHIP_CLASSES: tuple[str, ...] = ("cruiser", "carrier", "battleship")

# ---------------------------------------------------------------------------
# Fire dataclass
# ---------------------------------------------------------------------------


@dataclass
class Fire:
    """One active fire in a ship room."""

    room_id: str
    intensity: int              # 1–5
    spread_timer: float         # seconds until next spread attempt
    escalation_timer: float     # seconds until +1 intensity
    started_tick: int = 0
    suppression_timer: float = 0.0   # >0 means suppression in progress
    suppression_type: str = ""       # "local" / "deck" / "vent" / "manual"
    vent_elapsed: float = 0.0        # seconds room has been vented


# ---------------------------------------------------------------------------
# Section dataclass (B.5)
# ---------------------------------------------------------------------------


@dataclass
class Section:
    """One structural section of the ship (a group of 2 adjacent rooms)."""

    id: str                          # "deck1_a", "deck1_b", etc.
    deck_number: int                 # Physical deck number (1-based)
    deck_name: str                   # Crew deck name (from first room in section)
    room_ids: list[str] = field(default_factory=list)
    integrity: float = 100.0         # 0–100%
    collapsed: bool = False


# ---------------------------------------------------------------------------
# LifePod dataclass (B.6.3)
# ---------------------------------------------------------------------------


@dataclass
class LifePod:
    """One life pod on a ship deck."""

    id: str
    deck_number: int
    capacity: int = LIFE_POD_CAPACITY
    loaded_crew: int = 0
    launched: bool = False
    launch_timer: float = 0.0        # >0 means launching in progress
    _load_accum: float = 0.0         # fractional crew loading accumulator


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_active_dcts: dict[str, float] = {}         # room_id → elapsed repair seconds
_pending_hull_damage: float = 0.0           # accumulated hull damage not yet processed

_fires: dict[str, Fire] = {}                # room_id → Fire
_fire_teams: dict[str, float] = {}          # room_id → elapsed seconds (manual teams)
_vent_rooms: set[str] = set()               # rooms with ventilation cutoff active
_deck_suppression: dict[str, float] = {}    # deck_name → remaining cooldown

# Structural integrity (B.5).
_sections: dict[str, Section] = {}           # section_id → Section
_reinforcement_teams: dict[str, float] = {}  # section_id → elapsed seconds
_room_to_section: dict[str, str] = {}        # room_id → section_id (lookup cache)
_section_adjacency: dict[str, list[str]] = {}  # section_id → adjacent section IDs
_fire_structural_timers: dict[str, float] = {}  # section_id → accumulated fire-damage time

# Emergency bulkheads (B.6.1).
_sealed_connections: set[tuple[str, str]] = set()  # sorted (room_a, room_b) pairs

# Emergency power (B.6.2).
_deck_batteries: dict[int, float] = {}     # deck_number → remaining seconds
_deck_power: dict[int, str] = {}           # deck_number → "main" / "emergency" / "none"
_power_cut_overrides: set[int] = set()     # decks where HC manually cut power

# Life pods (B.6.3).
_life_pods: list[LifePod] = []
_abandon_ship: bool = False
_evacuation_order: list[int] = []          # deck_numbers in priority order

# C.3.1: Fire suppression power gate.
FIRE_SUPPRESSION_MIN_EFFICIENCY: float = 0.10
_fire_suppression_powered: bool = True

# C.12: QM resource consumption tracking.
DECON_SUPPLY_COST: float = 1.5
_resource_consumption: dict[str, float] = {}  # resource_type → total consumed

# C.7: Medical injury prediction + evacuation warnings.
_pending_evac_warnings: list[dict] = []

# B.2.3.3: Per-room crew presence for fire evacuation.
_room_crew_counts: dict[str, int] = {}   # room_id → crew present
_evacuated_rooms: set[str] = set()       # rooms evacuated due to intensity 3+ fire

_rng: random.Random = random.Random()


# ---------------------------------------------------------------------------
# Public API — lifecycle
# ---------------------------------------------------------------------------


def reset() -> None:
    """Clear all hazard-control state.  Called at game start."""
    global _pending_hull_damage, _abandon_ship, _fire_suppression_powered
    _active_dcts.clear()
    _pending_hull_damage = 0.0
    _fires.clear()
    _fire_teams.clear()
    _vent_rooms.clear()
    _deck_suppression.clear()
    _sections.clear()
    _reinforcement_teams.clear()
    _room_to_section.clear()
    _section_adjacency.clear()
    _fire_structural_timers.clear()
    # B.6 emergency systems.
    _sealed_connections.clear()
    _deck_batteries.clear()
    _deck_power.clear()
    _power_cut_overrides.clear()
    _life_pods.clear()
    _abandon_ship = False
    _evacuation_order.clear()
    # C.3.1: Fire suppression power gate.
    _fire_suppression_powered = True
    # C.12: QM resource consumption tracking.
    _resource_consumption.clear()
    # C.7: Medical evacuation warnings.
    _pending_evac_warnings.clear()
    # B.2.3.3: Room crew counts.
    _room_crew_counts.clear()
    _evacuated_rooms.clear()


# ---------------------------------------------------------------------------
# Public API — structural integrity (B.5)
# ---------------------------------------------------------------------------


def init_sections(interior: ShipInterior) -> None:
    """Build structural sections from the interior layout.

    Each deck's rooms are split into pairs of 2 in order of room ID.
    Adjacent sections are pre-computed for cascade calculations.
    """
    _sections.clear()
    _room_to_section.clear()
    _section_adjacency.clear()
    _fire_structural_timers.clear()
    _reinforcement_teams.clear()

    # Group rooms by deck_number.
    deck_rooms: dict[int, list[Room]] = {}
    for room in interior.rooms.values():
        deck_rooms.setdefault(room.deck_number, []).append(room)

    # Sort each deck's rooms by ID for deterministic ordering.
    for dn in sorted(deck_rooms):
        rooms = sorted(deck_rooms[dn], key=lambda r: r.id)
        # Split into pairs of 2.
        idx = 0
        suffix = ord("a")
        while idx < len(rooms):
            chunk = rooms[idx:idx + 2]
            section_id = f"deck{dn}_{chr(suffix)}"
            sec = Section(
                id=section_id,
                deck_number=dn,
                deck_name=chunk[0].deck,
                room_ids=[r.id for r in chunk],
            )
            _sections[section_id] = sec
            for r in chunk:
                _room_to_section[r.id] = section_id
            suffix += 1
            idx += 2

    # Compute adjacency (same deck_number OR cross-deck room connections).
    section_ids = list(_sections)
    for i, sid_a in enumerate(section_ids):
        sa = _sections[sid_a]
        adj: list[str] = []
        for sid_b in section_ids:
            if sid_b == sid_a:
                continue
            sb = _sections[sid_b]
            # Same deck.
            if sa.deck_number == sb.deck_number:
                adj.append(sid_b)
                continue
            # Cross-deck: check room connections.
            connected = False
            for rid_a in sa.room_ids:
                room_a = interior.rooms.get(rid_a)
                if room_a is None:
                    continue
                for rid_b in sb.room_ids:
                    if rid_b in room_a.connections:
                        connected = True
                        break
                if connected:
                    break
            if connected:
                adj.append(sid_b)
        _section_adjacency[sid_a] = adj


def rebuild_adjacency(interior: ShipInterior) -> None:
    """Recompute section adjacency from current sections and interior connections.

    Call after deserialise() when interior is available.
    """
    _section_adjacency.clear()
    section_ids = list(_sections)
    for sid_a in section_ids:
        sa = _sections[sid_a]
        adj: list[str] = []
        for sid_b in section_ids:
            if sid_b == sid_a:
                continue
            sb = _sections[sid_b]
            if sa.deck_number == sb.deck_number:
                adj.append(sid_b)
                continue
            connected = False
            for rid_a in sa.room_ids:
                room_a = interior.rooms.get(rid_a)
                if room_a is None:
                    continue
                for rid_b in sb.room_ids:
                    if rid_b in room_a.connections:
                        connected = True
                        break
                if connected:
                    break
            if connected:
                adj.append(sid_b)
        _section_adjacency[sid_a] = adj


def get_sections() -> dict[str, Section]:
    """Return the current sections dict (read-only intent)."""
    return _sections


def get_section_for_room(room_id: str) -> Section | None:
    """Look up the section containing a room."""
    sid = _room_to_section.get(room_id)
    if sid is None:
        return None
    return _sections.get(sid)


def get_section_state(section: Section) -> str:
    """Return the severity state for a section based on its integrity."""
    if section.collapsed:
        return "collapsed"
    if section.integrity >= STRUCT_NORMAL_MIN:
        return "normal"
    if section.integrity >= STRUCT_STRESSED_MIN:
        return "stressed"
    if section.integrity >= STRUCT_WEAKENED_MIN:
        return "weakened"
    if section.integrity >= STRUCT_CRITICAL_MIN:
        return "critical"
    return "collapsed"


def apply_combat_structural_damage(
    interior: ShipInterior, damage_type: str = "beam",
) -> list[dict]:
    """Apply structural damage from combat to a random non-collapsed section.

    damage_type: "beam" (-5 to -10%) or "torpedo" (-15 to -25%).
    Returns list of event dicts (collapse, structural_warning, etc.).
    """
    if damage_type == "torpedo":
        dmg = _rng.uniform(STRUCT_TORPEDO_DMG_MIN, STRUCT_TORPEDO_DMG_MAX)
    else:
        dmg = _rng.uniform(STRUCT_BEAM_DMG_MIN, STRUCT_BEAM_DMG_MAX)
    eligible = [s for s in _sections.values() if not s.collapsed]
    if not eligible:
        return []
    section = _rng.choice(eligible)
    return _apply_section_damage(section, dmg, interior)


def apply_breach_structural_damage(room_id: str) -> list[dict]:
    """Apply -10% structural damage when a hull breach is created."""
    sec = get_section_for_room(room_id)
    if sec is None or sec.collapsed:
        return []
    return _apply_section_damage(sec, STRUCT_BREACH_DMG)


def apply_explosion_structural_damage(
    room_id: str, interior: ShipInterior | None = None,
) -> list[dict]:
    """Apply -20 to -30% structural damage from an explosion."""
    sec = get_section_for_room(room_id)
    if sec is None or sec.collapsed:
        return []
    dmg = _rng.uniform(STRUCT_EXPLOSION_DMG_MIN, STRUCT_EXPLOSION_DMG_MAX)
    return _apply_section_damage(sec, dmg, interior)


def _apply_section_damage(
    section: Section, amount: float,
    interior: ShipInterior | None = None,
    ship: object | None = None,
    _collapsed_set: set[str] | None = None,
) -> list[dict]:
    """Reduce section integrity and check for collapse.

    Returns list of event dicts.
    """
    events: list[dict] = []
    if section.collapsed:
        return events

    old_integrity = section.integrity
    section.integrity = max(0.0, section.integrity - amount)

    # Ops warning when crossing 50%.
    if old_integrity >= 50.0 and section.integrity < 50.0:
        glops.add_feed_event(
            "HAZCON",
            f"STRUCTURAL WARNING: {section.id} at {section.integrity:.0f}%",
            "warning",
        )
        events.append({
            "type": "structural_warning",
            "section_id": section.id,
            "integrity": round(section.integrity, 1),
        })

    # Check for collapse chance on Weakened/Critical sections.
    state = get_section_state(section)
    if state == "weakened" and _rng.random() < STRUCT_WEAKENED_COLLAPSE_CHANCE:
        events.extend(_collapse_section(section, interior, ship, _collapsed_set))
    elif state == "critical" and _rng.random() < STRUCT_CRITICAL_COLLAPSE_CHANCE:
        events.extend(_collapse_section(section, interior, ship, _collapsed_set))
    elif section.integrity <= 0.0:
        events.extend(_collapse_section(section, interior, ship, _collapsed_set))

    return events


def _collapse_section(
    section: Section,
    interior: ShipInterior | None = None,
    ship: object | None = None,
    _collapsed_set: set[str] | None = None,
) -> list[dict]:
    """Collapse a section: destroy equipment, create breaches/fires/casualties, cascade."""
    import server.game_loop_atmosphere as glatm

    events: list[dict] = []
    section.collapsed = True
    section.integrity = 0.0
    # Cancel any reinforcement in progress.
    _reinforcement_teams.pop(section.id, None)

    if _collapsed_set is None:
        _collapsed_set = set()
    _collapsed_set.add(section.id)

    logger.info("Section COLLAPSED: %s", section.id)
    events.append({
        "type": "structural_collapse",
        "section_id": section.id,
        "deck_number": section.deck_number,
        "room_ids": list(section.room_ids),
    })

    for room_id in section.room_ids:
        # Destroy equipment (ship systems in this room).
        if ship is not None:
            systems = getattr(ship, "systems", {})
            for sys_obj in systems.values():
                if getattr(sys_obj, "room_id", None) == room_id:
                    sys_obj.health = 0.0

        # Create major breach.
        if interior is not None:
            glatm.create_breach(room_id, "major", interior)

        # Fire (80% chance, intensity 3).
        if interior is not None and _rng.random() < COLLAPSE_FIRE_CHANCE:
            start_fire(room_id, COLLAPSE_FIRE_INTENSITY, interior)

    # Crew casualties: injure 2 crew per room in section.
    if ship is not None:
        crew = getattr(ship, "crew", None)
        if crew is not None:
            casualty_count = len(section.room_ids) * 2
            crew.apply_casualties(section.deck_name, casualty_count)
            events.append({
                "type": "structural_casualties",
                "section_id": section.id,
                "deck_name": section.deck_name,
                "count": casualty_count,
            })

    # Cascade: adjacent sections take -15% damage.
    for adj_sid in _section_adjacency.get(section.id, []):
        if adj_sid in _collapsed_set:
            continue
        adj = _sections.get(adj_sid)
        if adj is not None and not adj.collapsed:
            events.extend(
                _apply_section_damage(adj, COLLAPSE_CASCADE_DMG, interior, ship, _collapsed_set)
            )

    return events


def restore_all_sections() -> None:
    """Restore all sections to 100% integrity (used on docking)."""
    for section in _sections.values():
        if not section.collapsed:
            section.integrity = 100.0


def reinforce_section(section_id: str, ship: object | None = None) -> bool:
    """Start structural reinforcement on a section.

    Returns False if collapsed, at max, or insufficient crew.
    """
    sec = _sections.get(section_id)
    if sec is None or sec.collapsed:
        return False
    if sec.integrity >= REINFORCE_MAX:
        return False
    if section_id in _reinforcement_teams:
        return False

    # Check crew: need at least 2 active on the section's deck.
    if ship is not None:
        crew = getattr(ship, "crew", None)
        if crew is not None:
            deck = crew.decks.get(sec.deck_name)
            if deck is None or deck.active < REINFORCE_MIN_CREW:
                return False

    _reinforcement_teams[section_id] = 0.0
    logger.debug("Reinforcement started: %s", section_id)
    return True


def cancel_reinforcement(section_id: str) -> bool:
    """Cancel active structural reinforcement."""
    if section_id in _reinforcement_teams:
        del _reinforcement_teams[section_id]
        return True
    return False


def get_structural_crew_penalties() -> dict[str, float]:
    """Return deck_name → worst crew efficiency penalty from structural damage.

    Weakened sections: 0.10 penalty.
    Critical sections: 0.30 penalty.
    """
    penalties: dict[str, float] = {}
    for sec in _sections.values():
        if sec.collapsed:
            continue
        state = get_section_state(sec)
        if state == "weakened":
            penalty = STRUCT_WEAKENED_CREW_PENALTY
        elif state == "critical":
            penalty = STRUCT_CRITICAL_CREW_PENALTY
        else:
            continue
        if penalty > penalties.get(sec.deck_name, 0.0):
            penalties[sec.deck_name] = penalty
    return penalties


# ---------------------------------------------------------------------------
# Public API — emergency bulkheads (B.6.1)
# ---------------------------------------------------------------------------


def _connection_key(room_a: str, room_b: str) -> tuple[str, str]:
    """Return a sorted (min, max) tuple for a room connection."""
    return (min(room_a, room_b), max(room_a, room_b))


def seal_connection(room_a: str, room_b: str, interior: ShipInterior) -> bool:
    """Seal an emergency bulkhead between two connected rooms.

    Returns False if rooms are not connected or already sealed.
    """
    ra = interior.rooms.get(room_a)
    rb = interior.rooms.get(room_b)
    if ra is None or rb is None:
        return False
    if room_b not in ra.connections:
        return False
    key = _connection_key(room_a, room_b)
    if key in _sealed_connections:
        return False
    _sealed_connections.add(key)
    logger.info("Emergency bulkhead sealed: %s ↔ %s", room_a, room_b)
    return True


def unseal_connection(room_a: str, room_b: str) -> bool:
    """Remove emergency bulkhead seal. Returns False if not sealed."""
    key = _connection_key(room_a, room_b)
    if key not in _sealed_connections:
        return False
    _sealed_connections.discard(key)
    logger.info("Emergency bulkhead unsealed: %s ↔ %s", room_a, room_b)
    return True


def is_connection_sealed(room_a: str, room_b: str) -> bool:
    """Check whether an emergency bulkhead is sealed between two rooms."""
    return _connection_key(room_a, room_b) in _sealed_connections


def get_sealed_connections() -> set[tuple[str, str]]:
    """Return a copy of all sealed connections."""
    return set(_sealed_connections)


def override_security_lock(room_id: str, interior: ShipInterior) -> list[dict]:
    """Override Security door lock (unlock room for evacuation).

    Returns event list. If the door was sealed, unlocks it and emits an event
    for Security notification.
    """
    room = interior.rooms.get(room_id)
    if room is None:
        return []
    if not room.door_sealed:
        return []
    room.door_sealed = False
    logger.info("HAZCON OVERRIDE: Door %s unlocked for evacuation", room_id)
    return [{"type": "security_override", "room_id": room_id,
             "message": f"HAZCON OVERRIDE: Door {room.name} unlocked for evacuation"}]


# ---------------------------------------------------------------------------
# Public API — emergency power (B.6.2)
# ---------------------------------------------------------------------------


def init_emergency_power(interior: ShipInterior) -> None:
    """Initialise per-deck batteries and power state. Called at game start."""
    _deck_batteries.clear()
    _deck_power.clear()
    _power_cut_overrides.clear()
    deck_numbers: set[int] = set()
    for room in interior.rooms.values():
        deck_numbers.add(room.deck_number)
    for dn in deck_numbers:
        _deck_batteries[dn] = EMERGENCY_BATTERY_CAPACITY
        _deck_power[dn] = "main"


def redirect_battery(from_deck: int, to_deck: int,
                     amount: float = BATTERY_TRANSFER_AMOUNT) -> bool:
    """Transfer battery seconds from one deck to another.

    Returns False if source has insufficient battery.
    """
    if from_deck not in _deck_batteries or to_deck not in _deck_batteries:
        return False
    available = _deck_batteries[from_deck]
    if available < amount:
        return False
    _deck_batteries[from_deck] -= amount
    _deck_batteries[to_deck] += amount
    logger.info("Battery redirected: deck %d → deck %d (%.0fs)", from_deck, to_deck, amount)
    return True


def cut_deck_power(deck_number: int) -> bool:
    """HC manually cuts main power on a deck. Returns True if now cut."""
    if deck_number not in _deck_power:
        return False
    _power_cut_overrides.add(deck_number)
    return True


def restore_deck_power(deck_number: int) -> bool:
    """HC removes manual power cut. Returns True if override was active."""
    if deck_number not in _power_cut_overrides:
        return False
    _power_cut_overrides.discard(deck_number)
    return True


def get_power_crew_penalties() -> dict[str, float]:
    """Return deck_name → 0.80 penalty for decks with no power."""
    penalties: dict[str, float] = {}
    for sec in _sections.values():
        if _deck_power.get(sec.deck_number) == "none":
            if NO_POWER_CREW_PENALTY > penalties.get(sec.deck_name, 0.0):
                penalties[sec.deck_name] = NO_POWER_CREW_PENALTY
    return penalties


def get_powerless_decks() -> set[int]:
    """Return deck numbers with power='none' (for cross-station queries)."""
    return {dn for dn, state in _deck_power.items() if state == "none"}


def get_deck_power() -> dict[int, str]:
    """Return deck_number → power state dict."""
    return dict(_deck_power)


def restore_all_power() -> None:
    """Restore all batteries and power to main (used on docking)."""
    _power_cut_overrides.clear()
    for dn in _deck_batteries:
        _deck_batteries[dn] = EMERGENCY_BATTERY_CAPACITY
        _deck_power[dn] = "main"


# ---------------------------------------------------------------------------
# Public API — life pods (B.6.3)
# ---------------------------------------------------------------------------


def init_life_pods(ship_class: str, interior: ShipInterior) -> None:
    """Create life pods based on ship class and interior layout."""
    _life_pods.clear()
    global _abandon_ship
    _abandon_ship = False
    _evacuation_order.clear()

    pods_per_deck = (LARGE_SHIP_PODS_PER_DECK
                     if ship_class in LARGE_SHIP_CLASSES
                     else SMALL_SHIP_PODS_PER_DECK)

    deck_numbers: set[int] = set()
    for room in interior.rooms.values():
        deck_numbers.add(room.deck_number)

    for dn in sorted(deck_numbers):
        for i in range(pods_per_deck):
            pod_id = f"pod_d{dn}_{chr(ord('a') + i)}"
            _life_pods.append(LifePod(id=pod_id, deck_number=dn))


def order_abandon_ship(ship: object | None = None) -> bool:
    """Set abandon ship flag. Server-side hull check (< 15% of max).

    Returns False if hull is above threshold or already abandoned.
    """
    global _abandon_ship
    if _abandon_ship:
        return False
    if ship is not None:
        hull = getattr(ship, "hull", 0.0)
        hull_max = getattr(ship, "hull_max", 120.0)
        if hull >= hull_max * ABANDON_SHIP_HULL_THRESHOLD:
            return False
    _abandon_ship = True
    logger.info("ABANDON SHIP ordered")
    return True


def set_evacuation_order(deck_order: list[int]) -> bool:
    """HC sets deck evacuation priority order."""
    global _evacuation_order
    if not _abandon_ship:
        return False
    _evacuation_order = list(deck_order)
    return True


def launch_pod(pod_id: str) -> bool:
    """Start launch countdown on a pod. Returns False if already launched or empty."""
    for pod in _life_pods:
        if pod.id == pod_id:
            if pod.launched or pod.loaded_crew <= 0:
                return False
            if pod.launch_timer > 0:
                return False  # Already launching
            pod.launch_timer = LIFE_POD_LAUNCH_TIME
            logger.info("Life pod %s launching (crew: %d)", pod_id, pod.loaded_crew)
            return True
    return False


def get_life_pods() -> list[LifePod]:
    """Return current life pod list."""
    return list(_life_pods)


def is_abandon_ship() -> bool:
    """Query abandon ship flag."""
    return _abandon_ship


# ---------------------------------------------------------------------------
# Public API — serialise / deserialise
# ---------------------------------------------------------------------------


def serialise() -> dict:
    fires_data = {}
    for rid, f in _fires.items():
        fires_data[rid] = {
            "intensity": f.intensity,
            "spread_timer": f.spread_timer,
            "escalation_timer": f.escalation_timer,
            "started_tick": f.started_tick,
            "suppression_timer": f.suppression_timer,
            "suppression_type": f.suppression_type,
            "vent_elapsed": f.vent_elapsed,
        }
    sections_data = {}
    for sid, sec in _sections.items():
        sections_data[sid] = {
            "deck_number": sec.deck_number,
            "deck_name": sec.deck_name,
            "room_ids": list(sec.room_ids),
            "integrity": sec.integrity,
            "collapsed": sec.collapsed,
        }
    # Life pods (B.6.3).
    pods_data = []
    for pod in _life_pods:
        pods_data.append({
            "id": pod.id,
            "deck_number": pod.deck_number,
            "capacity": pod.capacity,
            "loaded_crew": pod.loaded_crew,
            "launched": pod.launched,
            "launch_timer": pod.launch_timer,
            "load_accum": pod._load_accum,
        })

    return {
        "active_dcts": dict(_active_dcts),
        "pending_hull_damage": _pending_hull_damage,
        "fires": fires_data,
        "fire_teams": dict(_fire_teams),
        "vent_rooms": list(_vent_rooms),
        "deck_suppression": dict(_deck_suppression),
        "sections": sections_data,
        "reinforcement_teams": dict(_reinforcement_teams),
        "fire_structural_timers": dict(_fire_structural_timers),
        # B.6 emergency systems.
        "sealed_connections": [list(c) for c in _sealed_connections],
        "deck_batteries": {str(k): v for k, v in _deck_batteries.items()},
        "deck_power": {str(k): v for k, v in _deck_power.items()},
        "power_cut_overrides": list(_power_cut_overrides),
        "life_pods": pods_data,
        "abandon_ship": _abandon_ship,
        "evacuation_order": list(_evacuation_order),
        # C.3.1
        "fire_suppression_powered": _fire_suppression_powered,
    }


def deserialise(data: dict) -> None:
    global _pending_hull_damage, _fire_suppression_powered
    _active_dcts.clear()
    _active_dcts.update(data.get("active_dcts", {}))
    _fire_suppression_powered = data.get("fire_suppression_powered", True)
    _pending_hull_damage = data.get("pending_hull_damage", 0.0)

    _fires.clear()
    for rid, fd in data.get("fires", {}).items():
        _fires[rid] = Fire(
            room_id=rid,
            intensity=fd.get("intensity", 1),
            spread_timer=fd.get("spread_timer", 0.0),
            escalation_timer=fd.get("escalation_timer", ESCALATION_INTERVAL),
            started_tick=fd.get("started_tick", 0),
            suppression_timer=fd.get("suppression_timer", 0.0),
            suppression_type=fd.get("suppression_type", ""),
            vent_elapsed=fd.get("vent_elapsed", 0.0),
        )

    _fire_teams.clear()
    _fire_teams.update(data.get("fire_teams", {}))

    _vent_rooms.clear()
    _vent_rooms.update(data.get("vent_rooms", []))

    _deck_suppression.clear()
    _deck_suppression.update(data.get("deck_suppression", {}))

    # Structural integrity (B.5).
    _sections.clear()
    _room_to_section.clear()
    for sid, sd in data.get("sections", {}).items():
        sec = Section(
            id=sid,
            deck_number=sd.get("deck_number", 0),
            deck_name=sd.get("deck_name", ""),
            room_ids=sd.get("room_ids", []),
            integrity=sd.get("integrity", 100.0),
            collapsed=sd.get("collapsed", False),
        )
        _sections[sid] = sec
        for rid in sec.room_ids:
            _room_to_section[rid] = sid

    _reinforcement_teams.clear()
    _reinforcement_teams.update(data.get("reinforcement_teams", {}))

    _fire_structural_timers.clear()
    _fire_structural_timers.update(data.get("fire_structural_timers", {}))

    # B.6 emergency systems.
    global _abandon_ship
    _sealed_connections.clear()
    for pair in data.get("sealed_connections", []):
        if len(pair) == 2:
            _sealed_connections.add((pair[0], pair[1]))

    _deck_batteries.clear()
    for k, v in data.get("deck_batteries", {}).items():
        _deck_batteries[int(k)] = v

    _deck_power.clear()
    for k, v in data.get("deck_power", {}).items():
        _deck_power[int(k)] = v

    _power_cut_overrides.clear()
    _power_cut_overrides.update(data.get("power_cut_overrides", []))

    _life_pods.clear()
    for pd in data.get("life_pods", []):
        _life_pods.append(LifePod(
            id=pd["id"],
            deck_number=pd["deck_number"],
            capacity=pd.get("capacity", LIFE_POD_CAPACITY),
            loaded_crew=pd.get("loaded_crew", 0),
            launched=pd.get("launched", False),
            launch_timer=pd.get("launch_timer", 0.0),
            _load_accum=pd.get("load_accum", 0.0),
        ))

    _abandon_ship = data.get("abandon_ship", False)
    _evacuation_order.clear()
    _evacuation_order.extend(data.get("evacuation_order", []))


# ---------------------------------------------------------------------------
# Public API — fire management
# ---------------------------------------------------------------------------


def start_fire(room_id: str, intensity: int, interior: ShipInterior,
               tick: int = 0) -> bool:
    """Create or escalate a fire in the given room.

    If the room already has a fire, the intensity is set to the max of existing
    and new.  Returns True if a fire is now active.
    """
    room = interior.rooms.get(room_id)
    if room is None or room.state == "decompressed":
        return False

    intensity = max(1, min(5, intensity))

    if room_id in _fires:
        existing = _fires[room_id]
        existing.intensity = max(existing.intensity, intensity)
        existing.intensity = min(5, existing.intensity)
        # Reset escalation timer when intensity changes.
        existing.escalation_timer = ESCALATION_INTERVAL
        logger.debug("Fire escalated: %s → intensity %d", room_id, existing.intensity)
    else:
        _fires[room_id] = Fire(
            room_id=room_id,
            intensity=intensity,
            spread_timer=SPREAD_TIMERS.get(intensity, 60.0),
            escalation_timer=ESCALATION_INTERVAL,
            started_tick=tick,
        )
        room.state = "fire"
        logger.debug("Fire started: %s at intensity %d", room_id, intensity)

    return True


def get_fires() -> dict[str, Fire]:
    """Return the current fires dict (read-only intent)."""
    return _fires


def get_fire_crew_penalty(deck: str) -> float:
    """Return the worst crew effectiveness penalty for fires on this deck.

    Returns 0.0 if no fires on the deck, up to 1.0 (deck unusable).
    """
    worst = 0.0
    for fire in _fires.values():
        # We need the room's deck — but Fire only has room_id.
        # Callers should pass the interior to look this up.  For efficiency,
        # we store nothing extra; this is called via get_fire_penalties().
        pass
    return worst


def get_fire_penalties(interior: ShipInterior) -> dict[str, float]:
    """Return deck → worst crew penalty dict for all active fires."""
    penalties: dict[str, float] = {}
    for fire in _fires.values():
        room = interior.rooms.get(fire.room_id)
        if room is None:
            continue
        penalty = CREW_EFF_PENALTY.get(fire.intensity, 0.0)
        if penalty > penalties.get(room.deck, 0.0):
            penalties[room.deck] = penalty
    return penalties


def get_smoke_rooms() -> set[str]:
    """Return set of room IDs with fires at intensity 2+ (smoke/obscured)."""
    return {rid for rid, f in _fires.items() if f.intensity >= 2}


# ---------------------------------------------------------------------------
# Public API — B.2.3.3 crew fire evacuation
# ---------------------------------------------------------------------------


def init_room_crew_counts(interior: ShipInterior) -> None:
    """Initialize per-room crew counts from interior layout.

    System rooms (housing ship systems) get 3 crew; other rooms get 1.
    """
    _room_crew_counts.clear()
    _evacuated_rooms.clear()
    system_room_ids = set(interior.system_rooms.values()) if interior.system_rooms else set()
    for room_id in interior.rooms:
        _room_crew_counts[room_id] = 3 if room_id in system_room_ids else 1


def get_room_crew_counts() -> dict[str, int]:
    """Return the current per-room crew counts (read-only intent)."""
    return _room_crew_counts


def get_evacuated_rooms() -> set[str]:
    """Return the set of rooms currently marked as evacuated."""
    return _evacuated_rooms


def tick_crew_fire_evacuation(interior: ShipInterior) -> list[dict]:
    """Auto-move crew from rooms with fire intensity 3+.

    Crew relocate to the adjacent safe room with the lowest crew count.
    If no safe adjacent room exists, crew shelter in place.
    Returns evacuation event dicts for broadcasting.
    """
    events: list[dict] = []

    for room_id, fire in list(_fires.items()):
        if fire.intensity < 3:
            continue
        if room_id in _evacuated_rooms:
            continue

        crew_count = _room_crew_counts.get(room_id, 0)
        if crew_count <= 0:
            _evacuated_rooms.add(room_id)
            continue

        room = interior.rooms.get(room_id)
        if room is None:
            continue

        # Find adjacent safe room with lowest crew count.
        best_target: str | None = None
        best_count = float("inf")
        for adj_id in room.connections:
            adj = interior.rooms.get(adj_id)
            if adj is None:
                continue
            if adj.state == "decompressed":
                continue
            if adj_id in _fires and _fires[adj_id].intensity >= 3:
                continue
            adj_count = _room_crew_counts.get(adj_id, 0)
            if adj_count < best_count:
                best_count = adj_count
                best_target = adj_id

        if best_target is not None:
            _room_crew_counts[best_target] = _room_crew_counts.get(best_target, 0) + crew_count
            _room_crew_counts[room_id] = 0
            _evacuated_rooms.add(room_id)
            events.append({
                "type": "crew_evacuated",
                "room_id": room_id,
                "target_room": best_target,
                "crew_count": crew_count,
            })
        else:
            # No safe adjacent rooms — shelter in place.
            _evacuated_rooms.add(room_id)
            events.append({
                "type": "crew_sheltering",
                "room_id": room_id,
                "crew_count": crew_count,
            })

    # Clear evacuated flag for rooms where fire dropped below 3.
    for room_id in list(_evacuated_rooms):
        if room_id not in _fires or _fires[room_id].intensity < 3:
            _evacuated_rooms.discard(room_id)

    return events


# ---------------------------------------------------------------------------
# Public API — DCT dispatch (unchanged interface)
# ---------------------------------------------------------------------------


def apply_hull_damage(amount: float, interior: ShipInterior) -> None:
    """Accumulate hull damage and trigger room events when threshold is reached."""
    global _pending_hull_damage
    if amount <= 0.0:
        return
    _pending_hull_damage += amount
    while _pending_hull_damage >= HULL_DAMAGE_THRESHOLD:
        _pending_hull_damage -= HULL_DAMAGE_THRESHOLD
        _trigger_room_event(interior)


def dispatch_dct(room_id: str, interior: ShipInterior) -> bool:
    """Dispatch a DCT to repair the specified room."""
    room = interior.rooms.get(room_id)
    if room is None or room.state in ("normal", "decompressed"):
        return False
    if room_id not in _active_dcts:
        _active_dcts[room_id] = 0.0
    return True


def cancel_dct(room_id: str) -> bool:
    """Cancel an active DCT."""
    if room_id in _active_dcts:
        del _active_dcts[room_id]
        return True
    return False


# ---------------------------------------------------------------------------
# Public API — fire suppression power gate (C.3.1)
# ---------------------------------------------------------------------------


def is_fire_suppression_powered() -> bool:
    """Return whether fire suppression systems have enough power."""
    return _fire_suppression_powered


def update_fire_suppression_power(ship) -> None:
    """Compute avg system efficiency; set _fire_suppression_powered flag."""
    global _fire_suppression_powered
    systems = getattr(ship, "systems", None)
    if not systems:
        _fire_suppression_powered = True
        return
    efficiencies = [sys.efficiency for sys in systems.values()]
    if not efficiencies:
        _fire_suppression_powered = True
        return
    avg_eff = sum(efficiencies) / len(efficiencies)
    _fire_suppression_powered = avg_eff >= FIRE_SUPPRESSION_MIN_EFFICIENCY


# ---------------------------------------------------------------------------
# Public API — vent conflict detection (C.3.4)
# ---------------------------------------------------------------------------


def check_vent_conflict(room_id: str, interior) -> list[str]:
    """Return engineering repair team IDs on the same deck as *room_id*."""
    import server.game_loop_engineering as _gle
    room = interior.rooms.get(room_id) if interior else None
    if room is None:
        return []
    return _gle.get_teams_on_deck(room.deck, interior)


# ---------------------------------------------------------------------------
# Public API — suppression commands
# ---------------------------------------------------------------------------


def suppress_local(room_id: str, resources: object | None = None) -> bool:
    """Start localised suppression on a fire.  Costs 1 suppressant, takes 5s.

    Returns False if no fire, no suppressant available, or no power (C.3.1).
    """
    if not _fire_suppression_powered:
        return False
    if room_id not in _fires:
        return False

    # Check suppressant.
    if resources is not None:
        avail = getattr(resources, "suppressant", 0.0)
        if avail < LOCAL_SUPPRESS_COST:
            return False
        if hasattr(resources, "consume"):
            resources.consume("suppressant", LOCAL_SUPPRESS_COST)
        # C.12: Track consumption for QM.
        glrat.record_consumption("suppressant", LOCAL_SUPPRESS_COST, 0.0)
        _resource_consumption["suppressant"] = _resource_consumption.get("suppressant", 0.0) + LOCAL_SUPPRESS_COST

    fire = _fires[room_id]
    fire.suppression_timer = LOCAL_SUPPRESS_TIME
    fire.suppression_type = "local"
    logger.debug("Local suppression started: %s", room_id)
    return True


def suppress_deck(deck_name: str, interior: ShipInterior,
                  resources: object | None = None) -> bool:
    """Start deck-wide suppression.  Costs 3 suppressant, takes 15s.

    Returns False if no fires on deck, no suppressant, or no power (C.3.1).
    """
    if not _fire_suppression_powered:
        return False
    # Check if any fires on this deck.
    has_fire = False
    for fire in _fires.values():
        room = interior.rooms.get(fire.room_id)
        if room and room.deck == deck_name:
            has_fire = True
            break
    if not has_fire:
        return False

    # Check suppressant.
    if resources is not None:
        avail = getattr(resources, "suppressant", 0.0)
        if avail < DECK_SUPPRESS_COST:
            return False
        if hasattr(resources, "consume"):
            resources.consume("suppressant", DECK_SUPPRESS_COST)
        # C.12: Track consumption for QM.
        glrat.record_consumption("suppressant", DECK_SUPPRESS_COST, 0.0)
        _resource_consumption["suppressant"] = _resource_consumption.get("suppressant", 0.0) + DECK_SUPPRESS_COST

    _deck_suppression[deck_name] = DECK_SUPPRESS_TIME
    logger.debug("Deck-wide suppression started: %s", deck_name)
    return True


def vent_room(room_id: str, interior: ShipInterior) -> bool:
    """Start ventilation cutoff on a room.  Free but crew take O2 damage."""
    if room_id not in _fires:
        return False
    room = interior.rooms.get(room_id)
    if room is None:
        return False
    _vent_rooms.add(room_id)
    # Reset vent elapsed on the fire for O2 damage tracking.
    _fires[room_id].vent_elapsed = 0.0
    logger.debug("Ventilation cutoff started: %s", room_id)
    return True


def cancel_vent(room_id: str) -> bool:
    """Cancel ventilation cutoff on a room."""
    if room_id in _vent_rooms:
        _vent_rooms.discard(room_id)
        return True
    return False


def dispatch_fire_team(room_id: str, interior: ShipInterior) -> bool:
    """Dispatch a manual fire team to fight a fire.  Free but crew injury risk."""
    if room_id not in _fires:
        return False
    room = interior.rooms.get(room_id)
    if room is None:
        return False
    if room_id not in _fire_teams:
        _fire_teams[room_id] = 0.0
    logger.debug("Manual fire team dispatched: %s", room_id)
    return True


def cancel_fire_team(room_id: str) -> bool:
    """Recall a manual fire team."""
    if room_id in _fire_teams:
        del _fire_teams[room_id]
        return True
    return False


# ---------------------------------------------------------------------------
# Public API — C.12 QM resource consumption
# ---------------------------------------------------------------------------


def dispatch_decon_team(room_id: str, resources: object | None = None) -> bool:
    """Dispatch a decontamination team.  Costs DECON_SUPPLY_COST medical_supplies.

    Returns False if insufficient supplies.
    """
    if resources is not None:
        avail = getattr(resources, "medical_supplies", 0.0)
        if avail < DECON_SUPPLY_COST:
            return False
        if hasattr(resources, "consume"):
            resources.consume("medical_supplies", DECON_SUPPLY_COST)
        glrat.record_consumption("medical_supplies", DECON_SUPPLY_COST, 0.0)
        _resource_consumption["medical_supplies"] = (
            _resource_consumption.get("medical_supplies", 0.0) + DECON_SUPPLY_COST
        )
    return True


def request_suppressant(quantity: float, reason: str, tick: int,
                        ship: object | None = None) -> dict:
    """Request suppressant via QM allocation system."""
    return glrat.submit_request("hazard_control", "suppressant", quantity, reason,
                                tick, ship=ship)


def get_resource_consumption_summary() -> dict:
    """Return cumulative resource consumption by type."""
    return dict(_resource_consumption)


# ---------------------------------------------------------------------------
# Public API — C.7 Medical injury predictions + evacuation warnings
# ---------------------------------------------------------------------------


def get_hazard_injury_predictions(interior: ShipInterior) -> list[dict]:
    """Predict injuries from active hazards for Medical station.

    Checks fire intensity (≥3 → burns/smoke), atmosphere radiation (≥0.3 →
    radiation sickness), and chemical contamination (≥0.2 → poisoning).
    """
    import server.game_loop_atmosphere as glatm

    predictions: list[dict] = []
    # Fire hazards.
    for room_id, fire in _fires.items():
        if fire.intensity >= 3:
            room = interior.rooms.get(room_id)
            deck = room.deck if room else "unknown"
            predictions.append({
                "deck": deck,
                "room_id": room_id,
                "hazard_type": "fire",
                "injury_types": ["burns", "smoke_inhalation"],
                "severity": fire.intensity,
            })
    # Atmosphere hazards.
    atm_all = glatm.get_all_atmosphere()
    for room_id, atm in atm_all.items():
        room = interior.rooms.get(room_id)
        deck = room.deck if room else "unknown"
        if atm.radiation >= 0.3:
            predictions.append({
                "deck": deck,
                "room_id": room_id,
                "hazard_type": "radiation",
                "injury_types": ["radiation_sickness"],
                "severity": round(atm.radiation, 2),
            })
        if atm.chemical >= 0.2:
            predictions.append({
                "deck": deck,
                "room_id": room_id,
                "hazard_type": "contamination",
                "injury_types": ["poisoning"],
                "severity": round(atm.chemical, 2),
            })
    return predictions


def queue_evacuation_warning(deck: str, estimated_casualties: int) -> None:
    """Queue an evacuation warning for Medical station."""
    _pending_evac_warnings.append({
        "deck": deck,
        "estimated_casualties": estimated_casualties,
    })


def pop_evacuation_warnings() -> list[dict]:
    """Drain and return pending evacuation warnings."""
    warnings = list(_pending_evac_warnings)
    _pending_evac_warnings.clear()
    return warnings


# ---------------------------------------------------------------------------
# Public API — tick
# ---------------------------------------------------------------------------


def tick(interior: ShipInterior, dt: float, difficulty: object | None = None,
         resources: object | None = None, ship: object | None = None) -> list[dict]:
    """Advance fire model and DCT repairs for one simulation tick.

    Returns a list of event dicts for the game loop to broadcast.
    """
    events: list[dict] = []

    # 0. B.2.3.3: Crew auto-evacuation from intensity 3+ rooms.
    events.extend(tick_crew_fire_evacuation(interior))

    # 1. Fire escalation.
    _tick_fire_escalation(dt)

    # 2. Fire spread.
    _tick_fire_spread_intensity(interior, dt)

    # 3. Suppression progress (localised).
    _tick_local_suppression(interior, dt, events)

    # 4. Deck-wide suppression cooldowns.
    _tick_deck_suppression(interior, dt, events)

    # 5. Ventilation cutoff.
    _tick_vent_rooms(interior, dt, events)

    # 6. Manual fire teams.
    _tick_fire_teams(interior, dt, events)

    # 7. Cross-station effects: equipment damage, crew damage.
    _tick_fire_effects(interior, dt, ship)

    # 8. Flight deck fire check.
    _tick_flight_deck_fire(interior, ship)

    # 9. DCT repairs (existing system).
    _tick_dct_repairs(interior, dt, difficulty, resources)

    # 10. Clean up extinguished fires.
    _cleanup_fires(interior)

    # 11. Structural: fire damage to sections (intensity 4+).
    _tick_structural_fire_damage(interior, dt)

    # 12. Structural reinforcement.
    _tick_reinforcement_teams(dt, ship, events)

    # 13. Emergency power (B.6.2).
    _tick_emergency_power(dt, ship, interior, events)

    # 14. Life pods (B.6.3).
    _tick_life_pods(dt, ship, events)

    return events


def build_dc_state(interior: ShipInterior, difficulty: object | None = None,
                   ship=None) -> dict:
    """Serialise current state for broadcasting to Hazard Control / Engineering."""
    repair_mult = getattr(difficulty, "repair_speed_multiplier", 1.0) if difficulty else 1.0
    effective_repair_dur = DCT_REPAIR_DURATION / max(0.1, repair_mult)

    damaged_rooms = {
        room_id: {
            "name": room.name,
            "state": room.state,
            "deck": room.deck,
        }
        for room_id, room in interior.rooms.items()
        if room.state != "normal"
    }

    active_dcts = {
        room_id: round(min(elapsed / effective_repair_dur, 1.0), 2)
        for room_id, elapsed in _active_dcts.items()
    }

    # Fire data.
    fires_state = {}
    for rid, f in _fires.items():
        fires_state[rid] = {
            "intensity": f.intensity,
            "spread_timer": round(f.spread_timer, 1),
            "escalation_timer": round(f.escalation_timer, 1),
            "suppression_type": f.suppression_type,
            "suppression_timer": round(f.suppression_timer, 1),
            "venting": rid in _vent_rooms,
        }

    # Structural sections (B.5).
    sections_state = {}
    for sid, sec in _sections.items():
        sections_state[sid] = {
            "integrity": round(sec.integrity, 1),
            "state": get_section_state(sec),
            "room_ids": list(sec.room_ids),
            "deck_number": sec.deck_number,
            "collapsed": sec.collapsed,
            "reinforcing": sid in _reinforcement_teams,
        }

    return {
        "rooms": damaged_rooms,
        "active_dcts": active_dcts,
        "fires": fires_state,
        "fire_teams": {rid: round(elapsed, 1) for rid, elapsed in _fire_teams.items()},
        "vent_rooms": list(_vent_rooms),
        "deck_suppression": {dk: round(t, 1) for dk, t in _deck_suppression.items()},
        "sections": sections_state,
        # B.6 emergency systems.
        "sealed_connections": [list(c) for c in _sealed_connections],
        "deck_power": {str(k): v for k, v in _deck_power.items()},
        "deck_batteries": {str(k): round(v, 1) for k, v in _deck_batteries.items()},
        "life_pods": [
            {"id": p.id, "deck_number": p.deck_number, "capacity": p.capacity,
             "loaded_crew": p.loaded_crew, "launched": p.launched,
             "launching": p.launch_timer > 0}
            for p in _life_pods
        ],
        "abandon_ship": _abandon_ship,
        "evacuation_order": list(_evacuation_order),
        # C.3.1: Fire suppression power gate.
        "fire_suppression_powered": _fire_suppression_powered,
        # C.3.3: Life support power display.
        "life_support_efficiency": round(_get_ls_efficiency(ship), 3) if ship else None,
        # C.3.4: Engineering teams at risk from venting.
        "engineering_teams_at_risk": _get_engineering_teams_at_risk(interior),
        # B.2.3.3: Room crew counts and evacuated rooms.
        "room_crew_counts": dict(_room_crew_counts),
        "evacuated_rooms": sorted(_evacuated_rooms),
    }


def _get_ls_efficiency(ship) -> float:
    """Life support efficiency = average system efficiency."""
    systems = getattr(ship, "systems", None)
    if not systems:
        return 1.0
    efficiencies = [sys.efficiency for sys in systems.values()]
    return sum(efficiencies) / len(efficiencies) if efficiencies else 1.0


def _get_engineering_teams_at_risk(interior) -> dict[str, list[str]]:
    """Return {deck_name: [team_ids]} for repair teams on decks with active vents."""
    import server.game_loop_engineering as _gle
    result: dict[str, list[str]] = {}
    # Only care about decks that have active venting or space venting.
    vent_decks: set[str] = set()
    for rid in _vent_rooms:
        room = interior.rooms.get(rid)
        if room:
            vent_decks.add(room.deck)
    if not vent_decks:
        return result
    for deck_name in vent_decks:
        team_ids = _gle.get_teams_on_deck(deck_name, interior)
        if team_ids:
            result[deck_name] = team_ids
    return result


# ---------------------------------------------------------------------------
# Internal — fire escalation
# ---------------------------------------------------------------------------


def _tick_fire_escalation(dt: float) -> None:
    """Unsuppressed fires escalate +1 intensity every ESCALATION_INTERVAL."""
    for fire in list(_fires.values()):
        if fire.intensity >= 5:
            continue
        # Only escalate if not currently being suppressed.
        if fire.suppression_timer > 0 or fire.room_id in _vent_rooms or fire.room_id in _fire_teams:
            continue
        fire.escalation_timer -= dt
        if fire.escalation_timer <= 0.0:
            fire.intensity = min(5, fire.intensity + 1)
            fire.escalation_timer = ESCALATION_INTERVAL
            fire.spread_timer = SPREAD_TIMERS.get(fire.intensity, 60.0)
            logger.debug("Fire escalated: %s → intensity %d", fire.room_id, fire.intensity)


# ---------------------------------------------------------------------------
# Internal — fire spread (intensity-based)
# ---------------------------------------------------------------------------


def _tick_fire_spread_intensity(interior: ShipInterior, dt: float) -> None:
    """Each fire ticks its spread timer; on expiry, spreads to adjacent room."""
    for fire in list(_fires.values()):
        fire.spread_timer -= dt
        if fire.spread_timer <= 0.0:
            fire.spread_timer = SPREAD_TIMERS.get(fire.intensity, 60.0)
            _spread_fire_from_intensity(fire, interior)


def _spread_fire_from_intensity(source: Fire, interior: ShipInterior) -> None:
    """Spread fire from source to a random adjacent non-fire non-decompressed room."""
    room = interior.rooms.get(source.room_id)
    if room is None:
        return
    candidates = [
        interior.rooms[rid]
        for rid in room.connections
        if rid in interior.rooms
        and rid not in _fires
        and interior.rooms[rid].state != "decompressed"
        and not is_connection_sealed(source.room_id, rid)
    ]
    if not candidates:
        return
    target = _rng.choice(candidates)
    cascade_intensity = max(1, source.intensity - 1)
    start_fire(target.id, cascade_intensity, interior)
    logger.debug("Fire spread: %s (int %d) → %s (int %d)",
                 source.room_id, source.intensity, target.id, cascade_intensity)


# ---------------------------------------------------------------------------
# Internal — suppression tick helpers
# ---------------------------------------------------------------------------


def _tick_local_suppression(interior: ShipInterior, dt: float,
                            events: list[dict]) -> None:
    """Progress localised suppression timers."""
    for fire in list(_fires.values()):
        if fire.suppression_type != "local" or fire.suppression_timer <= 0:
            continue
        fire.suppression_timer -= dt
        if fire.suppression_timer <= 0.0:
            fire.intensity -= LOCAL_SUPPRESS_REDUCTION
            fire.suppression_type = ""
            fire.suppression_timer = 0.0
            # Reset escalation timer on suppression.
            fire.escalation_timer = ESCALATION_INTERVAL
            if fire.intensity <= 0:
                events.append({"type": "fire_extinguished", "room_id": fire.room_id})
            else:
                fire.spread_timer = SPREAD_TIMERS.get(fire.intensity, 60.0)
            logger.debug("Local suppression complete: %s → intensity %d",
                         fire.room_id, fire.intensity)


def _tick_deck_suppression(interior: ShipInterior, dt: float,
                           events: list[dict]) -> None:
    """Progress deck-wide suppression cooldowns."""
    completed_decks: list[str] = []
    for deck_name in list(_deck_suppression):
        _deck_suppression[deck_name] -= dt
        if _deck_suppression[deck_name] <= 0.0:
            completed_decks.append(deck_name)

    for deck_name in completed_decks:
        del _deck_suppression[deck_name]
        # Apply -1 intensity to all fires on this deck.
        for fire in list(_fires.values()):
            room = interior.rooms.get(fire.room_id)
            if room and room.deck == deck_name:
                fire.intensity -= DECK_SUPPRESS_REDUCTION
                fire.escalation_timer = ESCALATION_INTERVAL
                if fire.intensity <= 0:
                    events.append({"type": "fire_extinguished", "room_id": fire.room_id})
                else:
                    fire.spread_timer = SPREAD_TIMERS.get(fire.intensity, 60.0)
                logger.debug("Deck suppression applied: %s → intensity %d",
                             fire.room_id, fire.intensity)


def _tick_vent_rooms(interior: ShipInterior, dt: float,
                     events: list[dict]) -> None:
    """Ventilation cutoff: fire loses 1 intensity every VENT_REDUCTION_INTERVAL."""
    for room_id in list(_vent_rooms):
        fire = _fires.get(room_id)
        if fire is None:
            _vent_rooms.discard(room_id)
            continue

        fire.vent_elapsed += dt

        # Reduction every VENT_REDUCTION_INTERVAL seconds since venting started.
        intervals = int(fire.vent_elapsed / VENT_REDUCTION_INTERVAL)
        # We track progress by reducing intensity based on total intervals elapsed.
        # To avoid double-counting, we reduce once per interval boundary crossing.
        target_reductions = intervals
        # Intensity at start of venting = original intensity.
        # We use a simpler approach: reduce by 1 each interval tick.
        # Check if we just crossed an interval boundary.
        prev_intervals = int((fire.vent_elapsed - dt) / VENT_REDUCTION_INTERVAL)
        if intervals > prev_intervals:
            fire.intensity -= 1
            fire.escalation_timer = ESCALATION_INTERVAL
            if fire.intensity <= 0:
                events.append({"type": "fire_extinguished", "room_id": room_id})
                _vent_rooms.discard(room_id)
            else:
                fire.spread_timer = SPREAD_TIMERS.get(fire.intensity, 60.0)
            logger.debug("Vent reduction: %s → intensity %d", room_id, fire.intensity)


def _tick_fire_teams(interior: ShipInterior, dt: float,
                     events: list[dict]) -> None:
    """Manual fire teams: reduce intensity by 1 every MANUAL_TEAM_INTERVAL."""
    completed: list[str] = []
    for room_id in list(_fire_teams):
        fire = _fires.get(room_id)
        if fire is None:
            completed.append(room_id)
            continue

        _fire_teams[room_id] += dt
        prev_intervals = int((_fire_teams[room_id] - dt) / MANUAL_TEAM_INTERVAL)
        cur_intervals = int(_fire_teams[room_id] / MANUAL_TEAM_INTERVAL)

        if cur_intervals > prev_intervals:
            fire.intensity -= 1
            fire.escalation_timer = ESCALATION_INTERVAL

            # Injury risk for the fire team.
            if _rng.random() < MANUAL_TEAM_INJURY_CHANCE:
                events.append({"type": "fire_team_injury", "room_id": room_id})

            if fire.intensity <= 0:
                events.append({"type": "fire_extinguished", "room_id": room_id})
                completed.append(room_id)
            else:
                fire.spread_timer = SPREAD_TIMERS.get(fire.intensity, 60.0)
            logger.debug("Fire team reduction: %s → intensity %d",
                         room_id, fire.intensity)

    for room_id in completed:
        _fire_teams.pop(room_id, None)


# ---------------------------------------------------------------------------
# Internal — cross-station fire effects
# ---------------------------------------------------------------------------


def _tick_fire_effects(interior: ShipInterior, dt: float,
                       ship: object | None) -> None:
    """Apply crew HP damage and equipment damage from active fires."""
    if ship is None:
        return

    for fire in list(_fires.values()):
        room = interior.rooms.get(fire.room_id)
        if room is None:
            continue

        # Equipment damage at intensity 4+.
        dmg_rate = EQUIP_DAMAGE_PER_SEC.get(fire.intensity)
        if dmg_rate and hasattr(ship, "systems"):
            _apply_equipment_damage(room, dmg_rate * dt, ship)

        # Adjacent heat damage at intensity 5.
        if fire.intensity >= 5:
            for adj_id in room.connections:
                adj_room = interior.rooms.get(adj_id)
                if adj_room and adj_room.state != "decompressed":
                    _apply_equipment_damage(adj_room, ADJACENT_HEAT_DAMAGE_PER_SEC * dt, ship)

    # Crew O2 damage from vented rooms.
    for room_id in _vent_rooms:
        fire = _fires.get(room_id)
        if fire and fire.vent_elapsed > VENT_O2_DAMAGE_DELAY:
            pass  # O2 damage handled by atmosphere system (B.3)


def _apply_equipment_damage(room: Room, damage_pct: float,
                            ship: object) -> None:
    """Reduce health of the ship system housed in this room, if any."""
    systems = getattr(ship, "systems", {})
    for sys_name, sys_obj in systems.items():
        # Check if this system's room matches.
        sys_room = getattr(sys_obj, "room_id", None)
        if sys_room == room.id:
            old_health = getattr(sys_obj, "health", 100.0)
            new_health = max(0.0, old_health - damage_pct)
            sys_obj.health = new_health


def _tick_flight_deck_fire(interior: ShipInterior, ship: object | None) -> None:
    """Set flight deck fire flag based on whether any flight deck room is on fire."""
    if ship is None:
        return
    flight_deck = getattr(ship, "flight_deck", None)
    if flight_deck is None or not hasattr(flight_deck, "set_fire"):
        return

    # Check if any room tagged "flight_deck" or named with "flight" has a fire.
    has_flight_fire = False
    for fire in _fires.values():
        room = interior.rooms.get(fire.room_id)
        if room and ("flight_deck" in room.tags or "flight" in room.name.lower()):
            has_flight_fire = True
            break
    flight_deck.set_fire(has_flight_fire)


# ---------------------------------------------------------------------------
# Internal — DCT repairs
# ---------------------------------------------------------------------------


def _tick_dct_repairs(interior: ShipInterior, dt: float,
                      difficulty: object | None, resources: object | None) -> None:
    """Advance DCT repairs.  DCTs on fire rooms reduce intensity instead."""
    repair_mult = getattr(difficulty, "repair_speed_multiplier", 1.0) if difficulty else 1.0
    effective_repair_dur = DCT_REPAIR_DURATION / max(0.1, repair_mult)
    _rm_eff = glrat.get_effectiveness_multiplier("repair_materials")
    effective_repair_dur /= max(0.1, _rm_eff)

    completed: list[str] = []
    for room_id in list(_active_dcts):
        elapsed = _active_dcts[room_id] + dt
        room = interior.rooms.get(room_id)

        if room is None or room.state == "normal":
            completed.append(room_id)
            continue

        if elapsed >= effective_repair_dur:
            # If room has an active fire, DCT reduces intensity by 1.
            if room_id in _fires:
                fire = _fires[room_id]
                fire.intensity -= 1
                fire.escalation_timer = ESCALATION_INTERVAL
                logger.debug("DCT fire reduction: %s → intensity %d", room_id, fire.intensity)
                _active_dcts[room_id] = 0.0
                continue

            # Normal room.state repair.
            old_sev = _SEVERITY.get(room.state, 0)
            if old_sev == 2:
                rmu_cost = 2
            elif old_sev == 1:
                rmu_cost = 5
            elif old_sev == 3:
                rmu_cost = 10
            else:
                rmu_cost = 0

            if resources is not None and rmu_cost > 0:
                available = getattr(resources, "repair_materials", float("inf"))
                if old_sev == 1 and available < rmu_cost:
                    _active_dcts[room_id] = effective_repair_dur
                    continue
                if hasattr(resources, "consume"):
                    resources.consume("repair_materials", rmu_cost)
                    glrat.record_consumption("repair_materials", rmu_cost, 0.0)

            new_state = _SEVERITY_DOWN.get(_SEVERITY.get(room.state, 0), "normal")
            room.state = new_state
            logger.debug("DCT repair: %s → %s", room_id, new_state)
            if room.state == "normal":
                completed.append(room_id)
            else:
                _active_dcts[room_id] = 0.0
        else:
            _active_dcts[room_id] = elapsed

    for room_id in completed:
        _active_dcts.pop(room_id, None)


# ---------------------------------------------------------------------------
# Internal — fire cleanup
# ---------------------------------------------------------------------------


def _cleanup_fires(interior: ShipInterior) -> None:
    """Remove fires that have been reduced to intensity 0 or below."""
    to_remove: list[str] = []
    for rid, fire in _fires.items():
        if fire.intensity <= 0:
            to_remove.append(rid)
    for rid in to_remove:
        del _fires[rid]
        _fire_teams.pop(rid, None)
        _vent_rooms.discard(rid)
        # Set room to "damaged" after fire is extinguished (not "normal").
        room = interior.rooms.get(rid)
        if room and room.state == "fire":
            room.state = "damaged"
            logger.debug("Fire extinguished: %s → damaged", rid)


# ---------------------------------------------------------------------------
# Internal — room events (legacy + new fire model)
# ---------------------------------------------------------------------------


def _trigger_room_event(interior: ShipInterior) -> None:
    """Pick a random non-decompressed room and trigger damage/fire."""
    eligible = [r for r in interior.rooms.values() if r.state != "decompressed"]
    if not eligible:
        return
    room = _rng.choice(eligible)

    if room.state == "normal":
        if _rng.random() < FIRE_CHANCE:
            start_fire(room.id, COMBAT_FIRE_INTENSITY, interior)
        else:
            room.state = "damaged"
            logger.debug("Room event (from normal): %s → damaged", room.id)
    elif room.state == "damaged":
        if _rng.random() < 0.5:
            start_fire(room.id, COMBAT_FIRE_INTENSITY, interior)
    elif room.state == "fire":
        # Already on fire — escalate or spread.
        if room.id in _fires:
            fire = _fires[room.id]
            if fire.intensity < 5:
                fire.intensity += 1
                fire.escalation_timer = ESCALATION_INTERVAL
            else:
                _spread_fire_from_intensity(fire, interior)


# ---------------------------------------------------------------------------
# Internal — structural integrity tick helpers (B.5)
# ---------------------------------------------------------------------------


def _tick_structural_fire_damage(interior: ShipInterior, dt: float) -> None:
    """Fire at intensity 4+ damages the containing section: -2% per 30s."""
    for fire in _fires.values():
        if fire.intensity < 4:
            continue
        sec = get_section_for_room(fire.room_id)
        if sec is None or sec.collapsed:
            continue
        timer = _fire_structural_timers.get(sec.id, 0.0) + dt
        if timer >= STRUCT_FIRE_DMG_INTERVAL:
            timer -= STRUCT_FIRE_DMG_INTERVAL
            _apply_section_damage(sec, STRUCT_FIRE_DMG_AMOUNT, interior)
        _fire_structural_timers[sec.id] = timer


def _tick_reinforcement_teams(
    dt: float, ship: object | None, events: list[dict],
) -> None:
    """Advance reinforcement timers.  Every 30s, +10% capped at 80%."""
    completed: list[str] = []
    for section_id in list(_reinforcement_teams):
        sec = _sections.get(section_id)
        if sec is None or sec.collapsed:
            completed.append(section_id)
            continue

        _reinforcement_teams[section_id] += dt
        prev_intervals = int((_reinforcement_teams[section_id] - dt) / REINFORCE_INTERVAL)
        cur_intervals = int(_reinforcement_teams[section_id] / REINFORCE_INTERVAL)

        if cur_intervals > prev_intervals:
            # Check crew still available.
            crew_ok = True
            if ship is not None:
                crew = getattr(ship, "crew", None)
                if crew is not None:
                    deck = crew.decks.get(sec.deck_name)
                    if deck is None or deck.active < REINFORCE_MIN_CREW:
                        crew_ok = False

            if not crew_ok:
                completed.append(section_id)
                events.append({
                    "type": "reinforcement_cancelled",
                    "section_id": section_id,
                    "reason": "insufficient_crew",
                })
                continue

            sec.integrity = min(REINFORCE_MAX, sec.integrity + REINFORCE_AMOUNT)
            events.append({
                "type": "reinforcement_cycle",
                "section_id": section_id,
                "integrity": round(sec.integrity, 1),
            })
            logger.debug("Reinforcement cycle: %s → %.1f%%", section_id, sec.integrity)

            # Stop if at max.
            if sec.integrity >= REINFORCE_MAX:
                completed.append(section_id)

    for section_id in completed:
        _reinforcement_teams.pop(section_id, None)


# ---------------------------------------------------------------------------
# Internal — emergency power tick (B.6.2)
# ---------------------------------------------------------------------------


def _tick_emergency_power(
    dt: float, ship: object | None, interior: ShipInterior,
    events: list[dict],
) -> None:
    """Update deck power states and drain emergency batteries."""
    if not _deck_power:
        return

    # Determine which decks should lose main power.
    engines_down = False
    if ship is not None:
        systems = getattr(ship, "systems", {})
        engines_sys = systems.get("engines")
        if engines_sys is not None:
            engines_down = getattr(engines_sys, "health", 100.0) <= 0.0

    for dn in list(_deck_power):
        # Check if any section on this deck is collapsed.
        deck_collapsed = any(
            s.collapsed for s in _sections.values() if s.deck_number == dn
        )

        needs_emergency = (
            engines_down or deck_collapsed or dn in _power_cut_overrides
        )

        old_state = _deck_power[dn]

        if not needs_emergency:
            if old_state != "main":
                _deck_power[dn] = "main"
                if old_state != "main":
                    events.append({"type": "power_restored", "deck_number": dn})
            continue

        # Deck needs emergency/no power.
        battery = _deck_batteries.get(dn, 0.0)
        if battery > 0:
            _deck_batteries[dn] = max(0.0, battery - dt)
            if old_state != "emergency":
                _deck_power[dn] = "emergency"
                events.append({"type": "power_emergency", "deck_number": dn,
                               "battery": round(_deck_batteries[dn], 1)})
            # Battery just ran out this tick?
            if _deck_batteries[dn] <= 0:
                _deck_power[dn] = "none"
                events.append({"type": "power_none", "deck_number": dn})
        else:
            if old_state != "none":
                _deck_power[dn] = "none"
                events.append({"type": "power_none", "deck_number": dn})

            # No power: crew take slow injury.
            if ship is not None:
                crew = getattr(ship, "crew", None)
                if crew is not None:
                    # Find deck_name for this deck_number.
                    for sec in _sections.values():
                        if sec.deck_number == dn:
                            deck_crew = crew.decks.get(sec.deck_name)
                            if deck_crew is not None and deck_crew.active > 0:
                                # Slow injury: ~0.5 HP/30s = 0.017 HP/s.
                                # Model as fractional casualty accumulation.
                                injury_amount = NO_POWER_CREW_DAMAGE * dt
                                if injury_amount >= 1.0:
                                    crew.apply_casualties(sec.deck_name, int(injury_amount))
                            break


# ---------------------------------------------------------------------------
# Internal — life pod tick (B.6.3)
# ---------------------------------------------------------------------------


def _tick_life_pods(
    dt: float, ship: object | None, events: list[dict],
) -> None:
    """Load crew into pods and process launch countdowns."""
    if not _abandon_ship:
        return

    # Determine deck priority order.
    if _evacuation_order:
        ordered_decks = list(_evacuation_order)
    else:
        # Default: all decks in ascending order.
        ordered_decks = sorted({p.deck_number for p in _life_pods})

    # Auto-load crew into pods (LIFE_POD_LOAD_RATE per second per pod).
    load_per_tick = LIFE_POD_LOAD_RATE * dt
    for dn in ordered_decks:
        deck_pods = [p for p in _life_pods
                     if p.deck_number == dn and not p.launched and p.launch_timer <= 0]
        if not deck_pods:
            continue

        # Find available crew on this deck.
        available_crew = 0
        deck_name = None
        if ship is not None:
            crew = getattr(ship, "crew", None)
            if crew is not None:
                for sec in _sections.values():
                    if sec.deck_number == dn:
                        deck_name = sec.deck_name
                        break
                if deck_name is not None:
                    deck_crew = crew.decks.get(deck_name)
                    if deck_crew is not None:
                        available_crew = deck_crew.active + deck_crew.injured

        for pod in deck_pods:
            if pod.loaded_crew >= pod.capacity:
                continue
            remaining_space = pod.capacity - pod.loaded_crew
            can_add = min(load_per_tick, remaining_space, available_crew)
            if can_add <= 0:
                continue
            pod._load_accum += can_add
            if pod._load_accum >= 1.0:
                loaded = int(pod._load_accum)
                loaded = min(loaded, remaining_space, available_crew)
                pod.loaded_crew += loaded
                pod._load_accum -= loaded
                available_crew -= loaded

    # Process launch countdowns.
    for pod in _life_pods:
        if pod.launch_timer > 0:
            pod.launch_timer -= dt
            if pod.launch_timer <= 0:
                pod.launch_timer = 0.0
                pod.launched = True
                # Remove crew from ship roster.
                if ship is not None and pod.loaded_crew > 0:
                    crew = getattr(ship, "crew", None)
                    if crew is not None:
                        deck_name = None
                        for sec in _sections.values():
                            if sec.deck_number == pod.deck_number:
                                deck_name = sec.deck_name
                                break
                        if deck_name is not None:
                            crew.apply_casualties(deck_name, pod.loaded_crew)
                events.append({
                    "type": "pod_launched",
                    "pod_id": pod.id,
                    "deck_number": pod.deck_number,
                    "crew_saved": pod.loaded_crew,
                })
