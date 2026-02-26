"""Tests for v0.07-4.2: Per-Ship-Class Interior Layouts."""
from __future__ import annotations

from collections import deque

import pytest

from server.models.interior import (
    ShipInterior,
    clear_cache,
    get_boarding_config,
    get_deck_rooms,
    get_system_rooms,
    load_interior,
    make_default_interior,
)

ALL_CLASSES = ["scout", "corvette", "frigate", "cruiser", "battleship", "carrier", "medical_ship"]
ALL_SYSTEMS = ["engines", "beams", "torpedoes", "shields", "sensors", "manoeuvring", "flight_deck", "ecm_suite", "point_defence"]

EXPECTED_DECKS = {
    "scout": 3, "corvette": 4, "frigate": 5, "cruiser": 6,
    "carrier": 7, "battleship": 8, "medical_ship": 5,
}

EXPECTED_MIN_ROOMS = {
    "scout": 8, "corvette": 14, "frigate": 20, "cruiser": 35,
    "carrier": 38, "battleship": 48, "medical_ship": 20,
}
EXPECTED_MAX_ROOMS = {
    "scout": 12, "corvette": 18, "frigate": 20, "cruiser": 42,
    "carrier": 46, "battleship": 56, "medical_ship": 24,
}


@pytest.fixture(autouse=True)
def _clear():
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# Loading (7)
# ---------------------------------------------------------------------------

class TestLoading:
    @pytest.mark.parametrize("ship_class", ALL_CLASSES)
    def test_loads_without_error(self, ship_class: str) -> None:
        interior = make_default_interior(ship_class)
        assert isinstance(interior, ShipInterior)
        assert len(interior.rooms) > 0

    @pytest.mark.parametrize("ship_class", ALL_CLASSES)
    def test_room_count_in_range(self, ship_class: str) -> None:
        interior = make_default_interior(ship_class)
        n = len(interior.rooms)
        assert EXPECTED_MIN_ROOMS[ship_class] <= n <= EXPECTED_MAX_ROOMS[ship_class], (
            f"{ship_class}: {n} rooms outside [{EXPECTED_MIN_ROOMS[ship_class]}, {EXPECTED_MAX_ROOMS[ship_class]}]"
        )


# ---------------------------------------------------------------------------
# Frigate backward compatibility (3)
# ---------------------------------------------------------------------------

class TestFrigateBackwardCompat:
    def test_no_args_returns_frigate(self) -> None:
        interior = make_default_interior()
        assert len(interior.rooms) == 20

    def test_room_ids_match_hardcoded(self) -> None:
        interior = make_default_interior()
        expected = {
            "bridge", "conn", "ready_room", "observation",
            "sensor_array", "science_lab", "comms_center", "astrometrics",
            "weapons_bay", "torpedo_room", "shields_control", "combat_info",
            "medbay", "surgery", "quarantine", "pharmacy",
            "main_engineering", "engine_room", "auxiliary_power", "cargo_hold",
        }
        assert set(interior.rooms.keys()) == expected

    def test_connections_match_hardcoded(self) -> None:
        interior = make_default_interior()
        r = interior.rooms
        assert r["bridge"].connections == ["conn"]
        assert r["conn"].connections == ["bridge", "ready_room", "science_lab"]
        assert r["science_lab"].connections == ["sensor_array", "comms_center", "conn", "torpedo_room"]
        assert r["torpedo_room"].connections == ["weapons_bay", "shields_control", "science_lab", "surgery"]
        assert r["surgery"].connections == ["medbay", "quarantine", "torpedo_room", "engine_room"]
        assert r["engine_room"].connections == ["main_engineering", "auxiliary_power", "surgery"]
        assert r["cargo_hold"].connections == ["auxiliary_power"]


# ---------------------------------------------------------------------------
# Graph invariants — all 7 classes
# ---------------------------------------------------------------------------

def _bfs_all_reachable(interior: ShipInterior) -> bool:
    """Check if all rooms are reachable from the first room (ignoring sealed)."""
    if not interior.rooms:
        return True
    start = next(iter(interior.rooms))
    visited = {start}
    q = deque([start])
    while q:
        cur = q.popleft()
        room = interior.rooms[cur]
        for n in room.connections:
            if n not in visited and n in interior.rooms:
                visited.add(n)
                q.append(n)
    return visited == set(interior.rooms.keys())


class TestGraphInvariants:
    @pytest.mark.parametrize("ship_class", ALL_CLASSES)
    def test_connections_bidirectional(self, ship_class: str) -> None:
        interior = make_default_interior(ship_class)
        for room in interior.rooms.values():
            for conn_id in room.connections:
                peer = interior.rooms.get(conn_id)
                assert peer is not None, f"{ship_class}: {room.id} -> {conn_id} (room missing)"
                assert room.id in peer.connections or room.id in peer.marine_only_connections, (
                    f"{ship_class}: {room.id} -> {conn_id} not bidirectional"
                )

    @pytest.mark.parametrize("ship_class", ALL_CLASSES)
    def test_fully_connected(self, ship_class: str) -> None:
        interior = make_default_interior(ship_class)
        assert _bfs_all_reachable(interior), f"{ship_class}: graph not fully connected"

    @pytest.mark.parametrize("ship_class", ALL_CLASSES)
    def test_system_rooms_exist(self, ship_class: str) -> None:
        interior = make_default_interior(ship_class)
        sys_rooms = get_system_rooms(ship_class)
        for sys_name, room_id in sys_rooms.items():
            assert room_id in interior.rooms, f"{ship_class}: system {sys_name} -> {room_id} missing"

    @pytest.mark.parametrize("ship_class", ALL_CLASSES)
    def test_deck_rooms_exist(self, ship_class: str) -> None:
        interior = make_default_interior(ship_class)
        deck_rooms = get_deck_rooms(ship_class)
        for dk, rlist in deck_rooms.items():
            for rid in rlist:
                assert rid in interior.rooms, f"{ship_class}: deck {dk} -> {rid} missing"

    @pytest.mark.parametrize("ship_class", ALL_CLASSES)
    def test_boarding_rooms_exist(self, ship_class: str) -> None:
        interior = make_default_interior(ship_class)
        bc = get_boarding_config(ship_class)
        for ep in bc["entry_points"]:
            assert ep in interior.rooms, f"{ship_class}: entry_point {ep} missing"
        for obj, rid in bc["objective_rooms"].items():
            assert rid in interior.rooms, f"{ship_class}: objective {obj} -> {rid} missing"


# ---------------------------------------------------------------------------
# System room completeness (7)
# ---------------------------------------------------------------------------

class TestSystemRoomCompleteness:
    @pytest.mark.parametrize("ship_class", ALL_CLASSES)
    def test_all_nine_systems_mapped(self, ship_class: str) -> None:
        sys_rooms = get_system_rooms(ship_class)
        for sys_name in ALL_SYSTEMS:
            assert sys_name in sys_rooms, f"{ship_class}: missing system {sys_name}"


# ---------------------------------------------------------------------------
# Deck count matches ship class (7)
# ---------------------------------------------------------------------------

class TestDeckCounts:
    @pytest.mark.parametrize("ship_class", ALL_CLASSES)
    def test_deck_count(self, ship_class: str) -> None:
        deck_rooms = get_deck_rooms(ship_class)
        expected = EXPECTED_DECKS[ship_class]
        assert len(deck_rooms) == expected, (
            f"{ship_class}: expected {expected} decks, got {len(deck_rooms)}"
        )


# ---------------------------------------------------------------------------
# Scout (2)
# ---------------------------------------------------------------------------

class TestScout:
    def test_three_decks_ten_rooms(self) -> None:
        interior = make_default_interior("scout")
        assert len(interior.rooms) == 10
        assert len(get_deck_rooms("scout")) == 3

    def test_entry_to_bridge_short(self) -> None:
        interior = make_default_interior("scout")
        bc = get_boarding_config("scout")
        for ep in bc["entry_points"]:
            path = interior.find_path(ep, "bridge", ignore_sealed=True)
            assert 0 < len(path) <= 5, (
                f"scout: path from {ep} to bridge is {len(path)} rooms (expected <= 5)"
            )


# ---------------------------------------------------------------------------
# Corvette marine tunnels (3)
# ---------------------------------------------------------------------------

class TestCorvette:
    def test_four_decks_sixteen_rooms(self) -> None:
        interior = make_default_interior("corvette")
        assert len(interior.rooms) == 16
        assert len(get_deck_rooms("corvette")) == 4

    def test_marine_tunnels_shorter(self) -> None:
        interior = make_default_interior("corvette")
        # Find at least one pair where marine tunnels give a shorter path
        found_shorter = False
        for room in interior.rooms.values():
            if room.marine_only_connections:
                for target in room.marine_only_connections:
                    normal = interior.find_path(room.id, target, ignore_sealed=True)
                    marine = interior.find_path(room.id, target, ignore_sealed=True, use_marine_tunnels=True)
                    if marine and normal and len(marine) < len(normal):
                        found_shorter = True
                        break
            if found_shorter:
                break
        assert found_shorter, "corvette: no marine tunnel path is shorter than normal"

    def test_normal_path_does_not_use_tunnels(self) -> None:
        interior = make_default_interior("corvette")
        # conn has marine_only_connections to shields_control
        normal = interior.find_path("conn", "shields_control")
        # Normal path should go via science_lab -> torpedo_room -> shields_control
        # i.e. length > 2
        assert len(normal) > 2, "normal path should not use marine tunnels"


# ---------------------------------------------------------------------------
# Cruiser bridge protection (2)
# ---------------------------------------------------------------------------

class TestCruiser:
    def test_six_decks_thirtyeight_rooms(self) -> None:
        interior = make_default_interior("cruiser")
        assert len(interior.rooms) == 38
        assert len(get_deck_rooms("cruiser")) == 6

    def test_entry_to_bridge_through_sealed_doors(self) -> None:
        interior = make_default_interior("cruiser")
        bc = get_boarding_config("cruiser")
        for ep in bc["entry_points"]:
            path = interior.find_path(ep, "bridge", ignore_sealed=True)
            assert len(path) > 0, f"cruiser: no path from {ep} to bridge"
            sealed_count = sum(
                1 for rid in path
                if interior.rooms[rid].door_sealed
            )
            assert sealed_count >= 2, (
                f"cruiser: path from {ep} to bridge passes through only {sealed_count} sealed doors (need >= 2)"
            )


# ---------------------------------------------------------------------------
# Battleship depth (2)
# ---------------------------------------------------------------------------

class TestBattleship:
    def test_eight_decks_about_fiftytwo_rooms(self) -> None:
        interior = make_default_interior("battleship")
        assert 48 <= len(interior.rooms) <= 56
        assert len(get_deck_rooms("battleship")) == 8

    def test_entry_to_bridge_deep(self) -> None:
        interior = make_default_interior("battleship")
        bc = get_boarding_config("battleship")
        for ep in bc["entry_points"]:
            path = interior.find_path(ep, "bridge", ignore_sealed=True)
            assert len(path) >= 8, (
                f"battleship: path from {ep} to bridge is {len(path)} rooms (expected >= 8)"
            )


# ---------------------------------------------------------------------------
# Carrier hangars (2)
# ---------------------------------------------------------------------------

class TestCarrier:
    def test_seven_decks_with_hangars(self) -> None:
        interior = make_default_interior("carrier")
        assert len(get_deck_rooms("carrier")) == 7
        hangar_rooms = [r for r in interior.rooms.values() if "hangar" in r.tags]
        assert len(hangar_rooms) >= 4, "carrier: expected at least 4 hangar-tagged rooms"

    def test_hangar_rooms_well_connected(self) -> None:
        interior = make_default_interior("carrier")
        hangar_rooms = [r for r in interior.rooms.values() if "hangar" in r.tags]
        for room in hangar_rooms:
            assert len(room.connections) >= 3, (
                f"carrier: hangar room {room.id} has only {len(room.connections)} connections (need >= 3)"
            )


# ---------------------------------------------------------------------------
# Medical ship quarantine (2)
# ---------------------------------------------------------------------------

class TestMedicalShip:
    def test_five_decks_two_medical(self) -> None:
        interior = make_default_interior("medical_ship")
        assert len(get_deck_rooms("medical_ship")) == 5
        # Count rooms with crew_deck "medical"
        medical_decks = set()
        for room in interior.rooms.values():
            if room.deck == "medical":
                medical_decks.add(room.deck_number)
        assert len(medical_decks) >= 2, "medical_ship: expected at least 2 medical decks"

    def test_quarantine_lockable_rooms(self) -> None:
        interior = make_default_interior("medical_ship")
        lockable = [r for r in interior.rooms.values() if r.quarantine_lockable]
        assert len(lockable) >= 2, (
            f"medical_ship: expected >= 2 quarantine_lockable rooms, got {len(lockable)}"
        )


# ---------------------------------------------------------------------------
# Caching + error handling (2)
# ---------------------------------------------------------------------------

class TestCachingAndErrors:
    def test_cached_on_second_load(self) -> None:
        data1 = load_interior("frigate")
        data2 = load_interior("frigate")
        assert data1 is data2

    def test_file_not_found_for_nonexistent(self) -> None:
        with pytest.raises(FileNotFoundError):
            make_default_interior("nonexistent_class")


# ---------------------------------------------------------------------------
# Save round-trip (1)
# ---------------------------------------------------------------------------

class TestSaveRoundTrip:
    def test_create_damage_save_restore(self) -> None:
        interior = make_default_interior("frigate")
        # Damage some rooms
        interior.rooms["bridge"].state = "fire"
        interior.rooms["medbay"].door_sealed = True
        # Save state
        saved = {}
        for rid, room in interior.rooms.items():
            saved[rid] = {"state": room.state, "door_sealed": room.door_sealed}
        # Restore into fresh interior
        restored = make_default_interior("frigate")
        for rid, rstate in saved.items():
            if rid in restored.rooms:
                restored.rooms[rid].state = rstate["state"]
                restored.rooms[rid].door_sealed = rstate["door_sealed"]
        assert restored.rooms["bridge"].state == "fire"
        assert restored.rooms["medbay"].door_sealed is True
        assert restored.rooms["conn"].state == "normal"


# ---------------------------------------------------------------------------
# New Room fields present (parametric)
# ---------------------------------------------------------------------------

class TestNewRoomFields:
    @pytest.mark.parametrize("ship_class", ALL_CLASSES)
    def test_deck_number_set(self, ship_class: str) -> None:
        interior = make_default_interior(ship_class)
        for room in interior.rooms.values():
            assert room.deck_number > 0, f"{ship_class}: {room.id} has deck_number=0"

    @pytest.mark.parametrize("ship_class", ALL_CLASSES)
    def test_all_rooms_covered_by_deck_rooms(self, ship_class: str) -> None:
        interior = make_default_interior(ship_class)
        deck_rooms = get_deck_rooms(ship_class)
        covered = set()
        for rlist in deck_rooms.values():
            covered.update(rlist)
        all_ids = set(interior.rooms.keys())
        assert all_ids == covered, f"{ship_class}: deck_rooms mismatch: {all_ids - covered}"
