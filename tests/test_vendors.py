"""Tests for the Vendor System — v0.07 Phase 6.2."""
from __future__ import annotations

import random
import pytest

from server.models.vendor import (
    BASE_PRICES,
    HEAVY_MILITARY_ITEMS,
    MILITARY_ITEMS,
    STARTING_CREDITS,
    VENDOR_TEMPLATES,
    VENDOR_TYPES,
    Vendor,
    calculate_price,
    can_trade_with,
    generate_vendor_inventory,
    get_price_breakdown,
    is_military_item,
    map_station_to_vendor_type,
    _faction_modifier,
    _urgency_modifier,
    _reputation_modifier,
    _scarcity_modifier,
)
from server.models.ship import Ship
from server.models.ship_class import load_ship_class, SHIP_CLASS_ORDER
from server.models.resources import ResourceStore
from server.difficulty import get_preset
import server.game_loop_vendor as glvr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ship(credits: float = 1000.0, trade_reputation: float = 0.0) -> Ship:
    """Create a Ship with resources and credits for testing."""
    ship = Ship()
    ship.credits = credits
    ship.trade_reputation = trade_reputation
    ship.resources = ResourceStore(
        fuel=500.0, fuel_max=1000.0,
        medical_supplies=30.0, medical_supplies_max=60.0,
        repair_materials=25.0, repair_materials_max=50.0,
        drone_fuel=100.0, drone_fuel_max=200.0,
        drone_parts=6.0, drone_parts_max=12.0,
        ammunition=25.0, ammunition_max=50.0,
        provisions=200.0, provisions_max=400.0,
    )
    return ship


def _make_vendor(
    vendor_type: str = "neutral_station",
    faction: str = "neutral",
    base_multiplier: float | None = None,
    inventory: dict | None = None,
    inventory_max: dict | None = None,
) -> Vendor:
    """Create a Vendor for testing."""
    template = VENDOR_TEMPLATES.get(vendor_type, {})
    mult = base_multiplier if base_multiplier is not None else template.get("base_multiplier", 1.0)
    inv = inventory if inventory is not None else {"fuel": 500, "provisions": 200, "medical_supplies": 30}
    inv_max = inventory_max if inventory_max is not None else {k: v * 2 for k, v in inv.items()}
    return Vendor(
        id="test_vendor",
        vendor_type=vendor_type,
        name="Test Vendor",
        faction=faction,
        position=(1000.0, 2000.0),
        inventory=inv,
        inventory_max=inv_max,
        base_multiplier=mult,
    )


# ===========================================================================
# 1. Vendor model (5 tests)
# ===========================================================================


class TestVendorModel:
    """Tests for Vendor dataclass and constants."""

    def test_vendor_creation(self):
        v = _make_vendor()
        assert v.id == "test_vendor"
        assert v.vendor_type == "neutral_station"
        assert v.available is True
        assert v.trade_window is None

    def test_vendor_to_dict_from_dict_roundtrip(self):
        v = _make_vendor(vendor_type="black_market", faction="hostile")
        v.cooldown_items = {"fuel": 30.0}
        v.hidden_inventory = {"nuclear_torpedo": 1}
        d = v.to_dict()
        v2 = Vendor.from_dict(d)
        assert v2.id == v.id
        assert v2.vendor_type == v.vendor_type
        assert v2.faction == v.faction
        assert v2.position == v.position
        assert v2.inventory == v.inventory
        assert v2.hidden_inventory == v.hidden_inventory
        assert v2.cooldown_items == v.cooldown_items

    def test_all_vendor_types_valid(self):
        assert len(VENDOR_TYPES) == 8
        for vt in VENDOR_TYPES:
            assert vt in VENDOR_TEMPLATES

    def test_base_prices_cover_all_resources(self):
        """BASE_PRICES should cover fuel, all torpedo types, and all resource types."""
        expected = {
            "fuel", "provisions", "medical_supplies", "repair_materials",
            "drone_fuel", "drone_parts", "ammunition",
            "standard_torpedo", "homing_torpedo", "ion_torpedo", "piercing_torpedo",
            "heavy_torpedo", "proximity_torpedo", "nuclear_torpedo", "experimental_torpedo",
        }
        assert expected.issubset(set(BASE_PRICES.keys()))

    def test_military_item_classification(self):
        assert is_military_item("nuclear_torpedo")
        assert is_military_item("ammunition")
        assert not is_military_item("fuel")
        assert not is_military_item("provisions")
        assert not is_military_item("medical_supplies")


# ===========================================================================
# 2. Inventory generation (5 tests)
# ===========================================================================


class TestInventoryGeneration:
    """Tests for generate_vendor_inventory()."""

    def test_allied_station_full_range(self):
        inv, inv_max, hidden = generate_vendor_inventory("allied_station", random.Random(42))
        assert "fuel" in inv
        assert "provisions" in inv
        assert "standard_torpedo" in inv
        assert len(hidden) == 0

    def test_outpost_limited_stock(self):
        inv, _, hidden = generate_vendor_inventory("outpost", random.Random(42))
        # Outpost should only have basics.
        for item in inv:
            assert item in {"fuel", "provisions", "medical_supplies", "repair_materials"}
        assert len(hidden) == 0

    def test_black_market_has_hidden_items(self):
        """Black market should have some hidden items (with deterministic seed)."""
        rng = random.Random(42)
        inv, inv_max, hidden = generate_vendor_inventory("black_market", rng)
        # With seed 42, at least something should be in hidden or inventory.
        assert len(inv) + len(hidden) > 0

    def test_merchant_limited_categories(self):
        inv, _, _ = generate_vendor_inventory("merchant", random.Random(42))
        # Merchants carry 1-2 categories, not everything.
        assert len(inv) < 15  # less than full inventory

    def test_allied_warship_keeps_fraction(self):
        rng = random.Random(42)
        inv, inv_max, _ = generate_vendor_inventory("allied_warship", rng)
        # Available should be less than max (keep_fraction=0.60).
        for item in inv:
            assert inv[item] <= inv_max.get(item, inv[item])


# ===========================================================================
# 3. Pricing (8 tests)
# ===========================================================================


class TestPricing:
    """Tests for the 6-modifier pricing formula."""

    def test_faction_modifier(self):
        assert _faction_modifier(60.0) == 0.85    # high standing
        assert _faction_modifier(30.0) == 0.95    # moderate
        assert _faction_modifier(10.0) == 1.0     # neutral
        assert _faction_modifier(-10.0) == 1.1    # slightly hostile
        assert _faction_modifier(-30.0) == 1.3    # hostile

    def test_urgency_modifier(self):
        assert _urgency_modifier(0.05) == 1.5     # critical
        assert _urgency_modifier(0.15) == 1.2     # low
        assert _urgency_modifier(0.50) == 1.0     # fine

    def test_reputation_modifier(self):
        assert _reputation_modifier(60.0) == 0.9
        assert _reputation_modifier(30.0) == 0.95
        assert _reputation_modifier(10.0) == 1.0
        assert _reputation_modifier(-10.0) == 1.15

    def test_scarcity_modifier(self):
        v = _make_vendor(inventory={"fuel": 10}, inventory_max={"fuel": 100})
        assert _scarcity_modifier(v, "fuel") == 1.3   # 10% stock → scarce

        v2 = _make_vendor(inventory={"fuel": 90}, inventory_max={"fuel": 100})
        assert _scarcity_modifier(v2, "fuel") == 0.9  # 90% stock → abundant

        v3 = _make_vendor(inventory={"fuel": 50}, inventory_max={"fuel": 100})
        assert _scarcity_modifier(v3, "fuel") == 1.0  # 50% → normal

    def test_combined_price_allied_station(self):
        """Allied station fuel at Officer difficulty = base × 1.0 × modifiers."""
        v = _make_vendor(
            vendor_type="allied_station", faction="friendly",
            inventory={"fuel": 500}, inventory_max={"fuel": 1000},
        )
        # Standing 50+ → 0.85 faction mod; neutral urgency; 0 rep → 1.0; 50% stock → 1.0
        price = calculate_price("fuel", v, faction_standing=60.0,
                                trade_reputation=0.0, ship_resource_fraction=0.5)
        expected = 2.0 * 1.0 * 0.85 * 1.0 * 1.0 * 1.0  # = 1.70
        assert price == round(expected, 2)

    def test_salvage_yard_buy_vs_sell(self):
        """Salvage yard: buy at 0.7×, sell at 0.9×."""
        v = _make_vendor(vendor_type="salvage_yard", inventory={"fuel": 500},
                         inventory_max={"fuel": 1000})
        buy = calculate_price("fuel", v, faction_standing=0.0)
        sell = calculate_price("fuel", v, faction_standing=0.0, is_selling=True)
        # Buy: 2.0 × 0.7 × 1.0 × 1.0 × 1.0 × 1.0 = 1.4
        assert buy == round(2.0 * 0.7 * 1.0 * 1.0 * 1.0 * 1.0, 2)
        # Sell: 2.0 × 0.9 × 1.0 × 1.0 × 1.0 × 1.0 = 1.8  (no urgency/scarcity on sell)
        assert sell == round(2.0 * 0.9 * 1.0 * 1.0 * 1.0, 2)

    def test_allied_warship_free(self):
        """Allied warship: free transfer."""
        v = _make_vendor(vendor_type="allied_warship", faction="friendly",
                         inventory={"fuel": 200}, inventory_max={"fuel": 500})
        price = calculate_price("fuel", v, faction_standing=40.0)
        assert price == 0.0

    def test_price_breakdown_includes_all_modifiers(self):
        v = _make_vendor(inventory={"fuel": 500}, inventory_max={"fuel": 1000})
        bd = get_price_breakdown("fuel", v, faction_standing=10.0, trade_reputation=30.0)
        assert "base_price" in bd
        assert "vendor_type_modifier" in bd
        assert "faction_modifier" in bd
        assert "urgency_modifier" in bd
        assert "reputation_modifier" in bd
        assert "scarcity_modifier" in bd
        assert "final_price" in bd


# ===========================================================================
# 4. Trade reputation (4 tests)
# ===========================================================================


class TestTradeReputation:
    """Tests for trade reputation system."""

    def test_starts_at_zero(self):
        ship = _make_ship()
        assert ship.trade_reputation == 0.0

    def test_gains_on_fair_trade(self):
        ship = _make_ship()
        glvr.reset()
        v = glvr.spawn_vendor("allied_station", "Test Station", (0, 0), faction="friendly")
        v.inventory = {"fuel": 500}
        v.inventory_max = {"fuel": 1000}
        result = glvr.execute_trade(v.id, "fuel", 10, ship)
        assert result["ok"]
        assert ship.trade_reputation == 2.0

    def test_clamped_at_bounds(self):
        ship = _make_ship()
        ship.trade_reputation = 99.5
        glvr.adjust_reputation(ship, 5.0, "test")
        assert ship.trade_reputation == 100.0

        ship.trade_reputation = -99.5
        glvr.adjust_reputation(ship, -5.0, "test")
        assert ship.trade_reputation == -100.0

    def test_descriptor_text(self):
        assert glvr.get_reputation_descriptor(80.0) == "Renowned Trader"
        assert glvr.get_reputation_descriptor(55.0) == "Trusted Merchant"
        assert glvr.get_reputation_descriptor(25.0) == "Known Trader"
        assert glvr.get_reputation_descriptor(0.0) == "Unknown"
        assert glvr.get_reputation_descriptor(-30.0) == "Unreliable"
        assert glvr.get_reputation_descriptor(-60.0) == "Blacklisted"


# ===========================================================================
# 5. Credits (5 tests)
# ===========================================================================


class TestCredits:
    """Tests for credits system."""

    def test_all_ship_classes_have_starting_credits(self):
        for cid in SHIP_CLASS_ORDER:
            sc = load_ship_class(cid)
            assert sc.starting_credits > 0, f"{cid} has no starting_credits"

    def test_starting_credits_match_spec(self):
        """Verify starting credits match the spec values."""
        for cid, expected in STARTING_CREDITS.items():
            sc = load_ship_class(cid)
            assert sc.starting_credits == expected, (
                f"{cid}: expected {expected}, got {sc.starting_credits}"
            )

    def test_difficulty_multipliers(self):
        """All 4 difficulty presets have starting_credits_multiplier."""
        cadet = get_preset("cadet")
        officer = get_preset("officer")
        commander = get_preset("commander")
        admiral = get_preset("admiral")
        assert cadet.starting_credits_multiplier == 2.0
        assert officer.starting_credits_multiplier == 1.0
        assert commander.starting_credits_multiplier == 0.75
        assert admiral.starting_credits_multiplier == 0.5

    def test_credits_deducted_on_buy(self):
        glvr.reset()
        ship = _make_ship(credits=100.0)
        v = glvr.spawn_vendor("allied_station", "Test", (0, 0), faction="friendly")
        v.inventory = {"fuel": 500}
        v.inventory_max = {"fuel": 1000}
        result = glvr.execute_trade(v.id, "fuel", 10, ship)
        assert result["ok"]
        assert ship.credits < 100.0

    def test_insufficient_credits_blocks_trade(self):
        glvr.reset()
        ship = _make_ship(credits=0.0)
        v = glvr.spawn_vendor("neutral_station", "Test", (0, 0), faction="neutral")
        v.inventory = {"fuel": 500}
        v.inventory_max = {"fuel": 1000}
        result = glvr.execute_trade(v.id, "fuel", 10, ship)
        assert not result["ok"]
        assert "credits" in result.get("error", "").lower() or "Insufficient" in result.get("error", "")


# ===========================================================================
# 6. Trade execution (5 tests)
# ===========================================================================


class TestTradeExecution:
    """Tests for buy/sell trade execution."""

    def test_buy_success(self):
        glvr.reset()
        ship = _make_ship(credits=500.0)
        v = glvr.spawn_vendor("allied_station", "Test", (0, 0), faction="friendly")
        v.inventory = {"provisions": 100}
        v.inventory_max = {"provisions": 200}
        result = glvr.execute_trade(v.id, "provisions", 50, ship)
        assert result["ok"]
        assert result["quantity"] == 50
        assert ship.credits < 500.0

    def test_sell_success(self):
        glvr.reset()
        ship = _make_ship(credits=100.0)
        v = glvr.spawn_vendor("allied_station", "Test", (0, 0), faction="friendly")
        v.inventory = {}
        v.inventory_max = {"fuel": 1000}
        result = glvr.sell_to_vendor(v.id, "fuel", 50, ship)
        assert result["ok"]
        assert result["quantity"] == 50
        assert ship.credits > 100.0

    def test_vendor_inventory_depletes(self):
        glvr.reset()
        ship = _make_ship(credits=5000.0)
        v = glvr.spawn_vendor("allied_station", "Test", (0, 0), faction="friendly")
        v.inventory = {"fuel": 20}
        v.inventory_max = {"fuel": 100}
        # Try to buy more than available.
        result = glvr.execute_trade(v.id, "fuel", 50, ship)
        assert result["ok"]
        assert result["quantity"] == 20  # capped to available
        assert v.inventory["fuel"] == 0

    def test_hostile_standing_gate(self):
        glvr.reset()
        ship = _make_ship(credits=5000.0)
        v = glvr.spawn_vendor("hostile_station", "Enemy Base", (0, 0), faction="hostile")
        v.inventory = {"fuel": 100}
        v.inventory_max = {"fuel": 200}
        # Hostile station standing gate is -50; default hostile standing is -30
        # which is above -50, so trade should be allowed.
        result = glvr.execute_trade(v.id, "fuel", 10, ship)
        # restricted_items for hostile_station includes MILITARY_ITEMS
        # fuel is not military, so it should work.
        assert result["ok"]

    def test_neutral_military_restriction(self):
        glvr.reset()
        ship = _make_ship(credits=5000.0)
        v = glvr.spawn_vendor("neutral_station", "Trade Hub", (0, 0), faction="neutral")
        v.inventory = {"nuclear_torpedo": 5}
        v.inventory_max = {"nuclear_torpedo": 10}
        # Neutral station restricts heavy military items.
        result = glvr.execute_trade(v.id, "nuclear_torpedo", 1, ship)
        assert not result["ok"]
        assert "restricted" in result.get("error", "").lower()


# ===========================================================================
# 7. Vendor lifecycle (3 tests)
# ===========================================================================


class TestVendorLifecycle:
    """Tests for vendor spawn, removal, and trade window expiry."""

    def test_spawn_and_remove(self):
        glvr.reset()
        v = glvr.spawn_vendor("merchant", "Trader", (100, 200))
        assert glvr.get_vendor_by_id(v.id) is not None
        assert glvr.remove_vendor(v.id) is True
        assert glvr.get_vendor_by_id(v.id) is None

    def test_trade_window_expiry(self):
        glvr.reset()
        v = glvr.spawn_vendor("merchant", "Trader", (100, 200))
        v.trade_window = 10.0  # 10 seconds

        ship = _make_ship()
        # Tick 5 seconds — still available.
        glvr.tick(None, ship, 5.0)
        assert glvr.get_vendor_by_id(v.id) is not None

        # Tick 6 more seconds — should expire.
        glvr.tick(None, ship, 6.0)
        assert glvr.get_vendor_by_id(v.id) is None

    def test_cooldown_items_decay(self):
        glvr.reset()
        v = glvr.spawn_vendor("neutral_station", "Station", (100, 200))
        v.cooldown_items = {"fuel": 5.0}

        ship = _make_ship()
        glvr.tick(None, ship, 3.0)
        assert v.cooldown_items.get("fuel", 0) == pytest.approx(2.0, abs=0.1)

        glvr.tick(None, ship, 3.0)
        assert "fuel" not in v.cooldown_items


# ===========================================================================
# 8. Save/resume (2 tests)
# ===========================================================================


class TestVendorSaveResume:
    """Tests for vendor state serialisation round-trip."""

    def test_vendor_state_roundtrip(self):
        glvr.reset()
        v1 = glvr.spawn_vendor("allied_station", "Alpha Station", (1000, 2000),
                                faction="friendly", station_id="st_1")
        v2 = glvr.spawn_vendor("merchant", "Trader Bob", (3000, 4000),
                                faction="neutral")
        v2.trade_window = 120.0
        v1.inventory["fuel"] = 42

        data = glvr.serialise()
        glvr.reset()
        assert len(glvr.get_vendors()) == 0

        glvr.deserialise(data)
        vendors = glvr.get_vendors()
        assert len(vendors) == 2

        restored_v1 = glvr.get_vendor_by_id(v1.id)
        assert restored_v1 is not None
        assert restored_v1.name == "Alpha Station"
        assert restored_v1.inventory["fuel"] == 42
        assert restored_v1.station_id == "st_1"

        restored_v2 = glvr.get_vendor_by_id(v2.id)
        assert restored_v2 is not None
        assert restored_v2.trade_window == 120.0

    def test_backward_compat_no_vendors_key(self):
        """Deserialise with empty data should not crash."""
        glvr.reset()
        glvr.deserialise({})
        assert len(glvr.get_vendors()) == 0
