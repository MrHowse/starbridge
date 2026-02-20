"""
Tests for the beam frequency matching system (P3 — Gap Closure).

Enemies spawn with a random shield_frequency (alpha/beta/gamma/delta).
Player beams set to the matching frequency deal 1.5× damage; mismatched
deal 0.5×. No frequency specified → 1.0× (neutral).
"""
from __future__ import annotations

import pytest

from server.models.world import Enemy, spawn_enemy
from server.systems.combat import (
    FREQ_MATCH_MULT,
    FREQ_MISMATCH_MULT,
    apply_hit_to_enemy,
)
from server.systems.sensors import build_scan_result


# ---------------------------------------------------------------------------
# Enemy spawn
# ---------------------------------------------------------------------------


class TestEnemyShieldFrequency:
    """Enemy dataclass carries shield_frequency."""

    def test_enemy_has_shield_frequency_field(self):
        e = Enemy(id="e1", type="scout", x=0, y=0)
        assert hasattr(e, "shield_frequency")

    def test_default_shield_frequency_is_empty(self):
        e = Enemy(id="e1", type="scout", x=0, y=0)
        assert e.shield_frequency == ""

    def test_spawn_enemy_assigns_frequency(self):
        """spawn_enemy should set a non-empty shield_frequency."""
        e = spawn_enemy("scout", 0.0, 0.0, "e1")
        assert e.shield_frequency in ("alpha", "beta", "gamma", "delta")

    def test_spawn_enemy_varies_frequency(self):
        """Different spawns should produce varied frequencies (not all same)."""
        freqs = {spawn_enemy("scout", 0.0, 0.0, f"e{i}").shield_frequency for i in range(40)}
        assert len(freqs) > 1, "shield_frequency should vary across spawned enemies"


# ---------------------------------------------------------------------------
# Damage calculation
# ---------------------------------------------------------------------------


def _make_enemy(freq: str = "") -> Enemy:
    e = Enemy(id="e1", type="scout", x=0, y=0, hull=100, shield_front=0, shield_rear=0)
    e.shield_frequency = freq
    return e


class TestFrequencyDamageModifier:
    """apply_hit_to_enemy respects beam_frequency vs shield_frequency."""

    def test_no_frequency_neutral_damage(self):
        e = _make_enemy("alpha")
        before = e.hull
        apply_hit_to_enemy(e, 20.0, 100.0, 0.0, beam_frequency="")
        assert e.hull == pytest.approx(before - 20.0)

    def test_matched_frequency_bonus_damage(self):
        e = _make_enemy("beta")
        apply_hit_to_enemy(e, 20.0, 100.0, 0.0, beam_frequency="beta")
        expected_damage = 20.0 * FREQ_MATCH_MULT   # 30.0
        assert e.hull == pytest.approx(100.0 - expected_damage)

    def test_mismatched_frequency_penalty_damage(self):
        e = _make_enemy("gamma")
        apply_hit_to_enemy(e, 20.0, 100.0, 0.0, beam_frequency="delta")
        expected_damage = 20.0 * FREQ_MISMATCH_MULT   # 10.0
        assert e.hull == pytest.approx(100.0 - expected_damage)

    def test_no_enemy_frequency_neutral_damage(self):
        """Enemy with no shield_frequency → no modifier regardless of beam freq."""
        e = _make_enemy("")
        apply_hit_to_enemy(e, 20.0, 100.0, 0.0, beam_frequency="alpha")
        assert e.hull == pytest.approx(80.0)

    def test_all_four_frequencies_match(self):
        """Each frequency matches its own shield."""
        for freq in ("alpha", "beta", "gamma", "delta"):
            e = _make_enemy(freq)
            apply_hit_to_enemy(e, 10.0, 100.0, 0.0, beam_frequency=freq)
            expected = 100.0 - 10.0 * FREQ_MATCH_MULT
            assert e.hull == pytest.approx(expected), f"frequency {freq} should get bonus"

    def test_freq_match_constant_is_1_5(self):
        assert FREQ_MATCH_MULT == pytest.approx(1.5)

    def test_freq_mismatch_constant_is_0_5(self):
        assert FREQ_MISMATCH_MULT == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Sensor scan result includes shield_frequency
# ---------------------------------------------------------------------------


class TestScanResultFrequency:
    """build_scan_result includes shield_frequency after a scan."""

    def test_scanned_enemy_includes_shield_frequency(self):
        e = Enemy(id="e1", type="scout", x=0, y=0, scan_state="scanned")
        e.shield_frequency = "delta"
        result = build_scan_result(e)
        assert result.get("shield_frequency") == "delta"

    def test_scan_result_no_frequency_omits_key(self):
        e = Enemy(id="e1", type="scout", x=0, y=0, scan_state="scanned")
        e.shield_frequency = ""
        result = build_scan_result(e)
        assert "shield_frequency" not in result
