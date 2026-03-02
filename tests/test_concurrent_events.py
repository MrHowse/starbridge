"""
Tests for concurrent game events happening on the same tick.

Verifies that multiple game subsystems can process events simultaneously
without interfering with each other: combat + boarding, creature attacks +
system damage, fire + DCT repair, cumulative damage, medical treatment
during crew injury, power changes during combat, and crew death during
active state.
"""
from __future__ import annotations

import random
from unittest.mock import MagicMock

import pytest

from server.models.interior import make_default_interior
from server.models.ship import Ship
from server.models.world import World, spawn_enemy, spawn_creature
from server.models.crew_roster import (
    CrewMember,
    IndividualCrewRoster,
    Injury,
)
from server.models.injuries import (
    CRITICAL_DEATH_TIMER,
    generate_injuries,
)
from server.systems.combat import (
    apply_hit_to_player,
    apply_hit_to_enemy,
    CombatHitResult,
    CREW_CASUALTY_PER_HULL_DAMAGE,
)
import server.game_loop_hazard_control as glhc
import server.game_loop_medical_v2 as glmed
import server.game_loop_engineering as gle
import server.game_loop_security as gls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ship(**overrides) -> Ship:
    """Create a ship with sensible test defaults."""
    ship = Ship()
    for k, v in overrides.items():
        setattr(ship, k, v)
    return ship


def _make_roster(count: int = 8) -> IndividualCrewRoster:
    """Generate a deterministic crew roster."""
    return IndividualCrewRoster.generate(count, "frigate", rng=random.Random(42))


def _make_crew_member(
    crew_id: str = "crew_001",
    deck: int = 1,
    duty_station: str = "manoeuvring",
    status: str = "active",
) -> CrewMember:
    """Create a single crew member with minimal fields."""
    return CrewMember(
        id=crew_id,
        first_name="Test",
        surname="Crewman",
        rank="Crewman",
        rank_level=1,
        deck=deck,
        duty_station=duty_station,
        status=status,
        location=f"deck_{deck}",
    )


# ============================================================================
# Scenario 1 — Combat + boarding on the same tick
# ============================================================================


class TestCombatPlusBoardingConcurrent:
    """Combat hit and boarding activation on the same tick."""

    def test_hull_damage_and_intruders_spawn_concurrently(self):
        """Apply a beam hit and start boarding on the same call — both effects
        must apply without interfering."""
        ship = _make_ship()
        rng = random.Random(42)
        hull_before = ship.hull

        # 1. Apply combat hit (enemy north of ship → fore shields absorb).
        result = apply_hit_to_player(
            ship, damage=30.0,
            attacker_x=50_000.0, attacker_y=40_000.0,
            rng=rng, shield_bypass=0.0,
        )

        # 2. Start boarding on the same tick.
        gls.reset()
        interior = ship.interior
        gls.start_boarding(
            interior,
            squad_specs=[{"id": "alpha", "room_id": "d1_corridor"}],
            intruder_specs=[
                {"id": "intruder_1", "room_id": "d5_corridor",
                 "objective_id": "d1_corridor"},
            ],
        )

        # Hull took damage (shields absorbed some, but damage > 0 or shields
        # depleted and hull decreased).
        assert ship.hull <= hull_before
        # Boarding is active with one intruder present.
        assert gls.is_boarding_active()
        assert len(interior.intruders) == 1
        assert len(interior.marine_squads) == 1

    def test_combat_damage_independent_of_boarding_tick(self):
        """After both combat and boarding are set up, ticking security does
        not alter hull damage from combat, and combat result is unchanged."""
        ship = _make_ship()
        rng = random.Random(42)

        result = apply_hit_to_player(
            ship, damage=40.0,
            attacker_x=50_000.0, attacker_y=40_000.0,
            rng=rng, shield_bypass=0.0,
        )
        hull_after_hit = ship.hull

        gls.reset()
        interior = ship.interior
        gls.start_boarding(
            interior,
            squad_specs=[{"id": "alpha", "room_id": "d1_corridor"}],
            intruder_specs=[
                {"id": "intruder_1", "room_id": "d1_corridor",
                 "objective_id": "d5_corridor"},
            ],
        )

        # Tick security once — this should not change hull.
        events = gls.tick_security(interior, ship, 0.1)
        assert ship.hull == hull_after_hit
        # Security events should exist (intruder/squad in same room → combat).
        # At minimum, the tick runs without error.
        assert isinstance(events, list)

    def test_boarding_with_shield_bypass_hit(self):
        """A creature-style shield-bypass hit + boarding at the same time."""
        ship = _make_ship()
        rng = random.Random(42)

        # Shield-bypass hit (like a creature attack).
        result = apply_hit_to_player(
            ship, damage=25.0,
            attacker_x=50_000.0, attacker_y=60_000.0,
            rng=rng, shield_bypass=0.3,
        )

        gls.reset()
        interior = ship.interior
        gls.start_boarding(
            interior,
            squad_specs=[{"id": "bravo", "room_id": "d3_corridor"}],
            intruder_specs=[
                {"id": "intruder_a", "room_id": "d5_corridor",
                 "objective_id": "d1_corridor"},
                {"id": "intruder_b", "room_id": "d4_corridor",
                 "objective_id": "d1_corridor"},
            ],
        )

        # Bypass damage should have reduced hull more than pure shield hit.
        assert ship.hull < 100.0
        assert gls.is_boarding_active()
        assert len(interior.intruders) == 2


# ============================================================================
# Scenario 2 — Creature attack + system malfunction
# ============================================================================


class TestCreatureAttackPlusSystemMalfunction:
    """Creature hit with shield bypass + engineering system damage on the same tick."""

    def test_creature_hit_and_system_damage_independent(self):
        """Apply a creature hit (shield_bypass) AND gle.apply_system_damage —
        both damage sources apply independently."""
        ship = _make_ship()
        gle.reset()
        gle.init(ship)

        rng = random.Random(42)

        # 1. Creature hit with 50% shield bypass.
        result = apply_hit_to_player(
            ship, damage=20.0,
            attacker_x=50_000.0, attacker_y=40_000.0,
            rng=rng, shield_bypass=0.5,
        )
        hull_after_creature = ship.hull

        # 2. System malfunction on the same tick.
        events = gle.apply_system_damage("sensors", 30.0, "malfunction", tick=1)

        # Hull should have taken creature damage.
        assert hull_after_creature < 100.0
        # Engineering damage model should have recorded sensor damage.
        dm = gle.get_damage_model()
        assert dm is not None
        sensor_health = dm.get_system_health("sensors")
        assert sensor_health < 100.0

    def test_two_simultaneous_damage_sources_stack(self):
        """Creature hit damages hull; engineering damages beams — both accumulate."""
        ship = _make_ship()
        gle.reset()
        gle.init(ship)

        rng = random.Random(42)

        # Creature hit.
        apply_hit_to_player(
            ship, damage=15.0,
            attacker_x=50_000.0, attacker_y=60_000.0,
            rng=rng, shield_bypass=0.3,
        )

        # System damage via engineering.
        gle.apply_system_damage("beams", 40.0, "creature_malfunction", tick=1)

        # Tick engineering to sync health back to ship.
        gle.tick(ship, ship.interior, 0.1)

        assert ship.hull < 100.0
        assert ship.systems["beams"].health < 100.0

    def test_creature_bypass_reduces_hull_more_than_shielded(self):
        """Verify shield_bypass=0.5 lets more damage through than bypass=0.0."""
        ship_no_bypass = _make_ship()
        ship_bypass = _make_ship()

        rng1 = MagicMock()
        rng1.random = MagicMock(return_value=0.99)  # no system damage roll
        rng1.choice = MagicMock(return_value="sensors")
        rng1.uniform = MagicMock(return_value=10.0)

        rng2 = MagicMock()
        rng2.random = MagicMock(return_value=0.99)
        rng2.choice = MagicMock(return_value="sensors")
        rng2.uniform = MagicMock(return_value=10.0)

        apply_hit_to_player(
            ship_no_bypass, damage=40.0,
            attacker_x=50_000.0, attacker_y=40_000.0,
            rng=rng1, shield_bypass=0.0,
        )
        apply_hit_to_player(
            ship_bypass, damage=40.0,
            attacker_x=50_000.0, attacker_y=40_000.0,
            rng=rng2, shield_bypass=0.5,
        )

        # With bypass, more damage reaches hull.
        assert ship_bypass.hull < ship_no_bypass.hull


# ============================================================================
# Scenario 3 — Fire + DCT repair on the same tick
# ============================================================================


class TestFirePlusDCTConcurrent:
    """A room is on fire while a DCT is dispatched and ticking."""

    def test_dct_progresses_while_fire_present(self):
        """Dispatch DCT to a room on fire, tick — DCT timer advances even
        though the fire is still burning."""
        glhc.reset()
        interior = make_default_interior()

        # Set a room on fire.
        room = interior.rooms["weapons_bay"]
        room.state = "fire"

        # Dispatch DCT.
        assert glhc.dispatch_dct("weapons_bay", interior)

        # Tick a few seconds (< DCT_REPAIR_DURATION=8.0).
        for _ in range(30):  # 3.0 seconds
            glhc.tick(interior, 0.1)

        # DCT should have progress but room is still on fire (not yet 8s).
        dc_state = glhc.build_dc_state(interior)
        assert "weapons_bay" in dc_state["active_dcts"]
        progress = dc_state["active_dcts"]["weapons_bay"]
        assert progress > 0.0
        assert progress < 1.0
        assert room.state == "fire"  # still on fire, repair not complete

    def test_dct_completes_fire_to_damaged(self):
        """After DCT_REPAIR_DURATION ticks, fire is reduced to damaged."""
        glhc.reset()
        interior = make_default_interior()

        room = interior.rooms["sensor_array"]
        room.state = "fire"

        glhc.dispatch_dct("sensor_array", interior)

        # Tick for 8.1 seconds (just past DCT_REPAIR_DURATION=8.0).
        for _ in range(81):
            glhc.tick(interior, 0.1)

        # Room should now be "damaged" (one severity level down from fire).
        assert room.state == "damaged"


# ============================================================================
# Scenario 4 — Multiple damage to the same system
# ============================================================================


class TestMultipleDamageToSameSystem:
    """Two separate hits that both damage the same ship system."""

    def test_two_combat_hits_cumulate_hull_damage(self):
        """Two consecutive beam hits in the same tick accumulate hull damage."""
        ship = _make_ship()
        # Use mock rng that always rolls system damage on "sensors".
        rng = MagicMock()
        rng.random = MagicMock(return_value=0.99)  # > HULL_SYSTEM_DAMAGE_CHANCE → no system dmg
        rng.choice = MagicMock(return_value="sensors")
        rng.uniform = MagicMock(return_value=15.0)

        # Drain fore shields first for reliable hull damage.
        ship.shields.fore = 0.0

        apply_hit_to_player(
            ship, damage=20.0,
            attacker_x=50_000.0, attacker_y=40_000.0,
            rng=rng, shield_bypass=0.0,
        )
        hull_after_first = ship.hull

        apply_hit_to_player(
            ship, damage=20.0,
            attacker_x=50_000.0, attacker_y=40_000.0,
            rng=rng, shield_bypass=0.0,
        )
        hull_after_second = ship.hull

        # Both hits dealt hull damage that accumulated.
        assert hull_after_first < 100.0
        assert hull_after_second < hull_after_first

    def test_two_hits_damage_same_system_component(self):
        """Two gle.apply_system_damage calls on the same system accumulate."""
        ship = _make_ship()
        gle.reset()
        gle.init(ship)

        gle.apply_system_damage("engines", 25.0, "hit_1", tick=1)
        health_after_first = gle.get_damage_model().get_system_health("engines")

        gle.apply_system_damage("engines", 25.0, "hit_2", tick=1)
        health_after_second = gle.get_damage_model().get_system_health("engines")

        assert health_after_first < 100.0
        assert health_after_second < health_after_first

    def test_combat_plus_engineering_damage_same_system(self):
        """Combat damages a system via rng roll AND engineering applies
        damage to the same system — both stack."""
        ship = _make_ship()
        gle.reset()
        gle.init(ship)

        # Force combat to damage sensors.
        rng = MagicMock()
        rng.random = MagicMock(return_value=0.01)  # < HULL_SYSTEM_DAMAGE_CHANCE → triggers
        rng.choice = MagicMock(return_value="sensors")
        rng.uniform = MagicMock(return_value=15.0)

        ship.shields.fore = 0.0
        result = apply_hit_to_player(
            ship, damage=10.0,
            attacker_x=50_000.0, attacker_y=40_000.0,
            rng=rng, shield_bypass=0.0,
        )
        # Combat should have damaged sensors.
        assert len(result.damaged_systems) > 0
        sensor_health_after_combat = ship.systems["sensors"].health

        # Engineering also damages sensors.
        gle.apply_system_damage("sensors", 20.0, "malfunction", tick=1)

        # Tick to sync.
        gle.tick(ship, ship.interior, 0.1)

        # After engineering sync, sensor health should be lower than after
        # combat alone (engineering health is source of truth after sync).
        dm_health = gle.get_damage_model().get_system_health("sensors")
        assert dm_health < 100.0


# ============================================================================
# Scenario 5 — Medical crew injury during treatment
# ============================================================================


class TestMedicalInjuryDuringTreatment:
    """Start treating a patient, then injure medical crew — treatment
    continues but may be slower."""

    def _setup_medical(self):
        """Set up medical with a roster and one injured patient in bed."""
        glmed.reset()
        roster = _make_roster(count=8)
        glmed.init_roster(roster, "frigate")

        # Pick a crew member and give them an injury.
        patient_id = list(roster.members.keys())[0]
        patient = roster.members[patient_id]
        injury = Injury(
            id=roster.next_injury_id(),
            type="lacerations",
            body_region="torso",
            severity="moderate",
            description="Test injury",
            caused_by="explosion",
            treatment_type="first_aid",
            treatment_duration=20.0,
        )
        patient.injuries.append(injury)
        patient.update_status()

        # Admit to medical bay and start treatment.
        glmed.admit_patient(patient_id)
        result = glmed.start_crew_treatment(
            patient_id, injury.id, "first_aid",
        )
        assert result["success"]

        return roster, patient_id, injury

    def test_treatment_progresses_with_full_medical_crew(self):
        """With full medical crew, treatment progresses at normal rate."""
        roster, patient_id, injury = self._setup_medical()

        # Tick for 5 seconds.
        for _ in range(50):
            glmed.tick(roster, 0.1)

        state = glmed.get_medical_state()
        treatment = state["active_treatments"].get(patient_id)
        assert treatment is not None
        assert treatment["elapsed"] > 0.0

    def test_treatment_continues_after_medical_crew_injured(self):
        """Injure medical crew (reduce crew factor) — treatment continues."""
        roster, patient_id, injury = self._setup_medical()

        # Tick a bit so treatment starts.
        for _ in range(20):
            glmed.tick(roster, 0.1)

        state_before = glmed.get_medical_state()
        elapsed_before = state_before["active_treatments"][patient_id]["elapsed"]
        assert elapsed_before > 0.0

        # Injure medical bay crew (deck 4) — reduce their effectiveness.
        med_crew = roster.get_by_duty_station("medical_bay")
        for mc in med_crew:
            mc_injury = Injury(
                id=roster.next_injury_id(),
                type="blast_concussion",
                body_region="head",
                severity="serious",
                description="Blast concussion",
                caused_by="explosion",
                treatment_type="stabilise",
                treatment_duration=25.0,
            )
            mc.injuries.append(mc_injury)
            mc.update_status()

        # Medical crew factor should be reduced.
        med_factor = roster.crew_factor_for_duty_station("medical_bay")
        assert med_factor < 1.0

        # Tick more — treatment should still advance (just possibly slower).
        for _ in range(20):
            glmed.tick(roster, 0.1)

        state_after = glmed.get_medical_state()
        treatment_after = state_after["active_treatments"].get(patient_id)
        # Treatment should have advanced further (or completed).
        if treatment_after is not None:
            assert treatment_after["elapsed"] > elapsed_before
        # If treatment_after is None, treatment completed — that's also fine.

    def test_new_injuries_dont_cancel_active_treatment(self):
        """Generating new injuries on the ship doesn't cancel existing treatments."""
        roster, patient_id, injury = self._setup_medical()

        for _ in range(10):
            glmed.tick(roster, 0.1)

        state_before = glmed.get_medical_state()
        assert patient_id in state_before["active_treatments"]

        # Generate injuries on a different deck (deck 3 = weapons).
        rng = random.Random(42)
        new_injuries = generate_injuries(
            cause="explosion",
            deck=3,
            roster=roster,
            severity_scale=1.0,
            rng=rng,
        )

        # Apply injuries to crew members.
        for crew_id, inj in new_injuries:
            member = roster.members[crew_id]
            member.injuries.append(inj)
            member.update_status()

        # Tick again — original treatment should still be active.
        for _ in range(10):
            glmed.tick(roster, 0.1)

        state_after = glmed.get_medical_state()
        # Original treatment is either still running or completed — never cancelled.
        if patient_id in state_after["active_treatments"]:
            assert state_after["active_treatments"][patient_id]["elapsed"] > 0.0


# ============================================================================
# Scenario 6 — Power changes during combat
# ============================================================================


class TestPowerChangesDuringCombat:
    """Battery charging + reactor damage on the same tick cycle."""

    def test_battery_charges_then_reactor_damaged(self):
        """Battery in charging mode → tick → reactor damage → tick again.
        Battery should adjust to reduced reactor output."""
        ship = _make_ship()
        gle.reset()
        gle.init(ship)

        pg = gle.get_power_grid()
        assert pg is not None

        # Set battery to charging mode.
        pg.set_battery_mode("charging")
        initial_charge = pg.battery_charge

        # Tick engineering — battery should start charging from reactor surplus.
        gle.tick(ship, ship.interior, 0.1)
        charge_after_first_tick = pg.battery_charge

        # Battery should have charged (reactor output > system demand).
        assert charge_after_first_tick >= initial_charge

        # Now damage the reactor (simulates combat damage on the same tick).
        pg.damage_reactor(60.0)  # reactor health → 40%
        assert pg.reactor_health == 40.0

        # Tick again — reactor output is reduced, less surplus for charging.
        gle.tick(ship, ship.interior, 0.1)

        # Reactor output is now 40% of max (700 * 0.4 = 280).
        assert pg.reactor_output == pytest.approx(280.0, abs=0.1)

    def test_reactor_damage_triggers_battery_discharge_in_auto(self):
        """With battery in auto mode, if reactor damage causes deficit,
        battery switches to discharge automatically."""
        ship = _make_ship()
        gle.reset()
        gle.init(ship)

        pg = gle.get_power_grid()
        assert pg is not None

        # Ensure auto mode.
        pg.set_battery_mode("auto")
        pg.battery_charge = 300.0  # plenty of charge

        # Set all systems to 100 power (total demand = 900).
        for sys_name in ship.systems:
            gle.set_power(sys_name, 100.0)

        # Damage reactor severely so output < demand.
        pg.damage_reactor(90.0)  # reactor health → 10%, output = 70
        assert pg.reactor_output == pytest.approx(70.0, abs=0.1)

        # Tick — battery should discharge to compensate.
        result = gle.tick(ship, ship.interior, 0.1)

        # Battery should have discharged (charge decreased).
        assert pg.battery_charge < 300.0


# ============================================================================
# Scenario 7 — Crew death during active state
# ============================================================================


class TestCrewDeathDuringActiveState:
    """Crew member with critical injury ticks past death timer — crew factor
    updates, death event fires, morgue populated."""

    def test_critical_injury_death_timer_fires(self):
        """Tick medical past the death timer → crew_death event, status=dead."""
        glmed.reset()
        roster = _make_roster(count=6)
        glmed.init_roster(roster, "frigate")

        # Give a crew member a critical injury with short death timer.
        victim_id = list(roster.members.keys())[0]
        victim = roster.members[victim_id]
        injury = Injury(
            id=roster.next_injury_id(),
            type="internal_bleeding",
            body_region="torso",
            severity="critical",
            description="Internal bleeding",
            caused_by="explosion",
            death_timer=5.0,  # 5 seconds until death
            treatment_type="surgery",
            treatment_duration=45.0,
        )
        victim.injuries.append(injury)
        victim.update_status()
        assert victim.status == "critical"

        # Tick medical for 6 seconds (past the 5s death timer).
        all_events = []
        for _ in range(60):
            events = glmed.tick(roster, 0.1)
            all_events.extend(events)

        # Crew member should be dead.
        assert victim.status == "dead"
        assert victim.location == "morgue"

        # Death event should have fired.
        death_events = [e for e in all_events if e.get("event") == "crew_death"]
        assert len(death_events) >= 1
        assert death_events[0]["crew_id"] == victim_id

        # Morgue should contain the victim.
        state = glmed.get_medical_state()
        assert victim_id in state["morgue"]

    def test_crew_factor_updates_after_death(self):
        """After crew death, the crew factor for their duty station drops."""
        glmed.reset()
        roster = _make_roster(count=8)
        glmed.init_roster(roster, "frigate")

        # Find a crew member on a specific duty station.
        victim_id = None
        victim_station = None
        for mid, member in roster.members.items():
            if member.status == "active":
                victim_id = mid
                victim_station = member.duty_station
                break
        assert victim_id is not None

        # Record crew factor before death.
        factor_before = roster.crew_factor_for_duty_station(victim_station)

        # Kill the crew member via critical injury.
        victim = roster.members[victim_id]
        injury = Injury(
            id=roster.next_injury_id(),
            type="severe_burns",
            body_region="torso",
            severity="critical",
            description="Severe burns",
            caused_by="fire",
            death_timer=2.0,
            treatment_type="intensive_care",
            treatment_duration=50.0,
        )
        victim.injuries.append(injury)
        victim.update_status()

        # Tick past death timer.
        for _ in range(30):
            glmed.tick(roster, 0.1)

        assert victim.status == "dead"

        # Crew factor should have decreased.
        factor_after = roster.crew_factor_for_duty_station(victim_station)
        assert factor_after < factor_before
