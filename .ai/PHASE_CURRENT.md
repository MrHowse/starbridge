# Current Phase: Phase 3 — Engineering Station + Power System

> Replace this file's contents when moving to a new phase.

## Goal

Engineering controls power distribution across the ship's six systems. Other systems
respond to power levels in real time — reducing engine power slows the ship, boosting
manoeuvring makes turns snappier, and running systems above 100% risks gradual
heat/damage. This phase proves that multi-station interdependence works: Engineering
actions have immediate, visible effects on Helm.

## What This Phase Proves

- The Engineering station can adjust power levels and those changes propagate to physics
- System health degrades efficiency and can be repaired over time
- Overclock (>100%) works as a risk/reward mechanic
- The ship's behaviour visibly changes when power is redistributed (Helm sees this)
- A second player at Engineering and a first at Helm can coordinate meaningfully

## Power System (Section 3.4 / 4.1)

```
Power Pool: 300 units total (6 systems × 50 average = 300 baseline)
Each system: 0–150% power (0–150 units)
Overclock threshold: >100% per system → gradual heat/damage risk (Phase 3 Tier 1: damage risk only)

Systems:
├── engines      — max_speed    = BASE_MAX_SPEED    × efficiency
├── beams        — (Phase 4 — beam damage + recharge)
├── torpedoes    — (Phase 4 — reload speed)
├── shields      — (Phase 4 — shield strength)
├── sensors      — (Phase 5 — scan range + speed)
└── manoeuvring  — turn_rate    = BASE_TURN_RATE     × efficiency

efficiency = (power / 100) × (health / 100)    ← already implemented in ship.py
```

## Tasks (from Scope Document)

### Server
- [ ] Power allocation message — `engineering.set_power` handler + payload schema
- [ ] Power budget enforcement — reject allocations that exceed pool (300 units total)
- [ ] Repair allocation message — `engineering.set_repair` handler + payload schema
- [ ] Repair mechanic — focused system heals at `REPAIR_RATE` HP/tick; only one system at a time
- [ ] Overclock risk mechanic — system at >100% power has a chance per tick of taking damage
- [ ] `engineering.py` — `handle_engineering_message()`: validates and enqueues inputs
- [ ] Add `engineering` to routing table in `main.py`
- [ ] Add Phase 3 payload schemas to `messages.py`
- [ ] Game loop: drain engineering queue inputs each tick (alongside helm inputs)
- [ ] `ship.state` broadcast: already includes system power + health — no change needed

### Client
- [ ] Engineering client: ship cross-section diagram (canvas or SVG) showing all 6 systems
- [ ] Engineering client: power sliders for each system (0–150%) with live readout
- [ ] Engineering client: total power budget indicator (used / 300, red when over)
- [ ] Engineering client: system health bars (0–100%)
- [ ] Engineering client: repair allocation buttons (click to focus repair on a system)
- [ ] Engineering client: connect to WS, handle `game.started`, receive `ship.state`

### Tests
- [ ] `tests/test_engineering.py` — handler validates payload, enqueues, rejects invalid
- [ ] `tests/test_physics.py` — extend: verify max_speed / turn_rate change with power levels
- [ ] Integration test: set engine power → next tick ship_state shows changed max_speed

## Session Breakdown

### Session 3a: Power System + Engineering Handler
**Build**: `engineering.py` handler, Phase 3 message schemas, power budget enforcement,
overclock risk mechanic, repair mechanic, game loop drain of engineering queue.
**Test**: Unit tests for handler, power budget, overclock, repair.

### Session 3b: Engineering Client
**Build**: Engineering station HTML/JS/CSS — power sliders, budget indicator, health bars,
repair allocation, cross-section diagram. Connect to WS, receive ship.state updates.
**Test**: Visual verification — adjust engine slider → Helm sees speed change. Reduce
manoeuvring → Helm turns sluggishly. Overclock engines → health degrades over time.

## Key Files to Create / Modify

### Server (new)
- `server/engineering.py` — `handle_engineering_message()`, power + repair queue processing

### Server (modified)
- `server/models/messages.py` — add `EngineeringSetPowerPayload`, `EngineeringSetRepairPayload`
- `server/game_loop.py` — drain engineering inputs each tick; apply repair + overclock damage
- `server/main.py` — add `engineering` handler to routing table; wire engineering queue

### Client (new)
- `client/engineering/index.html` — full Engineering station layout
- `client/engineering/engineering.js` — power sliders, budget, health, repair allocation, WS handling
- `client/engineering/engineering.css` — layout for engineering panels

### Tests (new)
- `tests/test_engineering.py` — handler unit tests

## Acceptance Criteria (Phase Gate)

- [ ] Engineering can adjust power sliders for each of the 6 systems
- [ ] Total power budget indicator shows used / available and highlights over-allocation
- [ ] Reducing engine power → Helm's ship moves slower (max_speed decreases)
- [ ] Boosting manoeuvring power → Helm's ship turns faster
- [ ] Running a system above 100% → that system's health gradually decreases
- [ ] Allocating repair to a damaged system → health recovers at a visible rate
- [ ] System at 0 health → offline (efficiency = 0), power slider still moveable
- [ ] All new tests pass (`pytest`)
- [ ] `.ai/STATE.md` accurately reflects Phase 3 state

## Out of Scope for Phase 3

- Beam/torpedo/shield power effects (Phase 4)
- Sensor power effects (Phase 5)
- Coolant system / heat routing (Tier 2, post-v0.01)
- Individual component failure within a system (Tier 3, post-v0.01)
- Power conduit routing (Tier 4, post-v0.01)
- Enemy ships / combat (Phase 4)
- Mission objectives (Phase 6)
