# STARBRIDGE

**Cooperative multiplayer bridge crew simulator — v0.01**

5–6 players connect via web browsers on a local network, each taking a distinct role aboard a starship. No single player can succeed alone — the fun comes from communication, coordination, and creative problem-solving under pressure.

Inspired by [Artemis Spaceship Bridge Simulator](https://www.artemisspaceshipbridge.com/), rebuilt as a modern web application with zero setup friction.

---

## Quick Start

### Requirements

- Python 3.12+
- A local network (WiFi or wired)
- Modern web browsers (Chrome, Firefox, Safari, Edge)
- Minimum recommended screen: 768px wide (tablet or laptop)

### Setup

```bash
# Clone the repository
git clone <repo-url>
cd starbridge

# Create virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate          # Windows

# Install dependencies
pip install -r requirements.txt

# Start the server
python run.py
```

### Connect

1. The server prints a URL like `http://192.168.1.100:8666/client/lobby/`
2. Share this URL with your crew
3. Everyone opens it in their browser and enters a callsign
4. Choose roles, select a mission, launch, and save the galaxy

---

## Roles

| Role | Summary |
|------|---------|
| **Captain** | Overview of all systems. Sets alert level (shifts all stations to green/yellow/red). Makes strategic calls. Controls nothing directly. |
| **Helm** | Steers the ship. Manages speed and heading. Executes manoeuvres. |
| **Weapons** | Targets enemies. Fires beams and torpedoes. Manages shield balance. |
| **Engineering** | Distributes power across six systems. Repairs damage. Overclocks under pressure. |
| **Science** | Scans contacts. Identifies threats and weaknesses. Triangulates signals. |
| **Viewscreen** | Display-only role for a shared TV/projector. Shows the forward view. |

---

## Missions

| Mission | Description |
|---------|-------------|
| **Sandbox** | Free play. No objectives. Enemies spawn continuously. |
| **First Contact** | Patrol, scan the hostile scout, destroy all contacts, return to base. |
| **Defend the Station** | Repel three enemy waves before they destroy Station Kepler. |
| **Search and Rescue** | Triangulate a distress signal, navigate the asteroid field, extend shields around the damaged vessel, escort them home. |

---

## Game Flow

1. **Lobby** — Players connect, enter callsigns, claim roles, host selects a mission and clicks Launch
2. **Briefing** — Mission name and briefing text appear on all stations (15s auto-dismiss, click to skip)
3. **Mission** — Stations coordinate in real time; objectives update as goals are met
4. **End** — Victory or defeat overlay appears on all stations with duration and hull stats, plus a Return to Lobby button
5. **Repeat** — Host can launch a new mission immediately from the lobby

---

## Tech Stack

- **Server**: Python / FastAPI / asyncio / WebSockets (10 Hz game loop)
- **Client**: Vanilla HTML5 / Canvas / ES Modules (no framework, no build step)
- **Aesthetic**: Wire-frame vector graphics — Battlezone / DEFCON / Alien ship computer style

---

## Running Tests

```bash
python -m pytest
```

v0.01 ships with **331 passing tests** covering the server, missions, AI, combat, and sensors.

---

## Debug Endpoints

While the server is running you can use these HTTP endpoints:

```
GET  /                               — Health check
POST /debug/damage?system=hull&amount=40  — Deal damage to a system
POST /debug/spawn_enemy?type=cruiser      — Spawn an enemy near the player
POST /debug/start_game?mission_id=sandbox — Force-start without a lobby
GET  /debug/ship_status                   — Current ship state as JSON
```

Set `STARBRIDGE_DEBUG=false` to disable these before public deployment.

---

## Architecture Notes

- **One session per server process** — designed for LAN play with friends
- **No database** — all state lives in memory; game resets on server restart
- **10 Hz game loop** — asyncio task; clients render at 60 fps via interpolation
- **WebSocket envelope** — `{ "type": "category.event", "payload": {...} }`
- **Role-based broadcasts** — helm/engineering get full world data; weapons/science get sensor-filtered contacts

---

## License

TBD
