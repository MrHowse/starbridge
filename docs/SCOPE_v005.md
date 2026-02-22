# STARBRIDGE — v0.05 Scope
## "The Universe Update"

---

## 1. OVERVIEW

### 1.1 What v0.05 Adds

v0.04 built command and creativity — mission graphs, the Captain overhaul, save/resume, mission editor. v0.05 builds **the universe**:

- **Sector map system**: Multi-sector strategic grid and per-sector tactical map. Fog of war. Progressive scanning reveals the universe. Routes plotted across sectors.
- **Long-range Science scanning**: Sector sweep and multi-sector scan. Ties up Science for extended periods. Progressive reveal animation. Gives the crew strategic intelligence.
- **Space stations**: Friendly, neutral, hostile, and derelict. Docking for resupply, repair, crew transfer, intel. Multi-station docking event requiring coordination across roles.
- **Torpedo expansion**: Full torpedo loadout system with 8 types, magazine management, tactical selection based on Science data.
- **Enemy stations**: Fortified positions with shields, turrets, garrisons, and fighter bays. Assault mission design requiring approach planning and coordinated strikes.
- **Space creatures**: Passive fauna, territorial predators, parasitic organisms, hive swarms, and ancient leviathans. Study, communicate, avoid, or destroy — crew decides.
- **Environmental hazards as gameplay spaces**: Nebulae, asteroid fields, gravity wells, and radiation zones with gameplay properties beyond "avoid this."
- **Sandbox overhaul**: Event-driven sandbox that exercises all 12 stations, not just the combat triangle.
- **Bug fixes**: Logger debouncing, briefing screen fixes, WebSocket lifecycle cleanup, Medical deck selection, accessibility widget positioning, role bar functionality.

### 1.2 Design Principles

All previous principles carry forward. v0.05 adds:

- **The universe has geography**: Space isn't a featureless void. Sectors have identity, landmarks, hazards, and strategic value. Navigation is meaningful because locations matter.
- **Scanning is exploration**: The map starts dark. Every piece of information is earned through Science's work. The crew discovers the universe through their sensors, not through omniscient map data.
- **Encounters are ecosystems, not spawn points**: Enemies patrol routes, creatures migrate, stations have supply lines. The universe has internal logic that the crew can learn and exploit.
- **Every station has something to do in every situation**: Docking is multi-station. Creature encounters engage Science, Comms, Medical, and potentially Security. Environmental hazards affect Engineering, Helm, DC, and Science. No station should be idle during any game event.

### 1.3 Pre-Resolved Architectural Decisions

**Module-level globals stay for v0.05.** Multi-session is v0.06. This is the last version where we accept this constraint — v0.06 must address it.

**Sectors are data, not code.** Sector definitions are JSON files. Mission JSON references sector IDs. The sector map renderer reads sector data at game start. New sectors are authored without code changes.

**The multi-sector map is a MapRenderer layer, not a separate renderer.** The existing MapRenderer gains zoom levels: tactical (current), sector (zoomed out to full sector), and strategic (multi-sector grid). Zoom is continuous or stepped (configurable per station).

**Entity coordinates remain global (world space).** Sectors are overlaid as a named grid on the global coordinate system. An entity at (150000, 250000) is "in sector B3." Sectors don't create separate coordinate spaces — they're a labelling and visibility system.

**Space stations are entities with docking behaviour, not a new system.** Stations are WorldEntities with additional properties (services, defences, faction). Docking is a proximity-triggered state change, not a separate game mode. The game loop continues while docked — you can be attacked at dock.

---

## 2. SUB-RELEASE PLAN

### Dependency Graph

```
v0.05a (Bug fixes — logger, briefing, WebSocket, Medical, role bar, 
         a11y widget, sandbox activity)
  
v0.05b (Sector system — sector definitions, grid overlay, fog of war,
         sector properties)
v0.05c (Sector map UI — MapRenderer zoom levels, strategic view,
         sector labels, route plotting)
v0.05d (Long-range Science scanning — sector sweep, multi-sector scan,
         progressive reveal)
  └── b and c must complete before d (scanner needs sectors to reveal)

v0.05e (Space stations — entity type, services, transponders,
         sector map presence)
v0.05f (Docking system — proximity trigger, docking state, resupply,
         repair, crew transfer, multi-station coordination)
  └── e must complete before f

v0.05g (Torpedo expansion — 8 types, magazine management, tactical
         selection, Science frequency data integration)

v0.05h (Environmental hazards — nebula gameplay, asteroid fields,
         gravity wells, radiation zones, sector properties)

v0.05i (Enemy stations — fortified entities, shield generators,
         turrets, garrisons, fighter bays)
v0.05j (Station assault missions — approach planning, coordinated
         strikes, boarding, capture-or-destroy branches)
  └── i must complete before j

v0.05k (Space creatures — 5 creature types, encounter mechanics,
         study/communicate/avoid/destroy interactions)
v0.05l (Creature missions — 3-4 missions featuring creature encounters)
  └── k must complete before l

v0.05m (Sandbox overhaul — event system exercising all 12 stations)

v0.05n (New story missions — 4-5 missions showcasing all v0.05 systems)

v0.05o (Balance + integration + v0.05 gate)
```

### Key Ordering Constraints

- v0.05a (bug fixes) first — fix the foundation before building on it
- v0.05b-c (sector system) before v0.05d (scanning) — scanning reveals sectors
- v0.05e (stations) before v0.05f (docking) — must exist before you can dock
- v0.05g (torpedoes), v0.05h (hazards), and v0.05e-f (stations) are independent of each other
- v0.05i-j (enemy stations) can run in parallel with v0.05k-l (creatures)
- v0.05m (sandbox) and v0.05n (missions) benefit from all systems being complete
- v0.05o (gate) is always last

---

## 3. v0.05a — BUG FIXES + SANDBOX OVERHAUL

**Purpose**: Fix known issues from playtesting, improve sandbox for solo/testing play.

### 3.1 Bug Fixes

**Role bar** (critical): The hot-switch role bar must render on every station (all 12 + viewscreen). Clicking an unclaimed role switches to that station without going through the lobby. Clicking the player's current role on another station reclaims it seamlessly. Test: start as Captain → click Helm → click Weapons → click Captain. All transitions should be instant with no lobby round-trip.

**Medical deck selection**: Investigate and fix the deck panel click/hover bug. Check for z-index conflicts with accessibility widget, role bar, or notification overlays. Check for render loop (hover triggers re-render which resets hover). Verify: click each deck, see crew breakdown, no flickering.

**Accessibility widget positioning**: Move the ⚙ widget into the station header bar alongside volume controls and help button. Check all 12 stations for overlap.

**Briefing screen**: Fix missing `/client/shared/style.css` (404). Wire up `game.briefing_launch` handler on the server.

**WebSocket lifecycle**: Clean up broadcast race condition — check connection state before sending, remove closed connections immediately on close. Reduce `/api/status` polling to 5-second intervals (landing page) and 3-second (admin dashboard).

**Admin resume**: Disable resume button when no saves exist. Show clear error if resume fails.

**Logger debouncing**: Debounce `helm.heading_changed` and `helm.throttle_changed` — only log when the value hasn't changed for 200ms. Log final settled value, not every intermediate step. Server still processes every value for physics; only the logger debounces.

### 3.2 Sandbox Overhaul

Replace the minimal sandbox with an event-driven sandbox that exercises all stations:

**Event scheduler**: A sandbox-specific tick handler that generates random events at configured intervals:

| Event | Interval | Stations Engaged |
|-------|----------|-----------------|
| Enemy spawn (1-3 ships) | 60-90s | Weapons, Tactical, Helm, Science |
| Incoming transmission | 90-120s | Comms |
| System malfunction | 120-180s | Engineering, DC |
| Hull micro-damage | 120-180s | DC |
| Crew illness | 180-240s | Medical |
| Sensor anomaly | 90-150s | Science |
| Boarding attempt | 240-360s | Security, DC |
| Drone opportunity (scan target appears at edge of range) | 120-180s | Flight Ops |
| Enemy jamming attempt | 180-240s | EW |
| Distress signal | 180-300s | Comms, Helm, Captain |

Events scale with difficulty preset. Cadet gets fewer, slower events. Admiral gets frequent, overlapping crises. Events are independent — multiple can be active simultaneously.

### Acceptance Criteria

- [ ] Role bar switches stations instantly on all 12 stations
- [ ] Medical deck selection works without flickering
- [ ] Accessibility widget doesn't overlap any station controls
- [ ] Briefing screen loads with correct CSS and server handler works
- [ ] No WebSocket broadcast errors in server log during role switching
- [ ] Logger produces debounced helm/throttle events
- [ ] Sandbox generates events for all 12 stations within 5 minutes
- [ ] All existing tests pass

---

## 4. v0.05b — SECTOR SYSTEM

**Purpose**: Divide the game world into a named sector grid with properties, fog of war, and strategic significance.

### 4.1 Sector Definition

```
sectors/
├── sector_schema.json    # JSON schema for sector definitions
├── standard_grid.json    # Default 5×5 sector grid for missions
├── exploration_grid.json # Larger 8×8 grid for exploration missions
└── custom/               # Mission-specific sector layouts
```

**Sector JSON schema**:

```json
{
    "id": "B3",
    "name": "Kepler Reach",
    "grid_position": [1, 2],
    "world_bounds": {
        "min_x": 100000, "min_y": 200000,
        "max_x": 200000, "max_y": 300000
    },
    "properties": {
        "type": "nebula",
        "sensor_modifier": 0.6,
        "navigation_hazard": "moderate",
        "faction": "contested",
        "threat_level": "medium"
    },
    "features": [
        {
            "id": "kepler_station",
            "type": "friendly_station",
            "position": [150000, 250000],
            "name": "Kepler Research Station",
            "visible_without_scan": true
        },
        {
            "id": "asteroid_belt_1",
            "type": "asteroid_field",
            "bounds": { "centre": [130000, 230000], "radius": 15000 },
            "visible_without_scan": false
        }
    ],
    "patrol_routes": [
        {
            "faction": "hostile",
            "waypoints": [[120000, 210000], [180000, 260000], [140000, 290000]],
            "ship_count": 2,
            "ship_type": "scout"
        }
    ]
}
```

### 4.2 Fog of War

Each sector has a visibility state per game session:

| State | What's Shown | How to Reach |
|-------|-------------|-------------|
| **Unknown** | Nothing — sector cell is dark on strategic map | Default state |
| **Transponder** | Friendly stations and named features only (they broadcast) | Automatic for sectors containing friendly stations |
| **Scanned** | Major features visible (hazard zones, stations, large signatures). No individual ship data. | Long-range multi-sector scan (Science) |
| **Surveyed** | All features visible. Individual contacts shown at low detail. | Sector sweep scan (Science) while in-sector or adjacent |
| **Active** | Full tactical detail. All contacts with real-time updates. | Ship is currently in this sector |
| **Visited** | Decays from Active to Surveyed when you leave. Features persist, contacts go stale. | Ship was previously in this sector |

The fog of war state is tracked in the mission graph state (survives save/resume). Exploration missions start with most sectors Unknown. Combat missions might pre-reveal friendly space.

### 4.3 Sector Properties

Sector properties affect gameplay:

| Property | Effect |
|----------|--------|
| `nebula` | Sensor range × modifier (typically 0.4-0.7). Shields recharge slower. Cloaking is more effective. Visual: purple/blue tint on map. |
| `asteroid_field` | Navigation hazard — Helm must dodge or take hull damage. Provides cover (line-of-sight blocking). Mining opportunities. |
| `gravity_well` | Ship speed reduced. Fuel consumption increased. Can trap ships if engines are too weak. |
| `radiation_zone` | Crew take gradual damage unless shields are up. Science sensors get interference. Medical has ongoing casualties to manage. |
| `deep_space` | Nothing special — empty void between interesting sectors. Long travel times. Good for ambushes because there's nowhere to hide. |
| `friendly_space` | Reduced enemy spawns. Friendly patrols may assist. Stations available. |
| `contested_space` | Both friendly and hostile presence. Diplomatic encounters possible. Combat likely. |
| `hostile_space` | Enemy patrols, enemy stations, high threat. No friendly support. |

### 4.4 Server Implementation

```python
# server/models/sector.py
@dataclass
class Sector:
    id: str                          # "B3"
    name: str                        # "Kepler Reach"
    grid_position: tuple[int, int]   # (1, 2)
    world_bounds: Rect               # min/max world coordinates
    properties: SectorProperties
    features: list[SectorFeature]
    patrol_routes: list[PatrolRoute]
    visibility: SectorVisibility = SectorVisibility.UNKNOWN

@dataclass
class SectorGrid:
    sectors: dict[str, Sector]       # id → Sector
    grid_size: tuple[int, int]       # (5, 5)
    
    def sector_at_position(self, x: float, y: float) -> Sector | None:
        """Return the sector containing world position (x, y)."""
        ...
    
    def adjacent_sectors(self, sector_id: str) -> list[Sector]:
        """Return sectors sharing a border with the given sector."""
        ...
    
    def set_visibility(self, sector_id: str, level: SectorVisibility) -> None:
        ...
```

The SectorGrid is loaded at game start from the mission's referenced sector layout. It integrates with the existing world model — entities exist in world coordinates, and `sector_at_position` maps them to sectors.

### Acceptance Criteria

- [ ] Sector definitions load from JSON
- [ ] SectorGrid correctly maps world positions to sectors
- [ ] Adjacent sector lookup works
- [ ] Fog of war states transition correctly
- [ ] Sector properties are accessible to game systems
- [ ] Friendly station transponders auto-reveal sectors
- [ ] Sector data serialises for save/resume
- [ ] Tests for grid mapping, adjacency, visibility transitions

---

## 5. v0.05c — SECTOR MAP UI

**Purpose**: Multi-level zoom on the MapRenderer showing tactical, sector, and strategic views. Route plotting across sectors.

### 5.1 MapRenderer Zoom Levels

Extend the existing MapRenderer with three zoom levels:

**Tactical (current)**: What exists now — contacts, weapons, hazards within sensor range. The combat view. Range: ~30k units around the ship.

**Sector**: Shows the entire current sector. The ship is a small icon. Contacts appear as dots (not detailed wireframes). Hazard zones, stations, and sector features are visible. Sector boundaries shown as dashed lines. Adjacent sector names visible at edges. Range: one full sector (~100k units).

**Strategic**: Shows the multi-sector grid. Each sector is a cell with its name, major features as icons, and threat level colour. The ship's current sector is highlighted. Plotted routes show as lines across sectors. Fog of war visible (unknown sectors are dark). Range: entire grid.

**Zoom control**: Mouse wheel or pinch-to-zoom transitions smoothly between levels. Keyboard shortcuts: Z for zoom cycle, or 1/2/3 for specific levels. The zoom is continuous but snaps to named levels for clarity.

### 5.2 Per-Station Zoom Availability

| Station | Tactical | Sector | Strategic | Default |
|---------|---------|--------|-----------|---------|
| Captain | ✓ | ✓ | ✓ | Sector |
| Helm | ✓ | ✓ | ✓ | Tactical |
| Weapons | ✓ | ✗ | ✗ | Tactical |
| Science | ✓ | ✓ | ✓ | Sector |
| Tactical Officer | ✓ | ✓ | ✓ | Sector |
| Comms | ✓ | ✓ | ✗ | Sector |
| Flight Ops | ✓ | ✓ | ✗ | Sector |
| EW | ✓ | ✗ | ✗ | Tactical |
| Security | Interior only | ✗ | ✗ | Interior |
| Medical | Interior only | ✗ | ✗ | Interior |
| DC | Interior only | ✗ | ✗ | Interior |
| Viewscreen | Forward view | ✗ | ✗ | Forward |

### 5.3 Route Plotting

Helm and Captain can plot routes on the sector or strategic map:

1. Click a destination (sector, station, waypoint, or arbitrary point)
2. The system calculates a route: straight-line distance, estimated travel time at current speed, sectors traversed, hazards along the path
3. The route appears as a dashed line on all map-capable stations
4. Helm sees turn-by-turn waypoints: "Heading 045 for 3 minutes → enter sector C2 → heading 120 for 2 minutes → arrive at destination"
5. Multiple waypoints can be set (click, click, click for a multi-leg route)
6. Active route persists until completed, cancelled, or replaced

Route calculation accounts for sector properties: a route through a gravity well sector shows longer travel time. A route through a nebula shows reduced sensor range warning. A route through hostile space shows threat warning.

### 5.4 Sector Map Rendering

**Strategic view rendering**:
```
┌─────┬─────┬─────┬─────┬─────┐
│ A1  │ A2  │ A3  │ A4  │ A5  │
│     │ ░░░ │     │     │ ▓▓▓ │
│     │ NEB │     │     │ ??? │
├─────┼─────┼─────┼─────┼─────┤
│ B1  │ B2  │ B3  │ B4  │ B5  │
│ ⬡   │     │ ★●  │ ◊◊  │     │
│ STN │     │ YOU │ AST │     │
├─────┼─────┼─────┼─────┼─────┤
│ C1  │ C2  │ C3  │ C4  │ C5  │
│     │ ▲▲  │ ⬡   │     │ ▓▓▓ │
│     │ ENM │ STN │     │ ??? │
└─────┴─────┴─────┴─────┴─────┘

Key: ★ = ship, ⬡ = station, ◊ = asteroids, ░ = nebula, 
     ▲ = hostile, ▓ = unknown, ● = scanned contact
```

Wire aesthetic: sector grid as thin green lines, sector names in monospace, icons as simple geometric shapes, unknown sectors as dark cells with scanline pattern, the ship as a bright pulsing dot, routes as dashed amber lines.

### Acceptance Criteria

- [ ] Three zoom levels render correctly (tactical, sector, strategic)
- [ ] Smooth zoom transition between levels
- [ ] Strategic view shows sector grid with names and feature icons
- [ ] Fog of war visible on strategic view (unknown sectors dark)
- [ ] Route plotting works (click destination → route calculated → displayed)
- [ ] Route shows on all map-capable stations
- [ ] Helm sees turn-by-turn waypoints
- [ ] Route accounts for sector properties (travel time, hazard warnings)
- [ ] Captain and Helm can both plot routes
- [ ] Keyboard shortcuts work (Z cycle, 1/2/3 direct)

---

## 6. v0.05d — LONG-RANGE SCIENCE SCANNING

**Purpose**: Science can scan entire sectors and adjacent sectors for strategic intelligence.

### 6.1 Scan Types (Expanded)

Science now has three scan scales in addition to the four scan modes (EM/GRAV/BIO/SUB):

| Scale | Range | Duration | Ties Up Science | What It Reveals |
|-------|-------|----------|----------------|----------------|
| **Targeted** | Single entity | 5-10s | Partially (can still do passive) | Full entity detail per scan mode |
| **Sector sweep** | Current sector | 30-60s | Fully (no other scans possible) | All features, contacts, hazards in current sector. Sector visibility → Surveyed. |
| **Long-range** | Adjacent sectors | 120-180s | Fully (no other scans possible) | Major features in adjacent sectors. Sector visibility → Scanned. |

### 6.2 Sector Sweep Mechanic

When Science initiates a sector sweep:

1. The sensor display zooms out to show the full sector (automatic zoom to sector level)
2. A sweep line rotates outward from the ship's position (like a radar sweep but expanding)
3. As the sweep line passes over locations, features materialise on the map:
   - First pass (0-15s): Large features — stations, major hazard zones, large ship signatures
   - Second pass (15-30s): Medium features — asteroid clusters, patrol routes, anomalies
   - Third pass (30-45s): Small features — individual contacts, derelict ships, debris
   - Final refinement (45-60s): Detail — contact classifications, hazard density, resource signatures
4. Each reveal has a brief animation — contact pops in with a scan-line flash
5. During the sweep, Science cannot do targeted scans, mode switching, or any other sensor operation
6. A progress bar shows sweep completion
7. The Captain and Helm see the sector map updating in real-time as features are revealed

**Scan mode affects sector sweep**: The sweep runs in the currently active mode. EM sweep reveals energy signatures (ships, stations, power sources). GRAV sweep reveals mass concentrations (asteroids, gravity wells, debris). BIO sweep reveals life signs (crewed ships, creatures, habitable zones). SUB sweep reveals subspace phenomena (cloaked ships, subspace anomalies, communication sources). A full sector survey requires multiple sweeps in different modes — which takes 2-4 minutes of Science being fully occupied.

### 6.3 Long-Range Scan Mechanic

Multi-sector scanning works similarly but at lower resolution:

1. The sensor display zooms out to strategic view
2. Sweep radiates outward from the ship's sector to adjacent sectors
3. Only major features revealed — stations, large hazard zones, fleet-size ship concentrations
4. 120-180 seconds, fully occupies Science
5. Adjacent sectors go from Unknown to Scanned visibility

### 6.4 Scan Interruption

If the ship takes damage or enters combat during a sweep/long-range scan, Science gets a warning: "SCAN INTERRUPTED — combat detected. Continue scan or abort?" Continuing the scan means Science can't do targeted scans during the fight. Aborting saves partial results (whatever was revealed stays revealed, but the sweep doesn't complete). This creates a Captain decision: "Science, keep scanning or get me tactical data on those contacts?"

### 6.5 UI Changes

**Science station**: New scan scale selector alongside the mode selector:
```
[EM] [GRAV] [BIO] [SUB]    |    [TARGETED] [SECTOR] [LONG-RANGE]
```

When sector or long-range scan is active, the sensor canvas zooms out and shows the sweep animation. A large progress bar appears. The mode selector is locked (can't change mode mid-sweep). A cancel button allows aborting.

**Captain and Helm**: See the sector map updating in real-time as Science reveals features. A small indicator shows "SCIENCE: Sector sweep in progress — 45%."

### Acceptance Criteria

- [ ] Sector sweep reveals features progressively over 30-60 seconds
- [ ] Sweep animation shows expanding scan line with feature pop-ins
- [ ] Scan mode affects what the sweep reveals
- [ ] Long-range scan reveals adjacent sectors at low detail
- [ ] Science is fully occupied during sweeps (no targeted scans)
- [ ] Scan interruption on combat works (continue/abort choice)
- [ ] Partial results persist if scan is aborted
- [ ] Captain and Helm see real-time updates during sweeps
- [ ] Sector visibility states update correctly after scans
- [ ] Multiple sweeps in different modes build cumulative picture

---

## 7. v0.05e — SPACE STATIONS (Entity Type)

**Purpose**: Define space stations as world entities with services, factions, and transponders.

### 7.1 Station Types

| Type | Services | Faction | Always Visible | Defended |
|------|----------|---------|---------------|----------|
| **Military Outpost** | Weapons resupply, basic repair, intel | Friendly | Yes (transponder) | Yes (turrets, patrols) |
| **Civilian Station** | Medical facilities, food, atmosphere | Friendly/Neutral | Yes (transponder) | Light (security, no weapons) |
| **Trade Hub** | Everything at a cost (time/score penalty) | Neutral | Yes (transponder) | Moderate |
| **Research Station** | Sensor upgrades, data packages, specimens | Friendly | Yes (transponder) | None (fragile) |
| **Repair Dock** | Full hull/system repair | Friendly | Yes (transponder) | Moderate |
| **Derelict Station** | Salvageable — risk/reward | None | No (requires scan) | Varies (traps, hazards) |
| **Enemy Outpost** | None (hostile) | Hostile | No (requires scan) | Yes (see v0.05i) |

### 7.2 Station Entity Model

```python
@dataclass
class StationEntity(WorldEntity):
    station_type: str                    # "military", "civilian", etc.
    faction: str                         # "friendly", "neutral", "hostile"
    services: list[str]                  # ["weapons_resupply", "hull_repair", ...]
    docking_range: float = 2000.0        # Must be within this range to dock
    docking_ports: int = 2               # Max ships that can dock simultaneously
    transponder_active: bool = True      # Broadcasts position to all
    shields: float = 100.0               # Station shields (if defended)
    hull: float = 500.0                  # Station hull (much tougher than ships)
    defences: list[Defence] = field(default_factory=list)  # Turrets, etc.
    garrison: int = 0                    # Marines for boarding defence
    inventory: dict[str, int] = field(default_factory=dict)  # Available supplies
```

### 7.3 Station Transponders and Sector Map

Stations with `transponder_active = True` automatically reveal their sector on the strategic map at Transponder visibility. The station appears as a named icon. This means friendly infrastructure is always visible — the crew always knows where their nearest resupply is. Derelict and enemy stations require scanning to discover.

### Acceptance Criteria

- [ ] Station entities spawn and persist in the world
- [ ] Transponder stations appear on sector map without scanning
- [ ] Station types have correct service lists
- [ ] Stations appear on all map-capable stations at appropriate zoom
- [ ] Station hull/shields work (can be damaged/destroyed)
- [ ] Derelict stations only appear after scanning
- [ ] Station entity serialises for save/resume

---

## 8. v0.05f — DOCKING SYSTEM

**Purpose**: Multi-station coordinated docking event for resupply, repair, and crew operations.

### 8.1 Docking Flow

1. **Approach**: Helm manoeuvres within docking range (2000 units). Speed must be below 10% throttle.
2. **Request clearance**: Comms hails the station and requests docking permission. Friendly stations grant immediately. Neutral stations may negotiate (mission score cost). Hostile stations deny.
3. **Docking sequence**: Helm holds steady (auto-pilot locks position). Engineering manages power transfer (station provides auxiliary power — engine shutdown required). A 10-second docking animation plays.
4. **Docked state**: Ship is stationary and attached. Services panel appears on relevant stations. Engines offline (Helm has no control). Shields can stay up but at reduced power.
5. **Service selection**: The crew decides what to resupply/repair. Each service takes time. Multiple services can run in parallel but total docking time increases.
6. **Undocking**: Captain orders undock. 5-second undocking sequence. Ship drifts clear. Engines back online.

### 8.2 Per-Station Docking Roles

| Station | Docking Responsibility |
|---------|----------------------|
| **Helm** | Approach and hold position. Auto-locked during dock. |
| **Comms** | Request clearance. Negotiate terms at neutral stations. |
| **Engineering** | Manage power transfer. Shut down engines, redirect power to repair/resupply systems. |
| **Weapons** | Select torpedo resupply types and quantities. Manage magazine loading. |
| **Medical** | Transfer critical casualties to station hospital. Receive medical supplies. |
| **Security** | Monitor docking seal integrity. Watch for stowaways/sabotage. Manage crew shore leave. |
| **DC** | Authorise hull repair (structural work only possible at dock). Manage atmospheric resupply. |
| **Science** | Download sensor data packages (reveals additional sector data). Receive equipment upgrades. |
| **Flight Ops** | Service drones and shuttles in station hangar. Faster refuel/rearm than field ops. |
| **EW** | Update electronic warfare databases (new countermeasure profiles). |
| **Captain** | Authorise docking. Select service priorities. Authorise undocking. Monitor overall progress. |
| **Tactical** | Assess threat during dock (vulnerability window). Plan departure route. |

### 8.3 Station Services

| Service | Duration | Effect | Station |
|---------|----------|--------|---------|
| Torpedo resupply | 30s per type | Refill magazine for selected torpedo types | Weapons |
| Hull repair | 60s | Restore hull to 100% | DC |
| System repair | 20s per system | Restore system health to 100% | Engineering |
| Medical transfer | 45s | Transfer critical crew to station, receive fresh crew | Medical |
| Atmospheric resupply | 30s | Refill atmosphere reserves to 100% | DC |
| Sensor data package | 30s | Reveal 1-2 additional sectors to Scanned visibility | Science |
| Drone service | 40s | Refuel all drones, replace lost drones | Flight Ops |
| EW database update | 30s | Improve countermeasure effectiveness by 10% for rest of mission | EW |
| Crew rest | 60s | Restore crew morale (future mechanic) and minor health recovery | Medical |
| Intel briefing | 30s | Reveal enemy patrol routes in adjacent sectors | Comms |

Services run in parallel. Total docking time = longest single service. Captain can cut short ("Emergency undock!") to abort incomplete services.

### 8.4 Vulnerability During Dock

The ship is vulnerable while docked: engines offline, manoeuvrability zero, shields at 50% capacity. If enemies attack during docking, the Captain must decide: complete the resupply (we need those torpedoes) or emergency undock (we need to manoeuvre). The station may provide defensive fire (friendly stations only). This creates tension — docking is valuable but risky in contested space.

### Acceptance Criteria

- [ ] Helm can approach and dock with a station
- [ ] Comms clearance request works
- [ ] Docking sequence animation plays
- [ ] Services panel appears on relevant stations while docked
- [ ] Each service runs for the correct duration
- [ ] Multiple services run in parallel
- [ ] Torpedo resupply refills magazine
- [ ] Hull repair restores hull
- [ ] Emergency undock works mid-service
- [ ] Ship is vulnerable while docked (shields reduced, no engines)
- [ ] Station defensive fire works (friendly stations)
- [ ] Captain authorises dock/undock

---

## 9. v0.05g — TORPEDO EXPANSION

**Purpose**: Full torpedo loadout with 8 types, magazine management, and tactical selection.

### 9.1 Torpedo Types

| Type | Damage | Speed | Special | Magazine | Reload |
|------|--------|-------|---------|----------|--------|
| **Standard** | 50 | Medium | None — reliable baseline | 8 | 3s |
| **Homing** | 35 | Medium | Tracks target, adjusts course. Spoofable by EW countermeasures. | 4 | 4s |
| **Ion/EMP** | 10 hull | Medium | Drains shields 100%. Disables random system 10s. Useless vs unshielded. | 4 | 5s |
| **Piercing** | 40 | Slow | Ignores 75% shield absorption. The anti-shield-tank choice. | 4 | 4s |
| **Heavy** | 100 | Very slow | Massive damage. Easily intercepted by point defence. | 2 | 8s |
| **Proximity** | 30 (AOE) | Medium | Detonates within 2000 units. Hits all entities in blast radius. | 4 | 4s |
| **Nuclear** | 200 | Slow | Captain authorisation required. 1-2 per mission. Devastating. | 1-2 | 10s |
| **Experimental** | Varies | Varies | Station resupply only. Subspace (ignores shields), gravity (slows area), sensor (permanent paint). | 1 | 6s |

### 9.2 Magazine Management

Each torpedo type has a separate magazine count. The ship starts with a loadout defined by the ship class JSON:

```json
"torpedo_loadout": {
    "standard": 8,
    "homing": 4,
    "ion": 4,
    "piercing": 4,
    "heavy": 2,
    "proximity": 4,
    "nuclear": 1,
    "experimental": 0
}
```

When a magazine is empty, that type is unavailable. Resupply at stations restores to maximum (or a specified amount for trade hubs).

### 9.3 Weapons UI Changes

```
TORPEDO CONTROL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Type: [STD] [HOM] [ION] [PRC] [HVY] [PRX] [NUC] [EXP]
       8/8   4/4   3/4   4/4   2/2   4/4   1/1   0/0
       
Selected: HOMING (35 dmg, tracking, spoofable)
Tube 1: LOADED [FIRE]    Tube 2: RELOADING 2s...

BEAM FREQUENCY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[ALPHA] [BETA] [GAMMA] [DELTA]
Target shield freq: BETA (from Science EM scan)
Current beam freq: ALPHA — MISMATCHED (50% damage)
```

### 9.4 Tactical Decision Matrix

The Weapons player must consider:

- **Shield status** (Science EM scan): Shielded → Ion first to strip shields, then Standard. Unshielded → Piercing or Standard for direct hull damage.
- **Target speed** (Science data): Fast scout → Homing (tracks it). Slow cruiser → Heavy (won't be dodged).
- **Point defence** (EW assessment): Target has PD → Homing or Standard (faster, harder to intercept). No PD → Heavy for maximum damage.
- **Cluster formation**: Multiple ships grouped → Proximity for area damage. Single target → direct fire types.
- **Beam frequency match**: Science provides enemy shield frequency → Weapons matches beam frequency for 150% damage.

### Acceptance Criteria

- [ ] All 8 torpedo types implemented with correct stats
- [ ] Magazine tracking per type
- [ ] Weapons UI shows type selector with magazine counts
- [ ] Each torpedo type has correct special behaviour (tracking, shield drain, AOE, etc.)
- [ ] Ion torpedo disables enemy system for 10 seconds
- [ ] Proximity torpedo hits multiple targets in blast radius
- [ ] Nuclear requires Captain authorisation (existing mechanic)
- [ ] Beam frequency selector works
- [ ] Frequency matching multiplier applies (150% matched, 50% mismatched)
- [ ] Science EM scan reveals enemy shield frequency
- [ ] Resupply at stations refills torpedoes

---

## 10. v0.05h — ENVIRONMENTAL HAZARDS AS GAMEPLAY

**Purpose**: Nebulae, asteroid fields, gravity wells, and radiation zones create gameplay opportunities, not just obstacles.

### 10.1 Nebula Gameplay

**Effects**: Sensor range reduced by sector modifier (40-70%). Shields recharge 50% slower. EM and GRAV scans degraded (range reduced further). SUB scan unaffected (subspace phenomena penetrate nebulae).

**Gameplay opportunities**: Hide in a nebula to break contact with pursuing enemies (they lose sensor lock). Ambush from a nebula (exit at close range before enemies can react). EW jamming is more effective inside nebulae (stacks with sensor reduction). Science sector sweep inside a nebula takes 50% longer but reveals hidden objects that nebula interference was masking.

**Visual**: Purple/blue tint on the map. Fog particles on the viewscreen. Sensor display shows interference static.

### 10.2 Asteroid Field Gameplay

**Effects**: Navigation hazard — Helm takes periodic hull damage if moving above 30% throttle without navigating carefully (route calculation puzzle). Line-of-sight blocking — contacts behind asteroids are invisible to direct scans.

**Gameplay opportunities**: Use asteroids as cover during combat (break line-of-sight to enemy weapons). Mine asteroids for resources (future mechanic — DC or Engineering extracts materials). Hide behind a large asteroid for an ambush. Derelict ships and hidden stations are often found in asteroid fields (exploration incentive).

**Visual**: Scattered grey polygons on the map. Asteroids as wireframe rocks on the viewscreen. Proximity warning when moving fast.

### 10.3 Gravity Well Gameplay

**Effects**: Ship speed reduced proportional to well strength. Fuel consumption increased. Weak engines can get trapped (Engineering must boost engines above threshold to escape). Torpedoes curve in gravity wells (affects targeting).

**Gameplay opportunities**: Use a gravity well to slingshot (Helm approaches at the right angle and speed to get a speed boost on exit — a skill manoeuvre). Drag enemies into a gravity well to slow them (they're affected too). Gravity wells can be used to redirect torpedoes (fire a torpedo into the well's curve to hit a target around a corner — an advanced Weapons technique that Tactical can plan).

**Visual**: Concentric blue rings on the map. Distortion effect on the viewscreen. Ship shudder when inside.

### 10.4 Radiation Zone Gameplay

**Effects**: Crew take gradual damage (Medical has ongoing casualties). Sensors get interference (similar to nebula but affects all modes). Shields absorb some radiation if active (Engineering must balance shield power vs other systems).

**Gameplay opportunities**: Some creatures live in radiation zones (Bio-adapted — studying them requires entering the zone). Valuable salvage in irradiated wrecks (risk/reward). Enemy ships avoid radiation zones (use them as safe corridors if your Medical can handle the crew damage). Quick transit through a radiation zone is sometimes faster than going around.

**Visual**: Yellow/green tint on the map. Warning symbols. Geiger counter audio effect on all stations.

### Acceptance Criteria

- [ ] Nebula sectors reduce sensor range and affect scan modes
- [ ] Hiding in nebula breaks enemy sensor contact
- [ ] Asteroid fields cause navigation damage at high speed
- [ ] Asteroids block line-of-sight for scans and weapons
- [ ] Gravity wells reduce ship speed and affect torpedoes
- [ ] Radiation zones cause crew damage and sensor interference
- [ ] Shields absorb radiation (Engineering power tradeoff)
- [ ] Environmental visuals render on map and viewscreen
- [ ] Sector properties correctly apply all environmental effects
- [ ] Environmental effects are documented in the manual

---

## 11. v0.05i — ENEMY STATIONS

**Purpose**: Fortified hostile positions with multiple defensive systems.

### 11.1 Enemy Station Components

An enemy station is a StationEntity with hostile faction and defensive systems:

**Shield generators** (2-4): Each covers a section of the station. Destroying a generator creates a weak spot (no shields on that arc). Generators can be targeted individually by Weapons.

**Beam turrets** (4-8): Auto-fire at targets in range. Each turret has a firing arc. Turrets can be destroyed. Their fire rate and damage scale with the station's power (damaging the station's reactor reduces all turret effectiveness).

**Torpedo launchers** (1-2): Fire heavy torpedoes at approaching ships. Long reload time. High damage. Point defence can intercept them.

**Fighter bay** (0-2): Launches small fighter craft that harass approaching ships. Fighters are weak individually but numerous (3-5 per bay). Destroying the bay stops launches.

**Sensor array**: Long-range detection. If active, the station calls reinforcements when attacked. EW can jam the array to prevent the distress call. Destroying the array blinds the station (turrets become less accurate).

**Garrison**: Marines for boarding defence. If the crew boards the station, they face the garrison in room-to-room combat (using the Security interior mechanic on the station's layout).

### 11.2 Enemy Station Interiors

Each enemy station has its own interior layout (smaller than a ship — 8-12 rooms):
- Reactor room (destroying this cripples the station)
- Shield generator rooms (one per generator)
- Fighter bay
- Command centre (capturing this captures the station)
- Armoury
- Corridors connecting all rooms

If Security boards the station (via shuttle from Flight Ops), the Security player gets a second interior map — the station interior — alongside their ship interior. They manage two tactical situations simultaneously (or the crew assigns a second player to manage the station boarding using the multi-role tab system).

### Acceptance Criteria

- [ ] Enemy stations spawn with shield generators, turrets, launchers, and fighters
- [ ] Individual components can be targeted and destroyed
- [ ] Destroying shield generators creates exploitable weak spots
- [ ] Turrets auto-fire at ships in range
- [ ] Fighter bay launches fighters periodically
- [ ] Sensor array calls reinforcements (unless jammed by EW)
- [ ] Enemy station has an interior layout for boarding
- [ ] Boarding combat works on station interior
- [ ] Station can be captured (command centre secured) or destroyed

---

## 12. v0.05j — STATION ASSAULT MISSIONS

**Purpose**: 2-3 missions designed around attacking fortified enemy stations.

### 12.1 Mission: "Fortress"

**Crew size**: 8-12 | **Ship class**: Cruiser, Battleship

**Summary**: Assault a heavily defended enemy outpost. Multiple approach strategies.

**Graph structure**:
- Arrive in sector (sequential)
- Sector sweep reveals station and defences (Science)
- **Branch: Approach strategy**
  - Stealth approach (SUB scan for blind spots, EW spoofs signature, slow approach avoiding sensor range) → board and capture
  - Direct assault (Tactical plans strike, Weapons targets shield generators first) → destroy from range
  - Combined (disable sensors first with EW, then close for targeted strikes on generators, then board) → most complex but most rewarding
- Execute chosen strategy (varies by branch)
- Handle reinforcements if sensor array wasn't destroyed/jammed
- Victory: station captured or destroyed

### 12.2 Mission: "Supply Line"

**Crew size**: 6-10 | **Ship class**: Frigate, Cruiser

**Summary**: Destroy an enemy supply depot to cut off their fleet. The depot is lightly defended but resupply ships arrive periodically.

**Graph structure**:
- Navigate to depot sector
- Sector sweep reveals depot and patrol routes
- **Parallel**: Destroy the depot AND intercept supply ships (if supply ships dock, depot defences strengthen)
- **Conditional**: Every 3 minutes a supply ship arrives from a random adjacent sector. If it docks, depot launches additional fighters.
- Victory: depot destroyed and no supply ships escaped to warn the fleet

### Acceptance Criteria

- [ ] Both missions playable with multiple approach strategies
- [ ] Stealth approach works (EW jamming, slow approach)
- [ ] Direct assault works (shield generator targeting, coordinated fire)
- [ ] Boarding works (shuttle launch, station interior combat)
- [ ] Reinforcement mechanic works (sensor array → distress call → enemy ships arrive)
- [ ] Missions have meaningful branches with different crew experiences

---

## 13. v0.05k — SPACE CREATURES

**Purpose**: Five creature types with diverse interaction models beyond combat.

### 13.1 Creature Types

#### Void Whale (Passive)
- Enormous (appears as a massive signature on sensors). Harmless.
- BIO scan reveals species data. Extended study (60s scan) yields research score bonus.
- Getting within 1000 units startles it — it flees, generating a sensor-disrupting wake (all scans in the area interrupted for 10s).
- **Interaction model**: Observe carefully. Don't get too close. Science studies, everyone else stays back.

#### Rift Stalker (Territorial Predator)
- Claims a zone and attacks anything entering it. Fast, strong, adapted to space.
- EM scan reveals it's biological, not a ship (different engagement rules).
- **Four interaction paths**: Fight (hard — high hull, fast, regenerates), Distract (Flight Ops drones as bait, EW spoofed signatures draw it away), Communicate (Comms attempts frequency matching with its vocalisation pattern — unique puzzle), Sedate (Science BIO scan identifies a sedation frequency, Comms broadcasts it, creature sleeps for 2 minutes — enough to pass through).
- **Interaction model**: Crew chooses approach. Captain decides risk level.

#### Hull Leech (Parasitic)
- Attaches to hull, eats through it. DC sees hull integrity dropping in a specific section. Not visible on external sensors — BIO scan required to detect.
- **Three removal methods**: Depressurise affected section (kills leech, loses atmosphere, crew evacuation needed), EVA repair team (Security escorts, DC repairs, Medical treats injuries), Electrical discharge (Engineering overcharges hull plating in that section — damages the system but kills the leech instantly).
- **Interaction model**: Crisis management. DC leads, multiple stations support.

#### Swarm (Hive Intelligence)
- Thousands of tiny creatures that collectively attack. Individually harmless, collectively devastating.
- Adapt to tactics: beams cause them to spread (harder to hit), torpedoes cause them to cluster (area weapons work but they're a harder single target).
- Science must study adaptation pattern (frequency matching puzzle with shifting pattern).
- EW can disrupt their communication frequency (discovered by Science scan), causing the swarm to disperse.
- **Interaction model**: Puzzle-combat hybrid. Science drives the solution, EW executes, Weapons covers.

#### Ancient Leviathan (Dormant Giant)
- Enormous ancient creature, recently awakened. Not hostile — confused, heading toward a populated sector.
- Destroying it is possible but takes everything (massive hull, high damage output when agitated).
- Communicating with it requires: Science GRAV scan (it communicates via gravity waves), Comms decodes its "language" (unique puzzle), then Comms can redirect it.
- **Interaction model**: Multi-stage diplomacy/science challenge. The "right" answer is communication, but combat is always available as the desperate fallback.

### 13.2 Creature Entity Model

```python
@dataclass
class CreatureEntity(WorldEntity):
    creature_type: str           # "void_whale", "rift_stalker", etc.
    behaviour_state: str         # "idle", "feeding", "aggressive", "fleeing", "sedated"
    hull: float                  # Creature health
    territory_radius: float      # For territorial creatures
    adaptation_state: dict       # For swarm — tracks tactical adaptation
    communication_progress: float  # For creatures that can be communicated with
    study_progress: float        # Research scan progress (0-100%)
    
    def tick(self, game_state: dict) -> list[Action]:
        """Creature AI — behaviour varies by type and state."""
        ...
```

### Acceptance Criteria

- [ ] All 5 creature types spawn and behave correctly
- [ ] Void whale flees when approached, generates sensor wake
- [ ] Rift stalker attacks in territory, all 4 interaction paths work
- [ ] Hull leech attaches and damages hull, all 3 removal methods work
- [ ] Swarm adapts to weapon types, Science puzzle identifies pattern
- [ ] Ancient leviathan communication chain works (GRAV scan → decode → redirect)
- [ ] Creature entities appear on sensors and map
- [ ] BIO scan reveals creature-specific data
- [ ] Creatures integrate with the mission graph (triggers for creature events)

---

## 14. v0.05l — CREATURE MISSIONS

**Purpose**: 3 missions featuring creature encounters as primary gameplay.

### 14.1 Mission: "Migration"

**Crew size**: 6-12 | **Ship class**: Any

A void whale pod is migrating through a shipping lane. Protect them from poachers (hostile ships) while ensuring Science completes a research survey. The whales spook easily — combat near them causes them to scatter. The crew must balance defending the whales against fighting too close to them.

### 14.2 Mission: "The Nest"

**Crew size**: 8-12 | **Ship class**: Frigate, Cruiser

Navigate through a sector claimed by rift stalkers to reach a stranded research station. Multiple stalker territories overlap. The crew must either fight through (expensive, dangerous), negotiate passage (Comms with each stalker — time-consuming), or find a path between territories (Science GRAV mapping reveals territory boundaries).

### 14.3 Mission: "Outbreak"

**Crew size**: 8-12 | **Ship class**: Frigate, Medical Ship

A swarm has infested a space station. The crew must dock, study the swarm behaviour, disrupt their communication, and evacuate station personnel before the swarm overwhelms the station's structure. Medical heavy (treating infested personnel), Science heavy (analysing the swarm), Security heavy (holding corridors while evacuation proceeds).

### Acceptance Criteria

- [ ] All 3 missions playable with creature encounters as primary challenge
- [ ] Missions use branching graph structure
- [ ] Non-combat solutions viable for each mission
- [ ] Creature-specific mechanics (whale spooking, stalker territories, swarm adaptation) drive gameplay

---

## 15. v0.05m — SANDBOX OVERHAUL (CONTINUED)

Building on v0.05a's event system, add creature and station encounters to sandbox:

- Friendly station always present in the sector (docking available)
- Creature spawns every 5-8 minutes (random type, scaled to difficulty)
- Derelict station appears for exploration
- Environmental hazard zones present in sandbox sector layout

This ensures every v0.05 system is testable in sandbox without running specific missions.

### Acceptance Criteria

- [ ] Sandbox sector has a friendly station, hazard zones, and varied encounters
- [ ] Docking works in sandbox
- [ ] Creatures spawn and interact correctly in sandbox
- [ ] All 12 stations have regular activity in sandbox

---

## 16. v0.05n — NEW STORY MISSIONS

**Purpose**: 4-5 missions showcasing all v0.05 systems working together.

### 16.1 Mission: "The Long Patrol"

Multi-sector navigation mission. The crew patrols a 3×3 sector grid, scanning each sector, docking for resupply at a midpoint station, and responding to threats discovered during scanning. The mission is different every time because sector scanning reveals randomised encounters.

### 16.2 Mission: "Deep Space Rescue"

A distress signal from an unknown sector. The crew must navigate through hazardous sectors (nebula, asteroids, radiation), scan for the source, dock with a derelict station to evacuate survivors, and fight off scavengers who are also after the derelict. Docking, creatures (hull leeches in the wreck), and environmental hazards all feature.

### 16.3 Mission: "Siege Breaker"

A friendly station is under siege by an enemy fleet operating from a nearby enemy station. The crew must break through the blockade (combat), dock with the friendly station (resupply), then assault the enemy station (v0.05j mechanics). Full v0.05 showcase.

### 16.4 Mission: "First Survey"

Pure exploration. An unmapped 5×5 sector grid. No predetermined enemies. The crew maps the entire region using sector and long-range scans. Discovers stations, creatures, hazards, and anomalies. Score based on survey completeness. A non-combat mission that makes Science, Helm, Comms, and Flight Ops the stars.

### Acceptance Criteria

- [ ] All 4 missions playable
- [ ] Each mission uses at least 3 v0.05 systems (sectors, stations, creatures, hazards, torpedoes)
- [ ] First Survey is completable without firing a weapon
- [ ] Siege Breaker exercises docking and station assault
- [ ] Missions use graph branching and conditional objectives

---

## 17. v0.05o — BALANCE + INTEGRATION + v0.05 GATE

### 17.1 Balance Pass

- Torpedo damage values tuned across all 8 types
- Station service durations tuned for pacing
- Creature health/damage tuned per type
- Environmental hazard modifiers tuned
- Sector scan durations tuned (not too fast, not boring)
- Sandbox event intervals tuned for engagement

### 17.2 v0.05 Gate Checklist

- [ ] Sector system works (grid, fog of war, properties)
- [ ] All three map zoom levels render correctly
- [ ] Route plotting works across sectors
- [ ] Sector sweep and long-range scan work
- [ ] Space stations dock-able with full service menu
- [ ] Emergency undock works
- [ ] All 8 torpedo types functional
- [ ] Beam frequency matching works
- [ ] Enemy stations assaultable (all components targetable)
- [ ] Station boarding works
- [ ] All 5 creature types behave correctly
- [ ] Environmental hazards affect gameplay
- [ ] All new missions playable
- [ ] Sandbox exercises all stations
- [ ] All bug fixes verified
- [ ] Logger debouncing works
- [ ] All existing tests pass
- [ ] Performance acceptable with sectors + creatures + stations active

---

## 18. ESTIMATED SCOPE

| Sub-Release | Estimated Sessions | Notes |
|-------------|-------------------|-------|
| v0.05a Bug fixes + sandbox events | 3-4 | Mixed bag of fixes + event scheduler |
| v0.05b Sector system | 4-5 | Data model + fog of war + properties |
| v0.05c Sector map UI | 5-6 | Three zoom levels + route plotting |
| v0.05d Long-range scanning | 4-5 | Sweep animation + scan interruption |
| v0.05e Space stations | 3-4 | Entity type + transponders + services |
| v0.05f Docking system | 5-6 | Multi-station coordination + service menu |
| v0.05g Torpedo expansion | 4-5 | 8 types + magazine + beam frequencies |
| v0.05h Environmental hazards | 4-5 | 4 hazard types with gameplay effects |
| v0.05i Enemy stations | 5-6 | Components + defences + interior |
| v0.05j Station assault missions | 4-5 | 2 missions with multiple strategies |
| v0.05k Space creatures | 6-8 | 5 creature types with unique AI |
| v0.05l Creature missions | 4-5 | 3 missions |
| v0.05m Sandbox continued | 2-3 | Stations + creatures in sandbox |
| v0.05n Story missions | 5-6 | 4 missions using all systems |
| v0.05o Balance + gate | 4-5 | Tuning + comprehensive testing |

**Total: ~65-80 sessions.** The largest version yet. Creature AI (v0.05k) and the sector map system (v0.05b-d) are the most complex. Docking (v0.05f) is the most multi-station coordinated feature.

---

## 19. WHAT v0.05 ENABLES

After v0.05, Starbridge has:
- **A universe with geography**: Sectors, stations, hazards, creatures, and strategic navigation
- **Tactical depth**: 8 torpedo types, beam frequencies, environmental exploitation, enemy station assaults
- **Exploration gameplay**: Non-combat missions built on scanning, mapping, and discovery
- **Creature encounters**: Five unique interaction models beyond "shoot it"
- **Economic decisions**: Station resupply, service prioritisation, docking risk/reward
- **Every station engaged in every situation**: Docking, creatures, hazards, and station assaults all require multi-station coordination

The remaining gaps for "1.0": networked play beyond LAN (v0.06), dynamic campaign mode (linked missions with persistent consequences), fleet battles (multi-ship cooperation), community mission sharing. Those are v0.06 concerns.

---

*Document version: v0.05-scope-1.0*
*Last updated: 2026-02-21*
*Status: DRAFT — Begin implementation after v0.04 bug fixes and playtest*
