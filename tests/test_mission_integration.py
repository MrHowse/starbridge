"""Integration tests for Comms → Contact → Mission pipeline — v0.06.4 Part 4.

Full pipeline tests: signal decode → contact creation → mission generation →
captain accept → objective auto-completion → mission completion → rewards.
"""
from __future__ import annotations

import pytest

import server.game_loop_comms as glco
import server.game_loop_dynamic_missions as gldm
from server.models.dynamic_mission import (
    DynamicMission,
    MissionObjective,
    MissionRewards,
    NAVIGATE_COMPLETION_RADIUS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fresh():
    """Reset both comms and dynamic missions modules."""
    glco.reset()
    gldm.reset()


def _add_distress_signal(x=45200.0, y=83260.0):
    """Add a distress signal that requires decode."""
    return glco.add_signal(
        source="distress_beacon",
        source_name="ISS Valiant",
        frequency=0.90,
        signal_type="distress",
        priority="critical",
        raw_content=f"EMERGENCY — vessel in distress at ({int(x)}, {int(y)}).",
        decoded_content=f"EMERGENCY — vessel in distress at ({int(x)}, {int(y)}).",
        auto_decoded=False,
        requires_decode=True,
        faction="civilian",
        threat_level="unknown",
        response_deadline=90.0,
        location_data={
            "type": "exact",
            "position": [x, y],
            "radius": 0.0,
            "entity_type": "ship",
        },
    )


def _add_encrypted_signal(x=30000.0, y=50000.0):
    """Add an encrypted hostile signal that requires decode."""
    return glco.add_signal(
        source="intercept_src",
        source_name="Imperial Patrol",
        frequency=0.15,
        signal_type="encrypted",
        priority="high",
        raw_content="Encrypted fleet communication — hostile signatures.",
        decoded_content="Encrypted fleet communication — hostile signatures.",
        auto_decoded=False,
        requires_decode=True,
        faction="imperial",
        threat_level="hostile",
        location_data={
            "type": "approximate",
            "position": [x, y],
            "radius": 8000.0,
            "entity_type": "fleet",
        },
    )


def _add_hail_signal(x=40000.0, y=60000.0, faction="civilian"):
    """Add a civilian hail signal that requires decode."""
    return glco.add_signal(
        source="mv_prospector",
        source_name="MV Prospector",
        frequency=0.55,
        signal_type="hail",
        priority="medium",
        raw_content="This is MV Prospector. Requesting escort.",
        decoded_content="This is MV Prospector. Requesting escort.",
        auto_decoded=False,
        requires_decode=True,
        faction=faction,
        threat_level="friendly",
        location_data={
            "type": "exact",
            "position": [x, y],
            "radius": 0.0,
            "entity_type": "ship",
        },
    )


def _add_data_burst_signal(x=55000.0, y=40000.0):
    """Add a data burst signal that requires decode."""
    return glco.add_signal(
        source="probe_relay",
        source_name="Probe Relay Alpha",
        frequency=0.45,
        signal_type="data_burst",
        priority="medium",
        raw_content="Automated data burst — anomalous readings detected.",
        decoded_content="Automated data burst — anomalous readings detected.",
        auto_decoded=False,
        requires_decode=True,
        faction="civilian",
        threat_level="unknown",
        location_data={
            "type": "approximate",
            "position": [x, y],
            "radius": 5000.0,
            "entity_type": "anomaly",
        },
    )


def _tick_decode_to_completion(dt=0.1, max_ticks=5000):
    """Tick comms until first signal is fully decoded."""
    for _ in range(max_ticks):
        glco.tick_comms(dt, crew_factor=1.0)
        sigs = glco.get_signals()
        if sigs and sigs[0].decode_progress >= 1.0:
            return
    raise TimeoutError("Signal decode did not complete")


def _tick_decode_to_progress(target, dt=0.1, max_ticks=5000):
    """Tick comms until first signal reaches target progress."""
    for _ in range(max_ticks):
        glco.tick_comms(dt, crew_factor=1.0)
        sigs = glco.get_signals()
        if sigs and sigs[0].decode_progress >= target:
            return
    raise TimeoutError(f"Signal didn't reach {target} progress")


def _make_mission_with_objectives(
    mission_id="dm_integ",
    objectives=None,
    waypoint=(50000.0, 50000.0),
    mission_type="rescue",
):
    """Create a test mission with custom objectives."""
    if objectives is None:
        objectives = [
            MissionObjective(
                id="nav_1", description="Navigate to target",
                objective_type="navigate_to", target_position=waypoint,
            ),
        ]
    return DynamicMission(
        id=mission_id,
        source_signal_id="sig_1",
        source_contact_id="cc_1",
        title=f"Test {mission_type.title()} Mission",
        briefing="Test briefing.",
        mission_type=mission_type,
        objectives=objectives,
        waypoint=waypoint,
        waypoint_name="Target",
        status="offered",
        accept_deadline=60.0,
        completion_deadline=300.0,
        rewards=MissionRewards(
            faction_standing={"civilian": 10.0},
            crew=2,
            reputation=5,
            description="Test rewards",
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Full Pipeline: Signal → Contact → Mission
# ═══════════════════════════════════════════════════════════════════════════


class TestSignalToMissionPipeline:
    """Signal decode generates a contact and a mission."""

    def test_distress_decode_creates_mission(self):
        """Full pipeline: distress signal → decode → rescue mission generated."""
        fresh()
        _add_distress_signal()
        glco.start_decode(glco.get_signals()[0].id)
        _tick_decode_to_completion()

        missions = glco.pop_pending_generated_missions()
        assert len(missions) == 1
        m = missions[0]
        assert m.mission_type == "rescue"
        assert m.source_signal_id == glco.get_signals()[0].id

    def test_distress_decode_creates_contact(self):
        """Decode creates a comms contact at signal location."""
        fresh()
        sig = _add_distress_signal(x=45200.0, y=83260.0)
        glco.start_decode(sig.id)
        _tick_decode_to_completion()

        contacts = glco.get_comms_contacts()
        assert len(contacts) >= 1
        cc = contacts[0]
        assert cc.source_signal_id == sig.id
        assert abs(cc.position[0] - 45200.0) < 100
        assert abs(cc.position[1] - 83260.0) < 100

    def test_encrypted_decode_creates_intercept_mission(self):
        """Encrypted hostile signal → intercept mission."""
        fresh()
        sig = _add_encrypted_signal()
        glco.start_decode(sig.id)
        _tick_decode_to_completion()

        missions = glco.pop_pending_generated_missions()
        assert len(missions) == 1
        assert missions[0].mission_type == "intercept"

    def test_civilian_hail_creates_escort_mission(self):
        """Civilian hail → escort mission."""
        fresh()
        sig = _add_hail_signal(faction="civilian")
        glco.start_decode(sig.id)
        _tick_decode_to_completion()

        missions = glco.pop_pending_generated_missions()
        assert len(missions) == 1
        assert missions[0].mission_type == "escort"

    def test_data_burst_creates_investigation_mission(self):
        """Data burst signal → investigation mission."""
        fresh()
        sig = _add_data_burst_signal()
        glco.start_decode(sig.id)
        _tick_decode_to_completion()

        missions = glco.pop_pending_generated_missions()
        assert len(missions) == 1
        assert missions[0].mission_type == "investigate"

    def test_mission_links_to_contact(self):
        """Generated mission has source_contact_id matching the created contact."""
        fresh()
        sig = _add_distress_signal()
        glco.start_decode(sig.id)
        _tick_decode_to_completion()

        missions = glco.pop_pending_generated_missions()
        assert len(missions) == 1
        m = missions[0]
        assert m.source_contact_id is not None

        contacts = glco.get_comms_contacts()
        contact_ids = [c.id for c in contacts]
        assert m.source_contact_id in contact_ids

    def test_progressive_contact_before_mission(self):
        """Contact appears at 25% decode, mission only at 100%."""
        fresh()
        sig = _add_distress_signal()
        glco.start_decode(sig.id)

        # Decode to 25% — contact should exist but no mission yet
        _tick_decode_to_progress(0.25)
        contacts = glco.get_comms_contacts()
        assert len(contacts) >= 1
        assert len(glco.pop_pending_generated_missions()) == 0

        # Continue to 100%
        _tick_decode_to_completion()
        missions = glco.pop_pending_generated_missions()
        assert len(missions) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Mission Accept → Objective Tracking
# ═══════════════════════════════════════════════════════════════════════════


class TestMissionAcceptAndTrack:
    """Captain accepts missions and objectives are tracked."""

    def test_accept_mission_activates_objectives(self):
        """Accepting an offered mission sets it to active."""
        fresh()
        m = _make_mission_with_objectives()
        gldm.offer_mission(m)
        result = gldm.accept_mission(m.id)
        assert result["ok"]
        assert gldm.get_mission(m.id).status in ("accepted", "active")

    def test_navigate_to_auto_completes(self):
        """Navigate_to objective completes when ship reaches waypoint."""
        fresh()
        target = (50000.0, 50000.0)
        m = _make_mission_with_objectives(waypoint=target)
        gldm.offer_mission(m)
        gldm.accept_mission(m.id)

        # Ship far away — not complete
        gldm.tick_missions(0.0, 0.0, 0.1)
        assert not m.objectives[0].completed

        # Ship at waypoint — complete
        gldm.tick_missions(target[0], target[1], 0.1)
        assert m.objectives[0].completed

    def test_navigate_within_radius(self):
        """Navigate_to completes within NAVIGATE_COMPLETION_RADIUS."""
        fresh()
        target = (50000.0, 50000.0)
        m = _make_mission_with_objectives(waypoint=target)
        gldm.offer_mission(m)
        gldm.accept_mission(m.id)

        # Just within radius
        near_x = target[0] + NAVIGATE_COMPLETION_RADIUS - 100
        gldm.tick_missions(near_x, target[1], 0.1)
        assert m.objectives[0].completed


# ═══════════════════════════════════════════════════════════════════════════
# Destroy Objective Auto-completion
# ═══════════════════════════════════════════════════════════════════════════


class TestDestroyObjective:
    """Destroy objectives complete when target is absent from alive enemies."""

    def test_destroy_completes_when_enemy_gone(self):
        """Destroy objective completes when target_id not in alive enemies."""
        fresh()
        m = _make_mission_with_objectives(objectives=[
            MissionObjective(
                id="destroy_1", description="Destroy hostile vessel",
                objective_type="destroy", target_id="enemy_alpha",
            ),
        ])
        gldm.offer_mission(m)
        gldm.accept_mission(m.id)

        # Enemy still alive
        gldm.tick_missions(0.0, 0.0, 0.1, enemy_ids=frozenset({"enemy_alpha", "enemy_beta"}))
        assert not m.objectives[0].completed

        # Enemy destroyed (absent from set)
        gldm.tick_missions(0.0, 0.0, 0.1, enemy_ids=frozenset({"enemy_beta"}))
        assert m.objectives[0].completed

    def test_destroy_not_checked_without_enemy_ids(self):
        """Without enemy_ids, destroy objectives are not checked."""
        fresh()
        m = _make_mission_with_objectives(objectives=[
            MissionObjective(
                id="destroy_1", description="Destroy hostile",
                objective_type="destroy", target_id="enemy_alpha",
            ),
        ])
        gldm.offer_mission(m)
        gldm.accept_mission(m.id)

        # No enemy_ids passed — should not complete
        gldm.tick_missions(0.0, 0.0, 0.1)
        assert not m.objectives[0].completed

    def test_destroy_completes_mission(self):
        """Destroying last required target completes the mission."""
        fresh()
        m = _make_mission_with_objectives(objectives=[
            MissionObjective(
                id="nav_1", description="Navigate to area",
                objective_type="navigate_to", target_position=(50000, 50000),
            ),
            MissionObjective(
                id="destroy_1", description="Destroy hostile",
                objective_type="destroy", target_id="enemy_alpha",
            ),
        ])
        gldm.offer_mission(m)
        gldm.accept_mission(m.id)

        # Complete navigate
        gldm.tick_missions(50000, 50000, 0.1, enemy_ids=frozenset({"enemy_alpha"}))
        assert m.objectives[0].completed
        assert not m.objectives[1].completed
        assert m.status in ("accepted", "active")

        # Destroy enemy
        gldm.tick_missions(50000, 50000, 0.1, enemy_ids=frozenset())
        assert m.objectives[1].completed
        assert m.status == "completed"


# ═══════════════════════════════════════════════════════════════════════════
# Scan Objective Auto-completion
# ═══════════════════════════════════════════════════════════════════════════


class TestScanObjective:
    """Scan objectives complete via notification when scan finishes."""

    def test_scan_completes_on_notification(self):
        """notify_scan_completed triggers scan objective completion."""
        fresh()
        m = _make_mission_with_objectives(objectives=[
            MissionObjective(
                id="scan_1", description="Scan the anomaly",
                objective_type="scan", target_id="anomaly_x",
            ),
        ])
        gldm.offer_mission(m)
        gldm.accept_mission(m.id)

        # Before notification
        assert not m.objectives[0].completed

        # Wrong entity scanned
        gldm.notify_scan_completed("other_entity")
        assert not m.objectives[0].completed

        # Correct entity scanned
        gldm.notify_scan_completed("anomaly_x")
        assert m.objectives[0].completed

    def test_scan_only_active_missions(self):
        """Scan notification ignored for non-active missions."""
        fresh()
        m = _make_mission_with_objectives(objectives=[
            MissionObjective(
                id="scan_1", description="Scan target",
                objective_type="scan", target_id="entity_1",
            ),
        ])
        gldm.offer_mission(m)
        # Don't accept — still offered

        gldm.notify_scan_completed("entity_1")
        assert not m.objectives[0].completed


# ═══════════════════════════════════════════════════════════════════════════
# Dock Objective Auto-completion
# ═══════════════════════════════════════════════════════════════════════════


class TestDockObjective:
    """Dock objectives complete when docked with target station."""

    def test_dock_completes_when_docked(self):
        """Dock objective completes when docked_station_id matches target."""
        fresh()
        m = _make_mission_with_objectives(objectives=[
            MissionObjective(
                id="dock_1", description="Dock at station",
                objective_type="dock", target_id="station_alpha",
            ),
        ])
        gldm.offer_mission(m)
        gldm.accept_mission(m.id)

        # Not docked
        gldm.tick_missions(0.0, 0.0, 0.1, docked_station_id=None)
        assert not m.objectives[0].completed

        # Docked at wrong station
        gldm.tick_missions(0.0, 0.0, 0.1, docked_station_id="station_beta")
        assert not m.objectives[0].completed

        # Docked at correct station
        gldm.tick_missions(0.0, 0.0, 0.1, docked_station_id="station_alpha")
        assert m.objectives[0].completed

    def test_dock_completes_mission(self):
        """Docking at target completes entire mission if all required done."""
        fresh()
        m = _make_mission_with_objectives(objectives=[
            MissionObjective(
                id="dock_1", description="Dock at station",
                objective_type="dock", target_id="station_alpha",
            ),
        ])
        gldm.offer_mission(m)
        gldm.accept_mission(m.id)

        gldm.tick_missions(0.0, 0.0, 0.1, docked_station_id="station_alpha")
        assert m.status == "completed"


# ═══════════════════════════════════════════════════════════════════════════
# Negotiate Objective Auto-completion
# ═══════════════════════════════════════════════════════════════════════════


class TestNegotiateObjective:
    """Negotiate objectives complete when diplomatic response sent."""

    def test_negotiate_completes_on_response(self):
        """notify_signal_responded triggers negotiate objective completion."""
        fresh()
        m = _make_mission_with_objectives(objectives=[
            MissionObjective(
                id="negotiate_1", description="Negotiate with faction",
                objective_type="negotiate", target_id="sig_diplo",
            ),
        ])
        gldm.offer_mission(m)
        gldm.accept_mission(m.id)

        # Wrong signal
        gldm.notify_signal_responded("sig_other")
        assert not m.objectives[0].completed

        # Correct signal
        gldm.notify_signal_responded("sig_diplo")
        assert m.objectives[0].completed

    def test_negotiate_only_active(self):
        """Negotiate notification ignored for non-active missions."""
        fresh()
        m = _make_mission_with_objectives(objectives=[
            MissionObjective(
                id="negotiate_1", description="Negotiate",
                objective_type="negotiate", target_id="sig_x",
            ),
        ])
        gldm.offer_mission(m)

        gldm.notify_signal_responded("sig_x")
        assert not m.objectives[0].completed


# ═══════════════════════════════════════════════════════════════════════════
# Survive Objective Auto-completion
# ═══════════════════════════════════════════════════════════════════════════


class TestSurviveObjective:
    """Survive objectives complete when target tick is reached."""

    def test_survive_completes_at_tick(self):
        """Survive objective auto-completes when tick >= target_tick."""
        fresh()
        gldm.set_tick(100)
        m = _make_mission_with_objectives(objectives=[
            MissionObjective(
                id="survive_1", description="Survive for 60 seconds",
                objective_type="survive", target_tick=700,
            ),
        ])
        gldm.offer_mission(m)
        gldm.accept_mission(m.id)

        # Not yet
        gldm.set_tick(500)
        gldm.tick_missions(0.0, 0.0, 0.1)
        assert not m.objectives[0].completed

        # Reached
        gldm.set_tick(700)
        gldm.tick_missions(0.0, 0.0, 0.1)
        assert m.objectives[0].completed


# ═══════════════════════════════════════════════════════════════════════════
# Full Rescue Mission Pipeline
# ═══════════════════════════════════════════════════════════════════════════


class TestRescueMissionPipeline:
    """End-to-end: distress signal → rescue mission → navigate → destroy → complete."""

    def test_full_rescue_pipeline(self):
        """Signal → decode → offer → accept → navigate → destroy → complete → rewards."""
        fresh()
        pos = (45200.0, 83260.0)
        _add_distress_signal(x=pos[0], y=pos[1])
        sig = glco.get_signals()[0]

        # Decode signal
        glco.start_decode(sig.id)
        _tick_decode_to_completion()

        # Mission generated
        missions = glco.pop_pending_generated_missions()
        assert len(missions) == 1
        m = missions[0]
        assert m.mission_type == "rescue"

        # Offer and accept
        gldm.offer_mission(m)
        events = gldm.pop_pending_mission_events()
        assert any(e["event"] == "mission_offered" for e in events)

        result = gldm.accept_mission(m.id)
        assert result["ok"]
        events = gldm.pop_pending_mission_events()
        assert any(e["event"] == "mission_accepted" for e in events)

        # Navigate to waypoint
        gldm.tick_missions(m.waypoint[0], m.waypoint[1], 0.1,
                           enemy_ids=frozenset({"hostile_1"}))

        # Check navigate objective completed
        nav_objs = [o for o in m.objectives if o.objective_type == "navigate_to"]
        assert all(o.completed for o in nav_objs)

        # Destroy enemies (if any destroy objectives)
        destroy_objs = [o for o in m.objectives if o.objective_type == "destroy"]
        if destroy_objs:
            # Enemies still alive
            gldm.tick_missions(m.waypoint[0], m.waypoint[1], 0.1,
                               enemy_ids=frozenset())
            assert all(o.completed for o in destroy_objs)

        # Check rewards on completion
        events = gldm.pop_pending_mission_events()
        completed_events = [e for e in events if e["event"] == "mission_completed"]
        if completed_events:
            assert "rewards" in completed_events[0]

    def test_rescue_mission_has_navigate_objective(self):
        """Generated rescue mission always includes a navigate_to objective."""
        fresh()
        _add_distress_signal()
        glco.start_decode(glco.get_signals()[0].id)
        _tick_decode_to_completion()

        missions = glco.pop_pending_generated_missions()
        m = missions[0]
        nav_objs = [o for o in m.objectives if o.objective_type == "navigate_to"]
        assert len(nav_objs) >= 1


# ═══════════════════════════════════════════════════════════════════════════
# Investigation Mission Pipeline
# ═══════════════════════════════════════════════════════════════════════════


class TestInvestigationPipeline:
    """Data burst → investigation mission → navigate → scan → complete."""

    def test_investigation_navigate_and_scan(self):
        """Navigate to anomaly then scan it to complete investigation."""
        fresh()
        pos = (55000.0, 40000.0)
        _add_data_burst_signal(x=pos[0], y=pos[1])
        sig = glco.get_signals()[0]
        glco.start_decode(sig.id)
        _tick_decode_to_completion()

        missions = glco.pop_pending_generated_missions()
        assert len(missions) == 1
        m = missions[0]
        assert m.mission_type == "investigate"
        gldm.offer_mission(m)
        gldm.accept_mission(m.id)

        # Navigate to location
        gldm.tick_missions(pos[0], pos[1], 0.1)
        nav_objs = [o for o in m.objectives if o.objective_type == "navigate_to"]
        assert all(o.completed for o in nav_objs)

        # Scan the target (find scan objective's target_id)
        scan_objs = [o for o in m.objectives if o.objective_type == "scan"]
        if scan_objs:
            gldm.notify_scan_completed(scan_objs[0].target_id)
            assert scan_objs[0].completed


# ═══════════════════════════════════════════════════════════════════════════
# Mission Deadline + Failure
# ═══════════════════════════════════════════════════════════════════════════


class TestMissionDeadlineAndFailure:
    """Deadline expiry and mission failure paths."""

    def test_accept_deadline_expires(self):
        """Offer expires if not accepted within deadline."""
        fresh()
        m = _make_mission_with_objectives()
        m.accept_deadline = 5.0
        gldm.offer_mission(m)

        # Tick 50 times at 0.1s = 5.0s
        for _ in range(51):
            gldm.tick_missions(0.0, 0.0, 0.1)

        assert m.status == "expired"
        events = gldm.pop_pending_mission_events()
        assert any(e["event"] == "mission_expired" for e in events)

    def test_completion_deadline_fails_mission(self):
        """Active mission fails when completion deadline runs out."""
        fresh()
        m = _make_mission_with_objectives()
        m.completion_deadline = 3.0
        gldm.offer_mission(m)
        gldm.accept_mission(m.id)
        gldm.pop_pending_mission_events()  # Drain

        # Tick past completion deadline
        for _ in range(31):
            gldm.tick_missions(0.0, 0.0, 0.1)

        assert m.status == "failed"
        events = gldm.pop_pending_mission_events()
        assert any(e["event"] == "mission_failed" for e in events)

    def test_decline_mission(self):
        """Declining mission records consequences."""
        fresh()
        m = _make_mission_with_objectives()
        m.decline_consequences = {"description": "Civilians lost."}
        gldm.offer_mission(m)

        result = gldm.decline_mission(m.id)
        assert result["ok"]
        assert result["consequences"]["description"] == "Civilians lost."
        assert m.status == "declined"


# ═══════════════════════════════════════════════════════════════════════════
# Multi-Objective Missions
# ═══════════════════════════════════════════════════════════════════════════


class TestMultiObjectiveMission:
    """Missions with mixed objective types."""

    def test_multi_objective_completion_order(self):
        """All required objectives must complete for mission success."""
        fresh()
        m = _make_mission_with_objectives(objectives=[
            MissionObjective(
                id="nav_1", description="Navigate to area",
                objective_type="navigate_to", target_position=(50000, 50000),
            ),
            MissionObjective(
                id="scan_1", description="Scan the target",
                objective_type="scan", target_id="target_vessel",
            ),
            MissionObjective(
                id="dock_1", description="Dock at station",
                objective_type="dock", target_id="station_rescue",
            ),
        ])
        gldm.offer_mission(m)
        gldm.accept_mission(m.id)

        # Complete navigate
        gldm.tick_missions(50000, 50000, 0.1)
        assert m.objectives[0].completed
        assert m.status in ("accepted", "active")

        # Complete scan
        gldm.notify_scan_completed("target_vessel")
        assert m.objectives[1].completed
        assert m.status in ("accepted", "active")

        # Complete dock — triggers mission completion
        gldm.tick_missions(50000, 50000, 0.1, docked_station_id="station_rescue")
        assert m.objectives[2].completed
        assert m.status == "completed"

    def test_optional_objective_not_required(self):
        """Mission completes even if optional objectives are not done."""
        fresh()
        m = _make_mission_with_objectives(objectives=[
            MissionObjective(
                id="nav_1", description="Navigate to area",
                objective_type="navigate_to", target_position=(50000, 50000),
            ),
            MissionObjective(
                id="bonus_1", description="Optional: scan debris",
                objective_type="scan", target_id="debris_field",
                optional=True,
            ),
        ])
        gldm.offer_mission(m)
        gldm.accept_mission(m.id)

        # Complete only the required objective
        gldm.tick_missions(50000, 50000, 0.1)
        assert m.objectives[0].completed
        assert not m.objectives[1].completed
        assert m.status == "completed"


# ═══════════════════════════════════════════════════════════════════════════
# Trap Mission
# ═══════════════════════════════════════════════════════════════════════════


class TestTrapMission:
    """Trap signals appear normal but have _is_trap flag."""

    def test_trap_flag_not_in_broadcast(self):
        """_is_trap is NOT visible in to_dict() (client-facing)."""
        fresh()
        m = _make_mission_with_objectives()
        m._is_trap = True
        gldm.offer_mission(m)

        d = m.to_dict()
        assert "_is_trap" not in d
        assert "is_trap" not in d

    def test_trap_flag_preserved_in_serialise(self):
        """_is_trap is preserved across serialise/deserialise."""
        fresh()
        m = _make_mission_with_objectives()
        m._is_trap = True
        gldm.offer_mission(m)

        state = gldm.serialise()
        gldm.reset()
        gldm.deserialise(state)

        restored = gldm.get_mission(m.id)
        assert restored is not None
        assert restored._is_trap is True


# ═══════════════════════════════════════════════════════════════════════════
# Multiple Simultaneous Missions
# ═══════════════════════════════════════════════════════════════════════════


class TestSimultaneousMissions:
    """Multiple missions active at the same time."""

    def test_multiple_active_missions(self):
        """Up to MAX_ACTIVE_MISSIONS can be active simultaneously."""
        fresh()
        missions = []
        for i in range(3):
            m = _make_mission_with_objectives(
                mission_id=f"dm_{i}",
                waypoint=(10000.0 * (i + 1), 20000.0),
            )
            gldm.offer_mission(m)
            gldm.accept_mission(m.id)
            missions.append(m)

        active = gldm.get_active_missions()
        assert len(active) == 3

    def test_max_active_blocks_new_offers(self):
        """Cannot offer beyond MAX_ACTIVE_MISSIONS active missions."""
        fresh()
        for i in range(3):
            m = _make_mission_with_objectives(mission_id=f"dm_{i}")
            gldm.offer_mission(m)
            gldm.accept_mission(m.id)

        # 4th mission should be rejected
        extra = _make_mission_with_objectives(mission_id="dm_extra")
        result = gldm.offer_mission(extra)
        assert result is False

    def test_independent_objective_tracking(self):
        """Each mission tracks its own objectives independently."""
        fresh()
        m1 = _make_mission_with_objectives(
            mission_id="dm_1",
            objectives=[MissionObjective(
                id="scan_a", description="Scan A",
                objective_type="scan", target_id="entity_a",
            )],
        )
        m2 = _make_mission_with_objectives(
            mission_id="dm_2",
            objectives=[MissionObjective(
                id="scan_b", description="Scan B",
                objective_type="scan", target_id="entity_b",
            )],
        )
        gldm.offer_mission(m1)
        gldm.offer_mission(m2)
        gldm.accept_mission(m1.id)
        gldm.accept_mission(m2.id)

        gldm.notify_scan_completed("entity_a")
        assert m1.objectives[0].completed
        assert not m2.objectives[0].completed


# ═══════════════════════════════════════════════════════════════════════════
# Reward Application
# ═══════════════════════════════════════════════════════════════════════════


class TestRewardApplication:
    """Mission completion applies rewards correctly."""

    def test_rewards_returned_on_completion(self):
        """Completing a mission returns rewards dict."""
        fresh()
        m = _make_mission_with_objectives(objectives=[
            MissionObjective(
                id="nav_1", description="Navigate",
                objective_type="navigate_to", target_position=(50000, 50000),
            ),
        ])
        m.rewards = MissionRewards(
            faction_standing={"civilian": 15.0, "imperial": -5.0},
            crew=3,
            supplies={"torpedoes": 2},
            reputation=10,
            description="Good job!",
        )
        gldm.offer_mission(m)
        gldm.accept_mission(m.id)
        gldm.pop_pending_mission_events()

        # Complete the navigate objective
        gldm.tick_missions(50000, 50000, 0.1)

        events = gldm.pop_pending_mission_events()
        completed = [e for e in events if e["event"] == "mission_completed"]
        assert len(completed) == 1
        rewards = completed[0]["rewards"]
        assert rewards["crew"] == 3
        assert rewards["reputation"] == 10
        assert rewards["faction_standing"]["civilian"] == 15.0

    def test_apply_rewards_helper(self):
        """apply_rewards() produces correct summary."""
        fresh()
        rewards = MissionRewards(
            faction_standing={"rebel": 5.0},
            supplies={"fuel": 10},
            crew=1,
            reputation=8,
        )
        summary = gldm.apply_rewards(rewards, {})
        assert summary["crew_gained"] == 1
        assert summary["reputation"] == 8
        assert summary["supplies"]["fuel"] == 10


# ═══════════════════════════════════════════════════════════════════════════
# Serialisation Round-Trip
# ═══════════════════════════════════════════════════════════════════════════


class TestSerialisationRoundTrip:
    """Full state survives serialise/deserialise cycle."""

    def test_active_missions_survive_roundtrip(self):
        """Active missions with partial objectives survive save/load."""
        fresh()
        m = _make_mission_with_objectives(objectives=[
            MissionObjective(
                id="nav_1", description="Navigate",
                objective_type="navigate_to", target_position=(50000, 50000),
            ),
            MissionObjective(
                id="destroy_1", description="Destroy",
                objective_type="destroy", target_id="enemy_1",
            ),
        ])
        gldm.offer_mission(m)
        gldm.accept_mission(m.id)

        # Complete first objective
        gldm.tick_missions(50000, 50000, 0.1, enemy_ids=frozenset({"enemy_1"}))
        assert m.objectives[0].completed
        assert not m.objectives[1].completed

        # Serialise and restore
        state = gldm.serialise()
        gldm.reset()
        gldm.deserialise(state)

        restored = gldm.get_mission(m.id)
        assert restored is not None
        assert restored.status in ("accepted", "active")
        assert restored.objectives[0].completed
        assert not restored.objectives[1].completed
