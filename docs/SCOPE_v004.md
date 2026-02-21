# STARBRIDGE — v0.04 Scope
## "The Command Update"

---

## 1. OVERVIEW

### 1.1 What v0.04 Adds

v0.03 built scale — 12 roles, 7 ship classes, audio, QoL polish. v0.04 builds **command and creativity**:

- **Captain station overhaul**: 3D wireframe viewports (Elite-style), real-time damage/crew panels, system master controls, a station worthy of the command role
- **Mission graph system**: Replace the sequential objective model with a state graph supporting parallel, branching, and emergent objectives. Crew decisions shape the mission.
- **Mission editor**: Visual node-graph editor for creating missions without writing JSON. Players design, share, and playtest each other's missions.
- **Save and resume**: Pause mid-mission, serialise full game state, resume next session. Essential for 50-minute class periods.
- **Player profiles**: Persistent player stats, role history, achievements, exportable to CSV for assessment
- **Admin dashboard**: Live view of all stations, annotations, engagement monitoring
- **Compound objectives**: `all_of`, `any_of`, branching triggers, conditional objectives that appear based on game state
- **Performance hardening**: 12-client stress testing on school WiFi, bottleneck identification and fixes

### 1.2 Design Principles

All previous principles carry forward. v0.04 adds:

- **Player agency over scripted experience**: Missions present situations, not instructions. The crew decides how to respond. Different approaches lead to different outcomes. There is no single "correct" way to complete a mission.
- **Game as first-class deployment target**: Save/resume fits time periods. Profiles give assessment data. The mission editor is itself a learning activity. The admin dashboard enables supervision without interrupting play.
- **Command means command**: The Captain makes decisions that matter mechanically, not just socially. System overrides, alert levels, authorisations, and mission branch choices give the Captain real authority backed by game systems.

### 1.3 Pre-Resolved Architectural Decisions

**Module-level globals stay for v0.04.** Multi-session (concurrent games) is explicitly v0.05. All v0.04 work assumes single game per server. The save/resume system serialises module state but does not refactor it into classes.

**The mission graph replaces the sequential model entirely.** All 23 existing missions must be migrated to the graph format. Sequential missions are trivially representable as a linear graph (A→B→C). The migration is mechanical, not creative. Existing mission tests must pass after migration.

**The 3D wireframe viewports use canvas 2D projection, not WebGL.** Simple perspective projection of 3D wireframe models onto 2D canvas. No lighting, no textures, no shaders. This keeps the tech stack consistent (everything is canvas 2D) and the wire aesthetic authentic.

**The mission editor runs client-side.** It's a station-like page served by the same server. No additional backend frameworks. The editor produces mission JSON that drops into the missions folder. Server-side validation on save.

**Save files are JSON.** One file per save. Contains full game state, mission graph position, all module states. The save system calls a `serialise()` method on every game_loop module and stores the results. Resume calls `deserialise()` on each module. This is explicit and mechanical — each module is responsible for its own serialisation.

---

## 2. SUB-RELEASE PLAN

### Dependency Graph

```
v0.04a (Mission graph engine — replaces sequential model)
  ├── v0.04b (Migrate all 23 existing missions to graph format)
  ├── v0.04c (New graph-native missions: branching + emergent)
  └── v0.04d (Mission editor — visual node-graph UI)

v0.04e (Captain station overhaul — 3D viewports, damage/crew panels, 
         system controls)

v0.04f (Save and resume system)

v0.04g (Player profiles + achievements)

v0.04h (Admin dashboard + spectator mode)

v0.04i (Performance hardening + stress testing)

v0.04j (Accessibility pass)

v0.04k (Final integration + balance + v0.04 gate)
```

### Key Ordering Constraints

- v0.04a (mission graph engine) is the foundation — nothing else in the mission system works without it
- v0.04b (migration) must follow v0.04a immediately to validate the engine against real missions
- v0.04c (new missions) and v0.04d (editor) both need v0.04a+b complete
- v0.04e (Captain) is independent of the mission system work — can be built in parallel
- v0.04f (save/resume) needs all game_loop modules stable — build after v0.04a-e
- v0.04g (profiles) and v0.04h (admin dashboard) are independent of each other
- v0.04i (performance) should be near-last — test the complete system
- v0.04j (accessibility) can be done at any point but benefits from stable UI
- v0.04k (gate) is always last

---

## 3. v0.04a — MISSION GRAPH ENGINE

**Purpose**: Replace the sequential `_active_index` model with a state graph that supports parallel, branching, and emergent objectives.

### 3.1 Core Concepts

The mission is a **directed graph** of objective nodes connected by edges. Each node is an objective or objective group. Each edge has a trigger condition. The engine walks the graph each tick, checking triggers on all active edges.

**Node types**:

| Type | Behaviour |
|------|-----------|
| `objective` | A single objective with a trigger condition. Completes when trigger fires. |
| `parallel` | A group of child objectives all active simultaneously. Completes when all children complete (or when a specified count complete, for `any_of` semantics). |
| `branch` | A decision point. Multiple outgoing edges with different triggers. Whichever trigger fires first determines the path taken. Other branches are discarded. |
| `conditional` | An objective that appears/disappears based on a game state condition. Independent of the main mission track. Can interrupt or layer on top of the current objectives. |
| `checkpoint` | A node that triggers a save point (for save/resume) and optionally displays a status update to the crew. |

**Edge types**:

| Type | Behaviour |
|------|-----------|
| `sequence` | Source must complete before target activates. The default. |
| `branch_trigger` | Source is a branch node. This edge activates when its specific trigger fires before any sibling branch trigger. |
| `conditional_appear` | Target node appears (becomes active) when the condition is true. |
| `conditional_disappear` | Target node deactivates when the condition is true. |
| `on_complete` | Fires an action (spawn enemies, start puzzle, etc.) when the source completes. Same as current `on_complete` but attached to an edge. |

### 3.2 Graph Evaluation Per Tick

```python
def tick(self, game_state: dict) -> None:
    # 1. Check conditional nodes — activate/deactivate based on state
    for node in self._conditional_nodes:
        should_be_active = self._evaluate_condition(node.condition, game_state)
        if should_be_active and node not in self._active_nodes:
            self._activate_node(node)
        elif not should_be_active and node in self._active_nodes:
            self._deactivate_node(node)
    
    # 2. Check triggers on all active objectives
    completed_nodes = []
    for node in self._active_nodes:
        if node.type == 'objective' and self._check_trigger(node.trigger, game_state):
            completed_nodes.append(node)
        elif node.type == 'parallel':
            # Check each child; if completion threshold met, complete the group
            ...
        elif node.type == 'branch':
            # Check each outgoing edge trigger; first to fire wins
            ...
    
    # 3. Process completions — follow edges, activate next nodes
    for node in completed_nodes:
        self._complete_node(node)
        for edge in self._outgoing_edges(node):
            if edge.type == 'sequence':
                self._activate_node(edge.target)
            if edge.on_complete:
                self._queue_action(edge.on_complete)
    
    # 4. Check victory/defeat conditions
    if self._all_required_nodes_complete():
        self._queue_action({'action': 'victory'})
    if self._check_defeat_condition(game_state):
        self._queue_action({'action': 'defeat'})
```

### 3.3 Mission JSON Format (Graph)

```json
{
    "id": "salvage_run",
    "name": "Salvage Run",
    "briefing": "Investigate a derelict vessel in the Kepler debris field.",
    "ship_classes": ["frigate", "cruiser", "battleship"],
    "min_difficulty": "officer",
    
    "nodes": [
        {
            "id": "navigate_to_site",
            "type": "objective",
            "text": "Navigate to the salvage site",
            "trigger": { "type": "proximity", "target": "salvage_site", "range": 5000 }
        },
        {
            "id": "survey",
            "type": "parallel",
            "text": "Survey the wreckage",
            "complete_when": "all",
            "children": [
                {
                    "id": "scan_wreckage",
                    "type": "objective",
                    "text": "Science: Scan the derelict",
                    "trigger": { "type": "scan_completed", "target": "derelict_1" }
                },
                {
                    "id": "check_hostiles",
                    "type": "objective",
                    "text": "Security: Sweep for threats",
                    "trigger": { "type": "security_sweep", "area": "salvage_zone" }
                },
                {
                    "id": "check_signals",
                    "type": "objective",
                    "text": "Comms: Monitor for distress signals",
                    "trigger": { "type": "comms_monitor", "duration_seconds": 30 }
                }
            ]
        },
        {
            "id": "response_branch",
            "type": "branch",
            "text": "How do you respond?"
        },
        {
            "id": "combat_chain",
            "type": "objective",
            "text": "Engage hostile contacts",
            "trigger": { "type": "all_enemies_destroyed" }
        },
        {
            "id": "rescue_chain",
            "type": "parallel",
            "text": "Rescue survivors",
            "complete_when": "all",
            "children": [
                {
                    "id": "dock_with_derelict",
                    "text": "Helm: Dock with the derelict",
                    "trigger": { "type": "proximity", "target": "derelict_1", "range": 500 }
                },
                {
                    "id": "treat_survivors",
                    "text": "Medical: Treat survivors",
                    "trigger": { "type": "puzzle_completed", "label": "triage_survivors" }
                }
            ]
        },
        {
            "id": "escape_chain",
            "type": "objective",
            "text": "Navigate through the debris field to safety",
            "trigger": { "type": "proximity", "target": "safe_zone", "range": 5000 }
        },
        {
            "id": "return_to_base",
            "type": "objective",
            "text": "Return to base",
            "trigger": { "type": "proximity", "target": "home_base", "range": 5000 }
        },
        {
            "id": "hull_emergency",
            "type": "conditional",
            "text": "EMERGENCY: Hull critical — effect immediate repairs",
            "condition": { "type": "ship_hull_below", "value": 30 },
            "deactivate_when": { "type": "ship_hull_above", "value": 50 },
            "on_activate": { "action": "start_puzzle", "puzzle_type": "circuit_routing", "station": "engineering", "label": "emergency_repair" }
        },
        {
            "id": "boarding_emergency",
            "type": "conditional",
            "text": "ALERT: Boarders detected — repel intruders",
            "condition": { "type": "intruders_aboard" },
            "deactivate_when": { "type": "no_intruders" }
        }
    ],
    
    "edges": [
        { "from": "navigate_to_site", "to": "survey", "type": "sequence" },
        { "from": "survey", "to": "response_branch", "type": "sequence" },
        
        { "from": "response_branch", "to": "combat_chain", "type": "branch_trigger",
          "trigger": { "type": "enemies_detected_in_zone", "zone": "salvage_zone" },
          "on_complete": { "action": "spawn_wave", "wave_id": "ambush_fleet" } },
          
        { "from": "response_branch", "to": "rescue_chain", "type": "branch_trigger",
          "trigger": { "type": "distress_signal_decoded" },
          "on_complete": { "action": "spawn_entity", "entity": "survivor_pod" } },
          
        { "from": "response_branch", "to": "escape_chain", "type": "branch_trigger",
          "trigger": { "type": "timer_elapsed", "seconds": 60 },
          "on_complete": { "action": "spawn_wave", "wave_id": "delayed_ambush" } },
        
        { "from": "combat_chain", "to": "return_to_base", "type": "sequence" },
        { "from": "rescue_chain", "to": "return_to_base", "type": "sequence" },
        { "from": "escape_chain", "to": "return_to_base", "type": "sequence" }
    ],
    
    "start_node": "navigate_to_site",
    "victory_nodes": ["return_to_base"],
    "defeat_condition": { "type": "ship_hull_zero" },
    
    "entities": [ ... ],
    "spawns": { ... }
}
```

### 3.4 Key Design Details

**Branch resolution**: When a branch node activates, ALL outgoing edge triggers are evaluated each tick. The FIRST trigger to fire wins. The winning edge's target activates. All other branch edges are discarded. If none fire within an optional timeout, a default branch activates. This means the crew's actions determine the path — if Science scans first, the scan-triggered branch fires. If Weapons fires first, the combat branch fires.

**Parallel completion modes**: A parallel node supports `complete_when`:
- `"all"` — every child must complete (default)
- `"any"` — first child to complete completes the group (others are cancelled)
- `{ "count": N }` — N of the children must complete
- `{ "count": N, "within_seconds": T }` — N children within T seconds (timed challenge)

**Conditional nodes are independent tracks**: They don't block or interfere with the main mission graph. They appear when conditions are met, layer on top of whatever the crew is currently doing, and disappear when resolved or when the condition clears. They have their own optional on_activate/on_deactivate actions. Multiple conditionals can be active simultaneously.

**Backward compatibility**: A sequential mission (A→B→C→D) is represented as:
```json
{
    "nodes": [
        { "id": "A", "type": "objective", ... },
        { "id": "B", "type": "objective", ... },
        { "id": "C", "type": "objective", ... },
        { "id": "D", "type": "objective", ... }
    ],
    "edges": [
        { "from": "A", "to": "B", "type": "sequence" },
        { "from": "B", "to": "C", "type": "sequence" },
        { "from": "C", "to": "D", "type": "sequence" }
    ],
    "start_node": "A",
    "victory_nodes": ["D"]
}
```

This is a trivial automatic migration from the old format. No mission logic changes. A migration script converts all 23 missions.

### 3.5 Trigger Types (Expanded)

All existing trigger types carry forward, plus:

| Trigger | Params | Fires When |
|---------|--------|-----------|
| `enemies_detected_in_zone` | zone_id | Any enemy enters the defined zone |
| `distress_signal_decoded` | — | Comms successfully decodes a distress signal |
| `scan_mode_active` | mode | Science is actively scanning in the specified mode |
| `crew_casualties_above` | count | Total crew casualties exceed threshold |
| `system_offline` | system_name | A ship system reaches 0% health |
| `boarding_active` | — | Intruders are aboard the ship |
| `no_intruders` | — | All intruders eliminated |
| `drone_deployed_to_zone` | zone_id | A Flight Ops drone is active in the zone |
| `ew_jamming_active` | target_id | EW is actively jamming the specified target |
| `all_of` | trigger_list | All listed triggers are simultaneously true |
| `any_of` | trigger_list | Any listed trigger is true |
| `none_of` | trigger_list | None of the listed triggers are true |
| `ship_hull_below` | value | Ship hull % is below the threshold |
| `ship_hull_above` | value | Ship hull % is above the threshold |
| `player_choice` | choice_id | Captain has selected a named choice from a prompt |

The compound triggers (`all_of`, `any_of`, `none_of`) can nest, enabling arbitrary boolean logic: `all_of: [scan_completed, any_of: [comms_decoded, timer_elapsed]]`.

### Acceptance Criteria

- [ ] Mission graph engine evaluates nodes and edges each tick
- [ ] Parallel nodes work (all, any, count modes)
- [ ] Branch nodes work (first trigger wins, others discarded)
- [ ] Conditional nodes activate/deactivate based on game state
- [ ] Compound triggers (all_of, any_of) work with nesting
- [ ] on_complete actions fire on edge traversal
- [ ] Victory detected when all victory_nodes are complete
- [ ] Defeat detected from defeat_condition
- [ ] Graph state is inspectable (for debugging and save/resume)
- [ ] pop_pending_actions() returns queued actions (same interface as before)
- [ ] Comprehensive tests (node types, edge types, trigger types, compound logic)

---

## 4. v0.04b — MIGRATE EXISTING MISSIONS TO GRAPH FORMAT

**Purpose**: Convert all 23 existing missions from sequential format to graph format. Validate that every mission plays identically.

### 4.1 Migration Script

Write a Python script (`tools/migrate_missions.py`) that reads old-format mission JSON and outputs graph-format JSON. For sequential missions this is mechanical:

- Each objective becomes an `objective` node
- Adjacent objectives are connected by `sequence` edges
- First objective is `start_node`
- Last objective is in `victory_nodes`
- `defeat_condition` carries over directly
- `on_complete` actions move to edge `on_complete`

### 4.2 Manual Enhancement

After automated migration, review each mission for opportunities to add parallel/branching nodes that improve gameplay without changing the mission's character:

- **Defend the Station**: The three waves could have parallel sub-objectives within each wave (engage enemies AND protect station AND manage boarding — all simultaneously, not sequentially)
- **Search and Rescue**: The triangulation scans could be parallel (scan from position A AND scan from position B, in any order)
- **Diplomatic Summit**: The negotiation rounds could branch based on crew actions

These enhancements are optional per mission. Some missions (First Contact tutorial, training missions) should stay strictly sequential because they're teaching mechanics.

### 4.3 Validation

Every migrated mission must produce identical gameplay to the original when played sequentially. The graph structure enables new paths but doesn't force them. Existing tests for mission progression must pass against the graph engine.

### Acceptance Criteria

- [ ] Migration script converts all 23 missions
- [ ] All migrated missions load and parse correctly
- [ ] All existing mission tests pass against graph engine
- [ ] At least 3 missions enhanced with parallel/branching nodes
- [ ] Training missions remain strictly sequential
- [ ] Old mission engine code removed (no dual-path maintenance)

---

## 5. v0.04c — NEW GRAPH-NATIVE MISSIONS

**Purpose**: Build 3-4 new missions that showcase the graph system's capabilities — meaningful branches, emergent objectives, and player agency.

### 5.1 Mission: "Salvage Run"

**Crew size**: 6-12 | **Ship classes**: Frigate, Cruiser, Battleship

**Summary**: Investigate a derelict vessel in a debris field. The situation is not what it seems.

**Graph structure**:
- Navigate to site (sequential)
- Survey the wreckage (parallel: Science scans, Security sweeps, Comms monitors)
- **Branch point**: What the crew discovers depends on what they prioritised during survey
  - Science found it first → it's a trap. Combat branch.
  - Comms found it first → survivors detected. Rescue branch.
  - Neither found anything in 60 seconds → ambush. Escape branch.
- Resolve the situation (varies by branch)
- Return to base

**Conditional objectives**: Hull emergency appears if hull drops below 30%. Boarding emergency if enemies board. Medical emergency if crew casualties spike.

**Why it showcases the system**: The branch point is implicit — the crew doesn't choose from a menu. Their actions determine the path. Different survey priorities lead to genuinely different missions. Conditionals layer on additional crises that depend on performance.

### 5.2 Mission: "The Convoy"

**Crew size**: 8-12 | **Ship classes**: Cruiser, Battleship

**Summary**: Escort three civilian transports through hostile territory. Protect them all — or decide which ones to sacrifice.

**Graph structure**:
- Rendezvous with convoy (sequential)
- Escort through Sector 1 (parallel: protect Transport A, protect Transport B, protect Transport C — all simultaneously)
- **If all three survive**: direct route through Sector 2, easier final encounter
- **If one is lost**: detour through nebula (Helm challenge), harder final encounter
- **If two are lost**: emergency distress call, reinforcements arrive but mission is partially failed
- Final encounter (varies by how many transports survived)
- Deliver remaining transports to destination

**Conditional objectives**: If a transport takes heavy damage, a "Repair Escort" objective appears (extend shields, DC helps). If hostiles concentrate on one transport, a "Draw Fire" objective appears (Helm interposes, Weapons draws aggro).

**Why it showcases the system**: Multiple entities to protect creates genuine prioritisation decisions. The crew must split attention. The mission adapts to their performance — losing a transport doesn't end the mission, it changes it.

### 5.3 Mission: "First Contact Remastered"

**Crew size**: 5-12 | **Ship classes**: All

**Summary**: Enhanced version of the v0.01 First Contact tutorial. Same opening, but the encounter with the alien vessel now has three possible resolutions.

**Graph structure**:
- Patrol sector (sequential)
- Detect unknown contact (sequential)
- **Branch point**: crew's first action determines the path
  - Science initiates scan → Diplomatic path (Comms establishes communication, negotiate, potential alliance or trade)
  - Weapons locks on / fires → Combat path (aliens become hostile, engagement, potential salvage)
  - Helm changes course away → Avoidance path (aliens pursue or don't, navigation challenge, mystery unresolved)
- Each path has 2-3 objectives
- Return to base (sequential)
- **Debrief varies by path**: Diplomatic gets "first contact success", Combat gets "threat neutralised", Avoidance gets "contact logged, recommend follow-up"

**Why it showcases the system**: The original tutorial becomes replayable. Players can play it three times with different approaches and get three different experiences. The branch is driven by crew action, not a menu choice.

### 5.4 Mission: "Pandemic"

**Crew size**: 8-12 | **Ship classes**: Frigate, Medical Ship, Cruiser

**Summary**: A space station reports a disease outbreak. The crew must respond — but the situation escalates unpredictably.

**Graph structure**:
- Receive distress call (sequential, Comms decodes)
- Navigate to station (sequential)
- **Parallel assessment**: Science scans station (BIO mode), Medical prepares, Security assesses boarding risk, Engineering preps quarantine systems
- Dock with station (sequential)
- **Branch**: Based on Science BIO scan results
  - Pathogen is treatable → Medical triage mission (puzzle-heavy)
  - Pathogen is weaponised → Someone did this deliberately. Investigation branch (Security searches station, Comms intercepts transmissions, Science analyses pathogen origin)
  - Pathogen is alien → Unknown biology. Science-heavy branch (frequency matching to analyse, Comms attempts to contact the alien source)
- Resolve the pathogen (varies by branch, all require Medical involvement)
- **Conditional**: If quarantine fails, contagion spreads to player ship (medical emergency + DC atmospheric venting decisions). If hostile ship detected (investigation branch), combat layer activates on top of the medical crisis.
- Depart station (sequential)

**Why it showcases the system**: Heavy Medical/Science focus (shows these roles have mission-critical depth). Conditional objectives create cascading crises. Investigation branch demonstrates non-combat, non-puzzle gameplay (detective work using the tools of multiple stations).

### Acceptance Criteria

- [ ] All 3-4 new missions playable start to finish
- [ ] Each mission has at least one meaningful branch point
- [ ] Branches are triggered by crew actions, not menu choices
- [ ] Conditional objectives appear and disappear correctly
- [ ] Each branch path leads to a valid victory condition
- [ ] Missions are replayable with different outcomes
- [ ] Mission briefings don't reveal the branch structure (preserve surprise)

---

## 6. v0.04d — MISSION EDITOR

**Purpose**: Visual node-graph editor for creating missions. Runs as a client page served by the Starbridge server.

### 6.1 Editor Architecture

```
client/editor/
├── index.html            # Editor page
├── editor.js             # Main editor logic, graph manipulation
├── editor.css            # Editor styles (wire aesthetic)
├── graph_renderer.js     # Canvas rendering of the mission graph
├── node_panel.js         # Node property editor (right panel)
├── edge_panel.js         # Edge property editor
├── trigger_builder.js    # Visual trigger condition builder
├── entity_placer.js      # Star chart for placing spawn points, waypoints
├── validator.js          # Client-side mission validation
└── exporter.js           # Export to mission JSON
```

### 6.2 Editor UI Layout

```
┌──────────────────────────────────────────┬──────────────────┐
│                                          │ PROPERTIES       │
│   GRAPH CANVAS                           │                  │
│                                          │ [Node/Edge props]│
│   Nodes as boxes, edges as arrows        │ Name: ________   │
│   Drag to move nodes                     │ Type: [dropdown] │
│   Click to select                        │ Trigger: [build] │
│   Right-click for context menu           │ Text: ________   │
│   Ctrl+click to draw new edge            │                  │
│                                          │ on_complete:     │
│                                          │ [action builder] │
│                                          │                  │
├──────────────────────────────────────────┤                  │
│   STAR CHART (toggle)                    │ VALIDATION       │
│   Place entities, waypoints, zones       │ ⚠ No start node  │
│   Define spawn positions                 │ ✓ Victory path   │
│                                          │ ✓ All edges valid│
└──────────────────────────────────────────┴──────────────────┘
│ [NEW] [SAVE] [LOAD] [VALIDATE] [EXPORT] [TEST]             │
└─────────────────────────────────────────────────────────────┘
```

### 6.3 Core Editor Features

**Node operations**: Add objective/parallel/branch/conditional/checkpoint nodes. Drag to position. Edit properties in the right panel. Delete with keyboard shortcut. Nodes colour-coded by type (objective=green, parallel=cyan, branch=amber, conditional=red, checkpoint=white).

**Edge operations**: Ctrl+click a node and drag to another to create an edge. Edge type auto-inferred (sequence by default, branch_trigger if source is a branch node). Click edge to edit trigger condition and on_complete action.

**Trigger builder**: A visual condition builder. Dropdown for trigger type, fields auto-populate based on type. Compound triggers (`all_of`, `any_of`) render as nested groups. The builder generates the trigger JSON structure.

**Action builder**: Same pattern for on_complete actions. Dropdown for action type (spawn_wave, start_puzzle, spawn_entity, etc.), fields populate per type.

**Star chart**: Toggle between graph view and star chart view. The star chart is a MapRenderer instance where you click to place entities (enemy spawn points, waypoints, stations, asteroids), define zones (named rectangular or circular areas), and set initial ship position. Entities and zones are referenced by ID in triggers and actions.

**Validation**: Real-time validation in the panel:
- Every graph must have a start_node
- Every graph must have at least one victory_node
- Every node must be reachable from start_node
- Every victory_node must be reachable from at least one path
- Branch nodes must have at least 2 outgoing branch_trigger edges
- Parallel nodes must have at least 2 children
- All entity/zone references in triggers must exist in the star chart
- All puzzle_label references must be unique

**Test button**: Exports the mission and launches it immediately in a new tab (sandbox mode, single player). Allows rapid iteration — edit, test, edit, test.

### 6.4 Server Endpoints

```
GET  /editor              → Serves editor page
POST /editor/validate     → Server-side mission validation
POST /editor/save         → Save mission JSON to missions/ folder
GET  /editor/missions     → List all mission files
GET  /editor/mission/:id  → Load a specific mission for editing
```

### 6.5 Game Integration

The mission editor is an assessment activity. Players design missions that demonstrate understanding of:
- Conditional logic (trigger conditions)
- State machines (graph structure)
- Event-driven programming (on_complete actions)
- User experience design (pacing, difficulty, player agency)
- Systems thinking (how station interactions create emergent gameplay)

A rubric for mission design assessment:

| Criterion | Basic | Proficient | Advanced |
|-----------|-------|-----------|---------|
| Structure | Linear (A→B→C) | Includes parallel objectives | Includes branches and conditionals |
| Player agency | One path to victory | Multiple paths, some choices | Actions determine mission flow |
| Role engagement | 2-3 roles active | 5-6 roles each have meaningful work | All roles have critical moments |
| Difficulty curve | Flat | Builds tension | Escalates with emergent complications |
| Replay value | Same every time | Slight variation | Genuinely different on replay |

### Acceptance Criteria

- [ ] Editor loads and renders an empty graph
- [ ] All node types can be created, positioned, and edited
- [ ] Edges can be drawn between nodes with correct type inference
- [ ] Trigger builder produces valid trigger JSON for all trigger types
- [ ] Star chart allows entity and zone placement
- [ ] Validation catches common errors in real-time
- [ ] Export produces valid mission JSON that loads in the game
- [ ] Save/load works (missions persist across editor sessions)
- [ ] Test button launches the mission for immediate playtesting
- [ ] An existing mission can be loaded, modified, and re-saved
- [ ] A complete mission can be authored from scratch in the editor

---

## 7. v0.04e — CAPTAIN STATION OVERHAUL

**Purpose**: Transform the Captain station from a dashboard into a command centre.

### 7.1 3D Wireframe Viewports

Four viewports showing the space around the ship from forward, aft, port, and starboard perspectives. Elite (1984) / Battlezone visual style — vector graphics on dark background, no fills, no textures.

**3D projection system**:

```javascript
// Simple perspective projection — no WebGL needed
function project(worldPos, cameraPos, cameraHeading, fov, canvasSize) {
    // 1. Translate world position relative to camera
    const dx = worldPos.x - cameraPos.x;
    const dy = worldPos.y - cameraPos.y;
    
    // 2. Rotate into camera space based on viewport direction
    //    (forward = ship heading, aft = heading+180, port = heading+90, etc.)
    const cos = Math.cos(-cameraHeading);
    const sin = Math.sin(-cameraHeading);
    const cx = dx * cos - dy * sin;
    const cy = dx * sin + dy * cos;
    
    // 3. Perspective divide
    if (cx <= 0) return null;  // Behind camera
    const scale = fov / cx;
    const sx = canvasSize.w / 2 + cy * scale;
    const sy = canvasSize.h / 2;  // 2D game, so y is flat
    
    return { x: sx, y: sy, scale: scale };
}
```

**Wireframe ship models**: Each enemy type has a simple wireframe model defined as a list of edges (pairs of 3D points). Models are 5-15 edges each — enough to be recognisable, not enough to be expensive.

```javascript
const WIREFRAME_MODELS = {
    scout: {
        edges: [
            [[-10, 0], [10, 0]],    // Wing span
            [[ 10, 0], [ 0, 20]],   // Right wing to nose
            [[ -10, 0], [ 0, 20]],  // Left wing to nose
            [[ 0, 20], [ 0, -10]],  // Nose to tail
        ],
        colour: '--hostile'
    },
    cruiser: { ... },
    destroyer: { ... },
    station: { ... },
    torpedo: {
        edges: [[[-2, 0], [2, 0]], [[0, -2], [0, 2]]],  // Cross
        colour: '--hostile'
    },
    friendly: { ... }
};
```

**Per-viewport rendering**:
- Background: black with parallax star points (same as Helm viewscreen)
- Contacts within the viewport's 90° arc rendered as wireframe models at correct bearing and distance
- Beam weapons rendered as bright lines from source to target (fade over 200ms)
- Torpedoes rendered as bright dots with trailing lines
- Shield impacts rendered as arc flashes
- Explosions rendered as expanding wireframe circles
- Viewport border colour changes with alert level (green/amber/red)
- Contact wireframes colour-coded: hostile red, friendly green, neutral amber, unknown white

**Layout**: Four viewports arranged in a 2×2 grid, or in a cross pattern (forward top, port left, starboard right, aft bottom). The arrangement should be configurable or auto-selected based on screen aspect ratio.

### 7.2 Damage Report Panel

A real-time ship status display built on the Security ship-shaped hull outline:

- Ship silhouette divided into sections matching the ship interior rooms
- Each section colour-coded by system health: green (>60%), amber (30-60%), red (<30%), grey (offline/0%)
- Hull integrity percentage prominently displayed
- Click a section for detail popover: system name, health %, power %, crew factor, repair status, repair ETA
- Damage flash animation when a section takes damage (same pattern as Engineering)
- Breach indicators (if DC has breaches), fire indicators, decompression indicators
- Updates live from ship.state broadcasts

### 7.3 Crew Status Panel

Toggleable overlay on the ship silhouette (button to switch between "Systems" and "Crew" views):

- Same ship outline, but sections coloured by crew health: green (full crew), amber (casualties >20%), red (casualties >50%), grey (no crew/decompressed)
- Per-deck crew counts: active / injured / critical / dead
- Overall crew readiness percentage
- Medical treatment indicator (which deck Medical is currently treating)
- Crew factor per deck (the efficiency impact number)

### 7.4 System Master Controls

A panel showing every ship system with an on/off toggle:

```
SYSTEM CONTROLS          STATUS    POWER    HEALTH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Engines          [██ ON]   100%     ██████ 85%
Beams            [██ ON]   120%     ██████ 100%
Torpedoes        [░░ OFF]  0%       ████░░ 60%
Shields          [██ ON]   100%     ██████ 95%
Sensors          [██ ON]   80%      ██████ 100%
Manoeuvring      [██ ON]   100%     ██████ 90%
Flight Deck      [██ ON]   100%     ██████ 100%
ECM Suite        [░░ OFF]  0%       ██████ 100%
Point Defence    [██ ON]   60%      ██████ 100%
```

- Toggle switches send `captain.system_override { system, online: bool }` message
- When Captain takes a system offline, Engineering sees it go to 0% power and cannot re-enable it (override indicator shows "CAPTAIN OVERRIDE")
- When Captain brings a system online, it returns to whatever power level Engineering had set
- Confirmation dialog on each toggle: "Take TORPEDOES offline? Engineering will lose control of this system."
- Override status visible on Engineering's display (systems under Captain override show a lock icon)

**Server implementation**: Add `overrides: dict[str, bool]` to Ship. When an override is active for a system, the system's effective power is forced to 0% regardless of Engineering's setting. When the override is lifted, the system returns to Engineering's set power level. This is checked in the efficiency calculation, not in Engineering's handler.

### 7.5 Mission Objectives Panel (Enhanced)

The existing objectives panel, enhanced for graph missions:
- Active objectives shown with progress indicators
- Parallel objectives shown as a group with individual progress
- Branch decision shown as "AWAITING CREW RESPONSE" (not revealing the options)
- Conditional objectives appear/disappear with animation
- Completed objectives shown greyed with checkmark
- Failed objectives shown with red X

### 7.6 Overall Layout

```
┌──────────┬──────────┬──────────────────────┐
│ FORWARD  │  AFT     │  SHIP STATUS         │
│ VIEWPORT │ VIEWPORT │  [Systems/Crew toggle]│
│          │          │  [Ship silhouette]    │
├──────────┼──────────┤  [Click for details]  │
│ PORT     │ STARBOARD│                       │
│ VIEWPORT │ VIEWPORT ├──────────────────────┤
│          │          │  SYSTEM CONTROLS      │
│          │          │  [On/Off toggles]     │
├──────────┴──────────┼──────────────────────┤
│ TACTICAL MAP        │  OBJECTIVES           │
│ (existing, smaller) │  [Mission graph state] │
│                     │                       │
├─────────────────────┤  ALERT: [G] [Y] [R]  │
│ ALERT BOARD         │                       │
│ [Scrolling events]  │  [AUTH REQUESTS]      │
└─────────────────────┴──────────────────────┘
```

The tactical map stays but becomes smaller — the viewports are the primary spatial awareness tool. The tactical map becomes the "zoomed out strategic view" while the viewports are the "out the window" view.

### Acceptance Criteria

- [ ] Four 3D wireframe viewports render contacts at correct bearings
- [ ] Wireframe ship models visible and distinguishable by type
- [ ] Beam weapons, torpedoes, and explosions render in viewports
- [ ] Viewports respond to alert level (border colour, contact brightness)
- [ ] Damage report panel shows system health on ship silhouette
- [ ] Click a section for system detail popover
- [ ] Crew status panel shows crew health by deck
- [ ] Systems/Crew toggle switches the ship silhouette display
- [ ] System master controls toggle systems on/off
- [ ] Captain override prevents Engineering from changing the system
- [ ] Engineering sees "CAPTAIN OVERRIDE" indicator
- [ ] Mission objectives panel shows parallel/branch/conditional correctly
- [ ] Overall layout is responsive and usable on a laptop screen

---

## 8. v0.04f — SAVE AND RESUME

**Purpose**: Serialise full game state mid-mission, resume from save file.

### 8.1 Serialisation Architecture

Every game_loop module gets two new functions:

```python
# In each game_loop_*.py module:
def serialise() -> dict:
    """Return all module state as a JSON-serialisable dict."""
    ...

def deserialise(data: dict) -> None:
    """Restore module state from a serialised dict."""
    ...
```

The save system collects state from all modules:

```python
# server/save_system.py
def save_game(filepath: Path) -> None:
    state = {
        "version": "0.04",
        "timestamp": time.time(),
        "tick": game_loop.current_tick(),
        "mission": mission_engine.serialise(),
        "ship": ship.serialise(),
        "world": world.serialise(),
        "puzzle_engine": puzzle_engine.serialise(),
        "modules": {
            "weapons": game_loop_weapons.serialise(),
            "physics": game_loop_physics.serialise(),
            "mission": game_loop_mission.serialise(),
            "security": game_loop_security.serialise(),
            "medical": game_loop_medical.serialise(),
            "flight_ops": game_loop_flight_ops.serialise(),
            "ew": game_loop_ew.serialise(),
            "tactical": game_loop_tactical.serialise(),
            "damage_control": game_loop_damage_control.serialise(),
            "comms": game_loop_comms.serialise(),
            "captain": game_loop_captain.serialise(),
        },
        "players": lobby.serialise(),
        "logger": game_logger.serialise(),
    }
    filepath.write_text(json.dumps(state, indent=2))

def load_game(filepath: Path) -> None:
    state = json.loads(filepath.read_text())
    # Restore each module
    game_loop.set_tick(state["tick"])
    mission_engine.deserialise(state["mission"])
    ship.deserialise(state["ship"])
    # ... etc for every module
    # Resume the game loop
    game_loop.resume()
```

### 8.2 Save/Resume Flow

**Save**: Captain presses "SAVE GAME" button (or admin triggers via the admin dashboard). The game loop pauses (stops ticking), serialises everything, writes to `saves/save_YYYYMMDD_HHMMSS.json`, confirms to all clients ("GAME SAVED"), then all clients return to lobby.

**Resume**: In the lobby, the host clicks "RESUME GAME" instead of "NEW GAME". A file picker shows available saves. Host selects a save. Server loads the save, restores all state, sends `game.resumed` to all clients with the saved player-role assignments. Each player reclaims their previous role (or a different one if needed). When all required roles are filled, the game loop resumes.

**Auto-save**: Game auto-saves at checkpoint nodes in the mission graph (if defined). Auto-save files are overwritten each checkpoint (only latest checkpoint kept, not all of them).

### 8.3 Client Handling

On `game.resumed`, each station receives the full current state:
- `ship.state` (complete ship status)
- `world.entities` / `sensor.contacts` (all entities)
- `mission.status` (current graph state, active objectives)
- Any active puzzles (`puzzle.started` replayed)
- Security interior state, crew state, flight ops state, etc.

This is essentially the same as a reconnect but from a cold start. Stations must handle receiving full state without a preceding `game.started`.

### Acceptance Criteria

- [ ] Every game_loop module has serialise() and deserialise()
- [ ] Save produces a valid JSON file capturing full game state
- [ ] Resume restores game state identically
- [ ] Enemies, puzzles, mission progress all survive save/resume
- [ ] Auto-save works at checkpoint nodes
- [ ] Save file includes version for forward compatibility
- [ ] Resume flow in lobby works (select save, assign roles, launch)
- [ ] Round-trip test: start mission → play 2 minutes → save → exit → resume → continue playing → complete mission

---

## 9. v0.04g — Player PROFILES + ACHIEVEMENTS

**Purpose**: Persistent player identity, stats tracking, achievements, and exportable data.

### 9.1 Profile Storage

```
profiles/
├── index.json            # Player name → profile file mapping
├── alice.json            # Alice's profile
├── bob.json              # Bob's profile
└── ...
```

Each profile:
```json
{
    "name": "Alice",
    "created": "2026-03-01T09:00:00Z",
    "games_played": 24,
    "games_won": 18,
    "total_play_time_seconds": 43200,
    "roles_played": {
        "helm": 8,
        "weapons": 5,
        "science": 4,
        "engineering": 3,
        "captain": 2,
        "medical": 1,
        "security": 1
    },
    "missions_completed": ["first_contact", "defend_station", ...],
    "achievements": ["sharpshooter", "first_command", ...],
    "puzzle_scores": {
        "frequency_matching": { "attempts": 12, "best_score": 95, "avg_score": 72 },
        ...
    },
    "stats": {
        "damage_dealt": 4500,
        "damage_taken": 2800,
        "crew_treated": 120,
        "scans_completed": 85,
        ...
    }
}
```

### 9.2 Achievement System

Achievements are defined as conditions checked at mission end:

| Achievement | Condition | Icon |
|------------|-----------|------|
| First Command | Complete any mission as Captain | ⭐ |
| Bridge Regular | Play every role at least once | 🌟 |
| Sharpshooter | Deal >500 damage in one mission (Weapons) | 🎯 |
| Iron Hull | Complete a mission taking <10% hull damage | 🛡️ |
| Quick Thinker | Solve 3 puzzles in one mission with >80% score | ⚡ |
| Life Saver | Treat >20 crew in one mission (Medical) | ❤️ |
| Gatekeeper | Repel a boarding with zero marine casualties | 🚪 |
| Diplomat | Complete First Contact via diplomatic branch | 🤝 |
| Explorer | Complete all missions | 🗺️ |
| Admiral | Complete any mission on Admiral difficulty | 🏅 |
| Mission Designer | Create and share a mission using the editor | 📝 |
| Veteran | Play 50 games | ⭐⭐ |

### 9.3 Lobby Integration

- Login screen before lobby: enter name (or select from recent players list)
- Player card in lobby shows: name, games played, favourite role, recent achievements
- Leaderboard accessible from lobby: sortable by games won, damage dealt, puzzles solved, etc.

### 9.4 Data Export

`GET /profiles/export` returns a CSV with all player stats — one row per player, columns for every tracked metric. Admins can download this for player records.

### Acceptance Criteria

- [ ] Player profiles persist across game sessions
- [ ] Stats accumulate correctly across multiple games
- [ ] Achievements trigger and display correctly
- [ ] Lobby shows player cards with stats
- [ ] Leaderboard works
- [ ] CSV export works and includes all tracked metrics
- [ ] Profile data survives server restart

---

## 10. v0.04h — ADMIN DASHBOARD + SPECTATOR MODE

**Purpose**: Live monitoring of all stations, annotations, engagement tracking.

### 10.1 Admin Dashboard

A dedicated view at `/admin` showing a grid of all connected stations in miniature:

```
┌──────────┬──────────┬──────────┬──────────┐
│ CAPTAIN  │ HELM     │ WEAPONS  │ ENGINEER │
│ (Alice)  │ (Bob)    │ (Charlie)│ (Diana)  │
│ [mini]   │ [mini]   │ [mini]   │ [mini]   │
├──────────┼──────────┼──────────┼──────────┤
│ SCIENCE  │ MEDICAL  │ SECURITY │ COMMS    │
│ (Eve)    │ (Frank)  │ (Grace)  │ (Hank)   │
│ [mini]   │ [mini]   │ [mini]   │ [mini]   │
├──────────┼──────────┼──────────┼──────────┤
│ FLIGHT   │ EW       │ TACTICAL │ DC       │
│ (Iris)   │ (Jack)   │ (Kate)   │ (Liam)   │
│ [mini]   │ [mini]   │ [mini]   │ [mini]   │
└──────────┴──────────┴──────────┴──────────┘
```

Each mini-panel shows a simplified version of that station's current state — enough to tell if the player is engaged. Click a panel to enlarge it to full-size.

### 10.2 Admin Controls

- **Pause game**: Freeze the game loop (all clients see "PAUSED BY ADMIN")
- **Send annotation**: Click a station panel, type a message → appears on that players's screen as a admin note
- **Broadcast**: Send a message to all stations
- **Adjust difficulty**: Change difficulty mid-game (multipliers update on next tick)
- **Trigger event**: Manually fire a mission event (spawn enemies, start puzzle, trigger objective) for teaching purposes
- **Save game**: Trigger a save from the admin dashboard

### 10.3 Engagement Monitoring

The admin dashboard tracks per-station:
- Last interaction time (how long since this player clicked/typed anything)
- Actions per minute (rolling average)
- Idle indicator (>30 seconds with no interaction = amber, >60 seconds = red)

This helps the admin spot players who are disengaged, confused, or AFK.

### Acceptance Criteria

- [ ] Admin dashboard shows all connected stations in grid
- [ ] Mini-panels update in real-time
- [ ] Click to enlarge works
- [ ] Pause/resume from dashboard works
- [ ] Annotations appear on target station
- [ ] Broadcast reaches all stations
- [ ] Difficulty adjustment mid-game works
- [ ] Manual event triggering works
- [ ] Engagement monitoring shows idle indicators
- [ ] Dashboard works alongside normal gameplay (doesn't interfere)

---

## 11. v0.04i — PERFORMANCE HARDENING

**Purpose**: Verify the game works under real game conditions and fix bottlenecks.

### 11.1 Stress Test Script

A Python script that simulates 12 simultaneous WebSocket clients:

```
tools/stress_test.py
- Connects 12 WebSocket clients with different roles
- Each client sends realistic message patterns (helm changes, power adjustments, scans, weapon fires)
- Runs for 5 minutes simulating a combat mission
- Measures: server tick consistency (should be stable 10Hz), message latency (broadcast to receipt), memory usage, CPU usage
- Reports: max/avg/p99 tick time, message backlog, dropped messages, memory growth
```

### 11.2 Performance Targets

| Metric | Target | Acceptable | Unacceptable |
|--------|--------|-----------|-------------|
| Tick rate | 10Hz ±0.5Hz | 10Hz ±1Hz | Below 8Hz |
| Broadcast latency | <20ms | <50ms | >100ms |
| Memory usage | <200MB | <500MB | >1GB |
| CPU (single core) | <30% | <60% | >80% |
| 12-client WiFi | All stable | Occasional stutter | Frequent disconnects |

### 11.3 Known Risk Areas

- 12 WebSocket connections each receiving 10Hz broadcasts = 120 messages/second outbound
- sensor.contacts filtering runs per tick per role with different filter logic
- The game logger writing to disk on every event during combat
- Puzzle engine ticking multiple active puzzles simultaneously
- MapRenderer on older tablets/phones with 20+ contacts

### Acceptance Criteria

- [ ] Stress test script runs successfully with 12 simulated clients
- [ ] All performance targets met at "Acceptable" or better
- [ ] No memory leaks over a 10-minute session
- [ ] No dropped WebSocket connections under normal conditions
- [ ] Game logger doesn't create I/O bottleneck during combat
- [ ] Identified and fixed at least 2 performance bottlenecks

---

## 12. v0.04j — ACCESSIBILITY PASS

**Purpose**: Make the game usable by players with different abilities.

### 12.1 Colour-Blind Mode

The wire aesthetic relies heavily on green/red/amber colour coding. Add an alternative palette that uses shapes and patterns alongside colour:

- Friendly: green + circle marker → blue + circle marker
- Hostile: red + diamond marker → orange + diamond marker (with crosshatch pattern)
- Neutral: amber + square marker → purple + square marker
- Damaged: red → orange with striped pattern
- Healthy: green → blue with solid fill

Toggle in settings. Persisted per device.

### 12.2 Keyboard Navigation

Every station must be fully operable via keyboard:
- Tab cycles through interactive elements
- Enter/Space activates buttons and toggles
- Arrow keys for sliders and directional controls
- Number keys for common actions (already partially done for scan modes)
- Escape to dismiss overlays
- Clear focus indicators (visible outline on focused elements)

### 12.3 Screen Reader Hints

Add ARIA labels to all interactive elements. Add live regions for dynamic content (alerts, notifications, game state changes). Non-visual stations (Engineering sliders, Comms text interface) should be fully accessible. Visual stations (maps, viewports) get text summaries accessible via screen reader: "3 hostile contacts detected. Nearest at bearing 045, range 8000 units."

### 12.4 Reduced Motion Mode

For players sensitive to motion: disable parallax starfield, disable screen shake on hull hit, reduce animation speeds, disable scanline flicker. Toggle in settings.

### Acceptance Criteria

- [ ] Colour-blind mode provides distinguishable visuals without relying on red/green
- [ ] All stations navigable via keyboard only
- [ ] ARIA labels on all interactive elements
- [ ] At least 3 stations fully screen-reader accessible
- [ ] Reduced motion mode disables animations and flicker
- [ ] Settings persist per device

---

## 13. v0.04k — FINAL INTEGRATION + v0.04 GATE

### 13.1 Full Integration Test Matrix

| Test | Ship Class | Crew Size | Mission Type | Difficulty |
|------|-----------|-----------|-------------|-----------|
| 1 | Scout | 3 | First Contact Remastered (combat branch) | Officer |
| 2 | Frigate | 8 | Salvage Run (rescue branch) | Officer |
| 3 | Battleship | 12 | The Convoy | Commander |
| 4 | Medical Ship | 6 | Pandemic (alien branch) | Cadet |
| 5 | Any | 1 | Training mission (each station) | Cadet |
| 6 | Cruiser | 10 | player-created mission (from editor) | Officer |
| 7 | Any | 8 | Save mid-mission → resume next day | Officer |

### 13.2 v0.04 Gate Checklist

- [ ] Mission graph engine handles parallel, branch, conditional, checkpoint nodes
- [ ] All 23 existing missions migrated and functional
- [ ] 3-4 new graph-native missions playable with multiple valid paths
- [ ] Mission editor creates valid missions from scratch
- [ ] Captain station has 3D viewports, damage/crew panels, system overrides
- [ ] Save/resume works (round-trip test passes)
- [ ] Player profiles persist and accumulate stats
- [ ] Achievements trigger correctly
- [ ] Admin dashboard shows all stations live
- [ ] Performance targets met with 12 simultaneous clients
- [ ] Colour-blind mode distinguishable
- [ ] Keyboard navigation works on all stations
- [ ] All tests pass
- [ ] All v0.01/v0.02/v0.03 missions still work
- [ ] README updated with v0.04 features and game deployment guide

---

## 14. ESTIMATED SCOPE

| Sub-Release | Estimated Sessions | Notes |
|-------------|-------------------|-------|
| v0.04a Mission graph engine | 6-8 | Most architecturally critical piece |
| v0.04b Mission migration | 3-4 | Mostly mechanical, some creative enhancement |
| v0.04c New missions | 6-8 | 3-4 missions with branching and emergent objectives |
| v0.04d Mission editor | 8-10 | Most complex client work — node graph UI |
| v0.04e Captain overhaul | 6-8 | 3D projection + multiple panels + system controls |
| v0.04f Save/resume | 4-5 | Serialisation across all modules |
| v0.04g Player profiles | 3-4 | Straightforward persistence |
| v0.04h Admin dashboard | 5-6 | Live monitoring + controls |
| v0.04i Performance hardening | 3-4 | Testing and optimisation |
| v0.04j Accessibility | 3-4 | Colour-blind, keyboard, screen reader, motion |
| v0.04k Integration + gate | 4-5 | Comprehensive testing |

**Total: ~55-70 sessions.** The mission graph engine and editor are the largest items. The Captain overhaul is the most visually ambitious.

---

## 15. WHAT v0.04 ENABLES

After v0.04, Starbridge supports:
- **Player-driven narratives**: Missions respond to crew decisions, not scripts. Different playthroughs produce different stories.
- **Player creativity**: The mission editor turns mission design into an assessment activity. Players demonstrate computational thinking by building interactive experiences for their peers.
- **Game deployment**: Save/resume fits time periods. Profiles provide assessment data. The admin dashboard enables supervision. Difficulty presets accommodate mixed ability groups.
- **Genuine command authority**: The Captain makes mechanically meaningful decisions — system overrides, branch choices, mission prioritisation.
- **Accessibility**: Players with different abilities can participate meaningfully.

The remaining gap for a "1.0" release: networked play beyond LAN, community mission sharing, and a mission marketplace where Players share and rate each other's creations. Those are v0.05 concerns.

---

*Document version: v0.04-scope-1.0*
*Last updated: 2026-02-20*
*Status: DRAFT — Begin implementation after v0.03 playtest and review*
