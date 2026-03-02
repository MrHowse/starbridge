"""
Tests for v0.03m — Training Missions.

Covers:
  - Mission engine: training_flag trigger + set_training_flag + get_active_objective_index
  - game_loop_training: init, auto-simulation, hint tracking
  - Integration: training flag set from game loop drain_queue analogue
"""
from __future__ import annotations

import pytest

from server.missions.engine import MissionEngine
from server.models.ship import Ship
from server.models.world import World
import server.game_loop_training as gltr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ship(x: float = 50_000.0, y: float = 50_000.0, **kwargs) -> Ship:
    ship = Ship()
    ship.x = x
    ship.y = y
    for k, v in kwargs.items():
        setattr(ship, k, v)
    return ship


def make_world(ship: Ship | None = None) -> World:
    if ship is None:
        ship = make_ship()
    return World(ship=ship, width=100_000.0, height=100_000.0)


def make_training_mission(target_role: str = "helm") -> dict:
    return {
        "id": f"train_{target_role}",
        "name": f"{target_role.title()} Training",
        "is_training": True,
        "target_role": target_role,
        "auto_roles": ["helm", "engineering"],
        "objectives": [
            {
                "id": "obj_1",
                "text": "Do thing 1",
                "hint": "This is how you do thing 1.",
                "trigger": "training_flag",
                "args": {"flag": "action_a"},
            },
            {
                "id": "obj_2",
                "text": "Do thing 2",
                "hint": "Now do thing 2 like this.",
                "trigger": "training_flag",
                "args": {"flag": "action_b"},
            },
            {
                "id": "obj_3",
                "text": "Wait 5 seconds",
                "trigger": "timer_elapsed",
                "args": {"seconds": 5},
            },
        ],
        "victory_condition": "all_objectives_complete",
        "defeat_condition": "player_hull_zero",
    }


# ---------------------------------------------------------------------------
# Mission engine: training_flag trigger
# ---------------------------------------------------------------------------


class TestMissionEngineTrainingFlag:
    def test_training_flag_not_set_returns_false(self):
        mission = make_training_mission()
        engine = MissionEngine(mission)
        world = make_world()
        ship = make_ship()
        # Objective 0 requires "action_a" flag — not set yet, should not complete.
        result = engine.tick(world, ship, dt=0.1)
        assert result == []

    def test_training_flag_set_completes_objective(self):
        mission = make_training_mission()
        engine = MissionEngine(mission)
        world = make_world()
        ship = make_ship()
        engine.set_training_flag("action_a")
        result = engine.tick(world, ship, dt=0.1)
        assert "obj_1" in result

    def test_training_flag_wrong_flag_does_not_complete(self):
        mission = make_training_mission()
        engine = MissionEngine(mission)
        world = make_world()
        ship = make_ship()
        engine.set_training_flag("wrong_flag")
        result = engine.tick(world, ship, dt=0.1)
        assert result == []

    def test_sequential_flags_advance_objectives(self):
        mission = make_training_mission()
        engine = MissionEngine(mission)
        world = make_world()
        ship = make_ship()

        # Complete obj_1
        engine.set_training_flag("action_a")
        r1 = engine.tick(world, ship, dt=0.1)
        assert "obj_1" in r1

        # Complete obj_2
        engine.set_training_flag("action_b")
        r2 = engine.tick(world, ship, dt=0.1)
        assert "obj_2" in r2

    def test_flag_persists_across_ticks(self):
        mission = make_training_mission()
        engine = MissionEngine(mission)
        world = make_world()
        ship = make_ship()

        engine.set_training_flag("action_a")
        engine.tick(world, ship, dt=0.1)  # completes obj_1

        # Flag persists — setting action_b completes obj_2 next tick
        engine.set_training_flag("action_b")
        r2 = engine.tick(world, ship, dt=0.1)
        assert "obj_2" in r2

    def test_timer_elapsed_still_works_in_training_mission(self):
        mission = make_training_mission()
        engine = MissionEngine(mission)
        world = make_world()
        ship = make_ship()

        # Advance past first two objectives
        engine.set_training_flag("action_a")
        engine.tick(world, ship, dt=0.1)
        engine.set_training_flag("action_b")
        engine.tick(world, ship, dt=0.1)

        # Obj_3 uses timer_elapsed (5 seconds)
        r = engine.tick(world, ship, dt=6.0)
        assert "obj_3" in r

    def test_full_training_mission_ends_in_victory(self):
        mission = make_training_mission()
        engine = MissionEngine(mission)
        world = make_world()
        ship = make_ship()

        engine.set_training_flag("action_a")
        engine.tick(world, ship, dt=0.1)
        engine.set_training_flag("action_b")
        engine.tick(world, ship, dt=0.1)
        engine.tick(world, ship, dt=6.0)  # timer obj

        over, result = engine.is_over()
        assert over is True
        assert result == "victory"


# ---------------------------------------------------------------------------
# Mission engine: get_active_objective_index
# ---------------------------------------------------------------------------


class TestGetActiveObjectiveIndex:
    def test_starts_at_zero(self):
        mission = make_training_mission()
        engine = MissionEngine(mission)
        assert engine.get_active_objective_index() == 0

    def test_advances_on_completion(self):
        mission = make_training_mission()
        engine = MissionEngine(mission)
        world = make_world()
        ship = make_ship()

        engine.set_training_flag("action_a")
        engine.tick(world, ship, dt=0.1)
        assert engine.get_active_objective_index() == 1

    def test_at_end_equals_len(self):
        mission = make_training_mission()
        engine = MissionEngine(mission)
        world = make_world()
        ship = make_ship()

        engine.set_training_flag("action_a")
        engine.tick(world, ship, dt=0.1)
        engine.set_training_flag("action_b")
        engine.tick(world, ship, dt=0.1)
        engine.tick(world, ship, dt=6.0)

        # All objectives done — index equals len(objectives)
        assert engine.get_active_objective_index() == 3


# ---------------------------------------------------------------------------
# game_loop_training module
# ---------------------------------------------------------------------------


class TestGltrReset:
    def test_reset_clears_state(self):
        gltr.reset()
        assert gltr.is_training_active() is False
        assert gltr.get_target_role() == ""
        assert gltr.get_hint_for_idx(0) is None
        assert gltr.get_last_hint_idx() == -1

    def test_init_with_non_training_mission_stays_inactive(self):
        gltr.reset()
        gltr.init_training({"id": "sandbox"})
        assert gltr.is_training_active() is False


class TestGltrInitTraining:
    def setup_method(self):
        gltr.reset()

    def test_activates_on_is_training(self):
        mission = make_training_mission("helm")
        gltr.init_training(mission)
        assert gltr.is_training_active() is True

    def test_target_role_extracted(self):
        gltr.init_training(make_training_mission("weapons"))
        assert gltr.get_target_role() == "weapons"

    def test_hints_parsed_by_index(self):
        mission = make_training_mission("science")
        gltr.init_training(mission)
        assert gltr.get_hint_for_idx(0) == "This is how you do thing 1."
        assert gltr.get_hint_for_idx(1) == "Now do thing 2 like this."
        assert gltr.get_hint_for_idx(2) is None   # timer obj has no hint

    def test_hint_for_missing_index_returns_none(self):
        gltr.init_training(make_training_mission())
        assert gltr.get_hint_for_idx(99) is None

    def test_auto_helm_disabled_when_target_is_helm(self):
        mission = make_training_mission("helm")
        mission["auto_roles"] = ["helm", "engineering"]
        gltr.init_training(mission)
        # auto_helm should be disabled because target IS helm
        ship = make_ship(x=10_000.0, y=10_000.0, throttle=0.0)
        gltr.auto_helm_tick(ship, dt=0.5)
        # Ship should NOT be steered (auto_helm disabled for helm trainee)
        assert ship.target_heading == 0.0  # unchanged

    def test_auto_engineering_disabled_when_target_is_engineering(self):
        mission = make_training_mission("engineering")
        mission["auto_roles"] = ["helm", "engineering"]
        gltr.init_training(mission)
        ship = make_ship()
        ship.systems["engines"].power = 0.0
        gltr.auto_engineering_tick(ship, dt=0.5)
        # power should NOT be restored (auto_eng disabled for engineering trainee)
        assert ship.systems["engines"].power == 0.0


class TestAutoHelmTick:
    def setup_method(self):
        gltr.reset()

    def test_steers_toward_sector_centre(self):
        mission = make_training_mission("weapons")  # helm is auto-simulated
        gltr.init_training(mission)

        # Ship at north edge — sector centre is south.
        ship = make_ship(x=50_000.0, y=10_000.0, throttle=0.0)
        gltr.auto_helm_tick(ship, dt=0.1)

        # Target heading should point roughly south (toward cy=50_000).
        # bearing_to from (50k, 10k) toward (50k, 50k) is 180° (due south).
        assert abs(ship.target_heading - 180.0) < 5.0

    def test_accelerates_when_far_from_centre(self):
        mission = make_training_mission("weapons")
        gltr.init_training(mission)
        ship = make_ship(x=50_000.0, y=5_000.0, throttle=0.0)
        gltr.auto_helm_tick(ship, dt=0.5)
        assert ship.throttle > 0.0

    def test_decelerates_when_near_centre(self):
        mission = make_training_mission("weapons")
        gltr.init_training(mission)
        # Ship very close to sector centre
        ship = make_ship(x=50_100.0, y=50_100.0, throttle=0.4)
        gltr.auto_helm_tick(ship, dt=0.5)
        assert ship.throttle < 0.4

    def test_no_op_when_training_inactive(self):
        # No init_training called
        ship = make_ship(x=50_000.0, y=5_000.0, throttle=0.0)
        gltr.auto_helm_tick(ship, dt=0.5)
        assert ship.throttle == 0.0


class TestAutoEngineeringTick:
    def setup_method(self):
        gltr.reset()

    def test_restores_low_power_system(self):
        mission = make_training_mission("weapons")  # engineering is auto-simulated
        gltr.init_training(mission)
        ship = make_ship()
        ship.systems["engines"].power = 10.0  # below min threshold
        gltr.auto_engineering_tick(ship, dt=0.1)
        assert ship.systems["engines"].power > 10.0

    def test_does_not_lower_adequate_power(self):
        mission = make_training_mission("weapons")
        gltr.init_training(mission)
        ship = make_ship()
        ship.systems["engines"].power = 120.0
        gltr.auto_engineering_tick(ship, dt=0.1)
        assert ship.systems["engines"].power == 120.0  # untouched

    def test_no_op_when_training_inactive(self):
        ship = make_ship()
        ship.systems["engines"].power = 0.0
        gltr.auto_engineering_tick(ship, dt=0.1)
        assert ship.systems["engines"].power == 0.0


class TestHintTracking:
    def setup_method(self):
        gltr.reset()

    def test_last_hint_idx_starts_at_minus_one(self):
        assert gltr.get_last_hint_idx() == -1

    def test_set_last_hint_idx(self):
        gltr.set_last_hint_idx(2)
        assert gltr.get_last_hint_idx() == 2

    def test_reset_clears_last_hint_idx(self):
        gltr.set_last_hint_idx(5)
        gltr.reset()
        assert gltr.get_last_hint_idx() == -1


# ---------------------------------------------------------------------------
# Mission loader: training missions load correctly
# ---------------------------------------------------------------------------


class TestTrainingMissionsLoad:
    @pytest.mark.parametrize("mission_id", [
        "train_helm",
        "train_weapons",
        "train_engineering",
        "train_science",
        "train_medical",
        "train_security",
        "train_comms",
        "train_damage_control",
        "train_flight_ops",
        "train_ew",
        "train_operations",
        "train_captain",
    ])
    def test_mission_loads(self, mission_id):
        from server.missions.loader import load_mission
        mission = load_mission(mission_id)
        assert mission["is_training"] is True
        assert "target_role" in mission
        assert len(mission["nodes"]) >= 3

    @pytest.mark.parametrize("mission_id", [
        "train_helm",
        "train_weapons",
        "train_engineering",
        "train_science",
        "train_medical",
        "train_security",
        "train_comms",
        "train_damage_control",
        "train_flight_ops",
        "train_ew",
        "train_operations",
        "train_captain",
    ])
    def test_mission_has_hints(self, mission_id):
        from server.missions.loader import load_mission
        mission = load_mission(mission_id)
        hints = [obj.get("hint", "") for obj in mission["nodes"]]
        # Each training mission should have at least one hint.
        assert any(h for h in hints), f"{mission_id} has no hints"

    @pytest.mark.parametrize("mission_id", [
        "train_helm",
        "train_weapons",
        "train_engineering",
        "train_science",
        "train_medical",
        "train_security",
        "train_comms",
        "train_damage_control",
        "train_flight_ops",
        "train_ew",
        "train_operations",
        "train_captain",
    ])
    def test_mission_has_valid_triggers(self, mission_id):
        from server.missions.loader import load_mission
        valid_triggers = {
            "player_in_area", "scan_completed", "entity_destroyed",
            "all_enemies_destroyed", "player_hull_zero", "timer_elapsed",
            "wave_defeated", "station_hull_below", "signal_located",
            "proximity_with_shields", "puzzle_completed", "puzzle_failed",
            "puzzle_resolved", "training_flag",
        }
        mission = load_mission(mission_id)
        for obj in mission["nodes"]:
            if obj.get("type", "objective") != "objective":
                continue
            assert obj.get("trigger", {}).get("type") in valid_triggers, (
                f"{mission_id}/{obj['id']} has unknown trigger {obj.get('trigger')!r}"
            )


# ---------------------------------------------------------------------------
# game_loop_mission: get_mission_dict
# ---------------------------------------------------------------------------


class TestGetMissionDict:
    def test_returns_empty_before_init(self):
        import server.game_loop_mission as glm
        glm.reset()
        assert glm.get_mission_dict() == {}

    def test_returns_copy_of_loaded_mission(self):
        import server.game_loop_mission as glm
        world = make_world()
        glm.init_mission("train_helm", world)
        d = glm.get_mission_dict()
        assert d["id"] == "train_helm"
        assert d["is_training"] is True
        # Verify it's a copy (mutation does not affect internal state).
        d["is_training"] = False
        d2 = glm.get_mission_dict()
        assert d2["is_training"] is True
