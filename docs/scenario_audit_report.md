# Scenario System Audit Report

**Date:** 2026-03-04
**Baseline:** 6724 tests passing (post-fix)
**Scope:** Full audit of mission/scenario designer system + all 38 mission files + sandbox mode

---

## Part 1: Scenario Designer System

### 1.1 File Map

#### Server
| File | Purpose |
|------|---------|
| `server/mission_graph.py` | Primary mission engine — DAG with parallel/branch/conditional/checkpoint nodes; 27 trigger types; compound triggers (all_of/any_of/none_of) |
| `server/missions/engine.py` | Legacy sequential mission engine (MissionEngine); still imported by some test helpers |
| `server/missions/loader.py` | Loads mission JSON from `missions/` dir; synthetic sandbox dict; `spawn_from_mission()` entity spawner |
| `server/missions/__init__.py` | Package init |
| `server/mission_validator.py` | Structural validator — `validate_mission(dict)` returns error list; checks nodes/edges/reachability |
| `server/game_loop_mission.py` | Mission sub-module — owns MissionGraph instance; signal triangulation; per-tick mission evaluation |
| `server/game_loop_sandbox.py` | Sandbox activity generator — 14 event timers; `setup_world()` seeds sandbox entities |
| `server/game_loop_dynamic_missions.py` | Dynamic mission lifecycle — comms-sourced missions; offer/accept/decline/complete/fail state machine |
| `server/models/mission.py` | Pydantic schema reference for mission JSON (authoring-time validation, not runtime) |
| `server/models/dynamic_mission.py` | Dataclasses for dynamically generated missions — 8 mission types, 9 objective types |
| `server/game_debrief.py` | Post-mission debrief computation |

#### Client (Mission Editor)
| File | Purpose |
|------|---------|
| `client/editor/index.html` | Editor HTML — toolbar (NEW/OPEN/SAVE/VALIDATE/EXPORT/TEST), meta fields, canvas, property panel |
| `client/editor/editor.js` | Main orchestrator — manages editor state, toolbar actions, REST API calls |
| `client/editor/graph_renderer.js` | Canvas DAG renderer — nodes/edges, pan/zoom/drag/drop/double-click |
| `client/editor/node_panel.js` | Right panel — node type/text/trigger editing, parallel completion, checkpoint flags |
| `client/editor/edge_panel.js` | Right panel — edge type, trigger builder for branches, on_complete action builder |
| `client/editor/trigger_builder.js` | Dropdown trigger JSON builder — 15 trigger types + compound nesting |
| `client/editor/entity_placer.js` | Star-chart canvas modal — 100k×100k world; click-to-place entities |
| `client/editor/validator.js` | Client validator UI — POSTs to `/editor/validate` |
| `client/editor/exporter.js` | Mission JSON assembler + download |
| `client/editor/editor.css` | Editor stylesheet |

#### Server REST Endpoints (Mission Editor)
| Endpoint | Purpose |
|----------|---------|
| `GET /editor` | Redirect to `/client/editor/` |
| `GET /editor/missions` | List all mission JSON files |
| `GET /editor/mission/{id}` | Load mission by ID (404/422 on error) |
| `POST /editor/validate` | Validate mission structure → `{valid, errors}` |
| `POST /editor/save` | Save mission JSON to `missions/{id}.json` (alphanumeric ID enforced) |

#### Scenario Data Files
| Directory | Contents |
|-----------|----------|
| `missions/` | 38 JSON mission files (12 training + 26 gameplay) |

#### Tests
| File | Purpose |
|------|---------|
| `tests/test_mission_graph.py` | Unit tests for MissionGraph engine |
| `tests/test_mission_engine.py` | Legacy MissionEngine + loader tests |
| `tests/test_mission_validator.py` | validate_mission() tests |
| `tests/test_graph_missions.py` | Integration tests for 4 graph-native missions |
| `tests/test_station_assault_missions.py` | fortress.json + supply_line.json tests |
| `tests/test_creature_missions.py` | migration/the_nest/outbreak tests |
| `tests/test_story_missions.py` | Story mission structure tests |
| `tests/test_dynamic_missions.py` | Dynamic mission model + lifecycle tests |
| `tests/test_mission_integration.py` | End-to-end pipeline tests |
| `tests/test_mission_fallback_routing.py` | Unclaimed-station fallback tests |
| `tests/test_ops_mission_mgmt.py` | Operations station mission tracking tests |
| `tests/test_sandbox_activity.py` | Sandbox timer + event emission tests |
| `tests/test_sandbox_overhaul.py` | v0.05m sandbox overhaul tests |
| `tests/test_sandbox_missions.py` | Sandbox mission signal generation tests |
| `tests/test_sandbox_medical.py` | Sandbox medical injury side-effects tests |
| `tests/test_puzzle_mission.py` | Puzzle engine integration tests |
| `tests/test_drone_missions.py` | Drone mission data model tests |
| `tests/test_concurrent_events.py` | Concurrent event processing tests |
| `tests/test_integration_signals.py` | Cross-station signal-flow tests (46 tests) |

---

### 1.2 Schema Documentation

#### Mission File Schema

```
MISSION SCHEMA:
  metadata:
    id: string (REQUIRED) — alphanumeric + underscore; used as filename stem
    name: string (REQUIRED) — display title
    briefing: string (optional) — mission briefing text
    is_training: boolean (optional) — marks training missions
    target_role: string (optional) — training target station

  spawn: array (optional) — entities to spawn at mission start
    - id: string (required) — unique entity ID
      type: string (required) — "scout"|"cruiser"|"destroyer"|"station"|"enemy_station"|"creature"
      x: number (required) — world X coordinate
      y: number (required) — world Y coordinate
      creature_type: string (conditional) — required when type=="creature"
      variant: string (optional) — for enemy_station: "outpost"|"fortress"|etc.

  spawn_initial_wave: array (optional) — additional enemies (used by defend_station)
    - Same format as spawn entries (enemy types only)

  asteroids: array (optional) — asteroid field entries
    - id: string, x: number, y: number, radius: number (default 1000)

  hazards: array (optional) — hazard zone entries
    - id: string, x: number, y: number, radius: number (default 10000)
      hazard_type: string ("nebula"|"asteroid_field"|"radiation"), label: string

  signal_location: object (optional) — for signal triangulation missions
    - x: number, y: number

  nodes: array (REQUIRED for graph missions) — DAG nodes
    - id: string (required) — unique node ID
      type: string (required) — "objective"|"parallel"|"branch"|"conditional"|"checkpoint"
      text: string (required) — objective display text
      trigger: object (optional) — trigger condition (see trigger types below)
      complete_when: string|object (optional, parallel only) — "all"|"any"|{"count": N}
      children: array (optional, parallel/branch only) — nested child nodes
      on_complete: object (optional) — action to run on completion
      max_activations: integer (optional, conditional only) — max times node activates

  edges: array (REQUIRED for graph missions) — DAG edges
    - from: string (required) — source node ID
      to: string (required) — target node ID
      type: string (optional) — "sequence"|"branch_trigger"
      trigger: object (optional) — for branch_trigger edges
      on_complete: object (optional) — action on edge traversal

  start_node: string (REQUIRED for graph missions) — entry node ID
  victory_nodes: array of string (REQUIRED for graph missions) — winning node IDs
  defeat_condition: object (optional) — {"type": "player_hull_zero"} or {"type": "station_hull_below", ...}
  defeat_condition_alt: object (optional) — secondary defeat condition
```

#### Supported Trigger Types (27 types in MissionGraph._eval_trigger)

| Category | Trigger Type | Fields |
|----------|-------------|--------|
| Spatial | `player_in_area` | x, y, r |
| Entity | `scan_completed` | target (or entity_id) |
| Entity | `entity_destroyed` | target (or entity_id) |
| Entity | `all_enemies_destroyed` | — |
| Hull | `player_hull_zero` / `ship_hull_zero` | — |
| Hull | `ship_hull_below` | value (%) |
| Hull | `ship_hull_above` | value (%) |
| Timer | `timer_elapsed` | seconds |
| Wave | `wave_defeated` | prefix (or enemy_prefix) |
| Station | `station_hull_below` | station_id, threshold |
| Station | `station_destroyed` | station_id |
| Station | `station_captured` | station_id |
| Station | `component_destroyed` | component_id |
| Station | `station_sensor_jammed` | station_id |
| Station | `station_reinforcements_called` | station_id |
| Signal | `signal_located` | — |
| Proximity | `proximity_with_shields` | x, y, radius/r, min_shield, duration |
| Puzzle | `puzzle_completed` | label (or puzzle_label) |
| Puzzle | `puzzle_failed` | label (or puzzle_label) |
| Puzzle | `puzzle_resolved` | label (or puzzle_label) |
| Training | `training_flag` | flag |
| Boarding | `boarding_active` | — |
| Boarding | `no_intruders` | — |
| Creature | `creature_state` | creature_id, state |
| Creature | `creature_destroyed` | creature_id |
| Creature | `creature_study_complete` | creature_id |
| Creature | `creature_communication_complete` | creature_id |
| Creature | `no_creatures_type` | creature_type |
| Compound | `all_of` | triggers[] |
| Compound | `any_of` | triggers[] |
| Compound | `none_of` | triggers[] |

#### Supported on_complete Actions (5 types)

| Action | Fields |
|--------|--------|
| `spawn_wave` | enemies[] (type/x/y/id entries) |
| `start_puzzle` | puzzle_type, station, label, difficulty, ... |
| `deploy_squads` | count, room_id |
| `start_boarding` | intruders[] |
| `start_outbreak` | pathogen, severity |

#### Validation
- **On load:** `loader.py` does JSON parse only — no schema validation (crashes on missing keys at runtime)
- **Editor validation:** `mission_validator.py` checks required fields, node/edge refs, reachability, branch/parallel constraints, puzzle label uniqueness
- **Malformed data:** Missing JSON keys → `KeyError` at runtime; invalid JSON → `json.JSONDecodeError` caught by editor endpoint (422)

---

### 1.3 Feature Audit

#### Scenario Lifecycle

| Feature | Status | Notes |
|---------|--------|-------|
| Create new scenario from scratch | ✅ WORKS | Editor NEW button clears state |
| Save scenario to file | ✅ WORKS | POST `/editor/save` writes `missions/{id}.json` |
| Load existing scenario | ✅ WORKS | GET `/editor/mission/{id}` + client restore |
| Edit and re-save | ✅ WORKS | Editor state is mutable, save overwrites |
| Delete a scenario | ⚠️ MISSING | No delete endpoint or UI button |
| Duplicate a scenario | ⚠️ MISSING | No duplicate function — manual copy required |
| List all scenarios | ✅ WORKS | GET `/editor/missions` returns all JSON files |

#### Event System

| Feature | Status | Notes |
|---------|--------|-------|
| Time-based triggers | ✅ WORKS | `timer_elapsed` with `seconds` field |
| Condition-based triggers | ✅ WORKS | `ship_hull_below`, `ship_hull_above`, etc. |
| Event-based triggers | ✅ WORKS | `entity_destroyed`, `scan_completed`, etc. |
| Chained events | ✅ WORKS | Edge `on_complete` actions fire on traversal |
| Delayed events | 🔶 PARTIAL | Only via `timer_elapsed` — no "delay after event" trigger |
| Recurring events | ⚠️ MISSING | No repeat/loop mechanism in graph engine |
| Random events | ⚠️ MISSING | No probability field on triggers or events |
| Compound triggers | ✅ WORKS | `all_of`, `any_of`, `none_of` with nesting |

#### Entity Spawning

| Feature | Status | Notes |
|---------|--------|-------|
| Spawn enemy ships | ✅ WORKS | scout, cruiser, destroyer types supported |
| Spawn friendly contacts | ✅ WORKS | `type: "station"` with friendly faction |
| Spawn anomalies | 🔶 PARTIAL | Hazard zones (nebula, minefield, radiation) — no debris/energy signature entities |
| Spawn creatures | ✅ WORKS | `type: "creature"` with creature_type field |
| Spawn enemy stations | ✅ WORKS | `type: "enemy_station"` with variant |
| Set spawn positions | ✅ WORKS | Absolute coordinates (x, y) — no relative/bearing mode |
| Set entity behaviour | ⚠️ MISSING | No behaviour field in spawn entries (AI defaults apply) |
| Set entity properties | ⚠️ MISSING | No health/shields/loadout override in spawn entries |

#### Mission/Objective System

| Feature | Status | Notes |
|---------|--------|-------|
| Define mission objectives | ✅ WORKS | Navigate, scan, destroy, escort, defend, study all work |
| Objective sequencing | ✅ WORKS | DAG edges enforce order |
| Objective branching | ✅ WORKS | Branch nodes with trigger-based edge selection |
| Optional objectives | ⚠️ MISSING | No "optional" flag — all nodes are either on-path or unreachable |
| Time-limited objectives | 🔶 PARTIAL | Via compound trigger with `timer_elapsed` — no dedicated timeout field |
| Objective completion triggers | ✅ WORKS | `on_complete` actions on edges and nodes |
| Mission success/failure | ✅ WORKS | `victory_nodes` + `defeat_condition` |
| Mission rewards | ✅ WORKS | Dynamic missions have `MissionRewards` — graph missions use debrief |

#### Environmental Events (Scriptable)

| Feature | Status | Notes |
|---------|--------|-------|
| Script system damage | 🔶 PARTIAL | `system_damage` sandbox event exists; no mission-level scripting |
| Script fires | ⚠️ MISSING | No fire-start action in on_complete |
| Script hull breaches | ⚠️ MISSING | No breach action in on_complete |
| Script radiation events | ⚠️ MISSING | No radiation action in on_complete |
| Script boarding events | ✅ WORKS | `start_boarding` on_complete action |
| Script crew casualties | ⚠️ MISSING | No casualty action in on_complete |
| Script atmospheric events | ⚠️ MISSING | No atmosphere action in on_complete |
| Script structural damage | ⚠️ MISSING | No structural action in on_complete |

#### Communication Events

| Feature | Status | Notes |
|---------|--------|-------|
| Script incoming transmissions | 🔶 PARTIAL | Sandbox generates them; no mission-level scripting |
| Script distress signals | 🔶 PARTIAL | Sandbox generates; signal_location in mission JSON for triangulation only |
| Script diplomatic events | ⚠️ MISSING | No standing change action |
| Script mission offers | ✅ WORKS | Dynamic mission pipeline via comms signals |

#### Ship Configuration

| Feature | Status | Notes |
|---------|--------|-------|
| Set starting ship class | 🔶 PARTIAL | Set in lobby before mission start, not in mission JSON |
| Set starting position | ⚠️ MISSING | Ship always starts at default position |
| Set starting resources | ⚠️ MISSING | No resource override in mission JSON |
| Set starting system health | ⚠️ MISSING | All systems start at 100% |
| Set starting crew count | ⚠️ MISSING | No crew override in mission JSON |
| Set available stations | ⚠️ MISSING | All stations always available |

#### Sandbox Mode

| Feature | Status | Notes |
|---------|--------|-------|
| Random enemy spawning | ✅ WORKS | 60–90s interval, scout-heavy pool, MAX_ENEMIES=6 |
| Random event generation | ✅ WORKS | 14 timer-driven event types across all domains |
| Difficulty scaling | ✅ WORKS | `event_interval_multiplier` scales all timers |
| Event variety | ✅ WORKS | 14 distinct event types, 6 security incident subtypes |

---

### 1.4 UI Audit (Mission Editor)

| Feature | Status | Notes |
|---------|--------|-------|
| Access | ✅ WORKS | `GET /editor` → redirects to `/client/editor/` |
| Load without errors | ✅ WORKS | Static HTML + JS modules |
| Create events via UI | ✅ WORKS | Trigger builder with 15 types + compound nesting |
| Place entities on map | ✅ WORKS | Entity placer with 100k×100k canvas, 7 entity types |
| Set triggers and conditions | ✅ WORKS | TriggerBuilder with dropdowns and field inputs |
| Preview/test scenario | ⚠️ MISSING | No preview or dry-run button |
| Save and load | ✅ WORKS | Via REST endpoints |

#### Editor Trigger Coverage Gap

The trigger builder supports **15 trigger types**. The engine supports **30** (including aliases). Missing from editor UI:

| Missing Trigger | Used In Missions |
|-----------------|-----------------|
| `station_hull_below` | defend_station, the_convoy, outbreak, siege_breaker, long_patrol, deep_space_rescue |
| `station_destroyed` | supply_line |
| `station_captured` | fortress, siege_breaker |
| `station_sensor_jammed` | fortress, siege_breaker |
| `station_reinforcements_called` | fortress, supply_line, siege_breaker |
| `component_destroyed` | fortress, siege_breaker |
| `signal_located` | search_rescue, deep_space_rescue, first_survey |
| `proximity_with_shields` | search_rescue, salvage_run, deep_space_rescue |
| `creature_state` | the_nest, first_survey |
| `creature_destroyed` | (defined, unused) |
| `creature_study_complete` | migration, outbreak, long_patrol, deep_space_rescue, first_survey |
| `creature_communication_complete` | (defined, unused) |
| `no_creatures_type` | deep_space_rescue |
| `training_flag` | all 12 training missions |
| `none_of` | (defined, unused in missions) |

**Impact:** Authors using the editor UI cannot create missions using station assault, creature, signal, or proximity triggers — they must edit JSON directly.

#### Editor Entity Type Gap

The entity placer supports 7 types: `station`, `scout`, `cruiser`, `destroyer`, `hazard_nebula`, `hazard_minefield`, `hazard_radiation`. Missing:
- `enemy_station` (used by fortress, siege_breaker, supply_line)
- `creature` (used by migration, the_nest, outbreak, and story missions)
- `frigate`, `corvette`, `battleship` (valid enemy types)

---

### 1.5 v0.08 Compatibility Issues

#### Station Name References

| Location | Issue | Severity | Fixed? |
|----------|-------|----------|--------|
| `tests/test_integration_signals.py` lines 82,87,106,139 | BroadcastCapture routes to `"damage_control"` instead of `"hazard_control"` | HIGH | ✅ YES |
| `server/save_system.py` lines 674-675 | Backward-compat fallback reads `"tactical"` key from old saves | LOW (intentional) | No fix needed |
| `client/site/manual/index.html` lines 43,44,630,661 | HTML anchor IDs use `s-tactical` and `s-dc` (display text is correct) | LOW (cosmetic) | Deferred |
| `docs/MESSAGE_CATALOGUE.md` | Documents removed `tactical.*` message types | INFO | Deferred |
| `.ai/STATE.md` | Historical snapshot references old files | INFO | Deferred |

#### System References in Scenarios

- No mission file references old system names
- `DAMAGEABLE_SYSTEMS` in sandbox correctly lists: engines, shields, beams, torpedoes, sensors, manoeuvring, flight_deck, ecm_suite
- `point_defence` is NOT in `DAMAGEABLE_SYSTEMS` — intentional (PD should not randomly break)

#### New v0.08 System Integration Gaps

The scenario system has **no awareness** of:
- Fire system (5 intensity levels, room-based spread/suppression)
- Atmosphere system (O2, pressure, temperature, contamination per room)
- Radiation system (reactor leak, nuclear torpedo, shield leak; 4 zone tiers)
- Structural integrity (per-section states, collapse cascade, reinforcement)
- Emergency systems (bulkheads, emergency power, life pods)

**Impact:** Missions cannot script these events via `on_complete` actions. The sandbox generates zero events that directly exercise the Hazard Control station's core v0.08 workflow (fire management, breach response, atmosphere control, structural reinforcement).

#### API Compatibility

All mission system function signatures are stable. No breaking changes found in:
- `MissionGraph.__init__()`, `.tick()`, `.serialise()`/`.deserialise()`
- `loader.load_mission()`, `spawn_from_mission()`, `spawn_wave()`
- `validate_mission()`
- Dynamic mission generators

---

## Part 2: Existing Scenarios

### 2.1 Inventory

| # | File | Title | Category |
|---|------|-------|----------|
| 1 | `train_captain.json` | Captain Training | Training |
| 2 | `train_comms.json` | Comms Training | Training |
| 3 | `train_engineering.json` | Engineering Training | Training |
| 4 | `train_ew.json` | Electronic Warfare Training | Training |
| 5 | `train_flight_ops.json` | Flight Operations Training | Training |
| 6 | `train_hazard_control.json` | Hazard Control Training | Training |
| 7 | `train_helm.json` | Helm Training | Training |
| 8 | `train_medical.json` | Medical Training | Training |
| 9 | `train_operations.json` | Operations Officer Training | Training |
| 10 | `train_science.json` | Science Training | Training |
| 11 | `train_security.json` | Security Training | Training |
| 12 | `train_weapons.json` | Weapons Training | Training |
| 13 | `first_contact.json` | First Contact | Combat |
| 14 | `first_contact_remastered.json` | First Contact Remastered | Combat/Branch |
| 15 | `deep_strike.json` | Deep Strike | Combat |
| 16 | `defend_station.json` | Defend the Station | Combat/Waves |
| 17 | `boarding_action.json` | Boarding Action | Security |
| 18 | `nebula_crossing.json` | Nebula Crossing | Exploration |
| 19 | `search_rescue.json` | Search and Rescue | Exploration |
| 20 | `first_contact_protocol.json` | First Contact Protocol | Science |
| 21 | `diplomatic_summit.json` | Diplomatic Summit | Diplomacy |
| 22 | `engineering_drill.json` | Engineering Drill | Engineering |
| 23 | `plague_ship.json` | Plague Ship | Medical |
| 24 | `puzzle_poc.json` | Puzzle Framework PoC | Dev/Test |
| 25 | `salvage_run.json` | Salvage Run | Branch |
| 26 | `first_contact_remastered.json` | First Contact Remastered | Branch |
| 27 | `the_convoy.json` | The Convoy | Parallel |
| 28 | `pandemic.json` | Pandemic | Branch/Medical |
| 29 | `fortress.json` | Fortress | Station Assault |
| 30 | `supply_line.json` | Supply Line | Station Assault |
| 31 | `migration.json` | Migration | Creature |
| 32 | `the_nest.json` | The Nest | Creature |
| 33 | `outbreak.json` | Outbreak | Creature |
| 34 | `long_patrol.json` | The Long Patrol | Story |
| 35 | `deep_space_rescue.json` | Deep Space Rescue | Story |
| 36 | `siege_breaker.json` | Siege Breaker | Story |
| 37 | `first_survey.json` | First Survey | Story |
| 38 | `unnamed.json` | Unnamed Mission | Dev stub |

### 2.2 Per-Scenario Reports

#### Training Missions (12)

All 12 training missions use correct v0.08 station names (`operations`, `hazard_control`) and valid trigger types (`training_flag`, `timer_elapsed`, `player_in_area`, `scan_completed`, `all_enemies_destroyed`).

| Scenario | Schema | Station Refs | System Refs | Event Compat | Overall |
|----------|--------|-------------|-------------|--------------|---------|
| train_captain | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| train_comms | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| train_engineering | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| train_ew | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| train_flight_ops | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| train_hazard_control | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| train_helm | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| train_medical | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| train_operations | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| train_science | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| train_security | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| train_weapons | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |

#### Core Missions (8)

| Scenario | Schema | Station Refs | System Refs | Event Compat | Issues | Overall |
|----------|--------|-------------|-------------|--------------|--------|---------|
| first_contact | VALID | CLEAN | CLEAN | ALL VALID | — | ✅ READY |
| search_rescue | VALID | CLEAN | CLEAN | ALL VALID | — | ✅ READY |
| defend_station | VALID | CLEAN | CLEAN | ALL VALID | Uses legacy `enemy_prefix` key (backward-compat supported) | 🔶 MINOR |
| boarding_action | VALID | CLEAN | CLEAN | ALL VALID | Uses legacy `puzzle_label` key (backward-compat supported) | ✅ READY |
| deep_strike | VALID | CLEAN | CLEAN | ALL VALID | Uses legacy `puzzle_label` key | ✅ READY |
| nebula_crossing | VALID | CLEAN | CLEAN | ALL VALID | Uses legacy `puzzle_label` key | ✅ READY |
| plague_ship | VALID | CLEAN | CLEAN | ALL VALID | Uses legacy `puzzle_label` key | ✅ READY |
| puzzle_poc | VALID | CLEAN | CLEAN | ALL VALID | — | ✅ READY |

#### Parallel/Branch Missions (3)

| Scenario | Schema | Station Refs | System Refs | Event Compat | Overall |
|----------|--------|-------------|-------------|--------------|---------|
| engineering_drill | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| first_contact_protocol | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| diplomatic_summit | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |

#### Graph-Native Missions (4)

| Scenario | Schema | Station Refs | System Refs | Event Compat | Overall |
|----------|--------|-------------|-------------|--------------|---------|
| salvage_run | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| first_contact_remastered | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| the_convoy | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| pandemic | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |

#### Station Assault Missions (2)

| Scenario | Schema | Station Refs | System Refs | Event Compat | Overall |
|----------|--------|-------------|-------------|--------------|---------|
| fortress | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| supply_line | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |

#### Creature Missions (3)

| Scenario | Schema | Station Refs | System Refs | Event Compat | Issues | Overall |
|----------|--------|-------------|-------------|--------------|--------|---------|
| migration | VALID | CLEAN | CLEAN | ALL VALID | `complete_when: {"all": true}` fixed → `"all"` | ✅ READY (fixed) |
| the_nest | VALID | CLEAN | CLEAN | ALL VALID | — | ✅ READY |
| outbreak | VALID | CLEAN | CLEAN | ALL VALID | — | ✅ READY |

#### Story Missions (4)

| Scenario | Schema | Station Refs | System Refs | Event Compat | Overall |
|----------|--------|-------------|-------------|--------------|---------|
| long_patrol | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| deep_space_rescue | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| siege_breaker | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |
| first_survey | VALID | CLEAN | CLEAN | ALL VALID | ✅ READY |

#### Miscellaneous

| Scenario | Schema | Station Refs | System Refs | Event Compat | Issues | Overall |
|----------|--------|-------------|-------------|--------------|--------|---------|
| unnamed | VALID (minimal) | CLEAN | CLEAN | ALL VALID | No defeat_condition, stub content | 🔶 DEV STUB |

---

### 2.3 Sandbox Mode Audit

#### Event Rates

| Timer | Interval (steady state) | Initial Timer | Primary Station |
|-------|------------------------|---------------|-----------------|
| `enemy_spawn` | 60–90s | 30–60s | Weapons, Helm, Science, EW, Flight Ops |
| `system_damage` | 45–75s | 30–50s | Engineering |
| `crew_casualty` | 60–100s | 45–75s | Medical |
| `boarding` | 75–120s | 90–120s | Security |
| `security_event` | 30–60s | 20–40s | Security |
| `env_sickness` | 90–120s | 60–90s | Medical |
| `incoming_transmission` | 90–120s | 45–75s | Comms |
| `hull_micro_damage` | 120–180s | 60–90s | (global hull hit) |
| `sensor_anomaly` | 90–150s | 45–75s | Science |
| `drone_opportunity` | 120–180s | 60–90s | Flight Ops |
| `enemy_jamming` | 180–240s | 60–90s | EW |
| `creature_spawn` | 240–360s | 120–180s | Science, EW, Weapons |
| `mission_signal` | 90–180s | 60–90s | Comms |
| `distress_signal` | 180–300s | 90–120s | Comms, Helm, Captain |

#### Per-Station Event Rates (estimated, per 10 minutes, Officer difficulty)

| Station | Direct Events | Avg Interval | Est. Count/10min | Target (1/60-90s) | Status |
|---------|--------------|-------------|-------------------|-------------------|--------|
| Captain | distress_signal | 180–300s | ~3 | 7–10 | ❌ LOW |
| Helm | enemy_spawn + distress | 60–90s + 180–300s | ~8–10 | 7–10 | ✅ OK |
| Weapons | enemy_spawn | 60–90s | ~7–10 | 7–10 | ✅ OK |
| Engineering | system_damage | 45–75s | ~8–13 | 7–10 | ✅ OK |
| Science | sensor_anomaly + creature | 90–150s + 240–360s | ~5–7 | 7–10 | 🔶 BORDERLINE |
| Medical | crew_casualty + env_sickness + side-effects | ~60–100s combined | ~6–8 | 7–10 | 🔶 BORDERLINE |
| Security | boarding + security_event | 30–60s + 75–120s | ~13–20 | 7–10 | ✅ OK (high) |
| Comms | transmission + distress + mission_signal | 90–120s + others | ~6–8 | 7–10 | ✅ OK |
| EW | enemy_jamming | 180–240s | ~2–3 | 7–10 | ❌ LOW |
| Flight Ops | drone_opportunity | 120–180s | ~3–5 | 7–10 | ❌ LOW |
| Operations | (no dedicated events) | — | ~0 | 7–10 | ❌ NONE |
| Hazard Control | (no dedicated events) | — | ~0 | 7–10 | ❌ NONE |
| Quartermaster | (no dedicated events) | — | ~0 | 7–10 | ❌ NONE |

#### Sandbox Checklist

| Check | Status | Notes |
|-------|--------|-------|
| Stale station name references | ✅ CLEAN | No `"tactical"` or `"damage_control"` role strings |
| Uses v0.08 fire system | ❌ NO | No fire spawning events |
| Uses v0.08 atmosphere system | 🔶 PARTIAL | `env_sickness` reads atmosphere penalties but doesn't create atmosphere events |
| Uses v0.08 radiation system | ❌ NO | No radiation events |
| Uses v0.08 structural integrity | ❌ NO | No structural events |
| Generates Hazard Control events | ❌ NO | HC has zero dedicated sandbox events |
| Generates Operations events | ❌ NO | Ops has zero dedicated sandbox events |
| Generates Medical events (sufficient) | 🔶 LOW | Side-effect injuries (20%/10%/30% chance) are unreliable |
| Generates Quartermaster events | ❌ NO | No resource/trade events |
| `event_overlap_max` enforced | ❌ NO | Field exists in DifficultyPreset but is never read by sandbox |
| Difficulty scaling | ✅ WORKS | `event_interval_multiplier` and `boarding_frequency_multiplier` |

---

## Summary

### Issues Found: 12

| # | Severity | Issue | Status |
|---|----------|-------|--------|
| 1 | HIGH | `test_integration_signals.py` BroadcastCapture routes to `"damage_control"` instead of `"hazard_control"` (4 locations) | ✅ FIXED |
| 2 | MEDIUM | `migration.json` `complete_when: {"all": true}` wrong format (should be string `"all"`) | ✅ FIXED |
| 3 | MEDIUM | `test_creature_missions.py` asserts old dict format for `complete_when` | ✅ FIXED |
| 4 | LOW | `defend_station.json` uses legacy `enemy_prefix` key (engine supports via fallback) | Not fixed (harmless) |
| 5 | LOW | 8 missions use legacy `puzzle_label` key (engine supports via fallback) | Not fixed (harmless) |
| 6 | LOW | `client/site/manual/index.html` stale HTML anchor IDs `s-tactical` / `s-dc` | Not fixed (cosmetic) |
| 7 | INFO | `unnamed.json` is a dev stub with no defeat condition | Not fixed (test-only) |
| 8 | DESIGN | Editor trigger builder missing 15 trigger types (station/creature/signal/proximity) | Needs enhancement |
| 9 | DESIGN | Editor entity placer missing 5 entity types (enemy_station, creature, frigate, corvette, battleship) | Needs enhancement |
| 10 | DESIGN | Sandbox generates zero events for Hazard Control, Operations, Quartermaster stations | Needs new event types |
| 11 | DESIGN | Sandbox has no v0.08 fire/atmosphere/radiation/structural events | Needs new event types |
| 12 | DESIGN | `event_overlap_max` DifficultyPreset field is unused | Dead code or needs implementation |

### Fixed In-Place: 3
- `tests/test_integration_signals.py` — 4 `"damage_control"` → `"hazard_control"` replacements
- `missions/migration.json` — `complete_when: {"all": true}` → `"all"`
- `tests/test_creature_missions.py` — assertion updated to match fixed schema

### Needs Manual Fix: 0
### Deferred (Cosmetic/Harmless): 4

### Scenarios Ready: 37 / 38
### Scenarios with Minor Issues: 1 (defend_station — legacy key, functional)
### Scenarios Broken: 0

---

## Recommended Fixes (Prioritised)

### Priority 1: Sandbox Engagement Gaps (Stations with Zero Events)

1. **Add Hazard Control sandbox events** — New event types:
   - `start_fire` — room-based fire at intensity 1-2 (every 60–90s)
   - `hull_breach` — room-based breach creating atmosphere bleedout (every 120–180s)
   - `radiation_event` — reactor micro-leak or sensor shield fluctuation (every 180–240s)
   - `structural_stress` — random section stress from micrometeorite impacts (every 120–180s)

2. **Add Operations sandbox events** — New event types:
   - `priority_target_suggestion` — mark a contact for priority engagement (on enemy spawn)
   - `scan_request` — request detailed scan of a contact (every 90–120s)
   - `intel_assessment` — generate assessment data for ops to distribute (every 120s)

3. **Add Quartermaster sandbox events** — New event types:
   - `resource_alert` — low fuel/ammo/suppressant warnings (every 120–180s)
   - `trade_opportunity` — NPC offering resource exchange (every 180–240s)

### Priority 2: Editor Completeness

4. **Add missing trigger types to trigger_builder.js** — 15 types needed (station_*, creature_*, signal_located, proximity_with_shields, training_flag, none_of)

5. **Add missing entity types to entity_placer.js** — enemy_station, creature, frigate, corvette, battleship

6. **Add delete/duplicate endpoints** — `DELETE /editor/mission/{id}` and `POST /editor/duplicate/{id}`

### Priority 3: Cleanup

7. **Normalise legacy keys in mission files** — Update `enemy_prefix` → `prefix` in defend_station.json; `puzzle_label` → `label` in 8 files

8. **Update manual HTML anchors** — `s-tactical` → `s-operations`, `s-dc` → `s-hazard-control`

9. **Implement or remove `event_overlap_max`** — Either enforce it in sandbox tick or remove from DifficultyPreset

### Priority 4: Scenario System Enhancements

10. **Add v0.08 on_complete actions** — `start_fire`, `create_breach`, `apply_radiation`, `structural_damage`, `contaminate_atmosphere`

11. **Add scenario preview/dry-run** — Editor button to load mission in headless mode and step through timed events

12. **Add entity property overrides** — Allow spawn entries to set initial health, shields, behaviour mode
