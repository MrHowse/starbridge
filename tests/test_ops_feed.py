"""
Tests for Operations station Information Feed (v0.08 A.5).

Covers:
  A.5.2.1 Events from all station sources
  A.5.2.2 Severity coding (info, warning, critical)
  A.5.2.3 50-item cap (server-side 100), ordering
  Feed drain semantics
  Feed events from assessment, coordination, mission management
  Cross-station feed events

Target: 15+ tests (spec D.4).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from unittest.mock import patch

import pytest

import server.game_loop_operations as glops
from server.game_loop_operations import (
    DAMAGE_ASSESSMENT_DURATION,
)
from server.models.ship import Ship
from server.models.world import Enemy, World, spawn_enemy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _world_with_enemy(
    enemy_id: str = "e1",
    enemy_type: str = "cruiser",
    x: float = 5000.0,
    y: float = 5000.0,
) -> tuple[World, Ship, Enemy]:
    world = World()
    ship = world.ship
    ship.x, ship.y = 50000.0, 50000.0
    enemy = spawn_enemy(enemy_type, x, y, enemy_id)
    enemy.scan_state = "scanned"
    world.enemies.append(enemy)
    return world, ship, enemy


def _tick(world: World, ship: Ship, seconds: float, dt: float = 0.1) -> None:
    ticks = round(seconds / dt)
    for _ in range(ticks):
        glops.tick(world, ship, dt)


@dataclass
class FakeObjective:
    id: str
    text: str
    status: Literal["pending", "active", "complete", "cancelled", "failed"] = "pending"


class FakeMissionEngine:
    def __init__(self, objectives: list[FakeObjective]):
        self._objectives = objectives

    def get_objectives(self):
        return list(self._objectives)

    def get_active_node_ids(self):
        return [o.id for o in self._objectives if o.status == "active"]


# ═══════════════════════════════════════════════════════════════════════════
# A.5.2 — Feed Event Basics
# ═══════════════════════════════════════════════════════════════════════════


class TestFeedEventBasics:
    def test_add_feed_event_basic(self):
        world, ship, _ = _world_with_enemy()
        glops.add_feed_event("SCIENCE", "Scan complete on sector 4", "info")
        state = glops.build_state(world, ship)
        assert len(state["feed_events"]) == 1
        evt = state["feed_events"][0]
        assert evt["source"] == "SCIENCE"
        assert evt["text"] == "Scan complete on sector 4"
        assert evt["severity"] == "info"
        assert "id" in evt

    def test_severity_info(self):
        world, ship, _ = _world_with_enemy()
        glops.add_feed_event("HELM", "Course change", "info")
        state = glops.build_state(world, ship)
        assert state["feed_events"][0]["severity"] == "info"

    def test_severity_warning(self):
        world, ship, _ = _world_with_enemy()
        glops.add_feed_event("ENGINEERING", "Reactor overheating", "warning")
        state = glops.build_state(world, ship)
        assert state["feed_events"][0]["severity"] == "warning"

    def test_severity_critical(self):
        world, ship, _ = _world_with_enemy()
        glops.add_feed_event("SECURITY", "Boarding detected", "critical")
        state = glops.build_state(world, ship)
        assert state["feed_events"][0]["severity"] == "critical"

    def test_invalid_severity_defaults_to_info(self):
        world, ship, _ = _world_with_enemy()
        glops.add_feed_event("OPS", "Something happened", "banana")
        state = glops.build_state(world, ship)
        assert state["feed_events"][0]["severity"] == "info"

    def test_feed_events_drain_on_build_state(self):
        world, ship, _ = _world_with_enemy()
        glops.add_feed_event("HELM", "Full stop", "info")
        state1 = glops.build_state(world, ship)
        assert len(state1["feed_events"]) == 1
        state2 = glops.build_state(world, ship)
        assert len(state2["feed_events"]) == 0

    def test_feed_events_cap_at_100(self):
        world, ship, _ = _world_with_enemy()
        for i in range(120):
            glops.add_feed_event("OPS", f"Event {i}", "info")
        state = glops.build_state(world, ship)
        assert len(state["feed_events"]) == 100
        # Oldest events dropped — first event should be Event 20
        assert state["feed_events"][0]["text"] == "Event 20"

    def test_sequential_ids(self):
        world, ship, _ = _world_with_enemy()
        glops.add_feed_event("A", "First", "info")
        glops.add_feed_event("B", "Second", "info")
        state = glops.build_state(world, ship)
        ids = [e["id"] for e in state["feed_events"]]
        assert ids[1] > ids[0]

    def test_multiple_sources_in_one_tick(self):
        world, ship, _ = _world_with_enemy()
        glops.add_feed_event("SCIENCE", "Scan done", "info")
        glops.add_feed_event("WEAPONS", "Torpedo hit", "info")
        glops.add_feed_event("HELM", "Course change", "info")
        state = glops.build_state(world, ship)
        sources = [e["source"] for e in state["feed_events"]]
        assert "SCIENCE" in sources
        assert "WEAPONS" in sources
        assert "HELM" in sources

    def test_fifo_order(self):
        world, ship, _ = _world_with_enemy()
        glops.add_feed_event("A", "First", "info")
        glops.add_feed_event("B", "Second", "info")
        glops.add_feed_event("C", "Third", "info")
        state = glops.build_state(world, ship)
        texts = [e["text"] for e in state["feed_events"]]
        assert texts == ["First", "Second", "Third"]


# ═══════════════════════════════════════════════════════════════════════════
# A.5.2 — Feed Events from Operations Actions
# ═══════════════════════════════════════════════════════════════════════════


class TestFeedFromOpsActions:
    def test_assessment_complete_generates_feed(self):
        world, ship, enemy = _world_with_enemy()
        glops.start_assessment(enemy.id, world, ship)
        # With basic scan modifier (-0.25), effective speed = 0.75.
        # Duration = 15 / 0.75 = 20s. Tick 21s to be safe.
        _tick(world, ship, 21.0)
        state = glops.build_state(world, ship)
        feed = state["feed_events"]
        assert any("Assessment complete" in e["text"] for e in feed)

    def test_threat_level_critical_generates_feed(self):
        world, ship, _ = _world_with_enemy()
        glops.set_threat_level("e1", "critical")
        state = glops.build_state(world, ship)
        feed = state["feed_events"]
        crit_events = [e for e in feed if "CRITICAL" in e["text"].upper()]
        assert len(crit_events) >= 1
        assert crit_events[0]["severity"] == "critical"

    def test_threat_level_low_generates_info(self):
        world, ship, _ = _world_with_enemy()
        glops.set_threat_level("e1", "low")
        state = glops.build_state(world, ship)
        feed = state["feed_events"]
        low_events = [e for e in feed if "LOW" in e["text"].upper()]
        assert len(low_events) >= 1
        assert low_events[0]["severity"] == "info"

    def test_sync_initiated_generates_feed(self):
        world, ship, enemy = _world_with_enemy()
        glops.set_weapons_helm_sync(enemy.id, world, ship)
        state = glops.build_state(world, ship)
        feed = state["feed_events"]
        assert any("Sync initiated" in e["text"] for e in feed)

    def test_sync_broken_generates_feed(self):
        world, ship, enemy = _world_with_enemy()
        glops.set_weapons_helm_sync(enemy.id, world, ship)
        # Build state to drain the "initiated" event
        glops.build_state(world, ship)
        # Destroy the enemy to break sync
        world.enemies.clear()
        _tick(world, ship, 0.1)
        state = glops.build_state(world, ship)
        feed = state["feed_events"]
        assert any("Sync BROKEN" in e["text"] for e in feed)

    def test_evasion_alert_generates_feed(self):
        glops.issue_evasion_alert(90.0)
        world, ship, _ = _world_with_enemy()
        state = glops.build_state(world, ship)
        feed = state["feed_events"]
        evasion = [e for e in feed if "EVASION" in e["text"]]
        assert len(evasion) >= 1
        assert evasion[0]["severity"] == "critical"

    def test_station_advisory_generates_feed(self):
        world, ship, _ = _world_with_enemy()
        glops.send_station_advisory("helm", "Hold position")
        state = glops.build_state(world, ship)
        feed = state["feed_events"]
        assert any("Advisory" in e["text"] and "helm" in e["text"] for e in feed)

    def test_mark_objective_generates_feed(self):
        objs = [FakeObjective("obj1", "Test objective", "active")]
        engine = FakeMissionEngine(objs)
        with patch("server.game_loop_mission.get_mission_engine", return_value=engine):
            glops.mark_objective("obj1")
        world, ship, _ = _world_with_enemy()
        state = glops.build_state(world, ship)
        feed = state["feed_events"]
        assert any("Objective marked" in e["text"] for e in feed)

    def test_damage_coordination_complete_generates_feed(self):
        world, ship, _ = _world_with_enemy()
        glops.start_damage_coordination()
        _tick(world, ship, DAMAGE_ASSESSMENT_DURATION + 1.0)
        state = glops.build_state(world, ship)
        feed = state["feed_events"]
        assert any("Damage assessment complete" in e["text"] for e in feed)


# ═══════════════════════════════════════════════════════════════════════════
# Feed event round-trip (serialise has no feed — feed is transient)
# ═══════════════════════════════════════════════════════════════════════════


class TestFeedTransient:
    def test_feed_events_not_serialised(self):
        """Feed events are transient — not included in save data."""
        glops.add_feed_event("OPS", "Something", "info")
        data = glops.serialise()
        assert "feed_events" not in data

    def test_feed_cleared_on_reset(self):
        world, ship, _ = _world_with_enemy()
        glops.add_feed_event("OPS", "Something", "info")
        glops.reset()
        state = glops.build_state(world, ship)
        assert len(state["feed_events"]) == 0
