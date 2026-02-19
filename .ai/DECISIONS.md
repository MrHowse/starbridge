# Architecture Decisions

> **APPEND-ONLY** — Add new decisions at the bottom. Never modify or remove existing entries.

---

## 2026-02-18 — Server-authoritative simulation

**Decision**: The server is the single source of truth for all game state. Clients send intentions (e.g., "I want to turn left"), not state changes. The server validates, simulates, and broadcasts results.

**Reasoning**: Prevents desync between clients, makes state management conceptually simple (one place to look), and ensures consistency regardless of client behaviour. Since this is a co-op game, anti-cheat isn't the motivation — consistency and simplicity are.

**Alternatives considered**:
- Client-authoritative (each client manages its own state) — rejected: desync nightmare with 5+ clients
- Peer-to-peer — rejected: complex, no single source of truth, harder to debug

---

## 2026-02-18 — JSON message protocol with envelope format

**Decision**: All WebSocket messages use a standard JSON envelope: `{ type, payload, tick, timestamp }`. Types are namespaced with dots (e.g., `helm.set_heading`, `ship.state_update`).

**Reasoning**: Human-readable and easy to debug (just log the JSON). Extensible — new message types are added by defining new type strings and payload schemas. Fast enough for LAN use (not bandwidth-constrained). Pydantic validates payloads automatically.

**Alternatives considered**:
- Protocol Buffers — rejected: overkill for LAN game, adds build complexity
- Raw strings/custom format — rejected: fragile, no validation
- MessagePack/CBOR — rejected: harder to debug, marginal perf gain on LAN

---

## 2026-02-18 — No frontend framework

**Decision**: Client code uses vanilla JavaScript with ES modules. No React, Vue, Svelte, or similar. No build step, no npm, no bundler.

**Reasoning**: Each station is a relatively isolated page with specific rendering needs (mostly Canvas). A framework adds complexity without proportional benefit. No build step means the server just serves static files directly. ES modules provide sufficient code organisation. Alpine.js may be introduced later if reactivity becomes painful, but is not needed initially.

**Alternatives considered**:
- React — rejected: requires build step, overkill for mostly-Canvas UIs
- Svelte — rejected: build step requirement
- Alpine.js — deferred: may add later for reactive UI elements if vanilla JS becomes cumbersome

---

## 2026-02-18 — Fixed timestep game loop (10 ticks/sec)

**Decision**: The game simulation runs at a fixed rate of 10 ticks per second, decoupled from client frame rate and network conditions. Clients receive state snapshots and interpolate between them for smooth 60fps rendering.

**Reasoning**: Fixed timestep ensures deterministic simulation regardless of server load or client performance. 10 ticks/sec is sufficient for the pace of starship combat (not a twitch game). Client-side interpolation bridges the gap to 60fps visually. This is a well-proven pattern in networked games.

**Alternatives considered**:
- Variable timestep — rejected: non-deterministic, harder to reproduce bugs
- Higher tick rate (30-60) — rejected: unnecessary for this game's pace, wastes bandwidth
- Lower tick rate (5) — rejected: would feel sluggish for helm controls

---

## 2026-02-18 — Component-based ship systems

**Decision**: The ship is composed of independent system objects (engines, shields, weapons, sensors, etc.), each with a standard interface: power_level, health, efficiency, update(). New systems can be added without modifying existing code.

**Reasoning**: Enables the complexity layering design (Tier 1-4 per system). Systems can be damaged, repaired, powered independently. Power allocation is a simple distribution across components. New systems (e.g., tractor beam, cloaking device) slot in without touching existing code. Each system's update() is called once per tick.

**Alternatives considered**:
- Monolithic ship class with all logic — rejected: becomes unmaintainable as systems grow
- Entity-Component-System (ECS) — rejected: overkill for a single player ship with ~6 systems; ECS shines with hundreds of entities

---

## 2026-02-18 — Missions as data (JSON), not code

**Decision**: Missions are defined as JSON data files with triggers, conditions, objectives, and events. A mission engine interprets these at runtime. Complex missions can optionally hook into Python for custom logic.

**Reasoning**: Enables mission authoring without code changes. The project owner (or anyone) can create new missions by writing structured data. Supports rapid iteration on mission design. The trigger/event system covers most gameplay scenarios. Custom Python hooks are an escape hatch for truly novel mechanics.

**Alternatives considered**:
- Hardcoded Python missions — rejected: every new mission requires code changes, harder to iterate
- Lua scripting — rejected: adds a language dependency and complexity; JSON + Python hooks covers the same ground
- YAML instead of JSON — considered: slightly more readable, but JSON has better tooling and validation support

---

## 2026-02-18 — Single Message envelope model with tick: int | None

**Decision**: All WebSocket messages use a single `Message` Pydantic model with `tick: int | None = None`. The field is `None` for client→server messages and lobby messages, and populated by the server for in-game state updates. Outbound messages serialise with `exclude_none=True` so `tick` is absent from the JSON when not set.

**Reasoning**: One envelope model means one parse path, one validation path, and one serialisation call. Splitting into separate client-message and server-message models would add complexity with no real benefit — the protocol is uniform by design. Using `exclude_none=True` keeps the wire format clean (no `"tick": null` in lobby messages) without requiring a second model.

**Alternatives considered**:
- Separate `ClientMessage` / `ServerMessage` models — rejected: duplication, two parse paths, no meaningful type-safety gain at the boundary where JSON is parsed
- Always include `tick` as 0 or -1 in non-game messages — rejected: pollutes the protocol with a sentinel value that has no meaning in lobby context

---

## 2026-02-18 — Stub lobby handler wired up in Session 1a

**Decision**: `server/lobby.py` contains a real handler function (`handle_lobby_message`) that is imported and registered in the routing table in `server/main.py`. For Session 1a it only logs the message type and connection ID. The actual claim/release/launch logic is implemented in Session 1b.

**Reasoning**: The WebSocket routing infrastructure (envelope parse → category dispatch → handler call) is the thing being tested in Session 1a. Having the router call a real function through the real dispatch table verifies the full path end-to-end. A stub that is never imported or called would not test the wiring at all.

**Alternatives considered**:
- No lobby handler in 1a (just log "unhandled message" in the router) — rejected: doesn't test the routing wiring that will be used for all future message types
- Fully implement lobby logic in 1a — rejected: lobby state management belongs in Session 1b where it can be tested properly with its own test suite

---

## 2026-02-18 — Game input processed via queue at start of each tick

**Decision**: Station clients (Helm, Engineering, Weapons, etc.) send intention messages that are appended to a shared `asyncio.Queue`. At the start of each game loop tick, the loop drains this queue and applies all pending inputs to the game state before running the physics step.

**Reasoning**: Cleanly separates message receipt (async WebSocket events) from simulation (fixed schedule). Matches the convention in CONVENTIONS.md: "Client messages are queued and processed at the start of each tick." Setting this pattern in Phase 2 means Engineering, Weapons, and Science all use the same queue in later phases — one infrastructure piece, multiple consumers.

**Alternatives considered**:
- Direct mutation (messages write to ship model immediately on receipt) — rejected: simpler, but inconsistent with stated convention; harder to reason about game state mid-tick
- Per-station queues — rejected: unnecessary; a single typed queue is sufficient and avoids synchronisation overhead

---

## 2026-02-18 — Sector boundary: clamp position, stop velocity

**Decision**: When the ship reaches the edge of the 100,000 × 100,000 unit sector, its position is clamped to the boundary and velocity is set to zero. The player must change heading and reapply throttle to move away from the wall.

**Reasoning**: Simple, predictable, clear feedback. No teleportation confusion (wrap), no invisible wall mystery (position clamped but velocity persisting). The ship visibly stops.

**Alternatives considered**:
- Wrap-around — rejected for Phase 2: disorienting on minimap, better as a mission-level option in a future phase
- Allow unbounded movement — rejected: breaks minimap rendering and world entity coordinates

**Future**: A TODO comment marks the clamp site in physics.py. Some missions may want wrap-around or open boundaries. Should become configurable per-mission when the mission engine is built in Phase 6.

---

## 2026-02-18 — ship.state broadcast to all clients each tick (deferred role-filtering)

**Decision**: Every game loop tick broadcasts the full `ship.state` payload to all connected clients, regardless of role.

**Reasoning**: Phase 2 only has the Helm station. Broadcasting everything to everyone costs nothing on LAN, is easy to debug (any tab can log ship.state), and avoids premature design work on which roles see which fields. Role-filtering becomes a design concern in Phase 5 when Science creates information asymmetry.

**Alternatives considered**:
- Role-filter from the start — rejected: requires defining per-role field sets before those roles are implemented
- Separate payloads per role — deferred: correct long-term design, to be implemented in Phase 5

**Future**: A TODO comment marks the broadcast call in game_loop.py. In Phase 5: Captain gets full state, Helm gets nav fields, Weapons gets a contact view, Science gets sensor data, etc.

---

## 2026-02-18 — Late-join clients receive game.started from stored payload

**Decision**: When a client connects while a game is already running, the server sends `game.started` directly to that connection from a stored `lobby._game_payload`, rather than relying on the broadcast that fired at game start.

**Reasoning**: `game.started` is a one-shot broadcast — it fires once when the host launches. Any browser that connects after that point (station pages load fresh after the lobby redirect) would never receive it and would stay on their standby screen indefinitely. Storing the payload and re-sending it on connect costs nothing and solves the problem completely.

**Alternatives considered**:
- Periodic re-broadcast — rejected: would trigger state changes on already-active clients
- Polling / "are we in a game?" message — rejected: adds round-trip latency and complexity; storing the payload is simpler

---

## 2026-02-18 — DEFAULT_STATE fallback in helm.js prevents blank canvas on game start

**Decision**: `helm.js` defines a `DEFAULT_STATE` constant (heading 0, velocity 0, throttle 0, position at sector centre). `getInterpolatedState()` returns this when `currState` is `null` (no server tick received yet), instead of returning `null` and skipping rendering.

**Reasoning**: The helm station receives `game.started`, hides the standby screen, and starts the render loop — but the first `ship.state` tick won't arrive for up to 100 ms. Without a fallback state the canvases would remain blank (no draw calls) until the first tick. With `DEFAULT_STATE`, the starfield, compass, and minimap render immediately on game start.

**Alternatives considered**:
- Delay showing the helm UI until first tick — rejected: introduces a visible flash/delay
- Initialise `currState` with a hardcoded object — equivalent, but a named constant is clearer and easier to document

---

## 2026-02-18 — Placeholder station pages show "not yet operational" + lobby link

**Decision**: All unimplemented station pages (captain, weapons, engineering, science, viewscreen) display "This station is not yet operational." and a "← RETURN TO LOBBY" link in their standby screen, rather than a generic "STANDING BY / Awaiting mission orders." message with no exit path.

**Reasoning**: Testing revealed that a player who claimed the wrong role (e.g., Captain instead of Helm) was stuck on a blank standby screen with no indication of what went wrong or how to recover. Three symptoms: (1) no explanation that the page is unimplemented, (2) no phase info to set expectations, (3) no navigation back. All three are fixed by this change.

**Alternatives considered**:
- HTTP 404/redirect for unimplemented stations — rejected: would make the role unavailable in the lobby, affecting game flow
- Single generic "coming soon" page served for all placeholder routes — rejected: would break the role-specific redirect logic in lobby.js

---

## 2026-02-18 — Lobby module uses init(manager) to receive ConnectionManager

**Decision**: `server/lobby.py` exposes an `init(manager: ConnectionManager)` function that stores the manager as a module-level variable. `main.py` calls `lobby.init(manager)` once on startup after creating the `ConnectionManager` singleton. `init()` also resets the `LobbySession` to a fresh state, which doubles as the test injection point.

**Reasoning**: Keeps handler signatures uniform — `handle_lobby_message(connection_id, message)` matches the type used in `_HANDLERS` without wrapping. The alternative of passing `manager` as a parameter to every handler would require changing the handler type or using closures/partial functions. The `init()` pattern is a well-understood dependency injection approach, and resetting session state in `init()` makes tests clean without needing a separate reset function.

**Alternatives considered**:
- Pass manager as a parameter to each handler — rejected: changes handler signature, requires type changes in main.py routing table
- Import manager from main.py inside lobby functions — rejected: circular import
- Move manager to a separate server/state.py module — deferred: overkill for Phase 1; may revisit in Phase 2 when game loop needs access to manager

---

## 2026-02-18 — Explicit lobby.on_disconnect() call from main.py WebSocket handler

**Decision**: When a WebSocket disconnects, `main.py` calls `manager.disconnect(connection_id)` first (removes from connection pool), then `await lobby.on_disconnect(connection_id)` (releases role, reassigns host, broadcasts updated state to remaining clients). This is an explicit two-step call in the `except WebSocketDisconnect` block.

**Reasoning**: Simple and readable — the disconnect sequence is visible in one place. `lobby.on_disconnect` runs after `manager.disconnect` so that `manager.all_ids()` correctly excludes the departed connection when choosing a new host. No need for a general callback/event system for Phase 1.

**Alternatives considered**:
- Callback registration on ConnectionManager — deferred: would be cleaner when Phase 2 adds a game loop that also needs to react to disconnects; adding it now would be premature
- Single-step (lobby handles everything) — rejected: lobby should not call manager.disconnect() itself; that conflates connection lifecycle with lobby logic

---

## 2026-02-18 — Role-filtered WebSocket broadcasting

**Decision**: Each WebSocket connection is tagged with its assigned role. The server sends only role-relevant data to each client. A full state channel exists for the Captain's overview and for debugging.

**Reasoning**: Reduces bandwidth (important for older devices on WiFi). Keeps each client's logic focused on its own data. Enables information asymmetry as a game mechanic — Science sees things Weapons doesn't, which forces verbal communication. The Captain's full view is a gameplay feature, not a debug tool.

**Alternatives considered**:
- Broadcast everything to everyone, filter client-side — rejected: wastes bandwidth, undermines information asymmetry (client could cheat by reading other roles' data)
- Separate WebSocket endpoints per role — rejected: unnecessary complexity, harder to manage

---

## 2026-02-18 — Single auto-created game session (v0.01)

**Decision**: For v0.01, a single game session is created automatically when the server starts. No session creation/browsing UI. Players connect and join the one active session.

**Reasoning**: Simplifies the lobby significantly. For LAN play with friends, you only need one game at a time. Multi-session support can be added later without architectural changes (the lobby and connection manager already use session IDs internally).

**Alternatives considered**:
- Full session management (create, browse, join) — deferred: unnecessary complexity for v0.01 LAN use case

---

## 2026-02-18 — Power budget = 600 units (6 systems × 100% baseline)

**Decision**: The Engineering power pool is 600 units total (6 systems × 100% each). All systems start at 100% power, which is the sustainable baseline. To overclock any system above 100%, the Engineer must cut power from others to stay within the 600-unit budget.

**Reasoning**: At 600, the ship starts in a comfortable equilibrium — all systems functional, no scarcity. The drama escalates with the mission: when combat starts and Weapons wants 150% beams and Shields wants 150% shields, the Engineer is suddenly 300 units over budget and must make hard choices. This creates a gameplay arc (calm patrol → crisis under fire) rather than constant stress from mission start. Contrast with a 300-unit pool where the engineer is immediately resource-constrained before anything interesting happens.

**Alternatives considered**:
- Pool = 300 (50% per system at rest) — rejected: constant maximum tension removes the arc; engineer is always overloaded, making the role feel punishing rather than dramatic

---

## 2026-02-18 — Power budget enforcement via silent clamp at tick drain

**Decision**: When an `engineering.set_power` input would push the total system power above the 600-unit budget, the requested level is silently clamped to whatever headroom remains. The clamping happens in `game_loop._drain_queue()` where the ship model is available. The Engineering client shows the budget and clamped result in real time; the server never sends an error response.

**Reasoning**: Error messages feel like software feedback, not physical constraints. The reactor "can't give any more" — this should feel like a dial hitting a hard stop, not an administrative rejection. The client UI (budget bar, slider behaviour) communicates the constraint before the message is sent; by the time the server processes it, the clamp is expected. Silent clamping also avoids a round-trip latency before the UI updates.

**Alternatives considered**:
- Hard reject with `error.state` — rejected: administrative feel; client must wait for server rejection before updating UI; error message framing is wrong for a physical constraint

---

## 2026-02-18 — Engineering mechanics defined as named constants in game_loop.py

**Decision**: All tunable engineering parameters are defined as module-level constants at the top of `server/game_loop.py`: `POWER_BUDGET`, `OVERCLOCK_THRESHOLD`, `OVERCLOCK_DAMAGE_CHANCE`, `OVERCLOCK_DAMAGE_HP`, `REPAIR_HP_PER_TICK`.

**Reasoning**: These values are inevitably adjusted during playtesting — "feels too punishing / too lenient" are expected feedback. Named constants at the top of a single file are trivially findable and changeable. They are also inspectable from tests (e.g., `assert game_loop.REPAIR_HP_PER_TICK == 1.0`), which makes test assertions self-documenting. Phase 3 values: repair 1 HP/tick (10 HP/sec), overclock 10% chance/tick of 3 HP damage (~1 event/sec expected).

**Alternatives considered**:
- Hardcoded magic numbers inline — rejected: unfindable, not self-documenting, guaranteed to need a grep when tuning
- Config file / environment variables — deferred: unnecessary indirection for values that change only during development

---

## 2026-02-18 — Debug endpoints gated by STARBRIDGE_DEBUG environment variable

**Decision**: Two debug HTTP endpoints are added to `server/main.py`: `POST /debug/damage` (deal HP damage to a named system) and `GET /debug/ship_status` (return full ship state as JSON). Both return HTTP 404 when `STARBRIDGE_DEBUG` env var is not `"true"`. The var defaults to `"true"` in development.

**Reasoning**: A quick way to damage systems is essential for testing the repair mechanic and overclock risk without waiting for those mechanics to trigger naturally. HTTP endpoints work from any browser tab, from curl, and don't require a specific station client to be open. Gating behind an env var (rather than a compile flag or hardcoded boolean) means the endpoints can be disabled with a single environment change when deploying, without a code change.

**Alternatives considered**:
- Browser console command (`window.debugDamage(...)`) — rejected: requires the specific station page to be open; awkward when testing with two tabs
- Debug WebSocket message category — rejected: requires the WS connection to be open and authenticated; more code for the same result
- No debug mechanism — rejected: would require manual editing of ship state in memory, which is not viable during interactive testing

---

## 2026-02-18 — Budget gauge is informational only; never changes colour

**Decision**: The Engineering power budget bar stays green (primary colour) at all times, regardless of how much of the 600-unit pool is consumed. It does not shift to amber or red as the pool fills.

**Reasoning**: At game start all 6 systems run at 100% each = 600/600 total — exactly at the budget cap. A threshold-based colour scheme triggers red at game start, which communicates "crisis" at the exact moment the ship is in its most comfortable default state. The design intent (per the 600-unit pool decision) is that 600/600 is the sustainable equilibrium. Overclock warnings are already communicated per-system via the amber slider thumb (`.sys-row--overclocked` CSS class) and the per-node health colour on the schematic. The budget bar's role is purely informational — how much of the pool is allocated — not a warning system.

**Alternatives considered**:
- Amber at 88%, red at 100% — rejected: both thresholds trigger immediately at game start (600 >= 528 and 600 >= 600)
- Shift thresholds higher (e.g. red only above 120%) — rejected: overclock zone is already per-system; the budget bar would duplicate information already shown in the slider/row overrides
- Remove budget bar entirely — rejected: useful reference for the engineer to understand headroom at a glance

---

## 2026-02-18 — Entity IDs are consistent string identifiers assigned at spawn

**Decision**: Every world entity (enemy ships, torpedo projectiles, future stations/asteroids) carries a string `id` field assigned at spawn time. Format: `"enemy_1"`, `"enemy_2"`, `"torpedo_1"` etc. (incrementing counter per category). IDs are stable for the lifetime of the entity and referenced consistently in all messages: `world.entities`, `weapons.select_target`, `world.entity_destroyed`, `weapons.torpedo_hit`, and future `science.start_scan`.

**Reasoning**: Weapons needs to reference a specific target when firing. Science needs to reference a specific contact when scanning. Without stable IDs, clients have no reliable way to refer to individual entities across message types. UUID v4 would also work but incrementing strings are human-readable in logs, easier to type in test data, and sufficient for the number of entities in a single mission.

**Alternatives considered**:
- UUID v4 — rejected for v0.01: debugging is harder with opaque IDs; incrementing strings are functionally equivalent at this scale
- Position-based referencing ("target at bearing X, range Y") — rejected: ambiguous if two contacts are close, unusable for scan targeting

---

## 2026-02-18 — Enemy AI behaviours are role-differentiated, not uniform

**Decision**: Each enemy type has a distinct AI behaviour profile beyond the base idle/chase/attack/flee state machine. Scouts break off and circle at close range before re-engaging (flanking behaviour). Cruisers press the attack even when taking damage, only fleeing below 20% hull. Destroyers hold position at max weapon range and let their heavy beams do work ("standoff attack"). Individual enemies feel purposeful rather than identical.

**Reasoning**: Enemies that fly straight at you and fire are predictable and boring within seconds. Role-differentiated AI requires no additional architectural complexity (same state machine, different transition parameters and movement logic per type) but creates dramatically different tactical responses from the crew. Scouts become a harassment threat, Cruisers are aggressive mid-range fighters, Destroyers are a long-range threat that punishes the player for staying in one place.

**Alternatives considered**:
- Uniform "fly-at-player" AI for all types — rejected: dull within minutes; defeats the purpose of distinct enemy types
- Full behaviour tree / GOAP — rejected: overkill for Phase 4; the base state machine with type-specific parameters achieves the same result with far less code

---

## 2026-02-18 — Enemy wireframe shapes are drawn in the station module, not renderer.js

**Decision**: Scout (diamond), Cruiser (triangle), and Destroyer (hexagon) wireframe shapes on the tactical radar are drawn entirely in `client/weapons/weapons.js`. They are not added to `client/shared/renderer.js`.

**Reasoning**: This follows and extends the convention established by the Engineering schematic: station-specific canvas drawing belongs in the station module; shared/reusable utilities belong in `renderer.js`. Enemy shapes are only meaningful in the context of the Weapons tactical radar — they carry game-domain concepts (enemy type identity, targeting state) that have no relevance to Helm or any other station. Adding them to `renderer.js` would make a shared library aware of combat-specific domain concepts.

**Alternatives considered**:
- Add enemy shape helpers to renderer.js — rejected: pollutes shared code with station-specific domain knowledge; violates the established convention
- Create a separate `client/weapons/radar.js` module — deferred: weapons.js is manageable; split if file grows significantly

---

## 2026-02-18 — world.entities is a full snapshot every tick (no delta-encoding)

**Decision**: Each game loop tick broadcasts the complete `world.entities` payload containing the full list of all enemies and torpedoes with all fields. No delta-encoding, no "only send what changed" optimisation.

**Reasoning**: At LAN bandwidth with 1–3 enemies and ≤10 torpedoes, the payload is tiny (< 2 KB per tick). Full snapshots are simpler to consume on the client: replace the local entity list each tick, no merge logic, no missed-update edge cases. Delta-encoding would add meaningful complexity (tracking previous state per-client, encoding changes) for zero perceptible benefit. This is noted as a potential future optimisation if the entity count grows into the dozens.

**Alternatives considered**:
- Delta-encoding (send only changed entities) — deferred: appropriate optimisation once entity count grows; not needed for v0.01 scale
- `world.entity_spawned` / `world.entity_destroyed` individual events — considered for spawn/destroy notifications; these still fire as separate events for visual FX (spawn flash, explosion), but the primary state source is the full snapshot

---

## 2026-02-18 — Shield absorption: proportional formula with depletion

**Decision**: When a hit lands on a shield hemisphere, the shield absorbs up to `shield_hp × SHIELD_ABSORPTION_COEFF` (0.8) of the incoming damage. The shield's HP is reduced by `absorbed / SHIELD_ABSORPTION_COEFF` (i.e., absorbing 8 damage from a 10-HP shield drains 10 HP from the shield). Any remaining damage after absorption passes through to hull.

**Reasoning**: A linear coefficient (absorb 80% while any shield remains) creates a smooth and predictable damage model that is easy to test and reason about. It avoids the "all-or-nothing" feel of a flat damage-reduction model (where half-shield still blocks the same amount as full shield). Shields are meaningful even when depleted — draining the last 10 HP of shield saves 8 HP of hull. At 0 HP shields provide no protection.

**Alternatives considered**:
- Flat % reduction (e.g., 50% reduction regardless of HP) — rejected: full and half shields feel identical; no urgency to protect shields
- Ablative (direct 1:1 HP drain, remainder to hull) — considered: simpler math, but provides too little hull protection per shield HP spent; tuning felt wrong
- Separate `SHIELD_ABSORPTION_COEFF` constant — adopted: makes the formula discoverable and tunable without hunting through code

---

## 2026-02-18 — Torpedo collision radius and max range as class-level constants

**Decision**: Torpedo collision detection uses a fixed radius of 200 world units. Torpedoes that travel beyond 20,000 world units without hitting a target are despawned. Both values are `ClassVar[float]` constants on the `Torpedo` dataclass.

**Reasoning**: Placing constants on the dataclass keeps them co-located with the data they govern, avoids a separate constants file for two values, and makes them accessible from test code as `Torpedo.MAX_RANGE` without importing a separate module. The 200-unit collision radius is approximately 2% of torpedo speed per tick (speed = 500 u/s, tick = 100 ms → 50 u/tick), which prevents tunnelling while avoiding false positives at the typical engagement ranges (4,000–10,000 units).

**Alternatives considered**:
- Module-level constants in game_loop.py — rejected: combat constants belong near the entity they govern, not in the loop orchestrator
- Dynamic radius (based on torpedo type) — deferred: only one torpedo type in v0.01; generalise when multiple warhead types are added in Tier 2

---

## 2026-02-18 — Beam weapons use hold-to-fire mechanic (mousedown interval)

**Decision**: The FIRE BEAMS button in the Weapons station sends `weapons.fire_beams {}` immediately on `mousedown`, then continues sending at ~2 Hz (500 ms interval) while the button remains held. The interval is cleared on `mouseup` or `mouseleave` from the button (and on `window.mouseup` to catch releases outside the button).

**Reasoning**: Beams are a sustained weapon — holding the trigger while keeping the enemy in arc is the intended interaction. A single click would feel unrewarding for a powerful weapon. A hold mechanic requires active attention (release to stop firing) and creates a natural interaction cost that makes Engineering's beam power allocation meaningful: higher power makes each burst more damaging, not more automatic. The 2 Hz rate matches the server's maximum processing tempo and avoids flooding the input queue.

**Alternatives considered**:
- Single click → auto-fire while target in arc (server-side, no hold required) — rejected: removes the intentional action cost; beams become passive
- Continuous fire at rAF rate — rejected: would flood the server with hundreds of messages per second

---

## 2026-02-18 — _drain_queue world parameter is optional for backward test compatibility

**Decision**: `_drain_queue(ship, world=None)` accepts an optional `world` parameter (default `None`). The `weapons.fire_beams` and `weapons.fire_torpedo` branches are guarded with `if world is not None:`. All existing tests that call `_drain_queue(ship)` continue to work without modification.

**Reasoning**: Changing `_drain_queue` to require `world` would break all Phase 2 and Phase 3 tests that call it with a single argument. Rather than updating every existing test (churn with no benefit), the optional parameter preserves backward compatibility. The guard is explicit and honest — there is no meaningful fallback for fire commands without world access, so they simply skip. Tests that need to exercise fire commands must pass a world object explicitly.

**Alternatives considered**:
- Update all existing tests to pass a mock World — rejected: churn across ~30 test calls for no gameplay benefit
- Separate `_drain_weapons_queue(ship, world)` function — considered: cleaner separation, but adds a second function to maintain and call; optional parameter is simpler at this scale

---

## 2026-02-18 — sensor.contacts as a separate role-filtered broadcast (Phase 5)

**Decision**: Phase 5 introduces two distinct entity broadcast channels:
- `world.entities` → broadcast to `helm` + `engineering` roles (full enemy data: type, hull, shields)
- `sensor.contacts` → broadcast to `weapons` + `science` roles (range-filtered; type info stripped for unscanned contacts)

Weapons.js switches from listening to `world.entities` to listening to `sensor.contacts`. This is an explicit breaking change — no backward-compatibility shim.

**Reasoning**: This is the first implementation of role-filtered broadcasting for gameplay (information asymmetry) purposes, not merely bandwidth optimisation. Science scans reveal enemy type and weakness; Weapons must not be able to read that data before Science communicates it verbally. Enforcing the filter server-side (not client-side) is the only correct approach — a client-side filter can be bypassed by reading the raw WebSocket data. The server controls what each role receives.

The separation of channels also maps cleanly to the sensor power mechanic: `sensor.contacts` is gated by sensor range (which scales with sensor power), making Engineering's power allocation to the sensors system directly relevant to Science's and Weapons' situational awareness.

**Sensor power effects** (Phase 5 explicit design confirmation):
- **Scan range**: `effective_range = BASE_SENSOR_RANGE × sensor_efficiency` — contacts outside this range are invisible to Science/Weapons
- **Scan speed**: `progress_per_sec = 100 / (BASE_SCAN_TIME / sensor_efficiency)` — higher efficiency = faster scan completion

This creates the crew dependency loop: *"Science, scan that cruiser." "I can't — Engineering cut sensor power." "Engineering, give Science more juice." "I can't, it's all in shields."*

**Alternatives considered**:
- Client-side filtering (send all data to all clients, clients decide what to show) — rejected: undermines information asymmetry; clients can read filtered data from the WebSocket stream
- Single `world.entities` payload with role-gated field visibility — rejected: complex conditional serialisation logic; cleaner to have two distinct payloads with well-defined audiences
- Delta-only sensor.contacts (only send when contacts change) — deferred: full snapshot per tick is simpler and sufficient at LAN bandwidth with few contacts

---

## 2026-02-18 — Station pages re-claim their role on WebSocket connect

**Decision**: Each station page (weapons.js, science.js) sends `lobby.claim_role { role, player_name }` immediately when the WebSocket status becomes `connected`. The player name is read from `sessionStorage('player_name')`, which lobby.js writes before redirecting. This ensures the new connection is tagged with the correct role so it receives role-filtered broadcasts (e.g., `sensor.contacts`).

**Reasoning**: When a browser navigates from `/client/lobby/` to `/client/science/`, a new WebSocket connection is created — the old connection (with the role tag from `lobby.claim_role` during role selection) is gone. Without an explicit role claim on the station page, the connection has no role and receives no `broadcast_to_roles` messages. The phase gate for Phase 5 requires that Science receives `sensor.contacts` and Weapons receives the same; both require the connection to be tagged with the correct role.

**Alternatives considered**:
- Persist role via URL parameter or cookie on redirect — rejected: sessionStorage is simpler and avoids URL clutter; lobby already controls the redirect
- Send role-filtered messages to all connections regardless of role — rejected: defeats information asymmetry; any client could receive science/weapons data
- Store connection_id in localStorage and re-use it — not possible: connection IDs are server-generated UUIDs per-connection

---

## 2026-02-18 — Triangulation UX: bearing line on canvas AND numeric readout (Q1)

**Decision**: Science triangulation displays BOTH a bearing line overlaid on the sensor canvas AND a numeric bearing readout in the scan panel. Both representations are shown simultaneously.

**Reasoning**: The bearing line is spatially intuitive — Science can point at a direction and Helm can align course accordingly. The numeric readout is operationally precise — Science can call out "bearing 247" and Helm can dial it in without interpretation. The two together are complementary: visual for spatial reasoning, numeric for crew communication. Neither alone fully satisfies both use cases.

**Consequences**: Science client renders bearing lines on the sensor canvas starting from the ship (canvas centre) at the reported angle. After 2 scans from different positions an intersection diamond marker appears. The scan result panel also shows "Bearing: 247°" in text. The server computes bearing server-side (ship position → signal source) and sends it in the `mission.signal_bearing` message — the client draws; the server computes.

**Alternatives considered**:
- Bearing line only — rejected: hard to communicate exact angle verbally to Helm
- Numeric only — rejected: loses spatial intuition; Science can't "see" where to point
- Interactive protractor tool — deferred: over-engineered for Phase 7

---

## 2026-02-18 — Mission 2 enemy AI targets station exclusively (Q3)

**Decision**: In Mission 2 "Defend the Station", enemies exclusively target the friendly station (Starbase Kepler). Enemies engage the player ship only if the player enters within weapon range while moving to intercept — a side-effect of the attack AI, not a primary target switch.

**Reasoning**: "Station-only" targeting gives the mission its identity: players must actively protect a third party rather than just surviving. If enemies alternated targets, players could kite them away from the station (reducing tactical pressure). The station-only design forces Engineering to maintain shields, Weapons to intercept before enemies reach the station, and Helm to position for interception — all roles engaged. The player ship being engaged as a side-effect (while in weapon range) adds personal jeopardy without making the player the primary target.

**Implementation**: `tick_enemies()` in `server/systems/ai.py` receives an optional `station_targets: list[Station]` parameter. When non-empty, enemies in missions with stations chase the nearest station instead of the ship. The `attack` state fires at the current chase target (station or player). The idle→chase transition uses nearest station as primary target.

**Consequences**: This establishes the pattern for mission-specific AI targeting: game_loop passes contextual targets to tick_enemies based on what the current mission requires. Future missions can override targeting by passing different target lists without changing the AI state machine logic.

**Alternatives considered**:
- Alternating targets — rejected: reduces tactical pressure on players; kiting becomes dominant strategy
- Static "attack nearest" — rejected: enemies would attack player when they're far from station, reducing station-protection feel
- Separate AI variant per mission — rejected: code duplication; parametric targeting via argument is cleaner

---

## 2026-02-18 — Engineering schematic is drawn in station module, not renderer.js

**Decision**: The ship diagnostic schematic (the top-down wireframe canvas with 6 system nodes) is drawn entirely within `client/engineering/engineering.js`. It does not use or extend `client/shared/renderer.js` for its draw calls.

**Reasoning**: `renderer.js` is a library of *shared* utilities (starfield, compass, minimap, ship chevron) that multiple stations can reuse. The Engineering schematic is station-specific — it represents systems, health, repair focus, and damage flashes that have no meaning outside Engineering. Adding it to renderer.js would make renderer.js aware of game domain concepts it doesn't need to know. The convention is corrected in CONVENTIONS.md: station-specific canvas drawing belongs in the station module; shared/reusable utilities belong in renderer.js.

**Alternatives considered**:
- Put schematic draw functions in renderer.js — rejected: would pollute shared code with Engineering-specific domain knowledge
- Create a separate `client/engineering/schematic.js` module — deferred: the engineering.js file is manageable at ~750 lines; split if it grows significantly

---

## 2026-02-19 — Split game_loop.py into 4 files (Session 0.1a)

**Decision**: Split the 838-line `server/game_loop.py` into four files:
- `game_loop.py` (343 lines) — orchestrator with test-anchored symbols
- `game_loop_physics.py` — TICK_RATE/TICK_DT constants
- `game_loop_weapons.py` — stateful weapons sub-module
- `game_loop_mission.py` — stateful mission sub-module

**Reasoning**: game_loop.py had grown to 838 lines across 3 distinct concern domains (orchestration, weapons, mission). The split uses the established stateful module pattern from sensors.py (module-level state + reset()). Sub-modules are imported as `glw` / `glm` aliases at the top of game_loop.py — no circular imports.

**Key constraint**: Functions/constants tested directly via `game_loop.X` references in test files MUST stay in game_loop.py. Identified from test_game_loop.py and test_engineering.py: `_drain_queue`, `_apply_engineering`, `_build_ship_state`, `OVERCLOCK_DAMAGE_HP`, `OVERCLOCK_THRESHOLD`, `POWER_BUDGET`, and the `random` module import (patched via `patch("server.game_loop.random")`).

**Alternatives considered**:
- Pass all state as function parameters (no module-level state in sub-modules) — rejected: verbose and creates awkward coupling between game_loop.py's start() and sub-module init
- Move handle_enemy_beam_hits() inline to _loop() — rejected: would keep _loop() too long to reach <350-line target

---

## 2026-02-19 — Split messages.py into namespace package (Session 0.1b)

**Decision**: Split `server/models/messages.py` (255 lines) into `server/models/messages/` package: `base.py` (Message envelope + validate_payload + _PAYLOAD_SCHEMAS), plus one namespace file per station domain (lobby, helm, engineering, weapons, science, captain, game, world). The `__init__.py` re-exports all symbols for backward compatibility.

**Reasoning**: The monolithic messages.py was the single largest models file and mixed concerns across all station domains. The namespace split makes it easy to find where a payload lives, and each file stays under 150 lines. The re-export pattern in __init__.py ensures zero changes to any import site.

**Key constraint**: `base.py` imports FROM the namespace files (to build _PAYLOAD_SCHEMAS). Namespace files do NOT import from base.py. This keeps the import graph acyclic.

**Alternatives considered**:
- Keep as a single file — rejected: violates the <300-line file convention, increasingly hard to navigate as more message types are added
- Use `*` re-exports in __init__.py — rejected: hides what's actually exported; explicit re-exports + __all__ are more maintainable

---

## 2026-02-19 — mission.py: schema documentation models

**Decision**: Filled `server/models/mission.py` with Pydantic models (`MissionDefinition`, `ObjectiveDefinition`, `TriggerDefinition`, `EventDefinition`, `SpawnEntry`, `AsteroidEntry`) that document the mission JSON schema. These are NOT used to validate the dicts at runtime — the mission engine continues to use raw dicts for simplicity.

**Reasoning**: The placeholder was useless. The models now serve as canonical schema documentation and can be used to validate mission JSON files during authoring (run `MissionDefinition.model_validate(load_mission(id))` to check a file). Runtime behaviour unchanged.

---

## 2026-02-19 — Session 2a.1: crew_factor as deterministic efficiency multiplier

**Decision**: `ShipSystem._crew_factor` is a float field defaulting to 1.0. `efficiency` becomes `(power/100) * (health/100) * _crew_factor`. Crew casualties are applied deterministically: `int(hull_damage / CREW_CASUALTY_PER_HULL_DAMAGE)` — no extra `rng.random()` call. Deck selection uses `rng.choice()` on the existing rng object.

**Reasoning**: Deterministic casualty count keeps the combat function's rng call pattern unchanged relative to existing tests. Existing tests that mock `rng.choice.return_value = "engines"` still pass because "engines" is not a valid crew deck key — `ship.crew.decks.get("engines")` returns None → `apply_casualties` is a graceful no-op. All 331 existing tests pass unmodified.

**Alternatives considered**:
- Extra `rng.random()` roll for crew casualties — rejected: changes call count on the mock, would require updating existing tests (violates the zero-test-modification constraint)

---

## 2026-02-19 — Session 2a.1: DECK_SYSTEM_MAP splits weapons/shields on Deck 3

**Decision**: Physical Deck 3 (Combat) has four rooms: weapons_bay and torpedo_room belong to crew deck "weapons" (maps to beams+torpedoes systems); shields_control and combat_info belong to crew deck "shields" (maps to shields system). This gives all 6 crew decks physical rooms even though the ship has only 5 physical decks.

**Reasoning**: The DECK_SYSTEM_MAP from the v0.02 scope defines 6 logical crew decks. The ship interior has 5 physical decks (4 rooms each, 20 rooms total). Splitting Deck 3 between weapons and shields crew decks is the cleanest fit — these are operationally distinct functions that happen to occupy adjacent spaces on the same deck.

---

## 2026-02-19 — Session 2b: Puzzle trigger matching uses mission-author labels, not auto-generated puzzle IDs

**Decision**: The `puzzle_completed` and `puzzle_failed` trigger types in mission JSON reference puzzles by a `puzzle_label` field (e.g. `"args": { "puzzle_label": "sequence_1" }`). The `start_puzzle` on_complete action includes a `"label"` field. The puzzle engine maintains a `_label_to_id` map and reports resolved puzzles by label. The mission engine stores completed/failed labels in sets (`_completed_puzzle_labels`, `_failed_puzzle_labels`). `notify_puzzle_result(label, success)` takes the label string, not the auto-generated puzzle_id.

**Reasoning**: The auto-generated puzzle IDs (`"puzzle_1"`, `"puzzle_2"`) depend on the creation order within a game session. If two `start_puzzle` actions fire before the first resolves, the IDs shift. Mission authors would need to track creation order to write correct triggers — fragile and unintuitive. Labels are stable, mission-authored identifiers that mission writers control. Any future mission that starts a puzzle can declare its label in `start_puzzle` and reference it unambiguously in `puzzle_completed`. This is the same principle as using named entity IDs (`"enemy_1"`, `"station_kepler"`) for scan/destroy triggers rather than referencing by index.

**Consequences**: Every `start_puzzle` action in mission JSON must include a `"label"` field. Every `puzzle_completed` / `puzzle_failed` trigger must use `"puzzle_label"` not `"puzzle_id"` in args. The label→id mapping in PuzzleEngine exists for internal routing but is not exposed in triggers.

**Alternatives considered**:
- Auto-ID based triggers — rejected: fragile; creation order dependency breaks when multiple puzzles start near simultaneously
- Persistent UUID per puzzle type — rejected: overkill for mission authoring; human-readable labels are sufficient and easier to reason about in JSON files

---

## 2026-02-19 — Sequential objective model limitation: no compound "all_of" trigger (Session 2b2)

**Decision**: The sequential objective model is retained for v0.02b2. The Engineering Drill mission uses a three-objective chain (timer → freq_completed → circuit_completed) where the second puzzle may finish before the first is checked, causing an instant advance through objective 3.

**Known limitation**: The sequential model does not elegantly handle "complete these N tasks in any order." Missions that need parallel completion (e.g. "both Science AND Engineering solve their puzzles") currently require N sequential objectives, which means whichever puzzle finishes second auto-completes its objective instantly (no additional player interaction required). The UX "flash" is acceptable for the framework test mission but is not suitable for story missions.

**Required future work**: A compound trigger type — `all_of: [condition_A, condition_B]` — on a single objective. This would allow "advance when ALL of these sub-conditions are met, in any order." The trigger evaluator would maintain a set of satisfied sub-conditions and only fire the objective when all are in the set. This is a backward-compatible addition to the trigger system.

**Why not now**: The Engineering Drill is a framework test mission, not a story mission. The flash is acceptable and the added trigger type needs careful design (handling reset, sub-condition state, serialisation) that is out of scope for v0.02b2.

**Alternatives considered**:
- Redesign the mission engine as a DAG (directed acyclic graph) — deferred: correct long-term but requires rewriting all missions and mission tooling
- Use a timer-based consolidation objective (wait N seconds after first puzzle resolves, then check second) — rejected: brittle, delay feels arbitrary to players

---

## 2026-02-19 — on_complete supports list of actions (Session 2b2)

**Decision**: The `on_complete` field in mission JSON objective definitions now supports either a single action dict OR a list of action dicts. The mission engine branches on `isinstance(on_complete, list)` to extend vs append to `_pending_actions`. All existing missions with single-dict `on_complete` are unaffected.

**Reasoning**: Starting two puzzles simultaneously (Engineering Drill) requires one timer trigger to fire two `start_puzzle` actions. Introducing list support is the minimal change with zero backward-compatibility cost.

**Alternatives considered**:
- Wrapper action type `multi_action: [...]` — rejected: extra nesting with no benefit over a bare list
- Two sequential objectives with the same timer trigger — rejected: only one objective is active at a time; the second timer would never fire until the first objective completed

---

## 2026-02-19 — v0.02c Security: AP regen = 1 per 5 ticks (Q1)

**Decision**: Marine squad action points regenerate at 0.2 AP per tick (1 AP per 5 ticks). The pool is 10 AP, which fills completely in 50 ticks = 5 seconds. Moving costs 3 AP = requires 15 ticks of regen from empty = 1.5 seconds of waiting. Door control costs 2 AP.

**Reasoning**: At 0.2 AP/tick, a squad with an empty pool can move again after 1.5 seconds, which is fast enough to feel responsive but slow enough to require tactical commitment. A full-pool squad can move 3 times before needing to regen (~4.5 seconds of continuous movement). This creates genuine "action economy" choices without feeling sluggish. If playtesting shows moves are too frequent, raise AP_COST_MOVE rather than slowing regen.

**Correction noted**: The v0.02 scope document contained a math error ("25 seconds to fill pool"). The correct calculation is 10 AP ÷ 0.2 AP/tick × 0.1 s/tick = 5 seconds. The 25-second figure was based on an incorrect assumption of 1 AP per 25 ticks rather than 1 AP per 5 ticks.

**Constants** (in `server/models/security.py`):
- `AP_MAX = 10.0`
- `AP_REGEN_PER_TICK = 0.2` (i.e., 1.0 / 5)
- `AP_COST_MOVE = 3`
- `AP_COST_DOOR = 2`

**Alternatives considered**:
- Slower regen (1 AP per 25 ticks) — rejected: too punishing; squad can only move once per ~37 seconds from empty
- Real-time seconds instead of ticks — rejected: keeps all game logic in tick-units; seconds are only in presentation layer

---

## 2026-02-19 — v0.02c Security: Tactical positioning = planning phase puzzle (Q2)

**Decision**: The tactical positioning puzzle uses a planning-phase design. When a boarding alert fires, Science receives a threat assessment and Security gets a 60-second window to reposition marines. Boarding begins only after the player submits their positions (or the timer expires). During the planning phase, intruders are shown on the map in their starting positions but do not move.

**Reasoning**: The PuzzleInstance lifecycle (start → interact → submit → validate_submission → result broadcast) assumes a discrete "solve it, then see the outcome" structure. Bending this lifecycle for real-time scoring would require either hacking `validate_submission` to be stateful, or adding a new puzzle resolution path — neither is acceptable. The planning-phase design maps cleanly onto the existing lifecycle: `validate_submission` checks whether the submitted marine positions produce a successful defence outcome (scoring the simulated boarding encounter), and the subsequent "boarding unfolds" phase is a non-interactive consequence sequence, not a puzzle mechanic.

**Gameplay benefit**: Security sees the threat assessment, can discuss with the crew (verbally), and then commits positions. The drama is in the decision and the reveal, not in frantic real-time clicking.

**Alternatives considered**:
- Live scoring (score updates as marines move during boarding) — rejected: requires bending the puzzle lifecycle; adds a new resolution path with significant complexity
- No puzzle, just real-time boarding mini-game — deferred to v0.03: valid long-term design but requires the full boarding simulation infrastructure first

---

## 2026-02-19 — v0.02c Security: Fog of war via passive sensor efficiency (Q3)

**Decision**: Server-side fog of war uses a passive sensor efficiency threshold (`SENSOR_FOW_THRESHOLD = 0.5`). When building the `security.interior_state` broadcast, intruders are included in the payload only if: (a) a marine squad occupies the same room, OR (b) `ship.systems["sensors"].efficiency >= SENSOR_FOW_THRESHOLD`. When sensors are below 50%, only directly-observed intruders (squads in same room) are visible.

**Reasoning**: Reuses the existing sensor efficiency mechanic with no new UI or Science station interaction. Engineering's power allocation directly affects the Security station's situational awareness, reinforcing crew interdependencies. Active internal scanning is a richer mechanic but adds a full Science UI sub-feature that is out of scope for v0.02c.

**Implementation**: `is_intruder_visible(intruder, marine_squads, sensor_efficiency)` in `server/models/security.py`. Called per-intruder when building the `security.interior_state` payload. Server never sends invisible intruders to the client.

**Alternatives considered**:
- Active internal scanning (Science pings a room to reveal intruders) — deferred to v0.03
- Always-visible intruders (no fog of war) — rejected: removes strategic depth; Security would always have perfect information

---

## 2026-02-19 — v0.02c Security: Static interior layout in game.started (Q4)

**Decision**: The static room layout (room IDs, names, positions, connections, initial states) is included in the `game.started` payload as `"interior_layout"` — a list of room dicts. Dynamic state (squad positions, intruder visibility-filtered positions, room conditions, door states) is sent per-tick in `security.interior_state` to the `["security"]` role only.

**Reasoning**: The interior layout is small (~2 KB), stable for the lifetime of a game session, and needed by multiple future stations (Medical for treatment routing, Engineering for repair dispatch, Security for the tactical map). Including it in `game.started` means every station page can access the layout from session storage without a separate request/message. Dynamic state belongs in per-tick role-filtered broadcasts because it changes frequently and contains security-sensitive data (intruder positions).

**Alternatives considered**:
- Separate `interior.layout` message on connect — rejected: requires a new message type, an additional round trip, and handling on every station page that needs layout data
- Fetch interior layout via HTTP GET — rejected: adds a REST endpoint for data that is logically part of game initialisation

---

## 2026-02-19 — Cross-station sensor assist uses passive efficiency detection (Session 2b2)

**Decision**: When Science has an active `frequency_matching` puzzle, Engineering assists Science automatically when `ship.sensors.efficiency >= 1.2` (120%). There is no explicit "RELAY ASSIST" button on Engineering. Engineering receives a `puzzle.assist_available` notification panel telling them what to do; the assist fires once as soon as the power threshold is crossed and is not re-applied.

**Reasoning**: The power slider IS the action. Adding a confirmation button would create a two-step interaction (boost power → click relay) with no strategic value — boosting sensors already costs from the power budget, which is the commitment. The notification tells Engineering what the target is; crossing it is sufficient signal of intent. This keeps the interaction feel physical (dial the power up) rather than administrative (click a button).

**Consequences**: The `_check_sensor_assist()` function in `game_loop.py` runs each tick after `_apply_engineering()`. It duck-type-checks for `_tolerance` (a `FrequencyMatchingPuzzle` attribute) to confirm the puzzle type. Applied assists are tracked in `_applied_sensor_assists: set[str]` (cleared on game start). When applied, a `puzzle.assist_sent` message goes to Engineering confirming the relay.

**Alternatives considered**:
- Explicit RELAY ASSIST button on Engineering — rejected: administrative feel; removes the physical-constraint metaphor
- Comms station provides the assist (per scope) — deferred to v0.02d; Engineering sensor power is the v0.02b2 assist because it uses existing mechanics
- Re-apply assist continuously while sensors > 1.2 — rejected: would rapidly stack tolerance to max; one application per puzzle is the right balance

---
