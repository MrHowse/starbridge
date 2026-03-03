"""Tests for Security station data models.

Covers:
  server/models/security.py  — MarineSquad, Intruder, constants, is_intruder_visible
  server/models/interior.py  — ShipInterior.marine_squads / .intruders fields
"""
from __future__ import annotations

import pytest

from server.models.security import (
    AP_COST_DOOR,
    AP_COST_MOVE,
    AP_MAX,
    AP_REGEN_PER_TICK,
    INTRUDER_MOVE_INTERVAL,
    INTRUDER_DAMAGE_PER_TICK,
    MARINE_DAMAGE_PER_TICK,
    SENSOR_FOW_THRESHOLD,
    SQUAD_CASUALTY_THRESHOLD,
    Intruder,
    MarineSquad,
    is_intruder_visible,
)
from server.models.interior import ShipInterior, make_default_interior


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_squad(room_id: str = "bridge", ap: float = AP_MAX, health: float = 100.0,
               count: int = 4) -> MarineSquad:
    return MarineSquad(id="squad_1", room_id=room_id, health=health,
                       action_points=ap, count=count)


def make_intruder(room_id: str = "cargo_hold", move_timer: int = INTRUDER_MOVE_INTERVAL,
                  objective_id: str = "bridge") -> Intruder:
    return Intruder(id="intruder_1", room_id=room_id, objective_id=objective_id,
                    move_timer=move_timer)


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------


def test_ap_max():
    assert AP_MAX == pytest.approx(10.0)


def test_ap_regen_per_tick():
    assert AP_REGEN_PER_TICK == pytest.approx(0.2)


def test_ap_cost_move():
    assert AP_COST_MOVE == 3


def test_ap_cost_door():
    assert AP_COST_DOOR == 2


def test_intruder_move_interval():
    assert INTRUDER_MOVE_INTERVAL == 30


def test_sensor_fow_threshold():
    assert SENSOR_FOW_THRESHOLD == pytest.approx(0.5)


def test_squad_casualty_threshold():
    assert SQUAD_CASUALTY_THRESHOLD == pytest.approx(25.0)


def test_ap_pool_fills_in_correct_ticks():
    """AP_MAX / AP_REGEN_PER_TICK should be 50 ticks = 5 seconds at 10 Hz."""
    ticks_to_fill = AP_MAX / AP_REGEN_PER_TICK
    assert ticks_to_fill == pytest.approx(50.0)


def test_move_from_empty_costs_correct_ticks():
    """From 0 AP, moving costs AP_COST_MOVE / AP_REGEN_PER_TICK ticks = 15."""
    ticks = AP_COST_MOVE / AP_REGEN_PER_TICK
    assert ticks == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# MarineSquad — AP mechanics
# ---------------------------------------------------------------------------


def test_squad_regen_ap_increments():
    squad = make_squad(ap=0.0)
    squad.regen_ap()
    assert squad.action_points == pytest.approx(AP_REGEN_PER_TICK)


def test_squad_regen_ap_caps_at_max():
    squad = make_squad(ap=AP_MAX - 0.05)
    squad.regen_ap()
    assert squad.action_points == pytest.approx(AP_MAX)


def test_squad_regen_does_not_exceed_max():
    squad = make_squad(ap=AP_MAX)
    squad.regen_ap()
    assert squad.action_points == pytest.approx(AP_MAX)


def test_squad_can_move_when_enough_ap():
    squad = make_squad(ap=float(AP_COST_MOVE))
    assert squad.can_move() is True


def test_squad_cannot_move_when_insufficient_ap():
    squad = make_squad(ap=float(AP_COST_MOVE) - 0.1)
    assert squad.can_move() is False


def test_squad_deduct_move_ap():
    squad = make_squad(ap=AP_MAX)
    squad.deduct_move_ap()
    assert squad.action_points == pytest.approx(AP_MAX - AP_COST_MOVE)


def test_squad_can_seal_door_when_enough_ap():
    squad = make_squad(ap=float(AP_COST_DOOR))
    assert squad.can_seal_door() is True


def test_squad_cannot_seal_door_when_insufficient_ap():
    squad = make_squad(ap=float(AP_COST_DOOR) - 0.1)
    assert squad.can_seal_door() is False


def test_squad_deduct_door_ap():
    squad = make_squad(ap=AP_MAX)
    squad.deduct_door_ap()
    assert squad.action_points == pytest.approx(AP_MAX - AP_COST_DOOR)


def test_squad_multiple_regen_fills_to_move():
    """After 15 ticks of regen from 0, squad can move."""
    squad = make_squad(ap=0.0)
    for _ in range(15):
        squad.regen_ap()
    assert squad.can_move()


# ---------------------------------------------------------------------------
# MarineSquad — combat and casualties
# ---------------------------------------------------------------------------


def test_squad_take_damage_reduces_health():
    squad = make_squad(health=100.0)
    squad.take_damage(10.0)
    assert squad.health == pytest.approx(90.0)


def test_squad_take_damage_floor_at_zero():
    squad = make_squad(health=5.0)
    squad.take_damage(100.0)
    assert squad.health == pytest.approx(0.0)


def test_squad_casualty_triggers_when_health_drops_below_threshold():
    squad = make_squad(health=100.0, count=4)
    # Drop health just below threshold in one hit.
    damage = 100.0 - SQUAD_CASUALTY_THRESHOLD + 1.0
    result = squad.take_damage(damage)
    assert result is True
    assert squad.count == 3


def test_squad_casualty_only_triggers_once_per_dip():
    """Repeated hits below threshold don't generate repeated casualties."""
    squad = make_squad(health=100.0, count=4)
    # First drop below threshold.
    squad.take_damage(100.0 - SQUAD_CASUALTY_THRESHOLD + 1.0)
    assert squad.count == 3
    # Second hit while still below threshold — no additional casualty.
    result = squad.take_damage(1.0)
    assert result is False
    assert squad.count == 3


def test_squad_casualty_resets_when_health_recovers():
    """After health recovers above threshold, the next dip causes another casualty."""
    squad = make_squad(health=100.0, count=4)
    # Dip below threshold.
    squad.take_damage(100.0 - SQUAD_CASUALTY_THRESHOLD + 1.0)
    assert squad.count == 3

    # Restore health above threshold (simulate healing).
    squad.health = 80.0
    squad.take_damage(0.0)  # Force health update path (health > threshold).

    # Dip below again.
    result = squad.take_damage(80.0 - SQUAD_CASUALTY_THRESHOLD + 1.0)
    assert result is True
    assert squad.count == 2


def test_squad_casualty_does_not_go_below_zero_count():
    squad = make_squad(health=30.0, count=1)
    squad.take_damage(30.0 - SQUAD_CASUALTY_THRESHOLD + 1.0)
    # Trigger again — count was already at 0 from prior call.
    # Ensure we don't get to count = -1 even via _casualty_pending reset.
    assert squad.count >= 0


def test_squad_is_eliminated_when_count_zero():
    squad = make_squad(count=0)
    assert squad.is_eliminated() is True


def test_squad_is_not_eliminated_when_count_positive():
    squad = make_squad(count=1)
    assert squad.is_eliminated() is False


# ---------------------------------------------------------------------------
# Intruder — move timer
# ---------------------------------------------------------------------------


def test_intruder_move_timer_starts_at_interval():
    intruder = make_intruder()
    assert intruder.move_timer == INTRUDER_MOVE_INTERVAL


def test_intruder_tick_move_timer_decrements():
    intruder = make_intruder(move_timer=10)
    intruder.tick_move_timer()
    assert intruder.move_timer == 9


def test_intruder_tick_move_timer_floors_at_zero():
    intruder = make_intruder(move_timer=0)
    intruder.tick_move_timer()
    assert intruder.move_timer == 0


def test_intruder_is_ready_to_move_when_timer_zero():
    intruder = make_intruder(move_timer=0)
    assert intruder.is_ready_to_move() is True


def test_intruder_is_not_ready_to_move_when_timer_positive():
    intruder = make_intruder(move_timer=5)
    assert intruder.is_ready_to_move() is False


def test_intruder_reset_move_timer():
    intruder = make_intruder(move_timer=0)
    intruder.reset_move_timer()
    assert intruder.move_timer == INTRUDER_MOVE_INTERVAL


def test_intruder_timer_reaches_zero_after_interval_ticks():
    intruder = make_intruder()
    for _ in range(INTRUDER_MOVE_INTERVAL):
        intruder.tick_move_timer()
    assert intruder.is_ready_to_move()


# ---------------------------------------------------------------------------
# Intruder — combat
# ---------------------------------------------------------------------------


def test_intruder_take_damage_reduces_health():
    intruder = make_intruder()
    intruder.take_damage(20.0)
    assert intruder.health == pytest.approx(80.0)


def test_intruder_take_damage_floor_at_zero():
    intruder = make_intruder()
    intruder.take_damage(200.0)
    assert intruder.health == pytest.approx(0.0)


def test_intruder_is_defeated_at_zero_health():
    intruder = make_intruder()
    intruder.health = 0.0
    assert intruder.is_defeated() is True


def test_intruder_is_not_defeated_with_health():
    intruder = make_intruder()
    assert intruder.is_defeated() is False


def test_intruder_take_damage_until_defeated():
    intruder = make_intruder()
    intruder.take_damage(100.0)
    assert intruder.is_defeated()


# ---------------------------------------------------------------------------
# Intruder pathfinding via ShipInterior
# ---------------------------------------------------------------------------


def test_intruder_can_use_ship_find_path():
    """Intruder can navigate from cargo hold to bridge using interior pathfinding."""
    interior = make_default_interior()
    path = interior.find_path("cargo_hold", "bridge")
    assert len(path) > 0
    assert path[0] == "cargo_hold"
    assert path[-1] == "bridge"


def test_intruder_path_blocked_by_sealed_door():
    """Sealing a room blocks the path through it."""
    interior = make_default_interior()
    # Seal the engine room (key vertical corridor node at row 4).
    interior.rooms["engine_room"].door_sealed = True
    path = interior.find_path("cargo_hold", "bridge")
    # The direct path goes cargo_hold → auxiliary_power → engine_room → surgery → ...
    # With engine_room sealed, must route differently or may find no path.
    # Either way, engine_room must NOT appear in the path.
    assert "engine_room" not in path


def test_intruder_path_blocked_by_decompressed_room():
    """Decompressed rooms block BFS traversal."""
    interior = make_default_interior()
    interior.rooms["surgery"].state = "decompressed"
    path = interior.find_path("cargo_hold", "bridge")
    assert "surgery" not in path


# ---------------------------------------------------------------------------
# Fog-of-war — is_intruder_visible
# ---------------------------------------------------------------------------


def test_intruder_visible_when_squad_in_same_room():
    intruder = make_intruder(room_id="cargo_hold")
    squad = make_squad(room_id="cargo_hold")
    assert is_intruder_visible(intruder, [squad], sensor_efficiency=0.0) is True


def test_intruder_invisible_when_no_squad_and_low_sensors():
    intruder = make_intruder(room_id="cargo_hold")
    squad = make_squad(room_id="bridge")  # Different room
    assert is_intruder_visible(intruder, [squad], sensor_efficiency=0.3) is False


def test_intruder_visible_when_sensors_above_threshold():
    intruder = make_intruder(room_id="cargo_hold")
    squad = make_squad(room_id="bridge")  # Different room
    assert is_intruder_visible(intruder, [squad], sensor_efficiency=0.5) is True


def test_intruder_visible_with_no_squads_but_good_sensors():
    intruder = make_intruder(room_id="cargo_hold")
    assert is_intruder_visible(intruder, [], sensor_efficiency=0.8) is True


def test_intruder_invisible_with_no_squads_and_poor_sensors():
    intruder = make_intruder(room_id="cargo_hold")
    assert is_intruder_visible(intruder, [], sensor_efficiency=0.4) is False


def test_intruder_visible_at_exact_threshold():
    """Threshold is inclusive: >= 0.5 means visible."""
    intruder = make_intruder(room_id="cargo_hold")
    assert is_intruder_visible(intruder, [], sensor_efficiency=SENSOR_FOW_THRESHOLD) is True


def test_intruder_invisible_just_below_threshold():
    intruder = make_intruder(room_id="cargo_hold")
    assert is_intruder_visible(intruder, [], sensor_efficiency=SENSOR_FOW_THRESHOLD - 0.01) is False


def test_multiple_squads_any_same_room_triggers_visibility():
    intruder = make_intruder(room_id="cargo_hold")
    squads = [
        make_squad(room_id="bridge"),
        MarineSquad(id="squad_2", room_id="cargo_hold"),  # co-located
    ]
    assert is_intruder_visible(intruder, squads, sensor_efficiency=0.0) is True


# ---------------------------------------------------------------------------
# B.2.3.4: Smoke reduces sensor detection
# ---------------------------------------------------------------------------


def test_smoke_halves_sensor_detection():
    """Intruder in smoke room: sensor eff 0.8 → effective 0.4 < 0.5 → invisible."""
    intruder = make_intruder(room_id="cargo_hold")
    smoke = frozenset({"cargo_hold"})
    # 0.8 * 0.5 = 0.4, below threshold of 0.5.
    assert is_intruder_visible(intruder, [], sensor_efficiency=0.8, smoke_rooms=smoke) is False


def test_smoke_no_effect_on_high_sensors():
    """Intruder in smoke room: sensor eff 1.0 → effective 0.5 = threshold → visible."""
    intruder = make_intruder(room_id="cargo_hold")
    smoke = frozenset({"cargo_hold"})
    # 1.0 * 0.5 = 0.5, exactly at threshold → visible.
    assert is_intruder_visible(intruder, [], sensor_efficiency=1.0, smoke_rooms=smoke) is True


def test_marine_overrides_smoke():
    """Marine in same room as intruder in smoke → always visible."""
    intruder = make_intruder(room_id="cargo_hold")
    squad = make_squad(room_id="cargo_hold")
    smoke = frozenset({"cargo_hold"})
    # Even with sensors at 0 and smoke, marine presence overrides.
    assert is_intruder_visible(intruder, [squad], sensor_efficiency=0.0, smoke_rooms=smoke) is True


def test_no_smoke_normal_detection():
    """Intruder not in smoke room → normal sensor threshold applies."""
    intruder = make_intruder(room_id="cargo_hold")
    smoke = frozenset({"bridge"})  # Smoke in a different room.
    # 0.6 >= 0.5 → visible (no halving since intruder not in smoke).
    assert is_intruder_visible(intruder, [], sensor_efficiency=0.6, smoke_rooms=smoke) is True


# ---------------------------------------------------------------------------
# ShipInterior — marine_squads and intruders fields
# ---------------------------------------------------------------------------


def test_default_interior_has_empty_marine_squads():
    interior = make_default_interior()
    assert interior.marine_squads == []


def test_default_interior_has_empty_intruders():
    interior = make_default_interior()
    assert interior.intruders == []


def test_interior_can_hold_marine_squad():
    interior = make_default_interior()
    squad = make_squad(room_id="bridge")
    interior.marine_squads.append(squad)
    assert len(interior.marine_squads) == 1
    assert interior.marine_squads[0].id == "squad_1"


def test_interior_can_hold_intruder():
    interior = make_default_interior()
    intruder = make_intruder(room_id="cargo_hold")
    interior.intruders.append(intruder)
    assert len(interior.intruders) == 1
    assert interior.intruders[0].id == "intruder_1"


def test_interior_squad_room_is_valid_room():
    """Squad's room_id should correspond to an actual room in the interior."""
    interior = make_default_interior()
    squad = make_squad(room_id="bridge")
    interior.marine_squads.append(squad)
    assert squad.room_id in interior.rooms


def test_interior_intruder_objective_is_valid_room():
    """Intruder's objective_id should correspond to an actual room in the interior."""
    interior = make_default_interior()
    intruder = make_intruder(room_id="cargo_hold", objective_id="bridge")
    interior.intruders.append(intruder)
    assert intruder.objective_id in interior.rooms


def test_new_ship_interior_has_empty_lists():
    """Directly constructed ShipInterior also gets empty lists."""
    interior = ShipInterior()
    assert interior.marine_squads == []
    assert interior.intruders == []


def test_two_interiors_have_independent_lists():
    """Each ShipInterior instance must have its own list (no shared default mutable)."""
    interior_a = make_default_interior()
    interior_b = make_default_interior()
    interior_a.marine_squads.append(make_squad(room_id="bridge"))
    assert interior_b.marine_squads == []
