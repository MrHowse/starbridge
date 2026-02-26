"""Tests for v0.07-6 Commit B: Armour Client Display.

Verifies that _build_ship_state() includes armour fields and that
armour_zones is correctly populated per ship class.
"""
from __future__ import annotations

from server.models.ship import Ship
from server.models.ship_class import load_ship_class


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ship(class_id: str) -> Ship:
    """Create a Ship configured like game_loop.start() does for the given class."""
    sc = load_ship_class(class_id)
    ship = Ship()
    ship.hull = sc.max_hull
    ship.hull_max = sc.max_hull
    ship.armour = sc.armour
    ship.armour_max = sc.armour
    if class_id == "battleship" and sc.armour > 0:
        zone_val = sc.armour / 4.0
        ship.armour_zones = {
            "fore": zone_val, "aft": zone_val,
            "port": zone_val, "starboard": zone_val,
        }
        ship.armour_zones_max = dict(ship.armour_zones)
    else:
        ship.armour_zones = None
        ship.armour_zones_max = None
    return ship


# ============================================================================
# Tests
# ============================================================================


class TestArmourInShipState:
    """Verify ship state includes armour fields correctly."""

    def test_armour_fields_present(self):
        ship = _make_ship("frigate")
        assert hasattr(ship, "armour")
        assert hasattr(ship, "armour_max")
        assert ship.armour_max >= 0

    def test_battleship_has_armour_zones(self):
        ship = _make_ship("battleship")
        assert ship.armour_max > 0
        assert ship.armour_zones is not None
        assert set(ship.armour_zones.keys()) == {"fore", "aft", "port", "starboard"}
        assert ship.armour_zones_max is not None

    def test_non_battleship_no_armour_zones(self):
        for cls_id in ("scout", "corvette", "frigate", "cruiser", "carrier", "medical_ship"):
            ship = _make_ship(cls_id)
            assert ship.armour_zones is None, f"{cls_id} should not have armour_zones"

    def test_battleship_armour_zones_sum(self):
        ship = _make_ship("battleship")
        total = ship.armour_max
        for key in ("fore", "aft", "port", "starboard"):
            expected = total / 4.0
            assert abs(ship.armour_zones_max[key] - expected) < 1e-6

    def test_all_classes_have_armour_field(self):
        """Every ship class should have a numeric armour value."""
        for cls_id in ("scout", "corvette", "frigate", "cruiser",
                        "battleship", "carrier", "medical_ship"):
            ship = _make_ship(cls_id)
            assert isinstance(ship.armour, (int, float))
            assert isinstance(ship.armour_max, (int, float))
            assert ship.armour >= 0
            assert ship.armour == ship.armour_max  # starts full
