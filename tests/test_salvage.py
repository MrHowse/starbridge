"""Tests for Salvage System — v0.07 Phase 6.5."""
from __future__ import annotations

import random

import pytest

from server.models.salvage import (
    BOOBY_TRAP_CHANCE,
    DIRECT_USE_EFFICIENCY,
    REACTOR_BLAST_RANGE,
    REACTOR_DAMAGE_MAX,
    REACTOR_DAMAGE_MIN,
    REACTOR_TIMER,
    SALVAGE_MAX_SPEED,
    SALVAGE_RANGE,
    SCAN_DURATION,
    TRAP_TEAM_DAMAGE,
    UNSTABLE_REACTOR_CHANCE,
    WRECK_DESPAWN_TIME,
    SalvageItem,
    Wreck,
    generate_salvage_manifest,
)
from server.models.ship import Ship
from server.models.resources import ResourceStore
import server.game_loop_salvage as glsalv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ship(x: float = 1000.0, y: float = 1000.0, velocity: float = 0.0) -> Ship:
    ship = Ship()
    ship.x = x
    ship.y = y
    ship.velocity = velocity
    ship.hull = 100.0
    ship.cargo_capacity = 50.0
    ship.cargo = {}
    ship.resources = ResourceStore(
        fuel=100.0, fuel_max=500.0,
        medical_supplies=10.0, medical_supplies_max=30.0,
        repair_materials=10.0, repair_materials_max=50.0,
        drone_fuel=50.0, drone_fuel_max=100.0,
        drone_parts=3.0, drone_parts_max=10.0,
        ammunition=10.0, ammunition_max=50.0,
        provisions=100.0, provisions_max=200.0,
    )
    return ship


def _reset():
    glsalv.reset()
    glsalv._rng = random.Random(42)


# ===========================================================================
# Model tests
# ===========================================================================


class TestSalvageModel:
    """Wreck/SalvageItem creation, loot generation, serialisation."""

    def test_wreck_creation(self):
        w = Wreck(id="w1", x=100, y=200, source_type="enemy",
                  source_id="e1", enemy_type="cruiser")
        assert w.scan_state == "unscanned"
        assert w.despawn_timer == WRECK_DESPAWN_TIME
        assert w.salvage_state == "idle"

    def test_salvage_item_creation(self):
        item = SalvageItem(id="i1", name="Fuel", item_type="fuel",
                           quantity=50, cargo_size=2, salvage_time=30,
                           value=40, is_direct_use=True)
        assert item.salvaged is False
        assert item.is_direct_use is True

    def test_generate_manifest(self):
        rng = random.Random(99)
        items = generate_salvage_manifest("cruiser", rng)
        assert len(items) > 0
        for item in items:
            assert item.id.startswith("salvage_item_")
            assert item.quantity > 0

    def test_wreck_to_from_dict(self):
        items = generate_salvage_manifest("fighter", random.Random(1))
        w = Wreck(id="w2", x=50, y=60, source_type="enemy",
                  source_id="e2", enemy_type="fighter",
                  salvage_manifest=items, booby_trapped=True)
        d = w.to_dict()
        w2 = Wreck.from_dict(d)
        assert w2.id == "w2"
        assert w2.booby_trapped is True
        assert len(w2.salvage_manifest) == len(items)
        assert w2.salvage_manifest[0].name == items[0].name

    def test_salvage_item_to_from_dict(self):
        item = SalvageItem(id="i1", name="Core", item_type="data_core",
                           quantity=1, cargo_size=0.5, salvage_time=45,
                           value=120, is_direct_use=False, salvaged=True)
        d = item.to_dict()
        item2 = SalvageItem.from_dict(d)
        assert item2.salvaged is True
        assert item2.item_type == "data_core"


# ===========================================================================
# Assessment tests
# ===========================================================================


class TestAssessment:
    """Scanning wrecks to reveal manifests."""

    def setup_method(self):
        _reset()

    def test_start_scan(self):
        ship = _make_ship(x=100, y=100)
        w = glsalv.spawn_wreck("enemy", "e1", "cruiser", 100, 100)
        result = glsalv.assess_salvage(w.id, ship)
        assert result["ok"] is True
        assert w.scan_state == "scanning"
        assert w.scan_progress == 0.0

    def test_out_of_range_rejected(self):
        ship = _make_ship(x=0, y=0)
        w = glsalv.spawn_wreck("enemy", "e1", "cruiser", 5000, 5000)
        result = glsalv.assess_salvage(w.id, ship)
        assert result["ok"] is False
        assert result["error"] == "out_of_range"

    def test_too_fast_rejected(self):
        ship = _make_ship(x=100, y=100, velocity=50.0)
        w = glsalv.spawn_wreck("enemy", "e1", "cruiser", 100, 100)
        result = glsalv.assess_salvage(w.id, ship)
        assert result["ok"] is False
        assert result["error"] == "too_fast"

    def test_scan_progress_tick(self):
        ship = _make_ship(x=100, y=100)
        w = glsalv.spawn_wreck("enemy", "e1", "cruiser", 100, 100)
        glsalv.assess_salvage(w.id, ship)
        # Tick halfway through scan duration.
        glsalv.tick(ship, SCAN_DURATION / 2)
        assert w.scan_state == "scanning"
        assert w.scan_progress == pytest.approx(0.5, abs=0.01)

    def test_scan_completion_generates_manifest(self):
        ship = _make_ship(x=100, y=100)
        w = glsalv.spawn_wreck("enemy", "e1", "cruiser", 100, 100)
        glsalv.assess_salvage(w.id, ship)
        glsalv.tick(ship, SCAN_DURATION + 0.1)
        assert w.scan_state == "scanned"
        assert len(w.salvage_manifest) > 0
        events = glsalv.pop_pending_events()
        event_types = [e["type"] for e in events]
        assert "assessment_complete" in event_types


# ===========================================================================
# Risk tests
# ===========================================================================


class TestRisks:
    """Booby trap and reactor mechanics."""

    def setup_method(self):
        _reset()

    def test_trap_detected_on_full_scan(self):
        ship = _make_ship(x=100, y=100)
        w = glsalv.spawn_wreck("enemy", "e1", "fighter", 100, 100)
        w.booby_trapped = True
        glsalv.assess_salvage(w.id, ship)
        glsalv.tick(ship, SCAN_DURATION + 0.1)
        assert w.trap_detected is True

    def test_trap_undetected_on_partial_scan(self):
        ship = _make_ship(x=100, y=100)
        w = glsalv.spawn_wreck("enemy", "e1", "fighter", 100, 100)
        w.booby_trapped = True
        glsalv.assess_salvage(w.id, ship)
        glsalv.tick(ship, SCAN_DURATION / 2)
        assert w.trap_detected is False  # scan not yet complete

    def test_trap_damage_on_begin_salvage(self):
        ship = _make_ship(x=100, y=100)
        w = glsalv.spawn_wreck("enemy", "e1", "fighter", 100, 100)
        w.booby_trapped = True
        # Force scan complete without detecting trap.
        w.scan_state = "scanned"
        w.trap_detected = False
        w.salvage_manifest = generate_salvage_manifest("fighter", random.Random(1))
        item_ids = [item.id for item in w.salvage_manifest]
        glsalv.select_items(w.id, item_ids)
        hull_before = ship.hull
        glsalv.begin_salvage(w.id, ship)
        assert ship.hull == pytest.approx(hull_before - TRAP_TEAM_DAMAGE, abs=0.1)
        events = glsalv.pop_pending_events()
        event_types = [e["type"] for e in events]
        assert "trap_triggered" in event_types

    def test_reactor_countdown_and_detonation(self):
        ship = _make_ship(x=100, y=100)
        w = glsalv.spawn_wreck("enemy", "e1", "cruiser", 100, 100)
        w.unstable_reactor = True
        w.scan_state = "scanned"
        w.reactor_detected = False
        w.salvage_manifest = generate_salvage_manifest("cruiser", random.Random(1))
        item_ids = [item.id for item in w.salvage_manifest]
        glsalv.select_items(w.id, item_ids)
        hull_before = ship.hull
        glsalv.begin_salvage(w.id, ship)
        assert w.reactor_armed is True
        assert w.reactor_timer == pytest.approx(REACTOR_TIMER, abs=0.1)
        # Tick past reactor timer.
        glsalv.tick(ship, REACTOR_TIMER + 1.0)
        assert ship.hull < hull_before
        events = glsalv.pop_pending_events()
        event_types = [e["type"] for e in events]
        assert "reactor_detonation" in event_types


# ===========================================================================
# Salvage execution tests
# ===========================================================================


class TestSalvageExecution:
    """Item selection, extraction, transfer."""

    def setup_method(self):
        _reset()

    def test_select_items(self):
        ship = _make_ship(x=100, y=100)
        w = glsalv.spawn_wreck("enemy", "e1", "destroyer", 100, 100)
        w.scan_state = "scanned"
        w.salvage_manifest = generate_salvage_manifest("destroyer", random.Random(1))
        item_ids = [w.salvage_manifest[0].id]
        result = glsalv.select_items(w.id, item_ids)
        assert result["ok"] is True
        assert w.salvage_queue == item_ids

    def test_begin_and_complete_salvage(self):
        ship = _make_ship(x=100, y=100)
        w = glsalv.spawn_wreck("enemy", "e1", "fighter", 100, 100)
        w.scan_state = "scanned"
        w.salvage_manifest = generate_salvage_manifest("fighter", random.Random(1))
        item_ids = [item.id for item in w.salvage_manifest]
        glsalv.select_items(w.id, item_ids)
        glsalv.begin_salvage(w.id, ship)
        assert glsalv.is_salvaging() is True
        # Tick enough to complete all items.
        total_time = sum(item.salvage_time for item in w.salvage_manifest)
        glsalv.tick(ship, total_time + 1.0)
        assert w.salvage_state == "complete"
        assert glsalv.is_salvaging() is False

    def test_direct_use_70_percent(self):
        ship = _make_ship(x=100, y=100)
        w = glsalv.spawn_wreck("enemy", "e1", "fighter", 100, 100)
        w.scan_state = "scanned"
        # Create a single direct-use fuel item.
        fuel_item = SalvageItem(
            id="test_fuel", name="Fuel", item_type="fuel",
            quantity=100.0, cargo_size=1.0, salvage_time=5.0,
            value=20.0, is_direct_use=True,
        )
        w.salvage_manifest = [fuel_item]
        glsalv.select_items(w.id, ["test_fuel"])
        fuel_before = ship.resources.get("fuel")
        glsalv.begin_salvage(w.id, ship)
        glsalv.tick(ship, 6.0)
        fuel_after = ship.resources.get("fuel")
        expected = round(100.0 * DIRECT_USE_EFFICIENCY, 1)
        assert fuel_after == pytest.approx(fuel_before + expected, abs=0.2)

    def test_cargo_transfer(self):
        ship = _make_ship(x=100, y=100)
        w = glsalv.spawn_wreck("enemy", "e1", "scout", 100, 100)
        w.scan_state = "scanned"
        cargo_item = SalvageItem(
            id="test_comp", name="Components", item_type="components",
            quantity=5.0, cargo_size=2.0, salvage_time=5.0,
            value=80.0, is_direct_use=False,
        )
        w.salvage_manifest = [cargo_item]
        glsalv.select_items(w.id, ["test_comp"])
        glsalv.begin_salvage(w.id, ship)
        glsalv.tick(ship, 6.0)
        assert ship.cargo.get("components", 0) == 5.0

    def test_cancel_mid_salvage(self):
        ship = _make_ship(x=100, y=100)
        w = glsalv.spawn_wreck("enemy", "e1", "destroyer", 100, 100)
        w.scan_state = "scanned"
        w.salvage_manifest = generate_salvage_manifest("destroyer", random.Random(1))
        item_ids = [item.id for item in w.salvage_manifest]
        glsalv.select_items(w.id, item_ids)
        glsalv.begin_salvage(w.id, ship)
        # Tick for just a bit — first item shouldn't be done.
        glsalv.tick(ship, 1.0)
        result = glsalv.cancel_salvage(w.id)
        assert result["ok"] is True
        assert w.salvage_state == "aborted"
        assert glsalv.is_salvaging() is False


# ===========================================================================
# Integration tests
# ===========================================================================


class TestIntegration:
    """End-to-end integration: spawn, despawn, save round-trip, speed cancel."""

    def setup_method(self):
        _reset()

    def test_wreck_spawns_on_enemy_death(self):
        w = glsalv.spawn_wreck("enemy", "e1", "cruiser", 500, 600)
        wrecks = glsalv.get_wrecks()
        assert len(wrecks) == 1
        assert wrecks[0].id == w.id
        assert wrecks[0].x == 500

    def test_despawn_timer(self):
        ship = _make_ship(x=0, y=0)
        w = glsalv.spawn_wreck("enemy", "e1", "fighter", 50000, 50000)
        glsalv.pop_pending_events()  # clear spawn event
        # Tick almost to despawn.
        glsalv.tick(ship, WRECK_DESPAWN_TIME - 1.0)
        assert len(glsalv.get_wrecks()) == 1
        # Tick past despawn.
        glsalv.tick(ship, 2.0)
        assert len(glsalv.get_wrecks()) == 0
        events = glsalv.pop_pending_events()
        event_types = [e["type"] for e in events]
        assert "wreck_despawned" in event_types

    def test_save_round_trip(self):
        glsalv.spawn_wreck("enemy", "e1", "cruiser", 100, 200)
        glsalv.spawn_wreck("derelict", "d1", "derelict", 300, 400)
        data = glsalv.serialise()
        glsalv.reset()
        assert len(glsalv.get_wrecks()) == 0
        glsalv.deserialise(data)
        wrecks = glsalv.get_wrecks()
        assert len(wrecks) == 2
        assert wrecks[0].enemy_type == "cruiser"
        assert wrecks[1].source_type == "derelict"

    def test_speed_check_cancels_salvage(self):
        ship = _make_ship(x=100, y=100)
        w = glsalv.spawn_wreck("enemy", "e1", "fighter", 100, 100)
        w.scan_state = "scanned"
        w.salvage_manifest = generate_salvage_manifest("fighter", random.Random(1))
        item_ids = [item.id for item in w.salvage_manifest]
        glsalv.select_items(w.id, item_ids)
        glsalv.begin_salvage(w.id, ship)
        assert glsalv.is_salvaging() is True
        # Ship speeds up.
        ship.velocity = 100.0
        glsalv.tick(ship, 0.1)
        assert w.salvage_state == "aborted"
        assert glsalv.is_salvaging() is False


# ===========================================================================
# Edge case tests
# ===========================================================================


class TestEdgeCases:
    """Cargo overflow, multiple wrecks, wreck removal."""

    def setup_method(self):
        _reset()

    def test_cargo_capacity_exceeded(self):
        ship = _make_ship(x=100, y=100)
        ship.cargo_capacity = 1.0  # very small
        ship.cargo = {"components": 0.5}
        w = glsalv.spawn_wreck("enemy", "e1", "scout", 100, 100)
        w.scan_state = "scanned"
        cargo_item = SalvageItem(
            id="big_item", name="Big", item_type="components",
            quantity=10.0, cargo_size=5.0, salvage_time=5.0,
            value=100.0, is_direct_use=False,
        )
        w.salvage_manifest = [cargo_item]
        glsalv.select_items(w.id, ["big_item"])
        glsalv.begin_salvage(w.id, ship)
        glsalv.tick(ship, 6.0)
        # Item marked salvaged but cargo_full event emitted.
        events = glsalv.pop_pending_events()
        event_types = [e["type"] for e in events]
        assert "cargo_full" in event_types

    def test_multiple_wrecks_one_at_a_time(self):
        ship = _make_ship(x=100, y=100)
        w1 = glsalv.spawn_wreck("enemy", "e1", "fighter", 100, 100)
        w2 = glsalv.spawn_wreck("enemy", "e2", "fighter", 200, 100)
        w1.scan_state = "scanned"
        w1.salvage_manifest = generate_salvage_manifest("fighter", random.Random(1))
        w2.scan_state = "scanned"
        w2.salvage_manifest = generate_salvage_manifest("fighter", random.Random(2))
        # Select and begin on w1.
        glsalv.select_items(w1.id, [w1.salvage_manifest[0].id])
        glsalv.begin_salvage(w1.id, ship)
        # Trying to begin on w2 should fail.
        glsalv.select_items(w2.id, [w2.salvage_manifest[0].id])
        result = glsalv.begin_salvage(w2.id, ship)
        assert result["ok"] is False
        assert result["error"] == "salvage_op_active"

    def test_wreck_removal(self):
        w = glsalv.spawn_wreck("enemy", "e1", "fighter", 100, 100)
        assert len(glsalv.get_wrecks()) == 1
        removed = glsalv.remove_wreck(w.id)
        assert removed is True
        assert len(glsalv.get_wrecks()) == 0
        assert glsalv.remove_wreck("nonexistent") is False
