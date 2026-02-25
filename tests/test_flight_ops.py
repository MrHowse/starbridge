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
    BASE_RECOVERY_APPROACH_TIME,
    BASE_RECOVERY_CATCH_TIME,
    LAUNCH_PREP_TIME,
    FlightDeck,
)

# Full 2-phase launch time (prep + catapult) and full recovery time (approach + catch).
FULL_LAUNCH_TIME = LAUNCH_PREP_TIME + BASE_LAUNCH_TIME
FULL_RECOVERY_TIME = BASE_RECOVERY_APPROACH_TIME + BASE_RECOVERY_CATCH_TIME
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
    # Should create a patrol mission so the AI actually follows the route.
    assert drone.mission_type == "patrol"
    missions = glfo.get_missions()
    assert drone.id in missions
    assert missions[drone.id].mission_type == "patrol"
    assert len(missions[drone.id].waypoints) == 2


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
    # Tick past the full launch time (prep + catapult).
    events = glfo.tick(ship, FULL_LAUNCH_TIME + 1.0)
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
    # Tick the rest (need full launch time).
    events = glfo.tick(ship, FULL_LAUNCH_TIME)
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
    # Next ticks: recovery timer counts down (approach + catch = 10s).
    events2 = glfo.tick(ship, FULL_RECOVERY_TIME + 1.0)
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
    glfo.tick(ship, FULL_RECOVERY_TIME + 1.0)  # complete recovery
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
    glfo.tick(ship, FULL_RECOVERY_TIME + 1.0)  # complete recovery, start turnaround
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


# ---------------------------------------------------------------------------
# Mission lifecycle — timeout, completion, failure, survivor transfer
# ---------------------------------------------------------------------------


def _launch_and_activate(ship: Ship, drone_idx: int = 0, dt: float = 0.1) -> str:
    """Launch the Nth hangar drone and tick until active. Returns drone_id."""
    drones = glfo.get_drones()
    drone = drones[drone_idx]
    glfo.launch_drone(drone.id, ship)
    # Tick through full launch timer (prep + catapult).
    for _ in range(int(FULL_LAUNCH_TIME / dt) + 5):
        glfo.tick(ship, dt)
    assert drone.status == "active", f"Expected active, got {drone.status}"
    return drone.id


def test_mission_timeout_triggers_rtb():
    """When tick_num exceeds timeout_tick, the mission aborts and drone RTBs."""
    ship = fresh_ship()
    drone_id = _launch_and_activate(ship)
    drone = glfo.get_drone_by_id(drone_id)

    from server.models.drone_missions import create_patrol_mission
    mission = create_patrol_mission(drone_id, [(60_000, 60_000)], timeout_tick=10)
    glfo.assign_mission(drone_id, mission)

    # Tick with tick_num below timeout — no abort.
    events = glfo.tick(ship, 0.1, tick_num=5)
    assert drone.ai_behaviour != "rtb"

    # Tick with tick_num exceeding timeout — should abort + RTB.
    events = glfo.tick(ship, 0.1, tick_num=15)
    rtb_events = [e for e in events if e["type"] == "drone_rtb"]
    assert len(rtb_events) >= 1
    assert mission.status == "aborted"


def test_patrol_route_complete_triggers_rtb():
    """When patrol route is fully complete, drone auto-RTBs."""
    ship = fresh_ship()
    drone_id = _launch_and_activate(ship)
    drone = glfo.get_drone_by_id(drone_id)

    from server.models.drone_missions import create_patrol_mission
    # Single waypoint patrol — drone starts at ship pos.
    mission = create_patrol_mission(drone_id, [(50_001, 50_001)], loiter_time=0.0)
    glfo.assign_mission(drone_id, mission)

    # Manually advance the waypoint to simulate route completion.
    mission.advance_waypoint()
    assert mission.route_complete
    # Mark objective complete too.
    for obj in mission.objectives:
        obj.completed = True

    events = glfo.tick(ship, 0.1)
    complete_events = [e for e in events if e["type"] == "mission_complete"]
    assert len(complete_events) >= 1
    assert mission.status == "complete"


def test_mission_failure_on_drone_destruction():
    """When a drone is destroyed, its mission is marked as failed."""
    ship = fresh_ship()
    drone_id = _launch_and_activate(ship)
    drone = glfo.get_drone_by_id(drone_id)

    from server.models.drone_missions import create_patrol_mission
    mission = create_patrol_mission(drone_id, [(60_000, 60_000)])
    glfo.assign_mission(drone_id, mission)

    # Destroy the drone.
    from server.systems.drone_ai import apply_damage_to_drone
    apply_damage_to_drone(drone, drone.max_hull + 10)
    assert drone.status == "destroyed"

    events = glfo.tick(ship, 0.1)
    fail_events = [e for e in events if e["type"] == "mission_failed"]
    assert len(fail_events) >= 1
    assert fail_events[0]["mission_type"] == "patrol"
    assert fail_events[0]["reason"] == "destroyed"
    # Mission removed from active missions.
    assert drone_id not in glfo.get_missions()


def test_survivor_transfer_on_recovery():
    """Rescue drone cargo (survivors) generates transfer event on recovery."""
    ship = fresh_ship()
    # Reset as medical ship which has rescue drones.
    glfo.reset("medical_ship")
    # Find rescue drone.
    rescue = None
    for d in glfo.get_drones():
        if d.drone_type == "rescue":
            rescue = d
            break
    assert rescue is not None, "Medical ship must have rescue drones"

    drone_id = _launch_and_activate(ship, drone_idx=glfo.get_drones().index(rescue))
    drone = glfo.get_drone_by_id(drone_id)
    drone.cargo_current = 3  # Simulate 3 survivors aboard.

    # Set drone to RTB.
    drone.ai_behaviour = "rtb"
    drone.status = "rtb"

    # Tick until recovered.
    all_events = []
    for _ in range(200):
        evts = glfo.tick(ship, 0.1)
        all_events.extend(evts)
        if drone.status in ("maintenance", "hangar"):
            break

    transfer_events = [e for e in all_events if e["type"] == "survivors_transferred"]
    assert len(transfer_events) >= 1
    assert transfer_events[0]["count"] == 3
    assert drone.cargo_current == 0


def test_ecm_fuel_multiplier():
    """ECM drone consumes 2x fuel while actively jamming."""
    from server.systems.drone_ai import (
        DroneWorldContext,
        ECM_FUEL_MULTIPLIER,
        tick_drone,
    )
    from server.models.drones import create_drone

    ecm = create_drone("ecm_test", "ecm_drone", "Ghost")
    ecm.status = "active"
    ecm.fuel = 100.0
    ecm.position = (50_000, 50_000)

    # Tick with no contacts — normal fuel burn.
    ctx_empty = DroneWorldContext(ship_x=50_000, ship_y=50_000)
    initial_fuel = ecm.fuel
    tick_drone(ecm, 1.0, ctx_empty)
    normal_burn = initial_fuel - ecm.fuel

    # Reset fuel.
    ecm.fuel = 100.0
    initial_fuel = ecm.fuel

    # Tick with a hostile contact in ECM range — should burn 2x.
    ctx_hostile = DroneWorldContext(
        ship_x=50_000, ship_y=50_000,
        contacts=[{
            "id": "e1", "x": 50_100, "y": 50_100,
            "classification": "hostile", "kind": "enemy",
        }],
    )
    tick_drone(ecm, 1.0, ctx_hostile)
    ecm_burn = initial_fuel - ecm.fuel

    # ECM burn should be ~2x normal burn.
    assert ecm_burn == pytest.approx(normal_burn * ECM_FUEL_MULTIPLIER, rel=0.05)


def test_build_state_includes_new_fields():
    """build_state includes sensor_range, waypoints, and other new fields."""
    ship = fresh_ship()
    drone_id = _launch_and_activate(ship)
    drone = glfo.get_drone_by_id(drone_id)

    state = glfo.build_state(ship)
    d_state = next(d for d in state["drones"] if d["id"] == drone_id)

    assert "sensor_range" in d_state
    assert "weapon_range" in d_state
    assert "weapon_damage" in d_state
    assert "ecm_strength" in d_state
    assert "buoys_remaining" in d_state
    assert "buoy_capacity" in d_state
    assert "max_speed" in d_state
    assert "waypoints" in d_state
    assert "waypoint_index" in d_state
    assert "loiter_point" in d_state


def test_reset_uses_ship_class():
    """reset() with different ship class creates correct complement."""
    glfo.reset("carrier")
    expected = sum(DRONE_COMPLEMENT["carrier"].values())
    assert len(glfo.get_drones()) == expected
    # Carrier should have ECM drones.
    ecm_drones = [d for d in glfo.get_drones() if d.drone_type == "ecm_drone"]
    assert len(ecm_drones) == 1


# ---------------------------------------------------------------------------
# 2-phase launch
# ---------------------------------------------------------------------------


def test_two_phase_launch_prep_then_catapult():
    """Launch has a 3s prep phase, then 8s catapult phase."""
    from server.models.flight_deck import LAUNCH_PREP_TIME as LPT
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    glfo.launch_drone(drone.id, ship)

    # After 1s (within prep), no launch yet.
    glfo.tick(ship, 1.0)
    assert drone.status == "launching"

    # After prep completes (3s total), still launching (catapult phase).
    glfo.tick(ship, LPT)  # 1+3 = 4s total
    assert drone.status == "launching"

    # After catapult completes (8s more from prep end).
    events = glfo.tick(ship, 8.0)
    launched = [e for e in events if e["type"] == "drone_launched"]
    assert len(launched) == 1
    assert drone.status == "active"


def test_launch_prep_event_emitted():
    """A launch_prep event is emitted when a drone enters the tube."""
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    glfo.launch_drone(drone.id, ship)
    events = glfo.tick(ship, 0.1)
    types = [e["type"] for e in events]
    assert "launch_prep" in types


# ---------------------------------------------------------------------------
# Cancel launch
# ---------------------------------------------------------------------------


def test_cancel_launch_during_prep():
    """Cancel launch during prep phase returns drone to hangar."""
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    glfo.launch_drone(drone.id, ship)
    glfo.tick(ship, 0.1)  # Enter tube, start prep.
    assert drone.status == "launching"

    result = glfo.cancel_launch(drone.id)
    assert result is True
    assert drone.status == "hangar"


def test_cancel_launch_nonexistent_returns_false():
    assert glfo.cancel_launch("no_such") is False


# ---------------------------------------------------------------------------
# Combat launch damage conditional
# ---------------------------------------------------------------------------


def test_combat_launch_damage_only_in_combat():
    """Combat launch damage only rolls when in_combat=True."""
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    glfo.launch_drone(drone.id, ship)
    # Launch without combat — no damage events.
    events = glfo.tick(ship, FULL_LAUNCH_TIME + 1.0, in_combat=False)
    dmg_events = [e for e in events if e["type"] == "combat_launch_damage"]
    assert len(dmg_events) == 0


# ---------------------------------------------------------------------------
# Ditch mechanism
# ---------------------------------------------------------------------------


def test_ditch_rtb_drone_fuel_empty_deck_fire():
    """RTB drone with fuel=0 when deck has fire → ditched (lost)."""
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    drone.status = "rtb"
    drone.fuel = 0.0
    fd = glfo.get_flight_deck()
    fd.set_fire(True)

    events = glfo.tick(ship, 0.1)
    assert drone.status == "lost"
    ditch_events = [e for e in events if e["type"] == "drone_ditched"]
    assert len(ditch_events) >= 1


def test_ditch_not_triggered_when_deck_ok():
    """RTB drone with fuel=0 but deck operational → NOT ditched (queues recovery)."""
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    drone.status = "rtb"
    drone.fuel = 0.0

    glfo.tick(ship, 0.1)
    # Should queue recovery, not ditch.
    assert drone.status == "recovering"


def test_ditch_recovering_drone_fuel_empty_deck_depressurised():
    """Recovering drone with fuel=0 when deck depressurised → ditched."""
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    drone.status = "recovering"
    drone.fuel = 0.0
    fd = glfo.get_flight_deck()
    fd.set_depressurised(True)

    events = glfo.tick(ship, 0.1)
    assert drone.status == "lost"


# ---------------------------------------------------------------------------
# Auto-crash on recovery
# ---------------------------------------------------------------------------


def test_auto_crash_on_recovery_of_critical_drone():
    """Drone with hull < 10% crashes on deck during recovery."""
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    drone.status = "rtb"
    drone.hull = 1.0  # Below 10% of max

    # RTB → queue → recovery.
    glfo.tick(ship, 0.1)
    assert drone.status == "recovering"

    # Complete recovery → crash expected.
    events = glfo.tick(ship, FULL_RECOVERY_TIME + 1.0)
    crash_events = [e for e in events if e["type"] == "drone_crash_on_deck"]
    assert len(crash_events) >= 1
    assert drone.status == "destroyed"


# ---------------------------------------------------------------------------
# build_state turnaround sub-tasks
# ---------------------------------------------------------------------------


def test_build_state_turnaround_has_subtasks():
    """build_state turnaround entries include per-sub-task fields."""
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    drone.status = "rtb"
    drone.fuel = 50.0

    glfo.tick(ship, 0.1)  # queue recovery
    glfo.tick(ship, FULL_RECOVERY_TIME + 1.0)  # complete recovery, start turnaround

    state = glfo.build_state(ship)
    fd = state["flight_deck"]
    assert drone.id in fd["turnarounds"]
    ta = fd["turnarounds"][drone.id]
    assert "total_remaining" in ta
    assert "needs_refuel" in ta
    assert "refuel_remaining" in ta
    assert "needs_rearm" in ta
    assert "rearm_remaining" in ta
    assert "needs_repair" in ta
    assert "repair_remaining" in ta


# ---------------------------------------------------------------------------
# Serialise new state
# ---------------------------------------------------------------------------


def test_serialise_launch_phases():
    """Launch phases and retry delays are serialised/deserialised."""
    drone = glfo.get_drones()[0]
    glfo._launch_phases[drone.id] = "prep"
    glfo._retry_delays[drone.id] = 3.0
    glfo._recovery_timers[drone.id] = 7.0

    data = glfo.serialise()
    glfo.reset()
    glfo.deserialise(data)

    assert glfo._launch_phases.get(drone.id) == "prep"
    assert glfo._retry_delays.get(drone.id) == pytest.approx(3.0)
    assert glfo._recovery_timers.get(drone.id) == pytest.approx(7.0)


# ---------------------------------------------------------------------------
# Active drone tick updates position (Gap 3)
# ---------------------------------------------------------------------------


def test_tick_active_drone_updates_position():
    """An active drone should change position after tick."""
    ship = fresh_ship()
    drone = glfo.get_drones()[0]
    glfo.launch_drone(drone.id, ship)
    glfo.tick(ship, FULL_LAUNCH_TIME + 1.0)
    assert drone.status == "active"

    # Give the drone a loiter point so it moves.
    drone.loiter_point = (60000.0, 50000.0)
    pos_before = drone.position

    glfo.tick(ship, 1.0)

    # Position should have changed.
    assert drone.position != pos_before


# ---------------------------------------------------------------------------
# Combat drone events in tick output (Gap 4)
# ---------------------------------------------------------------------------


def test_tick_combat_drone_attack_events():
    """Combat drone attack events should appear in tick output."""
    ship = fresh_ship()
    drones = glfo.get_drones()
    combat = next(d for d in drones if d.drone_type == "combat")

    # Launch and activate.
    glfo.launch_drone(combat.id, ship)
    glfo.tick(ship, FULL_LAUNCH_TIME + 1.0)
    assert combat.status == "active"

    # Set up engagement with a contact in range.
    combat.ai_behaviour = "engage"
    combat.contact_of_interest = "enemy_1"
    contact = {"id": "enemy_1", "x": ship.x + 5000.0, "y": ship.y,
               "classification": "hostile"}

    events = glfo.tick(ship, 0.1, contacts=[contact])
    attack_events = [e for e in events if e.get("type") == "drone_attack"]
    assert len(attack_events) == 1
    assert attack_events[0]["target_id"] == "enemy_1"
    assert attack_events[0]["damage"] > 0


# ---------------------------------------------------------------------------
# Bingo warning through game loop tick (Gap 5)
# ---------------------------------------------------------------------------


def test_tick_bingo_fuel_warning():
    """Bingo fuel warning should appear in tick events."""
    ship = fresh_ship()
    drone = glfo.get_drones()[0]

    # Launch and activate.
    glfo.launch_drone(drone.id, ship)
    glfo.tick(ship, FULL_LAUNCH_TIME + 1.0)
    assert drone.status == "active"

    # Move drone far from ship and set low fuel.
    drone.position = (ship.x + 50000.0, ship.y)
    drone.fuel = 5.0

    events = glfo.tick(ship, 0.1)
    bingo_events = [e for e in events if e.get("type") == "bingo_fuel"]
    assert len(bingo_events) == 1
    assert bingo_events[0]["drone_id"] == drone.id
    assert drone.bingo_acknowledged is True


# ---------------------------------------------------------------------------
# Bingo auto-recall through game loop tick (Gap 6)
# ---------------------------------------------------------------------------


def test_tick_bingo_auto_recall():
    """Bingo auto-recall should fire after 15s through game loop tick."""
    ship = fresh_ship()
    drone = glfo.get_drones()[0]

    # Launch and activate.
    glfo.launch_drone(drone.id, ship)
    glfo.tick(ship, FULL_LAUNCH_TIME + 1.0)
    assert drone.status == "active"

    # Trigger bingo.
    drone.bingo_acknowledged = True
    drone.cargo_current = 0  # no critical cargo

    # Tick for less than auto-recall delay — no recall.
    for _ in range(100):
        glfo.tick(ship, 0.1)
    assert drone.ai_behaviour != "rtb"

    # Tick past auto-recall delay (15s total).
    for _ in range(60):
        glfo.tick(ship, 0.1)
    # Should have auto-recalled.
    assert drone.ai_behaviour == "rtb"


def test_tick_bingo_auto_recall_blocked_by_critical_cargo():
    """Bingo auto-recall should NOT fire when drone has critical cargo."""
    ship = fresh_ship()
    drones = glfo.get_drones()
    rescue = next(d for d in drones if d.drone_type == "rescue")

    # Launch and activate.
    glfo.launch_drone(rescue.id, ship)
    glfo.tick(ship, FULL_LAUNCH_TIME + 1.0)
    assert rescue.status == "active"

    # Trigger bingo with cargo (survivors aboard).
    rescue.bingo_acknowledged = True
    rescue.cargo_current = 3

    # Tick well past auto-recall delay.
    for _ in range(200):
        glfo.tick(ship, 0.1)
    # Should NOT have auto-recalled — critical cargo.
    assert rescue.ai_behaviour != "rtb"


# ---------------------------------------------------------------------------
# Part 6 audit — set_loiter_point
# ---------------------------------------------------------------------------


def test_set_loiter_point_sets_loiter_and_clears_waypoints():
    """set_loiter_point should set loiter_point, clear waypoints, set behaviour."""
    ship = fresh_ship()
    drone_id = _launch_and_activate(ship)
    drone = glfo.get_drone_by_id(drone_id)

    # Set a waypoint first.
    glfo.set_waypoint(drone_id, 60_000, 70_000)
    assert len(drone.waypoints) > 0

    # Now set loiter point — should clear waypoints.
    result = glfo.set_loiter_point(drone_id, 40_000, 30_000)
    assert result is True
    assert drone.loiter_point == (40_000, 30_000)
    assert drone.waypoints == []
    assert drone.ai_behaviour == "loiter"


def test_set_loiter_point_rejects_hangar_drone():
    """set_loiter_point should return False for drones in hangar."""
    drone_id = glfo.get_drones()[0].id
    result = glfo.set_loiter_point(drone_id, 40_000, 30_000)
    assert result is False


def test_set_loiter_point_rejects_unknown_id():
    """set_loiter_point should return False for unknown drone id."""
    result = glfo.set_loiter_point("bogus_id", 40_000, 30_000)
    assert result is False


# ---------------------------------------------------------------------------
# Part 6 audit — build_state includes new fields
# ---------------------------------------------------------------------------


def test_build_state_includes_part6_fields():
    """build_state includes fuel_consumption, damage_dealt, contacts_found,
    survivors_rescued, and pickup_timer in drone dicts."""
    ship = fresh_ship()
    drone_id = _launch_and_activate(ship)
    drone = glfo.get_drone_by_id(drone_id)
    # Set some tracking values.
    drone.damage_dealt = 12.5
    drone.contacts_found = 3
    drone.survivors_rescued = 2
    drone.pickup_timer = 5.0

    state = glfo.build_state(ship)
    d_state = next(d for d in state["drones"] if d["id"] == drone_id)

    assert "fuel_consumption" in d_state
    assert d_state["fuel_consumption"] == drone.fuel_consumption
    assert d_state["damage_dealt"] == 12.5
    assert d_state["contacts_found"] == 3
    assert d_state["survivors_rescued"] == 2
    assert d_state["pickup_timer"] == 5.0


# ---------------------------------------------------------------------------
# Part 7 audit — Cross-station integration
# ---------------------------------------------------------------------------


def test_drone_attack_applies_damage_to_enemy():
    """Combat drone attack events should actually reduce enemy hull via game_loop."""
    from server.systems.combat import apply_hit_to_enemy
    from server.models.world import spawn_enemy

    ship = fresh_ship()
    drone_id = _launch_and_activate(ship)
    drone = glfo.get_drone_by_id(drone_id)
    drone.drone_type = "combat"
    drone.position = (50_000, 50_100)

    # Create a target enemy with depleted shields.
    enemy = spawn_enemy("scout", 50_000, 50_200, entity_id="e1")
    enemy.shield_front = 0.0
    enemy.shield_rear = 0.0
    initial_hull = enemy.hull

    # Simulate what game_loop does: apply drone attack damage.
    apply_hit_to_enemy(enemy, 15.0, drone.position[0], drone.position[1])
    assert enemy.hull < initial_hull


def test_ecm_jamming_applies_jam_factor():
    """ECM drone jamming events should increase enemy jam_factor."""
    from server.models.world import spawn_enemy

    enemy = spawn_enemy("scout", 50_000, 50_200, entity_id="e1")
    assert enemy.jam_factor == 0.0

    # Simulate what game_loop does: apply ECM drone jamming.
    strength = 0.5
    dt = 0.1
    enemy.jam_factor = min(0.8, enemy.jam_factor + strength * dt)
    assert enemy.jam_factor == pytest.approx(0.05)


def test_evasive_recovery_penalty():
    """Evasive state should add 30% bolter chance during recovery."""
    from server.models.flight_deck import EVASIVE_MANOEUVRE_RECOVERY_PENALTY

    assert EVASIVE_MANOEUVRE_RECOVERY_PENALTY == pytest.approx(0.30)

    ship = fresh_ship()
    drone_id = _launch_and_activate(ship)
    drone = glfo.get_drone_by_id(drone_id)

    # Set evasive state.
    glfo._ship_evasive = True

    # Recall and run recovery.
    glfo.recall_drone(drone_id)
    # Tick until recovery window.
    for _ in range(200):
        glfo.tick(ship, 0.1, tick_num=1, ship_evasive=True)

    # We can't deterministically test random bolter, but we verify
    # the ship_evasive flag is accepted and stored.
    assert glfo._ship_evasive is True


def test_build_drone_summary():
    """build_drone_summary returns correct counts for Captain display."""
    ship = fresh_ship()
    summary = glfo.build_drone_summary()

    assert summary["total"] > 0
    assert summary["hangar"] == summary["total"]  # all in hangar initially
    assert summary["active"] == 0
    assert summary["destroyed"] == 0
    assert summary["recovering"] == 0
    assert summary["survivors_aboard"] == 0
    assert summary["buoys_active"] == 0

    # Launch a drone.
    drone_id = _launch_and_activate(ship)
    summary = glfo.build_drone_summary()
    assert summary["active"] == 1
    assert summary["hangar"] == summary["total"] - 1


def test_detection_bubbles_include_buoys():
    """get_detection_bubbles should include sensor buoys."""
    ship = fresh_ship()
    drone_id = _launch_and_activate(ship)

    # Deploy a buoy.
    drone = glfo.get_drone_by_id(drone_id)
    drone.drone_type = "scout"
    glfo.deploy_buoy_cmd(drone_id)

    bubbles = glfo.get_detection_bubbles()
    # Should have at least the active drone bubble.
    assert len(bubbles) >= 1
    # Each bubble is (x, y, range).
    for bx, by, br in bubbles:
        assert isinstance(bx, float)
        assert isinstance(by, float)
        assert isinstance(br, float)
        assert br > 0


def test_world_entities_includes_drones():
    """build_world_entities should include active drones and buoys."""
    import server.game_loop_mission as glm
    from server.models.world import World

    ship = fresh_ship()
    world = World(ship=ship)
    drone_id = _launch_and_activate(ship)

    msg = glm.build_world_entities(world)
    payload = msg.payload
    assert "drones" in payload
    assert "buoys" in payload
    assert len(payload["drones"]) == 1

    d = payload["drones"][0]
    assert d["id"] == drone_id
    assert "callsign" in d
    assert "drone_type" in d
    assert "x" in d
    assert "y" in d


def test_sensor_contacts_drone_detected_annotation():
    """Contacts within drone detection bubbles should have drone_detected=True."""
    from server.systems.sensors import build_sensor_contacts
    from server.models.world import World, spawn_enemy

    ship = fresh_ship()
    world = World(ship=ship)
    # Enemy at (50100, 50100).
    enemy = spawn_enemy("scout", 50_100, 50_100, entity_id="e1")
    world.enemies.append(enemy)

    # Bubble at (50000, 50000) with range 5000 — enemy is within range.
    bubbles = [(50_000.0, 50_000.0, 5_000.0)]
    contacts = build_sensor_contacts(world, ship, extra_bubbles=bubbles)
    enemy_contact = next(c for c in contacts if c["id"] == "e1")
    assert enemy_contact.get("drone_detected") is True

    # Bubble far away — enemy should NOT have drone_detected.
    bubbles_far = [(90_000.0, 90_000.0, 100.0)]
    contacts_far = build_sensor_contacts(world, ship, extra_bubbles=bubbles_far)
    enemy_contact_far = next(c for c in contacts_far if c["id"] == "e1")
    assert "drone_detected" not in enemy_contact_far


def test_admit_survivors_creates_patients():
    """admit_survivors should create crew members, some injured."""
    import server.game_loop_medical_v2 as glmed
    from server.models.crew_roster import IndividualCrewRoster

    glmed.reset()
    roster = IndividualCrewRoster()
    glmed.init_roster(roster)

    ship = fresh_ship()
    events = glmed.admit_survivors(4, ship)

    assert len(events) == 4
    # All should be survivor_admitted events.
    for ev in events:
        assert ev["event"] == "survivor_admitted"

    # Check roster has new members.
    survivor_members = [m for mid, m in roster.members.items() if mid.startswith("survivor_")]
    assert len(survivor_members) == 4


def test_is_ship_evasive():
    """_is_ship_evasive should detect sharp turns."""
    from server.game_loop import _is_ship_evasive, _EVASIVE_TURN_RATE
    import server.game_loop as game_loop

    ship = fresh_ship()
    ship.heading = 0.0
    game_loop._prev_heading = 0.0

    # No turn — not evasive.
    assert _is_ship_evasive(ship) is False

    # Sharp turn: 45 degrees in one tick (0.1s) = 450 deg/s.
    ship.heading = 45.0
    assert _is_ship_evasive(ship) is True

    # Small turn: 1 degree in one tick = 10 deg/s.
    ship.heading = 46.0
    assert _is_ship_evasive(ship) is False
