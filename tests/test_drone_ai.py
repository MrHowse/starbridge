"""Tests for server/systems/drone_ai.py — v0.06.5 drone flight model and AI."""
from __future__ import annotations

import pytest

from server.models.drones import (
    RESCUE_PICKUP_TIME,
    Decoy,
    create_drone,
)
from server.models.drone_missions import (
    create_patrol_mission,
    create_sar_mission,
    create_survey_mission,
    reset_mission_counter,
)
from server.systems.drone_ai import (
    ATTACK_AMMO_PER_PASS,
    ATTACK_COOLDOWN,
    BINGO_AUTO_RECALL_DELAY,
    CRITICAL_HEADING_DRIFT,
    ECM_FUEL_MULTIPLIER,
    ECM_JAM_RANGE,
    DroneWorldContext,
    _orbit_point,
    apply_damage_to_drone,
    deploy_buoy,
    initiate_rtb,
    should_auto_recall,
    tick_decoys,
    tick_drone,
)
from server.models.drones import BINGO_FUEL_SAFETY_MARGIN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def setup_function():
    reset_mission_counter()


def _make_scout(pos=(0.0, 0.0), fuel=100.0, status="active"):
    d = create_drone("drone_s1", "scout", "Hawk")
    d.position = pos
    d.fuel = fuel
    d.status = status
    return d


def _make_combat(pos=(0.0, 0.0), fuel=100.0, ammo=100.0, status="active"):
    d = create_drone("drone_c1", "combat", "Fang")
    d.position = pos
    d.fuel = fuel
    d.ammo = ammo
    d.status = status
    return d


def _make_rescue(pos=(0.0, 0.0), fuel=100.0, status="active"):
    d = create_drone("drone_r1", "rescue", "Angel")
    d.position = pos
    d.fuel = fuel
    d.status = status
    return d


def _make_survey(pos=(0.0, 0.0), fuel=100.0, status="active"):
    d = create_drone("drone_u1", "survey", "Compass")
    d.position = pos
    d.fuel = fuel
    d.status = status
    return d


def _make_ecm(pos=(0.0, 0.0), fuel=100.0, status="active"):
    d = create_drone("drone_e1", "ecm_drone", "Ghost")
    d.position = pos
    d.fuel = fuel
    d.status = status
    return d


def _ctx(ship_x=0.0, ship_y=0.0, contacts=None, survivors=None, in_combat=False, tick=0):
    return DroneWorldContext(
        ship_x=ship_x, ship_y=ship_y,
        contacts=contacts or [],
        survivors=survivors or [],
        in_combat=in_combat,
        tick=tick,
    )


# ---------------------------------------------------------------------------
# Basic flight model
# ---------------------------------------------------------------------------

class TestFlightModel:
    def test_fuel_consumption(self):
        d = _make_scout()
        ctx = _ctx()
        tick_drone(d, 1.0, ctx)
        assert d.fuel == pytest.approx(100.0 - d.fuel_consumption, abs=0.01)

    def test_inactive_drone_not_ticked(self):
        d = _make_scout(status="hangar")
        ctx = _ctx()
        events = tick_drone(d, 1.0, ctx)
        assert events == []
        assert d.fuel == 100.0

    def test_drone_moves_forward(self):
        d = _make_scout(pos=(0.0, 0.0))
        d.heading = 0.0  # north
        d.loiter_point = (0.0, -50000.0)  # force movement
        ctx = _ctx()
        tick_drone(d, 1.0, ctx)
        # Should have moved (y decreases when heading north)
        assert d.position[1] < 0.0

    def test_turn_toward_target(self):
        d = _make_scout(pos=(0.0, 0.0))
        d.heading = 0.0
        d.loiter_point = (10000.0, 0.0)  # east
        ctx = _ctx()
        tick_drone(d, 1.0, ctx)
        # Heading should have increased (turning clockwise toward east)
        assert d.heading > 0.0


# ---------------------------------------------------------------------------
# Fuel mechanics
# ---------------------------------------------------------------------------

class TestFuelMechanics:
    def test_fuel_exhaustion_marks_lost(self):
        d = _make_scout(fuel=0.05)
        ctx = _ctx()
        events = tick_drone(d, 1.0, ctx)
        assert d.status == "lost"
        assert d.fuel == 0.0
        ev_types = [e.event_type for e in events]
        assert "drone_lost" in ev_types

    def test_fuel_exhaustion_includes_cargo_info(self):
        d = _make_rescue(fuel=0.05)
        d.cargo_current = 3
        ctx = _ctx()
        events = tick_drone(d, 1.0, ctx)
        lost_ev = [e for e in events if e.event_type == "drone_lost"][0]
        assert lost_ev.data["cargo_current"] == 3

    def test_bingo_fuel_warning(self):
        d = _make_scout(pos=(50000.0, 0.0), fuel=5.0)
        ctx = _ctx(ship_x=0.0, ship_y=0.0)
        events = tick_drone(d, 0.1, ctx)
        ev_types = [e.event_type for e in events]
        assert "bingo_fuel" in ev_types
        assert d.bingo_acknowledged is True

    def test_bingo_only_fires_once(self):
        d = _make_scout(pos=(50000.0, 0.0), fuel=5.0)
        ctx = _ctx()
        tick_drone(d, 0.1, ctx)
        assert d.bingo_acknowledged is True
        events2 = tick_drone(d, 0.1, ctx)
        bingo_events = [e for e in events2 if e.event_type == "bingo_fuel"]
        assert len(bingo_events) == 0


# ---------------------------------------------------------------------------
# Bingo auto-recall
# ---------------------------------------------------------------------------

class TestBingoAutoRecall:
    def test_auto_recall_after_delay(self):
        d = _make_scout()
        d.bingo_acknowledged = True
        assert should_auto_recall(d, BINGO_AUTO_RECALL_DELAY, False) is True

    def test_no_auto_recall_before_delay(self):
        d = _make_scout()
        d.bingo_acknowledged = True
        assert should_auto_recall(d, BINGO_AUTO_RECALL_DELAY - 1, False) is False

    def test_no_auto_recall_with_critical_cargo(self):
        d = _make_rescue()
        d.bingo_acknowledged = True
        d.cargo_current = 2
        assert should_auto_recall(d, BINGO_AUTO_RECALL_DELAY + 10, True) is False

    def test_initiate_rtb(self):
        d = _make_scout()
        ev = initiate_rtb(d)
        assert d.ai_behaviour == "rtb"
        assert ev.event_type == "drone_rtb"

    def test_rtb_navigates_to_ship(self):
        d = _make_scout(pos=(10000.0, 0.0))
        d.ai_behaviour = "rtb"
        ctx = _ctx(ship_x=0.0, ship_y=0.0)
        tick_drone(d, 1.0, ctx)
        # Should be closer to ship after tick
        import math
        dist = math.sqrt(d.position[0]**2 + d.position[1]**2)
        assert dist < 10000.0


# ---------------------------------------------------------------------------
# Scout AI
# ---------------------------------------------------------------------------

class TestScoutAI:
    def test_detects_contacts_in_range(self):
        d = _make_scout(pos=(0.0, 0.0))
        contact = {"id": "enemy_1", "x": 5000.0, "y": 0.0, "kind": "enemy"}
        ctx = _ctx(contacts=[contact])
        events = tick_drone(d, 0.1, ctx)
        detect = [e for e in events if e.event_type == "contact_detected"]
        assert len(detect) == 1
        assert detect[0].data["contact_id"] == "enemy_1"
        assert "enemy_1" in d.known_contacts

    def test_does_not_detect_out_of_range(self):
        d = _make_scout(pos=(0.0, 0.0))
        # Effective sensor range for scout is 25000 (or 18750 if damaged)
        contact = {"id": "enemy_1", "x": 100000.0, "y": 0.0, "kind": "enemy"}
        ctx = _ctx(contacts=[contact])
        events = tick_drone(d, 0.1, ctx)
        detect = [e for e in events if e.event_type == "contact_detected"]
        assert len(detect) == 0

    def test_does_not_redetect_known_contact(self):
        d = _make_scout(pos=(0.0, 0.0))
        d.known_contacts.add("enemy_1")
        contact = {"id": "enemy_1", "x": 5000.0, "y": 0.0, "kind": "enemy"}
        ctx = _ctx(contacts=[contact])
        events = tick_drone(d, 0.1, ctx)
        detect = [e for e in events if e.event_type == "contact_detected"]
        assert len(detect) == 0

    def test_tracks_designated_contact(self):
        d = _make_scout(pos=(0.0, 0.0))
        d.contact_of_interest = "enemy_1"
        contact = {"id": "enemy_1", "x": 5000.0, "y": 0.0, "kind": "enemy"}
        ctx = _ctx(contacts=[contact])
        events = tick_drone(d, 0.1, ctx)
        tracked = [e for e in events if e.event_type == "contact_tracked"]
        assert len(tracked) == 1

    def test_flees_from_threat(self):
        d = _make_scout(pos=(0.0, 0.0))
        d.threat_detected = "enemy_1"
        contact = {"id": "enemy_1", "x": 5000.0, "y": 0.0}
        ctx = _ctx(contacts=[contact])
        events = tick_drone(d, 1.0, ctx)
        evade = [e for e in events if e.event_type == "threat_evading"]
        assert len(evade) == 1
        # Should be moving away from threat (further from 5000, 0)
        assert d.position[0] < 0.0 or d.position[1] != 0.0

    def test_contacts_found_counter(self):
        d = _make_scout(pos=(0.0, 0.0))
        contacts = [
            {"id": "enemy_1", "x": 1000.0, "y": 0.0, "kind": "enemy"},
            {"id": "enemy_2", "x": 2000.0, "y": 0.0, "kind": "enemy"},
        ]
        ctx = _ctx(contacts=contacts)
        tick_drone(d, 0.1, ctx)
        assert d.contacts_found == 2


# ---------------------------------------------------------------------------
# Combat AI
# ---------------------------------------------------------------------------

class TestCombatAI:
    def test_attack_run_in_range(self):
        d = _make_combat(pos=(0.0, 0.0))
        d.ai_behaviour = "engage"
        d.contact_of_interest = "enemy_1"
        # Place target within weapon range (10000)
        contact = {"id": "enemy_1", "x": 5000.0, "y": 0.0}
        ctx = _ctx(contacts=[contact])
        events = tick_drone(d, 0.1, ctx)
        attacks = [e for e in events if e.event_type == "drone_attack"]
        assert len(attacks) == 1
        assert d.ammo == pytest.approx(100.0 - ATTACK_AMMO_PER_PASS)
        assert d.damage_dealt > 0

    def test_winchester_when_out_of_ammo(self):
        d = _make_combat(pos=(0.0, 0.0), ammo=0.0)
        d.ai_behaviour = "engage"
        d.contact_of_interest = "enemy_1"
        contact = {"id": "enemy_1", "x": 5000.0, "y": 0.0}
        ctx = _ctx(contacts=[contact])
        events = tick_drone(d, 0.1, ctx)
        winch = [e for e in events if e.event_type == "winchester"]
        assert len(winch) == 1
        assert d.ai_behaviour == "rtb"

    def test_target_lost(self):
        d = _make_combat(pos=(0.0, 0.0))
        d.ai_behaviour = "engage"
        d.contact_of_interest = "enemy_1"
        ctx = _ctx(contacts=[])  # Target not in contacts
        events = tick_drone(d, 0.1, ctx)
        lost = [e for e in events if e.event_type == "target_lost"]
        assert len(lost) == 1
        assert d.ai_behaviour == "loiter"

    def test_closes_to_engagement_range(self):
        d = _make_combat(pos=(0.0, 0.0))
        d.ai_behaviour = "engage"
        d.contact_of_interest = "enemy_1"
        # Place target far beyond weapon range (10000 * 1.5 = 15000)
        contact = {"id": "enemy_1", "x": 30000.0, "y": 0.0}
        ctx = _ctx(contacts=[contact])
        events = tick_drone(d, 1.0, ctx)
        attacks = [e for e in events if e.event_type == "drone_attack"]
        assert len(attacks) == 0  # Too far to attack
        # Should have moved toward target
        assert d.position[0] > 0.0

    def test_escort_formation(self):
        d = _make_combat(pos=(0.0, 0.0))
        d.ai_behaviour = "escort"
        d.escort_target = "friendly_1"
        contact = {"id": "friendly_1", "x": 10000.0, "y": 0.0}
        ctx = _ctx(contacts=[contact])
        tick_drone(d, 1.0, ctx)
        # Should be moving toward escort target
        assert d.position[0] > 0.0

    def test_escort_weapons_free_engages_hostile(self):
        d = _make_combat(pos=(10000.0, 0.0))
        d.ai_behaviour = "escort"
        d.escort_target = "friendly_1"
        d.engagement_rules = "weapons_free"
        contacts = [
            {"id": "friendly_1", "x": 10000.0, "y": 0.0},
            {"id": "enemy_1", "x": 12000.0, "y": 0.0, "classification": "hostile"},
        ]
        ctx = _ctx(contacts=contacts)
        events = tick_drone(d, 0.1, ctx)
        engage = [e for e in events if e.event_type == "engaging_threat"]
        assert len(engage) == 1
        assert d.ai_behaviour == "engage"
        assert d.contact_of_interest == "enemy_1"

    def test_escort_weapons_hold_does_not_engage(self):
        d = _make_combat(pos=(10000.0, 0.0))
        d.ai_behaviour = "escort"
        d.escort_target = "friendly_1"
        d.engagement_rules = "weapons_hold"
        contacts = [
            {"id": "friendly_1", "x": 10000.0, "y": 0.0},
            {"id": "enemy_1", "x": 12000.0, "y": 0.0, "classification": "hostile"},
        ]
        ctx = _ctx(contacts=contacts)
        events = tick_drone(d, 0.1, ctx)
        engage = [e for e in events if e.event_type == "engaging_threat"]
        assert len(engage) == 0
        assert d.ai_behaviour == "escort"

    def test_escort_weapons_tight_engages_attacker(self):
        d = _make_combat(pos=(10000.0, 0.0))
        d.ai_behaviour = "escort"
        d.escort_target = "friendly_1"
        d.engagement_rules = "weapons_tight"
        contacts = [
            {"id": "friendly_1", "x": 10000.0, "y": 0.0},
            {"id": "enemy_1", "x": 12000.0, "y": 0.0, "classification": "hostile",
             "target_id": "friendly_1"},
        ]
        ctx = _ctx(contacts=contacts)
        events = tick_drone(d, 0.1, ctx)
        engage = [e for e in events if e.event_type == "engaging_threat"]
        assert len(engage) == 1


# ---------------------------------------------------------------------------
# Rescue AI
# ---------------------------------------------------------------------------

class TestRescueAI:
    def test_pickup_survivors(self):
        d = _make_rescue(pos=(1000.0, 0.0))
        mission = create_sar_mission("drone_r1", (1000.0, 0.0), expected_survivors=3)
        mission.activate()
        survivors = [{"x": 1000.0, "y": 0.0, "count": 3}]
        ctx = _ctx(survivors=survivors)
        # Tick for enough time to pick up one survivor
        for _ in range(int(RESCUE_PICKUP_TIME / 0.1) + 1):
            tick_drone(d, 0.1, ctx, mission=mission)
        # Should have picked up at least one by now
        assert d.cargo_current >= 1

    def test_cargo_capacity_limit(self):
        d = _make_rescue(pos=(1000.0, 0.0))
        d.cargo_current = d.cargo_capacity  # already full
        mission = create_sar_mission("drone_r1", (1000.0, 0.0), expected_survivors=3)
        mission.activate()
        survivors = [{"x": 1000.0, "y": 0.0, "count": 3}]
        ctx = _ctx(survivors=survivors)
        events = tick_drone(d, 0.1, ctx, mission=mission)
        rescue_complete = [e for e in events if e.event_type == "rescue_complete"]
        assert len(rescue_complete) == 1
        assert d.ai_behaviour == "rtb"

    def test_no_survivors_triggers_rtb(self):
        d = _make_rescue(pos=(1000.0, 0.0))
        mission = create_sar_mission("drone_r1", (1000.0, 0.0), expected_survivors=0)
        mission.activate()
        ctx = _ctx(survivors=[])  # No survivors
        events = tick_drone(d, 0.1, ctx, mission=mission)
        rescue_complete = [e for e in events if e.event_type == "rescue_complete"]
        assert len(rescue_complete) == 1
        assert rescue_complete[0].data["reason"] == "no_survivors"


# ---------------------------------------------------------------------------
# Survey AI
# ---------------------------------------------------------------------------

class TestSurveyAI:
    def test_survey_data_collection(self):
        d = _make_survey(pos=(1000.0, 0.0))
        mission = create_survey_mission("drone_u1", (1000.0, 0.0), loiter_time=60.0)
        mission.activate()
        ctx = _ctx()
        # Tick until data collected
        for _ in range(100):
            tick_drone(d, 1.0, ctx, mission=mission)
        obj = mission.objectives[0]
        assert obj.progress > 0.0

    def test_survey_completion_event(self):
        d = _make_survey(pos=(1000.0, 0.0))
        # Use long loiter time so the main loop doesn't advance past the
        # scan waypoint before survey objective completes.
        mission = create_survey_mission("drone_u1", (1000.0, 0.0), loiter_time=120.0)
        mission.activate()
        ctx = _ctx()
        all_events = []
        # Tick many times to complete survey (rate ~1.8%/s → ~56s)
        for _ in range(100):
            events = tick_drone(d, 1.0, ctx, mission=mission)
            all_events.extend(events)
        complete = [e for e in all_events if e.event_type == "survey_complete"]
        assert len(complete) >= 1


# ---------------------------------------------------------------------------
# ECM Drone AI
# ---------------------------------------------------------------------------

class TestECMAI:
    def test_ecm_jams_hostile_in_range(self):
        d = _make_ecm(pos=(0.0, 0.0))
        contact = {"id": "enemy_1", "x": 5000.0, "y": 0.0, "classification": "hostile"}
        ctx = _ctx(contacts=[contact])
        events = tick_drone(d, 0.1, ctx)
        jams = [e for e in events if e.event_type == "ecm_jamming"]
        assert len(jams) == 1
        assert jams[0].data["target_id"] == "enemy_1"

    def test_ecm_no_jam_out_of_range(self):
        d = _make_ecm(pos=(0.0, 0.0))
        contact = {"id": "enemy_1", "x": 100000.0, "y": 0.0, "classification": "hostile"}
        ctx = _ctx(contacts=[contact])
        events = tick_drone(d, 0.1, ctx)
        jams = [e for e in events if e.event_type == "ecm_jamming"]
        assert len(jams) == 0

    def test_ecm_does_not_jam_friendly(self):
        d = _make_ecm(pos=(0.0, 0.0))
        contact = {"id": "friendly_1", "x": 5000.0, "y": 0.0, "classification": "friendly"}
        ctx = _ctx(contacts=[contact])
        events = tick_drone(d, 0.1, ctx)
        jams = [e for e in events if e.event_type == "ecm_jamming"]
        assert len(jams) == 0


# ---------------------------------------------------------------------------
# Damage effects
# ---------------------------------------------------------------------------

class TestDamageEffects:
    def test_damage_reduces_hull(self):
        d = _make_combat()
        apply_damage_to_drone(d, 20.0)
        assert d.hull == pytest.approx(40.0)  # combat drone max_hull=60

    def test_destruction_event(self):
        d = _make_combat()
        ev = apply_damage_to_drone(d, 100.0)
        assert ev is not None
        assert ev.event_type == "drone_destroyed"
        assert d.status == "destroyed"
        assert d.hull == 0.0

    def test_speed_penalty_below_75_percent(self):
        d = _make_scout()
        d.hull = d.max_hull * 0.74
        assert d.effective_max_speed < d.max_speed

    def test_sensor_penalty_below_50_percent(self):
        d = _make_scout()
        d.hull = d.max_hull * 0.49
        assert d.effective_sensor_range < d.sensor_range

    def test_weapon_penalty_below_50_percent(self):
        d = _make_combat()
        d.hull = d.max_hull * 0.49
        assert d.effective_weapon_damage < d.weapon_damage

    def test_critical_hull_flag(self):
        d = _make_scout()
        d.hull = d.max_hull * 0.24
        assert d.is_critical is True

    def test_non_critical_hull(self):
        d = _make_scout()
        d.hull = d.max_hull * 0.5
        assert d.is_critical is False


# ---------------------------------------------------------------------------
# Waypoint navigation
# ---------------------------------------------------------------------------

class TestWaypointNavigation:
    def test_navigates_to_waypoint(self):
        d = _make_scout(pos=(0.0, 0.0))
        mission = create_patrol_mission("drone_s1", [(10000.0, 0.0)])
        mission.activate()
        ctx = _ctx()
        for _ in range(50):
            tick_drone(d, 1.0, ctx, mission=mission)
        # Should have moved toward waypoint
        assert d.position[0] > 0.0

    def test_waypoint_loiter(self):
        d = _make_scout(pos=(100.0, 0.0))
        mission = create_patrol_mission("drone_s1", [(100.0, 0.0)], loiter_time=5.0)
        mission.activate()
        ctx = _ctx()
        # Should loiter and eventually advance
        for _ in range(100):
            tick_drone(d, 0.1, ctx, mission=mission)
        assert mission.current_waypoint >= 1  # advanced past first wp


# ---------------------------------------------------------------------------
# Decoys
# ---------------------------------------------------------------------------

class TestDecoys:
    def test_decoy_expires(self):
        decoy = Decoy(id="decoy_1", position=(1000.0, 0.0), lifetime=1.0)
        events = tick_decoys([decoy], 1.5)
        assert not decoy.active
        assert decoy.lifetime == 0.0
        expired = [e for e in events if e.event_type == "decoy_expired"]
        assert len(expired) == 1

    def test_decoy_survives_tick(self):
        decoy = Decoy(id="decoy_1", position=(1000.0, 0.0), lifetime=10.0)
        events = tick_decoys([decoy], 1.0)
        assert decoy.active
        assert decoy.lifetime == pytest.approx(9.0)
        assert len(events) == 0

    def test_inactive_decoy_not_ticked(self):
        decoy = Decoy(id="decoy_1", position=(1000.0, 0.0), lifetime=0.0, active=False)
        events = tick_decoys([decoy], 1.0)
        assert len(events) == 0


# ---------------------------------------------------------------------------
# Buoy deployment
# ---------------------------------------------------------------------------

class TestBuoyDeployment:
    def test_deploy_buoy(self):
        d = _make_survey(pos=(5000.0, 3000.0))
        buoy = deploy_buoy(d)
        assert buoy is not None
        assert buoy.position == (5000.0, 3000.0)
        assert buoy.deployed_by == "Compass"
        assert d.buoys_remaining == 2  # survey starts with 3

    def test_deploy_buoy_no_remaining(self):
        d = _make_survey()
        d.buoys_remaining = 0
        buoy = deploy_buoy(d)
        assert buoy is None

    def test_sequential_buoy_ids(self):
        d = _make_survey()
        b1 = deploy_buoy(d)
        b2 = deploy_buoy(d)
        assert b1 is not None and b2 is not None
        assert b1.id != b2.id


# ---------------------------------------------------------------------------
# RTB behaviour
# ---------------------------------------------------------------------------

class TestRTB:
    def test_rtb_arrives_at_ship(self):
        d = _make_scout(pos=(400.0, 0.0))
        d.ai_behaviour = "rtb"
        ctx = _ctx(ship_x=0.0, ship_y=0.0)
        all_events = []
        for _ in range(50):
            events = tick_drone(d, 0.1, ctx)
            all_events.extend(events)
        arrived = [e for e in all_events if e.event_type == "drone_rtb_arrived"]
        assert len(arrived) >= 1
        assert d.status == "rtb"


# ---------------------------------------------------------------------------
# Attack cooldown (Gaps 1-3)
# ---------------------------------------------------------------------------

class TestAttackCooldown:
    def test_cooldown_prevents_consecutive_attacks(self):
        """Combat drone should not attack on consecutive ticks."""
        d = _make_combat(pos=(0.0, 0.0))
        d.ai_behaviour = "engage"
        d.contact_of_interest = "enemy_1"
        contact = {"id": "enemy_1", "x": 5000.0, "y": 0.0}
        ctx = _ctx(contacts=[contact])

        # First tick — should attack.
        events1 = tick_drone(d, 0.1, ctx)
        attacks1 = [e for e in events1 if e.event_type == "drone_attack"]
        assert len(attacks1) == 1

        # Second tick immediately after — on cooldown, should NOT attack.
        events2 = tick_drone(d, 0.1, ctx)
        attacks2 = [e for e in events2 if e.event_type == "drone_attack"]
        assert len(attacks2) == 0

    def test_cooldown_expires_allows_reattack(self):
        """After cooldown expires, drone can attack again."""
        d = _make_combat(pos=(0.0, 0.0))
        d.ai_behaviour = "engage"
        d.contact_of_interest = "enemy_1"
        contact = {"id": "enemy_1", "x": 5000.0, "y": 0.0}
        ctx = _ctx(contacts=[contact])

        # First attack.
        tick_drone(d, 0.1, ctx)
        assert d.attack_cooldown_remaining == pytest.approx(ATTACK_COOLDOWN)

        # Manually expire cooldown and reset position near target.
        d.attack_cooldown_remaining = 0.0
        d.position = (0.0, 0.0)

        events = tick_drone(d, 0.1, ctx)
        attacks = [e for e in events if e.event_type == "drone_attack"]
        assert len(attacks) == 1

    def test_break_away_during_cooldown(self):
        """During cooldown, drone should move away from target."""
        d = _make_combat(pos=(5000.0, 0.0))
        d.ai_behaviour = "engage"
        d.contact_of_interest = "enemy_1"
        contact = {"id": "enemy_1", "x": 5000.0, "y": 0.0}
        ctx = _ctx(contacts=[contact])

        # Fire first attack.
        tick_drone(d, 0.1, ctx)
        pos_after_attack = d.position

        # Tick during cooldown — should continue moving away.
        tick_drone(d, 1.0, ctx)
        dist_before = _dist_helper(pos_after_attack, (5000.0, 0.0))
        dist_after = _dist_helper(d.position, (5000.0, 0.0))
        assert dist_after > dist_before

    def test_cooldown_reset_on_target_lost(self):
        """Cooldown should reset when target is lost."""
        d = _make_combat(pos=(0.0, 0.0))
        d.ai_behaviour = "engage"
        d.contact_of_interest = "enemy_1"
        contact = {"id": "enemy_1", "x": 5000.0, "y": 0.0}
        ctx = _ctx(contacts=[contact])

        # Attack to set cooldown.
        tick_drone(d, 0.1, ctx)
        assert d.attack_cooldown_remaining > 0

        # Target disappears.
        ctx_empty = _ctx(contacts=[])
        tick_drone(d, 0.1, ctx_empty)
        assert d.attack_cooldown_remaining == 0.0
        assert d.ai_behaviour == "loiter"


def _dist_helper(a, b):
    import math
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


# ---------------------------------------------------------------------------
# ECM fuel consumption (Gap 4)
# ---------------------------------------------------------------------------

class TestECMFuelConsumption:
    def test_ecm_double_fuel_when_jamming(self):
        """ECM drone should consume 2x fuel while actively jamming."""
        d_jam = _make_ecm(pos=(0.0, 0.0), fuel=100.0)
        d_idle = _make_ecm(pos=(0.0, 0.0), fuel=100.0)
        d_idle.id = "drone_e2"

        contact = {"id": "enemy_1", "x": 5000.0, "y": 0.0, "classification": "hostile"}
        ctx_hostile = _ctx(contacts=[contact])
        ctx_empty = _ctx(contacts=[])

        tick_drone(d_jam, 1.0, ctx_hostile)
        tick_drone(d_idle, 1.0, ctx_empty)

        # Jamming drone should have consumed ~2x fuel vs idle drone.
        fuel_used_jam = 100.0 - d_jam.fuel
        fuel_used_idle = 100.0 - d_idle.fuel
        assert fuel_used_jam == pytest.approx(fuel_used_idle * ECM_FUEL_MULTIPLIER, rel=0.01)


# ---------------------------------------------------------------------------
# Critical hull drift (Gap 5)
# ---------------------------------------------------------------------------

class TestCriticalDrift:
    def test_critical_hull_causes_heading_drift(self):
        """At <25% hull, heading should drift erratically each tick."""
        d = _make_scout(pos=(0.0, 0.0))
        d.hull = d.max_hull * 0.20  # 20% = critical
        d.heading = 90.0
        # No loiter point — isolate drift from orbit navigation.

        import random
        random.seed(42)
        ctx = _ctx()

        headings = [d.heading]
        for _ in range(5):
            tick_drone(d, 1.0, ctx)
            headings.append(d.heading)

        # Heading should change due to random critical drift.
        diffs = [abs(headings[i + 1] - headings[i]) for i in range(len(headings) - 1)]
        assert any(diff > 1.0 for diff in diffs)

    def test_healthy_hull_no_drift(self):
        """At >25% hull, heading should not have erratic drift."""
        d = _make_scout(pos=(0.0, 0.0))
        d.hull = d.max_hull  # 100% = healthy
        d.heading = 0.0
        # No loiter point, no waypoints — drone should just drift forward.
        ctx = _ctx()

        import random
        random.seed(42)

        heading_before = d.heading
        tick_drone(d, 0.1, ctx)
        # Without any target/loiter, heading stays the same (drift forward).
        # The heading should NOT have random perturbation.
        assert d.heading == pytest.approx(heading_before, abs=0.01)


# ---------------------------------------------------------------------------
# Combat break-away (Gap 6)
# ---------------------------------------------------------------------------

class TestCombatBreakAway:
    def test_drone_moves_away_after_attack(self):
        """After firing, the combat drone should move away from target."""
        d = _make_combat(pos=(5000.0, 0.0))
        d.ai_behaviour = "engage"
        d.contact_of_interest = "enemy_1"
        target_pos = (5000.0, 0.0)
        contact = {"id": "enemy_1", "x": target_pos[0], "y": target_pos[1]}
        ctx = _ctx(contacts=[contact])

        # Place drone right at target to ensure in-range attack.
        dist_before = _dist_helper(d.position, target_pos)
        events = tick_drone(d, 1.0, ctx)
        attacks = [e for e in events if e.event_type == "drone_attack"]
        assert len(attacks) == 1

        # After attack, drone should have moved away.
        dist_after = _dist_helper(d.position, target_pos)
        assert dist_after > dist_before


# ---------------------------------------------------------------------------
# Weapons tight ignores non-attacker (Gap 7)
# ---------------------------------------------------------------------------

class TestWeaponsTightNonAttacker:
    def test_weapons_tight_ignores_hostile_not_targeting_escort(self):
        """Weapons tight should not engage a hostile that isn't attacking the escort."""
        d = _make_combat(pos=(10000.0, 0.0))
        d.ai_behaviour = "escort"
        d.escort_target = "friendly_1"
        d.engagement_rules = "weapons_tight"
        contacts = [
            {"id": "friendly_1", "x": 10000.0, "y": 0.0},
            # Hostile nearby but targeting something else, not our escort.
            {"id": "enemy_1", "x": 12000.0, "y": 0.0, "classification": "hostile",
             "target_id": "other_ship"},
        ]
        ctx = _ctx(contacts=contacts)
        events = tick_drone(d, 0.1, ctx)
        engage = [e for e in events if e.event_type == "engaging_threat"]
        assert len(engage) == 0
        assert d.ai_behaviour == "escort"

    def test_weapons_tight_ignores_hostile_no_target(self):
        """Weapons tight should not engage a hostile with no target_id."""
        d = _make_combat(pos=(10000.0, 0.0))
        d.ai_behaviour = "escort"
        d.escort_target = "friendly_1"
        d.engagement_rules = "weapons_tight"
        contacts = [
            {"id": "friendly_1", "x": 10000.0, "y": 0.0},
            {"id": "enemy_1", "x": 12000.0, "y": 0.0, "classification": "hostile"},
        ]
        ctx = _ctx(contacts=contacts)
        events = tick_drone(d, 0.1, ctx)
        engage = [e for e in events if e.event_type == "engaging_threat"]
        assert len(engage) == 0


# ---------------------------------------------------------------------------
# Orbit behaviour (Gap 8)
# ---------------------------------------------------------------------------

class TestOrbitBehaviour:
    def test_orbit_too_far_flies_toward_centre(self):
        """When far from orbit centre, drone should fly toward it."""
        d = _make_scout(pos=(20000.0, 0.0))
        d.heading = 0.0
        d.speed = d.max_speed
        centre = (0.0, 0.0)
        _orbit_point(d, centre, 3000.0, 1.0)
        # Should have moved closer to centre (20000 * 1.3 = 26000 > 20000, so "too far")
        # Actually 20000 > 3000 * 1.3 = 3900, so definitely too far.
        assert _dist_helper(d.position, centre) < 20000.0

    def test_orbit_too_close_flies_away(self):
        """When too close to orbit centre, drone should fly away."""
        d = _make_scout(pos=(500.0, 0.0))
        d.heading = 270.0  # facing west
        d.speed = d.max_speed
        centre = (0.0, 0.0)
        # 500 < 3000 * 0.7 = 2100, so "too close"
        _orbit_point(d, centre, 3000.0, 1.0)
        assert _dist_helper(d.position, centre) > 500.0

    def test_orbit_in_band_flies_tangent(self):
        """When in the orbit band, drone should fly tangentially."""
        d = _make_scout(pos=(3000.0, 0.0))
        d.heading = 0.0  # facing north
        d.speed = d.max_speed
        centre = (0.0, 0.0)
        # 3000 is between 3000*0.7=2100 and 3000*1.3=3900, so in-band.
        _orbit_point(d, centre, 3000.0, 1.0)
        # Bearing to centre from (3000,0) is 270° (west), tangent = 270+90=0° (north).
        # Drone already facing north — should move north (y decreases).
        assert d.position[1] < 0.0


# ---------------------------------------------------------------------------
# Bingo fuel calculation (Gap 9)
# ---------------------------------------------------------------------------

class TestBingoFuelCalculation:
    def test_bingo_fuel_at_exact_threshold(self):
        """Bingo should trigger when fuel equals return fuel + safety margin."""
        d = _make_scout(pos=(10000.0, 0.0))
        # Calculate exact bingo threshold.
        dist = 10000.0
        time_to_return = dist / d.max_speed
        fuel_to_return = time_to_return * d.fuel_consumption
        safety = fuel_to_return * BINGO_FUEL_SAFETY_MARGIN
        bingo_threshold = fuel_to_return + safety

        # Set fuel just at threshold — should be bingo.
        d.fuel = bingo_threshold
        assert d.is_bingo_fuel(0.0, 0.0) is True

    def test_not_bingo_above_threshold(self):
        """Should not be bingo when fuel is comfortably above threshold."""
        d = _make_scout(pos=(10000.0, 0.0))
        dist = 10000.0
        time_to_return = dist / d.max_speed
        fuel_to_return = time_to_return * d.fuel_consumption
        safety = fuel_to_return * BINGO_FUEL_SAFETY_MARGIN
        bingo_threshold = fuel_to_return + safety

        d.fuel = bingo_threshold + 10.0
        assert d.is_bingo_fuel(0.0, 0.0) is False

    def test_bingo_safety_margin_applied(self):
        """Bingo threshold should include the 20% safety margin."""
        d = _make_scout(pos=(10000.0, 0.0))
        dist = 10000.0
        time_to_return = dist / d.max_speed
        fuel_to_return = time_to_return * d.fuel_consumption

        # Without safety margin, this fuel would be enough.
        # With 20% margin, it should trigger bingo.
        d.fuel = fuel_to_return + 0.01
        assert d.is_bingo_fuel(0.0, 0.0) is True  # margin pushes threshold above bare minimum
