# STARBRIDGE — v0.03 Scope
## "The Fleet Update"

---

## 1. OVERVIEW

### 1.1 What v0.03 Adds

v0.02 built depth — 8 roles, puzzles, cross-station assists, crew and interior systems. v0.03 builds **polish and scale**:

- **Quality of life**: Audio system, unified map renderer, station help overlays, difficulty presets, cross-station notifications, reconnect fix, mission briefing room, debrief dashboard
- **Ship framework**: JSON-defined ship classes supporting 3-12 players, with different system loadouts, hull values, and role sets per class
- **Multi-role support**: Players can claim multiple roles and switch between them in a tabbed/split UI. Essential for small crews on small ships.
- **4 new roles**: Damage Control, Flight Operations, Electronic Warfare, Tactical Officer — bringing the total to 12
- **Science scan modes**: Four sensor bands (EM, GRAV, BIO, SUB) transforming Science from passive to active
- **Training missions**: Per-station solo tutorials for classroom onboarding
- **Captain's replay viewer**: Post-game playback from game logger data

### 1.2 Design Principles

All v0.01/v0.02 principles carry forward. v0.03 adds:

- **Polish before expansion**: QoL improvements land before new roles. Every new role benefits from audio, help overlays, the map system, and difficulty presets from day one.
- **Ships as data, not code**: Ship classes are JSON definitions, same philosophy as missions-as-data. New ships are authored without code changes.
- **Scalable crew size**: The game must feel right with 3 players on a Scout AND 12 players on a Battleship. Combined roles and the ship framework make this possible.
- **Classroom-first design**: Training missions, help overlays, difficulty presets, and the replay viewer are designed for a teacher running this with students, not just friends at a LAN party.

### 1.3 Pre-Resolved Architectural Decisions

**Module-level globals stay for v0.03.** Multi-session support (multiple concurrent games) is explicitly deferred to v0.04. All v0.03 work assumes a single game session per server. Log this in DECISIONS.md and do not revisit.

**Audio is procedural via Web Audio API.** No audio files, no loading, no licensing. Every sound is generated from oscillators, noise, filters, and envelopes. A `SoundBank` singleton with named presets keeps it clean.

**Ship classes do not change the server architecture.** The server already handles arbitrary role sets. Ship classes are a lobby-time configuration that determines which roles are available, system parameters, and hull/power values. The game loop doesn't know or care what ship class is active — it works with the Ship model, which is configured at game start from the ship class definition.

**Multi-role is client-side only.** The server sends role-filtered messages to each role independently. A combined-role client claims multiple roles on one WebSocket connection and routes messages to the appropriate station module internally. The server doesn't need a concept of "combined roles."

**The unified map renderer replaces per-station canvas code incrementally.** Don't rewrite all stations at once. Build MapRenderer, migrate one station (Captain — it has the most layers), validate, then migrate others. Stations that aren't migrated continue working with their existing canvas code.

---

## 2. SUB-RELEASE PLAN

### Dependency Graph

```
v0.03a (Audio system)
v0.03b (Reconnect fix + station help overlays + difficulty presets)
v0.03c (Unified map renderer + notification overlays)
v0.03d (Cross-station notification system)
v0.03e (Ship framework — JSON ship classes + lobby ship select)
v0.03f (Multi-role + role switching UI)
v0.03g (Mission briefing room)
  └── All of a–f should be complete before new roles begin

v0.03h (Science scan modes)
v0.03i (Damage Control Officer)
v0.03j (Flight Operations Officer)
v0.03k (Electronic Warfare Officer)
v0.03l (Tactical Officer)
  └── h–l are independent of each other, any order

v0.03m (Training missions — one per station, built after each role exists)
v0.03n (Debrief dashboard + Captain's replay viewer)
v0.03o (Ship class balancing + final integration + v0.03 gate)
```

### Key Ordering Constraints

- a–g (QoL) must complete before h–l (new roles). New roles should launch into a polished environment.
- v0.03e (ship framework) before v0.03f (multi-role). Multi-role's combined role definitions come from the ship class JSON.
- v0.03m (training) after all roles exist. Each training mission is built for a specific station.
- v0.03n (debrief/replay) last before the final gate. Needs all 12 roles generating logger data.

---

## 3. v0.03a — AUDIO SYSTEM

**Purpose**: Procedural audio atmosphere via Web Audio API. No audio files.

### 3.1 Architecture

```
client/shared/
├── audio.js              # SoundBank singleton, Web Audio context management,
│                          # volume controls, category mixing
├── audio_ambient.js      # Ambient layer: engine hum, reactor drone, 
│                          # sensor sweep, life support, alert-level shifts
├── audio_events.js       # Event sounds: weapons, impacts, damage, scans,
│                          # comms, boarding, doors
└── audio_ui.js           # UI feedback: clicks, slides, confirmations, errors
```

### 3.2 SoundBank Interface

```javascript
// Initialise (call once per station)
SoundBank.init();

// Play a named sound
SoundBank.play('beam_fire');
SoundBank.play('torpedo_launch');
SoundBank.play('hull_hit', { intensity: 0.8 });

// Ambient control
SoundBank.setAmbient('engine_hum', { throttle: 0.6 });
SoundBank.setAmbient('alert_level', { level: 'red' });

// Volume control (0-1 per category, persisted to localStorage)
SoundBank.setVolume('ambient', 0.5);
SoundBank.setVolume('events', 0.8);
SoundBank.setVolume('ui', 0.3);
SoundBank.mute();        // Master mute toggle
```

### 3.3 Sound Definitions

#### Ambient Layer

| Sound | Trigger | Parameters |
|-------|---------|------------|
| Engine hum | Always on during game | Pitch shifts with throttle (low = slow, high = fast). Deepens when engine power < 50%. |
| Reactor drone | Engineering station | Rises with total power draw. Warning oscillation above 90% budget. |
| Sensor sweep | Science station | Soft pulse synced to radar sweep rotation interval. |
| Life support hiss | All stations | Subtle white noise. Cuts out abruptly when a deck decompresses (dramatic silence). |
| Alert green | Alert level green | Calm, barely audible low-frequency pad. |
| Alert yellow | Alert level yellow | Tension drone. Low sawtooth oscillator with slow LFO. |
| Alert red | Alert level red | Klaxon pulse. 1-second on/off cycle. Filtered square wave. Unmistakable. |

#### Event Sounds

| Sound | Trigger | Design |
|-------|---------|--------|
| Beam fire (player) | weapons.beam_fired (source=player) | Sharp electrical discharge. High-frequency sweep down. 200ms. |
| Beam fire (enemy) | weapons.beam_fired (source=enemy) | Same but lower pitch, slightly distorted. Threatening. |
| Torpedo launch | weapons.torpedo_fired (source=player) | Mechanical thunk (noise burst) → whoosh (filtered noise fade). 500ms. |
| Torpedo impact | weapons.torpedo_hit | Deep bass hit. Sub-oscillator pulse. Screen shake pairs with this. |
| Shield hit (front) | ship.hull_hit with shield absorption | Crackling energy. High-pass filtered noise burst. Stereo-panned forward. |
| Shield hit (rear) | ship.hull_hit with shield absorption | Same, stereo-panned rear. |
| Hull hit | ship.hull_hit (direct hull damage) | Metallic crunch. Noise burst through bandpass filter. Bass-heavy. |
| System damage | ship.system_damaged | Electrical sparking. Short burst of random high-frequency clicks. |
| Scan complete | science.scan_complete | Data chime. Two-tone ascending. Clean sine waves. |
| Incoming transmission | Comms receives message | Comms chirp. Three short beeps, ascending pitch. |
| Boarding alert | security.boarding_started | Urgent proximity alarm. Fast pulse, hostile colour audio equivalent. |
| Door seal | security.set_door (sealed=true) | Pneumatic hiss → mechanical clunk. Noise → silence → click. |
| Door unseal | security.set_door (sealed=false) | Reverse: click → hiss. |
| Marine combat | Combat active in a room | Muffled distant gunfire. Low-pass filtered noise bursts at random intervals. Security station only. |
| Explosion | world.entity_destroyed | Expanding noise burst with reverb tail. 1 second. |
| Puzzle success | puzzle.result (success=true) | Ascending major arpeggio. Three clean sine tones. |
| Puzzle failure | puzzle.result (success=false) | Descending minor. Two dull tones. |
| Puzzle timeout warning | 10 seconds remaining | Ticking. Accelerating click track. |
| Victory | game.over (result=victory) | Triumphant brass-style chord. Stacked sawtooth oscillators with slow attack. |
| Defeat | game.over (result=defeat) | Low ominous drone fading to silence. |

#### UI Sounds

| Sound | Trigger | Design |
|-------|---------|--------|
| Button click | Any .btn click | Subtle mechanical click. Single short noise burst. 50ms. |
| Slider change | Range input change | Soft notch tick. Very quiet. 20ms. |
| Role claimed | lobby.state (role claimed) | Acceptance chime. Single clean tone. |
| Role released | lobby.state (role released) | Soft descending tone. |
| Error/rejection | error.validation received | Short buzz. Low square wave. 100ms. |

### 3.4 Station Integration

Each station calls `SoundBank.init()` in its init function and registers relevant event handlers:

```javascript
// In helm.js init():
SoundBank.init();
connection.on('ship.state', (p) => {
    SoundBank.setAmbient('engine_hum', { throttle: p.velocity / MAX_SPEED });
});
connection.on('ship.hull_hit', () => SoundBank.play('hull_hit'));
```

Stations only register sounds relevant to their role. Engineering hears the reactor drone but not marine combat. Security hears boarding alerts and door seals but not beam weapons (unless they hit the ship).

### 3.5 Volume Control UI

A small speaker icon in the station header bar. Click to expand a volume panel with three sliders (Ambient, Events, UI) and a master mute toggle. Persisted to localStorage per device. Collapsed by default — doesn't clutter the station.

### Acceptance Criteria

- [ ] SoundBank.init() works on all stations without errors
- [ ] Ambient engine hum plays and shifts with throttle
- [ ] Alert level changes produce audible atmosphere shift
- [ ] Beam/torpedo/impact sounds play during combat
- [ ] Puzzle success/failure sounds play
- [ ] Volume controls work per category
- [ ] Master mute works
- [ ] No audio plays before user interaction (browser autoplay policy)
- [ ] Sounds don't overlap badly (concurrent beam fires don't clip)
- [ ] All stations have appropriate sound registrations

---

## 4. v0.03b — RECONNECT FIX + HELP OVERLAYS + DIFFICULTY PRESETS

**Purpose**: Three quick-win QoL improvements that dramatically improve the player experience.

### 4.1 Reconnect Fix

**Current bug**: Role reclaim on reconnect fails silently if another player claimed the role during disconnection.

**Fix**: 
- On reconnect, if the role is occupied by a different player, show a clear modal: "ROLE OCCUPIED — [PlayerName] is currently on [Role]. Return to Lobby?"
- On reconnect, if the role is available, reclaim silently and resume (current behaviour when it works)
- On reconnect mid-game, the server replays the current game state: `game.started` (with current mission state), latest `ship.state`, current `world.entities` / `sensor.contacts`, and any active puzzles
- The lobby tracks disconnection timestamps. If a player disconnects for < 60 seconds, their role is "reserved" (shown as "DISCONNECTED" in the lobby, not claimable by others). After 60 seconds, the role opens up.

### 4.2 Station Help Overlay

**Trigger**: Press F1 or click a "?" button in the station header.

**Display**: Semi-transparent dark overlay covering the station. Annotated labels appear pointing to every interactive element with a one-line description:

```
[HEADING DIAL] ← Set your target heading. Ship turns toward this.
[THROTTLE SLIDER] ← Control ship speed. 0% = stop, 100% = full.
[MINIMAP] ← Your position in the sector. Green = you, red = enemies.
[FORWARD VIEW] ← What's ahead. Rotates with your heading.
```

Labels are positioned relative to the UI elements they describe. Wire aesthetic (same font, same colours, translucent panel behind each label). Dismisses on any click, Escape, or F1 again.

**Implementation**: Each station defines a help manifest — an array of `{ selector, text, position }` objects. The shared help renderer reads the manifest and draws the overlay. One shared module, per-station data.

```javascript
// In helm.js:
import { registerHelp } from '../shared/help_overlay.js';
registerHelp([
    { selector: '#heading-dial', text: 'Set target heading. Ship turns toward this.', position: 'right' },
    { selector: '#throttle-slider', text: 'Ship speed. 0% = stop, 100% = full.', position: 'left' },
    // ...
]);
```

### 4.3 Difficulty Presets

**Lobby UI**: After selecting mission, before launch, the host selects difficulty:

| Preset | Enemy Damage | Puzzle Timers | Spawn Rates | Crew Casualties | Hints |
|--------|-------------|---------------|-------------|-----------------|-------|
| **Cadet** | 50% | 150% (more time) | 75% | 50% | Enabled |
| **Officer** | 100% | 100% | 100% | 100% | Disabled |
| **Commander** | 130% | 80% | 120% | 130% | Disabled |
| **Admiral** | 160% | 60% | 150% | 160% | Disabled |

**Implementation**: Difficulty is a set of multipliers applied at game start. All combat, puzzle, and spawn constants are already named constants in their respective modules. The difficulty system wraps them:

```python
# server/difficulty.py
@dataclass
class DifficultySettings:
    enemy_damage_mult: float = 1.0
    puzzle_time_mult: float = 1.0
    spawn_rate_mult: float = 1.0
    crew_casualty_mult: float = 1.0
    hints_enabled: bool = False

PRESETS = {
    "cadet": DifficultySettings(0.5, 1.5, 0.75, 0.5, True),
    "officer": DifficultySettings(1.0, 1.0, 1.0, 1.0, False),
    "commander": DifficultySettings(1.3, 0.8, 1.2, 1.3, False),
    "admiral": DifficultySettings(1.6, 0.6, 1.5, 1.6, False),
}
```

Hints (Cadet mode): Subtle UI indicators that help new players. Weapons gets a "SUGGESTED TARGET" highlight on the most dangerous enemy. Engineering gets a "RECOMMENDED" label on underpowered critical systems. Helm gets a directional indicator pointing toward the current objective. These use existing data — no new game logic, just UI hints derived from game state.

### Acceptance Criteria

- [ ] Reconnect within 60 seconds reclaims role automatically
- [ ] Reconnect after 60 seconds shows "ROLE OCCUPIED" if taken
- [ ] Reserved roles show as "DISCONNECTED" in lobby
- [ ] F1 opens help overlay on every station
- [ ] Help overlay shows correct labels for every interactive element
- [ ] Help overlay dismisses on click/Escape/F1
- [ ] Difficulty selector appears in lobby before launch
- [ ] Cadet difficulty measurably reduces enemy damage and extends puzzle timers
- [ ] Admiral difficulty measurably increases everything
- [ ] Cadet hints appear on Weapons, Engineering, and Helm

---

## 5. v0.03c — UNIFIED MAP RENDERER + NOTIFICATION OVERLAYS

**Purpose**: Replace per-station canvas duplication with a shared, configurable map renderer. Add toggleable notification overlay layers.

### 5.1 MapRenderer Class

```
client/shared/
├── map_renderer.js       # MapRenderer class: configurable layers, zoom,
│                          # orientation, interaction, overlay system
├── map_layers/
│   ├── grid.js           # Background grid + range rings
│   ├── contacts.js       # Entity rendering (wireframe shapes per type)
│   ├── hazards.js        # Minefields, nebulae, gravity wells, radiation
│   ├── weapons.js        # Beam lines, torpedo trails, weapon arcs
│   ├── mission.js        # Waypoints, objective markers, area boundaries
│   └── interior.js       # Ship interior rooms (Security-specific layer)
├── map_overlays/
│   ├── damage.js         # Impact location pulses, damage direction
│   ├── contagion.js      # Biohazard zones, contagion spread animation
│   ├── boarders.js       # Intruder positions, breach points
│   ├── signals.js        # Signal sources, transmission bearings, hailing range
│   └── scan_coverage.js  # Active scan range, passive detection range per mode
```

**MapRenderer configuration**:
```javascript
const map = new MapRenderer(canvas, {
    range: 30000,               // World units visible from centre
    orientation: 'north-up',    // 'north-up' | 'heading-up'
    centre: 'ship',             // 'ship' | 'world' | {x, y}
    zoom: { enabled: true, min: 0.5, max: 4.0 },
    layers: ['grid', 'contacts', 'weapons'],
    overlays: [],               // Toggled by player
    interactive: false,         // Click-to-select contacts
    showArcs: false,            // Weapon arc overlays
    showRangeRings: true,
});

// Update each frame
map.update(gameState);
map.render();

// Toggle overlays
map.toggleOverlay('damage');
map.setOverlayConfig('scan_coverage', { mode: 'em', range: 30000 });
```

### 5.2 Per-Station Configuration

| Station | Orientation | Range | Layers | Overlays Available | Interactive |
|---------|------------|-------|--------|--------------------|-------------|
| Captain | North-up | 80k | All | All | Click for info |
| Helm | Heading-up | 20k | grid, contacts, hazards, mission | damage | No |
| Weapons | North-up | 15k | grid, contacts, weapons | damage | Click to target |
| Science | North-up | 35k | grid, contacts, hazards, signals | scan_coverage | Click to scan |
| Security | N/A | Interior | interior, boarders | contagion | Click to move |
| Comms | North-up | 40k | grid, contacts, signals | — | Click to hail |
| Viewscreen | Heading-up | 10k | contacts, weapons, hazards | — | No |
| Tactical* | North-up | 50k | grid, contacts, weapons, mission | damage | Click to designate |

*Tactical Officer station (v0.03l)

### 5.3 Migration Strategy

1. Build MapRenderer with grid and contacts layers
2. Migrate Captain's tactical map (most layers, best test case)
3. Validate rendering matches or improves on the original
4. Migrate Weapons radar
5. Migrate Science sensor display
6. Migrate Helm minimap
7. Migrate Viewscreen
8. Migrate Comms (new station, built on MapRenderer from the start)

Stations not yet migrated continue using their existing canvas code. Both paths coexist during migration.

### 5.4 Overlay Toggle UI

A small panel in the corner of the map canvas (or in the station controls area) with toggle buttons for available overlays. Each overlay has an icon and a name. Active overlays show their icon highlighted. The panel collapses to just icons when not hovered/focused.

### Acceptance Criteria

- [ ] MapRenderer renders grid, contacts, and range rings correctly
- [ ] North-up and heading-up orientations work
- [ ] Zoom in/out works (mouse wheel or pinch)
- [ ] Captain's map migrated and rendering matches or improves original
- [ ] At least 3 stations migrated to MapRenderer
- [ ] Damage overlay shows impact pulses that fade over 5 seconds
- [ ] Overlay toggles work per station
- [ ] Performance: 60fps with 20+ contacts on the map

---

## 6. v0.03d — CROSS-STATION NOTIFICATION SYSTEM

**Purpose**: Structured player-to-player messaging that supplements (not replaces) verbal communication.

### 6.1 Notification Types

**Quick notifications** — single-tap contextual messages:

| From | Notification | Context |
|------|-------------|---------|
| Science | "Target [X]: Weak to [direction] attack" | After completing an EM scan |
| Science | "Hazard detected at bearing [N]" | After GRAV scan reveals hazard |
| Engineering | "Power critical — [system] underpowered" | When budget is overcommitted |
| Engineering | "[System] offline — repair in progress" | When a system hits 0% |
| Medical | "Crew casualties on [deck] — [N] critical" | When critical count rises |
| Security | "Boarders detected — [location]" | When intruders are spotted |
| Security | "Deck [N] secured" | When intruders eliminated in an area |
| Comms | "Incoming transmission from [contact]" | When transmission received |
| Comms | "Intel: [brief summary]" | After decoding a transmission |
| Weapons | "Target [X] shields down" | When target shields reach 0 |
| Weapons | "Torpedo away — impact in [N]s" | After torpedo launch |
| Helm | "Maneuvering to [heading]" | On significant course change |
| Captain | "All stations: [preset message]" | Broadcast to all |

**Implementation**: Each notification is a `crew.notify` message with `{ from_role, to_role (or "all"), type, text }`. The server validates and broadcasts. The receiving station shows a small toast notification in the station header area — role colour-coded, auto-dismisses after 5 seconds, click to dismiss early. A notification log (scrollable, last 20 messages) is accessible via a small icon.

### 6.2 Quick-Send UI

A notification button or keyboard shortcut opens a compact quick-send panel. Context-aware: the options shown depend on the current game state. Science sees "Report scan results to Weapons" after completing a scan. Engineering sees "Report power warning to Captain" when budget is stressed. 2-3 relevant options max, not an overwhelming list.

### 6.3 Captain's Broadcast

Captain gets a special version: broadcast to all stations. Preset messages ("All stop", "Battle stations", "Prepare for docking", "Brace for impact") plus a free-text field for custom messages. These appear on every station simultaneously with the alert-level colour.

### Acceptance Criteria

- [ ] Quick-send notifications work between all station pairs
- [ ] Notifications appear as toast in receiving station's header
- [ ] Notifications auto-dismiss after 5 seconds
- [ ] Notification log accessible and scrollable
- [ ] Captain broadcast reaches all connected stations
- [ ] Context-aware quick-send shows relevant options
- [ ] Notifications are logged by the game logger

---

## 7. v0.03e — SHIP FRAMEWORK

**Purpose**: JSON-defined ship classes supporting 3-12 players with different capabilities.

### 7.1 Ship Class Definitions

```
ships/
├── scout.json            # 3-4 players. Fast, fragile, multitasking.
├── corvette.json         # 5-6 players. The v0.01 experience. Balanced.
├── frigate.json          # 7-8 players. The v0.02 experience. All core roles.
├── cruiser.json          # 9-10 players. Specialist roles emerge.
├── battleship.json       # 11-12 players. Full complement. Maximum coordination.
├── medical_ship.json     # 6-8 players. Lightly armed, massive medbay.
└── carrier.json          # 8-12 players. Flight Ops critical. Drone/fighter focus.
```

**Ship class JSON schema**:

```json
{
    "id": "corvette",
    "name": "Sentinel-class Corvette",
    "description": "Balanced warship. Reliable, adaptable, forgiving. The standard crew's first command.",
    "crew_size": { "min": 5, "max": 6 },
    "required_roles": ["captain", "helm", "weapons", "engineering", "science"],
    "optional_roles": ["comms"],
    "combined_roles": {
        "captain+tactical": { "label": "Command", "roles": ["captain", "tactical"] },
        "science+comms": { "label": "Operations", "roles": ["science", "comms"] }
    },
    "systems": {
        "engines": { "max_power": 150, "base_health": 100 },
        "beams": { "count": 2, "arc": 120, "max_power": 150 },
        "torpedoes": { "tubes": 2, "magazine": 10, "max_power": 150 },
        "shields": { "segments": 2, "max_power": 150 },
        "sensors": { "range": 30000, "max_power": 150 },
        "manoeuvring": { "max_power": 150 }
    },
    "hull": 100,
    "power_budget": 600,
    "marine_squads": 3,
    "interior": "standard",
    "viewscreen_model": "corvette"
}
```

**Scout (3-4 players)**:
```json
{
    "id": "scout",
    "name": "Pathfinder-class Scout",
    "description": "Fast and fragile. Outrun what you can't outfight.",
    "crew_size": { "min": 3, "max": 4 },
    "required_roles": ["helm", "weapons", "engineering"],
    "optional_roles": ["science"],
    "combined_roles": {
        "helm+science": { "label": "Navigator", "roles": ["helm", "science"] },
        "weapons+tactical": { "label": "Gunner", "roles": ["weapons", "tactical"] },
        "engineering+damage_control": { "label": "Chief Engineer", "roles": ["engineering", "damage_control"] }
    },
    "systems": {
        "engines": { "max_power": 120, "base_health": 60 },
        "beams": { "count": 1, "arc": 90, "max_power": 100 },
        "torpedoes": null,
        "shields": { "segments": 1, "max_power": 100 },
        "sensors": { "range": 20000, "max_power": 100 },
        "manoeuvring": { "max_power": 120 }
    },
    "hull": 60,
    "power_budget": 400,
    "marine_squads": 1,
    "interior": "scout",
    "viewscreen_model": "scout"
}
```

**Battleship (11-12 players)**:
```json
{
    "id": "battleship",
    "name": "Sovereign-class Battleship",
    "description": "Devastatingly powerful. Requires a full crew to operate effectively.",
    "crew_size": { "min": 10, "max": 12 },
    "required_roles": [
        "captain", "helm", "weapons", "engineering", "science",
        "comms", "medical", "security", "tactical", "damage_control"
    ],
    "optional_roles": ["flight_ops", "electronic_warfare"],
    "combined_roles": {},
    "systems": {
        "engines": { "max_power": 150, "base_health": 150 },
        "beams": { "count": 4, "arc": 90, "max_power": 150 },
        "torpedoes": { "tubes": 4, "magazine": 24, "max_power": 150 },
        "shields": { "segments": 4, "max_power": 150 },
        "sensors": { "range": 40000, "max_power": 150 },
        "manoeuvring": { "max_power": 120 },
        "point_defence": { "max_power": 100 },
        "ecm_suite": { "max_power": 100 },
        "flight_deck": { "max_power": 100 }
    },
    "hull": 200,
    "power_budget": 1000,
    "marine_squads": 6,
    "interior": "battleship",
    "viewscreen_model": "battleship"
}
```

### 7.2 Ship Loader

```python
# server/models/ship_class.py
def load_ship_class(ship_id: str) -> ShipClassDefinition: ...
def create_ship_from_class(ship_class: ShipClassDefinition) -> Ship: ...
def get_available_roles(ship_class: ShipClassDefinition) -> list[str]: ...
def get_combined_roles(ship_class: ShipClassDefinition) -> dict[str, list[str]]: ...
```

### 7.3 Lobby Changes

1. Host selects ship class (card-based UI showing ship name, description, crew range, silhouette)
2. Role selection updates to show only available roles for that ship class
3. Combined roles appear as single entries (e.g., "Navigator (Helm + Science)")
4. Mission select filters to missions compatible with the ship's capabilities (a Scout can't run Boarding Action with 1 marine squad)
5. Launch requires all required_roles filled

### 7.4 Ship Interiors

Each ship class references an interior layout. Different ships have different room configurations:

- **Scout interior**: 8 rooms across 2 decks. Compact, fast traversal.
- **Standard interior**: 20 rooms across 5 decks. Current v0.02 layout.
- **Battleship interior**: 35 rooms across 7 decks. Large, complex, multiple routes between areas.

Interior layouts are defined as JSON alongside the ship class definition.

### Acceptance Criteria

- [ ] Ship class JSON files load correctly
- [ ] Lobby shows ship class selection before role selection
- [ ] Role list updates based on selected ship class
- [ ] Combined roles appear correctly in lobby
- [ ] Ship parameters (hull, power budget, systems) configure from ship class
- [ ] Scout (3 players) is playable with combined roles
- [ ] Battleship (12 players) shows all roles available
- [ ] Mission filtering works (incompatible missions greyed out)
- [ ] Ship interior loads from ship class definition

---

## 8. v0.03f — MULTI-ROLE + ROLE SWITCHING

**Purpose**: One player operates multiple stations via tabbed or split-screen UI.

### 8.1 Combined Role Client

When a player claims a combined role (e.g., "Navigator = Helm + Science"), the client:

1. Claims both role strings on the WebSocket connection
2. Loads both station modules
3. Renders a tabbed interface with the station header showing tabs for each sub-role

**Tab mode** (default):
- Active tab shows full station UI
- Inactive tab shows a miniaturised status bar (1-line summary: "SCIENCE: 3 contacts, no active scan")
- Tab flashes with alert colour when the inactive station has an event requiring attention
- Keyboard shortcut: Tab key cycles, or number keys (1 = first role, 2 = second)
- Audio cue on inactive-tab event (distinct from other sounds)

**Split mode** (toggle via button):
- Both stations render side-by-side, each at 50% width
- Responsive: on narrow screens, stacks vertically
- Less detail visible but no context switching needed

### 8.2 Hot-Switching Mid-Game

A persistent role bar at the bottom of every station (collapsible) shows all roles for the current ship class:

```
[CAPTAIN ●] [HELM ●] [WEAPONS ●] [ENGINEERING ●] [SCIENCE ○] [COMMS ○]
  Alice       Bob      Charlie      Diana         (open)      (open)
```

● = claimed (shows player name), ○ = unclaimed.

Click an unclaimed role to switch to it. Your previous role becomes unclaimed. A brief confirmation prompt prevents accidental switches: "Switch from Engineering to Science? Engineering will become unclaimed."

The Captain's crew management panel shows the same view and allows sending switch requests to players.

### 8.3 Server Changes

Minimal server changes needed:

- A single WebSocket connection can claim multiple roles (already supported — `claim_role` just needs to allow additional claims without releasing the first)
- `release_role` can release a specific role (already works)
- Role-filtered broadcasting sends to connections that have ANY of the target roles (already works if the connection has multiple roles tagged)
- Lobby state shows combined role labels from the ship class definition

### Acceptance Criteria

- [ ] Combined roles load both station modules in tabbed UI
- [ ] Tab switching works via click and keyboard shortcut
- [ ] Inactive tab shows status summary
- [ ] Inactive tab flashes on relevant events
- [ ] Split mode renders both stations side-by-side
- [ ] Hot-switching between unclaimed roles works mid-game
- [ ] Previous role becomes unclaimed on switch
- [ ] Confirmation prompt prevents accidental switches
- [ ] 3-player Scout game playable with combined roles

---

## 9. v0.03g — MISSION BRIEFING ROOM

**Purpose**: Replace the briefing overlay with a proper pre-mission screen where the crew assembles.

### 9.1 Briefing Screen

After the host clicks "Launch" in the lobby, all players transition to a shared briefing screen (not their individual stations). The briefing shows:

- Mission name and briefing text (narrative)
- Star chart showing the mission area (using MapRenderer with mission layer)
- Per-role objective highlights: each player sees their role-specific first objectives
- Ship class and loadout summary
- Difficulty level
- Player roster showing who's on what role

### 9.2 Ready Check

Each player has a "READY" button. The status panel shows who's ready and who isn't:

```
CREW STATUS:
  ● Captain (Alice) ......... READY
  ● Helm (Bob) .............. READY
  ● Weapons (Charlie) ....... STANDING BY
  ○ Engineering (Diana) ..... READING BRIEFING
```

The game starts when all players are ready, or the Captain can override with "LAUNCH" (countdown 5 seconds, anyone can cancel). This creates a proper pre-mission moment and ensures everyone has read the briefing.

### 9.3 Transition

On launch, the briefing screen transitions to each player's station with a brief animation (screen wipe in the alert-level colour). The station loads with the briefing overlay already dismissed — the briefing room IS the briefing.

### Acceptance Criteria

- [ ] Briefing screen appears after lobby launch
- [ ] All players see the same mission briefing
- [ ] Per-role objectives shown to each player
- [ ] Ready check works (all ready → auto-launch)
- [ ] Captain override launches with countdown
- [ ] Transition to stations is smooth
- [ ] Star chart renders correctly on briefing screen

---

## 10. v0.03h — SCIENCE SCAN MODES

This section is fully specified in docs/SCOPE_v002.md, Section 14 (Addendum: Science Scan Modes). Implement Tier 1:

- Four scan modes (EM, GRAV, BIO, SUB)
- Mode switching with 3-second reconfiguration delay
- Per-mode passive detection (short range, low detail)
- Per-mode active scanning (long range, full results)
- Scan results accumulate per entity across modes
- Mode selector UI with keyboard shortcuts 1-4
- Per-mode canvas rendering style variation
- Contact detail panel with per-mode data tabs

### Acceptance Criteria

- [ ] All four scan modes functional
- [ ] Mode switching works with 3-second delay
- [ ] Passive detection range varies by mode
- [ ] Active scan produces mode-specific results
- [ ] Scan results accumulate (EM scan + BIO scan = both datasets)
- [ ] Unscanned modes show "NO DATA — REQUIRES [MODE] SCAN"
- [ ] Canvas rendering style changes per mode
- [ ] Keyboard shortcuts 1-4 work
- [ ] Existing Science tests pass (backwards compatible)

---

## 11. v0.03i — DAMAGE CONTROL OFFICER

**Purpose**: Physical damage management — hull breaches, fires, atmosphere, repair team routing.

### 11.1 Role Split from Engineering

Engineering keeps: power distribution, overclock management, system power levels, circuit routing puzzles.

Damage Control takes: hull integrity, fire suppression, atmospheric control, physical repair team management, decompression handling, emergency bulkheads.

Both stations show the ship interior map, but with different overlays: Engineering sees power conduits and system nodes; Damage Control sees structural integrity, fires, atmosphere, and repair teams.

### 11.2 Core Mechanics

**Hull breach management**: When hull takes damage in combat, there's a chance of a hull breach in a specific room. Breaches cause decompression (crew casualties, system efficiency loss). DC must seal the breach (repair puzzle or timed action) before the entire deck decompresses.

**Fire suppression**: System overloads, overclock damage, and combat hits can start fires. Fires spread to adjacent rooms if not contained. DC activates fire suppression per room (uses a limited suppressant resource) or seals the room and vents atmosphere (kills the fire but decompresses the room).

**Atmospheric control**: DC monitors atmosphere per room. Decompressed rooms can be repressurised after breaches are sealed (takes time, uses atmosphere reserves). DC decides priorities: repressurize the medbay so Medical can work, or repressurize engineering so repair teams can access the reactor?

**Repair team routing**: DC has repair teams (separate from Engineering's power-level repair and Security's marines). Repair teams physically travel through the ship interior to reach damaged locations. DC plots their route (blocked by fires, decompression, sealed doors, boarders). The ship interior map shows repair team positions and routes.

**Emergency bulkheads**: DC can trigger emergency bulkhead seals (faster than Security's door control, but affects more doors at once — seals an entire deck). This is the "contain the damage" panic button. Trade-off: it also blocks repair team and marine movement.

### 11.3 Damage Control Puzzle: Breach Repair

When a hull breach occurs, DC gets a timed puzzle: a structural integrity diagram showing the breach location and available repair materials. DC must route repair patches to cover the breach before atmosphere loss reaches critical. Similar to circuit routing but with physical structural constraints.

**Assist**: Engineering can reroute emergency power to structural integrity fields (slows atmosphere loss, giving DC more time). Security can send marines to assist with physical repairs (speeds up the repair).

### 11.4 UI Layout

```
┌─────────────────────────────┬──────────────────┐
│                             │ HULL INTEGRITY    │
│   SHIP INTERIOR MAP         │ ██████████ 78%    │
│   (structural overlay)      │                  │
│                             │ ATMOSPHERE        │
│   Fires: orange rooms       │ Deck 1: 100%     │
│   Breaches: red pulsing     │ Deck 2: 85% ▼    │
│   Decompressed: grey        │ Deck 3: 0% VOID  │
│   Repair teams: blue tokens │ Deck 4: 100%     │
│                             │ Deck 5: 92%      │
│                             ├──────────────────┤
│                             │ REPAIR TEAMS      │
│                             │ Team 1: Deck 3   │
│                             │ Team 2: Idle     │
│                             │ Team 3: En route │
│                             ├──────────────────┤
│                             │ SUPPRESSANT: 70% │
│                             │ ATMO RESERVE: 45%│
├─────────────────────────────┴──────────────────┤
│ ALERTS: Hull breach Deck 3 Cargo Hold          │
│         Fire spreading Deck 2 Science Lab      │
└────────────────────────────────────────────────┘
```

### Acceptance Criteria

- [ ] DC station renders ship interior with structural overlay
- [ ] Hull breaches occur from combat damage
- [ ] Breaches cause decompression in affected rooms
- [ ] Fire mechanics work (start, spread, suppression)
- [ ] Atmospheric control (depressurise/repressurize rooms)
- [ ] Repair teams move through ship interior
- [ ] Breach repair puzzle works
- [ ] Emergency bulkhead seal works
- [ ] DC ↔ Engineering assist chain works
- [ ] DC ↔ Security assist chain works
- [ ] Resources (suppressant, atmosphere reserves) are finite

---

## 12. v0.03j — FLIGHT OPERATIONS OFFICER

**Purpose**: Manages auxiliary craft — drones, probes, shuttlecraft, escape pods.

### 12.1 Core Mechanics

**Reconnaissance drones**: Small autonomous craft launched from the ship. Science tells Flight Ops where to deploy them. Drones extend sensor coverage in a direction (they have their own short-range passive sensors). Drones have limited fuel — must be recalled before it runs out or they're lost. 2-4 drones available depending on ship class.

**Sensor probes**: Stationary objects deployed at a location. Create a persistent detection bubble. Useful for monitoring chokepoints, scanning behind asteroid fields, or watching a flank. Probes are expendable (finite supply, not recovered). Data feeds to Science's sensor display.

**Shuttlecraft**: Multi-purpose craft for away missions, personnel transfer, cargo transport, and emergency evacuation. Shuttle launch/recovery requires Helm to maintain steady course and speed. Flight Ops plots the shuttle's route and monitors its status.

**Escape pods**: Emergency crew evacuation. Flight Ops manages pod launch, tracks pod positions, and coordinates recovery (by the player ship or friendly vessels). Relevant when hull integrity is critical — the Captain orders abandon ship, Flight Ops executes.

**Flight deck power**: The flight deck is a ship system (power allocation from Engineering). Low power = slower launch/recovery, reduced drone range. No power = flight deck offline.

### 12.2 Flight Ops Map

Flight Ops uses the MapRenderer with a custom overlay showing all auxiliary craft:

- Drones: Small friendly-coloured triangles with fuel gauge arcs
- Probes: Stationary friendly-coloured diamonds with detection range circles
- Shuttles: Larger friendly-coloured rectangles with route lines
- Escape pods: Small neutral-coloured dots with drift vectors

The map shows the main ship, all auxiliary craft, and their detection/communication ranges. Flight Ops can click to select and issue orders.

### 12.3 UI Layout

```
┌─────────────────────────────┬──────────────────┐
│                             │ CRAFT STATUS      │
│   SECTOR MAP                │ Drone 1: Deploy   │
│   (flight ops overlay)      │   Fuel: ████ 67%  │
│                             │   Pos: 45°, 12k   │
│   Ship + all craft visible  │ Drone 2: Hangar   │
│   Detection ranges shown    │ Probe 1: Active   │
│   Route lines for shuttles  │   Pos: 120°, 20k  │
│                             │ Shuttle: Hangar   │
│                             ├──────────────────┤
│                             │ FLIGHT DECK       │
│                             │ Power: 100%       │
│                             │ Status: Ready     │
│                             │                  │
│                             │ [LAUNCH DRONE]    │
│                             │ [DEPLOY PROBE]    │
│                             │ [LAUNCH SHUTTLE]  │
│                             │ [RECALL ALL]      │
├─────────────────────────────┴──────────────────┤
│ FLIGHT LOG: Drone 1 deployed to bearing 045    │
└────────────────────────────────────────────────┘
```

### Acceptance Criteria

- [ ] Flight Ops station renders sector map with auxiliary craft
- [ ] Drone launch, deployment, recall, and fuel management work
- [ ] Probes deploy and create persistent detection bubbles
- [ ] Drone/probe sensor data feeds to Science's display
- [ ] Shuttle launch and route plotting work
- [ ] Flight deck power affects launch/recovery speed
- [ ] Craft appear on Captain's tactical map
- [ ] Science → Flight Ops communication for drone direction
- [ ] Helm steady-course requirement for shuttle operations

---

## 13. v0.03k — ELECTRONIC WARFARE OFFICER

**Purpose**: Offensive and defensive cyber warfare — jamming, countermeasures, spoofing, system intrusion.

### 13.1 Core Mechanics

**Sensor jamming**: Target an enemy ship and degrade its sensor accuracy. Jammed enemies fire less accurately (wider spread on beams, worse torpedo tracking). Costs ECM power and has a limited range. Multiple enemies can't all be jammed simultaneously — EW must choose priorities.

**Countermeasures**: Defensive suite that reduces incoming weapon accuracy against the player ship. Deploys chaff (confuses beam targeting), decoys (diverts torpedoes), and false signatures (makes the ship harder to lock onto). Countermeasure charges are finite — replenished at stations.

**Sensor spoofing**: Create false contacts on enemy sensors. Enemy AI responds to spoofed contacts (chases decoys, fires at ghosts). Requires ECM power and must be maintained (spoofed contacts disappear if EW stops broadcasting). Useful for distracting enemies from the station during Defend missions.

**System intrusion**: Puzzle-based hacking mechanic. EW attempts to penetrate an enemy ship's systems. Success can temporarily disable enemy shields, weapons, or engines. The intrusion puzzle is similar to circuit routing but represents navigating a network — nodes are firewalls, connections are data paths, the target is the enemy system.

**Counterintelligence**: Detect and counter enemy jamming and intrusion attempts against the player ship. When enemy EW targets the player, a notification appears on the EW station. EW can allocate countermeasure resources to block the intrusion.

**ECM suite power**: The ECM suite is a ship system (power allocation from Engineering). Higher power = longer jam range, faster intrusion, more effective countermeasures.

### 13.2 Intrusion Puzzle

Similar to circuit routing but with a network/hacking theme:

**Visual**: Network topology diagram. Nodes are enemy firewalls (some active, some inactive). Connections are data paths. The starting node is the player ship. The target node is the enemy system (shields, weapons, or engines).

**Mechanic**: Plot a path from start to target through the network. Active firewalls must be bypassed (costs time), disabled (costs resources), or avoided (longer path). A countdown represents the enemy's intrusion detection — take too long and the connection is severed.

**Assist**: Science can probe the enemy network first (active EM scan reveals the network topology before the intrusion begins, effectively giving EW a preview of the puzzle). Comms can intercept enemy security codes (pre-bypasses some firewalls).

### 13.3 UI Layout

```
┌─────────────────────────────┬──────────────────┐
│                             │ ECM STATUS        │
│   TACTICAL/ECM MAP          │ Power: 100%       │
│                             │ Mode: Jamming     │
│   Jam ranges shown          │ Target: Enemy 2   │
│   Countermeasure field      │ Effectiveness: 72%│
│   Spoofed contacts visible  │                  │
│                             │ COUNTERMEASURES   │
│                             │ Chaff: ████ 80%   │
│                             │ Decoys: ███ 60%   │
│                             │ Charges: 12       │
│                             ├──────────────────┤
│                             │ INTRUSION         │
│                             │ Status: Idle      │
│                             │ [JAM TARGET]      │
│                             │ [DEPLOY CHAFF]    │
│                             │ [LAUNCH DECOY]    │
│                             │ [BEGIN INTRUSION]  │
├─────────────────────────────┴──────────────────┤
│ EW LOG: Jamming Enemy 2 — accuracy reduced 28% │
└────────────────────────────────────────────────┘
```

### Acceptance Criteria

- [ ] EW station renders tactical map with ECM overlays
- [ ] Sensor jamming reduces enemy weapon accuracy
- [ ] Countermeasures reduce incoming weapon accuracy
- [ ] Spoofed contacts appear on enemy AI sensors and distract them
- [ ] System intrusion puzzle works end-to-end
- [ ] Successful intrusion disables enemy system temporarily
- [ ] Counterintelligence detects enemy EW attempts
- [ ] ECM suite power affects effectiveness
- [ ] Countermeasure charges are finite
- [ ] Science → EW assist chain works (network topology reveal)
- [ ] Comms → EW assist chain works (security code intercept)

---

## 14. v0.03l — TACTICAL OFFICER

**Purpose**: Battle planning, threat assessment, engagement coordination.

### 14.1 Core Mechanics

**Tactical plot**: An annotated version of the sensor/map display. Tactical can add markers, threat vectors, engagement envelopes, and notes. These annotations are visible to Captain and (optionally) other stations. Think of it as a shared whiteboard overlaid on the star chart.

**Threat assessment**: Automated analysis of enemy contacts using Science scan data. Each contact gets a threat rating (low/medium/high/critical) based on weapon loadout, distance, heading, and behaviour. Tactical can override the auto-assessment. Threat ratings colour-code contacts on all displays.

**Engagement priorities**: Tactical designates targets as primary, secondary, or ignore. Weapons sees these designations on their radar. This is advisory, not mandatory — Weapons can still fire at whatever they want, but the designations help coordinate fire.

**Intercept plotting**: Tactical calculates intercept courses and relays them to Helm. "Helm, intercept Alpha at bearing 270, estimated time to weapons range 45 seconds." The intercept course appears as a suggested heading on Helm's display.

**Coordinated strikes**: Tactical sets up timed manoeuvres. "On my mark: Helm hard to port, Weapons fire all torpedoes." A countdown appears on the relevant stations. This is a coordination tool, not automation — each player still executes their part manually. The timing window is displayed so everyone knows when to act.

**Battle damage assessment**: After engaging a target, Tactical compiles a BDA from Science scan data: damage inflicted, systems disabled, crew casualties estimated. This feeds into the next engagement decision.

### 14.2 Tactical Plot Annotations

Annotations are drawn on the MapRenderer as a custom overlay layer:

| Annotation | How | Visual |
|------------|-----|--------|
| Threat vector | Click enemy, drag direction | Arrow from enemy showing expected movement |
| Engagement envelope | Click ship, define radius | Circle showing weapons range from a position |
| Waypoint | Click map location | Labelled marker |
| Area marker | Click and drag | Named zone (rectangle or circle) |
| Note | Click location, type text | Text label at position |
| Intercept line | Click enemy, click intercept point | Dashed line showing suggested approach |

Annotations persist until Tactical removes them or the game ends. Captain sees all annotations. Other stations see annotations tagged for their role.

### 14.3 Coordinated Strike Mechanic

1. Tactical creates a "strike plan" — a sequence of actions assigned to roles with timing:
   - T-10s: Helm sets heading 270
   - T-5s: Engineering boosts weapons to 130%
   - T-0: Weapons fires all torpedoes
   - T+2s: Helm hard to starboard (evasion)

2. The plan appears on each relevant station as a countdown card: "TACTICAL: Set heading 270 in 8... 7... 6..."

3. Each player executes their part manually at the right time. The plan is advisory — it shows what Tactical wants, not what the computer executes.

4. After the strike, Tactical sees whether each action was executed on time (based on server state changes matching the plan within a tolerance window).

This is a social coordination tool. It replaces the Captain verbally counting down — which works, but this gives it structure, visibility, and a success rating.

### 14.4 UI Layout

```
┌─────────────────────────────┬──────────────────┐
│                             │ THREAT BOARD      │
│   TACTICAL PLOT             │ Alpha: ●●● HIGH   │
│   (annotated map)           │   Cruiser, armed  │
│                             │   Range: 8,200    │
│   Annotations visible       │ Bravo: ●○○ LOW    │
│   Threat colours on         │   Scout, fleeing  │
│   contacts                  │   Range: 22,100   │
│   Intercept lines           │ Charlie: ●●○ MED  │
│                             │   Destroyer, appr │
│                             ├──────────────────┤
│                             │ ENGAGEMENT        │
│                             │ Primary: Alpha    │
│                             │ Secondary: Charlie│
│                             │ Ignore: Bravo     │
│                             ├──────────────────┤
│                             │ STRIKE PLAN       │
│                             │ [NEW PLAN]        │
│                             │ [EXECUTE PLAN]    │
│                             │                  │
├─────────────────────────────┴──────────────────┤
│ TACTICAL LOG: Alpha turning to engage — 45s to │
│ weapons range. Recommend intercept heading 270. │
└────────────────────────────────────────────────┘
```

### Acceptance Criteria

- [ ] Tactical station renders annotated tactical plot
- [ ] Threat assessment auto-rates contacts (using Science data)
- [ ] Engagement priorities visible on Weapons radar
- [ ] Intercept course suggestions appear on Helm display
- [ ] Tactical plot annotations work (add, view, remove)
- [ ] Captain sees all tactical annotations
- [ ] Coordinated strike plans work (countdown on relevant stations)
- [ ] Strike execution tracking works (did each player act on time?)
- [ ] Battle damage assessment compiles from Science scan data
- [ ] Annotations persist during game, cleared on game end

---

## 15. v0.03m — TRAINING MISSIONS

**Purpose**: Per-station solo tutorials for classroom onboarding.

### 15.1 Design

Each training mission:
- Targets a single station (other roles simulated by the server)
- Teaches controls step-by-step with guided prompts
- Takes 5-10 minutes
- Ends with a scored challenge using the taught mechanics
- Can be run solo — no other players needed

### 15.2 Training Mission List

| Mission | Target Station | Teaches |
|---------|---------------|---------|
| Helm Training | Helm | Heading control, throttle, minimap reading, waypoint navigation |
| Weapons Training | Weapons | Target selection, beam firing arcs, torpedo management, shield balance |
| Engineering Training | Engineering | Power distribution, overclock risk, repair management, budget constraints |
| Science Training | Science | Scan modes, active scanning, contact classification, data relay |
| Medical Training | Medical | Crew status reading, triage, treatment sequencing, quarantine |
| Security Training | Security | Interior map, squad movement, door control, boarding defence |
| Comms Training | Comms | Frequency scanning, hailing, transmission decoding |
| Damage Control Training | Damage Control | Breach repair, fire suppression, atmospheric management |
| Flight Ops Training | Flight Ops | Drone deployment, probe placement, shuttle operations |
| EW Training | Electronic Warfare | Jamming, countermeasures, intrusion puzzle |
| Tactical Training | Tactical | Threat assessment, engagement priorities, strike planning |
| Captain Training | Captain | Dashboard overview, alert levels, authorisation, crew management |

### 15.3 Server Simulation

Training missions run a simplified game loop where the server auto-plays the missing roles:
- Auto-helm follows waypoints at safe speed
- Auto-engineering maintains balanced power
- Auto-weapons fires at designated targets
- AI crew fills in whatever the student isn't doing

The simulation doesn't need to be sophisticated — it just needs to keep the game running so the student can focus on learning their station.

### Acceptance Criteria

- [ ] Each training mission is launchable solo
- [ ] Guided prompts appear step-by-step
- [ ] Server simulates missing roles adequately
- [ ] Each mission teaches the core mechanics of its station
- [ ] Scoring works at the end
- [ ] Training missions selectable from lobby (separate category from regular missions)
- [ ] All 12 training missions complete

---

## 16. v0.03n — DEBRIEF DASHBOARD + CAPTAIN'S REPLAY

**Purpose**: Post-game analysis using game logger data.

### 16.1 Debrief Dashboard

After game.over, instead of the current simple stats overlay, show a full debrief screen:

- **Timeline**: Scrollable event timeline showing major events (combat, damage, objectives, puzzle solves). Click to jump to that moment in the replay.
- **Per-station stats**: Activity metrics per role. Helm distance travelled, Weapons damage dealt, Engineering power changes, Science scans completed, Medical crew treated, etc.
- **Awards**: Fun per-player recognitions generated from the log data:
  - "Sharpshooter" — most damage dealt (Weapons)
  - "Iron Hull" — least damage taken (Helm)
  - "Power Broker" — most power reconfigurations (Engineering)
  - "Eagle Eye" — most contacts scanned (Science)
  - "Life Saver" — most crew treated (Medical)
  - "Gatekeeper" — most intruders stopped (Security)
  - "Voice of Reason" — most successful hails (Comms)
  - "Quick Fix" — fastest breach repair (Damage Control)
  - "Ace Pilot" — most drone flight time (Flight Ops)
  - "Ghost" — highest jamming uptime (EW)
  - "Mastermind" — most coordinated strikes executed (Tactical)
  - "Decisive Leader" — most authorisations given (Captain)
- **Key moments**: Auto-identified turning points ("Hull dropped below 50% at 12:34", "Station Alpha destroyed at 08:15", "All boarders eliminated at 15:22")

### 16.2 Captain's Replay Viewer

Accessible from the debrief screen. Plays back the entire game from the logger data.

- **Tactical map playback**: The map renders the game in real-time using logged positions, events, and state changes
- **Playback controls**: Play, pause, 1x/2x/4x/8x speed, scrub bar to jump to any moment
- **Event markers**: Events appear on the scrub bar as coloured dots (red = combat, blue = scan, yellow = mission objective, green = puzzle)
- **Per-station activity**: Optional side panel showing what each station was doing at the current playback moment
- **Exportable**: The log file can be saved and replayed later — useful for classroom review the next day

### Acceptance Criteria

- [ ] Debrief dashboard shows timeline, per-station stats, and awards
- [ ] Awards are generated from actual log data (not random)
- [ ] Key moments are identified from log events
- [ ] Replay viewer plays back the tactical map from log data
- [ ] Playback controls work (play, pause, speed, scrub)
- [ ] Per-station activity panel works during replay
- [ ] Log files can be loaded for replay from disk

---

## 17. v0.03o — SHIP BALANCING + FINAL INTEGRATION

**Purpose**: Balance all ship classes, final integration testing across all 12 roles, v0.03 gate.

### 17.1 Ship Class Balancing

Each ship class needs playtesting and parameter tuning:

- **Scout**: Can it survive a 3-player combat encounter? Is multi-tasking fun or frustrating?
- **Corvette**: Does the v0.01 experience still work? Any regression from new systems?
- **Frigate**: Are 8 roles all engaged in a standard mission? Any dead time?
- **Cruiser**: Do the specialist roles (EW, Tactical) feel useful with 9-10 players?
- **Battleship**: Is 12-player coordination chaotic-fun or chaotic-frustrating? Is any role bored?
- **Medical ship / Carrier**: Do the specialised ships create meaningfully different gameplay?

### 17.2 Full Integration Test

Run each mission type on at least two different ship classes:

- Combat missions on Scout (intense, minimal crew) and Battleship (coordinated, full crew)
- Puzzle-heavy missions on Frigate (standard) and Cruiser (with specialist support)
- Non-combat missions on Medical Ship and Corvette
- Boarding missions on Frigate (limited Security) and Battleship (full Security + DC)

### 17.3 v0.03 Gate Checklist

- [ ] All 12 roles functional and tested
- [ ] All ship classes balanced and playable at their crew ranges
- [ ] Audio system produces appropriate atmosphere across all scenarios
- [ ] Help overlays accurate for all 12 stations
- [ ] Difficulty presets produce measurably different experiences
- [ ] Multi-role works (3-player Scout game verified)
- [ ] Unified map renderer used by majority of stations
- [ ] Cross-station notifications work between all role pairs
- [ ] Training missions exist for all 12 stations
- [ ] Debrief dashboard generates meaningful stats
- [ ] Captain's replay viewer works
- [ ] Mission briefing room works
- [ ] Reconnect mid-game works reliably
- [ ] Science scan modes create meaningful decision-making
- [ ] All v0.01 and v0.02 missions still work
- [ ] All tests pass
- [ ] Performance acceptable with 12 simultaneous clients on LAN

---

## 18. ESTIMATED SCOPE

| Sub-Release | Estimated Sessions | Notes |
|-------------|-------------------|-------|
| v0.03a Audio | 3-4 | Procedural audio is fiddly to tune |
| v0.03b QoL fixes | 2-3 | Reconnect, help, difficulty — each is small |
| v0.03c Map renderer | 5-6 | Shared infrastructure + migration of 5+ stations |
| v0.03d Notifications | 2-3 | Straightforward messaging system |
| v0.03e Ship framework | 4-5 | JSON schema + lobby + 7 ship definitions |
| v0.03f Multi-role | 4-5 | Tab/split UI is the complexity |
| v0.03g Briefing room | 2-3 | Leverages MapRenderer |
| v0.03h Science scan modes | 4-5 | Per SCOPE_v002.md Section 14 |
| v0.03i Damage Control | 5-6 | New station with interior rendering |
| v0.03j Flight Ops | 5-6 | New entity types (drones/probes/shuttles) |
| v0.03k Electronic Warfare | 5-6 | Jamming mechanics + intrusion puzzle |
| v0.03l Tactical Officer | 4-5 | Annotation system + strike coordination |
| v0.03m Training missions | 6-8 | 12 missions, each is small but there are many |
| v0.03n Debrief + Replay | 4-5 | Log parsing + map playback |
| v0.03o Balancing + Gate | 4-5 | Playtesting-heavy |

**Total: ~60-75 sessions.** This is the largest version — it's adding 4 roles, a ship framework, and comprehensive QoL. Roughly half the sessions are QoL/infrastructure (a-g, m-o) and half are new roles (h-l).

---

## 19. WHAT v0.03 ENABLES

After v0.03, Starbridge supports:
- **12 simultaneous players** with distinct, engaging roles
- **Scalable crew sizes** from 3 (Scout) to 12 (Battleship) via ship classes and combined roles
- **Classroom deployment** with training missions, help overlays, difficulty presets, and post-game review tools
- **Polished audio-visual experience** that feels like a finished product, not a tech demo
- **Mission authoring** without code changes — ship classes, missions, and difficulty are all data-driven

The remaining gap for a "1.0" release would be: networked play beyond LAN (WebRTC or relay server), persistent player profiles (stats across sessions), a mission editor UI, and community mission sharing. Those are v0.04 concerns.

---

*Document version: v0.03-scope-1.0*
*Last updated: 2026-02-19*
*Status: DRAFT — Begin implementation after v0.02 gate passes*
