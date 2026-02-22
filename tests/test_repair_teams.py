"""
Repair Team Model — unit tests.

Covers team creation, dispatch, BFS travel, hazard casualties,
escort protection, repair rate, order queue, recall, and serialisation.
"""
from __future__ import annotations

import random

import pytest

from server.models.interior import make_default_interior, ShipInterior
from server.models.repair_teams import (
    RepairTeam,
    RepairTeamManager,
    SYSTEM_ROOMS,
    BASE_ROOM,
    TRAVEL_TIME_PER_ROOM,
    REPAIR_RATE_PER_MEMBER,
    FIRE_CASUALTY_CHANCE,
    DEFAULT_TEAM_SIZE,
    TEAM_NAMES,
)

DT = 0.1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _interior() -> ShipInterior:
    return make_default_interior()


def _simple_manager() -> RepairTeamManager:
    """Manager with one team of 3 at base room."""
    crew = [f"crew_{i:03d}" for i in range(1, 4)]
    return RepairTeamManager.create_teams(crew, team_size=3)


def _tick_seconds(mgr: RepairTeamManager, seconds: float,
                  interior: ShipInterior,
                  rng: random.Random | None = None) -> list[dict]:
    """Tick for N seconds at 10 Hz, collecting all events."""
    events: list[dict] = []
    ticks = int(seconds / DT)
    for _ in range(ticks):
        events.extend(mgr.tick(DT, interior, rng=rng))
    return events


# ---------------------------------------------------------------------------
# RepairTeam basics
# ---------------------------------------------------------------------------


class TestRepairTeam:
    def test_default_values(self):
        team = RepairTeam(id="t1", name="Test")
        assert team.status == "idle"
        assert team.size == DEFAULT_TEAM_SIZE
        assert team.room_id == BASE_ROOM
        assert team.is_available is True
        assert team.is_eliminated is False

    def test_repair_rate_scales_with_size(self):
        team = RepairTeam(id="t1", name="Test", size=4)
        assert team.repair_rate == REPAIR_RATE_PER_MEMBER * 4

    def test_eliminated_when_size_zero(self):
        team = RepairTeam(id="t1", name="Test", size=0)
        assert team.is_eliminated is True
        assert team.is_available is False

    def test_not_available_when_busy(self):
        team = RepairTeam(id="t1", name="Test", status="travelling")
        assert team.is_available is False

    def test_to_dict_round_trip(self):
        team = RepairTeam(
            id="t1", name="Alpha", member_ids=["c1", "c2"],
            size=2, room_id="bridge", status="repairing",
            target_system="sensors", target_room_id="sensor_array",
            path=["science_lab"], travel_progress=1.5,
            repair_progress=10.0, escort_squad_id="sq1",
        )
        restored = RepairTeam.from_dict(team.to_dict())
        assert restored.id == "t1"
        assert restored.member_ids == ["c1", "c2"]
        assert restored.status == "repairing"
        assert restored.escort_squad_id == "sq1"


# ---------------------------------------------------------------------------
# Team creation
# ---------------------------------------------------------------------------


class TestTeamCreation:
    def test_single_team(self):
        mgr = RepairTeamManager.create_teams(["c1", "c2", "c3"])
        assert len(mgr.teams) == 1
        team = list(mgr.teams.values())[0]
        assert team.size == 3
        assert team.name == "Alpha Team"

    def test_two_teams(self):
        crew = [f"c{i}" for i in range(6)]
        mgr = RepairTeamManager.create_teams(crew, team_size=3)
        assert len(mgr.teams) == 2
        names = {t.name for t in mgr.teams.values()}
        assert "Alpha Team" in names
        assert "Beta Team" in names

    def test_max_four_teams(self):
        crew = [f"c{i}" for i in range(20)]
        mgr = RepairTeamManager.create_teams(crew, team_size=3)
        assert len(mgr.teams) <= len(TEAM_NAMES)

    def test_extra_crew_distributed(self):
        crew = [f"c{i}" for i in range(5)]
        mgr = RepairTeamManager.create_teams(crew, team_size=3)
        assert len(mgr.teams) == 1
        team = list(mgr.teams.values())[0]
        assert team.size == 5
        assert len(team.member_ids) == 5

    def test_empty_crew(self):
        mgr = RepairTeamManager.create_teams([])
        assert len(mgr.teams) == 0

    def test_all_teams_at_base(self):
        crew = [f"c{i}" for i in range(9)]
        mgr = RepairTeamManager.create_teams(crew, team_size=3)
        for team in mgr.teams.values():
            assert team.room_id == BASE_ROOM
            assert team.status == "idle"


# ---------------------------------------------------------------------------
# System room mapping
# ---------------------------------------------------------------------------


class TestSystemRoomMapping:
    def test_all_nine_systems_mapped(self):
        assert len(SYSTEM_ROOMS) == 9

    def test_all_rooms_exist_in_interior(self):
        interior = _interior()
        for system, room_id in SYSTEM_ROOMS.items():
            assert room_id in interior.rooms, f"{system} → {room_id} missing"

    def test_path_exists_from_base(self):
        interior = _interior()
        for system, room_id in SYSTEM_ROOMS.items():
            path = interior.find_path(BASE_ROOM, room_id)
            assert len(path) >= 1, f"No path from {BASE_ROOM} to {room_id}"


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_dispatch_starts_travel(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        assert mgr.dispatch(tid, "sensors", interior) is True
        team = mgr.teams[tid]
        assert team.status == "travelling"
        assert team.target_system == "sensors"
        assert len(team.path) > 0

    def test_dispatch_invalid_system(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        assert mgr.dispatch(tid, "warp_core", interior) is False

    def test_dispatch_invalid_team(self):
        mgr = _simple_manager()
        interior = _interior()
        assert mgr.dispatch("nonexistent", "engines", interior) is False

    def test_dispatch_eliminated_team(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.teams[tid].size = 0
        assert mgr.dispatch(tid, "engines", interior) is False

    def test_dispatch_already_at_target(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.teams[tid].room_id = "engine_room"
        assert mgr.dispatch(tid, "engines", interior) is True
        assert mgr.teams[tid].status == "repairing"
        assert mgr.teams[tid].path == []

    def test_dispatch_clears_previous(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.dispatch(tid, "sensors", interior)
        mgr.dispatch(tid, "engines", interior)
        team = mgr.teams[tid]
        assert team.target_system == "engines"


# ---------------------------------------------------------------------------
# Travel
# ---------------------------------------------------------------------------


class TestTravel:
    def test_team_advances_over_time(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.dispatch(tid, "engines", interior)

        start_room = mgr.teams[tid].room_id
        _tick_seconds(mgr, TRAVEL_TIME_PER_ROOM + 0.1, interior)
        assert mgr.teams[tid].room_id != start_room

    def test_team_arrives_at_target(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.dispatch(tid, "engines", interior)
        path_len = len(mgr.teams[tid].path)

        events = _tick_seconds(mgr, path_len * TRAVEL_TIME_PER_ROOM + 1.0,
                               interior)
        assert mgr.teams[tid].status == "repairing"
        assert mgr.teams[tid].room_id == SYSTEM_ROOMS["engines"]
        assert any(e["type"] == "team_arrived" for e in events)

    def test_team_moved_events(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.dispatch(tid, "engines", interior)

        events = _tick_seconds(mgr, TRAVEL_TIME_PER_ROOM + 0.1, interior)
        moved = [e for e in events if e["type"] == "team_moved"]
        assert len(moved) >= 1
        assert "from_room" in moved[0]

    def test_blocked_by_sealed_door(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.dispatch(tid, "engines", interior)

        # Seal the next room on the path
        next_room_id = mgr.teams[tid].path[0]
        interior.rooms[next_room_id].door_sealed = True

        _tick_seconds(mgr, TRAVEL_TIME_PER_ROOM + 1.0, interior)
        # Team should still be at base — blocked
        assert mgr.teams[tid].room_id == BASE_ROOM

    def test_blocked_by_decompressed(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.dispatch(tid, "engines", interior)

        next_room_id = mgr.teams[tid].path[0]
        interior.rooms[next_room_id].state = "decompressed"

        _tick_seconds(mgr, TRAVEL_TIME_PER_ROOM + 1.0, interior)
        assert mgr.teams[tid].room_id == BASE_ROOM

    def test_travel_progress_accumulates(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.dispatch(tid, "engines", interior)

        mgr.tick(DT, interior)
        assert mgr.teams[tid].travel_progress == pytest.approx(DT)

    def test_long_distance_travel(self):
        """Travel from engineering to bridge (6 rooms)."""
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.dispatch(tid, "manoeuvring", interior)
        path_len = len(mgr.teams[tid].path)
        assert path_len >= 4  # at least 4 rooms away

        events = _tick_seconds(mgr, path_len * TRAVEL_TIME_PER_ROOM + 1.0,
                               interior)
        assert mgr.teams[tid].status == "repairing"
        assert mgr.teams[tid].room_id == "bridge"


# ---------------------------------------------------------------------------
# Hazards
# ---------------------------------------------------------------------------


class TestHazards:
    def test_fire_room_hazard_event(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.dispatch(tid, "engines", interior)

        # Set the next room on fire
        next_room_id = mgr.teams[tid].path[0]
        interior.rooms[next_room_id].state = "fire"

        rng = random.Random(42)
        events = _tick_seconds(mgr, TRAVEL_TIME_PER_ROOM + 0.5, interior,
                               rng=rng)
        hazard_events = [e for e in events if e["type"] == "entered_hazard"]
        assert len(hazard_events) >= 1
        assert hazard_events[0]["hazard"] == "fire"

    def test_fire_casualty_deterministic(self):
        """Force a casualty with an rng that always triggers."""
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.dispatch(tid, "engines", interior)

        next_room_id = mgr.teams[tid].path[0]
        interior.rooms[next_room_id].state = "fire"

        # Create rng that always returns 0.0 (< FIRE_CASUALTY_CHANCE)
        rng = random.Random()
        rng.random = lambda: 0.0

        events = _tick_seconds(mgr, TRAVEL_TIME_PER_ROOM + 0.5, interior,
                               rng=rng)
        casualties = [e for e in events if e["type"] == "casualty"]
        assert len(casualties) >= 1
        assert casualties[0]["cause"] == "fire"
        assert mgr.teams[tid].size == 2

    def test_no_casualty_when_rng_high(self):
        """No casualty when rng exceeds threshold."""
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.dispatch(tid, "engines", interior)

        next_room_id = mgr.teams[tid].path[0]
        interior.rooms[next_room_id].state = "fire"

        rng = random.Random()
        rng.random = lambda: 0.99

        events = _tick_seconds(mgr, TRAVEL_TIME_PER_ROOM + 0.5, interior,
                               rng=rng)
        casualties = [e for e in events if e["type"] == "casualty"]
        assert len(casualties) == 0
        assert mgr.teams[tid].size == 3

    def test_team_eliminated_by_repeated_casualties(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        team = mgr.teams[tid]
        team.size = 1
        team.member_ids = ["c1"]
        mgr.dispatch(tid, "engines", interior)

        next_room_id = team.path[0]
        interior.rooms[next_room_id].state = "fire"

        rng = random.Random()
        rng.random = lambda: 0.0

        events = _tick_seconds(mgr, TRAVEL_TIME_PER_ROOM + 0.5, interior,
                               rng=rng)
        elim = [e for e in events if e["type"] == "team_eliminated"]
        assert len(elim) == 1
        assert team.is_eliminated

    def test_damaged_room_no_casualty(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.dispatch(tid, "engines", interior)

        next_room_id = mgr.teams[tid].path[0]
        interior.rooms[next_room_id].state = "damaged"

        rng = random.Random()
        rng.random = lambda: 0.0

        events = _tick_seconds(mgr, TRAVEL_TIME_PER_ROOM + 0.5, interior,
                               rng=rng)
        casualties = [e for e in events if e["type"] == "casualty"]
        assert len(casualties) == 0  # damaged rooms don't cause casualties
        hazards = [e for e in events if e["type"] == "entered_hazard"]
        assert any(h["hazard"] == "damaged" for h in hazards)


# ---------------------------------------------------------------------------
# Escort
# ---------------------------------------------------------------------------


class TestEscort:
    def test_assign_escort(self):
        mgr = _simple_manager()
        tid = list(mgr.teams.keys())[0]
        assert mgr.request_escort(tid, "squad_alpha") is True
        assert mgr.teams[tid].escort_squad_id == "squad_alpha"

    def test_clear_escort(self):
        mgr = _simple_manager()
        tid = list(mgr.teams.keys())[0]
        mgr.request_escort(tid, "squad_alpha")
        mgr.clear_escort(tid)
        assert mgr.teams[tid].escort_squad_id is None

    def test_escort_prevents_casualty(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.request_escort(tid, "squad_alpha")
        mgr.dispatch(tid, "engines", interior)

        next_room_id = mgr.teams[tid].path[0]
        interior.rooms[next_room_id].state = "fire"

        rng = random.Random()
        rng.random = lambda: 0.0  # would cause casualty without escort

        events = _tick_seconds(mgr, TRAVEL_TIME_PER_ROOM + 0.5, interior,
                               rng=rng)
        casualties = [e for e in events if e["type"] == "casualty"]
        assert len(casualties) == 0
        assert mgr.teams[tid].size == 3  # no loss


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------


class TestRepair:
    def test_repair_emits_hp_events(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        # Place team at target room directly
        mgr.teams[tid].room_id = "engine_room"
        mgr.dispatch(tid, "engines", interior)
        assert mgr.teams[tid].status == "repairing"

        events = _tick_seconds(mgr, 1.0, interior)
        hp_events = [e for e in events if e["type"] == "repair_hp"]
        assert len(hp_events) == 10  # 1 second at 10 Hz
        total_hp = sum(e["hp"] for e in hp_events)
        expected = REPAIR_RATE_PER_MEMBER * 3 * 1.0  # 3 members, 1 second
        assert total_hp == pytest.approx(expected, rel=0.01)

    def test_repair_rate_lower_with_fewer_members(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.teams[tid].room_id = "engine_room"
        mgr.teams[tid].size = 1
        mgr.dispatch(tid, "engines", interior)

        events = _tick_seconds(mgr, 1.0, interior)
        hp_events = [e for e in events if e["type"] == "repair_hp"]
        total_hp = sum(e["hp"] for e in hp_events)
        assert total_hp == pytest.approx(REPAIR_RATE_PER_MEMBER * 1.0,
                                         rel=0.01)

    def test_repair_progress_accumulates(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.teams[tid].room_id = "engine_room"
        mgr.dispatch(tid, "engines", interior)

        _tick_seconds(mgr, 2.0, interior)
        expected = REPAIR_RATE_PER_MEMBER * 3 * 2.0
        assert mgr.teams[tid].repair_progress == pytest.approx(expected,
                                                                 rel=0.01)

    def test_repair_target_system_correct(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.teams[tid].room_id = "engine_room"
        mgr.dispatch(tid, "engines", interior)

        events = _tick_seconds(mgr, 0.5, interior)
        hp_events = [e for e in events if e["type"] == "repair_hp"]
        assert all(e["system"] == "engines" for e in hp_events)


# ---------------------------------------------------------------------------
# Recall
# ---------------------------------------------------------------------------


class TestRecall:
    def test_recall_starts_return(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.teams[tid].room_id = "bridge"
        assert mgr.recall(tid, interior) is True
        assert mgr.teams[tid].status == "returning"
        assert len(mgr.teams[tid].path) > 0

    def test_recall_already_at_base(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        assert mgr.recall(tid, interior) is False

    def test_recall_returns_to_base(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.teams[tid].room_id = "engine_room"
        mgr.recall(tid, interior)
        path_len = len(mgr.teams[tid].path)

        events = _tick_seconds(mgr, path_len * TRAVEL_TIME_PER_ROOM + 1.0,
                               interior)
        assert mgr.teams[tid].status == "idle"
        assert mgr.teams[tid].room_id == BASE_ROOM
        assert any(e["type"] == "team_returned" for e in events)

    def test_recall_while_repairing(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.teams[tid].room_id = "engine_room"
        mgr.dispatch(tid, "engines", interior)
        assert mgr.teams[tid].status == "repairing"

        mgr.recall(tid, interior)
        assert mgr.teams[tid].status == "returning"
        assert mgr.teams[tid].target_system is None


# ---------------------------------------------------------------------------
# Order queue
# ---------------------------------------------------------------------------


class TestOrderQueue:
    def test_add_order(self):
        mgr = _simple_manager()
        oid = mgr.add_order("shields", priority=2)
        assert oid.startswith("order_")
        assert len(mgr.order_queue) == 1

    def test_cancel_order(self):
        mgr = _simple_manager()
        oid = mgr.add_order("shields")
        assert mgr.cancel_order(oid) is True
        assert len(mgr.order_queue) == 0
        assert mgr.cancel_order(oid) is False  # already gone

    def test_priority_ordering(self):
        mgr = _simple_manager()
        mgr.add_order("shields", priority=1)
        mgr.add_order("engines", priority=3)
        mgr.add_order("beams", priority=2)
        assert mgr.order_queue[0]["system"] == "engines"
        assert mgr.order_queue[1]["system"] == "beams"
        assert mgr.order_queue[2]["system"] == "shields"

    def test_auto_assign_idle_team(self):
        mgr = _simple_manager()
        interior = _interior()
        mgr.add_order("engines", priority=1)
        mgr.tick(DT, interior)
        # The idle team should have picked up the order
        team = list(mgr.teams.values())[0]
        assert team.status in ("travelling", "repairing")
        assert team.target_system == "engines"
        assert len(mgr.order_queue) == 0

    def test_queue_persists_when_no_idle_teams(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.dispatch(tid, "engines", interior)
        mgr.add_order("shields", priority=1)
        mgr.tick(DT, interior)
        assert len(mgr.order_queue) == 1  # still queued


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


class TestSerialisation:
    def test_round_trip(self):
        mgr = _simple_manager()
        interior = _interior()
        tid = list(mgr.teams.keys())[0]
        mgr.dispatch(tid, "engines", interior)
        mgr.add_order("shields", priority=2)

        data = mgr.serialise()
        restored = RepairTeamManager.deserialise(data)

        assert len(restored.teams) == len(mgr.teams)
        assert len(restored.order_queue) == 1
        r_team = list(restored.teams.values())[0]
        assert r_team.target_system == "engines"
        assert r_team.status == "travelling"

    def test_deserialise_defaults(self):
        restored = RepairTeamManager.deserialise({})
        assert len(restored.teams) == 0
        assert len(restored.order_queue) == 0

    def test_team_dict_round_trip(self):
        team = RepairTeam(
            id="t1", name="Alpha", member_ids=["c1"],
            size=1, room_id="bridge", status="returning",
            escort_squad_id="sq1",
        )
        data = team.to_dict()
        restored = RepairTeam.from_dict(data)
        assert restored.escort_squad_id == "sq1"
        assert restored.room_id == "bridge"

    def test_order_id_counter_preserved(self):
        mgr = _simple_manager()
        mgr.add_order("shields")
        mgr.add_order("engines")
        data = mgr.serialise()
        restored = RepairTeamManager.deserialise(data)
        assert restored._next_order_id == 2
