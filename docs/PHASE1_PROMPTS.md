# STARBRIDGE — Phase 1 Session Prompts
## Foundation: Server + Connection + Lobby

---

## Overview

Phase 1 is broken into 4 sessions:

| Session | Focus | Model Recommendation |
|---------|-------|---------------------|
| **0** | Bootstrap — scaffold project, create .ai/ files | Primary (sets all patterns) |
| **1a** | Server skeleton + WebSocket hub + message protocol | Primary (critical architecture) |
| **1b** | Lobby system (server + client) | Primary (establishes client patterns) |
| **1c** | Polish, error handling, reconnection, phase gate | Primary or secondary (following patterns) |

Each prompt below is self-contained — copy it, attach the listed files, and go.

---

## SESSION 0: Bootstrap — Project Scaffold

### Purpose
Create the project skeleton, all .ai/ management files, and the empty folder structure. No game logic — just the scaffolding that every future session depends on.

### Prompt

```
## Context

I'm building Starbridge, a cooperative multiplayer bridge crew simulator (think 
Artemis Spaceship Bridge Simulator, but web-based). I have two reference documents:

1. SCOPE.md — the full v0.01 scoping document (attached)
2. AI_ENGINEERING_GUIDE.md — how this project is managed across AI sessions (attached)

Read both documents fully before proceeding.

## Task

Bootstrap the project by creating:

1. The complete folder structure as defined in Section 5 of the scope document. 
   Create all directories. For code files, create empty placeholder files with a 
   module docstring explaining what will go in them (e.g., `"""Game loop — fixed 
   timestep simulation. Implemented in Phase 2."""`).

2. The .ai/ management directory with these seeded files:
   - SYSTEM_PROMPT.md — based on Section 3.1 of the engineering guide
   - CONVENTIONS.md — based on Section 3.2 of the engineering guide
   - STATE.md — initialised as "Phase 1 not started", empty sections
   - DECISIONS.md — seed with the architectural decisions already made in the 
     scope document (message protocol format, no frontend framework, 
     server-authoritative, fixed timestep, component-based ship systems, 
     missions-as-data). Format each with Decision, Reasoning, Alternatives, Date.
   - LESSONS.md — empty template
   - PHASE_CURRENT.md — the Phase 1 brief extracted from the scope document, 
     including all Phase 1 tasks from the TODO checklist

3. docs/ reference files:
   - MESSAGE_PROTOCOL.md — seed with the full message protocol from Section 7 
     of the scope document, clearly organised into Client→Server and 
     Server→Client sections with payload schemas
   - MISSION_FORMAT.md — placeholder noting this will be defined in Phase 6
   - STYLE_GUIDE.md — the wire aesthetic guide from Section 8 of the scope 
     document, including the CSS custom properties, typography rules, canvas 
     rendering conventions, and colour palette

4. requirements.txt with: fastapi, uvicorn[standard], pydantic, websockets, pytest, 
   pytest-asyncio

5. run.py entry point (a simple uvicorn launcher):
   - Binds to 0.0.0.0:8000
   - Enables reload for development
   - Prints the local IP address and URL for LAN connections on startup

6. README.md with:
   - Project name and one-line description
   - Quick start instructions (venv, pip install, python run.py)
   - How to connect (open browser to server IP)
   - Project status (Phase 1 in progress)

## Constraints

- Do NOT implement any game logic, WebSocket handling, or UI. Only scaffolding.
- Placeholder files should have docstrings explaining their future purpose, nothing 
  more.
- run.py should be functional — it should actually start uvicorn pointing at 
  server/main.py (which can be a minimal FastAPI app returning "Starbridge server 
  running" at GET /).
- Follow all conventions from the engineering guide for file naming and structure.
- The .ai/ files are the most important output of this session. Get them right.

## Acceptance Criteria

- [ ] `python run.py` starts a server on port 8000 with no errors
- [ ] Visiting http://localhost:8000 returns a response
- [ ] All directories from the scope document exist
- [ ] All .ai/ files exist and contain meaningful, accurate content
- [ ] docs/MESSAGE_PROTOCOL.md contains the complete protocol from the scope doc
- [ ] docs/STYLE_GUIDE.md contains the complete aesthetic guide
- [ ] .ai/DECISIONS.md contains at least 6 pre-made architectural decisions
- [ ] .ai/STATE.md reflects the current state after this session

## After Completion

- Update .ai/STATE.md: mark scaffold as complete, list all created files, note 
  that Phase 1a (server skeleton + WebSocket hub) is next.
```

**Files to attach**: SCOPE.md (the v0.01 scope document), AI_ENGINEERING_GUIDE.md

---

## SESSION 1a: Server Skeleton + WebSocket Hub + Message Protocol

### Purpose
Build the core server infrastructure: the FastAPI app, WebSocket connection management, role-tagged connections, the message protocol with Pydantic validation, and role-filtered broadcasting. This is the nervous system everything else plugs into.

### Prompt

```
## Context

Read these project files for full context:
- .ai/SYSTEM_PROMPT.md (your working rules)
- .ai/STATE.md (current project state — scaffold complete)
- .ai/CONVENTIONS.md (code standards to follow)
- .ai/PHASE_CURRENT.md (Phase 1 brief and tasks)
- docs/MESSAGE_PROTOCOL.md (the message protocol to implement)

The project scaffold is in place. All directories exist. run.py starts a minimal 
FastAPI server. Your job is to build the real server skeleton.

## Task

### 1. Message Protocol (server/models/messages.py)

Implement the WebSocket message protocol using Pydantic v2 models:

- A base `Message` model with the envelope fields: type (str), payload (dict), 
  tick (int, optional — only server→client), timestamp (float)
- A `MessageType` enum or constants for all message types from MESSAGE_PROTOCOL.md
- Specific payload models for at least the lobby messages:
  - `LobbyClaimRole`: role (str), player_name (str)
  - `LobbyReleaseRole`: (empty or minimal)
  - `LobbyStartGame`: mission_id (str)
  - `LobbyState`: roles dict (role → player_name or null), host (str)
- A `create_message(type, payload)` helper that builds a properly formatted 
  message dict with timestamp
- Validation: unknown message types are caught, malformed payloads are caught

### 2. Connection Manager (server/main.py or a new server/connections.py)

A WebSocket connection manager that:
- Tracks active connections with metadata: connection ID, player name, role, 
  session ID, connected_at timestamp
- Supports `connect(websocket, player_name)` — registers a new connection
- Supports `disconnect(connection_id)` — cleans up
- Supports `assign_role(connection_id, role)` — tags a connection with a role
- Supports `broadcast_to_role(role, message)` — sends to all connections with 
  that role
- Supports `broadcast_to_all(message)` — sends to every connection
- Supports `broadcast_to_game(message, exclude_roles=None)` — sends to all 
  in-game connections, optionally excluding certain roles
- Supports `send_to(connection_id, message)` — sends to a specific connection
- Handles WebSocket errors gracefully (connection drops mid-send, etc.)

### 3. WebSocket Endpoint (server/main.py)

A WebSocket endpoint at `/ws` that:
- Accepts a connection and registers it with the connection manager
- Receives JSON messages, validates them against the Pydantic models
- Routes messages by type prefix:
  - `lobby.*` messages → lobby handler
  - `helm.*`, `weapons.*`, etc. → queued for game loop processing (stubbed for now)
- Sends validation errors back to the client for malformed messages
- Cleans up on disconnect

### 4. Static File Serving

Configure FastAPI to serve the `client/` directory as static files, so browsers 
can load HTML/CSS/JS directly from the game server.

## Constraints

- Do NOT implement the lobby logic yet (that's session 1b). Just route lobby 
  messages to a stub handler that logs them.
- Do NOT implement the game loop. Helm/weapons/etc. messages should be logged 
  with a "queued for game loop (not yet implemented)" note.
- The connection manager should be a singleton — one instance managing all 
  connections.
- All message serialisation goes through Pydantic. No raw dict construction 
  for outbound messages.
- Use Python's logging module, not print statements.
- Write tests for: message validation (valid and invalid messages), connection 
  manager (add, remove, role assignment, filtered broadcast).

## Acceptance Criteria

- [ ] Server starts cleanly with `python run.py`
- [ ] A WebSocket client can connect to ws://localhost:8000/ws
- [ ] Sending a valid JSON message gets acknowledged (no error)
- [ ] Sending an invalid JSON message returns a validation error to the client
- [ ] Sending a lobby.claim_role message gets logged as "routed to lobby handler"
- [ ] Multiple WebSocket connections can be open simultaneously
- [ ] Disconnecting a client cleans up the connection manager (no stale entries)
- [ ] pytest tests pass for message validation and connection manager
- [ ] Static files are served (create a test HTML file at client/test.html that 
      loads at http://localhost:8000/client/test.html)

## After Completion

- Update .ai/STATE.md with:
  - Files created/modified and their purpose
  - What works (WebSocket connections, message routing, static serving)
  - Known issues or stubs
  - Next step: Session 1b (lobby system)
- Update .ai/CONVENTIONS.md if any new patterns were established (e.g., how 
  the connection manager is accessed, how message routing works)
- Log any decisions made in .ai/DECISIONS.md
```

**Files to attach**: All .ai/ files, docs/MESSAGE_PROTOCOL.md, and the existing server/main.py placeholder.

---

## SESSION 1b: Lobby System (Server + Client)

### Purpose
Build the lobby — the first thing players see. Server-side session and role management, plus the client UI. This session establishes ALL client-side patterns (WebSocket connection, CSS theming, HTML structure) that every future station will follow.

### Prompt

```
## Context

Read these project files:
- .ai/SYSTEM_PROMPT.md (your working rules)
- .ai/STATE.md (current state — WebSocket hub and message protocol are built)
- .ai/CONVENTIONS.md (code standards)
- .ai/PHASE_CURRENT.md (Phase 1 brief)
- docs/STYLE_GUIDE.md (wire aesthetic — follow this precisely for the UI)
- server/main.py (WebSocket endpoint and routing)
- server/models/messages.py (message protocol)
- server/connections.py (connection manager — or wherever it was placed)

The WebSocket hub, message protocol, and connection manager are working. Lobby 
messages are routed to a stub handler. Your job is to implement the lobby system 
(server logic + browser client).

## Task

### 1. Lobby Server Logic (server/lobby.py)

Implement the lobby/session manager:

- **Game session model**: A dataclass or Pydantic model holding:
  - session_id (generated UUID)
  - host_connection_id (the player who created it)
  - roles: dict mapping role names to player info or None
    - Available roles: captain, helm, weapons, engineering, science
  - status: "lobby" | "in_game" | "completed"
  - settings: dict (future-proofing — empty for now)

- **Lobby message handlers**:
  - `lobby.claim_role` — Assigns the requesting player to a role if it's 
    available. Broadcasts updated lobby state to all connections.
  - `lobby.release_role` — Releases the player's current role. Broadcasts 
    updated state.
  - `lobby.start_game` — Only works if sender is the host. Only works if at 
    least one role is claimed (for testing — eventually require minimum roles). 
    Changes session status to "in_game". Broadcasts game.started to all.
  - On player disconnect — automatically releases their role. Broadcasts 
    updated state. If the host disconnects, assign host to the next connected player.

- **Auto-session**: For v0.01 simplicity, a single game session is created 
  automatically when the server starts. No need for session creation/browsing UI.

- **REST endpoints** (optional but useful):
  - `GET /api/lobby` — returns current lobby state as JSON (useful for debugging 
    and initial page load before WebSocket connects)

### 2. Shared Client Infrastructure

These establish patterns every station will reuse:

**client/shared/connection.js** — WebSocket connection manager:
- Connects to `ws://${window.location.host}/ws`
- Accepts a player name (prompted or from URL param)
- Sends messages via `send(type, payload)` helper
- Receives messages and dispatches to registered handlers via 
  `on(messageType, callback)`
- Reconnection: on disconnect, attempt reconnect with exponential backoff 
  (1s, 2s, 4s, 8s, max 30s). Show connection status in UI.
- Connection state: expose `isConnected` property

**client/shared/theme.css** — Base stylesheet:
- Implement the FULL colour palette and typography from docs/STYLE_GUIDE.md
- CSS custom properties for all colours, including alert-level switching
- Base element styles (body, headings, buttons, inputs, panels)
- The scanline overlay effect (CSS pseudo-element on body)
- Utility classes: .text-bright, .text-dim, .text-hostile, .text-friendly
- Panel component: .panel with border glow, dark background, header bar
- Responsive base: max-width containers, flex layouts

**client/shared/ui_components.js** — Reusable UI helpers:
- `createPanel(title)` — returns a styled panel DOM element
- `formatNumber(n, decimals)` — consistent number formatting
- `showConnectionStatus(element, isConnected)` — updates a status indicator
- Any other small helpers that feel natural

### 3. Lobby Client (client/lobby/)

**client/lobby/index.html**:
- Clean HTML5 page loading theme.css, lobby.css, connection.js, lobby.js
- Structure: header (game title + version), main content area, footer 
  (connection status)

**client/lobby/lobby.js**:
- On load: prompt for player name (simple text input, or use URL param ?name=X)
- Connect via shared/connection.js
- Display the 5 roles as cards/panels, each showing:
  - Role name and icon (ASCII/unicode art or simple symbol is fine)
  - One-line role description
  - Status: "Available" or "Claimed by [name]"
  - Claim/Release button (context-dependent — shows Claim if available and 
    you haven't claimed one, Release if you've claimed this one, greyed out 
    if someone else has it)
- A player can only hold one role at a time
- "Launch Mission" button — only visible/enabled for the host, only clickable 
  when at least 1 role is claimed
- Connected players list somewhere on screen
- All state updates come via WebSocket — lobby listens for lobby.state messages 
  and re-renders

**client/lobby/lobby.css**:
- Wire aesthetic per STYLE_GUIDE.md
- Role cards in a responsive grid (works on tablet and desktop)
- Glow effects on interactive elements
- Alert-level colour theming (green by default in lobby)
- The lobby should look like a starship computer terminal, not a web app

### 4. Navigation After Game Start

When `game.started` is received by the lobby client:
- Redirect the browser to the appropriate station page based on claimed role
  (e.g., `/client/helm/index.html`)
- For v0.01, the station pages can be placeholder HTML files that just say 
  "Welcome to [Station Name] — implementation coming in Phase [X]"
- Create these placeholder station pages for all 5 roles plus the viewscreen

## Constraints

- The lobby client must work with NO JavaScript framework — vanilla JS only, 
  ES modules.
- Do NOT implement any game logic, game loop, or station functionality.
- The lobby.start_game handler should broadcast the game.started message but 
  does NOT need to actually initialise the game world (that's Phase 2).
- All WebSocket messages must use the established envelope format.
- The lobby UI is the first thing players see — it sets the tone. Make it look 
  like a proper starship interface, not a prototype. Invest in the CSS.
- Create placeholder station HTML pages that maintain the aesthetic (dark 
  background, styled header, "Station coming online..." type message).

## Acceptance Criteria

- [ ] Opening http://localhost:8000/client/lobby/ shows the lobby interface
- [ ] Entering a name connects via WebSocket (connection status shows green)
- [ ] All 5 roles are displayed with descriptions
- [ ] Clicking "Claim" on an available role claims it (button changes to Release)
- [ ] A second browser tab sees the role as claimed by the first player's name
- [ ] Claiming a role when you already have one releases the old one first
- [ ] The host sees a "Launch Mission" button; non-hosts do not (or it's disabled)
- [ ] Clicking "Launch Mission" sends game.started to all clients
- [ ] On game.started, each client redirects to their station's placeholder page
- [ ] Disconnecting a tab releases their role (other tabs see the update)
- [ ] The lobby looks like a starship terminal — wire aesthetic, dark theme, glow
- [ ] Mobile/tablet: layout doesn't break (roles stack vertically if needed)
- [ ] GET /api/lobby returns the current lobby state as JSON

## After Completion

- Update .ai/STATE.md with:
  - All new files and their purposes
  - The shared client infrastructure patterns (how connection.js works, how 
    theme.css is structured, how stations will load shared resources)
  - What works, known issues
  - Next step: Session 1c (polish + error handling)
- Update .ai/CONVENTIONS.md with:
  - Client-side patterns established (module structure, DOM manipulation approach, 
    event handling, CSS class naming)
  - How station pages should load shared resources
  - WebSocket message handling pattern on the client
- Log any decisions in .ai/DECISIONS.md
```

**Files to attach**: All .ai/ files, docs/STYLE_GUIDE.md, docs/MESSAGE_PROTOCOL.md, and all server/ files from session 1a.

---

## SESSION 1c: Error Handling, Reconnection, Polish, Phase Gate

### Purpose
Harden Phase 1. Handle edge cases, test error paths, polish the lobby experience, and pass the phase gate checklist. This is the "make it solid" session before moving to Phase 2.

### Prompt

```
## Context

Read these project files:
- .ai/SYSTEM_PROMPT.md (your working rules)  
- .ai/STATE.md (current state — lobby system is built and working)
- .ai/CONVENTIONS.md (code standards and client patterns)
- .ai/PHASE_CURRENT.md (Phase 1 brief)

The lobby system is functional: players can connect, claim roles, and the host can 
launch a game. This session is about hardening, edge cases, and polish.

Also read the Phase Gate Checklist (Section 7.1 of the AI Engineering Guide) — 
every item must pass by the end of this session.

## Task

### 1. Error Handling & Edge Cases (Server)

Review and harden:
- What happens if two players try to claim the same role simultaneously? Ensure 
  only one succeeds (the connection manager or lobby handler needs a lock or 
  atomic check-and-set).
- What happens if a client sends a lobby.start_game but isn't the host? Return 
  an error message to that client.
- What happens if a client sends lobby.claim_role with an invalid role name? 
  Return a clear error.
- What happens if a client sends a message before identifying themselves (no 
  player name)? Handle gracefully.
- What happens if the server receives a non-JSON WebSocket message? Handle 
  without crashing.
- What happens if the server receives valid JSON that doesn't match the message 
  schema? Return a validation error.
- Add proper logging throughout: connection events, role changes, errors. Use 
  structured log messages that include connection_id and player_name.

### 2. Client Reconnection Polish (client/shared/connection.js)

Ensure the reconnection logic is robust:
- On disconnect, show a visual indicator (e.g., a banner: "Connection lost — 
  reconnecting...")
- Exponential backoff: 1s, 2s, 4s, 8s, cap at 30s
- On successful reconnect, re-send the player's name and attempt to reclaim 
  their previous role automatically
- If their role was taken during disconnect, show a message and return them 
  to role selection
- The connection status indicator should have 3 states: connected (green dot), 
  reconnecting (amber pulsing), disconnected (red)

### 3. Lobby UI Polish

Review the lobby interface against STYLE_GUIDE.md and improve:
- Ensure the scanline overlay effect is working and subtle (not distracting)
- Add a subtle animation when roles are claimed/released (brief glow flash)
- The "Launch Mission" button should have a distinct visual treatment (brighter, 
  possibly pulsing border when active)
- Add a header area with the game title rendered in the wire aesthetic (large 
  monospace text with letter-spacing, subtle glow)
- Add a "How to Connect" info panel showing the server URL that other players 
  should visit (helpful for LAN setup)
- Connection count indicator: "3 crew members connected"
- Test on a tablet-sized viewport (768px-1024px) and fix any layout issues

### 4. Tests

Write or expand tests:
- Test: simultaneous role claiming (verify only one succeeds)
- Test: invalid message handling (bad JSON, bad type, bad payload)
- Test: host disconnection and host transfer
- Test: reconnection and role reclaiming
- Test: all lobby message types produce correct state changes
- Organise tests clearly in tests/ directory

### 5. Phase Gate Review

Go through EVERY item in the Phase 1 TODO checklist (from the scope document, 
Section 9) and verify it's complete:

```
Phase 1: Foundation
- [ ] FastAPI app skeleton with static file serving
- [ ] WebSocket endpoint with connection management
- [ ] Connection tagging (role, player name, session ID)
- [ ] Message protocol: envelope format, serialisation, type routing
- [ ] Lobby system: create session, list sessions, claim/release role
- [ ] Lobby client: UI with role selection, player list, launch button
- [ ] Role-filtered broadcasting (send to specific roles only)
- [ ] Basic error handling (malformed messages, invalid roles)
```

For any items that are incomplete or have issues, fix them.

## Constraints

- Do NOT add new features beyond Phase 1 scope. This is hardening, not expanding.
- Do NOT start on the game loop, ship model, or any Phase 2 work.
- If you find architectural issues that would be painful to fix later, document 
  them in .ai/DECISIONS.md with a recommendation, but do not fix them unless 
  they affect Phase 1 functionality.
- Keep the lobby UI improvements consistent with existing CSS patterns.

## Acceptance Criteria

- [ ] All Phase 1 TODO items verified complete
- [ ] Error handling: invalid messages return errors, don't crash the server
- [ ] Race condition: rapid double-click on claim doesn't cause inconsistency
- [ ] Host disconnect: host transfers to next player, lobby continues working
- [ ] Client reconnection: disconnect banner appears, reconnects automatically, 
      reclaims role if available
- [ ] Connection status indicator works (green/amber/red states)
- [ ] Lobby looks polished — title, scanlines, glow effects, animations
- [ ] "How to Connect" panel shows the correct URL for LAN players
- [ ] All tests pass
- [ ] Layout works on tablet (768px viewport)
- [ ] Server logs are clean and informative (no uncaught errors, no spam)

## After Completion

- Update .ai/STATE.md with FINAL Phase 1 state:
  - Mark Phase 1 as COMPLETE
  - Complete file manifest with every file and its purpose
  - Mark stable files: server/connections.py — STABLE, server/models/messages.py 
    — STABLE (these shouldn't change in Phase 2)
  - List any known issues or tech debt
  - Set next step: Phase 2 (Game Loop + Ship Model + Helm Station)
- Update .ai/PHASE_CURRENT.md — replace Phase 1 content with Phase 2 brief 
  (extract from scope document: Phase 2 description, tasks, acceptance criteria)
- Final update to CONVENTIONS.md with any new patterns
- Add any lessons learned to .ai/LESSONS.md
```

**Files to attach**: All .ai/ files, all server/ source files, all client/ source files, docs/STYLE_GUIDE.md.

---

## NOTES FOR PETER

### How to Use These Prompts

1. **Start Session 0 in a fresh conversation.** Attach the two reference docs 
   (scope + engineering guide). Let the AI scaffold everything. Verify the output.

2. **Session 1a: new conversation.** Attach the .ai/ files the AI created in 
   Session 0, plus any existing code files it needs to see. The prompt references 
   files by path — the AI will read them.

3. **Session 1b: new conversation.** Attach updated .ai/ files + all server code 
   from 1a. This is the biggest session — the lobby UI and shared client 
   infrastructure. This session establishes every client pattern, so use the 
   primary model.

4. **Session 1c: new conversation.** Attach everything. This is the polish pass. 
   Could potentially use a secondary model since patterns are established, but 
   primary is safer for the first phase gate.

### Between Sessions

After each session, before starting the next:
1. Copy the AI's code into your local project
2. Run `python run.py` and test manually
3. Run `pytest` to check tests pass
4. Read the updated .ai/STATE.md — does it accurately reflect what exists?
5. Fix any inaccuracies in STATE.md yourself (you're the ground truth)
6. If something isn't right, iterate in the same session or start a targeted fix session

### What "Attach" Means

Depending on your tool:
- **claude.ai**: Upload files directly in the chat, or paste file contents 
  into the message
- **Claude Code**: The AI reads files directly from disk — just reference paths
- **API**: Include file contents in the message or as document attachments

For claude.ai, when there are many files, it's often easier to zip the .ai/ 
directory and the relevant source folders and upload the zip, then ask the AI 
to examine the contents.

### Adapting These Prompts

These prompts are detailed because Phase 1 sets all the patterns. Future phase 
prompts can be shorter because they'll reference established conventions:

> "Follow the same patterns established in the lobby client for DOM manipulation, 
> WebSocket handling, and CSS styling."

By Phase 4 or 5, your prompts might be half this length because CONVENTIONS.md 
will carry most of the context.

### Red Flags to Watch For

- AI creates files not listed in the task → scope creep, rein it in
- AI uses a library not in requirements.txt → ask why, probably unnecessary
- AI's STATE.md update is vague ("implemented lobby") → ask for specifics
- Code style differs from Session 0's patterns → attach CONVENTIONS.md more 
  prominently
- Tests are superficial (only happy path) → explicitly request edge case tests

---

*Ready to go. Start with Session 0 and build from there.*
