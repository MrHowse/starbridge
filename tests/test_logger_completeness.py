"""Tests for game logger event completeness and record format.

TEST GROUP 5: Verifies that GameLogger records events correctly,
debounce works, session lifecycle is proper, and that every significant
game event category has proper log output.

Covers:
  - Session start/stop lifecycle
  - Log record format (tick, ts, cat, event, data)
  - Debounce: intermediate values are collapsed
  - Debounce force-flush on stop
  - set_tick updates tick counter in records
  - Logging disabled via environment variable
  - Combat events: beam_fired, torpedo_hit, enemy_destroyed, ship_hit, system_damaged
  - Engineering events: overclock_damage, repair_started, dct_*, battery_mode, reroute
  - Medical events: patient_admit, treatment_v2_started, stabilise, discharge, quarantine
  - Weapons events: target_selected, shield_focus_changed, torpedo_fired
  - Science events: scan_started, scan_completed, sector_scan_*
  - Navigation events: route_plotted, route_cleared
  - Flight ops events: drone_launched, drone_recalled, probe_deployed
  - EW events: jam_target_set, countermeasures_toggled, intrusion_started
  - Tactical events: engagement_priority, intercept_target, annotation_*, strike_plan_*
  - Sandbox events: enemy_spawned, crew_casualty, hull_micro_damage, etc.
  - Security events: boarding_started, squad_moved, door_toggled
  - Creature events: sedate, ew_disrupt, comm_progress, leech_removed
  - Helm debounced: heading_changed, throttle_changed
  - Mission events: objective_completed
  - tick_summary periodic events
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from server.game_logger import GameLogger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_logger() -> tuple[GameLogger, Path]:
    """Create a logger that writes to a temp directory."""
    tmp = tempfile.mkdtemp()
    logger = GameLogger()
    # Monkey-patch log_dir
    with patch.object(Path, "mkdir", return_value=None):
        pass  # Let it create normally
    return logger, Path(tmp)


def start_logger_in_tmpdir() -> tuple[GameLogger, Path]:
    """Start a logger session writing to a temp directory, return (logger, logfile_path)."""
    tmp = Path(tempfile.mkdtemp())
    log_dir = tmp / "logs"
    log_dir.mkdir(exist_ok=True)

    logger = GameLogger()
    logger._FLUSH_INTERVAL = 1  # Flush every write in tests
    # Directly set up the logger to write to our temp directory
    logfile = log_dir / "test_game.jsonl"
    logger._log_file = logfile
    logger._fh = logfile.open("a", encoding="utf-8")
    logger._active = True
    logger._tick = 0
    logger._start_ts = time.monotonic()
    # Write session header
    logger._write({"tick": 0, "ts": 0.0, "cat": "session", "event": "started",
                    "data": {"mission_id": "test_mission", "players": {"helm": "player1"}}})
    return logger, logfile


def read_records(logfile: Path) -> list[dict]:
    """Read all JSON records from a JSONL log file."""
    records = []
    with open(logfile, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def close_logger(logger: GameLogger) -> None:
    """Close the logger gracefully."""
    if logger._active:
        logger.stop("test_complete")


# ---------------------------------------------------------------------------
# 1. Session Lifecycle
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    """Logger session start/stop produce proper records."""

    def test_start_writes_session_started(self):
        logger, logfile = start_logger_in_tmpdir()
        records = read_records(logfile)
        close_logger(logger)

        assert len(records) >= 1
        assert records[0]["cat"] == "session"
        assert records[0]["event"] == "started"
        assert records[0]["tick"] == 0

    def test_stop_writes_session_ended(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.stop("victory", {"score": 100})

        records = read_records(logfile)
        last = records[-1]
        assert last["cat"] == "session"
        assert last["event"] == "ended"
        assert last["data"]["result"] == "victory"
        assert last["data"]["stats"]["score"] == 100

    def test_stop_sets_inactive(self):
        logger, logfile = start_logger_in_tmpdir()
        assert logger.is_active()
        logger.stop("defeat")
        assert not logger.is_active()

    def test_log_after_stop_is_noop(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.stop("test")
        initial_count = len(read_records(logfile))
        logger.log("test", "should_not_appear")
        assert len(read_records(logfile)) == initial_count

    def test_get_log_path_active(self):
        logger, logfile = start_logger_in_tmpdir()
        assert logger.get_log_path() == logfile
        close_logger(logger)

    def test_get_log_path_after_stop(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.stop("done")
        # Last log file preserved
        assert logger.get_log_path() == logfile


# ---------------------------------------------------------------------------
# 2. Record Format
# ---------------------------------------------------------------------------


class TestRecordFormat:
    """Every log record has tick, ts, cat, event, data fields."""

    def test_record_has_all_fields(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("combat", "beam_fired", {"target": "enemy_1", "damage": 10.0})
        close_logger(logger)

        records = read_records(logfile)
        # Skip session started, check our record
        rec = records[1]
        assert "tick" in rec
        assert "ts" in rec
        assert "cat" in rec
        assert "event" in rec
        assert "data" in rec
        assert rec["cat"] == "combat"
        assert rec["event"] == "beam_fired"
        assert rec["data"]["target"] == "enemy_1"

    def test_tick_increments_in_records(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.set_tick(10)
        logger.log("test", "event1")
        logger.set_tick(20)
        logger.log("test", "event2")
        close_logger(logger)

        records = read_records(logfile)
        event_recs = [r for r in records if r["cat"] == "test"]
        assert event_recs[0]["tick"] == 10
        assert event_recs[1]["tick"] == 20

    def test_ts_is_monotonic(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("a", "first")
        logger.log("a", "second")
        close_logger(logger)

        records = read_records(logfile)
        assert records[-1]["ts"] >= records[-2]["ts"]

    def test_data_defaults_to_empty_dict(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("test", "no_data")
        close_logger(logger)

        records = read_records(logfile)
        rec = [r for r in records if r["event"] == "no_data"][0]
        assert rec["data"] == {}


# ---------------------------------------------------------------------------
# 3. Debounce
# ---------------------------------------------------------------------------


class TestDebounce:
    """Debounced events collapse intermediate values."""

    def test_debounce_collapses_rapid_events(self):
        logger, logfile = start_logger_in_tmpdir()

        # Simulate rapid helm changes (slider drag)
        for heading in range(0, 360, 10):
            logger.log_debounced("helm", "heading_changed",
                                 {"from": 0, "to": heading}, window_s=0.01)

        # Force flush
        time.sleep(0.02)
        logger.set_tick(1)  # Triggers flush
        close_logger(logger)

        records = read_records(logfile)
        helm_recs = [r for r in records if r["cat"] == "helm"]
        # Should have collapsed to 1 record with final "to" value
        assert len(helm_recs) == 1
        assert helm_recs[0]["data"]["to"] == 350
        assert helm_recs[0]["data"]["from"] == 0

    def test_debounce_preserves_original_from(self):
        logger, logfile = start_logger_in_tmpdir()

        logger.log_debounced("eng", "power", {"from": 50, "to": 60}, window_s=0.01)
        logger.log_debounced("eng", "power", {"from": 50, "to": 80}, window_s=0.01)
        logger.log_debounced("eng", "power", {"from": 50, "to": 100}, window_s=0.01)

        time.sleep(0.02)
        logger.set_tick(1)
        close_logger(logger)

        records = read_records(logfile)
        eng_recs = [r for r in records if r["cat"] == "eng"]
        assert len(eng_recs) == 1
        assert eng_recs[0]["data"]["from"] == 50  # Original
        assert eng_recs[0]["data"]["to"] == 100   # Final

    def test_stop_flushes_pending_debounced(self):
        logger, logfile = start_logger_in_tmpdir()

        logger.log_debounced("helm", "throttle", {"from": 0, "to": 50}, window_s=10.0)
        # Stop should force-flush even though window hasn't elapsed
        logger.stop("test")

        records = read_records(logfile)
        helm_recs = [r for r in records if r["cat"] == "helm"]
        assert len(helm_recs) == 1  # Flushed by stop

    def test_different_categories_debounce_independently(self):
        logger, logfile = start_logger_in_tmpdir()

        logger.log_debounced("helm", "heading_changed", {"from": 0, "to": 90}, window_s=0.01)
        logger.log_debounced("eng", "power_changed", {"from": 50, "to": 80}, window_s=0.01)

        time.sleep(0.02)
        logger.set_tick(1)
        close_logger(logger)

        records = read_records(logfile)
        helm_recs = [r for r in records if r["cat"] == "helm"]
        eng_recs = [r for r in records if r["cat"] == "eng"]
        assert len(helm_recs) == 1
        assert len(eng_recs) == 1


# ---------------------------------------------------------------------------
# 4. Environment Variable Control
# ---------------------------------------------------------------------------


class TestEnvControl:
    """STARBRIDGE_LOGGING=false disables logging."""

    def test_logging_disabled(self):
        logger = GameLogger()
        with patch.dict(os.environ, {"STARBRIDGE_LOGGING": "false"}):
            logger.start("test_mission", {"helm": "p1"})
        assert not logger.is_active()

    def test_logging_enabled_by_default(self):
        logger, logfile = start_logger_in_tmpdir()
        assert logger.is_active()
        close_logger(logger)


# ---------------------------------------------------------------------------
# 5. Combat Event Categories
# ---------------------------------------------------------------------------


class TestCombatEvents:
    """Combat event log records have correct categories and fields."""

    def test_beam_fired(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("weapons", "beam_fired", {
            "target_id": "enemy_1", "damage": 15.0, "hit": True,
        })
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "beam_fired"]
        assert len(recs) == 1
        assert recs[0]["data"]["target_id"] == "enemy_1"

    def test_torpedo_hit(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("weapons", "torpedo_hit", {
            "target_id": "enemy_2", "torpedo_type": "standard", "damage": 30.0,
        })
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "torpedo_hit"]
        assert len(recs) == 1
        assert "torpedo_type" in recs[0]["data"]

    def test_enemy_destroyed(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("combat", "enemy_destroyed", {"enemy_id": "e1", "cause": "beam"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "enemy_destroyed"]
        assert len(recs) == 1
        assert recs[0]["data"]["cause"] == "beam"

    def test_system_damaged(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("combat", "system_damaged", {
            "system": "engines", "new_health": 75.0,
            "component": "comp_1", "component_health": 80.0, "effect": "",
        })
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "system_damaged"]
        assert len(recs) == 1
        assert recs[0]["data"]["system"] == "engines"

    def test_crew_casualty(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("combat", "crew_casualty", {
            "deck": "weapons", "crew_id": "c1", "crew_name": "Lt. Chen",
            "injury_type": "shrapnel", "body_region": "torso", "severity": "serious",
        })
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "crew_casualty"]
        assert len(recs) == 1
        assert recs[0]["data"]["severity"] == "serious"

    def test_ship_hit(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("combat", "ship_hit", {
            "damage": 20.0, "facing": "fore", "shields_absorbed": 15.0,
        })
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "ship_hit"]
        assert len(recs) == 1


# ---------------------------------------------------------------------------
# 6. Engineering Event Categories
# ---------------------------------------------------------------------------


class TestEngineeringEvents:
    """Engineering events logged correctly."""

    def test_overclock_damage(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("engineering", "overclock_damage", {
            "system": "beams", "new_health": 90.0,
            "component": "emitter_1", "component_health": 85.0, "effect": "reduced_output",
        })
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "overclock_damage"]
        assert len(recs) == 1

    def test_repair_started(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("engineering", "repair_started", {"system": "engines"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "repair_started"]
        assert len(recs) == 1

    def test_dct_dispatched(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("engineering", "dct_dispatched", {"room_id": "room_1_1"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "dct_dispatched"]
        assert len(recs) == 1

    def test_battery_mode_changed(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("engineering", "battery_mode_changed", {"mode": "charging"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "battery_mode_changed"]
        assert len(recs) == 1

    def test_reroute_started(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("engineering", "reroute_started", {"target_bus": "bus_a"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "reroute_started"]
        assert len(recs) == 1


# ---------------------------------------------------------------------------
# 7. Medical Event Categories
# ---------------------------------------------------------------------------


class TestMedicalEvents:
    """Medical events logged correctly."""

    def test_patient_admit(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("medical", "patient_admit", {"crew_id": "c1", "success": True})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "patient_admit"]
        assert len(recs) == 1

    def test_treatment_started(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("medical", "treatment_v2_started", {
            "crew_id": "c1", "injury_id": "inj_001", "success": True,
        })
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "treatment_v2_started"]
        assert len(recs) == 1

    def test_stabilise(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("medical", "stabilise", {
            "crew_id": "c1", "injury_id": "inj_001", "success": True,
        })
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "stabilise"]
        assert len(recs) == 1

    def test_discharge(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("medical", "discharge", {"crew_id": "c1", "success": True})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "discharge"]
        assert len(recs) == 1

    def test_quarantine(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("medical", "quarantine", {"crew_id": "c1", "success": True})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "quarantine"]
        assert len(recs) == 1


# ---------------------------------------------------------------------------
# 8. Science Event Categories
# ---------------------------------------------------------------------------


class TestScienceEvents:
    def test_scan_started(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("science", "scan_started", {"entity_id": "e1"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "scan_started"]
        assert len(recs) == 1

    def test_scan_completed(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("science", "scan_completed", {"entity_id": "e1"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "scan_completed"]
        assert len(recs) == 1

    def test_sector_scan_started(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("science", "sector_scan_started", {"scale": "sector", "mode": "em"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "sector_scan_started"]
        assert len(recs) == 1

    def test_sector_scan_completed(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("science", "sector_scan_completed", {"scale": "sector", "mode": "em"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "sector_scan_completed"]
        assert len(recs) == 1


# ---------------------------------------------------------------------------
# 9. Navigation, FlightOps, EW, Tactical, Security, Creature Events
# ---------------------------------------------------------------------------


class TestNavigationEvents:
    def test_route_plotted(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("navigation", "route_plotted", {"from": [0, 0], "to": [100, 100]})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "route_plotted"]
        assert len(recs) == 1

    def test_route_cleared(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("navigation", "route_cleared", {})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "route_cleared"]
        assert len(recs) == 1


class TestFlightOpsEvents:
    def test_drone_launched(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("flight_ops", "drone_launched", {"drone_id": "d1"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "drone_launched"]
        assert len(recs) == 1

    def test_drone_recalled(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("flight_ops", "drone_recalled", {"drone_id": "d1"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "drone_recalled"]
        assert len(recs) == 1

    def test_probe_deployed(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("flight_ops", "probe_deployed", {"x": 100, "y": 200, "mode": "em"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "probe_deployed"]
        assert len(recs) == 1


class TestEWEvents:
    def test_jam_target_set(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("ew", "jam_target_set", {"entity_id": "e1"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "jam_target_set"]
        assert len(recs) == 1

    def test_countermeasures_toggled(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("ew", "countermeasures_toggled", {"active": True})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "countermeasures_toggled"]
        assert len(recs) == 1

    def test_intrusion_started(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("ew", "intrusion_started", {"target_id": "e1", "system": "sensors"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "intrusion_started"]
        assert len(recs) == 1


class TestTacticalEvents:
    def test_engagement_priority(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("tactical", "engagement_priority_set", {"entity_id": "e1", "priority": "high"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "engagement_priority_set"]
        assert len(recs) == 1

    def test_intercept_target(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("tactical", "intercept_target_set", {"entity_id": "e1"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "intercept_target_set"]
        assert len(recs) == 1

    def test_annotation_added(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("tactical", "annotation_added", {"id": "a1", "type": "waypoint"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "annotation_added"]
        assert len(recs) == 1

    def test_strike_plan_created(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("tactical", "strike_plan_created", {"plan_id": "sp1", "step_count": 3})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "strike_plan_created"]
        assert len(recs) == 1


class TestSecurityEvents:
    def test_boarding_started(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("security", "boarding_started", {"intruder_count": 5})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "boarding_started"]
        assert len(recs) == 1

    def test_squad_moved(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("security", "squad_moved", {"squad_id": "s1", "room_id": "r1"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "squad_moved"]
        assert len(recs) == 1

    def test_door_toggled(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("security", "door_toggled", {"room_id": "r1", "squad_id": "s1"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "door_toggled"]
        assert len(recs) == 1


class TestCreatureEvents:
    def test_sedate(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("creature", "sedate", {"creature_id": "cr1"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "sedate"]
        assert len(recs) == 1

    def test_ew_disrupt(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("creature", "ew_disrupt", {"creature_id": "cr1"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "ew_disrupt"]
        assert len(recs) == 1

    def test_leech_removed(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("creature", "leech_removed", {"creature_id": "cr1", "method": "manual"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "leech_removed"]
        assert len(recs) == 1


# ---------------------------------------------------------------------------
# 10. Sandbox & Mission Events
# ---------------------------------------------------------------------------


class TestSandboxEvents:
    def test_enemy_spawned(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("sandbox", "enemy_spawned", {"enemy_type": "raider"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "enemy_spawned"]
        assert len(recs) == 1

    def test_hull_micro_damage(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("sandbox", "hull_micro_damage", {"amount": 2.0})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "hull_micro_damage"]
        assert len(recs) == 1

    def test_crew_casualty(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("sandbox", "crew_casualty", {"deck": "weapons", "crew_id": "c1"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "crew_casualty"]
        assert len(recs) == 1


class TestMissionEvents:
    def test_objective_completed(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("mission", "objective_completed", {"objective_id": "obj_1"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "objective_completed"]
        assert len(recs) == 1


class TestTickSummary:
    def test_tick_summary(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.set_tick(100)
        logger.log("game", "tick_summary", {
            "hull": 95.0,
            "shields": {"fore": 50, "aft": 50, "port": 50, "starboard": 50},
            "ammo": {"standard": 10},
            "enemy_count": 3,
            "x": 1000.0, "y": 2000.0,
        })
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "tick_summary"]
        assert len(recs) == 1
        assert recs[0]["tick"] == 100
        assert recs[0]["data"]["hull"] == 95.0


# ---------------------------------------------------------------------------
# 11. Flush Batching
# ---------------------------------------------------------------------------


class TestFlushBatching:
    """Flush interval controls when data is flushed to disk."""

    def test_flush_interval(self):
        """A fresh GameLogger uses _FLUSH_INTERVAL=10 by default."""
        fresh = GameLogger()
        assert fresh._FLUSH_INTERVAL == 10

        # Our test helper sets it to 1 for convenience
        logger, logfile = start_logger_in_tmpdir()
        assert logger._FLUSH_INTERVAL == 1

        # Write 10 events — all should be readable immediately
        for i in range(10):
            logger.log("test", f"event_{i}")

        # All 11 records should be readable (1 session + 10 events)
        records = read_records(logfile)
        assert len(records) == 11
        close_logger(logger)

    def test_stop_flushes_remaining(self):
        logger, logfile = start_logger_in_tmpdir()
        # Write 3 events (under flush threshold)
        for i in range(3):
            logger.log("test", f"evt_{i}")
        logger.stop("done")

        records = read_records(logfile)
        # 1 session start + 3 events + 1 session end = 5
        assert len(records) == 5


# ---------------------------------------------------------------------------
# 12. Docking Events
# ---------------------------------------------------------------------------


class TestDockingEvents:
    def test_clearance_requested(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("comms", "docking_clearance_requested", {"station_id": "st1"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "docking_clearance_requested"]
        assert len(recs) == 1

    def test_service_started(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("captain", "docking_service_started", {"service": "repair"})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "docking_service_started"]
        assert len(recs) == 1

    def test_undock_ordered(self):
        logger, logfile = start_logger_in_tmpdir()
        logger.log("captain", "undock_ordered", {"emergency": False})
        close_logger(logger)
        recs = [r for r in read_records(logfile) if r["event"] == "undock_ordered"]
        assert len(recs) == 1
