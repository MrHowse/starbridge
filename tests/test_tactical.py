"""Tests for the Tactical Officer game loop module (game_loop_tactical.py).

Covers: reset, threat assessment, engagement priorities, intercept plotting,
        annotations, strike plan creation and execution, tick countdown
        broadcasts, build_state, payload schemas, and handler integration.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

import server.game_loop_tactical as gltac
from server.models.messages.tactical import (
    TacticalAddAnnotationPayload,
    TacticalCreateStrikePlanPayload,
    TacticalExecuteStrikePlanPayload,
    TacticalRemoveAnnotationPayload,
    TacticalSetEngagementPriorityPayload,
    TacticalSetInterceptTargetPayload,
    TacticalStrikePlanStep,
)
from server.models.world import World, spawn_enemy
from server.models.ship import Ship


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_world_with_enemy(
    eid: str = "e1",
    ex: float = 55_000.0,
    ey: float = 50_000.0,
    ai_state: str = "idle",
) -> World:
    world = World()
    enemy = spawn_enemy("scout", ex, ey, eid)
    enemy.ai_state = ai_state
    world.enemies.append(enemy)
    return world


def make_ship(sx: float = 50_000.0, sy: float = 50_000.0) -> Ship:
    ship = Ship()
    ship.x = sx
    ship.y = sy
    return ship


def fresh() -> tuple[World, Ship]:
    """Return a fresh world+ship pair, with tactical state reset."""
    gltac.reset()
    return make_world_with_enemy(), make_ship()


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------


def test_reset_clears_engagement_priorities():
    gltac.reset()
    gltac.set_engagement_priority("e1", "primary")
    gltac.reset()
    assert gltac.get_designations() == {}


def test_reset_clears_intercept_target():
    gltac.reset()
    gltac.set_intercept_target("e1")
    gltac.reset()
    world, ship = make_world_with_enemy(), make_ship()
    assert gltac.calc_intercept(world, ship) is None


def test_reset_clears_annotations():
    gltac.reset()
    gltac.add_annotation("waypoint", 1.0, 2.0)
    gltac.reset()
    assert gltac._annotations == []


def test_reset_clears_strike_plans():
    gltac.reset()
    gltac.create_strike_plan([{"role": "helm", "action": "turn", "offset_s": 0}])
    gltac.reset()
    assert gltac._strike_plans == []


def test_reset_clears_pending_broadcasts():
    gltac.reset()
    gltac._pending_broadcasts.append((["helm"], {"plan_id": "x"}))
    gltac.reset()
    assert gltac.pop_pending_broadcasts() == []


# ---------------------------------------------------------------------------
# Threat assessment
# ---------------------------------------------------------------------------


def test_auto_threat_idle_far_is_low():
    gltac.reset()
    enemy = MagicMock(ai_state="idle", x=70_000.0, y=50_000.0)
    assert gltac.auto_threat_level(enemy, 50_000.0, 50_000.0) == "low"


def test_auto_threat_chase_is_medium():
    gltac.reset()
    enemy = MagicMock(ai_state="chase", x=70_000.0, y=50_000.0)
    assert gltac.auto_threat_level(enemy, 50_000.0, 50_000.0) == "medium"


def test_auto_threat_attack_far_is_high():
    gltac.reset()
    enemy = MagicMock(ai_state="attack", x=58_000.0, y=50_000.0)  # 8k, attack → high
    assert gltac.auto_threat_level(enemy, 50_000.0, 50_000.0) == "high"


def test_auto_threat_attack_very_close_is_critical():
    gltac.reset()
    enemy = MagicMock(ai_state="attack", x=53_000.0, y=50_000.0)  # 3k < 5k threshold
    assert gltac.auto_threat_level(enemy, 50_000.0, 50_000.0) == "critical"


def test_auto_threat_idle_close_is_medium():
    gltac.reset()
    enemy = MagicMock(ai_state="idle", x=60_000.0, y=50_000.0)  # 10k — exactly on boundary
    # dist=10k is NOT < THREAT_HIGH_RANGE(10k), so falls to medium check
    # dist is not < THREAT_MEDIUM_RANGE(18k) AND ai != chase → would be low
    # but dist == 10k: 10k < 10k is False, so "high" condition fails
    # actually 10k < 18k is True → medium
    assert gltac.auto_threat_level(enemy, 50_000.0, 50_000.0) == "medium"


def test_threat_override_takes_precedence():
    gltac.reset()
    enemy = MagicMock(id="e1", ai_state="idle", x=70_000.0, y=50_000.0)
    gltac.set_threat_override("e1", "critical")
    assert gltac.get_threat_level(enemy, 50_000.0, 50_000.0) == "critical"


def test_threat_override_cleared_by_none():
    gltac.reset()
    enemy = MagicMock(id="e1", ai_state="idle", x=70_000.0, y=50_000.0)
    gltac.set_threat_override("e1", "critical")
    gltac.set_threat_override("e1", None)
    # Back to auto: idle + far → low
    assert gltac.get_threat_level(enemy, 50_000.0, 50_000.0) == "low"


# ---------------------------------------------------------------------------
# Engagement priorities
# ---------------------------------------------------------------------------


def test_set_engagement_priority_primary():
    gltac.reset()
    gltac.set_engagement_priority("e1", "primary")
    assert gltac.get_designations()["e1"] == "primary"


def test_set_engagement_priority_secondary():
    gltac.reset()
    gltac.set_engagement_priority("e1", "secondary")
    assert gltac.get_designations()["e1"] == "secondary"


def test_set_engagement_priority_ignore():
    gltac.reset()
    gltac.set_engagement_priority("e1", "ignore")
    assert gltac.get_designations()["e1"] == "ignore"


def test_clear_engagement_priority():
    gltac.reset()
    gltac.set_engagement_priority("e1", "primary")
    gltac.set_engagement_priority("e1", None)
    assert "e1" not in gltac.get_designations()


def test_get_designations_returns_copy():
    gltac.reset()
    gltac.set_engagement_priority("e1", "primary")
    d1 = gltac.get_designations()
    d1["e1"] = "ignore"
    d2 = gltac.get_designations()
    assert d2["e1"] == "primary"


# ---------------------------------------------------------------------------
# Intercept calculation
# ---------------------------------------------------------------------------


def test_intercept_none_when_no_target():
    gltac.reset()
    world, ship = fresh()
    assert gltac.calc_intercept(world, ship) is None


def test_intercept_none_when_target_not_in_world():
    gltac.reset()
    world, ship = make_world_with_enemy(), make_ship()
    gltac.set_intercept_target("MISSING")
    assert gltac.calc_intercept(world, ship) is None


def test_intercept_returns_bearing_and_eta():
    gltac.reset()
    world = make_world_with_enemy(eid="e1", ex=55_000.0, ey=50_000.0)
    ship  = make_ship(sx=50_000.0, sy=50_000.0)
    gltac.set_intercept_target("e1")
    result = gltac.calc_intercept(world, ship)
    assert result is not None
    assert result["target_id"] == "e1"
    assert "bearing" in result
    assert "eta_s" in result
    assert result["eta_s"] > 0


def test_intercept_bearing_east():
    """Enemy due east → bearing ≈ 90°."""
    gltac.reset()
    world = make_world_with_enemy(eid="e1", ex=55_000.0, ey=50_000.0)
    ship  = make_ship(sx=50_000.0, sy=50_000.0)
    gltac.set_intercept_target("e1")
    result = gltac.calc_intercept(world, ship)
    assert abs(result["bearing"] - 90.0) < 1.0


def test_set_intercept_target_none_clears():
    gltac.reset()
    world, ship = make_world_with_enemy(), make_ship()
    gltac.set_intercept_target("e1")
    gltac.set_intercept_target(None)
    assert gltac.calc_intercept(world, ship) is None


# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------


def test_add_annotation_returns_id():
    gltac.reset()
    ann_id = gltac.add_annotation("waypoint", 1000.0, 2000.0)
    assert ann_id.startswith("ann_")


def test_add_annotation_stores_data():
    gltac.reset()
    gltac.add_annotation("waypoint", 1000.0, 2000.0, label="Alpha", text="note")
    assert len(gltac._annotations) == 1
    a = gltac._annotations[0]
    assert a["type"] == "waypoint"
    assert a["label"] == "Alpha"


def test_add_multiple_annotations_unique_ids():
    gltac.reset()
    id1 = gltac.add_annotation("waypoint", 0.0, 0.0)
    id2 = gltac.add_annotation("waypoint", 1.0, 1.0)
    assert id1 != id2


def test_remove_annotation():
    gltac.reset()
    ann_id = gltac.add_annotation("waypoint", 0.0, 0.0)
    gltac.remove_annotation(ann_id)
    assert gltac._annotations == []


def test_remove_nonexistent_annotation_noop():
    gltac.reset()
    gltac.add_annotation("waypoint", 0.0, 0.0)
    gltac.remove_annotation("ann_999")
    assert len(gltac._annotations) == 1


# ---------------------------------------------------------------------------
# Strike plans
# ---------------------------------------------------------------------------


def test_create_strike_plan_returns_id():
    gltac.reset()
    plan_id = gltac.create_strike_plan([
        {"role": "helm", "action": "Turn 270", "offset_s": -5},
    ])
    assert plan_id.startswith("plan_")


def test_create_strike_plan_stored():
    gltac.reset()
    gltac.create_strike_plan([{"role": "helm", "action": "Turn", "offset_s": 0}])
    assert len(gltac._strike_plans) == 1


def test_strike_plan_not_executing_by_default():
    gltac.reset()
    plan_id = gltac.create_strike_plan([{"role": "helm", "action": "Turn", "offset_s": 0}])
    plan = next(p for p in gltac._strike_plans if p["plan_id"] == plan_id)
    assert plan["executing"] is False


def test_execute_strike_plan_returns_true():
    gltac.reset()
    plan_id = gltac.create_strike_plan([{"role": "helm", "action": "Turn", "offset_s": 5}])
    assert gltac.execute_strike_plan(plan_id) is True


def test_execute_strike_plan_marks_executing():
    gltac.reset()
    plan_id = gltac.create_strike_plan([{"role": "helm", "action": "Turn", "offset_s": 5}])
    gltac.execute_strike_plan(plan_id)
    plan = next(p for p in gltac._strike_plans if p["plan_id"] == plan_id)
    assert plan["executing"] is True


def test_execute_missing_plan_returns_false():
    gltac.reset()
    assert gltac.execute_strike_plan("plan_MISSING") is False


def test_execute_already_executing_returns_false():
    gltac.reset()
    plan_id = gltac.create_strike_plan([{"role": "helm", "action": "Turn", "offset_s": 5}])
    gltac.execute_strike_plan(plan_id)
    assert gltac.execute_strike_plan(plan_id) is False


# ---------------------------------------------------------------------------
# tick() — countdown broadcasts
# ---------------------------------------------------------------------------


def test_tick_no_broadcast_when_no_plans():
    gltac.reset()
    world, ship = fresh()
    gltac.tick(world, ship, 0.1)
    assert gltac.pop_pending_broadcasts() == []


def test_tick_no_broadcast_before_plan_executing():
    gltac.reset()
    world, ship = fresh()
    gltac.create_strike_plan([{"role": "helm", "action": "Turn", "offset_s": 5}])
    # Not executing — no broadcasts
    gltac.tick(world, ship, 0.1)
    assert gltac.pop_pending_broadcasts() == []


def test_tick_broadcasts_countdown_for_executing_plan():
    gltac.reset()
    world, ship = fresh()
    plan_id = gltac.create_strike_plan([{"role": "helm", "action": "Turn", "offset_s": 5}])
    gltac.execute_strike_plan(plan_id)
    # Manually set start time to 0 (step at offset 5 should show ~5s remaining)
    plan = gltac._strike_plans[0]
    plan["execute_start_t"] = time.monotonic() - 0.1  # just started
    gltac.tick(world, ship, 0.1)
    broadcasts = gltac.pop_pending_broadcasts()
    assert len(broadcasts) >= 1
    roles, data = broadcasts[0]
    assert "helm" in roles
    assert "plan_id" in data
    assert "seconds_remaining" in data


def test_tick_broadcast_dedupes_by_floor():
    """Second tick with same floor value should NOT push another broadcast."""
    gltac.reset()
    world, ship = fresh()
    plan_id = gltac.create_strike_plan([{"role": "helm", "action": "Turn", "offset_s": 5}])
    gltac.execute_strike_plan(plan_id)
    plan = gltac._strike_plans[0]
    plan["execute_start_t"] = time.monotonic() - 0.1
    gltac.tick(world, ship, 0.1)
    gltac.pop_pending_broadcasts()  # consume first
    gltac.tick(world, ship, 0.01)  # same floor — no new broadcast
    assert gltac.pop_pending_broadcasts() == []


def test_tick_plan_expires_after_last_step():
    gltac.reset()
    world, ship = fresh()
    plan_id = gltac.create_strike_plan([{"role": "helm", "action": "Turn", "offset_s": 0}])
    gltac.execute_strike_plan(plan_id)
    plan = gltac._strike_plans[0]
    # Set start time far in the past so elapsed > offset + EXPIRE
    plan["execute_start_t"] = time.monotonic() - (gltac.PLAN_EXPIRE_AFTER + 1)
    gltac.tick(world, ship, 0.1)
    assert plan["executing"] is False


# ---------------------------------------------------------------------------
# build_state()
# ---------------------------------------------------------------------------


def test_build_state_includes_enemies():
    gltac.reset()
    world, ship = fresh()
    state = gltac.build_state(world, ship)
    assert len(state["enemies"]) == 1
    assert state["enemies"][0]["id"] == "e1"


def test_build_state_includes_threat_level():
    gltac.reset()
    world, ship = fresh()
    state = gltac.build_state(world, ship)
    assert "threat_level" in state["enemies"][0]


def test_build_state_engagement_priority_in_enemies():
    gltac.reset()
    world, ship = fresh()
    gltac.set_engagement_priority("e1", "primary")
    state = gltac.build_state(world, ship)
    assert state["enemies"][0]["engagement_priority"] == "primary"


def test_build_state_annotations():
    gltac.reset()
    world, ship = fresh()
    gltac.add_annotation("waypoint", 1.0, 2.0, label="X")
    state = gltac.build_state(world, ship)
    assert len(state["annotations"]) == 1


def test_build_state_intercept_none_when_no_target():
    gltac.reset()
    world, ship = fresh()
    state = gltac.build_state(world, ship)
    assert state["intercept_target_id"] is None
    assert state["intercept_bearing"] is None


def test_build_state_intercept_bearing_when_target_set():
    gltac.reset()
    world, ship = fresh()
    gltac.set_intercept_target("e1")
    state = gltac.build_state(world, ship)
    assert state["intercept_bearing"] is not None


def test_build_state_strike_plans():
    gltac.reset()
    world, ship = fresh()
    gltac.create_strike_plan([{"role": "weapons", "action": "Fire", "offset_s": 0}])
    state = gltac.build_state(world, ship)
    assert len(state["strike_plans"]) == 1


def test_build_state_steps_no_internal_keys():
    """Steps in build_state output should not contain '_last_floor' key."""
    gltac.reset()
    world, ship = fresh()
    plan_id = gltac.create_strike_plan([{"role": "helm", "action": "Turn", "offset_s": 5}])
    gltac.execute_strike_plan(plan_id)
    gltac._strike_plans[0]["steps"][0]["_last_floor"] = 4
    state = gltac.build_state(world, ship)
    for step in state["strike_plans"][0]["steps"]:
        assert "_last_floor" not in step


# ---------------------------------------------------------------------------
# Payload schemas
# ---------------------------------------------------------------------------


def test_payload_set_engagement_priority_valid():
    p = TacticalSetEngagementPriorityPayload(entity_id="e1", priority="primary")
    assert p.priority == "primary"


def test_payload_set_engagement_priority_null():
    p = TacticalSetEngagementPriorityPayload(entity_id="e1", priority=None)
    assert p.priority is None


def test_payload_set_engagement_priority_invalid():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        TacticalSetEngagementPriorityPayload(entity_id="e1", priority="boss")


def test_payload_set_intercept_target():
    p = TacticalSetInterceptTargetPayload(entity_id="e1")
    assert p.entity_id == "e1"


def test_payload_set_intercept_target_none():
    p = TacticalSetInterceptTargetPayload(entity_id=None)
    assert p.entity_id is None


def test_payload_add_annotation():
    p = TacticalAddAnnotationPayload(annotation_type="waypoint", x=1.0, y=2.0, label="WPT")
    assert p.annotation_type == "waypoint"
    assert p.x == 1.0


def test_payload_remove_annotation():
    p = TacticalRemoveAnnotationPayload(annotation_id="ann_1")
    assert p.annotation_id == "ann_1"


def test_payload_strike_plan_step():
    s = TacticalStrikePlanStep(role="helm", action="Turn 270", offset_s=-5.0)
    assert s.role == "helm"
    assert s.offset_s == -5.0


def test_payload_create_strike_plan():
    p = TacticalCreateStrikePlanPayload(steps=[
        TacticalStrikePlanStep(role="helm", action="Turn", offset_s=0),
        TacticalStrikePlanStep(role="weapons", action="Fire", offset_s=2),
    ])
    assert len(p.steps) == 2


def test_payload_execute_strike_plan():
    p = TacticalExecuteStrikePlanPayload(plan_id="plan_1")
    assert p.plan_id == "plan_1"


# ---------------------------------------------------------------------------
# Handler integration
# ---------------------------------------------------------------------------


def fresh_handler():
    """Return (sender_mock, queue) pair for handler tests."""
    sender = AsyncMock()
    sender.send = AsyncMock()
    queue: asyncio.Queue = asyncio.Queue()
    return sender, queue


@pytest.mark.asyncio
async def test_handler_valid_set_engagement_priority():
    from server.tactical import init, handle_tactical_message
    from server.models.messages import Message
    sender, queue = fresh_handler()
    init(sender, queue)
    msg = Message.build("tactical.set_engagement_priority", {"entity_id": "e1", "priority": "primary"})
    await handle_tactical_message("conn1", msg)
    assert not queue.empty()
    msg_type, payload = await queue.get()
    assert msg_type == "tactical.set_engagement_priority"
    assert isinstance(payload, TacticalSetEngagementPriorityPayload)


@pytest.mark.asyncio
async def test_handler_invalid_payload_sends_error():
    from server.tactical import init, handle_tactical_message
    from server.models.messages import Message
    sender, queue = fresh_handler()
    init(sender, queue)
    msg = Message.build("tactical.set_engagement_priority", {"entity_id": "e1", "priority": "INVALID"})
    await handle_tactical_message("conn1", msg)
    sender.send.assert_called_once()
    sent_msg = sender.send.call_args[0][1]
    assert sent_msg.type == "error.validation"


@pytest.mark.asyncio
async def test_handler_unknown_message_type_no_queue():
    from server.tactical import init, handle_tactical_message
    from server.models.messages import Message
    sender, queue = fresh_handler()
    init(sender, queue)
    msg = Message.build("tactical.unknown_thing", {})
    await handle_tactical_message("conn1", msg)
    assert queue.empty()


@pytest.mark.asyncio
async def test_handler_create_strike_plan():
    from server.tactical import init, handle_tactical_message
    from server.models.messages import Message
    sender, queue = fresh_handler()
    init(sender, queue)
    msg = Message.build("tactical.create_strike_plan", {
        "steps": [{"role": "helm", "action": "Turn", "offset_s": 0}]
    })
    await handle_tactical_message("conn1", msg)
    assert not queue.empty()
