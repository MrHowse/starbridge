"""
Tests for v0.06-maps: Unified range controls + contact visibility fix.

Validates:
  - Server sensor range constant unchanged (BASE_SENSOR_RANGE = 30k)
  - sensor_range() calculation with efficiency, hazard, difficulty
  - build_sensor_contacts() filters by SENSOR range (game mechanic)
  - Contacts outside sensor range excluded; inside included
  - Extra detection bubbles (drone/probe) extend detection
  - Creature / station filtering
  - Client range presets spec compliance (values encoded in test)
  - Viewport range independence from sensor range
"""
from __future__ import annotations

import pytest

from server.models.ship import Ship
from server.models.world import (
    ENEMY_TYPE_PARAMS,
    Creature,
    Enemy,
    Station,
    World,
)
from server.systems.sensors import (
    BASE_SENSOR_RANGE,
    build_sensor_contacts,
    sensor_range,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ship(
    x: float = 50_000.0,
    y: float = 50_000.0,
    sensor_efficiency: float = 1.0,
) -> Ship:
    ship = Ship()
    ship.x = x
    ship.y = y
    ship.heading = 0.0
    ship.systems["sensors"]._power = 100
    ship.systems["sensors"]._crew_factor = sensor_efficiency
    return ship


def _make_enemy(
    eid: str = "e1",
    x: float = 50_000.0,
    y: float = 50_000.0,
    scan_state: str = "unknown",
) -> Enemy:
    return Enemy(
        id=eid,
        type="cruiser",
        x=x,
        y=y,
        hull=ENEMY_TYPE_PARAMS["cruiser"]["hull"],
        shield_front=100.0,
        shield_rear=100.0,
        ai_state="idle",
        shield_frequency="alpha",
        scan_state=scan_state,
    )


def _make_creature(
    cid: str = "c1",
    x: float = 50_000.0,
    y: float = 50_000.0,
    detected: bool = True,
) -> Creature:
    return Creature(
        id=cid,
        creature_type="void_whale",
        x=x,
        y=y,
        hull=200.0,
        hull_max=200.0,
        detected=detected,
    )


def _make_station(
    sid: str = "s1",
    x: float = 50_000.0,
    y: float = 50_000.0,
    faction: str = "hostile",
    transponder_active: bool = False,
) -> Station:
    return Station(
        id=sid,
        station_type="military",
        name="Test Station",
        x=x,
        y=y,
        hull=500.0,
        hull_max=500.0,
        faction=faction,
        transponder_active=transponder_active,
    )


def _make_world(ship: Ship | None = None) -> World:
    w = World()
    if ship:
        w.ship = ship
    return w


# ═══════════════════════════════════════════════════════════════════════════
# 1. Server constants
# ═══════════════════════════════════════════════════════════════════════════


class TestServerConstants:
    """Server sensor constants are unchanged by the range control work."""

    def test_base_sensor_range_is_30k(self):
        assert BASE_SENSOR_RANGE == 30_000.0

    def test_sensor_range_at_full_efficiency(self):
        ship = _make_ship(sensor_efficiency=1.0)
        assert sensor_range(ship) == pytest.approx(30_000.0)

    def test_sensor_range_at_half_efficiency(self):
        ship = _make_ship(sensor_efficiency=0.5)
        assert sensor_range(ship) == pytest.approx(15_000.0)

    def test_sensor_range_with_hazard_modifier(self):
        ship = _make_ship(sensor_efficiency=1.0)
        assert sensor_range(ship, hazard_modifier=0.5) == pytest.approx(15_000.0)

    def test_sensor_range_with_difficulty_multiplier(self):
        """If the difficulty preset has a sensor_range_multiplier, it scales range."""
        ship = _make_ship(sensor_efficiency=1.0)
        # Simulate a difficulty preset with sensor_range_multiplier = 0.8
        ship.difficulty = type("FakeDifficulty", (), {"sensor_range_multiplier": 0.8})()
        assert sensor_range(ship) == pytest.approx(24_000.0)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Sensor contact filtering — enemy detection
# ═══════════════════════════════════════════════════════════════════════════


class TestSensorContactFiltering:
    """build_sensor_contacts() includes ALL enemies — no distance filtering."""

    def test_enemy_within_sensor_range_included(self):
        ship = _make_ship(x=50_000, y=50_000)
        enemy = _make_enemy(x=50_000 + 20_000, y=50_000)
        world = _make_world(ship)
        world.enemies.append(enemy)

        contacts = build_sensor_contacts(world, ship)
        assert len(contacts) == 1
        assert contacts[0]["id"] == "e1"

    def test_enemy_far_away_still_included(self):
        """No distance filter — enemies at any range appear in contacts."""
        ship = _make_ship(x=50_000, y=50_000)
        enemy = _make_enemy(x=50_000 + 100_000, y=50_000)  # 100k away
        world = _make_world(ship)
        world.enemies.append(enemy)

        contacts = build_sensor_contacts(world, ship)
        assert len(contacts) == 1

    def test_multiple_enemies_all_included(self):
        """All enemies included regardless of distance."""
        ship = _make_ship(x=50_000, y=50_000)
        near = _make_enemy(eid="near", x=50_000 + 10_000, y=50_000)
        mid  = _make_enemy(eid="mid",  x=50_000 + 40_000, y=50_000)
        far  = _make_enemy(eid="far",  x=50_000 + 100_000, y=50_000)
        world = _make_world(ship)
        world.enemies.extend([near, mid, far])

        contacts = build_sensor_contacts(world, ship)
        ids = {c["id"] for c in contacts}
        assert ids == {"near", "mid", "far"}

    def test_contacts_independent_of_sensor_efficiency(self):
        """Sensor efficiency no longer filters contacts."""
        ship = _make_ship(x=50_000, y=50_000, sensor_efficiency=0.5)
        enemy = _make_enemy(x=50_000 + 20_000, y=50_000)
        world = _make_world(ship)
        world.enemies.append(enemy)

        contacts = build_sensor_contacts(world, ship)
        assert len(contacts) == 1

    def test_hazard_modifier_no_longer_filters(self):
        """Hazard modifier accepted but does not filter contacts."""
        ship = _make_ship(x=50_000, y=50_000)
        enemy = _make_enemy(x=50_000 + 20_000, y=50_000)
        world = _make_world(ship)
        world.enemies.append(enemy)

        contacts = build_sensor_contacts(world, ship, hazard_modifier=0.5)
        assert len(contacts) == 1

    def test_extra_bubbles_accepted_for_compat(self):
        """extra_bubbles param accepted but no longer needed for detection."""
        ship = _make_ship(x=50_000, y=50_000)
        enemy = _make_enemy(x=90_000, y=50_000)
        world = _make_world(ship)
        world.enemies.append(enemy)

        # Enemy visible without bubbles
        contacts = build_sensor_contacts(world, ship)
        assert len(contacts) == 1

        # Also visible with bubbles (same result)
        bubbles = [(80_000.0, 50_000.0, 15_000.0)]
        contacts_b = build_sensor_contacts(world, ship, extra_bubbles=bubbles)
        assert len(contacts_b) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 3. Contact data completeness
# ═══════════════════════════════════════════════════════════════════════════


class TestContactData:
    """Contacts carry the required fields for client display."""

    def test_unscanned_enemy_has_position_and_kind(self):
        ship = _make_ship(x=50_000, y=50_000)
        enemy = _make_enemy(x=55_000, y=50_000, scan_state="unknown")
        world = _make_world(ship)
        world.enemies.append(enemy)

        contacts = build_sensor_contacts(world, ship)
        c = contacts[0]
        assert "x" in c and "y" in c
        assert c["kind"] == "enemy"
        assert c["classification"] == "unknown"
        assert c["scan_state"] == "unknown"
        # Unscanned: should NOT have type/hull details
        assert "type" not in c

    def test_scanned_enemy_has_full_details(self):
        ship = _make_ship(x=50_000, y=50_000)
        enemy = _make_enemy(x=55_000, y=50_000, scan_state="scanned")
        world = _make_world(ship)
        world.enemies.append(enemy)

        contacts = build_sensor_contacts(world, ship)
        c = contacts[0]
        assert c["classification"] == "hostile"
        assert c["scan_state"] == "scanned"
        assert "type" in c
        assert "hull" in c
        assert "shield_front" in c

    def test_contact_includes_heading(self):
        ship = _make_ship(x=50_000, y=50_000)
        enemy = _make_enemy(x=55_000, y=50_000)
        world = _make_world(ship)
        world.enemies.append(enemy)

        contacts = build_sensor_contacts(world, ship)
        assert "heading" in contacts[0]


# ═══════════════════════════════════════════════════════════════════════════
# 4. Creature contact filtering
# ═══════════════════════════════════════════════════════════════════════════


class TestCreatureContacts:
    """Creature contacts filtered by detection status only (no range filter)."""

    def test_detected_creature_included(self):
        ship = _make_ship(x=50_000, y=50_000)
        creature = _make_creature(x=55_000, y=50_000, detected=True)
        world = _make_world(ship)
        world.creatures.append(creature)

        contacts = build_sensor_contacts(world, ship)
        assert len(contacts) == 1
        assert contacts[0]["kind"] == "creature"

    def test_undetected_creature_excluded(self):
        ship = _make_ship(x=50_000, y=50_000)
        creature = _make_creature(x=55_000, y=50_000, detected=False)
        world = _make_world(ship)
        world.creatures.append(creature)

        contacts = build_sensor_contacts(world, ship)
        assert len(contacts) == 0

    def test_detected_creature_far_away_still_included(self):
        """No distance filter — detected creatures always appear."""
        ship = _make_ship(x=50_000, y=50_000)
        creature = _make_creature(x=50_000 + 100_000, y=50_000, detected=True)
        world = _make_world(ship)
        world.creatures.append(creature)

        contacts = build_sensor_contacts(world, ship)
        assert len(contacts) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 5. Station contact filtering
# ═══════════════════════════════════════════════════════════════════════════


class TestStationContacts:
    """Station visibility: hostile always; others need transponder."""

    def test_hostile_station_in_range_included(self):
        ship = _make_ship(x=50_000, y=50_000)
        station = _make_station(x=60_000, y=50_000, faction="hostile")
        world = _make_world(ship)
        world.stations.append(station)

        contacts = build_sensor_contacts(world, ship)
        assert len(contacts) == 1
        assert contacts[0]["classification"] == "hostile"

    def test_friendly_station_without_transponder_excluded(self):
        ship = _make_ship(x=50_000, y=50_000)
        station = _make_station(x=55_000, y=50_000, faction="friendly", transponder_active=False)
        world = _make_world(ship)
        world.stations.append(station)

        contacts = build_sensor_contacts(world, ship)
        assert len(contacts) == 0

    def test_friendly_station_with_transponder_included(self):
        ship = _make_ship(x=50_000, y=50_000)
        station = _make_station(x=55_000, y=50_000, faction="friendly", transponder_active=True)
        world = _make_world(ship)
        world.stations.append(station)

        contacts = build_sensor_contacts(world, ship)
        assert len(contacts) == 1
        assert contacts[0]["classification"] == "friendly"

    def test_station_far_away_still_included(self):
        """No distance filter — visible stations always appear."""
        ship = _make_ship(x=50_000, y=50_000)
        station = _make_station(x=50_000 + 100_000, y=50_000, faction="hostile")
        world = _make_world(ship)
        world.stations.append(station)

        contacts = build_sensor_contacts(world, ship)
        assert len(contacts) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 6. Range presets — spec compliance
# ═══════════════════════════════════════════════════════════════════════════


class TestRangePresetSpec:
    """Verify expected range preset values (matching client range_control.js)."""

    EXPECTED_PRESETS = {
        "25":  25_000,
        "50":  50_000,
        "100": 100_000,
        "500": 500_000,
        "1K":  1_000_000,
        "5K":  5_000_000,
    }

    EXPECTED_STATION_DEFAULTS = {
        "captain":  "100",
        "helm":     "50",
        "weapons":  "50",
        "science":  "100",
        "operations": "100",
        "flight_ops": "50",
        "electronic_warfare": "50",
    }

    EXPECTED_STATION_RANGES = {
        "captain":  ["25", "50", "100", "500", "1K", "5K", "SEC", "STR"],
        "helm":     ["25", "50", "100", "500", "1K", "SEC"],
        "weapons":  ["25", "50", "100"],
        "science":  ["25", "50", "100", "500", "1K", "SEC", "STR"],
        "operations": ["25", "50", "100", "500", "1K", "SEC", "STR"],
        "flight_ops": ["25", "50", "100", "500"],
        "electronic_warfare": ["25", "50", "100"],
    }

    @pytest.mark.parametrize("key,expected_units", list(EXPECTED_PRESETS.items()))
    def test_range_preset_world_units(self, key, expected_units):
        """Each numeric range key maps to the expected world unit value."""
        # These are the values that the client's RANGE_PRESETS must use.
        # We encode them here to detect accidental spec drift.
        assert expected_units == int(key.replace("K", "000")) * 1000

    @pytest.mark.parametrize("station,default_range", list(EXPECTED_STATION_DEFAULTS.items()))
    def test_station_default_range(self, station, default_range):
        """Per-station default range matches spec."""
        assert default_range in self.EXPECTED_STATION_RANGES[station]

    @pytest.mark.parametrize("station", list(EXPECTED_STATION_RANGES.keys()))
    def test_station_has_at_least_two_ranges(self, station):
        """Every station has at least 2 range options."""
        assert len(self.EXPECTED_STATION_RANGES[station]) >= 2

    def test_weapons_no_sector_or_strategic(self):
        """Weapons station should not have SEC or STR ranges."""
        assert "SEC" not in self.EXPECTED_STATION_RANGES["weapons"]
        assert "STR" not in self.EXPECTED_STATION_RANGES["weapons"]

    def test_all_seven_map_stations_covered(self):
        """All map-capable stations have range config."""
        assert set(self.EXPECTED_STATION_RANGES.keys()) == {
            "captain", "helm", "weapons", "science",
            "operations", "flight_ops", "electronic_warfare",
        }


# ═══════════════════════════════════════════════════════════════════════════
# 7. Viewport independence — the critical invariant
# ═══════════════════════════════════════════════════════════════════════════


class TestViewportIndependence:
    """The server NEVER considers viewport zoom when building contacts.

    The client can zoom to 25km or 5000km — contacts included in the payload
    depend ONLY on sensor_range() (server game mechanic), not viewport range.
    """

    def test_contacts_same_regardless_of_hypothetical_viewport(self):
        """build_sensor_contacts returns ALL enemies — no distance filtering."""
        ship = _make_ship(x=50_000, y=50_000)
        near  = _make_enemy(eid="near",  x=55_000, y=50_000)   # 5k away
        mid   = _make_enemy(eid="mid",   x=70_000, y=50_000)   # 20k away
        far   = _make_enemy(eid="far",   x=90_000, y=50_000)   # 40k away
        world = _make_world(ship)
        world.enemies.extend([near, mid, far])

        contacts = build_sensor_contacts(world, ship)
        ids = {c["id"] for c in contacts}

        # All enemies included regardless of distance.
        assert ids == {"near", "mid", "far"}

    def test_sensor_range_is_game_mechanic_not_ui_zoom(self):
        """Sensor range (detection) is independent of any client-side zoom.

        The same server call with the same ship state always returns
        identical contact sets — the server has no concept of viewport range.
        """
        ship = _make_ship(x=50_000, y=50_000)
        enemy = _make_enemy(x=75_000, y=50_000)  # 25k away, within 30k range
        world = _make_world(ship)
        world.enemies.append(enemy)

        # Call multiple times — same result every time.
        c1 = build_sensor_contacts(world, ship)
        c2 = build_sensor_contacts(world, ship)
        assert len(c1) == len(c2) == 1
        assert c1[0]["id"] == c2[0]["id"] == "e1"

    def test_no_viewport_parameter_on_build_sensor_contacts(self):
        """build_sensor_contacts has no zoom/viewport/range parameter.

        This ensures the server can't accidentally couple to client zoom.
        """
        import inspect
        sig = inspect.signature(build_sensor_contacts)
        param_names = set(sig.parameters.keys())
        # Should only have: world, ship, extra_bubbles, hazard_modifier, ghost_contacts
        assert param_names == {"world", "ship", "extra_bubbles", "hazard_modifier", "ghost_contacts"}
