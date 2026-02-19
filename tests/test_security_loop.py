"""Tests for the Security boarding game loop sub-module.

Covers:
  server/game_loop_security.py  — reset, start_boarding, move_squad,
                                   toggle_door, tick_security, build_interior_state
  server/models/ship.py         — Ship.interior field added in v0.02c
  Integration with ShipInterior and MarineSquad / Intruder models.
"""
from __future__ import annotations

import pytest

import server.game_loop_security as gls
from server.models.interior import ShipInterior, make_default_interior
from server.models.security import (
    AP_COST_DOOR,
    AP_COST_MOVE,
    AP_MAX,
    AP_REGEN_PER_TICK,
    INTRUDER_MOVE_INTERVAL,
    MARINE_DAMAGE_PER_TICK,
    INTRUDER_DAMAGE_PER_TICK,
    SENSOR_FOW_THRESHOLD,
    SQUAD_CASUALTY_THRESHOLD,
    MarineSquad,
    Intruder,
)
from server.models.ship import Ship


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


DEFAULT_SQUADS = [
    {"id": "squad_1", "room_id": "bridge"},
    {"id": "squad_2", "room_id": "medbay"},
]

DEFAULT_INTRUDERS = [
    {"id": "intruder_1", "room_id": "cargo_hold", "objective_id": "bridge"},
]


def fresh_interior() -> ShipInterior:
    return make_default_interior()


def fresh_ship() -> Ship:
    return Ship()


def setup_function():
    """Reset module state before each test."""
    gls.reset()


# ---------------------------------------------------------------------------
# reset() and is_boarding_active()
# ---------------------------------------------------------------------------


def test_reset_clears_boarding_flag():
    gls.start_boarding(fresh_interior(), DEFAULT_SQUADS, DEFAULT_INTRUDERS)
    assert gls.is_boarding_active()
    gls.reset()
    assert not gls.is_boarding_active()


def test_boarding_not_active_initially():
    assert not gls.is_boarding_active()


# ---------------------------------------------------------------------------
# start_boarding()
# ---------------------------------------------------------------------------


def test_start_boarding_sets_active_flag():
    interior = fresh_interior()
    gls.start_boarding(interior, DEFAULT_SQUADS, DEFAULT_INTRUDERS)
    assert gls.is_boarding_active()


def test_start_boarding_places_squads():
    interior = fresh_interior()
    gls.start_boarding(interior, DEFAULT_SQUADS, DEFAULT_INTRUDERS)
    assert len(interior.marine_squads) == 2
    squad_ids = {s.id for s in interior.marine_squads}
    assert "squad_1" in squad_ids
    assert "squad_2" in squad_ids


def test_start_boarding_places_squads_in_correct_rooms():
    interior = fresh_interior()
    gls.start_boarding(interior, DEFAULT_SQUADS, DEFAULT_INTRUDERS)
    sq1 = next(s for s in interior.marine_squads if s.id == "squad_1")
    assert sq1.room_id == "bridge"


def test_start_boarding_places_intruders():
    interior = fresh_interior()
    gls.start_boarding(interior, DEFAULT_SQUADS, DEFAULT_INTRUDERS)
    assert len(interior.intruders) == 1
    assert interior.intruders[0].id == "intruder_1"
    assert interior.intruders[0].room_id == "cargo_hold"
    assert interior.intruders[0].objective_id == "bridge"


def test_start_boarding_replaces_existing_squads():
    interior = fresh_interior()
    gls.start_boarding(interior, DEFAULT_SQUADS, DEFAULT_INTRUDERS)
    gls.start_boarding(interior, [{"id": "squad_x", "room_id": "conn"}], [])
    assert len(interior.marine_squads) == 1
    assert interior.marine_squads[0].id == "squad_x"


def test_start_boarding_squad_starts_with_full_ap():
    interior = fresh_interior()
    gls.start_boarding(interior, DEFAULT_SQUADS, DEFAULT_INTRUDERS)
    for sq in interior.marine_squads:
        assert sq.action_points == pytest.approx(AP_MAX)


# ---------------------------------------------------------------------------
# move_squad()
# ---------------------------------------------------------------------------


def test_move_squad_advances_one_step():
    interior = fresh_interior()
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "cargo_hold"}], [])
    # cargo_hold → auxiliary_power (connected)
    result = gls.move_squad(interior, "squad_1", "auxiliary_power")
    assert result is True
    sq = interior.marine_squads[0]
    assert sq.room_id == "auxiliary_power"


def test_move_squad_deducts_ap():
    interior = fresh_interior()
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "cargo_hold"}], [])
    sq = interior.marine_squads[0]
    initial_ap = sq.action_points
    gls.move_squad(interior, "squad_1", "engine_room")
    assert sq.action_points == pytest.approx(initial_ap - AP_COST_MOVE)


def test_move_squad_returns_false_when_no_ap():
    interior = fresh_interior()
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "cargo_hold"}], [])
    sq = interior.marine_squads[0]
    sq.action_points = 0.0
    result = gls.move_squad(interior, "squad_1", "auxiliary_power")
    assert result is False
    assert sq.room_id == "cargo_hold"  # didn't move


def test_move_squad_returns_false_for_unknown_squad():
    interior = fresh_interior()
    gls.start_boarding(interior, DEFAULT_SQUADS, DEFAULT_INTRUDERS)
    result = gls.move_squad(interior, "nonexistent", "bridge")
    assert result is False


def test_move_squad_returns_false_for_unknown_target():
    interior = fresh_interior()
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "bridge"}], [])
    result = gls.move_squad(interior, "squad_1", "room_that_does_not_exist")
    assert result is False


def test_move_squad_to_same_room_is_noop():
    interior = fresh_interior()
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "bridge"}], [])
    sq = interior.marine_squads[0]
    initial_ap = sq.action_points
    result = gls.move_squad(interior, "squad_1", "bridge")
    assert result is True
    assert sq.action_points == pytest.approx(initial_ap)  # no AP spent
    assert sq.room_id == "bridge"


def test_move_squad_blocked_by_sealed_door():
    interior = fresh_interior()
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "cargo_hold"}], [])
    # Seal auxiliary_power — the only path from cargo_hold
    interior.rooms["auxiliary_power"].door_sealed = True
    result = gls.move_squad(interior, "squad_1", "engine_room")
    assert result is False


def test_move_squad_multi_step_advances_one_at_a_time():
    """Moving toward a distant room advances exactly one room per call."""
    interior = fresh_interior()
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "cargo_hold"}], [])
    # cargo_hold → auxiliary_power → engine_room → surgery → torpedo_room → ...
    gls.move_squad(interior, "squad_1", "bridge")  # one step
    sq = interior.marine_squads[0]
    assert sq.room_id == "auxiliary_power"  # one step toward bridge


# ---------------------------------------------------------------------------
# toggle_door()
# ---------------------------------------------------------------------------


def test_toggle_door_seals_own_room():
    interior = fresh_interior()
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "bridge"}], [])
    result = gls.toggle_door(interior, "bridge", "squad_1")
    assert result is True
    assert interior.rooms["bridge"].door_sealed is True


def test_toggle_door_unseals_sealed_room():
    interior = fresh_interior()
    interior.rooms["bridge"].door_sealed = True
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "bridge"}], [])
    result = gls.toggle_door(interior, "bridge", "squad_1")
    assert result is True
    assert interior.rooms["bridge"].door_sealed is False


def test_toggle_door_seals_adjacent_room():
    interior = fresh_interior()
    # bridge is connected to conn — squad in bridge can seal conn
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "bridge"}], [])
    result = gls.toggle_door(interior, "conn", "squad_1")
    assert result is True
    assert interior.rooms["conn"].door_sealed is True


def test_toggle_door_deducts_ap():
    interior = fresh_interior()
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "bridge"}], [])
    sq = interior.marine_squads[0]
    initial_ap = sq.action_points
    gls.toggle_door(interior, "bridge", "squad_1")
    assert sq.action_points == pytest.approx(initial_ap - AP_COST_DOOR)


def test_toggle_door_returns_false_when_no_ap():
    interior = fresh_interior()
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "bridge"}], [])
    interior.marine_squads[0].action_points = 0.0
    result = gls.toggle_door(interior, "bridge", "squad_1")
    assert result is False
    assert interior.rooms["bridge"].door_sealed is False


def test_toggle_door_returns_false_for_distant_room():
    interior = fresh_interior()
    # bridge and cargo_hold are not adjacent
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "bridge"}], [])
    result = gls.toggle_door(interior, "cargo_hold", "squad_1")
    assert result is False


def test_toggle_door_returns_false_for_unknown_squad():
    interior = fresh_interior()
    gls.start_boarding(interior, DEFAULT_SQUADS, DEFAULT_INTRUDERS)
    result = gls.toggle_door(interior, "bridge", "no_such_squad")
    assert result is False


def test_toggle_door_returns_false_for_unknown_room():
    interior = fresh_interior()
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "bridge"}], [])
    result = gls.toggle_door(interior, "phantom_room", "squad_1")
    assert result is False


# ---------------------------------------------------------------------------
# tick_security() — AP regen
# ---------------------------------------------------------------------------


def test_tick_security_returns_empty_when_not_active():
    interior = fresh_interior()
    ship = fresh_ship()
    events = gls.tick_security(interior, ship, 0.1)
    assert events == []


def test_tick_security_regens_squad_ap():
    interior = fresh_interior()
    ship = fresh_ship()
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "bridge"}], [])
    sq = interior.marine_squads[0]
    sq.action_points = 0.0
    gls.tick_security(interior, ship, 0.1)
    assert sq.action_points == pytest.approx(AP_REGEN_PER_TICK)


def test_tick_security_ap_does_not_exceed_max():
    interior = fresh_interior()
    ship = fresh_ship()
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "bridge"}], [])
    sq = interior.marine_squads[0]
    sq.action_points = AP_MAX
    gls.tick_security(interior, ship, 0.1)
    assert sq.action_points == pytest.approx(AP_MAX)


def test_tick_security_no_ap_regen_for_eliminated_squad():
    interior = fresh_interior()
    ship = fresh_ship()
    gls.start_boarding(interior, [{"id": "squad_1", "room_id": "bridge"}], [])
    sq = interior.marine_squads[0]
    sq.count = 0
    sq.action_points = 0.0
    gls.tick_security(interior, ship, 0.1)
    assert sq.action_points == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# tick_security() — intruder movement
# ---------------------------------------------------------------------------


def test_tick_security_decrements_intruder_move_timer():
    interior = fresh_interior()
    ship = fresh_ship()
    gls.start_boarding(interior, [], [{"id": "i1", "room_id": "cargo_hold", "objective_id": "bridge"}])
    intruder = interior.intruders[0]
    initial_timer = intruder.move_timer
    gls.tick_security(interior, ship, 0.1)
    assert intruder.move_timer == initial_timer - 1


def test_tick_security_moves_intruder_when_timer_zero():
    interior = fresh_interior()
    ship = fresh_ship()
    gls.start_boarding(interior, [], [{"id": "i1", "room_id": "cargo_hold", "objective_id": "bridge"}])
    intruder = interior.intruders[0]
    intruder.move_timer = 1  # one tick away from moving
    gls.tick_security(interior, ship, 0.1)
    # After one tick the timer hits 0 → intruder moves one step
    assert intruder.room_id != "cargo_hold"


def test_tick_security_intruder_resets_move_timer_after_move():
    interior = fresh_interior()
    ship = fresh_ship()
    gls.start_boarding(interior, [], [{"id": "i1", "room_id": "cargo_hold", "objective_id": "bridge"}])
    interior.intruders[0].move_timer = 1
    gls.tick_security(interior, ship, 0.1)
    assert interior.intruders[0].move_timer == INTRUDER_MOVE_INTERVAL


def test_tick_security_intruder_at_objective_emits_event():
    interior = fresh_interior()
    ship = fresh_ship()
    # Intruder already at its objective with timer at zero.
    gls.start_boarding(interior, [], [{"id": "i1", "room_id": "bridge", "objective_id": "bridge"}])
    interior.intruders[0].move_timer = 0
    events = gls.tick_security(interior, ship, 0.1)
    event_types = [e[0] for e in events]
    assert "security.intruder_reached_objective" in event_types


# ---------------------------------------------------------------------------
# tick_security() — combat
# ---------------------------------------------------------------------------


def test_tick_security_marines_damage_intruder():
    interior = fresh_interior()
    ship = fresh_ship()
    gls.start_boarding(
        interior,
        [{"id": "squad_1", "room_id": "bridge"}],
        [{"id": "i1", "room_id": "bridge", "objective_id": "bridge"}],
    )
    intruder = interior.intruders[0]
    initial_hp = intruder.health
    gls.tick_security(interior, ship, 0.1)
    # Squad count is 4; damage per tick per marine = MARINE_DAMAGE_PER_TICK
    expected_damage = MARINE_DAMAGE_PER_TICK * 4
    assert intruder.health == pytest.approx(initial_hp - expected_damage)


def test_tick_security_intruder_damages_squad():
    interior = fresh_interior()
    ship = fresh_ship()
    gls.start_boarding(
        interior,
        [{"id": "squad_1", "room_id": "bridge"}],
        [{"id": "i1", "room_id": "bridge", "objective_id": "bridge"}],
    )
    squad = interior.marine_squads[0]
    initial_hp = squad.health
    gls.tick_security(interior, ship, 0.1)
    assert squad.health == pytest.approx(initial_hp - INTRUDER_DAMAGE_PER_TICK)


def test_tick_security_no_combat_when_different_rooms():
    interior = fresh_interior()
    ship = fresh_ship()
    gls.start_boarding(
        interior,
        [{"id": "squad_1", "room_id": "bridge"}],
        [{"id": "i1", "room_id": "cargo_hold", "objective_id": "bridge"}],
    )
    intruder = interior.intruders[0]
    initial_hp = intruder.health
    gls.tick_security(interior, ship, 0.1)
    assert intruder.health == pytest.approx(initial_hp)


def test_tick_security_defeated_intruder_emits_event():
    interior = fresh_interior()
    ship = fresh_ship()
    gls.start_boarding(
        interior,
        [{"id": "squad_1", "room_id": "bridge"}],
        [{"id": "i1", "room_id": "bridge", "objective_id": "bridge"}],
    )
    interior.intruders[0].health = 0.001  # one hit away
    events = gls.tick_security(interior, ship, 0.1)
    event_types = [e[0] for e in events]
    assert "security.intruder_defeated" in event_types


def test_tick_security_removes_defeated_intruder():
    interior = fresh_interior()
    ship = fresh_ship()
    gls.start_boarding(
        interior,
        [{"id": "squad_1", "room_id": "bridge"}],
        [{"id": "i1", "room_id": "bridge", "objective_id": "bridge"}],
    )
    interior.intruders[0].health = 0.001
    gls.tick_security(interior, ship, 0.1)
    assert len(interior.intruders) == 0


def test_tick_security_squad_casualty_emits_event():
    interior = fresh_interior()
    ship = fresh_ship()
    gls.start_boarding(
        interior,
        [{"id": "squad_1", "room_id": "bridge"}],
        [{"id": "i1", "room_id": "bridge", "objective_id": "bridge"}],
    )
    # Set health so one hit (INTRUDER_DAMAGE_PER_TICK) brings it exactly to threshold.
    # SQUAD_CASUALTY_THRESHOLD + INTRUDER_DAMAGE_PER_TICK → after hit = threshold exactly.
    squad = interior.marine_squads[0]
    squad.health = SQUAD_CASUALTY_THRESHOLD + INTRUDER_DAMAGE_PER_TICK
    events = gls.tick_security(interior, ship, 0.1)
    event_types = [e[0] for e in events]
    assert "security.squad_casualty" in event_types


def test_tick_security_squad_elimination_emits_event_once():
    interior = fresh_interior()
    ship = fresh_ship()
    gls.start_boarding(
        interior,
        [{"id": "squad_1", "room_id": "bridge"}],
        [{"id": "i1", "room_id": "bridge", "objective_id": "bridge"}],
    )
    squad = interior.marine_squads[0]
    squad.count = 0  # already eliminated

    # First tick — should fire "squad_eliminated".
    events1 = gls.tick_security(interior, ship, 0.1)
    assert any(e[0] == "security.squad_eliminated" for e in events1)

    # Second tick — must NOT fire again.
    events2 = gls.tick_security(interior, ship, 0.1)
    assert not any(e[0] == "security.squad_eliminated" for e in events2)


# ---------------------------------------------------------------------------
# build_interior_state()
# ---------------------------------------------------------------------------


def test_build_interior_state_includes_rooms():
    interior = fresh_interior()
    ship = fresh_ship()
    gls.start_boarding(interior, DEFAULT_SQUADS, DEFAULT_INTRUDERS)
    state = gls.build_interior_state(interior, ship)
    assert "rooms" in state
    assert "bridge" in state["rooms"]
    assert "door_sealed" in state["rooms"]["bridge"]
    assert "state" in state["rooms"]["bridge"]


def test_build_interior_state_includes_squads():
    interior = fresh_interior()
    ship = fresh_ship()
    gls.start_boarding(interior, DEFAULT_SQUADS, DEFAULT_INTRUDERS)
    state = gls.build_interior_state(interior, ship)
    assert len(state["squads"]) == 2
    assert any(s["id"] == "squad_1" for s in state["squads"])


def test_build_interior_state_includes_visible_intruder_with_good_sensors():
    interior = fresh_interior()
    ship = fresh_ship()
    ship.systems["sensors"].power = 120.0  # efficiency > SENSOR_FOW_THRESHOLD
    gls.start_boarding(interior, DEFAULT_SQUADS, DEFAULT_INTRUDERS)
    state = gls.build_interior_state(interior, ship)
    assert any(i["id"] == "intruder_1" for i in state["intruders"])


def test_build_interior_state_excludes_invisible_intruder_with_poor_sensors():
    interior = fresh_interior()
    ship = fresh_ship()
    # Set sensors so efficiency < SENSOR_FOW_THRESHOLD and no squad co-located.
    ship.systems["sensors"].power = 30.0   # efficiency ≈ 0.3 < 0.5
    gls.start_boarding(
        interior,
        [{"id": "squad_1", "room_id": "bridge"}],  # squad NOT in cargo_hold
        [{"id": "intruder_1", "room_id": "cargo_hold", "objective_id": "bridge"}],
    )
    state = gls.build_interior_state(interior, ship)
    assert not any(i["id"] == "intruder_1" for i in state["intruders"])


def test_build_interior_state_includes_intruder_when_squad_co_located():
    interior = fresh_interior()
    ship = fresh_ship()
    ship.systems["sensors"].power = 30.0  # poor sensors
    gls.start_boarding(
        interior,
        [{"id": "squad_1", "room_id": "bridge"}],
        [{"id": "intruder_1", "room_id": "bridge", "objective_id": "conn"}],  # same room as squad
    )
    state = gls.build_interior_state(interior, ship)
    assert any(i["id"] == "intruder_1" for i in state["intruders"])


def test_build_interior_state_is_boarding_flag():
    interior = fresh_interior()
    ship = fresh_ship()
    assert gls.build_interior_state(interior, ship)["is_boarding"] is False
    gls.start_boarding(interior, DEFAULT_SQUADS, DEFAULT_INTRUDERS)
    assert gls.build_interior_state(interior, ship)["is_boarding"] is True


def test_build_interior_state_reflects_sealed_door():
    interior = fresh_interior()
    ship = fresh_ship()
    interior.rooms["bridge"].door_sealed = True
    gls.start_boarding(interior, DEFAULT_SQUADS, DEFAULT_INTRUDERS)
    state = gls.build_interior_state(interior, ship)
    assert state["rooms"]["bridge"]["door_sealed"] is True


# ---------------------------------------------------------------------------
# Ship.interior integration
# ---------------------------------------------------------------------------


def test_ship_has_interior_field():
    ship = fresh_ship()
    assert hasattr(ship, "interior")
    assert isinstance(ship.interior, ShipInterior)


def test_ship_interior_has_correct_rooms():
    ship = fresh_ship()
    assert "bridge" in ship.interior.rooms
    assert "cargo_hold" in ship.interior.rooms
    assert len(ship.interior.rooms) == 20


def test_ship_interior_starts_with_empty_squads_and_intruders():
    ship = fresh_ship()
    assert ship.interior.marine_squads == []
    assert ship.interior.intruders == []


def test_two_ships_have_independent_interiors():
    ship_a = fresh_ship()
    ship_b = fresh_ship()
    ship_a.interior.marine_squads.append(
        MarineSquad(id="squad_1", room_id="bridge")
    )
    assert ship_b.interior.marine_squads == []
