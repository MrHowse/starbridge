"""Tests for v0.07 armour system (spec §1.3).

Covers:
  - Armour absorption in damage pipeline (between shields and hull)
  - Armour degradation (−1 per hit absorbed)
  - Field repair cap (75% of armour_max)
  - Full repair at dock (100%)
  - Armour not affected by power allocation
  - Per-class armour values
  - Edge cases (zero armour, excess damage, etc.)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from server.models.ship import Ship
from server.models.ship_class import load_ship_class, SHIP_CLASS_ORDER
from server.systems.combat import (
    ARMOUR_FIELD_REPAIR_CAP,
    apply_hit_to_player,
    repair_armour,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ship(
    armour: float = 10.0,
    armour_max: float = 10.0,
    hull: float = 100.0,
    hull_max: float = 100.0,
    heading: float = 0.0,
) -> Ship:
    """Return a ship with configurable armour, shields zeroed for clean tests."""
    ship = Ship()
    ship.armour = armour
    ship.armour_max = armour_max
    ship.hull = hull
    ship.hull_max = hull_max
    ship.heading = heading
    ship.x = 0.0
    ship.y = 0.0
    # Zero shields so damage goes straight to armour layer.
    ship.shields.fore = 0.0
    ship.shields.aft = 0.0
    ship.shields.port = 0.0
    ship.shields.starboard = 0.0
    return ship


def _no_system_damage_rng() -> MagicMock:
    """Return an rng mock that suppresses system damage and crew casualty rolls."""
    rng = MagicMock()
    rng.random.return_value = 1.0  # above component_damage_chance → no system damage
    return rng


# ---------------------------------------------------------------------------
# 1. Armour absorbs damage between shields and hull (§1.3.1)
# ---------------------------------------------------------------------------


class TestArmourAbsorption:
    def test_armour_absorbs_up_to_its_value(self):
        """15 damage, armour 10 → armour absorbs 10, hull takes 5."""
        ship = make_ship(armour=10.0)
        rng = _no_system_damage_rng()
        apply_hit_to_player(ship, 15.0, 0.0, -1000.0, rng=rng)
        assert ship.hull == pytest.approx(95.0)

    def test_armour_absorbs_all_when_damage_less_than_armour(self):
        """5 damage, armour 10 → armour absorbs all 5, hull untouched."""
        ship = make_ship(armour=10.0)
        rng = _no_system_damage_rng()
        apply_hit_to_player(ship, 5.0, 0.0, -1000.0, rng=rng)
        assert ship.hull == pytest.approx(100.0)

    def test_armour_absorbs_exact_damage(self):
        """10 damage, armour 10 → armour absorbs all 10, hull untouched."""
        ship = make_ship(armour=10.0)
        rng = _no_system_damage_rng()
        apply_hit_to_player(ship, 10.0, 0.0, -1000.0, rng=rng)
        assert ship.hull == pytest.approx(100.0)

    def test_zero_armour_no_absorption(self):
        """0 armour → all damage to hull."""
        ship = make_ship(armour=0.0, armour_max=0.0)
        rng = _no_system_damage_rng()
        apply_hit_to_player(ship, 20.0, 0.0, -1000.0, rng=rng)
        assert ship.hull == pytest.approx(80.0)

    def test_result_reports_armour_absorbed(self):
        """CombatHitResult.armour_absorbed reports the correct amount."""
        ship = make_ship(armour=10.0)
        rng = _no_system_damage_rng()
        result = apply_hit_to_player(ship, 15.0, 0.0, -1000.0, rng=rng)
        assert result.armour_absorbed == pytest.approx(10.0)

    def test_result_armour_absorbed_zero_when_no_armour(self):
        ship = make_ship(armour=0.0, armour_max=0.0)
        rng = _no_system_damage_rng()
        result = apply_hit_to_player(ship, 10.0, 0.0, -1000.0, rng=rng)
        assert result.armour_absorbed == pytest.approx(0.0)

    def test_shields_absorb_before_armour(self):
        """Shields absorb first, then armour takes the remainder."""
        ship = make_ship(armour=10.0)
        ship.shields.fore = 50.0  # can absorb 50 × 0.8 = 40
        rng = _no_system_damage_rng()
        # 30 damage: shields absorb all 30, armour untouched, hull untouched.
        apply_hit_to_player(ship, 30.0, 0.0, -1000.0, rng=rng)
        assert ship.hull == pytest.approx(100.0)
        assert ship.armour == pytest.approx(10.0)  # not degraded

    def test_partial_shield_then_armour(self):
        """Shields partially absorb, armour handles remainder."""
        ship = make_ship(armour=10.0)
        ship.shields.fore = 12.5  # absorbs 12.5 × 0.8 = 10
        rng = _no_system_damage_rng()
        # 25 damage: shields absorb 10, remaining 15 → armour absorbs 10, hull takes 5.
        apply_hit_to_player(ship, 25.0, 0.0, -1000.0, rng=rng)
        assert ship.hull == pytest.approx(95.0)


# ---------------------------------------------------------------------------
# 2. Armour degradation (§1.3.2)
# ---------------------------------------------------------------------------


class TestArmourDegradation:
    def test_armour_degrades_by_one_per_hit(self):
        """Each hit that armour absorbs reduces armour by 1."""
        ship = make_ship(armour=10.0)
        rng = _no_system_damage_rng()
        apply_hit_to_player(ship, 5.0, 0.0, -1000.0, rng=rng)
        assert ship.armour == pytest.approx(9.0)

    def test_armour_degrades_even_on_full_absorption(self):
        """Armour degrades by 1 even when absorbing more than 1 damage."""
        ship = make_ship(armour=10.0)
        rng = _no_system_damage_rng()
        apply_hit_to_player(ship, 8.0, 0.0, -1000.0, rng=rng)
        assert ship.armour == pytest.approx(9.0)

    def test_armour_degrades_on_excess_damage(self):
        """Armour degrades by 1 when damage exceeds armour value."""
        ship = make_ship(armour=10.0)
        rng = _no_system_damage_rng()
        apply_hit_to_player(ship, 50.0, 0.0, -1000.0, rng=rng)
        assert ship.armour == pytest.approx(9.0)

    def test_armour_strips_to_zero_after_many_hits(self):
        """After enough hits, armour reaches 0."""
        ship = make_ship(armour=3.0, armour_max=3.0, hull=500.0, hull_max=500.0)
        rng = _no_system_damage_rng()
        for _ in range(3):
            apply_hit_to_player(ship, 1.0, 0.0, -1000.0, rng=rng)
        assert ship.armour == pytest.approx(0.0)

    def test_armour_does_not_go_below_zero(self):
        """Armour at 1 → after hit → 0, never negative."""
        ship = make_ship(armour=1.0)
        rng = _no_system_damage_rng()
        apply_hit_to_player(ship, 100.0, 0.0, -1000.0, rng=rng)
        assert ship.armour == pytest.approx(0.0)

    def test_no_degradation_when_shields_absorb_all(self):
        """When shields absorb the full hit, armour doesn't degrade."""
        ship = make_ship(armour=10.0)
        ship.shields.fore = 50.0  # absorbs 40 capacity
        rng = _no_system_damage_rng()
        apply_hit_to_player(ship, 5.0, 0.0, -1000.0, rng=rng)
        assert ship.armour == pytest.approx(10.0)  # unchanged

    def test_battleship_40_hits_strips_armour(self):
        """Spec scenario: battleship starts at 40, after 40 hits armour is 0."""
        ship = make_ship(armour=40.0, armour_max=40.0, hull=300.0, hull_max=300.0)
        rng = _no_system_damage_rng()
        for _ in range(40):
            apply_hit_to_player(ship, 1.0, 0.0, -1000.0, rng=rng)
        assert ship.armour == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 3. Field repair cap (§1.3.3)
# ---------------------------------------------------------------------------


class TestArmourFieldRepair:
    def test_field_repair_cap_is_75_percent(self):
        assert ARMOUR_FIELD_REPAIR_CAP == pytest.approx(0.75)

    def test_repair_to_cap(self):
        """Field repair restores armour up to 75% of armour_max."""
        ship = make_ship(armour=0.0, armour_max=40.0)
        restored = repair_armour(ship, 100.0)  # request more than cap
        assert ship.armour == pytest.approx(30.0)  # 40 × 0.75
        assert restored == pytest.approx(30.0)

    def test_repair_partial(self):
        """Partial repair within cap."""
        ship = make_ship(armour=0.0, armour_max=40.0)
        restored = repair_armour(ship, 10.0)
        assert ship.armour == pytest.approx(10.0)
        assert restored == pytest.approx(10.0)

    def test_repair_already_at_cap(self):
        """No repair when already at or above 75% cap."""
        ship = make_ship(armour=30.0, armour_max=40.0)  # exactly 75%
        restored = repair_armour(ship, 10.0)
        assert ship.armour == pytest.approx(30.0)
        assert restored == pytest.approx(0.0)

    def test_repair_above_cap_no_change(self):
        """If armour is above 75% (possible after dock), field repair does nothing."""
        ship = make_ship(armour=35.0, armour_max=40.0)
        restored = repair_armour(ship, 10.0)
        assert ship.armour == pytest.approx(35.0)
        assert restored == pytest.approx(0.0)

    def test_repair_zero_armour_max(self):
        """Ship with no armour (scout) → no repair."""
        ship = make_ship(armour=0.0, armour_max=0.0)
        restored = repair_armour(ship, 10.0)
        assert ship.armour == pytest.approx(0.0)
        assert restored == pytest.approx(0.0)

    def test_repair_caps_partial_fill(self):
        """Repair from 20 to 30 (cap) when requesting 15."""
        ship = make_ship(armour=20.0, armour_max=40.0)
        restored = repair_armour(ship, 15.0)
        assert ship.armour == pytest.approx(30.0)
        assert restored == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# 4. Dock restores armour to 100% (§1.3.3)
# ---------------------------------------------------------------------------


class TestArmourDockRepair:
    def test_dock_hull_repair_restores_full_armour(self):
        """hull_repair at dock restores armour to armour_max."""
        from server.game_loop_docking import _apply_service
        ship = make_ship(armour=5.0, armour_max=40.0, hull=200.0, hull_max=300.0)
        effects = _apply_service("hull_repair", None, ship)
        assert ship.armour == pytest.approx(40.0)
        assert effects.get("armour_restored") == pytest.approx(35.0)
        assert ship.hull == pytest.approx(300.0)

    def test_dock_hull_repair_no_armour_change_when_full(self):
        """When armour is already full, no armour_restored key."""
        from server.game_loop_docking import _apply_service
        ship = make_ship(armour=10.0, armour_max=10.0, hull=100.0, hull_max=100.0)
        effects = _apply_service("hull_repair", None, ship)
        assert "armour_restored" not in effects


# ---------------------------------------------------------------------------
# 5. Armour not affected by power allocation (§1.3.4)
# ---------------------------------------------------------------------------


class TestArmourPowerIndependent:
    def test_armour_works_with_zero_power(self):
        """Armour absorbs regardless of system power levels."""
        ship = make_ship(armour=10.0)
        for sys_obj in ship.systems.values():
            sys_obj.power = 0.0
        rng = _no_system_damage_rng()
        apply_hit_to_player(ship, 15.0, 0.0, -1000.0, rng=rng)
        assert ship.hull == pytest.approx(95.0)  # only 5 passed through
        assert ship.armour == pytest.approx(9.0)

    def test_armour_works_with_systems_offline(self):
        """Even with captain-offline systems, armour functions."""
        ship = make_ship(armour=20.0)
        for sys_obj in ship.systems.values():
            sys_obj._captain_offline = True
        rng = _no_system_damage_rng()
        apply_hit_to_player(ship, 10.0, 0.0, -1000.0, rng=rng)
        assert ship.hull == pytest.approx(100.0)
        assert ship.armour == pytest.approx(19.0)


# ---------------------------------------------------------------------------
# 6. Per-class armour values (§1.3.7)
# ---------------------------------------------------------------------------


class TestClassArmourValues:
    @pytest.mark.parametrize("class_id,expected_armour", [
        ("scout", 0.0),
        ("corvette", 5.0),
        ("frigate", 10.0),
        ("cruiser", 20.0),
        ("battleship", 40.0),
        ("carrier", 15.0),
        ("medical_ship", 5.0),
    ])
    def test_class_armour(self, class_id, expected_armour):
        sc = load_ship_class(class_id)
        assert sc.armour == pytest.approx(expected_armour)

    def test_combat_progression_armour_increases(self):
        """Combat line (scout→corvette→frigate→cruiser→battleship) has increasing armour."""
        combat_ids = ["scout", "corvette", "frigate", "cruiser", "battleship"]
        values = [load_ship_class(cid).armour for cid in combat_ids]
        assert values == sorted(values), f"Armour not monotonically increasing: {values}"

    def test_battleship_has_highest_armour(self):
        highest = max(load_ship_class(cid).armour for cid in SHIP_CLASS_ORDER)
        assert load_ship_class("battleship").armour == highest

    def test_scout_has_zero_armour(self):
        """Scout has no armour — all damage passes through."""
        assert load_ship_class("scout").armour == 0.0


# ---------------------------------------------------------------------------
# 7. ship.state broadcast includes armour (§1.3.5 / §1.3.6)
# ---------------------------------------------------------------------------


class TestArmourInBroadcast:
    def test_ship_state_includes_armour_fields(self):
        """The ship.state broadcast dict includes armour and armour_max."""
        from server.game_loop import _build_ship_state
        ship = Ship()
        ship.armour = 15.0
        ship.armour_max = 20.0
        msg = _build_ship_state(ship, tick=0)
        payload = msg.payload
        assert payload["armour"] == 15.0
        assert payload["armour_max"] == 20.0


# ---------------------------------------------------------------------------
# 8. Save/resume round-trip (§5.3.3)
# ---------------------------------------------------------------------------


class TestArmourSaveResume:
    def test_serialise_includes_armour(self):
        from server.save_system import _serialise_ship
        ship = Ship()
        ship.armour = 17.5
        ship.armour_max = 40.0
        data = _serialise_ship(ship)
        assert data["armour"] == 17.5
        assert data["armour_max"] == 40.0

    def test_deserialise_restores_armour(self):
        from server.save_system import _serialise_ship, _deserialise_ship
        ship = Ship()
        ship.armour = 17.5
        ship.armour_max = 40.0
        data = _serialise_ship(ship)
        new_ship = Ship()
        _deserialise_ship(data, new_ship)
        assert new_ship.armour == pytest.approx(17.5)
        assert new_ship.armour_max == pytest.approx(40.0)
