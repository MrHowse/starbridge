"""
World Model.

The World contains all entities in the 2D simulation space: the player ship
and (from Phase 4) enemy ships, stations, and projectiles.

The sector is 100,000 × 100,000 world units. The coordinate origin is the
top-left corner: x increases eastward, y increases southward. Heading 0° is
north (toward y=0), clockwise.
"""
from __future__ import annotations

import random as _rng_module
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Literal, Optional

if TYPE_CHECKING:
    from server.models.sector import SectorGrid, SectorFeature
    from server.models.interior import ShipInterior

_SHIELD_FREQUENCIES = ("alpha", "beta", "gamma", "delta")

from server.models.ship import Ship

# Sector dimensions in world units (100k × 100k).
SECTOR_WIDTH: float = 100_000.0
SECTOR_HEIGHT: float = 100_000.0


# ---------------------------------------------------------------------------
# Enemy type parameters
# ---------------------------------------------------------------------------

#: Per-type stats: hull, speed, detect_range, weapon_range, arc_deg,
#:                 beam_dmg, beam_cooldown, flee_threshold (fraction of max hull).
ENEMY_TYPE_PARAMS: dict[str, dict] = {
    "fighter": {
        "hull":          20.0,
        "speed":        400.0,
        "detect_range":  5_000.0,
        "weapon_range":  2_000.0,
        "arc_deg":         40.0,
        "beam_dmg":         4.0,
        "beam_cooldown":    1.0,
        "flee_threshold":   0.0,   # fighters never flee
        "target_profile":   0.4,   # v0.07: small, fast, hard to hit
    },
    "scout": {
        "hull":           40.0,
        "speed":         280.0,
        "detect_range": 15_000.0,
        "weapon_range":  4_000.0,
        "arc_deg":         40.0,
        "beam_dmg":         5.0,
        "beam_cooldown":    1.5,
        "flee_threshold":   0.30,
        "target_profile":   0.5,   # v0.07: small
    },
    "cruiser": {
        "hull":           70.0,
        "speed":         150.0,
        "detect_range": 12_000.0,
        "weapon_range":  6_000.0,
        "arc_deg":         40.0,
        "beam_dmg":        10.0,
        "beam_cooldown":    2.0,
        "flee_threshold":   0.20,
        "target_profile":   0.85,  # v0.07: large, easy to hit
    },
    "destroyer": {
        "hull":          100.0,
        "speed":         100.0,
        "detect_range": 20_000.0,
        "weapon_range": 10_000.0,
        "arc_deg":         30.0,
        "beam_dmg":        15.0,
        "beam_cooldown":    3.0,
        "flee_threshold":   0.15,
        "target_profile":   0.7,   # v0.07: medium-large
    },
}


# ---------------------------------------------------------------------------
# Entity dataclasses
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Station constants (v0.05e)
# ---------------------------------------------------------------------------

#: Services available at each station type.
STATION_TYPE_SERVICES: dict[str, list[str]] = {
    "military":    ["weapons_resupply", "hull_repair", "intel", "torpedo_resupply"],
    "civilian":    ["medical_facilities", "atmosphere", "crew_rest"],
    "trade_hub":   ["weapons_resupply", "hull_repair", "medical_facilities", "crew_rest",
                    "torpedo_resupply", "sensor_upgrade"],
    "research":    ["sensor_upgrade", "data_package"],
    "repair_dock": ["hull_repair", "system_repair", "atmospheric_resupply"],
    "derelict":    [],
    "enemy":       [],
}

#: Base hull values per station type.
STATION_TYPE_HULL: dict[str, float] = {
    "military":    600.0,
    "civilian":    300.0,
    "trade_hub":   400.0,
    "research":    200.0,
    "repair_dock": 500.0,
    "derelict":    100.0,
    "enemy":       800.0,
}

#: Starting shield values per station type (0 = unshielded).
STATION_TYPE_SHIELDS: dict[str, float] = {
    "military":    100.0,
    "civilian":      0.0,
    "trade_hub":    50.0,
    "research":      0.0,
    "repair_dock":  50.0,
    "derelict":      0.0,
    "enemy":       150.0,
}

#: SectorFeature types that materialise as Station entities in the world.
STATION_FEATURE_TYPES: frozenset[str] = frozenset({
    "friendly_station", "enemy_station", "outpost",
    "derelict", "research_station", "repair_dock", "trade_hub",
})

#: Mapping from sector feature type to (station_type, faction).
_FEATURE_TO_STATION: dict[str, dict[str, str]] = {
    "friendly_station": {"station_type": "military",    "faction": "friendly"},
    "enemy_station":    {"station_type": "enemy",       "faction": "hostile"},
    "outpost":          {"station_type": "military",    "faction": "friendly"},
    "derelict":         {"station_type": "derelict",    "faction": "none"},
    "research_station": {"station_type": "research",    "faction": "friendly"},
    "repair_dock":      {"station_type": "repair_dock", "faction": "friendly"},
    "trade_hub":        {"station_type": "trade_hub",   "faction": "neutral"},
}


# ---------------------------------------------------------------------------
# Enemy station defence components (v0.05i)
# ---------------------------------------------------------------------------


def _arc_covers(arc_start: float, arc_end: float, bearing: float) -> bool:
    """Return True if *bearing* (0–360) falls in the clockwise arc [start, end]."""
    b = bearing % 360.0
    s = arc_start % 360.0
    e = arc_end % 360.0
    if s <= e:
        return s <= b <= e
    # Arc wraps around north (e.g. 315 → 45)
    return b >= s or b <= e


@dataclass
class StationComponent:
    """Base class for a destructible component on an enemy station."""

    id: str
    hp: float
    hp_max: float

    @property
    def active(self) -> bool:
        return self.hp > 0.0


@dataclass
class ShieldArc(StationComponent):
    """Shield generator covering a directional arc around the station."""

    arc_start: float = 0.0   # clockwise from north, degrees
    arc_end: float = 180.0


@dataclass
class Turret(StationComponent):
    """Auto-firing beam turret on a station."""

    facing: float = 0.0        # fixed heading in degrees
    arc_deg: float = 50.0      # ± half-width of firing arc
    weapon_range: float = 8_000.0
    beam_dmg: float = 8.0
    beam_cooldown: float = 3.0
    cooldown_timer: float = 0.0


@dataclass
class TorpedoLauncher(StationComponent):
    """Torpedo launcher on a station."""

    launch_cooldown: float = 15.0
    cooldown_timer: float = 0.0


@dataclass
class FighterBay(StationComponent):
    """Fighter bay that periodically launches fighter craft."""

    launch_cooldown: float = 30.0
    cooldown_timer: float = 0.0
    fighters_in_bay: int = 4


@dataclass
class SensorArray(StationComponent):
    """Sensor array — calls reinforcements when active and not jammed."""

    jammed: bool = False
    distress_sent: bool = False


@dataclass
class StationReactor(StationComponent):
    """Reactor core — degraded power reduces turret effectiveness."""
    pass


@dataclass
class EnemyStationDefenses:
    """All defensive components of a hostile enemy station."""

    shield_arcs: list        # list[ShieldArc]
    turrets: list            # list[Turret]
    launchers: list          # list[TorpedoLauncher]
    fighter_bays: list       # list[FighterBay]
    sensor_array: SensorArray
    reactor: StationReactor
    garrison_count: int = 10
    station_interior: "ShipInterior | None" = None  # set by spawn_enemy_station

    def reactor_factor(self) -> float:
        """Power factor 0–1; debuffs turrets when reactor is damaged."""
        if self.reactor.hp_max <= 0.0:
            return 0.0
        return self.reactor.hp / self.reactor.hp_max

    def arc_is_shielded(self, bearing: float) -> bool:
        """True if an active shield generator covers *bearing*."""
        return any(
            g.active and _arc_covers(g.arc_start, g.arc_end, bearing)
            for g in self.shield_arcs
        )

    def all_components(self) -> list:
        """All components as a flat list (for ID lookup)."""
        result: list = (
            list(self.shield_arcs)
            + list(self.turrets)
            + list(self.launchers)
            + list(self.fighter_bays)
        )
        result.append(self.sensor_array)
        result.append(self.reactor)
        return result


@dataclass
class Station:
    """A space station entity in the sector (v0.05e)."""

    id: str
    x: float
    y: float
    name: str = ""
    station_type: str = "military"    # military | civilian | trade_hub | research | repair_dock | derelict | enemy
    faction: str = "friendly"         # friendly | neutral | hostile | none
    services: list[str] = field(default_factory=list)
    docking_range: float = 2_000.0
    docking_ports: int = 2
    transponder_active: bool = True   # broadcasts position; auto-reveals sector
    shields: float = 0.0
    shields_max: float = 0.0
    hull: float = 500.0
    hull_max: float = 500.0
    inventory: dict[str, int] = field(default_factory=dict)
    requires_scan: bool = False       # derelict/enemy stations hidden until sector is scanned
    # v0.05i — enemy station defensive systems (None for non-hostile stations)
    defenses: "EnemyStationDefenses | None" = None
    # v0.05j — set to True once the station has been boarded and captured
    captured: bool = False


@dataclass
class Asteroid:
    """An inert hazard in the sector. Causes hull damage on collision."""

    id: str
    x: float
    y: float
    radius: float = 1_000.0  # collision radius in world units


@dataclass
class Hazard:
    """A persistent environmental hazard in the sector.

    hazard_type values:
      ``nebula``         — sensor-obscuring cloud (visual + puzzle context).
      ``minefield``      — deals hull damage to ships inside (5 HP/s).
      ``gravity_well``   — caps ship velocity to 100 u/s when inside.
      ``radiation_zone`` — deals light hull damage (2 HP/s).
    """

    id: str
    x: float
    y: float
    radius: float = 10_000.0
    hazard_type: Literal["nebula", "minefield", "gravity_well", "radiation_zone"] = "nebula"
    label: Optional[str] = None   # display name (optional)


@dataclass
class Torpedo:
    """A short-lived projectile entity travelling through the sector."""

    id: str
    owner: str            # "player" or enemy entity_id
    x: float
    y: float
    heading: float
    velocity: float = 500.0
    distance_travelled: float = 0.0
    torpedo_type: str = "standard"   # standard | homing | ion | piercing | heavy | proximity | nuclear | experimental
    homing_target: Optional[str] = None   # entity_id of target (homing type only)
    MAX_RANGE: ClassVar[float] = 20_000.0


@dataclass
class Enemy:
    """An enemy vessel with its own AI state machine."""

    id: str
    type: Literal["fighter", "scout", "cruiser", "destroyer"]
    x: float
    y: float
    heading: float = 0.0
    velocity: float = 0.0
    hull: float = 100.0
    shield_front: float = 100.0
    shield_rear: float = 100.0
    ai_state: Literal["idle", "chase", "attack", "flee"] = "idle"
    beam_cooldown: float = 0.0    # seconds until next beam fire
    # Phase 5 — Science scanning
    scan_state: Literal["unknown", "scanned"] = "unknown"
    # v0.02g — EMP stun (ticks remaining; 0 = not stunned)
    stun_ticks: int = 0
    # v0.03k — Electronic Warfare
    jam_factor: float = 0.0          # 0.0 = not jammed; jam reduces beam damage fraction
    intrusion_stun_ticks: int = 0    # EW network intrusion: blocks beam fire when > 0
    # Gap closure — beam frequency vulnerability
    shield_frequency: str = ""       # alpha | beta | gamma | delta — matched by Weapons
    # v0.07 — target profile (hit probability modifier for incoming fire)
    target_profile: float = 1.0      # 0.0-1.0; lower = harder to hit


# ---------------------------------------------------------------------------
# Creature type parameters (v0.05k)
# ---------------------------------------------------------------------------

#: Per-type stats for space creatures.
CREATURE_TYPE_PARAMS: dict[str, dict] = {
    "void_whale": {
        "hull":           200.0,
        "speed":          100.0,
        "flee_range":   1_000.0,
        "study_duration":  60.0,
        "wake_duration":   10.0,
    },
    "rift_stalker": {
        "hull":           120.0,
        "speed":          350.0,
        "territory_radius": 12_000.0,
        "weapon_range":   3_000.0,
        "beam_dmg":         6.0,   # reduced: less punishing in territory encounters
        "beam_cooldown":    2.0,
        "regen_rate":       2.0,
        "sedate_duration": 120.0,
        "shield_bypass":    0.5,   # bio-energy attack: 50% bypasses shields
    },
    "hull_leech": {
        "hull":            30.0,
        "speed":          200.0,
        "attach_range":   500.0,
        "damage_per_interval": 3.0,
        "damage_interval":  5.0,
        "study_duration":  30.0,
        "shield_bypass":    1.0,   # attached to hull: 100% bypasses shields
    },
    "swarm": {
        "hull":            80.0,
        "speed":          250.0,
        "weapon_range":  6_000.0,
        "beam_dmg":         3.0,
        "beam_cooldown":    1.5,
        "swarm_range":   8_000.0,
        "study_duration":  45.0,
        "shield_bypass":    0.5,   # engulfing attack: 50% bypasses shields
    },
    "leviathan": {
        "hull":           800.0,
        "speed":           50.0,
        "weapon_range":  8_000.0,
        "beam_dmg":        25.0,
        "beam_cooldown":    5.0,
        "wake_range":   20_000.0,
        "comm_duration":   90.0,
        "study_duration":  60.0,
        "shield_bypass":    0.4,   # overwhelming energy: 40% bypasses shields
    },
}


@dataclass
class Creature:
    """A space creature entity in the sector (v0.05k)."""

    id: str
    creature_type: str  # "void_whale" | "rift_stalker" | "hull_leech" | "swarm" | "leviathan"
    x: float
    y: float
    heading: float = 0.0
    velocity: float = 0.0
    hull: float = 100.0
    hull_max: float = 100.0
    # AI behaviour state (type-specific; see creature_ai.py)
    behaviour_state: str = "idle"
    # Territorial creature data (rift stalker)
    territory_radius: float = 0.0
    territory_x: float = 0.0
    territory_y: float = 0.0
    # Science study and Comms communication progress (0–100)
    study_progress: float = 0.0
    communication_progress: float = 0.0
    # Sedation timer (rift stalker sedated path; 0 = not sedated)
    sedated_timer: float = 0.0
    # Void whale sensor wake
    wake_active: bool = False
    wake_timer: float = 0.0
    # Swarm adaptation state
    adaptation_state: str = "none"   # "none" | "spread" | "clustered"
    # Hull leech attachment
    attached: bool = False
    leech_damage_timer: float = 0.0
    # Combat timers
    beam_cooldown: float = 0.0
    regen_timer: float = 0.0
    # Sensor visibility (hull leech is hidden until BIO-scanned)
    detected: bool = True


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------


@dataclass
class World:
    """The full simulation state: sector bounds and all entities within it."""

    width: float = SECTOR_WIDTH
    height: float = SECTOR_HEIGHT

    # The player-controlled vessel.
    ship: Ship = field(default_factory=Ship)

    # Phase 4 entities — enemies and torpedoes.
    enemies: list[Enemy] = field(default_factory=list)
    torpedoes: list[Torpedo] = field(default_factory=list)

    # Phase 7 entities — friendly stations (Mission 2+) and asteroids (Mission 3).
    stations: list[Station] = field(default_factory=list)
    asteroids: list[Asteroid] = field(default_factory=list)

    # Session 2c entities — persistent hazard zones.
    hazards: list[Hazard] = field(default_factory=list)

    # v0.05b — sector grid overlay (fog of war, strategic map).  Optional:
    # None means the mission does not use the sector system.
    sector_grid: "SectorGrid | None" = None

    # v0.05k — space creature entities.
    creatures: list[Creature] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def spawn_station(station_id: str, x: float, y: float) -> Station:
    """Create a new Station at the given position with default military type."""
    hull = STATION_TYPE_HULL["military"]
    shld = STATION_TYPE_SHIELDS["military"]
    return Station(
        id=station_id, x=x, y=y,
        services=list(STATION_TYPE_SERVICES["military"]),
        hull=hull, hull_max=hull, shields=shld, shields_max=shld,
    )


def spawn_station_from_feature(feature: "SectorFeature", sector_name: str = "") -> Station:
    """Create a Station entity from a sector feature definition.

    ``feature.visible_without_scan`` determines whether the station broadcasts
    a transponder (i.e. is visible without active scanning).
    """
    mapping   = _FEATURE_TO_STATION.get(feature.type, {"station_type": "military", "faction": "friendly"})
    st_type   = mapping["station_type"]
    faction   = mapping["faction"]
    hull_max  = STATION_TYPE_HULL.get(st_type, 400.0)
    shld_max  = STATION_TYPE_SHIELDS.get(st_type, 0.0)
    services  = list(STATION_TYPE_SERVICES.get(st_type, []))
    transponder  = feature.visible_without_scan
    requires_scan = not feature.visible_without_scan
    return Station(
        id=feature.id,
        x=float(feature.position[0]),
        y=float(feature.position[1]),
        name=feature.name or sector_name,
        station_type=st_type,
        faction=faction,
        services=services,
        docking_range=2_000.0,
        docking_ports=2,
        transponder_active=transponder,
        shields=shld_max,
        shields_max=shld_max,
        hull=hull_max,
        hull_max=hull_max,
        inventory={},
        requires_scan=requires_scan,
    )


def spawn_hazard(
    hazard_id: str,
    x: float,
    y: float,
    radius: float = 10_000.0,
    hazard_type: Literal["nebula", "minefield", "gravity_well", "radiation_zone"] = "nebula",
    label: str | None = None,
) -> Hazard:
    """Create a new Hazard zone at the given position."""
    return Hazard(id=hazard_id, x=x, y=y, radius=radius, hazard_type=hazard_type, label=label)


def spawn_creature(creature_id: str, creature_type: str, x: float, y: float) -> Creature:
    """Create a new Creature at the given position with type-appropriate defaults."""
    params = CREATURE_TYPE_PARAMS[creature_type]
    hull = params["hull"]
    initial_state = "dormant" if creature_type == "leviathan" else "idle"
    detected = creature_type != "hull_leech"  # hull leech hidden until BIO-scanned
    territory_radius = params.get("territory_radius", 0.0)
    return Creature(
        id=creature_id,
        creature_type=creature_type,
        x=x,
        y=y,
        hull=hull,
        hull_max=hull,
        behaviour_state=initial_state,
        territory_radius=territory_radius,
        territory_x=x,
        territory_y=y,
        detected=detected,
    )


def spawn_enemy(type_: Literal["fighter", "scout", "cruiser", "destroyer"], x: float, y: float, entity_id: str) -> Enemy:
    """Create a new Enemy with type-appropriate starting stats."""
    params = ENEMY_TYPE_PARAMS[type_]
    # Fighters have no shields.
    init_shields = 0.0 if type_ == "fighter" else 100.0
    return Enemy(
        id=entity_id,
        type=type_,
        x=x,
        y=y,
        hull=params["hull"],
        shield_front=init_shields,
        shield_rear=init_shields,
        ai_state="idle",
        shield_frequency=_rng_module.choice(_SHIELD_FREQUENCIES),
        target_profile=params.get("target_profile", 1.0),
    )


def spawn_enemy_station(
    station_id: str,
    x: float,
    y: float,
    variant: str = "outpost",
) -> Station:
    """Create a hostile enemy station with full defensive components.

    ``variant`` is ``"outpost"`` (default) or ``"fortress"``:
      - outpost:  2 shield arcs, 4 turrets, 1 launcher, 1 fighter bay, 10 garrison
      - fortress: 4 shield arcs, 8 turrets, 2 launchers, 2 fighter bays, 20 garrison
    """
    from server.models.interior import make_station_interior  # local — avoids circular

    if variant == "fortress":
        n_gens = 4
        n_turrets = 8
        n_launchers = 2
        n_bays = 2
        hull_val = 1_200.0
        garrison = 20
    else:  # outpost
        n_gens = 2
        n_turrets = 4
        n_launchers = 1
        n_bays = 1
        hull_val = 800.0
        garrison = 10

    # Shield arcs — evenly divided around the station.
    arc_size = 360.0 / n_gens
    shield_arcs = [
        ShieldArc(
            id=f"{station_id}_gen_{i}",
            hp=80.0, hp_max=80.0,
            arc_start=(i * arc_size) % 360.0,
            arc_end=((i + 1) * arc_size) % 360.0,
        )
        for i in range(n_gens)
    ]

    # Turrets — evenly spaced facing outward.
    turrets = [
        Turret(
            id=f"{station_id}_turret_{i}",
            hp=40.0, hp_max=40.0,
            facing=(i * 360.0 / n_turrets) % 360.0,
        )
        for i in range(n_turrets)
    ]

    launchers = [
        TorpedoLauncher(id=f"{station_id}_launcher_{i}", hp=60.0, hp_max=60.0)
        for i in range(n_launchers)
    ]

    fighter_bays = [
        FighterBay(id=f"{station_id}_bay_{i}", hp=60.0, hp_max=60.0)
        for i in range(n_bays)
    ]

    defenses = EnemyStationDefenses(
        shield_arcs=shield_arcs,
        turrets=turrets,
        launchers=launchers,
        fighter_bays=fighter_bays,
        sensor_array=SensorArray(
            id=f"{station_id}_sensor", hp=50.0, hp_max=50.0,
        ),
        reactor=StationReactor(
            id=f"{station_id}_reactor", hp=100.0, hp_max=100.0,
        ),
        garrison_count=garrison,
        station_interior=make_station_interior(station_id),
    )

    return Station(
        id=station_id,
        x=x,
        y=y,
        name=f"Enemy {variant.capitalize()}",
        station_type="enemy",
        faction="hostile",
        services=[],
        docking_range=0.0,
        docking_ports=0,
        transponder_active=False,
        shields=0.0,
        shields_max=0.0,
        hull=hull_val,
        hull_max=hull_val,
        inventory={},
        requires_scan=True,
        defenses=defenses,
    )
