# Project State

> **LIVING DOCUMENT** — Update after every AI engineering session.
> This is the single source of truth for what exists in the project.

**Last updated**: 2026-02-18 (Session 2c — Late-join fix, placeholder UX)
**Current phase**: Phase 2 — Ship Physics & Helm
**Overall status**: Phase 2 complete (server + client). 141 tests passing.

## What Exists

### Project Infrastructure
- Complete directory structure per scope document
- `.ai/` management files (SYSTEM_PROMPT, CONVENTIONS, STATE, DECISIONS, LESSONS, PHASE_CURRENT)
- `docs/` reference files (MESSAGE_PROTOCOL, MISSION_FORMAT, STYLE_GUIDE)
- `requirements.txt` with all dependencies
- `run.py` entry point — starts uvicorn, prints LAN connection URL
- `README.md` with setup instructions

### Server
- `server/main.py` — FastAPI app, GET / health check, static file serving, `/ws` WebSocket endpoint, JSON envelope parsing, category-based message routing; wires `helm`, `game_loop`, `World`, `input_queue`; registers `game_loop.start` as lobby game-start callback
- `server/connections.py` — `ConnectionManager`: connect/disconnect, metadata tagging (player_name, role, session_id, is_host), individual send, full broadcast, role-filtered broadcast, `all_ids()`
- `server/models/messages.py` — `Message` envelope (Pydantic), `Message.build()` factory, `Message.to_json()` with `exclude_none=True`; payload schemas for all Phase 1+2 client→server and server→client message types; `HelmSetHeadingPayload`, `HelmSetThrottlePayload`, `ShipStatePayload`; `validate_payload()` dispatcher
- `server/models/ship.py` — `ShipSystem` (name, power, health, `efficiency` property), `Shields` (front, rear), `Ship` dataclass (position, heading, target_heading, velocity, throttle, hull, shields, 6 systems). Ship starts at sector centre (50 000, 50 000).
- `server/models/world.py` — `World` dataclass (width=100 000, height=100 000, ship). `SECTOR_WIDTH` / `SECTOR_HEIGHT` module-level constants.
- `server/systems/physics.py` — `tick(ship, dt, w, h)`: `_turn` (shortest-path heading, snap to avoid drift), `_thrust` (accel/decel toward throttle target), `_move` (sin/cos translation, clamp+stop at boundary). Constants: BASE_MAX_SPEED=200, BASE_TURN_RATE=45, ACCELERATION=50, DECELERATION=80.
- `server/game_loop.py` — asyncio background task, TICK_RATE=10 Hz, TICK_DT=0.1 s. `init()`, `start(mission_id)`, `stop()`. Each tick: drain input queue → physics.tick → broadcast ship.state.
- `server/helm.py` — `handle_helm_message()`: validates payload (error.validation on failure), enqueues `(message.type, payload)` to shared `input_queue` for game loop.
- `server/lobby.py` — Full lobby logic + `register_game_start_callback()` wired to `game_loop.start`. `_start_game()` calls the callback after broadcasting `game.started`.
- `server/utils/math_helpers.py` — `wrap_angle`, `angle_diff`, `distance`, `lerp`
- All other server files remain placeholders

### Client
- `client/shared/theme.css` — Full wire aesthetic: CSS custom properties, reset, panels, buttons, gauges, status dots, scanline overlay, keyframe animations
- `client/shared/connection.js` — WebSocket manager: `on()`, `onStatusChange()`, `send()`, `connect()`, exponential backoff reconnection
- `client/shared/ui_components.js` — `setAlertLevel()`, `setStatusDot()`, `redirectToStation()`
- `client/lobby/index.html` — Lobby page
- `client/lobby/lobby.js` — Full lobby logic: role cards, claim/release, callsign validation (empty + max 20 chars), game.started freeze + redirect
- `client/lobby/lobby.css` — Lobby styles
- `client/shared/renderer.js` — Canvas utilities: `lerp`, `lerpAngle`, `worldToScreen`, `createStarfield`, `drawBackground`, `drawStarfield` (parallax 3-layer, heading rotation), `drawCompass` (rotating card), `drawShipChevron`, `drawMinimap`. Colour constants exported.
- `client/helm/index.html` — Full helm station layout: header bar, standby overlay, forward viewscreen (canvas), compass dial (canvas + click-to-set), throttle (vertical range input + gauge), sector minimap (canvas), telemetry readout panel.
- `client/helm/helm.css` — CSS grid layout (2-col, 2-row), vertical throttle slider, compass body, telemetry grid.
- `client/helm/helm.js` — Full helm logic: WS connection, two-state interpolation (10Hz → 60fps), rAF render loop, held-key controls (A/D/W/S + arrows, 10Hz rate-limit), compass click-to-set, throttle slider, minimap, telemetry.
- All other 5 station HTML/JS/CSS files — working connect + game.started handler (placeholder until later phases)

### Tests
- `tests/test_messages.py` — 28 tests: envelope, build, to_json, Phase 1+2 payload schemas, validate_payload
- `tests/test_connections.py` — 21 tests: connect/disconnect lifecycle, tag/get, get_by_role, send, broadcast, broadcast_to_roles
- `tests/test_lobby.py` — 27 tests: on_connect, on_disconnect, claim_role, release_role, start_game
- `tests/test_main.py` — 13 tests: GET /, WebSocket lifecycle, error handling, routing
- `tests/test_math_helpers.py` — 13 tests: wrap_angle (identity, zero, 359, 360, negative, large), angle_diff (CW, CCW, across zero, same, 180°, full circle)
- `tests/test_ship.py` — 15 tests: ShipSystem efficiency (full, half power, half health, combined, overclock, zero health), Shields defaults, Ship defaults (name, position, heading, velocity/throttle, hull, 6 systems, full efficiency, independence)
- `tests/test_physics.py` — 22 tests: max_speed/turn_rate scaling, heading turn (CW/CCW, snap, wrap, shortest path, at target), thrust (accel, decel, cap, floor), movement (N/S/E/W, displacement), boundary clamping (N/S/E, velocity zeroed, mid-sector safe)
- `pytest.ini` — `asyncio_mode = auto` configured

### Missions
- `missions/` directory exists, no mission files yet

## What Works

- `python run.py` starts the server on port 8666
- `GET /` returns server status JSON (`"phase": "2 — Ship Physics & Helm"`)
- Static files served from `/client/` path
- LAN IP address printed on startup
- `ws://<host>:8666/ws` accepts WebSocket connections
- Inbound messages are parsed, envelope-validated, and routed by category prefix
- Invalid JSON / schema errors return `error.validation` to the sender without crashing
- Full lobby flow: connect → welcome + state, claim/release role, host launch
- Game start triggers the game loop (asyncio task, 10 Hz)
- Game loop drains helm input queue, runs physics.tick, broadcasts ship.state each tick
- Helm messages (`helm.set_heading`, `helm.set_throttle`) validated and enqueued
- Physics: heading turns toward target (shortest path), velocity accelerates/decelerates to throttle target, ship translates in heading direction, clamped at sector boundary (velocity zeroed on hit)
- Helm station fully operational: forward viewscreen with parallax starfield, rotating compass dial, throttle lever, sector minimap, telemetry readout
- Ship.state interpolation: two-state buffer with `lerpAngle`/`lerp` gives smooth 60fps motion between 10Hz server ticks
- 139 pytest tests pass (`pytest`)

## Known Issues

- Pyright false positive: `"helm" is unknown import symbol` in `main.py` (namespace package without `__init__.py`; runtime works, same pattern as `lobby` and `game_loop`)
- All non-helm station pages (captain, weapons, engineering, science, viewscreen) are placeholders; they now clearly say "This station is not yet operational" and have a "← RETURN TO LOBBY" link

## Stable Files

- `server/connections.py` — stable
- `server/models/messages.py` — stable for Phase 2
- `server/models/ship.py` — stable for Phase 2
- `server/models/world.py` — stable for Phase 2
- `server/systems/physics.py` — stable for Phase 2
- `server/utils/math_helpers.py` — stable
- `server/lobby.py` — stable for Phase 2
- `client/shared/connection.js` — stable
- `client/shared/ui_components.js` — stable
- `client/shared/theme.css` — stable
- `client/shared/renderer.js` — stable for Phase 2 (will expand in later phases)
- `pytest.ini` — stable

## File Manifest

```
starbridge/
├── .ai/
│   ├── SYSTEM_PROMPT.md      — Base prompt for AI engineering sessions
│   ├── CONVENTIONS.md        — Code style and patterns (living doc)
│   ├── STATE.md              — THIS FILE — project state (living doc)
│   ├── DECISIONS.md          — Architecture decision log (append-only)
│   ├── LESSONS.md            — Lessons learned log (append-only)
│   └── PHASE_CURRENT.md      — Current phase brief
├── server/
│   ├── main.py               — FastAPI app, /ws WebSocket endpoint, message routing, Phase 2 wiring
│   ├── game_loop.py          — Fixed timestep simulation loop (10 Hz, asyncio task)
│   ├── helm.py               — Helm message handler: validate + enqueue
│   ├── lobby.py              — Full lobby: session, roles, host, claim/release/start, game-start callback
│   ├── connections.py        — ConnectionManager: connect/tag/broadcast/all_ids
│   ├── models/
│   │   ├── __init__.py       — Models package init
│   │   ├── ship.py           — Ship, ShipSystem (efficiency), Shields dataclasses
│   │   ├── world.py          — World (sector bounds + ship), SECTOR_WIDTH/HEIGHT constants
│   │   ├── mission.py        — [placeholder] Mission, Objective, Trigger, Event
│   │   └── messages.py       — Message envelope + Phase 1+2 payload schemas
│   ├── systems/
│   │   ├── __init__.py       — Systems package init
│   │   ├── physics.py        — tick(): turn + thrust + move with boundary clamping
│   │   ├── combat.py         — [placeholder] Damage calculation, weapon firing
│   │   ├── ai.py             — [placeholder] Enemy behaviour state machine
│   │   └── sensors.py        — [placeholder] Scanning, detection ranges
│   ├── missions/
│   │   ├── loader.py         — [placeholder] Mission file parser
│   │   └── engine.py         — [placeholder] Mission runtime
│   └── utils/
│       ├── __init__.py       — Utils package init
│       └── math_helpers.py   — wrap_angle, angle_diff, distance, lerp
├── client/
│   ├── shared/
│   │   ├── connection.js     — WebSocket manager (on/send/connect/backoff)
│   │   ├── renderer.js       — Canvas utilities: starfield, compass, minimap, chevron, lerp, worldToScreen
│   │   ├── theme.css         — Wire aesthetic base styles (full implementation)
│   │   ├── ui_components.js  — setAlertLevel, setStatusDot, redirectToStation
│   │   └── audio.js          — [placeholder] Sound manager (future)
│   ├── lobby/
│   │   ├── index.html        — Lobby page
│   │   ├── lobby.js          — Full lobby: role cards, claim/release, launch
│   │   └── lobby.css         — Lobby styles
│   ├── captain/
│   │   ├── index.html        — Captain station (placeholder, Phase 3)
│   │   ├── captain.js        — Connect + game.started handler
│   │   └── captain.css       — Placeholder layout
│   ├── helm/
│   │   ├── index.html        — Full helm station layout (viewscreen, compass, throttle, minimap, telemetry)
│   │   ├── helm.js           — Full helm logic: interpolation, rAF loop, controls, canvas renders
│   │   └── helm.css          — Helm CSS grid layout, throttle slider, compass body
│   ├── weapons/
│   │   ├── index.html        — Weapons station (placeholder, Phase 4)
│   │   ├── weapons.js        — Connect + game.started handler
│   │   └── weapons.css       — Placeholder layout
│   ├── engineering/
│   │   ├── index.html        — Engineering station (placeholder, Phase 3)
│   │   ├── engineering.js    — Connect + game.started handler
│   │   └── engineering.css   — Placeholder layout
│   ├── science/
│   │   ├── index.html        — Science station (placeholder, Phase 5)
│   │   ├── science.js        — Connect + game.started handler
│   │   └── science.css       — Placeholder layout
│   └── viewscreen/
│       ├── index.html        — Viewscreen (placeholder, Phase 7)
│       ├── viewscreen.js     — Connect + game.started handler
│       └── viewscreen.css    — Placeholder layout
├── missions/                  — [empty] Mission data files (Phase 6)
├── docs/
│   ├── MESSAGE_PROTOCOL.md   — Complete WebSocket message protocol reference
│   ├── MISSION_FORMAT.md     — [placeholder] Mission JSON schema (Phase 6)
│   └── STYLE_GUIDE.md        — Wire aesthetic visual guidelines
├── tests/
│   ├── __init__.py           — Tests package init
│   ├── test_messages.py      — 28 message model / validation tests
│   ├── test_connections.py   — 21 connection manager tests
│   ├── test_lobby.py         — 27 lobby logic tests
│   ├── test_main.py          — 13 HTTP + WebSocket integration tests
│   ├── test_math_helpers.py  — 13 math helper tests (wrap_angle, angle_diff)
│   ├── test_ship.py          — 15 ship model tests (ShipSystem, Shields, Ship)
│   └── test_physics.py       — 22 physics tests (derived quantities, turn, thrust, move, boundary)
├── pytest.ini                — asyncio_mode = auto
├── requirements.txt          — Python dependencies
├── run.py                    — Entry point: starts uvicorn server
└── README.md                 — Project overview and setup instructions
```

## Phase 2 Gate Checklist

- [x] `Ship`, `ShipSystem`, `Shields`, `World` dataclasses implemented and tested
- [x] `ShipSystem.efficiency = (power/100) × (health/100)` tested including overclock
- [x] `physics.tick()` — turn, thrust, move, boundary clamp all tested
- [x] `game_loop.py` — asyncio task, 10 Hz, queue drain → physics → broadcast
- [x] `helm.py` — validates and enqueues `helm.set_heading` / `helm.set_throttle`
- [x] `lobby.register_game_start_callback()` wired; `_start_game()` triggers loop
- [x] `main.py` wires `input_queue`, `World`, `helm.init`, `game_loop.init`
- [x] 139 tests pass
- [x] **Session 2b**: Helm client UI — compass dial, throttle lever, forward viewscreen, minimap, telemetry
- [x] Phase 2 acceptance test: launch game → open Helm → A/D to turn, W/S for throttle, watch starfield rotate and minimap update

## Next Steps

- **Phase 3**: Captain's station — alert level control, orders/comms, ship status overview
