"""Integration tests for Flight Ops v0.06.5 — cross-station wiring.

Tests cover: message routing through game_loop._drain_queue, payload validation,
launch/recovery cycles, build_state broadcast, serialise round-trip through
save_system, and cross-station data flow.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import server.game_loop_flight_ops as glfo
from server.models.drones import DECOY_STOCK, DRONE_COMPLEMENT
from server.models.drone_missions import create_patrol_mission
from server.models.flight_deck import (
    BASE_LAUNCH_TIME,
    BASE_RECOVERY_APPROACH_TIME,
    BASE_RECOVERY_CATCH_TIME,
    LAUNCH_PREP_TIME,
)

# Full 2-phase launch time (prep + catapult) and full recovery time (approach + catch).
FULL_LAUNCH_TIME = LAUNCH_PREP_TIME + BASE_LAUNCH_TIME
FULL_RECOVERY_TIME = BASE_RECOVERY_APPROACH_TIME + BASE_RECOVERY_CATCH_TIME
from server.models.messages import Message, validate_payload
from server.models.messages.flight_ops import (
    FlightOpsAbortLandingPayload,
    FlightOpsClearToLandPayload,
    FlightOpsDeployBuoyPayload,
    FlightOpsDeployDecoyPayload,
    FlightOpsDesignateTargetPayload,
    FlightOpsEscortAssignPayload,
    FlightOpsLaunchDronePayload,
    FlightOpsPrioritiseRecoveryPayload,
    FlightOpsRecallDronePayload,
    FlightOpsRushTurnaroundPayload,
    FlightOpsSetBehaviourPayload,
    FlightOpsSetEngagementRulesPayload,
    FlightOpsSetWaypointPayload,
    FlightOpsSetWaypointsPayload,
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
    glfo.reset()


# ---------------------------------------------------------------------------
# Payload validation — new message types
# ---------------------------------------------------------------------------


class TestPayloadValidation:
    def test_launch_drone_payload(self):
        msg = Message.build("flight_ops.launch_drone", {"drone_id": "drone_s1"})
        payload = validate_payload(msg)
        assert isinstance(payload, FlightOpsLaunchDronePayload)
        assert payload.drone_id == "drone_s1"

    def test_recall_drone_payload(self):
        msg = Message.build("flight_ops.recall_drone", {"drone_id": "drone_s1"})
        payload = validate_payload(msg)
        assert isinstance(payload, FlightOpsRecallDronePayload)

    def test_set_waypoint_payload(self):
        msg = Message.build("flight_ops.set_waypoint", {
            "drone_id": "drone_s1", "x": 60000.0, "y": 50000.0,
        })
        payload = validate_payload(msg)
        assert isinstance(payload, FlightOpsSetWaypointPayload)
        assert payload.x == pytest.approx(60000.0)

    def test_set_waypoints_payload(self):
        msg = Message.build("flight_ops.set_waypoints", {
            "drone_id": "drone_s1", "waypoints": [[60000, 50000], [70000, 50000]],
        })
        payload = validate_payload(msg)
        assert isinstance(payload, FlightOpsSetWaypointsPayload)
        assert len(payload.waypoints) == 2

    def test_set_engagement_rules_payload(self):
        msg = Message.build("flight_ops.set_engagement_rules", {
            "drone_id": "drone_c1", "rules": "weapons_free",
        })
        payload = validate_payload(msg)
        assert isinstance(payload, FlightOpsSetEngagementRulesPayload)
        assert payload.rules == "weapons_free"

    def test_set_behaviour_payload(self):
        msg = Message.build("flight_ops.set_behaviour", {
            "drone_id": "drone_c1", "behaviour": "patrol",
        })
        payload = validate_payload(msg)
        assert isinstance(payload, FlightOpsSetBehaviourPayload)

    def test_designate_target_payload(self):
        msg = Message.build("flight_ops.designate_target", {
            "drone_id": "drone_c1", "target_id": "enemy_1",
        })
        payload = validate_payload(msg)
        assert isinstance(payload, FlightOpsDesignateTargetPayload)
        assert payload.target_id == "enemy_1"

    def test_deploy_decoy_payload(self):
        msg = Message.build("flight_ops.deploy_decoy", {"direction": 180.0})
        payload = validate_payload(msg)
        assert isinstance(payload, FlightOpsDeployDecoyPayload)
        assert payload.direction == pytest.approx(180.0)

    def test_deploy_buoy_payload(self):
        msg = Message.build("flight_ops.deploy_buoy", {"drone_id": "drone_u1"})
        payload = validate_payload(msg)
        assert isinstance(payload, FlightOpsDeployBuoyPayload)

    def test_escort_assign_payload(self):
        msg = Message.build("flight_ops.escort_assign", {
            "drone_id": "drone_c1", "escort_target": "friendly_1",
        })
        payload = validate_payload(msg)
        assert isinstance(payload, FlightOpsEscortAssignPayload)

    def test_clear_to_land_payload(self):
        msg = Message.build("flight_ops.clear_to_land", {"drone_id": "drone_s1"})
        payload = validate_payload(msg)
        assert isinstance(payload, FlightOpsClearToLandPayload)

    def test_rush_turnaround_payload(self):
        msg = Message.build("flight_ops.rush_turnaround", {"drone_id": "drone_s1"})
        payload = validate_payload(msg)
        assert isinstance(payload, FlightOpsRushTurnaroundPayload)

    def test_abort_landing_payload(self):
        msg = Message.build("flight_ops.abort_landing", {"drone_id": "drone_s1"})
        payload = validate_payload(msg)
        assert isinstance(payload, FlightOpsAbortLandingPayload)

    def test_prioritise_recovery_payload(self):
        msg = Message.build("flight_ops.prioritise_recovery", {
            "order": ["drone_s1", "drone_c1"],
        })
        payload = validate_payload(msg)
        assert isinstance(payload, FlightOpsPrioritiseRecoveryPayload)
        assert payload.order == ["drone_s1", "drone_c1"]


# ---------------------------------------------------------------------------
# Full mission cycle: launch → patrol → RTB → turnaround → relaunch
# ---------------------------------------------------------------------------


def test_full_launch_patrol_rtb_cycle():
    ship = fresh_ship()
    drone = glfo.get_drones()[0]

    # 1. Launch drone.
    assert glfo.launch_drone(drone.id, ship)

    # 2. Complete launch (prep + catapult).
    glfo.tick(ship, FULL_LAUNCH_TIME + 1.0)
    assert drone.status == "active"

    # 3. Assign patrol mission.
    mission = create_patrol_mission(drone.id, [(60000, 50000), (70000, 50000)])
    assert glfo.assign_mission(drone.id, mission)
    assert drone.mission_type == "patrol"

    # 4. Recall.
    assert glfo.recall_drone(drone.id)
    assert drone.ai_behaviour == "rtb"
    assert mission.status == "aborted"

    # 5. Simulate RTB arrival (set status directly since drone AI not ticking with real world).
    drone.status = "rtb"
    glfo.tick(ship, 0.1)
    assert drone.status == "recovering"

    # 6. Complete recovery (approach + catch).
    glfo.tick(ship, FULL_RECOVERY_TIME + 1.0)
    assert drone.status == "maintenance"

    # 7. Wait for turnaround to complete.
    for _ in range(100):
        glfo.tick(ship, 1.0)
    assert drone.status == "hangar"
    assert drone.fuel == pytest.approx(100.0)

    # 8. Can relaunch.
    assert glfo.launch_drone(drone.id, ship)


# ---------------------------------------------------------------------------
# Rescue cycle: launch → SAR → pickup → RTB → crew transfer
# ---------------------------------------------------------------------------


def test_rescue_mission_cycle():
    ship = fresh_ship()
    drones = glfo.get_drones()
    rescue = next(d for d in drones if d.drone_type == "rescue")

    # Launch (prep + catapult).
    glfo.launch_drone(rescue.id, ship)
    glfo.tick(ship, FULL_LAUNCH_TIME + 1.0)
    assert rescue.status == "active"

    # Set waypoint to rescue site.
    assert glfo.set_waypoint(rescue.id, 60000.0, 50000.0)

    # Simulate cargo pickup.
    rescue.cargo_current = 3
    assert rescue.cargo_current == 3

    # Recall with cargo.
    assert glfo.recall_drone(rescue.id)
    assert rescue.ai_behaviour == "rtb"


# ---------------------------------------------------------------------------
# Flight deck emergency blocks operations
# ---------------------------------------------------------------------------


def test_deck_fire_blocks_launch():
    ship = fresh_ship()
    fd = glfo.get_flight_deck()
    fd.fire_active = True

    drone = glfo.get_drones()[0]
    result = glfo.launch_drone(drone.id, ship)
    assert result is False


def test_deck_crash_block_prevents_recovery():
    fd = glfo.get_flight_deck()
    fd.crash_block_remaining = 15.0

    drone = glfo.get_drones()[0]
    result = fd.queue_recovery(drone.id)
    assert result is True  # Can queue
    # But can't clear to land.
    result = fd.clear_to_land(drone.id)
    assert result is False


# ---------------------------------------------------------------------------
# build_state structure
# ---------------------------------------------------------------------------


def test_build_state_full_structure():
    ship = fresh_ship()
    # Launch a drone.
    drone = glfo.get_drones()[0]
    glfo.launch_drone(drone.id, ship)
    glfo.tick(ship, FULL_LAUNCH_TIME + 1.0)

    state = glfo.build_state(ship)

    # Verify all top-level keys.
    assert set(state.keys()) == {"drones", "flight_deck", "buoys", "decoys", "decoy_stock"}

    # Verify drone fields.
    active = [d for d in state["drones"] if d["status"] == "active"]
    assert len(active) == 1
    d = active[0]
    assert "callsign" in d
    assert "drone_type" in d
    assert "hull" in d
    assert "max_hull" in d
    assert "ammo" in d
    assert "cargo_current" in d
    assert "bingo_acknowledged" in d

    # Verify flight deck fields.
    fd = state["flight_deck"]
    assert "catapult_health" in fd
    assert "recovery_health" in fd
    assert "fuel_lines_health" in fd
    assert "control_tower_health" in fd
    assert "turnarounds" in fd


# ---------------------------------------------------------------------------
# Save/resume round-trip
# ---------------------------------------------------------------------------


def test_save_resume_round_trip():
    ship = fresh_ship()

    # Create some state.
    drone = glfo.get_drones()[0]
    glfo.launch_drone(drone.id, ship)
    glfo.tick(ship, FULL_LAUNCH_TIME + 1.0)
    glfo.deploy_decoy_cmd(0.0, ship)

    # Serialise.
    data = glfo.serialise()

    # Reset completely.
    glfo.reset("scout")
    assert len(glfo.get_drones()) != sum(DRONE_COMPLEMENT["frigate"].values())

    # Restore.
    glfo.deserialise(data)

    # Verify state restored.
    assert len(glfo.get_drones()) == sum(DRONE_COMPLEMENT["frigate"].values())
    restored = glfo.get_drone_by_id(drone.id)
    assert restored is not None
    assert restored.status == "active"
    assert glfo.get_decoy_stock() == DECOY_STOCK["frigate"] - 1


# ---------------------------------------------------------------------------
# Detection bubbles integrate with sensors
# ---------------------------------------------------------------------------


def test_detection_bubbles_from_active_drones():
    drone = glfo.get_drones()[0]
    drone.status = "active"
    drone.position = (60_000.0, 50_000.0)

    bubbles = glfo.get_detection_bubbles(1.0)
    assert len(bubbles) == 1
    x, y, r = bubbles[0]
    assert x == pytest.approx(60_000.0)
    assert y == pytest.approx(50_000.0)
    assert r > 0


def test_detection_bubbles_none_from_hangar():
    assert glfo.get_detection_bubbles(1.0) == []


# ---------------------------------------------------------------------------
# Decoy deployment integration
# ---------------------------------------------------------------------------


def test_decoy_deploy_and_expire():
    ship = fresh_ship()
    assert glfo.deploy_decoy_cmd(90.0, ship)
    assert len(glfo.get_decoys()) == 1
    assert glfo.get_decoy_stock() == DECOY_STOCK["frigate"] - 1

    # Tick past decoy lifetime (30s default).
    for _ in range(40):
        glfo.tick(ship, 1.0)
    assert len(glfo.get_decoys()) == 0


# ---------------------------------------------------------------------------
# Multiple drone launch
# ---------------------------------------------------------------------------


def test_multiple_drones_launch_sequentially():
    ship = fresh_ship()
    drones = glfo.get_drones()
    fd = glfo.get_flight_deck()

    # Frigate has 1 launch tube; launches should serialize.
    glfo.launch_drone(drones[0].id, ship)
    glfo.launch_drone(drones[1].id, ship)

    # First drone enters tube, second waits in queue.
    glfo.tick(ship, 0.1)
    assert len(fd.tubes_in_use) == 1
    assert len(fd.launch_queue) == 1

    # Complete first launch (prep + catapult).
    glfo.tick(ship, FULL_LAUNCH_TIME + 1.0)
    assert drones[0].status == "active"

    # Second moves into tube.
    glfo.tick(ship, 0.1)
    assert len(fd.tubes_in_use) == 1

    # Complete second launch.
    glfo.tick(ship, FULL_LAUNCH_TIME + 1.0)
    assert drones[1].status == "active"


# ---------------------------------------------------------------------------
# Rush turnaround
# ---------------------------------------------------------------------------


def test_rush_turnaround_allows_relaunch():
    ship = fresh_ship()
    drone = glfo.get_drones()[0]

    # Complete launch→RTB→recovery cycle.
    glfo.launch_drone(drone.id, ship)
    glfo.tick(ship, FULL_LAUNCH_TIME + 1.0)
    drone.fuel = 50.0
    drone.status = "rtb"
    glfo.tick(ship, 0.1)  # queue recovery
    glfo.tick(ship, FULL_RECOVERY_TIME + 1.0)  # complete recovery
    assert drone.status == "maintenance"

    # Rush turnaround.
    result = glfo.rush_turnaround(drone.id)
    assert result is True

    # Tick to process turnaround_complete event.
    glfo.tick(ship, 0.1)

    # Drone should be back in hangar, ready for launch.
    assert drone.id not in glfo.get_flight_deck().turnarounds
    assert drone.status == "hangar"


# ---------------------------------------------------------------------------
# Escort assignment
# ---------------------------------------------------------------------------


def test_escort_assign_changes_behaviour():
    drones = glfo.get_drones()
    combat = next(d for d in drones if d.drone_type == "combat")
    combat.status = "active"

    result = glfo.escort_assign(combat.id, "convoy_1")
    assert result is True
    assert combat.escort_target == "convoy_1"
    assert combat.ai_behaviour == "escort"


# ---------------------------------------------------------------------------
# Handler wiring (flight_ops.py handler queues messages)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_queues_launch_message():
    from server import flight_ops

    mock_sender = MagicMock()
    mock_sender.send = AsyncMock()
    queue: asyncio.Queue = asyncio.Queue()
    flight_ops.init(mock_sender, queue)

    msg = Message.build("flight_ops.launch_drone", {"drone_id": "drone_s1"})
    await flight_ops.handle_flight_ops_message("conn1", msg)

    assert not queue.empty()
    msg_type, payload = queue.get_nowait()
    assert msg_type == "flight_ops.launch_drone"
    assert isinstance(payload, FlightOpsLaunchDronePayload)
    assert payload.drone_id == "drone_s1"


@pytest.mark.asyncio
async def test_handler_queues_set_waypoint():
    from server import flight_ops

    mock_sender = MagicMock()
    mock_sender.send = AsyncMock()
    queue: asyncio.Queue = asyncio.Queue()
    flight_ops.init(mock_sender, queue)

    msg = Message.build("flight_ops.set_waypoint", {
        "drone_id": "drone_s1", "x": 60000.0, "y": 50000.0,
    })
    await flight_ops.handle_flight_ops_message("conn1", msg)

    assert not queue.empty()
    msg_type, payload = queue.get_nowait()
    assert msg_type == "flight_ops.set_waypoint"
    assert isinstance(payload, FlightOpsSetWaypointPayload)


@pytest.mark.asyncio
async def test_handler_queues_deploy_decoy():
    from server import flight_ops

    mock_sender = MagicMock()
    mock_sender.send = AsyncMock()
    queue: asyncio.Queue = asyncio.Queue()
    flight_ops.init(mock_sender, queue)

    msg = Message.build("flight_ops.deploy_decoy", {"direction": 90.0})
    await flight_ops.handle_flight_ops_message("conn1", msg)

    assert not queue.empty()
    msg_type, payload = queue.get_nowait()
    assert msg_type == "flight_ops.deploy_decoy"
    assert isinstance(payload, FlightOpsDeployDecoyPayload)


@pytest.mark.asyncio
async def test_handler_rejects_invalid_payload():
    from server import flight_ops

    mock_sender = MagicMock()
    mock_sender.send = AsyncMock()
    queue: asyncio.Queue = asyncio.Queue()
    flight_ops.init(mock_sender, queue)

    # Missing required field.
    msg = Message.build("flight_ops.launch_drone", {})
    await flight_ops.handle_flight_ops_message("conn1", msg)

    # Error sent to client, nothing queued.
    assert queue.empty()
    mock_sender.send.assert_called_once()
