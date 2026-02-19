# STARBRIDGE — v0.02 Phase Prompts
## Starting from v0.01.1 Tech Debt Cleanup

---

## v0.01.1 — TECH DEBT CLEANUP

### Session 0.1a: Split game_loop.py + Extract Mission-Specific Code

```
Read these files in order:

1. .ai/SYSTEM_PROMPT.md
2. .ai/STATE.md
3. .ai/CONVENTIONS.md
4. docs/SCOPE_v002.md — Section 3 (v0.01.1 Tech Debt Cleanup)

Then read the file you'll be splitting:
- server/game_loop.py (all of it — understand the full tick sequence)
- server/missions/engine.py (the mission engine interface)

TASK: Split game_loop.py into 4 files:

1. server/game_loop.py — Orchestrator only. Contains _loop(), the tick 
   sequence (calling into the other modules), _drain_queue() as a dispatch 
   table (not inline logic), state broadcast assembly, and the 
   start()/stop() lifecycle. Target: under 350 lines.

2. server/game_loop_weapons.py — Beam fire helpers, torpedo fire helpers, 
   torpedo movement/impact, weapon-related queue processing. Everything 
   that currently handles weapons.fire_beams, weapons.fire_torpedo, and 
   torpedo tick updates.

3. server/game_loop_physics.py — Physics tick (entity movement, boundary 
   clamping), heading interpolation, speed calculations. The pure 
   simulation step.

4. server/game_loop_mission.py — Mission engine integration, 
   _handle_signal_scans(), the resupply docking timer, and any other 
   mission-specific logic currently embedded in the main loop. The key 
   goal: after this split, the orchestrator in game_loop.py has ZERO 
   mission-specific code.

CONSTRAINTS:
- This is a pure refactor. Behaviour must be IDENTICAL.
- All 331+ existing tests must pass without modification.
- The split modules should import from each other minimally — prefer 
  passing state as parameters over module-level shared state.
- Functions that move to new files keep their exact signatures.
- Update all imports in main.py and test files if needed.
- Do NOT add new features, fix bugs, or refactor logic. Move code only.

ACCEPTANCE CRITERIA:
- [ ] game_loop.py is under 350 lines
- [ ] No mission-specific code in game_loop.py
- [ ] _drain_queue dispatches to handler functions, not inline logic
- [ ] All existing tests pass (run pytest, zero failures)
- [ ] All three missions still work (start each, verify gameplay)
- [ ] The tick sequence is the same (same order of operations)

AFTER COMPLETION:
- Update .ai/STATE.md with the new file structure
- Update .ai/CONVENTIONS.md with the game_loop splitting convention
- Log the split decision in .ai/DECISIONS.md
```

---

### Session 0.1b: Split messages.py + Clean Up mission.py

```
Read .ai/STATE.md to confirm game_loop split is complete.

Then read:
- server/models/messages.py (the file to split)
- server/models/mission.py (the placeholder to replace)

TASK 1: Split messages.py into namespace files:

server/models/messages/
├── __init__.py          # Re-exports everything — ALL existing imports must 
│                         # continue working unchanged
├── base.py              # Message envelope, create_message(), validate_payload() 
│                         # dispatch, MessageType constants
├── lobby.py             # LobbyClaimRolePayload, LobbyReleaseRolePayload, etc.
├── helm.py              # HelmSetHeadingPayload, HelmSetThrottlePayload
├── weapons.py           # WeaponsSelectTargetPayload, WeaponsFireBeamsPayload, etc.
├── engineering.py       # EngineeringSetPowerPayload, EngineeringSetRepairPayload
├── science.py           # ScienceStartScanPayload, etc.
├── captain.py           # CaptainSetAlertPayload
├── game.py              # Game lifecycle payloads
└── world.py             # World entity payloads

TASK 2: Replace server/models/mission.py placeholder with useful models:

Move or create mission-related data models here:
- MissionDefinition (what load_mission returns)
- ObjectiveDefinition
- TriggerDefinition  
- EventDefinition

These should match the actual structures used in server/missions/engine.py 
and server/missions/loader.py. Extract them from wherever they currently 
live (probably inline dicts or ad-hoc structures).

CONSTRAINTS:
- All existing imports must continue working. The __init__.py re-export 
  is critical.
- All existing tests must pass without modification.
- Each namespace file should be under 150 lines.
- validate_payload() in base.py dispatches to the correct namespace module.
- No behaviour changes. This is a structural refactor only.

ACCEPTANCE CRITERIA:
- [ ] All existing tests pass
- [ ] No single messages file exceeds 150 lines
- [ ] `from server.models.messages import Message` still works
- [ ] `from server.models.messages import validate_payload` still works
- [ ] All payload classes importable from their namespace file
- [ ] server/models/mission.py contains real, used data models
- [ ] Server starts and all missions work

AFTER COMPLETION:
- Update .ai/STATE.md — mark v0.01.1 COMPLETE, update file manifest
- Update .ai/PHASE_CURRENT.md — replace with v0.02a brief
- Log decisions in .ai/DECISIONS.md
- Note: the messages __init__.py re-export pattern in CONVENTIONS.md
```

---

## v0.02a — CREW SYSTEM + SHIP INTERIOR + MEDICAL TIER 1

### Session 2a.1: Crew and Interior Data Models (Server Only)

```
Read these files in order:

1. .ai/SYSTEM_PROMPT.md
2. .ai/STATE.md (should show v0.01.1 complete)
3. .ai/CONVENTIONS.md
4. docs/SCOPE_v002.md — Sections 4.1, 4.2, 4.3 (Crew, Interior, Medical)

Then read the code you'll integrate with:
- server/models/ship.py (Ship and ShipSystem — you'll add crew_factor)
- server/game_loop.py (where crew updates will hook in)
- server/systems/combat.py (where crew damage will be added)

TASK: Build the crew and ship interior data models. No UI, no Medical 
station — server-side models, integration with existing systems, and tests.

1. Crew model (server/models/crew.py):
   - DeckCrew dataclass: deck_name, total, active, injured, critical, dead
   - crew_factor property: (active + injured * 0.5) / total
   - CrewRoster class: dict of deck_name → DeckCrew
   - Helper methods: apply_casualties(deck, count), treat_injured(deck, count), 
     treat_critical(deck, count), get_deck_for_system(system_name)
   - DECK_SYSTEM_MAP as a module-level constant
   - Default crew numbers per deck (e.g., bridge: 20, engineering: 40, etc.)

2. Ship interior model (server/models/interior.py):
   - Room dataclass: id, name, deck, position, connections, state, door_sealed
   - ShipInterior class: rooms dict, helper methods for pathfinding, 
     adjacent rooms, room state changes
   - Static ship layout data (the 5-deck, 20-room layout from the scope doc)
   - Pathfinding: simple BFS through unlocked, non-hazardous rooms

3. Integration with ShipSystem.efficiency:
   - Add _crew_factor: float = 1.0 field to ShipSystem
   - Modify efficiency property to include crew_factor
   - Add a method on Ship to update crew_factors from the CrewRoster
   - Call this update once per tick in the game loop

4. Combat crew damage:
   - In the existing damage pipeline (apply_hit_to_player or equivalent), 
     add a crew casualty roll: when hull takes damage, X% chance of crew 
     casualties on a random deck
   - Casualties are proportional to damage (1 casualty per 5 hull damage, 
     for example — make it a tunable constant)

5. Add crew state to ship.state broadcast:
   - Include crew summary per deck in the ship.state message
   - Captain and Medical will consume this

CONSTRAINTS:
- crew_factor defaults to 1.0 for all decks at game start (full crew)
- All existing tests must pass WITHOUT modification (this is the critical 
  constraint — crew_factor = 1.0 means efficiency is unchanged)
- Write comprehensive tests for crew model, interior pathfinding, and the 
  crew damage integration
- Do NOT build the Medical station UI yet — that's the next session

ACCEPTANCE CRITERIA:
- [ ] DeckCrew model with crew_factor calculation
- [ ] ShipInterior model with rooms and BFS pathfinding
- [ ] ShipSystem.efficiency includes crew_factor
- [ ] All existing tests pass (crew_factor = 1.0 = no change)
- [ ] Combat crew damage works (debug endpoint to verify)
- [ ] ship.state includes crew data
- [ ] Damaging crew on engineering deck reduces engine efficiency (test this)
- [ ] New tests cover crew model, pathfinding, crew damage pipeline

AFTER COMPLETION:
- Update .ai/STATE.md
- Log the crew_factor integration decision in DECISIONS.md
- Note the DECK_SYSTEM_MAP in CONVENTIONS.md (it's a key reference)
```

---

### Session 2a.2: Medical Station Tier 1

```
Read .ai/STATE.md to confirm crew/interior models are built.

Then read:
- server/models/crew.py (the crew model you'll interact with)
- docs/SCOPE_v002.md — Section 4.3 (Medical Station Tier 1)
- docs/STYLE_GUIDE.md (wire aesthetic for the UI)
- client/engineering/engineering.js (pattern reference — most similar station)

TASK: Build Medical station Tier 1 — crew overview and basic treatment.

SERVER:
- server/medical.py — Message handler (same pattern as engineering.py)
  - medical.treat_crew: { deck: str, target: "injured"|"critical" }
  - medical.set_triage_priority: { deck: str } (sets which deck gets 
    automatic healing each tick)
- Treatment mechanic: treating injured = 1 crew healed per 2 ticks. 
  Treating critical = 1 crew stabilised (critical → injured) per 5 ticks.
  One treatment active at a time per deck (like Engineering repair focus).
- Add message types to the messages module
- Wire into main.py handler routing

CLIENT:
- client/medical/index.html, medical.js, medical.css
- Deck-by-deck crew overview: each deck as a panel showing 
  active/injured/critical/dead counts with colour-coded bars
- Treatment interface: click a deck, choose "Treat Injured" or 
  "Stabilise Critical", see progress
- Crew factor display per deck (shows the efficiency impact)
- Overall ship crew readiness percentage
- Wire aesthetic consistent with other stations

LOBBY:
- Add "medical" to the valid roles list
- Create the Medical role card in the lobby UI

CONSTRAINTS:
- No disease mechanics, no triage puzzle, no supplies — those are v0.02e
- Medical Tier 1 is simple: see crew status, assign treatment, watch 
  them heal
- Follow existing station patterns exactly (connection.js, theme.css, 
  role reclaim on reconnect)

ACCEPTANCE CRITERIA:
- [ ] Medical appears as a claimable role in the lobby
- [ ] Medical station shows crew status by deck
- [ ] Treating injured crew heals them over time
- [ ] Stabilising critical crew moves them to injured
- [ ] Crew casualties from combat appear on Medical's display
- [ ] Crew factor visible per deck
- [ ] Two-tab test: damage ship via combat → Medical sees casualties → 
      treats them → Engineering sees efficiency recover
- [ ] Wire aesthetic consistent with other stations

AFTER COMPLETION:
- Update .ai/STATE.md — mark v0.02a COMPLETE
- Update .ai/PHASE_CURRENT.md — replace with v0.02b brief
- Update .ai/CONVENTIONS.md with Medical-specific patterns if any
```

---

## NOTES FOR FUTURE PROMPTS

From v0.02b onward, the prompting pattern is established. For each 
sub-release:

1. Start with context loading (STATE.md, CONVENTIONS.md, PHASE_CURRENT.md, 
   relevant scope section)
2. Break into sub-tasks (typically: server model → server logic → client UI → 
   integration test → phase gate)
3. Key priorities and constraints specific to that phase
4. Acceptance criteria that are testable
5. State file updates after completion

The puzzle engine phases (v0.02b, v0.02b2) should follow the same pattern 
but with extra emphasis on:
- The proof-of-concept validating the framework BEFORE building real puzzles
- Testing the full lifecycle (create → tick → assist → submit → result → 
  mission trigger)
- Client interaction patterns being established on the simplest puzzle first

The Security station (v0.02c) should be treated like Phase 4 was in v0.01 — 
the biggest and hardest phase, broken into 3-4 sessions minimum, with the 
interior canvas rendering getting its own dedicated session.

---

*Ready to go. Start with v0.01.1 Session 0.1a (game_loop split).*
