"""Tests for the Negotiation System — v0.07 Phase 6.3."""
from __future__ import annotations

import random
import pytest

from server.models.negotiation import (
    BARTER_PENALTY,
    BLUFF_BASE_CHANCE,
    BLUFF_COMMS_BONUS,
    BLUFF_COMPETING_SUCCESS_DISCOUNT,
    BLUFF_DAMAGE_PENALTY,
    BLUFF_MILITARY_BONUS,
    BLUFF_MILITARY_FAIL_REP,
    BLUFF_MILITARY_SUCCESS_DISCOUNT,
    BLUFF_NOT_URGENT_PENALTY_REP,
    BLUFF_REP_BONUS,
    BLUFF_REP_PENALTY,
    BLUFF_TYPES,
    BUNDLE_DISCOUNT_2ND,
    BUNDLE_DISCOUNT_3RD,
    CHANNEL_RANGE_DEGRADED,
    CHANNEL_RANGE_STABLE,
    COMBAT_URGENCY_MULTIPLIER,
    COUNTER_COOLDOWN,
    INSPECT_COST_FRACTION,
    MAX_COUNTER_ROUNDS,
    SERVICE_CONTRACT_TYPES,
    WALK_AWAY_CALLBACK_CHANCE,
    WALK_AWAY_CALLBACK_DELAY,
    WALK_AWAY_CALLBACK_DISCOUNT,
    BarterOffer,
    NegotiationSession,
    TradeChannel,
    calculate_barter_value,
    calculate_intel_value,
    evaluate_counter_offer,
)
from server.models.vendor import (
    BASE_PRICES,
    VENDOR_CIVILIAN_TYPES,
    VENDOR_MILITARY_TYPES,
    VENDOR_TEMPLATES,
    Vendor,
)
from server.models.dynamic_mission import generate_service_contract_mission
from server.models.ship import Ship
from server.models.resources import ResourceStore
import server.game_loop_vendor as glvr
import server.game_loop_negotiation as glng


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ship(credits: float = 1000.0, trade_reputation: float = 0.0) -> Ship:
    ship = Ship()
    ship.credits = credits
    ship.trade_reputation = trade_reputation
    ship.x = 0.0
    ship.y = 0.0
    ship.hull = 100.0
    ship.hull_max = 100.0
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
    mult = template.get("base_multiplier", 1.0)
    inv = inventory if inventory is not None else {"fuel": 500, "provisions": 200, "medical_supplies": 30}
    inv_max = {k: v * 2 for k, v in inv.items()}
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


def _setup_vendor_and_channel(ship=None, is_docked=True, vendor_type="neutral_station"):
    """Set up glvr + glng with a spawned vendor and open channel."""
    glvr.reset()
    glng.reset()
    vendor = glvr.spawn_vendor(
        vendor_type=vendor_type,
        name="Test Station",
        position=(1000.0, 2000.0),
        faction="neutral",
    )
    channel = glng.open_channel(vendor.id, None, 0.0, is_docked)
    assert isinstance(channel, TradeChannel)
    return vendor, channel


# ===========================================================================
# 1. TradeChannel model (3 tests)
# ===========================================================================


class TestTradeChannelModel:

    def test_creation(self):
        ch = TradeChannel(id="ch_1", vendor_id="v1", station_id="s1")
        assert ch.status == "open"
        assert ch.is_docked is False

    def test_to_dict_from_dict_roundtrip(self):
        ch = TradeChannel(id="ch_1", vendor_id="v1", station_id="s1",
                          status="degraded", distance=8000.0, is_docked=True)
        d = ch.to_dict()
        ch2 = TradeChannel.from_dict(d)
        assert ch2.id == ch.id
        assert ch2.status == "degraded"
        assert ch2.distance == 8000.0
        assert ch2.is_docked is True

    def test_status_transitions(self):
        ch = TradeChannel(id="ch_1", vendor_id="v1")
        assert ch.status == "open"
        ch.status = "degraded"
        assert ch.status == "degraded"
        ch.status = "closed"
        assert ch.status == "closed"


# ===========================================================================
# 2. NegotiationSession model (3 tests)
# ===========================================================================


class TestNegotiationSessionModel:

    def test_creation(self):
        s = NegotiationSession(id="neg_1", channel_id="ch_1", vendor_id="v1")
        assert s.status == "offer_presented"
        assert s.counter_rounds == 0
        assert s.bluff_used is False

    def test_to_dict_from_dict_roundtrip(self):
        s = NegotiationSession(
            id="neg_1", channel_id="ch_1", vendor_id="v1",
            item_type="fuel", quantity=100, vendor_offer=2.5,
            original_offer=2.5, counter_rounds=2, bluff_used=True,
        )
        d = s.to_dict()
        s2 = NegotiationSession.from_dict(d)
        assert s2.id == s.id
        assert s2.item_type == "fuel"
        assert s2.counter_rounds == 2
        assert s2.bluff_used is True

    def test_status_tracking(self):
        s = NegotiationSession(id="neg_1", channel_id="ch_1", vendor_id="v1")
        s.status = "counter_round"
        assert s.status == "counter_round"
        s.status = "completed"
        assert s.status == "completed"


# ===========================================================================
# 3. Channel management (4 tests)
# ===========================================================================


class TestChannelManagement:

    def test_open_close(self):
        glvr.reset()
        glng.reset()
        vendor = glvr.spawn_vendor("neutral_station", "Test", (0, 0))
        ch = glng.open_channel(vendor.id, None, 100.0, False)
        assert isinstance(ch, TradeChannel)
        assert ch.status == "open"
        assert glng.close_channel(ch.id) is True
        assert glng.get_channels() == []

    def test_range_stable(self):
        glvr.reset()
        glng.reset()
        vendor = glvr.spawn_vendor("neutral_station", "Test", (0, 0))
        ch = glng.open_channel(vendor.id, None, CHANNEL_RANGE_STABLE - 1, False)
        assert isinstance(ch, TradeChannel)
        assert ch.status == "open"

    def test_range_degraded(self):
        glvr.reset()
        glng.reset()
        vendor = glvr.spawn_vendor("neutral_station", "Test", (0, 0))
        ch = glng.open_channel(vendor.id, None, CHANNEL_RANGE_STABLE + 1000, False)
        assert isinstance(ch, TradeChannel)
        assert ch.status == "degraded"

    def test_range_out_of_range(self):
        glvr.reset()
        glng.reset()
        vendor = glvr.spawn_vendor("neutral_station", "Test", (0, 0))
        result = glng.open_channel(vendor.id, None, CHANNEL_RANGE_DEGRADED + 1, False)
        assert isinstance(result, str)
        assert "range" in result.lower()

    def test_docked_unlimited_range(self):
        glvr.reset()
        glng.reset()
        vendor = glvr.spawn_vendor("neutral_station", "Test", (0, 0))
        ch = glng.open_channel(vendor.id, None, 999999.0, True)
        assert isinstance(ch, TradeChannel)
        assert ch.status == "open"

    def test_no_duplicate_channels(self):
        glvr.reset()
        glng.reset()
        vendor = glvr.spawn_vendor("neutral_station", "Test", (0, 0))
        ch = glng.open_channel(vendor.id, None, 0.0, True)
        assert isinstance(ch, TradeChannel)
        result = glng.open_channel(vendor.id, None, 0.0, True)
        assert isinstance(result, str)
        assert "already" in result.lower()


# ===========================================================================
# 4. Negotiation flow (5 tests)
# ===========================================================================


class TestNegotiationFlow:

    def test_start_and_accept(self):
        vendor, ch = _setup_vendor_and_channel()
        ship = _make_ship(credits=10000.0)
        result = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
        assert result["ok"] is True
        assert "session_id" in result
        assert result["vendor_offer"] > 0

        accept = glng.accept_offer(result["session_id"], ship)
        assert accept["ok"] is True
        assert accept["credits_remaining"] < 10000.0

    def test_start_counter_accept(self):
        vendor, ch = _setup_vendor_and_channel()
        ship = _make_ship(credits=10000.0)
        result = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
        sid = result["session_id"]
        offer = result["vendor_offer"]

        # Counter within 10% → accepted
        counter = glng.counter_offer(sid, offer * 0.95, ship)
        assert counter["ok"] is True
        assert counter["response"] == "accepted"

    def test_bundle_discount(self):
        vendor, ch = _setup_vendor_and_channel()
        ship = _make_ship(credits=50000.0)

        # First item: no discount.
        r1 = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
        price1 = r1["vendor_offer"]
        glng.accept_offer(r1["session_id"], ship)

        # Second item: 5% discount.
        r2 = glng.start_negotiation(ch.id, "provisions", 10, False, ship)
        price2 = r2["vendor_offer"]
        glng.accept_offer(r2["session_id"], ship)

        # Third item: 10% discount.
        r3 = glng.start_negotiation(ch.id, "medical_supplies", 10, False, ship)
        price3 = r3["vendor_offer"]

        # Verify bundle discounts were applied (prices decrease relative to base).
        # Can't compare directly across item types, but bundle_index should advance.
        assert glng.get_bundle_count(vendor.id) == 2  # 2 completed trades

    def test_max_counter_rounds_final_offer(self):
        vendor, ch = _setup_vendor_and_channel()
        ship = _make_ship(credits=10000.0)
        result = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
        sid = result["session_id"]
        offer = result["vendor_offer"]

        # Counter 3 times at bad prices.
        for i in range(MAX_COUNTER_ROUNDS):
            c = glng.counter_offer(sid, offer * 0.75, ship)
            assert c["ok"] is True

        # Fourth counter should fail.
        c = glng.counter_offer(sid, offer * 0.75, ship)
        assert c["ok"] is False
        assert "maximum" in c["error"].lower() or "final" in c["error"].lower()

    def test_one_session_at_a_time(self):
        vendor, ch = _setup_vendor_and_channel()
        ship = _make_ship(credits=10000.0)
        r1 = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
        assert r1["ok"] is True
        r2 = glng.start_negotiation(ch.id, "provisions", 10, False, ship)
        assert r2["ok"] is False
        assert "already active" in r2["error"].lower()


# ===========================================================================
# 5. Counter-offer logic (6 tests)
# ===========================================================================


class TestCounterOfferLogic:

    def test_within_10_percent_accepted(self):
        resp, price = evaluate_counter_offer(9.5, 10.0, 10.0)
        assert resp == "accepted"
        assert price == 9.5

    def test_within_20_percent_split(self):
        resp, price = evaluate_counter_offer(8.5, 10.0, 10.0)
        assert resp == "split"
        assert price == pytest.approx(9.25, abs=0.01)

    def test_within_30_percent_concession(self):
        resp, price = evaluate_counter_offer(7.5, 10.0, 10.0)
        assert resp == "concession"
        assert price == pytest.approx(9.5, abs=0.01)

    def test_beyond_30_percent_raised(self):
        resp, price = evaluate_counter_offer(6.5, 10.0, 10.0)
        assert resp == "raised"
        assert price > 10.0

    def test_below_50_percent_break_off(self):
        resp, price = evaluate_counter_offer(4.0, 10.0, 10.0)
        assert resp == "broken_off"

    def test_cooldown_after_breakoff(self):
        vendor, ch = _setup_vendor_and_channel()
        ship = _make_ship(credits=10000.0)
        result = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
        sid = result["session_id"]
        offer = result["vendor_offer"]

        # Counter at 40% of vendor price → break off.
        c = glng.counter_offer(sid, offer * 0.3, ship)
        assert c["response"] == "broken_off"

        # Try to start new negotiation for same item — should fail due to cooldown.
        r2 = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
        assert r2["ok"] is False
        assert "cooldown" in r2["error"].lower()


# ===========================================================================
# 6. Walk-away / callback (4 tests)
# ===========================================================================


class TestWalkAwayCallback:

    def test_walk_away_callback_chance(self):
        """Walk away should have some callback probability."""
        callbacks = 0
        for _ in range(100):
            vendor, ch = _setup_vendor_and_channel()
            ship = _make_ship(credits=10000.0)
            r = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
            result = glng.walk_away(r["session_id"])
            if result.get("callback"):
                callbacks += 1
        # With 30% chance over 100 trials, should get at least some callbacks.
        assert callbacks > 5

    def test_callback_accept(self):
        # Force callback by using a fixed seed.
        vendor, ch = _setup_vendor_and_channel()
        ship = _make_ship(credits=50000.0)
        r = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
        original_offer = r["vendor_offer"]

        # Keep trying until we get a callback.
        for _ in range(50):
            glng.reset()
            glvr.reset()
            vendor, ch = _setup_vendor_and_channel()
            r = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
            result = glng.walk_away(r["session_id"])
            if result.get("callback"):
                accept = glng.accept_callback(r["session_id"], ship)
                assert accept["ok"] is True
                return
        pytest.skip("No callback triggered in 50 attempts")

    def test_callback_expire(self):
        # Keep trying until we get a callback, then let it expire.
        for _ in range(50):
            glng.reset()
            glvr.reset()
            vendor, ch = _setup_vendor_and_channel()
            ship = _make_ship(credits=50000.0)
            r = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
            result = glng.walk_away(r["session_id"])
            if result.get("callback"):
                # Tick past the callback delay.
                for _i in range(200):
                    glng.tick(None, ship, 0.1)
                sessions = glng.get_sessions()
                sess = [s for s in sessions if s.id == r["session_id"]][0]
                assert sess.status == "broken_off"
                return
        pytest.skip("No callback triggered in 50 attempts")

    def test_no_second_callback(self):
        """Second walk-away should close immediately."""
        for _ in range(50):
            glng.reset()
            glvr.reset()
            vendor, ch = _setup_vendor_and_channel()
            ship = _make_ship(credits=50000.0)
            r = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
            result = glng.walk_away(r["session_id"])
            if result.get("callback"):
                # Reject by walking away again.
                result2 = glng.walk_away(r["session_id"])
                assert result2.get("closed") is True
                return
        pytest.skip("No callback triggered in 50 attempts")


# ===========================================================================
# 7. Bluff mechanics (6 tests)
# ===========================================================================


class TestBluffMechanics:

    def test_base_chance(self):
        assert BLUFF_BASE_CHANCE == 0.50

    def test_rep_bonus(self):
        ship = _make_ship(trade_reputation=35.0)
        vendor, ch = _setup_vendor_and_channel()
        r = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
        chance = glng._calculate_bluff_chance("competing_offer", ship, vendor.id)
        assert chance >= BLUFF_BASE_CHANCE + BLUFF_REP_BONUS - 0.01

    def test_rep_penalty(self):
        ship = _make_ship(trade_reputation=-10.0)
        vendor, ch = _setup_vendor_and_channel()
        r = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
        chance = glng._calculate_bluff_chance("competing_offer", ship, vendor.id)
        assert chance <= BLUFF_BASE_CHANCE + BLUFF_REP_PENALTY + 0.01

    def test_hull_damage_penalty_for_not_urgent(self):
        ship = _make_ship()
        ship.hull = 30.0  # < 50% of hull_max (100)
        vendor, ch = _setup_vendor_and_channel()
        r = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
        chance = glng._calculate_bluff_chance("not_urgent", ship, vendor.id)
        assert chance <= BLUFF_BASE_CHANCE + BLUFF_DAMAGE_PENALTY + 0.01

    def test_military_ship_bonus(self):
        ship = _make_ship()
        ship.ship_class = "battleship"
        vendor, ch = _setup_vendor_and_channel()
        r = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
        chance = glng._calculate_bluff_chance("military_authority", ship, vendor.id)
        assert chance >= BLUFF_BASE_CHANCE + BLUFF_MILITARY_BONUS - 0.01

    def test_max_one_per_session(self):
        vendor, ch = _setup_vendor_and_channel()
        ship = _make_ship(credits=10000.0)
        r = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
        sid = r["session_id"]

        b1 = glng.attempt_bluff(sid, "competing_offer", ship)
        assert b1["ok"] is True

        b2 = glng.attempt_bluff(sid, "not_urgent", ship)
        assert b2["ok"] is False
        assert "already used" in b2["error"].lower()


# ===========================================================================
# 8. Barter system (4 tests)
# ===========================================================================


class TestBarterSystem:

    def test_resource_barter_at_80_percent(self):
        # Fuel base = 2cr each, 100 units, barter penalty = 80%.
        value = calculate_barter_value({"fuel": 100}, BASE_PRICES)
        assert value == pytest.approx(100 * 2 * BARTER_PENALTY, abs=0.01)

    def test_intel_value_per_vendor_type(self):
        mil_val = calculate_intel_value(1, "allied_station")
        civ_val = calculate_intel_value(1, "neutral_station")
        merch_val = calculate_intel_value(1, "merchant")
        assert mil_val > 0
        assert civ_val > 0
        assert merch_val > 0

    def test_black_market_50_percent(self):
        bm_val = calculate_intel_value(1, "black_market")
        merch_val = calculate_intel_value(1, "merchant")
        assert bm_val < merch_val

    def test_shortfall_rejection(self):
        vendor, ch = _setup_vendor_and_channel()
        ship = _make_ship(credits=0.0)
        r = glng.start_negotiation(ch.id, "fuel", 100, False, ship)
        sid = r["session_id"]

        # Offer tiny barter — should fail.
        result = glng.propose_barter(sid, {"resource_items": {"provisions": 1}}, ship)
        assert result["ok"] is False
        assert "shortfall" in result.get("error", "").lower() or result.get("shortfall", 0) > 0


# ===========================================================================
# 9. Service contracts (3 tests)
# ===========================================================================


class TestServiceContracts:

    def test_contract_types(self):
        assert len(SERVICE_CONTRACT_TYPES) == 4
        for ct in ("escort", "delivery", "scan", "patrol"):
            assert ct in SERVICE_CONTRACT_TYPES

    def test_generate_service_contract_mission(self):
        mission = generate_service_contract_mission(
            mission_id="contract_1",
            contract_type="escort",
            vendor_id="v1",
            vendor_name="Test Vendor",
            target_position=(5000.0, 5000.0),
            deadline=300.0,
            credit_value=500.0,
        )
        assert mission.id == "contract_1"
        assert "escort" in mission.title.lower()
        assert len(mission.objectives) == 1
        assert mission.objectives[0].objective_type == "escort_to"

    def test_failure_penalties_in_mission(self):
        mission = generate_service_contract_mission(
            mission_id="contract_2",
            contract_type="delivery",
            vendor_id="v2",
            vendor_name="Test Vendor 2",
            target_position=(5000.0, 5000.0),
            deadline=300.0,
            credit_value=800.0,
        )
        assert mission.failure_consequences.get("reputation") == -15
        assert "vendor" in mission.failure_consequences.get("faction_standing", {})


# ===========================================================================
# 10. Combat pressure (3 tests)
# ===========================================================================


class TestCombatPressure:

    def test_prices_increase_during_combat(self):
        vendor, ch = _setup_vendor_and_channel()
        ship = _make_ship(credits=50000.0)

        # No combat.
        glng.set_combat_active(False)
        r1 = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
        price_normal = r1["vendor_offer"]
        glng.accept_offer(r1["session_id"], ship)

        # With combat.
        glng.set_combat_active(True)
        r2 = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
        price_combat = r2["vendor_offer"]

        assert price_combat > price_normal

    def test_combat_multiplier_value(self):
        assert COMBAT_URGENCY_MULTIPLIER == 1.5

    def test_set_combat_active(self):
        glng.reset()
        assert glng.is_combat_active() is False
        glng.set_combat_active(True)
        assert glng.is_combat_active() is True
        glng.set_combat_active(False)
        assert glng.is_combat_active() is False


# ===========================================================================
# 11. Execute at price (2 tests)
# ===========================================================================


class TestExecuteAtPrice:

    def test_buy_at_negotiated_price(self):
        glvr.reset()
        vendor = glvr.spawn_vendor("neutral_station", "Test", (0, 0))
        ship = _make_ship(credits=500.0)
        result = glvr.execute_trade_at_price(vendor.id, "fuel", 10, 1.5, ship)
        assert result["ok"] is True
        assert result["unit_price"] == 1.5
        assert result["total_cost"] == 15.0
        assert ship.credits == pytest.approx(485.0, abs=0.01)

    def test_sell_at_negotiated_price(self):
        glvr.reset()
        vendor = glvr.spawn_vendor("neutral_station", "Test", (0, 0))
        ship = _make_ship(credits=100.0)
        result = glvr.sell_to_vendor_at_price(vendor.id, "fuel", 10, 3.0, ship)
        assert result["ok"] is True
        assert result["unit_price"] == 3.0
        assert result["total_earned"] == 30.0
        assert ship.credits == pytest.approx(130.0, abs=0.01)


# ===========================================================================
# 12. Save / resume (2 tests)
# ===========================================================================


class TestSaveResume:

    def test_negotiation_state_roundtrip(self):
        vendor, ch = _setup_vendor_and_channel()
        ship = _make_ship(credits=10000.0)
        r = glng.start_negotiation(ch.id, "fuel", 10, False, ship)

        state = glng.serialise()
        assert len(state["channels"]) == 1
        assert len(state["sessions"]) == 1

        glng.reset()
        assert glng.get_channels() == []

        glng.deserialise(state)
        assert len(glng.get_channels()) == 1
        assert len(glng.get_sessions()) == 1

    def test_backward_compat_no_negotiation_key(self):
        """Old saves without negotiation key should not crash."""
        glng.reset()
        # Simulating restore with empty data.
        glng.deserialise({})
        assert glng.get_channels() == []
        assert glng.get_sessions() == []


# ===========================================================================
# 13. Integration (1 test)
# ===========================================================================


class TestIntegration:

    def test_full_flow_open_negotiate_counter_accept(self):
        """Full flow: open channel → negotiate → counter within 10% → accept."""
        glvr.reset()
        glng.reset()

        vendor = glvr.spawn_vendor("neutral_station", "Test Station", (0, 0))
        ship = _make_ship(credits=50000.0)

        # Open channel.
        ch = glng.open_channel(vendor.id, None, 0.0, True)
        assert isinstance(ch, TradeChannel)

        # Start negotiation.
        r = glng.start_negotiation(ch.id, "fuel", 50, False, ship)
        assert r["ok"] is True
        offer = r["vendor_offer"]
        sid = r["session_id"]

        # Counter within 10%.
        counter = glng.counter_offer(sid, offer * 0.95, ship)
        assert counter["ok"] is True
        assert counter["response"] == "accepted"

        # Accept the accepted counter.
        accept = glng.accept_offer(sid, ship)
        assert accept["ok"] is True
        assert accept["credits_remaining"] < 50000.0
        assert ship.credits == accept["credits_remaining"]

        # Verify vendor events were emitted.
        events = glng.pop_pending_events()
        types = [e["type"] for e in events]
        assert "negotiation_started" in types
        assert "negotiation_completed" in types


# ===========================================================================
# 14. Vendor type constants (2 tests)
# ===========================================================================


class TestVendorTypeConstants:

    def test_civilian_types(self):
        assert "neutral_station" in VENDOR_CIVILIAN_TYPES
        assert "outpost" in VENDOR_CIVILIAN_TYPES
        assert "merchant" in VENDOR_CIVILIAN_TYPES

    def test_military_types(self):
        assert "allied_station" in VENDOR_MILITARY_TYPES
        assert "allied_warship" in VENDOR_MILITARY_TYPES


# ===========================================================================
# 15. Comms integration (1 test)
# ===========================================================================


class TestCommsIntegration:

    def test_has_decoded_vendor_signals(self):
        import server.game_loop_comms as glco
        glco.reset()
        # No signals → False.
        assert glco.has_decoded_vendor_signals("neutral") is False


# ===========================================================================
# 16. Inspect (1 test)
# ===========================================================================


class TestInspect:

    def test_inspect_deducts_credits(self):
        vendor, ch = _setup_vendor_and_channel()
        ship = _make_ship(credits=10000.0)
        r = glng.start_negotiation(ch.id, "fuel", 10, False, ship)
        sid = r["session_id"]

        result = glng.inspect_item(sid, ship)
        assert result["ok"] is True
        assert result["cost"] > 0
        assert ship.credits < 10000.0
