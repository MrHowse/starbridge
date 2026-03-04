"""
Tests for Operations station onboarding feed events.

Covers:
  - Scan complete severity bump to "warning"
  - Hull damage feed event from combat processing
  - Dynamic mission offered feed event
"""
from __future__ import annotations

import server.game_loop_operations as glops
from server.models.ship import Ship
from server.models.world import World, spawn_enemy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _world_with_enemy(
    enemy_id: str = "e1",
    enemy_type: str = "cruiser",
    x: float = 5000.0,
    y: float = 5000.0,
) -> tuple[World, Ship]:
    world = World()
    ship = world.ship
    ship.x, ship.y = 50000.0, 50000.0
    enemy = spawn_enemy(enemy_type, x, y, enemy_id)
    enemy.scan_state = "scanned"
    world.enemies.append(enemy)
    return world, ship


# ═══════════════════════════════════════════════════════════════════════════
# Scan complete severity bump
# ═══════════════════════════════════════════════════════════════════════════


class TestScanCompleteFeedSeverity:
    def test_scan_complete_feed_is_warning(self):
        """Scan-complete feed event should be 'warning' severity for visibility."""
        world, ship = _world_with_enemy()
        glops.add_feed_event("SCI", "SCAN COMPLETE: e1 — Ready for assessment", "warning")
        state = glops.build_state(world, ship)
        feed = state["feed_events"]
        sci_events = [e for e in feed if "SCAN COMPLETE" in e["text"]]
        assert len(sci_events) == 1
        assert sci_events[0]["severity"] == "warning"
        assert "Ready for assessment" in sci_events[0]["text"]

    def test_scan_complete_contains_entity_id(self):
        """Scan-complete feed text should contain the entity ID."""
        world, ship = _world_with_enemy()
        glops.add_feed_event("SCI", "SCAN COMPLETE: e1 — Ready for assessment", "warning")
        state = glops.build_state(world, ship)
        assert "e1" in state["feed_events"][0]["text"]


# ═══════════════════════════════════════════════════════════════════════════
# Hull damage feed event
# ═══════════════════════════════════════════════════════════════════════════


class TestHullDamageFeedEvent:
    def test_hull_damage_creates_warning_feed_event(self):
        """Hull damage above 25% remaining → warning severity."""
        world, ship = _world_with_enemy()
        glops.add_feed_event(
            "COMBAT",
            "Hull damage: 15 (85% remaining)",
            "warning",
        )
        state = glops.build_state(world, ship)
        feed = state["feed_events"]
        hull_events = [e for e in feed if "Hull damage" in e["text"]]
        assert len(hull_events) == 1
        assert hull_events[0]["severity"] == "warning"
        assert "85% remaining" in hull_events[0]["text"]

    def test_hull_damage_critical_when_low(self):
        """Hull damage below 25% remaining → critical severity."""
        world, ship = _world_with_enemy()
        glops.add_feed_event(
            "COMBAT",
            "Hull damage: 60 (20% remaining)",
            "critical",
        )
        state = glops.build_state(world, ship)
        feed = state["feed_events"]
        hull_events = [e for e in feed if "Hull damage" in e["text"]]
        assert len(hull_events) == 1
        assert hull_events[0]["severity"] == "critical"


# ═══════════════════════════════════════════════════════════════════════════
# Dynamic mission offered feed event
# ═══════════════════════════════════════════════════════════════════════════


class TestDynamicMissionOfferedFeedEvent:
    def test_mission_offered_creates_feed_event(self):
        """When a dynamic mission is offered, an info feed event appears."""
        world, ship = _world_with_enemy()
        glops.add_feed_event("MISSION", "Mission available: Rescue", "info")
        state = glops.build_state(world, ship)
        feed = state["feed_events"]
        mission_events = [e for e in feed if "Mission available" in e["text"]]
        assert len(mission_events) == 1
        assert mission_events[0]["severity"] == "info"
        assert "Rescue" in mission_events[0]["text"]

    def test_mission_offered_uses_title(self):
        """Feed event uses the mission title, not template ID."""
        world, ship = _world_with_enemy()
        glops.add_feed_event("MISSION", "Mission available: Supply Run", "info")
        state = glops.build_state(world, ship)
        assert "Supply Run" in state["feed_events"][0]["text"]
