"""Tests for Comms-sourced intelligence contacts — v0.06.4 missions Part 1.

CommsContact model, contact creation from signals, progressive decode,
staleness/expiry, sensor merge, visibility filtering.
"""
from __future__ import annotations

import pytest

import server.game_loop_comms as glco
from server.models.comms import (
    CONTACT_SOURCE_CIVILIAN,
    CONTACT_SOURCE_DISTRESS,
    CONTACT_SOURCE_FLEET,
    CONTACT_SOURCE_INTERCEPT,
    CONTACT_SOURCE_NAVIGATION,
    CONTACT_SOURCE_STATION,
    CONTACT_SOURCE_TRAP,
    DECODE_CONTACT_THRESHOLD,
    DECODE_DETAIL_THRESHOLD,
    DECODE_POSITION_THRESHOLD,
    DEFAULT_CONTACT_EXPIRY_TICKS,
    STALENESS_DOWNGRADE_THRESHOLD,
    UNCERTAINTY_RADIUS_25,
    UNCERTAINTY_RADIUS_50,
    UNCERTAINTY_RADIUS_75,
    CommsContact,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fresh_comms():
    """Reset comms module and return it."""
    glco.reset()
    return glco


def _add_distress_signal(co, x=45200.0, y=83260.0, auto=True):
    """Add a distress signal with location data."""
    return co.add_signal(
        source="distress_beacon",
        source_name="ISS Valiant",
        frequency=0.90,
        signal_type="distress",
        priority="critical",
        raw_content=f"EMERGENCY — vessel in distress at ({int(x)}, {int(y)}).",
        decoded_content=f"EMERGENCY — vessel in distress at ({int(x)}, {int(y)}).",
        auto_decoded=auto,
        requires_decode=not auto,
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


def _add_intercept_signal(co, x=30000.0, y=50000.0, auto=False):
    """Add an enemy intercept signal (encrypted, requires decode)."""
    return co.add_signal(
        source="intercept_src",
        source_name="Imperial Fleet",
        frequency=0.15,
        signal_type="encrypted",
        priority="high",
        raw_content="Fleet movement detected — patrol heading sector 7.",
        decoded_content="",
        auto_decoded=auto,
        requires_decode=not auto,
        faction="imperial",
        threat_level="hostile",
        intel_value="Fleet position",
        intel_category="fleet",
        location_data={
            "type": "approximate",
            "position": [x, y],
            "radius": 10000.0,
            "entity_type": "fleet",
        },
    )


def _add_nav_broadcast(co, x=60000.0, y=70000.0, auto=True):
    """Add a navigation broadcast with hazard zone."""
    return co.add_signal(
        source="nav_beacon",
        source_name="Navigation Beacon",
        frequency=0.55,
        signal_type="broadcast",
        priority="medium",
        raw_content="NAVWARN: Asteroid field detected.",
        decoded_content="NAVWARN: Asteroid field detected.",
        auto_decoded=auto,
        requires_decode=not auto,
        faction="civilian",
        threat_level="neutral",
        intel_category="navigation",
        location_data={
            "type": "region",
            "position": [x, y],
            "radius": 12000.0,
            "entity_type": "hazard",
        },
    )


def _add_station_broadcast(co, x=50000.0, y=20000.0, auto=True):
    """Add a station broadcast signal."""
    return co.add_signal(
        source="station_alpha",
        source_name="Way Station Alpha",
        frequency=0.55,
        signal_type="broadcast",
        priority="low",
        raw_content="Way Station Alpha — docking services available.",
        decoded_content="Way Station Alpha — docking services available.",
        auto_decoded=auto,
        requires_decode=not auto,
        faction="civilian",
        threat_level="friendly",
        location_data={
            "type": "exact",
            "position": [x, y],
            "radius": 0.0,
            "entity_type": "station",
        },
    )


def _add_civilian_hail(co, x=40000.0, y=60000.0, auto=True):
    """Add a civilian ship hail."""
    return co.add_signal(
        source="mv_prospector",
        source_name="MV Prospector",
        frequency=0.55,
        signal_type="hail",
        priority="medium",
        raw_content="This is MV Prospector. Requesting escort.",
        decoded_content="This is MV Prospector. Requesting escort.",
        auto_decoded=auto,
        requires_decode=not auto,
        faction="civilian",
        threat_level="friendly",
        location_data={
            "type": "exact",
            "position": [x, y],
            "radius": 0.0,
            "entity_type": "ship",
        },
    )


def _tick_until(co, progress_target, dt=0.1):
    """Tick comms until the first signal's decode progress reaches target."""
    for _ in range(5000):
        co.tick_comms(dt, crew_factor=1.0)
        sigs = co.get_signals()
        if sigs and sigs[0].decode_progress >= progress_target:
            return
    raise TimeoutError(f"Signal didn't reach {progress_target} progress")


# ═══════════════════════════════════════════════════════════════════════════
# PART 1: CommsContact Model
# ═══════════════════════════════════════════════════════════════════════════


class TestCommsContactModel:
    """CommsContact dataclass tests."""

    def test_contact_creation(self):
        cc = CommsContact(
            id="cc_1",
            source_signal_id="sig_1",
            source_type=CONTACT_SOURCE_DISTRESS,
            position=(45200.0, 83260.0),
            position_accuracy="exact",
            position_radius=0.0,
            name="ISS Valiant",
            entity_type="ship",
            faction="civilian",
            threat_level="distress",
            confidence="confirmed",
        )
        assert cc.id == "cc_1"
        assert cc.position == (45200.0, 83260.0)
        assert cc.confidence == "confirmed"
        assert cc.merged_sensor_id is None

    def test_contact_to_dict_round_trip(self):
        cc = CommsContact(
            id="cc_2",
            source_signal_id="sig_5",
            source_type=CONTACT_SOURCE_INTERCEPT,
            position=(30000.0, 50000.0),
            position_accuracy="approximate",
            position_radius=10000.0,
            name="Imperial Fleet",
            entity_type="fleet",
            faction="imperial",
            threat_level="hostile",
            confidence="probable",
            staleness=45.0,
            last_updated_tick=100,
            icon="hostile",
            visible_to=["captain", "weapons"],
            expires_tick=3500,
        )
        d = cc.to_dict()
        restored = CommsContact.from_dict(d)
        assert restored.id == cc.id
        assert restored.position == cc.position
        assert restored.position_radius == cc.position_radius
        assert restored.confidence == cc.confidence
        assert restored.visible_to == ["captain", "weapons"]
        assert restored.expires_tick == 3500

    def test_contact_defaults(self):
        cc = CommsContact(
            id="cc_3",
            source_signal_id="sig_1",
            source_type=CONTACT_SOURCE_DISTRESS,
            position=(0.0, 0.0),
            position_accuracy="exact",
            position_radius=0.0,
            name="Test",
            entity_type="ship",
            faction="unknown",
            threat_level="unknown",
            confidence="unverified",
        )
        assert cc.staleness == 0.0
        assert cc.mission_id is None
        assert cc.merged_sensor_id is None
        assert cc.decode_progress == 1.0
        assert cc._is_trap is False
        assert cc.assessment is None

    def test_trap_flag_not_in_dict(self):
        cc = CommsContact(
            id="cc_4",
            source_signal_id="sig_1",
            source_type=CONTACT_SOURCE_TRAP,
            position=(10000.0, 20000.0),
            position_accuracy="exact",
            position_radius=0.0,
            name="Fake Distress",
            entity_type="ship",
            faction="pirate",
            threat_level="distress",
            confidence="confirmed",
            _is_trap=True,
        )
        d = cc.to_dict()
        # _is_trap should NOT be in the broadcast dict
        assert "_is_trap" not in d


# ═══════════════════════════════════════════════════════════════════════════
# PART 2: Contact Creation from Signals
# ═══════════════════════════════════════════════════════════════════════════


class TestDistressContact:
    """Distress signal creates a contact at the correct position."""

    def test_distress_creates_contact(self):
        co = fresh_comms()
        _add_distress_signal(co, x=45200.0, y=83260.0)
        contacts = co.get_comms_contacts()
        assert len(contacts) == 1
        cc = contacts[0]
        assert cc.position == (45200.0, 83260.0)
        assert cc.position_accuracy == "exact"
        assert cc.position_radius == 0.0
        assert cc.entity_type == "ship"
        assert cc.threat_level == "distress"
        assert cc.confidence == "confirmed"
        assert cc.icon == "distress"

    def test_distress_visible_to_correct_stations(self):
        co = fresh_comms()
        _add_distress_signal(co)
        cc = co.get_comms_contacts()[0]
        assert "captain" in cc.visible_to
        assert "helm" in cc.visible_to
        assert "science" in cc.visible_to
        assert "weapons" in cc.visible_to

    def test_distress_contact_has_source_signal(self):
        co = fresh_comms()
        sig = _add_distress_signal(co)
        cc = co.get_comms_contacts()[0]
        assert cc.source_signal_id == sig.id

    def test_distress_contact_expiry(self):
        co = fresh_comms()
        co.set_tick(100)
        _add_distress_signal(co)
        cc = co.get_comms_contacts()[0]
        assert cc.expires_tick is not None


class TestInterceptContact:
    """Enemy intercept creates an approximate contact."""

    def test_intercept_creates_approximate_contact(self):
        co = fresh_comms()
        sig = _add_intercept_signal(co, auto=True)
        contacts = co.get_comms_contacts()
        assert len(contacts) == 1
        cc = contacts[0]
        assert cc.position_accuracy == "approximate"
        assert cc.position_radius >= 5000.0
        assert cc.entity_type == "fleet"
        assert cc.confidence == "probable"
        assert cc.icon == "hostile"

    def test_intercept_visible_to_tactical(self):
        co = fresh_comms()
        _add_intercept_signal(co, auto=True)
        cc = co.get_comms_contacts()[0]
        assert "captain" in cc.visible_to
        assert "weapons" in cc.visible_to


class TestNavigationContact:
    """Navigation broadcast creates a hazard region."""

    def test_nav_broadcast_creates_region(self):
        co = fresh_comms()
        _add_nav_broadcast(co)
        contacts = co.get_comms_contacts()
        assert len(contacts) == 1
        cc = contacts[0]
        assert cc.position_accuracy == "region"
        assert cc.position_radius >= 10000.0
        assert cc.entity_type == "hazard"
        assert cc.confidence == "confirmed"
        assert cc.icon == "hazard"

    def test_nav_visible_to_helm(self):
        co = fresh_comms()
        _add_nav_broadcast(co)
        cc = co.get_comms_contacts()[0]
        assert "helm" in cc.visible_to
        assert "science" in cc.visible_to
        assert "captain" in cc.visible_to


class TestStationContact:
    """Station broadcast creates an exact station contact."""

    def test_station_broadcast_creates_exact_contact(self):
        co = fresh_comms()
        _add_station_broadcast(co)
        contacts = co.get_comms_contacts()
        assert len(contacts) == 1
        cc = contacts[0]
        assert cc.position == (50000.0, 20000.0)
        assert cc.position_accuracy == "exact"
        assert cc.entity_type == "station"
        assert cc.confidence == "confirmed"


class TestCivilianContact:
    """Civilian hail creates a ship contact."""

    def test_civilian_hail_creates_ship_contact(self):
        co = fresh_comms()
        _add_civilian_hail(co)
        contacts = co.get_comms_contacts()
        assert len(contacts) == 1
        cc = contacts[0]
        assert cc.entity_type == "ship"
        assert cc.threat_level == "friendly"
        assert cc.name == "MV Prospector"

    def test_civilian_visible_to_all_map_stations(self):
        co = fresh_comms()
        _add_civilian_hail(co)
        cc = co.get_comms_contacts()[0]
        assert "captain" in cc.visible_to
        assert "helm" in cc.visible_to
        assert "comms" in cc.visible_to


class TestTrapContact:
    """Trap signal creates a normal-looking contact."""

    def test_trap_looks_like_distress(self):
        co = fresh_comms()
        co.add_signal(
            source="pirate_lure",
            source_name="Distress Beacon",
            frequency=0.90,
            signal_type="distress",
            priority="critical",
            raw_content="MAYDAY! Under attack!",
            decoded_content="MAYDAY! Under attack!",
            auto_decoded=True,
            requires_decode=False,
            faction="unknown",
            threat_level="unknown",
            location_data={
                "type": "exact",
                "position": [55000.0, 55000.0],
                "radius": 0.0,
                "entity_type": "ship",
                "is_trap": True,
            },
        )
        contacts = co.get_comms_contacts()
        assert len(contacts) == 1
        cc = contacts[0]
        # Looks normal from the outside
        assert cc.icon == "distress"
        assert cc.threat_level == "distress"
        # But server knows it's a trap
        assert cc._is_trap is True


# ═══════════════════════════════════════════════════════════════════════════
# PART 3: Partial Decode → Progressive Contact
# ═══════════════════════════════════════════════════════════════════════════


class TestPartialDecodeContact:
    """Partial decode creates a contact that becomes more precise."""

    def test_no_contact_below_25_percent(self):
        co = fresh_comms()
        sig = _add_intercept_signal(co, auto=False)
        co.start_decode(sig.id)
        # Tick a tiny amount (progress ≈ 0.5% — well below 25%)
        co.tick_comms(0.1, crew_factor=1.0)
        assert len(co.get_comms_contacts()) == 0

    def test_contact_appears_at_25_percent(self):
        co = fresh_comms()
        sig = _add_intercept_signal(co, auto=False)
        co.start_decode(sig.id)
        _tick_until(co, DECODE_CONTACT_THRESHOLD)
        contacts = co.get_comms_contacts()
        assert len(contacts) == 1
        cc = contacts[0]
        assert cc.position_radius == UNCERTAINTY_RADIUS_25

    def test_uncertainty_narrows_at_50_percent(self):
        co = fresh_comms()
        sig = _add_intercept_signal(co, auto=False)
        co.start_decode(sig.id)
        _tick_until(co, DECODE_POSITION_THRESHOLD)
        cc = co.get_comms_contacts()[0]
        assert cc.position_radius <= UNCERTAINTY_RADIUS_50

    def test_details_at_75_percent(self):
        co = fresh_comms()
        sig = _add_intercept_signal(co, auto=False)
        co.start_decode(sig.id)
        _tick_until(co, DECODE_DETAIL_THRESHOLD)
        cc = co.get_comms_contacts()[0]
        assert cc.position_radius <= UNCERTAINTY_RADIUS_75
        assert cc.name == "Imperial Fleet"

    def test_full_decode_finalises_contact(self):
        co = fresh_comms()
        sig = _add_intercept_signal(co, auto=False)
        co.start_decode(sig.id)
        _tick_until(co, 1.0)
        cc = co.get_comms_contacts()[0]
        assert cc.decode_progress == 1.0

    def test_signal_without_location_creates_no_contact(self):
        co = fresh_comms()
        co.add_signal(
            source="unknown",
            source_name="Unknown",
            signal_type="broadcast",
            priority="low",
            raw_content="General broadcast",
            decoded_content="General broadcast",
            auto_decoded=True,
            requires_decode=False,
            # No location_data
        )
        assert len(co.get_comms_contacts()) == 0


# ═══════════════════════════════════════════════════════════════════════════
# PART 4: Staleness and Expiry
# ═══════════════════════════════════════════════════════════════════════════


class TestContactStaleness:
    """Contact staleness increases and downgrades confidence."""

    def test_staleness_increases(self):
        co = fresh_comms()
        _add_intercept_signal(co, auto=True)
        cc = co.get_comms_contacts()[0]
        assert cc.staleness == 0.0

        # Tick 10 seconds
        for _ in range(100):
            co.tick_comms(0.1, crew_factor=1.0)
        cc = co.get_comms_contacts()[0]
        assert cc.staleness > 9.0

    def test_probable_downgrades_to_unverified(self):
        co = fresh_comms()
        _add_intercept_signal(co, auto=True)
        cc = co.get_comms_contacts()[0]
        assert cc.confidence == "probable"

        # Tick past the staleness threshold
        for _ in range(int(STALENESS_DOWNGRADE_THRESHOLD / 0.1) + 10):
            co.tick_comms(0.1, crew_factor=1.0)
        cc = co.get_comms_contacts()[0]
        assert cc.confidence == "unverified"

    def test_confirmed_does_not_downgrade(self):
        co = fresh_comms()
        _add_distress_signal(co)
        cc = co.get_comms_contacts()[0]
        assert cc.confidence == "confirmed"

        # Tick a lot — confirmed should not auto-downgrade
        for _ in range(int(STALENESS_DOWNGRADE_THRESHOLD / 0.1) + 10):
            co.tick_comms(0.1, crew_factor=1.0)
        cc = co.get_comms_contacts()[0]
        assert cc.confidence == "confirmed"

    def test_contact_expires(self):
        co = fresh_comms()
        co.set_tick(0)
        sig = co.add_signal(
            source="test",
            source_name="Expiring Contact",
            signal_type="distress",
            priority="medium",
            raw_content="Help!",
            decoded_content="Help!",
            auto_decoded=True,
            requires_decode=False,
            expires_ticks=100,  # expires at tick 100
            location_data={
                "type": "exact",
                "position": [10000.0, 20000.0],
                "radius": 0.0,
            },
        )
        assert len(co.get_comms_contacts()) == 1

        # Advance past expiry
        co.set_tick(101)
        co.tick_comms(0.1, crew_factor=1.0)
        assert len(co.get_comms_contacts()) == 0

    def test_merged_contact_does_not_age(self):
        co = fresh_comms()
        _add_distress_signal(co, x=45000.0, y=83000.0)
        cc = co.get_comms_contacts()[0]
        # Simulate sensor merge
        co.merge_with_sensor(cc.id, "enemy_1")

        for _ in range(int(STALENESS_DOWNGRADE_THRESHOLD / 0.1) + 10):
            co.tick_comms(0.1, crew_factor=1.0)
        cc = co.get_comms_contacts()[0]
        assert cc.staleness == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# PART 5: Sensor Merge
# ═══════════════════════════════════════════════════════════════════════════


class TestSensorMerge:
    """Comms contact merges with sensor-detected entity."""

    def test_merge_updates_contact(self):
        co = fresh_comms()
        _add_distress_signal(co, x=45200.0, y=83260.0)
        cc = co.get_comms_contacts()[0]
        result = co.merge_with_sensor(cc.id, "enemy_42")
        assert result is True
        cc = co.get_comms_contacts()[0]
        assert cc.merged_sensor_id == "enemy_42"
        assert cc.confidence == "confirmed"
        assert cc.position_accuracy == "exact"
        assert cc.position_radius == 0.0

    def test_cannot_merge_twice(self):
        co = fresh_comms()
        _add_distress_signal(co)
        cc = co.get_comms_contacts()[0]
        co.merge_with_sensor(cc.id, "enemy_1")
        result = co.merge_with_sensor(cc.id, "enemy_2")
        assert result is False

    def test_try_merge_by_proximity(self):
        co = fresh_comms()
        _add_distress_signal(co, x=45200.0, y=83260.0)
        sensor_contacts = [
            {"id": "enemy_1", "x": 45300.0, "y": 83200.0},  # within range
        ]
        events = co.try_merge_contacts_with_sensors(sensor_contacts)
        assert len(events) == 1
        assert events[0]["sensor_entity_id"] == "enemy_1"
        cc = co.get_comms_contacts()[0]
        assert cc.merged_sensor_id == "enemy_1"
        # Position updated to sensor data
        assert cc.position == (45300.0, 83200.0)

    def test_no_merge_when_too_far(self):
        co = fresh_comms()
        _add_distress_signal(co, x=10000.0, y=10000.0)
        sensor_contacts = [
            {"id": "enemy_1", "x": 90000.0, "y": 90000.0},  # very far
        ]
        events = co.try_merge_contacts_with_sensors(sensor_contacts)
        assert len(events) == 0

    def test_merge_generates_event(self):
        co = fresh_comms()
        _add_distress_signal(co, x=45200.0, y=83260.0)
        co.merge_with_sensor(co.get_comms_contacts()[0].id, "enemy_1")
        updates = co.pop_pending_contact_updates()
        # Should have: "new" (from creation) + "merged" (from merge)
        assert any(u["event"] == "merged" for u in updates)


# ═══════════════════════════════════════════════════════════════════════════
# PART 6: Role-Filtered Contact Access
# ═══════════════════════════════════════════════════════════════════════════


class TestRoleFiltering:
    """Contacts are filtered by station role visibility."""

    def test_captain_sees_all(self):
        co = fresh_comms()
        _add_distress_signal(co)
        _add_civilian_hail(co)
        _add_nav_broadcast(co)
        captain_contacts = co.get_comms_contacts_for_role("captain")
        assert len(captain_contacts) == 3

    def test_comms_sees_civilian_and_station(self):
        co = fresh_comms()
        _add_distress_signal(co)
        _add_civilian_hail(co)
        _add_station_broadcast(co)
        comms_contacts = co.get_comms_contacts_for_role("comms")
        # Comms sees civilian hail + station broadcast, NOT distress
        assert len(comms_contacts) == 2

    def test_weapons_sees_intercept(self):
        co = fresh_comms()
        _add_intercept_signal(co, auto=True)
        weapons_contacts = co.get_comms_contacts_for_role("weapons")
        assert len(weapons_contacts) == 1


# ═══════════════════════════════════════════════════════════════════════════
# PART 7: Serialise / Deserialise
# ═══════════════════════════════════════════════════════════════════════════


class TestContactSerialisation:
    """Contacts survive save/load round-trip."""

    def test_contacts_serialise(self):
        co = fresh_comms()
        _add_distress_signal(co)
        _add_intercept_signal(co, auto=True)
        data = co.serialise()
        assert "comms_contacts" in data
        assert len(data["comms_contacts"]) == 2

    def test_contacts_deserialise(self):
        co = fresh_comms()
        _add_distress_signal(co, x=12345.0, y=67890.0)
        data = co.serialise()

        co.reset()
        assert len(co.get_comms_contacts()) == 0
        co.deserialise(data)
        contacts = co.get_comms_contacts()
        assert len(contacts) == 1
        assert contacts[0].position == (12345.0, 67890.0)
        assert contacts[0].name == "ISS Valiant"

    def test_signal_contact_map_survives(self):
        co = fresh_comms()
        sig = _add_distress_signal(co)
        data = co.serialise()
        assert sig.id in data["signal_contact_map"]

        co.reset()
        co.deserialise(data)
        assert sig.id in data["signal_contact_map"]


# ═══════════════════════════════════════════════════════════════════════════
# PART 8: Contact Removal
# ═══════════════════════════════════════════════════════════════════════════


class TestContactRemoval:
    """Removing contacts cleans up state."""

    def test_remove_contact(self):
        co = fresh_comms()
        _add_distress_signal(co)
        cc = co.get_comms_contacts()[0]
        result = co.remove_comms_contact(cc.id)
        assert result is True
        assert len(co.get_comms_contacts()) == 0

    def test_remove_nonexistent(self):
        co = fresh_comms()
        result = co.remove_comms_contact("cc_999")
        assert result is False


# ═══════════════════════════════════════════════════════════════════════════
# PART 9: Pending Update Events
# ═══════════════════════════════════════════════════════════════════════════


class TestPendingUpdates:
    """Contact creation/update events are queued for broadcast."""

    def test_new_contact_emits_event(self):
        co = fresh_comms()
        _add_distress_signal(co)
        updates = co.pop_pending_contact_updates()
        assert len(updates) == 1
        assert updates[0]["event"] == "new"
        assert "contact" in updates[0]

    def test_pop_clears_queue(self):
        co = fresh_comms()
        _add_distress_signal(co)
        co.pop_pending_contact_updates()
        assert len(co.pop_pending_contact_updates()) == 0

    def test_stale_event_emitted(self):
        co = fresh_comms()
        _add_intercept_signal(co, auto=True)
        co.pop_pending_contact_updates()  # drain "new" event

        for _ in range(int(STALENESS_DOWNGRADE_THRESHOLD / 0.1) + 10):
            co.tick_comms(0.1, crew_factor=1.0)
        updates = co.pop_pending_contact_updates()
        assert any(u["event"] == "stale" for u in updates)


# ═══════════════════════════════════════════════════════════════════════════
# PART 10: Build Comms State Includes Contacts
# ═══════════════════════════════════════════════════════════════════════════


class TestCommsStateInclusion:
    """build_comms_state() includes comms contacts."""

    def test_comms_state_has_contacts(self):
        co = fresh_comms()
        _add_distress_signal(co)
        state = co.build_comms_state()
        assert "comms_contacts" in state
        assert len(state["comms_contacts"]) == 1
        assert state["comms_contacts"][0]["name"] == "ISS Valiant"
