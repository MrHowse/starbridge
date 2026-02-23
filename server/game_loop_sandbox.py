"""Sandbox Activity Generator.

Periodically generates events across all station domains so that every
role has meaningful work during free-play and solo-play sessions.
Only active when mission_id == "sandbox".

Events returned from tick():
  {"type": "spawn_enemy",   "enemy_type": str, "x": float, "y": float, "id": str}
  {"type": "system_damage", "system": str, "amount": float}
  {"type": "crew_casualty", "deck": str, "count": int}
  {"type": "start_boarding","intruders": list[dict]}
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
BOARDING_INTERVAL:      tuple[float, float] = (120.0, 180.0)

INCOMING_TRANSMISSION_INTERVAL: tuple[float, float] = (90.0,  120.0)
HULL_MICRO_DAMAGE_INTERVAL:     tuple[float, float] = (120.0, 180.0)
SENSOR_ANOMALY_INTERVAL:        tuple[float, float] = (90.0,  150.0)
DRONE_OPPORTUNITY_INTERVAL:     tuple[float, float] = (120.0, 180.0)
ENEMY_JAMMING_INTERVAL:         tuple[float, float] = (180.0, 240.0)
DISTRESS_SIGNAL_INTERVAL:       tuple[float, float] = (180.0, 300.0)

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

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_active: bool = False
_timers: dict[str, float] = {}
_entity_counter: int = 0   # offset counter for unique IDs

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset(active: bool = False) -> None:
    """Reset sandbox scheduler.  Pass active=True to start the scheduler."""
    global _active, _entity_counter
    _active = active
    _entity_counter = 1000    # offset well above mission-spawned entity IDs
    _timers.clear()
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


def is_active() -> bool:
    """Return True if the sandbox scheduler is running."""
    return _active


def tick(world: "World", dt: float, difficulty: object | None = None) -> list[dict]:
    """Advance all timers by *dt* seconds.  Return event dicts to process.

    *difficulty* — when provided, scales event intervals and boarding frequency.
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
            enemy_type = random.choice(ENEMY_TYPE_POOL)
            angle = random.uniform(0.0, 360.0)
            dist  = random.uniform(SPAWN_DIST_MIN, SPAWN_DIST_MAX)
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
        events.append({
            "type": "start_boarding",
            "intruders": [
                {"id": f"sb_i{_entity_counter}",     "room_id": "conn", "objective_id": None},
                {"id": f"sb_i{_entity_counter + 1}", "room_id": "conn", "objective_id": None},
            ],
        })
        _entity_counter += 1
        _timers["boarding"] = random.uniform(*BOARDING_INTERVAL) * _evt_mult / max(0.1, _brd_mult)

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
