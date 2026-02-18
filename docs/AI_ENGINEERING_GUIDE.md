# STARBRIDGE — AI Engineering Management Guide
## How to Run This Project with AI Engineers

---

## 1. THE CORE CHALLENGE

AI engineers (LLMs) are brilliant coders with amnesia. Every new session starts from zero. The quality of your output is directly proportional to the quality of context you feed in. This guide establishes the systems that make AI engineering reliable, consistent, and efficient across sessions, models, and phases.

### The Three Enemies
1. **Context loss** — AI doesn't remember what it built yesterday
2. **Style drift** — different sessions produce inconsistent code, naming, and UI
3. **Scope creep** — AI tends to over-build when not constrained, or under-build when not guided

### The Three Weapons
1. **Living documentation** — files the AI reads at the start of every session
2. **Strict phase discipline** — one phase at a time, fully tested before moving on
3. **Checkpoint verification** — you (the human) verify each phase before the next begins

---

## 2. PROJECT FILE STRUCTURE FOR AI MANAGEMENT

Beyond the game's own code structure, maintain these project management files at the repository root:

```
starbridge/
├── .ai/                          # AI engineering context (the AI reads this)
│   ├── SYSTEM_PROMPT.md          # Base system prompt for all sessions
│   ├── CONVENTIONS.md            # Code style, naming, patterns (LIVING DOC)
│   ├── STATE.md                  # Current project state (LIVING DOC — updated after every session)
│   ├── DECISIONS.md              # Architecture decisions log (append-only)
│   ├── PHASE_CURRENT.md          # The current phase brief (replaced each phase)
│   └── LESSONS.md                # What went wrong and how to avoid it (append-only)
│
├── docs/
│   ├── SCOPE.md                  # The v0.01 scope document (your main reference)
│   ├── MESSAGE_PROTOCOL.md       # WebSocket message reference (LIVING DOC)
│   ├── MISSION_FORMAT.md         # Mission JSON schema
│   └── STYLE_GUIDE.md            # Wire aesthetic reference
│
├── tests/                        # Test files (AI should write these)
│   ├── test_physics.py
│   ├── test_combat.py
│   └── ...
│
└── (game code as per scope document)
```

### What "LIVING DOC" Means

These files get updated during or after each session. They are the project's memory. When something changes — a convention is established, a decision is made, a bug is discovered — it goes into the appropriate file. This is non-negotiable. Without this, session 12 will contradict session 3 and you'll spend hours debugging inconsistencies.

---

## 3. THE CONTEXT DOCUMENTS

### 3.1 SYSTEM_PROMPT.md

This is the base prompt you paste (or attach) at the start of every AI session. It establishes identity, constraints, and working style. Keep it under 2000 words — dense, not verbose.

```markdown
# Starbridge — AI Engineer System Prompt

You are an AI engineer building Starbridge, a cooperative multiplayer bridge crew 
simulator. You are working under the direction of Peter, the project owner, who is 
an experienced Python developer and software engineering educator.

## Project Summary
Web-based multiplayer game where players take roles on a starship bridge (Captain, 
Helm, Weapons, Engineering, Science). Built with FastAPI + WebSockets (server) and 
vanilla HTML/Canvas/JS (clients). Wire-frame aesthetic. LAN play.

## Your Working Rules
1. **Read .ai/STATE.md and .ai/CONVENTIONS.md before writing any code.** These are 
   your ground truth for what exists and how it's built.
2. **Only work on the current phase.** Check .ai/PHASE_CURRENT.md. Do not build 
   ahead. Do not refactor previous phases unless explicitly asked.
3. **Follow established conventions exactly.** If CONVENTIONS.md says snake_case for 
   Python and camelCase for JS, you do that. No exceptions. No "improvements."
4. **Server is authoritative.** Clients send intentions, server validates and 
   broadcasts state. Never let clients modify game state directly.
5. **Every WebSocket message uses the envelope format.** Type, payload, tick, 
   timestamp. Add new message types to MESSAGE_PROTOCOL.md.
6. **Write tests for server logic.** Physics, combat, damage — anything with maths 
   or state transitions gets a test.
7. **Use the wire aesthetic.** Refer to docs/STYLE_GUIDE.md. Dark backgrounds, 
   monospace fonts, vector/wireframe rendering, glow effects. No fills, no gradients, 
   no rounded-friendly UI.
8. **When you finish a task, update .ai/STATE.md** with what you built, what works, 
   and any known issues.
9. **When you make an architectural decision, log it in .ai/DECISIONS.md** with the 
   decision, reasoning, alternatives considered, and date.
10. **If something is unclear, ask.** Do not assume. Peter will clarify.

## Technical Stack
- Python 3.12+, FastAPI, uvicorn, Pydantic v2, asyncio
- Vanilla JavaScript (ES modules), HTML5 Canvas, CSS custom properties
- No frontend framework. No build step. No npm.
- pytest for server tests

## Code Style Summary
(See .ai/CONVENTIONS.md for full details)
- Python: snake_case, type hints everywhere, dataclasses/Pydantic models
- JavaScript: camelCase, JSDoc comments, ES module imports
- CSS: BEM-style class names, CSS custom properties for theming
- Files: max ~300 lines before splitting. Clear module boundaries.
```

### 3.2 CONVENTIONS.md

This starts sparse and grows with the project. Seed it with basics, then add conventions as they emerge. The AI should update this file when establishing new patterns.

```markdown
# Code Conventions

## Python (Server)

### Naming
- Files: snake_case.py
- Classes: PascalCase
- Functions/methods: snake_case
- Constants: UPPER_SNAKE_CASE
- Private methods: _leading_underscore

### Type Hints
- All function signatures must have type hints
- Use `from __future__ import annotations` in every file
- Pydantic models for all WebSocket messages
- Dataclasses for game state objects

### Imports
- Standard library first, then third-party, then local
- Absolute imports only (from server.models.ship import Ship)

### Game Loop
- All game logic runs in the tick() function chain
- No game state modification outside the game loop
- Client messages are queued and processed at the start of each tick

### Error Handling
- WebSocket message validation via Pydantic (invalid messages are logged and dropped)
- No bare except clauses
- Game loop must never crash — catch and log errors per-entity

## JavaScript (Client)

### Naming
- Files: snake_case.js (matching the station name)
- Functions: camelCase
- Classes: PascalCase
- Constants: UPPER_SNAKE_CASE
- DOM elements: camelCase with type suffix (e.g., radarCanvas, throttleSlider)

### Modules
- ES module imports (import { x } from './module.js')
- Each station is a self-contained module with an init() entry point
- Shared code in client/shared/

### Canvas Rendering
- requestAnimationFrame for render loop
- Interpolate between server ticks for smooth movement
- All coordinates transformed: world space → screen space via camera
- Wireframe only — strokeStyle, never fillStyle (except for glow effects)

### WebSocket
- Single connection per client via shared/connection.js
- Messages are JSON with the standard envelope
- Connection manager handles reconnection with exponential backoff

## CSS

### Naming
- BEM-style: .station-panel, .station-panel__header, .station-panel--alert
- All theme colours via CSS custom properties (var(--primary), etc.)
- No inline styles in HTML

### Structure
- shared/theme.css loaded by all stations (colours, fonts, base elements)
- Station-specific CSS in station folder
- Mobile/responsive breakpoints at 768px and 1024px

## General

### Commit Messages
- Phase X: Brief description of what was added
- Fix: Description of bug and fix
- Refactor: What was changed and why

### File Size
- Target max 300 lines per file
- Split when a file exceeds this or has multiple distinct responsibilities
```

### 3.3 STATE.md

This is the most critical file. Updated after every session. It tells the next session exactly what exists.

```markdown
# Project State

**Last updated**: [date]
**Current phase**: 1 (Foundation)
**Overall status**: [Not started / In progress / Phase X complete]

## What Exists
- (nothing yet — update as things are built)

## What Works
- (verified working features)

## Known Issues
- (bugs, incomplete features, tech debt)

## File Manifest
- (list of key files and what they contain — helps the AI navigate)

## Next Steps
- (what needs to happen next within the current phase)
```

### 3.4 DECISIONS.md

Append-only log. This prevents the AI from re-litigating decided architecture.

```markdown
# Architecture Decisions

## [Date] — Message protocol format
**Decision**: JSON envelope with type, payload, tick, timestamp
**Reasoning**: Simple to debug, extensible, fast enough for LAN
**Alternatives**: Protocol buffers (overkill), raw strings (fragile)

## [Date] — No frontend framework
**Decision**: Vanilla JS with ES modules
**Reasoning**: No build step, each station is isolated, reduces complexity
**Alternatives**: React (build step, overkill), Alpine.js (may add later if needed)

(append new decisions as they're made)
```

### 3.5 LESSONS.md

Append-only. When something goes wrong, document it so it doesn't happen again.

```markdown
# Lessons Learned

(append issues as they arise)

## Template
**Date**: 
**Issue**: What went wrong
**Cause**: Why it happened  
**Fix**: How it was resolved
**Prevention**: How to avoid this in future sessions
```

---

## 4. SESSION WORKFLOW

### Starting a Session

Every AI engineering session follows this protocol:

```
1. PROVIDE CONTEXT
   ├── Paste or attach: SYSTEM_PROMPT.md
   ├── Paste or attach: CONVENTIONS.md  
   ├── Paste or attach: STATE.md
   ├── Paste or attach: PHASE_CURRENT.md
   └── If needed: relevant source files the AI will modify

2. STATE THE TASK
   ├── Be specific: "Implement the WebSocket hub from Phase 1"
   ├── Not vague: "Work on networking"
   └── Include acceptance criteria: "I should be able to open 3 tabs and see all 3 in the lobby"

3. AI WORKS
   ├── AI reads context, asks clarifying questions if needed
   ├── AI implements, following conventions
   └── AI writes/updates tests

4. VERIFY
   ├── You test the output (run server, open browsers, try to break it)
   ├── Check code against conventions
   └── Flag issues for the AI to fix

5. UPDATE LIVING DOCS
   ├── AI updates STATE.md with what was built
   ├── AI updates CONVENTIONS.md if new patterns were established
   ├── AI logs any decisions in DECISIONS.md
   └── You verify the updates are accurate

6. CLOSE SESSION
   └── STATE.md now reflects reality for the next session
```

### Task Sizing

Each session task should be completable in one sitting. Good sizing:

| Too Small | Right Size | Too Big |
|-----------|-----------|---------|
| "Add a CSS variable" | "Build the lobby UI with role selection" | "Build the entire Weapons station" |
| "Fix a typo" | "Implement the physics system with tests" | "Do all of Phase 4" |
| "Rename a function" | "Create the Engineering power sliders and integrate with ship systems" | "Make it all work" |

A good rule: **one task = one meaningful feature a player would notice**, or one complete system module with tests.

### Breaking a Phase into Session Tasks

Using Phase 4 (Weapons + Combat) as an example:

```
Session 4a: Enemy entity model + AI state machine
  → Enemies exist in the world, move around, transition between states
  → Test: spawn enemy, verify it chases player when in range

Session 4b: Combat system (beam + torpedo mechanics)  
  → Damage calculations, projectile physics, shield absorption
  → Test: unit tests for damage pipeline

Session 4c: Weapons client UI
  → Tactical radar, target selection, fire controls
  → Test: open Weapons station, see enemies on radar, fire at them

Session 4d: Integration + combat polish
  → Damage flows to Engineering, destruction handling, visual feedback
  → Test: full combat loop — find enemy, fight, take damage, repair, destroy
```

---

## 5. PROMPT STRATEGIES

### 5.1 The Context Sandwich

For every task prompt, use this structure:

```
[CONTEXT — what exists, what to read]
[TASK — what to build, specific and bounded]  
[CONSTRAINTS — what NOT to do, conventions to follow]
[ACCEPTANCE CRITERIA — how to verify it works]
```

Example:

```
CONTEXT: Read .ai/STATE.md for current project state and .ai/CONVENTIONS.md 
for code standards. The server skeleton from Phase 1 is complete — FastAPI app 
with WebSocket hub, lobby system, and message protocol. See server/main.py and 
server/lobby.py.

TASK: Implement the game loop and ship physics (Phase 2, tasks 1-4 from the 
scope document). This means:
- An asyncio game loop running at 10 ticks/sec (fixed timestep)
- A Ship dataclass (position, heading, velocity, throttle, systems dict)
- A physics system that updates ship position based on throttle and heading
- A World class holding the sector bounds and entity list
- State broadcast: each tick, send ship state to all connected clients

CONSTRAINTS:
- The game loop runs as a background asyncio task started on app startup
- Client messages (helm.set_heading, helm.set_throttle) are queued and 
  processed at the start of each tick, not applied immediately
- Ship max speed = base_speed * (engine_power / 100)
- Ship turn rate = base_turn_rate * (manoeuvring_power / 100) degrees per tick
- Default power levels: all systems at 50%
- Do not build the Helm client yet — that's the next task
- Follow all conventions in CONVENTIONS.md
- Write pytest tests for the physics calculations

ACCEPTANCE: 
- Server starts and game loop ticks are logged
- Sending helm.set_throttle via WebSocket makes the ship position change
- Sending helm.set_heading makes the ship heading change
- Physics tests pass: verify speed limiting, turn rate, position updates
- STATE.md is updated with what was built
```

### 5.2 Reference, Don't Repeat

When the AI has access to files (Claude Code, file attachments), reference them rather than re-explaining:

**Bad**: "The message format should be JSON with a type field that contains the category dot action, a payload field with the data, a tick field with the current tick number, and a timestamp..."

**Good**: "Follow the message protocol defined in docs/MESSAGE_PROTOCOL.md. Add any new message types to that file."

### 5.3 Constraining Scope

AI engineers love to over-build. Be explicit about boundaries:

**Bad**: "Build the weapons system"

**Good**: "Build beam weapons only. Torpedoes are the next task. Do not implement torpedoes, mines, or any other weapon type. Do not build the Weapons client UI — that's a separate task. Focus on the server-side beam firing logic: arc checking, damage calculation, and the fire/cooldown cycle."

### 5.4 Handling Multi-Model Work

If cost dictates using different models (e.g., Claude for architecture and complex systems, a cheaper model for repetitive UI work):

**High-capability model (Claude Opus/Sonnet) — use for**:
- Architecture and system design
- Game loop, physics, combat, AI systems
- Complex client logic (interpolation, canvas rendering)
- Debugging difficult issues
- Reviewing and refactoring code from other sessions

**Lower-cost model — use for**:
- Repetitive UI implementation (once patterns are established by the primary model)
- Writing tests from existing code
- Documentation updates
- CSS styling and layout work
- Simple CRUD-style endpoints
- Mission data file authoring (JSON)

**Critical rule**: The primary model should establish all patterns first. The secondary model follows established patterns. Never let a secondary model establish new architectural patterns — they'll drift from the design.

### 5.5 The Review Prompt

After a phase is "done", use the primary model to review:

```
CONTEXT: [attach all files from the completed phase]

TASK: Review the Phase [X] implementation for:
1. Convention compliance (check against CONVENTIONS.md)
2. Architectural consistency (check against DECISIONS.md)
3. Missing error handling
4. Untested logic
5. Potential bugs in multiplayer scenarios (race conditions, state desync)
6. Code that would make future phases harder to implement

Do NOT refactor or rewrite. List issues with file, line, and recommended fix. 
Categorise as: CRITICAL (must fix now), SHOULD FIX (fix before next phase), 
MINOR (note for later).
```

---

## 6. AGENT TOOL STRATEGIES

### 6.1 Claude Code (CLI Agent)

If using Claude Code, it can directly read/write files, run the server, and test in real-time. This is the most efficient mode for implementation tasks.

**Best practices for Claude Code sessions**:
- Start by asking it to read `.ai/STATE.md` and `.ai/CONVENTIONS.md`
- Give it the specific task with acceptance criteria
- Let it run the server and test with curl/websocket clients
- Have it update STATE.md before ending the session
- It can run pytest directly to verify tests pass

### 6.2 Chat Interface (claude.ai / API)

For sessions in the chat interface (where the AI can't directly access your filesystem):

**Workflow**:
1. Attach the context files as uploads
2. Describe the task
3. AI produces code blocks you copy into your project
4. You run and test locally
5. Report results back to the AI for iteration
6. Copy final STATE.md update from the AI into your file

**Tip**: For large file outputs, ask the AI to produce complete files rather than diffs. It's easier to replace a whole file than to manually apply 15 patches.

### 6.3 Computer Use / File Creation

In sessions where Claude has computer access (like this one), it can create complete file sets. Use this for:
- Scaffolding an entire phase's file structure
- Generating boilerplate (HTML pages, CSS, test files)
- Creating mission data files
- Producing documentation

### 6.4 Combining Approaches

A typical phase might use multiple approaches:

```
1. Chat session (Claude Opus): Discuss approach, resolve design questions, 
   produce the PHASE_CURRENT.md brief

2. Claude Code session: Implement the server-side systems, write tests, 
   verify they pass

3. Chat session (Claude Sonnet or cheaper): Generate client HTML/CSS 
   boilerplate following established patterns

4. Claude Code session: Implement client JavaScript, integrate with server, 
   end-to-end testing

5. Chat session (Claude Opus): Review phase, identify issues

6. Claude Code session: Fix issues, update living docs, close phase
```

---

## 7. QUALITY CONTROL

### 7.1 The Phase Gate Checklist

Before moving from Phase N to Phase N+1, verify ALL of:

```
□ All acceptance criteria from the phase brief are met
□ Manual testing with multiple browser tabs passes
□ Server-side tests pass (pytest)
□ Code follows CONVENTIONS.md
□ STATE.md is accurate and current
□ Any new message types are documented in MESSAGE_PROTOCOL.md
□ Any new conventions are added to CONVENTIONS.md
□ Any architecture decisions are logged in DECISIONS.md
□ No hardcoded values that should be configurable
□ No TODO/FIXME comments that represent unfinished work for this phase
□ UI matches the wire aesthetic (STYLE_GUIDE.md)
```

### 7.2 Testing Strategy

**Server-side (pytest)**:
- Physics calculations (speed, turning, position)
- Damage pipeline (weapon → shield → hull → system)
- Power system (budget limits, efficiency scaling)
- AI state transitions
- Mission trigger evaluation
- Message validation

**Manual testing protocol** (do this yourself after each phase):
1. Open the server in terminal — check for clean startup, no errors
2. Open browser tab 1 — connect to lobby, claim a role
3. Open browser tab 2 — connect to lobby, claim a different role
4. Open browser tab 3 — connect to lobby, claim a third role
5. Start the game — all tabs should transition from lobby to their station
6. Perform the core loop for the current phase's new features
7. Try to break it: disconnect a client mid-game, send nonsense via browser console, open a tab on your phone
8. Check server logs for errors

### 7.3 The "Explain It" Test

If you're unsure whether the AI's code is correct or well-structured, ask it to explain:

```
Explain the damage pipeline in server/systems/combat.py step by step. 
What happens when a beam hits a target? Walk through the exact function 
calls and state changes. I want to verify the logic is correct.
```

This catches cases where the AI wrote plausible-looking code that doesn't actually work correctly.

---

## 8. TROUBLESHOOTING COMMON AI ENGINEERING ISSUES

### "The AI rewrote working code from a previous phase"

**Prevention**: In the task prompt, explicitly state: "Do not modify [files]. Only work in [files]."
**In STATE.md**: Mark stable files: "server/lobby.py — STABLE, do not modify without explicit instruction"

### "The code style changed between sessions"

**Prevention**: CONVENTIONS.md must be provided every session. After the first few sessions, it should be comprehensive enough to prevent drift.
**Fix**: Use a review prompt to identify inconsistencies, then a targeted fix session.

### "The AI added features I didn't ask for"

**Prevention**: Explicit scope constraints in every prompt. "Do NOT implement [X, Y, Z]. Only implement [A]."
**Fix**: Revert the additions. Update LESSONS.md. Strengthen the constraints in future prompts.

### "The AI's code doesn't integrate with existing code"

**Prevention**: Always attach or reference the files the new code must integrate with. Don't assume the AI remembers the interfaces.
**Fix**: Provide both files and ask the AI to fix the integration points specifically.

### "Client behaviour is inconsistent across stations"

**Prevention**: Shared code in client/shared/ must be established by the primary model first. Other stations copy the patterns.
**Fix**: Review prompt comparing two stations, asking the AI to identify and resolve inconsistencies.

### "The game loop has subtle timing bugs"

**Prevention**: This is the hardest category. Insist on tests for physics and timing. Use deterministic tick numbers, not wall-clock time, for all game logic.
**Fix**: Ask the AI to write a test that reproduces the bug, then fix it. Log in LESSONS.md.

---

## 9. COST MANAGEMENT

### Token Estimation per Phase

| Phase | Estimated Sessions | Primary Model | Secondary Model |
|-------|--------------------|---------------|-----------------|
| 1: Foundation | 3-4 | 2-3 (architecture, WebSocket) | 1 (lobby UI HTML/CSS) |
| 2: Game Loop + Helm | 3-4 | 3-4 (all — game loop is critical) | 0 |
| 3: Engineering | 3-4 | 2 (power system, integration) | 1-2 (UI layout) |
| 4: Weapons + Combat | 4-5 | 3-4 (AI, combat, radar rendering) | 1 (UI elements) |
| 5: Science | 3-4 | 2-3 (sensor system, scanning) | 1 (UI) |
| 6: Captain + Missions | 4-5 | 3-4 (mission engine, triggers) | 1 (dashboard layout) |
| 7: Polish | 4-6 | 3-4 (visual effects, missions) | 1-2 (CSS, responsive) |

**Total estimate**: 24-32 sessions, roughly 18-24 with primary model.

### Cost-Saving Tactics

1. **Batch related tasks**: Instead of 3 sessions for 3 small fixes, batch them into one session with clear numbered tasks.

2. **Provide complete context, not conversational history**: Starting a fresh session with the right files attached is cheaper than a long back-and-forth conversation where you're re-explaining things.

3. **Use the cheapest model that can handle the task**: CSS layout work doesn't need Opus. Physics engine debugging does.

4. **Front-load architecture with the best model**: Getting the patterns right early saves enormous rework costs later. Spending more on Phases 1-2 saves money on Phases 3-7.

5. **Write acceptance criteria that prevent iteration loops**: Vague tasks cause 3-4 rounds of "not quite, try again." Specific tasks with testable criteria often work first time.

---

## 10. QUICK REFERENCE — SESSION START TEMPLATE

Copy and customise this for each session:

```
## Context

Read these files for project context:
- .ai/SYSTEM_PROMPT.md (your working rules)
- .ai/STATE.md (what currently exists)
- .ai/CONVENTIONS.md (code standards)
- .ai/PHASE_CURRENT.md (current phase brief)

[Attach any source files the AI needs to read or modify]

## Task

[Specific description of what to build]

## Constraints

- Only modify: [list of files]
- Do not implement: [out-of-scope features]
- Follow the conventions in CONVENTIONS.md
- [Any phase-specific constraints]

## Acceptance Criteria

- [ ] [Testable criterion 1]
- [ ] [Testable criterion 2]
- [ ] [Testable criterion 3]

## After Completion

- Update .ai/STATE.md with what was built
- Update .ai/CONVENTIONS.md if new patterns were established
- Log any architectural decisions in .ai/DECISIONS.md
- List any known issues or tech debt
```

---

*Document version: 1.0*
*Last updated: 2026-02-18*
