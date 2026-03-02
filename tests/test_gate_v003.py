"""
v0.03 Gate Verification Tests.

Programmatically checks the items from SCOPE_v003.md Section 17.3 that
can be verified without a live server or human testers.

Gate checklist items verified here:
  - All 12 training missions load and are valid
  - All ship classes load (7 total including specialised)
  - Ship class crew ranges are sane
  - All standard missions load and have valid triggers
  - Difficulty presets exist (cadet/officer/commander/admiral)
  - Mission engine: training_flag trigger works
  - Debrief: compute_from_log works on a synthetic log
  - game_loop_mission.get_mission_dict() returns a copy
  - All game_loop_* modules have a reset() function
  - game_logger: get_log_path() works before and after stop
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from server.missions.loader import load_mission
from server.models.ship_class import load_ship_class, list_ship_classes
from server.difficulty import get_preset, PRESETS
import server.game_debrief as gdb
import server.game_loop_training as gltr
import server.game_loop_mission as glm
import server.game_loop_weapons as glw
import server.game_loop_medical_v2 as glmed
import server.game_loop_security as gls
import server.game_loop_comms as glco
import server.game_loop_captain as glcap
import server.game_loop_damage_control as gldc
import server.game_loop_flight_ops as glfo
import server.game_loop_ew as glew
import server.game_loop_tactical as gltac


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TRAINING_MISSION_IDS = [
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
    "train_tactical",
    "train_captain",
]

STANDARD_MISSION_IDS = [
    "first_contact",
    "defend_station",
    "search_rescue",
    "puzzle_poc",
    "engineering_drill",
    "boarding_action",
    "first_contact_protocol",
    "plague_ship",
    "nebula_crossing",
    "deep_strike",
    "diplomatic_summit",
]

SHIP_CLASS_IDS = [
    "scout",
    "corvette",
    "frigate",
    "cruiser",
    "battleship",
    "medical_ship",
    "carrier",
]

VALID_TRIGGERS = {
    "player_in_area", "scan_completed", "entity_destroyed",
    "all_enemies_destroyed", "player_hull_zero", "timer_elapsed",
    "wave_defeated", "station_hull_below", "signal_located",
    "proximity_with_shields", "puzzle_completed", "puzzle_failed",
    "puzzle_resolved", "training_flag",
}


# ---------------------------------------------------------------------------
# Training missions
# ---------------------------------------------------------------------------


class TestTrainingMissionsGate:
    """Gate: Training missions exist for all 12 stations."""

    def test_twelve_training_missions(self):
        assert len(TRAINING_MISSION_IDS) == 12

    @pytest.mark.parametrize("mid", TRAINING_MISSION_IDS)
    def test_loads(self, mid):
        mission = load_mission(mid)
        assert mission["id"] == mid

    @pytest.mark.parametrize("mid", TRAINING_MISSION_IDS)
    def test_is_training_flag(self, mid):
        assert load_mission(mid).get("is_training") is True

    @pytest.mark.parametrize("mid", TRAINING_MISSION_IDS)
    def test_has_target_role(self, mid):
        assert "target_role" in load_mission(mid)

    @pytest.mark.parametrize("mid", TRAINING_MISSION_IDS)
    def test_at_least_three_objectives(self, mid):
        assert len(load_mission(mid)["nodes"]) >= 3

    @pytest.mark.parametrize("mid", TRAINING_MISSION_IDS)
    def test_valid_triggers(self, mid):
        mission = load_mission(mid)
        for obj in mission["nodes"]:
            if obj.get("type", "objective") != "objective":
                continue
            assert obj.get("trigger", {}).get("type") in VALID_TRIGGERS, (
                f"{mid}/{obj['id']} has invalid trigger {obj.get('trigger')!r}"
            )

    @pytest.mark.parametrize("mid", TRAINING_MISSION_IDS)
    def test_has_at_least_one_hint(self, mid):
        mission = load_mission(mid)
        hints = [obj.get("hint", "") for obj in mission["nodes"]]
        assert any(h for h in hints), f"{mid} has no hints"

    @pytest.mark.parametrize("mid", TRAINING_MISSION_IDS)
    def test_victory_condition_present(self, mid):
        assert "victory_nodes" in load_mission(mid)


# ---------------------------------------------------------------------------
# Standard missions
# ---------------------------------------------------------------------------


class TestStandardMissionsGate:
    """Gate: All v0.01 and v0.02 missions still work."""

    @pytest.mark.parametrize("mid", STANDARD_MISSION_IDS)
    def test_loads(self, mid):
        mission = load_mission(mid)
        assert mission["id"] == mid

    @pytest.mark.parametrize("mid", STANDARD_MISSION_IDS)
    def test_has_objectives(self, mid):
        mission = load_mission(mid)
        assert len(mission["nodes"]) >= 1

    @pytest.mark.parametrize("mid", STANDARD_MISSION_IDS)
    def test_valid_triggers(self, mid):
        mission = load_mission(mid)
        for obj in mission["nodes"]:
            if obj.get("type", "objective") != "objective":
                continue
            assert obj.get("trigger", {}).get("type") in VALID_TRIGGERS, (
                f"{mid}/{obj['id']} has invalid trigger {obj.get('trigger')!r}"
            )

    @pytest.mark.parametrize("mid", STANDARD_MISSION_IDS)
    def test_not_training(self, mid):
        # Standard missions must not accidentally set is_training.
        assert load_mission(mid).get("is_training", False) is False

    def test_sandbox_loads(self):
        # Sandbox is synthetic — loader.py handles it without a JSON file.
        mission = load_mission("sandbox")
        assert mission["id"] == "sandbox"


# ---------------------------------------------------------------------------
# Ship classes
# ---------------------------------------------------------------------------


class TestShipClassGate:
    """Gate: All ship classes balanced and loadable."""

    @pytest.mark.parametrize("ship_id", SHIP_CLASS_IDS)
    def test_loads(self, ship_id):
        sc = load_ship_class(ship_id)
        assert sc.id == ship_id

    @pytest.mark.parametrize("ship_id", SHIP_CLASS_IDS)
    def test_has_crew_range(self, ship_id):
        sc = load_ship_class(ship_id)
        assert sc.min_crew >= 1
        assert sc.max_crew >= sc.min_crew

    @pytest.mark.parametrize("ship_id", SHIP_CLASS_IDS)
    def test_has_positive_hull(self, ship_id):
        assert load_ship_class(ship_id).max_hull > 0

    def test_list_includes_all(self):
        classes = list_ship_classes()
        ids = {sc.id for sc in classes}
        for ship_id in SHIP_CLASS_IDS:
            assert ship_id in ids

    def test_hull_progression(self):
        scout     = load_ship_class("scout").max_hull
        frigate   = load_ship_class("frigate").max_hull
        battleship = load_ship_class("battleship").max_hull
        assert scout < frigate < battleship

    def test_crew_range_covers_1_to_12(self):
        # Smallest min_crew should be 3 (scout), largest max_crew should be 12 (battleship).
        classes = list_ship_classes()
        min_vals = [sc.min_crew for sc in classes]
        max_vals = [sc.max_crew for sc in classes]
        assert min(min_vals) <= 4    # scout or similar at bottom end
        assert max(max_vals) == 12   # battleship fills the top


# ---------------------------------------------------------------------------
# Difficulty presets
# ---------------------------------------------------------------------------


class TestDifficultyPresetsGate:
    """Gate: Difficulty presets produce measurably different experiences."""

    def test_all_four_presets_exist(self):
        for name in ("cadet", "officer", "commander", "admiral"):
            p = get_preset(name)
            assert p is not None

    def test_cadet_has_hints(self):
        assert get_preset("cadet").hints_enabled is True

    def test_officer_no_hints(self):
        assert get_preset("officer").hints_enabled is False

    def test_cadet_easier_damage(self):
        assert get_preset("cadet").enemy_damage_multiplier < get_preset("officer").enemy_damage_multiplier

    def test_admiral_harder_damage(self):
        assert get_preset("admiral").enemy_damage_multiplier > get_preset("officer").enemy_damage_multiplier

    def test_cadet_longer_puzzles(self):
        assert get_preset("cadet").puzzle_time_mult > get_preset("officer").puzzle_time_mult

    def test_admiral_shorter_puzzles(self):
        assert get_preset("admiral").puzzle_time_mult < get_preset("officer").puzzle_time_mult

    def test_unknown_preset_falls_back_to_officer(self):
        p = get_preset("nonexistent")
        officer = get_preset("officer")
        assert p.enemy_damage_multiplier == officer.enemy_damage_multiplier


# ---------------------------------------------------------------------------
# Debrief dashboard
# ---------------------------------------------------------------------------


class TestDebriefGate:
    """Gate: Debrief dashboard generates meaningful stats."""

    def test_compute_from_synthetic_log(self, tmp_path):
        records = [
            {"tick": 0,   "ts": 0.0,  "cat": "session", "event": "started",  "data": {}},
            {"tick": 5,   "ts": 5.0,  "cat": "helm",    "event": "heading_changed", "data": {}},
            {"tick": 10,  "ts": 10.0, "cat": "weapons",  "event": "beam_fired",     "data": {}},
            {"tick": 10,  "ts": 10.0, "cat": "weapons",  "event": "beam_fired",     "data": {}},
            {"tick": 10,  "ts": 10.0, "cat": "weapons",  "event": "beam_fired",     "data": {}},
            {"tick": 10,  "ts": 10.0, "cat": "weapons",  "event": "beam_fired",     "data": {}},
            {"tick": 10,  "ts": 10.0, "cat": "weapons",  "event": "beam_fired",     "data": {}},
            {"tick": 100, "ts": 10.0, "cat": "game",     "event": "tick_summary",   "data": {
                "hull": 80.0, "x": 51000.0, "y": 49000.0,
            }},
            {"tick": 200, "ts": 50.0, "cat": "mission",  "event": "objective_completed",
             "data": {"objective_id": "obj_1"}},
            {"tick": 999, "ts": 120.0,"cat": "session",  "event": "ended",     "data": {"result": "victory"}},
        ]
        log_path = tmp_path / "game.jsonl"
        with log_path.open("w") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

        result = gdb.compute_from_log(log_path)

        assert "helm" in result["per_station_stats"]
        assert "weapons" in result["per_station_stats"]
        assert any(a["award"] == "Sharpshooter" for a in result["awards"])
        assert len(result["timeline"]) == 1
        assert any("obj_1" in m["text"] for m in result["key_moments"])

    def test_empty_log_returns_structure(self, tmp_path):
        log_path = tmp_path / "empty.jsonl"
        log_path.write_text("")
        result = gdb.compute_from_log(log_path)
        assert "per_station_stats" in result
        assert "awards" in result
        assert "key_moments" in result
        assert "timeline" in result


# ---------------------------------------------------------------------------
# Cross-station notifications
# ---------------------------------------------------------------------------


class TestCrossStationNotificationsGate:
    """Gate: Training flags and mission integration verified."""

    def test_training_flag_trigger_in_mission_engine(self):
        from server.missions.engine import MissionEngine
        from server.models.ship import Ship
        from server.models.world import World

        mission = {
            "id": "gate_test",
            "is_training": True,
            "target_role": "helm",
            "objectives": [{
                "id": "obj1",
                "text": "Test",
                "trigger": "training_flag",
                "args": {"flag": "helm_heading_set"},
            }],
            "victory_condition": "all_objectives_complete",
            "defeat_condition": "player_hull_zero",
        }
        engine = MissionEngine(mission)
        ship = Ship()
        world = World(ship=ship, width=100_000, height=100_000)

        result = engine.tick(world, ship, dt=0.1)
        assert result == []   # flag not set yet

        engine.set_training_flag("helm_heading_set")
        result = engine.tick(world, ship, dt=0.1)
        assert "obj1" in result

    def test_get_active_objective_index(self):
        from server.missions.engine import MissionEngine
        from server.models.ship import Ship
        from server.models.world import World

        mission = {
            "id": "gate_test2",
            "objectives": [
                {"id": "o1", "text": "First",  "trigger": "timer_elapsed", "args": {"seconds": 0.05}},
                {"id": "o2", "text": "Second", "trigger": "timer_elapsed", "args": {"seconds": 0.05}},
            ],
            "victory_condition": "all_objectives_complete",
            "defeat_condition": "player_hull_zero",
        }
        engine = MissionEngine(mission)
        ship = Ship()
        world = World(ship=ship, width=100_000, height=100_000)
        assert engine.get_active_objective_index() == 0
        engine.tick(world, ship, dt=1.0)
        assert engine.get_active_objective_index() == 1


# ---------------------------------------------------------------------------
# game_loop_* modules have reset()
# ---------------------------------------------------------------------------


class TestGameLoopModuleResetGate:
    """Gate: All game_loop_* modules expose a reset() function (safe to call repeatedly)."""

    def test_gltr_reset(self):
        gltr.reset()
        assert not gltr.is_training_active()

    def test_glm_reset(self):
        glm.reset()
        assert glm.get_mission_dict() == {}

    def test_glw_reset(self):
        glw.reset()

    def test_glmed_reset(self):
        glmed.reset()

    def test_gls_reset(self):
        gls.reset()

    def test_glco_reset(self):
        glco.reset()

    def test_glcap_reset(self):
        glcap.reset()

    def test_gldc_reset(self):
        gldc.reset()

    def test_glfo_reset(self):
        glfo.reset()

    def test_glew_reset(self):
        glew.reset()

    def test_gltac_reset(self):
        gltac.reset()


# ---------------------------------------------------------------------------
# get_mission_dict returns a copy
# ---------------------------------------------------------------------------


class TestGetMissionDictGate:
    """Gate: get_mission_dict() isolation — mutations don't affect server state."""

    def test_returns_copy(self):
        from server.models.world import World
        from server.models.ship import Ship

        ship = Ship()
        world = World(ship=ship, width=100_000, height=100_000)
        glm.init_mission("first_contact", world)

        d1 = glm.get_mission_dict()
        d1["_mutated"] = True

        d2 = glm.get_mission_dict()
        assert "_mutated" not in d2

    def test_returns_correct_mission(self):
        from server.models.world import World
        from server.models.ship import Ship

        ship = Ship()
        world = World(ship=ship, width=100_000, height=100_000)
        glm.init_mission("defend_station", world)
        d = glm.get_mission_dict()
        assert d.get("id") == "defend_station"

    def test_empty_before_init(self):
        glm.reset()
        assert glm.get_mission_dict() == {}


# ---------------------------------------------------------------------------
# Lobby roles list (11 active player roles in current implementation)
# ---------------------------------------------------------------------------


class TestLobbyRolesGate:
    """Gate: All active player roles are registered in the lobby session."""

    def test_lobby_has_core_roles(self):
        from server.lobby import LobbySession
        session = LobbySession()
        for role in ("captain", "helm", "weapons", "engineering", "science"):
            assert role in session.roles

    def test_lobby_has_expanded_roles(self):
        from server.lobby import LobbySession
        session = LobbySession()
        for role in ("medical", "security", "comms", "flight_ops", "electronic_warfare", "tactical", "damage_control"):
            assert role in session.roles

    def test_lobby_role_count(self):
        from server.lobby import LobbySession
        session = LobbySession()
        # 14 distinct player roles (12 standard + janitor + quartermaster; viewscreen is passive display)
        assert len(session.roles) == 14
