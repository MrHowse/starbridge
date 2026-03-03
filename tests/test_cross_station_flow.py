"""D.12: End-to-End Cross-Station Flow Tests.

Each test exercises a multi-module event chain, calling actual module
functions in sequence to verify that the integration wiring works when
modules hand data from one station to another.

Audit areas:
  1. Eng ↔ HazCon: overclock → fire → suppression power gate
  2. Science ↔ Ops: request_scan → sensor tick → assessment enrichment
  3. Helm ↔ Multiple: high throttle → torpedo bonus + threat bearing
  4. Weapons ripple: combat effects fan-out (ion/nuclear/destroyed)
  5. Medical ↔ HazCon: fire ≥3 → injury prediction → evac warning
  6. Comms → Ops → Captain: intel route → analysis → pop
  7. EW ↔ Ops: intrusion → intel → jammed flag in assessment
  8. FlightOps → Science: drone detection bubble → contact annotation
  9. Security ↔ HazCon: sabotage fire → marine hazard damage → boarder vacuum
"""
from __future__ import annotations

import pytest

from server.models.interior import ShipInterior, Room
from server.models.ship import Ship
from server.models.world import Enemy, World
from server.models.resources import ResourceStore
from server.models.boarding import BoardingParty
from server.models.marine_teams import MarineTeam
import server.game_loop_hazard_control as glhc
import server.game_loop_atmosphere as glatm
import server.game_loop_operations as glops
import server.game_loop_weapons as glw
import server.game_loop_ew as glew
import server.game_loop_security as gls
import server.game_loop_flight_ops as glfo
from server.systems import sensors


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_ship(efficiency: float = 1.0, throttle: float = 0.5,
               heading: float = 0.0, x: float = 0.0, y: float = 0.0) -> Ship:
    ship = Ship(name="FlowTestShip", x=x, y=y, heading=heading, throttle=throttle)
    for sys in ship.systems.values():
        sys.power = 100.0
        sys.health = efficiency * 100.0
    ship.resources = ResourceStore(
        fuel=100.0, fuel_max=200.0,
        suppressant=10.0, suppressant_max=20.0,
        medical_supplies=20.0, medical_supplies_max=40.0,
        repair_materials=30.0, repair_materials_max=50.0,
    )
    return ship


def _make_interior() -> ShipInterior:
    rooms = {
        "engine_room": Room(id="engine_room", name="Engine Room",
                            deck="engineering", position=(0, 0),
                            deck_number=1, connections=["bridge"]),
        "bridge": Room(id="bridge", name="Bridge",
                       deck="command", position=(0, 1),
                       deck_number=2, connections=["engine_room", "weapons_bay"]),
        "weapons_bay": Room(id="weapons_bay", name="Weapons Bay",
                            deck="command", position=(1, 1),
                            deck_number=2, connections=["bridge"]),
    }
    system_rooms = {
        "engines": "engine_room",
        "beams": "weapons_bay",
        "manoeuvring": "bridge",
    }
    return ShipInterior(rooms=rooms, system_rooms=system_rooms)


def _make_world(enemies: list[Enemy] | None = None) -> World:
    return World(enemies=enemies or [])


# ===========================================================================
# Flow 1: Eng ↔ HazCon — overclock → fire → suppression power gate
# ===========================================================================


class TestEngHazConFlow:
    def test_overclock_fire_then_suppression_power_gate(self):
        """Overclock fire in engine room; suppression gated by ship power."""
        ship = _make_ship(efficiency=1.0)
        interior = _make_interior()

        # Step 1: Simulate overclock fire in engine_room (what game_loop does
        # when random < OVERCLOCK_FIRE_CHANCE after overclock damage).
        glhc.start_fire("engine_room", glhc.OVERCLOCK_FIRE_INTENSITY, interior)
        state = glhc.build_dc_state(interior)
        fires = state.get("fires", {})
        assert "engine_room" in fires

        # Step 2: Ship is powered → suppression is allowed.
        glhc.update_fire_suppression_power(ship)
        assert glhc.is_fire_suppression_powered() is True
        assert glhc.suppress_local("engine_room", resources=ship.resources) is True

        # Step 3: Restart fire, then kill power → suppression blocked.
        glhc.start_fire("engine_room", glhc.OVERCLOCK_FIRE_INTENSITY, interior)
        dead_ship = _make_ship(efficiency=0.0)
        glhc.update_fire_suppression_power(dead_ship)
        assert glhc.is_fire_suppression_powered() is False
        assert glhc.suppress_local("engine_room") is False


# ===========================================================================
# Flow 2: Science ↔ Ops — request_scan → sensor tick → assessment
# ===========================================================================


class TestScienceOpsFlow:
    def test_scan_then_assessment(self):
        """Ops requests scan → sensors tick to completion → assessment starts."""
        ship = _make_ship(efficiency=0.80)
        enemy = Enemy(id="e1", type="fighter", x=500.0, y=500.0, scan_state="unknown")
        world = _make_world([enemy])

        # Step 1: Ops requests a scan.
        result = glops.request_scan("e1", world)
        assert result["ok"] is True

        # Step 2: Science runs the scan via sensors.
        sensors.start_scan("e1")
        for _ in range(500):
            completed = sensors.tick(world, ship, 0.1)
            if completed:
                break
        assert enemy.scan_state == "scanned"
        assert enemy.scan_detail == "detailed"  # efficiency ≥ 0.75

        # Step 3: Ops starts an assessment on the scanned contact.
        asmt_result = glops.start_assessment("e1", world, ship)
        assert asmt_result["ok"] is True

        # Step 4: Tick ops until assessment completes.
        for _ in range(2000):
            glops.tick(world, ship, 0.1)
            asmt = glops._assessments.get("e1")
            if asmt and asmt.complete:
                break
        broadcasts = glops.pop_pending_broadcasts()
        complete_msgs = [b for b in broadcasts
                         if b[1].get("type") == "assessment_complete"]
        assert len(complete_msgs) >= 1
        # Detailed scan → system_health included.
        assert "system_health" in complete_msgs[0][1]


# ===========================================================================
# Flow 3: Helm ↔ Multiple — high throttle → torpedo bonus + threat bearing
# ===========================================================================


class TestHelmMultipleFlow:
    def test_high_speed_torpedo_and_threat_bearing(self):
        """High throttle grants torpedo bonus and threat bearing computes."""
        from server.game_loop import _compute_threat_bearing

        ship = _make_ship(efficiency=1.0, throttle=0.80, heading=0.0,
                          x=0.0, y=0.0)
        enemy = Enemy(id="e1", type="fighter", x=0.0, y=-1000.0)
        world = _make_world([enemy])

        # Step 1: Torpedo bonus at high throttle.
        bonus = glw.get_high_speed_torpedo_bonus(ship)
        assert bonus == glw.HIGH_SPEED_TORPEDO_BONUS  # +5%

        # Step 2: Threat bearing computation.
        bearing = _compute_threat_bearing(ship, world)
        assert bearing is not None
        assert bearing["enemy_id"] == "e1"
        assert bearing["facing"] == "fore"

        # Step 3: At low throttle, no bonus.
        ship.throttle = 0.5
        assert glw.get_high_speed_torpedo_bonus(ship) == 0.0


# ===========================================================================
# Flow 4: Weapons ripple — combat effects fan-out
# ===========================================================================


class TestWeaponsRippleFlow:
    def test_combat_effects_fan_out(self):
        """Ion → science, nuclear → medical+HC, destroyed → retarget chain."""
        # Step 1: Ion hit queues science effect.
        glw._pending_combat_effects.append({
            "effect": "ion_hit", "target_id": "e1",
        })

        # Step 2: Nuclear hit queues medical + HC effect.
        glw._pending_combat_effects.append({
            "effect": "nuclear_hit", "target_id": "e2",
        })

        # Step 3: Destroyed queues retarget.
        glw._pending_combat_effects.append({
            "effect": "enemy_destroyed", "target_id": "e3", "target_type": "fighter",
        })

        # Step 4: Pop all effects in one batch (like the game loop does).
        effects = glw.pop_combat_effects()
        assert len(effects) == 3

        ion_effects = [e for e in effects if e["effect"] == "ion_hit"]
        nuc_effects = [e for e in effects if e["effect"] == "nuclear_hit"]
        dest_effects = [e for e in effects if e["effect"] == "enemy_destroyed"]
        assert len(ion_effects) == 1
        assert len(nuc_effects) == 1
        assert len(dest_effects) == 1

        # Step 5: Destroyed enemy → flight ops retarget (should not raise).
        glfo.retarget_drones_from("e3")

        # Step 6: Effects buffer is now drained.
        assert glw.pop_combat_effects() == []


# ===========================================================================
# Flow 5: Medical ↔ HazCon — fire ≥3 → injury prediction → evac warning
# ===========================================================================


class TestMedicalHazConFlow:
    def test_fire_injury_prediction_then_evac_warning(self):
        """Fire ≥3 → injury prediction → evac warning queued → medical pops."""
        interior = _make_interior()
        glatm.init_atmosphere(interior)

        # Step 1: Start a severe fire.
        glhc.start_fire("bridge", 3, interior)

        # Step 2: HC generates injury predictions.
        preds = glhc.get_hazard_injury_predictions(interior)
        fire_preds = [p for p in preds if p["hazard_type"] == "fire"]
        assert len(fire_preds) == 1
        assert "burns" in fire_preds[0]["injury_types"]
        assert "smoke_inhalation" in fire_preds[0]["injury_types"]

        # Step 3: HC queues evacuation warning for the deck.
        glhc.queue_evacuation_warning("command", fire_preds[0].get("severity", 3))

        # Step 4: Medical pops evacuation warnings.
        warnings = glhc.pop_evacuation_warnings()
        assert len(warnings) == 1
        assert warnings[0]["deck"] == "command"
        # Second pop is empty.
        assert glhc.pop_evacuation_warnings() == []


# ===========================================================================
# Flow 6: Comms → Ops → Captain — intel pipeline
# ===========================================================================


class TestCommsOpsCaptainFlow:
    def test_comms_intel_to_ops_to_captain(self):
        """Comms intel → ops receive_comms_intel → pop_intel_analysis for captain."""
        # Step 1: Comms station decodes a signal producing intel.
        intel = {
            "signal_id": "sig_flow",
            "source_name": "Frigate Echo",
            "intel_category": "tactical",
            "threat_level": "high",
        }

        # Step 2: Ops receives the intel.
        glops.receive_comms_intel(intel)

        # Step 3: Captain pops the analysis.
        analyses = glops.pop_intel_analysis()
        assert len(analyses) == 1
        assert analyses[0]["signal_id"] == "sig_flow"
        assert analyses[0]["category"] == "tactical"
        assert analyses[0]["risk_level"] == "high"
        assert analyses[0]["recommendation"] == "Recommend caution"

        # Step 4: Second pop is empty (buffer drained).
        assert glops.pop_intel_analysis() == []


# ===========================================================================
# Flow 7: EW ↔ Ops — intrusion → intel → jammed flag
# ===========================================================================


class TestEWOpsFlow:
    def test_intrusion_success_to_ops_jammed_flag(self):
        """EW intrusion → intel extracted → beam fire emission → jammed flag."""
        ship = _make_ship(efficiency=1.0)
        enemy = Enemy(id="e1", type="fighter", x=500.0, y=500.0,
                      scan_state="scanned", scan_detail="basic")
        world = _make_world([enemy])

        # Step 1: EW intrusion success stuns the enemy and generates intel.
        glew.apply_intrusion_success("e1", world)

        # Step 2: Pop intrusion intel — ops receives system stun data.
        intel = glew.pop_intrusion_intel()
        assert len(intel) == 1
        assert intel[0]["target_id"] == "e1"
        assert intel[0]["systems_stunned"] is True

        # Step 3: Beam fire records emission spike in EW.
        glew.record_weapons_fire("beam")
        assert glew.get_emission_level() == pytest.approx(glew.EMISSION_BEAM_SPIKE)

        # Step 4: Set jam_factor on enemy (applied by EW jamming module during
        # normal tick) and verify ops propagates the jammed flag.
        enemy.jam_factor = 0.6
        glops.start_assessment("e1", world, ship)
        state = glops.build_state(world, ship)
        asmts = state.get("assessments", {})
        assert "e1" in asmts
        assert asmts["e1"].get("jammed") is True


# ===========================================================================
# Flow 8: FlightOps → Science — drone detection bubble → contact annotation
# ===========================================================================


class TestFlightOpsScienceFlow:
    def test_drone_bubble_tags_contact(self):
        """Drone detection bubble → sensor contacts annotated with drone_detected."""
        ship = _make_ship(efficiency=1.0)
        enemy = Enemy(id="e1", type="fighter", x=100.0, y=100.0)
        world = _make_world([enemy])

        # Step 1: Simulate a drone detection bubble near the enemy.
        # (In the real game loop, glfo.get_detection_bubbles() returns these.)
        drone_bubbles = [(100.0, 100.0, 5000.0)]  # (x, y, range)

        # Step 2: Build sensor contacts with the bubble.
        contacts = sensors.build_sensor_contacts(world, ship,
                                                 extra_bubbles=drone_bubbles)

        # Step 3: Verify the contact is tagged with drone_detected.
        e1_contacts = [c for c in contacts if c["id"] == "e1"]
        assert len(e1_contacts) == 1
        assert e1_contacts[0].get("drone_detected") is True

        # Step 4: Without bubbles, no drone_detected tag.
        contacts_no_drone = sensors.build_sensor_contacts(world, ship)
        e1_plain = [c for c in contacts_no_drone if c["id"] == "e1"]
        assert e1_plain[0].get("drone_detected") is not True


# ===========================================================================
# Flow 9: Security ↔ HazCon — sabotage fire → marine damage → boarder vacuum
# ===========================================================================


class TestSecurityHazConFlow:
    def test_sabotage_fire_marine_damage_boarder_vacuum(self):
        """Sabotage fire → HC starts fire → marine fire damage → vent → boarder vacuum."""
        interior = _make_interior()
        glatm.init_atmosphere(interior)

        # Step 1: Security detects sabotage fire.
        gls._pending_sabotage_fires.append("bridge")
        fires = gls.pop_sabotage_fires()
        assert fires == ["bridge"]

        # Step 2: HC starts the fire from sabotage event.
        glhc.start_fire("bridge", 3, interior)
        state = glhc.build_dc_state(interior)
        assert "bridge" in state.get("fires", {})

        # Step 3: Marines in the fire room take fire damage.
        team = MarineTeam(id="mt_a", name="Alpha", callsign="A1",
                          members=["c1", "c2", "c3", "c4"],
                          size=4, max_size=4, location="bridge")
        gls._marine_teams.append(team)
        fire_rooms = {"bridge": 3}
        events = gls.apply_hazard_damage_to_marines(fire_rooms, set(), set(), 3.0)
        assert len(events) >= 1
        assert events[0][1]["cause"] == "fire"

        # Step 4: Vent the room → vacuum. Boarders take vacuum damage.
        party = BoardingParty(id="bp_1", location="bridge", members=3,
                              max_members=3, status="sabotaging")
        gls._boarding_parties.append(party)
        gls._boarding_active = True
        vacuum_rooms = {"bridge"}
        vent_events = gls.apply_vent_damage_to_boarders(vacuum_rooms, 1.0)
        assert len(vent_events) >= 3
        assert vent_events[0][0] == "security.boarder_vacuum_casualty"
        assert party.members == 0
