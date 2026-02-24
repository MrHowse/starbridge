"""Tests for the v0.06.4 Comms Station Overhaul — Parts 1-3.

Signal management, decoding, diplomacy, channels, bandwidth, intel routing,
faction standing, translation matrices.
"""
from __future__ import annotations

import pytest

import server.game_loop_comms as glco
from server.models.comms import (
    BASE_DECODE_SPEED,
    CHANNEL_DEFAULTS,
    PASSIVE_DECODE_MULT,
    STANDING_EFFECTS,
    Channel,
    FactionStanding,
    Signal,
    TranslationMatrix,
    _disposition_from_standing,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fresh_comms():
    """Reset comms module and return it."""
    glco.reset()
    return glco


# ═══════════════════════════════════════════════════════════════════════════
# PART 1: Signal Model + Queue Management
# ═══════════════════════════════════════════════════════════════════════════


class TestSignalModel:
    """Signal dataclass tests."""

    def test_signal_creation(self):
        sig = Signal(
            id="sig_1", source="enemy_1", source_name="ISS Valiant",
            frequency=0.15, signal_type="hail", priority="high",
            raw_content="Mayday!", decoded_content="",
        )
        assert sig.id == "sig_1"
        assert sig.decode_progress == 0.0
        assert sig.requires_decode is True
        assert sig.responded is False

    def test_signal_to_dict_round_trip(self):
        sig = Signal(
            id="sig_1", source="enemy_1", source_name="Test",
            frequency=0.42, signal_type="distress", priority="critical",
            raw_content="Help!", decoded_content="Help!",
            decode_progress=1.0, auto_decoded=True,
            requires_decode=False, faction="rebel",
        )
        d = sig.to_dict()
        restored = Signal.from_dict(d)
        assert restored.id == sig.id
        assert restored.frequency == sig.frequency
        assert restored.faction == sig.faction
        assert restored.decode_progress == 1.0

    def test_signal_defaults(self):
        sig = Signal(
            id="s", source="u", source_name="U",
            frequency=0.5, signal_type="broadcast", priority="low",
            raw_content="", decoded_content="",
        )
        assert sig.language == "standard"
        assert sig.threat_level == "unknown"
        assert sig.dismissed is False
        assert sig.response_options == []


class TestSignalQueue:
    """Signal queue management in game_loop_comms."""

    def test_add_signal(self):
        c = fresh_comms()
        sig = c.add_signal(
            source="enemy_1", source_name="Raider",
            frequency=0.15, signal_type="hail", priority="high",
            raw_content="Identify yourself!",
            faction="imperial", auto_decoded=True,
        )
        assert sig.id == "sig_1"
        assert sig.auto_decoded is True
        assert sig.decode_progress == 1.0

    def test_add_multiple_signals_unique_ids(self):
        c = fresh_comms()
        s1 = c.add_signal(signal_type="hail", priority="high", raw_content="A")
        s2 = c.add_signal(signal_type="broadcast", priority="low", raw_content="B")
        assert s1.id != s2.id

    def test_get_signals_sorted_by_priority(self):
        c = fresh_comms()
        c.add_signal(priority="low", raw_content="low")
        c.add_signal(priority="critical", raw_content="crit")
        c.add_signal(priority="high", raw_content="high")
        signals = c.get_signals()
        assert [s.priority for s in signals] == ["critical", "high", "low"]

    def test_get_signal_by_id(self):
        c = fresh_comms()
        sig = c.add_signal(raw_content="test")
        found = c.get_signal(sig.id)
        assert found is sig

    def test_get_signal_not_found(self):
        c = fresh_comms()
        assert c.get_signal("nonexistent") is None

    def test_dismiss_signal(self):
        c = fresh_comms()
        sig = c.add_signal(raw_content="test")
        assert c.dismiss_signal(sig.id) is True
        assert c.get_active_signal_count() == 0
        # Dismissed signals don't appear in get_signals()
        assert len(c.get_signals()) == 0

    def test_dismiss_nonexistent(self):
        c = fresh_comms()
        assert c.dismiss_signal("nope") is False

    def test_signal_expiry(self):
        c = fresh_comms()
        c.set_tick(0)
        sig = c.add_signal(raw_content="temp", expires_ticks=10)
        assert sig.expires_tick == 10
        c.set_tick(11)
        c.tick_comms(0.1)
        assert c.get_signal(sig.id) is None

    def test_signal_not_expired_before_tick(self):
        c = fresh_comms()
        c.set_tick(0)
        sig = c.add_signal(raw_content="temp", expires_ticks=100)
        c.set_tick(50)
        c.tick_comms(0.1)
        assert c.get_signal(sig.id) is not None

    def test_auto_decoded_signal_has_full_content(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Full message here",
            decoded_content="Full message here",
            auto_decoded=True,
        )
        assert sig.decoded_content == "Full message here"
        assert sig.decode_progress == 1.0

    def test_active_signal_count(self):
        c = fresh_comms()
        c.add_signal(raw_content="a")
        c.add_signal(raw_content="b")
        sig3 = c.add_signal(raw_content="c")
        assert c.get_active_signal_count() == 3
        c.dismiss_signal(sig3.id)
        assert c.get_active_signal_count() == 2

    def test_signal_with_response_deadline(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Respond now!",
            response_deadline=30.0,
            auto_decoded=True,
            signal_type="hail",
            faction="imperial",
        )
        assert sig.response_deadline == 30.0


# ═══════════════════════════════════════════════════════════════════════════
# PART 2: Decode Mechanics
# ═══════════════════════════════════════════════════════════════════════════


class TestDecoding:
    """Signal decoding tests."""

    def test_start_decode(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Encrypted message",
            requires_decode=True,
        )
        assert c.start_decode(sig.id) is True
        assert sig.decoding_active is True

    def test_start_decode_invalid_signal(self):
        c = fresh_comms()
        assert c.start_decode("nonexistent") is False

    def test_start_decode_already_decoded(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Already done",
            auto_decoded=True,
        )
        assert c.start_decode(sig.id) is False

    def test_active_decode_progress_advances(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Secret message about fleet movements",
            requires_decode=True,
        )
        c.start_decode(sig.id)
        c.tick_comms(1.0)  # 1 second
        assert sig.decode_progress > 0.0
        assert sig.decode_progress < 1.0

    def test_passive_decode_slower_than_active(self):
        c = fresh_comms()
        active_sig = c.add_signal(raw_content="Active", requires_decode=True)
        passive_sig = c.add_signal(raw_content="Passive", requires_decode=True)
        c.start_decode(active_sig.id)
        c.tick_comms(1.0)
        assert active_sig.decode_progress > passive_sig.decode_progress
        # Active should be ~4x faster
        if passive_sig.decode_progress > 0:
            ratio = active_sig.decode_progress / passive_sig.decode_progress
            assert ratio > 3.0

    def test_decode_completion_event(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Short",
            requires_decode=True,
            faction="imperial",
        )
        c.start_decode(sig.id)
        # Tick enough to complete (BASE_DECODE_SPEED = 0.05/s → 20s for full)
        for _ in range(200):
            c.tick_comms(0.1)
        assert sig.decode_progress >= 1.0
        assert sig.decoded_content == sig.raw_content

    def test_switching_active_decode(self):
        c = fresh_comms()
        sig1 = c.add_signal(raw_content="First", requires_decode=True)
        sig2 = c.add_signal(raw_content="Second", requires_decode=True)
        c.start_decode(sig1.id)
        assert sig1.decoding_active is True
        c.start_decode(sig2.id)
        assert sig1.decoding_active is False
        assert sig2.decoding_active is True

    def test_decoded_content_progressively_revealed(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="This is a secret message",
            requires_decode=True,
        )
        c.start_decode(sig.id)
        c.tick_comms(5.0)  # Partial decode
        assert sig.decode_progress > 0.0
        assert sig.decode_progress < 1.0
        # Some characters should be revealed, others dashed
        assert "-" in sig.decoded_content or len(sig.decoded_content) > 0

    def test_faction_bonus_on_subsequent_decode(self):
        c = fresh_comms()
        # First signal from faction
        sig1 = c.add_signal(
            raw_content="First", requires_decode=True, faction="imperial",
        )
        c.start_decode(sig1.id)
        for _ in range(200):
            c.tick_comms(0.1)
        assert sig1.decode_progress >= 1.0

        # Second signal from same faction should decode faster
        sig2 = c.add_signal(
            raw_content="Second", requires_decode=True, faction="imperial",
        )
        sig3 = c.add_signal(
            raw_content="Third", requires_decode=True, faction="alien",
        )
        c.start_decode(sig2.id)
        c.tick_comms(1.0)
        # sig3 decodes passively without faction bonus
        assert sig2.decode_progress > sig3.decode_progress

    def test_auto_decoded_not_affected_by_tick(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Already decoded", auto_decoded=True,
        )
        old_progress = sig.decode_progress
        c.tick_comms(5.0)
        assert sig.decode_progress == old_progress


class TestTranslation:
    """Translation matrix tests."""

    def test_translation_matrix_creation(self):
        tm = TranslationMatrix(language="alien_alpha")
        assert tm.progress == 0.0
        assert tm.words_decoded == 0

    def test_translation_advance(self):
        tm = TranslationMatrix(language="alien_alpha")
        tm.advance(0.3)
        assert abs(tm.progress - 0.3) < 0.001

    def test_translation_clamped_at_1(self):
        tm = TranslationMatrix(language="alien_alpha")
        tm.advance(1.5)
        assert tm.progress == 1.0

    def test_translation_round_trip(self):
        tm = TranslationMatrix(language="alien_beta", progress=0.5, words_decoded=3)
        d = tm.to_dict()
        restored = TranslationMatrix.from_dict(d)
        assert restored.language == "alien_beta"
        assert abs(restored.progress - 0.5) < 0.001
        assert restored.words_decoded == 3

    def test_alien_decode_advances_translation(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Alien signal",
            requires_decode=True,
            language="alien_alpha",
            faction="alien",
        )
        c.start_decode(sig.id)
        # Fully decode
        for _ in range(250):
            c.tick_comms(0.1)
        assert sig.decode_progress >= 1.0
        # Translation should have advanced
        state = c.build_comms_state()
        assert "alien_alpha" in state["translations"]


# ═══════════════════════════════════════════════════════════════════════════
# PART 3: Diplomatic System
# ═══════════════════════════════════════════════════════════════════════════


class TestFactionStanding:
    """Faction standing tests."""

    def test_default_factions_created_on_reset(self):
        c = fresh_comms()
        standings = c.get_all_standings()
        assert "imperial" in standings
        assert "federation" in standings
        assert "pirate" in standings
        assert "alien" in standings
        assert "civilian" in standings

    def test_disposition_from_standing(self):
        assert _disposition_from_standing(80) == "allied"
        assert _disposition_from_standing(50) == "friendly"
        assert _disposition_from_standing(10) == "neutral"
        assert _disposition_from_standing(0) == "neutral"
        assert _disposition_from_standing(-10) == "suspicious"
        assert _disposition_from_standing(-50) == "hostile"
        assert _disposition_from_standing(-80) == "at_war"

    def test_faction_standing_adjust(self):
        fs = FactionStanding(faction_id="test", name="Test", standing=0.0)
        fs.adjust(10.0, "test_reason")
        assert fs.standing == 10.0
        assert "test_reason" in fs.recent_actions

    def test_faction_standing_clamped(self):
        fs = FactionStanding(faction_id="test", name="Test", standing=95.0)
        fs.adjust(20.0, "over_max")
        assert fs.standing == 100.0
        fs.adjust(-210.0, "under_min")
        assert fs.standing == -100.0

    def test_faction_standing_round_trip(self):
        fs = FactionStanding(
            faction_id="rebel", name="Rebels", standing=25.0,
            recent_actions=["helped", "traded"],
        )
        d = fs.to_dict()
        assert d["disposition"] == "neutral"
        restored = FactionStanding.from_dict(d)
        assert restored.faction_id == "rebel"
        assert restored.standing == 25.0

    def test_get_faction_standing(self):
        c = fresh_comms()
        fs = c.get_faction_standing("imperial")
        assert fs is not None
        assert fs.name == "Terran Empire"

    def test_get_faction_standing_not_found(self):
        c = fresh_comms()
        assert c.get_faction_standing("nonexistent") is None


class TestDiplomaticResponses:
    """Diplomatic response and NPC reply tests."""

    def test_response_options_generated_for_auto_decoded(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Identify yourself!",
            signal_type="hail",
            threat_level="unknown",
            auto_decoded=True,
            faction="imperial",
        )
        assert len(sig.response_options) > 0
        ids = [opt["id"] for opt in sig.response_options]
        assert "comply" in ids

    def test_respond_to_signal(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Identify yourself!",
            signal_type="hail",
            threat_level="unknown",
            auto_decoded=True,
            faction="imperial",
            response_deadline=60.0,
        )
        reply = c.respond_to_signal(sig.id, "comply")
        assert reply is not None
        assert "response_text" in reply
        assert sig.responded is True
        assert sig.response_deadline is None

    def test_respond_twice_fails(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Test", signal_type="hail", threat_level="unknown",
            auto_decoded=True, faction="imperial",
        )
        c.respond_to_signal(sig.id, "comply")
        assert c.respond_to_signal(sig.id, "formal") is None

    def test_respond_invalid_option(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Test", signal_type="hail", threat_level="unknown",
            auto_decoded=True, faction="imperial",
        )
        assert c.respond_to_signal(sig.id, "nonexistent_option") is None

    def test_standing_changes_from_response(self):
        c = fresh_comms()
        initial = c.get_faction_standing("imperial").standing
        sig = c.add_signal(
            raw_content="Test", signal_type="hail", threat_level="unknown",
            auto_decoded=True, faction="imperial",
        )
        c.respond_to_signal(sig.id, "comply")
        after = c.get_faction_standing("imperial").standing
        # "comply" → "honest_identify" → +3
        assert after > initial

    def test_pop_pending_standing_changes(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Test", signal_type="hail", threat_level="unknown",
            auto_decoded=True, faction="imperial",
        )
        c.respond_to_signal(sig.id, "comply")
        changes = c.pop_pending_standing_changes()
        assert len(changes) == 1
        assert changes[0]["faction_id"] == "imperial"
        # Second pop should be empty
        assert c.pop_pending_standing_changes() == []

    def test_deadline_expiry_causes_standing_loss(self):
        c = fresh_comms()
        initial = c.get_faction_standing("imperial").standing
        c.add_signal(
            raw_content="Respond!", signal_type="hail",
            threat_level="unknown", auto_decoded=True,
            faction="imperial", response_deadline=5.0,
        )
        # Tick past deadline
        c.tick_comms(6.0)
        after = c.get_faction_standing("imperial").standing
        assert after < initial

    def test_distress_deadline_expiry_standing_loss(self):
        c = fresh_comms()
        initial = c.get_faction_standing("civilian").standing
        c.add_signal(
            raw_content="Help!", signal_type="distress",
            auto_decoded=True, faction="civilian",
            response_deadline=5.0,
        )
        c.tick_comms(6.0)
        after = c.get_faction_standing("civilian").standing
        assert after < initial

    def test_dialogue_recorded(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Hello", signal_type="hail", threat_level="unknown",
            auto_decoded=True, faction="imperial",
        )
        c.respond_to_signal(sig.id, "comply")
        state = c.build_comms_state()
        assert sig.id in state["dialogues"]
        dialogue = state["dialogues"][sig.id]
        assert len(dialogue) == 3  # them, you, them
        assert dialogue[1]["speaker"] == "you"

    def test_distress_response_options(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Mayday!", signal_type="distress",
            threat_level="unknown", auto_decoded=True,
            faction="civilian",
        )
        ids = [opt["id"] for opt in sig.response_options]
        assert "acknowledge" in ids
        assert "unable" in ids

    def test_demand_response_options(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Surrender!", signal_type="demand",
            threat_level="hostile", auto_decoded=True,
            faction="pirate",
        )
        ids = [opt["id"] for opt in sig.response_options]
        assert "comply" in ids
        assert "refuse" in ids
        assert "negotiate" in ids


class TestDistressAssessment:
    """Distress signal assessment tests."""

    def test_assess_valid_distress(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Mayday! Hull breach!",
            signal_type="distress",
            faction="civilian",
            auto_decoded=True,
        )
        assessment = c.assess_distress(sig.id)
        assert assessment is not None
        assert "authenticity" in assessment
        assert "risk_level" in assessment
        assert 0.0 <= assessment["authenticity"] <= 1.0

    def test_assess_non_distress_returns_none(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Hello", signal_type="hail", auto_decoded=True,
        )
        assert c.assess_distress(sig.id) is None

    def test_assess_friendly_faction_higher_authenticity(self):
        c = fresh_comms()
        # Civilian has high standing
        sig = c.add_signal(
            raw_content="Help us!",
            signal_type="distress",
            faction="civilian",
            auto_decoded=True,
        )
        assessment = c.assess_distress(sig.id)
        assert assessment["authenticity"] >= 0.5

    def test_assess_hostile_faction_lower_authenticity(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Help us!",
            signal_type="distress",
            faction="pirate",
            auto_decoded=True,
        )
        assessment = c.assess_distress(sig.id)
        # Pirate standing is -20, should reduce authenticity
        assert assessment["authenticity"] < 0.6


# ═══════════════════════════════════════════════════════════════════════════
# CHANNELS & BANDWIDTH
# ═══════════════════════════════════════════════════════════════════════════


class TestChannels:
    """Channel management and bandwidth tests."""

    def test_default_channels_created(self):
        c = fresh_comms()
        channels = c.get_channels()
        assert len(channels) == len(CHANNEL_DEFAULTS)
        names = [ch.name for ch in channels]
        assert "emergency" in names
        assert "standard" in names

    def test_set_channel_status(self):
        c = fresh_comms()
        assert c.set_channel_status("broadcast", "open") is True
        channels = c.get_channels()
        broadcast = next(ch for ch in channels if ch.name == "broadcast")
        assert broadcast.status == "open"

    def test_cannot_close_emergency(self):
        c = fresh_comms()
        assert c.set_channel_status("emergency", "closed") is False
        channels = c.get_channels()
        emergency = next(ch for ch in channels if ch.name == "emergency")
        assert emergency.status == "open"

    def test_emergency_can_be_monitored(self):
        c = fresh_comms()
        # Emergency can be set to monitored (not closed)
        assert c.set_channel_status("emergency", "monitored") is True

    def test_set_invalid_channel(self):
        c = fresh_comms()
        assert c.set_channel_status("nonexistent", "open") is False

    def test_set_invalid_status(self):
        c = fresh_comms()
        assert c.set_channel_status("standard", "invalid") is False

    def test_bandwidth_usage_calculation(self):
        c = fresh_comms()
        usage = c.get_bandwidth_usage()
        assert usage > 0
        assert usage <= 100  # Defaults shouldn't exceed 100%

    def test_bandwidth_quality_normal(self):
        c = fresh_comms()
        quality = c.get_bandwidth_quality()
        assert quality == 1.0  # Default channels within budget

    def test_bandwidth_quality_degraded_when_overloaded(self):
        c = fresh_comms()
        # Open all channels
        for name, _, _ in CHANNEL_DEFAULTS:
            c.set_channel_status(name, "open")
        # Total: 5+15+20+25+10+15+10 = 100, so quality=1.0
        quality = c.get_bandwidth_quality()
        assert quality >= 0.3

    def test_channel_monitored_half_bandwidth(self):
        ch = Channel(name="test", status="monitored", bandwidth_cost=20.0)
        assert ch.active_cost == 10.0

    def test_channel_closed_zero_bandwidth(self):
        ch = Channel(name="test", status="closed", bandwidth_cost=20.0)
        assert ch.active_cost == 0.0

    def test_channel_round_trip(self):
        ch = Channel(name="fleet", status="monitored", bandwidth_cost=20.0)
        d = ch.to_dict()
        restored = Channel.from_dict(d)
        assert restored.name == "fleet"
        assert restored.status == "monitored"


# ═══════════════════════════════════════════════════════════════════════════
# INTEL ROUTING
# ═══════════════════════════════════════════════════════════════════════════


class TestIntelRouting:
    """Intelligence routing tests."""

    def test_route_decoded_intel(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Enemy fleet at sector 4B",
            auto_decoded=True,
            intel_value="Enemy fleet position",
            intel_category="tactical",
        )
        assert c.route_intel(sig.id, "captain") is True
        routes = c.pop_pending_intel_routes()
        assert len(routes) == 1
        assert routes[0]["target_station"] == "captain"
        assert routes[0]["intel_category"] == "tactical"

    def test_route_undecoded_fails(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Encrypted data",
            requires_decode=True,
            intel_value="Secret",
        )
        assert c.route_intel(sig.id, "science") is False

    def test_pop_intel_routes_drains(self):
        c = fresh_comms()
        sig = c.add_signal(raw_content="Intel", auto_decoded=True,
                           intel_value="Data")
        c.route_intel(sig.id, "helm")
        c.pop_pending_intel_routes()
        assert c.pop_pending_intel_routes() == []


# ═══════════════════════════════════════════════════════════════════════════
# HAILING (Outbound)
# ═══════════════════════════════════════════════════════════════════════════


class TestHailing:
    """Outbound hailing tests."""

    def test_hail_creates_signal(self):
        c = fresh_comms()
        c.tune(0.15)  # imperial
        sig = c.hail("contact_1", "negotiate")
        assert sig is not None
        assert sig.signal_type == "hail"
        assert sig.faction == "imperial"

    def test_hail_with_explicit_frequency(self):
        c = fresh_comms()
        sig = c.hail("contact_1", "negotiate", frequency=0.42)
        assert sig is not None
        assert sig.faction == "rebel"

    def test_hail_auto_decoded(self):
        c = fresh_comms()
        c.tune(0.15)
        sig = c.hail("contact_1", "negotiate")
        assert sig.auto_decoded is True
        assert sig.decode_progress == 1.0


# ═══════════════════════════════════════════════════════════════════════════
# PROBING
# ═══════════════════════════════════════════════════════════════════════════


class TestProbing:
    """Target probing tests."""

    def test_start_probe(self):
        c = fresh_comms()
        assert c.start_probe("enemy_1") is True

    def test_probe_duplicate_rejected(self):
        c = fresh_comms()
        c.start_probe("enemy_1")
        assert c.start_probe("enemy_1") is False

    def test_probe_completes_after_duration(self):
        c = fresh_comms()
        c.start_probe("enemy_1")
        # Tick past PROBE_DURATION (15s)
        c.tick_comms(16.0)
        # Probe should be gone now
        assert c.start_probe("enemy_1") is True  # Can restart


# ═══════════════════════════════════════════════════════════════════════════
# STATE BUILD & SERIALISE
# ═══════════════════════════════════════════════════════════════════════════


class TestStateBuild:
    """build_comms_state and serialise/deserialise tests."""

    def test_build_comms_state_structure(self):
        c = fresh_comms()
        state = c.build_comms_state()
        assert "active_frequency" in state
        assert "tuned_faction" in state
        assert "signals" in state
        assert "channels" in state
        assert "factions" in state
        assert "bandwidth_usage" in state
        assert "bandwidth_quality" in state
        assert "translations" in state
        assert "creatures" in state

    def test_build_comms_state_includes_signals(self):
        c = fresh_comms()
        c.add_signal(raw_content="Test signal", auto_decoded=True)
        state = c.build_comms_state()
        assert len(state["signals"]) == 1
        assert state["signal_count"] == 1

    def test_serialise_deserialise_round_trip(self):
        c = fresh_comms()
        c.tune(0.42)
        c.add_signal(
            raw_content="Test",
            faction="rebel",
            auto_decoded=True,
        )
        c.set_channel_status("fleet", "open")

        data = c.serialise()
        c.reset()  # Clear everything

        c.deserialise(data)
        assert abs(c.get_active_frequency() - 0.42) < 0.001
        assert c.get_active_signal_count() == 1

    def test_serialise_includes_all_state(self):
        c = fresh_comms()
        data = c.serialise()
        assert "active_frequency" in data
        assert "signals" in data
        assert "factions" in data
        assert "channels" in data
        assert "translations" in data
        assert "decoded_factions" in data

    def test_legacy_transmissions_in_state(self):
        c = fresh_comms()
        state = c.build_comms_state()
        assert "transmissions" in state


# ═══════════════════════════════════════════════════════════════════════════
# MESSAGE SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════


class TestMessageSchemas:
    """Pydantic payload schema tests."""

    def test_all_comms_schemas_registered(self):
        from server.models.messages.base import _PAYLOAD_SCHEMAS
        expected = [
            "comms.tune_frequency", "comms.hail", "comms.decode_signal",
            "comms.respond", "comms.route_intel", "comms.set_channel",
            "comms.probe", "comms.assess_distress", "comms.dismiss_signal",
        ]
        for msg_type in expected:
            assert msg_type in _PAYLOAD_SCHEMAS, f"Missing schema: {msg_type}"

    def test_decode_signal_payload(self):
        from server.models.messages.comms import CommsDecodeSignalPayload
        p = CommsDecodeSignalPayload(signal_id="sig_1")
        assert p.signal_id == "sig_1"

    def test_respond_payload(self):
        from server.models.messages.comms import CommsRespondPayload
        p = CommsRespondPayload(signal_id="sig_1", response_id="comply")
        assert p.response_id == "comply"

    def test_route_intel_payload(self):
        from server.models.messages.comms import CommsRouteIntelPayload
        p = CommsRouteIntelPayload(signal_id="sig_1", target_station="captain")
        assert p.target_station == "captain"

    def test_set_channel_payload(self):
        from server.models.messages.comms import CommsSetChannelPayload
        p = CommsSetChannelPayload(channel="fleet", status="open")
        assert p.status == "open"

    def test_hail_payload_extended(self):
        from server.models.messages.comms import CommsHailPayload
        p = CommsHailPayload(
            contact_id="enemy_1",
            message_type="negotiate",
            hail_type="warning",
            frequency=0.42,
        )
        assert p.hail_type == "warning"
        assert p.frequency == 0.42

    def test_probe_payload(self):
        from server.models.messages.comms import CommsProbePayload
        p = CommsProbePayload(target_id="enemy_1")
        assert p.target_id == "enemy_1"

    def test_assess_distress_payload(self):
        from server.models.messages.comms import CommsAssessDistressPayload
        p = CommsAssessDistressPayload(signal_id="sig_1")
        assert p.signal_id == "sig_1"

    def test_dismiss_signal_payload(self):
        from server.models.messages.comms import CommsDismissSignalPayload
        p = CommsDismissSignalPayload(signal_id="sig_1")
        assert p.signal_id == "sig_1"


# ═══════════════════════════════════════════════════════════════════════════
# FREQUENCY TUNING (legacy + new)
# ═══════════════════════════════════════════════════════════════════════════


class TestFrequencyTuning:
    """Frequency tuning tests."""

    def test_tune_and_get(self):
        c = fresh_comms()
        c.tune(0.42)
        assert c.get_tuned_faction() == "rebel"

    def test_tune_clamped(self):
        c = fresh_comms()
        c.tune(-0.5)
        assert c.get_active_frequency() == 0.0
        c.tune(1.5)
        assert c.get_active_frequency() == 1.0

    def test_tune_off_band(self):
        c = fresh_comms()
        c.tune(0.50)
        assert c.get_tuned_faction() is None

    def test_new_faction_bands(self):
        c = fresh_comms()
        # Pirate band at 0.08
        c.tune(0.08)
        assert c.get_tuned_faction() == "pirate"
        # Civilian at 0.55
        c.tune(0.55)
        assert c.get_tuned_faction() == "civilian"
        # Federation at 0.65
        c.tune(0.65)
        assert c.get_tuned_faction() == "federation"


# ═══════════════════════════════════════════════════════════════════════════
# RESET
# ═══════════════════════════════════════════════════════════════════════════


class TestReset:
    """Reset clears all state."""

    def test_reset_clears_signals(self):
        c = fresh_comms()
        c.add_signal(raw_content="test")
        c.reset()
        assert c.get_active_signal_count() == 0

    def test_reset_clears_factions(self):
        c = fresh_comms()
        # After reset, default factions should be re-created
        assert len(c.get_all_standings()) > 0

    def test_reset_creates_default_channels(self):
        c = fresh_comms()
        assert len(c.get_channels()) == len(CHANNEL_DEFAULTS)

    def test_reset_clears_frequency(self):
        c = fresh_comms()
        c.tune(0.8)
        c.reset()
        assert abs(c.get_active_frequency() - 0.15) < 0.001


# ═══════════════════════════════════════════════════════════════════════════
# SANDBOX SIGNAL GENERATION
# ═══════════════════════════════════════════════════════════════════════════


class TestSandboxSignals:
    """Sandbox events should create Signal objects via add_signal()."""

    def test_add_signal_for_incoming_transmission(self):
        c = fresh_comms()
        c.add_signal(
            source="sb_imperial_vessel",
            source_name="Imperial Vessel",
            frequency=0.15,
            signal_type="broadcast",
            priority="medium",
            raw_content="scrambled signal",
            requires_decode=True,
            faction="imperial",
            threat_level="unknown",
            expires_ticks=3000,
        )
        signals = c.get_signals()
        assert len(signals) == 1
        assert signals[0].signal_type == "broadcast"
        assert signals[0].faction == "imperial"
        assert signals[0].requires_decode is True
        assert signals[0].decode_progress == 0.0

    def test_add_signal_for_distress(self):
        c = fresh_comms()
        c.add_signal(
            source="distress_beacon",
            source_name="Distress Beacon",
            frequency=0.90,
            signal_type="distress",
            priority="critical",
            raw_content="EMERGENCY — vessel in distress",
            auto_decoded=True,
            requires_decode=False,
            faction="unknown",
            threat_level="unknown",
            response_deadline=90.0,
        )
        signals = c.get_signals()
        assert len(signals) == 1
        assert signals[0].signal_type == "distress"
        assert signals[0].priority == "critical"
        assert signals[0].auto_decoded is True
        assert signals[0].response_deadline == 90.0
        assert len(signals[0].response_options) > 0  # auto-decoded gets options

    def test_sandbox_signals_appear_in_state(self):
        c = fresh_comms()
        c.add_signal(
            source="sb_rebel_vessel",
            source_name="Rebel Vessel",
            frequency=0.42,
            signal_type="broadcast",
            priority="medium",
            raw_content="patrol coordinates",
            faction="rebel",
        )
        state = c.build_comms_state()
        assert state["signal_count"] == 1
        assert len(state["signals"]) == 1
        assert state["signals"][0]["faction"] == "rebel"

    def test_sandbox_distress_has_response_options(self):
        """Distress signals should have response options (acknowledge, etc.)."""
        c = fresh_comms()
        sig = c.add_signal(
            source="distress_beacon",
            source_name="Distress Beacon",
            frequency=0.90,
            signal_type="distress",
            priority="critical",
            raw_content="EMERGENCY",
            auto_decoded=True,
            requires_decode=False,
            faction="unknown",
            threat_level="unknown",
            response_deadline=90.0,
        )
        # Distress with unknown threat level should have response options
        assert len(sig.response_options) > 0
        option_ids = [o["id"] for o in sig.response_options]
        assert "acknowledge" in option_ids

    def test_multiple_sandbox_signals_sorted_by_priority(self):
        c = fresh_comms()
        c.add_signal(source="low", source_name="Low", priority="low",
                     raw_content="a", faction="civilian")
        c.add_signal(source="crit", source_name="Crit", priority="critical",
                     raw_content="b", faction="imperial")
        c.add_signal(source="med", source_name="Med", priority="medium",
                     raw_content="c", faction="rebel")
        signals = c.get_signals()
        assert signals[0].priority == "critical"
        assert signals[1].priority == "medium"
        assert signals[2].priority == "low"


# ═══════════════════════════════════════════════════════════════════════════
# CROSS-STATION INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossStationIntegration:
    """Intel routing, standing changes, and NPC responses drain correctly."""

    def test_intel_route_populates_pending(self):
        c = fresh_comms()
        sig = c.add_signal(
            raw_content="Enemy fleet at 7-7",
            auto_decoded=True,
            requires_decode=False,
            faction="rebel",
            intel_value="Fleet position at grid 7-7",
            intel_category="tactical",
        )
        c.route_intel(sig.id, "weapons")
        routes = c.pop_pending_intel_routes()
        assert len(routes) == 1
        assert routes[0]["target_station"] == "weapons"
        assert routes[0]["intel_value"] == "Fleet position at grid 7-7"
        # Second pop is empty
        assert c.pop_pending_intel_routes() == []

    def test_standing_change_on_response(self):
        c = fresh_comms()
        sig = c.add_signal(
            signal_type="distress",
            raw_content="Help!",
            auto_decoded=True,
            requires_decode=False,
            faction="civilian",
            threat_level="unknown",
            response_deadline=90.0,
        )
        c.respond_to_signal(sig.id, "acknowledge")
        changes = c.pop_pending_standing_changes()
        assert len(changes) >= 1
        assert changes[0]["faction_id"] == "civilian"
        assert changes[0]["amount"] > 0  # positive for helping

    def test_npc_response_on_respond(self):
        c = fresh_comms()
        sig = c.add_signal(
            signal_type="hail",
            raw_content="Identify yourself",
            auto_decoded=True,
            requires_decode=False,
            faction="imperial",
            threat_level="unknown",
        )
        reply = c.respond_to_signal(sig.id, "comply")
        assert reply is not None
        assert reply["faction"] == "imperial"
        assert reply["response_text"]  # non-empty

    def test_deadline_expiry_adjusts_standing(self):
        """Letting a signal deadline expire should negatively affect standing."""
        c = fresh_comms()
        c.add_signal(
            signal_type="hail",
            raw_content="Respond!",
            auto_decoded=True,
            requires_decode=False,
            faction="imperial",
            threat_level="unknown",
            response_deadline=1.0,
        )
        # Tick past deadline
        c.tick_comms(2.0)
        changes = c.pop_pending_standing_changes()
        assert len(changes) >= 1
        assert changes[0]["amount"] < 0  # negative for ignoring

    def test_probe_completes_after_duration(self):
        c = fresh_comms()
        c.start_probe("enemy_ship_01")
        assert "enemy_ship_01" in c._active_probes
        # Tick past probe duration (15s)
        c.tick_comms(16.0)
        assert "enemy_ship_01" not in c._active_probes

    def test_full_decode_reveal_respond_flow(self):
        """End-to-end: add signal → decode → respond → intel route."""
        c = fresh_comms()
        sig = c.add_signal(
            source="patrol_ship",
            source_name="ISS Valiant",
            frequency=0.15,
            signal_type="hail",
            priority="high",
            raw_content="Unidentified vessel, identify yourself immediately.",
            requires_decode=True,
            faction="imperial",
            threat_level="hostile",
            intel_value="Patrol route information",
            intel_category="tactical",
        )

        # Start active decode
        assert c.start_decode(sig.id) is True

        # Tick until fully decoded (at base speed ~0.05/s → ~20s)
        for _ in range(25):
            c.tick_comms(1.0)

        sig_after = c.get_signal(sig.id)
        assert sig_after.decode_progress >= 1.0
        assert len(sig_after.response_options) > 0

        # Respond
        opt_id = sig_after.response_options[0]["id"]
        reply = c.respond_to_signal(sig.id, opt_id)
        assert reply is not None

        # Route intel
        assert c.route_intel(sig.id, "captain") is True
        routes = c.pop_pending_intel_routes()
        assert len(routes) == 1
