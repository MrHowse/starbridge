"""Balance validation test for sandbox event generation.

Runs a 10-minute (simulated) sandbox session and asserts every station
receives at least one event within 5 minutes.
"""
from __future__ import annotations

import pytest

import server.game_loop_sandbox as glsb
import server.game_loop_hazard_control as glhc
import server.game_loop_atmosphere as glatm
from server.models.world import World
from server.models.interior import make_default_interior


# ---------------------------------------------------------------------------
# Station ↔ event type mapping
# ---------------------------------------------------------------------------

STATION_EVENTS: dict[str, list[str]] = {
    "helm":               ["sensor_anomaly"],
    "weapons":            ["spawn_enemy"],
    "engineering":        ["system_damage"],
    "science":            ["sensor_anomaly", "creature_spawn"],
    "comms":              ["incoming_transmission", "distress_signal", "sandbox_ew_intercept"],
    "tactical":           ["spawn_enemy"],
    "electronic_warfare": ["enemy_jamming", "sandbox_ew_intercept"],
    "flight_ops":         ["drone_opportunity", "sandbox_flight_contact"],
    "security":           ["boarding", "security_incident"],
    "medical":            ["crew_casualty", "env_sickness", "sandbox_medical_event"],
    "damage_control":     ["hull_micro_damage"],
    "hazard_control":     ["sandbox_fire", "sandbox_breach", "sandbox_radiation", "sandbox_structural"],
    "operations":         ["sandbox_intel_update", "sandbox_ops_alert"],
    "quartermaster":      ["sandbox_resource_pressure", "sandbox_trade_opportunity"],
    "captain":            ["sandbox_captain_decision"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_world() -> World:
    w = World()
    w.ship.x = 50_000.0
    w.ship.y = 50_000.0
    w.ship.interior = make_default_interior("frigate")
    # Init v0.08 subsystems so HC events can pick rooms/sections.
    glhc.init_sections(w.ship.interior)
    glatm.init_atmosphere(w.ship.interior)
    # Initialise resource maximums so QM events can report meaningful levels.
    resources = w.ship.resources
    for rtype in ("fuel", "ammunition", "suppressant", "repair_materials",
                  "medical_supplies", "provisions", "drone_fuel", "drone_parts"):
        setattr(resources, f"{rtype}_max", 100.0)
        resources.set(rtype, 100.0)
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
# 10-Minute Simulation
# ===========================================================================


class TestSandboxBalance:
    """Run a 10-minute sim and verify every station gets activity."""

    def test_all_stations_get_events_within_5_minutes(self) -> None:
        """Every station must see at least 1 event within 5 simulated minutes."""
        glsb.reset(active=True)
        world = _make_world()
        dt = 1.0
        total_seconds = 300  # 5 minutes

        event_counts: dict[str, int] = {station: 0 for station in STATION_EVENTS}

        for _ in range(total_seconds):
            events = glsb.tick(world, dt)
            for evt in events:
                etype = evt["type"]
                for station, etypes in STATION_EVENTS.items():
                    if etype in etypes:
                        event_counts[station] += 1

        starved = [s for s, c in event_counts.items() if c == 0]
        assert starved == [], (
            f"Stations with ZERO events in 5 min: {starved}\n"
            f"Full counts: {event_counts}"
        )

    def test_full_10_min_event_density(self) -> None:
        """In 10 minutes, each station should average ≥3 events."""
        glsb.reset(active=True)
        world = _make_world()
        dt = 1.0
        total_seconds = 600  # 10 minutes

        event_counts: dict[str, int] = {station: 0 for station in STATION_EVENTS}

        for _ in range(total_seconds):
            events = glsb.tick(world, dt)
            for evt in events:
                etype = evt["type"]
                for station, etypes in STATION_EVENTS.items():
                    if etype in etypes:
                        event_counts[station] += 1

        low = {s: c for s, c in event_counts.items() if c < 3}
        assert low == {}, (
            f"Stations with <3 events in 10 min: {low}\n"
            f"Full counts: {event_counts}"
        )

    def test_no_single_station_dominates(self) -> None:
        """No station should produce >40% of all events."""
        glsb.reset(active=True)
        world = _make_world()
        dt = 1.0
        total_seconds = 600

        event_counts: dict[str, int] = {station: 0 for station in STATION_EVENTS}

        for _ in range(total_seconds):
            events = glsb.tick(world, dt)
            for evt in events:
                etype = evt["type"]
                for station, etypes in STATION_EVENTS.items():
                    if etype in etypes:
                        event_counts[station] += 1

        total = sum(event_counts.values())
        if total > 0:
            for station, count in event_counts.items():
                ratio = count / total
                assert ratio < 0.40, (
                    f"{station} dominates with {count}/{total} = {ratio:.1%} of all events"
                )

    def test_timer_count(self) -> None:
        """After reset, should have 26 active timers."""
        glsb.reset(active=True)
        assert len(glsb._timers) >= 26, (
            f"Expected ≥26 timers, got {len(glsb._timers)}: {sorted(glsb._timers.keys())}"
        )

    def test_hazcon_events_fire_in_10_min(self) -> None:
        """All 4 HC event types should fire at least once in 10 min."""
        glsb.reset(active=True)
        world = _make_world()
        dt = 1.0
        hc_types = {"sandbox_fire", "sandbox_breach", "sandbox_radiation", "sandbox_structural"}
        seen: set[str] = set()

        for _ in range(600):
            events = glsb.tick(world, dt)
            for evt in events:
                if evt["type"] in hc_types:
                    seen.add(evt["type"])
            if seen == hc_types:
                break

        missing = hc_types - seen
        assert missing == set(), f"HC event types never fired: {missing}"

    def test_new_events_fire_in_10_min(self) -> None:
        """All new event types should fire at least once in 10 min."""
        glsb.reset(active=True)
        world = _make_world()
        dt = 1.0
        new_types = {
            "sandbox_fire", "sandbox_breach", "sandbox_radiation", "sandbox_structural",
            "sandbox_intel_update", "sandbox_ops_alert",
            "sandbox_resource_pressure", "sandbox_trade_opportunity",
            "sandbox_ew_intercept", "sandbox_flight_contact",
            "sandbox_captain_decision", "sandbox_medical_event",
        }
        seen: set[str] = set()

        for _ in range(600):
            events = glsb.tick(world, dt)
            for evt in events:
                if evt["type"] in new_types:
                    seen.add(evt["type"])
            if seen == new_types:
                break

        missing = new_types - seen
        assert missing == set(), f"New event types never fired in 10 min: {missing}"
