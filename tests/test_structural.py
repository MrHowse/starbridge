"""Tests for v0.08 B.5: Structural Integrity System."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

import pytest

import server.game_loop_hazard_control as glhc
import server.game_loop_atmosphere as glatm
from server.models.interior import ShipInterior, Room, make_default_interior


def fresh_interior():
    return make_default_interior()


@dataclass
class FakeDeckCrew:
    deck_name: str
    total: int = 6
    active: int = 6
    injured: int = 0
    critical: int = 0
    dead: int = 0

    @property
    def crew_factor(self) -> float:
        if self.total == 0:
            return 1.0
        effective = self.active + (self.injured * 0.5)
        return min(effective / self.total, 1.0)

    def apply_casualties(self, count: int) -> None:
        from_active = min(count, self.active)
        self.active -= from_active
        self.injured += from_active


class FakeCrewRoster:
    def __init__(self):
        self.decks = {
            "bridge": FakeDeckCrew("bridge"),
            "sensors": FakeDeckCrew("sensors"),
            "weapons": FakeDeckCrew("weapons"),
            "shields": FakeDeckCrew("shields"),
            "medical": FakeDeckCrew("medical"),
            "engineering": FakeDeckCrew("engineering"),
        }

    def apply_casualties(self, deck_name: str, count: int) -> None:
        deck = self.decks.get(deck_name)
        if deck is not None:
            deck.apply_casualties(count)


@dataclass
class FakeShipSystem:
    name: str
    power: float = 100.0
    health: float = 100.0
    room_id: str = ""


class FakeShip:
    def __init__(self):
        self.crew = FakeCrewRoster()
        self.systems = {}


def setup_function():
    glhc.reset()
    glatm.reset()


# ---------------------------------------------------------------------------
# B.5.1 Section Model
# ---------------------------------------------------------------------------


def test_init_sections_creates_correct_count():
    interior = fresh_interior()
    glhc.init_sections(interior)
    sections = glhc.get_sections()
    # Frigate: 5 decks × 4 rooms = 20 rooms → 10 sections (2 rooms each)
    assert len(sections) == 10


def test_init_sections_two_rooms_per_section():
    interior = fresh_interior()
    glhc.init_sections(interior)
    for sec in glhc.get_sections().values():
        assert len(sec.room_ids) == 2


def test_room_to_section_lookup():
    interior = fresh_interior()
    glhc.init_sections(interior)
    for room_id in interior.rooms:
        sec = glhc.get_section_for_room(room_id)
        assert sec is not None
        assert room_id in sec.room_ids


def test_section_adjacency_same_deck():
    interior = fresh_interior()
    glhc.init_sections(interior)
    sections = glhc.get_sections()
    # deck1_a and deck1_b should be adjacent (same deck)
    assert "deck1_b" in glhc._section_adjacency.get("deck1_a", [])
    assert "deck1_a" in glhc._section_adjacency.get("deck1_b", [])


def test_sections_start_at_100():
    interior = fresh_interior()
    glhc.init_sections(interior)
    for sec in glhc.get_sections().values():
        assert sec.integrity == 100.0
        assert not sec.collapsed


# ---------------------------------------------------------------------------
# B.5.1 Structural Damage
# ---------------------------------------------------------------------------


def test_beam_combat_damage():
    interior = fresh_interior()
    glhc.init_sections(interior)
    glhc._rng = random.Random(42)
    events = glhc.apply_combat_structural_damage(interior, "beam")
    # At least one section should have taken damage
    damaged = [s for s in glhc.get_sections().values() if s.integrity < 100.0]
    assert len(damaged) == 1
    sec = damaged[0]
    assert 90.0 <= sec.integrity <= 95.0  # 5-10% damage


def test_torpedo_combat_damage():
    interior = fresh_interior()
    glhc.init_sections(interior)
    glhc._rng = random.Random(42)
    events = glhc.apply_combat_structural_damage(interior, "torpedo")
    damaged = [s for s in glhc.get_sections().values() if s.integrity < 100.0]
    assert len(damaged) == 1
    sec = damaged[0]
    assert 75.0 <= sec.integrity <= 85.0  # 15-25% damage


def test_breach_structural_damage():
    interior = fresh_interior()
    glhc.init_sections(interior)
    rid = next(iter(interior.rooms))
    events = glhc.apply_breach_structural_damage(rid)
    sec = glhc.get_section_for_room(rid)
    assert sec is not None
    assert sec.integrity == pytest.approx(90.0)  # -10%


def test_explosion_structural_damage():
    interior = fresh_interior()
    glhc.init_sections(interior)
    glhc._rng = random.Random(42)
    rid = next(iter(interior.rooms))
    events = glhc.apply_explosion_structural_damage(rid, interior)
    sec = glhc.get_section_for_room(rid)
    assert sec is not None
    assert 70.0 <= sec.integrity <= 80.0  # -20 to -30%


def test_fire_intensity_4_damages_section():
    interior = fresh_interior()
    glhc.init_sections(interior)
    rid = next(iter(interior.rooms))
    # Start a fire at intensity 4
    glhc.start_fire(rid, 4, interior)
    # Tick for 30 seconds to trigger fire structural damage
    for _ in range(300):
        glhc.tick(interior, 0.1)
    sec = glhc.get_section_for_room(rid)
    assert sec is not None
    assert sec.integrity < 100.0  # Should have taken fire structural damage


def test_collapsed_section_no_further_damage():
    interior = fresh_interior()
    glhc.init_sections(interior)
    rid = next(iter(interior.rooms))
    sec = glhc.get_section_for_room(rid)
    sec.collapsed = True
    sec.integrity = 0.0
    events = glhc.apply_breach_structural_damage(rid)
    assert sec.integrity == 0.0  # No change


# ---------------------------------------------------------------------------
# B.5.1 Severity States
# ---------------------------------------------------------------------------


def test_normal_state():
    interior = fresh_interior()
    glhc.init_sections(interior)
    sec = next(iter(glhc.get_sections().values()))
    sec.integrity = 80.0
    assert glhc.get_section_state(sec) == "normal"


def test_stressed_state():
    interior = fresh_interior()
    glhc.init_sections(interior)
    sec = next(iter(glhc.get_sections().values()))
    sec.integrity = 60.0
    assert glhc.get_section_state(sec) == "stressed"


def test_weakened_state():
    interior = fresh_interior()
    glhc.init_sections(interior)
    sec = next(iter(glhc.get_sections().values()))
    sec.integrity = 40.0
    assert glhc.get_section_state(sec) == "weakened"


def test_critical_state():
    interior = fresh_interior()
    glhc.init_sections(interior)
    sec = next(iter(glhc.get_sections().values()))
    sec.integrity = 10.0
    assert glhc.get_section_state(sec) == "critical"


def test_collapsed_state():
    interior = fresh_interior()
    glhc.init_sections(interior)
    sec = next(iter(glhc.get_sections().values()))
    sec.collapsed = True
    sec.integrity = 0.0
    assert glhc.get_section_state(sec) == "collapsed"


def test_weakened_collapse_chance():
    """Weakened sections have a 15% chance of collapse on each hit."""
    interior = fresh_interior()
    glhc.init_sections(interior)
    glatm.init_atmosphere(interior)
    # Use a seeded RNG that will produce a value < 0.15
    glhc._rng = random.Random(1)
    sec = list(glhc.get_sections().values())[0]
    sec.integrity = 30.0  # weakened range
    # Apply many small hits to eventually trigger collapse
    collapsed = False
    for _ in range(100):
        if sec.collapsed:
            collapsed = True
            break
        glhc._apply_section_damage(sec, 1.0, interior)
    # With 100 tries at 15% chance, very likely to have collapsed
    assert collapsed


def test_critical_collapse_chance():
    """Critical sections have a 40% chance of collapse on each hit."""
    interior = fresh_interior()
    glhc.init_sections(interior)
    glatm.init_atmosphere(interior)
    glhc._rng = random.Random(42)
    sec = list(glhc.get_sections().values())[0]
    sec.integrity = 5.0  # critical range
    collapsed = False
    for _ in range(50):
        if sec.collapsed:
            collapsed = True
            break
        glhc._apply_section_damage(sec, 0.5, interior)
    assert collapsed


def test_crew_efficiency_penalties():
    interior = fresh_interior()
    glhc.init_sections(interior)
    sections = list(glhc.get_sections().values())
    # Set one section to weakened
    sections[0].integrity = 40.0
    penalties = glhc.get_structural_crew_penalties()
    assert sections[0].deck_name in penalties
    assert penalties[sections[0].deck_name] == pytest.approx(0.10)

    # Set another to critical
    sections[0].integrity = 10.0
    penalties = glhc.get_structural_crew_penalties()
    assert penalties[sections[0].deck_name] == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# B.5.2 Collapse Effects
# ---------------------------------------------------------------------------


def test_collapse_destroys_equipment():
    interior = fresh_interior()
    glhc.init_sections(interior)
    glatm.init_atmosphere(interior)
    ship = FakeShip()
    # Map a system to a room in the first section
    sec = list(glhc.get_sections().values())[0]
    rid = sec.room_ids[0]
    sys_obj = FakeShipSystem("test_sys", room_id=rid)
    ship.systems["test_sys"] = sys_obj

    sec.integrity = 0.5  # nearly collapsed
    glhc._rng = random.Random(42)
    # Force collapse by reducing to 0
    events = glhc._collapse_section(sec, interior, ship)
    assert sec.collapsed
    assert sys_obj.health == 0.0


def test_collapse_creates_breach():
    interior = fresh_interior()
    glhc.init_sections(interior)
    glatm.init_atmosphere(interior)
    sec = list(glhc.get_sections().values())[0]
    events = glhc._collapse_section(sec, interior)
    # Each room in section should have a breach
    for rid in sec.room_ids:
        assert rid in glatm._breaches


def test_collapse_creates_fire():
    interior = fresh_interior()
    glhc.init_sections(interior)
    glatm.init_atmosphere(interior)
    # Use seeded RNG where fire chance (0.80) will trigger
    glhc._rng = random.Random(42)
    sec = list(glhc.get_sections().values())[0]
    events = glhc._collapse_section(sec, interior)
    # With 80% chance per room, at least one fire should exist
    fires = glhc.get_fires()
    fire_in_section = [rid for rid in sec.room_ids if rid in fires]
    assert len(fire_in_section) >= 1


def test_collapse_crew_casualties():
    interior = fresh_interior()
    glhc.init_sections(interior)
    glatm.init_atmosphere(interior)
    ship = FakeShip()
    sec = list(glhc.get_sections().values())[0]
    deck_name = sec.deck_name
    initial_active = ship.crew.decks[deck_name].active
    events = glhc._collapse_section(sec, interior, ship)
    # Should have lost crew: 2 per room in section
    expected_casualties = len(sec.room_ids) * 2
    assert ship.crew.decks[deck_name].active == initial_active - expected_casualties


def test_cascade_adjacent_sections():
    interior = fresh_interior()
    glhc.init_sections(interior)
    glatm.init_atmosphere(interior)
    sections = list(glhc.get_sections().values())
    # Collapse first section — adjacent should take -15%
    sec = sections[0]
    adjacent_ids = glhc._section_adjacency.get(sec.id, [])
    assert len(adjacent_ids) > 0

    events = glhc._collapse_section(sec, interior)
    assert sec.collapsed
    for adj_id in adjacent_ids:
        adj = glhc.get_sections()[adj_id]
        if not adj.collapsed:
            assert adj.integrity <= 100.0 - glhc.COLLAPSE_CASCADE_DMG + 0.01


# ---------------------------------------------------------------------------
# B.5.2 Reinforcement
# ---------------------------------------------------------------------------


def test_reinforce_dispatch():
    interior = fresh_interior()
    glhc.init_sections(interior)
    ship = FakeShip()
    sec = list(glhc.get_sections().values())[0]
    sec.integrity = 50.0
    result = glhc.reinforce_section(sec.id, ship)
    assert result is True
    assert sec.id in glhc._reinforcement_teams


def test_reinforce_cancel():
    interior = fresh_interior()
    glhc.init_sections(interior)
    ship = FakeShip()
    sec = list(glhc.get_sections().values())[0]
    sec.integrity = 50.0
    glhc.reinforce_section(sec.id, ship)
    result = glhc.cancel_reinforcement(sec.id)
    assert result is True
    assert sec.id not in glhc._reinforcement_teams


def test_reinforce_adds_integrity():
    interior = fresh_interior()
    glhc.init_sections(interior)
    ship = FakeShip()
    sec = list(glhc.get_sections().values())[0]
    sec.integrity = 50.0
    glhc.reinforce_section(sec.id, ship)
    events = []
    # Tick for 30 seconds
    for _ in range(300):
        events.extend(glhc.tick(interior, 0.1, ship=ship))
    assert sec.integrity == pytest.approx(60.0)  # +10%
    assert any(e["type"] == "reinforcement_cycle" for e in events)


def test_reinforce_caps_at_80():
    interior = fresh_interior()
    glhc.init_sections(interior)
    ship = FakeShip()
    sec = list(glhc.get_sections().values())[0]
    sec.integrity = 75.0
    glhc.reinforce_section(sec.id, ship)
    # Tick for 60 seconds (2 cycles)
    for _ in range(600):
        glhc.tick(interior, 0.1, ship=ship)
    assert sec.integrity == pytest.approx(80.0)
    # Reinforcement should have stopped automatically
    assert sec.id not in glhc._reinforcement_teams


def test_reinforce_requires_crew():
    interior = fresh_interior()
    glhc.init_sections(interior)
    ship = FakeShip()
    sec = list(glhc.get_sections().values())[0]
    sec.integrity = 50.0
    # Set deck crew to only 1 active (below minimum 2)
    ship.crew.decks[sec.deck_name].active = 1
    result = glhc.reinforce_section(sec.id, ship)
    assert result is False


def test_reinforce_fails_on_collapsed():
    interior = fresh_interior()
    glhc.init_sections(interior)
    ship = FakeShip()
    sec = list(glhc.get_sections().values())[0]
    sec.collapsed = True
    sec.integrity = 0.0
    result = glhc.reinforce_section(sec.id, ship)
    assert result is False


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


def test_serialise_deserialise_roundtrip():
    interior = fresh_interior()
    glhc.init_sections(interior)
    sec = list(glhc.get_sections().values())[0]
    sec.integrity = 42.5
    ship = FakeShip()
    glhc.reinforce_section(sec.id, ship)

    data = glhc.serialise()
    glhc.reset()
    glhc.deserialise(data)
    glhc.rebuild_adjacency(interior)

    sections = glhc.get_sections()
    assert len(sections) > 0
    restored_sec = sections[sec.id]
    assert restored_sec.integrity == pytest.approx(42.5)
    assert sec.id in glhc._reinforcement_teams
    # Adjacency should be rebuilt
    assert len(glhc._section_adjacency) > 0


def test_build_dc_state_includes_sections():
    interior = fresh_interior()
    glhc.init_sections(interior)
    state = glhc.build_dc_state(interior)
    assert "sections" in state
    assert len(state["sections"]) == 10
    first = next(iter(state["sections"].values()))
    assert "integrity" in first
    assert "state" in first
    assert "room_ids" in first
    assert "collapsed" in first
    assert "reinforcing" in first


def test_docking_restores_integrity():
    interior = fresh_interior()
    glhc.init_sections(interior)
    sec = list(glhc.get_sections().values())[0]
    sec.integrity = 30.0
    glhc.restore_all_sections()
    assert sec.integrity == 100.0


def test_docking_skips_collapsed():
    interior = fresh_interior()
    glhc.init_sections(interior)
    sec = list(glhc.get_sections().values())[0]
    sec.collapsed = True
    sec.integrity = 0.0
    glhc.restore_all_sections()
    assert sec.integrity == 0.0  # Still collapsed


# ---------------------------------------------------------------------------
# Ops Warning
# ---------------------------------------------------------------------------


def test_ops_warning_below_50():
    interior = fresh_interior()
    glhc.init_sections(interior)
    sec = list(glhc.get_sections().values())[0]
    sec.integrity = 55.0
    # Apply 10% damage — should cross 50% threshold
    events = glhc._apply_section_damage(sec, 10.0)
    assert any(e["type"] == "structural_warning" for e in events)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_structural_constants():
    assert glhc.STRUCT_NORMAL_MIN == 76.0
    assert glhc.STRUCT_STRESSED_MIN == 51.0
    assert glhc.STRUCT_WEAKENED_MIN == 26.0
    assert glhc.STRUCT_CRITICAL_MIN == 1.0
    assert glhc.STRUCT_WEAKENED_COLLAPSE_CHANCE == 0.15
    assert glhc.STRUCT_CRITICAL_COLLAPSE_CHANCE == 0.40
    assert glhc.STRUCT_BEAM_DMG_MIN == 5.0
    assert glhc.STRUCT_BEAM_DMG_MAX == 10.0
    assert glhc.STRUCT_TORPEDO_DMG_MIN == 15.0
    assert glhc.STRUCT_TORPEDO_DMG_MAX == 25.0
    assert glhc.STRUCT_BREACH_DMG == 10.0
    assert glhc.REINFORCE_INTERVAL == 30.0
    assert glhc.REINFORCE_AMOUNT == 10.0
    assert glhc.REINFORCE_MAX == 80.0
    assert glhc.REINFORCE_MIN_CREW == 2
    assert glhc.COLLAPSE_FIRE_CHANCE == 0.80
    assert glhc.COLLAPSE_CASCADE_DMG == 15.0
