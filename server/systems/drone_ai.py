"""
Drone AI — flight model and per-type behaviour (v0.06.5).

Drone types and their primary behaviours:
  scout      — detect contacts, track designated, flee threats
  combat     — attack runs, escort formation, engagement rules
  rescue     — fly to site, pick up survivors, RTB when full
  survey     — orbit target, collect scan data, deploy buoys
  ecm_drone  — loiter near target, apply jamming

Public entry point:
  tick_drone(drone, dt, world_context) -> list[DroneEvent]
  tick_decoys(decoys, dt) -> list[DroneEvent]
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from server.models.drones import (
    DRONE_TURN_RATE,
    RESCUE_PICKUP_TIME,
    Decoy,
    Drone,
    SensorBuoy,
)
from server.models.drone_missions import (
    SURVEY_DATA_RATE,
    WAYPOINT_ARRIVAL_DIST,
    DroneMission,
)
from server.utils.math_helpers import bearing_to, distance


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Bingo fuel auto-recall grace period (seconds).
BINGO_AUTO_RECALL_DELAY: float = 15.0

# Combat drone attack run parameters.
ATTACK_AMMO_PER_PASS: float = 10.0   # % ammo consumed per attack pass
ATTACK_BREAK_DISTANCE: float = 5000.0  # break-away distance after pass
ATTACK_COOLDOWN: float = 3.0         # seconds between attack passes

# Escort formation offset distance.
ESCORT_FORMATION_DIST: float = 2000.0

# Escort threat detection range.
ESCORT_THREAT_RANGE: float = 20_000.0

# Scout threat flee range.
SCOUT_FLEE_RANGE: float = 15_000.0

# Critical hull random heading drift (degrees per second).
CRITICAL_HEADING_DRIFT: float = 30.0

# Survey data collection multiplier for sensor resolution.
SURVEY_RESOLUTION_MULT: float = 1.0

# ECM jamming effective range.
ECM_JAM_RANGE: float = 12_000.0

# ECM fuel consumption multiplier while actively jamming.
ECM_FUEL_MULTIPLIER: float = 2.0


# ---------------------------------------------------------------------------
# DroneEvent — events emitted by drone ticks
# ---------------------------------------------------------------------------


@dataclass
class DroneEvent:
    """An event emitted during a drone tick."""

    event_type: str
    drone_id: str
    data: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# World context — minimal info drones need about the world
# ---------------------------------------------------------------------------


@dataclass
class DroneWorldContext:
    """Information about the world that drones need for AI decisions.

    This is a lightweight snapshot — the game loop builds this each tick
    and passes it to drone AI, avoiding direct world references.
    """

    ship_x: float = 0.0
    ship_y: float = 0.0
    ship_heading: float = 0.0

    # Entities within sensor range of any drone.
    # Each: {id, x, y, heading, kind, classification, hull, faction, ...}
    contacts: list[dict] = field(default_factory=list)

    # Survivors at known locations: {position: (x,y), count: int}
    survivors: list[dict] = field(default_factory=list)

    # Current game tick.
    tick: int = 0

    # Is the ship in combat?
    in_combat: bool = False


# ---------------------------------------------------------------------------
# Movement helpers
# ---------------------------------------------------------------------------


def _apply_movement(drone: Drone, dt: float) -> None:
    """Move drone forward along its heading."""
    rad = math.radians(drone.heading)
    x, y = drone.position
    x += math.sin(rad) * drone.speed * dt
    y -= math.cos(rad) * drone.speed * dt
    drone.position = (x, y)


def _turn_toward(drone: Drone, target_heading: float, dt: float) -> None:
    """Turn drone heading toward target_heading at DRONE_TURN_RATE."""
    diff = ((target_heading - drone.heading + 180.0) % 360.0) - 180.0
    max_turn = DRONE_TURN_RATE * dt
    drone.heading = (drone.heading + max(min(diff, max_turn), -max_turn)) % 360.0


def _heading_to(from_pos: tuple[float, float], to_pos: tuple[float, float]) -> float:
    """Bearing from one position to another (degrees, 0=north, CW)."""
    return bearing_to(from_pos[0], from_pos[1], to_pos[0], to_pos[1])


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return distance(a[0], a[1], b[0], b[1])


def _orbit_point(
    drone: Drone, centre: tuple[float, float], radius: float, dt: float,
) -> None:
    """Fly an orbit around a point at the given radius."""
    dist = _dist(drone.position, centre)
    if dist < 1.0:
        # On top of centre — move outward.
        drone.heading = (drone.heading + 90.0) % 360.0
        drone.speed = drone.effective_max_speed * 0.5
        _apply_movement(drone, dt)
        return

    bearing = _heading_to(drone.position, centre)
    if dist > radius * 1.3:
        # Too far — fly toward centre.
        _turn_toward(drone, bearing, dt)
    elif dist < radius * 0.7:
        # Too close — fly away.
        away = (bearing + 180.0) % 360.0
        _turn_toward(drone, away, dt)
    else:
        # In the orbit band — fly tangentially (clockwise).
        tangent = (bearing + 90.0) % 360.0
        _turn_toward(drone, tangent, dt)

    drone.speed = drone.effective_max_speed * 0.6
    _apply_movement(drone, dt)


# ---------------------------------------------------------------------------
# Bingo fuel
# ---------------------------------------------------------------------------


def _check_bingo(drone: Drone, ctx: DroneWorldContext) -> DroneEvent | None:
    """Check bingo fuel status and emit warning if needed."""
    if drone.bingo_acknowledged:
        return None
    ship_pos = (ctx.ship_x, ctx.ship_y)
    if not drone.is_bingo_fuel(ship_pos[0], ship_pos[1]):
        return None

    drone.bingo_acknowledged = True
    return DroneEvent(
        event_type="bingo_fuel",
        drone_id=drone.id,
        data={
            "callsign": drone.callsign,
            "fuel": drone.fuel,
            "fuel_seconds": drone.fuel_seconds_remaining,
        },
    )


def _check_fuel_exhaustion(drone: Drone) -> DroneEvent | None:
    """Check if drone has run out of fuel."""
    if drone.fuel > 0:
        return None
    drone.fuel = 0.0
    drone.speed = 0.0
    drone.status = "lost"
    return DroneEvent(
        event_type="drone_lost",
        drone_id=drone.id,
        data={
            "callsign": drone.callsign,
            "reason": "fuel",
            "position": list(drone.position),
            "cargo_current": drone.cargo_current,
        },
    )


# ---------------------------------------------------------------------------
# Damage effects
# ---------------------------------------------------------------------------


def _apply_critical_drift(drone: Drone, dt: float) -> None:
    """Apply erratic heading drift when hull is critical."""
    if drone.is_critical:
        drift = random.uniform(-CRITICAL_HEADING_DRIFT, CRITICAL_HEADING_DRIFT) * dt
        drone.heading = (drone.heading + drift) % 360.0


def apply_damage_to_drone(drone: Drone, damage: float) -> DroneEvent | None:
    """Apply damage to a drone.  Returns destruction event if hull reaches 0."""
    drone.hull = max(0.0, drone.hull - damage)
    if drone.hull <= 0:
        drone.status = "destroyed"
        drone.speed = 0.0
        return DroneEvent(
            event_type="drone_destroyed",
            drone_id=drone.id,
            data={
                "callsign": drone.callsign,
                "position": list(drone.position),
                "cargo_current": drone.cargo_current,
            },
        )
    return None


# ---------------------------------------------------------------------------
# Waypoint navigation
# ---------------------------------------------------------------------------


def _navigate_to_waypoint(drone: Drone, wp_pos: tuple[float, float], dt: float) -> bool:
    """Fly toward a waypoint.  Returns True if arrived."""
    desired = _heading_to(drone.position, wp_pos)
    _turn_toward(drone, desired, dt)
    drone.speed = drone.effective_max_speed
    _apply_movement(drone, dt)
    return _dist(drone.position, wp_pos) < WAYPOINT_ARRIVAL_DIST


# ---------------------------------------------------------------------------
# Per-type AI tickers
# ---------------------------------------------------------------------------


def _tick_scout(
    drone: Drone, mission: DroneMission | None, ctx: DroneWorldContext, dt: float,
) -> list[DroneEvent]:
    """Scout AI: detect contacts, track designated target, flee threats."""
    events: list[DroneEvent] = []
    effective_range = drone.effective_sensor_range

    # Detect new contacts within sensor range.
    for contact in ctx.contacts:
        cid = contact.get("id", "")
        cx, cy = contact.get("x", 0.0), contact.get("y", 0.0)
        if _dist(drone.position, (cx, cy)) <= effective_range:
            if cid and cid not in drone.known_contacts:
                drone.known_contacts.add(cid)
                drone.contacts_found += 1
                events.append(DroneEvent(
                    event_type="contact_detected",
                    drone_id=drone.id,
                    data={
                        "callsign": drone.callsign,
                        "contact_id": cid,
                        "contact_x": cx,
                        "contact_y": cy,
                        "contact_kind": contact.get("kind", "unknown"),
                    },
                ))

    # Track designated contact.
    if drone.contact_of_interest:
        for contact in ctx.contacts:
            if contact.get("id") == drone.contact_of_interest:
                cx, cy = contact.get("x", 0.0), contact.get("y", 0.0)
                if _dist(drone.position, (cx, cy)) <= effective_range:
                    events.append(DroneEvent(
                        event_type="contact_tracked",
                        drone_id=drone.id,
                        data={
                            "callsign": drone.callsign,
                            "contact_id": drone.contact_of_interest,
                            "contact_x": cx,
                            "contact_y": cy,
                        },
                    ))
                break

    # Threat avoidance — flee from hostiles that get too close.
    if drone.threat_detected:
        for contact in ctx.contacts:
            if contact.get("id") == drone.threat_detected:
                cx, cy = contact.get("x", 0.0), contact.get("y", 0.0)
                if _dist(drone.position, (cx, cy)) < SCOUT_FLEE_RANGE:
                    flee_heading = (_heading_to((cx, cy), drone.position)) % 360.0
                    _turn_toward(drone, flee_heading, dt)
                    drone.speed = drone.effective_max_speed
                    _apply_movement(drone, dt)
                    events.append(DroneEvent(
                        event_type="threat_evading",
                        drone_id=drone.id,
                        data={
                            "callsign": drone.callsign,
                            "threat_id": drone.threat_detected,
                        },
                    ))
                    return events
                break

    return events


def _tick_combat(
    drone: Drone, mission: DroneMission | None, ctx: DroneWorldContext, dt: float,
) -> list[DroneEvent]:
    """Combat AI: attack runs, escort formation, engagement rules."""
    events: list[DroneEvent] = []

    # Tick down attack cooldown.
    if drone.attack_cooldown_remaining > 0:
        drone.attack_cooldown_remaining = max(0.0, drone.attack_cooldown_remaining - dt)

    if drone.ai_behaviour == "engage" and drone.contact_of_interest:
        # Find target in contacts.
        target = None
        for contact in ctx.contacts:
            if contact.get("id") == drone.contact_of_interest:
                target = contact
                break

        if target is None:
            # Target lost or destroyed.
            drone.ai_behaviour = "loiter"
            drone.contact_of_interest = None
            drone.attack_cooldown_remaining = 0.0
            events.append(DroneEvent(
                event_type="target_lost",
                drone_id=drone.id,
                data={"callsign": drone.callsign},
            ))
            return events

        tx, ty = target.get("x", 0.0), target.get("y", 0.0)
        dist_to_target = _dist(drone.position, (tx, ty))

        if drone.attack_cooldown_remaining > 0:
            # On cooldown — continue breaking away from target.
            away = (_heading_to((tx, ty), drone.position)) % 360.0
            _turn_toward(drone, away, dt)
            drone.speed = drone.effective_max_speed
            _apply_movement(drone, dt)

        elif dist_to_target > drone.weapon_range * 1.5:
            # Close to engagement range.
            _navigate_to_waypoint(drone, (tx, ty), dt)

        elif dist_to_target <= drone.weapon_range:
            if drone.ammo > 0:
                # In range — attack.
                damage = drone.effective_weapon_damage
                drone.ammo = max(0.0, drone.ammo - ATTACK_AMMO_PER_PASS)
                drone.damage_dealt += damage
                drone.attack_cooldown_remaining = ATTACK_COOLDOWN
                events.append(DroneEvent(
                    event_type="drone_attack",
                    drone_id=drone.id,
                    data={
                        "callsign": drone.callsign,
                        "target_id": drone.contact_of_interest,
                        "damage": damage,
                        "ammo_remaining": drone.ammo,
                    },
                ))
                # Break away after attack pass.
                away = (_heading_to((tx, ty), drone.position)) % 360.0
                drone.heading = away
                drone.speed = drone.effective_max_speed
                _apply_movement(drone, dt)
            else:
                # Winchester — out of ammo.
                events.append(DroneEvent(
                    event_type="winchester",
                    drone_id=drone.id,
                    data={"callsign": drone.callsign},
                ))
                drone.ai_behaviour = "rtb"
        else:
            # Between weapon_range and 1.5x — close.
            _navigate_to_waypoint(drone, (tx, ty), dt)

    elif drone.ai_behaviour == "escort" and drone.escort_target:
        # Find escort target.
        escort = None
        for contact in ctx.contacts:
            if contact.get("id") == drone.escort_target:
                escort = contact
                break

        if escort:
            ex, ey = escort.get("x", 0.0), escort.get("y", 0.0)
            # Maintain formation at offset.
            dist_to_escort = _dist(drone.position, (ex, ey))
            if dist_to_escort > ESCORT_FORMATION_DIST * 1.5:
                _navigate_to_waypoint(drone, (ex, ey), dt)
            else:
                _orbit_point(drone, (ex, ey), ESCORT_FORMATION_DIST, dt)

            # Check for threats to escort target.
            if drone.engagement_rules != "weapons_hold":
                for contact in ctx.contacts:
                    cid = contact.get("id", "")
                    if cid == drone.escort_target:
                        continue
                    classification = contact.get("classification", "unknown")
                    if classification not in ("hostile", "unknown"):
                        continue
                    cx, cy = contact.get("x", 0.0), contact.get("y", 0.0)
                    if _dist((ex, ey), (cx, cy)) < ESCORT_THREAT_RANGE:
                        if drone.engagement_rules == "weapons_free":
                            drone.contact_of_interest = cid
                            drone.ai_behaviour = "engage"
                            events.append(DroneEvent(
                                event_type="engaging_threat",
                                drone_id=drone.id,
                                data={
                                    "callsign": drone.callsign,
                                    "threat_id": cid,
                                },
                            ))
                            break
                        # weapons_tight — only engage if actively attacking escort.
                        if contact.get("target_id") == drone.escort_target:
                            drone.contact_of_interest = cid
                            drone.ai_behaviour = "engage"
                            events.append(DroneEvent(
                                event_type="engaging_threat",
                                drone_id=drone.id,
                                data={
                                    "callsign": drone.callsign,
                                    "threat_id": cid,
                                },
                            ))
                            break

    return events


def _tick_rescue(
    drone: Drone, mission: DroneMission | None, ctx: DroneWorldContext, dt: float,
) -> list[DroneEvent]:
    """Rescue AI: fly to site, pick up survivors, RTB when full."""
    events: list[DroneEvent] = []

    if not mission or mission.mission_type != "search_and_rescue":
        return events

    # Check if at rescue site (use loiter radius for proximity, not waypoint arrival).
    wp = mission.current_wp
    if wp and _dist(drone.position, wp.position) < max(drone.loiter_radius * 1.5, WAYPOINT_ARRIVAL_DIST):
        # At rescue site — look for survivors.
        survivors_here = 0
        for s in ctx.survivors:
            sx, sy = s.get("x", 0.0), s.get("y", 0.0)
            if _dist(drone.position, (sx, sy)) < 2000.0:
                survivors_here += s.get("count", 0)

        if survivors_here > 0 and drone.cargo_current < drone.cargo_capacity:
            # Picking up survivors.
            drone.pickup_timer += dt
            if drone.pickup_timer >= RESCUE_PICKUP_TIME:
                drone.pickup_timer -= RESCUE_PICKUP_TIME
                drone.cargo_current += 1
                drone.survivors_rescued += 1
                if mission:
                    mission.survivors_rescued += 1
                events.append(DroneEvent(
                    event_type="survivor_pickup",
                    drone_id=drone.id,
                    data={
                        "callsign": drone.callsign,
                        "cargo": drone.cargo_current,
                        "capacity": drone.cargo_capacity,
                    },
                ))
        elif drone.cargo_current >= drone.cargo_capacity or survivors_here == 0:
            # Full or no more survivors — RTB.
            reason = "full" if drone.cargo_current >= drone.cargo_capacity else "no_survivors"
            events.append(DroneEvent(
                event_type="rescue_complete",
                drone_id=drone.id,
                data={
                    "callsign": drone.callsign,
                    "survivors": drone.cargo_current,
                    "reason": reason,
                },
            ))
            drone.ai_behaviour = "rtb"

    return events


def _tick_survey(
    drone: Drone, mission: DroneMission | None, ctx: DroneWorldContext, dt: float,
) -> list[DroneEvent]:
    """Survey AI: orbit target, collect scan data."""
    events: list[DroneEvent] = []

    if not mission or mission.mission_type != "survey":
        return events

    wp = mission.current_wp
    if wp and wp.waypoint_type == "scan":
        if _dist(drone.position, wp.position) < max(drone.loiter_radius * 1.5, WAYPOINT_ARRIVAL_DIST):
            # At survey site — collect data.
            rate = SURVEY_DATA_RATE * drone.sensor_resolution * SURVEY_RESOLUTION_MULT
            wp.time_spent += dt
            # Update objective progress.
            for obj in mission.objectives:
                if obj.objective_type == "survey" and not obj.completed:
                    obj.progress = min(100.0, obj.progress + rate * dt)
                    if obj.progress >= 100.0:
                        obj.completed = True
                        events.append(DroneEvent(
                            event_type="survey_complete",
                            drone_id=drone.id,
                            data={
                                "callsign": drone.callsign,
                                "position": list(wp.position),
                            },
                        ))
                    break

    return events


def _tick_ecm(
    drone: Drone, mission: DroneMission | None, ctx: DroneWorldContext, dt: float,
) -> list[DroneEvent]:
    """ECM drone AI: loiter at position, apply jamming to nearby enemies."""
    events: list[DroneEvent] = []

    if drone.ecm_strength <= 0:
        return events

    # Check for enemies within ECM range.
    jamming_active = False
    for contact in ctx.contacts:
        classification = contact.get("classification", "unknown")
        if classification not in ("hostile",):
            continue
        cx, cy = contact.get("x", 0.0), contact.get("y", 0.0)
        if _dist(drone.position, (cx, cy)) <= ECM_JAM_RANGE:
            jamming_active = True
            events.append(DroneEvent(
                event_type="ecm_jamming",
                drone_id=drone.id,
                data={
                    "callsign": drone.callsign,
                    "target_id": contact.get("id", ""),
                    "strength": drone.ecm_strength,
                },
            ))

    # Active jamming consumes 2x fuel — apply the extra consumption
    # (base consumption already applied in tick_drone).
    if jamming_active:
        extra = drone.fuel_consumption * (ECM_FUEL_MULTIPLIER - 1.0) * dt
        drone.fuel = max(0.0, drone.fuel - extra)

    return events


# ---------------------------------------------------------------------------
# Main drone tick
# ---------------------------------------------------------------------------


def tick_drone(
    drone: Drone,
    dt: float,
    ctx: DroneWorldContext,
    mission: DroneMission | None = None,
) -> list[DroneEvent]:
    """Advance a single active drone by dt seconds.

    Returns a list of events that occurred this tick.
    """
    if drone.status != "active":
        return []

    events: list[DroneEvent] = []

    # 1. Consume fuel.
    drone.fuel -= drone.fuel_consumption * dt
    if drone.fuel < 0:
        drone.fuel = 0.0

    # 2. Check fuel exhaustion.
    fuel_event = _check_fuel_exhaustion(drone)
    if fuel_event:
        events.append(fuel_event)
        return events  # Drone is lost — no further processing.

    # 3. Check bingo fuel.
    bingo_event = _check_bingo(drone, ctx)
    if bingo_event:
        events.append(bingo_event)

    # 4. Apply critical hull drift.
    _apply_critical_drift(drone, dt)

    # 5. RTB behaviour (auto-return to ship).
    if drone.ai_behaviour == "rtb":
        ship_pos = (ctx.ship_x, ctx.ship_y)
        arrived = _navigate_to_waypoint(drone, ship_pos, dt)
        if arrived:
            drone.status = "rtb"
            events.append(DroneEvent(
                event_type="drone_rtb_arrived",
                drone_id=drone.id,
                data={"callsign": drone.callsign},
            ))
        return events

    # 6. Navigate toward current mission waypoint.
    navigating = False
    if mission and not mission.route_complete:
        wp = mission.current_wp
        if wp and not wp.completed:
            dist_to_wp = _dist(drone.position, wp.position)
            # Use loiter radius as "near enough" threshold for loiter/action waypoints.
            orbit_threshold = max(drone.loiter_radius * 1.5, WAYPOINT_ARRIVAL_DIST)
            at_waypoint = dist_to_wp <= WAYPOINT_ARRIVAL_DIST
            near_waypoint = dist_to_wp <= orbit_threshold

            if not at_waypoint and not near_waypoint:
                # Far away — navigate straight to waypoint.
                _navigate_to_waypoint(drone, wp.position, dt)
                navigating = True
            elif at_waypoint or near_waypoint:
                # At or near waypoint — handle loiter/action.
                if wp.loiter_time is not None:
                    wp.time_spent += dt
                    _orbit_point(drone, wp.position, drone.loiter_radius, dt)
                    navigating = True
                    if wp.time_spent >= wp.loiter_time:
                        mission.advance_waypoint()
                elif wp.action in ("pickup", "survey", "jam"):
                    # Action-based — orbit while type ticker handles logic.
                    _orbit_point(drone, wp.position, drone.loiter_radius, dt)
                    navigating = True
                elif at_waypoint:
                    # Simple navigate waypoint — advance.
                    mission.advance_waypoint()
                else:
                    # Near but not at — keep closing.
                    _navigate_to_waypoint(drone, wp.position, dt)
                    navigating = True

    # 7. Loiter at point if no active navigation.
    if not navigating and drone.loiter_point:
        _orbit_point(drone, drone.loiter_point, drone.loiter_radius, dt)
    elif not navigating and drone.speed > 0:
        # Drift forward if nothing else to do.
        drone.speed = drone.effective_max_speed * 0.3
        _apply_movement(drone, dt)

    # 8. Type-specific behaviours.
    if drone.drone_type == "scout":
        events.extend(_tick_scout(drone, mission, ctx, dt))
    elif drone.drone_type == "combat":
        events.extend(_tick_combat(drone, mission, ctx, dt))
    elif drone.drone_type == "rescue":
        events.extend(_tick_rescue(drone, mission, ctx, dt))
    elif drone.drone_type == "survey":
        events.extend(_tick_survey(drone, mission, ctx, dt))
    elif drone.drone_type == "ecm_drone":
        events.extend(_tick_ecm(drone, mission, ctx, dt))

    return events


# ---------------------------------------------------------------------------
# Bingo auto-recall (called by game loop with timer tracking)
# ---------------------------------------------------------------------------


def should_auto_recall(drone: Drone, bingo_elapsed: float, has_critical_cargo: bool) -> bool:
    """Check if a bingo drone should auto-recall.

    If the drone has critical cargo (e.g. survivors aboard), it does NOT
    auto-recall — Flight Ops must make the call.
    """
    if not drone.bingo_acknowledged:
        return False
    if has_critical_cargo:
        return False
    return bingo_elapsed >= BINGO_AUTO_RECALL_DELAY


def initiate_rtb(drone: Drone) -> DroneEvent:
    """Set drone to RTB mode."""
    drone.ai_behaviour = "rtb"
    return DroneEvent(
        event_type="drone_rtb",
        drone_id=drone.id,
        data={"callsign": drone.callsign, "reason": "bingo_auto"},
    )


# ---------------------------------------------------------------------------
# Decoy ticking
# ---------------------------------------------------------------------------


def tick_decoys(decoys: list[Decoy], dt: float) -> list[DroneEvent]:
    """Tick all active decoys.  Expired decoys are deactivated."""
    events: list[DroneEvent] = []
    for decoy in decoys:
        if not decoy.active:
            continue
        decoy.lifetime -= dt
        if decoy.lifetime <= 0:
            decoy.lifetime = 0.0
            decoy.active = False
            events.append(DroneEvent(
                event_type="decoy_expired",
                drone_id=decoy.id,
                data={"position": list(decoy.position)},
            ))
    return events


# ---------------------------------------------------------------------------
# Buoy deployment helper
# ---------------------------------------------------------------------------


def deploy_buoy(drone: Drone) -> SensorBuoy | None:
    """Deploy a sensor buoy at the drone's current position.

    Returns the buoy if successful, None if no buoys remain.
    """
    if drone.buoys_remaining <= 0:
        return None
    drone.buoys_remaining -= 1
    buoy_id = f"buoy_{drone.callsign}_{drone.buoy_capacity - drone.buoys_remaining}"
    return SensorBuoy(
        id=buoy_id,
        position=drone.position,
        deployed_by=drone.callsign,
    )
