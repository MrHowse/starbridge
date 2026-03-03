"""Tests for boarding area impact — C.2.1 + C.2.2."""
from __future__ import annotations

import pytest

import server.game_loop_security as gls
from server.models.boarding import BoardingParty
from server.models.interior import ShipInterior, Room, make_default_interior
from server.models.marine_teams import MarineTeam
from server.models.ship import Ship


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ship() -> Ship:
    ship = Ship()
    ship.interior = make_default_interior("frigate")
    return ship


def _make_simple_interior() -> ShipInterior:
    """Minimal interior for unit tests."""
    rooms = {
        "bridge": Room(id="bridge", name="Bridge", deck="command", position=(0, 0), connections=["corridor"]),
        "corridor": Room(id="corridor", name="Corridor", deck="command", position=(1, 0), connections=["bridge", "engine_room", "weapons_bay"]),
        "engine_room": Room(id="engine_room", name="Engine Room", deck="engineering", position=(2, 0), connections=["corridor"]),
        "weapons_bay": Room(id="weapons_bay", name="Weapons Bay", deck="tactical", position=(1, 1), connections=["corridor"]),
    }
    system_rooms = {
        "engines": "engine_room",
        "beams": "weapons_bay",
        "manoeuvring": "bridge",
    }
    return ShipInterior(rooms=rooms, system_rooms=system_rooms)


def _setup_boarding(interior: ShipInterior, location: str, add_marines: bool = False, marine_room: str | None = None):
    """Set up a boarding party (and optionally marines) in the given room."""
    gls.reset()
    party = BoardingParty(
        id="bp_1", location=location,
        members=4, max_members=4, status="sabotaging",
    )
    gls._boarding_parties.append(party)
    gls._boarding_active = True
    if add_marines:
        team = MarineTeam(
            id="mt_alpha", name="Alpha", callsign="Alpha",
            members=["m1", "m2"], leader="m1", size=2, max_size=4,
            location=marine_room or location,
        )
        gls._marine_teams.append(team)


# ---------------------------------------------------------------------------
# C.2.1: Occupied Rooms
# ---------------------------------------------------------------------------


class TestOccupiedRooms:
    def test_no_boarding(self):
        """No boarding = no occupied rooms."""
        gls.reset()
        assert gls.get_occupied_rooms() == {}

    def test_controlled_room(self):
        """Room with boarders and no marines is 'controlled'."""
        interior = _make_simple_interior()
        _setup_boarding(interior, "engine_room")
        occupied = gls.get_occupied_rooms()
        assert occupied == {"engine_room": "controlled"}

    def test_contested_room(self):
        """Room with boarders and marines is 'contested'."""
        interior = _make_simple_interior()
        _setup_boarding(interior, "engine_room", add_marines=True)
        occupied = gls.get_occupied_rooms()
        assert occupied == {"engine_room": "contested"}

    def test_marines_different_room(self):
        """Marines in a different room don't contest boarder room."""
        interior = _make_simple_interior()
        _setup_boarding(interior, "engine_room", add_marines=True, marine_room="bridge")
        occupied = gls.get_occupied_rooms()
        assert occupied == {"engine_room": "controlled"}


# ---------------------------------------------------------------------------
# C.2.1: System Penalties
# ---------------------------------------------------------------------------


class TestBoardingSystemPenalties:
    def test_no_penalty_when_clear(self):
        gls.reset()
        interior = _make_simple_interior()
        penalties = gls.get_boarding_system_penalties(interior)
        assert penalties == {}

    def test_controlled_system_disabled(self):
        """Boarder-controlled system room → 0.0 multiplier."""
        interior = _make_simple_interior()
        _setup_boarding(interior, "engine_room")
        penalties = gls.get_boarding_system_penalties(interior)
        assert penalties["engines"] == 0.0

    def test_contested_system_half(self):
        """Contested system room → 0.5 multiplier."""
        interior = _make_simple_interior()
        _setup_boarding(interior, "engine_room", add_marines=True)
        penalties = gls.get_boarding_system_penalties(interior)
        assert penalties["engines"] == 0.5

    def test_unaffected_systems(self):
        """Systems in non-occupied rooms have no penalty."""
        interior = _make_simple_interior()
        _setup_boarding(interior, "engine_room")
        penalties = gls.get_boarding_system_penalties(interior)
        assert "beams" not in penalties
        assert "manoeuvring" not in penalties

    def test_multiple_occupied_rooms(self):
        """Multiple rooms occupied → multiple penalties."""
        interior = _make_simple_interior()
        gls.reset()
        p1 = BoardingParty(id="bp_1", location="engine_room", members=4, max_members=4, status="sabotaging")
        p2 = BoardingParty(id="bp_2", location="weapons_bay", members=3, max_members=3, status="sabotaging")
        gls._boarding_parties.extend([p1, p2])
        gls._boarding_active = True
        penalties = gls.get_boarding_system_penalties(interior)
        assert penalties["engines"] == 0.0
        assert penalties["beams"] == 0.0


# ---------------------------------------------------------------------------
# C.2.1: system_rooms on ShipInterior
# ---------------------------------------------------------------------------


class TestSystemRoomsMapping:
    def test_frigate_system_rooms(self):
        """Frigate interior JSON populates system_rooms."""
        interior = make_default_interior("frigate")
        assert "engines" in interior.system_rooms
        assert "manoeuvring" in interior.system_rooms
        assert interior.system_rooms["engines"] == "engine_room"
        assert interior.system_rooms["manoeuvring"] == "bridge"

    def test_all_ship_classes_have_system_rooms(self):
        """All 7 ship classes have system_rooms populated."""
        from server.models.interior import clear_cache
        clear_cache()
        for cls in ["scout", "corvette", "frigate", "medical_ship", "cruiser", "carrier", "battleship"]:
            interior = make_default_interior(cls)
            assert len(interior.system_rooms) > 0, f"{cls} missing system_rooms"
            # manoeuvring maps to bridge in all classes.
            assert "manoeuvring" in interior.system_rooms, f"{cls} missing manoeuvring"


# ---------------------------------------------------------------------------
# C.2.2: Proximity Rooms
# ---------------------------------------------------------------------------


class TestProximityRooms:
    def test_proximity_rooms(self):
        interior = _make_simple_interior()
        _setup_boarding(interior, "engine_room")
        proximity = gls.get_boarder_proximity_rooms(interior)
        assert "corridor" in proximity
        # engine_room itself is occupied, not proximity.
        assert "engine_room" not in proximity

    def test_no_boarding_no_proximity(self):
        gls.reset()
        interior = _make_simple_interior()
        assert gls.get_boarder_proximity_rooms(interior) == set()


# ---------------------------------------------------------------------------
# C.2.2: Casualty Prediction
# ---------------------------------------------------------------------------


class TestCasualtyPrediction:
    def test_no_casualties(self):
        gls.reset()
        pred = gls.get_casualty_prediction()
        assert pred["contested_rooms"] == 0
        assert pred["estimated_casualties_per_minute"] == 0.0

    def test_contested_casualties(self):
        interior = _make_simple_interior()
        _setup_boarding(interior, "engine_room", add_marines=True)
        pred = gls.get_casualty_prediction()
        assert pred["contested_rooms"] == 1
        assert pred["estimated_casualties_per_minute"] > 0.0


# ---------------------------------------------------------------------------
# C.2.1: Penalty Clears on Elimination
# ---------------------------------------------------------------------------


class TestPenaltyClears:
    def test_penalties_clear_when_no_boarders(self):
        interior = _make_simple_interior()
        _setup_boarding(interior, "engine_room")
        assert gls.get_boarding_system_penalties(interior) != {}
        # Eliminate the boarding party.
        gls._boarding_parties[0].members = 0
        gls._boarding_parties[0].status = "eliminated"
        # Clean up like tick_combat does.
        gls._boarding_parties[:] = [p for p in gls._boarding_parties if not p.is_eliminated]
        assert gls.get_boarding_system_penalties(interior) == {}


# ---------------------------------------------------------------------------
# D.11: Room-Type Specific Impact
# ---------------------------------------------------------------------------


class TestRoomTypeSpecificImpact:
    """Each room type's specific system impact + transitions."""

    def test_bridge_occupation_disables_manoeuvring(self):
        """Bridge mapped to manoeuvring — controlled → 0.0 penalty."""
        interior = _make_simple_interior()
        _setup_boarding(interior, "bridge")
        penalties = gls.get_boarding_system_penalties(interior)
        assert "manoeuvring" in penalties
        assert penalties["manoeuvring"] == 0.0

    def test_weapons_bay_occupation_disables_beams(self):
        """Weapons bay mapped to beams — controlled → 0.0 penalty."""
        interior = _make_simple_interior()
        _setup_boarding(interior, "weapons_bay")
        penalties = gls.get_boarding_system_penalties(interior)
        assert "beams" in penalties
        assert penalties["beams"] == 0.0

    def test_contested_to_cleared_restores_instantly(self):
        """Boarders eliminated mid-contest → penalties removed immediately."""
        interior = _make_simple_interior()
        _setup_boarding(interior, "engine_room", add_marines=True)
        # Contested — should have a penalty.
        penalties = gls.get_boarding_system_penalties(interior)
        assert penalties.get("engines") == 0.5
        # Eliminate the boarders (marines win).
        gls._boarding_parties[0].members = 0
        gls._boarding_parties[0].status = "eliminated"
        gls._boarding_parties[:] = [p for p in gls._boarding_parties if not p.is_eliminated]
        # Penalties gone immediately.
        assert gls.get_boarding_system_penalties(interior) == {}

    def test_three_rooms_occupied_simultaneously(self):
        """3 boarding parties across 3 system rooms → all 3 penalised."""
        interior = _make_simple_interior()
        gls.reset()
        p1 = BoardingParty(id="bp_a", location="bridge", members=3, max_members=3, status="sabotaging")
        p2 = BoardingParty(id="bp_b", location="engine_room", members=3, max_members=3, status="sabotaging")
        p3 = BoardingParty(id="bp_c", location="weapons_bay", members=3, max_members=3, status="sabotaging")
        gls._boarding_parties.extend([p1, p2, p3])
        gls._boarding_active = True
        penalties = gls.get_boarding_system_penalties(interior)
        assert penalties["manoeuvring"] == 0.0
        assert penalties["engines"] == 0.0
        assert penalties["beams"] == 0.0
        assert len(penalties) == 3
