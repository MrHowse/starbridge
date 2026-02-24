"""Tests for BoardingParty model and factory — v0.06.3 Part 3.

Covers:
  server/models/boarding.py — BoardingParty, generate_boarding_party,
  select_objective, combat power, morale, serialise/deserialise.
"""
from __future__ import annotations

import random

import pytest

from server.models.boarding import (
    MAX_BOARDING_SIZE,
    MIN_BOARDING_SIZE,
    MORALE_LOSS_PER_CASUALTY,
    MORALE_RETREAT_THRESHOLD,
    OBJECTIVES,
    BoardingParty,
    generate_boarding_party,
    select_objective,
)
from server.models.interior import make_default_interior


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_party(**overrides) -> BoardingParty:
    defaults = dict(
        id="bp_001", entry_point="cargo_hold", location="cargo_hold",
        objective="bridge", objective_room="bridge",
        members=6, max_members=6,
    )
    defaults.update(overrides)
    return BoardingParty(**defaults)


# ---------------------------------------------------------------------------
# Combat power
# ---------------------------------------------------------------------------


class TestCombatPower:
    def test_full_party_with_leader(self):
        party = make_party(members=6, firepower=0.8, leader_alive=True, morale=1.0)
        # 6 * 0.8 * 1.2 (leader) * (0.5 + 1.0*0.5) = 6 * 0.8 * 1.2 * 1.0 = 5.76
        assert party.combat_power == pytest.approx(5.76)

    def test_no_leader_reduces_power(self):
        party = make_party(members=6, firepower=0.8, leader_alive=False, morale=1.0)
        # 6 * 0.8 * 1.0 * 1.0 = 4.8
        assert party.combat_power == pytest.approx(4.8)

    def test_low_morale_reduces_power(self):
        party = make_party(members=6, firepower=0.8, leader_alive=True, morale=0.5)
        # morale_factor = 0.5 + 0.5*0.5 = 0.75
        # 6 * 0.8 * 1.2 * 0.75 = 4.32
        assert party.combat_power == pytest.approx(4.32)

    def test_zero_members_zero_power(self):
        party = make_party(members=0)
        assert party.combat_power == pytest.approx(0.0)

    def test_zero_morale_halves_base(self):
        party = make_party(members=6, firepower=0.8, leader_alive=True, morale=0.0)
        # morale_factor = 0.5
        # 6 * 0.8 * 1.2 * 0.5 = 2.88
        assert party.combat_power == pytest.approx(2.88)


# ---------------------------------------------------------------------------
# Casualties
# ---------------------------------------------------------------------------


class TestCasualties:
    def test_apply_casualties_reduces_members(self):
        party = make_party(members=6, max_members=6)
        actual = party.apply_casualties(2)
        assert actual == 2
        assert party.members == 4

    def test_apply_casualties_capped(self):
        party = make_party(members=3)
        actual = party.apply_casualties(10)
        assert actual == 3
        assert party.members == 0

    def test_casualties_reduce_morale(self):
        party = make_party(morale=1.0)
        party.apply_casualties(3)
        expected_morale = 1.0 - 3 * MORALE_LOSS_PER_CASUALTY
        assert party.morale == pytest.approx(expected_morale)

    def test_morale_floors_at_zero(self):
        party = make_party(morale=0.1)
        party.apply_casualties(5)
        assert party.morale >= 0.0

    def test_total_loss_eliminates(self):
        party = make_party(members=2)
        party.apply_casualties(2)
        assert party.status == "eliminated"
        assert party.is_eliminated
        assert not party.leader_alive

    def test_partial_loss_preserves_status(self):
        party = make_party(members=6, status="advancing")
        party.apply_casualties(1)
        assert party.status == "advancing"


# ---------------------------------------------------------------------------
# Morale
# ---------------------------------------------------------------------------


class TestMorale:
    def test_check_morale_triggers_retreat(self):
        party = make_party(morale=MORALE_RETREAT_THRESHOLD - 0.01, status="advancing")
        retreated = party.check_morale()
        assert retreated is True
        assert party.status == "retreating"

    def test_check_morale_no_retreat_above_threshold(self):
        party = make_party(morale=0.5, status="advancing")
        retreated = party.check_morale()
        assert retreated is False
        assert party.status == "advancing"

    def test_check_morale_already_retreating_no_double(self):
        party = make_party(morale=0.1, status="retreating")
        retreated = party.check_morale()
        assert retreated is False  # already retreating

    def test_low_members_erodes_morale(self):
        party = make_party(members=2, max_members=8, morale=0.5, status="advancing")
        party.check_morale()
        assert party.morale < 0.5


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestProperties:
    def test_is_at_objective_true(self):
        party = make_party(location="bridge", objective_room="bridge")
        assert party.is_at_objective

    def test_is_at_objective_false(self):
        party = make_party(location="cargo_hold", objective_room="bridge")
        assert not party.is_at_objective

    def test_damage_reduction_from_armour(self):
        party = make_party(armour=0.3)
        assert party.damage_reduction == pytest.approx(0.3)

    def test_damage_reduction_capped(self):
        party = make_party(armour=0.95)
        assert party.damage_reduction == pytest.approx(0.8)

    def test_is_eliminated_false_with_members(self):
        party = make_party(members=1)
        assert not party.is_eliminated

    def test_is_eliminated_true_at_zero(self):
        party = make_party(members=0, status="eliminated")
        assert party.is_eliminated


# ---------------------------------------------------------------------------
# select_objective
# ---------------------------------------------------------------------------


class TestSelectObjective:
    def test_returns_valid_objective(self):
        rng = random.Random(42)
        for _ in range(50):
            obj = select_objective("cargo_hold", rng)
            assert obj in OBJECTIVES

    def test_entry_point_biases_selection(self):
        rng = random.Random(42)
        counts: dict[str, int] = {}
        for _ in range(1000):
            obj = select_objective("cargo_hold", rng)
            counts[obj] = counts.get(obj, 0) + 1
        # Cargo hold entry should favour cargo/reactor
        assert counts.get("cargo", 0) > counts.get("bridge", 0)

    def test_unknown_entry_uses_defaults(self):
        rng = random.Random(42)
        obj = select_objective("unknown_room", rng)
        assert obj in OBJECTIVES


# ---------------------------------------------------------------------------
# generate_boarding_party
# ---------------------------------------------------------------------------


class TestGenerate:
    def test_generates_party_with_correct_id(self):
        party = generate_boarding_party("bp_test", rng=random.Random(42))
        assert party.id == "bp_test"

    def test_size_within_bounds(self):
        rng = random.Random(42)
        for _ in range(50):
            party = generate_boarding_party("bp", rng=rng)
            assert MIN_BOARDING_SIZE <= party.members <= MAX_BOARDING_SIZE * 2

    def test_difficulty_scales_size(self):
        rng = random.Random(42)
        normal = generate_boarding_party("bp1", difficulty_scale=1.0, rng=random.Random(42))
        hard = generate_boarding_party("bp2", difficulty_scale=2.0, rng=random.Random(42))
        assert hard.members >= normal.members

    def test_objective_override(self):
        party = generate_boarding_party("bp", objective_override="medical",
                                        rng=random.Random(42))
        assert party.objective == "medical"
        assert party.objective_room == "medbay"

    def test_entry_deck_inferred(self):
        party = generate_boarding_party("bp", entry_point="bridge",
                                        rng=random.Random(42))
        assert party.entry_deck == 1

    def test_path_calculated_with_interior(self):
        interior = make_default_interior()
        party = generate_boarding_party(
            "bp", entry_point="cargo_hold",
            objective_override="bridge", interior=interior,
            rng=random.Random(42),
        )
        assert len(party.path) >= 2
        assert party.path[0] == "cargo_hold"
        assert party.path[-1] == "bridge"

    def test_no_path_without_interior(self):
        party = generate_boarding_party("bp", rng=random.Random(42))
        assert party.path == []

    def test_starts_advancing(self):
        party = generate_boarding_party("bp", rng=random.Random(42))
        assert party.status == "advancing"

    def test_full_morale_at_start(self):
        party = generate_boarding_party("bp", rng=random.Random(42))
        assert party.morale == pytest.approx(1.0)

    def test_leader_alive_at_start(self):
        party = generate_boarding_party("bp", rng=random.Random(42))
        assert party.leader_alive is True


# ---------------------------------------------------------------------------
# Serialise / deserialise
# ---------------------------------------------------------------------------


class TestSerialise:
    def test_round_trip(self):
        party = make_party(
            status="sabotaging",
            sabotage_progress=0.65,
            morale=0.45,
            path=["cargo_hold", "engine_room", "bridge"],
            path_index=1,
            engaged_by="mt_alpha",
            breach_progress=5.2,
        )
        data = party.to_dict()
        restored = BoardingParty.from_dict(data)
        assert restored.id == party.id
        assert restored.status == "sabotaging"
        assert restored.sabotage_progress == pytest.approx(0.65)
        assert restored.morale == pytest.approx(0.45)
        assert restored.path == ["cargo_hold", "engine_room", "bridge"]
        assert restored.path_index == 1
        assert restored.engaged_by == "mt_alpha"
        assert restored.breach_progress == pytest.approx(5.2)

    def test_to_dict_keys(self):
        party = make_party()
        data = party.to_dict()
        expected_keys = {
            "id", "source", "faction", "entry_point", "entry_deck",
            "members", "max_members", "leader_alive",
            "location", "objective", "objective_room", "path", "path_index",
            "status", "engaged_by", "sabotage_progress", "morale",
            "advance_progress", "breach_progress", "firepower", "armour",
        }
        assert set(data.keys()) == expected_keys

    def test_from_dict_defaults(self):
        minimal = {"id": "bp_min"}
        party = BoardingParty.from_dict(minimal)
        assert party.members == 6
        assert party.morale == pytest.approx(1.0)
        assert party.status == "advancing"
