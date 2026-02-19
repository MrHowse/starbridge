"""Tests for server/models/interior.py — Room and ShipInterior BFS pathfinding.

Covers:
  make_default_interior — 20 rooms, all decks represented, default state
  find_path — same room, adjacent, cross-deck, bridge→engine_room
  find_path — unknown room returns empty
  find_path — sealed door blocks traversal; bypass is unaffected
  find_path — decompressed room blocks traversal
"""
from __future__ import annotations

import pytest

from server.models.interior import Room, ShipInterior, make_default_interior


# ---------------------------------------------------------------------------
# make_default_interior
# ---------------------------------------------------------------------------


def test_default_interior_has_20_rooms():
    interior = make_default_interior()
    assert len(interior.rooms) == 20


def test_default_interior_all_rooms_normal_state():
    interior = make_default_interior()
    for room in interior.rooms.values():
        assert room.state == "normal"


def test_default_interior_no_sealed_doors():
    interior = make_default_interior()
    for room in interior.rooms.values():
        assert room.door_sealed is False


def test_default_interior_all_crew_decks_represented():
    interior = make_default_interior()
    deck_names = {room.deck for room in interior.rooms.values()}
    expected = {"bridge", "sensors", "weapons", "shields", "medical", "engineering"}
    assert deck_names == expected


def test_default_interior_connections_are_bidirectional():
    """Every connection A→B must have a matching B→A."""
    interior = make_default_interior()
    for room_id, room in interior.rooms.items():
        for connected_id in room.connections:
            connected_room = interior.rooms.get(connected_id)
            assert connected_room is not None, f"Room {room_id} references unknown room {connected_id}"
            assert room_id in connected_room.connections, (
                f"Room {room_id} → {connected_id} is one-way (missing reverse)"
            )


# ---------------------------------------------------------------------------
# find_path — basic navigation
# ---------------------------------------------------------------------------


def test_find_path_same_room():
    interior = make_default_interior()
    path = interior.find_path("bridge", "bridge")
    assert path == ["bridge"]


def test_find_path_adjacent_rooms():
    interior = make_default_interior()
    path = interior.find_path("bridge", "conn")
    assert path == ["bridge", "conn"]


def test_find_path_is_shortest():
    """BFS must return the shortest (fewest-step) path."""
    interior = make_default_interior()
    # science_lab directly connects to comms_center — path must be length 2
    path = interior.find_path("science_lab", "comms_center")
    assert path == ["science_lab", "comms_center"]


def test_find_path_cross_deck():
    """Path from bridge to science_lab must cross a deck boundary via conn."""
    interior = make_default_interior()
    path = interior.find_path("bridge", "science_lab")
    assert path[0] == "bridge"
    assert path[-1] == "science_lab"
    # Verify every step is valid
    for i in range(len(path) - 1):
        room = interior.rooms[path[i]]
        assert path[i + 1] in room.connections, (
            f"Step {path[i]} → {path[i + 1]} is not a valid connection"
        )


def test_find_path_bridge_to_engine_room():
    """Can navigate from the bridge all the way to the engine room."""
    interior = make_default_interior()
    path = interior.find_path("bridge", "engine_room")
    assert path[0] == "bridge"
    assert path[-1] == "engine_room"
    for i in range(len(path) - 1):
        room = interior.rooms[path[i]]
        assert path[i + 1] in room.connections


def test_find_path_dead_end_room():
    """Can navigate to a dead-end room (no onward connections)."""
    interior = make_default_interior()
    path = interior.find_path("bridge", "observation")
    assert path[0] == "bridge"
    assert path[-1] == "observation"


# ---------------------------------------------------------------------------
# find_path — unknown rooms
# ---------------------------------------------------------------------------


def test_find_path_unknown_destination_returns_empty():
    interior = make_default_interior()
    assert interior.find_path("bridge", "nonexistent") == []


def test_find_path_unknown_source_returns_empty():
    interior = make_default_interior()
    assert interior.find_path("nonexistent", "bridge") == []


def test_find_path_both_unknown_returns_empty():
    interior = make_default_interior()
    assert interior.find_path("foo", "bar") == []


# ---------------------------------------------------------------------------
# find_path — sealed doors
# ---------------------------------------------------------------------------


def test_find_path_blocked_by_sealed_door():
    """Sealing conn — the only exit from the bridge — makes bridge unreachable."""
    interior = make_default_interior()
    interior.rooms["conn"].door_sealed = True
    path = interior.find_path("bridge", "science_lab")
    assert path == []


def test_sealed_dead_end_does_not_affect_main_route():
    """Sealing a dead-end room (astrometrics) should not block the main corridor."""
    interior = make_default_interior()
    interior.rooms["astrometrics"].door_sealed = True
    path = interior.find_path("science_lab", "comms_center")
    assert path == ["science_lab", "comms_center"]


def test_sealed_room_blocks_route_but_bypass_exists():
    """If an alternate route exists, a sealed room does not block everything."""
    interior = make_default_interior()
    # Seal shields_control — but torpedo_room has another path via science_lab
    interior.rooms["shields_control"].door_sealed = True
    # weapons_bay can still reach torpedo_room directly (weapons_bay → torpedo_room)
    path = interior.find_path("weapons_bay", "torpedo_room")
    assert path == ["weapons_bay", "torpedo_room"]


# ---------------------------------------------------------------------------
# find_path — decompressed rooms
# ---------------------------------------------------------------------------


def test_find_path_blocked_by_decompressed_room():
    """A decompressed room is impassable."""
    interior = make_default_interior()
    interior.rooms["conn"].state = "decompressed"
    path = interior.find_path("bridge", "science_lab")
    assert path == []


def test_damaged_room_is_still_passable():
    """A 'damaged' room is not blocked — only 'decompressed' and sealed doors block."""
    interior = make_default_interior()
    interior.rooms["conn"].state = "damaged"
    path = interior.find_path("bridge", "science_lab")
    assert path[0] == "bridge"
    assert path[-1] == "science_lab"
