# Code Conventions

> **LIVING DOCUMENT** — Update this file when new patterns are established.
> Last updated: 2026-02-18 (Session 3c — canvas convention clarified, engineering schematic pattern)

## Python (Server)

### Naming

- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions/methods: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private methods: `_leading_underscore`

### Type Hints

- All function signatures must have type hints
- Use `from __future__ import annotations` in every file
- Pydantic models for all WebSocket messages
- Dataclasses for game state objects

### Imports

- Standard library first, then third-party, then local
- Absolute imports only (`from server.models.ship import Ship`)
- One blank line between import groups

### Game Loop

- All game logic runs in the `tick()` function chain
- No game state modification outside the game loop
- Client messages are queued and processed at the start of each tick

### messages package re-export pattern (Session 0.1b)

When splitting a module into a package, the `__init__.py` must re-export every public symbol so all existing `from server.models.messages import X` imports work unchanged. Use explicit `from .namespace import X` re-exports (not `*`) and maintain an `__all__` list. The package structure: `base.py` holds the central class and dispatcher; namespace files hold grouped payload models; `base.py` imports FROM the namespace files to build the dispatch table (not the other way around — avoids circular imports).

### game_loop splitting pattern (Session 0.1a)

The game loop is split into 4 files. Each sub-module is **stateful** (module-level state + `reset()`) following the `sensors.py` pattern:
- `game_loop.py` — orchestrator only; keeps `_drain_queue`, `_apply_engineering`, `_build_ship_state`, engineering constants, `random` import (test-anchored). No inline mission logic.
- `game_loop_physics.py` — timing constants (`TICK_RATE`, `TICK_DT`)
- `game_loop_weapons.py` — weapons state (target, ammo, cooldowns, entity counter), fire/tick helpers, `handle_enemy_beam_hits()`
- `game_loop_mission.py` — mission engine, signal scan, docking, per-tick mission update, broadcast builders (`build_world_entities`, `build_sensor_contacts`)
- Sub-modules imported as `import server.game_loop_weapons as glw` / `import server.game_loop_mission as glm` — no circular imports.
- Functions that tests call directly MUST stay in `game_loop.py` (check `tests/test_game_loop.py` and `tests/test_engineering.py` before moving anything).

### Error Handling

- WebSocket message validation via Pydantic (invalid messages are logged and dropped)
- No bare `except` clauses — always catch specific exceptions
- Game loop must never crash — catch and log errors per-entity
- Use Python's `logging` module, not `print()`

### File Structure

- Target max ~300 lines per file
- Split when a file exceeds this or has multiple distinct responsibilities
- Each module has a docstring explaining its purpose

## JavaScript (Client)

### Naming

- Files: `snake_case.js` (matching the station/module name)
- Functions: `camelCase`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- DOM element references: `camelCase` with type suffix (e.g., `radarCanvas`, `throttleSlider`)

### Modules

- ES module imports (`import { x } from './module.js'`)
- Each station is a self-contained module with an `init()` entry point
- Shared code in `client/shared/`
- No build step, no bundler, no npm

### Canvas Rendering

- `requestAnimationFrame` for render loop — render loop runs indefinitely while game is active
- Shared/reusable canvas utilities go in `client/shared/renderer.js` (starfield, compass, minimap, chevron, lerp, worldToScreen). Import these from station modules.
- Station-specific canvas drawing (e.g. the Engineering ship schematic) lives in the station module itself — do not force station-specific draw calls into renderer.js.
- Interpolate between server ticks for smooth 60fps movement (see Interpolation Pattern below)
- All coordinates transformed: world space → screen space via `worldToScreen()`
- Wireframe only — `strokeStyle`, never `fillStyle` (except background fill and translucent glow effects)
- Clear canvas each frame, full redraw (`drawBackground()` first)
- Canvas element is sized to its CSS container via `ResizeObserver` or container `.clientWidth/Height`

### Interpolation Pattern

The server broadcasts state at 10 Hz (TICK_MS = 100ms). The rAF loop renders at 60fps.
Use two-state interpolation for smooth visuals:

```javascript
// Store previous and current server state + timestamp of current arrival.
let prevState = null, currState = null, lastTickTime = 0;

function handleShipState(payload) {
  prevState    = currState;
  currState    = payload;
  lastTickTime = performance.now();
}

function getInterpolatedState() {
  if (!currState) return null;
  if (!prevState) return currState;
  const t = Math.min((performance.now() - lastTickTime) / TICK_MS, 1.0);
  return {
    heading:  lerpAngle(prevState.heading,  currState.heading,  t),
    velocity: lerp(prevState.velocity,      currState.velocity, t),
    throttle: currState.throttle,  // discrete — do not lerp
    position: {
      x: lerp(prevState.position.x, currState.position.x, t),
      y: lerp(prevState.position.y, currState.position.y, t),
    },
  };
}
```

- Use `lerpAngle(a, b, t)` for heading (shortest-path, handles 359→1 wrapping)
- Use `lerp(a, b, t)` for velocity and position
- Do NOT lerp discrete values like throttle, alert level, or system health

### renderer.js API

All exported from `client/shared/renderer.js`:

| Export | Description |
|---|---|
| `lerp(a, b, t)` | Linear interpolation |
| `lerpAngle(a, b, t)` | Shortest-path angle lerp (degrees) |
| `worldToScreen(wx, wy, camX, camY, zoom, cw, ch)` | World → canvas pixel coords |
| `createStarfield(count)` | Generate star array — call once, store |
| `drawBackground(ctx, w, h)` | Fill canvas with `--bg-primary` colour |
| `drawStarfield(ctx, w, h, heading, shipX, shipY, stars)` | Parallax starfield, rotates with heading |
| `drawCompass(ctx, size, currentHeading, targetHeading)` | Rotating compass card dial |
| `drawShipChevron(ctx, cx, cy, headingRad, halfSize, colour)` | Wireframe chevron at given position |
| `drawMinimap(ctx, size, shipX, shipY, heading)` | Full sector overview with ship position |

Colour constants: `C_PRIMARY`, `C_PRIMARY_DIM`, `C_PRIMARY_GLOW`, `C_FRIENDLY`, `C_BG`, `C_GRID`.

### WebSocket

- Single connection per client via `shared/connection.js`
- Messages are JSON with the standard envelope format
- Connection manager handles reconnection with exponential backoff
- Message handlers registered via `on(messageType, callback)` pattern
- Status change handlers registered via `onStatusChange(callback)` — receives `'connected' | 'reconnecting' | 'disconnected'`
- Send via `send(type, payload)` — drops silently if socket not open (warns to console)
- Call `connect()` once on page load; reconnection is automatic

### Station module pattern

- Every station page imports from `../shared/connection.js` and `../shared/ui_components.js`
- Entry point is an `init()` function called from `DOMContentLoaded`
- Sequence: register status handler → register message handlers → call `connect()`
- DOM elements referenced by `data-*` attributes, not class names

### Shared UI helpers (`ui_components.js`)

- `setAlertLevel(level)` — swaps `--primary` CSS variables on document root
- `setStatusDot(el, status)` — updates `.status-dot` class suffix
- `redirectToStation(role)` — navigates to `/client/{role}/` (falls back to viewscreen)

## CSS

### Naming

- BEM-style: `.station-panel`, `.station-panel__header`, `.station-panel--alert`
- All theme colours via CSS custom properties (`var(--primary)`, etc.)
- No inline styles in HTML

### Structure

- `shared/theme.css` loaded by all stations (colours, fonts, base elements)
- Station-specific CSS in station folder
- Mobile/responsive breakpoints at 768px and 1024px

### Theme Variables

- All colours defined as CSS custom properties in `:root`
- Alert level changes swap `--primary` and related variables
- Functional colours: `--friendly`, `--hostile`, `--neutral`, `--unknown`

## HTML

### Structure

- HTML5 doctype, lang="en"
- Load order: theme.css → station.css → shared JS modules → station JS
- Semantic elements where appropriate
- `data-*` attributes for JS hooks, not class names

## General

### Commit Messages

- `Phase X: Brief description of what was added`
- `Fix: Description of bug and fix`
- `Refactor: What was changed and why`

### File Size

- Target max ~300 lines per file
- Split when a file exceeds this or has multiple distinct responsibilities

### Documentation

- Python: module docstrings, function docstrings for non-obvious functions
- JavaScript: JSDoc comments for exported functions
- CSS: comment blocks for major sections
