"""
Comms sub-module for the game loop.

Manages the frequency scanner state, hailing queue with delayed NPC responses,
and the intercepted transmission log.

Faction frequency bands (normalised 0.0–1.0):
  imperial  0.15   Military channels
  rebel     0.42   Resistance channels
  alien     0.71   Unknown / alien signal
  emergency 0.90   Distress frequency
"""
from __future__ import annotations

import random

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FACTION_BANDS: dict[str, float] = {
    "imperial": 0.15,
    "rebel":    0.42,
    "alien":    0.71,
    "emergency": 0.90,
}
BAND_TOLERANCE: float = 0.05   # ±tolerance to be "tuned" to a band
HAIL_RESPONSE_DELAY: float = 2.0  # seconds before NPC responds

# NPC response templates by (faction, message_type)
_NPC_RESPONSES: dict[tuple[str, str], list[str]] = {
    ("imperial", "negotiate"): [
        "Imperial Command acknowledges. Stand by for orders.",
        "Halt and identify. State your business.",
    ],
    ("imperial", "demand"): [
        "You are in restricted space. Withdraw immediately.",
        "Warning: comply or be fired upon.",
    ],
    ("imperial", "bluff"): [
        "We have no record of your vessel. Transmitting ID request.",
        "Identity unverified. Security protocol engaged.",
    ],
    ("rebel", "negotiate"): [
        "Copy that. What's your cargo and destination?",
        "We're listening. Keep it brief.",
    ],
    ("rebel", "demand"): [
        "We don't take orders from strangers. Back off.",
        "Stand down. We outnumber you.",
    ],
    ("rebel", "bluff"): [
        "Hmm. Not in the network. Who sent you?",
        "Credentials don't check out. Who are you really?",
    ],
    ("alien", "negotiate"): [
        "...[interference]... signal... acknowledged...",
        "Resonance pattern received. Attempting translation.",
    ],
    ("alien", "demand"): [
        "...[carrier wave only]...",
        "Pattern unknown. Cannot resolve intent.",
    ],
    ("alien", "bluff"): [
        "...[sustained tone]...",
        "...[frequency shift detected]...",
    ],
    ("emergency", "negotiate"): [
        "Mayday mayday — hull breach on decks 3 and 4. Requesting immediate assistance.",
        "We're venting atmosphere. Please, anyone — respond!",
    ],
    ("emergency", "demand"): [
        "We can't respond to demands right now — we're dying out here!",
        "Please — no time for this — we need help!",
    ],
    ("emergency", "bluff"): [
        "I don't care who you are, just get us out of here!",
        "There's no time — send rescue now!",
    ],
}

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_active_frequency: float = 0.15
_pending_hails: list[dict] = []    # {"faction", "message_type", "timer"}
_transmissions: list[dict] = []    # log of received transmissions (last 10)
_interception_timer: float = 0.0   # timer for passive interception


def reset() -> None:
    """Clear all comms state. Called at game start."""
    global _active_frequency, _interception_timer
    _active_frequency = 0.15
    _interception_timer = 0.0
    _pending_hails.clear()
    _transmissions.clear()


# ---------------------------------------------------------------------------
# Frequency tuning
# ---------------------------------------------------------------------------


def tune(frequency: float) -> None:
    """Set the active frequency (0.0–1.0)."""
    global _active_frequency
    _active_frequency = max(0.0, min(1.0, frequency))


def get_tuned_faction() -> str | None:
    """Return the faction name if the scanner is tuned to a known band, else None."""
    for faction, band in FACTION_BANDS.items():
        if abs(_active_frequency - band) <= BAND_TOLERANCE:
            return faction
    return None


# ---------------------------------------------------------------------------
# Hailing
# ---------------------------------------------------------------------------


def hail(contact_id: str, message_type: str) -> None:
    """Queue a hail for the currently tuned faction (if any).

    contact_id is logged but NPC response uses the tuned faction band.
    """
    faction = get_tuned_faction()
    if faction is None:
        return
    _pending_hails.append({
        "faction": faction,
        "contact_id": contact_id,
        "message_type": message_type,
        "timer": HAIL_RESPONSE_DELAY,
    })


# ---------------------------------------------------------------------------
# Per-tick update
# ---------------------------------------------------------------------------


def tick_comms(dt: float) -> list[dict]:
    """Advance hail timers and passive interception.

    Returns a list of NPC response dicts ready to broadcast this tick.
    """
    global _interception_timer
    responses: list[dict] = []

    # Advance hail timers
    still_pending: list[dict] = []
    for hail_state in _pending_hails:
        hail_state["timer"] -= dt
        if hail_state["timer"] <= 0.0:
            faction = hail_state["faction"]
            msg_type = hail_state["message_type"]
            templates = _NPC_RESPONSES.get((faction, msg_type), ["...no response..."])
            text = random.choice(templates)
            response = {
                "faction": faction,
                "contact_id": hail_state["contact_id"],
                "message_type": msg_type,
                "response_text": text,
            }
            responses.append(response)
            _add_transmission(f"[{faction.upper()}] {text}", "incoming")
        else:
            still_pending.append(hail_state)

    _pending_hails[:] = still_pending

    # Passive interception: receive random fragments on tuned faction band
    faction = get_tuned_faction()
    if faction in ("imperial", "rebel"):
        _interception_timer += dt
        if _interception_timer >= 20.0:
            _interception_timer = 0.0
            _intercept_fragment(faction)

    return responses


def _intercept_fragment(faction: str) -> None:
    """Add a random intercepted fragment to the transmission log."""
    fragments = {
        "imperial": [
            "ENC: 7A-3F-12... patrol route updated",
            "ENC: ALPHA-DELTA-7... asset confirmed",
            "ENC: 3B-9C... reinforcements inbound",
        ],
        "rebel": [
            "ENC: rendezvous point... grid 7-7",
            "ENC: shipment delayed... hold position",
            "ENC: asset compromised... abort protocol",
        ],
    }
    text = random.choice(fragments.get(faction, ["ENC: ...static..."]))
    _add_transmission(text, "intercepted")


def _add_transmission(text: str, transmission_type: str) -> None:
    """Add a transmission to the log (keeps last 10)."""
    _transmissions.append({"text": text, "type": transmission_type})
    if len(_transmissions) > 10:
        _transmissions.pop(0)


# ---------------------------------------------------------------------------
# State builder
# ---------------------------------------------------------------------------


def build_comms_state(world: object | None = None) -> dict:
    """Serialise current comms state for broadcast."""
    state: dict = {
        "active_frequency": round(_active_frequency, 3),
        "tuned_faction": get_tuned_faction(),
        "transmissions": list(_transmissions),
        "pending_hails": len(_pending_hails),
    }
    # Include detected creatures that can be communicated with.
    creatures_data = []
    if world is not None:
        from server.utils.math_helpers import distance
        ship = world.ship  # type: ignore[union-attr]
        for creature in world.creatures:  # type: ignore[union-attr]
            if not creature.detected or creature.hull <= 0:
                continue
            dist = distance(ship.x, ship.y, creature.x, creature.y)
            creatures_data.append({
                "id": creature.id,
                "creature_type": creature.creature_type,
                "behaviour_state": creature.behaviour_state,
                "distance": round(dist, 1),
                "communication_progress": round(creature.communication_progress, 1),
            })
    state["creatures"] = creatures_data
    return state


def serialise() -> dict:
    return {
        "active_frequency": _active_frequency,
        "pending_hails": list(_pending_hails),
        "transmissions": list(_transmissions),
        "interception_timer": _interception_timer,
    }


def deserialise(data: dict) -> None:
    global _active_frequency, _interception_timer
    _active_frequency    = data.get("active_frequency", 0.0)
    _interception_timer  = data.get("interception_timer", 0.0)
    _pending_hails.clear()
    _pending_hails.extend(data.get("pending_hails", []))
    _transmissions.clear()
    _transmissions.extend(data.get("transmissions", []))
