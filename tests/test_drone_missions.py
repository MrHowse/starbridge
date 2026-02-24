"""Tests for server/models/drone_missions.py — v0.06.5 drone mission models."""
from __future__ import annotations

import pytest

from server.models.drone_missions import (
    ATTACK_BREAK_DISTANCE,
    MISSION_STATUSES,
    MISSION_TYPES,
    PATROL_LOITER_TIME,
    SAR_PICKUP_TIME,
    SURVEY_DATA_RATE,
    SURVEY_LOITER_TIME,
    WAYPOINT_ARRIVAL_DIST,
    DroneMission,
    DroneMissionObjective,
    DroneMissionWaypoint,
    add_waypoint,
    create_attack_run_mission,
    create_buoy_deployment_mission,
    create_escort_mission,
    create_ew_mission,
    create_patrol_mission,
    create_sar_mission,
    create_survey_mission,
    deserialise_mission,
    estimate_fuel_for_route,
    remove_waypoint,
    reset_mission_counter,
    serialise_mission,
    update_objective_progress,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def setup_function():
    reset_mission_counter()


# ---------------------------------------------------------------------------
# Patrol mission
# ---------------------------------------------------------------------------


class TestPatrolMission:
    def test_creates_correct_type(self):
        m = create_patrol_mission("drone_s1", [(1000, 2000), (3000, 4000)])
        assert m.mission_type == "patrol"

    def test_waypoint_count(self):
        m = create_patrol_mission("drone_s1", [(1000, 2000), (3000, 4000), (5000, 6000)])
        assert len(m.waypoints) == 3

    def test_waypoints_are_loiter_type(self):
        m = create_patrol_mission("drone_s1", [(1000, 2000)])
        assert m.waypoints[0].waypoint_type == "loiter"

    def test_default_loiter_time(self):
        m = create_patrol_mission("drone_s1", [(1000, 2000)])
        assert m.waypoints[0].loiter_time == pytest.approx(PATROL_LOITER_TIME)

    def test_custom_loiter_time(self):
        m = create_patrol_mission("drone_s1", [(1000, 2000)], loiter_time=20.0)
        assert m.waypoints[0].loiter_time == pytest.approx(20.0)

    def test_has_patrol_objective(self):
        m = create_patrol_mission("drone_s1", [(1000, 2000)])
        assert len(m.objectives) == 1
        assert m.objectives[0].objective_type == "patrol"

    def test_starts_in_briefing(self):
        m = create_patrol_mission("drone_s1", [(1000, 2000)])
        assert m.status == "briefing"

    def test_circuit_completes_when_all_waypoints_done(self):
        m = create_patrol_mission("drone_s1", [(1000, 2000), (3000, 4000)])
        m.activate()
        assert m.advance_waypoint() is True  # move to wp 1
        assert m.advance_waypoint() is False  # route done
        assert m.route_complete is True
        assert m.all_waypoints_complete is True

    def test_contacts_accumulate(self):
        m = create_patrol_mission("drone_s1", [(1000, 2000)])
        m.contacts_found.append("enemy_1")
        m.contacts_found.append("enemy_2")
        assert len(m.contacts_found) == 2


# ---------------------------------------------------------------------------
# Escort mission
# ---------------------------------------------------------------------------


class TestEscortMission:
    def test_creates_correct_type(self):
        m = create_escort_mission("drone_c1", "ship", (50000, 50000))
        assert m.mission_type == "escort"

    def test_has_escort_objective(self):
        m = create_escort_mission("drone_c1", "ship", (50000, 50000))
        assert m.objectives[0].objective_type == "escort"
        assert m.objectives[0].target_id == "ship"

    def test_engagement_rules(self):
        m = create_escort_mission("drone_c1", "ship", (50000, 50000),
                                  engagement_rules="weapons_free")
        assert m.engagement_rules == "weapons_free"

    def test_default_engagement_rules(self):
        m = create_escort_mission("drone_c1", "ship", (50000, 50000))
        assert m.engagement_rules == "weapons_tight"

    def test_indefinite_loiter(self):
        m = create_escort_mission("drone_c1", "ship", (50000, 50000))
        assert m.waypoints[0].loiter_time is None


# ---------------------------------------------------------------------------
# Attack run mission
# ---------------------------------------------------------------------------


class TestAttackRunMission:
    def test_creates_correct_type(self):
        m = create_attack_run_mission("drone_c1", "enemy_1", (60000, 50000))
        assert m.mission_type == "attack_run"

    def test_has_attack_objective(self):
        m = create_attack_run_mission("drone_c1", "enemy_1", (60000, 50000))
        assert m.objectives[0].objective_type == "attack"
        assert m.objectives[0].target_id == "enemy_1"

    def test_approach_bearing(self):
        m = create_attack_run_mission("drone_c1", "enemy_1", (60000, 50000),
                                      approach_bearing=180.0)
        assert m.objectives[0].data["approach_bearing"] == pytest.approx(180.0)

    def test_default_weapons_free(self):
        m = create_attack_run_mission("drone_c1", "enemy_1", (60000, 50000))
        assert m.engagement_rules == "weapons_free"

    def test_damage_dealt_accumulates(self):
        m = create_attack_run_mission("drone_c1", "enemy_1", (60000, 50000))
        m.damage_dealt += 4.0
        m.damage_dealt += 4.0
        assert m.damage_dealt == pytest.approx(8.0)


# ---------------------------------------------------------------------------
# Search and rescue mission
# ---------------------------------------------------------------------------


class TestSARMission:
    def test_creates_correct_type(self):
        m = create_sar_mission("drone_r1", (40000, 40000))
        assert m.mission_type == "search_and_rescue"

    def test_has_rescue_objective(self):
        m = create_sar_mission("drone_r1", (40000, 40000), expected_survivors=4)
        assert m.objectives[0].objective_type == "rescue"
        assert m.objectives[0].data["expected_survivors"] == 4

    def test_pickup_waypoint(self):
        m = create_sar_mission("drone_r1", (40000, 40000))
        assert m.waypoints[0].waypoint_type == "pickup"

    def test_survivors_tracked(self):
        m = create_sar_mission("drone_r1", (40000, 40000))
        m.survivors_rescued = 3
        assert m.survivors_rescued == 3


# ---------------------------------------------------------------------------
# Survey mission
# ---------------------------------------------------------------------------


class TestSurveyMission:
    def test_creates_correct_type(self):
        m = create_survey_mission("drone_u1", (30000, 30000))
        assert m.mission_type == "survey"

    def test_default_loiter_time(self):
        m = create_survey_mission("drone_u1", (30000, 30000))
        assert m.waypoints[0].loiter_time == pytest.approx(SURVEY_LOITER_TIME)

    def test_has_survey_objective(self):
        m = create_survey_mission("drone_u1", (30000, 30000))
        assert m.objectives[0].objective_type == "survey"

    def test_with_buoy_deployment(self):
        m = create_survey_mission("drone_u1", (30000, 30000), deploy_buoy=True)
        assert len(m.waypoints) == 2
        assert m.waypoints[1].action == "deploy_buoy"
        assert len(m.objectives) == 2
        assert m.objectives[1].objective_type == "deploy_buoy"

    def test_without_buoy_deployment(self):
        m = create_survey_mission("drone_u1", (30000, 30000), deploy_buoy=False)
        assert len(m.waypoints) == 1
        assert len(m.objectives) == 1

    def test_data_collection(self):
        m = create_survey_mission("drone_u1", (30000, 30000))
        m.data_collected["hull_composition"] = "standard"
        m.data_collected["atmosphere"] = "none"
        assert len(m.data_collected) == 2


# ---------------------------------------------------------------------------
# Buoy deployment mission
# ---------------------------------------------------------------------------


class TestBuoyDeploymentMission:
    def test_creates_correct_type(self):
        m = create_buoy_deployment_mission("drone_u1", [(10000, 10000), (20000, 20000)])
        assert m.mission_type == "buoy_deployment"

    def test_waypoint_per_position(self):
        positions = [(10000, 10000), (20000, 20000), (30000, 30000)]
        m = create_buoy_deployment_mission("drone_u1", positions)
        assert len(m.waypoints) == 3
        for wp in m.waypoints:
            assert wp.waypoint_type == "deploy"

    def test_objective_per_position(self):
        positions = [(10000, 10000), (20000, 20000)]
        m = create_buoy_deployment_mission("drone_u1", positions)
        assert len(m.objectives) == 2
        for obj in m.objectives:
            assert obj.objective_type == "deploy_buoy"

    def test_buoys_deployed_counter(self):
        m = create_buoy_deployment_mission("drone_u1", [(10000, 10000)])
        m.buoys_deployed = 1
        assert m.buoys_deployed == 1


# ---------------------------------------------------------------------------
# Electronic warfare mission
# ---------------------------------------------------------------------------


class TestEWMission:
    def test_creates_correct_type(self):
        m = create_ew_mission("drone_e1", (45000, 45000))
        assert m.mission_type == "electronic_warfare"

    def test_has_jam_objective(self):
        m = create_ew_mission("drone_e1", (45000, 45000))
        assert m.objectives[0].objective_type == "jam"

    def test_loiter_at_jam_position(self):
        m = create_ew_mission("drone_e1", (45000, 45000))
        assert m.waypoints[0].waypoint_type == "loiter"
        assert m.waypoints[0].action == "jam"

    def test_custom_loiter_time(self):
        m = create_ew_mission("drone_e1", (45000, 45000), loiter_time=30.0)
        assert m.waypoints[0].loiter_time == pytest.approx(30.0)

    def test_indefinite_jam_by_default(self):
        m = create_ew_mission("drone_e1", (45000, 45000))
        assert m.waypoints[0].loiter_time is None


# ---------------------------------------------------------------------------
# Mission status lifecycle
# ---------------------------------------------------------------------------


class TestMissionLifecycle:
    def test_briefing_to_active(self):
        m = create_patrol_mission("d1", [(1000, 2000)])
        assert m.status == "briefing"
        m.activate(tick=100)
        assert m.status == "active"
        assert m.started_tick == 100
        assert m.is_active is True

    def test_active_to_complete(self):
        m = create_patrol_mission("d1", [(1000, 2000)])
        m.activate()
        m.complete()
        assert m.status == "complete"
        assert m.is_over is True
        assert m.is_active is False

    def test_abort(self):
        m = create_patrol_mission("d1", [(1000, 2000)])
        m.activate()
        m.abort()
        assert m.status == "aborted"
        assert m.is_over is True

    def test_fail(self):
        m = create_patrol_mission("d1", [(1000, 2000)])
        m.activate()
        m.fail()
        assert m.status == "failed"
        assert m.is_over is True


# ---------------------------------------------------------------------------
# Waypoint navigation
# ---------------------------------------------------------------------------


class TestWaypointNavigation:
    def test_current_wp(self):
        m = create_patrol_mission("d1", [(1000, 2000), (3000, 4000)])
        assert m.current_wp is not None
        assert m.current_wp.position == (1000, 2000)

    def test_advance_waypoint(self):
        m = create_patrol_mission("d1", [(1000, 2000), (3000, 4000)])
        assert m.advance_waypoint() is True
        assert m.current_wp.position == (3000, 4000)

    def test_advance_past_end(self):
        m = create_patrol_mission("d1", [(1000, 2000)])
        assert m.advance_waypoint() is False
        assert m.route_complete is True

    def test_current_wp_none_when_past_end(self):
        m = create_patrol_mission("d1", [(1000, 2000)])
        m.advance_waypoint()
        assert m.current_wp is None

    def test_all_waypoints_complete(self):
        m = create_patrol_mission("d1", [(1000, 2000), (3000, 4000)])
        m.waypoints[0].completed = True
        assert m.all_waypoints_complete is False
        m.waypoints[1].completed = True
        assert m.all_waypoints_complete is True


# ---------------------------------------------------------------------------
# Objective management
# ---------------------------------------------------------------------------


class TestObjectives:
    def test_complete_objective(self):
        m = create_patrol_mission("d1", [(1000, 2000)])
        obj_id = m.objectives[0].id
        assert m.complete_objective(obj_id) is True
        assert m.objectives[0].completed is True
        assert m.objectives[0].progress == pytest.approx(100.0)

    def test_complete_nonexistent_objective(self):
        m = create_patrol_mission("d1", [(1000, 2000)])
        assert m.complete_objective("nonexistent") is False

    def test_all_required_complete(self):
        m = create_survey_mission("d1", (1000, 2000), deploy_buoy=True)
        assert m.all_required_complete is False
        for obj in m.objectives:
            obj.completed = True
        assert m.all_required_complete is True

    def test_optional_objective_not_required(self):
        m = create_patrol_mission("d1", [(1000, 2000)])
        # Add an optional objective
        m.objectives.append(DroneMissionObjective(
            id="opt_1", description="Optional", objective_type="bonus",
            required=False,
        ))
        m.objectives[0].completed = True
        assert m.all_required_complete is True  # optional not blocking

    def test_objective_summary(self):
        m = create_buoy_deployment_mission("d1", [(1000, 2000), (3000, 4000)])
        assert m.objective_summary == "0/2"
        m.objectives[0].completed = True
        assert m.objective_summary == "1/2"

    def test_update_objective_progress(self):
        m = create_survey_mission("d1", (1000, 2000))
        obj_id = m.objectives[0].id
        assert update_objective_progress(m, obj_id, 50.0) is True
        assert m.objectives[0].progress == pytest.approx(50.0)
        assert m.objectives[0].completed is False

    def test_update_objective_progress_auto_completes(self):
        m = create_survey_mission("d1", (1000, 2000))
        obj_id = m.objectives[0].id
        assert update_objective_progress(m, obj_id, 100.0) is True
        assert m.objectives[0].completed is True

    def test_update_objective_progress_clamps(self):
        m = create_survey_mission("d1", (1000, 2000))
        obj_id = m.objectives[0].id
        update_objective_progress(m, obj_id, 150.0)
        assert m.objectives[0].progress == pytest.approx(100.0)

    def test_update_objective_progress_nonexistent(self):
        m = create_patrol_mission("d1", [(1000, 2000)])
        assert update_objective_progress(m, "nope", 50.0) is False


# ---------------------------------------------------------------------------
# Route modification
# ---------------------------------------------------------------------------


class TestRouteModification:
    def test_add_waypoint(self):
        m = create_patrol_mission("d1", [(1000, 2000)])
        add_waypoint(m, (5000, 6000), waypoint_type="loiter", loiter_time=15.0)
        assert len(m.waypoints) == 2
        assert m.waypoints[1].position == (5000, 6000)

    def test_remove_waypoint(self):
        m = create_patrol_mission("d1", [(1000, 2000), (3000, 4000), (5000, 6000)])
        assert remove_waypoint(m, 2) is True
        assert len(m.waypoints) == 2

    def test_remove_completed_waypoint_fails(self):
        m = create_patrol_mission("d1", [(1000, 2000), (3000, 4000)])
        m.waypoints[0].completed = True
        assert remove_waypoint(m, 0) is False

    def test_remove_out_of_range_fails(self):
        m = create_patrol_mission("d1", [(1000, 2000)])
        assert remove_waypoint(m, 5) is False

    def test_remove_adjusts_current_waypoint(self):
        m = create_patrol_mission("d1", [(1000, 2000), (3000, 4000), (5000, 6000)])
        m.current_waypoint = 2
        remove_waypoint(m, 1)  # remove wp before current
        assert m.current_waypoint == 1


# ---------------------------------------------------------------------------
# Fuel estimation
# ---------------------------------------------------------------------------


class TestFuelEstimation:
    def test_straight_line(self):
        result = estimate_fuel_for_route(
            waypoints=[(10000, 0)],
            start_position=(0, 0),
            max_speed=250.0,
            fuel_consumption=0.8,
        )
        # 10000 / 250 = 40 seconds; 40 * 0.8 = 32% fuel
        assert result["route_fuel"] == pytest.approx(32.0)
        assert result["return_fuel"] == pytest.approx(0.0)
        assert result["total_fuel"] == pytest.approx(32.0)
        assert result["reserve"] == pytest.approx(68.0)

    def test_with_return(self):
        result = estimate_fuel_for_route(
            waypoints=[(10000, 0)],
            start_position=(0, 0),
            max_speed=250.0,
            fuel_consumption=0.8,
            return_to=(0, 0),
        )
        # Route: 32%, Return: 32%, Total: 64%
        assert result["total_fuel"] == pytest.approx(64.0)
        assert result["reserve"] == pytest.approx(36.0)

    def test_multi_waypoint(self):
        result = estimate_fuel_for_route(
            waypoints=[(5000, 0), (5000, 5000)],
            start_position=(0, 0),
            max_speed=250.0,
            fuel_consumption=1.0,
        )
        # Leg 1: 5000/250 = 20s * 1.0 = 20%
        # Leg 2: 5000/250 = 20s * 1.0 = 20%
        assert result["route_fuel"] == pytest.approx(40.0)

    def test_impossible_route(self):
        result = estimate_fuel_for_route(
            waypoints=[(100000, 0), (100000, 100000)],
            start_position=(0, 0),
            max_speed=250.0,
            fuel_consumption=1.5,
            return_to=(0, 0),
        )
        assert result["reserve"] < 0  # not enough fuel

    def test_zero_speed(self):
        result = estimate_fuel_for_route(
            waypoints=[(10000, 0)],
            start_position=(0, 0),
            max_speed=0.0,
            fuel_consumption=0.8,
        )
        assert result["total_fuel"] == pytest.approx(0.0)

    def test_empty_route(self):
        result = estimate_fuel_for_route(
            waypoints=[],
            start_position=(0, 0),
            max_speed=250.0,
            fuel_consumption=0.8,
        )
        assert result["route_fuel"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Mission timeout
# ---------------------------------------------------------------------------


class TestMissionTimeout:
    def test_timeout_stored(self):
        m = create_patrol_mission("d1", [(1000, 2000)], timeout_tick=500)
        assert m.timeout_tick == 500

    def test_no_timeout(self):
        m = create_patrol_mission("d1", [(1000, 2000)])
        assert m.timeout_tick is None


# ---------------------------------------------------------------------------
# Unique mission IDs
# ---------------------------------------------------------------------------


class TestMissionIDs:
    def test_sequential_ids(self):
        m1 = create_patrol_mission("d1", [(1000, 2000)])
        m2 = create_patrol_mission("d1", [(3000, 4000)])
        assert m1.id != m2.id

    def test_reset_counter(self):
        reset_mission_counter()
        m1 = create_patrol_mission("d1", [(1000, 2000)])
        reset_mission_counter()
        m2 = create_patrol_mission("d1", [(1000, 2000)])
        assert m1.id == m2.id  # same ID after reset


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


class TestSerialisation:
    def test_mission_round_trip(self):
        m = create_patrol_mission("drone_s1", [(1000, 2000), (3000, 4000)])
        m.activate(tick=42)
        m.contacts_found.append("enemy_1")
        m.waypoints[0].completed = True
        m.current_waypoint = 1

        data = serialise_mission(m)
        restored = deserialise_mission(data)

        assert restored.id == m.id
        assert restored.drone_id == m.drone_id
        assert restored.mission_type == "patrol"
        assert restored.status == "active"
        assert restored.started_tick == 42
        assert restored.current_waypoint == 1
        assert len(restored.waypoints) == 2
        assert restored.waypoints[0].completed is True
        assert restored.waypoints[1].completed is False
        assert len(restored.contacts_found) == 1
        assert len(restored.objectives) == 1

    def test_attack_mission_round_trip(self):
        m = create_attack_run_mission("drone_c1", "enemy_1", (60000, 50000),
                                       approach_bearing=90.0)
        m.damage_dealt = 12.5
        data = serialise_mission(m)
        restored = deserialise_mission(data)
        assert restored.damage_dealt == pytest.approx(12.5)
        assert restored.objectives[0].data["approach_bearing"] == pytest.approx(90.0)

    def test_sar_mission_round_trip(self):
        m = create_sar_mission("drone_r1", (40000, 40000), expected_survivors=6)
        m.survivors_rescued = 4
        data = serialise_mission(m)
        restored = deserialise_mission(data)
        assert restored.survivors_rescued == 4
        assert restored.objectives[0].data["expected_survivors"] == 6

    def test_buoy_mission_round_trip(self):
        m = create_buoy_deployment_mission("drone_u1", [(1000, 2000), (3000, 4000)])
        m.buoys_deployed = 1
        data = serialise_mission(m)
        restored = deserialise_mission(data)
        assert restored.buoys_deployed == 1
        assert len(restored.objectives) == 2
