# v0.09 — SHIP SIMULATION CORE

## The Problem

The current architecture is station-centric. Each station is a semi-independent module that emits events and listens for events from other stations. Cross-station interaction requires explicit wiring — a signal sent from Science to Operations, a broadcast from Engineering to Hazard Control, a notification from Captain to Weapons.

This creates three structural problems:

1. **Broken wires.** The signal audit found 25 broken connections. Every new feature requires manually wiring emitters to receivers across stations. Wires break silently — the only way to find them is to audit or playtest.

2. **Artificial event generation.** The sandbox needs 14+ timers to hand-feed events to individual stations. HazCon, Ops, and QM had zero events because nobody wrote a timer for them. Stations with nothing to do is a wiring problem, not a design problem.

3. **No emergent gameplay.** If Engineering overclocks and causes a fire, that fire only creates work for HazCon because someone explicitly coded "overclock → emit fire event → HazCon handler." The fire doesn't naturally fill the room with smoke, reduce O2, stress the hull, injure crew, or force evacuations unless each consequence is separately wired. Real gameplay emerges from simulation; our gameplay emerges from event chains.

## The Solution

**Simulate the ship. Stations are views.**

The ship exists as a complete physical model that ticks forward every frame regardless of what stations are manned. The ship has rooms with atmospheres. Rooms contain crew. Systems draw power and produce output. Fires spread based on oxygen levels. Breaches cause depressurisation. Crew in hazardous rooms get injured. Shields recharge based on power allocation. Sensors detect contacts based on range and resolution.

Stations don't generate reality — they observe and influence it. Weapons doesn't fire a torpedo event; Weapons issues a FIRE_TORPEDO command that the simulation processes. The torpedo becomes an entity in the world. It moves. It hits or misses based on physics. The impact damages the target's hull. The damage cascades through the target's rooms and systems. All of this happens in the simulation, not in station-to-station event handlers.

Every station always has something to look at because the ship is always doing something. Even in quiet moments, Engineering can see power consumption trending upward, Medical can see crew fatigue accumulating, Ops can see sensor contacts at the edge of detection range. The simulation generates work by existing, not by firing timer events.

---

## Architecture

### Three Layers

```
┌─────────────────────────────────────────────────────────────┐
│                    STATION LAYER (Views)                     │
│  Captain │ Helm │ Weapons │ Engineering │ Science │ ...      │
│  Each station: reads filtered ship state, issues commands    │
├─────────────────────────────────────────────────────────────┤
│                   COMMAND INTERFACE                           │
│  Validates commands, applies to ship model                   │
│  set_heading(270) │ fire_torpedo(target, type) │ ...         │
├─────────────────────────────────────────────────────────────┤
│                 SHIP SIMULATION (Model)                       │
│  ShipModel: rooms, systems, crew, resources, sensors         │
│  WorldModel: entities, spatial, contacts, environment        │
│  Ticks forward every frame autonomously                      │
└─────────────────────────────────────────────────────────────┘
```

**Ship Simulation** — the source of truth. Contains all state. Ticks forward every frame. Computes physics, environmental propagation, system outputs, crew effects, sensor detection. Does not know stations exist.

**Command Interface** — the only way to modify ship state. Stations issue commands. Commands are validated (is this station manned? does the player have authority? is the action possible?). Valid commands modify the ship model. Invalid commands are rejected with a reason.

**Station Layer** — pure views with controls. Each station defines what slice of the ship model it can see and what commands it can issue. The station reads its view of the ship state, renders it for the player, and forwards player inputs as commands.

### The Ship Model

```python
class ShipModel:
    """Complete physical model of the player's ship."""
    
    # Identity
    ship_class: ShipClass          # frigate, cruiser, etc.
    ship_name: str
    
    # Physical state
    position: Vector2              # world coordinates
    velocity: Vector2              # current velocity
    heading: float                 # degrees
    throttle: float                # 0.0–1.0
    
    # Hull and structure
    hull: HullModel                # total HP, armour rating
    sections: dict[str, Section]   # bridge, engineering, weapons, medical, ...
    rooms: dict[str, Room]         # individual rooms within sections
    
    # Power
    reactor: ReactorModel          # output, fuel consumption, overclock state
    power_grid: PowerGrid          # allocation to systems, total draw vs capacity
    
    # Systems
    systems: dict[str, ShipSystem] # engines, shields, beams, torpedoes, sensors, ...
    
    # Shields
    shields: ShieldModel           # per-facing HP, harmonics, recharge rate
    
    # Weapons
    beam_arrays: list[BeamArray]   # individual beam weapons with arcs, range, state
    torpedo_tubes: list[TorpedoTube]  # tubes with load state, reload timer
    point_defence: PointDefence
    
    # Sensors
    sensors: SensorModel           # detection range, resolution, active scans, contact list
    
    # Flight deck
    flight_deck: FlightDeckModel   # drone inventory, launch status, active drone missions
    
    # Crew
    crew: CrewModel                # individual crew with location, health, morale, assignment
    
    # Resources
    resources: ResourceModel       # fuel, ammo by type, suppressant, repair materials, medical supplies
    
    # Communications
    comms: CommsModel              # signal buffer, diplomatic standings, active channels
    
    # Alerts
    alert_state: AlertState        # current general order, per-deck alert levels

    def tick(self, dt: float, world: WorldModel):
        """Advance the entire ship simulation by one time step."""
        self.reactor.tick(dt)
        self.power_grid.tick(dt, self.reactor)
        for system in self.systems.values():
            system.tick(dt, self.power_grid)
        self.shields.tick(dt, self.systems['shields'])
        self._tick_movement(dt)
        self._tick_rooms(dt)          # atmosphere, fire, radiation propagation
        self._tick_crew(dt)           # crew health effects from room conditions
        self._tick_sensors(dt, world) # detection, contact list updates
        self._tick_weapons(dt)        # reload timers, beam cooldowns
        self._tick_flight_deck(dt, world)
        self._tick_resources(dt)      # fuel consumption, resource decay
```

### Room Model (where emergent gameplay lives)

```python
class Room:
    """A physical space on the ship. This is where simulation creates gameplay."""
    
    id: str                        # "engine_room", "bridge", "cargo_hold"
    section: str                   # which structural section this room belongs to
    adjacent_rooms: list[str]      # connected rooms (for fire spread, atmosphere flow)
    
    # Atmosphere
    oxygen: float                  # 0.0–1.0 (1.0 = normal)
    pressure: float                # 0.0–1.0 (1.0 = normal)
    temperature: float             # Celsius
    contamination: float           # 0.0–1.0 (0.0 = clean)
    
    # Hazards
    fire: FireState | None         # intensity, fuel, spread timer
    breach: BreachState | None     # severity, seal progress
    radiation: float               # rads/s exposure in this room
    
    # Structural
    structural_integrity: float    # 0.0–1.0
    bulkhead_sealed: bool          # emergency bulkhead state
    door_locked: bool
    
    # Contents
    crew_present: list[str]        # crew IDs currently in this room
    system_housed: str | None      # which ship system is in this room (if any)
    
    def tick(self, dt: float, adjacent: dict[str, 'Room']):
        """Advance room state. This is where cascading effects emerge."""
        if self.fire:
            self.fire.tick(dt, self.oxygen)           # fire consumes O2
            self.oxygen -= self.fire.o2_consumption * dt
            self.temperature += self.fire.heat_output * dt
            if self.fire.intensity >= 3:
                self._try_spread(adjacent)             # fire spreads to adjacent rooms
            self.structural_integrity -= self.fire.structural_damage * dt
        
        if self.breach:
            self.pressure -= self.breach.leak_rate * dt  # atmosphere bleeds out
            self.oxygen -= self.breach.leak_rate * dt
            self.temperature -= self.breach.cooling_rate * dt
        
        # Crew in this room take damage from conditions
        # (the simulation computes this — Medical sees the results)
        for crew_id in self.crew_present:
            if self.oxygen < 0.5:
                yield CrewEffect(crew_id, 'hypoxia', severity=1.0 - self.oxygen)
            if self.temperature > 60:
                yield CrewEffect(crew_id, 'burns', severity=(self.temperature - 60) / 40)
            if self.fire and self.fire.intensity >= 3:
                yield CrewEffect(crew_id, 'smoke_inhalation', severity=self.fire.intensity / 5)
            if self.radiation > 0:
                yield CrewEffect(crew_id, 'radiation_exposure', severity=self.radiation)
```

**This is the key insight.** The room model doesn't know about Hazard Control. It doesn't emit events to specific stations. It just simulates physics. A fire consumes oxygen, raises temperature, damages structure, and spreads to adjacent rooms. Crew in the room suffer effects based on conditions. HazCon sees all of this by reading room state. Medical sees casualties by reading crew health. Engineering sees system degradation because the system housed in a burning room takes damage. Everyone sees the same reality from their own perspective.

### Sensor Model (what you can see depends on sensors)

```python
class SensorModel:
    """What the ship can detect. ALL station views of the outside world flow through this."""
    
    detection_range: float         # base range in world units
    resolution: float              # ability to distinguish contacts (affects scan quality)
    active_scan: ActiveScan | None # current focused scan target and progress
    sector_scans: list[SectorScan] # running sector sweeps
    
    contacts: dict[str, Contact]   # all detected entities
    
    def tick(self, dt: float, world: WorldModel, ship_position: Vector2):
        """Update contact list based on what sensors can actually detect."""
        effective_range = self.detection_range * self.health_factor * self.power_factor
        effective_resolution = self.resolution * self.health_factor
        
        # Detect entities within range
        for entity in world.entities.values():
            distance = (entity.position - ship_position).magnitude()
            if distance <= effective_range:
                if entity.id not in self.contacts:
                    # NEW CONTACT — detected but unscanned
                    self.contacts[entity.id] = Contact(
                        entity_id=entity.id,
                        position=entity.position,
                        bearing=calculate_bearing(ship_position, entity.position),
                        distance=distance,
                        scan_level=0,         # unscanned
                        classification='unknown',
                        signal_strength=self._signal_strength(distance, entity)
                    )
                else:
                    # UPDATE existing contact position/bearing
                    self.contacts[entity.id].update(entity.position, distance)
            else:
                # LOST CONTACT — out of range
                if entity.id in self.contacts:
                    self.contacts[entity.id].status = 'lost'
        
        # Advance active scan
        if self.active_scan:
            self.active_scan.tick(dt, effective_resolution)
            if self.active_scan.complete:
                contact = self.contacts[self.active_scan.target_id]
                contact.scan_level = self.active_scan.scan_depth
                contact.classification = world.entities[self.active_scan.target_id].type
                contact.scan_data = self.active_scan.results
```

**This solves the "invisible contacts" bug from playtest 2 architecturally.** Contacts appear when sensors detect them, not when Science scans them. Scanning increases scan_level and reveals detail. Weapons sees all contacts (scan_level 0+ = a blip on screen). Science scanning upgrades the contact with classification, threat data, and vulnerabilities. Ops gets assessment data from high-level scans. It's all one model.

### Command Interface

```python
class CommandInterface:
    """The ONLY way to modify ship state. Stations issue commands here."""
    
    def execute(self, command: Command, ship: ShipModel, world: WorldModel) -> CommandResult:
        """Validate and execute a command against the ship model."""
        
        # 1. Validate authority (does this station have permission?)
        if not self._check_authority(command):
            return CommandResult(success=False, reason="Not authorised")
        
        # 2. Validate feasibility (is this physically possible?)
        if not self._check_feasibility(command, ship):
            return CommandResult(success=False, reason="Cannot comply")
        
        # 3. Execute against ship model
        result = command.execute(ship, world)
        
        # 4. Log for telemetry
        self._log_command(command, result)
        
        return result

# Example commands
class SetHeadingCommand(Command):
    station = 'helm'
    def execute(self, ship, world):
        ship.heading_target = self.heading
        return CommandResult(success=True)

class FireTorpedoCommand(Command):
    station = 'weapons'
    def execute(self, ship, world):
        tube = ship.torpedo_tubes[self.tube_index]
        if not tube.loaded:
            return CommandResult(success=False, reason="Tube not loaded")
        torpedo = tube.fire(self.target_id, ship.position, ship.heading)
        world.add_entity(torpedo)  # torpedo is now a world entity with physics
        return CommandResult(success=True)

class DispatchFireTeamCommand(Command):
    station = 'hazard_control'
    def execute(self, ship, world):
        team = ship.crew.get_available_fire_team()
        if not team:
            return CommandResult(success=False, reason="No fire team available")
        ship.crew.assign_team(team, destination=self.room_id, task='firefighting')
        return CommandResult(success=True)
```

### Station Views

```python
class StationView:
    """Defines what a station can see and do. Pure data — no game logic."""
    
    station_id: str
    
    def get_state(self, ship: ShipModel, world: WorldModel) -> dict:
        """Extract the slice of ship state this station needs."""
        raise NotImplementedError
    
    def get_commands(self) -> list[type[Command]]:
        """List of command types this station can issue."""
        raise NotImplementedError


class HelmView(StationView):
    station_id = 'helm'
    
    def get_state(self, ship, world):
        return {
            'position': ship.position,
            'heading': ship.heading,
            'speed': ship.velocity.magnitude(),
            'throttle': ship.throttle,
            'max_speed': ship.systems['engines'].current_output,
            'turn_rate': ship.systems['manoeuvring'].current_output,
            'contacts': {cid: _contact_summary(c) for cid, c in ship.sensors.contacts.items()},
            'waypoints': ship.navigation.waypoints,
            'hazards': world.get_hazards_near(ship.position, radius=20000),
        }
    
    def get_commands(self):
        return [SetHeadingCommand, SetThrottleCommand, ActivateEvasiveCommand]


class HazardControlView(StationView):
    station_id = 'hazard_control'
    
    def get_state(self, ship, world):
        return {
            'rooms': {
                rid: {
                    'oxygen': room.oxygen,
                    'pressure': room.pressure,
                    'temperature': room.temperature,
                    'contamination': room.contamination,
                    'fire': room.fire.to_dict() if room.fire else None,
                    'breach': room.breach.to_dict() if room.breach else None,
                    'radiation': room.radiation,
                    'structural_integrity': room.structural_integrity,
                    'crew_count': len(room.crew_present),
                    'bulkhead_sealed': room.bulkhead_sealed,
                    'door_locked': room.door_locked,
                }
                for rid, room in ship.rooms.items()
            },
            'sections': {
                sid: {'integrity': section.integrity}
                for sid, section in ship.sections.items()
            },
            'fire_teams': ship.crew.get_fire_teams(),
            'suppressant_remaining': ship.resources.suppressant,
        }
    
    def get_commands(self):
        return [
            DispatchFireTeamCommand, RecallFireTeamCommand,
            SealBulkheadCommand, UnsealBulkheadCommand,
            VentRoomCommand, EvacuateRoomCommand,
            ActivateSprinklerCommand, LockDoorCommand,
        ]
```

**Every station follows this pattern.** The view extracts what the station needs from the ship model. The command list defines what the station can do. The client renders the view and sends commands. No station-to-station wiring exists.

---

## What Emerges Naturally

With a simulation core, these gameplay moments emerge WITHOUT explicit wiring:

**Engineering overclocks engines → reactor heats up → coolant system stressed → micro-leak in engine room → temperature rises → crew in engine room get heat exposure → fire risk increases → fire starts → fire consumes O2 → smoke spreads to adjacent corridor → crew in corridor get smoke inhalation → Medical has patients → HazCon sees fire + atmosphere degradation + structural stress → fire team dispatched → suppression uses suppressant → QM sees suppressant levels drop**

In the current architecture, every arrow in that chain is a hand-wired event. In the simulation, it's just physics. The overclock increases heat output. The room model propagates temperature. The crew model applies health effects. Each station reads the state that concerns them.

**Sensor contact at edge of range → low signal strength → Science sees fuzzy blip → scan reveals it's a hostile → classification upgrades → Weapons now sees threat data → Ops gets assessment material → Captain sees tactical picture → contact moves closer → signal strength increases → more detail visible without scanning → contact enters beam range → Weapons can engage**

No "invisible until scanned" bug possible. Contacts exist when sensors detect them. Detail increases with proximity and scanning. Every station sees the same contacts filtered through the sensor model.

**Torpedo fired → torpedo becomes a world entity → torpedo has velocity and heading → homing torpedo adjusts heading toward target → torpedo reaches target → impact → damage to target hull → if target has rooms, fire/breach/casualties cascade inside target → target systems degrade → target behaviour changes (flee, fight harder) → if target destroyed, debris spawns → debris is a new entity → sensors detect debris → Science can scan debris for salvage**

Torpedoes aren't events — they're entities in the world with physics. The hit isn't a message from Weapons to the target; it's a collision in the simulation.

---

## Migration Path

This is NOT a rewrite. The v0.08 codebase has the right subsystems — fire, atmosphere, radiation, structural integrity, crew, power, shields, weapons. They just need to be consolidated into a unified model instead of operating as independent event-driven modules.

### Phase 1: ShipModel Shell (Foundation)

**Goal:** Create the ShipModel class that wraps existing state. All existing code continues to work — the ShipModel is an additional layer, not a replacement yet.

1. Create `server/simulation/ship_model.py` with the ShipModel class
2. Create `server/simulation/room.py` with the Room model
3. Create `server/simulation/systems.py` with the ShipSystem base and concrete systems
4. Create `server/simulation/sensors.py` with the SensorModel
5. Create `server/simulation/crew.py` with the CrewModel
6. Create `server/simulation/resources.py` with the ResourceModel
7. Create `server/simulation/shields.py` with the ShieldModel
8. Create `server/simulation/weapons.py` with weapon models
9. Create `server/simulation/world.py` with the WorldModel (entities, spatial)
10. Initialise ShipModel in the game loop alongside existing state
11. Mirror existing state into ShipModel each tick (dual-write)
12. Tests verify ShipModel state matches existing state every tick

**No behaviour changes. No client changes. Just a new data structure that shadows existing state.**

### Phase 2: Station Views (Read Path)

**Goal:** Stations read from ShipModel instead of receiving events. Event broadcasts still happen as a fallback.

1. Create `server/simulation/views/` directory with a view class per station
2. Each view's `get_state()` reads from ShipModel
3. Modify the WebSocket state push to use `view.get_state()` instead of per-station state builders
4. Keep existing event handlers as fallback — if a station receives data from both the view and an event, the view wins
5. Remove event handlers one station at a time as views are verified
6. Tests: for each station, verify the view produces identical output to the old state builder

**Stations start reading from the model. Client code changes are minimal — the JSON shape may need minor adjustments.**

### Phase 3: Command Interface (Write Path)

**Goal:** Player actions go through commands instead of directly modifying state.

1. Create `server/simulation/commands/` with the Command base class and CommandInterface
2. Define command classes for each station's actions
3. Modify WebSocket message handlers: instead of directly calling game logic, create and execute commands
4. Commands modify ShipModel state
5. ShipModel state changes propagate to existing systems (bridge period — both paths work)
6. Tests: for each command, verify it produces the same state change as the old direct handler

**Player inputs now flow through a clean interface. Old handlers are gradually replaced.**

### Phase 4: Simulation Tick (Autonomous Model)

**Goal:** ShipModel.tick() runs the simulation. Existing per-system tick functions are consolidated.

1. Implement ShipModel.tick() as the master tick function
2. Room.tick() handles atmosphere propagation, fire spread, crew effects
3. ShipSystem.tick() handles system output based on health and power
4. SensorModel.tick() handles contact detection and scan progress
5. Move logic from existing game_loop subsystems (game_loop_fire.py, game_loop_atmosphere.py, etc.) into the ShipModel tick
6. Remove old subsystem tick calls from the game loop one at a time
7. The game loop becomes: `ship_model.tick(dt, world_model)` → `push_views_to_clients()`
8. Tests: run simulation for N ticks, verify identical outcomes to old system

**The simulation is now autonomous. The game loop is clean.**

### Phase 5: Cleanup (Remove Old Wiring)

**Goal:** Remove all legacy event-driven wiring. The simulation is the only source of truth.

1. Remove station-to-station signal broadcasts
2. Remove per-station state builders (replaced by views)
3. Remove per-station event handlers (replaced by commands)
4. Remove sandbox event timers that generate artificial work (the simulation generates it naturally)
5. Consolidate game_loop_*.py files — most logic now lives in the simulation
6. Clean up tests — old event-based tests become simulation-based tests
7. Signal audit should show ZERO signals (no station-to-station communication exists)

---

## Phase Schedule

| Phase | Scope | Estimate | Risk |
|-------|-------|----------|------|
| 1: ShipModel Shell | New classes, dual-write, shadow state | 2 sessions | Low — additive, no changes to existing behaviour |
| 2: Station Views | 13 view classes, WebSocket changes | 3 sessions | Medium — client JSON shape changes need careful migration |
| 3: Commands | ~40-50 command classes, handler migration | 3 sessions | Medium — must maintain identical behaviour during transition |
| 4: Simulation Tick | Consolidate tick logic, room propagation | 3 sessions | High — this is where emergent behaviour replaces wired behaviour |
| 5: Cleanup | Remove old wiring, simplify game loop | 1–2 sessions | Low — mostly deletion |

**Total: ~12–14 Code sessions.** Each phase is independently testable. The game works at every stage. No big-bang cutover.

---

## Design Principles

1. **The simulation doesn't know about stations.** ShipModel has no concept of "this data is for Weapons" or "this event should notify HazCon." It's a physics model.

2. **Stations don't know about each other.** HelmView doesn't query WeaponsView. Both query ShipModel. Cross-station coordination happens because both stations see the same reality.

3. **Commands are the only write path.** No code outside the command interface should modify ship state. This makes the simulation deterministic and testable.

4. **Views are the only read path.** Stations don't subscribe to events — they read state snapshots. This eliminates the entire category of "missing handler" bugs.

5. **The simulation generates gameplay by existing.** Fires don't need a timer to start — they start because conditions in a room allow combustion. Casualties don't need a random number generator — they happen because crew are in dangerous rooms. Work exists because the ship has state that needs monitoring.

6. **Emergent over scripted.** The scenario system becomes simpler — instead of scripting individual events, it sets initial conditions and the simulation produces the consequences. A mission can say "start with a damaged reactor" and the simulation generates fires, radiation, crew injuries, and system failures as natural consequences.

---

## What This Means for Existing Systems

### Sandbox mode
The 14+ event timers mostly go away. The simulation generates fires, breaches, system damage, crew issues naturally. The sandbox only needs to control external factors: enemy spawn rate, environmental hazards in the world, and incoming transmissions. Everything internal to the ship is simulation-driven.

### Mission system
Missions set initial conditions (ship state, world entities, objectives) and define triggers based on simulation state (hull below threshold, entity destroyed, area reached). The `on_complete` actions modify simulation state through commands. The mission system is a thin layer on top of the simulation.

### Audio/visual
Stations subscribe to state changes in the ship model (fires starting, shields hit, hull damage) for audio/visual triggers. This is a notification system — not a gameplay system. If the audio handler is missing, the game still works. The current architecture breaks gameplay when handlers are missing.

### Testing
Tests become much simpler. Instead of testing event chains (A sends to B, B sends to C, C sends to D), tests set up simulation state, tick forward, and assert on the resulting state. "If a room has a fire at intensity 3 with 2 crew present for 10 seconds, crew health should decrease by X" — pure state-based testing.

---

## Files to Create

```
server/simulation/
    __init__.py
    ship_model.py          # ShipModel — the core class
    world_model.py         # WorldModel — entities, spatial
    room.py                # Room, FireState, BreachState, atmosphere
    section.py             # Structural section model
    systems.py             # ShipSystem base + concrete systems
    reactor.py             # ReactorModel, PowerGrid
    shields.py             # ShieldModel, per-facing
    weapons.py             # BeamArray, TorpedoTube, PointDefence
    sensors.py             # SensorModel, Contact, ActiveScan
    flight_deck.py         # FlightDeckModel, DroneModel
    crew.py                # CrewModel, CrewMember, team management
    resources.py           # ResourceModel — fuel, ammo, supplies
    comms.py               # CommsModel — signals, standings
    alerts.py              # AlertState — general orders, deck alerts
    
    commands/
        __init__.py
        base.py            # Command, CommandResult, CommandInterface
        helm.py            # SetHeading, SetThrottle, Evasive
        weapons.py         # FireTorpedo, FireBeam, SelectTarget, SetShieldFocus
        engineering.py     # SetPower, Overclock, StartRepair
        science.py         # StartScan, CancelScan, StartSectorScan
        hazard_control.py  # DispatchFireTeam, SealBulkhead, VentRoom, Evacuate
        security.py        # SendTeam, LockDoor, SetAlert
        medical.py         # Stabilise, Admit, Treat, Discharge
        captain.py         # SetPriorityTarget, IssueOrder, PlaceWaypoint, AcceptMission
        comms.py           # DecodeSignal, SendResponse, Hail
        ew.py              # ToggleCountermeasures, JamTarget
        flight_ops.py      # LaunchDrone, RecallDrone, SetDroneMission
        operations.py      # StartAssessment, DistributeIntel
        quartermaster.py   # AcceptTrade, AllocateResources
    
    views/
        __init__.py
        base.py            # StationView base class
        captain.py
        helm.py
        weapons.py
        engineering.py
        science.py
        medical.py
        security.py
        comms.py
        ew.py
        flight_ops.py
        operations.py
        hazard_control.py
        quartermaster.py
```

---

## Success Criteria

When v0.09 is complete:

1. **Zero station-to-station signals.** Stations read from the model and write through commands. No event wiring.
2. **All stations have work in sandbox.** The simulation generates fires, casualties, resource depletion, threats, and system degradation naturally. No artificial event timers needed for internal ship events.
3. **Contacts visible without scanning.** The sensor model detects entities based on range. Scanning adds detail. No station gates another station's access to world state.
4. **Cascading effects emerge from physics.** A fire in the engine room naturally reduces O2, injures crew, degrades the engine system, stresses the hull section, and spreads to adjacent rooms — all from one simulation tick, not from 6 separate event wires.
5. **The game works with zero stations manned.** Start a game, man no stations, advance 5 minutes. The ship should drift, systems should operate on defaults, fires should start from random events, crew should respond to emergencies via AI defaults. The simulation runs regardless of player input.
6. **Tests are state-based.** "Set room to X state, tick N times, assert room is in Y state." No more mocking event chains.
7. **6000+ existing tests still pass.** Migration is incremental. Nothing breaks during the transition.
