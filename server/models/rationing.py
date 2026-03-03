"""
Rationing Model — v0.07 Phase 6.6.

Defines AllocationRequest and ResourceForecast dataclasses, plus rationing
constants (consumption/effectiveness multipliers per level).
"""
from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RATION_LEVELS: tuple[str, ...] = ("unrestricted", "conserve", "ration", "emergency")

RATION_CONSUMPTION_MULT: dict[str, float] = {
    "unrestricted": 1.00,
    "conserve": 0.75,
    "ration": 0.50,
    "emergency": 0.25,
}

RATION_EFFECTIVENESS_MULT: dict[str, float] = {
    "unrestricted": 1.00,
    "conserve": 0.90,
    "ration": 0.75,
    "emergency": 0.50,
}

FORECAST_WINDOW: float = 60.0            # seconds of burn-rate averaging history
FORECAST_UPDATE_INTERVAL: float = 10.0   # seconds between forecast recalcs
AUTO_APPROVE_THRESHOLD: float = 0.50     # auto-approve allocation if stock fraction > 50%

RESOURCE_TYPES: tuple[str, ...] = (
    "fuel", "medical_supplies", "repair_materials",
    "drone_fuel", "drone_parts", "ammunition", "provisions",
    "suppressant",
)

REQUEST_STATUSES: tuple[str, ...] = ("pending", "approved", "denied")

# Forecast colour thresholds (fraction remaining).
FORECAST_COLOUR_RED: float = 0.10
FORECAST_COLOUR_AMBER: float = 0.25


# ---------------------------------------------------------------------------
# AllocationRequest
# ---------------------------------------------------------------------------


@dataclass
class AllocationRequest:
    """A cross-station request for a specific resource quantity."""

    id: str
    source_station: str       # "engineering" | "medical" | "flight_ops" | "security" | "weapons"
    resource_type: str
    quantity: float
    reason: str
    status: str = "pending"   # pending | approved | denied
    denial_reason: str = ""
    created_tick: int = 0
    impact_preview: float = 0.0  # fraction remaining after approval

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_station": self.source_station,
            "resource_type": self.resource_type,
            "quantity": self.quantity,
            "reason": self.reason,
            "status": self.status,
            "denial_reason": self.denial_reason,
            "created_tick": self.created_tick,
            "impact_preview": self.impact_preview,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AllocationRequest:
        return cls(
            id=data["id"],
            source_station=data["source_station"],
            resource_type=data["resource_type"],
            quantity=data["quantity"],
            reason=data["reason"],
            status=data.get("status", "pending"),
            denial_reason=data.get("denial_reason", ""),
            created_tick=data.get("created_tick", 0),
            impact_preview=data.get("impact_preview", 0.0),
        )


# ---------------------------------------------------------------------------
# ResourceForecast
# ---------------------------------------------------------------------------


@dataclass
class ResourceForecast:
    """Burn-rate forecast for a single resource type."""

    resource_type: str
    current: float
    capacity: float
    burn_rate: float              # units/sec (smoothed over last 60s)
    seconds_to_depletion: float   # -1 if no consumption
    colour: str = "green"         # green | amber | red | flashing_red
    projected_at_destination: float = -1.0  # -1 if no route

    def to_dict(self) -> dict:
        return {
            "resource_type": self.resource_type,
            "current": round(self.current, 2),
            "capacity": round(self.capacity, 2),
            "burn_rate": round(self.burn_rate, 4),
            "seconds_to_depletion": round(self.seconds_to_depletion, 1),
            "colour": self.colour,
            "projected_at_destination": round(self.projected_at_destination, 2),
        }
