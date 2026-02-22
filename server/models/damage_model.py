"""
Damage Diagnostic Model.

Component-level damage tracking for each ship system. Every system has
3-4 sub-components with individual health and weighted contribution to
overall system health. Damage events are recorded in a history log.

The DamageModel is the source of truth for system health. The game loop
propagates weighted health values to ShipSystem.health each tick.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Component specifications per system
# ---------------------------------------------------------------------------

COMPONENT_SPECS: dict[str, list[dict]] = {
    "engines": [
        {"id": "fuel_injectors",  "name": "Fuel Injectors",  "weight": 0.3, "effect": "max_speed"},
        {"id": "thrust_nozzles",  "name": "Thrust Nozzles",  "weight": 0.3, "effect": "acceleration"},
        {"id": "coolant_system",  "name": "Coolant System",  "weight": 0.2, "effect": "overclock_risk"},
        {"id": "power_coupling",  "name": "Power Coupling",  "weight": 0.2, "effect": "power_draw"},
    ],
    "beams": [
        {"id": "emitter_array",      "name": "Emitter Array",      "weight": 0.4, "effect": "beam_damage"},
        {"id": "targeting_computer", "name": "Targeting Computer", "weight": 0.3, "effect": "accuracy"},
        {"id": "power_conduit",      "name": "Power Conduit",      "weight": 0.3, "effect": "power_draw"},
    ],
    "torpedoes": [
        {"id": "loading_mechanism", "name": "Loading Mechanism", "weight": 0.3, "effect": "reload_time"},
        {"id": "guidance_system",   "name": "Guidance System",   "weight": 0.4, "effect": "homing_accuracy"},
        {"id": "magazine_housing",  "name": "Magazine Housing",  "weight": 0.3, "effect": "ammo_safety"},
    ],
    "shields": [
        {"id": "generator_coils",      "name": "Generator Coils",      "weight": 0.4, "effect": "shield_capacity"},
        {"id": "field_emitter",        "name": "Field Emitter",        "weight": 0.3, "effect": "recharge_rate"},
        {"id": "harmonic_stabiliser", "name": "Harmonic Stabiliser", "weight": 0.3, "effect": "frequency_stability"},
    ],
    "sensors": [
        {"id": "antenna_array",    "name": "Antenna Array",    "weight": 0.4, "effect": "scan_range"},
        {"id": "signal_processor", "name": "Signal Processor", "weight": 0.3, "effect": "contact_resolution"},
        {"id": "calibration_unit", "name": "Calibration Unit", "weight": 0.3, "effect": "scan_time"},
    ],
    "manoeuvring": [
        {"id": "gyroscope",      "name": "Gyroscope",           "weight": 0.4, "effect": "turn_rate"},
        {"id": "thruster_array", "name": "Thruster Array",      "weight": 0.3, "effect": "lateral_thrust"},
        {"id": "nav_computer",   "name": "Navigation Computer", "weight": 0.3, "effect": "heading_stability"},
    ],
    "flight_deck": [
        {"id": "launch_catapult",  "name": "Launch Catapult",  "weight": 0.3, "effect": "launch_time"},
        {"id": "recovery_system",  "name": "Recovery System",  "weight": 0.3, "effect": "recovery_time"},
        {"id": "deck_plating",     "name": "Deck Plating",     "weight": 0.4, "effect": "hangar_safety"},
    ],
    "ecm_suite": [
        {"id": "jammer_array",       "name": "Jammer Array",       "weight": 0.4, "effect": "jamming_power"},
        {"id": "signal_analyzer",    "name": "Signal Analyzer",    "weight": 0.3, "effect": "intercept_chance"},
        {"id": "countermeasure_pod", "name": "Countermeasure Pod", "weight": 0.3, "effect": "countermeasure_effectiveness"},
    ],
    "point_defence": [
        {"id": "tracking_radar",   "name": "Tracking Radar",   "weight": 0.4, "effect": "intercept_accuracy"},
        {"id": "turret_mechanism", "name": "Turret Mechanism", "weight": 0.3, "effect": "tracking_speed"},
        {"id": "ammo_feed",        "name": "Ammunition Feed",  "weight": 0.3, "effect": "feed_reliability"},
    ],
}

ALL_SYSTEMS: tuple[str, ...] = tuple(COMPONENT_SPECS.keys())


# ---------------------------------------------------------------------------
# SystemComponent
# ---------------------------------------------------------------------------


@dataclass
class SystemComponent:
    """A single sub-component within a ship system."""

    id: str
    name: str
    system: str
    health: float = 100.0   # 0-100
    weight: float = 1.0     # contribution to parent system weighted health
    effect: str = ""        # effect type when degraded (used by game loop)

    @property
    def health_contribution(self) -> float:
        """Weighted health contribution (0.0 to weight)."""
        return (self.health / 100.0) * self.weight

    @property
    def is_destroyed(self) -> bool:
        return self.health <= 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "system": self.system,
            "health": round(self.health, 2),
            "weight": self.weight,
            "effect": self.effect,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SystemComponent:
        return cls(
            id=data["id"],
            name=data["name"],
            system=data["system"],
            health=data.get("health", 100.0),
            weight=data.get("weight", 1.0),
            effect=data.get("effect", ""),
        )


# ---------------------------------------------------------------------------
# DamageEvent
# ---------------------------------------------------------------------------


@dataclass
class DamageEvent:
    """Record of a single damage event for history tracking."""

    tick: int
    system: str
    component_id: str
    damage: float
    cause: str

    def to_dict(self) -> dict:
        return {
            "tick": self.tick,
            "system": self.system,
            "component_id": self.component_id,
            "damage": round(self.damage, 2),
            "cause": self.cause,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DamageEvent:
        return cls(
            tick=data["tick"],
            system=data["system"],
            component_id=data["component_id"],
            damage=data.get("damage", 0.0),
            cause=data.get("cause", "unknown"),
        )


# ---------------------------------------------------------------------------
# DamageModel
# ---------------------------------------------------------------------------

MAX_EVENT_HISTORY: int = 100   # cap history to prevent unbounded growth


@dataclass
class DamageModel:
    """Component-level damage tracking for all ship systems.

    Each system has 3-4 sub-components with individual health values.
    System health is the weighted average of component healths.
    """

    components: dict[str, dict[str, SystemComponent]] = field(
        default_factory=dict)   # {system: {comp_id: SystemComponent}}
    event_history: list[DamageEvent] = field(default_factory=list)

    # ---- Factory ----

    @classmethod
    def create_default(cls) -> DamageModel:
        """Create a DamageModel with standard components for all 9 systems."""
        model = cls()
        for system, specs in COMPONENT_SPECS.items():
            model.components[system] = {}
            for spec in specs:
                comp = SystemComponent(
                    id=spec["id"],
                    name=spec["name"],
                    system=system,
                    weight=spec["weight"],
                    effect=spec["effect"],
                )
                model.components[system][spec["id"]] = comp
        return model

    # ---- Damage ----

    def apply_damage(self, system: str, damage: float, cause: str,
                     tick: int = 0,
                     component_id: str | None = None,
                     rng: random.Random | None = None) -> list[dict]:
        """Apply damage to a system's components.

        If component_id is specified, all damage goes to that component.
        Otherwise a random component is selected. Overflow damage (past 0 HP)
        carries to the next random component.

        Returns a list of event dicts for each component hit.
        """
        sys_comps = self.components.get(system)
        if sys_comps is None or damage <= 0.0:
            return []

        if rng is None:
            rng = random.Random()

        events: list[dict] = []
        remaining = damage

        if component_id is not None:
            # Targeted damage
            comp = sys_comps.get(component_id)
            if comp is None:
                return []
            actual = min(remaining, comp.health)
            comp.health = max(0.0, comp.health - remaining)
            self._record_event(tick, system, comp.id, actual, cause)
            events.append({
                "system": system,
                "component_id": comp.id,
                "damage": actual,
                "health": comp.health,
                "destroyed": comp.is_destroyed,
            })
            remaining -= actual
            # Overflow to random
            if remaining > 0.0:
                events.extend(
                    self._apply_overflow(sys_comps, remaining, cause,
                                         tick, rng, exclude={comp.id}))
        else:
            # Random component targeting with overflow
            events.extend(
                self._apply_overflow(sys_comps, remaining, cause,
                                     tick, rng))

        return events

    def _apply_overflow(self, sys_comps: dict[str, SystemComponent],
                        damage: float, cause: str, tick: int,
                        rng: random.Random,
                        exclude: set[str] | None = None) -> list[dict]:
        """Distribute damage across random components until absorbed."""
        events: list[dict] = []
        remaining = damage
        excluded = exclude or set()

        while remaining > 0.0:
            alive = [c for c in sys_comps.values()
                     if c.health > 0.0 and c.id not in excluded]
            if not alive:
                break

            target = rng.choice(alive)
            actual = min(remaining, target.health)
            target.health = max(0.0, target.health - remaining)
            remaining -= actual
            excluded.add(target.id)

            self._record_event(tick, target.system, target.id, actual, cause)
            events.append({
                "system": target.system,
                "component_id": target.id,
                "damage": actual,
                "health": target.health,
                "destroyed": target.is_destroyed,
            })

        return events

    def _record_event(self, tick: int, system: str,
                      component_id: str, damage: float,
                      cause: str) -> None:
        """Add a damage event to the history."""
        self.event_history.append(
            DamageEvent(tick=tick, system=system,
                        component_id=component_id,
                        damage=damage, cause=cause))
        # Cap history
        if len(self.event_history) > MAX_EVENT_HISTORY:
            self.event_history = self.event_history[-MAX_EVENT_HISTORY:]

    # ---- Repair ----

    def repair_component(self, system: str, component_id: str,
                         hp: float) -> float:
        """Repair a specific component. Returns actual HP repaired."""
        sys_comps = self.components.get(system)
        if sys_comps is None:
            return 0.0
        comp = sys_comps.get(component_id)
        if comp is None:
            return 0.0
        room = 100.0 - comp.health
        actual = min(hp, room)
        comp.health = min(100.0, comp.health + actual)
        return actual

    def repair_system(self, system: str, hp: float) -> float:
        """Repair the most damaged component in a system.

        Returns actual HP repaired.
        """
        worst = self.get_worst_component(system)
        if worst is None:
            return 0.0
        return self.repair_component(system, worst.id, hp)

    # ---- Query ----

    def get_system_health(self, system: str) -> float:
        """Weighted health for a system (0-100)."""
        sys_comps = self.components.get(system)
        if not sys_comps:
            return 100.0
        total_weight = sum(c.weight for c in sys_comps.values())
        if total_weight <= 0.0:
            return 100.0
        weighted_sum = sum(c.health_contribution for c in sys_comps.values())
        return (weighted_sum / total_weight) * 100.0

    def get_component_health(self, system: str,
                             component_id: str) -> float | None:
        """Get health of a specific component, or None if not found."""
        sys_comps = self.components.get(system)
        if sys_comps is None:
            return None
        comp = sys_comps.get(component_id)
        return comp.health if comp is not None else None

    def get_worst_component(self, system: str) -> SystemComponent | None:
        """Return the most damaged component in a system (lowest health)."""
        sys_comps = self.components.get(system)
        if not sys_comps:
            return None
        damaged = [c for c in sys_comps.values() if c.health < 100.0]
        if not damaged:
            return None
        return min(damaged, key=lambda c: c.health)

    def get_destroyed_components(self, system: str) -> list[SystemComponent]:
        """Return all destroyed components (health <= 0) in a system."""
        sys_comps = self.components.get(system)
        if not sys_comps:
            return []
        return [c for c in sys_comps.values() if c.is_destroyed]

    def get_all_damaged(self) -> dict[str, list[SystemComponent]]:
        """Return all damaged components across all systems."""
        result: dict[str, list[SystemComponent]] = {}
        for system, comps in self.components.items():
            damaged = [c for c in comps.values() if c.health < 100.0]
            if damaged:
                result[system] = damaged
        return result

    def get_component_effect_factor(self, system: str,
                                    effect: str) -> float:
        """Get the degradation factor (0.0-1.0) for a specific effect.

        Returns the health fraction of the component with that effect.
        1.0 = fully functional, 0.0 = destroyed.
        """
        sys_comps = self.components.get(system)
        if not sys_comps:
            return 1.0
        for comp in sys_comps.values():
            if comp.effect == effect:
                return comp.health / 100.0
        return 1.0

    def get_recent_events(self, count: int = 10) -> list[dict]:
        """Return the N most recent damage events as dicts."""
        return [e.to_dict() for e in self.event_history[-count:]]

    # ---- Serialisation ----

    def serialise(self) -> dict:
        return {
            "components": {
                system: {cid: c.to_dict() for cid, c in comps.items()}
                for system, comps in self.components.items()
            },
            "event_history": [e.to_dict() for e in self.event_history],
        }

    @classmethod
    def deserialise(cls, data: dict) -> DamageModel:
        model = cls()
        for system, comps_data in data.get("components", {}).items():
            model.components[system] = {}
            for cid, cdata in comps_data.items():
                model.components[system][cid] = SystemComponent.from_dict(cdata)
        for edata in data.get("event_history", []):
            model.event_history.append(DamageEvent.from_dict(edata))
        return model
