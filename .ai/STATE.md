# Project State

> **LIVING DOCUMENT** — Update after every AI engineering session.
> This is the single source of truth for what exists in the project.

**Last updated**: 2026-02-20 (v0.04c COMPLETE — new graph-native missions)
**Current phase**: v0.04c COMPLETE ✓
**Overall status**: 1781 tests passing. 11 active player roles + viewscreen (passive) = 12 stations.
27 JSON missions (15 story + 12 training) + sandbox (synthetic) — all in graph format. 9 puzzle types.
7 ship classes (5 combat + 2 specialised). 4 difficulty presets.
Game event logger (JSONL) + Debrief Dashboard + Captain's Replay.
MissionGraph engine (parallel/branch/conditional nodes) — all missions use graph format.
Bug fix: MissionGraph.tick() now returns parallel parent IDs when they complete.

---

## What Exists

### Project Infrastructure
- Complete directory structure per scope document
- `.ai/` management files (SYSTEM_PROMPT, CONVENTIONS, STATE, DECISIONS, LESSONS, PHASE_CURRENT)
- `docs/` reference files (MESSAGE_PROTOCOL, MISSION_FORMAT, STYLE_GUIDE, SCOPE)
- `requirements.txt` with all dependencies
- `run.py` entry point — starts uvicorn, prints LAN connection URL
- `README.md` with full setup instructions, roles, missions, game flow, debug endpoints

### Server

#### Core
- `server/main.py` — FastAPI app, `/ws` WebSocket endpoint, JSON envelope parsing, category-based message routing (all 11 active roles wired); debug endpoints: `POST /debug/damage`, `GET /debug/ship_status`, `POST /debug/spawn_enemy`, `POST /debug/start_game`; `game_loop.register_game_end_callback(lobby.on_game_end)` wired
- `server/connections.py` — `ConnectionManager`: connect/disconnect, metadata tagging (player_name, role, session_id, is_host), individual send, full broadcast, role-filtered broadcast, `all_ids()`
- `server/models/messages/` — Messages namespace package. `__init__.py` re-exports all symbols; `base.py` (Message, validate_payload, _PAYLOAD_SCHEMAS); one file per station domain. All existing imports unchanged.
- `server/models/ship.py` — `ShipSystem` (name, power, health, `_crew_factor=1.0`, `efficiency = (power/100)*(health/100)*_crew_factor`), `Shields` (front, rear), `Ship` dataclass (position, heading, target_heading, velocity, throttle, hull, shields, 8 systems: engines/beams/torpedoes/shields/sensors/manoeuvring/flight_deck/ecm_suite, alert_level, crew, medical_supplies=20, `interior: ShipInterior = make_default_interior()`). `Ship.update_crew_factors()` propagates deck crew factors to systems each tick.
- `server/models/crew.py` — `DeckCrew` (deck_name, total, active, injured, critical, dead, `crew_factor` property). `CrewRoster` (decks dict, `apply_casualties`, `treat_injured`, `treat_critical`, `get_deck_for_system`). `DECK_SYSTEM_MAP`. `DECK_DEFAULT_CREW`.
- `server/models/interior.py` — `Room` (id, name, deck, position, connections, state, door_sealed). `ShipInterior` (rooms dict, `find_path()` BFS pathfinding, `marine_squads: list[MarineSquad]`, `intruders: list[Intruder]`). `make_default_interior()` — 5 decks, 20 rooms.
- `server/models/security.py` — `MarineSquad`, `Intruder`, constants. `is_intruder_visible()` fog-of-war filter.
- `server/models/world.py` — `World` dataclass (width, height, ship, enemies, torpedoes, stations, asteroids). `Enemy`, `Torpedo`, `Station`, `Asteroid` dataclasses. `ENEMY_TYPE_PARAMS` dict. `spawn_enemy()` factory.
- `server/models/ship_class.py` — **[v0.03o]** `ShipClass` Pydantic model (id, name, description, max_hull, torpedo_ammo, min_crew, max_crew). `load_ship_class(id)` reads `ships/<id>.json`; raises FileNotFoundError if missing. `list_ship_classes()` returns all 7 in canonical order. `SHIP_CLASS_ORDER = ["scout","corvette","frigate","cruiser","battleship","medical_ship","carrier"]`.
- `server/models/mission.py` — Pydantic schema documentation models (not used at runtime).
- `server/utils/math_helpers.py` — `wrap_angle`, `angle_diff`, `distance`, `lerp`, `bearing_to`
- `server/difficulty.py` — **[v0.03]** `DifficultyPreset` dataclass (enemy_damage_mult, puzzle_time_mult, hints_enabled, spawn_rate_mult). `PRESETS` dict with 4 named presets. `get_preset(name)` falls back to "officer" for unknown names.
- `server/game_debrief.py` — **[v0.03n]** `parse_log(path)`, `compute_debrief(events)`, `compute_from_log(path)`. Returns `{per_station_stats, awards, key_moments, timeline}`. 12 threshold-based awards. Tracks hull milestones (75/50/25%), key moments (objective completions, critical hits), timeline from tick_summary x/y.
- `server/game_logger.py` — `GameLogger` class + module-level singleton. `start_logging()`, `log_event()`, `set_tick()`, `stop_logging()`, `is_logging()`. **[v0.03n]** `get_log_path()` returns active or last-completed path via `_last_log_file` preservation. JSONL format. Writes to `logs/game_YYYYMMDD_HHMMSS.jsonl`. Controlled via `STARBRIDGE_LOGGING` env var (default enabled). Never raises.

#### Systems
- `server/systems/physics.py` — `tick(ship, dt, w, h)`: turn + thrust + move + boundary clamp
- `server/systems/combat.py` — `beam_in_arc`, `apply_hit_to_player` (crew casualties: `int(hull_damage/5)` via rng.choice), `apply_hit_to_enemy`, `regenerate_shields`. `CREW_CASUALTY_PER_HULL_DAMAGE=5.0`.
- `server/systems/ai.py` — `tick_enemies(enemies, ship, dt)`. State machine (idle→chase→attack→flee). Type-differentiated movement. `AI_TURN_RATE=90°/s`.
- `server/systems/sensors.py` — `ActiveScan` dataclass. Scan lifecycle, range calculations, contact filtering, weakness computation.
- `server/puzzles/` — Puzzle engine package:
  - `base.py` — `PuzzleInstance` ABC with `**_kwargs` forwarding
  - `engine.py` — `PuzzleEngine` class (create/tick/submit/apply_assist/cancel/pop/reset). Registry via `register_puzzle_type()`
  - `sequence_match.py` — PoC: colour sequence reveal, self-registers at import
  - `circuit_routing.py` — Engineering: BFS grid routing, 3×3–5×5 by difficulty, `highlight_nodes` assist
  - `frequency_matching.py` — Science/Comms: multi-component sine waveform matching, `widen_tolerance` assist
  - `tactical_positioning.py` — Security: live interior ref + intruder_specs kwargs, 300-tick mini-sim validation, `reveal_interception_points` assist
  - `transmission_decoding.py` — Comms: cipher symbol mapping, sum-equation clues, `reveal_symbol` assist; stores relay_component for Comms→Science chain
  - `triage.py` — Medical: disease outbreak triage, deck prioritisation, `reveal_infection_map` assist
  - `route_calculation.py` — Helm: hazard field BFS navigation, `weapon_stagger` assist from Weapons
  - `firing_solution.py` — Weapons: intercept bearing calculation, `captain_log` assist from Captain
  - `network_intrusion.py` — **[v0.03k]** Electronic Warfare: network graph traversal / node-cracking puzzle, `signal_trace` assist

#### Station Handlers
- `server/helm.py` — validates + enqueues helm messages
- `server/engineering.py` — validates + enqueues engineering messages
- `server/weapons.py` — validates + enqueues weapons messages
- `server/science.py` — validates + enqueues science messages
- `server/captain.py` — `captain.set_alert`: broadcasts `ship.alert_changed` directly (instant, no queue). **[v0.03]** `game_loop_captain.py` sub-module for captain-side state.
- `server/medical.py` — validates + enqueues medical messages
- `server/security.py` — validates + enqueues `security.move_squad` and `security.toggle_door`
- `server/comms.py` — validates + enqueues `comms.tune_frequency` and `comms.hail`
- `server/flight_ops.py` — **[v0.03j]** validates + enqueues flight_ops messages (launch/recall fighters, assign patrol patterns)
- `server/ew.py` — **[v0.03k]** validates + enqueues `ew.jam_target`, `ew.deploy_decoy`, `ew.scan_network`
- `server/tactical.py` — **[v0.03l]** validates + enqueues `tactical.strike_plan`, `tactical.coordinate_fire`, `tactical.mark_target`
- `server/lobby.py` — full lobby logic; 11 active player roles; `register_game_start_callback()`, `_game_active` flag, `on_game_end()` callback; `game.started` payload includes mission data, `interior_layout`, ship_classes list (with min_crew/max_crew), difficulty preset; `_game_payload` for late-joiner replay

#### Game Loop (split into 13 files)
- `server/game_loop.py` — Orchestrator. `start()` resets all sub-modules. `_loop()` runs all tick functions; broadcasts station-specific state. Includes signal scan interception, `start_boarding`, Comms→Science relay chain, `_check_sensor_assist()`. Game-over path: capture log path → `stop_logging()` → `compute_from_log()` → `game.over` with debrief payload. **[v0.03n]** tick_summary includes x/y.
- `server/game_loop_physics.py` — `TICK_RATE=10`, `TICK_DT=0.1`
- `server/game_loop_weapons.py` — stateful weapons: target, ammo, cooldowns, fire, torpedo management
- `server/game_loop_mission.py` — stateful mission: `init_mission()`, `tick_mission()`, pending actions queue, `get_mission_dict()` returns deep copy
- `server/game_loop_medical.py` — treatment state: `start_treatment()` (costs 2 supplies), `tick_treatments()` (heals 1/deck/2s), `cancel_treatment()`, `get_active_treatments()`
- `server/game_loop_security.py` — boarding state: `deploy_squads()`, `start_boarding()`, `move_squad()`, `toggle_door()`, `tick_security()`, fog-of-war filtered `build_interior_state()`
- `server/game_loop_comms.py` — comms state: frequency tuning, hailing, NPC responses, passive interception fragments. `FACTION_BANDS` dict.
- `server/game_loop_captain.py` — **[v0.03]** captain-side state: strike plan log, nuclear authorisation flow
- `server/game_loop_damage_control.py` — **[v0.03i]** damage control state: hull breach detection, fire suppression, emergency repair priorities, deck pressure status. Backend-only (no dedicated player station page — integrated with Engineering station).
- `server/game_loop_flight_ops.py` — **[v0.03j]** flight operations state: fighter squadron launch/recall, patrol assignment, hangar bay management
- `server/game_loop_ew.py` — **[v0.03k]** electronic warfare state: jamming targets, decoy deployment, network scan results, ECM effectiveness
- `server/game_loop_tactical.py` — **[v0.03l]** tactical state: strike plan management, coordinated fire solutions, mark-target tracking
- `server/game_loop_training.py` — **[v0.03m]** training state: `is_training_active()`, `set_training_flag(flag)`, `reset()`. Station handlers call `set_training_flag()` when training-relevant actions occur (e.g. `helm_heading_set`, `weapons_beam_fired`).

#### Mission System (`server/missions/`)
- `server/missions/loader.py` — `load_mission(id)`: reads `missions/<id>.json`; sandbox returns synthetic graph-format dict. **[v0.04b]** Sandbox dict uses graph format: `{nodes:[], edges:[], start_node:None, victory_nodes:[], defeat_condition:None}`.
- `server/missions/engine.py` — `MissionEngine` class. Sequential objectives. **Still used in tests with inline dicts (do not remove).** Trigger types: all standard triggers + `training_flag`.
- `server/mission_graph.py` — **[v0.04a]** `MissionGraph` class. Drop-in replacement for `MissionEngine` with parallel/branch/conditional/checkpoint nodes. Same public interface: `tick(world, ship, dt)`, `pop_pending_actions()`, `notify_puzzle_result(label, success)`, `set_training_flag(flag)`, `record_signal_scan()`, `is_over()`, `get_objectives()`, `get_active_node_ids()`. Mission format: `nodes` (with nested `children` for parallel), `edges`, `start_node`, `victory_nodes`, `defeat_condition` dict. Trigger format: `{"type": "name", ...args}` (flat merge). **[v0.04c]** Bug fix: `_tick_completions` accumulator in `_do_complete_node` ensures parallel parent IDs appear in `tick()` return list when they complete via child completion.
- `tools/migrate_missions.py` — **[v0.04b]** Migration script: converts missions from old sequential format (objectives array + string triggers) to graph format. Handles `defeat_condition_alt` via `any_of`. Skips already-migrated files.

### Ships

`ships/` directory — 7 JSON files, one per ship class:
- `scout.json` — hull=60, ammo=8, min_crew=3, max_crew=4
- `corvette.json` — hull=80, ammo=10, min_crew=4, max_crew=6
- `frigate.json` — hull=100, ammo=12, min_crew=6, max_crew=9 (default game ship)
- `cruiser.json` — hull=140, ammo=16, min_crew=8, max_crew=11
- `battleship.json` — hull=200, ammo=20, min_crew=10, max_crew=12
- `medical_ship.json` — hull=80, ammo=6, min_crew=5, max_crew=8 (specialised — v0.04 unique mechanics)
- `carrier.json` — hull=120, ammo=8, min_crew=7, max_crew=12 (specialised — v0.04 fighter mechanics)

### Missions

#### Standard Missions (15 JSON files + sandbox)
- **Sandbox** — synthetic dict in `loader.py`; free play, no objectives, continuous enemy spawns
- `missions/first_contact.json` — 4 sequential: patrol → scan scout → destroy all → return
- `missions/defend_station.json` — 3 waves + station defence
- `missions/search_rescue.json` — signal triangulation, asteroid field, proximity_with_shields
- `missions/puzzle_poc.json` — framework PoC: sequence_match on Science
- `missions/engineering_drill.json` — simultaneous freq_matching + circuit_routing; sensor overclock assist chain
- `missions/boarding_action.json` — deploy_squads → tactical_positioning puzzle → boarding simulation
- `missions/first_contact_protocol.json` — freq_matching + transmission_decoding; Comms→Science relay chain
- `missions/plague_ship.json` — triage puzzle + disease outbreak + deck infection spread
- `missions/nebula_crossing.json` — route_calculation puzzle for Helm; weapon_stagger assist chain
- `missions/deep_strike.json` — firing_solution puzzle for Weapons; nuclear authorisation flow
- `missions/diplomatic_summit.json` — 9-objective flagship mission; all 8+ puzzle types simultaneously
- **[v0.04c]** `missions/salvage_run.json` — 3-way branch: science vs comms vs timer ambush; parallel rescue (dock + triage)
- **[v0.04c]** `missions/first_contact_remastered.json` — 3-way branch: scan (diplomatic any-of), destroy (combat), flee
- **[v0.04c]** `missions/the_convoy.json` — parallel count=2/3 attack groups; compound defeat condition; 3 station spawns
- **[v0.04c]** `missions/pandemic.json` — 3-way pathogen branch; two nested parallel "all" outcome paths

#### Training Missions (12 JSON files — one per role)
All training missions carry `"is_training": true` and `"target_role"`. Objectives use `training_flag` triggers. All have hints. All have `≥3` objectives.
- `missions/train_helm.json` — heading, throttle, minimap navigation
- `missions/train_weapons.json` — targeting, beam fire, torpedo launch
- `missions/train_engineering.json` — power allocation, repair, overclock warning
- `missions/train_science.json` — sensor scan, weakness identification, bearing triangulation
- `missions/train_medical.json` — treatment initiation, heal-over-time, resupply
- `missions/train_security.json` — squad movement, door control, boarding response
- `missions/train_comms.json` — frequency tuning, hailing, NPC responses
- `missions/train_damage_control.json` — hull breach response, fire suppression, emergency repair
- `missions/train_flight_ops.json` — fighter launch, patrol assignment, recall
- `missions/train_ew.json` — jamming, decoy deployment, network scan
- `missions/train_tactical.json` — strike plan, mark target, coordinated fire
- `missions/train_captain.json` — alert level, mission overview, crew coordination

### Client

#### Shared
- `client/shared/connection.js` — WebSocket manager: exponential backoff, `on()`, `send()`, `connect()`
- `client/shared/renderer.js` — Canvas utilities: starfield, compass, minimap, chevron, world-to-screen transform
- `client/shared/theme.css` — Wire aesthetic: CSS custom properties, panels, buttons, gauges, animations, `.puzzle-overlay` CSS
- `client/shared/ui_components.js` — `setAlertLevel()`, `setStatusDot()`, `redirectToStation()`, `showBriefing()`, **[v0.03n]** `showGameOver()` saves debrief to localStorage + shows "VIEW DEBRIEF" button when debrief data present
- `client/shared/audio.js` — placeholder; `SoundBank` class wired but silent
- `client/shared/puzzle_renderer.js` — `initPuzzleRenderer(sendFn)`: handles puzzle.* messages, overlay lifecycle, dynamic import of puzzle type module, SUBMIT + REVEAL HINT buttons, client-side countdown
- `client/shared/role_bar.js` — **[v0.03]** multi-role support: players holding multiple roles simultaneously; role indicator bar shown on all station pages
- `client/shared/puzzle_types/` — 8 client-side puzzle type renderers:
  - `sequence_match.js` — colour buttons, answer pips, undo
  - `circuit_routing.js` — canvas drag-to-connect, flow animation, applyAssist highlights solution
  - `frequency_matching.js` — oscilloscope canvas, amplitude/frequency sliders, match meter
  - `transmission_decoding.js` — cipher table, clue list, symbol input
  - `triage.js` — deck status grid, treatment priority selection
  - `route_calculation.js` — hazard field canvas, waypoint placement
  - `firing_solution.js` — bearing calculator, intercept arc display
  - `network_intrusion.js` — **[v0.03k]** network graph canvas, node selection, signal trace overlay

#### Lobby (`client/lobby/`)
- `index.html`, `lobby.js`, `lobby.css` — role cards (11 active roles + viewscreen), callsign validation, claim/release, host launch, mission select dropdown, difficulty preset select, ship class select with crew range display

#### Briefing Room (`client/briefing/`) — **[v0.03]**
- `index.html`, `briefing.js`, `briefing.css` — standalone pre-game briefing page; renders mission briefing text with atmospheric formatting; accessible before game launch

#### Helm (`client/helm/`)
- `index.html`, `helm.js`, `helm.css`
- Two-state interpolation (10Hz→60fps), parallax starfield, compass dial, throttle slider, minimap with enemy overlays, beam flash, hull-hit flash, briefing overlay, game-over overlay

#### Engineering (`client/engineering/`)
- `index.html`, `engineering.js`, `engineering.css`
- Ship schematic canvas, power sliders, repair allocation, overclock damage flash, `initPuzzleRenderer(send)` wired, cross-station assist notification panel, alert level

#### Weapons (`client/weapons/`)
- `index.html`, `weapons.js`, `weapons.css`
- 360° tactical radar, click-to-target, beam hold-to-fire (2Hz), torpedo tubes with reload by type (standard/emp/probe/nuclear), shield balance slider, torpedo trails, explosions

#### Science (`client/science/`)
- `index.html`, `science.js`, `science.css`
- Long-range sensor canvas (North-up), contact list with scan progress, bearing lines for signal triangulation, `initPuzzleRenderer(send)` wired. **[v0.03h]** Multiple scan modes: EM / GRAV / BIO / SUB — each reveals different contact properties.

#### Captain (`client/captain/`)
- `index.html`, `captain.js`, `captain.css`
- Tactical map (North-up, `MAP_WORLD_RADIUS=80,000`), alert buttons → `ship.alert_changed` broadcast, ship status panel, science summary, mission objectives panel, torpedo trails. **[v0.03n]** Saves debrief to localStorage on game.over; shows "VIEW DEBRIEF" button.

#### Comms (`client/comms/`)
- `index.html`, `comms.js`, `comms.css`
- Frequency scanner canvas (0.0–1.0 axis), faction signal blips, draggable tuner, faction badge, hailing interface, transmission log, `initPuzzleRenderer(send)` wired for transmission_decoding

#### Security (`client/security/`)
- `index.html`, `security.js`, `security.css`
- Ship interior canvas (5×4 room grid), squad tokens, intruder tokens (fog-of-war filtered), room state colour coding, door control sidebar, planning phase (tactical_positioning puzzle with threat markers + COMMIT button)

#### Medical (`client/medical/`)
- `index.html`, `medical.js`, `medical.css`
- Crew status by deck, treatment start/cancel, supply counter, heal progress bars

#### Flight Operations (`client/flight_ops/`) — **[v0.03j]**
- `index.html`, `flight_ops.js`, `flight_ops.css`
- Hangar bay display, fighter squadron status, launch/recall controls, patrol pattern assignment, `initPuzzleRenderer(send)` wired

#### Electronic Warfare (`client/ew/`) — **[v0.03k]**
- `index.html`, `ew.js`, `ew.css`
- ECM/ECCM status display, jamming target selector, decoy bay, network scan canvas, `initPuzzleRenderer(send)` wired for network_intrusion puzzle

#### Tactical (`client/tactical/`) — **[v0.03l]**
- `index.html`, `tactical.js`, `tactical.css`
- Tactical coordination panel: strike plan builder, target marking overlay, coordinated fire scheduler, `initPuzzleRenderer(send)` wired

#### Viewscreen (`client/viewscreen/`)
- `index.html`, `viewscreen.js`, `viewscreen.css` — passive display: third-person forward view, contact chevrons, torpedo trails, beam flashes, shield impact arc, explosion rings

#### Debrief Dashboard (`client/debrief/`) — **[v0.03n]**
- `index.html`, `debrief.js`, `debrief.css`
- Standalone post-game page. Reads `localStorage('starbridge_debrief')`. Renders:
  - Awards panel (up to 12 threshold-based awards)
  - Key moments timeline (objective completions, critical hull hits)
  - Captain's log entries
  - Per-station stats table (event counts by role)
  - Captain's Replay canvas: animated ship path with gold key-event markers, play/pause, scrub bar, speed select (1×/2×/4×/8×)
- Falls back to "No debrief data available" if localStorage empty

### Tests

| File | Tests | Phase |
|------|-------|-------|
| `test_messages.py` | 28 | Phase 1 |
| `test_connections.py` | 21 | Phase 1 |
| `test_lobby.py` | 41 | Phase 1–7, v0.03 |
| `test_main.py` | 13 | Phase 1 |
| `test_math_helpers.py` | 13 | Phase 2 |
| `test_ship.py` | 15 | Phase 2 |
| `test_physics.py` | 22 | Phase 2 |
| `test_game_loop.py` | 28 | Phase 2–3 |
| `test_engineering.py` | 18 | Phase 3 |
| `test_ai.py` | 26 | Phase 4 |
| `test_combat.py` | 22 | Phase 4 |
| `test_weapons.py` | 12 | Phase 4 |
| `test_sensors.py` | 24 | Phase 5 |
| `test_science.py` | 5 | Phase 5 |
| `test_captain.py` | 7 | Phase 6 |
| `test_mission_engine.py` | 46 | Phase 6–7 |
| `test_crew.py` | 31 | v0.02 [2a.1] |
| `test_interior.py` | 19 | v0.02 [2a.1] |
| `test_medical.py` | 21 | v0.02 [2a.2] |
| `test_security_models.py` | 58 | v0.02 [2c.1] |
| `test_security_loop.py` | 50 | v0.02 [2c.2] |
| `test_puzzle_engine.py` | 39 | v0.02 [2b] |
| `test_puzzle_mission.py` | 11 | v0.02 [2b] |
| `test_circuit_routing.py` | 44 | v0.02 [2b2] |
| `test_frequency_matching.py` | 35 | v0.02 [2b2] |
| `test_assist_chain.py` | 10 | v0.02 [2b2] |
| `test_tactical_positioning.py` | 31 | v0.02 [2c.4] |
| `test_transmission_decoding.py` | 39 | v0.02 [2c.5] |
| `test_triage.py` | 42 | v0.02 [2c.6] |
| `test_torpedo_types.py` | 40 | v0.02 [c.8] |
| `test_route_calculation.py` | 61 | v0.02 [c.8] |
| `test_firing_solution.py` | 35 | v0.02 [c.8] |
| `test_diplomatic_summit.py` | 51 | v0.02 [c.9] |
| `test_difficulty.py` | 14 | v0.03 |
| `test_crew_notify.py` | 8 | v0.03 |
| `test_multi_role.py` | 6 | v0.03 |
| `test_damage_control.py` | 34 | v0.03i |
| `test_flight_ops.py` | 52 | v0.03j |
| `test_ew.py` | 45 | v0.03k |
| `test_network_intrusion.py` | 32 | v0.03k |
| `test_tactical.py` | 61 | v0.03l |
| `test_training.py` | 66 | v0.03m |
| `test_debrief.py` | 35 | v0.03n |
| `test_ship_class.py` | 13 | v0.03o (updated) |
| `test_ship_classes.py` | 71 | v0.03o |
| `test_gate_v003.py` | 183 | v0.03o |
| `test_mission_graph.py` | 118 | v0.04a |
| `test_graph_missions.py` | 60 | v0.04c |

**Total: 1781 tests** ✓ (verified by pytest run 2026-02-20, post-v0.04c)

---

## What Works (v0.03)

- `python run.py` starts the server; LAN URL printed
- Full lobby flow: 11 claimable roles, ship class select, difficulty select, mission select
- Role bar: players can hold multiple roles simultaneously
- Training missions: role-specific tutorials with training_flag objectives and hints
- **Helm**: heading/throttle, starfield, compass, minimap, hull-hit flash
- **Engineering**: ship schematic, power sliders, repair, circuit_routing puzzle overlay
- **Weapons**: 360° radar, targeting, beam/torpedo fire (4 torpedo types), shield balance
- **Science**: sensor canvas, contact scanning + weakness, bearing triangulation, 4 scan modes (EM/GRAV/BIO/SUB), frequency_matching puzzle overlay
- **Captain**: tactical map, alert control, ship status, mission objectives, debrief button on game.over
- **Viewscreen**: third-person forward view, contact chevrons, beam flashes, explosions
- **Medical**: crew treatment, heal-over-time, medical supply management
- **Security**: boarding defence, squad movement, door control, fog-of-war, tactical_positioning puzzle
- **Comms**: frequency scanner, hailing, NPC responses, transmission_decoding puzzle, Comms→Science relay chain
- **Flight Operations**: fighter squadron launch/recall, patrol assignment
- **Electronic Warfare**: jamming, decoy deployment, network scan, network_intrusion puzzle
- **Tactical**: strike plan builder, target marking, coordinated fire, firing_solution puzzle
- Damage control mechanics: hull breach, fire suppression, emergency repair (backend, integrated with Engineering)
- Cross-station notifications: `crew.notify` → `crew.notification` broadcast to relevant roles
- 9 puzzle types: sequence_match, circuit_routing, frequency_matching, tactical_positioning, transmission_decoding, triage, route_calculation, firing_solution, network_intrusion
- 7 ship classes with crew ranges; lobby shows ship stats
- 4 difficulty presets (cadet/officer/commander/admiral) — hint availability, enemy damage mult, puzzle time mult, spawn rate mult
- Game event logger (JSONL, `logs/` dir) with debrief computation
- Debrief Dashboard: post-game awards, key moments, per-station stats, Captain's Replay canvas
- Mission briefing room (`/client/briefing/`): pre-game briefing with atmospheric rendering
- 23 missions: 11 story (Sandbox + 11 JSON) + 12 training (one per role)
- All stations handle `ship.alert_changed` + `game.started` briefing + `game.over` result overlay

---

## Known Limitations (v0.03 Close)

- **No audio** — `client/shared/audio.js` is a placeholder; `SoundBank` is wired but silent
- **No tablet layout verification** — not tested on physical hardware
- **No automated end-to-end tests** — no Playwright/Selenium suite
- **Science bearing lines accumulate indefinitely** — session-lifetime storage in science.js
- **Sandbox has no game.over** — infinite play; only hull-zero defeat fires
- **Lobby does not enforce min_crew** — host can launch with fewer players than min_crew
- **medical_ship and carrier have no differentiated gameplay** — hull/ammo differ; specialist mechanics (medbay expansion, fighter complement) are v0.04 scope
- **point_defence system absent** — declared in earlier scope for battleship, never implemented; 8 ship systems exist (not 9)
- **Stale health endpoint** — `server/main.py` returns `"phase": "4 — Weapons Station + Combat"` — not updated since Phase 4
- **Single session** — one game at a time; multi-game would require session namespacing

---

## Phase Gate Checklists

### Phases 1–6 Gate: COMPLETE ✓
(see archived git history or earlier STATE.md versions)

### Phase 7 Gate (v0.01): COMPLETE ✓
- [x] Viewscreen: forward view with contacts, torpedo trails, beam flashes, shield impact, explosions
- [x] Defend Station: 3 waves + station entity; victory/defeat from station health
- [x] Search & Rescue: signal triangulation (science bearing lines), asteroid field, proximity_with_shields
- [x] Briefing overlay on ALL stations
- [x] Victory/defeat overlay on ALL stations with duration + hull remaining
- [x] Return to Lobby button on all game-over overlays
- [x] Server resets after game ends
- [x] 331 tests pass

### v0.02 Gate: COMPLETE ✓ — 2026-02-19
- [x] 948 tests pass; 0 regressions from v0.01 baseline
- [x] 8 stations (captain, helm, weapons, engineering, science, medical, security, comms)
- [x] 8 puzzle types active
- [x] 11 JSON missions + sandbox
- [x] Cross-station assist chains: Engineering→Science, Comms→Science, Captain→Weapons, Weapons→Helm
- [x] Boarding system: deploy_squads, start_boarding, fog-of-war, AP system
- [x] Game event logger (JSONL, logs/ dir, STARBRIDGE_LOGGING env var)
- [x] Torpedo types: standard/emp/probe/nuclear + nuclear auth flow
- [x] Disease outbreak mechanics + triage puzzle
- [x] Diplomatic Summit: 9-objective flagship mission
- [x] Commit: fe339fc

### v0.03 Gate: COMPLETE ✓ — 2026-02-20
- [x] 1578 tests passing; 0 regressions from v0.02 baseline (948 tests)
- [x] 12 player stations (11 active roles + viewscreen passive): all verified 200 OK
- [x] 9 puzzle types across all stations
- [x] 23 JSON missions: 11 story + 12 training (one per role)
- [x] 7 ship classes: scout/corvette/frigate/cruiser/battleship/medical_ship/carrier — all with min_crew/max_crew
- [x] 4 difficulty presets: cadet/officer/commander/admiral
- [x] Game event logger + Debrief Dashboard + Captain's Replay
- [x] Multi-role play (role_bar.js)
- [x] Mission briefing room (client/briefing/)
- [x] Cross-station notification system (crew.notify → crew.notification)
- [x] Training flag trigger type + game_loop_training.py
- [x] Science scan modes (EM/GRAV/BIO/SUB) [v0.03h]
- [x] Damage Control backend (hull breach, fire suppression) [v0.03i]
- [x] Flight Operations station [v0.03j]
- [x] Electronic Warfare station + network_intrusion puzzle [v0.03k]
- [x] Tactical Officer station [v0.03l]
- [x] All game_loop_* modules have reset() [gate-verified]
- [x] get_mission_dict() returns deep copy [gate-verified]
- [x] All lobby roles present (11) [gate-verified]
- [x] All training missions loadable with is_training=True + target_role [gate-verified]
- [x] All standard missions loadable with valid triggers [gate-verified]
- [x] Debrief compute_from_log() works on synthetic log [gate-verified]

**Known gaps at v0.03 close (not blocking)**:
- No audio (audio.js placeholder)
- No tablet layout verification
- No automated E2E tests
- `point_defence` system absent (scope drift from earlier spec)
- Stale health endpoint phase string
- min_crew not enforced at launch
- medical_ship/carrier have no differentiated mechanics

---

## File Manifest (v0.03 — updated 2026-02-20)

```
starbridge/
├── .ai/
│   ├── SYSTEM_PROMPT.md
│   ├── CONVENTIONS.md
│   ├── STATE.md              ← THIS FILE
│   ├── DECISIONS.md
│   ├── LESSONS.md
│   └── PHASE_CURRENT.md
├── server/
│   ├── main.py
│   ├── connections.py
│   ├── lobby.py
│   ├── game_loop.py          (orchestrator; debrief + x/y tick_summary added v0.03n)
│   ├── game_loop_physics.py
│   ├── game_loop_weapons.py
│   ├── game_loop_mission.py
│   ├── game_loop_medical.py
│   ├── game_loop_security.py
│   ├── game_loop_comms.py
│   ├── game_loop_captain.py  [v0.03]
│   ├── game_loop_damage_control.py [v0.03i — backend only, no client page]
│   ├── game_loop_flight_ops.py [v0.03j]
│   ├── game_loop_ew.py       [v0.03k]
│   ├── game_loop_tactical.py [v0.03l]
│   ├── game_loop_training.py [v0.03m]
│   ├── helm.py
│   ├── engineering.py
│   ├── weapons.py
│   ├── science.py
│   ├── captain.py
│   ├── medical.py
│   ├── security.py
│   ├── comms.py
│   ├── flight_ops.py         [v0.03j]
│   ├── ew.py                 [v0.03k]
│   ├── tactical.py           [v0.03l]
│   ├── game_logger.py        (get_log_path + _last_log_file added v0.03n)
│   ├── game_debrief.py       [v0.03n]
│   ├── difficulty.py         [v0.03]
│   ├── models/
│   │   ├── __init__.py
│   │   ├── ship.py
│   │   ├── world.py
│   │   ├── mission.py
│   │   ├── crew.py           [2a.1]
│   │   ├── interior.py       [2a.1]
│   │   ├── security.py       [2c.1]
│   │   ├── ship_class.py     [v0.03o]
│   │   └── messages/
│   │       ├── __init__.py
│   │       ├── base.py
│   │       ├── lobby.py
│   │       ├── helm.py
│   │       ├── engineering.py
│   │       ├── weapons.py
│   │       ├── science.py
│   │       ├── captain.py
│   │       ├── game.py
│   │       ├── world.py
│   │       ├── medical.py    [2a.2]
│   │       └── security.py   [2c.2]
│   ├── systems/
│   │   ├── __init__.py
│   │   ├── physics.py
│   │   ├── combat.py
│   │   ├── ai.py
│   │   └── sensors.py
│   ├── missions/
│   │   ├── __init__.py
│   │   ├── loader.py
│   │   └── engine.py
│   ├── puzzles/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── engine.py
│   │   ├── sequence_match.py
│   │   ├── circuit_routing.py
│   │   ├── frequency_matching.py
│   │   ├── tactical_positioning.py
│   │   ├── transmission_decoding.py
│   │   ├── triage.py
│   │   ├── route_calculation.py
│   │   ├── firing_solution.py
│   │   └── network_intrusion.py  [v0.03k]
│   └── utils/
│       ├── __init__.py
│       └── math_helpers.py
├── client/
│   ├── shared/
│   │   ├── connection.js
│   │   ├── renderer.js
│   │   ├── theme.css
│   │   ├── ui_components.js  (debrief save + button added v0.03n)
│   │   ├── audio.js          (placeholder)
│   │   ├── role_bar.js       [v0.03 — multi-role support]
│   │   ├── puzzle_renderer.js
│   │   └── puzzle_types/
│   │       ├── sequence_match.js
│   │       ├── circuit_routing.js
│   │       ├── frequency_matching.js
│   │       ├── transmission_decoding.js
│   │       ├── triage.js
│   │       ├── route_calculation.js
│   │       ├── firing_solution.js
│   │       └── network_intrusion.js  [v0.03k]
│   ├── lobby/
│   │   ├── index.html
│   │   ├── lobby.js          (ship class select, difficulty select added v0.03)
│   │   └── lobby.css
│   ├── briefing/             [v0.03]
│   │   ├── index.html
│   │   ├── briefing.js
│   │   └── briefing.css
│   ├── captain/
│   │   ├── index.html        (debrief button added v0.03n)
│   │   ├── captain.js        (debrief save added v0.03n)
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
│   │   ├── science.js        (scan modes EM/GRAV/BIO/SUB added v0.03h)
│   │   └── science.css
│   ├── medical/
│   │   ├── index.html
│   │   ├── medical.js
│   │   └── medical.css
│   ├── security/
│   │   ├── index.html
│   │   ├── security.js
│   │   └── security.css
│   ├── comms/
│   │   ├── index.html
│   │   ├── comms.js
│   │   └── comms.css
│   ├── flight_ops/           [v0.03j]
│   │   ├── index.html
│   │   ├── flight_ops.js
│   │   └── flight_ops.css
│   ├── ew/                   [v0.03k]
│   │   ├── index.html
│   │   ├── ew.js
│   │   └── ew.css
│   ├── tactical/             [v0.03l]
│   │   ├── index.html
│   │   ├── tactical.js
│   │   └── tactical.css
│   ├── viewscreen/
│   │   ├── index.html
│   │   ├── viewscreen.js
│   │   └── viewscreen.css
│   └── debrief/              [v0.03n]
│       ├── index.html
│       ├── debrief.js
│       └── debrief.css
├── ships/                    [v0.03o]
│   ├── scout.json
│   ├── corvette.json
│   ├── frigate.json
│   ├── cruiser.json
│   ├── battleship.json
│   ├── medical_ship.json
│   └── carrier.json
├── missions/                 (sandbox is synthetic — no JSON file)
│   ├── first_contact.json
│   ├── defend_station.json
│   ├── search_rescue.json
│   ├── puzzle_poc.json
│   ├── engineering_drill.json
│   ├── boarding_action.json
│   ├── first_contact_protocol.json
│   ├── plague_ship.json
│   ├── nebula_crossing.json
│   ├── deep_strike.json
│   ├── diplomatic_summit.json
│   ├── train_helm.json       [v0.03m]
│   ├── train_weapons.json    [v0.03m]
│   ├── train_engineering.json [v0.03m]
│   ├── train_science.json    [v0.03m]
│   ├── train_medical.json    [v0.03m]
│   ├── train_security.json   [v0.03m]
│   ├── train_comms.json      [v0.03m]
│   ├── train_damage_control.json [v0.03m]
│   ├── train_flight_ops.json [v0.03m]
│   ├── train_ew.json         [v0.03m]
│   ├── train_tactical.json   [v0.03m]
│   ├── train_captain.json    [v0.03m]
│   ├── salvage_run.json      [v0.04c]
│   ├── first_contact_remastered.json [v0.04c]
│   ├── the_convoy.json       [v0.04c]
│   └── pandemic.json         [v0.04c]
├── docs/
│   ├── MESSAGE_PROTOCOL.md
│   ├── MISSION_FORMAT.md
│   ├── STYLE_GUIDE.md
│   └── SCOPE.md
├── tests/
│   ├── __init__.py
│   ├── test_messages.py           — 28
│   ├── test_connections.py        — 21
│   ├── test_lobby.py              — 41
│   ├── test_main.py               — 13
│   ├── test_math_helpers.py       — 13
│   ├── test_ship.py               — 15
│   ├── test_physics.py            — 22
│   ├── test_game_loop.py          — 28
│   ├── test_engineering.py        — 18
│   ├── test_ai.py                 — 26
│   ├── test_combat.py             — 22
│   ├── test_weapons.py            — 12
│   ├── test_sensors.py            — 24
│   ├── test_science.py            —  5
│   ├── test_captain.py            —  7
│   ├── test_mission_engine.py     — 46
│   ├── test_crew.py               — 31 [2a.1]
│   ├── test_interior.py           — 19 [2a.1]
│   ├── test_medical.py            — 21 [2a.2]
│   ├── test_security_models.py    — 58 [2c.1]
│   ├── test_security_loop.py      — 50 [2c.2]
│   ├── test_puzzle_engine.py      — 39 [2b]
│   ├── test_puzzle_mission.py     — 11 [2b]
│   ├── test_circuit_routing.py    — 44 [2b2]
│   ├── test_frequency_matching.py — 35 [2b2]
│   ├── test_assist_chain.py       — 10 [2b2]
│   ├── test_tactical_positioning.py — 31 [2c.4]
│   ├── test_transmission_decoding.py — 39 [2c.5]
│   ├── test_triage.py             — 42 [2c.6]
│   ├── test_torpedo_types.py      — 40 [c.8]
│   ├── test_route_calculation.py  — 61 [c.8]
│   ├── test_firing_solution.py    — 35 [c.8]
│   ├── test_diplomatic_summit.py  — 51 [c.9]
│   ├── test_difficulty.py         — 14 [v0.03]
│   ├── test_crew_notify.py        —  8 [v0.03]
│   ├── test_multi_role.py         —  6 [v0.03]
│   ├── test_damage_control.py     — 34 [v0.03i]
│   ├── test_flight_ops.py         — 52 [v0.03j]
│   ├── test_ew.py                 — 45 [v0.03k]
│   ├── test_network_intrusion.py  — 32 [v0.03k]
│   ├── test_tactical.py           — 61 [v0.03l]
│   ├── test_training.py           — 66 [v0.03m]
│   ├── test_debrief.py            — 35 [v0.03n]
│   ├── test_ship_class.py         — 13 [v0.03o updated]
│   ├── test_ship_classes.py       — 71 [v0.03o]
│   ├── test_gate_v003.py          — 183 [v0.03o]
│   ├── test_mission_graph.py      — 118 [v0.04a]
│   └── test_graph_missions.py     —  60 [v0.04c]
├── logs/                          (runtime — .gitignore)
├── pytest.ini
├── requirements.txt
├── run.py
└── README.md
```
