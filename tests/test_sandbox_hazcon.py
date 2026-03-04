"""Tests for sandbox Hazard Control event generators (v0.08).

Validates fire, breach, radiation, and structural stress events generated
by the sandbox activity generator for the Hazard Control station.
"""
from __future__ import annotations

import pytest

import server.game_loop_sandbox as glsb
import server.game_loop_hazard_control as glhc
import server.game_loop_atmosphere as glatm  # noqa: F811
from server.models.world import World
from server.models.interior import make_default_interior


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_world() -> World:
    w = World()
    w.ship.x = 50_000.0
    w.ship.y = 50_000.0
    w.ship.interior = make_default_interior("frigate")
    return w


@pytest.fixture(autouse=True)
def _reset():
    glsb.reset(active=False)
    glhc.reset()
    glatm.reset()
    yield
    glsb.reset(active=False)
    glhc.reset()
    glatm.reset()


# ===========================================================================
# Sandbox Fire
# ===========================================================================


class TestSandboxFire:
    def test_fire_timer_exists(self) -> None:
        glsb.reset(active=True)
        assert "sandbox_fire" in glsb._timers

    def test_fire_timer_fires(self) -> None:
        glsb.reset(active=True)
        glsb._timers["sandbox_fire"] = 0.05
        world = _make_world()
        glhc.init_sections(world.ship.interior)
        events = glsb.tick(world, 0.1)
        fires = [e for e in events if e["type"] == "sandbox_fire"]
        assert len(fires) == 1
        assert "room_id" in fires[0]
        assert fires[0]["intensity"] in (1, 2, 3)

    def test_fire_room_is_valid(self) -> None:
        glsb.reset(active=True)
        glsb._timers["sandbox_fire"] = 0.05
        world = _make_world()
        glhc.init_sections(world.ship.interior)
        events = glsb.tick(world, 0.1)
        fires = [e for e in events if e["type"] == "sandbox_fire"]
        assert len(fires) == 1
        assert fires[0]["room_id"] in world.ship.interior.rooms

    def test_fire_no_duplicate_rooms(self) -> None:
        """Don't start fires in rooms that already have active fires."""
        glsb.reset(active=True)
        world = _make_world()
        glhc.init_sections(world.ship.interior)
        # Start a fire in all rooms except one.
        room_ids = list(world.ship.interior.rooms.keys())
        for rid in room_ids[:-1]:
            glhc.start_fire(rid, 1, world.ship.interior)
        glsb._timers["sandbox_fire"] = 0.05
        events = glsb.tick(world, 0.1)
        fires = [e for e in events if e["type"] == "sandbox_fire"]
        if fires:
            assert fires[0]["room_id"] == room_ids[-1]

    def test_fire_max_cap(self) -> None:
        """Maximum 2 simultaneous sandbox-started fires."""
        glsb.reset(active=True)
        world = _make_world()
        glhc.init_sections(world.ship.interior)
        # Simulate 2 sandbox fires already active.
        glsb._sandbox_fire_rooms.add("room_a")
        glsb._sandbox_fire_rooms.add("room_b")
        glsb._timers["sandbox_fire"] = 0.05
        events = glsb.tick(world, 0.1)
        fires = [e for e in events if e["type"] == "sandbox_fire"]
        assert len(fires) == 0

    def test_fire_interval_constant(self) -> None:
        assert glsb.SANDBOX_FIRE_INTERVAL == (60.0, 90.0)

    def test_fire_difficulty_scaling(self) -> None:
        """Higher difficulty → higher fire intensity."""
        glsb.reset(active=True)

        class HardDifficulty:
            event_interval_multiplier = 0.5
            boarding_frequency_multiplier = 1.0

        world = _make_world()
        glhc.init_sections(world.ship.interior)
        intensities: list[int] = []
        for _ in range(20):
            glsb._timers["sandbox_fire"] = 0.05
            glsb._sandbox_fire_rooms.clear()
            events = glsb.tick(world, 0.1, difficulty=HardDifficulty())
            for e in events:
                if e["type"] == "sandbox_fire":
                    intensities.append(e["intensity"])
        # At Admiral difficulty, should see at least some intensity 2-3.
        assert any(i >= 2 for i in intensities), f"Expected some high intensity fires, got {intensities}"

    def test_fire_timer_resets_after_firing(self) -> None:
        glsb.reset(active=True)
        glsb._timers["sandbox_fire"] = 0.05
        world = _make_world()
        glhc.init_sections(world.ship.interior)
        glsb.tick(world, 0.1)
        assert glsb._timers["sandbox_fire"] > 10.0


# ===========================================================================
# Sandbox Breach
# ===========================================================================


class TestSandboxBreach:
    def test_breach_timer_exists(self) -> None:
        glsb.reset(active=True)
        assert "sandbox_breach" in glsb._timers

    def test_breach_timer_fires(self) -> None:
        glsb.reset(active=True)
        glsb._timers["sandbox_breach"] = 0.05
        world = _make_world()
        glatm.init_atmosphere(world.ship.interior)
        events = glsb.tick(world, 0.1)
        breaches = [e for e in events if e["type"] == "sandbox_breach"]
        assert len(breaches) == 1
        assert breaches[0]["room_id"] in world.ship.interior.rooms
        assert breaches[0]["severity"] in ("minor", "major")

    def test_breach_no_duplicate_rooms(self) -> None:
        glsb.reset(active=True)
        world = _make_world()
        glatm.init_atmosphere(world.ship.interior)
        # Breach all rooms except one.
        room_ids = list(world.ship.interior.rooms.keys())
        for rid in room_ids[:-1]:
            glatm.create_breach(rid, "minor", world.ship.interior)
        glsb._timers["sandbox_breach"] = 0.05
        events = glsb.tick(world, 0.1)
        breaches = [e for e in events if e["type"] == "sandbox_breach"]
        if breaches:
            assert breaches[0]["room_id"] == room_ids[-1]

    def test_breach_max_cap(self) -> None:
        glsb.reset(active=True)
        glsb._sandbox_breach_rooms.add("room_a")
        glsb._timers["sandbox_breach"] = 0.05
        world = _make_world()
        glatm.init_atmosphere(world.ship.interior)
        events = glsb.tick(world, 0.1)
        breaches = [e for e in events if e["type"] == "sandbox_breach"]
        assert len(breaches) == 0

    def test_breach_interval_constant(self) -> None:
        assert glsb.SANDBOX_BREACH_INTERVAL == (120.0, 180.0)


# ===========================================================================
# Sandbox Radiation
# ===========================================================================


class TestSandboxRadiation:
    def test_radiation_timer_exists(self) -> None:
        glsb.reset(active=True)
        assert "sandbox_radiation" in glsb._timers

    def test_radiation_timer_fires(self) -> None:
        glsb.reset(active=True)
        glsb._timers["sandbox_radiation"] = 0.05
        world = _make_world()
        glatm.init_atmosphere(world.ship.interior)
        events = glsb.tick(world, 0.1)
        rads = [e for e in events if e["type"] == "sandbox_radiation"]
        assert len(rads) == 1
        assert rads[0]["room_id"] in world.ship.interior.rooms
        assert rads[0]["amount"] > 0
        assert rads[0]["source"] in ("reactor_micro_leak", "shield_emitter_leak")

    def test_radiation_suppressed_when_active(self) -> None:
        glsb.reset(active=True)
        glsb._sandbox_radiation_active = True
        glsb._timers["sandbox_radiation"] = 0.05
        world = _make_world()
        glatm.init_atmosphere(world.ship.interior)
        events = glsb.tick(world, 0.1)
        rads = [e for e in events if e["type"] == "sandbox_radiation"]
        assert len(rads) == 0

    def test_radiation_interval_constant(self) -> None:
        assert glsb.SANDBOX_RADIATION_INTERVAL == (180.0, 240.0)


# ===========================================================================
# Sandbox Structural
# ===========================================================================


class TestSandboxStructural:
    def test_structural_timer_exists(self) -> None:
        glsb.reset(active=True)
        assert "sandbox_structural" in glsb._timers

    def test_structural_timer_fires(self) -> None:
        glsb.reset(active=True)
        glsb._timers["sandbox_structural"] = 0.05
        world = _make_world()
        glhc.init_sections(world.ship.interior)
        events = glsb.tick(world, 0.1)
        structs = [e for e in events if e["type"] == "sandbox_structural"]
        assert len(structs) == 1
        assert structs[0]["amount"] >= 5.0
        assert structs[0]["amount"] <= 15.0
        assert "section_id" in structs[0]

    def test_structural_skips_low_integrity(self) -> None:
        """Don't stress sections already below 30%."""
        glsb.reset(active=True)
        world = _make_world()
        glhc.init_sections(world.ship.interior)
        # Set all sections to 20% integrity.
        for sec in glhc.get_sections().values():
            sec.integrity = 20.0
        glsb._timers["sandbox_structural"] = 0.05
        events = glsb.tick(world, 0.1)
        structs = [e for e in events if e["type"] == "sandbox_structural"]
        assert len(structs) == 0

    def test_structural_interval_constant(self) -> None:
        assert glsb.SANDBOX_STRUCTURAL_INTERVAL == (120.0, 180.0)
