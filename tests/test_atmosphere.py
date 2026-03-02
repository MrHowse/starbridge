"""
Tests for atmosphere system — v0.08 B.3.

Covers: AtmosphereState, Breach, init, life support, fire effects, coolant leaks,
hull breach decompression, force field, bulkhead seal, evacuation, ventilation
exchange, filtered scrub, emergency space vent, cross-station penalties,
fire O2 starvation, serialise/deserialise round-trip, broadcast state builder.
"""
from __future__ import annotations

from dataclasses import dataclass

import server.game_loop_atmosphere as glatm
from server.models.interior import make_default_interior


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh_interior():
    return make_default_interior()


@dataclass
class FakeShipSystem:
    name: str
    power: float = 100.0
    health: float = 100.0

    @property
    def efficiency(self) -> float:
        return (self.power / 100.0) * (self.health / 100.0)


class FakeShip:
    def __init__(self, efficiency: float = 1.0):
        self.systems = {
            "engines": FakeShipSystem("engines", 100.0, efficiency * 100.0),
        }


@dataclass
class FakeFire:
    room_id: str
    intensity: int = 1


def setup_function():
    glatm.reset()


# ---------------------------------------------------------------------------
# B.3.1 Atmospheric Model
# ---------------------------------------------------------------------------


def test_init_sets_normal_values():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    atm = glatm.get_atmosphere(rid)
    assert atm is not None
    assert atm.oxygen_percent == 21.0
    assert atm.pressure_kpa == 101.3
    assert atm.temperature_c == 22.0
    assert atm.contamination_level == 0.0


def test_init_creates_vent_connections():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    # Should have at least some vent connections
    assert len(glatm._vent_states) > 0
    # All should start as open
    for state in glatm._vent_states.values():
        assert state == "open"


def test_life_support_restores_o2():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    atm = glatm.get_atmosphere(rid)
    atm.oxygen_percent = 10.0
    # Tick for 10 seconds (should restore ~2% at full efficiency)
    for _ in range(100):
        glatm.tick(interior, 0.1, ship=FakeShip(1.0))
    atm = glatm.get_atmosphere(rid)
    assert atm.oxygen_percent > 10.0
    assert atm.oxygen_percent <= 21.0


def test_life_support_restores_pressure():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    atm = glatm.get_atmosphere(rid)
    atm.pressure_kpa = 50.0
    for _ in range(100):
        glatm.tick(interior, 0.1, ship=FakeShip(1.0))
    atm = glatm.get_atmosphere(rid)
    assert atm.pressure_kpa > 50.0
    assert atm.pressure_kpa <= 101.3


def test_life_support_scales_with_efficiency():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    # Full efficiency
    atm_full = glatm.get_atmosphere(rid)
    atm_full.oxygen_percent = 10.0
    glatm.tick(interior, 1.0, ship=FakeShip(1.0))
    o2_after_full = atm_full.oxygen_percent

    glatm.reset()
    glatm.init_atmosphere(interior)
    atm_half = glatm.get_atmosphere(rid)
    atm_half.oxygen_percent = 10.0
    glatm.tick(interior, 1.0, ship=FakeShip(0.5))
    o2_after_half = atm_half.oxygen_percent

    # Half efficiency should restore less
    assert o2_after_full > o2_after_half


def test_fire_raises_temperature():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    fire = FakeFire(room_id=rid, intensity=3)
    initial_temp = glatm.get_atmosphere(rid).temperature_c
    glatm.tick(interior, 1.0, fires={rid: fire})
    assert glatm.get_atmosphere(rid).temperature_c > initial_temp


def test_fire_drops_o2():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    fire = FakeFire(room_id=rid, intensity=3)
    # Use 0 efficiency ship to disable life support restoration
    glatm.tick(interior, 1.0, ship=FakeShip(0.0), fires={rid: fire})
    assert glatm.get_atmosphere(rid).oxygen_percent < 21.0


def test_fire_raises_smoke():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    fire = FakeFire(room_id=rid, intensity=2)
    glatm.tick(interior, 1.0, fires={rid: fire})
    assert glatm.get_atmosphere(rid).smoke > 0.0


def test_coolant_raises_contamination():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm.start_coolant_leak(rid)
    glatm.tick(interior, 1.0)
    atm = glatm.get_atmosphere(rid)
    assert atm.coolant > 0.0
    assert atm.contamination_type == "coolant"


# ---------------------------------------------------------------------------
# B.3.2 Hull Breach
# ---------------------------------------------------------------------------


def test_minor_breach_decompression_rate():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm.create_breach(rid, "minor", interior)
    initial_p = glatm.get_atmosphere(rid).pressure_kpa
    glatm.tick(interior, 1.0)
    # Minor: 3.38 kPa/s
    assert glatm.get_atmosphere(rid).pressure_kpa < initial_p
    expected = initial_p - glatm.MINOR_BREACH_RATE
    assert abs(glatm.get_atmosphere(rid).pressure_kpa - expected) < 0.5


def test_major_breach_decompression_rate():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm.create_breach(rid, "major", interior)
    # Seal all vents to prevent adjacent rooms from equalising pressure
    for key in glatm._vent_states:
        glatm._vent_states[key] = "sealed"
    initial_p = glatm.get_atmosphere(rid).pressure_kpa
    # Use 0 efficiency ship to disable life support restoration
    glatm.tick(interior, 1.0, ship=FakeShip(0.0))
    # Major: 10 kPa/s, no LS restoration, no vent exchange
    expected = initial_p - glatm.MAJOR_BREACH_RATE
    assert abs(glatm.get_atmosphere(rid).pressure_kpa - expected) < 0.1


def test_force_field_stops_decompression():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm.create_breach(rid, "major", interior)
    glatm.apply_force_field(rid)
    initial_p = glatm.get_atmosphere(rid).pressure_kpa
    glatm.tick(interior, 1.0)
    # Force field active → no decompression
    assert glatm.get_atmosphere(rid).pressure_kpa >= initial_p


def test_force_field_expires_after_120s():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm.create_breach(rid, "minor", interior)
    glatm.apply_force_field(rid)
    breach = glatm._breaches[rid]
    assert breach.force_field_active
    assert breach.force_field_timer == 120.0
    # Tick for 121 seconds
    for _ in range(1210):
        glatm.tick(interior, 0.1)
    assert not glatm._breaches[rid].force_field_active


def test_bulkhead_seal_takes_5s():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm.create_breach(rid, "minor", interior)
    glatm.seal_bulkhead(rid)
    breach = glatm._breaches[rid]
    assert not breach.bulkhead_sealed
    assert breach.bulkhead_timer == 5.0
    # Tick for 6 seconds
    for _ in range(60):
        glatm.tick(interior, 0.1)
    assert glatm._breaches[rid].bulkhead_sealed


def test_bulkhead_seal_is_permanent():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm.create_breach(rid, "minor", interior)
    glatm.seal_bulkhead(rid)
    # Wait for seal to complete
    for _ in range(60):
        glatm.tick(interior, 0.1)
    assert glatm._breaches[rid].bulkhead_sealed
    # Should stop decompression permanently
    atm = glatm.get_atmosphere(rid)
    p_before = atm.pressure_kpa
    glatm.tick(interior, 1.0)
    assert glatm.get_atmosphere(rid).pressure_kpa >= p_before


def test_evacuation_takes_10s():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm.create_breach(rid, "minor", interior)
    glatm.order_evacuation(rid, interior)
    breach = glatm._breaches[rid]
    assert breach.evacuating
    assert breach.evacuation_timer == 10.0
    # Tick for 11 seconds
    events = []
    for _ in range(110):
        events.extend(glatm.tick(interior, 0.1))
    assert not glatm._breaches[rid].evacuating
    assert any(e["type"] == "evacuation_complete" for e in events)


def test_vacuum_crew_damage_event():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    atm = glatm.get_atmosphere(rid)
    atm.pressure_kpa = 0.0
    atm.oxygen_percent = 0.0
    # Create breach so LS won't restore; seal all vents so adjacent rooms don't push pressure in
    glatm.create_breach(rid, "major", interior)
    for key in glatm._vent_states:
        glatm._vent_states[key] = "sealed"
    events = glatm.tick(interior, 1.0, ship=FakeShip(0.0))
    assert any(e["type"] == "vacuum_damage" and e["room_id"] == rid for e in events)


def test_vacuum_equipment_damage():
    """Vacuum rooms emit vacuum_damage events with dt."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    atm = glatm.get_atmosphere(rid)
    atm.pressure_kpa = 0.0
    atm.oxygen_percent = 0.0
    # Create breach so LS won't restore; seal all vents
    glatm.create_breach(rid, "major", interior)
    for key in glatm._vent_states:
        glatm._vent_states[key] = "sealed"
    events = glatm.tick(interior, 0.5, ship=FakeShip(0.0))
    vacuum_events = [e for e in events if e["type"] == "vacuum_damage" and e["room_id"] == rid]
    assert len(vacuum_events) >= 1
    assert vacuum_events[0]["dt"] == 0.5


# ---------------------------------------------------------------------------
# B.3.3 Ventilation
# ---------------------------------------------------------------------------


def _find_connected_pair(interior):
    """Return (room_a_id, room_b_id) for the first connected pair."""
    for rid, room in interior.rooms.items():
        if room.connections:
            return rid, room.connections[0]
    raise RuntimeError("No connected rooms found")


def test_vent_state_cycle():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    a, b = _find_connected_pair(interior)
    key = glatm._vent_key(a, b)
    assert glatm._vent_states[key] == "open"
    result = glatm.cycle_vent_state(a, b)
    assert result == "filtered"
    assert glatm._vent_states[key] == "filtered"
    result = glatm.cycle_vent_state(a, b)
    assert result == "sealed"
    result = glatm.cycle_vent_state(a, b)
    assert result == "open"


def test_open_exchanges_atmosphere():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    a, b = _find_connected_pair(interior)
    # Set different O2 levels
    glatm._atmosphere[a].oxygen_percent = 21.0
    glatm._atmosphere[b].oxygen_percent = 5.0
    glatm.set_vent_state(a, b, "open")
    glatm.tick(interior, 1.0)
    # Should equalise somewhat
    assert glatm._atmosphere[a].oxygen_percent < 21.0
    assert glatm._atmosphere[b].oxygen_percent > 5.0


def test_filtered_scrubs_contaminants():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    a, b = _find_connected_pair(interior)
    glatm._atmosphere[a].smoke = 50.0
    glatm.set_vent_state(a, b, "filtered")
    glatm.tick(interior, 1.0)
    assert glatm._atmosphere[a].smoke < 50.0


def test_sealed_blocks_exchange():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    a, b = _find_connected_pair(interior)
    glatm._atmosphere[a].oxygen_percent = 21.0
    glatm._atmosphere[b].oxygen_percent = 5.0
    # Seal all vents
    for key in glatm._vent_states:
        glatm._vent_states[key] = "sealed"
    # Use 0 efficiency to prevent LS from restoring O2
    glatm.tick(interior, 1.0, ship=FakeShip(0.0))
    # Should not exchange
    assert glatm._atmosphere[a].oxygen_percent == 21.0
    assert glatm._atmosphere[b].oxygen_percent == 5.0


def test_sealed_blocks_contam_spread():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    a, b = _find_connected_pair(interior)
    glatm._atmosphere[a].smoke = 80.0
    glatm._atmosphere[b].smoke = 0.0
    for key in glatm._vent_states:
        glatm._vent_states[key] = "sealed"
    glatm.tick(interior, 1.0)
    assert glatm._atmosphere[b].smoke == 0.0


def test_emergency_space_vent_clears_atmosphere():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm._atmosphere[rid].smoke = 80.0
    glatm._atmosphere[rid].coolant = 50.0
    glatm.emergency_vent_to_space(rid)
    assert glatm._atmosphere[rid].pressure_kpa == 0.0
    assert glatm._atmosphere[rid].oxygen_percent == 0.0
    assert glatm._atmosphere[rid].smoke == 0.0
    assert glatm._atmosphere[rid].coolant == 0.0


def test_space_vent_repressurisation():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm.emergency_vent_to_space(rid)
    # Cancel the vent — should begin repressurising
    glatm.cancel_space_vent(rid)
    # Tick for a while — life support should restore pressure
    for _ in range(500):
        glatm.tick(interior, 0.1, ship=FakeShip(1.0))
    atm = glatm.get_atmosphere(rid)
    assert atm.pressure_kpa > 0.0


# ---------------------------------------------------------------------------
# B.3.4 Cross-Station Effects
# ---------------------------------------------------------------------------


def test_low_o2_crew_penalty():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm._atmosphere[rid].oxygen_percent = 10.0
    penalties = glatm.get_atmosphere_penalties()
    assert rid in penalties
    assert penalties[rid]["crew_eff_penalty"] == glatm.LOW_O2_PENALTY


def test_low_o2_hp_damage():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm._atmosphere[rid].oxygen_percent = 10.0
    penalties = glatm.get_atmosphere_penalties()
    assert penalties[rid]["crew_hp_rate"] == glatm.LOW_O2_HP_RATE


def test_high_temp_crew_penalty():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm._atmosphere[rid].temperature_c = 50.0
    penalties = glatm.get_atmosphere_penalties()
    assert rid in penalties
    assert penalties[rid]["crew_eff_penalty"] == glatm.HIGH_TEMP_PENALTY


def test_high_temp_equip_degrade():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm._atmosphere[rid].temperature_c = 50.0
    penalties = glatm.get_atmosphere_penalties()
    assert penalties[rid]["equip_degrade_rate"] == glatm.HIGH_TEMP_EQUIP_RATE


def test_high_contam_crew_damage():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm._atmosphere[rid].radiation = 60.0
    penalties = glatm.get_atmosphere_penalties()
    assert rid in penalties
    assert penalties[rid]["crew_hp_rate"] > 0


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


def test_fire_o2_starvation_extinguishes():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm._atmosphere[rid].oxygen_percent = 3.0
    fire = FakeFire(room_id=rid, intensity=3)
    fires = {rid: fire}
    events = glatm.tick(interior, 1.0, fires=fires)
    assert fire.intensity == 0
    assert any(e["type"] == "fire_starved" for e in events)


def test_breach_sets_room_decompressed():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm.create_breach(rid, "major", interior)
    # Tick until vacuum
    for _ in range(200):
        glatm.tick(interior, 0.1)
    assert interior.rooms[rid].state == "decompressed"


def test_serialise_deserialise_round_trip():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm._atmosphere[rid].oxygen_percent = 15.0
    glatm._atmosphere[rid].smoke = 30.0
    glatm.create_breach(rid, "minor", interior)
    glatm.apply_force_field(rid)
    glatm.start_coolant_leak(rid)

    data = glatm.serialise()
    glatm.reset()
    glatm.deserialise(data)

    atm = glatm.get_atmosphere(rid)
    assert atm is not None
    assert atm.oxygen_percent == 15.0
    assert atm.smoke == 30.0
    breach = glatm._breaches.get(rid)
    assert breach is not None
    assert breach.severity == "minor"
    assert breach.force_field_active
    assert rid in glatm._coolant_leaks


def test_build_atmosphere_state():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm._atmosphere[rid].oxygen_percent = 18.0
    glatm.create_breach(rid, "minor", interior)
    state = glatm.build_atmosphere_state(interior)
    assert "rooms" in state
    assert rid in state["rooms"]
    assert state["rooms"][rid]["o2"] == 18.0
    assert "breaches" in state
    assert rid in state["breaches"]
    assert state["breaches"][rid]["severity"] == "minor"


# ---------------------------------------------------------------------------
# B.3.2.1 Breach Causes
# ---------------------------------------------------------------------------


def test_torpedo_breach_chance():
    assert glatm.TORPEDO_BREACH_CHANCE == 0.70


def test_beam_breach_chance():
    assert glatm.HEAVY_BEAM_BREACH_CHANCE == 0.30


def test_breach_visible_to_engineering():
    """Breaches set room state to damaged, visible in interior."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm.create_breach(rid, "minor", interior)
    assert interior.rooms[rid].state == "damaged"


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


def test_breach_upgrade_minor_to_major():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm.create_breach(rid, "minor", interior)
    assert glatm._breaches[rid].severity == "minor"
    glatm.create_breach(rid, "major", interior)
    assert glatm._breaches[rid].severity == "major"


def test_unseal_bulkhead():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm.create_breach(rid, "minor", interior)
    glatm.seal_bulkhead(rid)
    for _ in range(60):
        glatm.tick(interior, 0.1)
    assert glatm._breaches[rid].bulkhead_sealed
    assert glatm.unseal_bulkhead(rid) is True
    assert not glatm._breaches[rid].bulkhead_sealed


def test_get_repair_speed_modifier_vacuum():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm._atmosphere[rid].pressure_kpa = 0.0
    assert glatm.get_repair_speed_modifier(rid) == glatm.EVA_REPAIR_MULT


def test_get_repair_speed_modifier_low_o2():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm._atmosphere[rid].oxygen_percent = 10.0
    assert glatm.get_repair_speed_modifier(rid) == 1.0 + glatm.LOW_O2_REPAIR_PENALTY


def test_get_repair_speed_modifier_normal():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    assert glatm.get_repair_speed_modifier(rid) == 1.0


def test_deck_atmosphere_summary():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    summary = glatm.get_deck_atmosphere_summary(interior)
    assert len(summary) > 0
    for deck_name, data in summary.items():
        assert "avg_o2" in data
        assert "avg_pressure" in data
        assert "avg_temp" in data
        assert "max_contam" in data
        assert "contam_type" in data
        assert "breach_count" in data
        assert data["avg_o2"] == 21.0
        assert data["avg_pressure"] == 101.3


def test_contamination_type_property():
    atm = glatm.AtmosphereState()
    assert atm.contamination_type == "none"
    atm.radiation = 50.0
    assert atm.contamination_type == "radiation"
    atm.smoke = 60.0
    assert atm.contamination_type == "smoke"


def test_is_vacuum():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    assert not glatm.is_vacuum(rid)
    glatm._atmosphere[rid].pressure_kpa = 0.0
    assert glatm.is_vacuum(rid)


def test_life_support_restores_temp():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm._atmosphere[rid].temperature_c = 50.0
    for _ in range(100):
        glatm.tick(interior, 0.1, ship=FakeShip(1.0))
    atm = glatm.get_atmosphere(rid)
    assert atm.temperature_c < 50.0


def test_stop_coolant_leak():
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    glatm.start_coolant_leak(rid)
    assert rid in glatm._coolant_leaks
    glatm.stop_coolant_leak(rid)
    assert rid not in glatm._coolant_leaks
