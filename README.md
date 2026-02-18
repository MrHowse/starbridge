# STARBRIDGE

**Cooperative multiplayer bridge crew simulator.**

5-6 players connect via web browsers on a local network, each taking a distinct role aboard a starship. No single player can succeed alone — the fun comes from communication, coordination, and creative problem-solving under pressure.

Inspired by [Artemis Spaceship Bridge Simulator](https://www.artemisspaceshipbridge.com/), rebuilt as a modern web application with zero setup friction.

## Quick Start

### Requirements

- Python 3.12+
- A local network (WiFi or wired)
- Modern web browsers (Chrome, Firefox, Safari, Edge)

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

1. The server prints a URL like `http://192.168.1.100:8000/client/lobby/`
2. Share this URL with your crew
3. Everyone opens it in their browser
4. Choose roles, launch the mission, and save the galaxy

## Roles

| Role | Summary |
|------|---------|
| **Captain** | Overview of all systems. Sets alert level. Makes decisions. Controls nothing directly. |
| **Helm** | Steers the ship. Manages speed. Executes manoeuvres. |
| **Weapons** | Targets enemies. Fires beams and torpedoes. Manages shields. |
| **Engineering** | Distributes power across systems. Repairs damage. |
| **Science** | Scans contacts. Identifies threats and weaknesses. Detects anomalies. |

## Project Status

**Current phase**: Phase 1 — Foundation (Server, WebSocket, Lobby)

See `docs/` for architecture documentation and `.ai/STATE.md` for current build status.

## Tech Stack

- **Server**: Python / FastAPI / WebSockets
- **Client**: Vanilla HTML5 / Canvas / JavaScript (no framework, no build step)
- **Aesthetic**: Wire-frame vector graphics (Battlezone / DEFCON / Alien ship computer style)

## License

TBD
