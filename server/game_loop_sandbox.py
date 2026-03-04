"""Sandbox Activity Generator.

Periodically generates events across all station domains so that every
role has meaningful work during free-play and solo-play sessions.
Only active when mission_id == "sandbox".

Events returned from tick():
  {"type": "spawn_enemy",   "enemy_type": str, "x": float, "y": float, "id": str}
  {"type": "system_damage", "system": str, "amount": float}
  {"type": "crew_casualty", "deck": str, "count": int}
  {"type": "start_boarding","intruders": list[dict]}
  {"type": "mission_signal","mission_type": str, "signal_params": dict}
  {"type": "security_incident","incident": str, "message": str, "deck": str}
  {"type": "env_sickness"}
  {"type": "sandbox_fire",  "room_id": str, "intensity": int}
  {"type": "sandbox_breach","room_id": str, "severity": str}
  {"type": "sandbox_radiation","room_id": str, "amount": float, "source": str}
  {"type": "sandbox_structural","room_id": str, "amount": float}
  {"type": "sandbox_intel_update","enemy_id": str|None, "assessment": dict}
  {"type": "sandbox_ops_alert","alert": str, "severity": str, "source": str}
  {"type": "sandbox_resource_pressure","resource": str, "level": float, "message": str}
  {"type": "sandbox_trade_opportunity","offer": dict}
  {"type": "sandbox_ew_intercept","faction": str, "intel": str}
  {"type": "sandbox_flight_contact","x": float, "y": float, "label": str, "id": str}
  {"type": "sandbox_captain_decision","decision_id": str, "prompt": str, "options": list}
  {"type": "sandbox_medical_event","cause": str, "deck": str, "severity_scale": float}
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.models.world import World

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

# Seconds between each class of event (min, max).
ENEMY_SPAWN_INTERVAL:   tuple[float, float] = (60.0,  90.0)
SYSTEM_DAMAGE_INTERVAL: tuple[float, float] = (45.0,  75.0)
CREW_CASUALTY_INTERVAL: tuple[float, float] = (60.0, 100.0)
BOARDING_INTERVAL:      tuple[float, float] = (75.0, 120.0)

INCOMING_TRANSMISSION_INTERVAL: tuple[float, float] = (90.0,  120.0)
HULL_MICRO_DAMAGE_INTERVAL:     tuple[float, float] = (120.0, 180.0)
SENSOR_ANOMALY_INTERVAL:        tuple[float, float] = (90.0,  150.0)
DRONE_OPPORTUNITY_INTERVAL:     tuple[float, float] = (75.0,  120.0)
ENEMY_JAMMING_INTERVAL:         tuple[float, float] = (90.0,  120.0)
DISTRESS_SIGNAL_INTERVAL:       tuple[float, float] = (180.0, 300.0)

# Minor security events to keep the Security station busy between boardings.
SECURITY_EVENT_INTERVAL:        tuple[float, float] = (30.0,  60.0)

# Chance of crew injury as side-effect of other sandbox events (Medical work).
CREW_INJURY_FROM_OVERCLOCK_CHANCE: float = 0.35   # 35% per overclock damage event
CREW_INJURY_FROM_SYSTEM_DAMAGE_CHANCE: float = 0.20  # 20% per system damage event
ALTERCATION_INJURY_CHANCE: float = 0.40            # 40% per crew_altercation incident

# Environmental sickness from prolonged bad atmosphere (low O2 / high temp).
ENV_SICKNESS_CHECK_INTERVAL: tuple[float, float] = (90.0, 120.0)

# ---------------------------------------------------------------------------
# Hazard Control event intervals (v0.08)
# ---------------------------------------------------------------------------
SANDBOX_FIRE_INTERVAL:       tuple[float, float] = (60.0,  90.0)
SANDBOX_BREACH_INTERVAL:     tuple[float, float] = (120.0, 180.0)
SANDBOX_RADIATION_INTERVAL:  tuple[float, float] = (180.0, 240.0)
SANDBOX_STRUCTURAL_INTERVAL: tuple[float, float] = (120.0, 180.0)

# Caps for simultaneous sandbox-started hazcon events.
MAX_SANDBOX_FIRES: int = 2
MAX_SANDBOX_BREACHES: int = 1
MAX_SANDBOX_RADIATION: int = 1

# ---------------------------------------------------------------------------
# Operations event intervals
# ---------------------------------------------------------------------------
SANDBOX_INTEL_UPDATE_INTERVAL: tuple[float, float] = (60.0,  90.0)
SANDBOX_OPS_ALERT_INTERVAL:   tuple[float, float] = (90.0, 120.0)

# ---------------------------------------------------------------------------
# Quartermaster event intervals
# ---------------------------------------------------------------------------
SANDBOX_RESOURCE_PRESSURE_INTERVAL: tuple[float, float] = (90.0,  120.0)
SANDBOX_TRADE_OPPORTUNITY_INTERVAL: tuple[float, float] = (180.0, 240.0)
TRADE_OFFER_EXPIRY: float = 75.0  # seconds before a trade offer expires

# ---------------------------------------------------------------------------
# Boosted station event intervals (EW, Flight Ops, Captain)
# ---------------------------------------------------------------------------
SANDBOX_EW_INTERCEPT_INTERVAL:      tuple[float, float] = (120.0, 180.0)
SANDBOX_FLIGHT_CONTACT_INTERVAL:    tuple[float, float] = (90.0,  120.0)
SANDBOX_CAPTAIN_DECISION_INTERVAL:  tuple[float, float] = (90.0,  120.0)

# ---------------------------------------------------------------------------
# Medical standalone event interval
# ---------------------------------------------------------------------------
SANDBOX_MEDICAL_EVENT_INTERVAL: tuple[float, float] = (90.0, 120.0)

# Minor security incident types — give Security work between boardings.
SECURITY_INCIDENT_TYPES: list[dict] = [
    {"incident": "sensor_ghost",       "message": "Unidentified contact on internal sensors, Deck {deck}."},
    {"incident": "crew_altercation",   "message": "Crew dispute reported on Deck {deck}. Possible fight."},
    {"incident": "suspicious_cargo",   "message": "Suspect item flagged in cargo scan — Deck {deck}."},
    {"incident": "system_access_alert","message": "Unauthorized system access attempt detected, Deck {deck}."},
    {"incident": "door_malfunction",   "message": "Door {room} jammed — investigate possible tampering."},
    {"incident": "missing_personnel",  "message": "Crew member unaccounted for on Deck {deck}. Last seen in {room}."},
]

# Hard cap on simultaneous sandbox enemies (initial 2 + up to 4 spawned).
MAX_ENEMIES: int = 6

# Creature spawn interval — 4 to 6 minutes (tuned for engagement).
CREATURE_SPAWN_INTERVAL: tuple[float, float] = (240.0, 360.0)

# Maximum live sandbox creatures before spawning is suppressed.
MAX_SANDBOX_CREATURES: int = 3

# Creature type pool — leviathan excluded (too powerful for sandbox free-play).
CREATURE_TYPE_POOL: list[str] = [
    "void_whale", "void_whale",      # docile; interesting for science players
    "rift_stalker", "rift_stalker",  # territorial; weapons/comms challenge
    "hull_leech",                     # rare but persistently annoying
    "swarm",                          # EW + science challenge
]

# ---------------------------------------------------------------------------
# Mission signal generation (dynamic mission pipeline)
# ---------------------------------------------------------------------------

# Seconds between mission-bearing signals (min, max) — scaled by difficulty.
MISSION_SIGNAL_INTERVAL: tuple[float, float] = (90.0, 180.0)

# Hard cap on simultaneous active dynamic missions before suppressing new signals.
MAX_SANDBOX_MISSIONS: int = 3

# Mission type budget: (type_key, base_weight, max_per_session).
MISSION_TYPE_BUDGET: list[tuple[str, float, int]] = [
    ("rescue",        2.0, 3),
    ("investigation", 2.0, 2),
    ("escort",        1.5, 2),
    ("trade",         1.5, 2),
    ("diplomatic",    1.0, 1),
    ("intercept",     0.5, 1),
    ("trap",          1.5, 2),
    ("patrol",        1.5, 2),
    ("salvage",       1.5, 2),
]

# Target travel time to mission waypoint (seconds).
MISSION_TARGET_TRAVEL_SECS: tuple[float, float] = (60.0, 120.0)

# First mission is close to teach the crew how missions work.
FIRST_MISSION_MAX_DIST: float = 5_000.0

# Vessel name pool for generated mission signals.
_MISSION_VESSEL_NAMES: list[str] = [
    "ISS Valiant", "CSV Horizon", "SS Wanderer", "MSV Pathfinder",
    "TCS Endurance", "RFS Resolute", "CSV Liberty", "MSV Fortune",
    "SS Meridian", "TCS Discovery",
]

# Faction → frequency mapping for mission signals.
_MISSION_FACTION_FREQ: dict[str, float] = {
    "civilian": 0.55,
    "federation": 0.65,
    "imperial": 0.15,
    "pirate": 0.08,
    "rebel": 0.42,
}

# Systems eligible for environmental damage events (Engineering / DC work).
DAMAGEABLE_SYSTEMS: list[str] = [
    "engines", "shields", "beams", "torpedoes", "sensors", "manoeuvring",
    "flight_deck", "ecm_suite",
]

# All crew decks that can receive casualties (Medical work).
CREW_DECKS: list[str] = [
    "bridge", "sensors", "weapons", "shields", "engineering", "medical",
]

# Enemy type pool — scouts more common so combat stays manageable solo.
ENEMY_TYPE_POOL: list[str] = [
    "scout", "scout", "scout", "cruiser",
]

# Faction bands for incoming transmissions (mirrors game_loop_comms.FACTION_BANDS).
# emergency band is reserved for distress_signal events.
TRANSMISSION_FACTIONS: dict[str, float] = {
    "imperial": 0.15,
    "rebel":    0.42,
    "alien":    0.71,
}

# Short hint strings shown to the Comms officer for incoming transmissions.
_TRANSMISSION_HINTS: list[str] = [
    "scrambled signal",
    "patrol coordinates",
    "supply manifest",
    "encrypted orders",
    "alliance request",
]

# Sensor anomaly classifications for the Science station.
SENSOR_ANOMALY_TYPES: list[str] = [
    "gravitational_flux",
    "energy_signature",
    "debris_field",
    "microwave_burst",
]

# Label strings for drone / probe scan opportunities (Flight Ops).
DRONE_OPPORTUNITY_LABELS: list[str] = [
    "Unknown Object",
    "Derelict Vessel",
    "Resource Deposit",
    "Anomalous Signature",
]

# Flight Ops contact labels for the sandbox_flight_contact event.
FLIGHT_CONTACT_LABELS: list[str] = [
    "Wreckage Detected",
    "Life Signs Detected",
    "Resource Cache",
    "Escape Pod",
    "Sensor Buoy",
    "Cargo Container",
]

# Ops alert templates keyed by game-state condition.
_OPS_ALERT_TEMPLATES: list[dict] = [
    {"condition": "enemies", "alert": "Multiple hostile contacts — recommend priority target designation", "severity": "warning", "source": "TACTICAL"},
    {"condition": "low_power", "alert": "Ship power reserves below 60% — recommend power reallocation", "severity": "warning", "source": "ENG"},
    {"condition": "damage", "alert": "Hull integrity degraded — recommend damage assessment", "severity": "warning", "source": "HAZCON"},
    {"condition": "crew_low", "alert": "Crew effectiveness reduced — recommend station rotation", "severity": "info", "source": "MEDICAL"},
    {"condition": "general", "alert": "Sector sweep incomplete — recommend science scan of adjacent grid", "severity": "info", "source": "SCIENCE"},
    {"condition": "general", "alert": "Fuel reserves nominal — recommend waypoint planning", "severity": "info", "source": "HELM"},
    {"condition": "general", "alert": "Communications traffic increasing — recommend signal monitoring", "severity": "info", "source": "COMMS"},
]

# Captain decision prompts.
_CAPTAIN_DECISIONS: list[dict] = [
    {
        "prompt": "Unidentified vessel approaching on passive sensors. Respond or maintain silence?",
        "options": ["Hail vessel", "Maintain silence", "Raise shields"],
    },
    {
        "prompt": "Crew requesting permission to investigate nearby anomaly. Divert?",
        "options": ["Approve diversion", "Deny — maintain course"],
    },
    {
        "prompt": "Engineering reports non-critical system can be taken offline for maintenance. Approve?",
        "options": ["Approve maintenance", "Defer — keep systems online"],
    },
    {
        "prompt": "Long-range sensors detect debris field. Investigate for salvage?",
        "options": ["Investigate", "Log and continue", "Send drone"],
    },
    {
        "prompt": "Crew morale report indicates fatigue on multiple decks. Action?",
        "options": ["Rotate stations", "Increase provisions", "No action"],
    },
    {
        "prompt": "Adjacent sector reports increased pirate activity. Alter course?",
        "options": ["Alter to avoid", "Maintain course", "Increase alert level"],
    },
]

# Medical event causes for standalone medical events.
_MEDICAL_EVENT_CAUSES: list[dict] = [
    {"cause": "system_malfunction", "label": "Crew illness — space adaptation syndrome", "severity_scale": 0.5},
    {"cause": "radiation",          "label": "Background radiation exposure symptoms",  "severity_scale": 0.4},
    {"cause": "system_malfunction", "label": "Food contamination — galley incident",    "severity_scale": 0.6},
    {"cause": "system_malfunction", "label": "Crew fatigue — overworked station operator", "severity_scale": 0.3},
    {"cause": "system_malfunction", "label": "Pre-existing condition flare-up",         "severity_scale": 0.5},
    {"cause": "hull_breach",        "label": "Minor decompression exposure",            "severity_scale": 0.4},
]

# Trade offer templates.
_TRADE_OFFERS: list[dict] = [
    {"give_type": "fuel", "give_amount": 20.0, "get_type": "ammunition", "get_amount": 4.0, "label": "Merchant offering 4 rounds of ammunition for 20 fuel units"},
    {"give_type": "fuel", "give_amount": 15.0, "get_type": "suppressant", "get_amount": 10.0, "label": "Trader offering 10 fire suppressant for 15 fuel units"},
    {"give_type": "provisions", "give_amount": 5.0, "get_type": "medical_supplies", "get_amount": 3.0, "label": "Supply vessel offering 3 medical kits for 5 provisions"},
    {"give_type": "fuel", "give_amount": 25.0, "get_type": "repair_materials", "get_amount": 8.0, "label": "Salvage team offering 8 repair materials for 25 fuel units"},
    {"give_type": "ammunition", "give_amount": 2.0, "get_type": "drone_parts", "get_amount": 3.0, "label": "Technician offering 3 drone parts for 2 rounds of ammo"},
]

# Spawn distance from the player ship.
SPAWN_DIST_MIN: float = 20_000.0
SPAWN_DIST_MAX: float = 35_000.0

# First enemy spawns closer so drones and weapons can engage early.
FIRST_ENEMY_DIST_MIN: float = 8_000.0
FIRST_ENEMY_DIST_MAX: float = 15_000.0

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_active: bool = False
_timers: dict[str, float] = {}
_entity_counter: int = 0   # offset counter for unique IDs
_mission_type_counts: dict[str, int] = {}  # per-session mission variety tracking
_first_mission_generated: bool = False  # first mission gets close distance
_first_enemy_spawned: bool = False  # first enemy spawns closer
_sandbox_fire_rooms: set[str] = set()      # rooms with sandbox-started fires
_sandbox_breach_rooms: set[str] = set()    # rooms with sandbox-started breaches
_sandbox_radiation_active: bool = False    # whether a sandbox radiation event is active
_active_trade_offers: list[dict] = []      # pending trade offers
_decision_counter: int = 0                 # unique IDs for captain decisions

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset(active: bool = False) -> None:
    """Reset sandbox scheduler.  Pass active=True to start the scheduler."""
    global _active, _entity_counter, _first_mission_generated, _first_enemy_spawned
    global _sandbox_radiation_active, _decision_counter
    _active = active
    _entity_counter = 1000    # offset well above mission-spawned entity IDs
    _timers.clear()
    _mission_type_counts.clear()
    _first_mission_generated = False
    _first_enemy_spawned = False
    _sandbox_fire_rooms.clear()
    _sandbox_breach_rooms.clear()
    _sandbox_radiation_active = False
    _active_trade_offers.clear()
    _decision_counter = 0
    if active:
        # Stagger initial timers so all events don't fire simultaneously.
        _timers["enemy_spawn"]          = random.uniform(30.0,  60.0)   # first wave sooner
        _timers["system_damage"]        = random.uniform(30.0,  50.0)
        _timers["crew_casualty"]        = random.uniform(45.0,  75.0)
        _timers["boarding"]             = random.uniform(90.0, 120.0)
        _timers["incoming_transmission"]= random.uniform(45.0,  75.0)
        _timers["hull_micro_damage"]    = random.uniform(60.0,  90.0)
        _timers["sensor_anomaly"]       = random.uniform(45.0,  75.0)
        _timers["drone_opportunity"]    = random.uniform(60.0,  90.0)
        _timers["enemy_jamming"]        = random.uniform(60.0,  90.0)
        _timers["distress_signal"]      = random.uniform(90.0, 120.0)
        _timers["creature_spawn"]       = random.uniform(120.0, 180.0)  # first one sooner
        _timers["mission_signal"]       = random.uniform(60.0,  90.0)   # first mission sooner
        _timers["security_event"]       = random.uniform(20.0,  40.0)   # minor events early
        _timers["env_sickness"]         = random.uniform(60.0,  90.0)   # env sickness check
        # v0.08 Hazard Control
        _timers["sandbox_fire"]         = random.uniform(45.0,  75.0)
        _timers["sandbox_breach"]       = random.uniform(90.0, 120.0)
        _timers["sandbox_radiation"]    = random.uniform(120.0, 180.0)
        _timers["sandbox_structural"]   = random.uniform(120.0, 180.0)
        # Operations
        _timers["sandbox_intel_update"] = random.uniform(30.0,  60.0)
        _timers["sandbox_ops_alert"]    = random.uniform(60.0,  90.0)
        # Quartermaster
        _timers["sandbox_resource_pressure"] = random.uniform(60.0, 90.0)
        _timers["sandbox_trade_opportunity"] = random.uniform(120.0, 180.0)
        # EW / Flight Ops / Captain boosts
        _timers["sandbox_ew_intercept"]     = random.uniform(60.0, 90.0)
        _timers["sandbox_flight_contact"]   = random.uniform(60.0, 90.0)
        _timers["sandbox_captain_decision"] = random.uniform(60.0, 90.0)
        # Medical standalone
        _timers["sandbox_medical_event"]    = random.uniform(60.0, 90.0)


def is_active() -> bool:
    """Return True if the sandbox scheduler is running."""
    return _active


def get_active_trade_offers() -> list[dict]:
    """Return active trade offers (for Quartermaster)."""
    return list(_active_trade_offers)


def accept_trade_offer(offer_id: str) -> dict | None:
    """Accept a pending trade offer by ID.  Returns the offer dict or None."""
    for i, offer in enumerate(_active_trade_offers):
        if offer.get("id") == offer_id:
            return _active_trade_offers.pop(i)
    return None


def notify_fire_extinguished(room_id: str) -> None:
    """Called when a sandbox-started fire is put out."""
    _sandbox_fire_rooms.discard(room_id)


def notify_breach_repaired(room_id: str) -> None:
    """Called when a sandbox-started breach is repaired."""
    _sandbox_breach_rooms.discard(room_id)


def notify_radiation_cleared() -> None:
    """Called when sandbox radiation event is resolved."""
    global _sandbox_radiation_active
    _sandbox_radiation_active = False


# ---------------------------------------------------------------------------
# Mission signal helpers (used by tick)
# ---------------------------------------------------------------------------


def _pick_mission_type() -> str | None:
    """Select a mission type via weighted random, respecting per-session caps."""
    candidates: list[tuple[str, float]] = []
    for type_key, weight, max_count in MISSION_TYPE_BUDGET:
        current = _mission_type_counts.get(type_key, 0)
        if current >= max_count:
            continue
        candidates.append((type_key, weight))

    if not candidates:
        return None

    total = sum(w for _, w in candidates)
    roll = random.uniform(0, total)
    cumulative = 0.0
    for type_key, weight in candidates:
        cumulative += weight
        if roll <= cumulative:
            return type_key

    return candidates[-1][0]


def _build_mission_signal(mission_type: str, world: "World") -> dict | None:
    """Build a ``mission_signal`` event dict for the given mission type.

    Returns None if the type is unrecognised.
    """
    global _entity_counter, _first_mission_generated
    _entity_counter += 1
    entity_id = f"sb_m{_entity_counter}"

    ship = world.ship

    # Calculate max distance based on ship speed (60-120 seconds of travel)
    from server.systems.physics import max_speed as _phys_max_speed
    effective_speed = max(_phys_max_speed(ship), ship.max_speed_base * 0.5)

    if not _first_mission_generated:
        # First mission is close to teach the crew how missions work
        dist = random.uniform(2_000.0, FIRST_MISSION_MAX_DIST)
        _first_mission_generated = True
    else:
        min_dist = effective_speed * MISSION_TARGET_TRAVEL_SECS[0]
        max_dist = effective_speed * MISSION_TARGET_TRAVEL_SECS[1]
        dist = random.uniform(min_dist, max_dist)

    angle = random.uniform(0.0, 360.0)
    px = max(5_000.0, min(world.width - 5_000.0,
                          ship.x + math.cos(math.radians(angle)) * dist))
    py = max(5_000.0, min(world.height - 5_000.0,
                          ship.y + math.sin(math.radians(angle)) * dist))

    vessel_name = random.choice(_MISSION_VESSEL_NAMES)
    loc: dict = {"position": [round(px, 1), round(py, 1)], "entity_type": "ship"}

    params: dict

    if mission_type == "rescue":
        faction = random.choice(["civilian", "federation", "imperial"])
        params = dict(
            source="distress_beacon",
            source_name=vessel_name,
            frequency=0.90,
            signal_type="distress",
            priority="critical",
            raw_content=f"MAYDAY — {vessel_name} under attack. Requesting immediate assistance.",
            decoded_content=f"MAYDAY — {vessel_name} under attack. Requesting immediate assistance.",
            auto_decoded=True,
            requires_decode=False,
            faction=faction,
            threat_level="distress",
            location_data=loc,
        )

    elif mission_type == "investigation":
        params = dict(
            source=f"unknown_{entity_id}",
            source_name="Unknown Source",
            frequency=round(random.uniform(0.2, 0.8), 3),
            signal_type="data_burst",
            priority="medium",
            raw_content="Automated data transmission from uncharted coordinates. Source unknown. Pattern non-standard.",
            requires_decode=True,
            faction="unknown",
            threat_level="unknown",
            intel_value="possible_tech",
            intel_category="science",
            location_data={**loc, "entity_type": "unknown"},
        )

    elif mission_type == "escort":
        params = dict(
            source=f"civilian_{entity_id}",
            source_name=vessel_name,
            frequency=_MISSION_FACTION_FREQ["civilian"],
            signal_type="hail",
            priority="medium",
            raw_content=f"This is {vessel_name}. Hostile contacts detected in our path. Requesting escort.",
            decoded_content=f"This is {vessel_name}. Hostile contacts detected in our path. Requesting escort.",
            auto_decoded=True,
            requires_decode=False,
            faction="civilian",
            threat_level="unknown",
            location_data=loc,
        )

    elif mission_type == "trade":
        faction = random.choice(["federation", "imperial"])
        params = dict(
            source=f"merchant_{entity_id}",
            source_name=vessel_name,
            frequency=_MISSION_FACTION_FREQ.get(faction, 0.55),
            signal_type="hail",
            priority="low",
            raw_content=f"This is {vessel_name}. Supplies available for trade. Interested in sensor data exchange.",
            decoded_content=f"This is {vessel_name}. Supplies available for trade. Interested in sensor data exchange.",
            auto_decoded=True,
            requires_decode=False,
            faction=faction,
            threat_level="unknown",
            location_data=loc,
        )

    elif mission_type == "diplomatic":
        faction = "pirate"
        params = dict(
            source=f"{faction}_envoy_{entity_id}",
            source_name=f"{faction.title()} Envoy",
            frequency=_MISSION_FACTION_FREQ.get(faction, 0.08),
            signal_type="hail",
            priority="high",
            raw_content=f"The {faction.title()} Clan proposes a meeting to discuss terms.",
            decoded_content=f"The {faction.title()} Clan proposes a meeting to discuss terms.",
            auto_decoded=True,
            requires_decode=False,
            faction=faction,
            threat_level="unknown",
            location_data=loc,
        )

    elif mission_type == "intercept":
        faction = random.choice(["pirate", "rebel"])
        params = dict(
            source=f"{faction}_comms_{entity_id}",
            source_name=f"{faction.title()} Fleet",
            frequency=_MISSION_FACTION_FREQ.get(faction, 0.15),
            signal_type="encrypted",
            priority="high",
            raw_content="Supply convoy departing sector grid. Escort: light. Manifest: munitions and fuel.",
            requires_decode=True,
            faction=faction,
            threat_level="hostile",
            intel_value="convoy_route",
            intel_category="military",
            location_data={**loc, "entity_type": "fleet"},
        )

    elif mission_type == "trap":
        faction = random.choice(["civilian", "unknown"])
        souls = random.randint(5, 20)
        params = dict(
            source="distress_beacon",
            source_name=vessel_name,
            frequency=0.90,
            signal_type="distress",
            priority="critical",
            raw_content=f"MAYDAY — {vessel_name} losing life support. {souls} souls aboard.",
            decoded_content=f"MAYDAY — {vessel_name} losing life support. {souls} souls aboard.",
            auto_decoded=True,
            requires_decode=False,
            faction=faction,
            threat_level="distress",
            location_data={**loc, "is_trap": True},
        )

    elif mission_type == "patrol":
        faction = random.choice(["federation", "imperial"])
        params = dict(
            source=f"fleet_command_{entity_id}",
            source_name=f"{faction.title()} Fleet Command",
            frequency=_MISSION_FACTION_FREQ.get(faction, 0.65),
            signal_type="broadcast",
            priority="normal",
            raw_content=f"Patrol sector grid reference {random.randint(1,9)}-{random.randint(1,9)}. Report contacts.",
            decoded_content=f"Patrol sector grid. Scan and report all contacts in area.",
            auto_decoded=True,
            requires_decode=False,
            faction=faction,
            threat_level="low",
            intel_category="fleet",
            location_data=loc,
        )

    elif mission_type == "salvage":
        params = dict(
            source=f"nav_beacon_{entity_id}",
            source_name="Navigation Beacon",
            frequency=0.55,
            signal_type="broadcast",
            priority="low",
            raw_content=f"Debris field detected at nav reference. Possible salvage opportunity.",
            decoded_content=f"Debris field with potential salvage. Caution: hazards present.",
            auto_decoded=True,
            requires_decode=False,
            faction="civilian",
            threat_level="low",
            intel_category="navigation",
            location_data=loc,
        )

    else:
        return None

    _mission_type_counts[mission_type] = _mission_type_counts.get(mission_type, 0) + 1

    return {
        "type": "mission_signal",
        "mission_type": mission_type,
        "signal_params": params,
    }


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


def tick(
    world: "World",
    dt: float,
    difficulty: object | None = None,
    *,
    active_mission_count: int = 0,
) -> list[dict]:
    """Advance all timers by *dt* seconds.  Return event dicts to process.

    *difficulty* — when provided, scales event intervals and boarding frequency.
    *active_mission_count* — current dynamic mission count (suppresses new
        mission signals when at capacity).
    """
    if not _active:
        return []

    global _entity_counter, _sandbox_radiation_active, _decision_counter

    _evt_mult = getattr(difficulty, "event_interval_multiplier", 1.0) if difficulty else 1.0
    _brd_mult = getattr(difficulty, "boarding_frequency_multiplier", 1.0) if difficulty else 1.0
    _overlap_max = getattr(difficulty, "event_overlap_max", 999) if difficulty else 999

    for key in list(_timers):
        _timers[key] -= dt

    events: list[dict] = []

    # --- Enemy spawn (Weapons / Helm / Science / EW / Flight Ops) --------
    if _timers.get("enemy_spawn", 1.0) <= 0.0:
        if len(world.enemies) < MAX_ENEMIES:
            global _first_enemy_spawned
            enemy_type = random.choice(ENEMY_TYPE_POOL)
            angle = random.uniform(0.0, 360.0)
            if not _first_enemy_spawned:
                dist = random.uniform(FIRST_ENEMY_DIST_MIN, FIRST_ENEMY_DIST_MAX)
                _first_enemy_spawned = True
            else:
                dist = random.uniform(SPAWN_DIST_MIN, SPAWN_DIST_MAX)
            sx    = world.ship.x + math.cos(math.radians(angle)) * dist
            sy    = world.ship.y + math.sin(math.radians(angle)) * dist
            # Clamp to world bounds with a safe margin.
            sx = max(5_000.0, min(world.width  - 5_000.0, sx))
            sy = max(5_000.0, min(world.height - 5_000.0, sy))
            _entity_counter += 1
            events.append({
                "type":       "spawn_enemy",
                "enemy_type": enemy_type,
                "x":          sx,
                "y":          sy,
                "id":         f"sb_e{_entity_counter}",
            })
        _timers["enemy_spawn"] = random.uniform(*ENEMY_SPAWN_INTERVAL) * _evt_mult

    # --- System damage — micrometeorite / power surge (Engineering / DC) --
    if _timers.get("system_damage", 1.0) <= 0.0:
        system = random.choice(DAMAGEABLE_SYSTEMS)
        if system in world.ship.systems:
            amount = round(random.uniform(8.0, 20.0), 1)
            events.append({"type": "system_damage", "system": system, "amount": amount})
        _timers["system_damage"] = random.uniform(*SYSTEM_DAMAGE_INTERVAL) * _evt_mult

    # --- Crew casualty — accident on a random deck (Medical) --------------
    if _timers.get("crew_casualty", 1.0) <= 0.0:
        deck = random.choice(CREW_DECKS)
        _casualty_cause = random.choice([
            "system_malfunction", "system_malfunction",
            "fire", "explosion", "hull_breach",
        ])
        events.append({"type": "crew_casualty", "deck": deck, "count": 1,
                        "cause": _casualty_cause})
        _timers["crew_casualty"] = random.uniform(*CREW_CASUALTY_INTERVAL) * _evt_mult

    # --- Boarding attempt (Security) --------------------------------------
    if _timers.get("boarding", 1.0) <= 0.0:
        _entity_counter += 1
        _boarding_objectives = ["bridge", "engine_room", "shields_control", "weapons_bay"]
        _intruder_count = random.choice([1, 1, 2, 2, 3])  # mostly 1-2
        _intruder_list = []
        for _bi in range(_intruder_count):
            _intruder_list.append({
                "id": f"sb_i{_entity_counter + _bi}",
                "room_id": "cargo_hold",
                "objective_id": random.choice(_boarding_objectives),
            })
        _entity_counter += _intruder_count
        events.append({
            "type": "start_boarding",
            "intruders": _intruder_list,
        })
        _timers["boarding"] = random.uniform(*BOARDING_INTERVAL) * _evt_mult / max(0.1, _brd_mult)

    # --- Minor security incident (Security) --------------------------------
    if _timers.get("security_event", 1.0) <= 0.0:
        _incident_tpl = random.choice(SECURITY_INCIDENT_TYPES)
        _deck = random.choice(CREW_DECKS)
        _room = random.choice(["cargo_hold", "corridor_a", "mess_hall", "armoury", "airlock_1"])
        _msg = _incident_tpl["message"].format(deck=_deck, room=_room)
        events.append({
            "type": "security_incident",
            "incident": _incident_tpl["incident"],
            "message": _msg,
            "deck": _deck,
        })
        _timers["security_event"] = random.uniform(*SECURITY_EVENT_INTERVAL) * _evt_mult

    # --- Environmental sickness (Medical) — prolonged atmo hazards ----------
    if _timers.get("env_sickness", 1.0) <= 0.0:
        events.append({"type": "env_sickness"})
        _timers["env_sickness"] = random.uniform(*ENV_SICKNESS_CHECK_INTERVAL) * _evt_mult

    # --- Incoming transmission — NPC contact on a faction band (Comms) ----
    if _timers.get("incoming_transmission", 1.0) <= 0.0:
        faction = random.choice(list(TRANSMISSION_FACTIONS.keys()))
        events.append({
            "type":         "incoming_transmission",
            "faction":      faction,
            "frequency":    TRANSMISSION_FACTIONS[faction],
            "message_hint": random.choice(_TRANSMISSION_HINTS),
        })
        _timers["incoming_transmission"] = random.uniform(*INCOMING_TRANSMISSION_INTERVAL) * _evt_mult

    # --- Hull micro-damage — micrometeorite strike (Hazard Control) --------
    if _timers.get("hull_micro_damage", 1.0) <= 0.0:
        amount = round(random.uniform(2.0, 8.0), 1)
        events.append({"type": "hull_micro_damage", "amount": amount})
        _timers["hull_micro_damage"] = random.uniform(*HULL_MICRO_DAMAGE_INTERVAL) * _evt_mult

    # --- Sensor anomaly — unexplained reading for Science to investigate --
    if _timers.get("sensor_anomaly", 1.0) <= 0.0:
        angle = random.uniform(0.0, 360.0)
        dist  = random.uniform(10_000.0, 30_000.0)
        ax    = max(5_000.0, min(world.width  - 5_000.0,
                                 world.ship.x + math.cos(math.radians(angle)) * dist))
        ay    = max(5_000.0, min(world.height - 5_000.0,
                                 world.ship.y + math.sin(math.radians(angle)) * dist))
        _entity_counter += 1
        events.append({
            "type":         "sensor_anomaly",
            "x":            round(ax, 1),
            "y":            round(ay, 1),
            "id":           f"sb_a{_entity_counter}",
            "anomaly_type": random.choice(SENSOR_ANOMALY_TYPES),
        })
        _timers["sensor_anomaly"] = random.uniform(*SENSOR_ANOMALY_INTERVAL) * _evt_mult

    # --- Drone opportunity — scan target enters range (Flight Ops) --------
    if _timers.get("drone_opportunity", 1.0) <= 0.0:
        angle = random.uniform(0.0, 360.0)
        dist  = random.uniform(SPAWN_DIST_MIN, SPAWN_DIST_MAX)
        dx    = max(5_000.0, min(world.width  - 5_000.0,
                                 world.ship.x + math.cos(math.radians(angle)) * dist))
        dy    = max(5_000.0, min(world.height - 5_000.0,
                                 world.ship.y + math.sin(math.radians(angle)) * dist))
        _entity_counter += 1
        events.append({
            "type":  "drone_opportunity",
            "x":     round(dx, 1),
            "y":     round(dy, 1),
            "id":    f"sb_d{_entity_counter}",
            "label": random.choice(DRONE_OPPORTUNITY_LABELS),
        })
        _timers["drone_opportunity"] = random.uniform(*DRONE_OPPORTUNITY_INTERVAL) * _evt_mult

    # --- Enemy jamming attempt (Electronic Warfare) -----------------------
    if _timers.get("enemy_jamming", 1.0) <= 0.0:
        events.append({
            "type":     "enemy_jamming",
            "strength": round(random.uniform(0.3, 0.7), 2),
        })
        _timers["enemy_jamming"] = random.uniform(*ENEMY_JAMMING_INTERVAL) * _evt_mult

    # --- Creature spawn (Science / EW / Weapons / Comms challenge) -------
    if _timers.get("creature_spawn", 1.0) <= 0.0:
        if len(world.creatures) < MAX_SANDBOX_CREATURES:
            creature_type = random.choice(CREATURE_TYPE_POOL)
            angle = random.uniform(0.0, 360.0)
            dist  = random.uniform(SPAWN_DIST_MIN, SPAWN_DIST_MAX)
            cx    = max(5_000.0, min(world.width  - 5_000.0,
                                     world.ship.x + math.cos(math.radians(angle)) * dist))
            cy    = max(5_000.0, min(world.height - 5_000.0,
                                     world.ship.y + math.sin(math.radians(angle)) * dist))
            _entity_counter += 1
            events.append({
                "type":          "spawn_creature",
                "creature_type": creature_type,
                "x":             round(cx, 1),
                "y":             round(cy, 1),
                "id":            f"sb_c{_entity_counter}",
            })
        _timers["creature_spawn"] = random.uniform(*CREATURE_SPAWN_INTERVAL) * _evt_mult

    # --- Mission-bearing signal generation (dynamic mission pipeline) ----
    if _timers.get("mission_signal", 1.0) <= 0.0:
        _can_gen = (
            active_mission_count < MAX_SANDBOX_MISSIONS
            and len(world.enemies) < 3   # suppress during heavy combat
        )
        if _can_gen:
            _mtype = _pick_mission_type()
            if _mtype is not None:
                _mevt = _build_mission_signal(_mtype, world)
                if _mevt is not None:
                    events.append(_mevt)
        _timers["mission_signal"] = random.uniform(*MISSION_SIGNAL_INTERVAL) * _evt_mult

    # --- Distress signal — emergency broadcast (Comms / Helm / Captain) --
    if _timers.get("distress_signal", 1.0) <= 0.0:
        angle = random.uniform(0.0, 360.0)
        dist  = random.uniform(30_000.0, 60_000.0)
        dsx   = max(5_000.0, min(world.width  - 5_000.0,
                                 world.ship.x + math.cos(math.radians(angle)) * dist))
        dsy   = max(5_000.0, min(world.height - 5_000.0,
                                 world.ship.y + math.sin(math.radians(angle)) * dist))
        events.append({
            "type":      "distress_signal",
            "x":         round(dsx, 1),
            "y":         round(dsy, 1),
            "frequency": 0.90,
        })
        _timers["distress_signal"] = random.uniform(*DISTRESS_SIGNAL_INTERVAL) * _evt_mult

    # ===================================================================
    # NEW v0.08 event generators
    # ===================================================================

    # --- Sandbox fire — room fire outbreak (Hazard Control) ---------------
    if _timers.get("sandbox_fire", 1.0) <= 0.0:
        interior = getattr(world.ship, "interior", None)
        if interior is not None and len(_sandbox_fire_rooms) < MAX_SANDBOX_FIRES:
            # Pick a random room that doesn't already have a fire.
            import server.game_loop_hazard_control as _glhc
            _existing_fires = _glhc.get_fires()
            _candidate_rooms = [
                rid for rid in interior.rooms
                if rid not in _existing_fires
            ]
            if _candidate_rooms:
                _fire_room = random.choice(_candidate_rooms)
                # Difficulty scales intensity: 1 at easy, up to 3 at hard.
                _diff_mult = getattr(difficulty, "event_interval_multiplier", 1.0) if difficulty else 1.0
                if _diff_mult <= 0.6:      # Admiral
                    _fire_intensity = random.choice([2, 2, 3])
                elif _diff_mult <= 0.8:    # Commander
                    _fire_intensity = random.choice([1, 2, 2])
                else:                       # Officer / Cadet
                    _fire_intensity = random.choice([1, 1, 2])
                _sandbox_fire_rooms.add(_fire_room)
                events.append({
                    "type": "sandbox_fire",
                    "room_id": _fire_room,
                    "intensity": _fire_intensity,
                })
        _timers["sandbox_fire"] = random.uniform(*SANDBOX_FIRE_INTERVAL) * _evt_mult

    # --- Sandbox breach — hull breach / atmosphere event (Hazard Control) -
    if _timers.get("sandbox_breach", 1.0) <= 0.0:
        interior = getattr(world.ship, "interior", None)
        if interior is not None and len(_sandbox_breach_rooms) < MAX_SANDBOX_BREACHES:
            import server.game_loop_atmosphere as _glatm
            _existing_breaches = _glatm.get_breaches()
            _breach_candidates = [
                rid for rid in interior.rooms
                if rid not in _existing_breaches
            ]
            if _breach_candidates:
                _breach_room = random.choice(_breach_candidates)
                _diff_mult = getattr(difficulty, "event_interval_multiplier", 1.0) if difficulty else 1.0
                _severity = "major" if _diff_mult <= 0.6 else "minor"
                _sandbox_breach_rooms.add(_breach_room)
                events.append({
                    "type": "sandbox_breach",
                    "room_id": _breach_room,
                    "severity": _severity,
                })
        _timers["sandbox_breach"] = random.uniform(*SANDBOX_BREACH_INTERVAL) * _evt_mult

    # --- Sandbox radiation — localised radiation leak (Hazard Control) ----
    if _timers.get("sandbox_radiation", 1.0) <= 0.0:
        interior = getattr(world.ship, "interior", None)
        if interior is not None and not _sandbox_radiation_active:
            # Pick a room in engineering or shields area.
            _rad_candidates = [
                rid for rid, room in interior.rooms.items()
                if room.deck in ("engineering", "shields", "sensors")
            ]
            if not _rad_candidates:
                _rad_candidates = list(interior.rooms.keys())
            if _rad_candidates:
                _rad_room = random.choice(_rad_candidates)
                _diff_mult = getattr(difficulty, "event_interval_multiplier", 1.0) if difficulty else 1.0
                # Radiation amount: 15-30 at easy, 30-50 at hard.
                if _diff_mult <= 0.6:
                    _rad_amount = round(random.uniform(30.0, 50.0), 1)
                elif _diff_mult <= 0.8:
                    _rad_amount = round(random.uniform(20.0, 40.0), 1)
                else:
                    _rad_amount = round(random.uniform(15.0, 30.0), 1)
                _rad_source = random.choice(["reactor_micro_leak", "shield_emitter_leak"])
                _sandbox_radiation_active = True
                events.append({
                    "type": "sandbox_radiation",
                    "room_id": _rad_room,
                    "amount": _rad_amount,
                    "source": _rad_source,
                })
        _timers["sandbox_radiation"] = random.uniform(*SANDBOX_RADIATION_INTERVAL) * _evt_mult

    # --- Sandbox structural — micrometeorite / fatigue stress (HC) --------
    if _timers.get("sandbox_structural", 1.0) <= 0.0:
        interior = getattr(world.ship, "interior", None)
        if interior is not None:
            import server.game_loop_hazard_control as _glhc2
            _sections = _glhc2.get_sections()
            # Don't stress sections already below 30%.
            _struct_candidates = [
                sid for sid, sec in _sections.items()
                if not sec.collapsed and sec.integrity > 30.0
            ]
            if _struct_candidates:
                _target_section = random.choice(_struct_candidates)
                _sec = _sections[_target_section]
                _struct_amount = round(random.uniform(5.0, 15.0), 1)
                # Pick a room in this section for the event payload.
                _struct_room = _sec.room_ids[0] if _sec.room_ids else ""
                events.append({
                    "type": "sandbox_structural",
                    "room_id": _struct_room,
                    "section_id": _target_section,
                    "amount": _struct_amount,
                })
        _timers["sandbox_structural"] = random.uniform(*SANDBOX_STRUCTURAL_INTERVAL) * _evt_mult

    # --- Sandbox intel update (Operations) --------------------------------
    if _timers.get("sandbox_intel_update", 1.0) <= 0.0:
        if world.enemies:
            _target_enemy = random.choice(world.enemies)
            _threat = "high" if _target_enemy.hull > 80 else ("medium" if _target_enemy.hull > 40 else "low")
            events.append({
                "type": "sandbox_intel_update",
                "enemy_id": _target_enemy.id,
                "assessment": {
                    "target": _target_enemy.id,
                    "type": getattr(_target_enemy, "enemy_type", "unknown"),
                    "hull": round(_target_enemy.hull, 1),
                    "threat_level": _threat,
                    "bearing": round(math.degrees(math.atan2(
                        _target_enemy.y - world.ship.y,
                        _target_enemy.x - world.ship.x,
                    )) % 360, 1),
                    "range": round(math.hypot(
                        _target_enemy.x - world.ship.x,
                        _target_enemy.y - world.ship.y,
                    ), 0),
                    "recommendation": random.choice([
                        "Engage at range", "Close to weapons range",
                        "Recommend torpedo solution", "Monitor — low priority",
                    ]),
                },
            })
        else:
            _sector_status = random.choice([
                "Sector clear — no hostile contacts",
                "Increased pirate activity reported in adjacent sector",
                "Long-range sensors nominal — no anomalies detected",
                "Civilian traffic in sector — standard watch",
                "Federation patrol route overlaps current heading",
            ])
            events.append({
                "type": "sandbox_intel_update",
                "enemy_id": None,
                "assessment": {
                    "sector_status": _sector_status,
                    "threat_level": "low",
                },
            })
        _timers["sandbox_intel_update"] = random.uniform(*SANDBOX_INTEL_UPDATE_INTERVAL) * _evt_mult

    # --- Sandbox ops alert — coordination prompt (Operations) -------------
    if _timers.get("sandbox_ops_alert", 1.0) <= 0.0:
        # Pick a contextually appropriate alert based on game state.
        _applicable: list[dict] = []
        for tpl in _OPS_ALERT_TEMPLATES:
            cond = tpl["condition"]
            if cond == "enemies" and len(world.enemies) >= 2:
                _applicable.append(tpl)
            elif cond == "low_power":
                _avg_power = sum(
                    s.power for s in world.ship.systems.values()
                ) / max(1, len(world.ship.systems))
                if _avg_power < 60:
                    _applicable.append(tpl)
            elif cond == "damage" and world.ship.hull < world.ship.hull_max * 0.7:
                _applicable.append(tpl)
            elif cond == "crew_low":
                _avg_cf = sum(
                    d.crew_factor for d in world.ship.crew.decks.values()
                ) / max(1, len(world.ship.crew.decks))
                if _avg_cf < 0.8:
                    _applicable.append(tpl)
            elif cond == "general":
                _applicable.append(tpl)

        if _applicable:
            _chosen_alert = random.choice(_applicable)
            events.append({
                "type": "sandbox_ops_alert",
                "alert": _chosen_alert["alert"],
                "severity": _chosen_alert["severity"],
                "source": _chosen_alert["source"],
            })
        _timers["sandbox_ops_alert"] = random.uniform(*SANDBOX_OPS_ALERT_INTERVAL) * _evt_mult

    # --- Sandbox resource pressure (Quartermaster) ------------------------
    if _timers.get("sandbox_resource_pressure", 1.0) <= 0.0:
        _resources = getattr(world.ship, "resources", None)
        if _resources is not None:
            # Check all resource types for low levels.
            _low_resources = []
            for _rtype in ("fuel", "ammunition", "suppressant", "repair_materials",
                           "medical_supplies", "provisions", "drone_fuel", "drone_parts"):
                _frac = _resources.fraction(_rtype)
                if _frac < 0.5:
                    _low_resources.append((_rtype, _frac))

            if _low_resources:
                _worst = min(_low_resources, key=lambda x: x[1])
                _rname, _rfrac = _worst
                if _rfrac < 0.1:
                    _msg = f"CRITICAL: {_rname} depleted — immediate resupply required"
                elif _rfrac < 0.25:
                    _msg = f"WARNING: {_rname} below 25% — recommend conservation"
                else:
                    _msg = f"ADVISORY: {_rname} below 50% — monitor consumption"
                events.append({
                    "type": "sandbox_resource_pressure",
                    "resource": _rname,
                    "level": round(_rfrac, 2),
                    "message": _msg,
                })
            else:
                # All resources healthy — generate consumption forecast.
                _forecast_resource = random.choice(["fuel", "ammunition", "suppressant"])
                _frac = _resources.fraction(_forecast_resource)
                events.append({
                    "type": "sandbox_resource_pressure",
                    "resource": _forecast_resource,
                    "level": round(_frac, 2),
                    "message": f"Resource status: {_forecast_resource} at {round(_frac * 100)}%",
                })
        _timers["sandbox_resource_pressure"] = random.uniform(*SANDBOX_RESOURCE_PRESSURE_INTERVAL) * _evt_mult

    # --- Sandbox trade opportunity (Quartermaster) -------------------------
    if _timers.get("sandbox_trade_opportunity", 1.0) <= 0.0:
        # Expire old offers.
        _active_trade_offers[:] = [
            o for o in _active_trade_offers if o.get("_remaining", 0) > 0
        ]
        _entity_counter += 1
        _offer_tpl = random.choice(_TRADE_OFFERS)
        _offer = {
            "id": f"sb_trade_{_entity_counter}",
            "give_type": _offer_tpl["give_type"],
            "give_amount": _offer_tpl["give_amount"],
            "get_type": _offer_tpl["get_type"],
            "get_amount": _offer_tpl["get_amount"],
            "label": _offer_tpl["label"],
            "_remaining": TRADE_OFFER_EXPIRY,
        }
        _active_trade_offers.append(_offer)
        events.append({
            "type": "sandbox_trade_opportunity",
            "offer": {k: v for k, v in _offer.items() if not k.startswith("_")},
        })
        _timers["sandbox_trade_opportunity"] = random.uniform(*SANDBOX_TRADE_OPPORTUNITY_INTERVAL) * _evt_mult

    # --- EW intercept — intercepted enemy comms (EW + Comms) --------------
    if _timers.get("sandbox_ew_intercept", 1.0) <= 0.0:
        _ew_faction = random.choice(["imperial", "rebel", "pirate"])
        _ew_intel = random.choice([
            "Intercepted fleet deployment orders — enemy reinforcements inbound",
            "Decoded supply manifest — munitions depot at bearing 270",
            "Captured patrol schedule — gap in coverage at 0300",
            "Encrypted communication — possible ambush coordinates",
            "Distorted signal — enemy fleet massing in adjacent sector",
        ])
        events.append({
            "type": "sandbox_ew_intercept",
            "faction": _ew_faction,
            "intel": _ew_intel,
        })
        _timers["sandbox_ew_intercept"] = random.uniform(*SANDBOX_EW_INTERCEPT_INTERVAL) * _evt_mult

    # --- Flight Ops contact — drone detects something (Flight Ops) --------
    if _timers.get("sandbox_flight_contact", 1.0) <= 0.0:
        angle = random.uniform(0.0, 360.0)
        dist  = random.uniform(10_000.0, 25_000.0)
        _fc_x = max(5_000.0, min(world.width  - 5_000.0,
                                  world.ship.x + math.cos(math.radians(angle)) * dist))
        _fc_y = max(5_000.0, min(world.height - 5_000.0,
                                  world.ship.y + math.sin(math.radians(angle)) * dist))
        _entity_counter += 1
        events.append({
            "type":  "sandbox_flight_contact",
            "x":     round(_fc_x, 1),
            "y":     round(_fc_y, 1),
            "id":    f"sb_fc{_entity_counter}",
            "label": random.choice(FLIGHT_CONTACT_LABELS),
        })
        _timers["sandbox_flight_contact"] = random.uniform(*SANDBOX_FLIGHT_CONTACT_INTERVAL) * _evt_mult

    # --- Captain decision — situation requiring Captain choice ------------
    if _timers.get("sandbox_captain_decision", 1.0) <= 0.0:
        _decision_counter += 1
        _decision = random.choice(_CAPTAIN_DECISIONS)
        events.append({
            "type": "sandbox_captain_decision",
            "decision_id": f"sb_dec_{_decision_counter}",
            "prompt": _decision["prompt"],
            "options": list(_decision["options"]),
        })
        _timers["sandbox_captain_decision"] = random.uniform(*SANDBOX_CAPTAIN_DECISION_INTERVAL) * _evt_mult

    # --- Standalone medical event (Medical) --------------------------------
    if _timers.get("sandbox_medical_event", 1.0) <= 0.0:
        _med_event = random.choice(_MEDICAL_EVENT_CAUSES)
        _med_deck = random.choice(CREW_DECKS)
        events.append({
            "type": "sandbox_medical_event",
            "cause": _med_event["cause"],
            "deck": _med_deck,
            "severity_scale": _med_event["severity_scale"],
            "label": _med_event["label"],
        })
        _timers["sandbox_medical_event"] = random.uniform(*SANDBOX_MEDICAL_EVENT_INTERVAL) * _evt_mult

    # --- Tick trade offer timers ------------------------------------------
    for _offer in _active_trade_offers:
        _offer["_remaining"] = _offer.get("_remaining", 0) - dt

    # Cap concurrent events per tick based on difficulty.event_overlap_max
    if len(events) > _overlap_max:
        events = events[:_overlap_max]

    return events



def get_mission_type_counts() -> dict[str, int]:
    """Return a copy of the per-session mission type generation counts."""
    return dict(_mission_type_counts)


def setup_world(world: "World") -> None:
    """Populate the sandbox world with persistent stations and hazard zones.

    Adds:
      - A friendly repair dock (``sb_port``) for docking and resupply.
      - A derelict station (``sb_derelict``) for exploration.
      - A nebula hazard zone and an asteroid field for environmental effects.

    Call once per session immediately after ``reset(active=True)``.
    No-op if the sandbox is not active.
    """
    if not _active:
        return

    from server.models.world import (
        Station,
        spawn_hazard,
        STATION_TYPE_SERVICES,
        STATION_TYPE_HULL,
        STATION_TYPE_SHIELDS,
    )

    # Friendly repair dock — always present, full services, transponder broadcasting.
    world.stations.append(Station(
        id="sb_port",
        x=50000.0,
        y=20000.0,
        name="Way Station Alpha",
        station_type="repair_dock",
        faction="friendly",
        services=list(STATION_TYPE_SERVICES["repair_dock"]),
        docking_range=4000.0,
        docking_ports=2,
        transponder_active=True,
        shields=STATION_TYPE_SHIELDS["repair_dock"],
        shields_max=STATION_TYPE_SHIELDS["repair_dock"],
        hull=STATION_TYPE_HULL["repair_dock"],
        hull_max=STATION_TYPE_HULL["repair_dock"],
    ))

    # Derelict — requires exploration; no services, hidden until scanned.
    world.stations.append(Station(
        id="sb_derelict",
        x=78000.0,
        y=72000.0,
        name="Derelict: Wrecked Freighter",
        station_type="derelict",
        faction="none",
        services=[],
        docking_range=3000.0,
        docking_ports=1,
        transponder_active=False,
        shields=STATION_TYPE_SHIELDS["derelict"],
        shields_max=STATION_TYPE_SHIELDS["derelict"],
        hull=STATION_TYPE_HULL["derelict"],
        hull_max=STATION_TYPE_HULL["derelict"],
        requires_scan=True,
    ))

    # Environmental hazard variety for sandbox sector.
    world.hazards.append(spawn_hazard(
        "sb_nebula_1", 22000.0, 68000.0, 14000.0, "nebula", "Sensor Nebula",
    ))
    world.hazards.append(spawn_hazard(
        "sb_asteroids_1", 72000.0, 32000.0, 10000.0, "asteroid_field", "Rock Field",
    ))
