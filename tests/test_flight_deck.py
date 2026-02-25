"""Tests for server/models/flight_deck.py — v0.06.5 flight deck model."""
from __future__ import annotations

import random

import pytest

from server.models.drones import Drone, create_drone
from server.models.flight_deck import (
    BASE_LAUNCH_TIME,
    COMBAT_LAUNCH_DAMAGE_AMOUNT,
    CRASH_RECOVERY_BLOCK_TIME,
    CRASH_RECOVERY_DAMAGE,
    LAUNCH_PREP_TIME,
    REARM_TIME,
    REFUEL_TIME,
    REFUEL_RESERVE_COST,
    REARM_RESERVE_COST,
    FlightDeck,
    create_flight_deck,
    deserialise_flight_deck,
    serialise_flight_deck,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_deck(**kwargs) -> FlightDeck:
    return FlightDeck(**kwargs)


def make_combat_drone(drone_id: str = "drone_c1", hull: float = 60.0,
                      fuel: float = 100.0, ammo: float = 100.0) -> Drone:
    d = create_drone(drone_id, "combat", "Fang")
    d.hull = hull
    d.fuel = fuel
    d.ammo = ammo
    return d


# ---------------------------------------------------------------------------
# Launch queue
# ---------------------------------------------------------------------------


class TestLaunchQueue:
    def test_queue_launch(self):
        fd = make_deck(launch_tubes=1)
        assert fd.queue_launch("drone_1") is True
        assert "drone_1" in fd.launch_queue

    def test_queue_launch_duplicate_rejected(self):
        fd = make_deck()
        fd.queue_launch("drone_1")
        assert fd.queue_launch("drone_1") is False

    def test_queue_launch_rejected_during_fire(self):
        fd = make_deck()
        fd.set_fire(True)
        assert fd.queue_launch("drone_1") is False

    def test_queue_launch_rejected_no_power(self):
        fd = make_deck()
        fd.set_power(False)
        assert fd.queue_launch("drone_1") is False

    def test_cancel_launch_from_queue(self):
        fd = make_deck()
        fd.queue_launch("drone_1")
        assert fd.cancel_launch("drone_1") is True
        assert "drone_1" not in fd.launch_queue

    def test_cancel_launch_from_tube(self):
        fd = make_deck()
        fd.tubes_in_use.append("drone_1")
        assert fd.cancel_launch("drone_1") is True
        assert "drone_1" not in fd.tubes_in_use

    def test_cancel_nonexistent(self):
        fd = make_deck()
        assert fd.cancel_launch("drone_99") is False


# ---------------------------------------------------------------------------
# Can launch / can recover
# ---------------------------------------------------------------------------


class TestCanLaunchRecover:
    def test_can_launch_operational(self):
        fd = make_deck(launch_tubes=2)
        assert fd.can_launch is True

    def test_cannot_launch_tubes_full(self):
        fd = make_deck(launch_tubes=1)
        fd.tubes_in_use.append("drone_1")
        assert fd.can_launch is False

    def test_cannot_launch_fire(self):
        fd = make_deck()
        fd.set_fire(True)
        assert fd.can_launch is False

    def test_cannot_launch_no_power(self):
        fd = make_deck()
        fd.set_power(False)
        assert fd.can_launch is False

    def test_can_recover_operational(self):
        fd = make_deck(recovery_slots=1)
        assert fd.can_recover is True

    def test_cannot_recover_fire(self):
        fd = make_deck()
        fd.set_fire(True)
        assert fd.can_recover is False

    def test_cannot_recover_depressurised(self):
        fd = make_deck()
        fd.set_depressurised(True)
        assert fd.can_recover is False

    def test_cannot_recover_crash_block(self):
        fd = make_deck()
        fd.start_crash_block(random.Random(0))
        assert fd.can_recover is False

    def test_can_launch_during_depressurisation(self):
        """Launching possible when depressurised (drones are sealed)."""
        fd = make_deck()
        fd.set_depressurised(True)
        assert fd.can_launch is True  # launch ok, recovery not


# ---------------------------------------------------------------------------
# Recovery queue
# ---------------------------------------------------------------------------


class TestRecoveryQueue:
    def test_queue_recovery(self):
        fd = make_deck()
        assert fd.queue_recovery("drone_1") is True
        assert "drone_1" in fd.recovery_queue

    def test_queue_recovery_duplicate_rejected(self):
        fd = make_deck()
        fd.queue_recovery("drone_1")
        assert fd.queue_recovery("drone_1") is False

    def test_clear_to_land(self):
        fd = make_deck(recovery_slots=1)
        fd.queue_recovery("drone_1")
        assert fd.clear_to_land("drone_1") is True
        assert "drone_1" in fd.recovery_in_progress
        assert "drone_1" not in fd.recovery_queue

    def test_clear_to_land_not_in_queue(self):
        fd = make_deck()
        assert fd.clear_to_land("drone_99") is False

    def test_clear_to_land_deck_full(self):
        fd = make_deck(recovery_slots=1)
        fd.recovery_in_progress.append("drone_1")
        fd.queue_recovery("drone_2")
        assert fd.clear_to_land("drone_2") is False

    def test_prioritise_recovery(self):
        fd = make_deck()
        fd.queue_recovery("drone_1")
        fd.queue_recovery("drone_2")
        fd.queue_recovery("drone_3")
        fd.prioritise_recovery(["drone_3", "drone_1"])
        assert fd.recovery_queue == ["drone_3", "drone_1", "drone_2"]

    def test_abort_landing(self):
        fd = make_deck()
        fd.recovery_in_progress.append("drone_1")
        assert fd.abort_landing("drone_1") is True
        assert "drone_1" not in fd.recovery_in_progress
        assert fd.recovery_queue[0] == "drone_1"

    def test_abort_landing_not_in_progress(self):
        fd = make_deck()
        assert fd.abort_landing("drone_99") is False


# ---------------------------------------------------------------------------
# Turnaround
# ---------------------------------------------------------------------------


class TestTurnaround:
    def test_start_turnaround_full_needs(self):
        fd = make_deck()
        d = make_combat_drone(hull=30.0, fuel=50.0, ammo=40.0)
        fd.start_turnaround(d)
        ta = fd.turnarounds["drone_c1"]
        assert ta.needs_refuel is True
        assert ta.needs_rearm is True
        assert ta.needs_repair is True
        assert ta.refuel_remaining == pytest.approx(REFUEL_TIME)
        assert ta.rearm_remaining == pytest.approx(REARM_TIME)

    def test_start_turnaround_no_rearm_for_scout(self):
        fd = make_deck()
        d = create_drone("drone_s1", "scout", "Hawk")
        d.fuel = 50.0
        d.hull = 20.0  # damaged
        fd.start_turnaround(d)
        ta = fd.turnarounds["drone_s1"]
        assert ta.needs_rearm is False
        assert ta.rearm_remaining == pytest.approx(0.0)

    def test_start_turnaround_no_refuel_if_full(self):
        fd = make_deck()
        d = make_combat_drone(fuel=100.0, ammo=50.0, hull=60.0)
        fd.start_turnaround(d)
        ta = fd.turnarounds["drone_c1"]
        assert ta.needs_refuel is False

    def test_turnaround_complete_check(self):
        fd = make_deck()
        d = make_combat_drone(fuel=50.0, ammo=100.0, hull=60.0)
        fd.start_turnaround(d)
        assert fd.is_turnaround_complete("drone_c1") is False
        fd.rush_turnaround("drone_c1")
        assert fd.is_turnaround_complete("drone_c1") is True

    def test_turnaround_complete_no_turnaround(self):
        fd = make_deck()
        assert fd.is_turnaround_complete("drone_x") is True

    def test_turnaround_tick_completes(self):
        fd = make_deck()
        d = make_combat_drone(fuel=99.0, ammo=100.0, hull=60.0)
        fd.start_turnaround(d)
        # Only needs refuel: 15s
        events = fd.tick(20.0)  # well beyond refuel time
        assert fd.is_turnaround_complete("drone_c1") is True
        assert any(e["type"] == "turnaround_complete" for e in events)

    def test_turnaround_parallel(self):
        """Refuel and rearm happen in parallel — total is max, not sum."""
        fd = make_deck()
        d = make_combat_drone(fuel=50.0, ammo=50.0, hull=60.0)
        fd.start_turnaround(d)
        ta = fd.turnarounds["drone_c1"]
        # Total should be max(15, 20, 0) = 20, not 35.
        assert ta.total_remaining == pytest.approx(REARM_TIME)

    def test_rush_turnaround(self):
        fd = make_deck()
        d = make_combat_drone(fuel=50.0, ammo=50.0, hull=30.0)
        fd.start_turnaround(d)
        assert fd.rush_turnaround("drone_c1", skip=["rearm", "repair"]) is True
        assert fd.is_turnaround_complete("drone_c1") is True

    def test_rush_turnaround_nonexistent(self):
        fd = make_deck()
        assert fd.rush_turnaround("drone_99") is False

    def test_finish_turnaround(self):
        fd = make_deck()
        d = make_combat_drone(fuel=50.0)
        fd.start_turnaround(d)
        fd.finish_turnaround("drone_c1")
        assert "drone_c1" not in fd.turnarounds

    def test_fuel_lines_damage_slows_refuel(self):
        fd = make_deck()
        fd.fuel_lines_health = 50.0  # 50% → rate 0.5
        d = make_combat_drone(fuel=50.0, ammo=100.0, hull=60.0)
        fd.start_turnaround(d)
        ta_before = fd.turnarounds["drone_c1"].refuel_remaining
        fd.tick(1.0)
        ta_after = fd.turnarounds["drone_c1"].refuel_remaining
        # At 50% fuel lines, 1s removes 0.5s of refuel time.
        assert ta_after == pytest.approx(ta_before - 0.5)


# ---------------------------------------------------------------------------
# Deck emergencies
# ---------------------------------------------------------------------------


class TestDeckEmergencies:
    def test_fire_suspends_launch_and_recovery(self):
        fd = make_deck()
        fd.set_fire(True)
        assert fd.can_launch is False
        assert fd.can_recover is False
        assert fd.deck_status == "fire"

    def test_fire_cleared(self):
        fd = make_deck()
        fd.set_fire(True)
        fd.set_fire(False)
        assert fd.can_launch is True
        assert fd.can_recover is True
        assert fd.deck_status == "operational"

    def test_depressurised_blocks_recovery_not_launch(self):
        fd = make_deck()
        fd.set_depressurised(True)
        assert fd.can_launch is True
        assert fd.can_recover is False
        assert fd.deck_status == "depressurised"

    def test_depressurised_cleared(self):
        fd = make_deck()
        fd.set_depressurised(True)
        fd.set_depressurised(False)
        assert fd.can_recover is True

    def test_power_loss_blocks_launch(self):
        fd = make_deck()
        fd.set_power(False)
        assert fd.can_launch is False
        assert fd.deck_status == "power_loss"

    def test_power_restored(self):
        fd = make_deck()
        fd.set_power(False)
        fd.set_power(True)
        assert fd.can_launch is True
        assert fd.deck_status == "operational"

    def test_crash_blocks_recovery(self):
        fd = make_deck()
        # Use rng that won't trigger fire (seed 0 → 0.844 > 0.30).
        rng = random.Random(0)
        fd.start_crash_block(rng)
        assert fd.can_recover is False
        assert fd.crash_block_remaining == pytest.approx(CRASH_RECOVERY_BLOCK_TIME)
        # Crash should damage recovery health.
        assert fd.recovery_health == pytest.approx(100.0 - CRASH_RECOVERY_DAMAGE)

    def test_crash_clears_after_time(self):
        fd = make_deck()
        # Use rng that won't trigger fire (seed 0 → 0.844 > 0.30).
        rng = random.Random(0)
        fd.start_crash_block(rng)
        events = fd.tick(CRASH_RECOVERY_BLOCK_TIME + 1.0)
        assert fd.crash_block_remaining == pytest.approx(0.0)
        assert fd.can_recover is True
        assert any(e["type"] == "crash_cleared" for e in events)


# ---------------------------------------------------------------------------
# Launch/recovery rolls
# ---------------------------------------------------------------------------


class TestRolls:
    def test_launch_failure_healthy_catapult(self):
        fd = make_deck()
        fd.catapult_health = 100.0
        assert fd.roll_launch_failure() is False

    def test_launch_failure_damaged_catapult(self):
        fd = make_deck()
        fd.catapult_health = 30.0
        rng = random.Random(42)
        # Run multiple times to verify the roll happens.
        results = [fd.roll_launch_failure(rng) for _ in range(100)]
        assert any(results)  # at least one failure in 100 rolls
        assert not all(results)  # not all failures

    def test_bolter_healthy_recovery(self):
        fd = make_deck()
        fd.recovery_health = 100.0
        assert fd.roll_bolter() is False

    def test_bolter_mid_damage(self):
        fd = make_deck()
        fd.recovery_health = 40.0  # below 50%, above 25%
        rng = random.Random(42)
        results = [fd.roll_bolter(rng) for _ in range(200)]
        assert any(results)

    def test_bolter_severe_damage(self):
        fd = make_deck()
        fd.recovery_health = 20.0  # below 25%
        rng = random.Random(42)
        results = [fd.roll_bolter(rng) for _ in range(200)]
        # Higher chance → more bolters.
        bolter_rate = sum(results) / len(results)
        assert bolter_rate > 0.15  # should be around 30%

    def test_combat_launch_damage(self):
        fd = make_deck()
        rng = random.Random(42)
        results = [fd.roll_combat_launch_damage(rng) for _ in range(1000)]
        damage_count = sum(1 for r in results if r > 0)
        # ~5% chance → ~50 out of 1000.
        assert 20 < damage_count < 100

    def test_combat_launch_damage_amount(self):
        fd = make_deck()
        rng = random.Random(0)  # Find a seed that triggers damage.
        for _ in range(1000):
            dmg = fd.roll_combat_launch_damage(rng)
            if dmg > 0:
                assert dmg == pytest.approx(COMBAT_LAUNCH_DAMAGE_AMOUNT)
                break

    def test_effective_launch_time_healthy(self):
        fd = make_deck()
        fd.catapult_health = 100.0
        # 3s prep + 8s catapult = 11s
        assert fd.get_effective_launch_time() == pytest.approx(LAUNCH_PREP_TIME + BASE_LAUNCH_TIME)

    def test_effective_launch_time_damaged(self):
        fd = make_deck()
        fd.catapult_health = 50.0
        # factor = 0.5; catapult = 8 / 0.5 = 16; total = 3 + 16 = 19
        assert fd.get_effective_launch_time() == pytest.approx(LAUNCH_PREP_TIME + BASE_LAUNCH_TIME / 0.5)

    def test_effective_launch_time_very_damaged(self):
        fd = make_deck()
        fd.catapult_health = 10.0
        # factor = max(0.25, 0.1) = 0.25; catapult = 8 / 0.25 = 32; total = 3 + 32 = 35
        assert fd.get_effective_launch_time() == pytest.approx(LAUNCH_PREP_TIME + BASE_LAUNCH_TIME / 0.25)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestFactory:
    def test_frigate(self):
        fd = create_flight_deck("frigate")
        assert fd.hangar_slots == 4
        assert fd.launch_tubes == 1
        assert fd.recovery_slots == 1

    def test_cruiser(self):
        fd = create_flight_deck("cruiser")
        assert fd.hangar_slots == 6
        assert fd.launch_tubes == 2
        assert fd.recovery_slots == 2

    def test_carrier(self):
        fd = create_flight_deck("carrier")
        assert fd.hangar_slots == 12
        assert fd.launch_tubes == 3
        assert fd.recovery_slots == 2

    def test_scout(self):
        fd = create_flight_deck("scout")
        assert fd.hangar_slots == 2
        assert fd.launch_tubes == 1


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


class TestSerialisation:
    def test_flight_deck_round_trip(self):
        fd = make_deck(launch_tubes=2, hangar_slots=6)
        fd.tubes_in_use.append("drone_1")
        fd.launch_queue.append("drone_2")
        fd.recovery_queue.append("drone_3")
        fd.drone_fuel_reserve = 80.0
        fd.drone_ammo_reserve = 80.0
        fd.catapult_health = 75.0
        fd.set_fire(True)

        d = make_combat_drone(fuel=50.0, ammo=30.0, hull=40.0)
        fd.start_turnaround(d)
        # Turnaround consumes reserves: 80 - 10 = 70 (fuel), 80 - 15 = 65 (ammo).
        expected_fuel = 80.0 - REFUEL_RESERVE_COST
        expected_ammo = 80.0 - REARM_RESERVE_COST

        data = serialise_flight_deck(fd)
        restored = deserialise_flight_deck(data)

        assert restored.launch_tubes == 2
        assert restored.hangar_slots == 6
        assert "drone_1" in restored.tubes_in_use
        assert "drone_2" in restored.launch_queue
        assert "drone_3" in restored.recovery_queue
        assert restored.drone_fuel_reserve == pytest.approx(expected_fuel)
        assert restored.drone_ammo_reserve == pytest.approx(expected_ammo)
        assert restored.catapult_health == pytest.approx(75.0)
        assert restored.fire_active is True
        assert restored.deck_status == "fire"
        assert "drone_c1" in restored.turnarounds
        ta = restored.turnarounds["drone_c1"]
        assert ta.needs_refuel is True
        assert ta.needs_rearm is True
        assert ta.needs_repair is True

    def test_minimal_deserialise(self):
        data = {"launch_tubes": 1, "hangar_slots": 2}
        fd = deserialise_flight_deck(data)
        assert fd.launch_tubes == 1
        assert fd.deck_status == "operational"
        assert fd.power_available is True


# ---------------------------------------------------------------------------
# Reserve consumption
# ---------------------------------------------------------------------------


class TestReserveConsumption:
    def test_refuel_consumes_fuel_reserve(self):
        fd = make_deck()
        fd.drone_fuel_reserve = 50.0
        d = make_combat_drone(fuel=50.0, ammo=100.0, hull=60.0)
        fd.start_turnaround(d)
        assert fd.drone_fuel_reserve == pytest.approx(50.0 - REFUEL_RESERVE_COST)

    def test_rearm_consumes_ammo_reserve(self):
        fd = make_deck()
        fd.drone_ammo_reserve = 50.0
        d = make_combat_drone(fuel=100.0, ammo=50.0, hull=60.0)
        fd.start_turnaround(d)
        assert fd.drone_ammo_reserve == pytest.approx(50.0 - REARM_RESERVE_COST)

    def test_no_refuel_when_fuel_reserve_empty(self):
        fd = make_deck()
        fd.drone_fuel_reserve = 0.0
        d = make_combat_drone(fuel=50.0, ammo=100.0, hull=60.0)
        fd.start_turnaround(d)
        ta = fd.turnarounds["drone_c1"]
        assert ta.needs_refuel is False
        assert fd.drone_fuel_reserve == pytest.approx(0.0)

    def test_no_rearm_when_ammo_reserve_empty(self):
        fd = make_deck()
        fd.drone_ammo_reserve = 0.0
        d = make_combat_drone(fuel=100.0, ammo=50.0, hull=60.0)
        fd.start_turnaround(d)
        ta = fd.turnarounds["drone_c1"]
        assert ta.needs_rearm is False
        assert fd.drone_ammo_reserve == pytest.approx(0.0)

    def test_reserve_floor_at_zero(self):
        fd = make_deck()
        fd.drone_fuel_reserve = 3.0  # less than REFUEL_RESERVE_COST (10)
        d = make_combat_drone(fuel=50.0, ammo=100.0, hull=60.0)
        fd.start_turnaround(d)
        assert fd.drone_fuel_reserve == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Crash risk and fire
# ---------------------------------------------------------------------------


class TestCrashRisk:
    def test_check_crash_risk_healthy_drone(self):
        fd = make_deck()
        d = make_combat_drone(hull=60.0)
        assert fd.check_crash_risk(d) is False

    def test_check_crash_risk_critical_drone(self):
        fd = make_deck()
        d = make_combat_drone(hull=3.0)  # 3/60 = 5% < 10% threshold
        assert fd.check_crash_risk(d, random.Random(0)) is True
        assert fd.crash_block_remaining > 0

    def test_crash_fire_with_low_rng(self):
        """Seed 1 → random() = 0.134 < 0.30 → fire starts."""
        fd = make_deck()
        rng = random.Random(1)
        fd.start_crash_block(rng)
        assert fd.fire_active is True
        assert any(e["type"] == "crash_fire" for e in fd.pending_events)

    def test_crash_no_fire_with_high_rng(self):
        """Seed 0 → random() = 0.844 > 0.30 → no fire."""
        fd = make_deck()
        rng = random.Random(0)
        fd.start_crash_block(rng)
        assert fd.fire_active is False

    def test_crash_recovery_damage(self):
        fd = make_deck()
        fd.recovery_health = 80.0
        fd.start_crash_block(random.Random(0))
        assert fd.recovery_health == pytest.approx(80.0 - CRASH_RECOVERY_DAMAGE)

    def test_effective_recovery_time(self):
        fd = make_deck()
        expected = 5.0 + 5.0  # approach + catch
        assert fd.get_effective_recovery_time() == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Rush with selective skip
# ---------------------------------------------------------------------------


class TestRushSkip:
    def test_rush_skip_rearm(self):
        fd = make_deck()
        d = make_combat_drone(fuel=50.0, ammo=50.0, hull=30.0)
        fd.start_turnaround(d)
        fd.rush_turnaround("drone_c1", skip=["rearm"])
        ta = fd.turnarounds["drone_c1"]
        assert ta.needs_rearm is False
        assert ta.rearm_remaining == pytest.approx(0.0)

    def test_rush_skip_repair(self):
        fd = make_deck()
        d = make_combat_drone(fuel=100.0, ammo=100.0, hull=30.0)
        fd.start_turnaround(d)
        fd.rush_turnaround("drone_c1", skip=["repair"])
        ta = fd.turnarounds["drone_c1"]
        assert ta.needs_repair is False

    def test_rush_skip_all(self):
        fd = make_deck()
        d = make_combat_drone(fuel=50.0, ammo=50.0, hull=30.0)
        fd.start_turnaround(d)
        fd.rush_turnaround("drone_c1", skip=["refuel", "rearm", "repair"])
        assert fd.is_turnaround_complete("drone_c1") is True
