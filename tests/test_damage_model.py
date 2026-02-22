"""
Damage Diagnostic Model — unit tests.

Covers component specs, weighted health, damage application (random
and targeted), overflow, repair, event history, effect factors, and
serialisation.
"""
from __future__ import annotations

import random

import pytest

from server.models.damage_model import (
    DamageModel,
    SystemComponent,
    DamageEvent,
    COMPONENT_SPECS,
    ALL_SYSTEMS,
    MAX_EVENT_HISTORY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _model() -> DamageModel:
    return DamageModel.create_default()


def _fixed_rng(seed: int = 0) -> random.Random:
    return random.Random(seed)


# ---------------------------------------------------------------------------
# Component specs validation
# ---------------------------------------------------------------------------


class TestComponentSpecs:
    def test_all_nine_systems(self):
        assert len(COMPONENT_SPECS) == 9

    def test_each_system_has_components(self):
        for system, specs in COMPONENT_SPECS.items():
            assert len(specs) >= 3, f"{system} has < 3 components"

    def test_weights_sum_to_one(self):
        for system, specs in COMPONENT_SPECS.items():
            total = sum(s["weight"] for s in specs)
            assert total == pytest.approx(1.0), (
                f"{system} weights sum to {total}")

    def test_all_components_have_effect(self):
        for system, specs in COMPONENT_SPECS.items():
            for spec in specs:
                assert spec["effect"], f"{system}/{spec['id']} has no effect"

    def test_total_component_count(self):
        total = sum(len(specs) for specs in COMPONENT_SPECS.values())
        assert total == 28  # 4 + 3*8


# ---------------------------------------------------------------------------
# SystemComponent
# ---------------------------------------------------------------------------


class TestSystemComponent:
    def test_full_health_contribution(self):
        comp = SystemComponent(id="c1", name="C", system="s",
                               weight=0.4, health=100.0)
        assert comp.health_contribution == pytest.approx(0.4)

    def test_half_health_contribution(self):
        comp = SystemComponent(id="c1", name="C", system="s",
                               weight=0.4, health=50.0)
        assert comp.health_contribution == pytest.approx(0.2)

    def test_zero_health_destroyed(self):
        comp = SystemComponent(id="c1", name="C", system="s", health=0.0)
        assert comp.is_destroyed is True

    def test_to_dict_round_trip(self):
        comp = SystemComponent(id="c1", name="Test", system="engines",
                               health=75.5, weight=0.3, effect="max_speed")
        restored = SystemComponent.from_dict(comp.to_dict())
        assert restored.id == "c1"
        assert restored.health == 75.5
        assert restored.effect == "max_speed"


# ---------------------------------------------------------------------------
# Default model creation
# ---------------------------------------------------------------------------


class TestDefaultModel:
    def test_creates_all_systems(self):
        model = _model()
        for system in ALL_SYSTEMS:
            assert system in model.components

    def test_components_match_specs(self):
        model = _model()
        for system, specs in COMPONENT_SPECS.items():
            assert len(model.components[system]) == len(specs)
            for spec in specs:
                assert spec["id"] in model.components[system]

    def test_all_start_at_full_health(self):
        model = _model()
        for comps in model.components.values():
            for comp in comps.values():
                assert comp.health == 100.0

    def test_all_systems_start_at_100(self):
        model = _model()
        for system in ALL_SYSTEMS:
            assert model.get_system_health(system) == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Weighted health
# ---------------------------------------------------------------------------


class TestWeightedHealth:
    def test_full_health(self):
        model = _model()
        assert model.get_system_health("engines") == pytest.approx(100.0)

    def test_single_component_damaged(self):
        model = _model()
        model.components["engines"]["fuel_injectors"].health = 50.0
        # fuel_injectors weight = 0.3 → contributes 0.15 instead of 0.30
        # other 3 contribute 0.30 + 0.20 + 0.20 = 0.70
        # total = 0.15 + 0.70 = 0.85 → 85.0
        assert model.get_system_health("engines") == pytest.approx(85.0)

    def test_all_components_at_50(self):
        model = _model()
        for comp in model.components["beams"].values():
            comp.health = 50.0
        assert model.get_system_health("beams") == pytest.approx(50.0)

    def test_all_components_destroyed(self):
        model = _model()
        for comp in model.components["sensors"].values():
            comp.health = 0.0
        assert model.get_system_health("sensors") == pytest.approx(0.0)

    def test_weighted_vs_average(self):
        """Higher-weight components affect health more."""
        model = _model()
        # Destroy the 0.4-weight component
        model.components["beams"]["emitter_array"].health = 0.0
        health_a = model.get_system_health("beams")
        # Restore and destroy the 0.3-weight component instead
        model.components["beams"]["emitter_array"].health = 100.0
        model.components["beams"]["power_conduit"].health = 0.0
        health_b = model.get_system_health("beams")
        # Heavier component should cause more health loss
        assert health_a < health_b

    def test_unknown_system_returns_100(self):
        model = _model()
        assert model.get_system_health("warp_core") == 100.0


# ---------------------------------------------------------------------------
# Damage application — random
# ---------------------------------------------------------------------------


class TestRandomDamage:
    def test_reduces_component_health(self):
        model = _model()
        rng = _fixed_rng()
        model.apply_damage("engines", 20.0, "beam_hit", rng=rng)
        # At least one component should be damaged
        healths = [c.health for c in model.components["engines"].values()]
        assert any(h < 100.0 for h in healths)

    def test_system_health_reduced(self):
        model = _model()
        rng = _fixed_rng()
        model.apply_damage("beams", 30.0, "torpedo_hit", rng=rng)
        assert model.get_system_health("beams") < 100.0

    def test_returns_event_dicts(self):
        model = _model()
        rng = _fixed_rng()
        events = model.apply_damage("shields", 15.0, "collision", rng=rng)
        assert len(events) >= 1
        assert "component_id" in events[0]
        assert "damage" in events[0]
        assert "health" in events[0]

    def test_overflow_to_next_component(self):
        """Damage exceeding one component's health flows to next."""
        model = _model()
        # Set one component to 5 HP, then deal 20 damage
        model.components["beams"]["emitter_array"].health = 5.0
        rng = random.Random()
        # Force the rng to pick emitter_array first
        rng.choice = lambda alive: min(alive, key=lambda c: c.id)
        events = model.apply_damage("beams", 20.0, "overload", rng=rng)
        assert model.components["beams"]["emitter_array"].health == 0.0
        # Overflow should hit another component
        other_healths = [c.health for c in model.components["beams"].values()
                         if c.id != "emitter_array"]
        assert any(h < 100.0 for h in other_healths)

    def test_invalid_system_no_events(self):
        model = _model()
        events = model.apply_damage("warp_core", 10.0, "test")
        assert events == []

    def test_zero_damage_no_events(self):
        model = _model()
        events = model.apply_damage("engines", 0.0, "test")
        assert events == []


# ---------------------------------------------------------------------------
# Damage application — targeted
# ---------------------------------------------------------------------------


class TestTargetedDamage:
    def test_damages_specific_component(self):
        model = _model()
        model.apply_damage("engines", 25.0, "fire",
                           component_id="coolant_system")
        assert model.components["engines"]["coolant_system"].health == 75.0
        # Others untouched
        assert model.components["engines"]["fuel_injectors"].health == 100.0

    def test_targeted_overflow(self):
        model = _model()
        model.components["engines"]["coolant_system"].health = 10.0
        events = model.apply_damage("engines", 30.0, "explosion",
                                    component_id="coolant_system",
                                    rng=_fixed_rng())
        assert model.components["engines"]["coolant_system"].health == 0.0
        # Overflow should damage another component
        assert len(events) >= 2

    def test_invalid_component(self):
        model = _model()
        events = model.apply_damage("engines", 10.0, "test",
                                    component_id="nonexistent")
        assert events == []

    def test_destroyed_flag_in_events(self):
        model = _model()
        model.components["beams"]["emitter_array"].health = 5.0
        events = model.apply_damage("beams", 10.0, "hit",
                                    component_id="emitter_array")
        assert events[0]["destroyed"] is True


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------


class TestRepair:
    def test_repair_component(self):
        model = _model()
        model.components["engines"]["fuel_injectors"].health = 50.0
        actual = model.repair_component("engines", "fuel_injectors", 20.0)
        assert actual == pytest.approx(20.0)
        assert model.components["engines"]["fuel_injectors"].health == 70.0

    def test_repair_capped_at_100(self):
        model = _model()
        model.components["beams"]["emitter_array"].health = 95.0
        actual = model.repair_component("beams", "emitter_array", 20.0)
        assert actual == pytest.approx(5.0)
        assert model.components["beams"]["emitter_array"].health == 100.0

    def test_repair_invalid_system(self):
        model = _model()
        assert model.repair_component("warp_core", "x", 10.0) == 0.0

    def test_repair_invalid_component(self):
        model = _model()
        assert model.repair_component("engines", "flux_cap", 10.0) == 0.0

    def test_repair_system_targets_worst(self):
        model = _model()
        model.components["shields"]["generator_coils"].health = 30.0
        model.components["shields"]["field_emitter"].health = 60.0
        actual = model.repair_system("shields", 15.0)
        assert actual == pytest.approx(15.0)
        assert model.components["shields"]["generator_coils"].health == 45.0
        assert model.components["shields"]["field_emitter"].health == 60.0

    def test_repair_system_nothing_damaged(self):
        model = _model()
        assert model.repair_system("engines", 10.0) == 0.0


# ---------------------------------------------------------------------------
# Event history
# ---------------------------------------------------------------------------


class TestEventHistory:
    def test_events_recorded(self):
        model = _model()
        model.apply_damage("engines", 10.0, "beam_hit", tick=42,
                           rng=_fixed_rng())
        assert len(model.event_history) >= 1
        assert model.event_history[0].tick == 42
        assert model.event_history[0].cause == "beam_hit"

    def test_multiple_events(self):
        model = _model()
        model.apply_damage("engines", 10.0, "hit_1", tick=1, rng=_fixed_rng())
        model.apply_damage("beams", 15.0, "hit_2", tick=2, rng=_fixed_rng())
        assert len(model.event_history) >= 2

    def test_history_capped(self):
        model = _model()
        rng = _fixed_rng()
        for i in range(MAX_EVENT_HISTORY + 20):
            model.apply_damage("engines", 0.5, f"hit_{i}", tick=i, rng=rng)
        assert len(model.event_history) <= MAX_EVENT_HISTORY

    def test_get_recent_events(self):
        model = _model()
        rng = _fixed_rng()
        for i in range(5):
            model.apply_damage("engines", 5.0, f"hit_{i}", tick=i, rng=rng)
        recent = model.get_recent_events(3)
        assert len(recent) == 3
        assert recent[-1]["cause"].startswith("hit_")

    def test_damage_event_round_trip(self):
        ev = DamageEvent(tick=10, system="engines",
                         component_id="fuel_injectors",
                         damage=15.5, cause="torpedo")
        restored = DamageEvent.from_dict(ev.to_dict())
        assert restored.tick == 10
        assert restored.damage == 15.5


# ---------------------------------------------------------------------------
# Query methods
# ---------------------------------------------------------------------------


class TestQueries:
    def test_get_component_health(self):
        model = _model()
        model.components["sensors"]["antenna_array"].health = 42.0
        assert model.get_component_health("sensors", "antenna_array") == 42.0

    def test_get_component_health_invalid(self):
        model = _model()
        assert model.get_component_health("warp", "x") is None
        assert model.get_component_health("sensors", "x") is None

    def test_get_worst_component(self):
        model = _model()
        model.components["engines"]["thrust_nozzles"].health = 20.0
        model.components["engines"]["coolant_system"].health = 50.0
        worst = model.get_worst_component("engines")
        assert worst is not None
        assert worst.id == "thrust_nozzles"

    def test_get_worst_component_none_damaged(self):
        model = _model()
        assert model.get_worst_component("engines") is None

    def test_get_destroyed_components(self):
        model = _model()
        model.components["beams"]["emitter_array"].health = 0.0
        model.components["beams"]["power_conduit"].health = 0.0
        destroyed = model.get_destroyed_components("beams")
        assert len(destroyed) == 2

    def test_get_all_damaged(self):
        model = _model()
        model.components["engines"]["fuel_injectors"].health = 80.0
        model.components["shields"]["generator_coils"].health = 60.0
        damaged = model.get_all_damaged()
        assert "engines" in damaged
        assert "shields" in damaged
        assert "beams" not in damaged

    def test_get_component_effect_factor(self):
        model = _model()
        model.components["engines"]["fuel_injectors"].health = 60.0
        factor = model.get_component_effect_factor("engines", "max_speed")
        assert factor == pytest.approx(0.6)

    def test_effect_factor_unknown_returns_one(self):
        model = _model()
        assert model.get_component_effect_factor("engines", "warp") == 1.0
        assert model.get_component_effect_factor("warp", "x") == 1.0


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


class TestSerialisation:
    def test_round_trip(self):
        model = _model()
        model.apply_damage("engines", 20.0, "test", tick=5, rng=_fixed_rng())
        model.apply_damage("beams", 15.0, "test2", tick=6, rng=_fixed_rng())

        data = model.serialise()
        restored = DamageModel.deserialise(data)

        for system in ALL_SYSTEMS:
            assert model.get_system_health(system) == pytest.approx(
                restored.get_system_health(system))

        assert len(restored.event_history) == len(model.event_history)

    def test_deserialise_empty(self):
        restored = DamageModel.deserialise({})
        assert len(restored.components) == 0
        assert len(restored.event_history) == 0

    def test_component_health_preserved(self):
        model = _model()
        model.components["sensors"]["antenna_array"].health = 33.33
        data = model.serialise()
        restored = DamageModel.deserialise(data)
        assert restored.components["sensors"]["antenna_array"].health == 33.33

    def test_event_history_preserved(self):
        model = _model()
        model.apply_damage("engines", 10.0, "fire", tick=99, rng=_fixed_rng())
        data = model.serialise()
        restored = DamageModel.deserialise(data)
        assert restored.event_history[0].tick == 99
        assert restored.event_history[0].cause == "fire"
