"""Tests for server/models/drones.py — v0.06.5 drone models."""
from __future__ import annotations

import math

import pytest

from server.models.drones import (
    BASE_SHIP_SPEED,
    BINGO_FUEL_SAFETY_MARGIN,
    CALLSIGN_POOLS,
    DECOY_LIFETIME,
    DECOY_STOCK,
    DRONE_COMPLEMENT,
    DRONE_TYPE_PARAMS,
    DRONE_TYPES,
    Decoy,
    Drone,
    SensorBuoy,
    create_drone,
    create_ship_drones,
    deserialise_buoy,
    deserialise_decoy,
    deserialise_drone,
    get_decoy_stock,
    get_hangar_slots,
    HANGAR_SLOTS,
    HULL_CRITICAL_THRESHOLD,
    HULL_SENSOR_PENALTY_THRESHOLD,
    HULL_SPEED_PENALTY_THRESHOLD,
    serialise_buoy,
    serialise_decoy,
    serialise_drone,
)


# ---------------------------------------------------------------------------
# Drone type generation
# ---------------------------------------------------------------------------


class TestScoutDrone:
    def test_scout_max_speed(self):
        d = create_drone("d1", "scout", "Hawk")
        assert d.max_speed == pytest.approx(BASE_SHIP_SPEED * 1.5)

    def test_scout_hull(self):
        d = create_drone("d1", "scout", "Hawk")
        assert d.hull == pytest.approx(30.0)
        assert d.max_hull == pytest.approx(30.0)

    def test_scout_fuel_consumption(self):
        d = create_drone("d1", "scout", "Hawk")
        assert d.fuel_consumption == pytest.approx(0.8)

    def test_scout_sensor_range(self):
        d = create_drone("d1", "scout", "Hawk")
        assert d.sensor_range == pytest.approx(25_000.0)

    def test_scout_no_weapons(self):
        d = create_drone("d1", "scout", "Hawk")
        assert d.weapon_damage == 0.0
        assert d.weapon_range == 0.0
        assert d.ammo == 0.0

    def test_scout_no_cargo(self):
        d = create_drone("d1", "scout", "Hawk")
        assert d.cargo_capacity == 0


class TestCombatDrone:
    def test_combat_max_speed(self):
        d = create_drone("d1", "combat", "Fang")
        assert d.max_speed == pytest.approx(BASE_SHIP_SPEED * 1.2)

    def test_combat_hull(self):
        d = create_drone("d1", "combat", "Fang")
        assert d.hull == pytest.approx(60.0)

    def test_combat_fuel_consumption(self):
        d = create_drone("d1", "combat", "Fang")
        assert d.fuel_consumption == pytest.approx(1.2)

    def test_combat_weapon_damage(self):
        d = create_drone("d1", "combat", "Fang")
        assert d.weapon_damage == pytest.approx(4.0)

    def test_combat_weapon_range(self):
        d = create_drone("d1", "combat", "Fang")
        assert d.weapon_range == pytest.approx(10_000.0)

    def test_combat_ammo(self):
        d = create_drone("d1", "combat", "Fang")
        assert d.ammo == pytest.approx(100.0)


class TestRescueDrone:
    def test_rescue_max_speed(self):
        d = create_drone("d1", "rescue", "Angel")
        assert d.max_speed == pytest.approx(BASE_SHIP_SPEED * 0.8)

    def test_rescue_hull(self):
        d = create_drone("d1", "rescue", "Angel")
        assert d.hull == pytest.approx(80.0)

    def test_rescue_cargo_capacity(self):
        d = create_drone("d1", "rescue", "Angel")
        assert d.cargo_capacity == 6

    def test_rescue_no_weapons(self):
        d = create_drone("d1", "rescue", "Angel")
        assert d.weapon_damage == 0.0


class TestSurveyDrone:
    def test_survey_max_speed(self):
        d = create_drone("d1", "survey", "Compass")
        assert d.max_speed == pytest.approx(BASE_SHIP_SPEED * 1.0)

    def test_survey_hull(self):
        d = create_drone("d1", "survey", "Compass")
        assert d.hull == pytest.approx(40.0)

    def test_survey_sensor_range(self):
        d = create_drone("d1", "survey", "Compass")
        assert d.sensor_range == pytest.approx(15_000.0)

    def test_survey_buoy_capacity(self):
        d = create_drone("d1", "survey", "Compass")
        assert d.buoy_capacity == 3
        assert d.buoys_remaining == 3


class TestEcmDrone:
    def test_ecm_max_speed(self):
        d = create_drone("d1", "ecm_drone", "Ghost")
        assert d.max_speed == pytest.approx(BASE_SHIP_SPEED * 1.4)

    def test_ecm_hull(self):
        d = create_drone("d1", "ecm_drone", "Ghost")
        assert d.hull == pytest.approx(25.0)

    def test_ecm_fuel_consumption(self):
        d = create_drone("d1", "ecm_drone", "Ghost")
        assert d.fuel_consumption == pytest.approx(1.5)

    def test_ecm_strength(self):
        d = create_drone("d1", "ecm_drone", "Ghost")
        assert d.ecm_strength == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# Fuel calculations
# ---------------------------------------------------------------------------


class TestFuelCalculations:
    def test_fuel_seconds_remaining(self):
        d = create_drone("d1", "scout", "Hawk")
        d.fuel = 80.0
        expected = 80.0 / 0.8
        assert d.fuel_seconds_remaining == pytest.approx(expected)

    def test_fuel_minutes_remaining(self):
        d = create_drone("d1", "scout", "Hawk")
        d.fuel = 48.0
        secs = 48.0 / 0.8
        assert d.fuel_minutes_remaining == pytest.approx(secs / 60.0)

    def test_fuel_seconds_remaining_zero_consumption(self):
        d = create_drone("d1", "scout", "Hawk")
        d.fuel_consumption = 0.0
        assert d.fuel_seconds_remaining == float("inf")


# ---------------------------------------------------------------------------
# Bingo fuel
# ---------------------------------------------------------------------------


class TestBingoFuel:
    def test_bingo_fuel_false_in_hangar(self):
        d = create_drone("d1", "scout", "Hawk")
        d.status = "hangar"
        assert d.is_bingo_fuel(50_000, 50_000) is False

    def test_bingo_fuel_true_when_low(self):
        d = create_drone("d1", "scout", "Hawk")
        d.status = "active"
        d.position = (60_000, 50_000)
        d.fuel = 1.0  # very low fuel
        assert d.is_bingo_fuel(50_000, 50_000) is True

    def test_bingo_fuel_false_when_plenty(self):
        d = create_drone("d1", "scout", "Hawk")
        d.status = "active"
        d.position = (50_100, 50_000)  # very close to ship
        d.fuel = 90.0
        assert d.is_bingo_fuel(50_000, 50_000) is False

    def test_bingo_fuel_distance_based(self):
        d = create_drone("d1", "combat", "Fang")
        d.status = "active"
        d.position = (80_000, 50_000)  # 30_000 units away
        dist = 30_000
        time_to_return = dist / d.max_speed
        fuel_needed = time_to_return * d.fuel_consumption
        margin = fuel_needed * BINGO_FUEL_SAFETY_MARGIN
        threshold = fuel_needed + margin

        # Just above threshold — should NOT be bingo
        d.fuel = threshold + 1.0
        assert d.is_bingo_fuel(50_000, 50_000) is False

        # Just below threshold — should BE bingo
        d.fuel = threshold - 0.1
        assert d.is_bingo_fuel(50_000, 50_000) is True


# ---------------------------------------------------------------------------
# Hull damage effects
# ---------------------------------------------------------------------------


class TestHullDamage:
    def test_full_hull_no_penalties(self):
        d = create_drone("d1", "combat", "Fang")  # 60 hull — comfortably above thresholds
        assert d.effective_max_speed == d.max_speed
        assert d.effective_sensor_range == d.sensor_range
        assert not d.is_critical

    def test_speed_penalty_below_75_pct(self):
        d = create_drone("d1", "combat", "Fang")  # max_hull = 60
        d.hull = d.max_hull * 0.74  # 74% of max
        assert d.effective_max_speed == pytest.approx(d.max_speed * 0.9)

    def test_no_speed_penalty_at_75_pct(self):
        d = create_drone("d1", "combat", "Fang")
        d.hull = d.max_hull * 0.76  # 76% — above threshold
        assert d.effective_max_speed == pytest.approx(d.max_speed)

    def test_sensor_penalty_below_50_pct(self):
        d = create_drone("d1", "scout", "Hawk")  # max_hull = 30
        d.hull = d.max_hull * 0.49  # 49% of max
        assert d.effective_sensor_range == pytest.approx(d.sensor_range * 0.75)

    def test_weapon_penalty_below_50_pct(self):
        d = create_drone("d1", "combat", "Fang")  # max_hull = 60
        d.hull = d.max_hull * 0.49
        assert d.effective_weapon_damage == pytest.approx(d.weapon_damage * 0.75)

    def test_critical_below_25_pct(self):
        d = create_drone("d1", "combat", "Fang")
        d.hull = d.max_hull * 0.24  # 24% of max
        assert d.is_critical is True

    def test_not_critical_at_zero(self):
        d = create_drone("d1", "scout", "Hawk")
        d.hull = 0.0
        assert d.is_critical is False  # destroyed, not critical

    def test_destroyed_at_zero(self):
        d = create_drone("d1", "scout", "Hawk")
        d.hull = 0.0
        assert d.is_destroyed is True

    def test_destroyed_by_status(self):
        d = create_drone("d1", "scout", "Hawk")
        d.status = "destroyed"
        assert d.is_destroyed is True

    def test_not_destroyed_healthy(self):
        d = create_drone("d1", "scout", "Hawk")
        assert d.is_destroyed is False

    def test_hull_percent(self):
        d = create_drone("d1", "combat", "Fang")  # max_hull = 60
        d.hull = 30.0
        assert d.hull_percent == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Callsigns
# ---------------------------------------------------------------------------


class TestCallsigns:
    def test_callsign_pools_cover_all_types(self):
        for dtype in DRONE_TYPES:
            assert dtype in CALLSIGN_POOLS
            assert len(CALLSIGN_POOLS[dtype]) >= 6

    def test_callsigns_unique_within_ship(self):
        drones = create_ship_drones("carrier")
        callsigns = [d.callsign for d in drones]
        assert len(callsigns) == len(set(callsigns))

    def test_callsigns_unique_within_type(self):
        drones = create_ship_drones("carrier")
        by_type: dict[str, list[str]] = {}
        for d in drones:
            by_type.setdefault(d.drone_type, []).append(d.callsign)
        for dtype, cs_list in by_type.items():
            assert len(cs_list) == len(set(cs_list)), f"Duplicate callsign in {dtype}"

    def test_drone_ids_unique(self):
        drones = create_ship_drones("carrier")
        ids = [d.id for d in drones]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Drone complement per ship class
# ---------------------------------------------------------------------------


class TestDroneComplement:
    def test_scout_complement(self):
        drones = create_ship_drones("scout")
        assert len(drones) == 2
        types = {d.drone_type for d in drones}
        assert "scout" in types
        assert "combat" in types

    def test_corvette_complement(self):
        drones = create_ship_drones("corvette")
        assert len(drones) == 3

    def test_frigate_complement(self):
        drones = create_ship_drones("frigate")
        assert len(drones) == 4

    def test_cruiser_complement(self):
        drones = create_ship_drones("cruiser")
        assert len(drones) == 6

    def test_battleship_complement(self):
        drones = create_ship_drones("battleship")
        assert len(drones) == 8
        types = [d.drone_type for d in drones]
        assert types.count("ecm_drone") == 1

    def test_medical_ship_complement(self):
        drones = create_ship_drones("medical_ship")
        assert len(drones) == 4
        types = [d.drone_type for d in drones]
        assert types.count("rescue") == 3
        assert types.count("combat") == 0

    def test_carrier_complement(self):
        drones = create_ship_drones("carrier")
        assert len(drones) == 12
        types = [d.drone_type for d in drones]
        assert types.count("scout") == 3
        assert types.count("combat") == 4
        assert types.count("rescue") == 2
        assert types.count("survey") == 2
        assert types.count("ecm_drone") == 1

    def test_hangar_slots_match(self):
        for cls_id, slot_count in HANGAR_SLOTS.items():
            drones = create_ship_drones(cls_id)
            assert len(drones) <= slot_count, (
                f"{cls_id}: {len(drones)} drones > {slot_count} hangar slots"
            )

    def test_unknown_class_returns_empty(self):
        drones = create_ship_drones("nonexistent")
        assert drones == []


# ---------------------------------------------------------------------------
# Hangar slots and decoy stock
# ---------------------------------------------------------------------------


class TestHangarAndDecoys:
    def test_hangar_slots_per_class(self):
        assert get_hangar_slots("scout") == 2
        assert get_hangar_slots("carrier") == 12

    def test_decoy_stock_per_class(self):
        assert get_decoy_stock("scout") == 2
        assert get_decoy_stock("frigate") == 3
        assert get_decoy_stock("carrier") == 4

    def test_decoy_default_lifetime(self):
        d = Decoy(id="decoy_1", position=(100.0, 200.0))
        assert d.lifetime == pytest.approx(DECOY_LIFETIME)
        assert d.active is True


# ---------------------------------------------------------------------------
# Sensor buoy
# ---------------------------------------------------------------------------


class TestSensorBuoy:
    def test_buoy_defaults(self):
        b = SensorBuoy(id="buoy_1", position=(1000.0, 2000.0))
        assert b.sensor_range == pytest.approx(15_000.0)
        assert b.active is True

    def test_buoy_deployed_by(self):
        b = SensorBuoy(id="buoy_1", position=(0.0, 0.0), deployed_by="Compass")
        assert b.deployed_by == "Compass"


# ---------------------------------------------------------------------------
# Serialise / deserialise
# ---------------------------------------------------------------------------


class TestSerialisation:
    def test_drone_round_trip(self):
        d = create_drone("drone_s1", "scout", "Hawk", hangar_slot=0)
        d.position = (10_000.0, 20_000.0)
        d.fuel = 75.5
        d.status = "active"
        d.waypoints = [(1.0, 2.0), (3.0, 4.0)]
        d.contacts_found = 3

        data = serialise_drone(d)
        restored = deserialise_drone(data)

        assert restored.id == d.id
        assert restored.callsign == d.callsign
        assert restored.drone_type == d.drone_type
        assert restored.position == pytest.approx(d.position)
        assert restored.fuel == pytest.approx(d.fuel)
        assert restored.status == d.status
        assert len(restored.waypoints) == 2
        assert restored.contacts_found == 3
        assert restored.sensor_range == pytest.approx(d.sensor_range)

    def test_decoy_round_trip(self):
        d = Decoy(id="decoy_1", position=(500.0, 600.0), heading=90.0, lifetime=15.0)
        data = serialise_decoy(d)
        restored = deserialise_decoy(data)
        assert restored.id == d.id
        assert restored.position == pytest.approx(d.position)
        assert restored.heading == pytest.approx(d.heading)
        assert restored.lifetime == pytest.approx(d.lifetime)

    def test_buoy_round_trip(self):
        b = SensorBuoy(id="buoy_1", position=(1000.0, 2000.0), deployed_by="Compass")
        data = serialise_buoy(b)
        restored = deserialise_buoy(data)
        assert restored.id == b.id
        assert restored.position == pytest.approx(b.position)
        assert restored.deployed_by == b.deployed_by
        assert restored.sensor_range == pytest.approx(b.sensor_range)

    def test_deserialise_handles_missing_fields(self):
        """Backward compatibility: minimal dict restores a valid drone."""
        data = {"id": "drone_x1", "callsign": "Test"}
        d = deserialise_drone(data)
        assert d.id == "drone_x1"
        assert d.status == "hangar"
        assert d.fuel == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Factory error handling
# ---------------------------------------------------------------------------


class TestFactoryErrors:
    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown drone type"):
            create_drone("d1", "invalid_type", "Test")

    def test_all_types_creatable(self):
        for dtype in DRONE_TYPES:
            pool = CALLSIGN_POOLS[dtype]
            d = create_drone(f"d_{dtype}", dtype, pool[0])
            assert d.drone_type == dtype
            assert d.hull > 0
            assert d.fuel == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Drone initial state
# ---------------------------------------------------------------------------


class TestDroneInitialState:
    def test_starts_in_hangar(self):
        d = create_drone("d1", "scout", "Hawk")
        assert d.status == "hangar"

    def test_starts_with_full_fuel(self):
        d = create_drone("d1", "combat", "Fang")
        assert d.fuel == pytest.approx(100.0)

    def test_starts_at_origin(self):
        d = create_drone("d1", "scout", "Hawk")
        assert d.position == (0.0, 0.0)

    def test_hangar_slot_assigned(self):
        d = create_drone("d1", "scout", "Hawk", hangar_slot=3)
        assert d.hangar_slot == 3

    def test_sequential_hangar_slots_in_complement(self):
        drones = create_ship_drones("frigate")
        slots = [d.hangar_slot for d in drones]
        assert slots == list(range(len(drones)))
