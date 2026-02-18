# Mission Data Format

> **This document will be fully defined in Phase 6 when the mission engine is built.**

## Overview

Missions are defined as JSON files in the `missions/` directory. A mission engine loads and interprets these files at runtime, evaluating triggers and executing events.

## Planned Structure

```json
{
  "id": "first_contact",
  "name": "First Contact",
  "description": "A routine patrol turns into humanity's first encounter...",
  "briefing": "Long-form briefing text shown before mission start.",
  "objectives": [
    {
      "id": "obj_1",
      "text": "Patrol to waypoint Alpha",
      "type": "reach_area",
      "required": true
    }
  ],
  "triggers": [
    {
      "id": "trg_1",
      "condition": { "type": "player_in_area", "area": { "x": 1000, "y": 2000, "radius": 500 } },
      "events": [
        { "type": "spawn_entity", "entity_type": "scout", "position": { "x": 1200, "y": 2200 } },
        { "type": "display_message", "text": "Contact detected on sensors!" }
      ],
      "once": true
    }
  ],
  "entities": [],
  "settings": {
    "sector_size": 100000,
    "time_limit": null
  }
}
```

## Trigger Types (Planned)

- `player_in_area` — Player ship enters a defined area
- `entity_destroyed` — A specific entity or entity type is destroyed
- `timer_elapsed` — A specified time has passed since mission start or since a previous trigger
- `scan_completed` — Science has scanned a specific entity
- `objective_complete` — A specific objective has been completed
- `hull_below` — Player ship hull drops below a threshold
- `all_enemies_destroyed` — No hostile entities remain

## Event Types (Planned)

- `spawn_entity` — Add an entity to the world
- `display_message` — Show a message on relevant stations
- `play_transmission` — Show an incoming comms transmission
- `update_objective` — Mark an objective as complete/failed, or add a new one
- `set_waypoint` — Add or update a navigation waypoint
- `end_mission` — Trigger mission victory or defeat

## Notes

- Triggers can fire once or repeatedly
- Triggers can have delays (fire N seconds after condition is met)
- Multiple events can be chained from a single trigger
- The format should be kept simple enough to author by hand in a text editor
- Detailed schema with validation will be defined alongside the Phase 6 implementation
