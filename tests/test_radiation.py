"""
Tests for radiation system — v0.08 B.4.

Covers: radiation sources (reactor, shields, nuclear), radiation zone tiers,
decontamination teams, cross-station effects (engineering efficiency, sensor
penalty, radiation sickness), integration (serialise, vent mechanics), and constants.
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


@dataclass
class FakePowerGrid:
    reactor_health: float = 100.0
    reactor_max: float = 100.0


class FakeShip:
    def __init__(self, reactor_health: float = 100.0, shield_health: float = 100.0):
        self.systems = {
            "engines": FakeShipSystem("engines"),
            "beams": FakeShipSystem("beams"),
            "torpedoes": FakeShipSystem("torpedoes"),
            "shields": FakeShipSystem("shields", health=shield_health),
            "sensors": FakeShipSystem("sensors"),
            "manoeuvring": FakeShipSystem("manoeuvring"),
            "flight_deck": FakeShipSystem("flight_deck"),
            "ecm_suite": FakeShipSystem("ecm_suite"),
            "point_defence": FakeShipSystem("point_defence"),
        }
        self._reactor_health = reactor_health

    @property
    def reactor_health(self):
        return self._reactor_health


# Patch the power grid lookup for tests
_test_power_grid: FakePowerGrid | None = None


def _patch_power_grid(monkeypatch, reactor_health: float):
    global _test_power_grid
    _test_power_grid = FakePowerGrid(reactor_health=reactor_health)
    import server.game_loop_engineering as gle
    monkeypatch.setattr(gle, "get_power_grid", lambda: _test_power_grid)


def setup_function():
    glatm.reset()


# ---------------------------------------------------------------------------
# B.4.1 Radiation Sources
# ---------------------------------------------------------------------------


def test_reactor_below_60_leaks_to_engineering(monkeypatch):
    """Reactor below 60% health leaks radiation to engineering deck rooms."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    _patch_power_grid(monkeypatch, 50.0)
    ship = FakeShip(reactor_health=50.0)

    # Call radiation source tick directly to avoid vent exchange spreading
    glatm._tick_radiation_sources(interior, 10.0, ship)

    # Engineering rooms should have radiation
    for room_id, room in interior.rooms.items():
        atm = glatm.get_atmosphere(room_id)
        if room.deck == "engineering":
            assert atm.radiation > 0.0, f"Room {room_id} on engineering deck should have radiation"
        else:
            assert atm.radiation == 0.0, f"Room {room_id} should NOT have radiation from mild leak"


def test_reactor_below_30_leaks_to_adjacent(monkeypatch):
    """Reactor below 30% leaks to engineering AND adjacent deck rooms."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    _patch_power_grid(monkeypatch, 20.0)
    ship = FakeShip(reactor_health=20.0)

    # Call radiation source tick directly to isolate the leak
    glatm._tick_radiation_sources(interior, 10.0, ship)

    eng_rooms = [rid for rid, r in interior.rooms.items() if r.deck == "engineering"]
    med_rooms = [rid for rid, r in interior.rooms.items() if r.deck == "medical"]

    # Engineering rooms
    for rid in eng_rooms:
        atm = glatm.get_atmosphere(rid)
        assert atm.radiation > 0.0

    # Adjacent (medical deck, deck_number 4 vs engineering 5) should also have radiation
    for rid in med_rooms:
        atm = glatm.get_atmosphere(rid)
        assert atm.radiation > 0.0, f"Room {rid} on medical (adjacent) should have radiation"


def test_reactor_above_60_no_leak(monkeypatch):
    """Reactor at 70% health should not leak radiation."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    _patch_power_grid(monkeypatch, 70.0)
    ship = FakeShip(reactor_health=70.0)

    glatm.tick(interior, 10.0, ship=ship)

    for room_id in interior.rooms:
        atm = glatm.get_atmosphere(room_id)
        assert atm.radiation == 0.0


def test_shield_below_25_leaks_to_outer_decks(monkeypatch):
    """Shields below 25% health leak radiation to outer deck rooms (weapons/shields)."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    _patch_power_grid(monkeypatch, 100.0)  # reactor fine
    ship = FakeShip(reactor_health=100.0, shield_health=20.0)

    # Call radiation source tick directly
    glatm._tick_radiation_sources(interior, 10.0, ship)

    for room_id, room in interior.rooms.items():
        atm = glatm.get_atmosphere(room_id)
        if room.deck in ("weapons", "shields"):
            assert atm.radiation > 0.0, f"Room {room_id} on {room.deck} should have radiation"


def test_shield_above_25_no_leak(monkeypatch):
    """Shields at 30% health should not leak radiation."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    _patch_power_grid(monkeypatch, 100.0)
    ship = FakeShip(reactor_health=100.0, shield_health=30.0)

    glatm.tick(interior, 10.0, ship=ship)

    for room_id, room in interior.rooms.items():
        atm = glatm.get_atmosphere(room_id)
        if room.deck in ("weapons", "shields"):
            assert atm.radiation == 0.0


def test_nuclear_impact_radiation():
    """Nuclear torpedo impact: hit deck → 80%, adjacent decks → 40%."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)

    glatm.apply_nuclear_radiation(interior, "weapons")

    # Find the deck_number for the weapons deck
    weapons_deck_num = None
    for room in interior.rooms.values():
        if room.deck == "weapons":
            weapons_deck_num = room.deck_number
            break

    for room_id, room in interior.rooms.items():
        atm = glatm.get_atmosphere(room_id)
        if room.deck == "weapons":
            # Hit deck
            assert atm.radiation >= glatm.NUCLEAR_HIT_RADIATION
        elif abs(room.deck_number - weapons_deck_num) == 1:
            # Adjacent deck_numbers
            assert atm.radiation >= glatm.NUCLEAR_ADJACENT_RADIATION


# ---------------------------------------------------------------------------
# B.4.2 Radiation Zones
# ---------------------------------------------------------------------------


def test_green_zone_no_damage():
    """Radiation below AMBER threshold → no crew damage."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    atm = glatm.get_atmosphere(rid)
    atm.radiation = 5.0  # green zone

    penalties = glatm.get_atmosphere_penalties(interior)
    if rid in penalties:
        assert penalties[rid]["crew_hp_rate"] == 0.0


def test_amber_zone_damage_rate():
    """Radiation in AMBER zone (11–30) → 0.5 HP/60s rate."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    atm = glatm.get_atmosphere(rid)
    atm.radiation = 20.0  # amber zone

    penalties = glatm.get_atmosphere_penalties(interior)
    assert rid in penalties
    assert abs(penalties[rid]["crew_hp_rate"] - glatm.RAD_AMBER_HP_RATE) < 0.001


def test_orange_zone_damage_rate():
    """Radiation in ORANGE zone (31–60) → 1 HP/30s rate."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    atm = glatm.get_atmosphere(rid)
    atm.radiation = 45.0  # orange zone

    penalties = glatm.get_atmosphere_penalties(interior)
    assert rid in penalties
    assert abs(penalties[rid]["crew_hp_rate"] - glatm.RAD_ORANGE_HP_RATE) < 0.001


def test_red_zone_damage_rate():
    """Radiation in RED zone (61–100) → 3 HP/10s rate."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    atm = glatm.get_atmosphere(rid)
    atm.radiation = 75.0  # red zone

    penalties = glatm.get_atmosphere_penalties(interior)
    assert rid in penalties
    assert abs(penalties[rid]["crew_hp_rate"] - glatm.RAD_RED_HP_RATE) < 0.01


# ---------------------------------------------------------------------------
# B.4.3 Decon Teams
# ---------------------------------------------------------------------------


def test_dispatch_creates_team():
    """dispatch_decon_team creates a team entry."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))

    result = glatm.dispatch_decon_team(rid)
    assert result is True
    assert rid in glatm.get_decon_teams()


def test_cancel_removes_team():
    """cancel_decon_team removes the team."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))

    glatm.dispatch_decon_team(rid)
    result = glatm.cancel_decon_team(rid)
    assert result is True
    assert rid not in glatm.get_decon_teams()


def test_decon_team_reduces_radiation():
    """Decon team reduces radiation by 10% every 30s."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    atm = glatm.get_atmosphere(rid)
    atm.radiation = 50.0

    glatm.dispatch_decon_team(rid)

    # Tick for 30 seconds (DECON_INTERVAL)
    events = glatm.tick(interior, 30.0)

    atm = glatm.get_atmosphere(rid)
    assert atm.radiation <= 40.5  # 50 - 10 + possible minor drift from scrubbing


def test_decon_team_damage_reduction():
    """Decon team gives 50% reduced crew damage in the room."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    atm = glatm.get_atmosphere(rid)
    atm.radiation = 75.0  # red zone

    # Without decon team
    penalties_no_decon = glatm.get_atmosphere_penalties(interior)
    hp_rate_no_decon = penalties_no_decon[rid]["crew_hp_rate"]

    # With decon team
    glatm.dispatch_decon_team(rid)
    penalties_with_decon = glatm.get_atmosphere_penalties(interior)
    hp_rate_with_decon = penalties_with_decon[rid]["crew_hp_rate"]

    assert abs(hp_rate_with_decon - hp_rate_no_decon * 0.5) < 0.001


def test_decon_team_serialise_roundtrip():
    """Decon team state survives serialise/deserialise."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    atm = glatm.get_atmosphere(rid)
    atm.radiation = 40.0

    glatm.dispatch_decon_team(rid)
    # Tick a bit so elapsed > 0
    glatm.tick(interior, 5.0)

    data = glatm.serialise()
    glatm.reset()
    glatm.deserialise(data)

    teams = glatm.get_decon_teams()
    assert rid in teams
    assert teams[rid] > 0.0


# ---------------------------------------------------------------------------
# B.4.4 Cross-Station Effects
# ---------------------------------------------------------------------------


def test_engineering_radiation_reduces_crew_efficiency():
    """Radiation on engineering deck rooms → crew efficiency penalty."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)

    # Find an engineering room
    eng_room = None
    for rid, room in interior.rooms.items():
        if room.deck == "engineering":
            eng_room = rid
            break
    assert eng_room is not None

    atm = glatm.get_atmosphere(eng_room)
    atm.radiation = 20.0  # amber zone

    penalties = glatm.get_atmosphere_penalties(interior)
    assert eng_room in penalties
    assert penalties[eng_room]["crew_eff_penalty"] >= glatm.RAD_ENGINEERING_EFF_PENALTY


def test_sensor_radiation_penalty():
    """Radiation on sensors deck → sensor accuracy penalty up to 30%."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)

    # Set radiation on all sensor deck rooms
    for rid, room in interior.rooms.items():
        if room.deck == "sensors":
            atm = glatm.get_atmosphere(rid)
            atm.radiation = 100.0

    penalty = glatm.get_sensor_radiation_penalty(interior)
    assert abs(penalty - glatm.RAD_SENSOR_MAX_PENALTY) < 0.01


def test_sensor_no_penalty_below_threshold():
    """No sensor penalty when radiation is in green zone."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)

    penalty = glatm.get_sensor_radiation_penalty(interior)
    assert penalty == 0.0


def test_radiation_sickness_amber_exposure():
    """Radiation sickness event after 3min exposure in amber zone."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)

    # Set amber radiation on engineering deck
    for rid, room in interior.rooms.items():
        if room.deck == "engineering":
            atm = glatm.get_atmosphere(rid)
            atm.radiation = 20.0  # amber zone

    # Tick for 180 seconds (amber sickness threshold)
    all_events = []
    # Large single tick to cross the threshold
    events = glatm.tick(interior, 181.0)
    all_events.extend(events)

    sickness_events = [e for e in all_events if e.get("type") == "radiation_sickness"]
    assert len(sickness_events) > 0
    assert sickness_events[0]["severity"] == "amber"


def test_radiation_sickness_orange_exposure():
    """Radiation sickness event after 60s exposure in orange zone."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)

    # Set orange radiation on a deck
    for rid, room in interior.rooms.items():
        if room.deck == "engineering":
            atm = glatm.get_atmosphere(rid)
            atm.radiation = 45.0  # orange zone

    events = glatm.tick(interior, 61.0)
    sickness_events = [e for e in events if e.get("type") == "radiation_sickness"]
    assert len(sickness_events) > 0
    assert sickness_events[0]["severity"] == "orange"


def test_radiation_sickness_red_immediate():
    """Red zone radiation → immediate sickness event."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)

    for rid, room in interior.rooms.items():
        if room.deck == "engineering":
            atm = glatm.get_atmosphere(rid)
            atm.radiation = 75.0  # red zone

    events = glatm.tick(interior, 0.1)
    sickness_events = [e for e in events if e.get("type") == "radiation_sickness"]
    assert len(sickness_events) > 0
    assert sickness_events[0]["severity"] == "red"


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


def test_reactor_repair_stops_leak(monkeypatch):
    """Reactor repair above 60% stops leak."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    _patch_power_grid(monkeypatch, 50.0)
    ship = FakeShip(reactor_health=50.0)

    # Apply radiation source directly
    glatm._tick_radiation_sources(interior, 10.0, ship)

    eng_room = None
    for rid, room in interior.rooms.items():
        if room.deck == "engineering":
            eng_room = rid
            break

    rad_before = glatm.get_atmosphere(eng_room).radiation
    assert rad_before > 0.0

    # "Repair" reactor above threshold
    _patch_power_grid(monkeypatch, 65.0)
    ship2 = FakeShip(reactor_health=65.0)

    # Apply radiation source again — should NOT add more radiation
    glatm._tick_radiation_sources(interior, 10.0, ship2)
    rad_after = glatm.get_atmosphere(eng_room).radiation
    # Should be exactly the same since reactor is above threshold
    assert rad_after == rad_before


def test_sealed_vents_block_radiation_spread():
    """Sealed vents block radiation spread between rooms."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)

    # Find two connected rooms
    room_a = None
    room_b = None
    for rid, room in interior.rooms.items():
        if room.connections:
            room_a = rid
            room_b = room.connections[0]
            break

    # Seal the vent between them
    glatm.set_vent_state(room_a, room_b, "sealed")

    # Set radiation in room A
    atm_a = glatm.get_atmosphere(room_a)
    atm_a.radiation = 80.0

    # Tick
    glatm.tick(interior, 10.0)

    # Room B should have less radiation than if vents were open
    atm_b = glatm.get_atmosphere(room_b)
    # With sealed vents, no exchange should occur between these specific rooms
    # (Other rooms connected to room_b via open vents may have exchanged some)
    # The key assertion is that room_a's radiation didn't transfer directly
    assert atm_b.radiation < 30.0  # significantly less than 80


def test_emergency_vent_clears_radiation():
    """Emergency vent to space clears radiation (existing B.3 mechanic)."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    atm = glatm.get_atmosphere(rid)
    atm.radiation = 80.0

    glatm.emergency_vent_to_space(rid)

    atm = glatm.get_atmosphere(rid)
    assert atm.radiation == 0.0


def test_exposure_tracking_serialise_roundtrip():
    """Radiation exposure tracking survives serialise/deserialise."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)

    # Set radiation on engineering
    for rid, room in interior.rooms.items():
        if room.deck == "engineering":
            atm = glatm.get_atmosphere(rid)
            atm.radiation = 25.0

    # Tick to build exposure
    glatm.tick(interior, 30.0)

    data = glatm.serialise()
    exposure_before = dict(glatm.get_radiation_exposure())
    assert "engineering" in exposure_before

    glatm.reset()
    glatm.deserialise(data)

    exposure_after = glatm.get_radiation_exposure()
    assert abs(exposure_after.get("engineering", 0.0) - exposure_before["engineering"]) < 0.1


def test_radiation_in_broadcast_state():
    """Radiation zone tier appears in build_atmosphere_state broadcast."""
    interior = fresh_interior()
    glatm.init_atmosphere(interior)
    rid = next(iter(interior.rooms))
    atm = glatm.get_atmosphere(rid)
    atm.radiation = 50.0  # orange zone

    state = glatm.build_atmosphere_state(interior)
    assert state["rooms"][rid]["rad_zone"] == "orange"
    assert state["rooms"][rid]["radiation"] == 50.0


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_reactor_leak_threshold():
    assert glatm.REACTOR_LEAK_THRESHOLD == 60.0
    assert glatm.REACTOR_SERIOUS_THRESHOLD == 30.0


def test_nuclear_radiation_levels():
    assert glatm.NUCLEAR_HIT_RADIATION == 80.0
    assert glatm.NUCLEAR_ADJACENT_RADIATION == 40.0


def test_zone_tier_thresholds():
    assert glatm.RAD_AMBER_THRESHOLD == 11.0
    assert glatm.RAD_ORANGE_THRESHOLD == 31.0
    assert glatm.RAD_RED_THRESHOLD == 61.0
