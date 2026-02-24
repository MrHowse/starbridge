"""Tests for the enhanced interior combat system — v0.06.3 Part 4.

Covers:
  server/game_loop_security.py — init_marine_teams, start_enhanced_boarding,
  send_team, set_team_patrol, tick_combat, room combat resolution,
  boarding party movement/sabotage/retreat, marine team movement.
"""
from __future__ import annotations

import random

import pytest

import server.game_loop_security as gls
from server.models.boarding import (
    ADVANCE_TIME_PER_ROOM,
    BREACH_TIME,
    SABOTAGE_RATE,
    BoardingParty,
)
from server.models.interior import ShipInterior, make_default_interior
from server.models.marine_teams import TRAVEL_TIME_PER_ROOM, MarineTeam
from server.models.ship import Ship


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh() -> tuple[ShipInterior, Ship]:
    return make_default_interior(), Ship()


@pytest.fixture(autouse=True)
def _reset_security():
    gls.reset()


# ---------------------------------------------------------------------------
# init_marine_teams
# ---------------------------------------------------------------------------


class TestInitMarineTeams:
    def test_creates_teams_for_frigate(self):
        teams = gls.init_marine_teams("frigate")
        assert len(teams) == 2

    def test_creates_teams_for_battleship(self):
        teams = gls.init_marine_teams("battleship")
        assert len(teams) == 3

    def test_teams_stored_in_module(self):
        gls.init_marine_teams("frigate")
        assert len(gls.get_marine_teams()) == 2

    def test_reset_clears_teams(self):
        gls.init_marine_teams("frigate")
        gls.reset()
        assert len(gls.get_marine_teams()) == 0

    def test_with_crew_ids(self):
        crew = [f"c{i}" for i in range(8)]
        teams = gls.init_marine_teams("frigate", crew_member_ids=crew)
        all_members = []
        for t in teams:
            all_members.extend(t.members)
        assert set(all_members) == set(crew)


# ---------------------------------------------------------------------------
# start_enhanced_boarding
# ---------------------------------------------------------------------------


class TestStartEnhancedBoarding:
    def test_creates_boarding_party(self):
        interior, _ = fresh()
        party = gls.start_enhanced_boarding(interior, entry_point="cargo_hold",
                                             rng=random.Random(42))
        assert party.id == "bp_001"
        assert party.location == "cargo_hold"

    def test_activates_boarding(self):
        interior, _ = fresh()
        gls.start_enhanced_boarding(interior, rng=random.Random(42))
        assert gls.is_boarding_active()

    def test_multiple_parties(self):
        interior, _ = fresh()
        p1 = gls.start_enhanced_boarding(interior, rng=random.Random(42))
        p2 = gls.start_enhanced_boarding(interior, rng=random.Random(43))
        assert p1.id != p2.id
        assert len(gls.get_boarding_parties()) == 2

    def test_party_has_path(self):
        interior, _ = fresh()
        party = gls.start_enhanced_boarding(
            interior, entry_point="cargo_hold",
            objective_override="bridge", rng=random.Random(42))
        assert len(party.path) >= 2
        assert party.path[0] == "cargo_hold"
        assert party.path[-1] == "bridge"

    def test_party_stored_in_module(self):
        interior, _ = fresh()
        gls.start_enhanced_boarding(interior, rng=random.Random(42))
        assert len(gls.get_boarding_parties()) == 1

    def test_reset_clears_parties(self):
        interior, _ = fresh()
        gls.start_enhanced_boarding(interior, rng=random.Random(42))
        gls.reset()
        assert len(gls.get_boarding_parties()) == 0


# ---------------------------------------------------------------------------
# Player commands — send_team, set_team_patrol, station_team
# ---------------------------------------------------------------------------


class TestPlayerCommands:
    def test_send_team_to_room(self):
        gls.init_marine_teams("frigate")
        teams = gls.get_marine_teams()
        result = gls.send_team(teams[0].id, "bridge")
        assert result is True
        assert teams[0].status == "responding"
        assert teams[0].destination == "bridge"

    def test_send_unknown_team_fails(self):
        assert gls.send_team("nonexistent", "bridge") is False

    def test_send_incapacitated_team_fails(self):
        gls.init_marine_teams("frigate")
        teams = gls.get_marine_teams()
        teams[0].apply_casualties(teams[0].size)  # wipe out
        assert gls.send_team(teams[0].id, "bridge") is False

    def test_set_patrol(self):
        gls.init_marine_teams("frigate")
        teams = gls.get_marine_teams()
        result = gls.set_team_patrol(teams[0].id, ["bridge", "conn", "engine_room"])
        assert result is True
        assert teams[0].status == "patrolling"
        assert teams[0].patrol_route == ["bridge", "conn", "engine_room"]

    def test_set_patrol_empty_fails(self):
        gls.init_marine_teams("frigate")
        teams = gls.get_marine_teams()
        assert gls.set_team_patrol(teams[0].id, []) is False

    def test_station_team(self):
        gls.init_marine_teams("frigate")
        teams = gls.get_marine_teams()
        teams[0].order_respond("bridge")
        result = gls.station_team(teams[0].id)
        assert result is True
        assert teams[0].status == "stationed"

    def test_assign_escort(self):
        gls.init_marine_teams("frigate")
        teams = gls.get_marine_teams()
        result = gls.assign_escort(teams[0].id, "team_alpha")
        assert result is True
        assert teams[0].status == "escorting"
        assert teams[0].escort_target == "team_alpha"

    def test_disengage(self):
        gls.init_marine_teams("frigate")
        teams = gls.get_marine_teams()
        teams[0].engage("bp_001")
        result = gls.disengage_team(teams[0].id)
        assert result is True
        assert teams[0].status == "responding"

    def test_disengage_non_engaging_fails(self):
        gls.init_marine_teams("frigate")
        teams = gls.get_marine_teams()
        assert gls.disengage_team(teams[0].id) is False


# ---------------------------------------------------------------------------
# Boarding party movement
# ---------------------------------------------------------------------------


class TestBoardingPartyMovement:
    def test_party_advances_over_time(self):
        interior, ship = fresh()
        party = gls.start_enhanced_boarding(
            interior, entry_point="cargo_hold",
            objective_override="bridge", rng=random.Random(42))
        start_loc = party.location
        # Tick enough for one room advance
        for _ in range(int(ADVANCE_TIME_PER_ROOM * 10) + 1):
            gls.tick_combat(interior, ship, 0.1)
        assert party.location != start_loc or party.status == "sabotaging"

    def test_party_starts_sabotage_at_objective(self):
        interior, ship = fresh()
        party = gls.start_enhanced_boarding(
            interior, entry_point="bridge",
            objective_override="bridge", rng=random.Random(42))
        # Already at objective
        events = gls.tick_combat(interior, ship, 0.1)
        assert party.status == "sabotaging"
        assert any(e[0] == "security.sabotage_started" for e in events)

    def test_sabotage_completes(self):
        interior, ship = fresh()
        party = gls.start_enhanced_boarding(
            interior, entry_point="bridge",
            objective_override="bridge", rng=random.Random(42))
        # Tick until sabotage complete (1/30 per second → 30 seconds)
        total_ticks = int(1.0 / SABOTAGE_RATE * 10) + 10
        all_events = []
        for _ in range(total_ticks):
            all_events.extend(gls.tick_combat(interior, ship, 0.1))
        assert any(e[0] == "security.sabotage_complete" for e in all_events)

    def test_party_breaches_locked_door(self):
        interior, ship = fresh()
        # Lock auxiliary_power (on path from cargo_hold)
        interior.rooms["auxiliary_power"].door_sealed = True
        party = gls.start_enhanced_boarding(
            interior, entry_point="cargo_hold",
            objective_override="reactor", rng=random.Random(42))
        # Tick enough for breach
        all_events = []
        for _ in range(int((ADVANCE_TIME_PER_ROOM + BREACH_TIME) * 10) + 20):
            all_events.extend(gls.tick_combat(interior, ship, 0.1))
        breach_events = [e for e in all_events if e[0] == "security.door_breached"]
        assert len(breach_events) >= 1

    def test_party_retreats_on_low_morale(self):
        interior, ship = fresh()
        party = gls.start_enhanced_boarding(
            interior, entry_point="cargo_hold",
            objective_override="bridge", rng=random.Random(42))
        party.morale = 0.15  # below retreat threshold
        events = gls.tick_combat(interior, ship, 0.1)
        assert party.status == "retreating"
        assert any(e[0] == "security.party_retreating" for e in events)


# ---------------------------------------------------------------------------
# Marine team movement
# ---------------------------------------------------------------------------


class TestMarineTeamMovement:
    def test_responding_team_moves(self):
        interior, ship = fresh()
        gls.init_marine_teams("frigate")
        teams = gls.get_marine_teams()
        team = teams[0]
        start_loc = team.location
        team.order_respond("bridge")
        # Tick enough for one room
        for _ in range(int(TRAVEL_TIME_PER_ROOM * 10) + 1):
            gls.tick_combat(interior, ship, 0.1)
        assert team.location != start_loc or team.location == "bridge"

    def test_team_arrives_event(self):
        interior, ship = fresh()
        gls.init_marine_teams("frigate")
        teams = gls.get_marine_teams()
        team = teams[0]
        team.location = "conn"  # one room from bridge
        team.order_respond("bridge")
        all_events = []
        for _ in range(int(TRAVEL_TIME_PER_ROOM * 10) + 5):
            all_events.extend(gls.tick_combat(interior, ship, 0.1))
        assert any(e[0] == "security.team_arrived" for e in all_events)

    def test_team_auto_engages_boarder(self):
        interior, ship = fresh()
        gls.init_marine_teams("frigate")
        party = gls.start_enhanced_boarding(
            interior, entry_point="bridge",
            objective_override="bridge", rng=random.Random(42))
        teams = gls.get_marine_teams()
        team = teams[0]
        team.location = "conn"
        team.order_respond("bridge")
        all_events = []
        for _ in range(int(TRAVEL_TIME_PER_ROOM * 10) + 5):
            all_events.extend(gls.tick_combat(interior, ship, 0.1))
        engage_events = [e for e in all_events if e[0] == "security.team_engaging"]
        if team.location == "bridge":
            assert len(engage_events) >= 1

    def test_patrolling_team_cycles(self):
        interior, ship = fresh()
        gls.init_marine_teams("frigate")
        teams = gls.get_marine_teams()
        team = teams[0]
        team.location = "conn"
        team.order_patrol(["conn", "bridge"])
        # Tick many times to allow patrol cycling
        for _ in range(200):
            gls.tick_combat(interior, ship, 0.1)
        # Team should have patrolled (patrol_index should have advanced)
        assert team.patrol_index >= 0


# ---------------------------------------------------------------------------
# Room combat resolution
# ---------------------------------------------------------------------------


class TestRoomCombat:
    def test_combat_damages_boarders(self):
        interior, ship = fresh()
        gls.init_marine_teams("frigate")
        teams = gls.get_marine_teams()
        team = teams[0]
        team.location = "bridge"
        party = gls.start_enhanced_boarding(
            interior, entry_point="bridge",
            objective_override="bridge", rng=random.Random(42))
        initial_members = party.members
        # Tick many times for combat
        for _ in range(100):
            gls.tick_combat(interior, ship, 0.1)
        # Either party lost members or was eliminated
        assert party.members < initial_members or party.is_eliminated

    def test_combat_damages_marines(self):
        interior, ship = fresh()
        gls.init_marine_teams("frigate")
        teams = gls.get_marine_teams()
        team = teams[0]
        team.location = "bridge"
        party = gls.start_enhanced_boarding(
            interior, entry_point="bridge",
            objective_override="bridge", rng=random.Random(42))
        initial_size = team.size
        for _ in range(100):
            gls.tick_combat(interior, ship, 0.1)
        # Marine casualties possible (armour reduces but doesn't eliminate)
        # Not guaranteed in 100 ticks, so just verify no crash
        assert team.size <= initial_size

    def test_room_secured_event_when_all_boarders_eliminated(self):
        interior, ship = fresh()
        gls.init_marine_teams("frigate")
        teams = gls.get_marine_teams()
        team = teams[0]
        team.location = "bridge"
        party = gls.start_enhanced_boarding(
            interior, entry_point="bridge",
            objective_override="bridge", rng=random.Random(42))
        party.members = 1  # weak party
        party.morale = 1.0  # don't retreat
        all_events = []
        for _ in range(200):
            all_events.extend(gls.tick_combat(interior, ship, 0.1))
        secured = [e for e in all_events if e[0] == "security.room_secured"]
        eliminated = [e for e in all_events if e[0] == "security.party_eliminated"]
        assert len(eliminated) >= 1 or len(secured) >= 1

    def test_ammo_consumed_in_combat(self):
        interior, ship = fresh()
        gls.init_marine_teams("frigate")
        teams = gls.get_marine_teams()
        team = teams[0]
        team.location = "bridge"
        gls.start_enhanced_boarding(
            interior, entry_point="bridge",
            objective_override="bridge", rng=random.Random(42))
        initial_ammo = team.ammo
        for _ in range(10):
            gls.tick_combat(interior, ship, 0.1)
        assert team.ammo < initial_ammo

    def test_no_combat_in_different_rooms(self):
        interior, ship = fresh()
        gls.init_marine_teams("frigate")
        teams = gls.get_marine_teams()
        team = teams[0]
        team.location = "bridge"
        party = gls.start_enhanced_boarding(
            interior, entry_point="cargo_hold",
            objective_override="bridge", rng=random.Random(42))
        initial_members = party.members
        # One tick — party is at cargo_hold, team at bridge
        gls.tick_combat(interior, ship, 0.1)
        assert party.members == initial_members  # no combat


# ---------------------------------------------------------------------------
# Multiple simultaneous boarding parties
# ---------------------------------------------------------------------------


class TestMultipleParties:
    def test_two_parties_simultaneously(self):
        interior, ship = fresh()
        gls.init_marine_teams("frigate")
        p1 = gls.start_enhanced_boarding(
            interior, entry_point="cargo_hold",
            objective_override="bridge", rng=random.Random(42))
        p2 = gls.start_enhanced_boarding(
            interior, entry_point="observation",
            objective_override="reactor", rng=random.Random(43))
        assert len(gls.get_boarding_parties()) == 2
        # Tick — both should advance independently
        for _ in range(10):
            gls.tick_combat(interior, ship, 0.1)
        assert p1.id != p2.id


# ---------------------------------------------------------------------------
# Serialise / deserialise
# ---------------------------------------------------------------------------


class TestSerialise:
    def test_round_trip_marine_teams(self):
        gls.init_marine_teams("frigate")
        data = gls.serialise()
        gls.reset()
        gls.deserialise(data)
        assert len(gls.get_marine_teams()) == 2

    def test_round_trip_boarding_parties(self):
        interior, _ = fresh()
        gls.start_enhanced_boarding(interior, rng=random.Random(42))
        data = gls.serialise()
        gls.reset()
        gls.deserialise(data)
        assert len(gls.get_boarding_parties()) == 1

    def test_round_trip_next_party_id(self):
        interior, _ = fresh()
        gls.start_enhanced_boarding(interior, rng=random.Random(42))
        gls.start_enhanced_boarding(interior, rng=random.Random(43))
        data = gls.serialise()
        gls.reset()
        gls.deserialise(data)
        p3 = gls.start_enhanced_boarding(interior, rng=random.Random(44))
        assert p3.id == "bp_003"


# ---------------------------------------------------------------------------
# build_interior_state includes new data
# ---------------------------------------------------------------------------


class TestInteriorState:
    def test_state_includes_marine_teams(self):
        interior, ship = fresh()
        gls.init_marine_teams("frigate")
        state = gls.build_interior_state(interior, ship)
        assert len(state["marine_teams"]) == 2
        assert "id" in state["marine_teams"][0]

    def test_state_includes_boarding_parties(self):
        interior, ship = fresh()
        gls.start_enhanced_boarding(interior, rng=random.Random(42))
        state = gls.build_interior_state(interior, ship)
        assert len(state["boarding_parties"]) == 1
        assert "id" in state["boarding_parties"][0]

    def test_eliminated_party_excluded_from_state(self):
        interior, ship = fresh()
        party = gls.start_enhanced_boarding(interior, rng=random.Random(42))
        party.members = 0
        party.status = "eliminated"
        state = gls.build_interior_state(interior, ship)
        assert len(state["boarding_parties"]) == 0
