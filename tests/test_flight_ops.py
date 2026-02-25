"""Tests for server/game_loop_flight_ops.py — v0.06.5 rewrite."""
from __future__ import annotations

import pytest

import server.game_loop_flight_ops as glfo
from server.models.drones import (
    DECOY_STOCK,
    DRONE_COMPLEMENT,
    SensorBuoy,
)
from server.models.drone_missions import create_patrol_mission
from server.models.flight_deck import (
    BASE_LAUNCH_TIME,
    BASE_RECOVERY_CATCH_TIME,
    FlightDeck,
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


def test_reset_creates_frigate_complement():
    comp = DRONE_COMPLEMENT["frigate"]
    expected = sum(comp.values())
    assert len(glfo.get_drones()) == expected


def test_reset_drones_in_hangar():
    for drone in glfo.get_drones():
        assert drone.status == "hangar"


def test_reset_drones_full_fuel():
    for drone in glfo.get_drones():
        assert drone.fuel == pytest.approx(100.0)


def test_reset_clears_decoys():
    ship = fresh_ship()
    glfo.deploy_decoy_cmd(0.0, ship)
    glfo.reset()
    assert glfo.get_decoys() == []


def test_reset_restores_decoy_stock():
    ship = fresh_ship()
    glfo.deploy_decoy_cmd(0.0, ship)
    glfo.reset()
    assert glfo.get_decoy_stock() == DECOY_STOCK["frigate"]


def test_reset_carrier_creates_more_drones():
    glfo.reset("carrier")
    comp = DRONE_COMPLEMENT["carrier"]
    expected = sum(comp.values())
    assert len(glfo.get_drones()) == expected


def test_reset_clears_missions():
    glfo.reset()
    assert glfo.get_missions() == {}


def test_reset_clears_buoys():
    glfo.reset()
    assert glfo.get_buoys() == []


def test_reset_drone_ids_unique():
    ids = [d.id for d in glfo.get_drones()]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


def test_get_drone_by_id_found():
    d = glfo.get_drones()[0]
    assert glfo.get_drone_by_id(d.id) is d


def test_get_drone_by_id_missing():
    assert glfo.get_drone_by_id("no_such_drone") is None


def test_get_flight_deck_type():
    assert isinstance(glfo.get_flight_deck(), FlightDeck)


# ---------------------------------------------------------------------------
# launch_drone()
# ---------------------------------------------------------------------------


def test_launch_drone_queues():
    ship = fresh_ship()
    drone_id = glfo.get_drones()[0].id
    result = glfo.launch_drone(drone_id, ship)
    assert result is True
    fd = glfo.get_flight_deck()
    assert drone_id in fd.launch_queue or drone_id in fd.tubes_in_use


def test_launch_drone_sets_position():
    ship = fresh_ship(x=12_345.0, y=67_890.0)
    drone = glfo.get_drones()[0]
    glfo.launch_drone(drone.id, ship)
    assert drone.position == (12_345.0, 67_890.0)


def test_launch_drone_nonexistent_returns_false():
    ship = fresh_ship()
    assert glfo.launch_drone("no_such_drone", ship) is False


def test_launch_drone_active_returns_false():
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    drone.status = "active"
    assert glfo.launch_drone(drone.id, ship) is False


def test_launch_drone_already_queued_returns_false():
    ship = fresh_ship()
    drone_id = glfo.get_drones()[0].id
    glfo.launch_drone(drone_id, ship)
    result = glfo.launch_drone(drone_id, ship)
    assert result is False


# ---------------------------------------------------------------------------
# recall_drone()
# ---------------------------------------------------------------------------


def test_recall_active_drone():
    drone = glfo.get_drones()[0]
    drone.status = "active"
    result = glfo.recall_drone(drone.id)
    assert result is True
    assert drone.ai_behaviour == "rtb"


def test_recall_aborts_mission():
    drone = glfo.get_drones()[0]
    drone.status = "active"
    mission = create_patrol_mission(drone.id, [(10000, 10000)])
    glfo.assign_mission(drone.id, mission)
    glfo.recall_drone(drone.id)
    assert mission.status == "aborted"


def test_recall_hangar_drone_returns_false():
    drone = glfo.get_drones()[0]
    assert glfo.recall_drone(drone.id) is False


def test_recall_nonexistent_returns_false():
    assert glfo.recall_drone("ghost_drone") is False


# ---------------------------------------------------------------------------
# assign_mission()
# ---------------------------------------------------------------------------


def test_assign_mission_to_active_drone():
    drone = glfo.get_drones()[0]
    drone.status = "active"
    mission = create_patrol_mission(drone.id, [(10000, 10000)])
    result = glfo.assign_mission(drone.id, mission)
    assert result is True
    assert glfo.get_missions()[drone.id] is mission
    assert mission.status == "active"
    assert drone.mission_type == "patrol"


def test_assign_mission_to_hangar_returns_false():
    drone = glfo.get_drones()[0]
    mission = create_patrol_mission(drone.id, [(10000, 10000)])
    result = glfo.assign_mission(drone.id, mission)
    assert result is False


# ---------------------------------------------------------------------------
# set_waypoint / set_waypoints
# ---------------------------------------------------------------------------


def test_set_waypoint_on_active_drone():
    drone = glfo.get_drones()[0]
    drone.status = "active"
    result = glfo.set_waypoint(drone.id, 1000.0, 2000.0)
    assert result is True
    assert drone.waypoints == [(1000.0, 2000.0)]
    assert drone.waypoint_index == 0
    assert drone.loiter_point == (1000.0, 2000.0)


def test_set_waypoint_hangar_returns_false():
    drone = glfo.get_drones()[0]
    result = glfo.set_waypoint(drone.id, 1000.0, 2000.0)
    assert result is False


def test_set_waypoints_route():
    drone = glfo.get_drones()[0]
    drone.status = "active"
    route = [(1000.0, 2000.0), (3000.0, 4000.0)]
    result = glfo.set_waypoints(drone.id, route)
    assert result is True
    assert len(drone.waypoints) == 2
    assert drone.waypoint_index == 0


# ---------------------------------------------------------------------------
# set_engagement_rules / set_behaviour / designate_target
# ---------------------------------------------------------------------------


def test_set_engagement_rules():
    drone = glfo.get_drones()[0]
    result = glfo.set_engagement_rules(drone.id, "weapons_free")
    assert result is True
    assert drone.engagement_rules == "weapons_free"


def test_set_behaviour():
    drone = glfo.get_drones()[0]
    result = glfo.set_behaviour(drone.id, "patrol")
    assert result is True
    assert drone.ai_behaviour == "patrol"


def test_designate_target():
    drone = glfo.get_drones()[0]
    result = glfo.designate_target(drone.id, "enemy_1")
    assert result is True
    assert drone.contact_of_interest == "enemy_1"


def test_designate_target_nonexistent():
    result = glfo.designate_target("no_such", "enemy_1")
    assert result is False


# ---------------------------------------------------------------------------
# deploy_decoy_cmd()
# ---------------------------------------------------------------------------


def test_deploy_decoy_decrements_stock():
    ship = fresh_ship()
    initial = glfo.get_decoy_stock()
    glfo.deploy_decoy_cmd(0.0, ship)
    assert glfo.get_decoy_stock() == initial - 1


def test_deploy_decoy_creates_decoy():
    ship = fresh_ship()
    glfo.deploy_decoy_cmd(0.0, ship)
    assert len(glfo.get_decoys()) == 1


def test_deploy_decoy_position_north():
    ship = fresh_ship(x=50_000.0, y=50_000.0)
    glfo.deploy_decoy_cmd(0.0, ship)  # 0° = north
    decoy = glfo.get_decoys()[0]
    assert decoy.position[0] == pytest.approx(50_000.0, abs=1.0)
    # North means y decreases (sin(0)=0, -cos(0)=-1 → y - 2000)
    assert decoy.position[1] < 50_000.0


def test_deploy_decoy_zero_stock_returns_false():
    ship = fresh_ship()
    # Exhaust stock.
    for _ in range(DECOY_STOCK["frigate"]):
        glfo.deploy_decoy_cmd(0.0, ship)
    assert glfo.deploy_decoy_cmd(0.0, ship) is False


def test_deploy_decoy_generates_event():
    ship = fresh_ship()
    glfo.deploy_decoy_cmd(0.0, ship)
    # Pending events are drained in tick.
    events = glfo.tick(ship, 0.0)
    types = [e["type"] for e in events]
    assert "decoy_deployed" in types


# ---------------------------------------------------------------------------
# deploy_buoy_cmd()
# ---------------------------------------------------------------------------


def test_deploy_buoy_from_survey_drone():
    # Need a ship class with survey drones.
    glfo.reset("cruiser")
    drones = glfo.get_drones()
    survey_drone = next(d for d in drones if d.drone_type == "survey")
    survey_drone.status = "active"
    survey_drone.buoy_stock = 2
    result = glfo.deploy_buoy_cmd(survey_drone.id)
    assert result is True
    assert len(glfo.get_buoys()) == 1


def test_deploy_buoy_non_survey_returns_false():
    drone = glfo.get_drones()[0]  # scout in frigate
    drone.status = "active"
    result = glfo.deploy_buoy_cmd(drone.id)
    assert result is False


# ---------------------------------------------------------------------------
# escort_assign()
# ---------------------------------------------------------------------------


def test_escort_assign_combat_drone():
    drones = glfo.get_drones()
    combat = next(d for d in drones if d.drone_type == "combat")
    result = glfo.escort_assign(combat.id, "friendly_1")
    assert result is True
    assert combat.escort_target == "friendly_1"
    assert combat.ai_behaviour == "escort"


def test_escort_assign_non_combat_returns_false():
    drones = glfo.get_drones()
    scout = next(d for d in drones if d.drone_type == "scout")
    result = glfo.escort_assign(scout.id, "friendly_1")
    assert result is False


# ---------------------------------------------------------------------------
# clear_to_land / prioritise_recovery / abort_landing
# ---------------------------------------------------------------------------


def test_clear_to_land_from_recovery_queue():
    fd = glfo.get_flight_deck()
    drone = glfo.get_drones()[0]
    fd.recovery_queue.append(drone.id)
    result = glfo.clear_to_land(drone.id)
    assert result is True
    assert drone.id in fd.recovery_in_progress


def test_clear_to_land_not_in_queue_returns_false():
    assert glfo.clear_to_land("no_such") is False


def test_abort_landing():
    fd = glfo.get_flight_deck()
    drone = glfo.get_drones()[0]
    fd.recovery_in_progress.append(drone.id)
    result = glfo.abort_landing(drone.id)
    assert result is True
    assert drone.id in fd.recovery_queue


# ---------------------------------------------------------------------------
# tick() — launch processing
# ---------------------------------------------------------------------------


def test_tick_launch_completes():
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    glfo.launch_drone(drone.id, ship)
    # Tick past the launch time.
    events = glfo.tick(ship, BASE_LAUNCH_TIME + 1.0)
    launched = [e for e in events if e["type"] == "drone_launched"]
    assert len(launched) == 1
    assert drone.status == "active"


def test_tick_launch_incremental():
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    glfo.launch_drone(drone.id, ship)
    # Tick partway — should not complete yet.
    glfo.tick(ship, 1.0)
    assert drone.status == "launching"  # still in queue/tube
    # Tick the rest.
    events = glfo.tick(ship, BASE_LAUNCH_TIME)
    launched = [e for e in events if e["type"] == "drone_launched"]
    assert len(launched) == 1
    assert drone.status == "active"


def test_tick_launch_prep_event():
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    glfo.launch_drone(drone.id, ship)
    events = glfo.tick(ship, 0.1)  # small tick to start
    types = [e["type"] for e in events]
    assert "launch_prep" in types


# ---------------------------------------------------------------------------
# tick() — recovery processing
# ---------------------------------------------------------------------------


def test_tick_recovery_completes():
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    drone.status = "rtb"
    # First tick: RTB → queue_recovery → recovering.
    glfo.tick(ship, 0.1)
    assert drone.status == "recovering"
    # Next ticks: recovery timer counts down.
    events2 = glfo.tick(ship, BASE_RECOVERY_CATCH_TIME + 1.0)
    recovered = [e for e in events2 if e["type"] == "drone_recovered"]
    assert len(recovered) == 1
    assert drone.status == "maintenance"


def test_tick_recovery_starts_turnaround():
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    drone.status = "rtb"
    drone.fuel = 50.0
    # Queue and complete recovery.
    glfo.tick(ship, 0.1)  # rtb → recovering
    glfo.tick(ship, BASE_RECOVERY_CATCH_TIME + 1.0)  # complete recovery
    fd = glfo.get_flight_deck()
    assert drone.id in fd.turnarounds


# ---------------------------------------------------------------------------
# tick() — RTB arrival
# ---------------------------------------------------------------------------


def test_tick_rtb_queues_recovery():
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    drone.status = "rtb"
    events = glfo.tick(ship, 0.1)
    assert drone.status == "recovering"
    recovery_events = [e for e in events if e["type"] == "drone_recovery_queued"]
    assert len(recovery_events) == 1


# ---------------------------------------------------------------------------
# tick() — turnaround completion
# ---------------------------------------------------------------------------


def test_tick_turnaround_restores_drone():
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    drone.status = "rtb"
    drone.fuel = 50.0
    # RTB → recover → maintenance → turnaround → hangar.
    glfo.tick(ship, 0.1)  # queue recovery
    glfo.tick(ship, BASE_RECOVERY_CATCH_TIME + 1.0)  # complete recovery, start turnaround
    # Turnaround duration depends on fuel/repair needs — tick generously.
    for _ in range(100):
        glfo.tick(ship, 1.0)
    assert drone.status == "hangar"
    assert drone.fuel == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# tick() — decoy ticking
# ---------------------------------------------------------------------------


def test_tick_decoy_expires():
    ship = fresh_ship()
    glfo.deploy_decoy_cmd(0.0, ship)
    assert len(glfo.get_decoys()) == 1
    # Decoy lifetime is ~30s by default; tick past it.
    for _ in range(40):
        glfo.tick(ship, 1.0)
    assert len(glfo.get_decoys()) == 0


# ---------------------------------------------------------------------------
# tick() — destroyed/lost cleanup
# ---------------------------------------------------------------------------


def test_tick_destroyed_cleans_mission():
    drone = glfo.get_drones()[0]
    drone.status = "active"
    mission = create_patrol_mission(drone.id, [(10000, 10000)])
    glfo.assign_mission(drone.id, mission)
    assert drone.id in glfo.get_missions()
    drone.status = "destroyed"
    ship = fresh_ship()
    glfo.tick(ship, 0.1)
    assert drone.id not in glfo.get_missions()


# ---------------------------------------------------------------------------
# get_detection_bubbles()
# ---------------------------------------------------------------------------


def test_detection_bubbles_empty_when_no_active():
    bubbles = glfo.get_detection_bubbles(1.0)
    assert bubbles == []


def test_detection_bubbles_active_drone():
    drone = glfo.get_drones()[0]
    drone.status = "active"
    drone.position = (60_000.0, 50_000.0)
    bubbles = glfo.get_detection_bubbles(1.0)
    assert len(bubbles) == 1
    x, y, r = bubbles[0]
    assert x == pytest.approx(60_000.0)
    assert y == pytest.approx(50_000.0)
    assert r > 0


def test_detection_bubbles_scales_with_efficiency():
    drone = glfo.get_drones()[0]
    drone.status = "active"
    drone.position = (60_000.0, 50_000.0)
    full = glfo.get_detection_bubbles(1.0)[0][2]
    half = glfo.get_detection_bubbles(0.5)[0][2]
    assert half == pytest.approx(full * 0.5)


def test_detection_bubbles_buoy():
    buoy = SensorBuoy(
        id="buoy_1",
        position=(70_000.0, 40_000.0),
        deployed_by="drone_u1",
    )
    glfo._buoys.append(buoy)
    bubbles = glfo.get_detection_bubbles(1.0)
    assert len(bubbles) == 1


def test_detection_bubbles_hangar_excluded():
    bubbles = glfo.get_detection_bubbles(1.0)
    assert bubbles == []


def test_detection_bubbles_combined():
    drone = glfo.get_drones()[0]
    drone.status = "active"
    drone.position = (60_000.0, 50_000.0)
    buoy = SensorBuoy(
        id="buoy_1",
        position=(70_000.0, 40_000.0),
        deployed_by="drone_u1",
    )
    glfo._buoys.append(buoy)
    bubbles = glfo.get_detection_bubbles(1.0)
    assert len(bubbles) == 2


# ---------------------------------------------------------------------------
# build_state()
# ---------------------------------------------------------------------------


def test_build_state_has_required_keys():
    ship = fresh_ship()
    state = glfo.build_state(ship)
    assert "drones" in state
    assert "flight_deck" in state
    assert "buoys" in state
    assert "decoys" in state
    assert "decoy_stock" in state


def test_build_state_drone_count_matches():
    ship = fresh_ship()
    state = glfo.build_state(ship)
    expected = sum(DRONE_COMPLEMENT["frigate"].values())
    assert len(state["drones"]) == expected


def test_build_state_drone_has_fields():
    ship = fresh_ship()
    state = glfo.build_state(ship)
    d = state["drones"][0]
    for key in ("id", "callsign", "drone_type", "status", "x", "y",
                "heading", "speed", "hull", "max_hull", "fuel", "ammo",
                "ai_behaviour", "engagement_rules"):
        assert key in d, f"Missing key: {key}"


def test_build_state_flight_deck_has_fields():
    ship = fresh_ship()
    state = glfo.build_state(ship)
    fd = state["flight_deck"]
    for key in ("launch_tubes", "tubes_in_use", "launch_queue",
                "recovery_slots", "deck_status", "catapult_health"):
        assert key in fd, f"Missing key: {key}"


def test_build_state_decoy_stock_correct():
    ship = fresh_ship()
    glfo.deploy_decoy_cmd(0.0, ship)
    state = glfo.build_state(ship)
    assert state["decoy_stock"] == DECOY_STOCK["frigate"] - 1


# ---------------------------------------------------------------------------
# serialise / deserialise round-trip
# ---------------------------------------------------------------------------


def test_serialise_returns_dict():
    data = glfo.serialise()
    assert isinstance(data, dict)
    assert "drones" in data
    assert "flight_deck" in data
    assert "missions" in data
    assert "buoys" in data
    assert "decoys" in data


def test_serialise_round_trip():
    ship = fresh_ship()
    # Launch a drone to create some state.
    drone = glfo.get_drones()[0]
    glfo.launch_drone(drone.id, ship)
    # Deploy a decoy.
    glfo.deploy_decoy_cmd(90.0, ship)

    data = glfo.serialise()
    # Reset and restore.
    glfo.reset()
    glfo.deserialise(data)

    assert len(glfo.get_drones()) == sum(DRONE_COMPLEMENT["frigate"].values())
    assert glfo.get_decoy_stock() == DECOY_STOCK["frigate"] - 1
    assert len(glfo.get_decoys()) == 1


def test_serialise_missions_round_trip():
    drone = glfo.get_drones()[0]
    drone.status = "active"
    mission = create_patrol_mission(drone.id, [(10000, 10000)])
    glfo.assign_mission(drone.id, mission)

    data = glfo.serialise()
    glfo.reset()
    glfo.deserialise(data)

    assert drone.id in data["missions"]


def test_serialise_bingo_timers():
    drone = glfo.get_drones()[0]
    glfo._bingo_timers[drone.id] = 5.0
    data = glfo.serialise()
    assert data["bingo_timers"][drone.id] == 5.0


def test_serialise_launch_timers():
    drone = glfo.get_drones()[0]
    glfo._launch_timers[drone.id] = 3.0
    data = glfo.serialise()
    glfo.reset()
    glfo.deserialise(data)
    assert glfo._launch_timers[drone.id] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Sensor contacts integration
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

    contacts = sen.build_sensor_contacts(world, ship)
    assert len(contacts) == 1
    assert contacts[0]["id"] == "e1"

    # extra_bubbles accepted but ignored (API compat).
    bubble = [(70_000.0, 50_000.0, 8_000.0)]
    contacts2 = sen.build_sensor_contacts(world, ship, extra_bubbles=bubble)
    assert len(contacts2) == 1
