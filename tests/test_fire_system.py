"""
Tests for fire intensity model — v0.08 B.2.

Covers: Fire dataclass, escalation, spread, four suppression methods,
suppressant resource, cross-station effects, DCT+fire coexistence,
serialise/deserialise round-trips.
"""
from __future__ import annotations

import pytest

import server.game_loop_hazard_control as glhc
from server.models.interior import make_default_interior
from server.models.resources import ResourceStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh_interior():
    return make_default_interior()


def fresh_resources(**overrides):
    """Return a ResourceStore with suppressant pre-loaded."""
    rs = ResourceStore()
    rs.suppressant = overrides.get("suppressant", 20.0)
    rs.suppressant_max = overrides.get("suppressant_max", 20.0)
    rs.repair_materials = overrides.get("repair_materials", 50.0)
    rs.repair_materials_max = overrides.get("repair_materials_max", 60.0)
    return rs


def _room_with_connections(interior):
    """Return the ID of the first room that has at least one connection."""
    for rid, room in interior.rooms.items():
        if room.connections:
            return rid
    raise RuntimeError("No rooms with connections found")


def setup_function():
    glhc.reset()


# ---------------------------------------------------------------------------
# Fire model — start_fire
# ---------------------------------------------------------------------------


def test_start_fire_creates_fire_entry():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    assert glhc.start_fire(rid, 2, interior) is True
    assert rid in glhc._fires
    assert glhc._fires[rid].intensity == 2
    assert interior.rooms[rid].state == "fire"


def test_start_fire_escalates_existing():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 2, interior)
    glhc.start_fire(rid, 4, interior)
    assert glhc._fires[rid].intensity == 4


def test_start_fire_does_not_downgrade():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 4, interior)
    glhc.start_fire(rid, 1, interior)
    assert glhc._fires[rid].intensity == 4


def test_fire_intensity_clamped_1_to_5():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 10, interior)
    assert glhc._fires[rid].intensity == 5
    glhc.reset()
    glhc.start_fire(rid, -2, interior)
    assert glhc._fires[rid].intensity == 1


def test_start_fire_on_decompressed_room_returns_false():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    interior.rooms[rid].state = "decompressed"
    assert glhc.start_fire(rid, 2, interior) is False
    assert rid not in glhc._fires


def test_start_fire_on_nonexistent_room_returns_false():
    interior = fresh_interior()
    assert glhc.start_fire("no_such_room", 2, interior) is False


# ---------------------------------------------------------------------------
# Fire escalation
# ---------------------------------------------------------------------------


def test_fire_escalation_45s_increments():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 1, interior)

    # Tick 44.9s — should still be intensity 1.
    glhc.tick(interior, 44.9)
    assert glhc._fires[rid].intensity == 1

    # Tick past 45s — should escalate to 2.
    glhc.tick(interior, 0.2)
    assert glhc._fires[rid].intensity == 2


def test_fire_escalation_caps_at_5():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 4, interior)

    # One escalation: 4 → 5.
    glhc.tick(interior, glhc.ESCALATION_INTERVAL + 0.1)
    assert glhc._fires[rid].intensity == 5

    # Another interval: should stay at 5.
    glhc.tick(interior, glhc.ESCALATION_INTERVAL + 0.1)
    assert glhc._fires[rid].intensity == 5


# ---------------------------------------------------------------------------
# Fire spread
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("intensity,expected_timer", [
    (1, 60.0), (2, 90.0), (3, 60.0), (4, 30.0), (5, 15.0),
])
def test_fire_spread_timer_matches_intensity(intensity, expected_timer):
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, intensity, interior)
    assert glhc._fires[rid].spread_timer == pytest.approx(expected_timer)


def test_cascade_fire_starts_at_source_minus_1():
    interior = fresh_interior()
    rid = _room_with_connections(interior)
    # Use intensity 5 with 15s spread timer — escalation won't change it (already max).
    glhc.start_fire(rid, 5, interior)
    glhc._rng.seed(0)

    # Advance past the spread timer (intensity 5 → 15s).
    glhc.tick(interior, 15.01)

    # Find the cascaded fire.
    adj_fires = {frid: f for frid, f in glhc._fires.items() if frid != rid}
    assert len(adj_fires) >= 1, "Should have spread to at least one adjacent room"
    for f in adj_fires.values():
        assert f.intensity == 4, "Cascade should be source_intensity - 1"


# ---------------------------------------------------------------------------
# Fire causes
# ---------------------------------------------------------------------------


def test_combat_fire_chance_triggers():
    """Hull damage events can create fires at intensity 2."""
    interior = fresh_interior()
    # Run many seeds to confirm fire creation happens.
    found_fire = False
    for seed in range(200):
        glhc.reset()
        for r in interior.rooms.values():
            r.state = "normal"
        glhc._rng.seed(seed)
        glhc.apply_hull_damage(glhc.HULL_DAMAGE_THRESHOLD, interior)
        if glhc._fires:
            found_fire = True
            fire = next(iter(glhc._fires.values()))
            assert fire.intensity == glhc.COMBAT_FIRE_INTENSITY
            break
    assert found_fire, "Expected at least one seed to trigger a fire"


# ---------------------------------------------------------------------------
# Crew effects
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("intensity,expected_penalty", [
    (1, 0.05), (2, 0.15), (3, 0.30), (4, 0.60), (5, 1.00),
])
def test_crew_eff_penalty_per_intensity(intensity, expected_penalty):
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, intensity, interior)
    penalties = glhc.get_fire_penalties(interior)
    deck = interior.rooms[rid].deck
    assert penalties[deck] == pytest.approx(expected_penalty)


def test_smoke_rooms_at_intensity_2_plus():
    interior = fresh_interior()
    rids = list(interior.rooms.keys())
    # Intensity 1: no smoke.
    glhc.start_fire(rids[0], 1, interior)
    assert rids[0] not in glhc.get_smoke_rooms()

    # Intensity 2: smoke.
    glhc.start_fire(rids[1], 2, interior)
    assert rids[1] in glhc.get_smoke_rooms()


# ---------------------------------------------------------------------------
# Suppression — localised
# ---------------------------------------------------------------------------


def test_local_suppress_reduces_by_2():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 4, interior)
    res = fresh_resources()

    assert glhc.suppress_local(rid, res) is True
    # Wait for suppression to complete (5s).
    glhc.tick(interior, glhc.LOCAL_SUPPRESS_TIME + 0.01)
    assert glhc._fires[rid].intensity == 2


def test_local_suppress_costs_1_suppressant():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 3, interior)
    res = fresh_resources(suppressant=5.0)

    glhc.suppress_local(rid, res)
    assert res.suppressant == pytest.approx(4.0)


def test_local_suppress_extinguishes_low_fire():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 1, interior)
    res = fresh_resources()

    glhc.suppress_local(rid, res)
    glhc.tick(interior, glhc.LOCAL_SUPPRESS_TIME + 0.01)
    # Cleanup pass removes fires at intensity <= 0.
    glhc.tick(interior, 0.01)

    assert rid not in glhc._fires
    assert interior.rooms[rid].state == "damaged"


def test_local_suppress_fails_no_suppressant():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 3, interior)
    res = fresh_resources(suppressant=0.0)

    assert glhc.suppress_local(rid, res) is False


def test_local_suppress_fails_no_fire():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    res = fresh_resources()
    assert glhc.suppress_local(rid, res) is False


# ---------------------------------------------------------------------------
# Suppression — deck-wide
# ---------------------------------------------------------------------------


def test_deck_suppress_reduces_all_by_1():
    interior = fresh_interior()
    # Start fires on two rooms of the same deck.
    rooms_on_deck = {}
    for rid, room in interior.rooms.items():
        rooms_on_deck.setdefault(room.deck, []).append(rid)
    deck_name = next(dk for dk, rids in rooms_on_deck.items() if len(rids) >= 2)
    r1, r2 = rooms_on_deck[deck_name][:2]

    glhc.start_fire(r1, 3, interior)
    glhc.start_fire(r2, 4, interior)
    res = fresh_resources()

    assert glhc.suppress_deck(deck_name, interior, res) is True
    # Wait for deck suppression to complete (15s).
    glhc.tick(interior, glhc.DECK_SUPPRESS_TIME + 0.01)

    assert glhc._fires[r1].intensity == 2
    assert glhc._fires[r2].intensity == 3


def test_deck_suppress_costs_3():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    deck = interior.rooms[rid].deck
    glhc.start_fire(rid, 2, interior)
    res = fresh_resources(suppressant=10.0)

    glhc.suppress_deck(deck, interior, res)
    assert res.suppressant == pytest.approx(7.0)


def test_deck_suppress_fails_no_fires_on_deck():
    interior = fresh_interior()
    # Pick a deck with no fires.
    deck = next(iter({r.deck for r in interior.rooms.values()}))
    res = fresh_resources()
    assert glhc.suppress_deck(deck, interior, res) is False


# ---------------------------------------------------------------------------
# Suppression — ventilation cutoff
# ---------------------------------------------------------------------------


def test_vent_reduces_by_1_every_20s():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 3, interior)

    assert glhc.vent_room(rid, interior) is True
    assert rid in glhc._vent_rooms

    # After 20s, intensity should drop by 1.
    glhc.tick(interior, 20.01)
    assert glhc._fires[rid].intensity == 2

    # After another 20s, drop again.
    glhc.tick(interior, 20.0)
    assert glhc._fires[rid].intensity == 1


def test_vent_extinguishes_fire():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 1, interior)
    glhc.vent_room(rid, interior)

    glhc.tick(interior, 20.01)
    # Cleanup.
    glhc.tick(interior, 0.01)
    assert rid not in glhc._fires


def test_vent_no_fire_returns_false():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    assert glhc.vent_room(rid, interior) is False


def test_cancel_vent():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 3, interior)
    glhc.vent_room(rid, interior)
    assert glhc.cancel_vent(rid) is True
    assert rid not in glhc._vent_rooms


def test_cancel_vent_not_active():
    assert glhc.cancel_vent("nonexistent") is False


# ---------------------------------------------------------------------------
# Suppression — manual fire team
# ---------------------------------------------------------------------------


def test_manual_team_reduces_by_1_every_20s():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 3, interior)
    glhc._rng.seed(99)  # Seed to avoid injury on this test.

    assert glhc.dispatch_fire_team(rid, interior) is True
    glhc.tick(interior, 20.01)
    assert glhc._fires[rid].intensity == 2


def test_manual_team_injury_chance():
    """Over enough cycles, at least one injury event should fire."""
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 5, interior)

    injuries = 0
    for seed in range(100):
        glhc.reset()
        for r in interior.rooms.values():
            r.state = "normal"
        glhc.start_fire(rid, 5, interior)
        glhc._rng.seed(seed)
        glhc.dispatch_fire_team(rid, interior)
        events = glhc.tick(interior, 20.01)
        injuries += sum(1 for e in events if e.get("type") == "fire_team_injury")
        if injuries > 0:
            break

    assert injuries > 0, "Expected at least one injury across 100 seeds"


def test_manual_team_no_fire_returns_false():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    assert glhc.dispatch_fire_team(rid, interior) is False


def test_cancel_fire_team():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 2, interior)
    glhc.dispatch_fire_team(rid, interior)
    assert glhc.cancel_fire_team(rid) is True
    assert rid not in glhc._fire_teams


def test_cancel_fire_team_not_active():
    assert glhc.cancel_fire_team("nonexistent") is False


# ---------------------------------------------------------------------------
# No suppressant blocks local and deck
# ---------------------------------------------------------------------------


def test_no_suppressant_blocks_local_and_deck():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    deck = interior.rooms[rid].deck
    glhc.start_fire(rid, 3, interior)
    res = fresh_resources(suppressant=0.0)

    assert glhc.suppress_local(rid, res) is False
    assert glhc.suppress_deck(deck, interior, res) is False

    # Vent and manual team should still work.
    assert glhc.vent_room(rid, interior) is True
    glhc.cancel_vent(rid)
    assert glhc.dispatch_fire_team(rid, interior) is True


# ---------------------------------------------------------------------------
# DCT + fire coexistence
# ---------------------------------------------------------------------------


def test_dct_on_fire_reduces_intensity():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 3, interior)
    glhc.dispatch_dct(rid, interior)

    # One DCT cycle should reduce intensity by 1.
    glhc.tick(interior, glhc.DCT_REPAIR_DURATION + 0.01)
    assert glhc._fires[rid].intensity == 2


def test_dct_continues_after_fire_extinguished():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 1, interior)
    glhc.dispatch_dct(rid, interior)

    # One DCT cycle: fire intensity 1 → 0, fire removed, room → "damaged".
    glhc.tick(interior, glhc.DCT_REPAIR_DURATION + 0.01)
    assert rid not in glhc._fires
    assert interior.rooms[rid].state == "damaged"

    # DCT should still be active to repair damaged → normal.
    assert rid in glhc._active_dcts
    glhc.tick(interior, glhc.DCT_REPAIR_DURATION + 0.01)
    assert interior.rooms[rid].state == "normal"
    assert rid not in glhc._active_dcts


# ---------------------------------------------------------------------------
# Serialise / deserialise round-trips
# ---------------------------------------------------------------------------


def test_fire_serialise_round_trip():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 3, interior)
    glhc._fires[rid].escalation_timer = 20.0
    glhc._fires[rid].spread_timer = 30.0

    data = glhc.serialise()
    glhc.reset()
    glhc.deserialise(data)

    assert rid in glhc._fires
    f = glhc._fires[rid]
    assert f.intensity == 3
    assert f.escalation_timer == pytest.approx(20.0)
    assert f.spread_timer == pytest.approx(30.0)


def test_vent_state_serialise_round_trip():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 2, interior)
    glhc.vent_room(rid, interior)

    data = glhc.serialise()
    glhc.reset()
    glhc.deserialise(data)

    assert rid in glhc._vent_rooms
    assert rid in glhc._fires


def test_fire_team_serialise_round_trip():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 2, interior)
    glhc.dispatch_fire_team(rid, interior)
    glhc._fire_teams[rid] = 10.5

    data = glhc.serialise()
    glhc.reset()
    glhc.deserialise(data)

    assert rid in glhc._fire_teams
    assert glhc._fire_teams[rid] == pytest.approx(10.5)


# ---------------------------------------------------------------------------
# build_dc_state includes fires
# ---------------------------------------------------------------------------


def test_build_dc_state_includes_fires():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 3, interior)

    state = glhc.build_dc_state(interior)
    assert "fires" in state
    assert rid in state["fires"]
    assert state["fires"][rid]["intensity"] == 3


def test_build_dc_state_includes_vent_status():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    glhc.start_fire(rid, 2, interior)
    glhc.vent_room(rid, interior)

    state = glhc.build_dc_state(interior)
    assert state["fires"][rid]["venting"] is True


# ---------------------------------------------------------------------------
# Suppression resets escalation timer
# ---------------------------------------------------------------------------


def test_suppression_resets_escalation_timer():
    interior = fresh_interior()
    rid = next(iter(interior.rooms))
    # Use intensity 4 so after local suppress (-2) the fire remains at 2.
    glhc.start_fire(rid, 4, interior)

    # Advance 30s towards escalation.
    glhc.tick(interior, 30.0)
    assert glhc._fires[rid].escalation_timer == pytest.approx(15.0)

    # Suppress locally — should reset escalation timer on completion.
    res = fresh_resources()
    glhc.suppress_local(rid, res)
    glhc.tick(interior, glhc.LOCAL_SUPPRESS_TIME + 0.01)
    # Fire should be at intensity 2, and escalation timer reset.
    assert glhc._fires[rid].intensity == 2
    assert glhc._fires[rid].escalation_timer == pytest.approx(glhc.ESCALATION_INTERVAL)
