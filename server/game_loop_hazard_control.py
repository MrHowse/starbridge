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

_rng: random.Random = random.Random()


# ---------------------------------------------------------------------------
# Public API — lifecycle
# ---------------------------------------------------------------------------


def reset() -> None:
    """Clear all hazard-control state.  Called at game start."""
    global _pending_hull_damage
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
            "HAZARD",
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
    }


def deserialise(data: dict) -> None:
    global _pending_hull_damage
    _active_dcts.clear()
    _active_dcts.update(data.get("active_dcts", {}))
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
# Public API — suppression commands
# ---------------------------------------------------------------------------


def suppress_local(room_id: str, resources: object | None = None) -> bool:
    """Start localised suppression on a fire.  Costs 1 suppressant, takes 5s.

    Returns False if no fire, or no suppressant available.
    """
    if room_id not in _fires:
        return False

    # Check suppressant.
    if resources is not None:
        avail = getattr(resources, "suppressant", 0.0)
        if avail < LOCAL_SUPPRESS_COST:
            return False
        if hasattr(resources, "consume"):
            resources.consume("suppressant", LOCAL_SUPPRESS_COST)

    fire = _fires[room_id]
    fire.suppression_timer = LOCAL_SUPPRESS_TIME
    fire.suppression_type = "local"
    logger.debug("Local suppression started: %s", room_id)
    return True


def suppress_deck(deck_name: str, interior: ShipInterior,
                  resources: object | None = None) -> bool:
    """Start deck-wide suppression.  Costs 3 suppressant, takes 15s.

    Returns False if no fires on deck or no suppressant.
    """
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
# Public API — tick
# ---------------------------------------------------------------------------


def tick(interior: ShipInterior, dt: float, difficulty: object | None = None,
         resources: object | None = None, ship: object | None = None) -> list[dict]:
    """Advance fire model and DCT repairs for one simulation tick.

    Returns a list of event dicts for the game loop to broadcast.
    """
    events: list[dict] = []

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

    return events


def build_dc_state(interior: ShipInterior, difficulty: object | None = None) -> dict:
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
    }


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
