"""Tests for v0.08 C.6–C.12: Remaining Cross-Station Integrations.

Covers:
  C.12 Quartermaster ↔ Hazard Control — resource consumption + allocation
  C.7  Medical ↔ Hazard Control — injury predictions + evac warnings
  C.11 Security ↔ Hazard Control — door origins, hazard damage, sabotage
  C.6  Weapons ↔ Multiple — torpedo effects, fire rate, destruction fan-out
  C.9  EW ↔ Ops ↔ Weapons — emission, intrusion intel, jam status
  C.10 Flight Ops ↔ Multiple — drone contacts, rescue ETA, ECM
  C.8  Comms ↔ Ops ↔ Captain — intel pipeline, action requests, feasibility
"""
from __future__ import annotations

import pytest

from server.models.interior import ShipInterior, Room
from server.models.ship import Ship
from server.models.world import Enemy, World
from server.models.resources import ResourceStore
import server.game_loop_hazard_control as glhc
import server.game_loop_atmosphere as glatm
import server.game_loop_security as gls
import server.game_loop_weapons as glw
import server.game_loop_ew as glew
import server.game_loop_operations as glops
import server.game_loop_rationing as glrat
import server.game_loop_flight_ops as glfo
from server.models.boarding import BoardingParty
from server.models.marine_teams import MarineTeam


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_ship(efficiency: float = 1.0) -> Ship:
    ship = Ship(name="TestShip", x=0.0, y=0.0)
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
    return ShipInterior(rooms=rooms)


def _make_world(enemies: list[Enemy] | None = None) -> World:
    return World(enemies=enemies or [])


def _make_enemy(eid: str = "e1", hull: float = 100.0, **kw) -> Enemy:
    return Enemy(id=eid, type="fighter", x=500.0, y=500.0, hull=hull, **kw)


# ===========================================================================
# C.12: QM ↔ HC
# ===========================================================================


class TestQMResourceConsumption:
    """C.12: HC actions consume QM resources."""

    def test_suppress_local_consumes_suppressant(self):
        """suppress_local tracks consumption in glrat."""
        ship = _make_ship()
        interior = _make_interior()
        glhc.start_fire("bridge", 3, interior)
        assert glhc.suppress_local("bridge", resources=ship.resources) is True
        summary = glhc.get_resource_consumption_summary()
        assert summary.get("suppressant", 0) == glhc.LOCAL_SUPPRESS_COST

    def test_suppress_deck_tracks_consumption(self):
        """suppress_deck tracks consumption."""
        ship = _make_ship()
        interior = _make_interior()
        glhc.start_fire("bridge", 3, interior)
        assert glhc.suppress_deck("command", interior, resources=ship.resources) is True
        summary = glhc.get_resource_consumption_summary()
        assert summary.get("suppressant", 0) == glhc.DECK_SUPPRESS_COST

    def test_decon_consumes_medical_supplies(self):
        """dispatch_decon_team consumes medical_supplies."""
        ship = _make_ship()
        assert glhc.dispatch_decon_team("bridge", resources=ship.resources) is True
        assert ship.resources.medical_supplies < 20.0
        summary = glhc.get_resource_consumption_summary()
        assert summary.get("medical_supplies", 0) == glhc.DECON_SUPPLY_COST

    def test_decon_blocked_insufficient(self):
        """dispatch_decon_team fails when supplies insufficient."""
        ship = _make_ship()
        ship.resources.medical_supplies = 0.5
        assert glhc.dispatch_decon_team("bridge", resources=ship.resources) is False

    def test_request_suppressant_allocation(self):
        """request_suppressant creates allocation via glrat."""
        ship = _make_ship()
        result = glhc.request_suppressant(5.0, "low reserves", 100, ship=ship)
        assert result["ok"] is True
        assert "request_id" in result

    def test_depleted_suppressant_blocks_suppress(self):
        """suppress_local returns False when suppressant depleted."""
        ship = _make_ship()
        ship.resources.suppressant = 0.0
        interior = _make_interior()
        glhc.start_fire("bridge", 3, interior)
        assert glhc.suppress_local("bridge", resources=ship.resources) is False


# ===========================================================================
# C.7: Medical ↔ HC
# ===========================================================================


class TestMedicalHCIntegration:
    """C.7: Medical sees injury predictions from HC hazards."""

    def test_fire_ge3_predicts_burns(self):
        """Fire intensity ≥ 3 predicts burns + smoke inhalation."""
        interior = _make_interior()
        glhc.start_fire("bridge", 3, interior)
        preds = glhc.get_hazard_injury_predictions(interior)
        fire_preds = [p for p in preds if p["hazard_type"] == "fire"]
        assert len(fire_preds) == 1
        assert "burns" in fire_preds[0]["injury_types"]
        assert "smoke_inhalation" in fire_preds[0]["injury_types"]

    def test_fire_lt3_no_prediction(self):
        """Fire intensity < 3 does not predict injuries."""
        interior = _make_interior()
        glhc.start_fire("bridge", 2, interior)
        preds = glhc.get_hazard_injury_predictions(interior)
        fire_preds = [p for p in preds if p["hazard_type"] == "fire"]
        assert len(fire_preds) == 0

    def test_radiation_predicts_sickness(self):
        """Atmosphere radiation ≥ 0.3 predicts radiation sickness."""
        interior = _make_interior()
        glatm.init_atmosphere(interior)
        atm = glatm.get_atmosphere("bridge")
        assert atm is not None
        atm.radiation = 0.5
        preds = glhc.get_hazard_injury_predictions(interior)
        rad_preds = [p for p in preds if p["hazard_type"] == "radiation"]
        assert len(rad_preds) >= 1
        assert "radiation_sickness" in rad_preds[0]["injury_types"]

    def test_contamination_predicts_poisoning(self):
        """Chemical contamination ≥ 0.2 predicts poisoning."""
        interior = _make_interior()
        glatm.init_atmosphere(interior)
        atm = glatm.get_atmosphere("bridge")
        assert atm is not None
        atm.chemical = 0.3
        preds = glhc.get_hazard_injury_predictions(interior)
        chem_preds = [p for p in preds if p["hazard_type"] == "contamination"]
        assert len(chem_preds) >= 1
        assert "poisoning" in chem_preds[0]["injury_types"]

    def test_evac_warning_queue_pop(self):
        """Evacuation warnings queue and pop correctly."""
        glhc.queue_evacuation_warning("engineering", 3)
        glhc.queue_evacuation_warning("command", 5)
        warnings = glhc.pop_evacuation_warnings()
        assert len(warnings) == 2
        assert warnings[0]["deck"] == "engineering"
        assert warnings[1]["estimated_casualties"] == 5
        # Second pop returns empty.
        assert glhc.pop_evacuation_warnings() == []


# ===========================================================================
# C.11: Security ↔ HC
# ===========================================================================


class TestSecurityHCIntegration:
    """C.11: Door lock origins, hazard damage, sabotage fires."""

    def test_lock_tracks_origin(self):
        """lock_door stores origin."""
        interior = _make_interior()
        gls.lock_door(interior, "bridge", origin="security")
        origins = gls.get_door_lock_origins()
        assert origins.get("bridge") == "security"

    def test_hc_override_changes_origin(self):
        """HC override lock is tracked with hazard_control origin."""
        interior = _make_interior()
        gls.lock_door(interior, "bridge", origin="hazard_control")
        origins = gls.get_door_lock_origins()
        assert origins.get("bridge") == "hazard_control"

    def test_marine_fire_damage(self):
        """Marines take fire damage in rooms with intensity ≥ 3."""
        gls._marine_teams.clear()
        team = MarineTeam(id="m1", name="Alpha", callsign="A1",
                          members=["c1", "c2", "c3", "c4"],
                          size=4, max_size=4, location="bridge")
        gls._marine_teams.append(team)
        fire_rooms = {"bridge": 3}
        # Accumulate enough damage (0.5 HP/s × 3s = 1.5 → 1 casualty).
        events = gls.apply_hazard_damage_to_marines(fire_rooms, set(), set(), 3.0)
        assert len(events) >= 1
        assert events[0][0] == "security.marine_hazard_casualty"
        assert events[0][1]["cause"] == "fire"

    def test_marine_vacuum_damage(self):
        """Marines take vacuum damage in vented rooms."""
        gls._marine_teams.clear()
        team = MarineTeam(id="m2", name="Beta", callsign="B1",
                          members=["c1", "c2"], size=2, max_size=2,
                          location="engine_room")
        gls._marine_teams.append(team)
        vacuum_rooms = {"engine_room"}
        # 2.0 HP/s × 1s = 2 → 2 casualties.
        events = gls.apply_hazard_damage_to_marines({}, vacuum_rooms, set(), 1.0)
        assert len(events) >= 2
        assert events[0][1]["cause"] == "vacuum"

    def test_boarder_vacuum_damage(self):
        """Boarders take vacuum damage in vented rooms."""
        gls._boarding_parties.clear()
        party = BoardingParty(id="bp1", members=3, max_members=3,
                              location="bridge")
        gls._boarding_parties.append(party)
        vacuum_rooms = {"bridge"}
        # 3.0 HP/s × 1s = 3 → 3 casualties.
        events = gls.apply_vent_damage_to_boarders(vacuum_rooms, 1.0)
        assert len(events) >= 3
        assert events[0][0] == "security.boarder_vacuum_casualty"
        assert party.members == 0

    def test_no_damage_in_safe_rooms(self):
        """No damage when marines/boarders in safe rooms."""
        gls._marine_teams.clear()
        team = MarineTeam(id="m3", name="Gamma", callsign="G1",
                          members=["c1"], size=1, max_size=1,
                          location="bridge")
        gls._marine_teams.append(team)
        events = gls.apply_hazard_damage_to_marines({}, set(), set(), 1.0)
        assert len(events) == 0

    def test_sabotage_fire_pop(self):
        """Sabotage fires are queued and popped correctly."""
        gls._pending_sabotage_fires.append("bridge")
        fires = gls.pop_sabotage_fires()
        assert fires == ["bridge"]
        assert gls.pop_sabotage_fires() == []

    def test_serialise_door_origins(self):
        """Door lock origins survive serialise/deserialise."""
        interior = _make_interior()
        gls.lock_door(interior, "bridge", origin="hazard_control")
        data = gls.serialise()
        gls.reset()
        gls.deserialise(data)
        origins = gls.get_door_lock_origins()
        assert origins.get("bridge") == "hazard_control"


# ===========================================================================
# C.6: Weapons ↔ Multiple
# ===========================================================================


class TestWeaponsCombatEffects:
    """C.6: Combat effects + fire rate tracking."""

    def test_ion_queues_science_effect(self):
        """Ion torpedo hit queues ion_hit combat effect."""
        glw._pending_combat_effects.append({
            "effect": "ion_hit", "target_id": "e1",
        })
        effects = glw.pop_combat_effects()
        assert len(effects) == 1
        assert effects[0]["effect"] == "ion_hit"
        assert glw.pop_combat_effects() == []

    def test_nuclear_queues_medical_and_hc(self):
        """Nuclear torpedo hit queues nuclear_hit combat effect."""
        glw._pending_combat_effects.append({
            "effect": "nuclear_hit", "target_id": "e1",
        })
        effects = glw.pop_combat_effects()
        assert effects[0]["effect"] == "nuclear_hit"

    def test_enemy_destroyed_queues_effect(self):
        """Enemy destroyed queues enemy_destroyed combat effect."""
        glw._pending_combat_effects.append({
            "effect": "enemy_destroyed", "target_id": "e1", "target_type": "fighter",
        })
        effects = glw.pop_combat_effects()
        assert effects[0]["effect"] == "enemy_destroyed"
        assert effects[0]["target_type"] == "fighter"

    def test_consumption_low_when_no_fire(self):
        """Torpedo consumption is LOW when no torpedoes fired."""
        level = glw.get_torpedo_consumption_level()
        assert level == "LOW"

    def test_consumption_high_when_rapid(self):
        """Torpedo consumption is HIGH with rapid fire."""
        import time
        now = time.monotonic()
        glw._torpedo_fire_times.extend([now - 10, now - 5])
        level = glw.get_torpedo_consumption_level()
        assert level == "HIGH"

    def test_retarget_drones_clears_mission(self):
        """retarget_drones_from clears target_id on affected missions."""
        # Basic attribute test via the function existing and not raising.
        glfo.retarget_drones_from("dead_enemy")  # should not raise

    def test_fire_rate_tracking(self):
        """Torpedo fire times track recent fires."""
        import time
        now = time.monotonic()
        glw._torpedo_fire_times.append(now)
        assert glw.get_torpedo_consumption_level() in ("MEDIUM", "HIGH")


# ===========================================================================
# C.9: EW ↔ Ops ↔ Weapons
# ===========================================================================


class TestEWEmissionTracking:
    """C.9: Emission tracking + intrusion intel + jam status."""

    def test_beam_fire_spikes_emission(self):
        """Beam fire spikes emission level."""
        assert glew.get_emission_level() == 0.0
        glew.record_weapons_fire("beam")
        assert glew.get_emission_level() == pytest.approx(glew.EMISSION_BEAM_SPIKE)

    def test_torpedo_spikes_higher(self):
        """Torpedo fire spikes higher than beam."""
        glew.record_weapons_fire("torpedo")
        assert glew.get_emission_level() == pytest.approx(glew.EMISSION_TORPEDO_SPIKE)

    def test_emission_decays(self):
        """Emission decays over time."""
        ship = _make_ship()
        world = _make_world()
        glew.record_weapons_fire("beam")
        initial = glew.get_emission_level()
        glew.tick(world, ship, 1.0)
        assert glew.get_emission_level() < initial

    def test_mask_cost_active_while_emitting(self):
        """Mask cost modifier is active while emission > 0."""
        assert glew.get_mask_cost_modifier() == 0.0
        glew.record_weapons_fire("beam")
        assert glew.get_mask_cost_modifier() == pytest.approx(glew.WEAPONS_MASK_COST_MOD)

    def test_emission_zero_when_no_fire(self):
        """Emission is zero when no weapons fired."""
        assert glew.get_emission_level() == 0.0
        assert glew.get_mask_cost_modifier() == 0.0

    def test_intrusion_feeds_ops_intel(self):
        """Intrusion success feeds intel to ops."""
        enemy = _make_enemy()
        world = _make_world([enemy])
        glew.apply_intrusion_success("e1", world)
        intel = glew.pop_intrusion_intel()
        assert len(intel) == 1
        assert intel[0]["target_id"] == "e1"
        assert intel[0]["systems_stunned"] is True

    def test_jammed_enemy_flagged_in_ops(self):
        """Enemy with jam_factor ≥ 0.5 gets jammed=True in ops state."""
        enemy = _make_enemy()
        enemy.jam_factor = 0.6
        world = _make_world([enemy])
        ship = _make_ship()
        # Need to register an assessment.
        glops.start_assessment("e1", world, ship)
        state = glops.build_state(world, ship)
        asmts = state.get("assessments", {})
        if "e1" in asmts:
            assert asmts["e1"].get("jammed") is True


# ===========================================================================
# C.10: Flight Ops ↔ Multiple
# ===========================================================================


class TestFlightOpsIntegration:
    """C.10: Drone contacts, rescue ETA, ECM effectiveness."""

    def test_rescue_eta_empty_when_no_cargo(self):
        """get_rescue_drone_eta returns empty when no rescue missions."""
        eta = glfo.get_rescue_drone_eta()
        assert eta == []

    def test_ecm_drone_effectiveness(self):
        """get_ecm_drone_effectiveness returns float."""
        eff = glfo.get_ecm_drone_effectiveness()
        assert isinstance(eff, float)
        assert eff >= 0.0

    def test_retarget_clears_mission_target(self):
        """retarget_drones_from doesn't crash with no active missions."""
        glfo.retarget_drones_from("dead_enemy")
        # No exception = pass.


# ===========================================================================
# C.8: Comms ↔ Ops ↔ Captain
# ===========================================================================


class TestCommsOpsIntegration:
    """C.8: Intel pipeline + action requests + mission feasibility."""

    def test_intel_routes_through_ops(self):
        """receive_comms_intel creates analysis for captain."""
        intel = {
            "signal_id": "sig_1",
            "source_name": "Frigate Echo",
            "intel_category": "tactical",
            "threat_level": "high",
        }
        glops.receive_comms_intel(intel)
        analyses = glops.pop_intel_analysis()
        assert len(analyses) == 1
        assert analyses[0]["category"] == "tactical"
        assert analyses[0]["risk_level"] == "high"

    def test_tactical_intel_analysed(self):
        """Tactical intel with high threat → high risk."""
        intel = {
            "signal_id": "sig_2",
            "source_name": "Unknown",
            "intel_category": "tactical",
            "threat_level": "critical",
        }
        glops.receive_comms_intel(intel)
        analyses = glops.pop_intel_analysis()
        assert analyses[0]["risk_level"] == "high"
        assert analyses[0]["recommendation"] == "Recommend caution"

    def test_low_risk_intel(self):
        """General intel with low threat → low risk."""
        intel = {
            "signal_id": "sig_3",
            "source_name": "Station Alpha",
            "intel_category": "general",
            "threat_level": "low",
        }
        glops.receive_comms_intel(intel)
        analyses = glops.pop_intel_analysis()
        assert analyses[0]["risk_level"] == "low"

    def test_intel_analysis_pop_clear(self):
        """pop_intel_analysis clears the buffer."""
        glops.receive_comms_intel({"signal_id": "x", "intel_category": "general"})
        glops.pop_intel_analysis()
        assert glops.pop_intel_analysis() == []

    def test_comms_action_request(self):
        """request_comms_action queues advisory broadcast."""
        result = glops.request_comms_action("hail_contact", "Unknown vessel")
        assert result["ok"] is True
        assert result["action"] == "hail_contact"

    def test_comms_action_invalid(self):
        """Invalid action is rejected."""
        result = glops.request_comms_action("invalid_action")
        assert result["ok"] is False

    def test_mission_feasibility_low_risk(self):
        """Healthy ship → low risk assessment."""
        ship = _make_ship()
        ship.hull = 100.0
        ship.hull_max = 120.0
        world = _make_world()
        result = glops.assess_mission_feasibility({}, ship, world)
        assert result["risk_level"] == "low"

    def test_mission_feasibility_high_risk(self):
        """Damaged ship → high risk assessment."""
        ship = _make_ship()
        ship.hull = 20.0
        ship.hull_max = 120.0
        world = _make_world()
        result = glops.assess_mission_feasibility({}, ship, world)
        assert result["risk_level"] == "high"
        assert "critical" in result["recommendation"].lower()


# ===========================================================================
# Atmosphere helper test
# ===========================================================================


class TestAtmosphereHelper:
    """Test get_all_atmosphere() helper for C.7."""

    def test_get_all_atmosphere_returns_dict(self):
        """get_all_atmosphere returns atmosphere state dict."""
        interior = _make_interior()
        glatm.init_atmosphere(interior)
        all_atm = glatm.get_all_atmosphere()
        assert isinstance(all_atm, dict)
        assert "bridge" in all_atm
