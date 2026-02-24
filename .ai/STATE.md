# Project State

> **LIVING DOCUMENT** — Update after every AI engineering session.
> This is the single source of truth for what exists in the project.

**Last updated**: 2026-02-24 (v0.06-crew COMPLETE — Individual Crew System)
**Current phase**: v0.06-crew COMPLETE ✓ — v0.06 in progress
**Overall status**: 3513 tests passing. 12 stations (11 active + viewscreen passive).
33 JSON missions (21 story + 12 training) + sandbox — all in graph format. 9 puzzle types.
7 ship classes. 4 difficulty presets (28 fields, fully wired). Mission editor. Save/resume. Player profiles. Admin dashboard.
Accessibility pass (colour-blind mode, reduced-motion, keyboard nav) across all 19 pages.
Game event logger (JSONL) + Debrief Dashboard + Captain's Replay.
MissionGraph engine (parallel/branch/conditional nodes) — all missions use graph format.
5 space creature types (void_whale, rift_stalker, hull_leech, swarm, leviathan) with per-type AI.
Sector system (5×5 + 8×8 grids, FoW, sector scanning). Space stations (docking, services, enemy stations with AI).
8 torpedo types. Environmental hazards. Station assault missions. Creature missions.
Landing page + site docs. 4-facing shield system. Full difficulty wiring. Individual crew roster with reassignment.

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
- `server/models/ship.py` — `ShipSystem` (name, power, health, `_crew_factor=1.0`, `efficiency = (power/100)*(health/100)*_crew_factor`), `Shields` (front, rear), `Ship` dataclass (position, heading, target_heading, velocity, throttle, `hull`, **[v0.05f]** `hull_max=100.0` set from ship class, `docked_at: str|None=None`, shields, 9 systems, alert_level, crew, medical_supplies=20, `interior`). `Ship.update_crew_factors()` propagates deck crew factors to systems each tick.
- `server/models/crew.py` — `DeckCrew` (deck_name, total, active, injured, critical, dead, `crew_factor` property). `CrewRoster` (decks dict, `apply_casualties`, `treat_injured`, `treat_critical`, `get_deck_for_system`). `DECK_SYSTEM_MAP`. `DECK_DEFAULT_CREW`.
- `server/models/interior.py` — `Room` (id, name, deck, position, connections, state, door_sealed). `ShipInterior` (rooms dict, `find_path()` BFS pathfinding, `marine_squads: list[MarineSquad]`, `intruders: list[Intruder]`). `make_default_interior()` — 5 decks, 20 rooms.
- `server/models/security.py` — `MarineSquad`, `Intruder`, constants. `is_intruder_visible()` fog-of-war filter.
- `server/models/world.py` — `World` dataclass **[v0.05i]** + `StationComponent`, `ShieldArc`, `Turret`, `TorpedoLauncher`, `FighterBay`, `SensorArray`, `StationReactor`, `EnemyStationDefenses`; `_arc_covers()`; `Station.defenses: EnemyStationDefenses|None`; `spawn_enemy_station(id, x, y, variant)` outpost(2gen/4turr/1launcher/1bay/10garrison/800hp) or fortress(4/8/2/2/20/1200hp); `Enemy.type` includes "fighter"; "fighter" in `ENEMY_TYPE_PARAMS` (20hp, 400u/s, no shields, flee_threshold=0).
- `server/models/interior.py` — `make_station_interior(station_id)` 8-room layout (command, bay, corridor, reactor, armoury, gen_a, gen_b, quarters); prefixed by station_id.
- `server/models/world.py` — `World` dataclass (width, height, ship, enemies, torpedoes, stations, asteroids, hazards, sector_grid). `Enemy`, `Torpedo`, `Station`, `Asteroid`, `Hazard` dataclasses. `ENEMY_TYPE_PARAMS` dict. `spawn_enemy()` factory. **[v0.05e]** `Station` expanded with `name`, `station_type`, `faction`, `services`, `docking_range/ports`, `transponder_active`, `shields/max`, `hull/max`, `inventory`, `requires_scan`. Constants: `STATION_TYPE_SERVICES`, `STATION_TYPE_HULL`, `STATION_TYPE_SHIELDS`, `STATION_FEATURE_TYPES`, `_FEATURE_TO_STATION`. Factories: `spawn_station()`, `spawn_station_from_feature(feature, sector_name)`, `spawn_station_from_grid(station_id, x, y)`, `spawn_hazard()`.
- `server/models/ship_class.py` — **[v0.03o]** `ShipClass` Pydantic model (id, name, description, max_hull, torpedo_ammo, min_crew, max_crew). `load_ship_class(id)` reads `ships/<id>.json`; raises FileNotFoundError if missing. `list_ship_classes()` returns all 7 in canonical order. `SHIP_CLASS_ORDER = ["scout","corvette","frigate","cruiser","battleship","medical_ship","carrier"]`.
- `server/models/mission.py` — Pydantic schema documentation models (not used at runtime).
- `server/utils/math_helpers.py` — `wrap_angle`, `angle_diff`, `distance`, `lerp`, `bearing_to`
- `server/difficulty.py` — **[v0.03]** `DifficultyPreset` dataclass (enemy_damage_mult, puzzle_time_mult, hints_enabled, spawn_rate_mult). `PRESETS` dict with 4 named presets. `get_preset(name)` falls back to "officer" for unknown names.
- `server/game_debrief.py` — **[v0.03n]** `parse_log(path)`, `compute_debrief(events)`, `compute_from_log(path)`. Returns `{per_station_stats, awards, key_moments, timeline}`. 12 threshold-based awards. Tracks hull milestones (75/50/25%), key moments (objective completions, critical hits), timeline from tick_summary x/y.
- `server/game_logger.py` — `GameLogger` class + module-level singleton. `start_logging()`, `log_event()`, `set_tick()`, `stop_logging()`, `is_logging()`. **[v0.03n]** `get_log_path()` returns active or last-completed path via `_last_log_file` preservation. JSONL format. Writes to `logs/game_YYYYMMDD_HHMMSS.jsonl`. Controlled via `STARBRIDGE_LOGGING` env var (default enabled). Never raises.

#### Systems
- `server/systems/physics.py` — `tick(ship, dt, w, h)`: turn + thrust + move + boundary clamp
- `server/systems/combat.py` — `beam_in_arc`, `apply_hit_to_player` (crew casualties: `int(hull_damage/5)` via rng.choice), `apply_hit_to_enemy`, `regenerate_shields(ship, hazard_modifier=1.0)`. `CREW_CASUALTY_PER_HULL_DAMAGE=5.0`. **[v0.05h]** `hazard_modifier` scales shield regen rate.
- `server/systems/ai.py` — `tick_enemies(enemies, ship, dt, sensor_modifier=1.0)`. State machine (idle→chase→attack→flee). Type-differentiated movement. `AI_TURN_RATE=90°/s`. **[v0.05h]** `sensor_modifier` scales enemy detect_range for nebula concealment.
- `server/systems/sensors.py` — `ActiveScan` dataclass. Scan lifecycle, range calculations, contact filtering, weakness computation. **[v0.05h]** `sensor_range(ship, hazard_modifier=1.0)` and `build_sensor_contacts(..., hazard_modifier=1.0)`.
- `server/systems/station_ai.py` — **[v0.05i]** Enemy station defensive AI. `tick_station_ai(stations, ship, world, dt, station_attacked_ids)` → `(beam_hits, launched_fighters, reinforcement_calls)`. Turrets auto-fire at ship in range+arc scaled by reactor_factor. Launchers fire standard torpedoes. Fighter bays launch fighters (spawn_enemy("fighter",...)). Sensor array emits distress_call when attacked+active+not-jammed. `jam_station_sensor()` / `unjam_station_sensor()`. `STATION_TORPEDO_VELOCITY=400`.
- `server/systems/hazards.py` — **[v0.05h]** Full environmental hazard system. Entity hazards (minefield, radiation_zone, gravity_well, nebula) + sector-type hazards (nebula, asteroid_field, gravity_well, radiation_zone). Module-level modifier state: `_sensor_modifier`, `_shield_regen_modifier`, `_velocity_cap`, `_active_hazard_types`. Public API: `reset_state()`, `get_sensor_modifier()`, `get_shield_regen_modifier()`, `get_velocity_cap()`, `get_active_hazard_types()`. `tick_hazards(world, ship, dt)` applies entity + sector effects and stores modifiers. Constants: `NEBULA_ENTITY_SENSOR_MODIFIER=0.5`, `NEBULA_SHIELD_REGEN_MODIFIER=0.5`, `ASTEROID_THROTTLE_THRESHOLD=30.0`, `ASTEROID_DAMAGE_PER_SEC=2.0`, `GRAVITY_WELL_SECTOR_VEL_CAP=200.0`, `RADIATION_SECTOR_DAMAGE_PER_SEC=1.5`, `RADIATION_SHIELD_THRESHOLD=50.0`, `RADIATION_SHIELD_ABSORPTION_FRAC=0.6`, `RADIATION_SENSOR_MODIFIER=0.75`.
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
- `server/captain.py` — Direct broadcast handler for all `captain.*` messages. `init(manager, ship, queue)` — queue enables forwarding. Handles `set_alert`, `system_override`, `save_game`, `reassign_crew` directly; forwards `authorize`, `add_log`, `undock` to game loop queue via `_QUEUE_FORWARDED_TYPES`. **[v0.06-crew]** Routing fix: all captain.* messages route here via main.py `_HANDLERS` map (NOT via `_drain_queue`). `game_loop_captain.py` sub-module for captain-side state.
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
- `server/game_loop_weapons.py` — **[v0.05g]** stateful weapons: **[v0.05i]** component targeting: `fire_player_beams` handles component IDs and station hull IDs in addition to enemy IDs. Shield-arc absorption (80%) on station hull hits. Component hit: reduces `component.hp`, adds to `_stations_attacked_this_tick`, emits `_pending_component_destroyed` on hp→0. `pop_stations_attacked()→set`, `pop_component_destroyed_events()→list`. `tick_torpedoes` now hits hostile station hulls (500-unit radius, shield arc absorption).
- `server/game_loop_security.py` — **[v0.05i]** station boarding: `start_station_boarding(station, squad_specs)` populates garrison as intruders in station interior; `tick_station_boarding(ship, dt)→events`; `is_station_boarding_active()`; `check_station_capture(station_id)→bool` (all intruders defeated + squad in command room); `build_station_interior_state(station_id)→dict`.
- `server/game_loop_ew.py` — **[v0.05i]** EW tick also jams station sensor arrays: if `_jam_target_id` ends with `_sensor` and matches a station component, sets `jammed=True` when in range; clears when untargeted.
- `server/game_loop.py` — **[v0.05i]** imports `tick_station_ai`; after enemy tick: pops `station_attacked_ids`, calls `tick_station_ai`, appends fighters to `world.enemies`, broadcasts `station.reinforcement_call`, `station.component_destroyed`, `station.captured`, `station.destroyed`; calls `tick_station_boarding`; broadcasts `security.station_interior` when station boarding active. **[v0.05j]** Station capture: sets `station.captured = True` on first detection, calls `glm.get_mission_engine().notify_station_captured(station.id)` to notify mission graph. Guard prevents repeated broadcast/notification each tick.
- `server/game_loop_weapons.py` — **[v0.05g]** stateful weapons: 8 torpedo types (standard/homing/ion/piercing/heavy/proximity/nuclear/experimental); per-type magazine dict (`_torpedo_ammo: dict[str,int]`); `TORPEDO_DAMAGE/VELOCITY/RELOAD_BY_TYPE` dicts; homing guidance (HOMING_TURN_RATE=90°/s); ion drain+stun (ION_STUN_TICKS=100); piercing (shield_absorption_mult=0.25); proximity AOE (PROXIMITY_BLAST_RADIUS=2000u); per-tube reload times (`_tube_reload_times: list[float]`); `reset(initial_loadout)`, `get_ammo()→dict`, `get_ammo_max()→dict`, `get_ammo_for_type(t)`, `set_ammo_for_type(t,n)`, `get_tube_reload_times()→list`; backward compat deserialise for int saves
- `server/game_loop_mission.py` — stateful mission: `init_mission()`, `tick_mission()`, pending actions queue, `get_mission_dict()` returns deep copy. **[v0.05h]** `build_sensor_contacts(..., hazard_modifier=1.0)`. **[v0.05i]** `build_world_entities` station payload includes `defenses` dict (shield_arcs/turrets/launchers/fighter_bays/sensor_array/reactor/garrison_count).
- `server/game_loop_medical.py` — treatment state: `start_treatment()` (costs 2 supplies), `tick_treatments()` (heals 1/deck/2s), `cancel_treatment()`, `get_active_treatments()`
- `server/game_loop_security.py` — boarding state: `deploy_squads()`, `start_boarding()`, `move_squad()`, `toggle_door()`, `tick_security()`, fog-of-war filtered `build_interior_state()`
- `server/game_loop_comms.py` — comms state: frequency tuning, hailing, NPC responses, passive interception fragments. `FACTION_BANDS` dict.
- `server/game_loop_captain.py` — **[v0.03]** captain-side state: strike plan log, nuclear authorisation flow
- `server/game_loop_damage_control.py` — **[v0.03i]** damage control state: hull breach detection, fire suppression, emergency repair priorities, deck pressure status. Backend-only (no dedicated player station page — integrated with Engineering station).
- `server/game_loop_flight_ops.py` — **[v0.03j]** flight operations state: fighter squadron launch/recall, patrol assignment, hangar bay management
- `server/game_loop_ew.py` — **[v0.03k]** electronic warfare state: jamming targets, decoy deployment, network scan results, ECM effectiveness
- `server/game_loop_tactical.py` — **[v0.03l]** tactical state: strike plan management, coordinated fire solutions, mark-target tracking
- `server/game_loop_training.py` — **[v0.03m]** training state: `is_training_active()`, `set_training_flag(flag)`, `reset()`. Station handlers call `set_training_flag()` when training-relevant actions occur (e.g. `helm_heading_set`, `weapons_beam_fired`).
- `server/models/sector.py` — **[v0.05b]** `SectorVisibility` enum (6 levels), `Rect`, `SectorProperties`, `SectorFeature`, `PatrolRoute`, `Sector`, `SectorGrid` dataclasses. `SectorGrid` methods: `sector_at_position()`, `adjacent_sectors()`, `set_visibility()`, `update_ship_position()`, `on_sector_leave()`, `apply_transponder_reveals()`, `serialise()`, `deserialise_visibility()`. `load_sector_grid(layout_id)` reads `sectors/<id>.json`. `_sector_grid_from_dict()` parser.
- `sectors/standard_grid.json` — **[v0.05b]** 5×5 grid (25 sectors, each 100k×100k). A1 is the default gameplay sector; has friendly_station transponder feature. Includes nebula, asteroid_field, radiation_zone, gravity_well, hostile, friendly, contested types.
- `sectors/exploration_grid.json` — **[v0.05b]** 8×8 grid (64 sectors, each 100k×100k).
- `sectors/sector_schema.json` — **[v0.05b]** JSON Schema for sector layout files.
- `server/game_loop_science_scan.py` — **[v0.05d]** sector-scale scan state machine: `reset()`, `is_active()`, `start_scan(scale, mode, sector_id, adjacent_ids)`, `cancel_scan()`, `set_interrupt_response(continue_scan)`, `build_progress() → dict`, `get_scan_indicator() → str|None`, `tick(dt, world) → list[dict]`. Constants: `SECTOR_SWEEP_DURATION=45.0`, `LONG_RANGE_DURATION=150.0`, `PHASE_THRESHOLDS=[0,25,50,75]`, `COMBAT_INTERRUPT_RANGE=15_000`, `MODE_FEATURE_AFFINITY` dict. Events: `progress`, `sector_visibility_changed`, `interrupted`, `complete`. Partial reveals at each phase; SectorVisibility progression (Unknown→Scanned/Surveyed); ACTIVE sectors not downgraded.
- `server/game_loop_docking.py` — **[v0.05f]** docking state machine: `reset()`, `serialise()/deserialise()`, `is_docked()`, `get_state()`, `get_active_services()`, `request_clearance()`, `start_service()`, `cancel_service()`, `captain_undock(emergency)`, `tick(world, ship, manager, dt)`. States: none→clearance_pending→sequencing→docked→undocking→none. Constants: `DOCK_APPROACH_MAX_THROTTLE=10%`, `DOCKING_SEQUENCE_DURATION=10s`, `UNDOCKING_DURATION=5s`, `SHIELDS_DOCKED_CAP=50%`. 10 services with durations (hull_repair 60s → full hull restore; system_repair 20s → all systems 100%; medical_transfer 45s → +10 supplies + stabilise critical; torpedo_resupply 30s → **[v0.05g]** refills all 8 types to max; ew_database_update 30s → +5 charges; others placeholder). Proximity approach_info emitted to Helm when near station (2× docking_range). Physics: velocity/throttle=0, shields capped while docked/sequencing.
- `server/game_loop_sandbox.py` — **[v0.05a]** sandbox activity generator: `reset(active)`, `is_active()`, `tick(world, dt)`. 10 event types covering all 12 stations: `spawn_enemy` (60-90s, Weapons/Helm/Tactical/Science), `system_damage` (45-75s, Engineering/DC), `crew_casualty` (60-100s, Medical), `start_boarding` (120-180s, Security/DC), `incoming_transmission` (90-120s, Comms), `hull_micro_damage` (120-180s, DC), `sensor_anomaly` (90-150s, Science), `drone_opportunity` (120-180s, Flight Ops), `enemy_jamming` (180-240s, EW), `distress_signal` (180-300s, Comms/Helm/Captain). Initial stagger timers ensure all 10 fire within 5 minutes.

#### Individual Crew System (v0.06-crew)
- `server/models/crew_roster.py` — **[v0.06-crew]** `IndividualCrewRoster` with named `CrewMember` instances. `crew_factor_for_duty_station(station)` — accounts for active/injured/dead/medical_bay status, reassignment timer (blocks contribution while > 0), reassignment_effectiveness (0.6 at new post). `reassign_crew(crew_id, new_station)` — 30s transition timer, 60% effectiveness, max 2 reassignments per member, returning to original restores 100%. `tick_reassignments(dt)` counts down timers. Threshold notifications at 75/50/25% crossing. Serialisation via `to_dict()`/`from_dict()`.
- `server/game_loop_medical_v2.py` — **[v0.06-crew]** Medical feedback loop: `treatment.elapsed += dt * max(roster.crew_factor_for_duty_station("medical_bay"), 0.10)`. `get_roster()` public API for captain.py access.
- `server/models/ship.py` — **[v0.06-crew]** `update_crew_factors()` accepts `individual_roster` parameter with 10% minimum floor. Falls back to legacy deck-level system when no individual roster. **[v0.06a]** 4-facing shields (fore/aft/port/starboard, default 50 each); `calculate_shield_distribution(x,y)→dict`; `shield_focus={x,y}` + `shield_distribution`.
- `server/difficulty.py` — **[v0.06-difficulty]** `DifficultyPreset` expanded to 28 fields; all multipliers wired into combat/AI/sensors/hazards/DC/sandbox/docking/scanning/medical/injuries. Admin override endpoint.

#### Mission System (`server/missions/`)
- `server/missions/loader.py` — `load_mission(id)`: reads `missions/<id>.json`; sandbox returns synthetic graph-format dict. **[v0.04b]** Sandbox dict uses graph format: `{nodes:[], edges:[], start_node:None, victory_nodes:[], defeat_condition:None}`.
- `server/missions/engine.py` — `MissionEngine` class. Sequential objectives. **Still used in tests with inline dicts (do not remove).** Trigger types: all standard triggers + `training_flag`.
- `server/mission_graph.py` — **[v0.04a]** `MissionGraph` class. Drop-in replacement for `MissionEngine` with parallel/branch/conditional/checkpoint nodes. Same public interface: `tick(world, ship, dt)`, `pop_pending_actions()`, `notify_puzzle_result(label, success)`, `set_training_flag(flag)`, `record_signal_scan()`, `is_over()`, `get_objectives()`, `get_active_node_ids()`. Mission format: `nodes` (with nested `children` for parallel), `edges`, `start_node`, `victory_nodes`, `defeat_condition` dict. Trigger format: `{"type": "name", ...args}` (flat merge). **[v0.04c]** Bug fix: `_tick_completions` accumulator in `_do_complete_node` ensures parallel parent IDs appear in `tick()` return list when they complete via child completion. **[v0.05j]** New triggers: `station_destroyed`, `station_captured`, `component_destroyed`, `station_sensor_jammed`, `station_reinforcements_called`. Conditional `max_activations: N` (0=unlimited) prevents re-firing after N activations; tracked in `_conditional_activation_count`. `notify_station_captured(station_id)` method adds to `_captured_station_ids`. All new state serialised/deserialised.
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

#### Standard Missions (20 JSON files + sandbox)
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
- **[v0.05j]** `missions/fortress.json` — enemy outpost assault; branch: stealth (jam sensor → dock) vs direct assault (destroy gen_0 → gen_1 → hull < 50% → dock); reinforcement conditional (max_activations=1); victory: station_captured
- **[v0.05j]** `missions/supply_line.json` — parallel: destroy depot + intercept all supply_ ships; conditional resupply waves at t=60/120 (guard: depot alive, max_activations=1); reinforcement conditional; victory: extract
- **[v0.05l]** `missions/migration.json` — creature mission: void whale migration event
- **[v0.05l]** `missions/the_nest.json` — creature mission: rift stalker nest
- **[v0.05l]** `missions/outbreak.json` — creature mission: swarm/hull leech outbreak
- **[v0.05n]** `missions/long_patrol.json` — story mission: extended patrol
- **[v0.05n]** `missions/deep_space_rescue.json` — story mission: deep space rescue
- **[v0.05n]** `missions/siege_breaker.json` — story mission: break a siege
- **[v0.05n]** `missions/first_survey.json` — story mission: first survey

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
- Long-range sensor canvas (North-up), contact list with scan progress, bearing lines for signal triangulation, `initPuzzleRenderer(send)` wired. **[v0.03h]** Multiple scan modes: EM / GRAV / BIO / SUB — each reveals different contact properties. **[v0.05d]** Scan scale selector (TARGETED / SECTOR SWEEP / LONG-RANGE); sector scan sends `science.start_sector_scan {scale, mode}`; sweep progress mirrored in scan bar + radial sweep canvas overlay with phase boundary arcs; combat interrupt overlay (CONTINUE / ABORT); cancel button handles both entity and sector scans; mode buttons locked during sector sweep; `map.scan_indicator` received for Captain/Helm status.

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

| `test_sector_scan.py` | 52 | v0.05d |
| `test_space_stations.py` | 24 | v0.05e |
| `test_docking.py` | 44 | v0.05f |
| `test_torpedo_expansion.py` | ~80 | v0.05g |
| `test_environmental_hazards.py` | 69 | v0.05h |
| `test_enemy_stations.py` | 77 | v0.05i |
| `test_station_assault_missions.py` | 57 | v0.05j |
| `test_creature_missions.py` | ~56 | v0.05k–l |
| `test_sandbox_v2.py` | ~40 | v0.05m |
| `test_story_missions.py` | ~57 | v0.05n |
| `test_gate_v005.py` | 152 | v0.05o |
| `test_shield_focus.py` | 28 | v0.06a |
| `test_difficulty.py` | 69 | v0.06-difficulty (updated) |
| `test_crew_factor.py` | 55 | v0.06-crew |

**Total at v0.04c: 1781 tests** ✓
**Total at v0.05j: 2483 tests** ✓
**Total at v0.05o: 2863 tests** ✓ (v0.05 CLOSED 2026-02-22)
**Total at v0.06-crew: 3513 tests** ✓

### v0.04 Additions (tests/test_gate_v004.py + more)

| File | Tests | Phase |
|------|-------|-------|
| `test_mission_validator.py` | 20 | v0.04d |
| `test_editor_endpoints.py` | 15 | v0.04d |
| `test_profiles.py` | 25 | v0.04g |
| `test_admin_endpoints.py` | 20 | v0.04h |
| `test_gate_v004.py` | 74 | v0.04k |

**Additional tests (save system, terminology, misc)**: ~52 more tests across v0.04e–v0.04f

**Total: 1987 tests** ✓ (verified by pytest run 2026-02-21, post-v0.04k)

---

## v0.04 Additions to What Exists

### New Server Modules (v0.04d–v0.04j)
- `server/mission_validator.py` — **[v0.04d]** `validate_mission(dict) → list[str]`. 9 rules: id/name presence, start_node exists, victory_nodes non-empty, edges reference real nodes, branch ≥2 trigger edges, parallel ≥2 children, BFS reachability check (excluding conditionals), unique puzzle labels.
- `server/save_system.py` — **[v0.04f]** `save_game()`, `list_saves()`, `load_save(id)`, `restore_game(id, world)`. Saves JSON to `saves/{id}.json`. Full ship + world + all module state (12 sub-modules). Serialised/restored dataclasses.
- `server/profiles.py` — **[v0.04g]** `PROFILES_DIR = profiles/`. `get_or_create_profile(name)`, `update_game_result(name, role, result, mission_id, duration_s, station_stats)`, `get_profile(name)`, `list_profiles()`, `export_csv()`. 6 career achievements: first_command, bridge_regular, veteran, sharpshooter, life_saver, explorer.
- `server/admin.py` — **[v0.04h]** `reset()`, `update_interaction(role)`, `get_engagement_status(role)`, `build_engagement_report()`. Constants: IDLE_SECS=30, AWAY_SECS=60. ALL_STATION_ROLES list (12 roles).

### New main.py Endpoints (v0.04d–v0.04j)
- `GET /editor` → redirect to `/client/editor/`
- `GET /editor/missions` → list all missions in missions/ dir
- `GET /editor/mission/{mission_id}` → load single mission JSON
- `POST /editor/validate` → `{"valid": bool, "errors": list[str]}`
- `POST /editor/save` → save mission to missions/ dir; validates id chars; returns warnings
- `GET /admin` → redirect to `/client/admin/`
- `GET /admin/state` → `{game_running, tick, ship, engagement, preset, saved_games}`
- `POST /admin/pause`, `/admin/resume` → 409 if no game running
- `POST /admin/annotate` → log annotation entry
- `POST /admin/broadcast` → broadcast text to all clients
- `POST /admin/difficulty` → change difficulty preset mid-game (validates against PRESETS)
- `POST /admin/save` → save current game (409 if not running)
- `GET /saves` → list saved games
- `GET /saves/{save_id}` → load save metadata
- `POST /saves/resume/{save_id}` → restore game from save
- `POST /profiles/login` → get or create profile
- `GET /profiles/leaderboard` → sorted by games_won
- `GET /profiles/export` → CSV string
- `GET /profiles` → list all profiles
- `GET /profiles/{name}` → single profile

### game_loop.py Additions (v0.04g–v0.04i)
- `_session_players: dict[str, str]` — role→player_name map for profile updates
- `set_session_players(players)` — called from _on_game_start wrapper in main.py
- `_update_profiles(result, stats)` — updates all session players on game-over
- `_paused: bool` — pause state; `pause()`, `resume()`, `is_paused()`
- `_last_dc_state_json: str` — JSON hash for DC state change detection

### game_logger.py Additions (v0.04i)
- `_FLUSH_INTERVAL = 10` — flush every 10 writes (was every write)
- `_pending_writes` counter — tracks writes since last flush

### New Client Directories (v0.04d–v0.04j)
- `client/editor/` — **[v0.04d]** Mission editor SPA: index.html, editor.js, editor.css, graph_renderer.js, node_panel.js, edge_panel.js, trigger_builder.js, entity_placer.js, validator.js, exporter.js
- `client/damage_control/` — **[v0.04e]** Damage control station: index.html, damage_control.js, damage_control.css
- `client/login/` — **[v0.04g]** Player login: index.html, login.js, login.css; callsign input + profile card + leaderboard modal
- `client/admin/` — **[v0.04h]** Admin dashboard: index.html, admin.js, admin.css; 12-panel grid, engagement dots, pause/resume controls

### Shared Accessibility Files (v0.04j)
- `client/shared/settings.js` — `initSettings()`, `getSetting(key)`, `toggleSetting(key)`, `setSetting(key, value)`. localStorage key `starbridge_settings`. Auto-applies `body.cb-mode` and `body.no-motion` classes.
- `client/shared/accessibility.css` — Colour-blind palette (`body.cb-mode`: green→blue, red→orange), reduced motion (`body.no-motion` + `prefers-reduced-motion`), `:focus-visible` keyboard indicators, `.sr-only` utility.
- `client/shared/a11y_widget.js` — Self-injecting floating ⚙ button (bottom-right). Settings panel with toggle switches. Keyboard: Escape closes. `announce(text)` for screen reader live region.
- All 19 HTML pages include accessibility.css + a11y_widget.js.

### Saves Directory
- `saves/` — runtime directory for save JSON files (gitignored)

### Profiles Directory
- `profiles/` — runtime directory for player profile JSON files (gitignored)

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
- 33 missions: 21 story (Sandbox + 20 JSON) + 12 training (one per role)
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

### v0.04 Gate: COMPLETE ✓ — 2026-02-21

- [x] 1987 tests passing; 0 regressions from v0.04c baseline (1781 tests)
- [x] Mission Graph Engine: MissionGraph in game_loop_mission; all 23 missions in graph format
- [x] 4 new graph-native missions (salvage_run, first_contact_remastered, the_convoy, pandemic)
- [x] Mission validator: validate_mission() returns error list
- [x] Editor REST endpoints: /editor/validate, /editor/save, /editor/missions, /editor/mission/{id}
- [x] Mission editor SPA: client/editor/ with 8 JS files
- [x] Damage control station: client/damage_control/ (dedicated page)
- [x] Save system: save_game/list_saves/load_save/restore_game; saves/ dir; lobby resume UI
- [x] Player profiles: profiles.py; 6 achievements; REST API (/profiles/*); login page
- [x] Admin dashboard: admin.py engagement tracking; pause/resume; /admin/* endpoints; client/admin/
- [x] Performance: logger flush batching (10×); DC state change detection; stress_test.py
- [x] Accessibility: settings.js + accessibility.css + a11y_widget.js; wired on all 19 pages
- [x] Health check phase: "v0.04"
- [x] Gate tests: test_gate_v004.py — 74 tests covering all sub-releases

**Known gaps at v0.04 close (not blocking)**:
- No audio (placeholder remains)
- No automated E2E tests
- Admin engage tracking polls at 2s (no server push)
- Profile leaderboard is client-fetch on demand (no live updates)
- medical_ship/carrier still have no differentiated gameplay mechanics

### v0.05 Gate: COMPLETE ✓ — 2026-02-22

- [x] 2863 tests passing; 0 regressions
- [x] Sector system: 5×5 standard + 8×8 exploration grids; 6 visibility levels; FoW; sector scanning (3 scales)
- [x] Space stations: docking state machine; 10 services; physics lockout; save round-trip
- [x] 8 torpedo types: standard/homing/ion/piercing/heavy/proximity/nuclear/experimental
- [x] Environmental hazards: sector-type effects; hazard_modifier on shields/sensors
- [x] Enemy stations: turrets/launchers/fighters; station_ai.py; station boarding
- [x] Station assault missions (fortress, supply_line); 5 new triggers
- [x] Space creatures: 5 types with per-type AI; creature missions (migration, the_nest, outbreak)
- [x] Story missions: long_patrol, deep_space_rescue, siege_breaker, first_survey
- [x] Sandbox overhaul: creature spawn, port/derelict/hazards
- [x] Balance pass: 6 tweaks applied
- [x] Gate tests: test_gate_v005.py — 152 tests

### v0.06 Progress (in progress)

**v0.06a: 2D Shield Focus Control** ✓ (2923 tests)
- 4-facing shields (fore/aft/port/starboard); `calculate_shield_distribution(x,y)`
- `get_hit_facing()` in combat.py; canvas drag UI + lock/centre buttons
- Captain 4-bar shield display; `tests/test_shield_focus.py` (+28 tests)

**v0.06-difficulty: Full Difficulty System Wiring** ✓ (3440 tests)
- DifficultyPreset expanded to 28 fields
- All multipliers wired into combat/AI/sensors/hazards/DC/sandbox/docking/scanning/medical/injuries
- Admin override endpoint; lobby tooltips; debrief display
- `tests/test_difficulty.py` updated (+69 tests)

**v0.06-crew: Individual Crew System** ✓ (3513 tests)
- `server/models/crew_roster.py`: IndividualCrewRoster with named CrewMembers; crew_factor_for_duty_station()
- Crew factor → system effectiveness pipeline with 10% minimum floor
- Medical feedback loop: treatment speed scales with medical crew factor
- Captain crew reassignment: 30s timer, 60% effectiveness, max 2 reassignments
- Captain station crew management UI (ship_status.js panel with dropdowns)
- Captain routing fix: all captain.* messages route via captain.py; queue forwarding for authorize/add_log/undock
- Threshold notifications at 75/50/25% crossing
- `tests/test_crew_factor.py` — 55 tests

---

## File Manifest (updated 2026-02-24)

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
│   │   ├── sector.py         [v0.05b]
│   │   ├── flight_ops.py     [v0.03j]
│   │   ├── crew_roster.py    [v0.06-crew]
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
│   │   ├── sensors.py
│   │   ├── station_ai.py     [v0.05i]
│   │   ├── hazards.py        [v0.05h]
│   │   └── creature_ai.py    [v0.05k]
│   ├── game_loop_science_scan.py [v0.05d]
│   ├── game_loop_docking.py  [v0.05f]
│   ├── game_loop_sandbox.py  [v0.05a]
│   ├── game_loop_creatures.py [v0.05k]
│   ├── game_loop_medical_v2.py [v0.06-crew]
│   ├── mission_graph.py      [v0.04a]
│   ├── save_system.py        [v0.04f]
│   ├── profiles.py           [v0.04g]
│   ├── admin.py              [v0.04h]
│   ├── mission_validator.py  [v0.04d]
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
│   │   ├── settings.js       [v0.04j]
│   │   ├── accessibility.css [v0.04j]
│   │   ├── a11y_widget.js    [v0.04j]
│   │   ├── crew_roster.js    [v0.06-crew]
│   │   ├── crew_roster.css   [v0.06-crew]
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
│   ├── debrief/              [v0.03n]
│   │   ├── index.html
│   │   ├── debrief.js
│   │   └── debrief.css
│   ├── editor/               [v0.04d]
│   ├── damage_control/       [v0.04e]
│   ├── login/                [v0.04g]
│   ├── admin/                [v0.04h]
│   └── site/                 [v0.04l — landing page + docs]
│       ├── site.css
│       ├── index.html
│       ├── manual/
│       ├── faq/
│       └── about/
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
│   ├── pandemic.json         [v0.04c]
│   ├── fortress.json         [v0.05j]
│   ├── supply_line.json      [v0.05j]
│   ├── migration.json        [v0.05l]
│   ├── the_nest.json         [v0.05l]
│   ├── outbreak.json         [v0.05l]
│   ├── long_patrol.json      [v0.05n]
│   ├── deep_space_rescue.json [v0.05n]
│   ├── siege_breaker.json    [v0.05n]
│   └── first_survey.json     [v0.05n]
├── sectors/                     [v0.05b]
│   ├── standard_grid.json
│   ├── exploration_grid.json
│   └── sector_schema.json
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
│   ├── test_graph_missions.py     —  60 [v0.04c]
│   ├── test_sector_scan.py        —  52 [v0.05d]
│   ├── test_space_stations.py     —  24 [v0.05e]
│   ├── test_docking.py            —  44 [v0.05f]
│   ├── test_torpedo_expansion.py  — ~80 [v0.05g]
│   ├── test_environmental_hazards.py — 69 [v0.05h]
│   ├── test_enemy_stations.py     —  77 [v0.05i]
│   ├── test_station_assault_missions.py — 57 [v0.05j]
│   ├── test_gate_v005.py          — 152 [v0.05o]
│   ├── test_shield_focus.py       —  28 [v0.06a]
│   └── test_crew_factor.py        —  55 [v0.06-crew]
├── logs/                          (runtime — .gitignore)
├── pytest.ini
├── requirements.txt
├── run.py
└── README.md
```
