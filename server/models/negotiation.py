"""
Negotiation Model — v0.07 Phase 6.3.

Trade channels, negotiation sessions, barter offers, and constants for the
negotiation layer that sits on top of the vendor system (§6.2).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Channel range thresholds (§6.3.1.3)
# ---------------------------------------------------------------------------

CHANNEL_RANGE_STABLE: float = 5000.0
CHANNEL_RANGE_DEGRADED: float = 15000.0
DEGRADED_ROUND_MULTIPLIER: float = 1.5

# ---------------------------------------------------------------------------
# Counter-offer thresholds (§6.3.2.3)
# ---------------------------------------------------------------------------

COUNTER_ACCEPT_WITHIN: float = 0.10
COUNTER_SPLIT_WITHIN: float = 0.20
COUNTER_CONCESSION_WITHIN: float = 0.30
COUNTER_INCREASE_PENALTY: float = 0.05
COUNTER_BREAKOFF_BELOW: float = 0.50
COUNTER_COOLDOWN: float = 120.0

MAX_COUNTER_ROUNDS: int = 3

# ---------------------------------------------------------------------------
# Walk-away / callback (§6.3.2.4)
# ---------------------------------------------------------------------------

WALK_AWAY_CALLBACK_CHANCE: float = 0.30
WALK_AWAY_CALLBACK_DELAY: float = 15.0
WALK_AWAY_CALLBACK_DISCOUNT: float = 0.10

# ---------------------------------------------------------------------------
# Bundle discount (§6.3.2.5)
# ---------------------------------------------------------------------------

BUNDLE_DISCOUNT_2ND: float = 0.05
BUNDLE_DISCOUNT_3RD: float = 0.10

# ---------------------------------------------------------------------------
# Inspect cost (§6.3.2.2)
# ---------------------------------------------------------------------------

INSPECT_COST_FRACTION: float = 0.05

# ---------------------------------------------------------------------------
# Barter (§6.3.3)
# ---------------------------------------------------------------------------

BARTER_PENALTY: float = 0.80

INTEL_VALUE_MILITARY: tuple[float, float] = (10.0, 50.0)
INTEL_VALUE_CIVILIAN: tuple[float, float] = (5.0, 30.0)
INTEL_VALUE_MERCHANT: tuple[float, float] = (15.0, 40.0)
INTEL_VALUE_BLACK_MARKET_MULT: float = 0.50

# ---------------------------------------------------------------------------
# Service contracts (§6.3.3.4)
# ---------------------------------------------------------------------------

SERVICE_CONTRACT_TYPES: tuple[str, ...] = ("escort", "delivery", "scan", "patrol")
SERVICE_CONTRACT_FAILURE_REP: float = -15.0
SERVICE_CONTRACT_FAILURE_STANDING: float = -10.0

# ---------------------------------------------------------------------------
# Bluff (§6.3.4)
# ---------------------------------------------------------------------------

BLUFF_TYPES: tuple[str, ...] = ("not_urgent", "military_authority", "competing_offer")
BLUFF_BASE_CHANCE: float = 0.50
BLUFF_REP_BONUS: float = 0.15
BLUFF_REP_PENALTY: float = -0.20
BLUFF_COMMS_BONUS: float = 0.20
BLUFF_DAMAGE_PENALTY: float = -0.15
BLUFF_MILITARY_BONUS: float = 0.25

BLUFF_NOT_URGENT_PENALTY_REP: float = -5.0
BLUFF_MILITARY_FAIL_COOLDOWN: float = 180.0
BLUFF_MILITARY_FAIL_REP: float = -10.0
BLUFF_MILITARY_SUCCESS_DISCOUNT: float = 0.20
BLUFF_COMPETING_SUCCESS_DISCOUNT: float = 0.10

# ---------------------------------------------------------------------------
# Combat pressure (§6.3.2.6)
# ---------------------------------------------------------------------------

COMBAT_URGENCY_MULTIPLIER: float = 1.5
COMBAT_SPEED_MULTIPLIER: float = 0.5

# ---------------------------------------------------------------------------
# Session statuses
# ---------------------------------------------------------------------------

SESSION_STATUSES: tuple[str, ...] = (
    "idle", "opening", "offer_presented", "counter_round",
    "walk_away", "callback_pending", "barter", "bluff_pending",
    "final_offer", "completed", "broken_off",
)

CHANNEL_STATUSES: tuple[str, ...] = ("open", "degraded", "closed")


# ---------------------------------------------------------------------------
# TradeChannel
# ---------------------------------------------------------------------------

@dataclass
class TradeChannel:
    """A communication channel to a vendor for negotiation."""

    id: str
    vendor_id: str
    station_id: str | None = None
    status: str = "open"            # open | degraded | closed
    opened_at: float = 0.0         # game tick when opened
    distance: float = 0.0          # current distance to vendor
    is_docked: bool = False        # docked → unlimited range

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "vendor_id": self.vendor_id,
            "station_id": self.station_id,
            "status": self.status,
            "opened_at": self.opened_at,
            "distance": self.distance,
            "is_docked": self.is_docked,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TradeChannel:
        return cls(
            id=data["id"],
            vendor_id=data["vendor_id"],
            station_id=data.get("station_id"),
            status=data.get("status", "open"),
            opened_at=float(data.get("opened_at", 0.0)),
            distance=float(data.get("distance", 0.0)),
            is_docked=bool(data.get("is_docked", False)),
        )


# ---------------------------------------------------------------------------
# NegotiationSession
# ---------------------------------------------------------------------------

@dataclass
class NegotiationSession:
    """An active negotiation for a specific item with a vendor."""

    id: str
    channel_id: str
    vendor_id: str
    status: str = "offer_presented"
    item_type: str = ""
    quantity: int = 0
    is_selling: bool = False
    vendor_offer: float = 0.0       # current vendor price per unit
    original_offer: float = 0.0     # first vendor price (for counter % calc)
    counter_rounds: int = 0
    max_counter_rounds: int = MAX_COUNTER_ROUNDS
    bundle_index: int = 0           # 0=first item, 1=second (+5%), 2=third+ (+10%)
    walk_away_used: bool = False
    callback_timer: float = 0.0
    callback_discount: float = 0.0
    bluff_used: bool = False
    inspect_paid: bool = False
    combat_active: bool = False
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "channel_id": self.channel_id,
            "vendor_id": self.vendor_id,
            "status": self.status,
            "item_type": self.item_type,
            "quantity": self.quantity,
            "is_selling": self.is_selling,
            "vendor_offer": self.vendor_offer,
            "original_offer": self.original_offer,
            "counter_rounds": self.counter_rounds,
            "max_counter_rounds": self.max_counter_rounds,
            "bundle_index": self.bundle_index,
            "walk_away_used": self.walk_away_used,
            "callback_timer": self.callback_timer,
            "callback_discount": self.callback_discount,
            "bluff_used": self.bluff_used,
            "inspect_paid": self.inspect_paid,
            "combat_active": self.combat_active,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> NegotiationSession:
        return cls(
            id=data["id"],
            channel_id=data["channel_id"],
            vendor_id=data["vendor_id"],
            status=data.get("status", "offer_presented"),
            item_type=data.get("item_type", ""),
            quantity=int(data.get("quantity", 0)),
            is_selling=bool(data.get("is_selling", False)),
            vendor_offer=float(data.get("vendor_offer", 0.0)),
            original_offer=float(data.get("original_offer", 0.0)),
            counter_rounds=int(data.get("counter_rounds", 0)),
            max_counter_rounds=int(data.get("max_counter_rounds", MAX_COUNTER_ROUNDS)),
            bundle_index=int(data.get("bundle_index", 0)),
            walk_away_used=bool(data.get("walk_away_used", False)),
            callback_timer=float(data.get("callback_timer", 0.0)),
            callback_discount=float(data.get("callback_discount", 0.0)),
            bluff_used=bool(data.get("bluff_used", False)),
            inspect_paid=bool(data.get("inspect_paid", False)),
            combat_active=bool(data.get("combat_active", False)),
            created_at=float(data.get("created_at", 0.0)),
        )


# ---------------------------------------------------------------------------
# BarterOffer
# ---------------------------------------------------------------------------

@dataclass
class BarterOffer:
    """A barter offer from the player to a vendor."""

    resource_items: dict[str, int] = field(default_factory=dict)
    intel_items: list[str] = field(default_factory=list)
    service_contract: str | None = None
    credit_value: float = 0.0

    def to_dict(self) -> dict:
        return {
            "resource_items": dict(self.resource_items),
            "intel_items": list(self.intel_items),
            "service_contract": self.service_contract,
            "credit_value": self.credit_value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BarterOffer:
        return cls(
            resource_items=dict(data.get("resource_items", {})),
            intel_items=list(data.get("intel_items", [])),
            service_contract=data.get("service_contract"),
            credit_value=float(data.get("credit_value", 0.0)),
        )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def evaluate_counter_offer(
    counter_price: float,
    vendor_price: float,
    original_price: float,
) -> tuple[str, float]:
    """Evaluate a player's counter-offer against the vendor's position.

    Returns (response, new_price) where response is one of:
    "accepted", "split", "concession", "hold", "raised", "broken_off"
    """
    if original_price <= 0:
        return ("broken_off", vendor_price)

    # How far from vendor's current offer (as fraction of original)?
    diff_fraction = abs(counter_price - vendor_price) / original_price

    # If below 50% of vendor price → vendor breaks off.
    if counter_price < vendor_price * (1.0 - COUNTER_BREAKOFF_BELOW):
        return ("broken_off", vendor_price)

    # Within 10% of vendor's current offer → vendor accepts.
    if diff_fraction <= COUNTER_ACCEPT_WITHIN:
        return ("accepted", counter_price)

    # Within 20% → split the difference.
    if diff_fraction <= COUNTER_SPLIT_WITHIN:
        split_price = round((counter_price + vendor_price) / 2.0, 2)
        return ("split", split_price)

    # Within 30% → vendor concedes 5% of original.
    if diff_fraction <= COUNTER_CONCESSION_WITHIN:
        concession = round(vendor_price - (original_price * 0.05), 2)
        return ("concession", concession)

    # Beyond 30% → vendor raises by 5% of original.
    raised = round(vendor_price + (original_price * COUNTER_INCREASE_PENALTY), 2)
    return ("raised", raised)


def calculate_barter_value(
    resource_items: dict[str, int],
    base_prices: dict[str, float],
) -> float:
    """Calculate the credit equivalent of bartered goods at 80% value."""
    total = 0.0
    for item_type, qty in resource_items.items():
        unit_price = base_prices.get(item_type, 0.0)
        total += unit_price * qty
    return round(total * BARTER_PENALTY, 2)


def calculate_intel_value(
    signal_count: int,
    vendor_type: str,
) -> float:
    """Calculate the credit equivalent of offered intel signals."""
    from server.models.vendor import VENDOR_TYPES  # noqa: avoid circular at module level

    if vendor_type == "black_market":
        lo, hi = INTEL_VALUE_MERCHANT
        per_signal = (lo + hi) / 2.0 * INTEL_VALUE_BLACK_MARKET_MULT
    elif vendor_type in ("allied_station", "allied_warship"):
        lo, hi = INTEL_VALUE_MILITARY
        per_signal = (lo + hi) / 2.0
    elif vendor_type == "merchant":
        lo, hi = INTEL_VALUE_MERCHANT
        per_signal = (lo + hi) / 2.0
    else:
        lo, hi = INTEL_VALUE_CIVILIAN
        per_signal = (lo + hi) / 2.0

    return round(per_signal * signal_count, 2)
