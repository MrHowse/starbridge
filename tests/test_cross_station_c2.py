"""Tests for v0.08-C.2: Engineering/Science/Helm Cross-Station Integrations.

Covers:
  C.3 Engineering ↔ Hazard Control (fire suppression, breach repair, LS, vent, overclock)
  C.4 Science ↔ Ops (request scan, scan quality, assessment output)
  C.5 Helm ↔ Multiple (high-speed torpedo, threat bearing)
"""
from __future__ import annotations

import pytest

from server.models.interior import ShipInterior, Room
from server.models.ship import Ship
from server.models.world import Enemy, World
import server.game_loop_hazard_control as glhc
import server.game_loop_atmosphere as glatm
import server.game_loop_engineering as gle
import server.game_loop_operations as glops
import server.game_loop_weapons as glw
from server.models.repair_teams import RepairTeamManager
from server.systems import sensors


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_ship(efficiency: float = 1.0, throttle: float = 0.5,
               heading: float = 0.0, x: float = 0.0, y: float = 0.0) -> Ship:
    """Create a Ship with all systems at the given efficiency.

    Sets power=100 and health=efficiency*100 so sys.efficiency == efficiency.
    """
    ship = Ship(name="TestShip", x=x, y=y, heading=heading, throttle=throttle)
    for sys in ship.systems.values():
        sys.power = 100.0
        sys.health = efficiency * 100.0
    return ship


def _make_interior() -> ShipInterior:
    """Minimal 2-deck interior for testing."""
    rooms = {
        "engine_room": Room(id="engine_room", name="Engine Room",
                            deck="engineering", position=(0, 0),
                            deck_number=1, connections=["bridge"]),
        "bridge": Room(id="bridge", name="Bridge",
                       deck="command", position=(0, 1),
                       deck_number=2, connections=["engine_room", "weapons_bay"]),
        "weapons_bay": Room(id="weapons_bay", name="Weapons Bay",
                            deck="command", position=(1, 1),
                            deck_number=2, connections=["bridge"]),
    }
    return ShipInterior(rooms=rooms)


def _make_world(enemies: list[Enemy] | None = None) -> World:
    return World(enemies=enemies or [])


# ===========================================================================
# C.3 Engineering ↔ Hazard Control
# ===========================================================================


class TestFireSuppressionPower:
    """C.3.1: Fire suppression power gate."""

    def test_powered_ok(self):
        """Suppression works when avg system efficiency >= threshold."""
        ship = _make_ship(efficiency=1.0)
        glhc.update_fire_suppression_power(ship)
        assert glhc.is_fire_suppression_powered() is True

    def test_unpowered_blocks_suppress_local(self):
        """suppress_local returns False when power too low."""
        ship = _make_ship(efficiency=0.0)
        glhc.update_fire_suppression_power(ship)
        assert glhc.is_fire_suppression_powered() is False
        interior = _make_interior()
        glhc.start_fire("bridge", 2, interior, 0)
        assert glhc.suppress_local("bridge") is False

    def test_unpowered_blocks_suppress_deck(self):
        """suppress_deck returns False when power too low."""
        ship = _make_ship(efficiency=0.0)
        glhc.update_fire_suppression_power(ship)
        interior = _make_interior()
        glhc.start_fire("bridge", 2, interior, 0)
        assert glhc.suppress_deck("command", interior) is False

    def test_state_field_in_dc_state(self):
        """build_dc_state includes fire_suppression_powered."""
        interior = _make_interior()
        state = glhc.build_dc_state(interior)
        assert "fire_suppression_powered" in state
        assert state["fire_suppression_powered"] is True

    def test_threshold_boundary(self):
        """Exactly at threshold is powered; just below is not."""
        # At threshold (10%)
        ship = _make_ship(efficiency=0.10)
        glhc.update_fire_suppression_power(ship)
        assert glhc.is_fire_suppression_powered() is True

        # Below threshold
        ship = _make_ship(efficiency=0.09)
        glhc.update_fire_suppression_power(ship)
        assert glhc.is_fire_suppression_powered() is False


class TestBreachRepair:
    """C.3.2: Breach repair coordination."""

    def test_repair_breach_removes_breach(self):
        """repair_breach removes the breach from atmosphere state."""
        interior = _make_interior()
        glatm.init_atmosphere(interior)
        glatm.create_breach("bridge", "minor", interior)
        assert "bridge" in glatm.get_breaches()
        assert glatm.repair_breach("bridge") is True
        assert "bridge" not in glatm.get_breaches()

    def test_repair_breach_no_breach(self):
        """repair_breach returns False if no breach exists."""
        assert glatm.repair_breach("nonexistent") is False

    def test_dispatch_to_room(self):
        """dispatch_to_room sends team to breach room."""
        interior = _make_interior()
        mgr = RepairTeamManager.create_teams(["c1", "c2", "c3"],
                                             base_room="engine_room")
        team_id = list(mgr.teams.keys())[0]
        result = mgr.dispatch_to_room(team_id, "bridge", interior)
        assert result["ok"] is True
        team = mgr.teams[team_id]
        assert team.target_system == "__breach__"
        assert team.target_room_id == "bridge"
        assert team.status in ("travelling", "repairing")

    def test_breach_repair_event(self):
        """Breach repair emits breach_repaired event after 8s."""
        interior = _make_interior()
        mgr = RepairTeamManager.create_teams(["c1", "c2", "c3"],
                                             base_room="bridge")
        team_id = list(mgr.teams.keys())[0]
        mgr.dispatch_to_room(team_id, "bridge", interior)
        # Tick until repair completes (8s at 4.5 HP/s = ~1.78s progress per tick)
        all_events = []
        for _ in range(100):
            events = mgr.tick(0.1, interior)
            all_events.extend(events)
        breach_events = [e for e in all_events if e.get("type") == "breach_repaired"]
        assert len(breach_events) == 1
        assert breach_events[0]["room_id"] == "bridge"

    def test_get_teams_on_deck(self):
        """get_teams_on_deck returns teams deployed on a given deck."""
        ship = _make_ship()
        interior = _make_interior()
        gle.init(ship, crew_member_ids=["c1", "c2", "c3"],
                 repair_base_room="engine_room")
        gle.dispatch_team(list(gle.get_repair_manager().teams.keys())[0],
                          "engines", interior)
        result = gle.get_teams_on_deck("engineering", interior)
        assert len(result) >= 1


class TestLifeSupportDisplay:
    """C.3.3: Life support efficiency in build_dc_state."""

    def test_ls_efficiency_in_state(self):
        """build_dc_state includes life_support_efficiency when ship provided."""
        ship = _make_ship(efficiency=0.8)
        interior = _make_interior()
        state = glhc.build_dc_state(interior, ship=ship)
        assert "life_support_efficiency" in state
        assert 0.7 < state["life_support_efficiency"] < 0.9

    def test_ls_efficiency_varies_with_damage(self):
        """LS efficiency decreases when systems are damaged."""
        ship = _make_ship(efficiency=1.0)
        state1 = glhc.build_dc_state(_make_interior(), ship=ship)

        ship2 = _make_ship(efficiency=0.5)
        state2 = glhc.build_dc_state(_make_interior(), ship=ship2)

        assert state2["life_support_efficiency"] < state1["life_support_efficiency"]


class TestVentConflict:
    """C.3.4: Vent warning for engineering teams."""

    def test_no_conflict(self):
        """No conflict when no teams on venting deck."""
        interior = _make_interior()
        result = glhc.check_vent_conflict("bridge", interior)
        assert result == []

    def test_conflict_detected(self):
        """Conflict detected when repair team is on venting deck."""
        ship = _make_ship()
        interior = _make_interior()
        gle.init(ship, crew_member_ids=["c1", "c2", "c3"],
                 repair_base_room="engine_room")
        mgr = gle.get_repair_manager()
        team_id = list(mgr.teams.keys())[0]
        # Dispatch to engine_room (engineering deck)
        gle.dispatch_team(team_id, "engines", interior)
        # Check conflict for engine_room (same deck)
        result = glhc.check_vent_conflict("engine_room", interior)
        assert len(result) >= 1

    def test_idle_ignored(self):
        """Idle teams at base are not reported as at risk."""
        ship = _make_ship()
        interior = _make_interior()
        gle.init(ship, crew_member_ids=["c1", "c2", "c3"],
                 repair_base_room="engine_room")
        # Don't dispatch — team stays idle
        result = glhc.check_vent_conflict("engine_room", interior)
        assert result == []


class TestOverclockFireBroadcast:
    """C.3.5: Overclock fire notification to HC."""

    def test_overclock_fire_constant_exists(self):
        """OVERCLOCK_FIRE_INTENSITY and OVERCLOCK_FIRE_CHANCE exist."""
        assert hasattr(glhc, "OVERCLOCK_FIRE_INTENSITY")
        assert hasattr(glhc, "OVERCLOCK_FIRE_CHANCE")


# ===========================================================================
# C.4 Science ↔ Ops
# ===========================================================================


class TestOpsRequestScan:
    """C.4.1: Ops scan request flow."""

    def test_unscanned_ok(self):
        """Request scan succeeds for unscanned enemy."""
        enemy = Enemy(id="e1", type="fighter", x=100, y=100, scan_state="unknown")
        world = _make_world([enemy])
        result = glops.request_scan("e1", world)
        assert result["ok"] is True

    def test_already_scanned(self):
        """Request scan fails for already scanned enemy."""
        enemy = Enemy(id="e1", type="fighter", x=100, y=100, scan_state="scanned")
        world = _make_world([enemy])
        result = glops.request_scan("e1", world)
        assert result["ok"] is False
        assert "already scanned" in result["reason"].lower()

    def test_not_found(self):
        """Request scan fails for nonexistent contact."""
        world = _make_world([])
        result = glops.request_scan("e_missing", world)
        assert result["ok"] is False
        assert "not found" in result["reason"].lower()


class TestScanQuality:
    """C.4.2: scan_detail on Enemy + assessment output gating."""

    def test_detailed_scan_at_high_efficiency(self):
        """Scan at ≥75% efficiency sets scan_detail to 'detailed'."""
        ship = _make_ship(efficiency=0.80)
        enemy = Enemy(id="e1", type="fighter", x=100, y=100)
        world = _make_world([enemy])
        sensors.start_scan("e1")
        # Tick until scan completes.
        for _ in range(200):
            completed = sensors.tick(world, ship, 0.1)
            if completed:
                break
        assert enemy.scan_detail == "detailed"

    def test_basic_scan_at_low_efficiency(self):
        """Scan at <75% efficiency sets scan_detail to 'basic'."""
        ship = _make_ship(efficiency=0.50)
        enemy = Enemy(id="e2", type="fighter", x=100, y=100)
        world = _make_world([enemy])
        sensors.start_scan("e2")
        for _ in range(500):
            completed = sensors.tick(world, ship, 0.1)
            if completed:
                break
        assert enemy.scan_detail == "basic"

    def test_assessment_output_gates_system_health(self):
        """Assessment includes system_health only for detailed scans."""
        ship = _make_ship(efficiency=1.0)
        enemy = Enemy(id="e3", type="fighter", x=100, y=100,
                      scan_state="scanned", scan_detail="basic")
        world = _make_world([enemy])
        # Start assessment
        glops.start_assessment("e3", world, ship)
        # Tick to completion
        for _ in range(2000):
            glops.tick(world, ship, 0.1)
            asmt = glops._assessments.get("e3")
            if asmt and asmt.complete:
                break
        # Collect broadcasts
        broadcasts = glops.pop_pending_broadcasts()
        complete_msgs = [b for b in broadcasts
                         if b[1].get("type") == "assessment_complete"]
        assert len(complete_msgs) >= 1
        msg = complete_msgs[0][1]
        assert msg.get("scan_quality") == "basic"
        assert "system_health" not in msg

    def test_assessment_output_includes_health_for_detailed(self):
        """Assessment includes system_health for detailed scans."""
        ship = _make_ship(efficiency=1.0)
        enemy = Enemy(id="e4", type="fighter", x=100, y=100,
                      scan_state="scanned", scan_detail="detailed")
        world = _make_world([enemy])
        glops.start_assessment("e4", world, ship)
        for _ in range(2000):
            glops.tick(world, ship, 0.1)
            asmt = glops._assessments.get("e4")
            if asmt and asmt.complete:
                break
        broadcasts = glops.pop_pending_broadcasts()
        complete_msgs = [b for b in broadcasts
                         if b[1].get("type") == "assessment_complete"]
        assert len(complete_msgs) >= 1
        msg = complete_msgs[0][1]
        assert msg.get("scan_quality") == "detailed"
        assert "system_health" in msg


# ===========================================================================
# C.5 Helm ↔ Multiple Stations
# ===========================================================================


class TestHighSpeedTorpedoBonus:
    """C.5.2: High-speed torpedo damage bonus."""

    def test_below_threshold(self):
        """No bonus when throttle < 0.75."""
        ship = _make_ship(throttle=0.5)
        assert glw.get_high_speed_torpedo_bonus(ship) == 0.0

    def test_above_threshold(self):
        """5% bonus when throttle >= 0.75."""
        ship = _make_ship(throttle=0.80)
        assert glw.get_high_speed_torpedo_bonus(ship) == glw.HIGH_SPEED_TORPEDO_BONUS

    def test_at_threshold(self):
        """5% bonus when throttle == 0.75."""
        ship = _make_ship(throttle=0.75)
        assert glw.get_high_speed_torpedo_bonus(ship) == glw.HIGH_SPEED_TORPEDO_BONUS

    def test_constants_exist(self):
        """Constants are defined."""
        assert glw.HIGH_SPEED_THRESHOLD == 0.75
        assert glw.HIGH_SPEED_TORPEDO_BONUS == 0.05


class TestThreatBearing:
    """C.5.4: Threat bearing indicator."""

    def test_no_enemies(self):
        """Returns None when no enemies exist."""
        from server.game_loop import _compute_threat_bearing
        ship = _make_ship(heading=0.0, x=0.0, y=0.0)
        world = _make_world([])
        assert _compute_threat_bearing(ship, world) is None

    def test_enemy_ahead(self):
        """Nearest enemy directly ahead → facing 'fore'."""
        from server.game_loop import _compute_threat_bearing
        ship = _make_ship(heading=0.0, x=0.0, y=0.0)
        enemy = Enemy(id="e1", type="fighter", x=0.0, y=-1000.0)  # directly ahead (north)
        world = _make_world([enemy])
        result = _compute_threat_bearing(ship, world)
        assert result is not None
        assert result["enemy_id"] == "e1"
        assert result["facing"] == "fore"

    def test_nearest_used(self):
        """Multiple enemies — nearest is used."""
        from server.game_loop import _compute_threat_bearing
        ship = _make_ship(heading=0.0, x=0.0, y=0.0)
        near = Enemy(id="near", type="fighter", x=100.0, y=0.0)
        far = Enemy(id="far", type="fighter", x=10000.0, y=0.0)
        world = _make_world([far, near])
        result = _compute_threat_bearing(ship, world)
        assert result["enemy_id"] == "near"

    def test_facing_correct(self):
        """Enemy behind → facing 'aft'."""
        from server.game_loop import _compute_threat_bearing
        ship = _make_ship(heading=0.0, x=0.0, y=0.0)
        enemy = Enemy(id="e1", type="fighter", x=0.0, y=1000.0)  # directly behind (south)
        world = _make_world([enemy])
        result = _compute_threat_bearing(ship, world)
        assert result is not None
        assert result["facing"] == "aft"


# ===========================================================================
# Serialisation round-trips
# ===========================================================================


class TestSerialisation:
    """Verify new state survives serialise/deserialise."""

    def test_fire_suppression_power_roundtrip(self):
        """Fire suppression power flag survives save/load."""
        glhc._fire_suppression_powered = False
        data = glhc.serialise()
        glhc.reset()
        assert glhc._fire_suppression_powered is True
        glhc.deserialise(data)
        assert glhc._fire_suppression_powered is False

    def test_scan_detail_roundtrip(self):
        """scan_detail survives enemy serialise/deserialise."""
        from server.save_system import _serialise_entities, _deserialise_entities
        enemy = Enemy(id="e1", type="fighter", x=0, y=0,
                      scan_detail="detailed")
        world = World(enemies=[enemy])
        data = _serialise_entities(world)
        assert data["enemies"][0]["scan_detail"] == "detailed"
        world2 = World()
        _deserialise_entities(data, world2)
        assert world2.enemies[0].scan_detail == "detailed"
