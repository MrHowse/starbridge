# Current Phase: Phase 2 — Game Loop + Ship Model + Helm Station

> Replace this file's contents when moving to a new phase.

## Goal

A ship that exists in a 2D world, can be steered by the Helm station, and whose
movement is visible on a canvas viewscreen. This phase proves that the game loop
architecture works, ship physics are deterministic, and client rendering can stay
smooth between server ticks.

## What This Phase Proves

- The asyncio game loop runs independently of WebSocket message handling
- The ship model is server-authoritative (clients send intentions, server moves the ship)
- Physics are deterministic and testable (thrust, heading, speed limits, turn rate)
- State is broadcast every tick to connected clients in a role-filtered way
- The Helm client can control the ship and see its own movement in real time
- A non-Helm client (e.g. a second browser tab) sees the same ship state update

## Ship Model (Section 3.4)

```
Ship: "TSS Endeavour"
├── Hull: 100 HP
├── Systems (each has power: 0-150%):
│   ├── engines      — affects max speed
│   ├── beams        — affects beam damage + recharge (Phase 4)
│   ├── torpedoes    — affects reload speed (Phase 4)
│   ├── shields      — affects shield strength (Phase 4)
│   ├── sensors      — affects scan range + speed (Phase 5)
│   └── manoeuvring  — affects turn rate
├── Shields: front 0-100%, rear 0-100%
├── Weapons: 2 beam banks, 2 torpedo tubes (Phase 4)
└── Movement:
    ├── position:  (x, y) in world units
    ├── heading:   0-359° (0 = north/up, clockwise)
    ├── velocity:  current speed (world units/sec)
    ├── throttle:  0-100% (player-set target speed fraction)
    ├── max_speed: f(engines power)
    └── turn_rate: f(manoeuvring power)
```

All 6 systems present in the model from Phase 2. Only engines and manoeuvring
actively affect physics in Phase 2. Others default to 100% power and are connected
in Phase 3 (Engineering).

## Tasks (from Scope Document)

### Server
- [ ] Game loop — `asyncio` task, 10 ticks/sec, fixed timestep (TICK_RATE = 10)
- [ ] Ship model — `Ship` dataclass: position, heading, velocity, throttle, hull, shields, systems
- [ ] `ShipSystem` dataclass — name, power, health, efficiency
- [ ] Physics system — apply throttle → velocity, move in heading direction, clamp to max_speed(engine power), apply turn_rate(manoeuvring power)
- [ ] World model — `World` dataclass: sector bounds (100k × 100k), entity list
- [ ] State broadcast each tick — `ship.state` to all connected clients (role-filtered later)
- [ ] Handle `helm.set_heading` and `helm.set_throttle` messages
- [ ] Add `helm` to routing table in main.py
- [ ] Add Phase 2 payload schemas to messages.py
- [ ] Add Phase 2 messages to docs/MESSAGE_PROTOCOL.md

### Client
- [ ] Helm client: heading control (compass dial, keyboard arrow support)
- [ ] Helm client: throttle control (vertical slider)
- [ ] Helm client: forward viewscreen (canvas — wire starfield that rotates with heading)
- [ ] Helm client: sector minimap (canvas — ship position + heading in 100k × 100k sector)
- [ ] Client-side tick interpolation (smooth 60fps between 10tps server updates)

## Session Breakdown

### Session 2a: Game Loop + Ship Model + Physics
**Build**: Game loop task, `Ship`/`ShipSystem`/`World` models in `server/models/ship.py`
and `server/models/world.py`, physics in `server/systems/physics.py`, helm message
handler in `server/helm.py`, state broadcast each tick, wire up routing in main.py.
**Test**: Physics unit tests, tick timing, state broadcast shape.

### Session 2b: Helm Client
**Build**: Heading and throttle controls, forward viewscreen canvas (parallax wire starfield),
sector minimap canvas, client-side interpolation between server ticks.
**Test**: Visual verification — ship moves on minimap when throttle increases, viewscreen
rotates when heading changes. A second tab sees position update.

## Key Files to Create / Modify

### Server (new)
- `server/models/ship.py` — `Ship`, `ShipSystem`, `Shields`, `Weapon` dataclasses
- `server/models/world.py` — `World`, `Entity`, `Position` dataclasses
- `server/systems/physics.py` — `tick(ship, dt)` — apply movement physics
- `server/game_loop.py` — asyncio task, fixed timestep, calls physics.tick + broadcast
- `server/helm.py` — `handle_helm_message()`, queues heading/throttle intents

### Server (modified)
- `server/main.py` — start/stop game loop task on game start; add `helm` handler
- `server/models/messages.py` — add `HelmSetHeadingPayload`, `HelmSetThrottlePayload`, `ShipStatePayload`
- `server/utils/math_helpers.py` — add `angle_towards()` or `delta_angle()` helper if needed

### Client (new/modified)
- `client/helm/index.html` — full Helm station layout
- `client/helm/helm.js` — heading + throttle controls, ship.state handler, interpolation
- `client/helm/helm.css` — layout for helm station panels

### Tests (new)
- `tests/test_physics.py` — ship movement, heading, speed clamping, turn rate
- `tests/test_ship.py` — Ship model defaults, system efficiency

## Acceptance Criteria (Phase Gate)

- [ ] Game loop starts when game is launched and ticks at 10 Hz
- [ ] Helm station loads with viewscreen canvas, heading control, throttle slider, minimap
- [ ] Moving throttle slider makes the ship move (minimap shows position changing)
- [ ] Changing heading rotates the viewscreen starfield
- [ ] Ship position wraps or clamps at sector boundary (decision to be made)
- [ ] A second browser tab (any role) receives `ship.state` updates and can log them
- [ ] All new tests pass (`pytest`)
- [ ] `docs/MESSAGE_PROTOCOL.md` updated with Phase 2 messages
- [ ] `.ai/STATE.md` accurately reflects Phase 2 state

## Out of Scope for Phase 2

- Engineering power sliders (Phase 3)
- Enemy ships / combat (Phase 4)
- Science scanning (Phase 5)
- Captain's station UI (Phase 6)
- Weapon firing
- Shield damage / hull damage
- Mission objectives
