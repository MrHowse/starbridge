"""Tests for v0.08 environmental on_complete actions in game_loop_mission.py.

Covers:
  - start_fire: creates fire in room via glhc
  - create_breach: creates hull breach via glatm
  - apply_radiation: adds radiation to room atmosphere
  - structural_damage: reduces section integrity
  - contaminate_atmosphere: adds contaminant to room
  - system_damage: reduces ship system health
  - crew_casualty: queued to pending list
  - send_transmission: injects signal into comms
  - Graceful error handling for invalid room/system
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from server.mission_graph import MissionGraph
from server.models.ship import Ship
from server.models.interior import make_default_interior
from server.models.world import World
import server.game_loop_mission as glm
import server.game_loop_hazard_control as glhc
import server.game_loop_atmosphere as glatm
import server.game_loop_comms as glcomms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ship():
    s = Ship()
    s.x = 50_000
    s.y = 50_000
    s.hull = 100.0
    s.interior = make_default_interior("frigate")
    return s


def _make_world():
    w = World()
    return w


def _first_room(ship):
    """Return the first room_id from the ship interior."""
    return next(iter(ship.interior.rooms))


def _mission_with_action(action_dict):
    """Build a minimal mission that fires an action at time 0."""
    return {
        "id": "test_action",
        "name": "Test Action",
        "nodes": [
            {"id": "start", "type": "objective", "text": "Go",
             "trigger": {"type": "timer_elapsed", "seconds": 0}},
            {"id": "end", "type": "objective", "text": "Win",
             "trigger": {"type": "timer_elapsed", "seconds": 999}},
        ],
        "edges": [
            {"from": "start", "to": "end", "type": "sequence",
             "on_complete": action_dict},
        ],
        "start_node": "start",
        "victory_nodes": ["end"],
    }


async def _tick_once(ship, world, dt=0.1):
    """Tick mission engine once, return (game_over, result)."""
    manager = AsyncMock()
    manager.broadcast = AsyncMock()
    return await glm.tick_mission(world, ship, manager, dt)


# ---------------------------------------------------------------------------
# Tests: start_fire
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_fire_creates_fire():
    ship = _make_ship()
    world = _make_world()
    world.ship = ship
    room_id = _first_room(ship)

    glhc.init_sections(ship.interior)
    glatm.init_atmosphere(ship.interior)

    mission = _mission_with_action({"action": "start_fire", "room_id": room_id, "intensity": 3})
    glm.reset()
    glm._mission_engine = MissionGraph(mission)

    await _tick_once(ship, world, dt=0.1)

    fires = glhc.get_fires()
    assert room_id in fires, f"Expected fire in {room_id}, got {list(fires.keys())}"


@pytest.mark.asyncio
async def test_start_fire_invalid_room_no_crash():
    ship = _make_ship()
    world = _make_world()
    world.ship = ship

    glhc.init_sections(ship.interior)

    mission = _mission_with_action({"action": "start_fire", "room_id": "nonexistent_room", "intensity": 2})
    glm.reset()
    glm._mission_engine = MissionGraph(mission)

    # Should not raise
    await _tick_once(ship, world, dt=0.1)


# ---------------------------------------------------------------------------
# Tests: create_breach
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_breach():
    ship = _make_ship()
    world = _make_world()
    world.ship = ship
    room_id = _first_room(ship)

    glatm.init_atmosphere(ship.interior)

    mission = _mission_with_action({"action": "create_breach", "room_id": room_id, "severity": "minor"})
    glm.reset()
    glm._mission_engine = MissionGraph(mission)

    await _tick_once(ship, world, dt=0.1)

    breaches = glatm.get_breaches()
    assert room_id in breaches, f"Expected breach in {room_id}"


@pytest.mark.asyncio
async def test_create_breach_moderate_maps_to_major():
    ship = _make_ship()
    world = _make_world()
    world.ship = ship
    room_id = _first_room(ship)

    glatm.init_atmosphere(ship.interior)

    mission = _mission_with_action({"action": "create_breach", "room_id": room_id, "severity": "moderate"})
    glm.reset()
    glm._mission_engine = MissionGraph(mission)

    await _tick_once(ship, world, dt=0.1)

    breaches = glatm.get_breaches()
    assert room_id in breaches
    assert breaches[room_id].severity == "major"


# ---------------------------------------------------------------------------
# Tests: apply_radiation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_radiation():
    ship = _make_ship()
    world = _make_world()
    world.ship = ship
    room_id = _first_room(ship)

    glatm.init_atmosphere(ship.interior)

    mission = _mission_with_action({"action": "apply_radiation", "room_id": room_id, "source": "reactor", "tier": 3})
    glm.reset()
    glm._mission_engine = MissionGraph(mission)

    await _tick_once(ship, world, dt=0.1)

    atm = glatm.get_atmosphere(room_id)
    assert atm is not None
    assert atm.radiation >= 75.0  # tier 3 = 75


@pytest.mark.asyncio
async def test_apply_radiation_invalid_room():
    ship = _make_ship()
    world = _make_world()
    world.ship = ship

    glatm.init_atmosphere(ship.interior)

    mission = _mission_with_action({"action": "apply_radiation", "room_id": "fake", "source": "x", "tier": 1})
    glm.reset()
    glm._mission_engine = MissionGraph(mission)

    # Should not raise
    await _tick_once(ship, world, dt=0.1)


# ---------------------------------------------------------------------------
# Tests: structural_damage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structural_damage():
    ship = _make_ship()
    world = _make_world()
    world.ship = ship
    room_id = _first_room(ship)

    glhc.init_sections(ship.interior)

    mission = _mission_with_action({"action": "structural_damage", "section": room_id, "amount": 30})
    glm.reset()
    glm._mission_engine = MissionGraph(mission)

    await _tick_once(ship, world, dt=0.1)

    sec = glhc.get_section_for_room(room_id)
    assert sec is not None
    assert sec.integrity <= 70.0


# ---------------------------------------------------------------------------
# Tests: contaminate_atmosphere
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contaminate_atmosphere():
    ship = _make_ship()
    world = _make_world()
    world.ship = ship
    room_id = _first_room(ship)

    glatm.init_atmosphere(ship.interior)

    mission = _mission_with_action({
        "action": "contaminate_atmosphere",
        "room_id": room_id,
        "contaminant": "smoke",
        "concentration": 0.5,
    })
    glm.reset()
    glm._mission_engine = MissionGraph(mission)

    await _tick_once(ship, world, dt=0.1)

    atm = glatm.get_atmosphere(room_id)
    assert atm is not None
    assert atm.smoke >= 50.0


# ---------------------------------------------------------------------------
# Tests: system_damage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_damage():
    ship = _make_ship()
    world = _make_world()
    world.ship = ship

    mission = _mission_with_action({"action": "system_damage", "system": "engines", "amount": 25})
    glm.reset()
    glm._mission_engine = MissionGraph(mission)

    await _tick_once(ship, world, dt=0.1)

    assert ship.systems["engines"].health <= 75.0


@pytest.mark.asyncio
async def test_system_damage_invalid_system():
    ship = _make_ship()
    world = _make_world()
    world.ship = ship

    mission = _mission_with_action({"action": "system_damage", "system": "warp_drive", "amount": 10})
    glm.reset()
    glm._mission_engine = MissionGraph(mission)

    # Should not raise
    await _tick_once(ship, world, dt=0.1)


# ---------------------------------------------------------------------------
# Tests: crew_casualty (queued)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crew_casualty_queued():
    ship = _make_ship()
    world = _make_world()
    world.ship = ship
    room_id = _first_room(ship)

    mission = _mission_with_action({"action": "crew_casualty", "room_id": room_id, "count": 2})
    glm.reset()
    glm._mission_engine = MissionGraph(mission)

    await _tick_once(ship, world, dt=0.1)

    casualties = glm.pop_pending_casualties()
    assert len(casualties) == 1
    assert casualties[0]["room_id"] == room_id
    assert casualties[0]["count"] == 2


# ---------------------------------------------------------------------------
# Tests: send_transmission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_transmission_open():
    ship = _make_ship()
    world = _make_world()
    world.ship = ship

    glcomms.reset()

    mission = _mission_with_action({
        "action": "send_transmission",
        "faction": "federation",
        "message": "Help us!",
        "channel": "open",
    })
    glm.reset()
    glm._mission_engine = MissionGraph(mission)

    await _tick_once(ship, world, dt=0.1)

    signals = glcomms.get_signals()
    assert any("Help us!" in (s.raw_content or "") for s in signals)


@pytest.mark.asyncio
async def test_send_transmission_distress():
    ship = _make_ship()
    world = _make_world()
    world.ship = ship

    glcomms.reset()

    mission = _mission_with_action({
        "action": "send_transmission",
        "faction": "corsair",
        "message": "Mayday!",
        "channel": "distress",
    })
    glm.reset()
    glm._mission_engine = MissionGraph(mission)

    await _tick_once(ship, world, dt=0.1)

    signals = glcomms.get_signals()
    distress = [s for s in signals if s.signal_type == "distress"]
    assert len(distress) >= 1
