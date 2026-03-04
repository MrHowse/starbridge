"""Tests for v0.07-2.4: Cruiser Flag Bridge.

Covers: module activation, tactical drawings, target priority queue,
engagement timeline, fleet stubs, message integration, save/resume,
build_state, debrief.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import server.game_loop_flag_bridge as glfb
from server.models.ship import Ship


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_ship(**overrides) -> Ship:
    kwargs = {"x": 50_000.0, "y": 50_000.0}
    kwargs.update(overrides)
    return Ship(**kwargs)


@dataclass
class FakeEnemy:
    id: str = "e1"
    type: str = "cruiser"
    x: float = 60_000.0
    y: float = 50_000.0
    heading: float = 270.0  # pointing left (toward ship)
    velocity: float = 100.0
    hull: float = 100.0
    ai_state: str = "chase"


@dataclass
class FakeWorld:
    enemies: list = field(default_factory=list)
    asteroids: list = field(default_factory=list)
    torpedoes: list = field(default_factory=list)
    stations: list = field(default_factory=list)
    hazards: list = field(default_factory=list)
    creatures: list = field(default_factory=list)


@pytest.fixture(autouse=True)
def _reset():
    glfb.reset()
    yield
    glfb.reset()


# ===========================================================================
# Module activation
# ===========================================================================


class TestActivation:
    def test_active_when_cruiser(self):
        glfb.reset(active=True)
        assert glfb.is_active() is True

    def test_inactive_by_default(self):
        glfb.reset()
        assert glfb.is_active() is False

    def test_inactive_for_non_cruiser(self):
        glfb.reset(active=False)
        assert glfb.is_active() is False

    def test_reset_clears_state(self):
        glfb.reset(active=True)
        glfb.add_drawing("waypoint", 100, 200, label="test")
        glfb.set_priority_queue(["e1", "e2"])
        glfb.set_weapons_override(True)
        glfb.reset()
        assert glfb.get_drawings() == []
        assert glfb.get_priority_queue() == []
        assert glfb.is_weapons_override() is False
        assert glfb.is_active() is False


# ===========================================================================
# Tactical drawings
# ===========================================================================


class TestDrawings:
    def test_add_waypoint(self):
        glfb.reset(active=True)
        result = glfb.add_drawing("waypoint", 100.0, 200.0, label="Alpha")
        assert result["ok"] is True
        assert "id" in result
        drawings = glfb.get_drawings()
        assert len(drawings) == 1
        assert drawings[0]["type"] == "waypoint"
        assert drawings[0]["label"] == "Alpha"
        assert drawings[0]["x"] == 100.0
        assert drawings[0]["y"] == 200.0

    def test_add_arrow_with_endpoints(self):
        glfb.reset(active=True)
        result = glfb.add_drawing("arrow", 100.0, 200.0, x2=300.0, y2=400.0)
        assert result["ok"] is True
        d = glfb.get_drawings()[0]
        assert d["type"] == "arrow"
        assert d["x2"] == 300.0
        assert d["y2"] == 400.0

    def test_add_danger_zone(self):
        glfb.reset(active=True)
        result = glfb.add_drawing("danger_zone", 500.0, 600.0, label="Mines")
        assert result["ok"] is True
        assert glfb.get_drawings()[0]["type"] == "danger_zone"

    def test_add_objective_marker(self):
        glfb.reset(active=True)
        result = glfb.add_drawing("objective", 700.0, 800.0, label="Target")
        assert result["ok"] is True
        assert glfb.get_drawings()[0]["type"] == "objective"

    def test_invalid_type_rejected(self):
        glfb.reset(active=True)
        result = glfb.add_drawing("invalid_type", 100.0, 200.0)
        assert result["ok"] is False
        assert result["reason"] == "invalid_type"
        assert glfb.get_drawings() == []

    def test_not_active_rejected(self):
        glfb.reset(active=False)
        result = glfb.add_drawing("waypoint", 100.0, 200.0)
        assert result["ok"] is False
        assert result["reason"] == "not_active"

    def test_remove_drawing(self):
        glfb.reset(active=True)
        r = glfb.add_drawing("waypoint", 100.0, 200.0)
        drawing_id = r["id"]
        result = glfb.remove_drawing(drawing_id)
        assert result["ok"] is True
        assert glfb.get_drawings() == []

    def test_remove_nonexistent(self):
        glfb.reset(active=True)
        result = glfb.remove_drawing("draw_999")
        assert result["ok"] is False
        assert result["reason"] == "not_found"

    def test_clear_all_drawings(self):
        glfb.reset(active=True)
        glfb.add_drawing("waypoint", 100.0, 200.0)
        glfb.add_drawing("waypoint", 300.0, 400.0)
        glfb.add_drawing("arrow", 500.0, 600.0)
        result = glfb.clear_drawings()
        assert result["ok"] is True
        assert result["cleared"] == 3
        assert glfb.get_drawings() == []

    def test_max_drawings_enforced(self):
        glfb.reset(active=True)
        for i in range(glfb.MAX_DRAWINGS):
            r = glfb.add_drawing("waypoint", float(i), float(i))
            assert r["ok"] is True
        # One more should fail.
        r = glfb.add_drawing("waypoint", 999.0, 999.0)
        assert r["ok"] is False
        assert r["reason"] == "max_drawings"
        assert len(glfb.get_drawings()) == glfb.MAX_DRAWINGS

    def test_custom_colour(self):
        glfb.reset(active=True)
        glfb.add_drawing("waypoint", 100.0, 200.0, colour="#ff0000")
        assert glfb.get_drawings()[0]["colour"] == "#ff0000"

    def test_default_colour(self):
        glfb.reset(active=True)
        glfb.add_drawing("waypoint", 100.0, 200.0)
        assert glfb.get_drawings()[0]["colour"] == "#ffaa00"


# ===========================================================================
# Priority queue
# ===========================================================================


class TestPriorityQueue:
    def test_set_priority(self):
        glfb.reset(active=True)
        result = glfb.set_priority_queue(["e1", "e2", "e3"])
        assert result["ok"] is True
        assert glfb.get_priority_queue() == ["e1", "e2", "e3"]

    def test_clear_priority(self):
        glfb.reset(active=True)
        glfb.set_priority_queue(["e1", "e2"])
        glfb.clear_priority_queue()
        assert glfb.get_priority_queue() == []

    def test_order_preserved(self):
        glfb.reset(active=True)
        glfb.set_priority_queue(["e3", "e1", "e2"])
        assert glfb.get_priority_queue() == ["e3", "e1", "e2"]

    def test_max_targets_enforced(self):
        glfb.reset(active=True)
        ids = [f"e{i}" for i in range(15)]
        glfb.set_priority_queue(ids)
        assert len(glfb.get_priority_queue()) == glfb.MAX_PRIORITY_TARGETS

    def test_set_resets_weapons_override(self):
        glfb.reset(active=True)
        glfb.set_weapons_override(True)
        assert glfb.is_weapons_override() is True
        glfb.set_priority_queue(["e1"])
        assert glfb.is_weapons_override() is False

    def test_weapons_override_flag(self):
        glfb.reset(active=True)
        assert glfb.is_weapons_override() is False
        glfb.set_weapons_override(True)
        assert glfb.is_weapons_override() is True
        glfb.set_weapons_override(False)
        assert glfb.is_weapons_override() is False

    def test_empty_list_valid(self):
        glfb.reset(active=True)
        glfb.set_priority_queue(["e1"])
        glfb.set_priority_queue([])
        assert glfb.get_priority_queue() == []

    def test_duplicates_deduplicated(self):
        glfb.reset(active=True)
        glfb.set_priority_queue(["e1", "e2", "e1", "e3", "e2"])
        assert glfb.get_priority_queue() == ["e1", "e2", "e3"]


# ===========================================================================
# Engagement timeline
# ===========================================================================


class TestTimeline:
    def test_empty_when_inactive(self):
        glfb.reset(active=False)
        ship = _fresh_ship()
        world = FakeWorld(enemies=[FakeEnemy()])
        assert glfb.compute_timeline(world, ship) == []

    def test_enemy_approaching_torpedo_range(self):
        glfb.reset(active=True)
        ship = _fresh_ship(velocity=0.0, heading=0.0)
        # Enemy 20_000 units away, heading toward ship at 100 u/s.
        enemy = FakeEnemy(
            id="e1", x=70_000.0, y=50_000.0,
            heading=270.0, velocity=100.0,  # heading west toward ship
        )
        world = FakeWorld(enemies=[enemy])
        timeline = glfb.compute_timeline(world, ship)
        torpedo_entries = [e for e in timeline if e["type"] == "torpedo_range"]
        assert len(torpedo_entries) == 1
        # Distance 20_000, torpedo range 15_000 → gap 5_000 at 100 u/s → ~50s.
        assert torpedo_entries[0]["eta_s"] == pytest.approx(50.0, abs=1.0)
        assert torpedo_entries[0]["entity_id"] == "e1"

    def test_enemy_approaching_beam_range(self):
        glfb.reset(active=True)
        ship = _fresh_ship(velocity=0.0, heading=0.0)
        enemy = FakeEnemy(
            id="e1", x=70_000.0, y=50_000.0,
            heading=270.0, velocity=100.0,
        )
        world = FakeWorld(enemies=[enemy])
        timeline = glfb.compute_timeline(world, ship)
        beam_entries = [e for e in timeline if e["type"] == "beam_range"]
        assert len(beam_entries) == 1
        # Distance 20_000, beam range 10_000 → gap 10_000 at 100 u/s → ~100s.
        assert beam_entries[0]["eta_s"] == pytest.approx(100.0, abs=1.0)

    def test_enemy_already_in_range(self):
        glfb.reset(active=True)
        ship = _fresh_ship(velocity=0.0)
        # Enemy 5_000 units away — within both ranges.
        enemy = FakeEnemy(x=55_000.0, y=50_000.0, velocity=0.0)
        world = FakeWorld(enemies=[enemy])
        timeline = glfb.compute_timeline(world, ship)
        assert all(e["eta_s"] == 0.0 for e in timeline)
        types = {e["type"] for e in timeline}
        assert "torpedo_range" in types
        assert "beam_range" in types

    def test_multiple_enemies_sorted_by_eta(self):
        glfb.reset(active=True)
        ship = _fresh_ship(velocity=0.0, heading=0.0)
        # Close enemy (in range).
        close = FakeEnemy(id="close", x=55_000.0, y=50_000.0, velocity=0.0)
        # Far enemy approaching.
        far = FakeEnemy(
            id="far", x=80_000.0, y=50_000.0,
            heading=270.0, velocity=200.0,
        )
        world = FakeWorld(enemies=[far, close])
        timeline = glfb.compute_timeline(world, ship)
        assert len(timeline) >= 2
        # First entries should be ETA 0 (close enemy).
        assert timeline[0]["eta_s"] == 0.0

    def test_stationary_enemy_no_closing(self):
        glfb.reset(active=True)
        ship = _fresh_ship(velocity=0.0, heading=0.0)
        # Far stationary enemy — no closing speed, should not appear.
        enemy = FakeEnemy(x=80_000.0, y=50_000.0, velocity=0.0, heading=0.0)
        world = FakeWorld(enemies=[enemy])
        timeline = glfb.compute_timeline(world, ship)
        # No entries since closing speed is 0 (or negative) and not in range.
        assert len(timeline) == 0

    def test_no_enemies_empty_timeline(self):
        glfb.reset(active=True)
        ship = _fresh_ship()
        world = FakeWorld(enemies=[])
        timeline = glfb.compute_timeline(world, ship)
        assert timeline == []

    def test_ship_moving_toward_enemy(self):
        glfb.reset(active=True)
        # Ship heading east (90°) at 150 u/s toward enemy at x=70_000.
        ship = _fresh_ship(velocity=150.0, heading=90.0)
        enemy = FakeEnemy(x=70_000.0, y=50_000.0, velocity=0.0, heading=0.0)
        world = FakeWorld(enemies=[enemy])
        timeline = glfb.compute_timeline(world, ship)
        torpedo_entries = [e for e in timeline if e["type"] == "torpedo_range"]
        assert len(torpedo_entries) == 1
        # Distance 20_000, torpedo range 15_000 → gap 5_000 at 150 u/s → ~33.3s.
        assert torpedo_entries[0]["eta_s"] == pytest.approx(33.3, abs=1.0)


# ===========================================================================
# Fleet coordination stubs
# ===========================================================================


class TestFleetStubs:
    def test_issue_fleet_order_not_implemented(self):
        result = glfb.issue_fleet_order("attack", target_id="e1")
        assert result["ok"] is False
        assert result["reason"] == "not_implemented"

    def test_get_fleet_ships_empty(self):
        assert glfb.get_fleet_ships() == []

    def test_fleet_order_payload_validates(self):
        from server.models.messages.flag_bridge import FlagBridgeFleetOrderPayload
        p = FlagBridgeFleetOrderPayload(order_type="attack", target_id="e1", x=100.0, y=200.0)
        assert p.order_type == "attack"
        assert p.target_id == "e1"


# ===========================================================================
# Message payloads
# ===========================================================================


class TestPayloads:
    def test_add_drawing_payload(self):
        from server.models.messages.flag_bridge import FlagBridgeAddDrawingPayload
        p = FlagBridgeAddDrawingPayload(drawing_type="waypoint", x=100.0, y=200.0)
        assert p.drawing_type == "waypoint"
        assert p.colour == "#ffaa00"
        assert p.x2 is None

    def test_remove_drawing_payload(self):
        from server.models.messages.flag_bridge import FlagBridgeRemoveDrawingPayload
        p = FlagBridgeRemoveDrawingPayload(drawing_id="draw_1")
        assert p.drawing_id == "draw_1"

    def test_set_priority_payload(self):
        from server.models.messages.flag_bridge import FlagBridgeSetPriorityPayload
        p = FlagBridgeSetPriorityPayload(entity_ids=["e1", "e2"])
        assert p.entity_ids == ["e1", "e2"]

    def test_weapons_override_payload(self):
        from server.models.messages.flag_bridge import FlagBridgeWeaponsOverridePayload
        p = FlagBridgeWeaponsOverridePayload()
        assert p.override is True
        p2 = FlagBridgeWeaponsOverridePayload(override=False)
        assert p2.override is False

    def test_clear_drawings_payload(self):
        from server.models.messages.flag_bridge import FlagBridgeClearDrawingsPayload
        p = FlagBridgeClearDrawingsPayload()
        assert p is not None

    def test_clear_priority_payload(self):
        from server.models.messages.flag_bridge import FlagBridgeClearPriorityPayload
        p = FlagBridgeClearPriorityPayload()
        assert p is not None


# ===========================================================================
# Message schema registration
# ===========================================================================


class TestSchemaRegistration:
    def test_all_flag_bridge_types_registered(self):
        from server.models.messages.base import _PAYLOAD_SCHEMAS
        expected_types = [
            "captain.flag_add_drawing",
            "captain.flag_remove_drawing",
            "captain.flag_clear_drawings",
            "captain.flag_set_priority",
            "captain.flag_clear_priority",
            "weapons.override_priority",
            "captain.fleet_order",
        ]
        for msg_type in expected_types:
            assert msg_type in _PAYLOAD_SCHEMAS, f"{msg_type} not registered"

    def test_captain_forwards_flag_bridge_types(self):
        from server.captain import _QUEUE_FORWARDED_TYPES
        expected = [
            "captain.flag_add_drawing",
            "captain.flag_remove_drawing",
            "captain.flag_clear_drawings",
            "captain.flag_set_priority",
            "captain.flag_clear_priority",
            "captain.fleet_order",
        ]
        for msg_type in expected:
            assert msg_type in _QUEUE_FORWARDED_TYPES, f"{msg_type} not forwarded"


# ===========================================================================
# Save / Resume
# ===========================================================================


class TestSerialisation:
    def test_drawings_round_trip(self):
        glfb.reset(active=True)
        glfb.add_drawing("waypoint", 100.0, 200.0, label="WP1")
        glfb.add_drawing("arrow", 300.0, 400.0, x2=500.0, y2=600.0)
        data = glfb.serialise()
        glfb.reset()
        glfb.deserialise(data)
        assert glfb.is_active() is True
        assert len(glfb.get_drawings()) == 2
        assert glfb.get_drawings()[0]["label"] == "WP1"
        assert glfb.get_drawings()[1]["x2"] == 500.0

    def test_priority_queue_round_trip(self):
        glfb.reset(active=True)
        glfb.set_priority_queue(["e3", "e1", "e2"])
        data = glfb.serialise()
        glfb.reset()
        glfb.deserialise(data)
        assert glfb.get_priority_queue() == ["e3", "e1", "e2"]

    def test_weapons_override_round_trip(self):
        glfb.reset(active=True)
        glfb.set_weapons_override(True)
        data = glfb.serialise()
        glfb.reset()
        glfb.deserialise(data)
        assert glfb.is_weapons_override() is True

    def test_drawing_counter_preserved(self):
        glfb.reset(active=True)
        glfb.add_drawing("waypoint", 1.0, 2.0)
        glfb.add_drawing("waypoint", 3.0, 4.0)
        data = glfb.serialise()
        assert data["drawing_counter"] == 2
        glfb.reset()
        glfb.deserialise(data)
        # Next drawing should get id draw_3, not draw_1.
        r = glfb.add_drawing("waypoint", 5.0, 6.0)
        assert r["id"] == "draw_3"

    def test_inactive_saves_empty(self):
        glfb.reset(active=False)
        data = glfb.serialise()
        assert data["flag_bridge_active"] is False
        assert data["drawings"] == []
        assert data["priority_queue"] == []


# ===========================================================================
# Build state
# ===========================================================================


class TestBuildState:
    def test_build_state_includes_all_subsystems(self):
        glfb.reset(active=True)
        glfb.add_drawing("waypoint", 100.0, 200.0)
        glfb.set_priority_queue(["e1"])
        glfb.set_weapons_override(True)
        ship = _fresh_ship()
        world = FakeWorld()
        state = glfb.build_state(world, ship)
        assert state["flag_bridge_active"] is True
        assert len(state["drawings"]) == 1
        assert state["priority_queue"] == ["e1"]
        assert state["weapons_override"] is True
        assert "timeline" in state
        assert "fleet_ships" in state

    def test_build_state_timeline_computed(self):
        glfb.reset(active=True)
        ship = _fresh_ship(velocity=0.0)
        enemy = FakeEnemy(x=55_000.0, y=50_000.0, velocity=0.0)
        world = FakeWorld(enemies=[enemy])
        state = glfb.build_state(world, ship)
        assert len(state["timeline"]) > 0

    def test_build_state_inactive(self):
        glfb.reset(active=False)
        ship = _fresh_ship()
        world = FakeWorld()
        state = glfb.build_state(world, ship)
        assert state["flag_bridge_active"] is False
        assert state["timeline"] == []


# ===========================================================================
# Debrief
# ===========================================================================


class TestDebrief:
    def test_flag_bridge_in_debrief(self):
        glfb.reset(active=True)
        from server.game_debrief import compute_debrief
        result = compute_debrief([])
        assert "flag_bridge_active" in result
        assert result["flag_bridge_active"] is True

    def test_flag_bridge_inactive_in_debrief(self):
        glfb.reset(active=False)
        from server.game_debrief import compute_debrief
        result = compute_debrief([])
        assert result["flag_bridge_active"] is False
