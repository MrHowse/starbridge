"""
Tests for v0.04e Captain station system override mechanics.

Tests the _captain_offline flag on ShipSystem, the captain.system_override
message handler, and the system_overrides field in ship.state.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from server.models.ship import Ship, ShipSystem
from server.models.messages import Message


# ---------------------------------------------------------------------------
# ShipSystem._captain_offline unit tests
# ---------------------------------------------------------------------------


def test_system_offline_flag_defaults_false():
    sys = ShipSystem("engines")
    assert sys._captain_offline is False


def test_system_efficiency_normal_when_online():
    sys = ShipSystem("engines", power=100.0, health=100.0)
    assert sys.efficiency == pytest.approx(1.0)


def test_system_efficiency_zero_when_captain_offline():
    sys = ShipSystem("engines", power=100.0, health=100.0)
    sys._captain_offline = True
    assert sys.efficiency == 0.0


def test_system_offline_ignores_power_level():
    sys = ShipSystem("beams", power=150.0, health=100.0)
    sys._captain_offline = True
    assert sys.efficiency == 0.0


def test_system_offline_ignores_health():
    sys = ShipSystem("shields", power=100.0, health=50.0)
    sys._captain_offline = True
    assert sys.efficiency == 0.0


def test_system_offline_ignores_crew_factor():
    sys = ShipSystem("sensors", power=100.0, health=100.0)
    sys._crew_factor = 0.8
    sys._captain_offline = True
    assert sys.efficiency == 0.0


def test_restore_online_resumes_normal_efficiency():
    sys = ShipSystem("engines", power=80.0, health=100.0)
    sys._captain_offline = True
    assert sys.efficiency == 0.0
    sys._captain_offline = False
    assert sys.efficiency == pytest.approx(0.8)


def test_restore_online_respects_health():
    sys = ShipSystem("engines", power=100.0, health=60.0)
    sys._captain_offline = True
    sys._captain_offline = False
    assert sys.efficiency == pytest.approx(0.6)


def test_restore_online_respects_crew_factor():
    sys = ShipSystem("engines", power=100.0, health=100.0)
    sys._crew_factor = 0.5
    sys._captain_offline = True
    sys._captain_offline = False
    assert sys.efficiency == pytest.approx(0.5)


def test_all_default_systems_support_offline():
    ship = Ship()
    for name, sys in ship.systems.items():
        sys._captain_offline = True
        assert sys.efficiency == 0.0, f"{name} should be 0 when offline"
        sys._captain_offline = False


# ---------------------------------------------------------------------------
# captain.py handler tests
# ---------------------------------------------------------------------------


def _make_captain_setup():
    """Return (manager, ship) ready for captain.py tests."""
    import server.captain as cap_module
    manager = MagicMock()
    manager.send = AsyncMock()
    manager.broadcast = AsyncMock()
    ship = Ship()
    cap_module.init(manager, ship)
    return manager, ship, cap_module


@pytest.mark.asyncio
async def test_system_override_offline_sets_flag():
    manager, ship, cap = _make_captain_setup()
    msg = Message.build("captain.system_override", {"system": "engines", "online": False})
    await cap.handle_captain_message("conn1", msg)
    assert ship.systems["engines"]._captain_offline is True


@pytest.mark.asyncio
async def test_system_override_online_clears_flag():
    manager, ship, cap = _make_captain_setup()
    ship.systems["engines"]._captain_offline = True
    msg = Message.build("captain.system_override", {"system": "engines", "online": True})
    await cap.handle_captain_message("conn1", msg)
    assert ship.systems["engines"]._captain_offline is False


@pytest.mark.asyncio
async def test_system_override_broadcasts_override_changed():
    manager, ship, cap = _make_captain_setup()
    msg = Message.build("captain.system_override", {"system": "beams", "online": False})
    await cap.handle_captain_message("conn1", msg)
    assert manager.broadcast.called
    call_args = manager.broadcast.call_args[0][0]
    assert call_args.type == "captain.override_changed"
    assert call_args.payload["system"] == "beams"
    assert call_args.payload["online"] is False


@pytest.mark.asyncio
async def test_system_override_broadcast_online_true():
    manager, ship, cap = _make_captain_setup()
    ship.systems["torpedoes"]._captain_offline = True
    msg = Message.build("captain.system_override", {"system": "torpedoes", "online": True})
    await cap.handle_captain_message("conn1", msg)
    call_args = manager.broadcast.call_args[0][0]
    assert call_args.payload["online"] is True


@pytest.mark.asyncio
async def test_system_override_invalid_system_returns_error():
    manager, ship, cap = _make_captain_setup()
    msg = Message.build("captain.system_override", {"system": "warp_core", "online": False})
    await cap.handle_captain_message("conn1", msg)
    assert manager.send.called
    sent = manager.send.call_args[0][1]
    assert sent.type == "error.validation"


@pytest.mark.asyncio
async def test_system_override_invalid_system_does_not_broadcast():
    manager, ship, cap = _make_captain_setup()
    msg = Message.build("captain.system_override", {"system": "not_real", "online": False})
    await cap.handle_captain_message("conn1", msg)
    assert not manager.broadcast.called


@pytest.mark.asyncio
async def test_system_override_all_nine_systems():
    """All nine default systems can be overridden without errors."""
    manager, ship, cap = _make_captain_setup()
    for name in ("engines", "beams", "torpedoes", "shields", "sensors",
                 "manoeuvring", "flight_deck", "ecm_suite", "point_defence"):
        manager.broadcast.reset_mock()
        msg = Message.build("captain.system_override", {"system": name, "online": False})
        await cap.handle_captain_message("conn1", msg)
        assert ship.systems[name]._captain_offline is True
        assert manager.broadcast.called


# ---------------------------------------------------------------------------
# system_overrides in ship.state (via game_loop._build_ship_state)
# ---------------------------------------------------------------------------


def test_ship_state_includes_system_overrides():
    from server.game_loop import _build_ship_state
    import server.game_loop_weapons as glw
    glw.reset()
    ship = Ship()
    msg = _build_ship_state(ship, tick=1)
    assert "system_overrides" in msg.payload


def test_ship_state_overrides_all_true_by_default():
    from server.game_loop import _build_ship_state
    import server.game_loop_weapons as glw
    glw.reset()
    ship = Ship()
    msg = _build_ship_state(ship, tick=1)
    overrides = msg.payload["system_overrides"]
    assert all(v is True for v in overrides.values())


def test_ship_state_overrides_false_when_captain_offline():
    from server.game_loop import _build_ship_state
    import server.game_loop_weapons as glw
    glw.reset()
    ship = Ship()
    ship.systems["torpedoes"]._captain_offline = True
    msg = _build_ship_state(ship, tick=1)
    overrides = msg.payload["system_overrides"]
    assert overrides["torpedoes"] is False
    # Other systems still online
    assert overrides["engines"] is True


def test_ship_state_overrides_restored_after_online():
    from server.game_loop import _build_ship_state
    import server.game_loop_weapons as glw
    glw.reset()
    ship = Ship()
    ship.systems["shields"]._captain_offline = True
    ship.systems["shields"]._captain_offline = False
    msg = _build_ship_state(ship, tick=1)
    assert msg.payload["system_overrides"]["shields"] is True
