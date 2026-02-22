"""
Station AI — Enemy station defensive systems simulation.

Handles per-tick behaviour for all active components on hostile stations:
  - Beam turrets: auto-fire at the player ship when in range and arc
  - Torpedo launchers: periodically launch heavy torpedoes at the ship
  - Fighter bays: periodically launch fighter craft
  - Sensor array: emit a distress call (reinforcements) when the station
    is attacked and the array is active and not jammed

Public entry point:
    tick_station_ai(stations, ship, world, dt, station_attacked_ids)
        → tuple[list[BeamHitEvent], list[Enemy], list[str]]

Returns:
  beam_hits       — BeamHitEvent list (same type as ai.py), forwarded to
                    handle_enemy_beam_hits in game_loop.py
  launched_fighters — new Enemy entities spawned this tick (append to world.enemies)
  reinforcement_calls — station IDs whose sensor array fired a distress call
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from server.models.ship import Ship
from server.models.world import Enemy, Station, World, spawn_enemy
from server.systems.ai import BeamHitEvent
from server.utils.math_helpers import bearing_to, distance

# Torpedo type fired by station launchers (standard for simplicity).
STATION_TORPEDO_TYPE: str = "standard"
# Velocity for station-fired torpedoes.
STATION_TORPEDO_VELOCITY: float = 400.0
# Hit radius for station torpedoes (world units).
STATION_TORPEDO_HIT_RADIUS: float = 200.0


def tick_station_ai(
    stations: list[Station],
    ship: Ship,
    world: World,
    dt: float,
    station_attacked_ids: set[str],
) -> tuple[list[BeamHitEvent], list[Enemy], list[str]]:
    """Simulate all active enemy station components for one tick.

    *station_attacked_ids* is the set of station IDs that the player hit
    this tick (triggers sensor-array distress calls).

    Returns (beam_hits, launched_fighters, reinforcement_calls).
    """
    # Import here to avoid circular at module load time.
    import server.game_loop_weapons as glw

    beam_hits: list[BeamHitEvent] = []
    launched_fighters: list[Enemy] = []
    reinforcement_calls: list[str] = []

    for station in stations:
        defenses = station.defenses
        if defenses is None:
            continue
        if station.hull <= 0.0:
            continue

        rf = defenses.reactor_factor()

        # -- Turrets ----------------------------------------------------------
        dist_to_ship = distance(station.x, station.y, ship.x, ship.y)
        brg_to_ship = bearing_to(station.x, station.y, ship.x, ship.y)

        for turret in defenses.turrets:
            if not turret.active:
                continue
            turret.cooldown_timer = max(0.0, turret.cooldown_timer - dt)
            if turret.cooldown_timer > 0.0:
                continue
            if dist_to_ship > turret.weapon_range:
                continue
            if not _in_arc(turret.facing, brg_to_ship, turret.arc_deg):
                continue

            effective_dmg = turret.beam_dmg * rf
            beam_hits.append(BeamHitEvent(
                attacker_id=turret.id,
                attacker_x=station.x,
                attacker_y=station.y,
                damage=effective_dmg,
                target="player",
            ))
            turret.cooldown_timer = turret.beam_cooldown

        # -- Torpedo launchers ------------------------------------------------
        for launcher in defenses.launchers:
            if not launcher.active:
                continue
            launcher.cooldown_timer = max(0.0, launcher.cooldown_timer - dt)
            if launcher.cooldown_timer > 0.0:
                continue

            _spawn_station_torpedo(station, ship, world, glw)
            launcher.cooldown_timer = launcher.launch_cooldown

        # -- Fighter bays -----------------------------------------------------
        for bay in defenses.fighter_bays:
            if not bay.active:
                continue
            if bay.fighters_in_bay <= 0:
                continue
            bay.cooldown_timer = max(0.0, bay.cooldown_timer - dt)
            if bay.cooldown_timer > 0.0:
                continue

            fighter = spawn_enemy(
                "fighter",
                station.x + 500.0,
                station.y,
                glw.next_entity_id("fighter"),
            )
            launched_fighters.append(fighter)
            bay.fighters_in_bay -= 1
            bay.cooldown_timer = bay.launch_cooldown

        # -- Sensor array -----------------------------------------------------
        sa = defenses.sensor_array
        if sa.active and not sa.jammed and not sa.distress_sent:
            if station.id in station_attacked_ids:
                sa.distress_sent = True
                reinforcement_calls.append(station.id)

    return beam_hits, launched_fighters, reinforcement_calls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _in_arc(facing: float, bearing: float, arc_deg: float) -> bool:
    """True if *bearing* is within ±arc_deg of *facing*."""
    diff = abs(((bearing - facing) + 180.0) % 360.0 - 180.0)
    return diff <= arc_deg


def _spawn_station_torpedo(
    station: Station,
    ship: Ship,
    world: World,
    glw: object,
) -> None:
    """Spawn a torpedo from the station aimed at the ship."""
    from server.models.world import Torpedo  # local to avoid circular at top-level

    heading = bearing_to(station.x, station.y, ship.x, ship.y)
    torp = Torpedo(
        id=glw.next_entity_id("torpedo"),  # type: ignore[attr-defined]
        owner=station.id,
        x=station.x,
        y=station.y,
        heading=heading,
        velocity=STATION_TORPEDO_VELOCITY,
        torpedo_type=STATION_TORPEDO_TYPE,
    )
    world.torpedoes.append(torp)


def jam_station_sensor(world: World, station_id: str) -> bool:
    """Set the sensor array for *station_id* to jammed=True.

    Returns True if the array was found and marked jammed, False otherwise.
    """
    for station in world.stations:
        if station.id == station_id and station.defenses is not None:
            station.defenses.sensor_array.jammed = True
            return True
    return False


def unjam_station_sensor(world: World, station_id: str) -> None:
    """Clear the jammed flag on a station's sensor array."""
    for station in world.stations:
        if station.id == station_id and station.defenses is not None:
            station.defenses.sensor_array.jammed = False
