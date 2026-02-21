"""
Tests for server/profiles.py — v0.04g.

Covers profile creation, stat accumulation, achievement unlocking,
listing, full-profile retrieval, and CSV export.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

import server.profiles as prof


# ---------------------------------------------------------------------------
# Fixture: redirect PROFILES_DIR to a temp directory
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def tmp_profiles(tmp_path, monkeypatch):
    """Redirect all profile I/O to a temporary directory."""
    monkeypatch.setattr(prof, "PROFILES_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_station_stats(role: str, events: dict) -> dict:
    """Build a minimal per_station_stats dict for one role."""
    return {role: {"total": sum(events.values()), "events": events}}


# ---------------------------------------------------------------------------
# get_or_create_profile
# ---------------------------------------------------------------------------


def test_get_or_create_creates_new_profile():
    p = prof.get_or_create_profile("Alice")
    assert p["name"] == "Alice"


def test_get_or_create_default_counts_zero():
    p = prof.get_or_create_profile("Bob")
    assert p["games_played"] == 0
    assert p["games_won"] == 0
    assert p["games_lost"] == 0


def test_get_or_create_loads_existing():
    # First call creates profile.
    prof.get_or_create_profile("Carol")
    # Second call returns the same data.
    p2 = prof.get_or_create_profile("Carol")
    assert p2["name"] == "Carol"


def test_get_or_create_writes_file(tmp_profiles):
    prof.get_or_create_profile("Dave")
    assert (tmp_profiles / "Dave.json").exists()


def test_get_or_create_achievements_empty():
    p = prof.get_or_create_profile("Eve")
    assert p["achievements"] == []


# ---------------------------------------------------------------------------
# update_game_result
# ---------------------------------------------------------------------------


def test_update_game_result_increments_games_played():
    prof.get_or_create_profile("Frank")
    prof.update_game_result("Frank", "helm", "victory", "mission_1", 60.0, {})
    p = prof.get_or_create_profile("Frank")
    assert p["games_played"] == 1


def test_update_game_result_victory_increments_games_won():
    prof.get_or_create_profile("Grace")
    prof.update_game_result("Grace", "helm", "victory", "mission_1", 60.0, {})
    p = prof.get_or_create_profile("Grace")
    assert p["games_won"] == 1
    assert p["games_lost"] == 0


def test_update_game_result_defeat_increments_games_lost():
    prof.get_or_create_profile("Hank")
    prof.update_game_result("Hank", "weapons", "defeat", "mission_1", 30.0, {})
    p = prof.get_or_create_profile("Hank")
    assert p["games_lost"] == 1
    assert p["games_won"] == 0


def test_update_game_result_accumulates_career_events():
    prof.get_or_create_profile("Ivy")
    stats1 = _make_station_stats("weapons", {"beam_fired": 10})
    stats2 = _make_station_stats("weapons", {"beam_fired": 15})
    prof.update_game_result("Ivy", "weapons", "victory", "m1", 60.0, stats1)
    prof.update_game_result("Ivy", "weapons", "victory", "m1", 60.0, stats2)
    p = prof.get_or_create_profile("Ivy")
    assert p["career_events"]["beam_fired"] == 25


def test_update_game_result_tracks_mission():
    prof.get_or_create_profile("Jack")
    prof.update_game_result("Jack", "helm", "victory", "first_contact", 60.0, {})
    p = prof.get_or_create_profile("Jack")
    assert "first_contact" in p["missions_played"]


def test_update_game_result_no_duplicate_mission():
    prof.get_or_create_profile("Kate")
    prof.update_game_result("Kate", "helm", "victory", "first_contact", 60.0, {})
    prof.update_game_result("Kate", "helm", "victory", "first_contact", 60.0, {})
    p = prof.get_or_create_profile("Kate")
    assert p["missions_played"].count("first_contact") == 1


# ---------------------------------------------------------------------------
# Achievement unlocking
# ---------------------------------------------------------------------------


def test_first_command_unlocked_after_first_game():
    prof.get_or_create_profile("Leo")
    newly = prof.update_game_result("Leo", "helm", "defeat", "m1", 30.0, {})
    assert "first_command" in newly


def test_bridge_regular_unlocked_at_5_games():
    prof.get_or_create_profile("Mia")
    for i in range(5):
        prof.update_game_result("Mia", "helm", "victory", f"m{i}", 60.0, {})
    p = prof.get_or_create_profile("Mia")
    assert "bridge_regular" in p["achievements"]


def test_veteran_not_unlocked_before_20_games():
    prof.get_or_create_profile("Ned")
    for i in range(10):
        prof.update_game_result("Ned", "helm", "victory", f"m{i}", 60.0, {})
    p = prof.get_or_create_profile("Ned")
    assert "veteran" not in p["achievements"]


def test_sharpshooter_unlocked_at_50_beams():
    prof.get_or_create_profile("Olivia")
    stats = _make_station_stats("weapons", {"beam_fired": 50})
    newly = prof.update_game_result("Olivia", "weapons", "victory", "m1", 60.0, stats)
    assert "sharpshooter" in newly


def test_life_saver_unlocked_at_20_treatments():
    prof.get_or_create_profile("Peter")
    stats = _make_station_stats("medical", {"treatment_started": 20})
    newly = prof.update_game_result("Peter", "medical", "victory", "m1", 60.0, stats)
    assert "life_saver" in newly


def test_explorer_unlocked_at_5_missions():
    prof.get_or_create_profile("Quinn")
    missions = ["m1", "m2", "m3", "m4", "m5"]
    for m in missions:
        prof.update_game_result("Quinn", "helm", "victory", m, 60.0, {})
    p = prof.get_or_create_profile("Quinn")
    assert "explorer" in p["achievements"]


def test_newly_unlocked_returned_once():
    """Achievement IDs returned only when first earned, not on subsequent games."""
    prof.get_or_create_profile("Rose")
    n1 = prof.update_game_result("Rose", "helm", "defeat", "m1", 30.0, {})
    assert "first_command" in n1
    n2 = prof.update_game_result("Rose", "helm", "defeat", "m2", 30.0, {})
    assert "first_command" not in n2


# ---------------------------------------------------------------------------
# list_profiles
# ---------------------------------------------------------------------------


def test_list_profiles_empty_dir():
    result = prof.list_profiles()
    assert result == []


def test_list_profiles_returns_entries():
    prof.get_or_create_profile("Sam")
    prof.get_or_create_profile("Tina")
    result = prof.list_profiles()
    assert len(result) == 2


def test_list_profiles_sorted_by_wins():
    prof.get_or_create_profile("Uma")
    prof.get_or_create_profile("Victor")
    # Uma wins 3 games, Victor wins 1.
    for _ in range(3):
        prof.update_game_result("Uma", "captain", "victory", "m1", 60.0, {})
    prof.update_game_result("Victor", "captain", "victory", "m1", 60.0, {})
    result = prof.list_profiles()
    assert result[0]["name"] == "Uma"
    assert result[1]["name"] == "Victor"


# ---------------------------------------------------------------------------
# get_profile
# ---------------------------------------------------------------------------


def test_get_profile_returns_full():
    prof.get_or_create_profile("Wendy")
    p = prof.get_profile("Wendy")
    assert p is not None
    assert p["name"] == "Wendy"
    assert "career_events" in p


def test_get_profile_none_if_missing():
    assert prof.get_profile("nobody") is None


# ---------------------------------------------------------------------------
# export_csv
# ---------------------------------------------------------------------------


def test_export_csv_contains_header():
    prof.get_or_create_profile("Xavier")
    csv_text = prof.export_csv()
    assert "name" in csv_text
    assert "games_won" in csv_text


def test_export_csv_contains_profile():
    prof.get_or_create_profile("Yara")
    prof.update_game_result("Yara", "science", "victory", "m1", 90.0, {})
    csv_text = prof.export_csv()
    assert "Yara" in csv_text
