"""
Tests for Operations station Mission Management (v0.08 A.4).

Covers:
  A.4.1 Mission tracking with objective-by-objective progress
  A.4.2 Status display (title, status, responsible station)
  A.4.3 Ops marks objectives "IN PROGRESS" → appears on Captain display
  A.4.4 Station Advisory messages
  A.4.5 Advisory: 15s persist, max 1/station, max 80 chars
  Serialise / deserialise round-trip

Target: 15+ tests (spec D.3).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from unittest.mock import patch

import pytest

import server.game_loop_operations as glops
from server.game_loop_operations import (
    ADVISORY_DURATION,
    ADVISORY_MAX_LENGTH,
    _infer_responsible_station,
)
from server.models.ship import Ship
from server.models.world import World


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tick(world: World, ship: Ship, seconds: float, dt: float = 0.1) -> None:
    ticks = round(seconds / dt)
    for _ in range(ticks):
        glops.tick(world, ship, dt)


def _make_world() -> tuple[World, Ship]:
    world = World()
    return world, world.ship


@dataclass
class FakeObjective:
    id: str
    text: str
    status: Literal["pending", "active", "complete", "cancelled", "failed"] = "pending"


class FakeMissionEngine:
    """Minimal stub that satisfies _build_mission_tracking and mark_objective."""

    def __init__(self, objectives: list[FakeObjective]):
        self._objectives = objectives

    def get_objectives(self):
        return list(self._objectives)

    def get_active_node_ids(self):
        return [o.id for o in self._objectives if o.status == "active"]

    def get_node_trigger(self, node_id: str) -> dict:
        return {}


# ═══════════════════════════════════════════════════════════════════════════
# A.4.1–A.4.2 — Mission Tracking
# ═══════════════════════════════════════════════════════════════════════════


class TestMissionTracking:
    def _patch_mission(self, objectives, title="Test Mission"):
        engine = FakeMissionEngine(objectives)
        mission_dict = {"title": title, "nodes": [], "edges": [], "start_node": None, "victory_nodes": []}
        return (
            patch("server.game_loop_operations.glm.get_mission_engine", return_value=engine),
            patch("server.game_loop_operations.glm.get_mission_dict", return_value=mission_dict),
        )

    def test_tracking_with_no_mission(self):
        world, ship = _make_world()
        with patch("server.game_loop_mission.get_mission_engine", return_value=None):
            state = glops.build_state(world, ship)
            tracking = state["mission_tracking"]
            assert tracking["title"] is None
            assert tracking["objectives"] == []

    def test_tracking_shows_objectives(self):
        objs = [
            FakeObjective("nav1", "Navigate to waypoint Alpha", "active"),
            FakeObjective("scan1", "Scan the anomaly", "pending"),
            FakeObjective("kill1", "Destroy the raiders", "complete"),
        ]
        engine = FakeMissionEngine(objs)
        mission_dict = {"title": "Patrol Mission"}

        with patch("server.game_loop_mission.get_mission_engine", return_value=engine), \
             patch("server.game_loop_mission.get_mission_dict", return_value=mission_dict):
            world, ship = _make_world()
            state = glops.build_state(world, ship)
            tracking = state["mission_tracking"]
            assert tracking["title"] == "Patrol Mission"
            assert len(tracking["objectives"]) == 3

    def test_objective_status_reflected(self):
        objs = [
            FakeObjective("a", "Navigate to sector", "active"),
            FakeObjective("b", "Hail the station", "complete"),
        ]
        engine = FakeMissionEngine(objs)

        with patch("server.game_loop_mission.get_mission_engine", return_value=engine), \
             patch("server.game_loop_mission.get_mission_dict", return_value={"title": "T"}):
            world, ship = _make_world()
            state = glops.build_state(world, ship)
            statuses = {o["id"]: o["status"] for o in state["mission_tracking"]["objectives"]}
            assert statuses["a"] == "active"
            assert statuses["b"] == "complete"


# ═══════════════════════════════════════════════════════════════════════════
# A.4.2 — Responsible Station Inference
# ═══════════════════════════════════════════════════════════════════════════


class TestResponsibleStation:
    def test_navigate_to_helm(self):
        assert _infer_responsible_station("Navigate to waypoint Alpha") == "helm"

    def test_scan_to_science(self):
        assert _infer_responsible_station("Scan the anomaly") == "science"

    def test_destroy_to_weapons(self):
        assert _infer_responsible_station("Destroy the enemy cruiser") == "weapons"

    def test_hail_to_comms(self):
        assert _infer_responsible_station("Hail the station commander") == "comms"

    def test_repair_to_engineering(self):
        assert _infer_responsible_station("Repair the engine systems") == "engineering"

    def test_unknown_defaults_to_operations(self):
        assert _infer_responsible_station("Complete the mission") == "operations"

    def test_medical_to_medical(self):
        assert _infer_responsible_station("Treat the injured crew") == "medical"


# ═══════════════════════════════════════════════════════════════════════════
# A.4.3 — Mark Objective In Progress
# ═══════════════════════════════════════════════════════════════════════════


class TestMarkObjective:
    def test_mark_ok(self):
        objs = [FakeObjective("obj1", "Test objective", "active")]
        engine = FakeMissionEngine(objs)

        with patch("server.game_loop_mission.get_mission_engine", return_value=engine):
            result = glops.mark_objective("obj1")
            assert result["ok"] is True
            assert "obj1" in glops.get_objectives_marked()

    def test_mark_unknown_objective(self):
        objs = [FakeObjective("obj1", "Test", "active")]
        engine = FakeMissionEngine(objs)

        with patch("server.game_loop_mission.get_mission_engine", return_value=engine):
            result = glops.mark_objective("nonexistent")
            assert result["ok"] is False

    def test_mark_no_mission(self):
        with patch("server.game_loop_mission.get_mission_engine", return_value=None):
            result = glops.mark_objective("obj1")
            assert result["ok"] is False

    def test_mark_broadcasts_to_captain(self):
        objs = [FakeObjective("obj1", "Test", "active")]
        engine = FakeMissionEngine(objs)

        with patch("server.game_loop_mission.get_mission_engine", return_value=engine):
            glops.mark_objective("obj1")
            broadcasts = glops.pop_pending_broadcasts()
            mark_bc = [b for b in broadcasts if b[1].get("type") == "objective_marked"]
            assert len(mark_bc) == 1
            assert "captain" in mark_bc[0][0]


# ═══════════════════════════════════════════════════════════════════════════
# A.4.4–A.4.5 — Station Advisory
# ═══════════════════════════════════════════════════════════════════════════


class TestStationAdvisory:
    def test_send_advisory_ok(self):
        result = glops.send_station_advisory("helm", "Hold position for 30 seconds")
        assert result["ok"] is True

    def test_advisory_query(self):
        glops.send_station_advisory("helm", "Hold position")
        assert glops.get_station_advisory("helm") == "Hold position"

    def test_advisory_broadcasts_to_target(self):
        glops.send_station_advisory("science", "Scan now")
        broadcasts = glops.pop_pending_broadcasts()
        adv_bc = [b for b in broadcasts if b[1].get("type") == "station_advisory"]
        assert len(adv_bc) == 1
        assert "science" in adv_bc[0][0]
        assert adv_bc[0][1]["message"] == "Scan now"

    def test_advisory_expires_after_duration(self):
        world, ship = _make_world()
        glops.send_station_advisory("helm", "Hold position")
        _tick(world, ship, ADVISORY_DURATION + 1.0)
        assert glops.get_station_advisory("helm") is None

    def test_advisory_persists_before_expiry(self):
        world, ship = _make_world()
        glops.send_station_advisory("helm", "Hold position")
        _tick(world, ship, ADVISORY_DURATION - 5.0)
        assert glops.get_station_advisory("helm") == "Hold position"

    def test_new_advisory_replaces_old(self):
        glops.send_station_advisory("helm", "First message")
        glops.send_station_advisory("helm", "Second message")
        assert glops.get_station_advisory("helm") == "Second message"

    def test_max_one_per_station(self):
        glops.send_station_advisory("helm", "Helm message")
        glops.send_station_advisory("science", "Science message")
        assert glops.get_station_advisory("helm") == "Helm message"
        assert glops.get_station_advisory("science") == "Science message"

    def test_truncate_long_message(self):
        long_msg = "A" * 200
        glops.send_station_advisory("helm", long_msg)
        assert glops.get_station_advisory("helm") is not None
        assert len(glops.get_station_advisory("helm")) <= ADVISORY_MAX_LENGTH

    def test_empty_message_rejected(self):
        result = glops.send_station_advisory("helm", "   ")
        assert result["ok"] is False

    def test_invalid_station_rejected(self):
        result = glops.send_station_advisory("nonexistent_station", "Hello")
        assert result["ok"] is False

    def test_no_advisory_returns_none(self):
        assert glops.get_station_advisory("helm") is None


# ═══════════════════════════════════════════════════════════════════════════
# Serialise / Deserialise round-trip
# ═══════════════════════════════════════════════════════════════════════════


class TestMissionMgmtSerialise:
    def test_advisory_round_trip(self):
        glops.send_station_advisory("helm", "Hold position")
        data = glops.serialise()
        glops.reset()
        glops.deserialise(data)
        assert glops.get_station_advisory("helm") == "Hold position"

    def test_marked_objectives_round_trip(self):
        objs = [FakeObjective("obj1", "Test", "active")]
        engine = FakeMissionEngine(objs)

        with patch("server.game_loop_mission.get_mission_engine", return_value=engine):
            glops.mark_objective("obj1")
        data = glops.serialise()
        glops.reset()
        glops.deserialise(data)
        assert "obj1" in glops.get_objectives_marked()


# ═══════════════════════════════════════════════════════════════════════════
# Build state
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildStateMissionMgmt:
    def test_advisories_in_state(self):
        world, ship = _make_world()
        glops.send_station_advisory("helm", "Hold position")
        state = glops.build_state(world, ship)
        assert "helm" in state["station_advisories"]
        assert state["station_advisories"]["helm"]["message"] == "Hold position"
