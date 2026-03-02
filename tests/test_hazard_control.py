"""Tests for server/game_loop_hazard_control.py — room damage, fire spread, DCT dispatch."""
from __future__ import annotations

import pytest

import server.game_loop_hazard_control as glhc
from server.models.interior import make_default_interior
from server.models.messages import EngineeringDispatchDCTPayload, EngineeringCancelDCTPayload
from server.models.messages.base import validate_payload, Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh_interior():
    """Return a fresh default interior with all rooms normal."""
    return make_default_interior()


def setup_function():
    """Reset damage-control state before each test."""
    glhc.reset()


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------


def test_reset_clears_active_dcts():
    interior = fresh_interior()
    room_id = next(iter(interior.rooms))
    interior.rooms[room_id].state = "damaged"
    glhc.dispatch_dct(room_id, interior)
    assert glhc._active_dcts  # DCT was added

    glhc.reset()
    assert not glhc._active_dcts


def test_reset_clears_pending_hull_damage():
    interior = fresh_interior()
    # Accumulate some damage without crossing threshold.
    glhc.apply_hull_damage(3.0, interior)
    assert glhc._pending_hull_damage == pytest.approx(3.0)

    glhc.reset()
    assert glhc._pending_hull_damage == pytest.approx(0.0)


def test_reset_resets_fire_spread_timer():
    interior = fresh_interior()
    # Advance the timer.
    glhc.tick(interior, 10.0)
    glhc.reset()
    assert glhc._fire_spread_timer == pytest.approx(glhc.FIRE_SPREAD_INTERVAL)


# ---------------------------------------------------------------------------
# apply_hull_damage()
# ---------------------------------------------------------------------------


def test_apply_hull_damage_below_threshold_no_room_change():
    interior = fresh_interior()
    all_normal = all(r.state == "normal" for r in interior.rooms.values())
    assert all_normal

    glhc.apply_hull_damage(glhc.HULL_DAMAGE_THRESHOLD - 0.01, interior)

    still_all_normal = all(r.state == "normal" for r in interior.rooms.values())
    assert still_all_normal


def test_apply_hull_damage_at_threshold_triggers_event():
    interior = fresh_interior()
    # Fix the RNG to always pick 'damaged' (not fire).
    glhc._rng.seed(0)
    glhc.apply_hull_damage(glhc.HULL_DAMAGE_THRESHOLD, interior)

    non_normal = [r for r in interior.rooms.values() if r.state != "normal"]
    assert len(non_normal) >= 1


def test_apply_hull_damage_zero_no_change():
    interior = fresh_interior()
    glhc.apply_hull_damage(0.0, interior)
    assert glhc._pending_hull_damage == pytest.approx(0.0)
    assert all(r.state == "normal" for r in interior.rooms.values())


def test_apply_hull_damage_negative_no_change():
    interior = fresh_interior()
    glhc.apply_hull_damage(-5.0, interior)
    assert glhc._pending_hull_damage == pytest.approx(0.0)


def test_apply_hull_damage_accumulates_across_calls():
    interior = fresh_interior()
    half = glhc.HULL_DAMAGE_THRESHOLD / 2
    glhc.apply_hull_damage(half, interior)
    assert all(r.state == "normal" for r in interior.rooms.values())

    # Second call crosses threshold.
    glhc._rng.seed(42)
    glhc.apply_hull_damage(half + 0.01, interior)
    non_normal = [r for r in interior.rooms.values() if r.state != "normal"]
    assert len(non_normal) >= 1


def test_apply_hull_damage_large_triggers_multiple_events():
    interior = fresh_interior()
    glhc._rng.seed(7)
    # 3× threshold should trigger 3 events (rooms may overlap, so just check ≥ 1 non-normal).
    glhc.apply_hull_damage(glhc.HULL_DAMAGE_THRESHOLD * 3, interior)
    non_normal = [r for r in interior.rooms.values() if r.state != "normal"]
    assert len(non_normal) >= 1


# ---------------------------------------------------------------------------
# Room state transitions via _trigger_room_event()
# ---------------------------------------------------------------------------


def test_trigger_event_sets_normal_to_damaged_or_fire():
    interior = fresh_interior()
    glhc._rng.seed(0)
    glhc.apply_hull_damage(glhc.HULL_DAMAGE_THRESHOLD, interior)
    states = {r.state for r in interior.rooms.values()}
    assert states & {"damaged", "fire"}


def test_trigger_event_escalates_damaged_room_to_fire():
    interior = fresh_interior()
    # Mark a specific room as damaged.
    room_id = list(interior.rooms.keys())[0]
    interior.rooms[room_id].state = "damaged"

    # Seed so the first eligible room chosen is the damaged one and escalation fires.
    # We rely on statistical likelihood — run enough times to hit the escalation.
    fired = False
    for seed in range(100):
        glhc.reset()
        interior.rooms[room_id].state = "damaged"
        glhc._rng.seed(seed)
        # Make all other rooms decompressed so only our room is eligible.
        for rid, room in interior.rooms.items():
            if rid != room_id:
                room.state = "decompressed"
        glhc.apply_hull_damage(glhc.HULL_DAMAGE_THRESHOLD, interior)
        if interior.rooms[room_id].state == "fire":
            fired = True
            break
        # Restore for next iteration.
        for rid, room in interior.rooms.items():
            room.state = "normal"

    assert fired, "Expected damaged room to escalate to fire in at least one seed"


# ---------------------------------------------------------------------------
# dispatch_dct() / cancel_dct()
# ---------------------------------------------------------------------------


def test_dispatch_dct_on_damaged_room_returns_true():
    interior = fresh_interior()
    room_id = list(interior.rooms.keys())[0]
    interior.rooms[room_id].state = "damaged"
    result = glhc.dispatch_dct(room_id, interior)
    assert result is True
    assert room_id in glhc._active_dcts


def test_dispatch_dct_on_fire_room_returns_true():
    interior = fresh_interior()
    room_id = list(interior.rooms.keys())[0]
    interior.rooms[room_id].state = "fire"
    assert glhc.dispatch_dct(room_id, interior) is True


def test_dispatch_dct_on_normal_room_returns_false():
    interior = fresh_interior()
    room_id = list(interior.rooms.keys())[0]
    # Room is normal by default.
    result = glhc.dispatch_dct(room_id, interior)
    assert result is False
    assert room_id not in glhc._active_dcts


def test_dispatch_dct_on_decompressed_room_returns_false():
    interior = fresh_interior()
    room_id = list(interior.rooms.keys())[0]
    interior.rooms[room_id].state = "decompressed"
    assert glhc.dispatch_dct(room_id, interior) is False


def test_dispatch_dct_on_unknown_room_returns_false():
    interior = fresh_interior()
    assert glhc.dispatch_dct("nonexistent_room", interior) is False


def test_dispatch_dct_preserves_progress():
    interior = fresh_interior()
    room_id = list(interior.rooms.keys())[0]
    interior.rooms[room_id].state = "fire"
    glhc.dispatch_dct(room_id, interior)
    # Simulate partial progress.
    glhc._active_dcts[room_id] = 4.0
    # Dispatching again should NOT reset progress.
    glhc.dispatch_dct(room_id, interior)
    assert glhc._active_dcts[room_id] == pytest.approx(4.0)


def test_cancel_dct_active_returns_true():
    interior = fresh_interior()
    room_id = list(interior.rooms.keys())[0]
    interior.rooms[room_id].state = "damaged"
    glhc.dispatch_dct(room_id, interior)
    assert glhc.cancel_dct(room_id) is True
    assert room_id not in glhc._active_dcts


def test_cancel_dct_inactive_returns_false():
    assert glhc.cancel_dct("nonexistent_room") is False


# ---------------------------------------------------------------------------
# tick() — DCT repair progression
# ---------------------------------------------------------------------------


def test_tick_advances_dct_elapsed_time():
    interior = fresh_interior()
    room_id = list(interior.rooms.keys())[0]
    interior.rooms[room_id].state = "damaged"
    glhc.dispatch_dct(room_id, interior)

    glhc.tick(interior, 1.0)
    assert glhc._active_dcts[room_id] == pytest.approx(1.0)


def test_dct_reduces_fire_to_damaged_after_duration():
    interior = fresh_interior()
    room_id = list(interior.rooms.keys())[0]
    interior.rooms[room_id].state = "fire"
    glhc.dispatch_dct(room_id, interior)

    # Tick just over the repair duration.
    glhc.tick(interior, glhc.DCT_REPAIR_DURATION + 0.01)

    assert interior.rooms[room_id].state == "damaged"
    # Timer should have reset for next level, not be removed.
    assert room_id in glhc._active_dcts
    assert glhc._active_dcts[room_id] == pytest.approx(0.0)


def test_dct_reduces_damaged_to_normal_after_duration():
    interior = fresh_interior()
    room_id = list(interior.rooms.keys())[0]
    interior.rooms[room_id].state = "damaged"
    glhc.dispatch_dct(room_id, interior)

    glhc.tick(interior, glhc.DCT_REPAIR_DURATION + 0.01)

    assert interior.rooms[room_id].state == "normal"
    # DCT should be auto-cancelled once room is normal.
    assert room_id not in glhc._active_dcts


def test_dct_auto_cancels_when_room_already_normal():
    interior = fresh_interior()
    room_id = list(interior.rooms.keys())[0]
    interior.rooms[room_id].state = "damaged"
    glhc.dispatch_dct(room_id, interior)

    # Room repaired externally before DCT completes.
    interior.rooms[room_id].state = "normal"
    glhc.tick(interior, 0.1)

    assert room_id not in glhc._active_dcts


# ---------------------------------------------------------------------------
# tick() — fire spread
# ---------------------------------------------------------------------------


def test_fire_spread_timer_decrements():
    interior = fresh_interior()
    initial = glhc._fire_spread_timer
    glhc.tick(interior, 5.0)
    assert glhc._fire_spread_timer == pytest.approx(initial - 5.0)


def test_fire_spread_resets_timer_after_expiry():
    interior = fresh_interior()
    glhc.tick(interior, glhc.FIRE_SPREAD_INTERVAL + 0.01)
    assert glhc._fire_spread_timer == pytest.approx(glhc.FIRE_SPREAD_INTERVAL)


def test_fire_spread_ignites_adjacent_room():
    interior = fresh_interior()
    # Find a room that has connections so spread can happen.
    fire_room = None
    for room in interior.rooms.values():
        if room.connections:
            fire_room = room
            break
    assert fire_room is not None

    fire_room.state = "fire"
    glhc._rng.seed(0)

    # Advance past the spread timer.
    glhc.tick(interior, glhc.FIRE_SPREAD_INTERVAL + 0.01)

    # At least one adjacent room should be non-normal.
    adj_states = {interior.rooms[rid].state for rid in fire_room.connections if rid in interior.rooms}
    assert adj_states & {"damaged", "fire"}, "Fire should have spread to an adjacent room"


# ---------------------------------------------------------------------------
# build_dc_state()
# ---------------------------------------------------------------------------


def test_build_dc_state_empty_when_all_normal():
    interior = fresh_interior()
    state = glhc.build_dc_state(interior)
    assert state["rooms"] == {}
    assert state["active_dcts"] == {}


def test_build_dc_state_includes_damaged_rooms():
    interior = fresh_interior()
    room_id = list(interior.rooms.keys())[0]
    interior.rooms[room_id].state = "fire"

    state = glhc.build_dc_state(interior)
    assert room_id in state["rooms"]
    assert state["rooms"][room_id]["state"] == "fire"
    assert "name" in state["rooms"][room_id]
    assert "deck" in state["rooms"][room_id]


def test_build_dc_state_excludes_normal_rooms():
    interior = fresh_interior()
    ids = list(interior.rooms.keys())
    interior.rooms[ids[0]].state = "damaged"

    state = glhc.build_dc_state(interior)
    # Only the damaged room should appear.
    assert len(state["rooms"]) == 1
    assert ids[0] in state["rooms"]


def test_build_dc_state_includes_active_dct_progress():
    interior = fresh_interior()
    room_id = list(interior.rooms.keys())[0]
    interior.rooms[room_id].state = "damaged"
    glhc.dispatch_dct(room_id, interior)
    glhc._active_dcts[room_id] = glhc.DCT_REPAIR_DURATION / 2  # 50 % progress

    state = glhc.build_dc_state(interior)
    assert state["active_dcts"][room_id] == pytest.approx(0.5)


def test_build_dc_state_dct_progress_capped_at_one():
    interior = fresh_interior()
    room_id = list(interior.rooms.keys())[0]
    interior.rooms[room_id].state = "damaged"
    glhc.dispatch_dct(room_id, interior)
    glhc._active_dcts[room_id] = glhc.DCT_REPAIR_DURATION * 2  # over 100 %

    state = glhc.build_dc_state(interior)
    assert state["active_dcts"][room_id] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Message payload validation
# ---------------------------------------------------------------------------


def test_dispatch_dct_payload_validates_correctly():
    msg = Message.build("engineering.dispatch_dct", {"room_id": "bridge_0"})
    payload = validate_payload(msg)
    assert isinstance(payload, EngineeringDispatchDCTPayload)
    assert payload.room_id == "bridge_0"


def test_cancel_dct_payload_validates_correctly():
    msg = Message.build("engineering.cancel_dct", {"room_id": "engine_room"})
    payload = validate_payload(msg)
    assert isinstance(payload, EngineeringCancelDCTPayload)
    assert payload.room_id == "engine_room"


def test_dispatch_dct_payload_missing_room_id_raises():
    from pydantic import ValidationError
    msg = Message.build("engineering.dispatch_dct", {})
    with pytest.raises(ValidationError):
        validate_payload(msg)
