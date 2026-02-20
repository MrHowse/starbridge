# Current Phase: v0.04c — New Graph-Native Missions (COMPLETE ✓)

> Updated 2026-02-20 — v0.04c complete.

## Status

**v0.04c COMPLETE.** 4 new graph-native missions created, showcasing branch/parallel/conditional depth.

- **1781 tests passing**, 0 regressions from v0.04b baseline (1721 tests)
- **Bug fix**: `MissionGraph.tick()` now returns parent parallel node IDs when they complete via
  child completion (previously only child IDs were returned). Fixed by tracking completions in
  `_do_complete_node` via `_tick_completions` list, reset each tick.
- 4 new mission JSON files in `missions/`:
  - `salvage_run.json` — 3-way branch: science vs comms vs timer ambush; rescue parallel
  - `first_contact_remastered.json` — 3-way branch: scan (diplomatic), destroy (combat), flee
  - `the_convoy.json` — parallel count=2/3 attack groups; compound defeat condition
  - `pandemic.json` — 3-way pathogen branch; two nested parallel "all" outcome paths
- `tests/test_graph_missions.py` — 60 tests covering all 4 missions (load + branch simulation)
- Next: v0.04d — (see SCOPE_v004.md)

## v0.04b Status (CLOSED)

**v0.04b COMPLETE.** All 23 missions converted to graph format, game_loop switched to MissionGraph.

- **1721 tests passing**, 0 regressions from v0.04a baseline (1719 tests)
- `tools/migrate_missions.py` — migration script (converts old sequential format → graph format)
- All 23 JSON missions converted: nodes/edges/start_node/victory_nodes/defeat_condition
- 3 missions enhanced with parallel nodes (engineering_drill, first_contact_protocol, diplomatic_summit)
- `server/game_loop_mission.py` — now uses `MissionGraph` instead of `MissionEngine`
- `server/missions/loader.py` — sandbox dict updated to graph format
- All 7 test files updated to use new mission format keys
- `tests/test_diplomatic_summit.py` — fully rewritten for graph format + MissionGraph

## v0.03 Status (CLOSED)

**v0.03 is CLOSED.** Gate verification completed 2026-02-20.

- **1578 tests at gate**, 0 regressions from v0.02 baseline (948 tests)
- **12 player stations**: captain, helm, weapons, engineering, science, medical,
  security, comms, flight_ops, electronic_warfare, tactical + viewscreen (passive)
- **9 puzzle types** across all stations
- **23 JSON missions** + sandbox (synthetic): 11 story + 12 training (train_*)
- **7 ship classes**: scout, corvette, frigate, cruiser, battleship, medical_ship, carrier
  — all with min_crew/max_crew crew ranges
- **4 difficulty presets**: cadet, officer, commander, admiral
- Game event logger + Debrief Dashboard + Captain's Replay
- Training missions for all 12 player roles
- Multi-role play supported (role_bar.js, combined roles)
- Mission briefing room (client/briefing/)
- Cross-station notification system (crew.notify → crew.notification)
- v0.03 gate tests in tests/test_gate_v003.py

## v0.03 Sub-releases Completed

| Sub-release | Tests at close | Feature |
|-------------|---------------|---------|
| v0.03a–g    | ~999          | Audio placeholder, QoL fixes, MapRenderer, notifications, ship framework, multi-role, briefing room |
| v0.03h      | 999           | Science scan modes (EM/GRAV/BIO/SUB) |
| v0.03i      | 1033          | Damage Control station |
| v0.03j      | 1085          | Flight Operations Officer |
| v0.03k      | 1162          | Electronic Warfare Officer |
| v0.03l      | 1223          | Tactical Officer |
| v0.03m      | 1289          | Training Missions (12 missions, all roles) |
| v0.03n      | 1324          | Debrief Dashboard + Captain's Replay |
| v0.03o      | 1578          | Ship Balancing + Final Integration + Gate |

## Known Gaps at v0.03 Close (not blocking)

- No audio — `client/shared/audio.js` is a placeholder; `SoundBank` is wired in JS but silent
- No tablet layout verification on physical hardware
- No automated end-to-end tests (Playwright/Selenium)
- Science bearing lines accumulate indefinitely (session-lifetime storage)
- Sandbox has no game.over — infinite play only
- Lobby does not enforce min_crew (host can launch with fewer players than min_crew)
- medical_ship and carrier have no differentiated gameplay mechanics from standard frigate
  (hull/ammo values differ; specialist mechanics are v0.04 scope)
