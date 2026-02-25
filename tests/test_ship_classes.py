"""
Tests for ship class data (v0.03o + v0.07 physical profiles).

Covers:
  - All 7 ship classes load without error
  - Hull progression is ordered: scout < corvette < frigate < cruiser < battleship
  - Crew ranges are valid
  - Torpedo ammo progression makes sense
  - medical_ship and carrier exist with appropriate specs
  - list_ship_classes() returns classes in canonical order
  - v0.07: Physical profiles (max_speed, acceleration, turn_rate, target_profile, armour, handling_trait, decks)
  - v0.07: Exact stat values match spec 1.1.X
  - v0.07: Stat spreads have 2x+ variation between extremes
  - v0.07: Game_loop wires class stats to Ship
"""
from __future__ import annotations

import pytest

from server.models.ship_class import ShipClass, load_ship_class, list_ship_classes, SHIP_CLASS_ORDER, VALID_HANDLING_TRAITS

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
        assert load_ship_class("battleship").max_hull == 300

    def test_scout_hull_is_60(self):
        assert load_ship_class("scout").max_hull == 60

    def test_frigate_hull_is_120(self):
        assert load_ship_class("frigate").max_hull == 120

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

    def test_carrier_hull_is_200(self):
        # Carrier is a large ship — hull matches spec 1.1.6.1.
        assert load_ship_class("carrier").max_hull == 200

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


# ---------------------------------------------------------------------------
# v0.07: Exact physical stats per class (spec 1.1.X)
# ---------------------------------------------------------------------------


class TestScoutPhysical:
    """Spec 1.1.1: Scout physical profile."""
    def test_hull(self):         assert load_ship_class("scout").max_hull == 60
    def test_max_speed(self):    assert load_ship_class("scout").max_speed == 250
    def test_acceleration(self): assert load_ship_class("scout").acceleration == 50
    def test_turn_rate(self):    assert load_ship_class("scout").turn_rate == 180
    def test_target_profile(self): assert load_ship_class("scout").target_profile == 0.5
    def test_armour(self):       assert load_ship_class("scout").armour == 0
    def test_decks(self):        assert load_ship_class("scout").decks == 3
    def test_handling(self):     assert load_ship_class("scout").handling_trait == "twitchy"


class TestCorvettePhysical:
    """Spec 1.1.2: Corvette physical profile."""
    def test_hull(self):         assert load_ship_class("corvette").max_hull == 90
    def test_max_speed(self):    assert load_ship_class("corvette").max_speed == 200
    def test_acceleration(self): assert load_ship_class("corvette").acceleration == 40
    def test_turn_rate(self):    assert load_ship_class("corvette").turn_rate == 120
    def test_target_profile(self): assert load_ship_class("corvette").target_profile == 0.6
    def test_armour(self):       assert load_ship_class("corvette").armour == 5
    def test_decks(self):        assert load_ship_class("corvette").decks == 4
    def test_handling(self):     assert load_ship_class("corvette").handling_trait == "smooth"


class TestFrigatePhysical:
    """Spec 1.1.3: Frigate physical profile."""
    def test_hull(self):         assert load_ship_class("frigate").max_hull == 120
    def test_max_speed(self):    assert load_ship_class("frigate").max_speed == 160
    def test_acceleration(self): assert load_ship_class("frigate").acceleration == 30
    def test_turn_rate(self):    assert load_ship_class("frigate").turn_rate == 90
    def test_target_profile(self): assert load_ship_class("frigate").target_profile == 0.75
    def test_armour(self):       assert load_ship_class("frigate").armour == 10
    def test_decks(self):        assert load_ship_class("frigate").decks == 5
    def test_handling(self):     assert load_ship_class("frigate").handling_trait == "clean"


class TestCruiserPhysical:
    """Spec 1.1.4: Cruiser physical profile."""
    def test_hull(self):         assert load_ship_class("cruiser").max_hull == 180
    def test_max_speed(self):    assert load_ship_class("cruiser").max_speed == 120
    def test_acceleration(self): assert load_ship_class("cruiser").acceleration == 20
    def test_turn_rate(self):    assert load_ship_class("cruiser").turn_rate == 60
    def test_target_profile(self): assert load_ship_class("cruiser").target_profile == 0.85
    def test_armour(self):       assert load_ship_class("cruiser").armour == 20
    def test_decks(self):        assert load_ship_class("cruiser").decks == 6
    def test_handling(self):     assert load_ship_class("cruiser").handling_trait == "steady"


class TestBattleshipPhysical:
    """Spec 1.1.5: Battleship physical profile."""
    def test_hull(self):         assert load_ship_class("battleship").max_hull == 300
    def test_max_speed(self):    assert load_ship_class("battleship").max_speed == 80
    def test_acceleration(self): assert load_ship_class("battleship").acceleration == 10
    def test_turn_rate(self):    assert load_ship_class("battleship").turn_rate == 30
    def test_target_profile(self): assert load_ship_class("battleship").target_profile == 1.0
    def test_armour(self):       assert load_ship_class("battleship").armour == 40
    def test_decks(self):        assert load_ship_class("battleship").decks == 8
    def test_handling(self):     assert load_ship_class("battleship").handling_trait == "ponderous"


class TestCarrierPhysical:
    """Spec 1.1.6: Carrier physical profile."""
    def test_hull(self):         assert load_ship_class("carrier").max_hull == 200
    def test_max_speed(self):    assert load_ship_class("carrier").max_speed == 100
    def test_acceleration(self): assert load_ship_class("carrier").acceleration == 15
    def test_turn_rate(self):    assert load_ship_class("carrier").turn_rate == 45
    def test_target_profile(self): assert load_ship_class("carrier").target_profile == 0.95
    def test_armour(self):       assert load_ship_class("carrier").armour == 15
    def test_decks(self):        assert load_ship_class("carrier").decks == 7
    def test_handling(self):     assert load_ship_class("carrier").handling_trait == "heavy"


class TestMedicalShipPhysical:
    """Spec 1.1.7: Medical ship physical profile."""
    def test_hull(self):         assert load_ship_class("medical_ship").max_hull == 100
    def test_max_speed(self):    assert load_ship_class("medical_ship").max_speed == 140
    def test_acceleration(self): assert load_ship_class("medical_ship").acceleration == 25
    def test_turn_rate(self):    assert load_ship_class("medical_ship").turn_rate == 75
    def test_target_profile(self): assert load_ship_class("medical_ship").target_profile == 0.7
    def test_armour(self):       assert load_ship_class("medical_ship").armour == 5
    def test_decks(self):        assert load_ship_class("medical_ship").decks == 5
    def test_handling(self):     assert load_ship_class("medical_ship").handling_trait == "gentle"


# ---------------------------------------------------------------------------
# v0.07: Cross-class stat spread validation (spec says 2-3x variation)
# ---------------------------------------------------------------------------


class TestStatSpreads:
    """Verify that stat spreads create dramatic differences between classes."""

    def _stat_range(self, attr: str) -> tuple[float, float]:
        vals = [getattr(load_ship_class(cid), attr) for cid in ALL_IDS]
        return min(vals), max(vals)

    def test_hull_spread_at_least_3x(self):
        lo, hi = self._stat_range("max_hull")
        assert hi / lo >= 3.0, f"Hull spread {hi}/{lo} = {hi/lo:.1f}x (need ≥3x)"

    def test_max_speed_spread_at_least_2x(self):
        lo, hi = self._stat_range("max_speed")
        assert hi / lo >= 2.0, f"Speed spread {hi}/{lo} = {hi/lo:.1f}x (need ≥2x)"

    def test_acceleration_spread_at_least_2x(self):
        lo, hi = self._stat_range("acceleration")
        assert hi / lo >= 2.0

    def test_turn_rate_spread_at_least_2x(self):
        lo, hi = self._stat_range("turn_rate")
        assert hi / lo >= 2.0

    def test_target_profile_spread_at_least_2x(self):
        lo, hi = self._stat_range("target_profile")
        assert hi / lo >= 2.0


# ---------------------------------------------------------------------------
# v0.07: Handling trait validity
# ---------------------------------------------------------------------------


class TestHandlingTraits:
    @pytest.mark.parametrize("ship_id", ALL_IDS)
    def test_handling_trait_is_valid(self, ship_id):
        sc = load_ship_class(ship_id)
        assert sc.handling_trait in VALID_HANDLING_TRAITS

    def test_all_traits_used(self):
        """Each valid handling trait is used by at least one ship class."""
        used = {load_ship_class(cid).handling_trait for cid in ALL_IDS}
        assert used == VALID_HANDLING_TRAITS


# ---------------------------------------------------------------------------
# v0.07: Deck counts
# ---------------------------------------------------------------------------


class TestDeckCounts:
    @pytest.mark.parametrize("ship_id", ALL_IDS)
    def test_decks_positive(self, ship_id):
        assert load_ship_class(ship_id).decks >= 3

    def test_scout_fewest_decks(self):
        scout = load_ship_class("scout").decks
        for cid in ALL_IDS:
            if cid != "scout":
                assert load_ship_class(cid).decks >= scout

    def test_battleship_most_decks(self):
        bs = load_ship_class("battleship").decks
        for cid in ALL_IDS:
            assert load_ship_class(cid).decks <= bs


# ---------------------------------------------------------------------------
# v0.07: Armour values
# ---------------------------------------------------------------------------


class TestArmourValues:
    @pytest.mark.parametrize("ship_id", ALL_IDS)
    def test_armour_non_negative(self, ship_id):
        assert load_ship_class(ship_id).armour >= 0

    def test_scout_has_no_armour(self):
        assert load_ship_class("scout").armour == 0

    def test_battleship_has_most_armour(self):
        bs = load_ship_class("battleship").armour
        for cid in ALL_IDS:
            assert load_ship_class(cid).armour <= bs

    def test_combat_armour_progression(self):
        """Armour increases with ship size for combat classes."""
        combat = ["scout", "corvette", "frigate", "cruiser", "battleship"]
        armours = [load_ship_class(cid).armour for cid in combat]
        assert armours == sorted(armours)


# ---------------------------------------------------------------------------
# v0.07: Game loop wires class-specific physical stats
# ---------------------------------------------------------------------------


import asyncio
from server import game_loop
from server.models.world import World


class _MockManager:
    def __init__(self) -> None:
        self.broadcasts: list = []

    async def broadcast(self, msg: object) -> None:
        self.broadcasts.append(msg)

    async def broadcast_to_roles(self, roles: list[str], msg: object) -> None:
        self.broadcasts.append(msg)

    def get_by_role(self, role: str) -> list:
        return []


def _fresh():
    manager = _MockManager()
    world = World()
    queue: asyncio.Queue = asyncio.Queue()  # type: ignore[type-arg]
    game_loop.init(world, manager, queue)
    return manager, world, queue


@pytest.fixture(autouse=True)
async def _stop_loop_after_test():
    yield
    await game_loop.stop()


class TestGameLoopWiresPhysicalStats:
    async def test_scout_max_speed_base(self):
        _, world, _ = _fresh()
        await game_loop.start("sandbox", ship_class="scout")
        assert world.ship.max_speed_base == 250.0

    async def test_scout_acceleration_base(self):
        _, world, _ = _fresh()
        await game_loop.start("sandbox", ship_class="scout")
        assert world.ship.acceleration_base == 50.0

    async def test_scout_turn_rate_base(self):
        _, world, _ = _fresh()
        await game_loop.start("sandbox", ship_class="scout")
        assert world.ship.turn_rate_base == 180.0

    async def test_scout_target_profile(self):
        _, world, _ = _fresh()
        await game_loop.start("sandbox", ship_class="scout")
        assert world.ship.target_profile == 0.5

    async def test_scout_armour(self):
        _, world, _ = _fresh()
        await game_loop.start("sandbox", ship_class="scout")
        assert world.ship.armour == 0.0
        assert world.ship.armour_max == 0.0

    async def test_battleship_armour(self):
        _, world, _ = _fresh()
        await game_loop.start("sandbox", ship_class="battleship")
        assert world.ship.armour == 40.0
        assert world.ship.armour_max == 40.0

    async def test_battleship_max_speed_base(self):
        _, world, _ = _fresh()
        await game_loop.start("sandbox", ship_class="battleship")
        assert world.ship.max_speed_base == 80.0
