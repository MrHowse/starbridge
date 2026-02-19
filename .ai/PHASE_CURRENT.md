# Current Phase: Phase 7 — Polish, Viewscreen + Remaining Missions

> Replace this file's contents when moving to a new phase.

## Goal

v0.01 becomes a complete, cohesive experience. Five deliverables:
1. **Viewscreen** — shared-screen forward display for group play; the showpiece
2. **Mission 2 "Defend the Station"** — wave survival, station entity, resupply
3. **Mission 3 "Search and Rescue"** — triangulation, asteroid field, shield extension, escort
4. **Visual polish** — torpedo trails, beam lines, shield impacts, hit flash consistency
5. **Game flow** — lobby→brief→play→debrief→lobby; disconnect/reconnect; tablet layouts

---

## Phase 6 Baseline (what exists)

- **301 pytest tests passing**
- Captain station: tactical map, ship status, science summary, objectives, alert level
- Mission engine: `MissionEngine(dict)`, 5 trigger types, sequential objectives, victory/defeat
- Mission loader: `load_mission(id)`, `spawn_from_mission()`
- `missions/first_contact.json`: 4-objective tutorial mission
- All 5 stations handle `ship.alert_changed`
- Lobby: mission select (Sandbox / First Contact)
- game_loop.py: mission engine integrated, broadcasts `mission.objective_update`

---

## Sub-Task Architecture

---

### 7a: Viewscreen Client

**Goal**: A display-only forward view for a shared screen/TV. Wire aesthetic at its best.

**No new server messages needed** — viewscreen gets `world.entities` (add to broadcast_to_roles)
and already-broadcast messages: `ship.state`, `world.entities`, `weapons.beam_fired`,
`weapons.torpedo_hit`, `weapons.torpedo_fired`, `ship.hull_hit`.

**`client/viewscreen/index.html`** — Full replacement:
- `<canvas id="viewscreen-canvas">` filling the entire viewport
- No controls, no panels — pure display
- Optional: small HUD overlay (mission name, hull bar, alert level)

**`client/viewscreen/viewscreen.js`** — Full replacement:
- Auto-connect, no role claim (observer)
- `on('game.started', ...)` → init canvas, start rAF loop
- `on('ship.state', ...)` → store position, heading, velocity for camera
- `on('world.entities', ...)` → store enemies and torpedoes
- `on('weapons.beam_fired', ...)` → add beam flash to render queue
- `on('weapons.torpedo_fired', ...)` → track torpedo trail state
- `on('weapons.torpedo_hit', ...)` → add explosion effect
- `on('ship.hull_hit', ...)` → screen flash
- `on('ship.alert_changed', ...)` → setAlertLevel
- `on('game.over', ...)` → overlay
- **Render loop**: forward view (ship heading = up/forward)
  - Stars: `drawStarfield` (existing, heading-adjusted parallax)
  - Grid: removed (forward view has no fixed grid)
  - Enemies: wireframe shapes, range-scaled, port/starboard position
  - Torpedoes: bright dot + 5-point trail (fade with distance)
  - Beam flash: bright line SOURCE→TARGET, fades over 200ms
  - Explosion: expanding wireframe circle (3 rings expanding, fading)
  - Shield hit: arc flash at impact point on ship outline
  - HUD strip: mission name, heading, hull bar, alert colour

**`server/game_loop.py`** — add `"viewscreen"` to world.entities broadcast_to_roles:
```python
await _manager.broadcast_to_roles(
    ["helm", "engineering", "captain", "viewscreen"],
    _build_world_entities(_world),
)
```
Viewscreen gets full unfiltered data (it's a spectator display, no information asymmetry).

**Visual effects (Viewscreen-specific)**:
- Torpedo trails: keep last N positions per torpedo ID in a ring buffer
- Beam flash: store `{fromX, fromY, toX, toY, startTime}` in flash list, render for 200ms
- Explosion: store `{x, y, startTime, maxRadius}` list, expand ring for 400ms then fade
- Shield shimmer: arc segment on ship outline, bright flash for 300ms

**No new server tests needed** — the viewscreen is purely a client addition.

---

### 7b: Mission 2 — "Defend the Station"

**Goal**: Wave survival. Players protect a friendly starbase. Resupply between waves.

#### New engine features needed

**`timer_elapsed` trigger** — fires N seconds after mission start:
```python
if trigger == "timer_elapsed":
    return self._elapsed >= args["seconds"]
```
Engine must track `self._elapsed` (incremented by `dt` each tick called with dt).
`tick(world, ship, dt: float)` signature change (add dt parameter).

**`station_hull_below` trigger** — station health below threshold:
```python
if trigger == "station_hull_below":
    station = world.get_station(args["station_id"])
    return station is not None and station.hull < args["threshold"]
```

**`wave_defeated` trigger** — all enemies with IDs matching a prefix destroyed:
```python
if trigger == "wave_defeated":
    prefix = args["enemy_prefix"]
    return not any(e.id.startswith(prefix) for e in world.enemies)
```

**New action type: `spawn_wave`** — spawn a group of enemies mid-mission.
The current engine only checks triggers → marks objectives complete. It needs to also support
**side effects** on trigger: spawn enemies, repair ship/station, etc.

Design: add `on_complete` field to objective:
```json
{ "id": "wave_2_start", "text": "...", "trigger": "wave_defeated",
  "args": { "enemy_prefix": "w1_" },
  "on_complete": { "action": "spawn_wave", "enemies": [...], "repair": 20 } }
```
`MissionEngine.tick()` returns list of `(objective_id, on_complete_dict)` tuples for newly-completed
objectives; game_loop handles the on_complete actions (spawn enemies, heal ship/station).

#### New entity: Station

**`server/models/world.py`** — add `Station` dataclass:
```python
@dataclass
class Station:
    id: str
    x: float
    y: float
    hull: float = 200.0
    hull_max: float = 200.0
```
`World.stations: list[Station] = field(default_factory=list)`

Station has no AI. Takes damage from enemy beam hits (enemies target nearest: player OR station).

**`_build_world_entities()`** — include stations in payload.

**AI change**: enemies attack whichever target (player or station) is closer. New `attack_target`
decision per-tick in `tick_enemies()`.

**Resupply mechanic**: When ship is within `DOCK_RANGE = 1500` of a station for `DOCK_TIME = 3s`,
auto-resupply fires:
- `ship.hull` += 20 (capped at 100)
- `_torpedo_ammo` += 5 (capped at 10)
- broadcasts `ship.resupplied { hull, torpedo_ammo }` to all
- docking only works between waves (game_loop tracks wave state via mission engine)

Docking timer tracked in game_loop module state.

#### `missions/defend_station.json`

```json
{
  "id": "defend_station",
  "name": "Defend the Station",
  "briefing": "Starbase Kepler is under attack. Defend it through three waves. Resupply between engagements.",
  "spawn": [
    { "type": "station", "x": 50000, "y": 35000, "id": "kepler" }
  ],
  "objectives": [
    { "id": "wave_1", "text": "Repel first attack wave",
      "trigger": "wave_defeated", "args": { "enemy_prefix": "w1_" },
      "on_complete": { "action": "spawn_wave",
        "enemies": [
          { "type": "cruiser", "x": 20000, "y": 50000, "id": "w2_1" },
          { "type": "cruiser", "x": 80000, "y": 50000, "id": "w2_2" }
        ]
      }
    },
    { "id": "wave_2", "text": "Repel second attack wave",
      "trigger": "wave_defeated", "args": { "enemy_prefix": "w2_" },
      "on_complete": { "action": "spawn_wave",
        "enemies": [
          { "type": "destroyer", "x": 50000, "y": 90000, "id": "w3_1" },
          { "type": "scout",     "x": 30000, "y": 80000, "id": "w3_2" },
          { "type": "scout",     "x": 70000, "y": 80000, "id": "w3_3" }
        ]
      }
    },
    { "id": "wave_3", "text": "Repel final assault",
      "trigger": "wave_defeated", "args": { "enemy_prefix": "w3_" } }
  ],
  "spawn_initial_wave": [
    { "type": "scout", "x": 20000, "y": 20000, "id": "w1_1" },
    { "type": "scout", "x": 80000, "y": 20000, "id": "w1_2" },
    { "type": "scout", "x": 50000, "y": 10000, "id": "w1_3" }
  ],
  "victory_condition": "all_objectives_complete",
  "defeat_condition": "player_hull_zero",
  "defeat_condition_alt": { "trigger": "station_hull_below",
    "args": { "station_id": "kepler", "threshold": 0 } }
}
```

**Lobby**: add DEFEND THE STATION option to mission select.

**Test count estimate**: +20 tests → ~321

---

### 7c: Mission 3 — "Search and Rescue"

**Goal**: Non-combat proof point. Every role has a meaningful task. No killing required.

#### Triangulation mechanic (Science)

Science triangulates a distress signal by scanning from different positions. The server computes
a **bearing** from the ship's current position toward the signal source (a hidden world point).
Science sees the bearing; Helm drives to a new position; Science scans again. Two bearings from
different positions geometrically intersect at the signal source. On the third scan the game
reveals the location.

Implementation:
- Signal source is a hidden `(sx, sy)` world point stored in the mission engine
- When Science scans the `"signal"` entity (a special pseudo-entity), the server returns
  `{ bearing_to_signal: float }` — computed server-side from ship position
- Mission engine tracks `triangulation_count: int`; after 2 scans from positions ≥ 8000 units
  apart, trigger `signal_located` fires → reveals actual position as a waypoint marker
- New trigger type: `signal_located` — `triangulation_count >= 2 AND positions_apart >= 8000`

Science client shows the "SIGNAL" pseudo-contact as a special ? marker; after each scan it draws
a bearing line on the sensor canvas; after 2 scans a small diamond marker appears at the
intersection.

#### Asteroid field (Helm)

**`server/models/world.py`** — add `Asteroid` dataclass:
```python
@dataclass
class Asteroid:
    id: str
    x: float
    y: float
    radius: float       # collision radius (500–2000)
    heading: float = 0  # slow drift heading
    velocity: float = 0 # very slow drift (0-10 units/sec)
```
`World.asteroids: list[Asteroid] = field(default_factory=list)`

Asteroid field spawned in the JSON. Physics system: if ship within `asteroid.radius`, ship.hull
takes 2 HP/tick. Helm must navigate through gaps.

Asteroids rendered on Helm viewscreen (wireframe irregular polygon) and minimap.
Rendered on Viewscreen canvas as irregular polygons.

#### Shield extension mechanic (Engineering)

The damaged vessel entity (`rescue_target`) has a proximity trigger: if ship is within 2000 units
AND `ship.shields.front >= 80 AND ship.shields.rear >= 80` for 10 consecutive seconds, the
`shields_extended` objective completes.

This is a data-driven trigger:
```python
if trigger == "proximity_with_shields":
    dist = distance(ship.x, ship.y, args["x"], args["y"])
    min_shield = min(ship.shields.front, ship.shields.rear)
    if dist < args["radius"] and min_shield >= args["min_shield"]:
        self._proximity_timer += dt
    else:
        self._proximity_timer = 0
    return self._proximity_timer >= args["duration"]
```

Engineering UI addition: show the "SHIELDS EXTENDED" status when condition is met.

#### Escort trigger

After shields extended, escort the rescue target to safety (player_in_area at starbase, target
follows player automatically once "escorted" state is set).

#### `missions/search_rescue.json`

```json
{
  "id": "search_rescue",
  "name": "Search and Rescue",
  "briefing": "Distress beacon detected. Triangulate, navigate the field, extend shields, and bring them home.",
  "signal_location": { "x": 72000, "y": 68000 },
  "spawn": [
    { "type": "station",      "x": 50000, "y": 50000, "id": "base"   },
    { "type": "rescue_target","x": 72000, "y": 68000, "id": "target" }
  ],
  "asteroids": [
    { "x": 60000, "y": 57000, "radius": 1800 },
    { "x": 65000, "y": 62000, "radius": 1200 },
    ...
  ],
  "objectives": [
    { "id": "triangulate", "text": "Triangulate the distress signal",
      "trigger": "signal_located" },
    { "id": "navigate", "text": "Navigate to the rescue target",
      "trigger": "player_in_area", "args": { "x": 72000, "y": 68000, "r": 3000 } },
    { "id": "extend_shields", "text": "Extend shields around the damaged vessel (shields ≥80%, hold 10s)",
      "trigger": "proximity_with_shields",
      "args": { "x": 72000, "y": 68000, "radius": 2000, "min_shield": 80, "duration": 10 } },
    { "id": "escort", "text": "Escort to sector base",
      "trigger": "player_in_area", "args": { "x": 50000, "y": 50000, "r": 5000 } }
  ],
  "victory_condition": "all_objectives_complete",
  "defeat_condition": "player_hull_zero"
}
```

**Test count estimate**: +20 tests → ~341

---

### 7d: Visual Polish

**Torpedo trails** — in all canvas renderers (Viewscreen, Weapons, Captain):
- Client maintains `torpedoTrails: Map<id, {x, y}[]>` — append position each render frame
- Trail: 5 dots from current position backward, each 30% dimmer
- Clear trail on torpedo removal

**Beam firing lines** — already partially in weapons.js; make consistent:
- `weapons.beam_fired` received → store `{x1,y1,x2,y2,t}` per beam
- Render: full-bright line at t=0, fade over 200ms (opacity = 1 - elapsed/200)
- All canvas displays (Viewscreen, Weapons, Captain) show beam flashes

**Shield impact arcs** — on `ship.hull_hit`:
- Compute impact arc: if attacker is in front hemisphere → arc on forward edge, else rear
- Render: bright arc segment (90°), fade over 300ms
- Implemented in Viewscreen (most visible) and Weapons (gives feedback)

**Explosion effects** — on `weapons.torpedo_hit` / enemy destroyed:
- 3 wireframe circles expanding from impact point: radii 100→800, 200→1200, 300→1600
- All expand over 400ms and fade simultaneously
- Implemented in Viewscreen and Weapons

**Hit flash consistency** — all 5 station HTML pages already have `.station-container.hit` CSS
class + hit-flash animation in theme.css. Verify weapons.js, helm.js, engineering.js,
science.js, captain.js all add the class on `ship.hull_hit`.

**Smooth gauge animations** — ensure all CSS gauge fills use `transition: width 0.15s linear`
(verify across all stations — engineering has it, confirm others).

**Scanline refinement** — check `body::after` scanline overlay is consistent and not too heavy
on canvas-heavy stations.

---

### 7e: Game Flow Polish

#### Briefing screen

After `game.started`, all stations show a **briefing overlay** before the game is interactive:
- Overlay covers station UI with mission name + briefing text
- Auto-dismisses after 8 seconds OR on click
- Helm, Engineering, Weapons, Science show generic briefing
- Captain shows briefing + mission objectives list

Server adds `objectives` array to `game.started` payload:
```python
# game_loop.start() / lobby._start_game():
game_payload["objectives"] = [
    {"id": o.id, "text": o.text, "status": o.status}
    for o in _mission_engine.get_objectives()
]
```
Requires `_mission_engine` available at game start, which it is.

#### Debrief / victory-defeat screen

Current `game.over` overlay on stations is minimal. Expand `game.over` payload:
```python
"stats": {
    "duration_ticks": _tick_count,
    "duration_seconds": round(_tick_count / TICK_RATE),
    "objectives_completed": sum(1 for o in _mission_engine.get_objectives() if o.status == "complete"),
    "objectives_total": len(_mission_engine.get_objectives()),
    "hull_remaining": round(_world.ship.hull, 1),
}
```
Each station's game.over handler renders a richer overlay:
- VICTORY: mission name, time taken, "X/Y objectives complete", hull remaining
- DEFEAT: "SHIP DESTROYED", time survived
- "RETURN TO LOBBY" button → `window.location = '/client/lobby/'`

#### Disconnect/reconnect handling

Current state: reconnecting client gets a new connection_id and receives the current lobby.state,
but if a game is running they get no game state. Session storage preserves `player_name`.

Additions needed:
1. **`lobby.py`**: track `_game_payload` (set when game.started fires). On new connection
   during an active game, send `game.started` to that connection immediately after welcome.
2. **`game_loop.py`**: expose a `is_running() → bool` function. `lobby.on_connect()` uses this
   to decide whether to replay `game.started`.
3. **Station JS**: `on('game.started', ...)` must be idempotent — safe to call twice.
   Currently most stations check `if gameActive return;` before initialising, which handles this.
4. **Role reclaim on reconnect**: already implemented (sessionStorage player_name → claim_role
   on welcome). Verify it works when game is already running.
5. **`mission.objective_update`** on reconnect: when a new captain/observer connects during a game,
   send current objective state. Expose `get_current_objectives()` from game_loop.

#### Tablet-responsive check

All stations need to remain usable at 768px width. Key risk points:
- Weapons: 2-column grid collapses poorly — add `@media (max-width: 900px)` breakpoint
- Science: similar 2-column issue
- Engineering: power sliders may need larger touch targets on tablet
- Lobby: 5-column role grid collapses → already has media queries, verify

---

## Message Protocol Additions (Phase 7)

### Server → Client
```
ship.resupplied         { hull: float, torpedo_ammo: int }   (Mission 2 docking)
mission.signal_bearing  { bearing: float, scan_count: int }  (Mission 3 triangulation)
```

### game.started payload extension
```
game.started {
  mission_id, mission_name, briefing_text,
  objectives: [{ id, text, status }]       ← NEW Phase 7
}
```

### game.over payload extension
```
game.over {
  result: "victory" | "defeat",
  stats: {
    duration_seconds: int,
    objectives_completed: int,
    objectives_total: int,
    hull_remaining: float
  }
}
```

---

## New Pydantic Schemas

```python
# No new client→server messages needed for 7a/7d/7e.
# 7b/7c may need:
# (none — ship.resupplied is server-only; triangulation is internal)
```

---

## Acceptance Criteria (Phase Gate)

- [ ] Viewscreen renders forward view with wire-aesthetic effects on shared screen
- [ ] Torpedo trails visible on Viewscreen and Weapons radar
- [ ] Beam lines visible on all canvas displays (Viewscreen, Weapons, Captain)
- [ ] Shield impact arcs visible on Viewscreen
- [ ] Explosion wireframe visible on torpedo/enemy destruction
- [ ] Mission 2 "Defend the Station": three waves, station health bar, resupply mechanic works
- [ ] Mission 2 defeat condition: station hull → 0 = mission failed
- [ ] Mission 3 "Search and Rescue": Science triangulates signal (2 scans from different positions)
- [ ] Mission 3: Asteroid field visible and causes hull damage on contact
- [ ] Mission 3: Shield extension objective completable by Engineering
- [ ] All 3 missions appear in lobby mission select
- [ ] Briefing overlay shown on all stations after game.started (auto-dismiss 8s or click)
- [ ] Debrief screen shows stats: time, objectives, hull remaining
- [ ] Reconnecting player can re-claim role mid-mission and see current game state
- [ ] Stations work at 768px width (tablet)
- [ ] All tests pass (target: ~340 tests)

---

## Design Questions Requiring Decisions

1. **Triangulation UX on Science client**: bearing-line overlay on sensor canvas, or numerical
   readout in a panel? (bearing line is more dramatic but harder to act on)

2. **Asteroid collision**: hull damage only, or also velocity reduction / heading interference?

3. **Enemies attack station in Mission 2**: do enemies ignore the player and go straight for the
   station, or alternate targets? (Station-only gives clearer mission feel; alternating is more
   tactical)

4. **Rescue target behaviour post-shields**: does the rescued vessel auto-follow the player to
   base, or is "escort" purely cosmetic (player returns to base and objective completes)?

5. **Briefing auto-dismiss vs. click**: 8-second auto for the shared viewscreen experience, or
   require each player to click ready (adds coordination but feels more deliberate)?

6. **Stats tracking location**: game_loop module state (simple) or a dedicated StatsTracker
   dataclass (cleaner, easier to test)?
