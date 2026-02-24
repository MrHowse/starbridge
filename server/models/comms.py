"""Comms station data models.

Signal, FactionStanding, Channel, and TranslationMatrix dataclasses
for the v0.06.4 Comms Station Overhaul.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SIGNAL_TYPES = (
    "hail", "distress", "broadcast", "demand", "encrypted",
    "automated", "jamming_noise", "data_burst",
)

PRIORITIES = ("critical", "high", "medium", "low")
PRIORITY_ORDER = {p: i for i, p in enumerate(PRIORITIES)}

FACTIONS = (
    "imperial", "federation", "pirate", "alien", "civilian", "unknown",
)

DISPOSITIONS = (
    "allied", "friendly", "neutral", "suspicious", "hostile", "at_war",
)

LANGUAGES = ("standard", "alien_alpha", "alien_beta", "coded", "unknown")

THREAT_LEVELS = ("friendly", "neutral", "hostile", "unknown")

# Channel definitions: (name, default_status, bandwidth_cost_percent)
CHANNEL_DEFAULTS: list[tuple[str, str, float]] = [
    ("emergency",    "open",      5.0),
    ("standard",     "open",     15.0),
    ("fleet",        "closed",   20.0),
    ("intelligence", "open",     25.0),
    ("broadcast",    "monitored", 10.0),
    ("science",      "closed",   15.0),
    ("internal",     "open",     10.0),
]

CHANNEL_STATUSES = ("open", "monitored", "closed")

# Standing thresholds → disposition
STANDING_THRESHOLDS: list[tuple[float, str]] = [
    (75.0,  "allied"),
    (30.0,  "friendly"),
    (0.0,   "neutral"),
    (-30.0, "suspicious"),
    (-75.0, "hostile"),
]
# Below -75 → "at_war"

# Standing effects for diplomatic actions
STANDING_EFFECTS: dict[str, float] = {
    "respond_promptly":        +2.0,
    "ignore_hail":             -5.0,
    "help_distress":          +10.0,
    "ignore_distress":         -3.0,
    "honest_identify":         +3.0,
    "deception_caught":       -10.0,
    "comply_demand":           +5.0,
    "comply_demand_ally_cost": -2.0,
    "refuse_aggressive":       -5.0,
    "refuse_aggressive_rival": +2.0,
    "successful_negotiation":  +5.0,
    "attack_after_negotiate": -20.0,
    "rescue_civilian":         +5.0,
    "fire_on_civilian":       -30.0,
    "cease_fire_agreed":       +3.0,
}

# Decode speed constants
BASE_DECODE_SPEED: float = 0.05      # per second at full crew/bandwidth
PASSIVE_DECODE_MULT: float = 0.25    # passive decode = 25% of active
DECODE_EW_BONUS: float = 1.3         # +30% if EW scanning source
DECODE_SCIENCE_BONUS: float = 1.2    # +20% if Science scanned source
DECODE_FACTION_BONUS: float = 1.15   # +15% if same faction decoded before

# Response deadline defaults (seconds)
DEADLINE_HAIL: float = 60.0
DEADLINE_DISTRESS: float = 90.0
DEADLINE_DEMAND: float = 45.0

# Comms contact constants
POSITION_ACCURACIES = ("exact", "approximate", "region")
ENTITY_TYPES = (
    "ship", "station", "hazard", "convoy", "debris",
    "anomaly", "fleet", "unknown",
)
CONFIDENCE_LEVELS = ("confirmed", "probable", "unverified", "rumour")
CONTACT_THREAT_LEVELS = (
    "friendly", "neutral", "hostile", "unknown", "distress",
)
# Staleness threshold (seconds) before confidence downgrades
STALENESS_DOWNGRADE_THRESHOLD: float = 120.0
# Default contact expiry (seconds) — overridden per source type
DEFAULT_CONTACT_EXPIRY_TICKS: int = 3000  # 300s at 10 Hz

# Decode progress thresholds for progressive contact creation
DECODE_CONTACT_THRESHOLD: float = 0.25   # contact first appears
DECODE_POSITION_THRESHOLD: float = 0.50  # position narrows
DECODE_DETAIL_THRESHOLD: float = 0.75    # details filled in
DECODE_FINAL_THRESHOLD: float = 1.0      # full intelligence

# Uncertainty radius by decode progress
UNCERTAINTY_RADIUS_25: float = 20000.0   # very large circle
UNCERTAINTY_RADIUS_50: float = 10000.0   # moderate
UNCERTAINTY_RADIUS_75: float = 5000.0    # narrowing
UNCERTAINTY_RADIUS_100: float = 0.0      # exact

# Source types that generate contacts
CONTACT_SOURCE_DISTRESS = "distress_decode"
CONTACT_SOURCE_INTERCEPT = "enemy_intercept"
CONTACT_SOURCE_NAVIGATION = "navigation_broadcast"
CONTACT_SOURCE_FLEET = "fleet_movement"
CONTACT_SOURCE_CIVILIAN = "civilian_hail"
CONTACT_SOURCE_STATION = "station_broadcast"
CONTACT_SOURCE_TRAP = "trap_signal"
CONTACT_SOURCE_DATA_BURST = "data_burst"


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    """A communication signal received or intercepted by the ship."""

    id: str
    source: str                     # Entity ID or "unknown"
    source_name: str                # "ISS Valiant", "Unknown vessel"
    frequency: float                # 0.0–1.0 spectrum position
    signal_type: str                # One of SIGNAL_TYPES
    priority: str                   # One of PRIORITIES

    # Content
    raw_content: str                # Garbled/encoded version
    decoded_content: str            # Clean version (revealed progressively)
    decode_progress: float = 0.0    # 0.0–1.0
    auto_decoded: bool = False      # True if standard frequency/protocol
    requires_decode: bool = True    # True if encrypted or degraded
    language: str = "standard"      # One of LANGUAGES

    # Timing
    arrived_tick: int = 0
    expires_tick: int | None = None
    responded: bool = False
    response_deadline: float | None = None  # seconds remaining

    # Metadata
    faction: str = "unknown"
    threat_level: str = "unknown"
    intel_value: str = ""           # Description of intel contained
    intel_category: str = ""        # "tactical", "navigation", "technical",
                                    # "combat", "medical", or ""

    # Decode state
    decoding_active: bool = False   # True if Comms is actively decoding

    # Diplomacy
    response_options: list[dict] = field(default_factory=list)
    dismissed: bool = False

    # Location data for contact generation (optional)
    location_data: dict | None = None  # {type, position, radius, entity_ref}

    def to_dict(self) -> dict:
        """Serialise for broadcast or save."""
        return {
            "id": self.id,
            "source": self.source,
            "source_name": self.source_name,
            "frequency": round(self.frequency, 3),
            "signal_type": self.signal_type,
            "priority": self.priority,
            "raw_content": self.raw_content,
            "decoded_content": self.decoded_content,
            "decode_progress": round(self.decode_progress, 3),
            "auto_decoded": self.auto_decoded,
            "requires_decode": self.requires_decode,
            "language": self.language,
            "arrived_tick": self.arrived_tick,
            "expires_tick": self.expires_tick,
            "responded": self.responded,
            "response_deadline": (
                round(self.response_deadline, 1)
                if self.response_deadline is not None else None
            ),
            "faction": self.faction,
            "threat_level": self.threat_level,
            "intel_value": self.intel_value,
            "intel_category": self.intel_category,
            "decoding_active": self.decoding_active,
            "response_options": self.response_options,
            "dismissed": self.dismissed,
            "location_data": self.location_data,
        }

    @staticmethod
    def from_dict(d: dict) -> Signal:
        """Deserialise from save/broadcast dict."""
        return Signal(
            id=d["id"],
            source=d.get("source", "unknown"),
            source_name=d.get("source_name", "Unknown"),
            frequency=d.get("frequency", 0.0),
            signal_type=d.get("signal_type", "broadcast"),
            priority=d.get("priority", "low"),
            raw_content=d.get("raw_content", ""),
            decoded_content=d.get("decoded_content", ""),
            decode_progress=d.get("decode_progress", 0.0),
            auto_decoded=d.get("auto_decoded", False),
            requires_decode=d.get("requires_decode", True),
            language=d.get("language", "standard"),
            arrived_tick=d.get("arrived_tick", 0),
            expires_tick=d.get("expires_tick"),
            responded=d.get("responded", False),
            response_deadline=d.get("response_deadline"),
            faction=d.get("faction", "unknown"),
            threat_level=d.get("threat_level", "unknown"),
            intel_value=d.get("intel_value", ""),
            intel_category=d.get("intel_category", ""),
            decoding_active=d.get("decoding_active", False),
            response_options=d.get("response_options", []),
            dismissed=d.get("dismissed", False),
            location_data=d.get("location_data"),
        )


# ---------------------------------------------------------------------------
# FactionStanding
# ---------------------------------------------------------------------------

def _disposition_from_standing(standing: float) -> str:
    """Derive disposition string from numeric standing."""
    for threshold, disposition in STANDING_THRESHOLDS:
        if standing >= threshold:
            return disposition
    return "at_war"


@dataclass
class FactionStanding:
    """Track the ship's relationship with a faction."""

    faction_id: str
    name: str
    standing: float = 0.0           # -100 to +100
    recent_actions: list[str] = field(default_factory=list)

    @property
    def disposition(self) -> str:
        return _disposition_from_standing(self.standing)

    def adjust(self, amount: float, reason: str) -> None:
        """Adjust standing, clamped to [-100, +100]. Records reason."""
        self.standing = max(-100.0, min(100.0, self.standing + amount))
        self.recent_actions.append(reason)
        # Keep last 10 actions
        if len(self.recent_actions) > 10:
            self.recent_actions.pop(0)

    def to_dict(self) -> dict:
        return {
            "faction_id": self.faction_id,
            "name": self.name,
            "standing": round(self.standing, 1),
            "disposition": self.disposition,
            "recent_actions": list(self.recent_actions),
        }

    @staticmethod
    def from_dict(d: dict) -> FactionStanding:
        return FactionStanding(
            faction_id=d["faction_id"],
            name=d.get("name", d["faction_id"]),
            standing=d.get("standing", 0.0),
            recent_actions=d.get("recent_actions", []),
        )


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------

@dataclass
class Channel:
    """A ship communication channel."""

    name: str
    status: str = "open"            # "open", "monitored", "closed"
    bandwidth_cost: float = 10.0    # percent of total bandwidth

    @property
    def active_cost(self) -> float:
        """Bandwidth consumed based on status."""
        if self.status == "open":
            return self.bandwidth_cost
        if self.status == "monitored":
            return self.bandwidth_cost * 0.5
        return 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "bandwidth_cost": self.bandwidth_cost,
        }

    @staticmethod
    def from_dict(d: dict) -> Channel:
        return Channel(
            name=d["name"],
            status=d.get("status", "open"),
            bandwidth_cost=d.get("bandwidth_cost", 10.0),
        )


# ---------------------------------------------------------------------------
# TranslationMatrix
# ---------------------------------------------------------------------------

@dataclass
class TranslationMatrix:
    """Tracks translation progress for alien languages."""

    language: str                    # "alien_alpha", "alien_beta"
    progress: float = 0.0           # 0.0–1.0 (percentage / 100)
    words_decoded: int = 0

    def advance(self, amount: float) -> None:
        """Advance translation, clamped to [0, 1]."""
        self.progress = min(1.0, self.progress + amount)

    @property
    def translation_quality(self) -> float:
        """How much of alien text can be translated (0.0–1.0)."""
        return self.progress

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "progress": round(self.progress, 3),
            "words_decoded": self.words_decoded,
        }

    @staticmethod
    def from_dict(d: dict) -> TranslationMatrix:
        return TranslationMatrix(
            language=d["language"],
            progress=d.get("progress", 0.0),
            words_decoded=d.get("words_decoded", 0),
        )


# ---------------------------------------------------------------------------
# CommsContact
# ---------------------------------------------------------------------------

@dataclass
class CommsContact:
    """A map contact derived from communications intelligence."""

    id: str
    source_signal_id: str           # Signal that generated this contact
    source_type: str                # CONTACT_SOURCE_* constant

    # Position
    position: tuple[float, float]   # World coordinates (x, y)
    position_accuracy: str          # "exact", "approximate", "region"
    position_radius: float          # Uncertainty radius (0 for exact)

    # Identity
    name: str                       # "ISS Valiant", "Reported Pirate Activity"
    entity_type: str                # "ship", "station", "hazard", etc.
    faction: str                    # Faction ID
    threat_level: str               # "friendly", "neutral", "hostile", etc.

    # Intelligence quality
    confidence: str                 # "confirmed", "probable", "unverified", "rumour"
    staleness: float = 0.0          # Seconds since intel was current
    last_updated_tick: int = 0

    # Display
    icon: str = "unknown"           # Map icon type
    visible_to: list[str] = field(default_factory=lambda: [
        "captain", "helm", "science", "weapons",
    ])
    expires_tick: int | None = None  # Contact fades after this tick

    # Mission link
    mission_id: str | None = None   # Associated dynamic mission

    # Merge tracking
    merged_sensor_id: str | None = None  # Sensor contact ID after merge
    decode_progress: float = 1.0    # Mirrors signal decode for partial contacts

    # Trap flag (server-side only — never sent to client)
    _is_trap: bool = field(default=False, repr=False)

    # Assessment (if Comms assessed distress)
    assessment: dict | None = None  # {authenticity, risk_level, factors}

    def to_dict(self) -> dict:
        """Serialise for broadcast or save."""
        return {
            "id": self.id,
            "source_signal_id": self.source_signal_id,
            "source_type": self.source_type,
            "position": list(self.position),
            "position_accuracy": self.position_accuracy,
            "position_radius": round(self.position_radius, 1),
            "name": self.name,
            "entity_type": self.entity_type,
            "faction": self.faction,
            "threat_level": self.threat_level,
            "confidence": self.confidence,
            "staleness": round(self.staleness, 1),
            "last_updated_tick": self.last_updated_tick,
            "icon": self.icon,
            "visible_to": list(self.visible_to),
            "expires_tick": self.expires_tick,
            "mission_id": self.mission_id,
            "merged_sensor_id": self.merged_sensor_id,
            "decode_progress": round(self.decode_progress, 3),
            "assessment": self.assessment,
        }

    @staticmethod
    def from_dict(d: dict) -> CommsContact:
        """Deserialise from save/broadcast dict."""
        pos = d.get("position", [0.0, 0.0])
        return CommsContact(
            id=d["id"],
            source_signal_id=d.get("source_signal_id", ""),
            source_type=d.get("source_type", "unknown"),
            position=(float(pos[0]), float(pos[1])),
            position_accuracy=d.get("position_accuracy", "approximate"),
            position_radius=d.get("position_radius", 10000.0),
            name=d.get("name", "Unknown Contact"),
            entity_type=d.get("entity_type", "unknown"),
            faction=d.get("faction", "unknown"),
            threat_level=d.get("threat_level", "unknown"),
            confidence=d.get("confidence", "unverified"),
            staleness=d.get("staleness", 0.0),
            last_updated_tick=d.get("last_updated_tick", 0),
            icon=d.get("icon", "unknown"),
            visible_to=d.get("visible_to", ["captain", "helm", "science", "weapons"]),
            expires_tick=d.get("expires_tick"),
            mission_id=d.get("mission_id"),
            merged_sensor_id=d.get("merged_sensor_id"),
            decode_progress=d.get("decode_progress", 1.0),
            assessment=d.get("assessment"),
            _is_trap=d.get("_is_trap", False),
        )


# ---------------------------------------------------------------------------
# Diplomatic response templates
# ---------------------------------------------------------------------------

# Response options by (signal_type, threat_level) → list of option dicts
# Each option: {id, label, description, likely_outcome, standing_effect}
RESPONSE_TEMPLATES: dict[tuple[str, str], list[dict]] = {
    ("hail", "unknown"): [
        {
            "id": "comply",
            "label": "COMPLY",
            "description": "Identify ship and state intentions.",
            "likely_outcome": "Positive — most vessels respond well to openness.",
            "standing_effect": "honest_identify",
        },
        {
            "id": "formal",
            "label": "FORMAL",
            "description": "Demand reciprocal identification first.",
            "likely_outcome": "Neutral — professional but cautious.",
            "standing_effect": "respond_promptly",
        },
        {
            "id": "evasive",
            "label": "EVASIVE",
            "description": "Claim to be a civilian transport.",
            "likely_outcome": "Risky — works if they don't scan you.",
            "standing_effect": "respond_promptly",
        },
        {
            "id": "assertive",
            "label": "ASSERTIVE",
            "description": "Identify as a warship and demand they stand down.",
            "likely_outcome": "Intimidating — weaker ships comply.",
            "standing_effect": "refuse_aggressive",
        },
    ],
    ("hail", "friendly"): [
        {
            "id": "comply",
            "label": "COMPLY",
            "description": "Identify ship and state intentions.",
            "likely_outcome": "Positive — friendly contact.",
            "standing_effect": "honest_identify",
        },
        {
            "id": "formal",
            "label": "FORMAL",
            "description": "Standard professional response.",
            "likely_outcome": "Neutral — routine exchange.",
            "standing_effect": "respond_promptly",
        },
    ],
    ("hail", "hostile"): [
        {
            "id": "formal",
            "label": "FORMAL",
            "description": "Acknowledge but reveal nothing.",
            "likely_outcome": "Neutral — delays engagement.",
            "standing_effect": "respond_promptly",
        },
        {
            "id": "assertive",
            "label": "ASSERTIVE",
            "description": "Warn them to back off.",
            "likely_outcome": "Provocative — may trigger attack.",
            "standing_effect": "refuse_aggressive",
        },
        {
            "id": "evasive",
            "label": "EVASIVE",
            "description": "Deny military affiliation.",
            "likely_outcome": "Risky — if scanned, standing drops.",
            "standing_effect": "respond_promptly",
        },
    ],
    ("distress", "unknown"): [
        {
            "id": "acknowledge",
            "label": "ACKNOWLEDGE",
            "description": "Confirm receipt and offer assistance.",
            "likely_outcome": "Positive — may be genuine.",
            "standing_effect": "help_distress",
        },
        {
            "id": "request_coords",
            "label": "REQUEST COORDS",
            "description": "Ask for precise coordinates before committing.",
            "likely_outcome": "Cautious — delays response.",
            "standing_effect": "respond_promptly",
        },
        {
            "id": "unable",
            "label": "UNABLE",
            "description": "Acknowledge but cannot assist.",
            "likely_outcome": "Negative — standing loss.",
            "standing_effect": "ignore_distress",
        },
    ],
    ("distress", "friendly"): [
        {
            "id": "acknowledge",
            "label": "ACKNOWLEDGE",
            "description": "Confirm and set course to assist.",
            "likely_outcome": "Positive — ally grateful.",
            "standing_effect": "help_distress",
        },
        {
            "id": "unable",
            "label": "UNABLE",
            "description": "Cannot divert at this time.",
            "likely_outcome": "Negative — ally disappointed.",
            "standing_effect": "ignore_distress",
        },
    ],
    ("demand", "hostile"): [
        {
            "id": "comply",
            "label": "COMPLY",
            "description": "Agree to their demands.",
            "likely_outcome": "Submissive — avoids combat.",
            "standing_effect": "comply_demand",
        },
        {
            "id": "refuse",
            "label": "REFUSE",
            "description": "Reject their demands outright.",
            "likely_outcome": "Aggressive — expect combat.",
            "standing_effect": "refuse_aggressive",
        },
        {
            "id": "negotiate",
            "label": "NEGOTIATE",
            "description": "Counter-offer or stall for time.",
            "likely_outcome": "Uncertain — buys time.",
            "standing_effect": "respond_promptly",
        },
    ],
    ("demand", "unknown"): [
        {
            "id": "comply",
            "label": "COMPLY",
            "description": "Agree to their demands.",
            "likely_outcome": "Safe — avoids confrontation.",
            "standing_effect": "comply_demand",
        },
        {
            "id": "refuse",
            "label": "REFUSE",
            "description": "Reject their demands.",
            "likely_outcome": "May provoke attack.",
            "standing_effect": "refuse_aggressive",
        },
        {
            "id": "negotiate",
            "label": "NEGOTIATE",
            "description": "Attempt to negotiate terms.",
            "likely_outcome": "Uncertain.",
            "standing_effect": "respond_promptly",
        },
    ],
    ("broadcast", "friendly"): [
        {
            "id": "acknowledge",
            "label": "ACKNOWLEDGE",
            "description": "Note the broadcast.",
            "likely_outcome": "Informational — no response needed.",
            "standing_effect": "respond_promptly",
        },
    ],
    ("broadcast", "unknown"): [
        {
            "id": "acknowledge",
            "label": "ACKNOWLEDGE",
            "description": "Note the broadcast.",
            "likely_outcome": "Informational.",
            "standing_effect": "respond_promptly",
        },
    ],
    ("encrypted", "unknown"): [],   # No response until decoded
    ("data_burst", "unknown"): [],   # Route intel, no response
}


# NPC reply templates for diplomatic responses
# Key: (signal_type, response_id) → list of possible replies
NPC_REPLY_TEMPLATES: dict[tuple[str, str], list[str]] = {
    ("hail", "comply"): [
        "Acknowledged. Welcome to this sector.",
        "Copy that. Safe travels.",
        "Identification confirmed. You're clear.",
    ],
    ("hail", "formal"): [
        "Understood. This is a routine patrol. Proceed.",
        "We are the merchant vessel Horizon. Passing through.",
        "Acknowledged. State your business.",
    ],
    ("hail", "evasive"): [
        "Very well, civilian transport. Move along.",
        "Hmm. Our sensors say otherwise. Stand by.",
        "Understood. Continue on your heading.",
    ],
    ("hail", "assertive"): [
        "We comply. Altering course now.",
        "Understood. We mean no hostility.",
        "Big words. Let's see if your guns match.",
    ],
    ("distress", "acknowledge"): [
        "Thank you! Coordinates transmitting now. Please hurry!",
        "Copy — help is on the way? We're venting atmosphere!",
        "We read you! Hull integrity failing — ETA?",
    ],
    ("distress", "request_coords"): [
        "Coordinates: sector 4B, bearing 127. Hurry!",
        "Sending coordinates now. We don't have much time.",
    ],
    ("distress", "unable"): [
        "Copy... understood. We'll try to hold out.",
        "Please... if anyone else can hear this...",
    ],
    ("demand", "comply"): [
        "Smart decision. Cut your engines and prepare for boarding.",
        "Wise choice. Transmit your cargo manifest.",
    ],
    ("demand", "refuse"): [
        "You'll regret that. All weapons — fire!",
        "Your funeral. Engaging.",
    ],
    ("demand", "negotiate"): [
        "We're listening. What do you propose?",
        "You have 30 seconds. Talk fast.",
    ],
}
