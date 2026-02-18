# STARBRIDGE — Bridge Crew Simulator
## v0.01 Scoping Document for AI Engineer

---

## 1. PROJECT BACKGROUND

### 1.1 Vision

Starbridge is a cooperative multiplayer bridge crew simulator inspired by Artemis Spaceship Bridge Simulator. Players connect via web browsers on a local network, each taking on a distinct role aboard a starship. The magic of the game is **interdependence** — no single player can succeed alone. The captain can't fire weapons, the weapons officer can't steer, the engineer controls the power everyone depends on, and the science officer holds information no one else can see.

The original Artemis suffered from painful setup processes, platform compatibility issues, and janky networking. Starbridge solves this by being entirely web-based — any device with a modern browser becomes a station.

### 1.2 Design Philosophy

- **Interdependence over individual power**: Every role must need other roles. The fun comes from communication and coordination, not individual skill.
- **Complexity as a dial, not a wall**: Each system should have a basic mode that's immediately playable and advanced modes that reward mastery. This applies to both development (build simple first, layer complexity) and gameplay (new players can jump in).
- **Missions, not just combat**: While space combat is the obvious draw, the system must support exploration, diplomacy, rescue, stealth, puzzle, and landing missions from its architectural foundations.
- **Wire aesthetic, not placeholder aesthetic**: The wireframe/vector look is a deliberate art direction (think Battlezone, DEFCON, Alien's ship computers), not a shortcut. Lean into it with scanlines, phosphor glow, and crisp vector lines.
- **Flexible and extensible**: The architecture must support adding new roles, new mission types, new ship systems, and new game mechanics without rewriting core systems.

### 1.3 Target Experience

5-6 players gather in a room (or across a LAN). One person starts the server on a laptop. Everyone else opens a browser and navigates to the server address. They see a lobby, choose roles, and launch a mission. For the next 30-60 minutes, the room is full of people shouting coordinates, requesting power transfers, calling out enemy positions, and arguing about whether to fight or flee. When the mission ends, they debrief, laugh about disasters, and start another one.

---

## 2. ARCHITECTURE

### 2.1 Overview

```
┌─────────────────────────────────────────────┐
│              FastAPI Server                  │
│                                             │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  │
│  │  Lobby   │  │   Game   │  │  Mission   │  │
│  │ Manager  │  │   Loop   │  │  Engine    │  │
│  └─────────┘  └──────────┘  └───────────┘  │
│                                             │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  │
│  │  Ship   │  │  World   │  │    AI      │  │
│  │  State  │  │  State   │  │  Director  │  │
│  └─────────┘  └──────────┘  └───────────┘  │
│                                             │
│         WebSocket Hub (role-filtered)       │
└──────────┬──────────┬──────────┬────────────┘
           │          │          │
     ┌─────┴──┐ ┌─────┴──┐ ┌────┴───┐
     │ Helm   │ │Weapons │ │Engineer│  ... (browser clients)
     │Client  │ │Client  │ │Client  │
     └────────┘ └────────┘ └────────┘
```

### 2.2 Technology Stack

| Component | Technology | Reasoning |
|-----------|-----------|-----------|
| **Server** | Python 3.12+ / FastAPI | Async-native, excellent WebSocket support, familiar to the project owner. FastAPI's dependency injection is useful for managing game state. |
| **Game Loop** | `asyncio` task | Must be decoupled from request handling. Fixed timestep (10 ticks/sec for v0.01) with interpolation data sent to clients. |
| **Real-time Comms** | Native FastAPI WebSockets | Lighter than Socket.IO. We'll implement our own message protocol (JSON). Reconnection logic is simple enough to hand-roll for LAN use. |
| **Game State** | Python dataclasses / Pydantic models | In-memory only. No database during gameplay. Pydantic gives us serialisation for free and validation for the message protocol. |
| **Client Rendering** | HTML5 Canvas (2D context) | Universal browser support, excellent for the wire-aesthetic. SVG for static UI elements (gauges, labels). No framework dependencies. |
| **Client Logic** | Vanilla JavaScript (ES modules) | No build step, no framework overhead. Each station is a separate HTML page with shared utility modules. Alpine.js can be introduced later if reactivity becomes painful. |
| **Styling** | CSS with custom properties | Theme variables for the wire aesthetic (colours, glow effects, fonts). Responsive for tablets and phones. |
| **Audio** (future) | Web Audio API | Procedural sound effects fit the aesthetic perfectly. Not in v0.01. |

### 2.3 Key Architectural Decisions

**Decision: Server-authoritative simulation**
*Reasoning*: The server is the single source of truth. Clients send **intentions** ("I want to turn left", "I want to fire torpedo at target X"), not state changes. The server validates, simulates, and broadcasts results. This prevents desync, makes cheating irrelevant (it's co-op anyway, but consistency matters), and simplifies the mental model.

**Decision: Role-filtered WebSocket messages**
*Reasoning*: Not every client needs every piece of state. The weapons officer doesn't need detailed engineering readouts. Each WebSocket connection is tagged with its role, and the server sends only relevant data to each. This reduces bandwidth (important for older devices on WiFi) and keeps each client's logic focused. A `full_state` channel exists for the Captain's overview and for debugging.

**Decision: Fixed timestep game loop**
*Reasoning*: The simulation runs at a fixed rate (10 ticks/sec in v0.01) regardless of client frame rate or connection quality. Clients receive state snapshots and interpolate between them for smooth rendering. This decouples simulation accuracy from network conditions.

**Decision: Component-based ship systems**
*Reasoning*: The ship is composed of **systems** (engines, shields, weapons, sensors, life_support, etc.), each of which is an independent object with standard interfaces (power_level, health, efficiency, update()). This means new systems can be added without touching existing code, systems can be damaged/repaired independently, and power allocation is a simple distribution across components.

**Decision: Mission-as-data, not mission-as-code**
*Reasoning*: Missions should be defined as data structures (JSON/YAML) with triggers, conditions, objectives, and events. A mission engine interprets these. This means new missions can be authored without Python code changes, and the AI engineer (or the project owner) can create missions by writing structured data. Complex missions can still hook into Python for custom logic.

**Decision: Message protocol over JSON**
*Reasoning*: Every WebSocket message follows a standard envelope:
```json
{
  "type": "category.action",
  "payload": { ... },
  "tick": 1234,
  "timestamp": 1700000000.123
}
```
Types are namespaced (e.g., `helm.set_heading`, `ship.state_update`, `weapons.fire_torpedo`). This is easy to debug, easy to extend, and fast enough for LAN use.

---

## 3. v0.01 SCOPE DEFINITION

### 3.1 What v0.01 IS

The minimum build that creates a **fun, playable session** with the core loop of:
connect → choose role → play mission → mission ends → debrief

v0.01 must prove that:
1. Multiple browsers can connect and interact in real-time
2. Each role feels distinct and essential  
3. Players must communicate to succeed
4. The wire aesthetic looks intentional and cool, not cheap
5. The architecture supports future expansion

### 3.2 What v0.01 is NOT

- Not feature-complete (no landing missions, no diplomacy, limited mission variety)
- Not polished (rough edges in UI are fine, broken gameplay is not)
- Not optimised (LAN performance is fine, internet play is not a goal)
- Not persistent (no saved games, no player profiles, no progression)

### 3.3 Roles in v0.01

#### CAPTAIN (Overview + Command)
**Core loop**: Monitor all systems, set priorities, make decisions, issue orders verbally.
**Screen**: Miniaturised versions of all other stations' key data — a tactical map, ship health overview, power summary, current mission objectives. No direct controls over ship systems except alert level and self-destruct (with confirmation!).
**Why it's fun**: You see everything but control nothing. The pressure of decision-making with imperfect information.
**v0.01 scope**: Overview dashboard with live data from all stations. Alert level control (green/yellow/red — affects UI colour scheme on all clients). Mission objective display.

#### HELM (Navigation + Piloting)
**Core loop**: Steer the ship, manage speed, execute manoeuvres.
**Screen**: Forward viewscreen (wire-rendered starfield + objects), heading compass, throttle control, ship position on sector map.
**Why it's fun**: Direct, visceral control. You're the one dodging asteroids and positioning for torpedo shots.
**v0.01 scope**: Heading control (0-359°), throttle (0-100%), impulse engines. Forward viewscreen with wire-rendered objects. Sector minimap showing ship position.

#### WEAPONS (Tactical + Combat)
**Core loop**: Target enemies, manage firing arcs, fire weapons, manage shield frequencies.
**Screen**: 360° tactical radar, target info panel, weapon status, shield controls.
**Why it's fun**: The action role. Timing shots, calling for heading changes, managing limited torpedoes.
**v0.01 scope**: Tactical radar with contacts, target selection, beam weapons (forward arc, require power), torpedo tubes (limited ammo, load time), front/rear shield balance.

#### ENGINEERING (Power + Repair)
**Core loop**: Distribute limited power across systems, dispatch repair teams, manage coolant.
**Screen**: Ship cross-section showing all systems, power allocation sliders, repair team positions, system health readouts.
**Why it's fun**: The resource management puzzle. Everyone wants more power, you never have enough. Deciding what to sacrifice.
**v0.01 scope**: 6 systems (engines, beams, torpedoes, shields, sensors, manoeuvring) with power sliders (total limited to 100% base capacity with overclock to 150% at risk). System health display. Repair allocation (move repair points to damaged systems).

#### SCIENCE (Sensors + Intel)
**Core loop**: Scan contacts, identify enemies, find weaknesses, detect anomalies.
**Screen**: Long-range sensor display, scan interface, contact database, anomaly readouts.
**Why it's fun**: The information asymmetry role. You know things nobody else does. The team depends on your intel.
**v0.01 scope**: Long-range sensor sweep (wider range than tactical radar), contact scanning (reveals enemy type, shield frequency, weakness), scan results that must be verbally communicated to other stations.

#### COMMS (Communication + Diplomacy) — OPTIONAL for v0.01
**Core loop**: Hail contacts, manage faction relations, intercept transmissions, request resupply.
**Screen**: Frequency scanner, contact list, message composition, faction status.
**Why it's fun**: The social/narrative role. Talking your way out of fights, calling for backup, managing reputation.
**v0.01 scope**: If included — hail friendly stations (request resupply/repair), receive scripted mission transmissions, surrender demands to enemies (may or may not work based on relative strength). If excluded — these functions are automated or handled by mission scripts.

### 3.4 Ship Model (v0.01)

```
Ship: "TSS Endeavour" (default)
├── Hull: 100 HP
├── Systems:
│   ├── Engines       (power: 0-150%) — affects max speed
│   ├── Beam Weapons  (power: 0-150%) — affects beam damage + recharge
│   ├── Torpedoes     (power: 0-150%) — affects reload speed
│   ├── Shields       (power: 0-150%) — affects shield strength
│   ├── Sensors       (power: 0-150%) — affects scan range + speed
│   └── Manoeuvring   (power: 0-150%) — affects turn rate
├── Shields:
│   ├── Forward: 0-100%
│   └── Rear: 0-100%
├── Weapons:
│   ├── Beam Banks x2 (forward arc ±45°, range: medium)
│   └── Torpedo Tubes x2 (ammo: 10, reload: 5 sec)
└── Movement:
    ├── Heading: 0-359°
    ├── Throttle: 0-100%
    ├── Max Speed: f(engine_power)
    └── Turn Rate: f(manoeuvring_power)
```

### 3.5 Game World (v0.01)

- **2D space** — top-down coordinate system (x, y in arbitrary units)
- **One sector** — approximately 100,000 x 100,000 units
- **Entities**: Player ship, enemy ships (1-3 types), space stations (friendly), asteroids (obstacles), mission waypoints
- **No terrain/nebulae in v0.01** — these are excellent additions for v0.02+ (nebulae block sensors, asteroid fields damage shields, etc.)

### 3.6 Enemy AI (v0.01 — Basic)

**Complexity Level: BASIC**
- Enemies have a **behaviour state**: `idle`, `patrol`, `chase`, `attack`, `flee`
- State transitions based on simple conditions (player distance, health threshold)
- `chase`: Move toward player ship
- `attack`: Close to weapon range, fire when in arc
- `flee`: Move away when health < 20%
- Enemies have the same system model as the player (hull, shields, weapons) but AI-controlled
- 2-3 enemy types: Scout (fast, weak), Cruiser (balanced), Destroyer (slow, tough)

### 3.7 Mission Structure (v0.01)

One to three playable missions demonstrating different gameplay:

**Mission 1: "First Contact"** (Tutorial/Combat)
- Patrol to 3 waypoints
- Encounter a single scout — science scans, weapons engages
- Encounter a cruiser — requires coordination (engineer boosts shields, helm manoeuvres, weapons targets weak point found by science)
- Return to starbase
- *Teaches*: Basic role interactions, combat flow

**Mission 2: "Defend the Station"** (Survival/Combat)
- Waves of enemies attack a friendly starbase
- Players must protect the station (it has its own health bar)
- Waves increase in difficulty
- Resupply at station between waves
- *Teaches*: Sustained resource management, prioritisation

**Mission 3: "Search and Rescue"** (Exploration/Non-combat)
- Distress signal from unknown location
- Science must use sensors to triangulate signal source
- Navigate through asteroid field (helm skill challenge)
- Find damaged ship, engineering must manage power to extend shields around it
- Escort back to starbase while avoiding or fighting off scavengers
- *Teaches*: Non-combat roles, creative system use

---

## 4. COMPLEXITY LAYERING SYSTEM

Each game system is designed with multiple complexity tiers. v0.01 implements Tier 1. Higher tiers are designed to slot in without architectural changes.

### 4.1 Example: Engineering Power System

| Tier | Feature | Gameplay Impact |
|------|---------|----------------|
| **1 (v0.01)** | Sliders allocate power %. Total limited to 100% (150% overclock with risk). | Basic resource management. |
| **2** | Overclock generates heat. Heat must be managed with coolant. Coolant is finite and must be routed. | Deeper risk/reward. Positioning coolant becomes a mini-game. |
| **3** | Individual system components can fail. Repair teams are crew members with stats and pathfinding on a ship interior map. | Crew management layer. |
| **4** | Power grid topology — systems connected by conduits that can be damaged. Rerouting power through backup conduits. | Emergent puzzle solving under pressure. |

### 4.2 Example: Weapons System

| Tier | Feature | Gameplay Impact |
|------|---------|----------------|
| **1 (v0.01)** | Beam banks (auto-fire in arc), torpedoes (manual fire, limited ammo). | Point and shoot. |
| **2** | Multiple weapon types (EMP, mines, point defence). Weapon frequency tuning. | Tactical variety. |
| **3** | Firing solutions — weapons officer calculates lead for moving targets. Beam overcharge mechanic. | Skill expression. |
| **4** | Modular weapon loadouts chosen pre-mission. Custom torpedo warheads (science + weapons collaboration). | Pre-mission strategy. |

### 4.3 Example: Science System

| Tier | Feature | Gameplay Impact |
|------|---------|----------------|
| **1 (v0.01)** | Scan contacts to reveal type, shields, weakness. Long-range sensor sweep. | Intel role. |
| **2** | Anomaly analysis mini-game. Environmental scanning (nebulae, radiation). | Exploration content. |
| **3** | Electronic warfare — jamming, spoofing, decoys. Counter-scanning. | Adversarial info warfare. |
| **4** | Research system — collect data from anomalies to unlock ship upgrades mid-campaign. | Progression and strategy. |

### 4.4 Example: Mission Types

| Tier | Feature | Gameplay Impact |
|------|---------|----------------|
| **1 (v0.01)** | Combat, defend, search-and-rescue. Linear objective chains. | Core gameplay variety. |
| **2** | Branching objectives, timed events, optional objectives. Stealth missions (avoid detection). | Replayability, diverse play styles. |
| **3** | Landing missions — away team subset manages ground operations while bridge crew provides orbital support. Diplomacy missions with dialogue trees (comms role). | Whole new gameplay modes. |
| **4** | Procedural mission generation. Campaign mode with persistent state across missions. Faction reputation system. | Endless content. |

---

## 5. FILE AND FOLDER STRUCTURE

```
starbridge/
├── server/
│   ├── main.py                  # FastAPI app, startup, WebSocket hub
│   ├── game_loop.py             # Fixed timestep simulation loop
│   ├── lobby.py                 # Session creation, role assignment
│   ├── models/
│   │   ├── __init__.py
│   │   ├── ship.py              # Ship, System, Shield, Weapon dataclasses
│   │   ├── world.py             # World, Entity, Position, Sector
│   │   ├── mission.py           # Mission, Objective, Trigger, Event
│   │   └── messages.py          # WebSocket message schemas (Pydantic)
│   ├── systems/
│   │   ├── __init__.py
│   │   ├── physics.py           # Movement, collision detection
│   │   ├── combat.py            # Damage calculation, weapon firing
│   │   ├── ai.py                # Enemy behaviour state machine
│   │   └── sensors.py           # Scanning, detection ranges
│   ├── missions/
│   │   ├── loader.py            # Mission file parser
│   │   └── engine.py            # Mission runtime (trigger evaluation, events)
│   └── utils/
│       ├── __init__.py
│       └── math_helpers.py      # Angle wrapping, distance, interpolation
│
├── client/
│   ├── shared/
│   │   ├── connection.js        # WebSocket manager, reconnection
│   │   ├── renderer.js          # Canvas utilities, wire-frame primitives
│   │   ├── theme.css            # Wire aesthetic — colours, glow, fonts
│   │   ├── ui_components.js     # Shared UI: gauges, sliders, radar
│   │   └── audio.js             # (stub for v0.01) Sound manager
│   ├── lobby/
│   │   ├── index.html
│   │   ├── lobby.js
│   │   └── lobby.css
│   ├── captain/
│   │   ├── index.html
│   │   ├── captain.js
│   │   └── captain.css
│   ├── helm/
│   │   ├── index.html
│   │   ├── helm.js
│   │   └── helm.css
│   ├── weapons/
│   │   ├── index.html
│   │   ├── weapons.js
│   │   └── weapons.css
│   ├── engineering/
│   │   ├── index.html
│   │   ├── engineering.js
│   │   └── engineering.css
│   ├── science/
│   │   ├── index.html
│   │   ├── science.js
│   │   └── science.css
│   └── viewscreen/             # Optional: a shared "main screen" display
│       ├── index.html
│       ├── viewscreen.js
│       └── viewscreen.css
│
├── missions/
│   ├── first_contact.json
│   ├── defend_station.json
│   └── search_rescue.json
│
├── docs/
│   ├── ARCHITECTURE.md          # This document (trimmed for reference)
│   ├── MESSAGE_PROTOCOL.md      # Complete message type reference
│   ├── MISSION_FORMAT.md        # How to author missions
│   └── STYLE_GUIDE.md          # Wire aesthetic visual guidelines
│
├── requirements.txt
├── README.md
└── run.py                       # Entry point: `python run.py`
```

---

## 6. BUILD GUIDE — PHASED IMPLEMENTATION

### Phase 1: Foundation (Server + Connection + Lobby)

**Goal**: A running server that clients can connect to, see a lobby, and claim roles.

**Tasks**:
1. FastAPI app with static file serving for client assets
2. WebSocket endpoint at `/ws` with connection lifecycle (connect, authenticate with role, disconnect, reconnect)
3. Lobby system:
   - `POST /api/game/create` — creates a game session
   - `GET /api/game/{id}/status` — returns session state (roles claimed, settings)
   - WebSocket messages for role claim/release, game start/stop
4. Lobby client page — shows game code/URL, role buttons (available/claimed), "Start Game" for host
5. Message protocol implementation — envelope format, type routing, serialisation

**Acceptance criteria**: 
- Open 3 browser tabs, all connect to lobby
- Each claims a different role  
- Host clicks "Start Game" and all clients receive a `game.started` message

**AI Engineer prompt**:
> Build the FastAPI server foundation for a multiplayer bridge crew game. Create the WebSocket hub that manages connections tagged by role, a lobby system where players claim roles, and the message protocol (JSON envelope with type, payload, tick, timestamp). Serve static client files. Create the lobby client page with a clean wire-aesthetic UI (dark background, green/amber vector lines, monospace font). The lobby should show all available roles with descriptions, let players claim/release roles, and have a "Launch Mission" button for the host. Focus on clean architecture — the WebSocket hub must support role-filtered broadcasting (send messages only to relevant roles) and the message protocol must be extensible. Use Pydantic for message validation.

---

### Phase 2: Game Loop + Ship Model + Helm Station

**Goal**: A ship that exists in a 2D world, can be steered by the Helm station, and whose movement is visible on a canvas viewscreen.

**Tasks**:
1. Game loop — `asyncio` task running at 10 ticks/sec, fixed timestep
2. Ship model — dataclass with position (x, y), heading, velocity, throttle, systems
3. Physics system — apply thrust in heading direction, enforce max speed based on engine power, apply turn rate based on manoeuvring power
4. World model — sector bounds, entity list (just the player ship for now)
5. State broadcast — each tick, send relevant state to connected clients
6. Helm client:
   - Heading control (compass dial or slider, 0-359°)
   - Throttle control (0-100% slider or lever)
   - Forward viewscreen (canvas rendering: starfield, heading indicator)
   - Sector minimap (canvas: ship position and heading in the sector)
7. Client-side interpolation — smooth rendering between server ticks

**Acceptance criteria**:
- Helm station shows the viewscreen and controls
- Moving the throttle makes the ship move (visible on minimap)
- Changing heading rotates the viewscreen starfield
- A second client (e.g., captain) can see the ship's position updating

**AI Engineer prompt**:
> Implement the core game loop and Helm station. The server needs an asyncio game loop running at 10 ticks/sec with fixed timestep. Create the Ship model (position, heading, velocity, throttle, systems with power levels) and a physics system that moves the ship based on throttle and heading. The Helm client needs: a compass-style heading control (draggable or arrow-key driven), a throttle slider, a forward viewscreen rendered on HTML5 Canvas showing a parallax wire-frame starfield that rotates with heading, and a minimap showing ship position in the sector. Implement client-side interpolation between server ticks for smooth 60fps rendering. Use the wire aesthetic throughout — dark background (#0a0a0a), primary colour (amber #ff9900 or green #00ff41), scanline overlay effect, subtle glow on lines.

---

### Phase 3: Engineering Station + Power System

**Goal**: Engineering controls power distribution. Other systems respond to power levels.

**Tasks**:
1. Power system — 6 systems, each with a power slider (0-150%), total allocation pool of 300% (100% baseline, effectively 50% average per system at max draw), overclock above 100% per system causes gradual heat/damage risk
2. System health — each system has HP (0-100), damage reduces efficiency, 0 HP = offline
3. Engineering client:
   - Ship cross-section diagram (SVG or canvas) showing all systems
   - Power sliders for each system with real-time readouts
   - Total power budget indicator
   - System health bars
   - Repair point allocation (simple: assign repair focus to a system, it heals over time)
4. Integration: Helm max speed now depends on engine power. Turn rate depends on manoeuvring power.

**Acceptance criteria**:
- Engineering can adjust power sliders
- Reducing engine power visibly slows the ship (Helm notices)
- Boosting manoeuvring power makes the ship turn faster
- Damaging a system (via debug command) shows on Engineering's display
- Allocating repair to a damaged system heals it over time

**AI Engineer prompt**:
> Build the Engineering station with the power distribution system. The ship has 6 systems (engines, beams, torpedoes, shields, sensors, manoeuvring), each with a power slider from 0-150%. Total available power is a pool (300 units by default, meaning you cannot run everything at max). Each system's effectiveness scales with its power level. Create the Engineering client with a ship cross-section view showing all systems, interactive power sliders with a budget indicator that shows when you're over-allocating, system health displays, and a repair allocation interface. Integrate power levels with existing physics — engine power affects max speed, manoeuvring power affects turn rate. Add a system health model where damaged systems lose efficiency proportionally. Keep the wire aesthetic consistent with existing stations.

---

### Phase 4: Weapons Station + Combat

**Goal**: Enemies exist in the world. Weapons station can target and destroy them. Enemies can damage the player.

**Tasks**:
1. Enemy entities — spawn in world with position, heading, velocity, hull HP, shields, weapons
2. Basic AI — state machine (idle → chase → attack → flee) with range-based transitions
3. Combat system — beam damage calculation (factoring power, range, shield strength), torpedo mechanics (travel time, damage)
4. Weapons client:
   - 360° tactical radar (canvas, top-down, ship at centre)
   - Contact list with target selection
   - Beam weapon controls (fire when target in arc, show arc overlay on radar)
   - Torpedo controls (fire button, ammo count, reload timer)
   - Shield balance (forward/rear slider)
5. Damage integration — enemies that hit the player damage shields first, then hull, then randomly damage systems
6. Ship destruction — player ship destroyed = mission failed. Enemy destroyed = removed from world.

**Acceptance criteria**:
- Enemies appear on the tactical radar
- Weapons can select a target and see its info
- Beams fire and damage enemies when in arc and range
- Torpedoes fire, travel, and impact
- Enemies fight back — player takes damage visible on Engineering
- Destroying an enemy removes it from the world
- Player ship reaching 0 hull = game over

**AI Engineer prompt**:
> Add enemies and combat. Create enemy entities with position, heading, velocity, hull, shields, and weapons. Implement a basic AI state machine (idle → chase player when in detection range → attack when in weapon range → flee when health low). Build the combat system with beam weapons (continuous damage while target in arc, effectiveness scales with beam power) and torpedoes (projectile entities with travel time, high damage, limited ammo, reload timer). Create the Weapons client with a 360° tactical radar rendered on canvas (ship at centre, contacts as wireframe shapes, selectable), beam arc overlay, torpedo fire controls, ammo/reload display, and a front/rear shield balance slider. Implement the damage pipeline: weapon hit → check shields → reduce shield/hull → if hull damage, chance to damage a random system (which Engineering then has to repair). Wire aesthetic for all UI.

---

### Phase 5: Science Station + Scanning

**Goal**: Science provides intel that other stations can't get on their own. Information asymmetry creates interdependence.

**Tasks**:
1. Sensor system — detection range based on sensor power, different detail levels based on range
2. Scanning mechanic — target a contact, initiate scan, scan takes time (reduced by sensor power), reveals detailed info
3. Contact types — until scanned, contacts show as "Unknown Contact" with size estimate only
4. Scan results — enemy type, shield frequency, hull strength, weapon loadout, weakness (e.g., "rear shields 50% weaker")
5. Science client:
   - Long-range sensor display (canvas, larger range than weapons radar)
   - Contact list with scan status
   - Scan interface (select contact, initiate scan, progress bar)
   - Scan results panel (detailed info on scanned contacts)
6. Integration: Weapons can see contacts on radar, but only as unknowns until Science scans them. Science scan results appear on Captain's overview.

**Acceptance criteria**:
- Science sees contacts at longer range than Weapons
- Unscanned contacts appear as "Unknown" on Weapons radar
- Scanning a contact reveals its details on Science's panel
- Captain's overview shows scan data
- Science can identify enemy weaknesses that Weapons can exploit (e.g., weak rear shields)
- Sensor power affects scan range and speed

**AI Engineer prompt**:
> Build the Science station with the scanning system. Science gets a long-range sensor display showing contacts at greater range than the weapons tactical radar. Before Science scans a contact, it appears as "Unknown Contact" on all stations — only showing an approximate size and bearing. Scanning is an active process: select a target, initiate scan, wait for it to complete (time reduced by sensor power level). Scan results reveal the contact's type, shield strength, weapons, and a specific weakness (e.g., "aft shields compromised", "vulnerable to low-frequency beams"). These results display on the Science panel and propagate to the Captain's overview, but crucially do NOT automatically appear on Weapons — the Science player must verbally relay tactical information. This information asymmetry is a core design goal. Create the Science client with a large sensor sweep display, contact list with scan progress indicators, and a detailed results panel. Wire aesthetic consistent with other stations.

---

### Phase 6: Captain Station + Mission System

**Goal**: Captain has the overview. Missions provide structured objectives. The game has a beginning, middle, and end.

**Tasks**:
1. Captain client:
   - Miniaturised tactical map (from weapons)
   - Ship status summary (from engineering)
   - Sensor summary (from science)
   - Current mission objectives panel
   - Alert level control (green/yellow/red — changes UI theme colour on ALL clients)
2. Mission engine:
   - Load mission from JSON file
   - Trigger system (conditions → events): "when player enters area X, spawn enemies"
   - Objective tracking (complete/incomplete/failed)
   - Mission state transitions (briefing → active → complete/failed → debrief)
3. Mission data format — JSON schema for defining missions
4. Implement at least Mission 1 ("First Contact") as a complete playable mission
5. Victory/defeat conditions and end-of-mission screen

**Acceptance criteria**:
- Captain sees a dashboard of all station data
- Alert level changes propagate to all clients (colour theme shifts)
- Mission 1 is playable start to finish
- Mission objectives appear and update correctly
- Mission triggers fire (enter waypoint area → event happens)
- Victory/defeat screens display on all clients

**AI Engineer prompt**:
> Build the Captain station and mission system. The Captain's screen is an overview dashboard: a miniaturised tactical map, ship health/power summary from Engineering, sensor contact summary from Science, and a mission objectives panel. The Captain's only direct control is the alert level (green/yellow/red) which changes the primary UI colour on ALL connected clients — this is a powerful atmospheric tool. Build the mission engine that loads missions from JSON files with a trigger/event system: triggers are conditions (player_in_area, entity_destroyed, timer_elapsed, scan_completed) that fire events (spawn_entities, display_message, update_objective, play_transmission). Implement Mission 1 "First Contact": brief at starbase → patrol to 3 waypoints → encounter scout at waypoint 2 → encounter cruiser at waypoint 3 (science must scan to find weakness) → return to starbase → victory. Create the mission JSON format, document it, and make it easy to author new missions.

---

### Phase 7: Polish, Viewscreen + Remaining Missions

**Goal**: The experience feels cohesive. Multiple missions are playable. An optional shared viewscreen display exists.

**Tasks**:
1. Viewscreen client — a display-only view of the forward perspective, intended for a shared screen/TV in the room. Shows the wire-rendered space view, nearby objects, weapon impacts, shield hits. No controls.
2. Visual polish:
   - Consistent wire aesthetic across all stations
   - Scanline/CRT overlay effect
   - Hit flash effects when ship takes damage
   - Torpedo trail rendering
   - Shield impact visualisation
   - Smooth animations for all state changes
3. Implement Mission 2 ("Defend the Station") and Mission 3 ("Search and Rescue")
4. Game flow polish — lobby → mission select → briefing → play → debrief → back to lobby
5. Error handling — client disconnect/reconnect, late join handling
6. Responsive layout — stations should be usable on tablet screens (not phone for v0.01, but shouldn't break)

**AI Engineer prompt**:
> Polish pass and complete the v0.01 experience. Create the Viewscreen client — a display-only forward view intended for a shared screen, showing the wire-rendered space environment, nearby ships, weapon fire, torpedo trails, and shield impact effects. It has no controls and auto-connects as an observer. Apply visual polish across all stations: CRT scanline overlay, phosphor glow on bright elements, hit flash when the ship takes damage, smooth animations for all gauge/slider changes, torpedo trail particles, and shield shimmer effects. Implement the remaining two missions (Defend the Station: wave survival protecting a starbase with resupply between waves; Search and Rescue: triangulate a distress signal via sensor sweeps, navigate an asteroid field, extend shields around a damaged vessel, escort to safety). Polish the full game flow: lobby → mission select → briefing screen → gameplay → victory/defeat → debrief stats → return to lobby. Handle client disconnection gracefully (role becomes available, reconnecting player can reclaim). Ensure layouts work on tablets.

---

## 7. MESSAGE PROTOCOL REFERENCE (v0.01)

### Client → Server (Intentions)

```
helm.set_heading        { heading: 0-359 }
helm.set_throttle       { throttle: 0-100 }
weapons.select_target   { entity_id: string }
weapons.fire_beams      { }
weapons.fire_torpedo    { }
weapons.set_shields     { front: 0-100, rear: 0-100 }
engineering.set_power   { system: string, level: 0-150 }
engineering.set_repair  { system: string }
science.start_scan      { entity_id: string }
science.cancel_scan     { }
captain.set_alert       { level: "green"|"yellow"|"red" }
lobby.claim_role        { role: string }
lobby.release_role      { }
lobby.start_game        { mission_id: string }
```

### Server → Client (State Updates)

```
game.started            { mission_id, mission_name, briefing_text }
game.tick               { tick: number, timestamp: number }
game.over               { result: "victory"|"defeat", stats: {} }

ship.state              { position, heading, velocity, hull, shields, systems, alert_level }
ship.system_damaged     { system: string, new_health: number }
ship.hull_hit           { damage: number, new_hull: number }

world.entities          { entities: [{ id, type, position, heading, ... }] }
world.entity_spawned    { entity: {} }
world.entity_destroyed  { entity_id: string }

weapons.beam_fired      { target_id, damage }
weapons.torpedo_fired   { torpedo_id, heading }
weapons.torpedo_hit     { torpedo_id, target_id, damage }

science.scan_progress   { entity_id, progress: 0-100 }
science.scan_complete   { entity_id, results: {} }

mission.objective_update { objectives: [{ id, text, status }] }
mission.transmission     { from: string, message: string }
mission.event           { type: string, data: {} }

lobby.state             { roles: { role: player_name|null }, host: player_id }
```

---

## 8. WIRE AESTHETIC STYLE GUIDE

### Colour Palette

```css
:root {
  /* Base */
  --bg-primary: #0a0a0a;
  --bg-secondary: #111111;
  --bg-panel: #0d0d0d;
  
  /* Alert level colours (primary UI colour shifts with alert) */
  --alert-green: #00ff41;
  --alert-yellow: #ffb000;
  --alert-red: #ff2020;
  
  /* Current primary (set by alert level, default green) */
  --primary: var(--alert-green);
  --primary-dim: rgba(0, 255, 65, 0.3);
  --primary-glow: rgba(0, 255, 65, 0.15);
  
  /* Functional */
  --friendly: #00aaff;
  --hostile: #ff3333;
  --neutral: #888888;
  --unknown: #ffff00;
  --hull-damage: #ff6600;
  
  /* Text */
  --text-bright: var(--primary);
  --text-normal: rgba(0, 255, 65, 0.7);
  --text-dim: rgba(0, 255, 65, 0.4);
}
```

### Typography
- Primary font: `'Share Tech Mono', 'Courier New', monospace`
- Headings: `text-transform: uppercase; letter-spacing: 0.15em;`
- Data readouts: tabular-nums for aligned numbers

### Visual Effects
- **Scanlines**: Subtle repeating horizontal lines via CSS pseudo-element or canvas overlay
- **Glow**: `text-shadow` and `box-shadow` using `var(--primary-glow)` — apply sparingly to key elements, not everything
- **Grid**: Faint grid lines on all canvas displays (radar, maps, viewscreen)
- **Flicker**: Very subtle opacity animation on panel borders (1-2% variation, not distracting)

### Canvas Rendering Conventions
- All entities rendered as wireframe outlines, never filled
- Player ship: chevron/arrow shape
- Enemy ships: distinct wireframe shapes per type (diamond, triangle, hexagon)
- Stations: circle with cross
- Torpedoes: small dots with trailing line
- Beams: bright line from source to target, fade over 200ms
- Shield hits: arc flash at impact point

---

## 9. TODO CHECKLIST

### Phase 1: Foundation
- [ ] FastAPI app skeleton with static file serving
- [ ] WebSocket endpoint with connection management
- [ ] Connection tagging (role, player name, session ID)
- [ ] Message protocol: envelope format, serialisation, type routing
- [ ] Lobby system: create session, list sessions, claim/release role
- [ ] Lobby client: UI with role selection, player list, launch button
- [ ] Role-filtered broadcasting (send to specific roles only)
- [ ] Basic error handling (malformed messages, invalid roles)

### Phase 2: Game Loop + Helm
- [ ] Fixed timestep game loop (10 ticks/sec)
- [ ] Ship model (position, heading, velocity, throttle, systems)
- [ ] Physics system (thrust, speed limits, turning)
- [ ] World model (sector, entity list)
- [ ] State broadcast each tick (role-filtered)
- [ ] Helm client: heading control
- [ ] Helm client: throttle control
- [ ] Helm client: forward viewscreen (canvas, starfield, objects)
- [ ] Helm client: sector minimap
- [ ] Client-side tick interpolation for smooth rendering

### Phase 3: Engineering
- [ ] Power system model (6 systems, sliders, budget pool)
- [ ] System health model (HP, efficiency scaling)
- [ ] Overclock risk mechanic (>100% power = gradual risk)
- [ ] Repair mechanic (allocate repair focus, heal over time)
- [ ] Engineering client: ship cross-section display
- [ ] Engineering client: power sliders with budget indicator
- [ ] Engineering client: system health bars
- [ ] Engineering client: repair allocation interface
- [ ] Integration: engine power → max speed
- [ ] Integration: manoeuvring power → turn rate

### Phase 4: Weapons + Combat
- [ ] Enemy entity model (hull, shields, weapons, AI state)
- [ ] Enemy AI state machine (idle, chase, attack, flee)
- [ ] Beam weapon system (arc check, damage calc, power scaling)
- [ ] Torpedo system (projectile entity, travel, impact, ammo, reload)
- [ ] Shield system (front/rear, absorb damage, power scaling)
- [ ] Damage pipeline (weapon → shield → hull → system damage chance)
- [ ] Weapons client: 360° tactical radar (canvas)
- [ ] Weapons client: target selection + info panel
- [ ] Weapons client: beam fire controls with arc overlay
- [ ] Weapons client: torpedo controls with ammo/reload display
- [ ] Weapons client: shield balance slider
- [ ] Ship destruction handling (player + enemy)

### Phase 5: Science
- [ ] Sensor range system (based on sensor power)
- [ ] Contact visibility levels (unknown → scanned)
- [ ] Scanning mechanic (target, progress, completion)
- [ ] Scan results model (type, shields, weapons, weakness)
- [ ] Science client: long-range sensor display (canvas)
- [ ] Science client: contact list with scan status
- [ ] Science client: scan interface with progress bar
- [ ] Science client: scan results panel
- [ ] Integration: unscanned contacts show as "Unknown" on Weapons
- [ ] Integration: scan data propagates to Captain overview

### Phase 6: Captain + Missions
- [ ] Captain client: tactical map overview
- [ ] Captain client: ship status summary
- [ ] Captain client: sensor/science summary
- [ ] Captain client: mission objectives panel
- [ ] Captain client: alert level control
- [ ] Alert level propagation to all clients (colour theme change)
- [ ] Mission JSON schema design
- [ ] Mission loader (parse JSON → mission runtime objects)
- [ ] Mission engine: trigger evaluation system
- [ ] Mission engine: event execution system
- [ ] Mission engine: objective tracking
- [ ] Mission 1 "First Contact" implementation
- [ ] Game flow: briefing → active → complete/failed
- [ ] Victory/defeat screen on all clients

### Phase 7: Polish
- [ ] Viewscreen client (display only, no controls)
- [ ] CRT/scanline overlay effect
- [ ] Phosphor glow effects
- [ ] Hit flash on damage
- [ ] Torpedo trail rendering
- [ ] Shield impact visualisation
- [ ] Beam firing visualisation
- [ ] Mission 2 "Defend the Station" implementation
- [ ] Mission 3 "Search and Rescue" implementation
- [ ] Full game flow (lobby → select → brief → play → debrief → lobby)
- [ ] Client disconnect/reconnect handling
- [ ] Late join handling
- [ ] Tablet-responsive layouts
- [ ] README with setup instructions

---

## 10. FUTURE CONSIDERATIONS (Post v0.01)

These are not in scope but should not be architecturally prevented:

- **Comms station** — diplomacy, faction relations, hailing, NPC dialogue
- **Landing/away missions** — subset of crew does ground operations (different interface), bridge crew provides support
- **Ship customisation** — loadout selection before missions
- **Campaign mode** — persistent ship state, crew progression, faction standing across missions
- **Procedural missions** — generated from templates and parameters
- **Audio** — procedural engine hum, weapon sounds, alert klaxons, voice comm between stations
- **Internet play** — would require state compression and lag compensation
- **Custom ships** — define ship configurations in data files
- **AI crew** — unfilled roles handled by basic AI so 2-3 players can still play
- **Spectator mode** — observe the game from outside, useful for events/streaming
- **Mobile station variants** — simplified role interfaces for phone screens
- **Modding support** — custom missions, ships, and enemy types from community

---

## 11. GETTING STARTED (for the AI Engineer)

1. Read this entire document first.
2. Start with Phase 1. Do not skip ahead.
3. Each phase should be **fully working and testable** before moving to the next.
4. After each phase, test with multiple browser tabs to verify multiplayer behaviour.
5. When building client UIs, refer to Section 8 (Style Guide) for visual consistency.
6. When adding WebSocket messages, add them to the protocol reference (Section 7) and validate with Pydantic.
7. Keep the mission format (Section 6, Phase 6) in mind when building game systems — things need to be triggerable by the mission engine, not just hardcoded.
8. Commit frequently with descriptive messages. Each phase is a natural commit boundary.
9. Ask questions if requirements are ambiguous. The project owner is an experienced software engineer and educator — they'll have opinions.

### Quick Start Commands
```bash
# Setup
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install fastapi uvicorn pydantic websockets

# Run
python run.py
# Server starts on http://0.0.0.0:8000
# Other devices on LAN connect to http://<server-ip>:8000
```

---

*Document version: v0.01-scope-1.0*
*Last updated: 2026-02-17*
*Project codename: STARBRIDGE*
