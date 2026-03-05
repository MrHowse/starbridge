# v0.09 PHASE 1: SHIP MODEL SHELL

**Purpose:** Create the ShipModel class hierarchy as a foundation for the simulation-first architecture. This phase is purely additive — no existing behaviour changes, no client changes, no removed code. The ShipModel shadows existing state via dual-write. Tests verify the model matches existing state every tick.

**Risk level:** LOW. This adds new files and initialises new classes alongside existing code. The game continues to work exactly as it does now. The ShipModel is a parallel data structure that proves we can represent the full ship state before we start routing anything through it.

**Prerequisite:** Read `v009_ship_simulation_spec.md` for the full architecture. This prompt implements the foundation described there.

Commit after each section. Run pytest after each commit. Zero regressions.

---

## PROMPT (copy everything below this line)

---

Read the v0.09 architecture spec at `v009_ship_simulation_spec.md` before starting. This prompt implements Phase 1: the ShipModel shell.

Create the `server/simulation/` package with all model classes. Each model class mirrors existing game state. At the end of this phase, the ShipModel is initialised each game, populated from existing state every tick, and tested for consistency.

No existing behaviour changes. No client changes. No removed code. Additive only.

---

## 1. PACKAGE STRUCTURE

`commit: feat(sim): Create simulation package structure`

Create the directory and all `__init__.py` files:

```
server/simulation/
    __init__.py              # exports ShipModel, WorldModel
    ship_model.py
    world_model.py
    room.py
    section.py
    systems.py
    reactor.py
    shields.py
    weapons.py
    sensors.py
    flight_deck.py
    crew.py
    resources.py
    comms.py
    alerts.py
    commands/
        __init__.py
    views/
        __init__.py
```

Create stub files with class definitions and docstrings. No implementation yet — just the shape.

---

## 2. ROOM AND SECTION MODELS

`commit: feat(sim): Implement Room and Section models`

### Room model (`server/simulation/room.py`):

```python
@dataclass
class FireState:
    intensity: float          # 0–5
    fuel_remaining: float     # time until self-extinguish
    spread_timer: float       # countdown to spread attempt
    
@dataclass
class BreachState:
    severity: str             # "minor", "moderate", "major"
    leak_rate: float          # atmosphere loss per second
    seal_progress: float      # 0.0–1.0 (1.0 = sealed)

@dataclass  
class Room:
    id: str
    section_id: str
    adjacent_room_ids: list[str]
    
    # Atmosphere
    oxygen: float = 1.0
    pressure: float = 1.0
    temperature: float = 20.0
    contamination: float = 0.0
    
    # Hazards
    fire: FireState | None = None
    breach: BreachState | None = None
    radiation: float = 0.0
    
    # Structural
    structural_integrity: float = 1.0
    bulkhead_sealed: bool = False
    door_locked: bool = False
    
    # Contents
    crew_present: list[str] = field(default_factory=list)
    system_housed: str | None = None
```

### Section model (`server/simulation/section.py`):

```python
@dataclass
class Section:
    id: str
    room_ids: list[str]
    integrity: float = 1.0    # 0.0–1.0
    collapsed: bool = False
```

### Populate from existing state:
Find where the existing code stores room and section data. Create a `Room.from_existing(existing_room_data)` class method that converts the current representation into the new Room model. Same for Section.

### Tests (`tests/test_sim_room.py`):
- Create a Room, verify default values
- Create a Room with fire, verify FireState
- Create a Room with breach, verify BreachState
- Test `from_existing()` produces correct Room from existing game state
- Test Section creation with room list

---

## 3. SHIP SYSTEMS MODEL

`commit: feat(sim): Implement ShipSystem models`

### Systems model (`server/simulation/systems.py`):

```python
@dataclass
class SystemComponent:
    id: str
    health: float = 100.0     # 0–100
    effect: str = ""          # what this component affects when damaged
    
@dataclass
class ShipSystem:
    id: str                   # "engines", "shields", "beams", "torpedoes", "sensors", "manoeuvring", "flight_deck", "ecm_suite"
    health: float = 100.0     # overall health 0–100
    power_allocated: int = 0  # power units assigned
    power_required: int = 0   # nominal power draw
    overclocked: bool = False
    components: list[SystemComponent] = field(default_factory=list)
    room_id: str | None = None  # which room houses this system
    
    @property
    def efficiency(self) -> float:
        """Output as fraction of maximum. Affected by health and power."""
        health_factor = self.health / 100.0
        power_factor = min(self.power_allocated / max(self.power_required, 1), 1.0)
        return health_factor * power_factor
```

### Populate from existing state:
Find the existing system health, power allocation, overclock state, and component data. Create `ShipSystem.from_existing()` to convert.

### Tests (`tests/test_sim_systems.py`):
- Create system, verify default health and efficiency
- Test efficiency calculation with reduced health
- Test efficiency calculation with reduced power
- Test overclock flag
- Test component health tracking
- Test `from_existing()` matches current game state

---

## 4. REACTOR AND POWER GRID

`commit: feat(sim): Implement ReactorModel and PowerGrid`

### Reactor (`server/simulation/reactor.py`):

```python
@dataclass
class ReactorModel:
    max_output: int           # total power units available
    current_output: int       # actual output (may be reduced by damage)
    fuel_consumption_rate: float
    temperature: float = 0.0
    overclocked: bool = False
    health: float = 100.0

@dataclass
class PowerGrid:
    reactor: ReactorModel
    allocation: dict[str, int]  # system_id → power units
    total_draw: int = 0
    total_capacity: int = 0
    
    @property
    def utilisation(self) -> float:
        return self.total_draw / max(self.total_capacity, 1)
```

### Populate from existing Engineering/power state.

### Tests (`tests/test_sim_reactor.py`):
- Reactor default state
- Power grid allocation and utilisation calculation
- `from_existing()` matches current power state

---

## 5. SHIELDS MODEL

`commit: feat(sim): Implement ShieldModel`

### Shields (`server/simulation/shields.py`):

```python
@dataclass
class ShieldFacing:
    direction: str            # "fore", "aft", "port", "starboard"
    current_hp: float
    max_hp: float
    recharge_rate: float
    
@dataclass
class ShieldModel:
    facings: dict[str, ShieldFacing]
    harmonics: dict[str, float]  # frequency → effectiveness
    total_hp: float = 0.0
    total_max: float = 0.0
```

### Tests (`tests/test_sim_shields.py`).

---

## 6. WEAPONS MODEL

`commit: feat(sim): Implement weapons models`

### Weapons (`server/simulation/weapons.py`):

```python
@dataclass
class BeamArray:
    id: str
    damage: float
    range: float
    frequency: str
    cooldown: float = 0.0
    arc_start: float = 0.0   # firing arc in degrees
    arc_end: float = 360.0

@dataclass
class TorpedoTube:
    id: str
    loaded_type: str | None = None
    reload_timer: float = 0.0
    reload_time: float = 5.0

@dataclass
class WeaponsModel:
    beam_arrays: list[BeamArray]
    torpedo_tubes: list[TorpedoTube]
    ammo: dict[str, int]      # torpedo_type → count
    selected_target: str | None = None
```

### Tests (`tests/test_sim_weapons.py`).

---

## 7. SENSOR MODEL

`commit: feat(sim): Implement SensorModel and Contact`

### Sensors (`server/simulation/sensors.py`):

```python
@dataclass
class Contact:
    entity_id: str
    position: tuple[float, float]
    bearing: float
    distance: float
    scan_level: int = 0       # 0=unscanned, 1=basic, 2=detailed, 3=full
    classification: str = 'unknown'
    signal_strength: float = 0.0
    status: str = 'active'    # 'active', 'lost'
    scan_data: dict = field(default_factory=dict)

@dataclass
class ActiveScan:
    target_id: str
    progress: float = 0.0     # 0.0–1.0
    scan_depth: int = 1

@dataclass
class SensorModel:
    detection_range: float
    resolution: float
    health_factor: float = 1.0
    power_factor: float = 1.0
    contacts: dict[str, Contact] = field(default_factory=dict)
    active_scan: ActiveScan | None = None
    sector_scans: list = field(default_factory=list)
```

### Tests (`tests/test_sim_sensors.py`).

---

## 8. CREW, RESOURCES, COMMS, ALERTS, FLIGHT DECK

`commit: feat(sim): Implement remaining ship subsystem models`

### Crew (`server/simulation/crew.py`):
```python
@dataclass
class CrewMember:
    id: str
    name: str
    room_id: str
    health: float = 100.0
    morale: float = 100.0
    assignment: str | None = None  # station or team assignment
    injuries: list[dict] = field(default_factory=list)

@dataclass
class CrewModel:
    members: dict[str, CrewMember]
    total_count: int = 0
    casualties: int = 0
```

### Resources (`server/simulation/resources.py`):
```python
@dataclass
class ResourceModel:
    fuel: float = 100.0
    ammo: dict[str, int] = field(default_factory=dict)
    suppressant: float = 100.0
    repair_materials: float = 100.0
    medical_supplies: float = 100.0
```

### Comms (`server/simulation/comms.py`):
```python
@dataclass
class CommsModel:
    signals: list[dict] = field(default_factory=list)
    standings: dict[str, float] = field(default_factory=dict)
    active_channels: list[str] = field(default_factory=list)
```

### Alerts (`server/simulation/alerts.py`):
```python
@dataclass
class AlertState:
    general_order: str = 'condition_green'
    deck_alerts: dict[int, str] = field(default_factory=dict)
    priority_target: str | None = None
```

### Flight Deck (`server/simulation/flight_deck.py`):
```python
@dataclass
class DroneState:
    id: str
    type: str
    status: str               # 'ready', 'launched', 'returning', 'damaged'
    position: tuple[float, float] | None = None
    mission: str | None = None

@dataclass
class FlightDeckModel:
    drones: dict[str, DroneState]
    launch_ready: bool = True
    catapult_health: float = 100.0
```

### Tests for each: basic creation, `from_existing()` where applicable.

---

## 9. WORLD MODEL

`commit: feat(sim): Implement WorldModel`

### World (`server/simulation/world_model.py`):

```python
@dataclass
class WorldEntity:
    id: str
    entity_type: str          # 'ship', 'station', 'anomaly', 'creature', 'torpedo', 'drone', 'debris'
    position: tuple[float, float]
    velocity: tuple[float, float] = (0.0, 0.0)
    heading: float = 0.0
    faction: str = 'neutral'
    health: float = 100.0
    
@dataclass
class WorldModel:
    entities: dict[str, WorldEntity]
    hazard_zones: list[dict] = field(default_factory=list)
    
    def entities_in_range(self, position: tuple, radius: float) -> list[WorldEntity]:
        """Return all entities within radius of position."""
        ...
    
    def add_entity(self, entity: WorldEntity):
        self.entities[entity.id] = entity
    
    def remove_entity(self, entity_id: str):
        self.entities.pop(entity_id, None)
```

### Tests (`tests/test_sim_world.py`):
- Add/remove entities
- Range query returns correct entities
- Entity position and velocity

---

## 10. SHIP MODEL COMPOSITE

`commit: feat(sim): Implement ShipModel composite class`

### ShipModel (`server/simulation/ship_model.py`):

```python
class ShipModel:
    """Complete physical model of the player's ship.
    
    This is the single source of truth for all ship state.
    In Phase 1, it shadows existing game state via dual-write.
    In later phases, it becomes the primary state store.
    """
    
    def __init__(self, ship_class: str, ship_name: str):
        self.ship_class = ship_class
        self.ship_name = ship_name
        
        # Physical
        self.position = (50000.0, 50000.0)
        self.velocity = (0.0, 0.0)
        self.heading = 0.0
        self.throttle = 0.0
        
        # Hull
        self.hull_hp = 120.0
        self.hull_max = 120.0
        
        # Subsystems (initialised by ship class config)
        self.sections: dict[str, Section] = {}
        self.rooms: dict[str, Room] = {}
        self.reactor = ReactorModel(...)
        self.power_grid = PowerGrid(...)
        self.systems: dict[str, ShipSystem] = {}
        self.shields = ShieldModel(...)
        self.weapons = WeaponsModel(...)
        self.sensors = SensorModel(...)
        self.flight_deck = FlightDeckModel(...)
        self.crew = CrewModel(...)
        self.resources = ResourceModel(...)
        self.comms = CommsModel(...)
        self.alerts = AlertState()
    
    @classmethod
    def from_existing_game_state(cls, game_state) -> 'ShipModel':
        """Build a ShipModel from current game state. Used for dual-write shadow."""
        model = cls(game_state.ship_class, game_state.ship_name)
        model._sync_from(game_state)
        return model
    
    def sync_from(self, game_state):
        """Update all model fields from existing game state. Called every tick during Phase 1."""
        # Physical
        self.position = (game_state.ship.x, game_state.ship.y)
        self.heading = game_state.ship.heading
        self.throttle = game_state.ship.throttle
        self.hull_hp = game_state.ship.hull
        
        # Systems
        for sys_id, sys_data in game_state.systems.items():
            if sys_id in self.systems:
                self.systems[sys_id].health = sys_data.health
                self.systems[sys_id].power_allocated = sys_data.power
                self.systems[sys_id].overclocked = sys_data.overclocked
        
        # Shields
        for facing, shield_data in game_state.shields.items():
            if facing in self.shields.facings:
                self.shields.facings[facing].current_hp = shield_data.hp
        
        # Rooms (fire, atmosphere, etc.)
        for room_id, room_data in game_state.rooms.items():
            if room_id in self.rooms:
                self.rooms[room_id].oxygen = room_data.oxygen
                self.rooms[room_id].pressure = room_data.pressure
                self.rooms[room_id].temperature = room_data.temperature
                # ... etc for all room fields
        
        # Resources
        self.resources.fuel = game_state.fuel
        self.resources.ammo = dict(game_state.ammo)
        self.resources.suppressant = game_state.suppressant
        
        # ... continue for all subsystems
    
    def validate_against(self, game_state) -> list[str]:
        """Compare model state against existing game state. Returns list of mismatches.
        Used in testing to verify the shadow model is accurate."""
        mismatches = []
        if abs(self.hull_hp - game_state.ship.hull) > 0.01:
            mismatches.append(f"hull: model={self.hull_hp}, game={game_state.ship.hull}")
        # ... check every field
        return mismatches
```

### Initialisation in game loop:
Find where the game loop starts (game begins, ship is created). After existing initialisation, add:

```python
from server.simulation import ShipModel

# After existing ship/game state is set up:
self.ship_model = ShipModel.from_existing_game_state(self.game_state)
```

### Per-tick sync:
In the main tick function, after all existing updates complete:

```python
# End of tick — sync shadow model
self.ship_model.sync_from(self.game_state)
```

This is dual-write: existing code updates existing state as normal, then we copy it into the ShipModel. The ShipModel is a passive mirror at this stage.

### Tests (`tests/test_sim_ship_model.py`):
- Create ShipModel for each ship class
- Verify all subsystems are initialised
- Run 100 ticks of a real game, sync each tick, call `validate_against()` — expect zero mismatches
- Test with combat (torpedo fire, shield damage, hull damage)
- Test with fires and breaches
- Test with crew casualties
- Test with power changes and overclock

**These validation tests are the critical deliverable.** If the shadow model matches existing state for 100 ticks across multiple scenarios, we know the model is accurate and Phase 2 can begin safely.

---

## 11. WORLD MODEL INTEGRATION

`commit: feat(sim): Populate WorldModel from existing entity state`

Find where the game stores entities (enemies, stations, anomalies, creatures, torpedoes in flight). Create `WorldModel.from_existing_game_state()` and sync it each tick alongside ShipModel.

### Tests:
- Spawn enemies, verify WorldModel.entities matches
- Destroy an enemy, verify it's removed from WorldModel
- Fire a torpedo, verify it appears as a world entity
- Verify `entities_in_range()` returns correct results

---

## 12. SHIP CLASS CONFIGURATIONS

`commit: feat(sim): Ship class configs for ShipModel initialisation`

Create a configuration file/module that defines per-ship-class parameters:

```python
SHIP_CONFIGS = {
    'frigate': {
        'hull_max': 120,
        'sections': ['bridge', 'engineering', 'weapons', 'medical', 'cargo'],
        'rooms': {
            'bridge': {'section': 'bridge', 'adjacent': ['corridor_a'], 'system': 'manoeuvring'},
            'engine_room': {'section': 'engineering', 'adjacent': ['corridor_b', 'main_engineering'], 'system': 'engines'},
            # ... all rooms
        },
        'systems': {
            'engines': {'power_required': 3, 'room': 'engine_room'},
            'shields': {'power_required': 3, 'room': 'shields_control'},
            # ... all systems
        },
        'reactor': {'max_output': 20},
        'shields': {'fore': 20, 'aft': 20, 'port': 20, 'starboard': 20},
        'weapons': {
            'beam_arrays': [{'range': 5000, 'damage': 7.5, 'arc': [0, 360]}],
            'torpedo_tubes': [{'reload_time': 5.0}, {'reload_time': 5.0}],
        },
        'sensors': {'detection_range': 15000, 'resolution': 1.0},
        'crew_count': 30,
        'resources': {'fuel': 100, 'suppressant': 100, 'repair_materials': 100},
    },
    'cruiser': { ... },
    # ... all 7 ship classes
}
```

Extract these values from the existing ship class definitions. The ShipModel constructor uses this config to initialise all subsystems.

### Tests:
- Create ShipModel for each of the 7 ship classes
- Verify hull, system count, room count, shield values match existing ship class data
- Verify no ship class is missing or has mismatched values

---

## AFTER ALL SECTIONS

1. Run full pytest — zero regressions
2. Run a sandbox game for 300 ticks with the shadow model syncing every tick — verify zero mismatches
3. Run a combat scenario for 200 ticks — verify zero mismatches
4. Report: model class count, test count, any sync mismatches found and resolved
5. Final test count

The ShipModel is now a verified shadow of the entire game state. Phase 2 will start routing station reads through this model.
