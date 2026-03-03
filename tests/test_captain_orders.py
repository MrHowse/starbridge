"""Tests for captain orders — priority target, general orders, bridge control."""
from __future__ import annotations

import asyncio
import pytest

import server.game_loop_captain_orders as glcord
from server.models.interior import ShipInterior, Room, make_default_interior
from server.models.ship import Ship
from server.models.world import World, Enemy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ship() -> Ship:
    ship = Ship()
    ship.interior = make_default_interior("frigate")
    return ship


def _make_world_with_enemy(eid: str = "e1") -> World:
    world = World()
    enemy = Enemy(id=eid, type="scout", x=5000, y=5000, heading=0.0)
    world.enemies.append(enemy)
    return world


# ---------------------------------------------------------------------------
# C.1.1 Priority Target
# ---------------------------------------------------------------------------


class TestPriorityTarget:
    def test_set_priority_target(self):
        world = _make_world_with_enemy("e1")
        result = glcord.set_priority_target("e1", world)
        assert result["ok"] is True
        assert glcord.get_priority_target() == "e1"

    def test_set_priority_target_invalid(self):
        world = World()
        result = glcord.set_priority_target("missing", world)
        assert result["ok"] is False
        assert "not found" in result["reason"].lower()
        assert glcord.get_priority_target() is None

    def test_clear_priority_target(self):
        world = _make_world_with_enemy("e1")
        glcord.set_priority_target("e1", world)
        result = glcord.set_priority_target(None, world)
        assert result["ok"] is True
        assert result.get("cleared") is True
        assert glcord.get_priority_target() is None

    def test_on_entity_destroyed_clears_target(self):
        world = _make_world_with_enemy("e1")
        glcord.set_priority_target("e1", world)
        was_priority = glcord.on_entity_destroyed("e1")
        assert was_priority is True
        assert glcord.get_priority_target() is None

    def test_on_entity_destroyed_starts_morale_boost(self):
        world = _make_world_with_enemy("e1")
        glcord.set_priority_target("e1", world)
        glcord.on_entity_destroyed("e1")
        assert glcord.get_crew_factor_boost() == glcord.MORALE_BOOST_AMOUNT

    def test_morale_boost_decays(self):
        world = _make_world_with_enemy("e1")
        glcord.set_priority_target("e1", world)
        glcord.on_entity_destroyed("e1")
        ship = _make_ship()
        # Tick 61 seconds to expire boost.
        for _ in range(610):
            glcord.tick(0.1, ship, ship.interior)
        assert glcord.get_crew_factor_boost() == 0.0

    def test_on_entity_destroyed_non_priority(self):
        world = _make_world_with_enemy("e1")
        glcord.set_priority_target("e1", world)
        was_priority = glcord.on_entity_destroyed("e2")
        assert was_priority is False
        assert glcord.get_priority_target() == "e1"

    def test_priority_accuracy_bonus(self):
        """Priority target gives +5% accuracy bonus."""
        assert glcord.PRIORITY_ACCURACY_BONUS == 0.05


# ---------------------------------------------------------------------------
# C.1.2 General Orders
# ---------------------------------------------------------------------------


class TestGeneralOrders:
    def test_battle_stations(self):
        ship = _make_ship()
        world = World()
        result = glcord.set_general_order("battle_stations", ship, world)
        assert result["ok"] is True
        assert ship.alert_level == "red"
        assert glcord.get_active_order() == "battle_stations"

    def test_condition_green(self):
        ship = _make_ship()
        world = World()
        glcord.set_general_order("battle_stations", ship, world)
        result = glcord.set_general_order("condition_green", ship, world)
        assert result["ok"] is True
        assert ship.alert_level == "green"
        assert glcord.get_active_order() is None

    def test_silent_running_not_capable(self):
        """Silent running fails for non-scout ships."""
        ship = _make_ship()
        world = World()
        result = glcord.set_general_order("silent_running", ship, world)
        assert result["ok"] is False
        assert "not stealth-capable" in result["reason"].lower() or "not_capable" in result["reason"].lower()

    def test_evasive_manoeuvres(self):
        ship = _make_ship()
        world = World()
        result = glcord.set_general_order("evasive_manoeuvres", ship, world)
        assert result["ok"] is True
        assert glcord.get_active_order() == "evasive_manoeuvres"
        assert glcord.get_target_profile_modifier() == 0.85
        assert glcord.get_accuracy_modifier() == -0.10

    def test_evasive_modifiers_clear_on_condition_green(self):
        ship = _make_ship()
        world = World()
        glcord.set_general_order("evasive_manoeuvres", ship, world)
        glcord.set_general_order("condition_green", ship, world)
        assert glcord.get_target_profile_modifier() == 1.0
        assert glcord.get_accuracy_modifier() == 0.0

    def test_all_stop(self):
        ship = _make_ship()
        ship.throttle = 50
        world = World()
        result = glcord.set_general_order("all_stop", ship, world)
        assert result["ok"] is True
        assert ship.throttle == 0
        assert glcord.is_all_stop_active() is True

    def test_all_stop_helm_lock(self):
        ship = _make_ship()
        world = World()
        glcord.set_general_order("all_stop", ship, world)
        assert glcord.is_all_stop_active() is True
        # Tick enforces throttle = 0.
        ship.throttle = 50
        glcord.tick(0.1, ship, ship.interior)
        assert ship.throttle == 0

    def test_acknowledge_all_stop(self):
        ship = _make_ship()
        world = World()
        glcord.set_general_order("all_stop", ship, world)
        result = glcord.acknowledge_all_stop()
        assert result["ok"] is True
        assert glcord.is_all_stop_active() is False
        assert glcord.get_active_order() is None

    def test_acknowledge_all_stop_no_active(self):
        result = glcord.acknowledge_all_stop()
        assert result["ok"] is False

    def test_invalid_order(self):
        ship = _make_ship()
        world = World()
        result = glcord.set_general_order("invalid", ship, world)
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# Serialise / Deserialise
# ---------------------------------------------------------------------------


class TestSerialise:
    def test_roundtrip(self):
        world = _make_world_with_enemy("e1")
        ship = _make_ship()
        glcord.set_priority_target("e1", world)
        glcord.set_general_order("evasive_manoeuvres", ship, world)
        data = glcord.serialise()
        glcord.reset()
        assert glcord.get_priority_target() is None
        glcord.deserialise(data)
        assert glcord.get_priority_target() == "e1"
        assert glcord.get_active_order() == "evasive_manoeuvres"


# ---------------------------------------------------------------------------
# Bridge Control Timer
# ---------------------------------------------------------------------------


class TestBridgeControl:
    def test_bridge_captured_defeat(self):
        """Boarders controlling the bridge for 60s triggers defeat."""
        ship = _make_ship()
        interior = ship.interior
        # Simulate boarder controlling the bridge.
        from server.models.boarding import BoardingParty
        import server.game_loop_security as gls
        gls.reset()
        bridge_room = interior.system_rooms.get("manoeuvring", "bridge")
        party = BoardingParty(
            id="bp_1", location=bridge_room,
            members=4, max_members=4, status="sabotaging",
        )
        gls._boarding_parties.append(party)
        gls._boarding_active = True
        # Tick 61 seconds.
        events = []
        for _ in range(610):
            events.extend(glcord.tick(0.1, ship, interior))
        defeat_events = [e for e in events if e[0] == "game.defeat"]
        assert len(defeat_events) == 1
        assert defeat_events[0][1]["reason"] == "bridge_captured"

    def test_bridge_contested_no_defeat(self):
        """Contested bridge (marines present) does not trigger defeat."""
        ship = _make_ship()
        interior = ship.interior
        from server.models.boarding import BoardingParty
        from server.models.marine_teams import MarineTeam
        import server.game_loop_security as gls
        gls.reset()
        bridge_room = interior.system_rooms.get("manoeuvring", "bridge")
        party = BoardingParty(
            id="bp_1", location=bridge_room,
            members=4, max_members=4, status="sabotaging",
        )
        gls._boarding_parties.append(party)
        gls._boarding_active = True
        team = MarineTeam(
            id="mt_alpha", name="Alpha", callsign="Alpha",
            members=["m1", "m2"], leader="m1", size=2, max_size=4,
            location=bridge_room,
        )
        gls._marine_teams.append(team)
        events = []
        for _ in range(610):
            events.extend(glcord.tick(0.1, ship, interior))
        defeat_events = [e for e in events if e[0] == "game.defeat"]
        assert len(defeat_events) == 0
