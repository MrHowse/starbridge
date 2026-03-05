"""Tests for server/telemetry.py — Section 1.3: Combat Effectiveness Metrics."""
from __future__ import annotations

import server.telemetry as tel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _LogCapture:
    """Capture telemetry log calls."""

    def __init__(self):
        self.events: list[tuple[str, str, dict]] = []

    def __enter__(self):
        self._orig_log = tel._log
        tel._log = lambda cat, event, data: self.events.append((cat, event, data))
        return self

    def __exit__(self, *args):
        tel._log = self._orig_log

    def find(self, event: str) -> list[dict]:
        return [d for _, e, d in self.events if e == event]


def _init() -> None:
    tel.init({"weapons": "Alice", "helm": "Bob"})


# ---------------------------------------------------------------------------
# Tests: record functions
# ---------------------------------------------------------------------------


class TestCombatRecording:

    def test_torpedo_fired_increments(self):
        _init()
        tel.record_torpedo_fired()
        tel.record_torpedo_fired()
        assert tel.get_combat_window().torpedoes_fired == 2

    def test_torpedo_hit_increments(self):
        _init()
        tel.record_torpedo_hit("standard", "e1", 50.0)
        assert tel.get_combat_window().torpedoes_hit == 1

    def test_beam_fired_increments_and_tracks_damage(self):
        _init()
        tel.record_beam_fired(25.0)
        tel.record_beam_fired(30.0)
        cw = tel.get_combat_window()
        assert cw.beam_shots_fired == 2
        assert cw.beam_damage_dealt == 55.0

    def test_enemy_destroyed_increments(self):
        _init()
        tel.record_enemy_destroyed()
        tel.record_enemy_destroyed()
        assert tel.get_combat_window().enemies_destroyed == 2

    def test_damage_taken_accumulates(self):
        _init()
        tel.record_damage_taken(10.0, 5.0)
        tel.record_damage_taken(20.0, 15.0)
        cw = tel.get_combat_window()
        assert cw.damage_taken_hull == 30.0
        assert cw.damage_taken_shields == 20.0

    def test_torpedo_outcome_logged(self):
        _init()
        with _LogCapture() as cap:
            tel.record_torpedo_outcome("standard", "e1", True, distance=1000.0, flight_time=3.5)
        outcomes = cap.find("torpedo_outcome")
        assert len(outcomes) == 1
        assert outcomes[0]["hit"] is True
        assert outcomes[0]["torpedo_type"] == "standard"
        assert outcomes[0]["target_distance_at_fire"] == 1000.0


# ---------------------------------------------------------------------------
# Tests: 30 s combat summary
# ---------------------------------------------------------------------------


class TestCombatSummary:

    def test_summary_emitted_at_300_ticks_with_combat(self):
        _init()
        tel.record_torpedo_fired()
        tel.record_torpedo_hit("standard", "e1", 50.0)
        tel.record_beam_fired(20.0)
        tel.record_enemy_destroyed()
        tel.record_damage_taken(5.0, 3.0)
        with _LogCapture() as cap:
            for i in range(1, 301):
                tel.tick(i, 0.1, enemy_count=2)
        summaries = cap.find("combat_summary")
        assert len(summaries) == 1
        s = summaries[0]
        assert s["torpedoes_fired"] == 1
        assert s["torpedoes_hit"] == 1
        assert s["torpedo_hit_rate"] == 1.0
        assert s["beam_shots_fired"] == 1
        assert s["beam_damage_dealt"] == 20.0
        assert s["enemies_destroyed"] == 1
        assert s["enemies_active"] == 2
        assert s["damage_taken_hull"] == 5.0
        assert s["damage_taken_shields"] == 3.0

    def test_no_summary_without_combat_activity(self):
        _init()
        with _LogCapture() as cap:
            for i in range(1, 301):
                tel.tick(i, 0.1, enemy_count=0)
        assert cap.find("combat_summary") == []

    def test_summary_resets_window(self):
        _init()
        tel.record_torpedo_fired()
        for i in range(1, 301):
            tel.tick(i, 0.1, enemy_count=1)
        cw = tel.get_combat_window()
        assert cw.torpedoes_fired == 0
        assert cw.beam_shots_fired == 0

    def test_shield_efficiency_calculated(self):
        _init()
        tel.record_damage_taken(10.0, 30.0)  # 30 / 40 = 0.75
        with _LogCapture() as cap:
            for i in range(1, 301):
                tel.tick(i, 0.1, enemy_count=1)
        s = cap.find("combat_summary")[0]
        assert s["shield_efficiency"] == 0.75

    def test_reset_clears_combat(self):
        _init()
        tel.record_torpedo_fired()
        tel.record_beam_fired(10.0)
        tel.reset()
        cw = tel.get_combat_window()
        assert cw.torpedoes_fired == 0
        assert cw.beam_shots_fired == 0
