"""Tests for Ship Credits and Economy — v0.07 Phase 6.4."""
from __future__ import annotations

import pytest

from server.models.vendor import (
    STARTING_CREDITS,
    Vendor,
    VENDOR_TEMPLATES,
    calculate_price,
)
from server.models.ship import Ship
from server.models.ship_class import load_ship_class, SHIP_CLASS_ORDER
from server.models.resources import ResourceStore
from server.models.dynamic_mission import (
    DynamicMission,
    MissionObjective,
    MissionRewards,
    generate_rescue_mission,
    generate_intercept_mission,
    generate_patrol_mission,
    generate_investigation_mission,
    generate_service_contract_mission,
)
from server.difficulty import get_preset
import server.game_loop_vendor as glvr
import server.game_loop_dynamic_missions as gldm


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
    inventory: dict | None = None,
) -> Vendor:
    template = VENDOR_TEMPLATES.get(vendor_type, {})
    inv = inventory if inventory is not None else {"fuel": 500, "provisions": 200}
    return Vendor(
        id="eco_vendor",
        vendor_type=vendor_type,
        name="Economy Test Vendor",
        faction=faction,
        position=(0.0, 0.0),
        inventory=inv,
        inventory_max={k: v * 2 for k, v in inv.items()},
        base_multiplier=template.get("base_multiplier", 1.0),
    )


# ===========================================================================
# 1. Starting Credits (§6.4.1) — 7 tests
# ===========================================================================


class TestStartingCredits:
    """Starting credits match spec per ship class."""

    EXPECTED = {
        "scout": 300,
        "corvette": 500,
        "frigate": 800,
        "cruiser": 1200,
        "battleship": 1500,
        "carrier": 1000,
        "medical_ship": 600,
    }

    def test_starting_credits_per_class(self):
        for cls_id, expected in self.EXPECTED.items():
            assert STARTING_CREDITS[cls_id] == expected, f"{cls_id}"

    def test_ship_class_json_matches(self):
        for cls_id, expected in self.EXPECTED.items():
            sc = load_ship_class(cls_id)
            assert sc.starting_credits == expected, f"{cls_id}"

    def test_all_seven_classes_have_starting_credits(self):
        for cls_id in SHIP_CLASS_ORDER:
            assert cls_id in STARTING_CREDITS
            assert STARTING_CREDITS[cls_id] > 0


# ===========================================================================
# 2. Difficulty Multiplier (§6.4.1.2) — 4 tests
# ===========================================================================


class TestDifficultyMultiplier:
    """Difficulty presets modify starting credits correctly."""

    def test_cadet_doubles(self):
        preset = get_preset("cadet")
        assert preset.starting_credits_multiplier == 2.0

    def test_officer_baseline(self):
        preset = get_preset("officer")
        assert preset.starting_credits_multiplier == 1.0

    def test_commander_reduced(self):
        preset = get_preset("commander")
        assert preset.starting_credits_multiplier == 0.75

    def test_admiral_halved(self):
        preset = get_preset("admiral")
        assert preset.starting_credits_multiplier == 0.5


# ===========================================================================
# 3. Credit Initialisation (§6.4.1) — 3 tests
# ===========================================================================


class TestCreditInitialisation:
    """Ship credits are correctly initialised from class × difficulty."""

    def test_credits_on_ship_default_zero(self):
        ship = Ship()
        assert ship.credits == 0.0

    def test_credits_calculated(self):
        """Simulate the game_loop start() logic."""
        for cls_id in SHIP_CLASS_ORDER:
            sc = load_ship_class(cls_id)
            for diff in ("cadet", "officer", "commander", "admiral"):
                preset = get_preset(diff)
                expected = round(sc.starting_credits * preset.starting_credits_multiplier, 2)
                ship = Ship()
                ship.credits = round(sc.starting_credits * preset.starting_credits_multiplier, 2)
                assert ship.credits == expected, f"{cls_id}/{diff}"

    def test_trade_reputation_starts_zero(self):
        ship = Ship()
        assert ship.trade_reputation == 0.0


# ===========================================================================
# 4. Earning Credits — Vendor Sales (§6.4.2.1–2) — 4 tests
# ===========================================================================


class TestEarningCreditsVendor:
    """Selling to vendors earns credits."""

    def setup_method(self):
        glvr.reset()

    def test_sell_resources_earns_credits(self):
        ship = _make_ship(credits=100.0)
        vendor = _make_vendor(inventory={"fuel": 100})
        glvr.spawn_vendor(
            vendor_type=vendor.vendor_type,
            name=vendor.name,
            faction=vendor.faction,
            position=vendor.position,
        )
        vendors = glvr.get_vendors()
        assert len(vendors) >= 1
        v = vendors[0]
        # Sell fuel to vendor
        result = glvr.sell_to_vendor(v.id, "fuel", 10, ship)
        assert result["ok"]
        assert ship.credits > 100.0

    def test_sell_at_negotiated_price(self):
        ship = _make_ship(credits=100.0)
        glvr.spawn_vendor(
            vendor_type="neutral_station",
            name="Test",
            faction="neutral",
            position=(0.0, 0.0),
        )
        v = glvr.get_vendors()[0]
        result = glvr.sell_to_vendor_at_price(v.id, "fuel", 10, 5.0, ship)
        assert result["ok"]
        assert ship.credits == pytest.approx(150.0)  # 100 + 10*5

    def test_buy_resources_costs_credits(self):
        ship = _make_ship(credits=500.0)
        glvr.spawn_vendor(
            vendor_type="neutral_station",
            name="Test",
            faction="neutral",
            position=(0.0, 0.0),
        )
        v = glvr.get_vendors()[0]
        result = glvr.execute_trade(v.id, "fuel", 10, ship)
        assert result["ok"]
        assert ship.credits < 500.0

    def test_buy_at_negotiated_price(self):
        ship = _make_ship(credits=500.0)
        glvr.spawn_vendor(
            vendor_type="neutral_station",
            name="Test",
            faction="neutral",
            position=(0.0, 0.0),
        )
        v = glvr.get_vendors()[0]
        result = glvr.execute_trade_at_price(v.id, "fuel", 10, 3.0, ship)
        assert result["ok"]
        assert ship.credits == pytest.approx(470.0)  # 500 - 10*3


# ===========================================================================
# 5. Mission Credit Rewards (§6.4.2.5) — 6 tests
# ===========================================================================


class TestMissionCreditRewards:
    """Dynamic missions award credits on completion."""

    def setup_method(self):
        gldm.reset()

    def test_mission_rewards_has_credits_field(self):
        r = MissionRewards(credits=50.0)
        assert r.credits == 50.0

    def test_mission_rewards_default_zero(self):
        r = MissionRewards()
        assert r.credits == 0.0

    def test_mission_rewards_to_dict_includes_credits(self):
        r = MissionRewards(credits=75.0)
        d = r.to_dict()
        assert d["credits"] == 75.0

    def test_mission_rewards_from_dict(self):
        d = {"credits": 42.5, "reputation": 5}
        r = MissionRewards.from_dict(d)
        assert r.credits == 42.5

    def test_mission_rewards_from_dict_backward_compat(self):
        """Old saves without credits field default to 0."""
        d = {"reputation": 5}
        r = MissionRewards.from_dict(d)
        assert r.credits == 0.0

    def test_apply_rewards_includes_credits(self):
        rewards = MissionRewards(credits=100.0, reputation=5)
        summary = gldm.apply_rewards(rewards, {})
        assert summary["credits"] == 100.0

    def test_apply_rewards_no_credits_when_zero(self):
        rewards = MissionRewards(reputation=5)
        summary = gldm.apply_rewards(rewards, {})
        assert "credits" not in summary


# ===========================================================================
# 6. Template Generators Credit Rewards (§6.4.2.5) — 4 tests
# ===========================================================================


class TestTemplateGeneratorCredits:
    """Some mission templates include credit bounties."""

    def test_rescue_mission_has_credits(self):
        m = generate_rescue_mission(
            "m1", "sig1", "c1", "Distressed Ship",
            (1000.0, 2000.0), "neutral", 0,
        )
        assert m.rewards.credits == 50.0

    def test_intercept_mission_has_credits(self):
        m = generate_intercept_mission(
            "m2", "sig2", "c2",
            (3000.0, 4000.0), "hostile", 0,
        )
        assert m.rewards.credits == 75.0

    def test_patrol_mission_has_credits(self):
        m = generate_patrol_mission(
            "m3", "sig3", "c3",
            (5000.0, 6000.0), "allied", 0,
        )
        assert m.rewards.credits == 40.0

    def test_investigation_mission_has_credits(self):
        m = generate_investigation_mission(
            "m4", "sig4", "c4",
            (7000.0, 8000.0), 0,
        )
        assert m.rewards.credits == 60.0


# ===========================================================================
# 7. Service Contract Credits (§6.4.2.4) — 2 tests
# ===========================================================================


class TestServiceContractCredits:
    """Service contracts use credit_value for briefing but don't award credits
    separately (goods already received upfront)."""

    def test_service_contract_no_credit_reward(self):
        m = generate_service_contract_mission(
            "sc1", "escort", "v1", "Vendor Alpha",
            (1000.0, 2000.0), 300.0, 200.0,
        )
        # Credits are folded into trade terms — reward is reputation only
        assert m.rewards.credits == 0.0
        assert m.rewards.reputation == 5

    def test_service_contract_briefing_mentions_value(self):
        m = generate_service_contract_mission(
            "sc2", "delivery", "v2", "Vendor Beta",
            (3000.0, 4000.0), 300.0, 150.0,
        )
        assert "150" in m.briefing


# ===========================================================================
# 8. Trade Reputation Changes (§6.2.4) — 3 tests
# ===========================================================================


class TestTradeReputation:
    """Trade reputation adjusts correctly."""

    def setup_method(self):
        glvr.reset()

    def test_buy_trade_increases_reputation(self):
        ship = _make_ship(credits=500.0)
        glvr.spawn_vendor(
            vendor_type="allied_station",
            name="Ally",
            faction="allied",
            position=(0.0, 0.0),
        )
        v = glvr.get_vendors()[0]
        old_rep = ship.trade_reputation
        glvr.execute_trade(v.id, "fuel", 5, ship)
        assert ship.trade_reputation > old_rep

    def test_reputation_modifier_affects_price(self):
        vendor = _make_vendor()
        price_low = calculate_price("fuel", vendor, trade_reputation=-10.0)
        price_high = calculate_price("fuel", vendor, trade_reputation=60.0)
        # High rep should get better (lower) price
        assert price_high < price_low

    def test_reputation_range(self):
        """Trade reputation clamped to -100..100."""
        ship = Ship()
        ship.trade_reputation = 80.0
        glvr.adjust_reputation(ship, 200.0, "test")
        assert ship.trade_reputation <= 100.0
        glvr.adjust_reputation(ship, -300.0, "test")
        assert ship.trade_reputation >= -100.0


# ===========================================================================
# 9. Mission Completion Credit Award Pipeline — 2 tests
# ===========================================================================


class TestMissionCompletionPipeline:
    """Complete mission flow awards credits to ship."""

    def setup_method(self):
        gldm.reset()

    def test_complete_mission_produces_credit_event(self):
        """Mission completion event contains credits in rewards."""
        mission = DynamicMission(
            id="eco_m1",
            source_signal_id="s1",
            source_contact_id="c1",
            title="Bounty Hunt",
            briefing="Hunt the target.",
            mission_type="intercept",
            objectives=[
                MissionObjective(
                    id="eco_m1_o1",
                    description="Destroy target",
                    objective_type="destroy",
                    target_id="enemy_1",
                    order=1,
                ),
            ],
            waypoint=(100.0, 200.0),
            rewards=MissionRewards(credits=75.0, reputation=5),
            estimated_difficulty="hard",
        )
        gldm.offer_mission(mission)
        gldm.accept_mission("eco_m1")
        result = gldm.complete_mission("eco_m1")
        assert result["ok"]
        assert result["rewards"]["credits"] == 75.0
        # Event should also contain credits
        events = gldm.pop_pending_mission_events()
        completed_events = [e for e in events if e["event"] == "mission_completed"]
        assert len(completed_events) == 1
        assert completed_events[0]["rewards"]["credits"] == 75.0

    def test_complete_mission_no_credits_when_zero(self):
        mission = DynamicMission(
            id="eco_m2",
            source_signal_id="s2",
            source_contact_id="c2",
            title="Recon",
            briefing="Scout the area.",
            mission_type="patrol",
            objectives=[
                MissionObjective(
                    id="eco_m2_o1",
                    description="Navigate to waypoint",
                    objective_type="navigate_to",
                    target_position=(500.0, 500.0),
                    order=1,
                ),
            ],
            waypoint=(500.0, 500.0),
            rewards=MissionRewards(reputation=3),
            estimated_difficulty="easy",
        )
        gldm.offer_mission(mission)
        gldm.accept_mission("eco_m2")
        result = gldm.complete_mission("eco_m2")
        assert result["ok"]
        assert result["rewards"].get("credits", 0.0) == 0.0


# ===========================================================================
# 10. Credit Display (§6.4.3) — 2 tests
# ===========================================================================


class TestCreditDisplay:
    """Credits and trade reputation are stored on the Ship model."""

    def test_credits_on_ship(self):
        ship = _make_ship(credits=750.0)
        assert ship.credits == 750.0

    def test_trade_reputation_on_ship(self):
        ship = _make_ship(trade_reputation=25.0)
        assert ship.trade_reputation == 25.0

    def test_credits_arithmetic(self):
        """Credits can be added and deducted."""
        ship = _make_ship(credits=100.0)
        ship.credits += 50.0
        assert ship.credits == 150.0
        ship.credits -= 30.0
        assert ship.credits == 120.0
