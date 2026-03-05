# STARBRIDGE

**Cooperative multiplayer bridge crew simulator — v0.08**

3–12 players connect via web browsers on a local network, each taking a distinct role aboard a starship. No single player can succeed alone — the fun comes from communication, coordination, and creative problem-solving under pressure.

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

1. The server prints a URL like `http://192.168.1.100:8666/`
2. Share this URL with your crew
3. Everyone opens it in their browser and clicks PLAY
4. Enter a callsign, choose roles, select a mission, launch

---

## Roles (13 Stations)

| Role | Summary |
|------|---------|
| **Captain** | Overview of all systems. Sets alert level, maintains the log, authorises nuclear launches. |
| **Helm** | Steers the ship. Speed, heading, evasive manoeuvres, docking approach. |
| **Weapons** | Targets enemies. Fires beams and torpedoes. Manages shield focus. |
| **Engineering** | Distributes power across nine systems. Dispatches repair teams. |
| **Science** | Scans contacts. Four scan modes (EM, GRAV, BIO, SUB). Triangulates signals. |
| **Medical** | Treats individual crew injuries. Triage, surgery, quarantine. |
| **Security** | Internal defence. Marine teams, door control, boarding response. |
| **Communications** | Decodes signals, manages faction diplomacy, hails contacts. |
| **Flight Ops** | Launches and directs drones — scout, combat, rescue, survey, ECM. |
| **Electronic Warfare** | Jams enemy sensors, runs intrusion attacks, deploys countermeasures. |
| **Operations** | Analyses threats, coordinates crew, tracks mission objectives. |
| **Hazard Control** | Manages fires, atmosphere, radiation, and structural integrity. |
| **Quartermaster** | Manages resources, supplies, rationing, and trade. |

---

## Ship Classes (7)

| Class | Hull | Crew | Notes |
|-------|------|------|-------|
| Scout | 60 | 3–4 | Fast and light |
| Corvette | 90 | 4–6 | Good for new crews |
| Frigate | 120 | 6–9 | Default balanced class |
| Medical Ship | 100 | 5–8 | Enhanced medical capacity |
| Cruiser | 180 | 8–11 | Heavy combat |
| Carrier | 200 | 7–12 | Expanded flight deck |
| Battleship | 300 | 10–12 | Maximum firepower |

---

## Documentation

- **Manual**: `/manual/` — full station guides, mechanics, shortcuts
- **FAQ**: `/faq/` — common questions answered
- **About**: `/about/` — version history and credits
- **Shortcut Reference**: `/client/site/manual/shortcuts.html` — printable keyboard shortcuts

---

## Game Flow

1. **Lobby** — Players connect, enter callsigns, claim roles, host selects mission + ship class + difficulty
2. **Briefing** — Mission objectives shown with 30-second countdown
3. **Mission** — Stations coordinate in real time; objectives update as goals are met
4. **Debrief** — Per-station stats, awards, key moments, Captain's Replay
5. **Repeat** — Return to lobby for the next mission

---

## Tech Stack

- **Server**: Python / FastAPI / asyncio / WebSockets (10 Hz game loop)
- **Client**: Vanilla HTML5 / Canvas / ES Modules (no framework, no build step)
- **Aesthetic**: Wire-frame vector graphics — Battlezone / DEFCON / Alien ship computer style
- **Tests**: 6,831 passing (pytest + pytest-asyncio)

---

## Running Tests

```bash
python -m pytest
```

---

## License

TBD
