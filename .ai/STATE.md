# Project State

> **LIVING DOCUMENT** — Update after every AI engineering session.
> This is the single source of truth for what exists in the project.

**Last updated**: 2026-02-19 (v0.02 CLOSED — gate verification complete)
**Current phase**: v0.02 COMPLETE ✓
**Overall status**: 948 tests passing. 8 stations. 11 JSON missions + sandbox (synthetic). 8 puzzle types. Game event logger (JSONL, logs/ dir, STARBRIDGE_LOGGING env var).

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
- `server/main.py` — FastAPI app, `/ws` WebSocket endpoint, JSON envelope parsing, category-based message routing (lobby/helm/engineering/weapons/science/medical/security/captain); **security handler wired [2c.4]**; all handlers wired; `POST /debug/damage`, `GET /debug/ship_status`, `POST /debug/spawn_enemy`, `POST /debug/start_game` debug endpoints; `game_loop.register_game_end_callback(lobby.on_game_end)` wired
- `server/connections.py` — `ConnectionManager`: connect/disconnect, metadata tagging (player_name, role, session_id, is_host), individual send, full broadcast, role-filtered broadcast, `all_ids()`
- `server/models/messages/` — **[0.1b split]** Messages namespace package. `__init__.py` re-exports all symbols; `base.py` (Message, validate_payload, _PAYLOAD_SCHEMAS); `lobby.py`, `helm.py`, `engineering.py`, `weapons.py`, `science.py`, `captain.py`, `game.py`, `world.py`, **`security.py`** **[2c.2]** (`SecurityMoveSquadPayload`, `SecurityToggleDoorPayload`). All existing imports unchanged.
- `server/models/ship.py` — `ShipSystem` (name, power, health, `_crew_factor=1.0`, `efficiency = (power/100)*(health/100)*_crew_factor`), `Shields` (front, rear), `Ship` dataclass (position, heading, target_heading, velocity, throttle, hull, shields, 6 systems, alert_level, crew, medical_supplies=20, **`interior: ShipInterior = make_default_interior()`** **[2c.2]**). `Ship.update_crew_factors()` propagates deck crew factors to systems each tick.
- `server/models/crew.py` — **[2a.1]** `DeckCrew` (deck_name, total, active, injured, critical, dead, `crew_factor` property). `CrewRoster` (decks dict, `apply_casualties`, `treat_injured`, `treat_critical`, `get_deck_for_system`). `DECK_SYSTEM_MAP` (bridge→manoeuvring, sensors→sensors, weapons→beams+torpedoes, shields→shields, engineering→engines). `DECK_DEFAULT_CREW`.
- `server/models/interior.py` — **[2a.1]** `Room` (id, name, deck, position, connections, state, door_sealed). `ShipInterior` (rooms dict, `find_path()` BFS pathfinding — blocks sealed/decompressed, `marine_squads: list[MarineSquad]`, `intruders: list[Intruder]` — both empty by default). `make_default_interior()` — 5 decks, 20 rooms, bidirectional connections, vertical corridor at column 1.
- `server/models/security.py` — **[2c.1]** `MarineSquad` (id, room_id, health, action_points, count; `regen_ap`, `can_move/deduct_move_ap`, `can_seal_door/deduct_door_ap`, `take_damage` → casualty on threshold dip, `is_eliminated`). `Intruder` (id, room_id, objective_id, health, move_timer; `tick_move_timer`, `is_ready_to_move`, `reset_move_timer`, `take_damage`, `is_defeated`). Constants: `AP_MAX=10`, `AP_REGEN_PER_TICK=0.2`, `AP_COST_MOVE=3`, `AP_COST_DOOR=2`, `INTRUDER_MOVE_INTERVAL=30`, `MARINE_DAMAGE_PER_TICK=0.2`, `INTRUDER_DAMAGE_PER_TICK=0.15`, `SQUAD_CASUALTY_THRESHOLD=25.0`, `SENSOR_FOW_THRESHOLD=0.5`. `is_intruder_visible(intruder, squads, sensor_efficiency)` — fog-of-war filter.
- `server/models/world.py` — `World` dataclass (width, height, ship, enemies, torpedoes, stations, asteroids lists). `Enemy`, `Torpedo`, `Station`, `Asteroid` dataclasses. `ENEMY_TYPE_PARAMS` dict. `spawn_enemy()` factory. `SECTOR_WIDTH`/`SECTOR_HEIGHT` constants.
- `server/utils/math_helpers.py` — `wrap_angle`, `angle_diff`, `distance`, `lerp`, `bearing_to`

#### Systems
- `server/systems/physics.py` — `tick(ship, dt, w, h)`: turn + thrust + move + boundary clamp
- `server/systems/combat.py` — `beam_in_arc`, `apply_hit_to_player` (now applies crew casualties: `int(hull_damage/5)` crew on a random deck via `rng.choice`), `apply_hit_to_enemy`, `regenerate_shields`. New constant `CREW_CASUALTY_PER_HULL_DAMAGE=5.0`.
- `server/puzzles/` — **[2b]** Puzzle engine package:
  - `base.py` — `PuzzleInstance` ABC (`generate`, `validate_submission`, `apply_assist`, `tick` with auto-timeout, `_resolve`, `pop_pending_broadcasts`). **[2c.4]** `__init__` now accepts `**_kwargs` to absorb extra params forwarded by engine.
  - `engine.py` — `PuzzleEngine` class (`create_puzzle`, `tick`, `submit`, `apply_assist`, `cancel`, `pop_pending_broadcasts`, `pop_resolved`, `get_active_for_station`, `reset`). Registry via `register_puzzle_type()`. `submit()` immediately adds to `_resolved` and prunes puzzle to avoid double-reporting. **[2c.4]** `create_puzzle` forwards `**params` to puzzle constructor.
  - `sequence_match.py` — `SequenceMatchPuzzle` PoC: random colour sequence, `reveal_start` assist, self-registers at import.
  - `circuit_routing.py` — **[2b2]** `CircuitRoutingPuzzle` (Engineering): BFS grid routing, `_GRID_SIZES` (3×3–5×5 by diff), `_SLACK` extra conduits, damaged nodes, `highlight_nodes` assist → solution path. Helpers: `_node_id`, `_parse_node_id`, `_are_adjacent`, `_canon_edge`, `_build_all_edges`, `_bfs_path`.
  - `frequency_matching.py` — **[2b2]** `FrequencyMatchingPuzzle` (Science): multi-component sine waveform matching, `_DIFFICULTY_PARAMS` (2–5 components, tolerance 0.30–0.08), `_relative_rms_error` validation, `widen_tolerance` assist (+0.15, capped at 0.45). Helpers: `_sample_waveform`, `_relative_rms_error`.
  - `tactical_positioning.py` — **[2c.4]** `TacticalPositioningPuzzle` (Security): receives `interior` (live ShipInterior ref) and `intruder_specs` via **kwargs. `generate()` returns intruder_threats list. `validate_submission({"confirmed": True})` deep-copies interior, runs 300-tick mini-simulation to check if current squad positions can defeat all intruders; returns True/False. `apply_assist("reveal_interception_points")` returns midpoint rooms on each intruder's BFS path.
  - `transmission_decoding.py` — **[2c.5]** `TransmissionDecodingPuzzle` (Comms): N cipher symbols (difficulty 1–5: 3–6 symbols), some revealed as hints. Generates sum-equation clues. `validate_submission({"mappings": {sym: int}})` checks all unknowns correct. `apply_assist("reveal_symbol")` reveals one more symbol. `_relay_component` stored on success for Comms→Science relay chain.
- `server/game_logger.py` — **[c.9+]** `GameLogger` class + module-level singleton. `start_logging(mission_id, players)`, `log_event(cat, event, data)`, `set_tick(n)`, `stop_logging(result, stats)`, `is_logging()`. JSONL format, one line per event. Writes to `logs/game_YYYYMMDD_HHMMSS.jsonl`. Controlled via `STARBRIDGE_LOGGING` env var (default enabled). Never raises. Integrated into: lobby.py (role_claimed/released/game_started), captain.py (alert_changed), game_loop.py (tick_summary/200+ hook sites), game_loop_weapons.py (enemy_destroyed/ship_hit), game_loop_mission.py (objective_completed).
- `server/medical.py` — **[2a.2]** Queue-based handler for `medical.treat_crew` and `medical.cancel_treatment`. Same pattern as science.py.
- `server/game_loop_medical.py` — **[2a.2]** Stateful treatment module. `reset()`, `start_treatment(deck, type, ship)` (costs TREATMENT_COST=2 supplies), `cancel_treatment(deck)`, `tick_treatments(ship, dt)` (heals 1 crew per HEAL_INTERVAL=2.0s, auto-cancels when no crew left), `get_active_treatments()`.
- `server/models/messages/medical.py` — **[2a.2]** `MedicalTreatCrewPayload`, `MedicalCancelTreatmentPayload`.
- `server/systems/ai.py` — `tick_enemies(enemies, ship, dt) → list[BeamHitEvent]`. State machine (idle→chase→attack→flee), type-differentiated movement, beam fire with arc check, flee despawn. `AI_TURN_RATE=90°/s`.
- `server/systems/sensors.py` — `ActiveScan` dataclass. `reset/start/cancel_scan`, `get_scan_progress`, `sensor_range(ship)`, `tick(world, ship, dt) → list[completed_ids]`, `build_sensor_contacts(world, ship) → list[dict]`, `build_scan_result(enemy)`, `_compute_weakness(enemy)`

#### Station Handlers
- `server/helm.py` — validates + enqueues helm messages
- `server/engineering.py` — validates + enqueues engineering messages
- `server/weapons.py` — validates + enqueues weapons messages
- `server/science.py` — validates + enqueues science messages (start_scan, cancel_scan)
- `server/captain.py` — **[Phase 6]** `captain.set_alert`: validates level, updates `ship.alert_level`, broadcasts `ship.alert_changed` directly (instant, no queue)
- `server/medical.py` — **[2a.2]** validates + enqueues medical messages
- `server/security.py` — **[2c.2]** validates + enqueues `security.move_squad` and `security.toggle_door` messages; same init(sender, queue) pattern
- `server/comms.py` — **[2c.5]** validates + enqueues `comms.tune_frequency` and `comms.hail` messages; same init(sender, queue) pattern
- `server/lobby.py` — full lobby logic, role management; roles now include "security" **[2c.2]** and **"comms" [2c.5]**; `register_game_start_callback()`, `_game_active` flag, `on_game_end()` callback, `game.started` payload includes real mission data + **`interior_layout`** (static room data) **[2c.3]**

#### Game Loop (split into 5 files — Session 0.1a + 2c.2)
- `server/game_loop.py` — Orchestrator. `start()` calls `gls.reset()` + **`glco.reset()` [2c.5]**; resets `ship.interior`. `_loop()` calls `gls.tick_security()` + **`glco.tick_comms()` [2c.5]** each tick; broadcasts `security.interior_state` to `["security"]` + **`comms.state` + NPC responses to `["comms"]` [2c.5]**; handles `start_boarding` + **Comms→Science relay chain [2c.5]** (step 8.65: `pop_relay_data()` → `apply_assist("relay_frequency")` on Science). `_drain_queue()` handles `security.*` + **`comms.tune_frequency` + `comms.hail` [2c.5]**. When `frequency_matching` puzzle starts on Science, now notifies both `["engineering"]` and **`["comms"]` [2c.5]** via `puzzle.assist_available`.
- `server/game_loop_physics.py` — `TICK_RATE=10`, `TICK_DT=0.1`
- `server/game_loop_weapons.py` — Stateful weapons module. `reset()`, `get/set_target()`, `get/set_ammo()`, `get_cooldowns()`, `tick_cooldowns()`, `next_entity_id()`, `fire_player_beams()`, `fire_torpedo()`, `tick_torpedoes()`, `handle_enemy_beam_hits()`
- `server/game_loop_mission.py` — Stateful mission module. `init_mission()`, `tick_mission()` (queues `start_puzzle`, `start_boarding`, and **`deploy_squads` [2c.4]** on_complete actions), `pop_pending_puzzle_starts()`, `pop_pending_boardings()` **[2c.2]**, **`pop_pending_deployments()` [2c.4]**, `build_sensor_contacts()`, `build_world_entities()`
- `server/game_loop_comms.py` — **[2c.5]** Stateful comms module. `reset()`, `tune(freq)`, `hail(contact_id, message_type)`, `tick_comms(dt)` → NPC responses when hail timer expires, passive interception fragments on tuned hostile bands. `get_tuned_faction()` checks `FACTION_BANDS` (imperial=0.15, rebel=0.42, alien=0.71, emergency=0.90) ±0.05. `build_comms_state()` → `{active_frequency, tuned_faction, transmissions, pending_hails}`.
- `server/game_loop_security.py` — **[2c.2]** Stateful boarding module. `reset()`, **`deploy_squads(interior, squad_specs)` [2c.4]** (places squads without activating boarding — planning phase), `start_boarding(interior, squad_specs, intruder_specs)` **[2c.4 modified: empty squad_specs preserves existing squads from deploy_squads]**, `move_squad(interior, squad_id, room_id) → bool`, `toggle_door(interior, room_id, squad_id) → bool`, `tick_security(interior, ship, dt) → list[tuple[str, dict]]` (AP regen, intruder movement, combat, events), `is_boarding_active()`, `build_interior_state(interior, ship) → dict` (fog-of-war filtered). `_eliminated_reported: set[str]` prevents duplicate elimination events.

#### Mission System (`server/missions/`)
- `server/missions/__init__.py`
- `server/missions/loader.py` — `load_mission(id) → dict` (reads `missions/<id>.json`; sandbox returns synthetic dict); `spawn_from_mission(mission, world, counter) → counter`
- `server/missions/engine.py` — **[Phase 6 + 2b]** `Objective` dataclass, `MissionEngine` class:
  - Sequential objectives (active_index pointer — only current objective checked each tick)
  - Trigger types: `player_in_area`, `scan_completed`, `entity_destroyed`, `all_enemies_destroyed`, `player_hull_zero`, `timer_elapsed`, `wave_complete`, `signal_located`, `proximity_with_shields`
  - `record_signal_scan(x, y)` — rejects scans within 8 000 world units of previous scan
  - `_proximity_timer` for shields-held-in-range tracking
  - New trigger types: `puzzle_completed` (checks `args["puzzle_label"]`), `puzzle_failed`, **`puzzle_resolved` [2c.4]** (fires for either success or failure)
  - `notify_puzzle_result(label, success)` — called by game loop when a puzzle resolves
  - `tick(world, ship, dt) → list[newly_completed_ids]`
  - `get_objectives() → list[Objective]`
  - `is_over() → (bool, str | None)` — "victory" or "defeat"
  - **[2b2]** `on_complete` now supports list of action dicts (backward-compatible with single dict)

### Missions

#### Mission Files
- **Sandbox** — synthetic dict in `loader.py`; no JSON file. Free play, no objectives, continuous enemy spawns via `_spawn_sandbox_enemies()`. No `missions/sandbox.json` exists or is needed.
- `missions/first_contact.json` — 4 sequential objectives: patrol waypoint, scan scout, destroy all, return to origin
- `missions/defend_station.json` — **[Phase 7b]** 3 waves + station defence; `protect_station` objective, wave_complete triggers, station entity in world
- `missions/search_rescue.json` — **[Phase 7c]** signal triangulation (2 scans ≥ 8 000 units apart), asteroid field, proximity_with_shields (hold shields near damaged vessel for 10s)
- `missions/puzzle_poc.json` — **[2b]** Puzzle framework PoC: `timer_elapsed` (3s) → `start_puzzle` sequence_match on Science → `puzzle_completed` → victory
- `missions/engineering_drill.json` — **[2b2]** Engineering Drill: `timer_elapsed` (5s) → list on_complete fires `frequency_matching` on Science + `circuit_routing` on Engineering simultaneously; sensor overclock assist chain active
- `missions/boarding_action.json` — **[2c.4]** Boarding Action: deploys marine squads, activates intruder boarding, `tactical_positioning` puzzle for Security pre-combat
- `missions/first_contact_protocol.json` — **[2c.5]** First Contact Protocol: `frequency_matching(science)` + `transmission_decoding(comms)` simultaneously; Comms→Science relay assist chain; 120s hold for victory
- `missions/nebula_crossing.json` — **[c.8]** Nebula Crossing: `route_calculation` puzzle for Helm (hazard field navigation); weapon stagger assist chain (Weapons→Helm)
- `missions/deep_strike.json` — **[c.8]** Deep Strike: `firing_solution` puzzle for Weapons; Captain's log + nuclear authorisation
- `missions/plague_ship.json` — **[2c.6]** Plague Ship: `triage` puzzle for Medical + disease outbreak mechanics
- `missions/diplomatic_summit.json` — **[c.9]** Flagship 9-objective mission: all 7 active puzzle types across all 7 stations simultaneously; faction ships as station entities; 240s final timer for victory

### Client

#### Shared
- `client/shared/connection.js` — WebSocket manager: `on()`, `onStatusChange()`, `send()`, `connect()`, exponential backoff
- `client/shared/renderer.js` — Canvas: `lerp`, `lerpAngle`, `worldToScreen`, `createStarfield`, `drawBackground`, `drawStarfield`, `drawCompass`, `drawShipChevron`, `drawMinimap`. Colour constants exported.
- `client/shared/theme.css` — Wire aesthetic: CSS custom properties, reset, panels, buttons, gauges, status dots, scanline overlay, keyframe animations (`hit-flash`), `.briefing-overlay`, `.shared-game-over`, **`.puzzle-overlay` + sequence-match CSS** (added 2b)
- `client/shared/ui_components.js` — `setAlertLevel()`, `setStatusDot()`, `redirectToStation()`, **`showBriefing(missionName, briefingText)`** (auto-dismiss 15s, click to dismiss), **`showGameOver(result, stats)`** (duration + hull remaining + Return to Lobby link)
- `client/shared/puzzle_renderer.js` — **[2b]** `initPuzzleRenderer(sendFn)`. Handles `puzzle.started` (dynamic import + overlay), `puzzle.result` (success/failure, auto-dismiss 2s), `puzzle.assist_applied` (forwards to module). SUBMIT + REVEAL HINT buttons wired. Client-side countdown timer animation. **[2b2]** `successMessage` from `puzzleData.data.success_message`.
- `client/shared/puzzle_types/sequence_match.js` — **[2b]** PoC puzzle type. `init()`, `applyAssist()`, `getSubmission()`, `destroy()`. Colour buttons, answer track with pips, undo button.
- `client/shared/puzzle_types/circuit_routing.js` — **[2b2]** Canvas drag-to-connect UI. BFS pathfinding (client-side mirror), rAF draw loop, flow animation on valid path, node types (source/target/junction/damaged), `applyAssist` highlights solution path, `getSubmission` returns placed_connections array.
- `client/shared/puzzle_types/frequency_matching.js` — **[2b2]** Oscilloscope canvas (target=amber, player=green waveforms) + amplitude/frequency sliders per component. Live match meter with threshold marker. `applyAssist` widens tolerance + flashes meter, `getSubmission` returns components array.

#### Lobby (`client/lobby/`)
- `index.html`, `lobby.js`, `lobby.css` — role cards, callsign validation, claim/release, host launch, **mission select dropdown** (Sandbox / First Contact / Defend Station / Search & Rescue), sessionStorage callsign persist before redirect

#### Helm (`client/helm/`)
- `index.html`, `helm.js`, `helm.css`
- Two-state interpolation (10Hz→60fps), parallax starfield, compass dial, throttle slider, minimap with enemy contact overlays (hostile chevrons)
- **[7d]**: `ship.hull_hit` → CSS `.hit` flash on `.station-container`; `weapons.beam_fired` → beam line on minimap for `BEAM_FLASH_MS=300`; `game.over` → `showGameOver()`; `showBriefing()` on game.started

#### Engineering (`client/engineering/`)
- `index.html`, `engineering.js`, `engineering.css`
- Ship schematic canvas, power sliders, repair allocation, overclock damage flash
- **[6a]**: `ship.alert_changed` → `setAlertLevel()`
- **[7d]**: `showBriefing()` on game.started; `game.over` → `showGameOver()`
- **[2b2]**: `initPuzzleRenderer(send)` wired — circuit_routing puzzle overlay active. `puzzle.assist_available` → floating `.assist-panel` notification. `puzzle.assist_sent` → confirmation panel with auto-dismiss (4s).

#### Weapons (`client/weapons/`)
- `index.html`, `weapons.js`, `weapons.css`
- 360° tactical radar (range rings, beam arc wedge, enemy wireframe shapes, torpedo dots, beam flash, click-to-target), target info panel, beam hold-to-fire (2Hz), torpedo tubes with reload, shield balance slider
- **[Phase 5]**: switched to sensor.contacts; unknown contacts gracefully shown
- **[7d]**: torpedo trails (ring buffer, `TRAIL_LENGTH=5`, fading blue dots); enemy explosions (3 expanding red wireframe rings, 500ms); `showBriefing()` on game.started; `showGameOver()` on game.over

#### Science (`client/science/`)
- `index.html`, `science.js` (now imports `initPuzzleRenderer` — puzzle overlay active), `science.css`
- Long-range sensor canvas (North-up, range rings, unknown/scanned contact rendering), contact list, scan progress bar, scan results panel, sensor power/efficiency display
- **[7c]**: signal pseudo-contact injected into contact list when `signalScanCount < 2`; bearing lines drawn on sensor canvas after each signal scan; numeric bearing readout; `mission.signal_bearing` handler; `showBriefing()` + `showGameOver()`

#### Captain (`client/captain/`)
- `index.html`, `captain.js`, `captain.css` — **[Phase 6] FULL**
- Tactical map canvas (North-up, enemies/torpedoes with wireframe shapes, ship chevron)
- Alert buttons [GRN][YEL][RED] → `captain.set_alert` → `ship.alert_changed` broadcast to all stations
- Ship status panel: hull gauge, shield gauges, power budget
- Science summary: active scan progress, last scan result + weakness
- Mission objectives panel: real-time updates from `mission.objective_update`
- **[7d]**: torpedo trails; `ship.hull_hit` → CSS `.hit` flash; `showBriefing()` on game.started; stats in existing HTML game-over overlay

#### Comms (`client/comms/`) **[2c.5]**
- `index.html`, `comms.js`, `comms.css`
- Frequency scanner canvas: horizontal frequency axis (0.0–1.0), faction signal blips (imperial/rebel/alien/emergency with unique colours), draggable tuner line, noise baseline static effect
- Faction bands auto-detected (BAND_TOLERANCE ±0.05): badge shows tuned faction name in faction colour
- Hailing interface: shows faction contact controls (contact-id input + NEGOTIATE/DEMAND/BLUFF buttons) only when tuned to a faction band; greyed hint when not tuned
- Transmission log: rolling last-10 entries, colour-coded by type (incoming=green border, intercepted=amber italic)
- Assist panel: shows `puzzle.assist_available` notifications (Science frequency puzzle) with instructions; auto-hides after 15s
- `initPuzzleRenderer(send)` wired for `transmission_decoding` puzzle overlay
- `puzzle.assist_sent` notifies Comms when relay_frequency was applied to Science
- Handles: `comms.state`, `comms.npc_response`, `puzzle.assist_available`, game lifecycle messages

#### Security (`client/security/`) **[2c.3 + 2c.4]**
- `index.html`, `security.js`, `security.css`
- Ship interior canvas: 5-row × 4-column room grid, connection lines (dashed red when door sealed), room state colour-coding (normal=green, damaged=amber, decompressed=grey, fire=orange, hostile=red)
- Marine squad tokens: blue circles with member count, offset for multiple squads in same room
- Intruder tokens: red circles with `!`, fog-of-war filtered server-side
- Click interaction: click room → select squad in room; with squad selected → click target room → `security.move_squad` (deselects after send); click own room → deselect (works during both planning and boarding)
- Door control sidebar: appears when squad selected and boarding active; dropdown of own room + adjacent rooms with `[SEALED]` tag; TOGGLE button → `security.toggle_door` (now dynamically recreated in renderSidebar)
- **Planning phase [2c.4]**: `puzzle.started` (tactical_positioning) → threat markers drawn on canvas (orange fill + "THREAT" for spawn rooms, red X + "OBJ" for objective rooms); countdown badge "POSITIONING — XXs"; COMMIT POSITIONS button → `puzzle.submit {confirmed: true}`; client-side countdown via setInterval. `puzzle.result` clears planning state.
- Sidebar: squad cards (health gauge, AP gauge, member count, room name); intruder contacts (location + objective + health gauge); boarding/planning status badge with pulse animation
- `interior_layout` (static) from `game.started`; `security.interior_state` (dynamic) from each tick

#### Viewscreen (`client/viewscreen/`)
- `index.html`, `viewscreen.js`, `viewscreen.css` — **[Phase 7a] FULL**
- Third-person forward view: starfield parallax, contact chevrons with range text, torpedo dots with trails (5-point ring buffer), beam flash lines (orange/magenta per type), shield arc impact effect at hull hit, explosion rings (500ms, 3 expanding circles)
- `showBriefing()` on game.started; game.over overlay with duration/hull stats + Return to Lobby link

### Tests
- `tests/test_messages.py` — 28 tests
- `tests/test_connections.py` — 21 tests
- `tests/test_lobby.py` — 29 tests (2 added Phase 7c for signal_location in game.started)
- `tests/test_main.py` — 13 tests
- `tests/test_math_helpers.py` — 13 tests
- `tests/test_ship.py` — 15 tests
- `tests/test_physics.py` — 22 tests
- `tests/test_game_loop.py` — 28 tests
- `tests/test_engineering.py` — 18 tests
- `tests/test_ai.py` — 23 tests
- `tests/test_combat.py` — 22 tests (unmodified; crew logic uses rng.choice → "engines" is not a valid deck key → graceful no-op in existing tests)
- `tests/test_crew.py` — **[2a.1]** 31 tests (DeckCrew.crew_factor, CrewRoster defaults + apply/treat methods, Ship.update_crew_factors integration)
- `tests/test_interior.py` — **[2a.1]** 19 tests (make_default_interior, find_path basic + cross-deck + sealed + decompressed)
- `tests/test_security_models.py` — **[2c.1]** 58 tests (constants, AP regen/deduction, casualties, intruder move timer, combat, pathfinding, fog-of-war, ShipInterior fields)
- `tests/test_security_loop.py` — **[2c.2]** 50 tests (reset, start_boarding, move_squad, toggle_door, tick_security AP/movement/combat/events, build_interior_state fog-of-war, Ship.interior field)
- `tests/test_medical.py` — **[2a.2]** 21 tests (glmed module functions, handle_medical_message validate+queue, ship defaults)
- `tests/test_puzzle_engine.py` — **[2b]** 39 tests (SequenceMatchPuzzle generate/validate/assist; PuzzleEngine lifecycle, timeout, submit, assist, cancel, multi-puzzle, reset)
- `tests/test_puzzle_mission.py` — **[2b]** 11 tests (puzzle_completed/failed triggers, notify_puzzle_result, pop_pending_puzzle_starts, full lifecycle integration)
- `tests/test_circuit_routing.py` — **[2b2]** 44 tests (grid helpers, generate at each difficulty, validate_submission, apply_assist, engine integration)
- `tests/test_frequency_matching.py` — **[2b2]** 35 tests (waveform helpers, generate params, validate_submission, apply_assist, engine integration)
- `tests/test_assist_chain.py` — **[2b2]** 10 tests (_check_sensor_assist conditions + one-shot, mission engine list on_complete)
- `tests/test_tactical_positioning.py` — **[2c.4]** 31 tests (TacticalPositioningPuzzle generate/validate/assist, deploy_squads, start_boarding empty squads, PuzzleEngine params forwarding, puzzle_resolved trigger, pop_pending_deployments, tick_mission deploy_squads, integration)
- `tests/test_transmission_decoding.py` — **[2c.5]** 39 tests (TransmissionDecodingPuzzle generate/validate/assist, relay_data capture, FrequencyMatchingPuzzle relay_frequency assist, game_loop_comms module, lobby comms role, handler registration, message schemas)
- `tests/test_triage.py` — **[2c.6]** 42 tests (TriagePuzzle generate/validate/assist, game_loop_medical disease mechanics, game_loop_mission start_outbreak, plague_ship mission loadable)
- `tests/test_torpedo_types.py` — **[c.8]** 40 tests (torpedo types/damage constants, tube loading, fire by type, nuclear auth, EMP stun/decay/fire-block, probe scan, nuclear hits, deep_strike mission)
- `tests/test_route_calculation.py` — **[c.8]** 65 tests (RouteCalculationPuzzle generate/validate/assist, hazard model, BFS path, nebula_crossing mission)
- `tests/test_firing_solution.py` — **[c.8]** 35 tests (FiringSolutionPuzzle generate/validate/assist, intercept bearing, captain log, engine integration)
- `tests/test_diplomatic_summit.py` — **[c.9]** 51 tests (mission load/structure, objective chain via MissionEngine, balance validation for all 8 puzzle types)
- `tests/test_weapons.py` — 12 tests
- `tests/test_sensors.py` — 24 tests
- `tests/test_science.py` — 5 tests
- `tests/test_captain.py` — **[Phase 6]** 7 tests
- `tests/test_mission_engine.py` — **[Phases 6–7]** 46 tests (all mission triggers, loader, spawn, wave logic, signal triangulation, proximity_with_shields)
- `tests/test_ai.py` — 26 tests

**Total: 948 tests** ✓ (verified by pytest run 2026-02-19)

## What Works (v0.01)

- `python run.py` starts the server; LAN URL printed; visits `/` returns status JSON
- Full lobby flow: connect → callsign → claim/release role → host selects mission → launch
- Role reclaim on reconnect (sessionStorage callsign → lobby.claim_role on station WS connect)
- Mission select: Sandbox / First Contact / Defend Station / Search & Rescue
- Briefing overlay on all 6 stations (auto-dismiss 15s, click to dismiss)
- **Helm**: heading/throttle control, parallax starfield, compass, minimap with contact overlays, beam flash on minimap, hull-hit flash
- **Engineering**: ship schematic, power sliders, repair allocation, hull-hit flash
- **Weapons**: 360° tactical radar, click-to-target, beam hold-to-fire, torpedo tubes, shield balance, torpedo trails, explosions, hull-hit flash
- **Science**: long-range sensor canvas, contact scanning, scan results + weakness, signal triangulation bearing lines (Mission 3)
- **Captain**: tactical map, alert level control (all stations shift colour), science summary panel, objective status panel, torpedo trails
- **Viewscreen**: third-person forward view, contact chevrons, torpedo trails, beam flashes, shield impact arc, explosions
- Alert level broadcast: Captain → `ship.alert_changed` → all 5 stations update theme colour simultaneously
- **Mission Engine** (sequential objectives):
  - Sandbox: free play, continuous spawns, no objectives, no game.over from engine
  - First Contact: patrol → scan scout → destroy all → return; victory on all 4 complete
  - Defend Station: 3 enemy waves + station protection; victory after wave 3 cleared with station alive; defeat if station destroyed or hull zero
  - Search & Rescue: signal triangulation (2 bearing scans ≥ 8 000 units apart), asteroid field navigation, shields-held-in-range for 10s; victory on rescue complete
- `game.over { result, stats: {duration_s, hull_remaining} }` on all stations — victory or defeat
- Return to Lobby button on all game-over overlays; server lobby resets when game ends (reconnecting clients get lobby state, not game.started replay)
- Enemy AI: idle/chase/attack/flee, 3 types (scout/cruiser/destroyer), type-differentiated movement, beam fire with arc check, flee+despawn
- Full combat pipeline: weapon → shield hemisphere absorption → hull → 25% system damage roll
- Sensor range scales with Engineering power allocation; info asymmetry enforced (world.entities vs sensor.contacts)
- **331 pytest tests pass**

## Known Limitations (v0.01)

- **No audio** — `client/shared/audio.js` is a placeholder; no sound effects or music
- **No tablet layout verification** — styles are written mobile-first at 768px min, but not tested on physical hardware
- **No automated end-to-end tests** — mission flow is integration-tested at unit level; no Playwright/Selenium suite
- **Single session** — one game at a time; multi-game support would require session namespacing
- **No reconnect mid-game** — reconnecting during a game replays `game.started` (correct) but role reclaim depends on the player having the same callsign in sessionStorage; if another player has claimed the role in the interim, the reconnect fails silently
- **Sandbox has no game.over** — infinite play; only hull-zero defeat fires
- **No mission timer** — no time-based pressure for any mission; Defend Station relies on wave count, not elapsed time
- **Captain tactical map has no waypoints** — objective positions not rendered on the map; text in objective panel is the only waypoint cue
- **Science bearing lines never clear** — stored for session lifetime; closing/reopening doesn't wipe them

## Phase Gate Checklists

### Phases 1–5: COMPLETE ✓
(see archived git history or earlier STATE.md versions)

### Phase 6 Gate: COMPLETE ✓
- [x] `captain.set_alert` → all stations shift colour simultaneously
- [x] Captain tactical map shows all enemies with wireframe shapes
- [x] Captain science summary updates during/after scans
- [x] Captain mission objectives panel updates in real time
- [x] First Contact completable start to finish
- [x] `game.over { result: "victory" }` fires after final objective
- [x] `game.over { result: "defeat" }` fires when hull → 0
- [x] Sandbox still works (no JSON required)
- [x] 6 captain tests pass

### Phase 7 Gate (v0.01): COMPLETE ✓
- [x] Viewscreen: forward view with contacts, torpedo trails, beam flashes, shield impact, explosions
- [x] Defend Station: 3 waves + station entity; victory/defeat from station health
- [x] Search & Rescue: signal triangulation (science bearing lines), asteroid field, proximity_with_shields
- [x] Briefing overlay on ALL 6 stations (game.started → auto-dismiss 15s)
- [x] Victory/defeat overlay on ALL 6 stations with duration + hull remaining
- [x] Return to Lobby button on all game-over overlays
- [x] Server resets after game ends (reconnecting clients see lobby, not stale game.started)
- [x] `game.over` stats: `{duration_s, hull_remaining}` from `_build_game_stats()`
- [x] Lobby mission select: all 4 missions (Sandbox + 3 story missions)
- [x] Torpedo trails on Weapons and Captain
- [x] Hull-hit flash on ALL stations
- [x] Beam flash on Helm minimap
- [x] Enemy explosions on Weapons radar
- [x] 331 tests pass
- [x] README.md updated for v0.01
- [x] STATE.md marked v0.01 COMPLETE

### v0.02b2 Gate: COMPLETE ✓
- [x] `circuit_routing.py` — generate + validate + assist; all 5 difficulties solvable
- [x] `frequency_matching.py` — waveform generation + RMS validation + widen_tolerance assist
- [x] Engineering station wired: `initPuzzleRenderer(send)` + `puzzle.assist_available/sent` handlers
- [x] Cross-station assist chain: `_check_sensor_assist()` fires once when sensors ≥ 120%
- [x] Mission engine `on_complete` supports list of actions (backward-compatible)
- [x] `engineering_drill.json` — fires both puzzles simultaneously via list on_complete
- [x] `client/shared/puzzle_types/circuit_routing.js` + `frequency_matching.js` implemented
- [x] 541 tests pass; 0 regressions (v0.02b2)
- [x] 599 tests pass; 0 regressions (v0.02c.1 Security models)
- [x] 649 tests pass; 0 regressions (v0.02c.2 Boarding event system)

### v0.02 Gate (FULL): COMPLETE ✓ — 2026-02-19
- [x] 948 tests pass; 0 regressions from v0.01 baseline (331 tests)
- [x] All 8 stations functional: captain, helm, weapons, engineering, science, medical, security, comms
- [x] All 8 puzzle types: sequence_match, circuit_routing, frequency_matching, tactical_positioning, transmission_decoding, triage, route_calculation, firing_solution
- [x] All 7 client puzzle renderers present (tactical_positioning rendered in security.js; 7 overlay JS files for other 7 types)
- [x] All 11 JSON missions present + sandbox (synthetic — no JSON file, handled in loader.py)
- [x] Cross-station assist chains: Engineering→Science (sensor power), Comms→Science (relay_frequency), Captain→Weapons (log_entry), Weapons→Helm (weapon_stagger)
- [x] `puzzle_resolved` trigger type supports either success OR failure (for mission branching)
- [x] `deploy_squads` pre-planning phase: squads placed before boarding starts
- [x] Game event logger: JSONL output, logs/ dir, STARBRIDGE_LOGGING env var, never raises, integrated across 5 server files
- [x] Diplomatic Summit: 9-objective flagship mission exercising all 7 active puzzle types
- [x] Torpedo types: standard/emp/probe/nuclear + per-tube loading + nuclear auth flow
- [x] Disease outbreak mechanics: `triage` puzzle + `start_outbreak` action + deck infection spread
- [x] Comms station: frequency scanner, hailing, NPC responses, passive interception
- [x] Security station: boarding, squad movement, door control, fog-of-war filtering, AP system
- [x] Medical station: crew treatment, heal-over-time, resupply at station docking
- [x] All stations handle `ship.alert_changed` (captain → all stations)
- [x] All stations handle `game.started` briefing overlay + `game.over` result overlay
- [x] Lobby: all 8 roles listed; mission select covers all playable missions
- [x] README.md accurate for v0.02 feature set
- [x] All .ai/ state files updated (STATE.md, DECISIONS.md, LESSONS.md, CONVENTIONS.md, PHASE_CURRENT.md)
- [x] Commit: fe339fc "v0.02h: Security, Comms, Medical expansion, 8 puzzle types, Diplomatic Summit, game event logger"

**Known gaps at v0.02 close (not blocking)**:
- No audio — audio.js is a placeholder
- No tablet layout verification on physical hardware
- No automated end-to-end tests (Playwright/Selenium)
- `missions/sandbox.json` in old file manifest was always wrong — sandbox is synthetic
- Science bearing lines never clear (session-lifetime storage in science.js)

## File Manifest (v0.02 — updated 2026-02-19)

> Note: this manifest reflects v0.02 COMPLETE. The "v0.01" label below is from the original template.

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
│   ├── game_loop.py          (orchestrator; security + comms + puzzle handling wired)
│   ├── game_loop_physics.py  [0.1a — TICK_RATE/TICK_DT constants]
│   ├── game_loop_weapons.py  [0.1a — weapons state + helpers]
│   ├── game_loop_mission.py  [0.1a — mission state + broadcast builders]
│   ├── game_loop_medical.py  [2a.2 — treatment state + tick]
│   ├── game_loop_security.py [2c.2 — boarding state + tick]
│   └── game_loop_comms.py    [2c.5 — comms state + tick]
│   ├── helm.py
│   ├── engineering.py
│   ├── weapons.py
│   ├── science.py
│   ├── captain.py            [Phase 6]
│   ├── medical.py            [2a.2]
│   ├── security.py           [2c.2]
│   ├── comms.py              [2c.5]
│   ├── game_logger.py        [c.9+]
│   ├── lobby.py
│   ├── connections.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── ship.py           (_crew_factor + crew + update_crew_factors() added 2a.1)
│   │   ├── world.py          (Station, Asteroid, Hazard added; ENEMY_TYPE_PARAMS)
│   │   ├── mission.py        [0.1b]
│   │   ├── crew.py           [2a.1]
│   │   ├── interior.py       [2a.1]
│   │   ├── security.py       [2c.1 — MarineSquad, Intruder, constants, fog-of-war]
│   │   └── messages/         [0.1b — split into namespace package]
│   │       ├── __init__.py   (re-exports all symbols)
│   │       ├── base.py       (Message, validate_payload)
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
│   │   ├── loader.py         [Phase 6]
│   │   └── engine.py         [Phase 6–7; list on_complete added 2b2]
│   ├── puzzles/
│   │   ├── __init__.py
│   │   ├── base.py                    [2b]
│   │   ├── engine.py                  [2b; submit→_resolved fix 2b2]
│   │   ├── sequence_match.py          [2b]
│   │   ├── circuit_routing.py         [2b2]
│   │   ├── frequency_matching.py      [2b2]
│   │   ├── tactical_positioning.py    [2c.4]
│   │   ├── transmission_decoding.py   [2c.5]
│   │   ├── triage.py                  [2c.6]
│   │   ├── route_calculation.py       [c.8]
│   │   └── firing_solution.py         [c.8]
│   └── utils/
│       ├── __init__.py
│       └── math_helpers.py
├── client/
│   ├── shared/
│   │   ├── connection.js
│   │   ├── renderer.js
│   │   ├── theme.css         (puzzle CSS added 2b2)
│   │   ├── ui_components.js  (showBriefing, showGameOver added Phase 7)
│   │   ├── audio.js          (placeholder)
│   │   ├── puzzle_renderer.js [2b; successMessage 2b2]
│   │   └── puzzle_types/
│   │       ├── sequence_match.js          [2b]
│   │       ├── circuit_routing.js         [2b2]
│   │       ├── frequency_matching.js      [2b2]
│   │       ├── transmission_decoding.js   [2c.5]
│   │       ├── triage.js                  [2c.6]
│   │       ├── route_calculation.js       [c.8]
│   │       └── firing_solution.js         [c.8]
│   ├── lobby/
│   │   ├── index.html
│   │   ├── lobby.js          (mission select added Phase 7)
│   │   └── lobby.css
│   ├── captain/
│   │   ├── index.html        [Phase 6 — full]
│   │   ├── captain.js        [Phase 6 — full, torpedo trails Phase 7]
│   │   └── captain.css       [Phase 6 — full]
│   ├── helm/
│   │   ├── index.html
│   │   ├── helm.js           (hull_hit, beam_fired, game.over, briefing added Phase 7)
│   │   └── helm.css
│   ├── weapons/
│   │   ├── index.html
│   │   ├── weapons.js        (torpedo trails, explosions, briefing added Phase 7)
│   │   └── weapons.css
│   ├── engineering/
│   │   ├── index.html
│   │   ├── engineering.js    (alert_changed Phase 6; briefing, game.over Phase 7; puzzle+assist 2b2)
│   │   └── engineering.css   (assist-panel CSS added 2b2)
│   ├── science/
│   │   ├── index.html
│   │   ├── science.js        (bearing lines, signal contact Phase 7c; briefing, showGameOver Phase 7)
│   │   └── science.css
│   ├── medical/              [2a.2]
│   │   ├── index.html
│   │   ├── medical.js
│   │   └── medical.css
│   ├── security/             [2c.3 + 2c.4]
│   │   ├── index.html
│   │   ├── security.js
│   │   └── security.css
│   ├── comms/                [2c.5]
│   │   ├── index.html
│   │   ├── comms.js
│   │   └── comms.css
│   └── viewscreen/
│       ├── index.html        [Phase 7a — full]
│       ├── viewscreen.js     [Phase 7a — full, briefing Phase 7]
│       └── viewscreen.css    [Phase 7a — full]
├── missions/                    (sandbox is synthetic — no JSON file)
│   ├── first_contact.json        [Phase 6]
│   ├── defend_station.json       [Phase 7b]
│   ├── search_rescue.json        [Phase 7c]
│   ├── puzzle_poc.json           [2b]
│   ├── engineering_drill.json    [2b2]
│   ├── boarding_action.json      [2c.4]
│   ├── first_contact_protocol.json [2c.5]
│   ├── plague_ship.json          [2c.6]
│   ├── nebula_crossing.json      [c.8]
│   ├── deep_strike.json          [c.8]
│   └── diplomatic_summit.json    [c.9]
├── docs/
│   ├── MESSAGE_PROTOCOL.md
│   ├── MISSION_FORMAT.md
│   ├── STYLE_GUIDE.md
│   └── SCOPE.md
├── tests/
│   ├── __init__.py
│   ├── test_messages.py           — 28 tests
│   ├── test_connections.py        — 21 tests
│   ├── test_lobby.py              — 31 tests
│   ├── test_main.py               — 13 tests
│   ├── test_math_helpers.py       — 13 tests
│   ├── test_ship.py               — 15 tests
│   ├── test_physics.py            — 22 tests
│   ├── test_game_loop.py          — 28 tests
│   ├── test_engineering.py        — 18 tests
│   ├── test_ai.py                 — 26 tests
│   ├── test_combat.py             — 22 tests
│   ├── test_crew.py               — 31 tests  [2a.1]
│   ├── test_interior.py           — 19 tests  [2a.1]
│   ├── test_security_models.py    — 58 tests  [2c.1]
│   ├── test_security_loop.py      — 50 tests  [2c.2]
│   ├── test_medical.py            — 21 tests  [2a.2]
│   ├── test_weapons.py            — 12 tests
│   ├── test_sensors.py            — 24 tests
│   ├── test_science.py            — 5 tests
│   ├── test_captain.py            — 7 tests   [Phase 6]
│   ├── test_mission_engine.py     — 46 tests  [Phases 6–7]
│   ├── test_puzzle_engine.py      — 39 tests  [2b]
│   ├── test_puzzle_mission.py     — 11 tests  [2b]
│   ├── test_circuit_routing.py    — 44 tests  [2b2]
│   ├── test_frequency_matching.py — 35 tests  [2b2]
│   ├── test_assist_chain.py       — 10 tests  [2b2]
│   ├── test_tactical_positioning.py — 31 tests [2c.4]
│   ├── test_transmission_decoding.py — 39 tests [2c.5]
│   ├── test_triage.py             — 42 tests  [2c.6]
│   ├── test_torpedo_types.py      — 40 tests  [c.8]
│   ├── test_route_calculation.py  — 65 tests  [c.8]
│   ├── test_firing_solution.py    — 35 tests  [c.8]
│   └── test_diplomatic_summit.py  — 51 tests  [c.9]
├── pytest.ini
├── requirements.txt
├── run.py
└── README.md
```
