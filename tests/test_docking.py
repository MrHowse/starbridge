"""Tests for v0.05f Docking System.

Covers:
  - Constants (SERVICE_DURATIONS, SHIELDS_DOCKED_CAP, etc.)
  - reset() clears all state
  - serialise/deserialise round-trip
  - request_clearance() — friendly/neutral/hostile, distance, speed, already-in-progress
  - Clearance timer → sequencing transition
  - Sequencing → docked transition; ship.docked_at set
  - Physics constraints while docked (velocity, throttle, shields)
  - start_service() — success, not docked, already running, unknown service
  - Service completion effects: hull_repair, system_repair, medical_transfer,
    ew_database_update, torpedo_resupply
  - cancel_service() — success and not-active error
  - captain_undock() — normal, emergency, not-docked error
  - Undocking → none; ship.docked_at cleared
  - Proximity approach_info broadcast (Helm notification)
  - save_system round-trip for hull_max and docked_at
  - game_loop._build_ship_state includes docking fields
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import server.game_loop_docking as gldo
from server.game_loop_docking import (
    CLEARANCE_DELAY_FRIENDLY,
    CLEARANCE_DELAY_NEUTRAL,
    DOCK_APPROACH_MAX_THROTTLE,
    DOCKING_SEQUENCE_DURATION,
    SERVICE_DURATIONS,
    SHIELDS_DOCKED_CAP,
    UNDOCKING_DURATION,
)
from server.models.ship import Ship
from server.models.world import Station, World


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _fresh_ship(**kwargs) -> Ship:
    s = Ship(**kwargs)
    s.hull_max = s.hull
    return s


def _fresh_world(*stations: Station) -> World:
    w = World()
    w.enemies.clear()
    w.torpedoes.clear()
    w.stations.clear()
    w.asteroids.clear()
    w.hazards.clear()
    for st in stations:
        w.stations.append(st)
    return w


def _friendly_station(
    sid: str = "s1",
    x: float = 1_000.0,
    y: float = 0.0,
    docking_range: float = 2_000.0,
) -> Station:
    return Station(
        id=sid, x=x, y=y,
        name="Alpha Base",
        station_type="military",
        faction="friendly",
        services=["hull_repair", "torpedo_resupply"],
        docking_range=docking_range,
    )


def _make_manager() -> AsyncMock:
    mgr = AsyncMock()
    mgr.broadcast = AsyncMock()
    mgr.broadcast_to_roles = AsyncMock()
    return mgr


async def _tick(world, ship, manager, dt: float = 0.1) -> None:
    await gldo.tick(world, ship, manager, dt)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_service_durations_has_all_keys():
    expected = {
        "hull_repair", "torpedo_resupply", "medical_transfer", "system_repair",
        "atmospheric_resupply", "sensor_data_package", "drone_service",
        "ew_database_update", "crew_rest", "intel_briefing",
    }
    assert expected == set(SERVICE_DURATIONS.keys())


def test_shields_docked_cap_is_50():
    assert SHIELDS_DOCKED_CAP == pytest.approx(50.0)


def test_dock_approach_max_throttle_is_10():
    assert DOCK_APPROACH_MAX_THROTTLE == pytest.approx(10.0)


def test_docking_sequence_duration_is_10():
    assert DOCKING_SEQUENCE_DURATION == pytest.approx(10.0)


def test_undocking_duration_is_5():
    assert UNDOCKING_DURATION == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------


def test_reset_clears_state():
    gldo.reset()
    assert gldo.get_state() == "none"
    assert gldo.get_docked_station_id() is None
    assert gldo.get_active_services() == {}
    assert not gldo.is_docked()


# ---------------------------------------------------------------------------
# serialise / deserialise
# ---------------------------------------------------------------------------


def test_serialise_deserialise_round_trip():
    gldo.reset()
    # Manually set internal state for serialise test.
    gldo._state = "docked"
    gldo._target_station_id = "s99"
    gldo._sequence_timer = 3.5
    gldo._active_services["hull_repair"] = 45.0

    data = gldo.serialise()
    gldo.reset()
    gldo.deserialise(data)

    assert gldo.get_state() == "docked"
    assert gldo._target_station_id == "s99"
    assert gldo._sequence_timer == pytest.approx(3.5)
    assert gldo.get_active_services()["hull_repair"] == pytest.approx(45.0)


def test_deserialise_defaults_on_empty():
    gldo.deserialise({})
    assert gldo.get_state() == "none"
    assert gldo._target_station_id is None


# ---------------------------------------------------------------------------
# request_clearance()
# ---------------------------------------------------------------------------


def test_clearance_friendly_sets_state():
    gldo.reset()
    ship = _fresh_ship(x=0.0, y=0.0, throttle=5.0)
    st = _friendly_station(x=500.0)
    world = _fresh_world(st)
    err = gldo.request_clearance("s1", world, ship)
    assert err is None
    assert gldo.get_state() == "clearance_pending"
    assert gldo._target_station_id == "s1"
    assert gldo._clearance_timer == pytest.approx(CLEARANCE_DELAY_FRIENDLY)


def test_clearance_neutral_uses_longer_delay():
    gldo.reset()
    ship = _fresh_ship(x=0.0, y=0.0, throttle=5.0)
    st = Station(id="n1", x=500.0, y=0.0, faction="neutral",
                 station_type="trade_hub", docking_range=2_000.0, services=[])
    world = _fresh_world(st)
    gldo.request_clearance("n1", world, ship)
    assert gldo._clearance_timer == pytest.approx(CLEARANCE_DELAY_NEUTRAL)


def test_clearance_hostile_emits_denied_stays_none():
    gldo.reset()
    ship = _fresh_ship(x=0.0, y=0.0, throttle=5.0)
    st = Station(id="e1", x=500.0, y=0.0, faction="hostile",
                 station_type="enemy", docking_range=2_000.0, services=[])
    world = _fresh_world(st)
    err = gldo.request_clearance("e1", world, ship)
    assert err is None
    assert gldo.get_state() == "none"
    # A denial broadcast should be queued.
    assert any(m == "docking.clearance_denied" for _, m, _ in gldo._pending_broadcasts)


def test_clearance_too_far_returns_error():
    gldo.reset()
    ship = _fresh_ship(x=0.0, y=0.0, throttle=5.0)
    st = _friendly_station(x=10_000.0)   # beyond 2 000 docking range
    world = _fresh_world(st)
    err = gldo.request_clearance("s1", world, ship)
    assert err is not None
    assert "far" in err.lower()
    assert gldo.get_state() == "none"


def test_clearance_too_fast_returns_error():
    gldo.reset()
    ship = _fresh_ship(x=0.0, y=0.0, throttle=50.0)  # over 10%
    st = _friendly_station(x=500.0)
    world = _fresh_world(st)
    err = gldo.request_clearance("s1", world, ship)
    assert err is not None
    assert "speed" in err.lower() or "throttle" in err.lower()


def test_clearance_already_in_progress_returns_error():
    gldo.reset()
    gldo._state = "sequencing"
    ship = _fresh_ship(x=0.0, y=0.0, throttle=5.0)
    st = _friendly_station(x=500.0)
    world = _fresh_world(st)
    err = gldo.request_clearance("s1", world, ship)
    assert err is not None


def test_clearance_unknown_station_returns_error():
    gldo.reset()
    ship = _fresh_ship(x=0.0, y=0.0)
    world = _fresh_world()
    err = gldo.request_clearance("nonexistent", world, ship)
    assert err is not None


# ---------------------------------------------------------------------------
# Clearance timer → sequencing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clearance_timer_expires_to_sequencing():
    gldo.reset()
    ship = _fresh_ship(x=0.0, y=0.0, throttle=5.0)
    st = _friendly_station(x=500.0)
    world = _fresh_world(st)
    gldo.request_clearance("s1", world, ship)
    gldo._pending_broadcasts.clear()  # consume request broadcast

    mgr = _make_manager()
    # Tick past clearance delay.
    await gldo.tick(world, ship, mgr, CLEARANCE_DELAY_FRIENDLY + 0.1)

    assert gldo.get_state() == "sequencing"
    assert gldo._sequence_timer == pytest.approx(DOCKING_SEQUENCE_DURATION)
    # Clearance-granted broadcast emitted.
    assert mgr.broadcast.called


# ---------------------------------------------------------------------------
# Sequencing → docked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sequencing_to_docked():
    gldo.reset()
    gldo._state = "sequencing"
    gldo._target_station_id = "s1"
    gldo._sequence_timer = 0.05

    ship = _fresh_ship(x=0.0, y=0.0)
    ship.hull_max = 100.0
    st = _friendly_station()
    world = _fresh_world(st)
    mgr = _make_manager()

    await gldo.tick(world, ship, mgr, 0.1)

    assert gldo.get_state() == "docked"
    assert ship.docked_at == "s1"
    assert gldo.is_docked()
    assert mgr.broadcast.called  # docking.complete emitted


# ---------------------------------------------------------------------------
# Physics constraints while docked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_docked_velocity_and_throttle_zeroed():
    gldo.reset()
    gldo._state = "docked"
    gldo._target_station_id = "s1"

    ship = _fresh_ship(x=0.0, y=0.0, velocity=50.0, throttle=80.0)
    st = _friendly_station()
    world = _fresh_world(st)
    mgr = _make_manager()

    await gldo.tick(world, ship, mgr, 0.1)

    assert ship.velocity == pytest.approx(0.0)
    assert ship.throttle == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_docked_shields_capped():
    gldo.reset()
    gldo._state = "docked"
    gldo._target_station_id = "s1"

    ship = _fresh_ship()
    ship.shields.fore      = 100.0
    ship.shields.aft       = 100.0
    ship.shields.port      = 100.0
    ship.shields.starboard = 100.0
    st = _friendly_station()
    world = _fresh_world(st)
    mgr = _make_manager()

    await gldo.tick(world, ship, mgr, 0.1)

    assert ship.shields.fore      == pytest.approx(SHIELDS_DOCKED_CAP)
    assert ship.shields.aft       == pytest.approx(SHIELDS_DOCKED_CAP)
    assert ship.shields.port      == pytest.approx(SHIELDS_DOCKED_CAP)
    assert ship.shields.starboard == pytest.approx(SHIELDS_DOCKED_CAP)


@pytest.mark.asyncio
async def test_shields_capped_during_sequencing():
    gldo.reset()
    gldo._state = "sequencing"
    gldo._target_station_id = "s1"
    gldo._sequence_timer = 5.0

    ship = _fresh_ship()
    ship.shields.fore      = 100.0
    ship.shields.aft       = 100.0
    ship.shields.port      = 100.0
    ship.shields.starboard = 100.0
    st = _friendly_station()
    world = _fresh_world(st)
    mgr = _make_manager()

    await gldo.tick(world, ship, mgr, 0.1)

    assert ship.shields.fore == pytest.approx(SHIELDS_DOCKED_CAP)


# ---------------------------------------------------------------------------
# start_service() / cancel_service()
# ---------------------------------------------------------------------------


def test_start_service_succeeds_when_docked():
    gldo.reset()
    gldo._state = "docked"
    err = gldo.start_service("hull_repair")
    assert err is None
    assert "hull_repair" in gldo.get_active_services()


def test_start_service_error_when_not_docked():
    gldo.reset()
    err = gldo.start_service("hull_repair")
    assert err is not None
    assert "not docked" in err.lower()


def test_start_service_error_already_running():
    gldo.reset()
    gldo._state = "docked"
    gldo._active_services["hull_repair"] = 30.0
    err = gldo.start_service("hull_repair")
    assert err is not None
    assert "already" in err.lower()


def test_start_service_error_unknown():
    gldo.reset()
    gldo._state = "docked"
    err = gldo.start_service("teleport_crew")
    assert err is not None
    assert "unknown" in err.lower()


def test_cancel_service_success():
    gldo.reset()
    gldo._state = "docked"
    gldo._active_services["system_repair"] = 10.0
    err = gldo.cancel_service("system_repair")
    assert err is None
    assert "system_repair" not in gldo.get_active_services()


def test_cancel_service_error_not_active():
    gldo.reset()
    err = gldo.cancel_service("hull_repair")
    assert err is not None


# ---------------------------------------------------------------------------
# Service completion effects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hull_repair_restores_hull():
    gldo.reset()
    gldo._state = "docked"
    gldo._target_station_id = "s1"
    gldo._active_services["hull_repair"] = 0.05  # almost done

    ship = _fresh_ship()
    ship.hull = 40.0
    ship.hull_max = 100.0
    world = _fresh_world(_friendly_station())
    mgr = _make_manager()

    await gldo.tick(world, ship, mgr, 0.1)

    assert ship.hull == pytest.approx(100.0)
    assert "hull_repair" not in gldo.get_active_services()


@pytest.mark.asyncio
async def test_system_repair_restores_health():
    gldo.reset()
    gldo._state = "docked"
    gldo._target_station_id = "s1"
    gldo._active_services["system_repair"] = 0.05

    ship = _fresh_ship()
    ship.systems["engines"].health = 20.0
    ship.systems["beams"].health = 50.0
    world = _fresh_world(_friendly_station())
    mgr = _make_manager()

    await gldo.tick(world, ship, mgr, 0.1)

    assert ship.systems["engines"].health == pytest.approx(100.0)
    assert ship.systems["beams"].health == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_medical_transfer_adds_supplies():
    gldo.reset()
    gldo._state = "docked"
    gldo._target_station_id = "s1"
    gldo._active_services["medical_transfer"] = 0.05

    ship = _fresh_ship()
    ship.medical_supplies = 5
    world = _fresh_world(_friendly_station())
    mgr = _make_manager()

    await gldo.tick(world, ship, mgr, 0.1)

    assert ship.medical_supplies == 15   # 5 + 10, capped at 20


@pytest.mark.asyncio
async def test_ew_database_update_adds_charges():
    gldo.reset()
    gldo._state = "docked"
    gldo._target_station_id = "s1"
    gldo._active_services["ew_database_update"] = 0.05

    ship = _fresh_ship()
    ship.countermeasure_charges = 3
    world = _fresh_world(_friendly_station())
    mgr = _make_manager()

    await gldo.tick(world, ship, mgr, 0.1)

    assert ship.countermeasure_charges == 8   # 3 + 5


@pytest.mark.asyncio
async def test_torpedo_resupply_restores_all_types_to_max():
    import server.game_loop_weapons as glw
    gldo.reset()
    gldo._state = "docked"
    gldo._target_station_id = "s1"
    gldo._active_services["torpedo_resupply"] = 0.05

    glw.reset()
    glw.set_ammo_for_type("standard", 2)
    glw.set_ammo_for_type("homing", 0)

    ship = _fresh_ship()
    world = _fresh_world(_friendly_station())
    mgr = _make_manager()

    await gldo.tick(world, ship, mgr, 0.1)

    for t, max_count in glw.get_ammo_max().items():
        assert glw.get_ammo_for_type(t) == max_count, f"type={t} not restored"


# ---------------------------------------------------------------------------
# captain_undock()
# ---------------------------------------------------------------------------


def test_captain_undock_normal():
    gldo.reset()
    gldo._state = "docked"
    gldo._target_station_id = "s1"
    err = gldo.captain_undock(emergency=False)
    assert err is None
    assert gldo.get_state() == "undocking"
    assert gldo._sequence_timer == pytest.approx(UNDOCKING_DURATION)


def test_captain_undock_emergency_immediate():
    gldo.reset()
    gldo._state = "docked"
    gldo._target_station_id = "s1"
    err = gldo.captain_undock(emergency=True)
    assert err is None
    assert gldo.get_state() == "none"
    assert gldo._target_station_id is None


def test_captain_undock_error_when_not_docked():
    gldo.reset()
    err = gldo.captain_undock()
    assert err is not None


def test_captain_undock_clears_active_services():
    gldo.reset()
    gldo._state = "docked"
    gldo._active_services["hull_repair"] = 30.0
    gldo.captain_undock()
    assert gldo.get_active_services() == {}


# ---------------------------------------------------------------------------
# Undocking → none
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_undocking_timer_expires_to_none():
    gldo.reset()
    gldo._state = "undocking"
    gldo._target_station_id = "s1"
    gldo._sequence_timer = 0.05

    ship = _fresh_ship()
    ship.docked_at = "s1"
    world = _fresh_world(_friendly_station())
    mgr = _make_manager()

    await gldo.tick(world, ship, mgr, 0.1)

    assert gldo.get_state() == "none"
    assert gldo._target_station_id is None
    assert ship.docked_at is None
    assert mgr.broadcast.called  # docking.undocked emitted


# ---------------------------------------------------------------------------
# Proximity approach_info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approach_info_emitted_when_near_station():
    gldo.reset()
    ship = _fresh_ship(x=0.0, y=0.0, throttle=5.0)
    # Station at 3 000, just within 2× docking_range approach zone (4 000).
    st = _friendly_station(x=3_000.0)
    world = _fresh_world(st)
    mgr = _make_manager()

    await gldo.tick(world, ship, mgr, 0.1)

    # broadcast_to_roles should have been called for ["helm"].
    calls = [str(c) for c in mgr.broadcast_to_roles.call_args_list]
    assert any("helm" in c for c in calls)


@pytest.mark.asyncio
async def test_approach_info_not_emitted_when_far():
    gldo.reset()
    ship = _fresh_ship(x=0.0, y=0.0)
    st = _friendly_station(x=50_000.0)  # far away
    world = _fresh_world(st)
    mgr = _make_manager()

    await gldo.tick(world, ship, mgr, 0.1)

    assert not mgr.broadcast_to_roles.called


@pytest.mark.asyncio
async def test_approach_info_not_emitted_for_hostile():
    gldo.reset()
    ship = _fresh_ship(x=0.0, y=0.0)
    st = Station(id="h1", x=500.0, y=0.0, faction="hostile",
                 station_type="enemy", docking_range=2_000.0, services=[])
    world = _fresh_world(st)
    mgr = _make_manager()

    await gldo.tick(world, ship, mgr, 0.1)

    assert not mgr.broadcast_to_roles.called


# ---------------------------------------------------------------------------
# save_system — hull_max and docked_at
# ---------------------------------------------------------------------------


def test_serialise_ship_includes_hull_max():
    import server.save_system as ss
    world = World()
    world.ship.hull = 80.0
    world.ship.hull_max = 100.0
    data = ss._serialise_ship(world.ship)
    assert data["hull_max"] == pytest.approx(100.0)


def test_serialise_ship_includes_docked_at():
    import server.save_system as ss
    world = World()
    world.ship.docked_at = "station_x"
    data = ss._serialise_ship(world.ship)
    assert data["docked_at"] == "station_x"


def test_deserialise_ship_restores_hull_max():
    import server.save_system as ss
    world = World()
    ss._deserialise_ship({"hull": 70.0, "hull_max": 140.0}, world.ship)
    assert world.ship.hull_max == pytest.approx(140.0)


def test_deserialise_ship_restores_docked_at():
    import server.save_system as ss
    world = World()
    ss._deserialise_ship({"docked_at": "stn2"}, world.ship)
    assert world.ship.docked_at == "stn2"


def test_deserialise_ship_docked_at_defaults_none():
    import server.save_system as ss
    world = World()
    world.ship.docked_at = "old"
    ss._deserialise_ship({}, world.ship)
    assert world.ship.docked_at is None
