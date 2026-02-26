"""
Consumable Resource Store — v0.07 Phase 6.1.

Tracks all finite consumable resources on the ship: fuel, medical supplies,
repair materials, drone fuel, drone parts, ammunition, and provisions.
Torpedoes remain managed by game_loop_weapons (discrete per-type items).

ResourceStore is a flat dataclass — type-safe explicit fields with string-keyed
accessors for generic operations (UI display, save/restore, threshold checks).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WARNING_THRESHOLD: float = 0.25
CRITICAL_THRESHOLD: float = 0.10

# Provisions depletion consequences.
PROVISIONS_MORALE_DROP: float = 2.0       # % per minute at 0 provisions
PROVISIONS_EFFECTIVENESS_DROP: float = 1.0  # % per minute at 0 provisions
PROVISIONS_CONSUMPTION_RATE: float = 0.02  # PVU per crew member per minute

# Ammunition depletion consequence.
AMMO_DEPLETED_FIREPOWER_PENALTY: float = 0.60  # 60% firepower reduction

# DC repair material costs.
REPAIR_COST_FIRE_TO_DAMAGED: int = 2
REPAIR_COST_DAMAGED_TO_NORMAL: int = 5
REPAIR_COST_DECOMPRESSED_TO_FIRE: int = 10

# Resource type keys (used for generic accessors).
RESOURCE_TYPES: tuple[str, ...] = (
    "fuel",
    "medical_supplies",
    "repair_materials",
    "drone_fuel",
    "drone_parts",
    "ammunition",
    "provisions",
)


# ---------------------------------------------------------------------------
# ResourceStore
# ---------------------------------------------------------------------------


@dataclass
class ResourceStore:
    """Finite consumable resource inventory for the player ship.

    Each resource has a current value and a maximum capacity.
    Fuel also tracks engine burn rate and reactor idle rate.
    """

    # Fuel
    fuel: float = 0.0
    fuel_max: float = 0.0
    engine_burn_rate: float = 1.0   # FU/s at full throttle
    reactor_idle_rate: float = 0.5  # FU/s at zero throttle

    # Medical supplies
    medical_supplies: float = 0.0
    medical_supplies_max: float = 0.0

    # Repair materials
    repair_materials: float = 0.0
    repair_materials_max: float = 0.0

    # Drone fuel
    drone_fuel: float = 0.0
    drone_fuel_max: float = 0.0

    # Drone parts
    drone_parts: float = 0.0
    drone_parts_max: float = 0.0

    # Ammunition (marine small arms)
    ammunition: float = 0.0
    ammunition_max: float = 0.0

    # Provisions
    provisions: float = 0.0
    provisions_max: float = 0.0

    # Provisions depletion tracking
    provisions_depleted_time: float = 0.0  # seconds at 0 provisions
    provisions_crew_penalty: float = 0.0   # current crew factor penalty (0.0-0.5)

    # Threshold alert tracking (avoid duplicate alerts).
    _warned: dict[str, bool] = field(default_factory=dict)
    _critical_warned: dict[str, bool] = field(default_factory=dict)

    # --- Generic accessors ---

    def get(self, resource_type: str) -> float:
        """Get current value for a resource type."""
        return getattr(self, resource_type, 0.0)

    def get_max(self, resource_type: str) -> float:
        """Get maximum capacity for a resource type."""
        return getattr(self, f"{resource_type}_max", 0.0)

    def set(self, resource_type: str, amount: float) -> None:
        """Set current value, clamped to [0, max]."""
        mx = self.get_max(resource_type)
        setattr(self, resource_type, max(0.0, min(amount, mx)))

    def consume(self, resource_type: str, amount: float) -> float:
        """Consume up to *amount* of a resource. Returns actual amount consumed."""
        current = self.get(resource_type)
        actual = min(amount, current)
        setattr(self, resource_type, current - actual)
        return actual

    def add(self, resource_type: str, amount: float) -> float:
        """Add up to *amount* of a resource. Returns actual amount added."""
        current = self.get(resource_type)
        mx = self.get_max(resource_type)
        actual = min(amount, mx - current)
        if actual > 0:
            setattr(self, resource_type, current + actual)
        return max(0.0, actual)

    def fraction(self, resource_type: str) -> float:
        """Return current / max as 0.0-1.0. Returns 1.0 if max is 0."""
        mx = self.get_max(resource_type)
        if mx <= 0.0:
            return 1.0
        return self.get(resource_type) / mx

    def is_warning(self, resource_type: str) -> bool:
        """True if resource is at or below WARNING_THRESHOLD."""
        mx = self.get_max(resource_type)
        if mx <= 0.0:
            return False
        return self.get(resource_type) / mx <= WARNING_THRESHOLD

    def is_critical(self, resource_type: str) -> bool:
        """True if resource is at or below CRITICAL_THRESHOLD."""
        mx = self.get_max(resource_type)
        if mx <= 0.0:
            return False
        return self.get(resource_type) / mx <= CRITICAL_THRESHOLD

    def is_depleted(self, resource_type: str) -> bool:
        """True if resource is at 0."""
        return self.get(resource_type) <= 0.0

    def check_thresholds(self) -> list[dict]:
        """Check all resources for threshold crossings.

        Returns a list of dicts: {resource, level, fraction} for each
        newly-crossed threshold. Resets tracking when resource climbs back
        above threshold.
        """
        alerts: list[dict] = []
        for rt in RESOURCE_TYPES:
            mx = self.get_max(rt)
            if mx <= 0.0:
                continue
            frac = self.get(rt) / mx

            # Critical check.
            if frac <= CRITICAL_THRESHOLD:
                if not self._critical_warned.get(rt, False):
                    self._critical_warned[rt] = True
                    alerts.append({"resource": rt, "level": "critical", "fraction": round(frac, 3)})
            else:
                self._critical_warned[rt] = False

            # Warning check.
            if frac <= WARNING_THRESHOLD:
                if not self._warned.get(rt, False):
                    self._warned[rt] = True
                    alerts.append({"resource": rt, "level": "warning", "fraction": round(frac, 3)})
            else:
                self._warned[rt] = False

        return alerts

    def to_dict(self) -> dict:
        """Serialise to a JSON-friendly dict."""
        result: dict = {}
        for rt in RESOURCE_TYPES:
            result[rt] = round(self.get(rt), 2)
            result[f"{rt}_max"] = round(self.get_max(rt), 2)
            result[f"{rt}_fraction"] = round(self.fraction(rt), 3)
        result["engine_burn_rate"] = self.engine_burn_rate
        result["reactor_idle_rate"] = self.reactor_idle_rate
        result["provisions_depleted_time"] = round(self.provisions_depleted_time, 1)
        result["provisions_crew_penalty"] = round(self.provisions_crew_penalty, 3)
        return result

    @classmethod
    def from_ship_class_resources(cls, resources: dict | None) -> ResourceStore:
        """Create a ResourceStore from a ship class JSON resources block.

        Expected format:
        {
          "fuel": {"starting": 1200, "capacity": 1200, "engine_burn": 1.0, "reactor_idle": 0.5},
          "medical_supplies": {"starting": 60, "capacity": 80},
          ...
        }
        """
        store = cls()
        if resources is None:
            return store

        fuel = resources.get("fuel", {})
        store.fuel = float(fuel.get("starting", 0))
        store.fuel_max = float(fuel.get("capacity", 0))
        store.engine_burn_rate = float(fuel.get("engine_burn", 1.0))
        store.reactor_idle_rate = float(fuel.get("reactor_idle", 0.5))

        for rt in RESOURCE_TYPES:
            if rt == "fuel":
                continue
            block = resources.get(rt, {})
            setattr(store, rt, float(block.get("starting", 0)))
            setattr(store, f"{rt}_max", float(block.get("capacity", 0)))

        return store
