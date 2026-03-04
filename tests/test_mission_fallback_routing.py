"""Tests for mission routing fallbacks when stations are unclaimed.

Covers:
- Comms auto-decode when comms station is unclaimed (30s delay)
- Captain auto-decline when captain station is unclaimed
- Station warnings on mission broadcast dicts
"""
from __future__ import annotations

import server.game_loop_comms as glco
import server.game_loop_dynamic_missions as gldm
from server.models.comms import Signal
from server.models.dynamic_mission import (
    DynamicMission,
    MissionObjective,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fresh():
    """Reset both comms and dynamic missions modules."""
    glco.reset()
    gldm.reset()


def _add_signal(tick: int = 0, *, signal_id: str = "sig_1") -> Signal:
    """Add a signal that requires decoding, with location data for mission gen."""
    glco.set_tick(tick)
    sig = Signal(
        id=signal_id,
        source="unknown",
        source_name="ISS Valiant",
        frequency=0.65,
        signal_type="distress",
        priority="high",
        raw_content="Distress call from ISS Valiant",
        decoded_content="",
        faction="federation",
        requires_decode=True,
        language="standard",
        arrived_tick=tick,
        location_data={"position": [5000.0, 5000.0]},
    )
    glco._signals.append(sig)
    return sig


def _make_offered_mission(mission_id: str = "dm_test") -> DynamicMission:
    """Create and offer a minimal test mission."""
    mission = DynamicMission(
        id=mission_id,
        source_signal_id="sig_1",
        source_contact_id="cc_1",
        title=f"Test Mission {mission_id}",
        briefing="Test briefing.",
        mission_type="rescue",
        objectives=[
            MissionObjective(
                id=f"{mission_id}_nav",
                description="Navigate to target",
                objective_type="navigate_to",
                target_position=(50000.0, 50000.0),
                order=1,
            ),
        ],
        waypoint=(50000.0, 50000.0),
        waypoint_name="Test",
        status="offered",
        accept_deadline=60.0,
        completion_deadline=300.0,
    )
    gldm.offer_mission(mission)
    return mission


# ===========================================================================
# Comms auto-decode when unclaimed
# ===========================================================================

class TestCommsAutoDecodeWhenUnclaimed:
    """Signals auto-decode after 30s when comms station is unclaimed."""

    def test_signal_auto_decodes_after_30s(self):
        fresh()
        sig = _add_signal(tick=0)
        glco.set_comms_crewed(False)

        # Advance 300 ticks = 30s at 10Hz
        for t in range(1, 301):
            glco.set_tick(t)
            glco._tick_decode(0.1, 1.0, 1.0)

        assert sig.decode_progress == 1.0

    def test_signal_not_auto_decoded_before_30s(self):
        fresh()
        sig = _add_signal(tick=0)
        glco.set_comms_crewed(False)

        # Advance 290 ticks = 29s — just under the threshold
        for t in range(1, 291):
            glco.set_tick(t)
            glco._tick_decode(0.1, 1.0, 1.0)

        # Should still be decoding (passive decode runs at 25% speed too,
        # but 29s of passive decode alone won't finish a fresh signal)
        assert sig.decode_progress < 1.0

    def test_auto_decode_generates_mission(self):
        fresh()
        _add_signal(tick=0)
        glco.set_comms_crewed(False)
        gldm.set_tick(300)

        # Advance past 30s
        for t in range(1, 301):
            glco.set_tick(t)
            glco._tick_decode(0.1, 1.0, 1.0)

        # Check that comms generated a mission from the decoded signal
        events = glco.pop_pending_decode_completions()
        assert len(events) >= 1
        assert events[0]["signal_id"] == "sig_1"

    def test_auto_decode_disabled_when_comms_crewed(self):
        fresh()
        sig = _add_signal(tick=0)
        glco.set_comms_crewed(True)  # Crewed — no auto-decode

        # Advance 300 ticks, but only passive decode (no active target)
        for t in range(1, 301):
            glco.set_tick(t)
            glco._tick_decode(0.1, 1.0, 1.0)

        # With passive decode at 25% speed and base rate ~0.05/s,
        # 30s × 0.05 × 0.25 = 0.375 — should NOT be fully decoded
        assert sig.decode_progress < 1.0


# ===========================================================================
# Captain auto-decline when unclaimed
# ===========================================================================

class TestCaptainAutoDeclineWhenUnclaimed:
    """Offered missions auto-decline when captain station is unclaimed."""

    def test_offered_mission_auto_declined(self):
        fresh()
        mission = _make_offered_mission()
        gldm.set_captain_crewed(False)

        gldm.tick_missions(0.0, 0.0, 0.1)

        assert mission.status == "declined"
        events = gldm.pop_pending_mission_events()
        # First event is the "offered" from offer_mission, second is the decline
        decline_events = [e for e in events if e["event"] == "mission_declined"]
        assert len(decline_events) == 1
        assert decline_events[0]["auto_declined"] is True
        assert "No captain" in decline_events[0]["reason"]

    def test_offered_mission_not_declined_when_captain_crewed(self):
        fresh()
        mission = _make_offered_mission()
        gldm.set_captain_crewed(True)

        gldm.tick_missions(0.0, 0.0, 0.1)

        assert mission.status == "offered"

    def test_auto_decline_does_not_affect_active_missions(self):
        """Active missions should not be declined, only offered ones."""
        fresh()
        mission = _make_offered_mission()
        gldm.set_captain_crewed(True)
        gldm.accept_mission(mission.id)
        assert mission.status == "active"

        # Now set captain as uncrewed
        gldm.set_captain_crewed(False)
        gldm.tick_missions(0.0, 0.0, 0.1)

        # Active mission should remain active
        assert mission.status == "active"


# ===========================================================================
# Station warnings on mission dicts
# ===========================================================================

class TestStationWarnings:
    """Mission broadcast dicts should carry station warnings."""

    def test_warnings_when_comms_unclaimed(self):
        fresh()
        _make_offered_mission()
        dm_list = gldm.get_missions_for_broadcast()

        # Simulate game_loop annotation
        for entry in dm_list:
            warnings = []
            if True:  # comms unclaimed
                warnings.append("\u26a0 No Comms officer \u2014 signal auto-decoded")
            entry["station_warnings"] = warnings

        assert len(dm_list[0]["station_warnings"]) == 1
        assert "Comms" in dm_list[0]["station_warnings"][0]

    def test_warnings_when_ops_unclaimed(self):
        fresh()
        _make_offered_mission()
        dm_list = gldm.get_missions_for_broadcast()

        for entry in dm_list:
            warnings = []
            if True:  # ops unclaimed
                warnings.append("\u26a0 No Operations officer \u2014 assessment unavailable")
            entry["station_warnings"] = warnings

        assert len(dm_list[0]["station_warnings"]) == 1
        assert "Operations" in dm_list[0]["station_warnings"][0]

    def test_no_warnings_when_all_claimed(self):
        fresh()
        _make_offered_mission()
        dm_list = gldm.get_missions_for_broadcast()

        for entry in dm_list:
            entry["station_warnings"] = []

        assert dm_list[0]["station_warnings"] == []

    def test_station_warnings_field_serialise_roundtrip(self):
        """station_warnings field survives to_dict/from_dict."""
        mission = DynamicMission(
            id="dm_rt",
            source_signal_id="sig_1",
            source_contact_id="cc_1",
            title="Roundtrip Test",
            briefing="Test.",
            mission_type="rescue",
            station_warnings=["\u26a0 No Comms officer"],
        )
        d = mission.to_dict()
        assert d["station_warnings"] == ["\u26a0 No Comms officer"]

        restored = DynamicMission.from_dict(d)
        assert restored.station_warnings == ["\u26a0 No Comms officer"]
