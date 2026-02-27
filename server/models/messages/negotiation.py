"""Negotiation message payload schemas — v0.07 Phase 6.3."""
from __future__ import annotations

from pydantic import BaseModel, Field


class NegotiationOpenChannelPayload(BaseModel):
    """Open a trade channel to a vendor."""
    vendor_id: str


class NegotiationCloseChannelPayload(BaseModel):
    """Close a trade channel."""
    channel_id: str


class NegotiationStartPayload(BaseModel):
    """Start a negotiation on an open channel."""
    channel_id: str
    item_type: str
    quantity: int = Field(ge=1)
    is_selling: bool = False


class NegotiationAcceptPayload(BaseModel):
    """Accept the current vendor offer."""
    session_id: str


class NegotiationCounterPayload(BaseModel):
    """Submit a counter-offer."""
    session_id: str
    proposed_price: float = Field(gt=0)


class NegotiationWalkAwayPayload(BaseModel):
    """Walk away from the negotiation."""
    session_id: str


class NegotiationAcceptCallbackPayload(BaseModel):
    """Accept a vendor callback offer."""
    session_id: str


class NegotiationInspectPayload(BaseModel):
    """Pay to inspect item details."""
    session_id: str


class NegotiationBluffPayload(BaseModel):
    """Attempt a bluff during negotiation."""
    session_id: str
    bluff_type: str  # not_urgent | military_authority | competing_offer


class NegotiationBarterPayload(BaseModel):
    """Propose a barter trade."""
    session_id: str
    resource_items: dict[str, int] = Field(default_factory=dict)
    intel_items: list[str] = Field(default_factory=list)
    service_contract: str | None = None


class NegotiationServiceContractPayload(BaseModel):
    """Propose a service contract to cover trade cost."""
    session_id: str
    contract_type: str  # escort | delivery | scan | patrol
