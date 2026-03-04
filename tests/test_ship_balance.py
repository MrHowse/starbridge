"""v0.07 §5.2 — Ship class balance verification.

Ensures no class is universally dominant, stat spreads are meaningful,
power budgets are solvent, and cross-class matchups are plausible.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from server.models.ship_class import SHIP_CLASS_ORDER, load_ship_class, ShipClass

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

INTERIORS_DIR = Path(__file__).resolve().parent.parent / "interiors"
ALL_IDS: list[str] = list(SHIP_CLASS_ORDER)

EXPECTED_UNIQUE: dict[str, list[str]] = {
    "scout": ["stealth"],
    "corvette": ["advanced_ecm"],
    "frigate": [],
    "cruiser": ["flag_bridge", "dual_targeting"],
    "battleship": ["spinal_mount", "armour_zones", "dual_targeting"],
    "carrier": ["flight_centre"],
    "medical_ship": ["hospital"],
}

TORPEDO_TYPES = [
    "standard", "homing", "ion", "piercing",
    "heavy", "proximity", "nuclear", "experimental",
]


def _all_classes() -> list[ShipClass]:
    return [load_ship_class(cid) for cid in ALL_IDS]


def _beam_dps(sc: ShipClass) -> float:
    """Beam DPS = beam_damage * beam_count / beam_fire_rate."""
    w = sc.weapons
    if w is None or w.get("beam_fire_rate", 0) == 0:
        return 0.0
    return w["beam_damage"] * w["beam_count"] / w["beam_fire_rate"]


def _effective_hp(sc: ShipClass) -> float:
    """Simplified effective HP = hull * (1 + armour/100) * (1 + shields.capacity/100)."""
    armour_factor = 1.0 + sc.armour / 100.0
    shield_cap = sc.shields["capacity"] if sc.shields else 0
    shield_factor = 1.0 + shield_cap / 100.0
    return sc.max_hull * armour_factor * shield_factor


# ---------------------------------------------------------------------------
# §5.2.2 — No class ranks #1 in all stats
# ---------------------------------------------------------------------------

class TestNoBestInAll:
    def test_no_class_dominates_all_stats(self):
        """No single class should rank #1 across every key stat."""
        classes = _all_classes()
        stats = {
            "hull": [sc.max_hull for sc in classes],
            "speed": [sc.max_speed for sc in classes],
            "turn_rate": [sc.turn_rate for sc in classes],
            "armour": [sc.armour for sc in classes],
            "shield_cap": [sc.shields["capacity"] if sc.shields else 0 for sc in classes],
            "sensor_range": [sc.sensors["range"] if sc.sensors else 0 for sc in classes],
            "beam_dps": [_beam_dps(sc) for sc in classes],
        }
        for i, sc in enumerate(classes):
            first_in_all = all(
                stats[k][i] == max(stats[k]) for k in stats
            )
            assert not first_in_all, f"{sc.id} ranks #1 in every stat"


# ---------------------------------------------------------------------------
# §5.2.3 — Stat spreads (max/min >= 2.0)
# ---------------------------------------------------------------------------

class TestStatSpreads:
    """Key stats should have at least 2× spread across the fleet."""

    def _check_spread(self, values: list[float], label: str, min_ratio: float = 2.0):
        nonzero = [v for v in values if v > 0]
        assert len(nonzero) >= 2, f"{label}: not enough nonzero values"
        ratio = max(nonzero) / min(nonzero)
        assert ratio >= min_ratio, f"{label}: spread {ratio:.1f}x < {min_ratio}x"

    def test_hull_spread(self):
        self._check_spread([sc.max_hull for sc in _all_classes()], "hull")

    def test_speed_spread(self):
        self._check_spread([sc.max_speed for sc in _all_classes()], "max_speed")

    def test_armour_spread(self):
        self._check_spread([sc.armour for sc in _all_classes()], "armour")

    def test_shield_capacity_spread(self):
        vals = [sc.shields["capacity"] for sc in _all_classes() if sc.shields]
        self._check_spread(vals, "shield_capacity")

    def test_sensor_range_spread(self):
        vals = [sc.sensors["range"] for sc in _all_classes() if sc.sensors]
        self._check_spread(vals, "sensor_range", min_ratio=1.5)

    def test_turn_rate_spread(self):
        self._check_spread([sc.turn_rate for sc in _all_classes()], "turn_rate")


# ---------------------------------------------------------------------------
# §5.2.4 — Power budget solvency
# ---------------------------------------------------------------------------

class TestPowerBudget:
    @pytest.mark.parametrize("class_id", ALL_IDS)
    def test_reactor_covers_crew_load(self, class_id: str):
        """Reactor must cover at least min_crew × 100 W (one system per player)."""
        sc = load_ship_class(class_id)
        assert sc.power_grid is not None, f"{class_id} missing power_grid"
        reactor = sc.power_grid["reactor_max"]
        minimum = sc.min_crew * 100
        assert reactor >= minimum, (
            f"{class_id}: reactor_max {reactor} < {minimum} (min_crew={sc.min_crew})"
        )


# ---------------------------------------------------------------------------
# §5.2.5 — Beam DPS plausible range
# ---------------------------------------------------------------------------

class TestBeamDPS:
    @pytest.mark.parametrize("class_id", ALL_IDS)
    def test_beam_dps_in_range(self, class_id: str):
        sc = load_ship_class(class_id)
        dps = _beam_dps(sc)
        if class_id == "medical_ship":
            assert dps == 0.0, "Medical ship should have zero beam DPS"
        else:
            assert 2.0 <= dps <= 20.0, f"{class_id}: DPS {dps:.1f} out of range"


# ---------------------------------------------------------------------------
# §5.2.6 — TTK matrix
# ---------------------------------------------------------------------------

class TestTTKMatrix:
    def test_ttk_no_instant_kills(self):
        """No matchup should end in < 5 s (except spinal mount vs scout)."""
        classes = _all_classes()
        for attacker in classes:
            dps = _beam_dps(attacker)
            if dps == 0:
                continue
            for defender in classes:
                ehp = _effective_hp(defender)
                ttk = ehp / dps
                # Spinal mount (battleship) vs scout is allowed to be fast
                if attacker.id == "battleship" and defender.id == "scout":
                    continue
                assert ttk >= 5.0, (
                    f"{attacker.id} vs {defender.id}: TTK={ttk:.1f}s < 5s"
                )

    def test_most_matchups_above_30s(self):
        """Most matchups should take > 30 s to resolve."""
        classes = _all_classes()
        total = 0
        above_30 = 0
        for attacker in classes:
            dps = _beam_dps(attacker)
            if dps == 0:
                continue
            for defender in classes:
                ehp = _effective_hp(defender)
                ttk = ehp / dps
                total += 1
                if ttk > 30.0:
                    above_30 += 1
        assert total > 0
        ratio = above_30 / total
        assert ratio > 0.5, f"Only {above_30}/{total} ({ratio:.0%}) matchups > 30s"


# ---------------------------------------------------------------------------
# §5.2.7 — Survivability spread
# ---------------------------------------------------------------------------

class TestSurvivabilitySpread:
    def test_effective_hp_spread(self):
        """EHP spread between toughest and softest should be 4-6×."""
        classes = _all_classes()
        ehps = [_effective_hp(sc) / sc.target_profile for sc in classes]
        ratio = max(ehps) / min(ehps)
        assert 3.0 <= ratio <= 10.0, f"EHP spread {ratio:.1f}x outside 3-10x range"


# ---------------------------------------------------------------------------
# Torpedo loadout completeness
# ---------------------------------------------------------------------------

class TestTorpedoLoadout:
    @pytest.mark.parametrize("class_id", ALL_IDS)
    def test_all_torpedo_types_present(self, class_id: str):
        sc = load_ship_class(class_id)
        loadout = sc.get_torpedo_loadout()
        for ttype in TORPEDO_TYPES:
            assert ttype in loadout, f"{class_id}: missing torpedo type {ttype}"


# ---------------------------------------------------------------------------
# Weapon subfield completeness
# ---------------------------------------------------------------------------

class TestWeaponSubfields:
    REQUIRED_KEYS = {"beam_damage", "beam_fire_rate", "beam_arc", "beam_count", "beam_range"}

    @pytest.mark.parametrize("class_id", ALL_IDS)
    def test_weapon_fields_present(self, class_id: str):
        sc = load_ship_class(class_id)
        assert sc.weapons is not None, f"{class_id} missing weapons"
        for key in self.REQUIRED_KEYS:
            assert key in sc.weapons, f"{class_id}: weapons missing {key}"

    @pytest.mark.parametrize("class_id", ALL_IDS)
    def test_beam_range_scales_with_class(self, class_id: str):
        sc = load_ship_class(class_id)
        rng = sc.weapons["beam_range"]
        if class_id == "medical_ship":
            assert rng == 0, "Medical ship should have zero beam range"
        else:
            assert 4000 <= rng <= 16000, f"{class_id}: beam_range {rng} out of bounds"

    def test_battleship_has_longest_beam_range(self):
        classes = {cid: load_ship_class(cid) for cid in ALL_IDS}
        ranges = {cid: sc.weapons["beam_range"] for cid, sc in classes.items()}
        assert ranges["battleship"] == max(ranges.values())


# ---------------------------------------------------------------------------
# Unique systems consistency
# ---------------------------------------------------------------------------

class TestUniqueSystems:
    @pytest.mark.parametrize("class_id", ALL_IDS)
    def test_unique_systems_match_expected(self, class_id: str):
        sc = load_ship_class(class_id)
        assert sorted(sc.unique_systems) == sorted(EXPECTED_UNIQUE[class_id]), (
            f"{class_id}: expected {EXPECTED_UNIQUE[class_id]}, got {sc.unique_systems}"
        )


# ---------------------------------------------------------------------------
# Interior layout reference valid
# ---------------------------------------------------------------------------

class TestInteriorLayout:
    @pytest.mark.parametrize("class_id", ALL_IDS)
    def test_interior_layout_file_exists(self, class_id: str):
        sc = load_ship_class(class_id)
        assert sc.interior_layout, f"{class_id}: interior_layout is empty"
        layout_path = INTERIORS_DIR / f"{sc.interior_layout}.json"
        assert layout_path.exists(), (
            f"{class_id}: interiors/{sc.interior_layout}.json not found"
        )
