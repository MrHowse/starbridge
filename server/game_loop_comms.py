"""
Comms sub-module for the game loop — v0.06.4 full rewrite.

Signal management, decoding, diplomacy, channel/bandwidth, intel routing,
faction standing, and translation matrices.

Old interface preserved: reset(), tune(), build_comms_state(), serialise(),
deserialise().  New interface added for signal queue, decode, diplomacy.
"""
from __future__ import annotations

import random
from typing import Any

from server.models.comms import (
    BASE_DECODE_SPEED,
    CHANNEL_DEFAULTS,
    DEADLINE_DEMAND,
    DEADLINE_DISTRESS,
    DEADLINE_HAIL,
    DECODE_FACTION_BONUS,
    NPC_REPLY_TEMPLATES,
    PASSIVE_DECODE_MULT,
    PRIORITY_ORDER,
    RESPONSE_TEMPLATES,
    STANDING_EFFECTS,
    Channel,
    FactionStanding,
    Signal,
    TranslationMatrix,
)

# ---------------------------------------------------------------------------
# Legacy constants (kept for backward compat with training missions)
# ---------------------------------------------------------------------------

FACTION_BANDS: dict[str, float] = {
    "imperial": 0.15,
    "rebel":    0.42,
    "alien":    0.71,
    "emergency": 0.90,
    "pirate":   0.08,
    "civilian": 0.55,
    "federation": 0.65,
}
BAND_TOLERANCE: float = 0.05

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_active_frequency: float = 0.15
_signals: list[Signal] = []
_signal_counter: int = 0
_factions: dict[str, FactionStanding] = {}
_channels: list[Channel] = []
_translations: dict[str, TranslationMatrix] = {}
_decoded_factions: set[str] = set()  # factions we've decoded before

# Active decode target
_active_decode_id: str | None = None

# Active dialogues: signal_id → conversation entries
_dialogues: dict[str, list[dict]] = {}

# Pending intel routes (consumed by game_loop for cross-station broadcast)
_pending_intel_routes: list[dict] = []

# Pending standing changes (consumed by game_loop for broadcast)
_pending_standing_changes: list[dict] = []

# Pending NPC responses (consumed by game_loop for broadcast)
_pending_npc_responses: list[dict] = []

# Probe state
_active_probes: dict[str, float] = {}  # target_id → remaining_seconds
PROBE_DURATION: float = 15.0

# Legacy compat
_transmissions: list[dict] = []
_interception_timer: float = 0.0

# Tick counter (set from game_loop)
_tick: int = 0


# ---------------------------------------------------------------------------
# Reset / Init
# ---------------------------------------------------------------------------

def reset() -> None:
    """Clear all comms state. Called at game start."""
    global _active_frequency, _signal_counter, _active_decode_id
    global _interception_timer, _tick
    _active_frequency = 0.15
    _signal_counter = 0
    _active_decode_id = None
    _interception_timer = 0.0
    _tick = 0
    _signals.clear()
    _factions.clear()
    _channels.clear()
    _translations.clear()
    _decoded_factions.clear()
    _dialogues.clear()
    _pending_intel_routes.clear()
    _pending_standing_changes.clear()
    _pending_npc_responses.clear()
    _active_probes.clear()
    _transmissions.clear()

    # Set up default channels
    for name, status, cost in CHANNEL_DEFAULTS:
        _channels.append(Channel(name=name, status=status, bandwidth_cost=cost))

    # Set up default faction standings
    _init_default_factions()


def _init_default_factions() -> None:
    """Create default faction standings."""
    defaults = [
        ("imperial",   "Terran Empire",   10.0),
        ("federation", "Federation",      20.0),
        ("pirate",     "Pirate Clans",   -20.0),
        ("alien",      "Unknown Alien",    0.0),
        ("civilian",   "Civilian",        30.0),
        ("rebel",      "Rebel Alliance",   0.0),
    ]
    for fid, name, standing in defaults:
        _factions[fid] = FactionStanding(
            faction_id=fid, name=name, standing=standing
        )


# ---------------------------------------------------------------------------
# Frequency tuning (legacy + new)
# ---------------------------------------------------------------------------

def tune(frequency: float) -> None:
    """Set the active frequency (0.0–1.0)."""
    global _active_frequency
    _active_frequency = max(0.0, min(1.0, frequency))


def get_tuned_faction() -> str | None:
    """Return the faction name if tuned to a known band, else None."""
    for faction, band in FACTION_BANDS.items():
        if abs(_active_frequency - band) <= BAND_TOLERANCE:
            return faction
    return None


def get_active_frequency() -> float:
    return _active_frequency


# ---------------------------------------------------------------------------
# Signal management
# ---------------------------------------------------------------------------

def _next_signal_id() -> str:
    global _signal_counter
    _signal_counter += 1
    return f"sig_{_signal_counter}"


def add_signal(
    source: str = "unknown",
    source_name: str = "Unknown",
    frequency: float = 0.5,
    signal_type: str = "broadcast",
    priority: str = "low",
    raw_content: str = "",
    decoded_content: str = "",
    auto_decoded: bool = False,
    requires_decode: bool = True,
    language: str = "standard",
    expires_ticks: int | None = None,
    response_deadline: float | None = None,
    faction: str = "unknown",
    threat_level: str = "unknown",
    intel_value: str = "",
    intel_category: str = "",
) -> Signal:
    """Add a new signal to the queue. Returns the created signal."""
    sig = Signal(
        id=_next_signal_id(),
        source=source,
        source_name=source_name,
        frequency=frequency,
        signal_type=signal_type,
        priority=priority,
        raw_content=raw_content,
        decoded_content=decoded_content if auto_decoded else "",
        auto_decoded=auto_decoded,
        requires_decode=requires_decode,
        language=language,
        arrived_tick=_tick,
        expires_tick=(_tick + expires_ticks) if expires_ticks is not None else None,
        response_deadline=response_deadline,
        faction=faction,
        threat_level=threat_level,
        intel_value=intel_value,
        intel_category=intel_category,
        decode_progress=1.0 if auto_decoded else 0.0,
    )

    # Auto-decoded signals get full content and response options immediately
    if auto_decoded:
        sig.decoded_content = decoded_content or raw_content
        _generate_response_options(sig)

    _signals.append(sig)
    return sig


def get_signals() -> list[Signal]:
    """Return signals sorted by priority."""
    return sorted(
        [s for s in _signals if not s.dismissed],
        key=lambda s: PRIORITY_ORDER.get(s.priority, 99),
    )


def get_signal(signal_id: str) -> Signal | None:
    """Find a signal by ID."""
    for s in _signals:
        if s.id == signal_id:
            return s
    return None


def dismiss_signal(signal_id: str) -> bool:
    """Mark a signal as dismissed. Returns True if found."""
    sig = get_signal(signal_id)
    if sig is None:
        return False
    sig.dismissed = True
    return True


def get_active_signal_count() -> int:
    """Count non-dismissed, non-expired signals."""
    return sum(1 for s in _signals if not s.dismissed)


# ---------------------------------------------------------------------------
# Decode mechanics
# ---------------------------------------------------------------------------

def start_decode(signal_id: str) -> bool:
    """Start actively decoding a signal. Only one at a time."""
    global _active_decode_id
    sig = get_signal(signal_id)
    if sig is None or not sig.requires_decode or sig.decode_progress >= 1.0:
        return False

    # Deactivate previous
    if _active_decode_id is not None:
        prev = get_signal(_active_decode_id)
        if prev is not None:
            prev.decoding_active = False

    sig.decoding_active = True
    _active_decode_id = signal_id
    return True


def _tick_decode(dt: float, crew_factor: float, bandwidth_quality: float) -> list[dict]:
    """Advance decode progress on all signals. Returns decode-complete events."""
    events: list[dict] = []

    for sig in _signals:
        if sig.dismissed or not sig.requires_decode or sig.decode_progress >= 1.0:
            continue

        # Calculate decode rate
        is_active = sig.decoding_active and sig.id == _active_decode_id
        base_rate = BASE_DECODE_SPEED
        rate = base_rate * crew_factor * bandwidth_quality

        # Bonuses
        if sig.faction in _decoded_factions:
            rate *= DECODE_FACTION_BONUS

        if not is_active:
            rate *= PASSIVE_DECODE_MULT

        sig.decode_progress = min(1.0, sig.decode_progress + rate * dt)

        # Update decoded content based on progress
        _update_decoded_content(sig)

        # Check completion
        if sig.decode_progress >= 1.0:
            sig.decoded_content = sig.raw_content  # Full reveal
            _decoded_factions.add(sig.faction)
            _generate_response_options(sig)

            # Advance translation if alien
            if sig.language in ("alien_alpha", "alien_beta"):
                _advance_translation(sig.language, 0.1)

            events.append({
                "signal_id": sig.id,
                "source_name": sig.source_name,
                "signal_type": sig.signal_type,
                "faction": sig.faction,
                "intel_value": sig.intel_value,
            })

    return events


def _update_decoded_content(sig: Signal) -> None:
    """Reveal portions of raw_content based on decode_progress."""
    if sig.auto_decoded or not sig.raw_content:
        return

    raw = sig.raw_content
    progress = sig.decode_progress
    length = len(raw)

    if progress <= 0:
        sig.decoded_content = ""
        return

    # Reveal characters progressively, keeping word structure
    reveal_count = int(length * progress)
    revealed = []
    for i, ch in enumerate(raw):
        if i < reveal_count or ch == " " or ch in ".,!?—":
            revealed.append(ch)
        else:
            revealed.append("-")
    sig.decoded_content = "".join(revealed)


def _advance_translation(language: str, amount: float) -> None:
    """Advance a translation matrix."""
    if language not in _translations:
        _translations[language] = TranslationMatrix(language=language)
    _translations[language].advance(amount)
    _translations[language].words_decoded += 1


# ---------------------------------------------------------------------------
# Response / Diplomacy
# ---------------------------------------------------------------------------

def _generate_response_options(sig: Signal) -> None:
    """Populate response options for a decoded signal."""
    key = (sig.signal_type, sig.threat_level)
    templates = RESPONSE_TEMPLATES.get(key, [])

    # Also try with "unknown" threat level as fallback
    if not templates:
        key = (sig.signal_type, "unknown")
        templates = RESPONSE_TEMPLATES.get(key, [])

    sig.response_options = list(templates)


def respond_to_signal(signal_id: str, response_id: str) -> dict | None:
    """Apply a diplomatic response to a signal.

    Returns the NPC reply dict, or None if invalid.
    """
    sig = get_signal(signal_id)
    if sig is None or sig.responded:
        return None

    # Find the response option
    option = None
    for opt in sig.response_options:
        if opt["id"] == response_id:
            option = opt
            break
    if option is None:
        return None

    sig.responded = True
    sig.response_deadline = None

    # Apply standing effect
    effect_key = option.get("standing_effect", "")
    if effect_key and effect_key in STANDING_EFFECTS:
        amount = STANDING_EFFECTS[effect_key]
        _adjust_standing(sig.faction, amount, effect_key)

    # Generate NPC reply
    reply_key = (sig.signal_type, response_id)
    templates = NPC_REPLY_TEMPLATES.get(reply_key, ["...acknowledged..."])
    reply_text = random.choice(templates)

    reply = {
        "signal_id": sig.id,
        "source_name": sig.source_name,
        "faction": sig.faction,
        "response_id": response_id,
        "response_text": reply_text,
    }

    # Add to dialogue
    if sig.id not in _dialogues:
        _dialogues[sig.id] = []
    _dialogues[sig.id].append({
        "speaker": "them",
        "text": sig.decoded_content or sig.raw_content,
    })
    _dialogues[sig.id].append({
        "speaker": "you",
        "text": option["label"],
    })
    _dialogues[sig.id].append({
        "speaker": "them",
        "text": reply_text,
    })

    _pending_npc_responses.append(reply)
    return reply


def _adjust_standing(faction_id: str, amount: float, reason: str) -> None:
    """Adjust faction standing and record the change."""
    if faction_id not in _factions:
        _factions[faction_id] = FactionStanding(
            faction_id=faction_id, name=faction_id.title()
        )
    old_disposition = _factions[faction_id].disposition
    _factions[faction_id].adjust(amount, reason)
    new_disposition = _factions[faction_id].disposition

    _pending_standing_changes.append({
        "faction_id": faction_id,
        "amount": amount,
        "reason": reason,
        "new_standing": _factions[faction_id].standing,
        "old_disposition": old_disposition,
        "new_disposition": new_disposition,
    })


def get_faction_standing(faction_id: str) -> FactionStanding | None:
    """Get standing for a faction."""
    return _factions.get(faction_id)


def get_all_standings() -> dict[str, FactionStanding]:
    """Return all faction standings."""
    return dict(_factions)


# ---------------------------------------------------------------------------
# Channel / Bandwidth
# ---------------------------------------------------------------------------

def set_channel_status(channel_name: str, status: str) -> bool:
    """Set a channel's status. Emergency cannot be closed. Returns success."""
    if status not in ("open", "monitored", "closed"):
        return False
    for ch in _channels:
        if ch.name == channel_name:
            if ch.name == "emergency" and status == "closed":
                return False  # Emergency always open
            ch.status = status
            return True
    return False


def get_bandwidth_usage() -> float:
    """Total bandwidth consumed by open/monitored channels (0–100+)."""
    return sum(ch.active_cost for ch in _channels)


def get_bandwidth_quality() -> float:
    """Signal quality multiplier based on bandwidth usage.

    <=100% → 1.0; over 100% degrades linearly down to 0.3.
    """
    usage = get_bandwidth_usage()
    if usage <= 100.0:
        return 1.0
    overage = usage - 100.0
    return max(0.3, 1.0 - overage / 100.0)


def get_channels() -> list[Channel]:
    """Return all channels."""
    return list(_channels)


# ---------------------------------------------------------------------------
# Intel routing
# ---------------------------------------------------------------------------

def route_intel(signal_id: str, target_station: str) -> bool:
    """Route decoded intelligence from a signal to another station.

    Returns True if successful.
    """
    sig = get_signal(signal_id)
    if sig is None or sig.decode_progress < 1.0:
        return False

    _pending_intel_routes.append({
        "signal_id": sig.id,
        "source_name": sig.source_name,
        "intel_value": sig.intel_value,
        "intel_category": sig.intel_category,
        "target_station": target_station,
        "faction": sig.faction,
        "decoded_content": sig.decoded_content,
    })
    return True


def pop_pending_intel_routes() -> list[dict]:
    """Drain and return pending intel routes."""
    routes = list(_pending_intel_routes)
    _pending_intel_routes.clear()
    return routes


def pop_pending_standing_changes() -> list[dict]:
    """Drain and return pending standing changes."""
    changes = list(_pending_standing_changes)
    _pending_standing_changes.clear()
    return changes


def pop_pending_npc_responses() -> list[dict]:
    """Drain and return pending NPC responses."""
    responses = list(_pending_npc_responses)
    _pending_npc_responses.clear()
    return responses


# ---------------------------------------------------------------------------
# Hailing (outbound)
# ---------------------------------------------------------------------------

def hail(contact_id: str, message_type: str, frequency: float | None = None,
         hail_type: str = "identify") -> Signal | None:
    """Send an outbound hail to a contact.

    Creates a signal representing the expected response (pending).
    Returns the created signal, or None if cannot hail.
    """
    freq = frequency if frequency is not None else _active_frequency
    faction = get_tuned_faction() if frequency is None else _faction_for_frequency(freq)

    # Determine response content based on hail type
    reply_key = ("hail", hail_type)
    templates = NPC_REPLY_TEMPLATES.get(reply_key, [])
    if not templates:
        # Fall back to generic
        reply_key = ("hail", "comply")
        templates = NPC_REPLY_TEMPLATES.get(reply_key, ["...no response..."])

    # Create a pending response signal (arrives after delay)
    sig = add_signal(
        source=contact_id,
        source_name=contact_id.replace("_", " ").title(),
        frequency=freq,
        signal_type="hail",
        priority="medium",
        raw_content=random.choice(templates),
        decoded_content="",
        auto_decoded=True,
        requires_decode=False,
        faction=faction or "unknown",
        threat_level="unknown",
        response_deadline=DEADLINE_HAIL,
    )

    # Also add to legacy transmissions log
    _add_transmission(
        f"HAILING {contact_id} [{hail_type.upper()}]", "outgoing"
    )

    return sig


def _faction_for_frequency(freq: float) -> str | None:
    """Find faction for a given frequency."""
    for faction, band in FACTION_BANDS.items():
        if abs(freq - band) <= BAND_TOLERANCE:
            return faction
    return None


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------

def start_probe(target_id: str) -> bool:
    """Start probing a target's communications. Takes 15s."""
    if target_id in _active_probes:
        return False
    _active_probes[target_id] = PROBE_DURATION
    return True


def _tick_probes(dt: float) -> list[dict]:
    """Advance probe timers. Returns completed probe results."""
    events: list[dict] = []
    completed: list[str] = []

    for target_id, remaining in _active_probes.items():
        remaining -= dt
        _active_probes[target_id] = remaining
        if remaining <= 0:
            completed.append(target_id)
            events.append({
                "target_id": target_id,
                "frequencies_detected": [
                    round(random.uniform(0.1, 0.9), 3)
                    for _ in range(random.randint(1, 3))
                ],
                "faction_hint": random.choice(
                    ["imperial", "rebel", "pirate", "civilian", "unknown"]
                ),
                "comm_active": random.choice([True, False]),
            })

    for tid in completed:
        del _active_probes[tid]

    return events


# ---------------------------------------------------------------------------
# Distress assessment
# ---------------------------------------------------------------------------

def assess_distress(signal_id: str) -> dict | None:
    """Assess a distress signal for authenticity.

    Returns assessment dict or None if invalid.
    """
    sig = get_signal(signal_id)
    if sig is None or sig.signal_type != "distress":
        return None

    # Simple authenticity scoring based on signal characteristics
    authenticity = 0.5  # base

    # Automated signals are less likely genuine
    if "automated" in sig.raw_content.lower() or "beacon" in sig.raw_content.lower():
        authenticity -= 0.2

    # Known friendly faction more likely genuine
    fs = _factions.get(sig.faction)
    if fs and fs.standing > 20:
        authenticity += 0.2
    elif fs and fs.standing < -20:
        authenticity -= 0.2

    # Emergency frequency is standard
    if abs(sig.frequency - FACTION_BANDS.get("emergency", 0.9)) <= BAND_TOLERANCE:
        authenticity += 0.1

    authenticity = max(0.0, min(1.0, authenticity))

    assessment = {
        "signal_id": sig.id,
        "authenticity": round(authenticity, 2),
        "risk_level": (
            "low" if authenticity > 0.7
            else "medium" if authenticity > 0.4
            else "high"
        ),
        "factors": [],
    }

    if authenticity > 0.7:
        assessment["factors"].append("Signal characteristics consistent with genuine distress.")
    if authenticity < 0.4:
        assessment["factors"].append("Signal anomalies detected — possible trap.")
    if fs and fs.standing > 20:
        assessment["factors"].append(f"{sig.faction.title()} is a known ally.")
    if fs and fs.standing < -20:
        assessment["factors"].append(f"{sig.faction.title()} is hostile — exercise caution.")

    return assessment


# ---------------------------------------------------------------------------
# Per-tick update
# ---------------------------------------------------------------------------

def set_tick(tick: int) -> None:
    """Update the current tick counter."""
    global _tick
    _tick = tick


def tick_comms(dt: float, crew_factor: float = 1.0) -> list[dict]:
    """Advance all comms state. Returns legacy NPC response dicts."""
    global _interception_timer

    bandwidth_quality = get_bandwidth_quality()

    # 1. Tick decode progress
    decode_events = _tick_decode(dt, crew_factor, bandwidth_quality)

    # 2. Tick response deadlines
    expired_events = _tick_deadlines(dt)

    # 3. Tick signal expiry
    _tick_expiry()

    # 4. Tick probes
    probe_events = _tick_probes(dt)

    # 5. Legacy passive interception (kept for backward compat)
    faction = get_tuned_faction()
    if faction in ("imperial", "rebel"):
        _interception_timer += dt
        if _interception_timer >= 20.0:
            _interception_timer = 0.0
            _intercept_fragment(faction)

    # Return legacy-compatible responses (for existing game_loop broadcast)
    return pop_pending_npc_responses()


def _tick_deadlines(dt: float) -> list[dict]:
    """Tick response deadlines. Returns expired signal events."""
    events: list[dict] = []

    for sig in _signals:
        if sig.dismissed or sig.responded:
            continue
        if sig.response_deadline is not None:
            sig.response_deadline -= dt
            if sig.response_deadline <= 0 and not sig.responded:
                sig.response_deadline = 0.0
                # Apply consequence for ignoring
                effect = STANDING_EFFECTS.get("ignore_hail", -5.0)
                if sig.signal_type == "distress":
                    effect = STANDING_EFFECTS.get("ignore_distress", -3.0)
                _adjust_standing(sig.faction, effect, f"ignored_{sig.signal_type}")

                events.append({
                    "signal_id": sig.id,
                    "source_name": sig.source_name,
                    "signal_type": sig.signal_type,
                    "consequence": f"Standing with {sig.faction} decreased",
                })

                sig.responded = True  # Mark as handled (negatively)

    return events


def _tick_expiry() -> None:
    """Remove signals that have expired."""
    to_remove: list[str] = []
    for sig in _signals:
        if sig.expires_tick is not None and _tick >= sig.expires_tick:
            to_remove.append(sig.id)
    _signals[:] = [s for s in _signals if s.id not in set(to_remove)]


# ---------------------------------------------------------------------------
# Legacy helpers (kept for backward compat)
# ---------------------------------------------------------------------------

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
    """Add a transmission to the legacy log (keeps last 20)."""
    _transmissions.append({"text": text, "type": transmission_type})
    if len(_transmissions) > 20:
        _transmissions.pop(0)


# ---------------------------------------------------------------------------
# State builder
# ---------------------------------------------------------------------------

def build_comms_state(world: object | None = None) -> dict:
    """Serialise current comms state for broadcast to comms station."""
    # Sorted signal queue (non-dismissed only)
    signal_dicts = [s.to_dict() for s in get_signals()]

    # Channel status
    channel_dicts = [ch.to_dict() for ch in _channels]

    # Faction standings
    faction_dicts = {fid: fs.to_dict() for fid, fs in _factions.items()}

    # Translation progress
    translation_dicts = {
        lang: tm.to_dict() for lang, tm in _translations.items()
    }

    # Active dialogue
    dialogue_data = dict(_dialogues)

    state: dict[str, Any] = {
        "active_frequency": round(_active_frequency, 3),
        "tuned_faction": get_tuned_faction(),
        "signals": signal_dicts,
        "signal_count": get_active_signal_count(),
        "channels": channel_dicts,
        "bandwidth_usage": round(get_bandwidth_usage(), 1),
        "bandwidth_quality": round(get_bandwidth_quality(), 3),
        "factions": faction_dicts,
        "translations": translation_dicts,
        "active_decode_id": _active_decode_id,
        "dialogues": dialogue_data,
        "active_probes": {
            tid: round(rem, 1) for tid, rem in _active_probes.items()
        },
        # Legacy fields
        "transmissions": list(_transmissions),
        "pending_hails": 0,
    }

    # Include detected creatures (legacy compat)
    creatures_data: list[dict] = []
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


# ---------------------------------------------------------------------------
# Serialise / Deserialise
# ---------------------------------------------------------------------------

def serialise() -> dict:
    """Serialise full comms state for save system."""
    return {
        "active_frequency": _active_frequency,
        "signal_counter": _signal_counter,
        "signals": [s.to_dict() for s in _signals],
        "factions": {fid: fs.to_dict() for fid, fs in _factions.items()},
        "channels": [ch.to_dict() for ch in _channels],
        "translations": {
            lang: tm.to_dict() for lang, tm in _translations.items()
        },
        "decoded_factions": list(_decoded_factions),
        "active_decode_id": _active_decode_id,
        "dialogues": dict(_dialogues),
        "transmissions": list(_transmissions),
        "interception_timer": _interception_timer,
        "active_probes": dict(_active_probes),
    }


def deserialise(data: dict) -> None:
    """Restore comms state from save."""
    global _active_frequency, _signal_counter, _active_decode_id
    global _interception_timer

    _active_frequency = data.get("active_frequency", 0.15)
    _signal_counter = data.get("signal_counter", 0)
    _active_decode_id = data.get("active_decode_id")
    _interception_timer = data.get("interception_timer", 0.0)

    _signals.clear()
    for sd in data.get("signals", []):
        _signals.append(Signal.from_dict(sd))

    _factions.clear()
    for fid, fd in data.get("factions", {}).items():
        _factions[fid] = FactionStanding.from_dict(fd)

    _channels.clear()
    for cd in data.get("channels", []):
        _channels.append(Channel.from_dict(cd))

    _translations.clear()
    for lang, td in data.get("translations", {}).items():
        _translations[lang] = TranslationMatrix.from_dict(td)

    _decoded_factions.clear()
    _decoded_factions.update(data.get("decoded_factions", []))

    _dialogues.clear()
    _dialogues.update(data.get("dialogues", {}))

    _transmissions.clear()
    _transmissions.extend(data.get("transmissions", []))

    _active_probes.clear()
    _active_probes.update(data.get("active_probes", {}))
