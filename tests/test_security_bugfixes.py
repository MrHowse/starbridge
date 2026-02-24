"""Tests for v0.06.3 Part 1 — Security bug fixes.

BUG A: Marine squads not displaying when boarding starts without explicit squads.
BUG B: Sandbox intruders inert because objective_id was None.
"""
from __future__ import annotations

import pytest

import server.game_loop_security as gls
from server.models.interior import ShipInterior, make_default_interior
from server.models.ship import Ship


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh() -> tuple[ShipInterior, Ship]:
    return make_default_interior(), Ship()


def setup_function():
    gls.reset()


# ---------------------------------------------------------------------------
# BUG A — auto-create default squads when none provided
# ---------------------------------------------------------------------------


def test_start_boarding_empty_squads_creates_defaults():
    """When squad_specs=[] and no pre-deployed squads, defaults are auto-created."""
    interior, _ = fresh()
    gls.start_boarding(interior, [], [{"id": "i1", "room_id": "cargo_hold", "objective_id": "bridge"}])
    assert len(interior.marine_squads) >= 1
    ids = {s.id for s in interior.marine_squads}
    assert "squad_1" in ids


def test_default_squads_placed_in_valid_rooms():
    """All auto-created squads must be in rooms that exist in the interior."""
    interior, _ = fresh()
    gls.start_boarding(interior, [], [{"id": "i1", "room_id": "cargo_hold", "objective_id": "bridge"}])
    for sq in interior.marine_squads:
        assert sq.room_id in interior.rooms, f"Squad {sq.id} placed in non-existent room {sq.room_id}"


def test_default_squads_have_full_ap_and_health():
    interior, _ = fresh()
    gls.start_boarding(interior, [], [{"id": "i1", "room_id": "cargo_hold", "objective_id": "bridge"}])
    for sq in interior.marine_squads:
        assert sq.health == pytest.approx(100.0)
        assert sq.action_points == pytest.approx(10.0)
        assert sq.count == 4


def test_explicit_squads_override_defaults():
    """When squad_specs is provided, defaults are NOT used."""
    interior, _ = fresh()
    gls.start_boarding(interior, [{"id": "custom", "room_id": "medbay"}], [])
    assert len(interior.marine_squads) == 1
    assert interior.marine_squads[0].id == "custom"


def test_pre_deployed_squads_preserved():
    """deploy_squads() then start_boarding([], intruders) preserves planned positions."""
    interior, _ = fresh()
    gls.deploy_squads(interior, [{"id": "alpha", "room_id": "weapons_bay"}])
    gls.start_boarding(interior, [], [{"id": "i1", "room_id": "cargo_hold", "objective_id": "bridge"}])
    assert len(interior.marine_squads) == 1
    assert interior.marine_squads[0].id == "alpha"
    assert interior.marine_squads[0].room_id == "weapons_bay"


def test_default_squads_visible_in_interior_state():
    """Auto-created squads appear in the broadcast state dict."""
    interior, ship = fresh()
    gls.start_boarding(interior, [], [{"id": "i1", "room_id": "cargo_hold", "objective_id": "bridge"}])
    state = gls.build_interior_state(interior, ship)
    assert len(state["squads"]) >= 1
    assert any(s["id"] == "squad_1" for s in state["squads"])


def test_default_squads_skip_invalid_rooms():
    """If a default room doesn't exist in the interior, that squad is skipped."""
    # Create a minimal interior without 'combat_info'
    from server.models.interior import Room
    rooms = {
        "bridge": Room("bridge", "Bridge", "bridge", (0, 0), ["conn"]),
        "conn": Room("conn", "Conn", "bridge", (1, 0), ["bridge"]),
    }
    interior = ShipInterior(rooms=rooms)
    gls.start_boarding(interior, [], [{"id": "i1", "room_id": "conn", "objective_id": "bridge"}])
    # Only squad_1 (bridge) should be created; squad_2 (combat_info) skipped
    assert len(interior.marine_squads) == 1
    assert interior.marine_squads[0].room_id == "bridge"


# ---------------------------------------------------------------------------
# BUG B — sandbox intruders need valid objectives
# ---------------------------------------------------------------------------


def test_sandbox_intruders_have_objectives():
    """Sandbox boarding event provides intruders with valid room objectives."""
    import server.game_loop_sandbox as glsb
    glsb.reset(active=True)
    # Force the boarding timer to fire
    glsb._timers["boarding"] = 0.0
    events = glsb.tick(None, 0.1)
    boarding_events = [e for e in events if e["type"] == "start_boarding"]
    assert len(boarding_events) == 1
    for intruder in boarding_events[0]["intruders"]:
        assert intruder["objective_id"] is not None, f"Intruder {intruder['id']} has no objective"
        assert isinstance(intruder["objective_id"], str)


def test_sandbox_intruders_spawn_at_cargo_hold():
    """Sandbox intruders now spawn at cargo_hold (stern entry point)."""
    import server.game_loop_sandbox as glsb
    glsb.reset(active=True)
    glsb._timers["boarding"] = 0.0
    events = glsb.tick(None, 0.1)
    boarding = [e for e in events if e["type"] == "start_boarding"][0]
    for intruder in boarding["intruders"]:
        assert intruder["room_id"] == "cargo_hold"


def test_sandbox_intruders_can_pathfind_to_objectives():
    """Intruders from sandbox can find a BFS path to their objectives."""
    import server.game_loop_sandbox as glsb
    glsb.reset(active=True)
    glsb._timers["boarding"] = 0.0
    events = glsb.tick(None, 0.1)
    boarding = [e for e in events if e["type"] == "start_boarding"][0]
    interior = make_default_interior()
    for intruder in boarding["intruders"]:
        path = interior.find_path(intruder["room_id"], intruder["objective_id"])
        assert len(path) >= 2, f"No path from {intruder['room_id']} to {intruder['objective_id']}"


def test_intruder_moves_toward_objective_after_timer():
    """Intruder with valid objective advances toward it when move timer expires."""
    interior, ship = fresh()
    gls.start_boarding(
        interior, [],
        [{"id": "i1", "room_id": "cargo_hold", "objective_id": "bridge"}],
    )
    intruder = interior.intruders[0]
    intruder.move_timer = 1  # one tick from moving
    gls.tick_security(interior, ship, 0.1)
    assert intruder.room_id != "cargo_hold", "Intruder should have moved"


def test_intruder_reaches_objective_emits_event():
    """When intruder arrives at objective, an event is emitted."""
    interior, ship = fresh()
    gls.start_boarding(
        interior, [],
        [{"id": "i1", "room_id": "bridge", "objective_id": "bridge"}],
    )
    interior.intruders[0].move_timer = 0
    events = gls.tick_security(interior, ship, 0.1)
    event_types = [e[0] for e in events]
    assert "security.intruder_reached_objective" in event_types


# ---------------------------------------------------------------------------
# Integration — full boarding cycle with auto-squads
# ---------------------------------------------------------------------------


def test_full_sandbox_boarding_cycle():
    """Auto-squads + valid-objective intruders produce a working boarding encounter."""
    interior, ship = fresh()
    # Simulate sandbox boarding: no squads provided, intruders with objectives
    gls.start_boarding(interior, [], [
        {"id": "i1", "room_id": "cargo_hold", "objective_id": "bridge"},
        {"id": "i2", "room_id": "cargo_hold", "objective_id": "engine_room"},
    ])
    assert gls.is_boarding_active()
    assert len(interior.marine_squads) >= 1, "Default squads should exist"
    assert len(interior.intruders) == 2

    # Tick several times — intruders should move, squads should regen AP
    for _ in range(50):
        gls.tick_security(interior, ship, 0.1)

    # After 50 ticks (5 seconds), intruder timers (30 ticks) should fire at least once
    # Check intruders have moved from cargo_hold
    moved = any(i.room_id != "cargo_hold" for i in interior.intruders)
    assert moved, "At least one intruder should have moved after 50 ticks"


def test_combat_occurs_when_squad_meets_intruder():
    """When squad and intruder share a room, combat reduces health."""
    interior, ship = fresh()
    gls.start_boarding(
        interior,
        [{"id": "s1", "room_id": "bridge"}],
        [{"id": "i1", "room_id": "bridge", "objective_id": "bridge"}],
    )
    initial_intruder_hp = interior.intruders[0].health
    gls.tick_security(interior, ship, 0.1)
    assert interior.intruders[0].health < initial_intruder_hp
