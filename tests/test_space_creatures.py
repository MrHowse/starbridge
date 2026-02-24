"""Tests for v0.05k — Space Creatures.

Covers:
  - Creature dataclass and spawn factory
  - Per-type AI state machines (void_whale, rift_stalker, hull_leech, swarm, leviathan)
  - game_loop_creatures public API (sedate, EW disrupt, comm progress, leech removal)
  - Sensor contacts include detected creatures
  - BIO scan study advancement
  - Mission graph creature triggers (creature_state, creature_destroyed,
    creature_study_complete, creature_communication_complete, no_creatures_type)
  - Serialise/deserialise of destroyed_creature_ids
"""
from __future__ import annotations

import math
import pytest
from unittest.mock import AsyncMock, MagicMock

from server.models.world import (
    World, Creature, CREATURE_TYPE_PARAMS,
    spawn_creature, Enemy,
)
from server.models.ship import Ship
from server.systems.creature_ai import tick_creatures, CREATURE_TURN_RATE
from server.systems.sensors import build_sensor_contacts
import server.game_loop_creatures as glc
import server.mission_graph as mg_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fresh_world() -> World:
    w = World()
    w.ship = Ship()
    w.ship.x = 50_000.0
    w.ship.y = 50_000.0
    return w


def _graph(nodes=None, edges=None, start_node="n1", victory_nodes=None):
    return mg_module.MissionGraph({
        "nodes": nodes or [],
        "edges": edges or [],
        "start_node": start_node,
        "victory_nodes": victory_nodes or [],
        "defeat_condition": None,
    })


# ---------------------------------------------------------------------------
# 1. Creature dataclass and spawn factory
# ---------------------------------------------------------------------------

class TestSpawnCreature:
    def test_spawn_void_whale(self):
        c = spawn_creature("w1", "void_whale", 1000.0, 2000.0)
        assert c.id == "w1"
        assert c.creature_type == "void_whale"
        assert c.x == 1000.0
        assert c.y == 2000.0
        assert c.hull == CREATURE_TYPE_PARAMS["void_whale"]["hull"]
        assert c.hull_max == c.hull
        assert c.behaviour_state == "idle"
        assert c.detected is True

    def test_spawn_rift_stalker_has_territory(self):
        c = spawn_creature("rs1", "rift_stalker", 3000.0, 4000.0)
        assert c.territory_radius == CREATURE_TYPE_PARAMS["rift_stalker"]["territory_radius"]
        assert c.territory_x == 3000.0
        assert c.territory_y == 4000.0

    def test_spawn_hull_leech_not_detected(self):
        c = spawn_creature("hl1", "hull_leech", 0.0, 0.0)
        assert c.detected is False
        assert c.creature_type == "hull_leech"

    def test_spawn_swarm(self):
        c = spawn_creature("sw1", "swarm", 0.0, 0.0)
        assert c.hull == CREATURE_TYPE_PARAMS["swarm"]["hull"]
        assert c.behaviour_state == "idle"

    def test_spawn_leviathan_dormant(self):
        c = spawn_creature("lev1", "leviathan", 0.0, 0.0)
        assert c.behaviour_state == "dormant"
        assert c.hull == CREATURE_TYPE_PARAMS["leviathan"]["hull"]


# ---------------------------------------------------------------------------
# 2. Void whale AI
# ---------------------------------------------------------------------------

class TestVoidWhaleAI:
    def setup_method(self):
        glc.reset()

    def _make_whale(self, wx=50_000.0, wy=50_000.0) -> tuple[Creature, Ship]:
        c = spawn_creature("w1", "void_whale", wx, wy)
        ship = Ship()
        ship.x = 60_000.0  # far away
        ship.y = 50_000.0
        return c, ship

    def test_idle_state_moves_slowly(self):
        c, ship = self._make_whale()
        x0, y0 = c.x, c.y
        tick_creatures([c], ship, 1.0)
        dist = math.hypot(c.x - x0, c.y - y0)
        assert dist > 0  # creature moved
        assert c.behaviour_state == "idle"

    def test_flees_when_player_close(self):
        c = spawn_creature("w1", "void_whale", 50_000.0, 50_000.0)
        ship = Ship()
        ship.x = 50_100.0  # within flee_range=1000
        ship.y = 50_000.0
        tick_creatures([c], ship, 0.1)
        assert c.behaviour_state == "fleeing"

    def test_wake_active_when_fleeing(self):
        c = spawn_creature("w1", "void_whale", 50_000.0, 50_000.0)
        ship = Ship()
        ship.x = 50_100.0
        ship.y = 50_000.0
        tick_creatures([c], ship, 0.1)
        assert c.wake_active is True
        assert c.wake_timer > 0

    def test_wake_timer_decrements(self):
        c = spawn_creature("w1", "void_whale", 50_000.0, 50_000.0)
        ship = Ship()
        ship.x = 50_100.0
        ship.y = 50_000.0
        tick_creatures([c], ship, 0.1)  # trigger flee + wake
        timer0 = c.wake_timer
        tick_creatures([c], ship, 1.0)
        assert c.wake_timer < timer0

    def test_wake_deactivates_after_timeout(self):
        c = spawn_creature("w1", "void_whale", 50_000.0, 50_000.0)
        ship = Ship()
        ship.x = 50_100.0
        ship.y = 50_000.0
        tick_creatures([c], ship, 0.1)  # trigger flee + wake
        # Fast-forward the wake timer
        c.wake_timer = 0.01
        tick_creatures([c], ship, 0.05)
        assert c.wake_active is False

    def test_returns_to_idle_when_far_enough(self):
        c = spawn_creature("w1", "void_whale", 50_000.0, 50_000.0)
        c.behaviour_state = "fleeing"
        c.wake_timer = 0.0
        c.wake_active = False
        ship = Ship()
        # Place ship far away (beyond flee_range * 5 = 5000)
        ship.x = 60_000.0
        ship.y = 50_000.0
        tick_creatures([c], ship, 0.1)
        assert c.behaviour_state == "idle"

    def test_no_beam_hits_ever(self):
        c = spawn_creature("w1", "void_whale", 50_000.0, 50_000.0)
        ship = Ship()
        ship.x = 50_100.0
        ship.y = 50_000.0
        hits = tick_creatures([c], ship, 1.0)
        assert len(hits) == 0

    def test_velocity_increases_when_fleeing(self):
        c = spawn_creature("w1", "void_whale", 50_000.0, 50_000.0)
        c.behaviour_state = "fleeing"
        c.wake_active = True
        c.wake_timer = 5.0
        ship = Ship()
        ship.x = 50_100.0
        ship.y = 50_000.0
        tick_creatures([c], ship, 0.1)
        params = CREATURE_TYPE_PARAMS["void_whale"]
        assert c.velocity == params["speed"]


# ---------------------------------------------------------------------------
# 3. Rift stalker AI
# ---------------------------------------------------------------------------

class TestRiftStalkerAI:
    def setup_method(self):
        glc.reset()

    def _make_stalker(self, sx=50_000.0, sy=50_000.0) -> tuple[Creature, Ship]:
        c = spawn_creature("rs1", "rift_stalker", sx, sy)
        ship = Ship()
        ship.x = 80_000.0  # far outside territory
        ship.y = 50_000.0
        return c, ship

    def test_idle_patrols_within_territory(self):
        c, ship = self._make_stalker()
        x0, y0 = c.x, c.y
        tick_creatures([c], ship, 0.5)
        assert c.behaviour_state == "idle"

    def test_becomes_aggressive_on_territory_breach(self):
        c = spawn_creature("rs1", "rift_stalker", 50_000.0, 50_000.0)
        ship = Ship()
        # Place player inside territory radius (12000)
        ship.x = 55_000.0
        ship.y = 50_000.0
        tick_creatures([c], ship, 0.1)
        assert c.behaviour_state == "aggressive"

    def test_attacks_when_in_weapon_range(self):
        c = spawn_creature("rs1", "rift_stalker", 50_000.0, 50_000.0)
        c.behaviour_state = "aggressive"
        ship = Ship()
        ship.x = 51_000.0  # within weapon_range=3000
        ship.y = 50_000.0
        tick_creatures([c], ship, 0.1)
        assert c.behaviour_state == "attacking"

    def test_fires_beam_when_attacking(self):
        c = spawn_creature("rs1", "rift_stalker", 50_000.0, 50_000.0)
        c.behaviour_state = "attacking"
        c.beam_cooldown = 0.0
        ship = Ship()
        ship.x = 51_000.0
        ship.y = 50_000.0
        hits = tick_creatures([c], ship, 0.5)
        assert len(hits) == 1
        assert hits[0].attacker_id == "rs1"
        assert hits[0].damage == CREATURE_TYPE_PARAMS["rift_stalker"]["beam_dmg"]

    def test_regenerates_hull(self):
        c = spawn_creature("rs1", "rift_stalker", 50_000.0, 50_000.0)
        c.hull = 50.0
        c.hull_max = 120.0
        ship = Ship()
        ship.x = 80_000.0
        ship.y = 50_000.0
        # regen_timer needs to reach 1.0
        c.regen_timer = 0.95
        tick_creatures([c], ship, 0.1)
        assert c.hull > 50.0

    def test_sedated_no_attack(self):
        world = fresh_world()
        c = spawn_creature("rs1", "rift_stalker", 50_000.0, 50_000.0)
        c.behaviour_state = "attacking"
        c.beam_cooldown = 0.0
        c.sedated_timer = 60.0
        world.creatures.append(c)
        hits = tick_creatures([c], world.ship, 1.0)
        assert len(hits) == 0
        assert c.behaviour_state == "sedated"

    def test_sedation_wears_off(self):
        c = spawn_creature("rs1", "rift_stalker", 50_000.0, 50_000.0)
        c.sedated_timer = 0.05
        ship = Ship()
        ship.x = 80_000.0
        ship.y = 50_000.0
        tick_creatures([c], ship, 0.1)
        assert c.sedated_timer == 0.0

    def test_flees_when_low_hp(self):
        c = spawn_creature("rs1", "rift_stalker", 50_000.0, 50_000.0)
        c.behaviour_state = "attacking"
        c.hull = c.hull_max * 0.15  # below 20% threshold
        ship = Ship()
        ship.x = 51_000.0
        ship.y = 50_000.0
        tick_creatures([c], ship, 0.1)
        assert c.behaviour_state == "fleeing"

    def test_sedate_creature_api(self):
        world = fresh_world()
        c = spawn_creature("rs1", "rift_stalker", 50_000.0, 50_000.0)
        world.creatures.append(c)
        result = glc.sedate_creature("rs1", world)
        assert result is True
        assert c.sedated_timer == CREATURE_TYPE_PARAMS["rift_stalker"]["sedate_duration"]
        assert c.behaviour_state == "sedated"

    def test_sedate_wrong_id_returns_false(self):
        world = fresh_world()
        result = glc.sedate_creature("nonexistent", world)
        assert result is False


# ---------------------------------------------------------------------------
# 4. Hull leech AI
# ---------------------------------------------------------------------------

class TestHullLeechAI:
    def setup_method(self):
        glc.reset()

    def test_idle_wanders(self):
        c = spawn_creature("hl1", "hull_leech", 50_000.0, 50_000.0)
        ship = Ship()
        ship.x = 80_000.0  # far away
        ship.y = 50_000.0
        x0, y0 = c.x, c.y
        tick_creatures([c], ship, 1.0)
        dist = math.hypot(c.x - x0, c.y - y0)
        assert dist > 0
        assert c.behaviour_state == "idle"

    def test_approaches_player_when_close(self):
        c = spawn_creature("hl1", "hull_leech", 50_000.0, 50_000.0)
        ship = Ship()
        ship.x = 51_000.0  # within 5000 approach range
        ship.y = 50_000.0
        tick_creatures([c], ship, 0.1)
        assert c.behaviour_state == "approaching"

    def test_attaches_when_in_attach_range(self):
        c = spawn_creature("hl1", "hull_leech", 50_000.0, 50_000.0)
        c.behaviour_state = "approaching"
        ship = Ship()
        ship.x = 50_200.0  # within attach_range=500
        ship.y = 50_000.0
        tick_creatures([c], ship, 0.1)
        assert c.attached is True
        assert c.behaviour_state == "attached"

    def test_detected_after_attach(self):
        c = spawn_creature("hl1", "hull_leech", 50_000.0, 50_000.0)
        assert c.detected is False
        c.behaviour_state = "approaching"
        ship = Ship()
        ship.x = 50_200.0
        ship.y = 50_000.0
        tick_creatures([c], ship, 0.1)
        assert c.detected is True

    def test_deals_damage_on_interval(self):
        c = spawn_creature("hl1", "hull_leech", 50_000.0, 50_000.0)
        c.attached = True
        c.behaviour_state = "attached"
        c.leech_damage_timer = 0.05  # almost expired
        ship = Ship()
        ship.x = 50_000.0
        ship.y = 50_000.0
        hits = tick_creatures([c], ship, 0.1)
        assert len(hits) == 1
        assert hits[0].damage == CREATURE_TYPE_PARAMS["hull_leech"]["damage_per_interval"]

    def test_not_detected_initially(self):
        c = spawn_creature("hl1", "hull_leech", 0.0, 0.0)
        assert c.detected is False

    def test_detected_after_bio_scan(self):
        c = spawn_creature("hl1", "hull_leech", 0.0, 0.0)
        assert c.detected is False
        glc.advance_bio_study([c], 1.0)
        assert c.detected is True

    def test_remove_leech_depressurise(self):
        world = fresh_world()
        c = spawn_creature("hl1", "hull_leech", 50_000.0, 50_000.0)
        c.attached = True
        world.creatures.append(c)
        result = glc.remove_leech_depressurise("hl1", world)
        assert result is True
        assert len(world.creatures) == 0

    def test_remove_leech_electrical(self):
        world = fresh_world()
        c = spawn_creature("hl1", "hull_leech", 50_000.0, 50_000.0)
        world.creatures.append(c)
        result = glc.remove_leech_electrical("hl1", world)
        assert result is True
        assert not any(x.id == "hl1" for x in world.creatures)

    def test_remove_leech_eva(self):
        world = fresh_world()
        c = spawn_creature("hl1", "hull_leech", 50_000.0, 50_000.0)
        world.creatures.append(c)
        result = glc.remove_leech_eva("hl1", world)
        assert result is True
        assert len(world.creatures) == 0


# ---------------------------------------------------------------------------
# 5. Swarm AI
# ---------------------------------------------------------------------------

class TestSwarmAI:
    def setup_method(self):
        glc.reset()

    def test_idle_when_player_far(self):
        c = spawn_creature("sw1", "swarm", 50_000.0, 50_000.0)
        ship = Ship()
        ship.x = 80_000.0
        ship.y = 50_000.0
        tick_creatures([c], ship, 0.1)
        assert c.behaviour_state == "idle"

    def test_attacks_player_in_swarm_range(self):
        c = spawn_creature("sw1", "swarm", 50_000.0, 50_000.0)
        ship = Ship()
        ship.x = 53_000.0  # within swarm_range=8000
        ship.y = 50_000.0
        tick_creatures([c], ship, 0.1)
        assert c.behaviour_state == "attacking"

    def test_fires_beam_when_attacking(self):
        c = spawn_creature("sw1", "swarm", 50_000.0, 50_000.0)
        c.behaviour_state = "attacking"
        c.beam_cooldown = 0.0
        ship = Ship()
        ship.x = 50_500.0  # within weapon_range=6000
        ship.y = 50_000.0
        hits = tick_creatures([c], ship, 0.1)
        assert len(hits) == 1
        assert hits[0].damage == CREATURE_TYPE_PARAMS["swarm"]["beam_dmg"]

    def test_adapts_to_beam_weapon(self):
        world = fresh_world()
        c = spawn_creature("sw1", "swarm", 50_000.0, 50_000.0)
        world.creatures.append(c)
        glc.notify_weapon_hit("sw1", "beam", world)
        assert c.adaptation_state == "spread"

    def test_adapts_to_torpedo(self):
        world = fresh_world()
        c = spawn_creature("sw1", "swarm", 50_000.0, 50_000.0)
        world.creatures.append(c)
        glc.notify_weapon_hit("sw1", "torpedo", world)
        assert c.adaptation_state == "clustered"

    def test_disperses_from_ew_disrupt(self):
        world = fresh_world()
        c = spawn_creature("sw1", "swarm", 50_000.0, 50_000.0)
        c.behaviour_state = "attacking"
        world.creatures.append(c)
        result = glc.ew_disrupt_swarm("sw1", world)
        assert result is True
        assert c.behaviour_state == "dispersed"

    def test_dispersed_flees_no_attack(self):
        c = spawn_creature("sw1", "swarm", 50_000.0, 50_000.0)
        c.behaviour_state = "dispersed"
        c.beam_cooldown = 0.0
        ship = Ship()
        ship.x = 50_500.0
        ship.y = 50_000.0
        hits = tick_creatures([c], ship, 0.5)
        assert len(hits) == 0

    def test_ew_disrupt_wrong_type_returns_false(self):
        world = fresh_world()
        c = spawn_creature("w1", "void_whale", 50_000.0, 50_000.0)
        world.creatures.append(c)
        result = glc.ew_disrupt_swarm("w1", world)
        assert result is False


# ---------------------------------------------------------------------------
# 6. Leviathan AI
# ---------------------------------------------------------------------------

class TestLeviathanAI:
    def setup_method(self):
        glc.reset()

    def test_dormant_initially(self):
        c = spawn_creature("lev1", "leviathan", 50_000.0, 50_000.0)
        assert c.behaviour_state == "dormant"
        assert c.velocity == 0.0

    def test_wakes_on_player_approach(self):
        c = spawn_creature("lev1", "leviathan", 50_000.0, 50_000.0)
        ship = Ship()
        # within wake_range=20000
        ship.x = 60_000.0
        ship.y = 50_000.0
        tick_creatures([c], ship, 0.1)
        assert c.behaviour_state == "wandering"

    def test_wakes_on_damage(self):
        c = spawn_creature("lev1", "leviathan", 50_000.0, 50_000.0)
        c.hull = c.hull_max - 10.0  # simulate damage
        ship = Ship()
        ship.x = 0.0  # far away
        ship.y = 0.0
        tick_creatures([c], ship, 0.1)
        assert c.behaviour_state == "wandering"

    def test_wanders_north(self):
        c = spawn_creature("lev1", "leviathan", 50_000.0, 50_000.0)
        c.behaviour_state = "wandering"
        c.heading = 0.0
        ship = Ship()
        ship.x = 0.0
        ship.y = 0.0
        y0 = c.y
        tick_creatures([c], ship, 1.0)
        assert c.y < y0  # north = decreasing y

    def test_fires_beam_when_agitated(self):
        c = spawn_creature("lev1", "leviathan", 50_000.0, 50_000.0)
        c.behaviour_state = "agitated"
        c.beam_cooldown = 0.0
        ship = Ship()
        ship.x = 50_500.0  # within weapon_range=8000
        ship.y = 50_000.0
        hits = tick_creatures([c], ship, 0.1)
        assert len(hits) == 1
        assert hits[0].damage == CREATURE_TYPE_PARAMS["leviathan"]["beam_dmg"]

    def test_redirected_when_comm_complete(self):
        c = spawn_creature("lev1", "leviathan", 50_000.0, 50_000.0)
        c.behaviour_state = "wandering"
        c.communication_progress = 100.0
        ship = Ship()
        ship.x = 0.0
        ship.y = 0.0
        tick_creatures([c], ship, 0.1)
        assert c.behaviour_state == "redirected"

    def test_set_comm_progress_api(self):
        world = fresh_world()
        c = spawn_creature("lev1", "leviathan", 50_000.0, 50_000.0)
        world.creatures.append(c)
        result = glc.set_comm_progress("lev1", 75.0, world)
        assert result is True
        assert c.communication_progress == 75.0

    def test_moves_south_when_redirected(self):
        c = spawn_creature("lev1", "leviathan", 50_000.0, 50_000.0)
        c.behaviour_state = "redirected"
        c.heading = 180.0
        ship = Ship()
        ship.x = 0.0
        ship.y = 0.0
        y0 = c.y
        tick_creatures([c], ship, 1.0)
        assert c.y > y0  # south = increasing y


# ---------------------------------------------------------------------------
# 7. Sensor contacts include creatures
# ---------------------------------------------------------------------------

class TestCreatureSensors:
    def test_detected_creature_in_contacts(self):
        world = fresh_world()
        # Place creature close to ship
        c = spawn_creature("w1", "void_whale", 50_001.0, 50_000.0)
        c.detected = True
        world.creatures.append(c)
        contacts = build_sensor_contacts(world, world.ship)
        ids = [ct["id"] for ct in contacts]
        assert "w1" in ids

    def test_creature_contact_has_kind_field(self):
        world = fresh_world()
        c = spawn_creature("w1", "void_whale", 50_001.0, 50_000.0)
        c.detected = True
        world.creatures.append(c)
        contacts = build_sensor_contacts(world, world.ship)
        ct = next(ct for ct in contacts if ct["id"] == "w1")
        assert ct["kind"] == "creature"
        assert ct["creature_type"] == "void_whale"

    def test_detected_creature_always_in_contacts(self):
        """Detected creatures included regardless of distance (no range filter)."""
        world = fresh_world()
        c = spawn_creature("w1", "void_whale", 0.0, 0.0)
        c.detected = True
        world.creatures.append(c)
        contacts = build_sensor_contacts(world, world.ship)
        ids = [ct["id"] for ct in contacts]
        assert "w1" in ids

    def test_undetected_leech_not_in_contacts(self):
        world = fresh_world()
        c = spawn_creature("hl1", "hull_leech", 50_001.0, 50_000.0)
        assert c.detected is False
        world.creatures.append(c)
        contacts = build_sensor_contacts(world, world.ship)
        ids = [ct["id"] for ct in contacts]
        assert "hl1" not in ids

    def test_detected_leech_in_contacts(self):
        world = fresh_world()
        c = spawn_creature("hl1", "hull_leech", 50_001.0, 50_000.0)
        c.detected = True
        world.creatures.append(c)
        contacts = build_sensor_contacts(world, world.ship)
        ids = [ct["id"] for ct in contacts]
        assert "hl1" in ids


# ---------------------------------------------------------------------------
# 8. BIO scan study advancement
# ---------------------------------------------------------------------------

class TestBioScanStudy:
    def setup_method(self):
        glc.reset()

    def test_advance_bio_study_progresses(self):
        c = spawn_creature("w1", "void_whale", 0.0, 0.0)
        assert c.study_progress == 0.0
        glc.advance_bio_study([c], 10.0)
        assert c.study_progress > 0.0

    def test_advance_bio_study_reveals_hull_leech(self):
        c = spawn_creature("hl1", "hull_leech", 0.0, 0.0)
        assert c.detected is False
        glc.advance_bio_study([c], 0.1)
        assert c.detected is True

    def test_advance_bio_study_capped_at_100(self):
        c = spawn_creature("w1", "void_whale", 0.0, 0.0)
        c.study_progress = 99.0
        glc.advance_bio_study([c], 999.0)
        assert c.study_progress == 100.0

    def test_advance_bio_study_multiple_creatures(self):
        creatures = [
            spawn_creature("c1", "void_whale", 0.0, 0.0),
            spawn_creature("c2", "rift_stalker", 1.0, 0.0),
            spawn_creature("c3", "hull_leech", 2.0, 0.0),
        ]
        glc.advance_bio_study(creatures, 1.0)
        for c in creatures:
            assert c.study_progress > 0.0


# ---------------------------------------------------------------------------
# 9. game_loop_creatures module events
# ---------------------------------------------------------------------------

class TestGameLoopCreatureEvents:
    def setup_method(self):
        glc.reset()

    def test_tick_returns_beam_hits_and_events(self):
        world = fresh_world()
        c = spawn_creature("rs1", "rift_stalker", 50_000.0, 50_000.0)
        c.behaviour_state = "attacking"
        c.beam_cooldown = 0.0
        world.ship.x = 51_000.0
        world.ship.y = 50_000.0
        world.creatures.append(c)
        hits, events = glc.tick(world, 0.5)
        assert len(hits) == 1
        assert hits[0].attacker_id == "rs1"

    def test_wake_started_event_fires(self):
        world = fresh_world()
        c = spawn_creature("w1", "void_whale", 50_000.0, 50_000.0)
        # Set up fleeing state and wake
        c.behaviour_state = "fleeing"
        c.wake_active = True
        c.wake_timer = 5.0
        world.creatures.append(c)
        _, events = glc.tick(world, 0.1)
        event_types = [e["type"] for e in events]
        assert "creature.wake_started" in event_types

    def test_wake_ended_event_fires(self):
        world = fresh_world()
        c = spawn_creature("w1", "void_whale", 50_000.0, 50_000.0)
        c.behaviour_state = "fleeing"
        c.wake_active = True
        c.wake_timer = 5.0
        world.creatures.append(c)
        glc.tick(world, 0.1)  # tick once to record wake_was_active=True
        c.wake_timer = 0.01
        _, events = glc.tick(world, 0.05)  # timer expires
        event_types = [e["type"] for e in events]
        assert "creature.wake_ended" in event_types

    def test_study_complete_event_fires_once(self):
        world = fresh_world()
        c = spawn_creature("w1", "void_whale", 0.0, 0.0)
        c.study_progress = 99.9
        world.creatures.append(c)
        # Advance study to complete
        glc.advance_bio_study(world.creatures, 1.0)
        _, events = glc.tick(world, 0.1)
        study_events = [e for e in events if e["type"] == "creature.study_complete"]
        assert len(study_events) == 1
        # Second tick — should NOT fire again
        _, events2 = glc.tick(world, 0.1)
        study_events2 = [e for e in events2 if e["type"] == "creature.study_complete"]
        assert len(study_events2) == 0

    def test_creature_destroyed_event_and_removal(self):
        world = fresh_world()
        c = spawn_creature("w1", "void_whale", 0.0, 0.0)
        c.hull = 0.0  # dead
        world.creatures.append(c)
        _, events = glc.tick(world, 0.1)
        destroyed_events = [e for e in events if e["type"] == "creature.destroyed"]
        assert len(destroyed_events) == 1
        assert destroyed_events[0]["creature_id"] == "w1"
        assert len(world.creatures) == 0  # removed from world

    def test_leech_attachment_event(self):
        world = fresh_world()
        c = spawn_creature("hl1", "hull_leech", 50_000.0, 50_000.0)
        c.attached = True
        c.detected = True
        world.creatures.append(c)
        _, events = glc.tick(world, 0.1)
        attach_events = [e for e in events if e["type"] == "creature.leech_attached"]
        assert len(attach_events) == 1

    def test_comm_complete_event_fires_once(self):
        world = fresh_world()
        c = spawn_creature("lev1", "leviathan", 50_000.0, 50_000.0)
        c.communication_progress = 100.0
        world.creatures.append(c)
        _, events = glc.tick(world, 0.1)
        comm_events = [e for e in events if e["type"] == "creature.communication_complete"]
        assert len(comm_events) == 1
        _, events2 = glc.tick(world, 0.1)
        comm_events2 = [e for e in events2 if e["type"] == "creature.communication_complete"]
        assert len(comm_events2) == 0


# ---------------------------------------------------------------------------
# 10. Mission graph creature triggers
# ---------------------------------------------------------------------------

class TestMissionGraphCreatureTriggers:
    def _graph_with_trigger(self, trigger: dict):
        """Helper: build a MissionGraph with a single objective using the trigger."""
        mission = {
            "nodes": [{"id": "n1", "type": "objective", "text": "test", "trigger": trigger}],
            "edges": [],
            "start_node": "n1",
            "victory_nodes": ["n1"],
            "defeat_condition": None,
        }
        return mg_module.MissionGraph(mission)

    def test_creature_state_trigger(self):
        world = fresh_world()
        c = spawn_creature("w1", "void_whale", 0.0, 0.0)
        c.behaviour_state = "fleeing"
        world.creatures.append(c)
        graph = self._graph_with_trigger({"type": "creature_state", "creature_id": "w1", "state": "fleeing"})
        # Activate the node manually
        graph._graph_nodes["n1"].status = "active"
        graph._active_set.add("n1")
        completed = graph.tick(world, world.ship, 0.1)
        assert "n1" in completed

    def test_creature_state_trigger_wrong_state(self):
        world = fresh_world()
        c = spawn_creature("w1", "void_whale", 0.0, 0.0)
        c.behaviour_state = "idle"
        world.creatures.append(c)
        trigger = {"type": "creature_state", "creature_id": "w1", "state": "fleeing"}
        graph = self._graph_with_trigger(trigger)
        graph._graph_nodes["n1"].status = "active"
        graph._active_set.add("n1")
        completed = graph.tick(world, world.ship, 0.1)
        assert "n1" not in completed

    def test_creature_destroyed_trigger_false_before_notify(self):
        world = fresh_world()
        trigger = {"type": "creature_destroyed", "creature_id": "w1"}
        graph = self._graph_with_trigger(trigger)
        graph._graph_nodes["n1"].status = "active"
        graph._active_set.add("n1")
        completed = graph.tick(world, world.ship, 0.1)
        assert "n1" not in completed

    def test_creature_destroyed_trigger_after_notify(self):
        world = fresh_world()
        trigger = {"type": "creature_destroyed", "creature_id": "w1"}
        graph = self._graph_with_trigger(trigger)
        graph._graph_nodes["n1"].status = "active"
        graph._active_set.add("n1")
        graph.notify_creature_destroyed("w1")
        completed = graph.tick(world, world.ship, 0.1)
        assert "n1" in completed

    def test_creature_study_complete_trigger(self):
        world = fresh_world()
        c = spawn_creature("w1", "void_whale", 0.0, 0.0)
        c.study_progress = 100.0
        world.creatures.append(c)
        trigger = {"type": "creature_study_complete", "creature_id": "w1"}
        graph = self._graph_with_trigger(trigger)
        graph._graph_nodes["n1"].status = "active"
        graph._active_set.add("n1")
        completed = graph.tick(world, world.ship, 0.1)
        assert "n1" in completed

    def test_creature_study_complete_trigger_not_ready(self):
        world = fresh_world()
        c = spawn_creature("w1", "void_whale", 0.0, 0.0)
        c.study_progress = 50.0
        world.creatures.append(c)
        trigger = {"type": "creature_study_complete", "creature_id": "w1"}
        graph = self._graph_with_trigger(trigger)
        graph._graph_nodes["n1"].status = "active"
        graph._active_set.add("n1")
        completed = graph.tick(world, world.ship, 0.1)
        assert "n1" not in completed

    def test_creature_communication_complete_trigger(self):
        world = fresh_world()
        c = spawn_creature("lev1", "leviathan", 0.0, 0.0)
        c.communication_progress = 100.0
        world.creatures.append(c)
        trigger = {"type": "creature_communication_complete", "creature_id": "lev1"}
        graph = self._graph_with_trigger(trigger)
        graph._graph_nodes["n1"].status = "active"
        graph._active_set.add("n1")
        completed = graph.tick(world, world.ship, 0.1)
        assert "n1" in completed

    def test_no_creatures_type_trigger(self):
        world = fresh_world()
        # No void whales in world
        trigger = {"type": "no_creatures_type", "creature_type": "void_whale"}
        graph = self._graph_with_trigger(trigger)
        graph._graph_nodes["n1"].status = "active"
        graph._active_set.add("n1")
        completed = graph.tick(world, world.ship, 0.1)
        assert "n1" in completed

    def test_no_creatures_type_trigger_false_when_present(self):
        world = fresh_world()
        c = spawn_creature("w1", "void_whale", 0.0, 0.0)
        world.creatures.append(c)
        trigger = {"type": "no_creatures_type", "creature_type": "void_whale"}
        graph = self._graph_with_trigger(trigger)
        graph._graph_nodes["n1"].status = "active"
        graph._active_set.add("n1")
        completed = graph.tick(world, world.ship, 0.1)
        assert "n1" not in completed

    def test_serialise_includes_destroyed_creature_ids(self):
        world = fresh_world()
        mission = {
            "nodes": [{"id": "n1", "type": "checkpoint", "text": "test"}],
            "edges": [],
            "start_node": "n1",
            "victory_nodes": ["n1"],
            "defeat_condition": None,
        }
        graph = mg_module.MissionGraph(mission)
        graph.notify_creature_destroyed("w1")
        graph.notify_creature_destroyed("w2")
        state = graph.serialise_state()
        assert set(state["destroyed_creature_ids"]) == {"w1", "w2"}

    def test_deserialise_restores_destroyed_creature_ids(self):
        world = fresh_world()
        mission = {
            "nodes": [{"id": "n1", "type": "checkpoint", "text": "test"}],
            "edges": [],
            "start_node": "n1",
            "victory_nodes": ["n1"],
            "defeat_condition": None,
        }
        graph = mg_module.MissionGraph(mission)
        graph.notify_creature_destroyed("w1")
        state = graph.serialise_state()
        # New graph, deserialise
        graph2 = mg_module.MissionGraph(mission)
        graph2.deserialise_state(state)
        assert "w1" in graph2._destroyed_creature_ids
