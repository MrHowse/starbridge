"""Tests for server/game_loop_flight_ops.py — drone and probe management."""
from __future__ import annotations

import pytest

import server.game_loop_flight_ops as glfo
from server.models.flight_ops import (
    DRONE_FUEL_DRAIN_DEPLOYED,
    DRONE_FUEL_DRAIN_TRANSIT,
    DRONE_FUEL_REFILL_RATE,
    DRONE_LOW_FUEL,
    DRONE_RECOVERY_DIST,
    DRONE_SENSOR_RANGE_BASE,
    DRONE_SPEED,
    PROBE_SENSOR_RANGE,
    DEFAULT_DRONE_COUNT,
    DEFAULT_PROBE_STOCK,
)
from server.models.messages import Message
from server.models.messages.base import validate_payload
from server.models.messages.flight_ops import (
    FlightOpsDeployProbePayload,
    FlightOpsLaunchDronePayload,
    FlightOpsRecallDronePayload,
)
from server.models.ship import Ship


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh_ship(x: float = 50_000.0, y: float = 50_000.0) -> Ship:
    s = Ship()
    s.x = x
    s.y = y
    return s


def setup_function():
    """Reset glfo state before each test."""
    glfo.reset()


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------


def test_reset_creates_default_drone_count():
    assert len(glfo.get_drones()) == DEFAULT_DRONE_COUNT


def test_reset_drones_in_hangar():
    for drone in glfo.get_drones():
        assert drone.state == "hangar"


def test_reset_drones_full_fuel():
    for drone in glfo.get_drones():
        assert drone.fuel == pytest.approx(100.0)


def test_reset_clears_probes():
    glfo.deploy_probe(1000.0, 2000.0)
    glfo.reset()
    assert glfo.get_probes() == []


def test_reset_restores_probe_stock():
    glfo.deploy_probe(1000.0, 2000.0)
    glfo.reset()
    assert glfo.get_probe_stock() == DEFAULT_PROBE_STOCK


def test_reset_custom_drone_count():
    glfo.reset(drone_count=4)
    assert len(glfo.get_drones()) == 4


def test_reset_custom_probe_stock():
    glfo.reset(probe_stock=8)
    assert glfo.get_probe_stock() == 8


def test_reset_drone_ids_unique():
    ids = [d.id for d in glfo.get_drones()]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# launch_drone()
# ---------------------------------------------------------------------------


def test_launch_drone_sets_transit():
    ship = fresh_ship()
    drone_id = glfo.get_drones()[0].id
    result = glfo.launch_drone(drone_id, 60_000.0, 50_000.0, ship)
    assert result is True
    assert glfo.get_drones()[0].state == "transit"


def test_launch_drone_places_at_ship_position():
    ship = fresh_ship(x=12_345.0, y=67_890.0)
    drone_id = glfo.get_drones()[0].id
    glfo.launch_drone(drone_id, 60_000.0, 50_000.0, ship)
    drone = glfo.get_drones()[0]
    assert drone.x == pytest.approx(12_345.0)
    assert drone.y == pytest.approx(67_890.0)


def test_launch_drone_sets_target():
    ship = fresh_ship()
    drone_id = glfo.get_drones()[0].id
    glfo.launch_drone(drone_id, 60_000.0, 55_000.0, ship)
    drone = glfo.get_drones()[0]
    assert drone.target_x == pytest.approx(60_000.0)
    assert drone.target_y == pytest.approx(55_000.0)


def test_launch_drone_nonexistent_returns_false():
    ship = fresh_ship()
    assert glfo.launch_drone("no_such_drone", 0.0, 0.0, ship) is False


def test_launch_drone_transit_returns_false():
    ship = fresh_ship()
    drone_id = glfo.get_drones()[0].id
    glfo.launch_drone(drone_id, 60_000.0, 50_000.0, ship)
    result = glfo.launch_drone(drone_id, 70_000.0, 50_000.0, ship)
    assert result is False


def test_launch_drone_deployed_returns_false():
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    drone.state = "deployed"
    assert glfo.launch_drone(drone.id, 60_000.0, 50_000.0, ship) is False


# ---------------------------------------------------------------------------
# recall_drone()
# ---------------------------------------------------------------------------


def test_recall_transit_drone_sets_returning():
    ship = fresh_ship()
    drone_id = glfo.get_drones()[0].id
    glfo.launch_drone(drone_id, 60_000.0, 50_000.0, ship)
    result = glfo.recall_drone(drone_id)
    assert result is True
    assert glfo.get_drones()[0].state == "returning"


def test_recall_deployed_drone_sets_returning():
    drone = glfo.get_drones()[0]
    drone.state = "deployed"
    result = glfo.recall_drone(drone.id)
    assert result is True
    assert drone.state == "returning"


def test_recall_hangar_drone_returns_false():
    drone = glfo.get_drones()[0]
    assert glfo.recall_drone(drone.id) is False


def test_recall_returning_drone_returns_false():
    drone = glfo.get_drones()[0]
    drone.state = "returning"
    assert glfo.recall_drone(drone.id) is False


def test_recall_nonexistent_returns_false():
    assert glfo.recall_drone("ghost_drone") is False


# ---------------------------------------------------------------------------
# deploy_probe()
# ---------------------------------------------------------------------------


def test_deploy_probe_decrements_stock():
    initial = glfo.get_probe_stock()
    glfo.deploy_probe(1000.0, 2000.0)
    assert glfo.get_probe_stock() == initial - 1


def test_deploy_probe_adds_to_list():
    glfo.deploy_probe(1000.0, 2000.0)
    assert len(glfo.get_probes()) == 1


def test_deploy_probe_correct_position():
    glfo.deploy_probe(12_345.6, 78_901.2)
    probe = glfo.get_probes()[0]
    assert probe.x == pytest.approx(12_345.6)
    assert probe.y == pytest.approx(78_901.2)


def test_deploy_probe_zero_stock_returns_false():
    glfo.reset(probe_stock=0)
    assert glfo.deploy_probe(1000.0, 2000.0) is False


def test_deploy_probe_zero_stock_no_probe_added():
    glfo.reset(probe_stock=0)
    glfo.deploy_probe(1000.0, 2000.0)
    assert glfo.get_probes() == []


def test_deploy_probe_multiple():
    glfo.deploy_probe(1000.0, 2000.0)
    glfo.deploy_probe(3000.0, 4000.0)
    assert len(glfo.get_probes()) == 2
    assert glfo.get_probe_stock() == DEFAULT_PROBE_STOCK - 2


# ---------------------------------------------------------------------------
# tick() — hangar (refuel)
# ---------------------------------------------------------------------------


def test_tick_hangar_refuels_drone():
    drone = glfo.get_drones()[0]
    drone.fuel = 50.0
    ship = fresh_ship()
    glfo.tick(ship, 1.0)
    assert drone.fuel == pytest.approx(50.0 + DRONE_FUEL_REFILL_RATE)


def test_tick_hangar_fuel_capped_at_100():
    drone = glfo.get_drones()[0]
    drone.fuel = 99.0
    ship = fresh_ship()
    glfo.tick(ship, 10.0)
    assert drone.fuel == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# tick() — transit (movement + fuel drain)
# ---------------------------------------------------------------------------


def test_tick_transit_drone_moves_toward_target():
    ship = fresh_ship(x=50_000.0, y=50_000.0)
    drone = glfo.get_drones()[0]
    drone.state = "transit"
    drone.x = 50_000.0
    drone.y = 50_000.0
    drone.target_x = 60_000.0
    drone.target_y = 50_000.0

    glfo.tick(ship, 1.0)
    assert drone.x == pytest.approx(50_000.0 + DRONE_SPEED)


def test_tick_transit_drains_fuel():
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    drone.state = "transit"
    drone.x = 50_000.0
    drone.y = 50_000.0
    drone.target_x = 60_000.0
    drone.target_y = 50_000.0

    glfo.tick(ship, 1.0)
    assert drone.fuel == pytest.approx(100.0 - DRONE_FUEL_DRAIN_TRANSIT)


def test_tick_transit_arrives_and_becomes_deployed():
    ship = fresh_ship(x=50_000.0, y=50_000.0)
    drone = glfo.get_drones()[0]
    drone.state = "transit"
    # Place drone very close to its target (within DRONE_RECOVERY_DIST)
    drone.target_x = 50_000.0 + DRONE_RECOVERY_DIST * 0.5
    drone.target_y = 50_000.0
    drone.x = 50_000.0
    drone.y = 50_000.0

    glfo.tick(ship, 1.0)
    assert drone.state == "deployed"


def test_tick_transit_auto_recall_on_low_fuel():
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    drone.state = "transit"
    drone.fuel = DRONE_LOW_FUEL + 0.01
    drone.x = 50_000.0
    drone.y = 50_000.0
    drone.target_x = 60_000.0
    drone.target_y = 50_000.0

    # One tick should drain fuel below threshold → auto-recall
    glfo.tick(ship, 1.0)
    assert drone.state == "returning"


# ---------------------------------------------------------------------------
# tick() — deployed (fuel drain + auto-recall)
# ---------------------------------------------------------------------------


def test_tick_deployed_drains_fuel():
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    drone.state = "deployed"
    initial_fuel = 80.0
    drone.fuel = initial_fuel

    glfo.tick(ship, 1.0)
    assert drone.fuel == pytest.approx(initial_fuel - DRONE_FUEL_DRAIN_DEPLOYED)


def test_tick_deployed_auto_recall_on_low_fuel():
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    drone.state = "deployed"
    drone.fuel = DRONE_LOW_FUEL + 0.01

    glfo.tick(ship, 1.0)
    assert drone.state == "returning"


def test_tick_deployed_fuel_not_below_zero():
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    drone.state = "deployed"
    drone.fuel = 0.01

    glfo.tick(ship, 1000.0)
    assert drone.fuel >= 0.0


# ---------------------------------------------------------------------------
# tick() — returning (movement + landing)
# ---------------------------------------------------------------------------


def test_tick_returning_drone_moves_toward_ship():
    ship = fresh_ship(x=50_000.0, y=50_000.0)
    drone = glfo.get_drones()[0]
    drone.state = "returning"
    drone.x = 60_000.0
    drone.y = 50_000.0

    glfo.tick(ship, 1.0)
    # Drone should have moved toward the ship (x decreased)
    assert drone.x < 60_000.0


def test_tick_returning_drone_lands_when_close():
    ship = fresh_ship(x=50_000.0, y=50_000.0)
    drone = glfo.get_drones()[0]
    drone.state = "returning"
    drone.fuel = 10.0
    # Place drone within recovery distance of ship
    drone.x = 50_000.0 + DRONE_RECOVERY_DIST * 0.5
    drone.y = 50_000.0

    glfo.tick(ship, 1.0)
    assert drone.state == "hangar"


# ---------------------------------------------------------------------------
# get_detection_bubbles()
# ---------------------------------------------------------------------------


def test_detection_bubbles_empty_when_no_deployed():
    bubbles = glfo.get_detection_bubbles(1.0)
    assert bubbles == []


def test_detection_bubbles_deployed_drone():
    drone = glfo.get_drones()[0]
    drone.state = "deployed"
    drone.x = 60_000.0
    drone.y = 50_000.0

    bubbles = glfo.get_detection_bubbles(1.0)
    assert len(bubbles) == 1
    x, y, r = bubbles[0]
    assert x == pytest.approx(60_000.0)
    assert y == pytest.approx(50_000.0)
    assert r == pytest.approx(DRONE_SENSOR_RANGE_BASE)


def test_detection_bubbles_drone_range_scales_with_efficiency():
    drone = glfo.get_drones()[0]
    drone.state = "deployed"

    bubbles = glfo.get_detection_bubbles(0.5)
    _, _, r = bubbles[0]
    assert r == pytest.approx(DRONE_SENSOR_RANGE_BASE * 0.5)


def test_detection_bubbles_probe():
    glfo.deploy_probe(70_000.0, 40_000.0)

    bubbles = glfo.get_detection_bubbles(1.0)
    assert len(bubbles) == 1
    x, y, r = bubbles[0]
    assert x == pytest.approx(70_000.0)
    assert y == pytest.approx(40_000.0)
    assert r == pytest.approx(PROBE_SENSOR_RANGE)


def test_detection_bubbles_transit_drone_excluded():
    drone = glfo.get_drones()[0]
    drone.state = "transit"

    bubbles = glfo.get_detection_bubbles(1.0)
    assert bubbles == []


def test_detection_bubbles_combined_drone_and_probe():
    drone = glfo.get_drones()[0]
    drone.state = "deployed"
    glfo.deploy_probe(70_000.0, 40_000.0)

    bubbles = glfo.get_detection_bubbles(1.0)
    assert len(bubbles) == 2


# ---------------------------------------------------------------------------
# build_state()
# ---------------------------------------------------------------------------


def test_build_state_has_required_keys():
    ship = fresh_ship()
    state = glfo.build_state(ship)
    assert "drones" in state
    assert "probes" in state
    assert "probe_stock" in state


def test_build_state_drone_count_matches():
    ship = fresh_ship()
    state = glfo.build_state(ship)
    assert len(state["drones"]) == DEFAULT_DRONE_COUNT


def test_build_state_probe_stock_correct():
    glfo.deploy_probe(1000.0, 2000.0)
    ship = fresh_ship()
    state = glfo.build_state(ship)
    assert state["probe_stock"] == DEFAULT_PROBE_STOCK - 1


def test_build_state_probe_in_list():
    glfo.deploy_probe(1234.5, 6789.0)
    ship = fresh_ship()
    state = glfo.build_state(ship)
    assert len(state["probes"]) == 1
    p = state["probes"][0]
    assert "id" in p
    assert "x" in p
    assert "y" in p


def test_build_state_drone_has_fuel_field():
    ship = fresh_ship()
    state = glfo.build_state(ship)
    for d in state["drones"]:
        assert "fuel" in d
        assert "state" in d
        assert "id" in d


# ---------------------------------------------------------------------------
# Sensor extension — extra_bubbles in sensors.build_sensor_contacts()
# ---------------------------------------------------------------------------


def test_sensor_contacts_include_all_enemies():
    """All enemies appear in sensor contacts regardless of range or bubbles."""
    from server.systems import sensors as sen
    from server.models.world import World, Enemy

    ship = Ship()
    ship.x = 50_000.0
    ship.y = 50_000.0
    ship.systems["sensors"].power = 1.0
    ship.systems["sensors"].health = 1.0

    world = World()
    e = Enemy(id="e1", type="scout", x=70_000.0, y=50_000.0)
    world.enemies.append(e)

    # All enemies included — no range filtering
    contacts = sen.build_sensor_contacts(world, ship)
    assert len(contacts) == 1
    assert contacts[0]["id"] == "e1"

    # extra_bubbles accepted but ignored (API compat)
    bubble = [(70_000.0, 50_000.0, 8_000.0)]
    contacts_with_bubble = sen.build_sensor_contacts(world, ship, extra_bubbles=bubble)
    assert len(contacts_with_bubble) == 1


# ---------------------------------------------------------------------------
# Message payload validation
# ---------------------------------------------------------------------------


def test_launch_drone_payload_validates():
    msg = Message.build("flight_ops.launch_drone", {
        "drone_id": "drone_1",
        "target_x": 60_000.0,
        "target_y": 50_000.0,
    })
    payload = validate_payload(msg)
    assert isinstance(payload, FlightOpsLaunchDronePayload)
    assert payload.drone_id == "drone_1"
    assert payload.target_x == pytest.approx(60_000.0)


def test_recall_drone_payload_validates():
    msg = Message.build("flight_ops.recall_drone", {"drone_id": "drone_2"})
    payload = validate_payload(msg)
    assert isinstance(payload, FlightOpsRecallDronePayload)
    assert payload.drone_id == "drone_2"


def test_deploy_probe_payload_validates():
    msg = Message.build("flight_ops.deploy_probe", {"target_x": 70_000.0, "target_y": 40_000.0})
    payload = validate_payload(msg)
    assert isinstance(payload, FlightOpsDeployProbePayload)
    assert payload.target_x == pytest.approx(70_000.0)
    assert payload.target_y == pytest.approx(40_000.0)


def test_launch_drone_payload_missing_field_raises():
    from pydantic import ValidationError
    msg = Message.build("flight_ops.launch_drone", {"drone_id": "drone_1"})
    with pytest.raises(ValidationError):
        validate_payload(msg)
