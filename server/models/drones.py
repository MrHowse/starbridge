"""
Drone Models — v0.06.5 Flight Ops Overhaul.

Six drone types (scout, combat, rescue, survey, ecm_drone, decoy) each with
distinct stats, callsign pools, and capabilities.  Decoys are expendable
fire-and-forget items, not recoverable drones.

Ship class determines the drone complement via DRONE_COMPLEMENT.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DRONE_STATUSES = (
    "hangar", "launching", "active", "rtb", "recovering",
    "emergency", "lost", "destroyed",
    "refuelling", "rearming", "maintenance",
)

DRONE_TYPES = ("scout", "combat", "rescue", "survey", "ecm_drone")

AI_MODES = ("manual", "semi_auto", "autonomous")

AI_BEHAVIOURS = (
    "patrol", "escort", "engage", "evade", "search", "loiter",
)

ENGAGEMENT_RULES = ("weapons_free", "weapons_tight", "weapons_hold")

# Base ship speed used for relative drone speeds.
BASE_SHIP_SPEED = 250.0  # world units / second (frigate baseline)

# ---------------------------------------------------------------------------
# Drone type parameters
# ---------------------------------------------------------------------------

CALLSIGN_POOLS: dict[str, list[str]] = {
    "scout":     ["Hawk", "Eagle", "Owl", "Falcon", "Kite", "Harrier"],
    "combat":    ["Fang", "Sabre", "Viper", "Talon", "Reaper", "Striker"],
    "rescue":    ["Angel", "Mercy", "Haven", "Guardian", "Lifeline", "Shepherd"],
    "survey":    ["Compass", "Atlas", "Pathfinder", "Cartographer", "Seeker", "Surveyor"],
    "ecm_drone": ["Ghost", "Phantom", "Shadow", "Wraith", "Spectre", "Mirage"],
}

DRONE_TYPE_PARAMS: dict[str, dict[str, Any]] = {
    "scout": {
        "max_speed_mult": 1.5,          # × BASE_SHIP_SPEED
        "hull": 30.0,
        "fuel_consumption": 0.8,        # % per second
        "sensor_range": 25_000.0,
        "sensor_resolution": 0.7,
        "weapon_damage": 0.0,
        "weapon_range": 0.0,
        "ammo": 0.0,
        "cargo_capacity": 0,
        "ecm_strength": 0.0,
        "loiter_radius": 3000.0,
    },
    "combat": {
        "max_speed_mult": 1.2,
        "hull": 60.0,
        "fuel_consumption": 1.2,
        "sensor_range": 10_000.0,
        "sensor_resolution": 0.3,
        "weapon_damage": 4.0,
        "weapon_range": 10_000.0,
        "ammo": 100.0,
        "cargo_capacity": 0,
        "ecm_strength": 0.0,
        "loiter_radius": 2000.0,
    },
    "rescue": {
        "max_speed_mult": 0.8,
        "hull": 80.0,
        "fuel_consumption": 1.0,
        "sensor_range": 8_000.0,
        "sensor_resolution": 0.3,
        "weapon_damage": 0.0,
        "weapon_range": 0.0,
        "ammo": 0.0,
        "cargo_capacity": 6,
        "ecm_strength": 0.0,
        "loiter_radius": 2000.0,
    },
    "survey": {
        "max_speed_mult": 1.0,
        "hull": 40.0,
        "fuel_consumption": 0.9,
        "sensor_range": 15_000.0,
        "sensor_resolution": 0.9,
        "weapon_damage": 0.0,
        "weapon_range": 0.0,
        "ammo": 0.0,
        "cargo_capacity": 0,
        "ecm_strength": 0.0,
        "loiter_radius": 2500.0,
        "buoy_capacity": 3,
    },
    "ecm_drone": {
        "max_speed_mult": 1.4,
        "hull": 25.0,
        "fuel_consumption": 1.5,
        "sensor_range": 8_000.0,
        "sensor_resolution": 0.2,
        "weapon_damage": 0.0,
        "weapon_range": 0.0,
        "ammo": 0.0,
        "cargo_capacity": 0,
        "ecm_strength": 0.4,
        "loiter_radius": 2000.0,
    },
}

# Per ship class: {drone_type: count, ...}
DRONE_COMPLEMENT: dict[str, dict[str, int]] = {
    "scout":        {"scout": 1, "combat": 1},
    "corvette":     {"scout": 1, "combat": 1, "rescue": 1},
    "frigate":      {"scout": 1, "combat": 2, "rescue": 1},
    "cruiser":      {"scout": 2, "combat": 2, "rescue": 1, "survey": 1},
    "battleship":   {"scout": 2, "combat": 3, "rescue": 1, "survey": 1, "ecm_drone": 1},
    "medical_ship": {"scout": 1, "rescue": 3},
    "carrier":      {"scout": 3, "combat": 4, "rescue": 2, "survey": 2, "ecm_drone": 1},
}

# Hangar slot counts per ship class.
HANGAR_SLOTS: dict[str, int] = {
    "scout": 2, "corvette": 3, "frigate": 4,
    "cruiser": 6, "battleship": 8, "medical_ship": 4, "carrier": 12,
}

# Decoy stock per ship class.
DECOY_STOCK: dict[str, int] = {
    "scout": 2, "corvette": 2, "frigate": 3,
    "cruiser": 3, "battleship": 4, "medical_ship": 2, "carrier": 4,
}

# Decoy parameters.
DECOY_LIFETIME: float = 30.0            # seconds
DECOY_SENSOR_ACCURACY_THRESHOLD = 0.7   # enemies below this accuracy may target decoy

# Safety margin for bingo fuel calculation.
BINGO_FUEL_SAFETY_MARGIN = 0.2          # 20% extra over calculated return fuel

# Damage thresholds affecting performance.
HULL_SPEED_PENALTY_THRESHOLD = 75.0     # hull < 75% → 10% speed loss
HULL_SENSOR_PENALTY_THRESHOLD = 50.0    # hull < 50% → 25% sensor/weapon loss
HULL_CRITICAL_THRESHOLD = 25.0          # hull < 25% → erratic flight

# Turn rate for drone heading changes.
DRONE_TURN_RATE = 120.0  # degrees per second

# Pickup time for rescue drones.
RESCUE_PICKUP_TIME = 15.0  # seconds per survivor


# ---------------------------------------------------------------------------
# Drone dataclass
# ---------------------------------------------------------------------------


@dataclass
class Drone:
    """A recoverable autonomous drone craft."""

    id: str                                         # "drone_s1", "drone_c2"
    callsign: str = ""                              # "Hawk", "Fang"
    drone_type: str = "scout"

    # Physical state
    position: tuple[float, float] = (0.0, 0.0)
    heading: float = 0.0                            # degrees
    speed: float = 0.0
    max_speed: float = 0.0                          # set by type
    hull: float = 100.0                             # current HP
    max_hull: float = 100.0                         # set by type

    # Resources
    fuel: float = 100.0                             # 0-100 %
    fuel_consumption: float = 0.8                   # % per second
    ammo: float = 0.0                               # 0-100 %

    # Status
    status: str = "hangar"
    mission_type: str | None = None                 # current mission type
    waypoints: list[tuple[float, float]] = field(default_factory=list)
    waypoint_index: int = 0
    loiter_point: tuple[float, float] | None = None
    loiter_radius: float = 2000.0

    # Hangar state
    hangar_slot: int | None = None
    launch_tube: int | None = None
    recovery_queue_pos: int | None = None
    turnaround_time: float = 0.0                    # total seconds for turnaround
    turnaround_remaining: float = 0.0               # countdown

    # Turnaround sub-tasks
    needs_refuel: bool = False
    needs_rearm: bool = False
    needs_repair: bool = False
    refuel_progress: float = 0.0                    # 0-100 %
    rearm_progress: float = 0.0
    repair_progress: float = 0.0

    # Capabilities (set by type)
    sensor_range: float = 0.0
    sensor_resolution: float = 0.0
    weapon_damage: float = 0.0
    weapon_range: float = 0.0
    cargo_capacity: int = 0
    cargo_current: int = 0
    ecm_strength: float = 0.0
    buoy_capacity: int = 0
    buoys_remaining: int = 0

    # Autonomy
    ai_mode: str = "semi_auto"
    ai_behaviour: str = "loiter"
    engagement_rules: str = "weapons_tight"
    contact_of_interest: str | None = None
    escort_target: str | None = None
    threat_detected: str | None = None

    # Tracking
    known_contacts: set[str] = field(default_factory=set)
    pickup_timer: float = 0.0
    bingo_acknowledged: bool = False
    damage_dealt: float = 0.0
    contacts_found: int = 0
    survivors_rescued: int = 0
    attack_cooldown_remaining: float = 0.0

    # -----------------------------------------------------------------------
    # Properties
    # -----------------------------------------------------------------------

    @property
    def fuel_seconds_remaining(self) -> float:
        """Estimated seconds of fuel remaining at current consumption."""
        if self.fuel_consumption <= 0:
            return float("inf")
        return self.fuel / self.fuel_consumption

    @property
    def fuel_minutes_remaining(self) -> float:
        return self.fuel_seconds_remaining / 60.0

    def is_bingo_fuel(self, ship_x: float, ship_y: float) -> bool:
        """Check if fuel is at minimum required to return to ship safely."""
        if self.status == "hangar":
            return False
        dx = self.position[0] - ship_x
        dy = self.position[1] - ship_y
        dist = math.sqrt(dx * dx + dy * dy)
        if self.max_speed <= 0:
            return True
        time_to_return = dist / self.max_speed
        fuel_to_return = time_to_return * self.fuel_consumption
        safety = fuel_to_return * BINGO_FUEL_SAFETY_MARGIN
        return self.fuel <= fuel_to_return + safety

    @property
    def hull_percent(self) -> float:
        """Hull as percentage of max."""
        if self.max_hull <= 0:
            return 0.0
        return (self.hull / self.max_hull) * 100.0

    @property
    def effective_max_speed(self) -> float:
        """Max speed adjusted for hull damage."""
        spd = self.max_speed
        if self.hull_percent < HULL_SPEED_PENALTY_THRESHOLD:
            spd *= 0.9
        return spd

    @property
    def effective_sensor_range(self) -> float:
        """Sensor range adjusted for hull damage."""
        r = self.sensor_range
        if self.hull_percent < HULL_SENSOR_PENALTY_THRESHOLD:
            r *= 0.75
        return r

    @property
    def effective_weapon_damage(self) -> float:
        """Weapon damage adjusted for hull damage."""
        d = self.weapon_damage
        if self.hull_percent < HULL_SENSOR_PENALTY_THRESHOLD:
            d *= 0.75
        return d

    @property
    def is_critical(self) -> bool:
        """True when hull is in critical condition."""
        return self.hull_percent < HULL_CRITICAL_THRESHOLD and self.hull > 0

    @property
    def is_destroyed(self) -> bool:
        return self.hull <= 0 or self.status == "destroyed"


# ---------------------------------------------------------------------------
# Decoy dataclass
# ---------------------------------------------------------------------------


@dataclass
class Decoy:
    """Expendable decoy that mimics the ship's sensor signature."""

    id: str
    position: tuple[float, float] = (0.0, 0.0)
    heading: float = 0.0
    lifetime: float = DECOY_LIFETIME      # seconds remaining
    active: bool = True


# ---------------------------------------------------------------------------
# Sensor buoy dataclass
# ---------------------------------------------------------------------------


@dataclass
class SensorBuoy:
    """Permanent sensor post deployed by survey drones."""

    id: str
    position: tuple[float, float] = (0.0, 0.0)
    sensor_range: float = 15_000.0
    deployed_by: str = ""                  # drone callsign
    active: bool = True


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def create_drone(
    drone_id: str,
    drone_type: str,
    callsign: str,
    hangar_slot: int | None = None,
) -> Drone:
    """Create a drone with type-appropriate stats."""
    params = DRONE_TYPE_PARAMS.get(drone_type)
    if params is None:
        raise ValueError(f"Unknown drone type: {drone_type!r}")

    max_speed = BASE_SHIP_SPEED * params["max_speed_mult"]
    buoy_cap = params.get("buoy_capacity", 0)

    return Drone(
        id=drone_id,
        callsign=callsign,
        drone_type=drone_type,
        max_speed=max_speed,
        hull=params["hull"],
        max_hull=params["hull"],
        fuel=100.0,
        fuel_consumption=params["fuel_consumption"],
        ammo=params["ammo"],
        sensor_range=params["sensor_range"],
        sensor_resolution=params["sensor_resolution"],
        weapon_damage=params["weapon_damage"],
        weapon_range=params["weapon_range"],
        cargo_capacity=params["cargo_capacity"],
        ecm_strength=params["ecm_strength"],
        loiter_radius=params["loiter_radius"],
        buoy_capacity=buoy_cap,
        buoys_remaining=buoy_cap,
        hangar_slot=hangar_slot,
    )


def create_ship_drones(
    ship_class_id: str,
    complement_override: dict[str, int] | None = None,
) -> list[Drone]:
    """Generate the full drone complement for a ship class.

    Each drone gets a sequential ID (``drone_s1``, ``drone_c2``, etc.)
    and a unique callsign from its type's pool.

    If complement_override is provided, it replaces the default complement.
    """
    complement = complement_override if complement_override is not None else DRONE_COMPLEMENT.get(ship_class_id, {})
    drones: list[Drone] = []

    # Track callsign usage per type to assign unique names.
    type_counters: dict[str, int] = {}
    slot = 0

    for dtype, count in complement.items():
        pool = CALLSIGN_POOLS.get(dtype, [])
        prefix = dtype[0]  # s, c, r, u (survey), e
        if dtype == "survey":
            prefix = "u"
        elif dtype == "ecm_drone":
            prefix = "e"

        for _ in range(count):
            idx = type_counters.get(dtype, 0)
            type_counters[dtype] = idx + 1
            drone_id = f"drone_{prefix}{idx + 1}"
            callsign = pool[idx % len(pool)] if pool else f"{dtype}_{idx + 1}"
            drones.append(create_drone(drone_id, dtype, callsign, hangar_slot=slot))
            slot += 1

    return drones


def get_hangar_slots(ship_class_id: str) -> int:
    """Return hangar slot count for a ship class."""
    return HANGAR_SLOTS.get(ship_class_id, 4)


def get_decoy_stock(ship_class_id: str) -> int:
    """Return initial decoy stock for a ship class."""
    return DECOY_STOCK.get(ship_class_id, 2)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def serialise_drone(drone: Drone) -> dict:
    """Serialise a drone to a JSON-compatible dict."""
    return {
        "id": drone.id,
        "callsign": drone.callsign,
        "drone_type": drone.drone_type,
        "position": list(drone.position),
        "heading": drone.heading,
        "speed": drone.speed,
        "max_speed": drone.max_speed,
        "hull": drone.hull,
        "max_hull": drone.max_hull,
        "fuel": drone.fuel,
        "fuel_consumption": drone.fuel_consumption,
        "ammo": drone.ammo,
        "status": drone.status,
        "mission_type": drone.mission_type,
        "waypoints": [list(wp) for wp in drone.waypoints],
        "waypoint_index": drone.waypoint_index,
        "loiter_point": list(drone.loiter_point) if drone.loiter_point else None,
        "loiter_radius": drone.loiter_radius,
        "hangar_slot": drone.hangar_slot,
        "turnaround_remaining": drone.turnaround_remaining,
        "needs_refuel": drone.needs_refuel,
        "needs_rearm": drone.needs_rearm,
        "needs_repair": drone.needs_repair,
        "refuel_progress": drone.refuel_progress,
        "rearm_progress": drone.rearm_progress,
        "repair_progress": drone.repair_progress,
        "sensor_range": drone.sensor_range,
        "sensor_resolution": drone.sensor_resolution,
        "weapon_damage": drone.weapon_damage,
        "weapon_range": drone.weapon_range,
        "cargo_capacity": drone.cargo_capacity,
        "cargo_current": drone.cargo_current,
        "ecm_strength": drone.ecm_strength,
        "buoy_capacity": drone.buoy_capacity,
        "buoys_remaining": drone.buoys_remaining,
        "ai_mode": drone.ai_mode,
        "ai_behaviour": drone.ai_behaviour,
        "engagement_rules": drone.engagement_rules,
        "contact_of_interest": drone.contact_of_interest,
        "escort_target": drone.escort_target,
        "bingo_acknowledged": drone.bingo_acknowledged,
        "damage_dealt": drone.damage_dealt,
        "contacts_found": drone.contacts_found,
        "survivors_rescued": drone.survivors_rescued,
        "attack_cooldown_remaining": drone.attack_cooldown_remaining,
    }


def deserialise_drone(data: dict) -> Drone:
    """Restore a drone from a serialised dict."""
    d = Drone(
        id=data["id"],
        callsign=data.get("callsign", ""),
        drone_type=data.get("drone_type", "scout"),
    )
    d.position = tuple(data.get("position", [0.0, 0.0]))
    d.heading = data.get("heading", 0.0)
    d.speed = data.get("speed", 0.0)
    d.max_speed = data.get("max_speed", 0.0)
    d.hull = data.get("hull", 100.0)
    d.max_hull = data.get("max_hull", 100.0)
    d.fuel = data.get("fuel", 100.0)
    d.fuel_consumption = data.get("fuel_consumption", 0.8)
    d.ammo = data.get("ammo", 0.0)
    d.status = data.get("status", "hangar")
    d.mission_type = data.get("mission_type")
    d.waypoints = [tuple(wp) for wp in data.get("waypoints", [])]
    d.waypoint_index = data.get("waypoint_index", 0)
    lp = data.get("loiter_point")
    d.loiter_point = tuple(lp) if lp else None
    d.loiter_radius = data.get("loiter_radius", 2000.0)
    d.hangar_slot = data.get("hangar_slot")
    d.turnaround_remaining = data.get("turnaround_remaining", 0.0)
    d.needs_refuel = data.get("needs_refuel", False)
    d.needs_rearm = data.get("needs_rearm", False)
    d.needs_repair = data.get("needs_repair", False)
    d.refuel_progress = data.get("refuel_progress", 0.0)
    d.rearm_progress = data.get("rearm_progress", 0.0)
    d.repair_progress = data.get("repair_progress", 0.0)
    d.sensor_range = data.get("sensor_range", 0.0)
    d.sensor_resolution = data.get("sensor_resolution", 0.0)
    d.weapon_damage = data.get("weapon_damage", 0.0)
    d.weapon_range = data.get("weapon_range", 0.0)
    d.cargo_capacity = data.get("cargo_capacity", 0)
    d.cargo_current = data.get("cargo_current", 0)
    d.ecm_strength = data.get("ecm_strength", 0.0)
    d.buoy_capacity = data.get("buoy_capacity", 0)
    d.buoys_remaining = data.get("buoys_remaining", 0)
    d.ai_mode = data.get("ai_mode", "semi_auto")
    d.ai_behaviour = data.get("ai_behaviour", "loiter")
    d.engagement_rules = data.get("engagement_rules", "weapons_tight")
    d.contact_of_interest = data.get("contact_of_interest")
    d.escort_target = data.get("escort_target")
    d.bingo_acknowledged = data.get("bingo_acknowledged", False)
    d.damage_dealt = data.get("damage_dealt", 0.0)
    d.contacts_found = data.get("contacts_found", 0)
    d.survivors_rescued = data.get("survivors_rescued", 0)
    d.attack_cooldown_remaining = data.get("attack_cooldown_remaining", 0.0)
    return d


def serialise_decoy(decoy: Decoy) -> dict:
    return {
        "id": decoy.id,
        "position": list(decoy.position),
        "heading": decoy.heading,
        "lifetime": decoy.lifetime,
        "active": decoy.active,
    }


def deserialise_decoy(data: dict) -> Decoy:
    return Decoy(
        id=data["id"],
        position=tuple(data.get("position", [0.0, 0.0])),
        heading=data.get("heading", 0.0),
        lifetime=data.get("lifetime", DECOY_LIFETIME),
        active=data.get("active", True),
    )


def serialise_buoy(buoy: SensorBuoy) -> dict:
    return {
        "id": buoy.id,
        "position": list(buoy.position),
        "sensor_range": buoy.sensor_range,
        "deployed_by": buoy.deployed_by,
        "active": buoy.active,
    }


def deserialise_buoy(data: dict) -> SensorBuoy:
    return SensorBuoy(
        id=data["id"],
        position=tuple(data.get("position", [0.0, 0.0])),
        sensor_range=data.get("sensor_range", 15_000.0),
        deployed_by=data.get("deployed_by", ""),
        active=data.get("active", True),
    )
