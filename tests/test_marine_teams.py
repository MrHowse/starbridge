"""Tests for MarineTeam model and factory — v0.06.3 Part 2.

Covers:
  server/models/marine_teams.py — MarineTeam, generate_marine_teams,
  SHIP_CLASS_MARINES, constants, combat stats, serialise/deserialise.
"""
from __future__ import annotations

import pytest

from server.models.marine_teams import (
    AMMO_PER_COMBAT_TICK,
    AMMO_REARM_RATE,
    DEFAULT_MARINES,
    SHIP_CLASS_MARINES,
    SUPPRESSION_DECAY,
    SUPPRESSION_GAIN,
    MarineTeam,
    generate_marine_teams,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_team(**overrides) -> MarineTeam:
    defaults = dict(
        id="mt_alpha", name="Alpha Squad", callsign="ALPHA",
        members=["m1", "m2", "m3", "m4"], leader="m1",
        size=4, max_size=4, location="conn",
    )
    defaults.update(overrides)
    return MarineTeam(**defaults)


# ---------------------------------------------------------------------------
# Factory — generate_marine_teams
# ---------------------------------------------------------------------------


class TestGenerateMarineTeams:
    def test_frigate_produces_two_teams(self):
        teams = generate_marine_teams("frigate")
        assert len(teams) == 2

    def test_scout_produces_one_team(self):
        teams = generate_marine_teams("scout")
        assert len(teams) == 1

    def test_battleship_produces_three_teams(self):
        teams = generate_marine_teams("battleship")
        assert len(teams) == 3

    def test_team_size_matches_class(self):
        for cls_id, (count, size) in SHIP_CLASS_MARINES.items():
            teams = generate_marine_teams(cls_id)
            assert len(teams) == count, f"{cls_id}: expected {count} teams"
            for t in teams:
                assert t.max_size == size, f"{cls_id}: expected max_size {size}"

    def test_unknown_class_uses_defaults(self):
        teams = generate_marine_teams("unknown_ship")
        count, size = DEFAULT_MARINES
        assert len(teams) == count
        assert all(t.max_size == size for t in teams)

    def test_crew_ids_assigned_to_teams(self):
        crew = [f"crew_{i}" for i in range(8)]
        teams = generate_marine_teams("frigate", crew_member_ids=crew)
        all_members = []
        for t in teams:
            all_members.extend(t.members)
        assert set(all_members) == set(crew)

    def test_leader_is_first_member(self):
        crew = ["leader1", "m2", "m3", "m4", "leader2", "m5", "m6", "m7"]
        teams = generate_marine_teams("frigate", crew_member_ids=crew)
        assert teams[0].leader == "leader1"
        assert teams[1].leader == "leader2"

    def test_teams_start_at_default_positions(self):
        teams = generate_marine_teams("battleship")
        assert teams[0].location == "conn"
        assert teams[1].location == "engine_room"
        assert teams[2].location == "combat_info"

    def test_teams_start_stationed(self):
        teams = generate_marine_teams("frigate")
        for t in teams:
            assert t.status == "stationed"

    def test_full_ammo_at_start(self):
        teams = generate_marine_teams("frigate")
        for t in teams:
            assert t.ammo == pytest.approx(100.0)

    def test_full_effectiveness_at_start(self):
        teams = generate_marine_teams("frigate")
        for t in teams:
            assert t.combat_effectiveness == pytest.approx(1.0)

    def test_no_suppression_at_start(self):
        teams = generate_marine_teams("frigate")
        for t in teams:
            assert t.suppression_level == pytest.approx(0.0)

    def test_placeholder_member_ids_when_no_crew(self):
        teams = generate_marine_teams("scout")
        assert len(teams[0].members) == 3
        assert all(m.startswith("mt_alpha_marine_") for m in teams[0].members)


# ---------------------------------------------------------------------------
# Firepower calculation
# ---------------------------------------------------------------------------


class TestFirepower:
    def test_full_team_full_stats(self):
        team = make_team(size=4, max_size=4, combat_effectiveness=1.0,
                         suppression_level=0.0, ammo=100.0)
        assert team.firepower == pytest.approx(1.0)

    def test_half_team_halves_firepower(self):
        team = make_team(size=2, max_size=4, combat_effectiveness=0.5,
                         suppression_level=0.0, ammo=100.0)
        # base = 2/4 = 0.5, effectiveness = 0.5 → 0.25
        assert team.firepower == pytest.approx(0.25)

    def test_suppression_reduces_firepower(self):
        team = make_team(suppression_level=0.5)
        # suppression_factor = 1 - 0.5 * 0.5 = 0.75
        assert team.firepower == pytest.approx(0.75)

    def test_max_suppression_halves_firepower(self):
        team = make_team(suppression_level=1.0)
        assert team.firepower == pytest.approx(0.5)

    def test_low_ammo_reduces_firepower(self):
        team = make_team(ammo=10.0)
        # ammo_factor = min(10/20, 1.0) = 0.5
        assert team.firepower == pytest.approx(0.5)

    def test_zero_ammo_zero_firepower(self):
        team = make_team(ammo=0.0)
        assert team.firepower == pytest.approx(0.0)

    def test_zero_size_zero_firepower(self):
        team = make_team(size=0)
        assert team.firepower == pytest.approx(0.0)

    def test_firepower_compound_reduction(self):
        team = make_team(size=2, max_size=4, combat_effectiveness=0.5,
                         suppression_level=0.5, ammo=10.0)
        # base=0.5, eff=0.5, supp_factor=0.75, ammo_factor=0.5
        expected = 0.5 * 0.5 * 0.75 * 0.5
        assert team.firepower == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Casualties
# ---------------------------------------------------------------------------


class TestCasualties:
    def test_apply_casualties_reduces_size(self):
        team = make_team(size=4, max_size=4)
        actual = team.apply_casualties(2)
        assert actual == 2
        assert team.size == 2

    def test_apply_casualties_capped_at_current_size(self):
        team = make_team(size=2, max_size=4)
        actual = team.apply_casualties(5)
        assert actual == 2
        assert team.size == 0

    def test_casualties_update_effectiveness(self):
        team = make_team(size=4, max_size=4)
        team.apply_casualties(2)
        assert team.combat_effectiveness == pytest.approx(0.5)

    def test_total_loss_sets_incapacitated(self):
        team = make_team(size=4, max_size=4)
        team.apply_casualties(4)
        assert team.status == "incapacitated"
        assert team.is_incapacitated

    def test_partial_loss_keeps_status(self):
        team = make_team(size=4, max_size=4, status="engaging")
        team.apply_casualties(1)
        assert team.status == "engaging"
        assert not team.is_incapacitated

    def test_casualties_remove_member_ids(self):
        team = make_team(members=["a", "b", "c", "d"], size=4)
        team.apply_casualties(2)
        assert team.members == ["a", "b"]


# ---------------------------------------------------------------------------
# Ammo and suppression
# ---------------------------------------------------------------------------


class TestAmmoSuppression:
    def test_consume_ammo(self):
        team = make_team(ammo=100.0)
        team.consume_ammo()
        assert team.ammo == pytest.approx(100.0 - AMMO_PER_COMBAT_TICK)

    def test_ammo_floor_at_zero(self):
        team = make_team(ammo=1.0)
        team.consume_ammo(5.0)
        assert team.ammo == pytest.approx(0.0)

    def test_rearm_increases_ammo(self):
        team = make_team(ammo=50.0)
        team.rearm(1.0)
        assert team.ammo == pytest.approx(50.0 + AMMO_REARM_RATE)

    def test_rearm_caps_at_100(self):
        team = make_team(ammo=99.0)
        team.rearm(10.0)
        assert team.ammo == pytest.approx(100.0)

    def test_suppress_increases_level(self):
        team = make_team(suppression_level=0.0)
        team.suppress()
        assert team.suppression_level == pytest.approx(SUPPRESSION_GAIN)

    def test_suppression_caps_at_one(self):
        team = make_team(suppression_level=0.95)
        team.suppress(0.1)
        assert team.suppression_level == pytest.approx(1.0)

    def test_decay_suppression(self):
        team = make_team(suppression_level=0.5)
        team.decay_suppression()
        assert team.suppression_level == pytest.approx(0.5 - SUPPRESSION_DECAY)

    def test_suppression_floor_at_zero(self):
        team = make_team(suppression_level=0.02)
        team.decay_suppression()
        assert team.suppression_level == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


class TestOrders:
    def test_order_respond_sets_status(self):
        team = make_team()
        team.order_respond("bridge")
        assert team.status == "responding"
        assert team.destination == "bridge"

    def test_order_patrol_sets_route(self):
        team = make_team()
        team.order_patrol(["bridge", "conn", "engine_room"])
        assert team.status == "patrolling"
        assert team.patrol_route == ["bridge", "conn", "engine_room"]
        assert team.destination == "bridge"

    def test_order_escort_sets_target(self):
        team = make_team()
        team.order_escort("team_alpha")
        assert team.status == "escorting"
        assert team.escort_target == "team_alpha"

    def test_order_station_clears_state(self):
        team = make_team(status="responding", destination="bridge", engagement="bp1")
        team.order_station()
        assert team.status == "stationed"
        assert team.destination is None
        assert team.engagement is None

    def test_engage_sets_engagement(self):
        team = make_team()
        team.engage("bp_001")
        assert team.status == "engaging"
        assert team.engagement == "bp_001"

    def test_disengage_clears_engagement(self):
        team = make_team(status="engaging", engagement="bp_001")
        team.disengage()
        assert team.status == "responding"
        assert team.engagement is None

    def test_is_available_when_stationed(self):
        team = make_team(status="stationed")
        assert team.is_available

    def test_is_available_when_patrolling(self):
        team = make_team(status="patrolling")
        assert team.is_available

    def test_not_available_when_engaging(self):
        team = make_team(status="engaging")
        assert not team.is_available

    def test_not_available_when_incapacitated(self):
        team = make_team(size=0, status="incapacitated")
        assert not team.is_available


# ---------------------------------------------------------------------------
# Serialise / deserialise
# ---------------------------------------------------------------------------


class TestSerialise:
    def test_round_trip(self):
        team = make_team(
            status="patrolling",
            patrol_route=["bridge", "conn"],
            patrol_index=1,
            ammo=72.5,
            suppression_level=0.3,
            combat_effectiveness=0.75,
            destination="conn",
            travel_progress=0.42,
        )
        data = team.to_dict()
        restored = MarineTeam.from_dict(data)
        assert restored.id == team.id
        assert restored.status == "patrolling"
        assert restored.patrol_route == ["bridge", "conn"]
        assert restored.ammo == pytest.approx(72.5)
        assert restored.suppression_level == pytest.approx(0.3)
        assert restored.combat_effectiveness == pytest.approx(0.75)
        assert restored.destination == "conn"
        assert restored.travel_progress == pytest.approx(0.42)

    def test_to_dict_includes_all_fields(self):
        team = make_team()
        data = team.to_dict()
        expected_keys = {
            "id", "name", "callsign", "members", "leader",
            "size", "max_size", "location", "destination",
            "travel_progress", "patrol_route", "patrol_index",
            "status", "engagement", "escort_target",
            "combat_effectiveness", "suppression_level", "ammo",
        }
        assert set(data.keys()) == expected_keys

    def test_from_dict_defaults(self):
        minimal = {"id": "mt_test", "name": "Test", "callsign": "TEST"}
        team = MarineTeam.from_dict(minimal)
        assert team.size == 4
        assert team.ammo == pytest.approx(100.0)
        assert team.status == "stationed"
