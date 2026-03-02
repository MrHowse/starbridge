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
DRONE_OPPORTUNITY_INTERVAL:     tuple[float, float] = (120.0, 180.0)
ENEMY_JAMMING_INTERVAL:         tuple[float, float] = (180.0, 240.0)
DISTRESS_SIGNAL_INTERVAL:       tuple[float, float] = (180.0, 300.0)

# Minor security events to keep the Security station busy between boardings.
SECURITY_EVENT_INTERVAL:        tuple[float, float] = (30.0,  60.0)

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

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset(active: bool = False) -> None:
    """Reset sandbox scheduler.  Pass active=True to start the scheduler."""
    global _active, _entity_counter, _first_mission_generated, _first_enemy_spawned
    _active = active
    _entity_counter = 1000    # offset well above mission-spawned entity IDs
    _timers.clear()
    _mission_type_counts.clear()
    _first_mission_generated = False
    _first_enemy_spawned = False
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


def is_active() -> bool:
    """Return True if the sandbox scheduler is running."""
    return _active


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

    global _entity_counter

    _evt_mult = getattr(difficulty, "event_interval_multiplier", 1.0) if difficulty else 1.0
    _brd_mult = getattr(difficulty, "boarding_frequency_multiplier", 1.0) if difficulty else 1.0

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
        events.append({"type": "crew_casualty", "deck": deck, "count": 1})
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

    # --- Hull micro-damage — micrometeorite strike (Damage Control) -------
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
