"""Tests for v0.08 B.6: Emergency Systems."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

import pytest

import server.game_loop_hazard_control as glhc
import server.game_loop_atmosphere as glatm
from server.models.interior import ShipInterior, Room, make_default_interior


def fresh_interior():
    return make_default_interior()


@dataclass
class FakeDeckCrew:
    deck_name: str
    total: int = 6
    active: int = 6
    injured: int = 0
    critical: int = 0
    dead: int = 0

    @property
    def crew_factor(self) -> float:
        if self.total == 0:
            return 1.0
        effective = self.active + (self.injured * 0.5)
        return min(effective / self.total, 1.0)

    def apply_casualties(self, count: int) -> None:
        from_active = min(count, self.active)
        self.active -= from_active
        self.injured += from_active


class FakeCrewRoster:
    def __init__(self):
        self.decks = {
            "bridge": FakeDeckCrew("bridge"),
            "sensors": FakeDeckCrew("sensors"),
            "weapons": FakeDeckCrew("weapons"),
            "shields": FakeDeckCrew("shields"),
            "medical": FakeDeckCrew("medical"),
            "engineering": FakeDeckCrew("engineering"),
        }

    def apply_casualties(self, deck_name: str, count: int) -> None:
        deck = self.decks.get(deck_name)
        if deck is not None:
            deck.apply_casualties(count)


@dataclass
class FakeShipSystem:
    name: str
    power: float = 100.0
    health: float = 100.0
    room_id: str = ""


class FakeShip:
    def __init__(self):
        self.crew = FakeCrewRoster()
        self.systems = {
            "engines": FakeShipSystem("engines", room_id="engine_room"),
        }
        self.hull = 10.0
        self.hull_max = 120.0
        self.ship_class = "frigate"


def setup_function():
    glhc.reset()
    glatm.reset()


# =========================================================================
# B.6.1 — Emergency Bulkheads
# =========================================================================


class TestSealConnection:
    def test_seal_connection_adds_entry(self):
        interior = fresh_interior()
        # bridge ↔ conn are connected in the frigate layout
        result = glhc.seal_connection("bridge", "conn", interior)
        assert result is True
        assert glhc.is_connection_sealed("bridge", "conn") is True
        # Order shouldn't matter
        assert glhc.is_connection_sealed("conn", "bridge") is True

    def test_seal_connection_rejects_non_adjacent(self):
        interior = fresh_interior()
        # bridge and engine_room are not directly connected
        result = glhc.seal_connection("bridge", "engine_room", interior)
        assert result is False
        assert glhc.is_connection_sealed("bridge", "engine_room") is False

    def test_seal_connection_rejects_already_sealed(self):
        interior = fresh_interior()
        glhc.seal_connection("bridge", "conn", interior)
        result = glhc.seal_connection("bridge", "conn", interior)
        assert result is False

    def test_unseal_connection(self):
        interior = fresh_interior()
        glhc.seal_connection("bridge", "conn", interior)
        result = glhc.unseal_connection("bridge", "conn")
        assert result is True
        assert glhc.is_connection_sealed("bridge", "conn") is False

    def test_unseal_not_sealed(self):
        result = glhc.unseal_connection("bridge", "conn")
        assert result is False


class TestSealedConnectionBlocking:
    def test_sealed_connection_blocks_fire_spread(self):
        interior = fresh_interior()
        glhc.init_sections(interior)
        # Seal bridge ↔ conn
        glhc.seal_connection("bridge", "conn", interior)
        # Start intense fire in bridge
        glhc._rng = random.Random(42)
        glhc.start_fire("bridge", 5, interior)
        # Tick many times — fire should NOT spread to conn
        for _ in range(1000):
            glhc.tick(interior, 0.1)
        assert "conn" not in glhc.get_fires()

    def test_sealed_connection_blocks_pathfinding(self):
        interior = fresh_interior()
        # Without seal, path exists
        path = interior.find_path("bridge", "conn")
        assert len(path) > 0
        # Seal the connection
        glhc.seal_connection("bridge", "conn", interior)
        sealed = glhc.get_sealed_connections()
        # With blocked_connections, path should be blocked or rerouted
        path = interior.find_path("bridge", "conn", blocked_connections=sealed)
        # conn is directly adjacent to bridge — if sealed, path goes through
        # other rooms or is empty (depends on connectivity)
        # bridge → conn is the only direct route? Check if alternative exists
        if path:
            # Path should NOT go directly bridge→conn
            for i in range(len(path) - 1):
                key = (min(path[i], path[i + 1]), max(path[i], path[i + 1]))
                assert key not in sealed

    def test_sealed_connection_blocks_atmosphere_exchange(self):
        interior = fresh_interior()
        glatm.init_atmosphere(interior)
        glhc.init_sections(interior)
        # Set different O2 levels in bridge and conn
        atm_bridge = glatm._atmosphere.get("bridge")
        atm_conn = glatm._atmosphere.get("conn")
        assert atm_bridge is not None and atm_conn is not None
        atm_bridge.oxygen_percent = 10.0
        atm_conn.oxygen_percent = 21.0
        # Seal the connection
        glhc.seal_connection("bridge", "conn", interior)
        # Ensure vent state is open between bridge and conn
        glatm.set_vent_state("bridge", "conn", "open")
        # Tick atmosphere
        bridge_o2_before = atm_bridge.oxygen_percent
        glatm._tick_vent_exchange(0.1)
        # O2 should NOT change because connection is sealed
        assert atm_bridge.oxygen_percent == pytest.approx(bridge_o2_before, abs=0.001)


class TestOverrideSecurityLock:
    def test_override_unlocks_door(self):
        interior = fresh_interior()
        room = interior.rooms["bridge"]
        room.door_sealed = True
        events = glhc.override_security_lock("bridge", interior)
        assert room.door_sealed is False
        assert len(events) == 1
        assert events[0]["type"] == "security_override"
        assert events[0]["room_id"] == "bridge"

    def test_override_noop_if_not_sealed(self):
        interior = fresh_interior()
        events = glhc.override_security_lock("bridge", interior)
        assert len(events) == 0


# =========================================================================
# B.6.2 — Emergency Power
# =========================================================================


class TestEmergencyPowerInit:
    def test_batteries_init_at_180s(self):
        interior = fresh_interior()
        glhc.init_emergency_power(interior)
        batteries = glhc._deck_batteries
        assert len(batteries) > 0
        for dn, capacity in batteries.items():
            assert capacity == pytest.approx(glhc.EMERGENCY_BATTERY_CAPACITY)

    def test_power_state_defaults_to_main(self):
        interior = fresh_interior()
        glhc.init_emergency_power(interior)
        for dn, state in glhc._deck_power.items():
            assert state == "main"


class TestEmergencyPowerTriggers:
    def test_section_collapse_triggers_emergency(self):
        interior = fresh_interior()
        ship = FakeShip()
        glhc.init_sections(interior)
        glhc.init_emergency_power(interior)
        # Collapse a section on deck 1
        sections = glhc.get_sections()
        sec = next(s for s in sections.values() if s.deck_number == 1)
        sec.collapsed = True
        sec.integrity = 0.0
        # Tick to detect power state change
        events = glhc.tick(interior, 0.1, ship=ship)
        assert glhc._deck_power[1] == "emergency"

    def test_engines_health_zero_triggers_all_decks(self):
        interior = fresh_interior()
        ship = FakeShip()
        glhc.init_sections(interior)
        glhc.init_emergency_power(interior)
        # Kill engines
        ship.systems["engines"].health = 0.0
        events = glhc.tick(interior, 0.1, ship=ship)
        for dn, state in glhc._deck_power.items():
            assert state == "emergency"

    def test_battery_drains(self):
        interior = fresh_interior()
        ship = FakeShip()
        glhc.init_sections(interior)
        glhc.init_emergency_power(interior)
        # Kill engines to trigger emergency power
        ship.systems["engines"].health = 0.0
        initial_battery = glhc._deck_batteries[1]
        # Tick 10 seconds
        for _ in range(100):
            glhc.tick(interior, 0.1, ship=ship)
        assert glhc._deck_batteries[1] < initial_battery
        assert glhc._deck_batteries[1] == pytest.approx(initial_battery - 10.0, abs=0.5)

    def test_battery_exhaustion_transitions_to_none(self):
        interior = fresh_interior()
        ship = FakeShip()
        glhc.init_sections(interior)
        glhc.init_emergency_power(interior)
        ship.systems["engines"].health = 0.0
        # Set battery very low
        for dn in glhc._deck_batteries:
            glhc._deck_batteries[dn] = 0.5
        # Tick enough to exhaust
        for _ in range(10):
            glhc.tick(interior, 0.1, ship=ship)
        for dn, state in glhc._deck_power.items():
            assert state == "none"

    def test_power_auto_restores_when_engines_repaired(self):
        interior = fresh_interior()
        ship = FakeShip()
        glhc.init_sections(interior)
        glhc.init_emergency_power(interior)
        # Kill engines → emergency
        ship.systems["engines"].health = 0.0
        glhc.tick(interior, 0.1, ship=ship)
        assert glhc._deck_power[1] == "emergency"
        # Repair engines → main
        ship.systems["engines"].health = 50.0
        glhc.tick(interior, 0.1, ship=ship)
        assert glhc._deck_power[1] == "main"


class TestRedirectBattery:
    def test_redirect_transfers_time(self):
        interior = fresh_interior()
        glhc.init_emergency_power(interior)
        initial_1 = glhc._deck_batteries[1]
        initial_2 = glhc._deck_batteries[2]
        result = glhc.redirect_battery(1, 2)
        assert result is True
        assert glhc._deck_batteries[1] == pytest.approx(initial_1 - glhc.BATTERY_TRANSFER_AMOUNT)
        assert glhc._deck_batteries[2] == pytest.approx(initial_2 + glhc.BATTERY_TRANSFER_AMOUNT)

    def test_redirect_fails_insufficient(self):
        interior = fresh_interior()
        glhc.init_emergency_power(interior)
        glhc._deck_batteries[1] = 10.0
        result = glhc.redirect_battery(1, 2, amount=60.0)
        assert result is False


class TestNoPowerEffects:
    def test_no_power_crew_penalty(self):
        interior = fresh_interior()
        glhc.init_sections(interior)
        glhc.init_emergency_power(interior)
        # Set deck 1 to "none"
        glhc._deck_power[1] = "none"
        penalties = glhc.get_power_crew_penalties()
        # Deck 1 is "bridge" deck
        assert "bridge" in penalties
        assert penalties["bridge"] == pytest.approx(glhc.NO_POWER_CREW_PENALTY)

    def test_powerless_decks_query(self):
        interior = fresh_interior()
        glhc.init_emergency_power(interior)
        glhc._deck_power[3] = "none"
        powerless = glhc.get_powerless_decks()
        assert 3 in powerless
        assert 1 not in powerless


class TestManualPowerCut:
    def test_cut_and_restore(self):
        interior = fresh_interior()
        ship = FakeShip()
        glhc.init_sections(interior)
        glhc.init_emergency_power(interior)
        # Cut power to deck 2
        assert glhc.cut_deck_power(2) is True
        glhc.tick(interior, 0.1, ship=ship)
        assert glhc._deck_power[2] == "emergency"
        # Restore
        assert glhc.restore_deck_power(2) is True
        glhc.tick(interior, 0.1, ship=ship)
        assert glhc._deck_power[2] == "main"


# =========================================================================
# B.6.3 — Life Pods
# =========================================================================


class TestLifePodInit:
    def test_pods_init_frigate(self):
        interior = fresh_interior()
        glhc.init_sections(interior)
        glhc.init_life_pods("frigate", interior)
        pods = glhc.get_life_pods()
        # Frigate: 5 decks × 1 pod = 5 pods
        assert len(pods) == 5
        for pod in pods:
            assert pod.capacity == glhc.LIFE_POD_CAPACITY
            assert pod.launched is False
            assert pod.loaded_crew == 0

    def test_pods_init_cruiser_has_more(self):
        interior = fresh_interior()
        glhc.init_sections(interior)
        glhc.init_life_pods("cruiser", interior)
        pods = glhc.get_life_pods()
        # Cruiser is large ship: 2 pods/deck × 5 decks = 10
        assert len(pods) == 10


class TestAbandonShip:
    def test_abandon_ship_fails_hull_too_high(self):
        ship = FakeShip()
        ship.hull = 100.0  # way above 15% of 120
        result = glhc.order_abandon_ship(ship)
        assert result is False
        assert glhc.is_abandon_ship() is False

    def test_abandon_ship_succeeds_low_hull(self):
        ship = FakeShip()
        ship.hull = 10.0  # ~8.3% of 120, below 15%
        result = glhc.order_abandon_ship(ship)
        assert result is True
        assert glhc.is_abandon_ship() is True

    def test_abandon_ship_double_call_fails(self):
        ship = FakeShip()
        ship.hull = 10.0
        glhc.order_abandon_ship(ship)
        result = glhc.order_abandon_ship(ship)
        assert result is False


class TestCrewLoading:
    def test_crew_auto_load(self):
        interior = fresh_interior()
        ship = FakeShip()
        glhc.init_sections(interior)
        glhc.init_life_pods("frigate", interior)
        glhc.init_emergency_power(interior)
        ship.hull = 10.0
        glhc.order_abandon_ship(ship)
        # Tick for a few seconds to load crew
        for _ in range(50):  # 5 seconds
            glhc.tick(interior, 0.1, ship=ship)
        pods = glhc.get_life_pods()
        # At least some pods should have crew loaded
        total_loaded = sum(p.loaded_crew for p in pods)
        assert total_loaded > 0


class TestPodLaunch:
    def test_launch_starts_timer(self):
        interior = fresh_interior()
        ship = FakeShip()
        glhc.init_sections(interior)
        glhc.init_life_pods("frigate", interior)
        glhc.init_emergency_power(interior)
        ship.hull = 10.0
        glhc.order_abandon_ship(ship)
        # Load crew first
        for _ in range(50):
            glhc.tick(interior, 0.1, ship=ship)
        pods = glhc.get_life_pods()
        loaded_pod = next((p for p in pods if p.loaded_crew > 0), None)
        assert loaded_pod is not None
        result = glhc.launch_pod(loaded_pod.id)
        assert result is True
        assert loaded_pod.launch_timer == pytest.approx(glhc.LIFE_POD_LAUNCH_TIME)

    def test_pod_launched_after_timer(self):
        interior = fresh_interior()
        ship = FakeShip()
        glhc.init_sections(interior)
        glhc.init_life_pods("frigate", interior)
        glhc.init_emergency_power(interior)
        ship.hull = 10.0
        glhc.order_abandon_ship(ship)
        # Load crew
        for _ in range(50):
            glhc.tick(interior, 0.1, ship=ship)
        pods = glhc.get_life_pods()
        loaded_pod = next((p for p in pods if p.loaded_crew > 0), None)
        assert loaded_pod is not None
        crew_before = loaded_pod.loaded_crew
        glhc.launch_pod(loaded_pod.id)
        # Tick through launch timer (10s)
        for _ in range(110):  # 11 seconds to be safe
            glhc.tick(interior, 0.1, ship=ship)
        assert loaded_pod.launched is True

    def test_launch_fails_empty_pod(self):
        interior = fresh_interior()
        glhc.init_sections(interior)
        glhc.init_life_pods("frigate", interior)
        pods = glhc.get_life_pods()
        result = glhc.launch_pod(pods[0].id)
        assert result is False

    def test_evacuation_order(self):
        interior = fresh_interior()
        ship = FakeShip()
        glhc.init_sections(interior)
        glhc.init_life_pods("frigate", interior)
        glhc.init_emergency_power(interior)
        ship.hull = 10.0
        glhc.order_abandon_ship(ship)
        result = glhc.set_evacuation_order([5, 4, 3, 2, 1])
        assert result is True


# =========================================================================
# Integration
# =========================================================================


class TestSerialiseDeserialise:
    def test_sealed_connections_roundtrip(self):
        interior = fresh_interior()
        glhc.init_sections(interior)
        glhc.init_emergency_power(interior)
        glhc.init_life_pods("frigate", interior)
        glhc.seal_connection("bridge", "conn", interior)
        glhc.seal_connection("sensor_array", "science_lab", interior)
        data = glhc.serialise()
        glhc.reset()
        glhc.deserialise(data)
        assert glhc.is_connection_sealed("bridge", "conn")
        assert glhc.is_connection_sealed("sensor_array", "science_lab")

    def test_power_state_roundtrip(self):
        interior = fresh_interior()
        glhc.init_sections(interior)
        glhc.init_emergency_power(interior)
        glhc._deck_power[1] = "emergency"
        glhc._deck_batteries[1] = 100.0
        data = glhc.serialise()
        glhc.reset()
        glhc.deserialise(data)
        assert glhc._deck_power[1] == "emergency"
        assert glhc._deck_batteries[1] == pytest.approx(100.0)

    def test_life_pods_roundtrip(self):
        interior = fresh_interior()
        glhc.init_sections(interior)
        glhc.init_life_pods("frigate", interior)
        pods = glhc.get_life_pods()
        pods[0].loaded_crew = 3
        pods[0].launch_timer = 5.0
        data = glhc.serialise()
        glhc.reset()
        glhc.deserialise(data)
        restored = glhc.get_life_pods()
        assert len(restored) == 5
        assert restored[0].loaded_crew == 3
        assert restored[0].launch_timer == pytest.approx(5.0)

    def test_abandon_ship_roundtrip(self):
        interior = fresh_interior()
        glhc.init_sections(interior)
        glhc.init_life_pods("frigate", interior)
        glhc.init_emergency_power(interior)
        ship = FakeShip()
        ship.hull = 10.0
        glhc.order_abandon_ship(ship)
        glhc.set_evacuation_order([3, 2, 1])
        data = glhc.serialise()
        glhc.reset()
        glhc.deserialise(data)
        assert glhc.is_abandon_ship() is True
        assert glhc._evacuation_order == [3, 2, 1]


class TestBuildDCState:
    def test_includes_b6_data(self):
        interior = fresh_interior()
        glhc.init_sections(interior)
        glhc.init_emergency_power(interior)
        glhc.init_life_pods("frigate", interior)
        glhc.seal_connection("bridge", "conn", interior)
        state = glhc.build_dc_state(interior)
        assert "sealed_connections" in state
        assert len(state["sealed_connections"]) == 1
        assert "deck_power" in state
        assert "deck_batteries" in state
        assert "life_pods" in state
        assert len(state["life_pods"]) == 5
        assert "abandon_ship" in state
        assert state["abandon_ship"] is False


class TestDockingRestore:
    def test_restore_all_power(self):
        interior = fresh_interior()
        glhc.init_sections(interior)
        glhc.init_emergency_power(interior)
        glhc._deck_power[1] = "none"
        glhc._deck_batteries[1] = 0.0
        glhc._power_cut_overrides.add(1)
        glhc.restore_all_power()
        assert glhc._deck_power[1] == "main"
        assert glhc._deck_batteries[1] == pytest.approx(glhc.EMERGENCY_BATTERY_CAPACITY)
        assert 1 not in glhc._power_cut_overrides


class TestConstants:
    def test_emergency_power_constants(self):
        assert glhc.EMERGENCY_BATTERY_CAPACITY == 180.0
        assert glhc.BATTERY_TRANSFER_AMOUNT == 60.0
        assert glhc.NO_POWER_CREW_PENALTY == 0.80
        assert glhc.NO_POWER_CREW_DAMAGE == pytest.approx(0.017)

    def test_life_pod_constants(self):
        assert glhc.LIFE_POD_CAPACITY == 4
        assert glhc.LIFE_POD_LAUNCH_TIME == 10.0
        assert glhc.LIFE_POD_LOAD_RATE == 1.0
        assert glhc.ABANDON_SHIP_HULL_THRESHOLD == 0.15
        assert glhc.SMALL_SHIP_PODS_PER_DECK == 1
        assert glhc.LARGE_SHIP_PODS_PER_DECK == 2
        assert "cruiser" in glhc.LARGE_SHIP_CLASSES
        assert "carrier" in glhc.LARGE_SHIP_CLASSES
        assert "battleship" in glhc.LARGE_SHIP_CLASSES
