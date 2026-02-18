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
