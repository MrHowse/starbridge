"""
Tests for v0.03o — Ship Class Balancing.

Covers:
  - All 7 ship classes load without error
  - Hull progression is ordered: scout < corvette < frigate < cruiser < battleship
  - Crew ranges are valid (min >= 1, max <= 12, min < max)
  - Torpedo ammo progression makes sense
  - medical_ship and carrier exist with appropriate specs
  - list_ship_classes() returns classes in canonical order
  - Backward-compatible defaults for min_crew / max_crew
"""
from __future__ import annotations

import pytest

from server.models.ship_class import ShipClass, load_ship_class, list_ship_classes, SHIP_CLASS_ORDER

ALL_IDS = ["scout", "corvette", "frigate", "cruiser", "battleship", "medical_ship", "carrier"]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


class TestShipClassLoading:
    @pytest.mark.parametrize("ship_id", ALL_IDS)
    def test_loads_without_error(self, ship_id):
        sc = load_ship_class(ship_id)
        assert sc.id == ship_id

    def test_unknown_id_raises(self):
        with pytest.raises(FileNotFoundError):
            load_ship_class("nonexistent_class")

    def test_list_ship_classes_returns_all_canonical(self):
        classes = list_ship_classes()
        ids = [sc.id for sc in classes]
        for cid in ["scout", "corvette", "frigate", "cruiser", "battleship"]:
            assert cid in ids

    def test_list_ship_classes_includes_specialised(self):
        classes = list_ship_classes()
        ids = [sc.id for sc in classes]
        assert "medical_ship" in ids
        assert "carrier" in ids

    def test_list_ship_classes_order_matches_canonical(self):
        classes = list_ship_classes()
        ids = [sc.id for sc in classes]
        for i, expected_id in enumerate(SHIP_CLASS_ORDER):
            if expected_id in ids:
                assert ids.index(expected_id) == i


# ---------------------------------------------------------------------------
# Hull values
# ---------------------------------------------------------------------------


class TestHullValues:
    def test_scout_hull_lowest(self):
        assert load_ship_class("scout").max_hull < load_ship_class("corvette").max_hull

    def test_corvette_hull_less_than_frigate(self):
        assert load_ship_class("corvette").max_hull < load_ship_class("frigate").max_hull

    def test_frigate_hull_less_than_cruiser(self):
        assert load_ship_class("frigate").max_hull < load_ship_class("cruiser").max_hull

    def test_cruiser_hull_less_than_battleship(self):
        assert load_ship_class("cruiser").max_hull < load_ship_class("battleship").max_hull

    def test_battleship_hull_highest_combat(self):
        assert load_ship_class("battleship").max_hull == 200

    def test_scout_hull_is_60(self):
        assert load_ship_class("scout").max_hull == 60

    def test_frigate_hull_is_100(self):
        assert load_ship_class("frigate").max_hull == 100

    @pytest.mark.parametrize("ship_id", ALL_IDS)
    def test_hull_positive(self, ship_id):
        assert load_ship_class(ship_id).max_hull > 0


# ---------------------------------------------------------------------------
# Torpedo ammo
# ---------------------------------------------------------------------------


class TestTorpedoAmmo:
    def test_scout_lowest_ammo(self):
        assert load_ship_class("scout").torpedo_ammo < load_ship_class("frigate").torpedo_ammo

    def test_battleship_highest_ammo(self):
        assert load_ship_class("battleship").torpedo_ammo >= load_ship_class("cruiser").torpedo_ammo

    def test_medical_ship_low_ammo(self):
        # Medical ship is a support vessel — lightly armed.
        assert load_ship_class("medical_ship").torpedo_ammo <= load_ship_class("frigate").torpedo_ammo

    @pytest.mark.parametrize("ship_id", ALL_IDS)
    def test_ammo_non_negative(self, ship_id):
        assert load_ship_class(ship_id).torpedo_ammo >= 0


# ---------------------------------------------------------------------------
# Crew ranges
# ---------------------------------------------------------------------------


class TestCrewRanges:
    @pytest.mark.parametrize("ship_id", ALL_IDS)
    def test_min_crew_at_least_1(self, ship_id):
        assert load_ship_class(ship_id).min_crew >= 1

    @pytest.mark.parametrize("ship_id", ALL_IDS)
    def test_max_crew_at_most_12(self, ship_id):
        assert load_ship_class(ship_id).max_crew <= 12

    @pytest.mark.parametrize("ship_id", ALL_IDS)
    def test_min_less_than_max(self, ship_id):
        sc = load_ship_class(ship_id)
        assert sc.min_crew < sc.max_crew

    def test_scout_min_crew_is_3(self):
        assert load_ship_class("scout").min_crew == 3

    def test_scout_max_crew_is_4(self):
        assert load_ship_class("scout").max_crew == 4

    def test_battleship_max_crew_is_12(self):
        assert load_ship_class("battleship").max_crew == 12

    def test_battleship_min_crew_high(self):
        # Battleship needs at least 10 players to work well.
        assert load_ship_class("battleship").min_crew >= 10

    def test_crew_progression(self):
        # Scout < Corvette < Frigate in min_crew.
        scout    = load_ship_class("scout").min_crew
        corvette = load_ship_class("corvette").min_crew
        frigate  = load_ship_class("frigate").min_crew
        assert scout <= corvette <= frigate

    def test_medical_ship_crew_range(self):
        sc = load_ship_class("medical_ship")
        assert 4 <= sc.min_crew <= 6
        assert 7 <= sc.max_crew <= 9

    def test_carrier_crew_range(self):
        sc = load_ship_class("carrier")
        assert sc.min_crew >= 5
        assert sc.max_crew >= 10


# ---------------------------------------------------------------------------
# Specialised ship classes
# ---------------------------------------------------------------------------


class TestSpecialisedShips:
    def test_medical_ship_lower_hull_than_cruiser(self):
        # Medical ship is a support vessel, not a warship.
        assert load_ship_class("medical_ship").max_hull < load_ship_class("cruiser").max_hull

    def test_carrier_mid_range_hull(self):
        # Carrier sits between corvette and cruiser in durability.
        sc = load_ship_class("carrier")
        assert load_ship_class("corvette").max_hull <= sc.max_hull <= load_ship_class("cruiser").max_hull

    def test_medical_ship_has_description(self):
        sc = load_ship_class("medical_ship")
        assert len(sc.description) > 20
        assert "medical" in sc.description.lower() or "hospital" in sc.description.lower()

    def test_carrier_has_description(self):
        sc = load_ship_class("carrier")
        assert len(sc.description) > 20
        assert "drone" in sc.description.lower() or "flight" in sc.description.lower()


# ---------------------------------------------------------------------------
# ShipClass model defaults (backward-compatibility)
# ---------------------------------------------------------------------------


class TestShipClassDefaults:
    def test_min_crew_default(self):
        sc = ShipClass(id="test", name="Test", description="desc")
        assert sc.min_crew == 1

    def test_max_crew_default(self):
        sc = ShipClass(id="test", name="Test", description="desc")
        assert sc.max_crew == 12

    def test_max_hull_default(self):
        sc = ShipClass(id="test", name="Test", description="desc")
        assert sc.max_hull == 100.0

    def test_torpedo_ammo_default(self):
        sc = ShipClass(id="test", name="Test", description="desc")
        assert sc.torpedo_ammo == 12
