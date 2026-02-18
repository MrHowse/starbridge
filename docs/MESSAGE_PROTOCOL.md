# WebSocket Message Protocol

> **LIVING DOCUMENT** — Add new message types as they are implemented.
> Every WebSocket message must conform to this protocol.

## Envelope Format

Every message (client→server and server→client) uses this JSON envelope:

```json
{
  "type": "category.action",
  "payload": { },
  "tick": 1234,
  "timestamp": 1700000000.123
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `type` | string | Yes | Namespaced: `category.action` |
| `payload` | object | Yes | Action-specific data. Empty `{}` if no data needed. |
| `tick` | integer | Server→Client only | Current game tick. Absent in client→server and lobby messages. |
| `timestamp` | float | Yes | Unix timestamp (seconds with millisecond precision) |

## Type Naming Convention

- Lowercase, dot-separated: `category.action`
- Categories match roles or systems: `lobby`, `helm`, `weapons`, `engineering`, `science`, `captain`, `ship`, `world`, `mission`, `game`
- Actions are verbs or descriptors: `set_heading`, `fire_torpedo`, `state_update`

---

## Client → Server Messages

These are **intentions** — the client requests an action, the server validates and executes.

### Lobby

| Type | Payload | Description |
|------|---------|-------------|
| `lobby.claim_role` | `{ "role": string, "player_name": string }` | Request to claim a role. Roles: `captain`, `helm`, `weapons`, `engineering`, `science` |
| `lobby.release_role` | `{ }` | Release the player's currently held role |
| `lobby.start_game` | `{ "mission_id": string }` | Host requests game start. Only valid from host connection. |

### Helm (Phase 2)

| Type | Payload | Description |
|------|---------|-------------|
| `helm.set_heading` | `{ "heading": float }` | Set desired heading (0-359.9 degrees) |
| `helm.set_throttle` | `{ "throttle": float }` | Set throttle level (0-100) |

### Weapons (Phase 4)

| Type | Payload | Description |
|------|---------|-------------|
| `weapons.select_target` | `{ "entity_id": string }` | Select a target contact |
| `weapons.fire_beams` | `{ }` | Fire beam weapons at selected target |
| `weapons.fire_torpedo` | `{ }` | Fire a torpedo at selected target |
| `weapons.set_shields` | `{ "front": float, "rear": float }` | Set front/rear shield balance (each 0-100) |

### Engineering (Phase 3)

| Type | Payload | Description |
|------|---------|-------------|
| `engineering.set_power` | `{ "system": string, "level": float }` | Set power level for a system (0-150) |
| `engineering.set_repair` | `{ "system": string }` | Assign repair focus to a system |

### Science (Phase 5)

| Type | Payload | Description |
|------|---------|-------------|
| `science.start_scan` | `{ "entity_id": string }` | Begin scanning a contact |
| `science.cancel_scan` | `{ }` | Cancel the current scan |

### Captain (Phase 6)

| Type | Payload | Description |
|------|---------|-------------|
| `captain.set_alert` | `{ "level": string }` | Set alert level: `"green"`, `"yellow"`, or `"red"` |

---

## Server → Client Messages

These are **state updates and events** — the server tells clients what happened.

### Lobby

| Type | Payload | Description | Sent To |
|------|---------|-------------|---------|
| `lobby.welcome` | `{ "connection_id": string, "is_host": bool }` | Sent to a new client immediately after they connect. Provides their server-assigned connection ID and whether they are the host. | Connecting client |
| `lobby.state` | `{ "roles": { role: player_name \| null }, "host": string, "session_id": string }` | Current lobby state. `host` is the connection ID of the current host. Clients compare this to their own `connection_id` (from `lobby.welcome`) to determine if they are host. | All |
| `lobby.error` | `{ "message": string }` | Error response to a lobby action | Requesting client |

### Game Lifecycle

| Type | Payload | Description | Sent To |
|------|---------|-------------|---------|
| `game.started` | `{ "mission_id": string, "mission_name": string, "briefing_text": string }` | Game session has begun | All |
| `game.tick` | `{ "tick": integer, "timestamp": float }` | Tick heartbeat (for sync) | All |
| `game.over` | `{ "result": "victory" \| "defeat", "stats": object }` | Game has ended | All |

### Ship State (Phase 2+)

| Type | Payload | Description | Sent To |
|------|---------|-------------|---------|
| `ship.state` | `{ "position": {x, y}, "heading": float, "velocity": float, "hull": float, "shields": { "front": float, "rear": float }, "systems": { system_name: { "power": float, "health": float, "efficiency": float } }, "alert_level": string }` | Full ship state update | Captain (full), others (filtered) |
| `ship.system_damaged` | `{ "system": string, "new_health": float, "cause": string }` | A system took damage | Engineering, Captain |
| `ship.hull_hit` | `{ "damage": float, "new_hull": float, "direction": string }` | Hull took direct damage | All |

### World State (Phase 2+)

| Type | Payload | Description | Sent To |
|------|---------|-------------|---------|
| `world.entities` | `{ "entities": [{ "id": string, "type": string, "position": {x, y}, "heading": float, "velocity": float, "classification": string }] }` | Visible entities update | Role-filtered (range/scan dependent) |
| `world.entity_spawned` | `{ "entity": object }` | New entity appeared | Relevant roles |
| `world.entity_destroyed` | `{ "entity_id": string, "cause": string }` | Entity removed from world | All |

### Combat (Phase 4)

| Type | Payload | Description | Sent To |
|------|---------|-------------|---------|
| `weapons.beam_fired` | `{ "source_id": string, "target_id": string, "damage": float }` | Beam weapon discharged | Weapons, Captain, Viewscreen |
| `weapons.torpedo_fired` | `{ "torpedo_id": string, "source_id": string, "heading": float, "position": {x, y} }` | Torpedo launched | All |
| `weapons.torpedo_hit` | `{ "torpedo_id": string, "target_id": string, "damage": float }` | Torpedo impacted | All |

### Science (Phase 5)

| Type | Payload | Description | Sent To |
|------|---------|-------------|---------|
| `science.scan_progress` | `{ "entity_id": string, "progress": float }` | Scan progress update (0-100) | Science |
| `science.scan_complete` | `{ "entity_id": string, "results": { "type": string, "shield_strength": float, "weapon_loadout": string, "weakness": string, "hull": float } }` | Scan finished with full results | Science, Captain |

### Mission (Phase 6)

| Type | Payload | Description | Sent To |
|------|---------|-------------|---------|
| `mission.objective_update` | `{ "objectives": [{ "id": string, "text": string, "status": "active" \| "complete" \| "failed" }] }` | Mission objectives changed | Captain, All (configurable) |
| `mission.transmission` | `{ "from": string, "message": string, "priority": string }` | Incoming communication | Comms (if exists), Captain |
| `mission.event` | `{ "type": string, "data": object }` | Generic mission event | Varies |

---

## Error Messages

The server may send error messages to individual clients:

| Type | Payload | Description |
|------|---------|-------------|
| `error.validation` | `{ "message": string, "original_type": string }` | Message failed validation |
| `error.permission` | `{ "message": string, "original_type": string }` | Action not permitted (e.g., non-host starting game) |
| `error.state` | `{ "message": string, "original_type": string }` | Action invalid in current state (e.g., firing weapons in lobby) |

---

## Implementation Notes

- All payload schemas should have corresponding Pydantic models in `server/models/messages.py`
- Client→Server messages are validated on receipt; invalid messages trigger `error.validation` response
- Server→Client messages are constructed via helper functions that ensure envelope compliance
- The `tick` field is only present on server→client messages sent during active gameplay
- `timestamp` is always present and uses `time.time()` (Unix seconds, float)
