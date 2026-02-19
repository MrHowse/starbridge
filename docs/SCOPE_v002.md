# STARBRIDGE — v0.02 Finalised Scope
## "The Depth Update"

> This document supersedes docs/SCOPE_v002_DRAFT.md. It incorporates findings
> from the v0.01 codebase audit and resolves all open design questions.

---

## 1. OVERVIEW

### 1.1 What v0.02 Adds

- **3 new roles**: Communications, Medical, Security
- **A puzzle engine**: Reusable framework for interactive station challenges
- **6 puzzle types**: Circuit routing, frequency matching, transmission decoding, triage, tactical positioning, route calculation
- **Cross-station assists**: Puzzles are solvable alone, dramatically easier with intel from other stations
- **Crew as a resource**: Personnel system with injuries, deck assignments, efficiency impact
- **Ship interior**: Deck map used by Engineering (repair routing), Medical (crew location), and Security (marine deployment)
- **Expanded existing roles**: Deeper mechanics for all v0.01 stations
- **New mission types**: First Contact Protocol, Plague Ship, Boarding Action, Nebula Crossing, Diplomatic Summit

### 1.2 Design Principles

All v0.01 principles carry forward. v0.02 adds:

- **Approach 2 philosophy, Approach 1 mechanics**: Puzzles are pattern-matching canvas interactions (solvable by one player). The inputs to the puzzle come from other stations. A Science decoding puzzle is solvable alone given enough time — but if Comms provides the cipher key and Engineering stabilises sensor power, it takes 10 seconds instead of 2 minutes. Assists are helpful, never required.

### 1.3 Key Architectural Decisions (Pre-Resolved)

These were identified during the codebase audit and are decided here to avoid re-litigation during implementation:

**Puzzle engine broadcasts via game loop, not directly.**
The puzzle engine is a pure state machine. It returns pending messages via `pop_pending_broadcasts()` (same pattern as the mission engine's `pop_pending_actions()`). The game loop collects these each tick and broadcasts them. This keeps the game loop as the single broadcast authority and avoids giving the puzzle engine a dependency on the connection manager.

**Security is real-time with action point regeneration.**
Marines have an action pool. Movement and positioning cost actions. Actions regenerate at a fixed rate per tick (e.g., 1 action per 5 ticks). Intruders move continuously per tick. This avoids embedding a turn-based system inside the real-time loop while still giving Security deliberate tactical pacing. Marines can't spam-move, but there's no "end turn" button — you spend actions as they become available.

**Crew factor initialises at 1.0 for backward compatibility.**
The crew data model is added in v0.02a. All crew start at 100% active/required, so `crew_factor = 1.0` and the existing `ShipSystem.efficiency` calculation is unchanged. Existing tests continue passing without modification. Crew damage mechanics only activate when Medical and the ship interior are built.

**Assist routing: puzzle engine exposes lookup, game loop does the wiring.**
The puzzle engine maintains `active_puzzles_by_station: dict[str, PuzzleInstance]`. When a `puzzle.request_assist` message arrives in `_drain_queue`, the game loop looks up the target puzzle via the puzzle engine and calls `puzzle.apply_assist()`. The puzzle engine returns the resulting `puzzle.assist_applied` message in its pending broadcasts. No new routing infrastructure needed.

**Don't retrofit puzzles into existing v0.01 missions.**
Existing missions (First Contact, Defend the Station, Search and Rescue) remain unchanged. New puzzle-enabled missions are added alongside them. This keeps v0.01 missions stable and avoids test migration risk.

---

## 2. SUB-RELEASE PLAN

### Dependency Graph

```
v0.01.1 (tech debt cleanup)
  └── v0.02a (crew model + ship interior data)
        ├── v0.02b (puzzle engine framework + proof-of-concept)
        │     └── v0.02b2 (circuit routing + frequency matching + first assist chain)
        │           ├── v0.02d (Comms station + transmission decoding)
        │           └── v0.02e (Medical expansion + triage puzzle)
        └── v0.02c (Security station + interior rendering + tactical puzzle)
              └── (v0.02c also needs v0.02a directly)

v0.02f (Helm route calculation + hazard navigation + Nebula Crossing)
v0.02g (Weapons loading + firing solutions + Captain authorisation)
v0.02h (Diplomatic Summit + full balance pass)
```

v0.02c and v0.02d have no dependency on each other and can be built in either order or in parallel.

v0.02f, v0.02g, and v0.02h are independent of each other and depend only on v0.02b2 (for puzzle integration).

---

## 3. v0.01.1 — TECH DEBT CLEANUP

**Purpose**: Clean the v0.01 codebase before building on it. No new features.

### Tasks

#### 3.1 Split game_loop.py (838 lines → ~4 files)

```
server/
├── game_loop.py              # Orchestrator: _loop(), _drain_queue() dispatch,
│                              # tick sequencing, broadcast assembly (~300 lines)
├── game_loop_weapons.py      # Beam/torpedo fire helpers, weapon queue processing
├── game_loop_physics.py      # Physics tick, entity movement, boundary clamping
└── game_loop_mission.py      # Mission engine integration, signal scan handling,
                               # docking timer, mission-specific queue interception
```

The split must preserve the exact same behaviour. All 331+ existing tests must pass without modification after the refactor.

#### 3.2 Extract mission-specific code from the game loop

- The `if payload.entity_id == "signal"` guard in `_drain_queue` and the `_handle_signal_scans()` function must move to the mission engine or to `game_loop_mission.py` as a mission-specific message interceptor.
- The resupply docking timer (lines 295-317) must move out of `_loop()` and into `game_loop_mission.py`.
- After extraction, `_drain_queue` and `_loop()` should contain zero mission-specific code.

#### 3.3 Split messages.py by namespace

```
server/models/
├── messages/
│   ├── __init__.py          # Re-exports: Message, validate_payload, create_message
│   ├── base.py              # Message envelope, create_message(), core validation
│   ├── lobby.py             # Lobby message payloads
│   ├── helm.py              # Helm message payloads
│   ├── weapons.py           # Weapons message payloads
│   ├── engineering.py       # Engineering message payloads
│   ├── science.py           # Science message payloads (including sensor.contacts)
│   ├── captain.py           # Captain message payloads
│   ├── game.py              # Game lifecycle payloads (started, over, tick)
│   └── world.py             # World entity payloads
```

The `__init__.py` re-exports ensure all existing imports (`from server.models.messages import ...`) continue working without change.

#### 3.4 Clean up server/models/mission.py

Either delete the placeholder or make it the home for mission-related data models (MissionDefinition, Objective, Trigger). Given that v0.02 expands the mission system, making it useful is the better choice.

#### 3.5 Update documentation

- Update `.ai/STATE.md` with the new file structure
- Update `.ai/CONVENTIONS.md` with the game_loop module splitting convention
- Update `docs/MESSAGE_PROTOCOL.md` if the split changes any import paths
- Log the refactoring decisions in `.ai/DECISIONS.md`

### Acceptance Criteria

- [ ] All existing tests pass (zero test modifications)
- [ ] game_loop.py is under 350 lines
- [ ] messages.py is split into namespace files, all under 150 lines each
- [ ] No mission-specific code in the main game loop orchestrator
- [ ] All existing imports continue working (re-exports in __init__.py)
- [ ] Server behaviour is identical (run all three missions, verify gameplay)

---

## 4. v0.02a — CREW SYSTEM + SHIP INTERIOR DATA MODEL

**Purpose**: Add the crew and ship interior data models. No new UI. Medical station Tier 1 (crew overview, basic treatment).

### 4.1 Crew Model

```python
@dataclass
class DeckCrew:
    deck_name: str              # "bridge", "engineering", "medical", etc.
    total: int                  # Total crew assigned to this deck
    active: int                 # Healthy and working
    injured: int                # Impaired, partial contribution
    critical: int               # Incapacitated, zero contribution, will die without treatment
    dead: int                   # Permanently lost

    @property
    def crew_factor(self) -> float:
        """Ratio of effective crew to required crew. 1.0 = fully staffed."""
        if self.total == 0:
            return 1.0
        effective = self.active + (self.injured * 0.5)  # Injured contribute half
        return min(effective / self.total, 1.0)
```

**Deck-to-system mapping** (static dict):
```python
DECK_SYSTEM_MAP = {
    "bridge": ["manoeuvring"],
    "sensors": ["sensors"],
    "weapons": ["beams", "torpedoes"],
    "shields": ["shields"],
    "engineering": ["engines"],
    "medical": [],              # No ship system, but crew health matters
}
```

**Efficiency integration**:
```python
# ShipSystem.efficiency becomes:
@property
def efficiency(self) -> float:
    return (self.power / 100.0) * (self.health / 100.0) * self._crew_factor

# _crew_factor defaults to 1.0 and is updated by the crew system each tick
```

### 4.2 Ship Interior Model

```python
@dataclass
class Room:
    id: str                     # "bridge", "engineering_bay", "medbay", etc.
    name: str                   # Display name
    deck: str                   # Which deck this room belongs to
    position: tuple[int, int]   # Grid position for rendering
    connections: list[str]      # IDs of adjacent rooms
    state: str                  # "normal", "damaged", "decompressed", "fire", "hostile"
    door_sealed: bool           # Whether the door to this room is sealed

@dataclass
class ShipInterior:
    rooms: dict[str, Room]
    # Marine squads and intruder positions added in v0.02c
```

The ship layout from the v0.02 draft (5 decks, 20 rooms) is defined as a static data structure, not hardcoded in rendering.

### 4.3 Medical Station (Tier 1)

**Screen**: Crew status overview by deck. Treatment interface (select injured/critical crew on a deck, assign treatment, healing over time). Medical supply counter (finite, resupplied at stations).

**Server**: Medical message handlers (`medical.treat_crew`, `medical.set_triage_priority`). Crew damage integrated into the existing `apply_hit_to_player()` pipeline — when the ship takes hull damage, crew on a random deck take casualties.

**Lobby**: Medical added as an available role. Minimum players for missions remain at 1 (for testing).

### Acceptance Criteria

- [ ] Crew model exists with deck assignments and health states
- [ ] Ship interior model exists with rooms and connections
- [ ] crew_factor integrates into ShipSystem.efficiency
- [ ] All existing v0.01 tests pass (crew_factor = 1.0 by default)
- [ ] Combat damage causes crew casualties
- [ ] Medical station displays crew status by deck
- [ ] Medical can treat injured/critical crew
- [ ] Crew casualties reduce system efficiency (testable: damage crew on engineering deck → engine efficiency drops)

---

## 5. v0.02b — PUZZLE ENGINE FRAMEWORK

**Purpose**: Build the puzzle infrastructure with ONE trivial proof-of-concept puzzle. No gameplay-specific puzzles yet.

### 5.1 Server-Side Puzzle Engine

```
server/puzzles/
├── __init__.py
├── engine.py               # PuzzleEngine: create, tick, validate, assist, timeout
├── base.py                 # PuzzleInstance base class
└── sequence_match.py       # Proof-of-concept: match a colour sequence (trivial)
```

**PuzzleEngine interface**:
```python
class PuzzleEngine:
    active_puzzles: dict[str, PuzzleInstance]  # puzzle_id → instance
    
    def create_puzzle(self, puzzle_type, station, difficulty, **params) -> PuzzleInstance
    def tick(self) -> None                    # Tick all active puzzles (timers, degradation)
    def submit(self, puzzle_id, submission) -> PuzzleResult
    def apply_assist(self, puzzle_id, assist_type, data) -> AssistResult
    def cancel(self, puzzle_id) -> None
    def pop_pending_broadcasts(self) -> list[tuple[str, dict]]  # [(role, message), ...]
    def get_active_for_station(self, station: str) -> PuzzleInstance | None
```

**Integration with game loop**:
```python
# In the tick sequence (game_loop.py):
puzzle_engine.tick()
for role, message in puzzle_engine.pop_pending_broadcasts():
    manager.broadcast_to_role(role, message)
```

**Integration with mission engine**:
New trigger types: `puzzle_completed`, `puzzle_failed`, `puzzle_score_above`.
Mission events can fire: `start_puzzle` (type, station, difficulty, params).

### 5.2 Client-Side Puzzle Infrastructure

```
client/shared/
├── puzzle_renderer.js      # Shared puzzle chrome: timer bar, assist indicator,
│                            # submit button, puzzle container management
└── puzzle_types/
    └── sequence_match.js   # Proof-of-concept: click coloured buttons in order
```

**Puzzle renderer**: Manages the puzzle overlay lifecycle on any station. When `puzzle.started` arrives, it creates a canvas overlay, loads the appropriate puzzle type module, and wires up the timer and submit button. When `puzzle.result` arrives, it shows success/failure and removes the overlay.

**Puzzle type interface** (every puzzle type exports):
```javascript
export function init(canvas, puzzleData) { }     // Set up the puzzle
export function applyAssist(assistData) { }       // Simplify with external help
export function getSubmission() { }               // Return player's solution
export function destroy() { }                     // Clean up
```

### 5.3 Proof-of-Concept Puzzle: Sequence Match

A trivial puzzle for testing the framework lifecycle:
- Server generates a random colour sequence (e.g., [red, blue, green, red])
- Client shows coloured buttons, player clicks them in order
- Submit → server validates → result broadcast
- Timer counts down, timeout → failure
- An "assist" reveals the first N elements of the sequence

This puzzle has zero gameplay value but exercises: generation, client rendering, timed interaction, submission, validation, assist application, success/failure, and mission trigger integration.

### Acceptance Criteria

- [ ] Puzzle engine creates, ticks, validates, and times out puzzles
- [ ] Proof-of-concept puzzle works end-to-end (start → interact → submit → result)
- [ ] Assist flow works (apply assist → puzzle becomes easier)
- [ ] Mission trigger fires on puzzle completion
- [ ] Client puzzle overlay appears and disappears correctly
- [ ] Multiple puzzles can be active simultaneously (different stations)
- [ ] All v0.01 and v0.02a tests still pass

---

## 6. v0.02b2 — GAMEPLAY PUZZLES + FIRST ASSIST CHAIN

**Purpose**: Build the first two real puzzles (Engineering circuit routing, Science frequency matching) and validate the cross-station assist flow end-to-end.

### 6.1 Circuit Routing (Engineering)

**Visual**: Grid of nodes and connections. Power flows from reactor to target system. Some paths are damaged.

**Mechanic**: Drag to create/reroute connections. Flow must meet target requirement. Limited spare conduits.

**Difficulty**: Grid size (3×3 to 6×6), damaged nodes, spare conduits.

**Assists**:
- Science: Highlight salvageable nodes (reduces dead-end attempts)

### 6.2 Frequency Matching (Science)

**Visual**: Target waveform + adjustable composite signal from frequency sliders.

**Mechanic**: Adjust amplitude/wavelength/phase sliders to match target waveform.

**Difficulty**: Number of component frequencies (2-5), noise level, tolerance.

**Assists**:
- Engineering: Boost sensor power → wider matching tolerance

### 6.3 First Assist Chain

Validate the full cross-station assist flow:
1. Mission trigger fires a frequency matching puzzle on Science
2. Engineering receives a notification: "Sensor calibration data available — relay to Science?"
3. Engineering performs an action (boost sensor power to 120%+)
4. Server detects the power level and sends an assist to Science's active puzzle
5. Science's puzzle becomes easier (tolerance widens)
6. Science solves, mission trigger fires

This is a simpler assist than the draft's "Comms provides cipher key" because it uses an existing mechanic (power levels) rather than requiring a new station. The Comms cipher assist comes in v0.02d.

### Acceptance Criteria

- [ ] Circuit routing puzzle works: generate, render, interact (drag connections), validate, time out
- [ ] Frequency matching puzzle works: generate, render, interact (sliders), validate, time out
- [ ] Cross-station assist works end-to-end (Engineering boosts power → Science puzzle gets easier)
- [ ] Both puzzles are triggered by mission events
- [ ] Puzzle difficulty scaling works (missions can specify difficulty 1-5)
- [ ] A test mission uses both puzzles (can be a simple "engineering drill" mission)

---

## 7. v0.02c — SECURITY STATION + SHIP INTERIOR RENDERING

**Purpose**: Build the Security station with ship interior map, marine deployment, boarding defence, and tactical positioning puzzle.

### 7.1 Security Design (Real-Time with Action Points)

**Marines**: 3-4 squads. Each has: position (room ID), health, action_points (0-10), equipment.

**Action costs**: Move to adjacent room = 3 actions. Seal/unseal door = 2 actions. Hold position (defensive bonus) = 0 actions.

**Action regeneration**: 1 action per 5 ticks (0.5 seconds). Full pool regenerates in 25 seconds.

**Intruders**: Move continuously (1 room per ~30 ticks). Pathfind toward objectives. Auto-combat when in the same room as marines (resolved per tick based on numbers and positioning).

**Fog of war**: Intruders are only visible in rooms with marines OR rooms with functioning internal sensors (Science dependency). Without sensors, Security is blind.

### 7.2 Ship Interior Canvas Rendering

The Security station's primary display: top-down deck map showing rooms as labelled rectangles, corridors as connecting lines, doors as toggleable segments. Room colours indicate state (normal/damaged/decompressed/hostile). Marine tokens as friendly-coloured circles, intruder tokens as hostile-coloured circles (when visible).

This is expected to be the most complex canvas rendering in the project. Plan for it to take 2-3 sessions.

### 7.3 Tactical Positioning Puzzle

Fires during boarding events. Security must position marines optimally to intercept intruders approaching critical systems. The puzzle is essentially "the boarding is happening AND it's scored" — faster interception with fewer casualties = higher score.

### Acceptance Criteria

- [ ] Security station renders ship interior map
- [ ] Marines can be deployed to rooms (click room → move squad)
- [ ] Action points limit movement speed
- [ ] Boarding event spawns intruders at airlocks
- [ ] Intruders pathfind toward objectives
- [ ] Auto-combat resolves when marines and intruders share a room
- [ ] Door control works (seal/unseal affects pathfinding)
- [ ] Fog of war: intruders invisible without sensors or marine line-of-sight
- [ ] Tactical positioning puzzle triggers during boarding events
- [ ] Science internal sensors affect intruder visibility

---

## 8. v0.02d — COMMUNICATIONS STATION

**Purpose**: Build the Comms station with frequency scanning, hailing, transmission decoding, and the Comms→Science assist chain.

### 8.1 Core Mechanics

- **Frequency scanner**: Visual sweep showing signal blips. Different factions on different bands.
- **Hailing**: Select contact, choose preset message (negotiate, demand, bluff). Outcomes affect mission flow.
- **Interception**: Passively receive encrypted enemy transmissions. Decoding reveals intel.
- **Distress signals**: Receive and relay coordinates to Helm.

### 8.2 Transmission Decoding Puzzle

Cryptogram-style pattern matching with visual symbols. Partial decode still provides useful (if incomplete) information.

### 8.3 Comms → Science Assist Chain

The full cipher assist flow:
1. Science gets a frequency matching puzzle
2. Comms receives an intercepted transmission (encrypted)
3. Comms decodes transmission (their own puzzle — simpler, faster)
4. Decoded transmission contains a frequency signature
5. Comms relays it (puzzle.request_assist) → Science's puzzle pre-fills one slider

### 8.4 New Mission: First Contact Protocol

Science scans unknown vessel (frequency puzzle) → Comms establishes communication (decoding puzzle) → Captain decides approach → outcomes branch based on puzzle scores and Captain's choice.

### Acceptance Criteria

- [ ] Comms station renders frequency scanner, hailing interface, transmission log
- [ ] Hailing contacts works with preset messages and NPC responses
- [ ] Transmission decoding puzzle works end-to-end
- [ ] Comms → Science assist chain works (decoded cipher → frequency puzzle assist)
- [ ] First Contact Protocol mission is playable
- [ ] Faction reputation basics functional (hailing outcomes affect reputation)

---

## 9. v0.02e — MEDICAL EXPANSION + TRIAGE PUZZLE

**Purpose**: Expand Medical beyond Tier 1. Disease mechanics, contagion, quarantine coordination with Security, triage puzzle.

### 9.1 Disease Mechanics

- Diseases spread between adjacent decks if not quarantined
- Medical must identify the pathogen (Science assist: pathogen analysis)
- Treatment sequence matters (wrong order worsens condition)
- Quarantine = Security seals deck doors (cross-station coordination)

### 9.2 Triage Puzzle

Patient cards with symptoms → diagnose → assign treatment in correct sequence → prioritise under time pressure. Contagious patients must be isolated (limited isolation beds).

### 9.3 New Mission: Plague Ship

Distress signal → board plague ship → identify pathogen → triage survivors → prevent contamination. Involves Comms (decode distress), Security (boarding party), Science (pathogen analysis), Medical (treatment), Engineering (quarantine life support).

### Acceptance Criteria

- [ ] Disease mechanics work (contagion spread, quarantine)
- [ ] Triage puzzle works end-to-end
- [ ] Science → Medical assist chain works (pathogen analysis → narrows diagnosis)
- [ ] Security quarantine coordination works (sealed doors prevent contagion)
- [ ] Plague Ship mission is playable
- [ ] Cross-station coordination required for optimal outcome

---

## 10. v0.02f — HELM EXPANSION + NEBULA CROSSING

**Purpose**: Route calculation puzzle, hazard navigation mechanics, Nebula Crossing mission.

### 10.1 Hazard Navigation

New world entities: minefields (damage hull), nebulae (block sensors), gravity wells (reduce speed), radiation zones (injure crew). Each has defined boundaries and effects applied per tick while the ship is inside.

### 10.2 Route Calculation Puzzle

Plot waypoints through a hazard-filled sector. Shorter paths are riskier. Science can scan hazards to reveal exact boundaries (assist).

### 10.3 New Mission: Nebula Crossing

Navigate through a sensor-blocking nebula with hidden hazards. Science maps the interior, Helm plots the course, Engineering manages power fluctuations, Comms tries to maintain contact with base.

---

## 11. v0.02g — WEAPONS EXPANSION + CAPTAIN EXPANSION

**Purpose**: Weapon loading management, firing solutions, Captain authorisation system and log entries.

### 11.1 Weapons Loading

Torpedo types (standard, EMP, nuclear, probe). Tubes must be loaded (takes time). Choosing the right ordnance matters.

### 11.2 Firing Solutions

Long-range torpedo shots require lead calculation. Science provides target velocity data (assist).

### 11.3 Captain Authorisation

Some actions require Captain approval: nuclear torpedo launch, self-destruct, surrender, boarding action. Appears as a confirmation prompt on the Captain's station.

### 11.4 Captain's Log

Captain can record log entries at key moments. Entries appear in post-mission debrief.

---

## 12. v0.02h — DIPLOMATIC SUMMIT + BALANCE PASS

**Purpose**: Final mission type, full cross-station balance pass, comprehensive playtesting.

### 12.1 Diplomatic Summit Mission

Host negotiations between rival factions. Comms mediates, Security monitors, Science provides evidence, Captain decides. All puzzle types potentially in play.

### 12.2 Balance Pass

- Puzzle difficulty tuning across all types
- Assist impact tuning (how much easier should an assist make things?)
- Timer tuning (how long is fair for each puzzle type at each difficulty?)
- Crew damage rate tuning
- Mission pacing review (are there enough quiet moments between crises?)

### 12.3 Final v0.02 Gate

- All 8 roles functional (Captain, Helm, Weapons, Engineering, Science, Comms, Medical, Security)
- All puzzle types working with cross-station assists
- All new missions playable start to finish
- All v0.01 missions still working unchanged
- Full game flow with 6-8 simultaneous players tested
- Tablet-responsive across all stations

---

## 13. ESTIMATED SCOPE

| Sub-Release | Estimated Sessions | Primary Model | Notes |
|-------------|-------------------|---------------|-------|
| v0.01.1 Tech Debt | 2-3 | Primary | Pure refactor, must not break anything |
| v0.02a Crew + Interior | 4-5 | Primary (model), Secondary (Medical UI) | Foundation for everything |
| v0.02b Puzzle Framework | 3-4 | Primary | Framework must be right |
| v0.02b2 Gameplay Puzzles | 5-6 | Primary (puzzles), Secondary (mission data) | Client puzzles are complex |
| v0.02c Security | 6-8 | Primary | Most complex new station |
| v0.02d Comms | 4-5 | Primary (mechanics), Secondary (UI) | |
| v0.02e Medical Expansion | 4-5 | Primary (disease), Secondary (puzzle UI) | |
| v0.02f Helm + Nebula | 3-4 | Primary | |
| v0.02g Weapons + Captain | 3-4 | Mixed | Less novel, more expansion |
| v0.02h Diplomatic + Balance | 4-5 | Primary | Playtesting-heavy |

**Total: ~40-50 sessions.** Roughly 2-3× the effort of v0.01, which tracks given the scope expansion.

---

*Document version: v0.02-scope-final-1.0*
*Last updated: 2026-02-19*
*Status: FINALISED — Implementation begins with v0.01.1 tech debt cleanup*
