"""
Flight Operations — v0.06.5 complete rewrite.

Module-level state managing drones, flight deck, missions, sensor buoys,
and decoys.  Called each tick from game_loop.py.

Lifecycle: reset() → tick() each frame.  Message handlers modify state
via public API functions.  build_state() returns the broadcast payload.
serialise()/deserialise() for save/resume.
"""
from __future__ import annotations

import math

from server.models.drones import (
    Decoy,
    Drone,
    SensorBuoy,
    create_ship_drones,
    deserialise_buoy,
    deserialise_decoy,
    deserialise_drone,
    get_decoy_stock as _get_decoy_stock_for_class,
    serialise_buoy,
    serialise_decoy,
    serialise_drone,
)
from server.models.drone_missions import (
    DroneMission,
    create_patrol_mission,
    deserialise_mission,
    reset_mission_counter,
    serialise_mission,
)
from server.models.flight_deck import (
    LAUNCH_PREP_TIME,
    LAUNCH_RETRY_DELAY,
    BOLTER_RETRY_DELAY,
    FlightDeck,
    create_flight_deck,
    deserialise_flight_deck,
    serialise_flight_deck,
)
from server.models.ship import Ship
from server.systems.drone_ai import (
    DroneWorldContext,
    apply_damage_to_drone,
    deploy_buoy,
    initiate_rtb,
    should_auto_recall,
    tick_decoys,
    tick_drone,
)


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_drones: list[Drone] = []
_flight_deck: FlightDeck = FlightDeck()
_missions: dict[str, DroneMission] = {}  # drone_id → active mission
_buoys: list[SensorBuoy] = []
_decoys: list[Decoy] = []
_decoy_stock: int = 0
_decoy_counter: int = 0

# Bingo timers: drone_id → seconds since bingo acknowledged.
_bingo_timers: dict[str, float] = {}

# Pending events for broadcast.
_pending_events: list[dict] = []

# Launch timers: drone_id → seconds remaining in launch prep + launch.
_launch_timers: dict[str, float] = {}

# Launch phases: drone_id → "prep" | "launch" (used for 2-phase launch).
_launch_phases: dict[str, str] = {}

# Retry delay timers: drone_id → seconds remaining before re-queue.
_retry_delays: dict[str, float] = {}

# Recovery timers: drone_id → seconds remaining in recovery.
_recovery_timers: dict[str, float] = {}


# ---------------------------------------------------------------------------
# Public API — reset / init
# ---------------------------------------------------------------------------


def reset(ship_class_id: str = "frigate") -> None:
    """Initialise flight ops state at game start."""
    global _drones, _flight_deck, _missions, _buoys, _decoys
    global _decoy_stock, _decoy_counter, _bingo_timers, _pending_events
    global _launch_timers, _launch_phases, _retry_delays, _recovery_timers

    _drones = create_ship_drones(ship_class_id)
    _flight_deck = create_flight_deck(ship_class_id)
    _missions = {}
    _buoys = []
    _decoys = []
    _decoy_stock = _get_decoy_stock_for_class(ship_class_id)
    _decoy_counter = 0
    _bingo_timers = {}
    _pending_events = []
    _launch_timers = {}
    _launch_phases = {}
    _retry_delays = {}
    _recovery_timers = {}
    reset_mission_counter()


# ---------------------------------------------------------------------------
# Public API — accessors
# ---------------------------------------------------------------------------


def get_drones() -> list[Drone]:
    return _drones


def get_flight_deck() -> FlightDeck:
    return _flight_deck


def get_buoys() -> list[SensorBuoy]:
    return _buoys


def get_decoys() -> list[Decoy]:
    return _decoys


def get_decoy_stock() -> int:
    return _decoy_stock


def get_missions() -> dict[str, DroneMission]:
    return _missions


def get_drone_by_id(drone_id: str) -> Drone | None:
    for d in _drones:
        if d.id == drone_id:
            return d
    return None


# ---------------------------------------------------------------------------
# Public API — message handlers (called from _drain_queue)
# ---------------------------------------------------------------------------


def launch_drone(drone_id: str, ship: Ship) -> bool:
    """Queue a drone for launch.  Returns False if not possible."""
    drone = get_drone_by_id(drone_id)
    if drone is None or drone.status != "hangar":
        return False
    if not _flight_deck.queue_launch(drone_id):
        return False
    # Mark status immediately so the UI reflects the pending launch.
    drone.status = "launching"
    # Place drone at ship position when launch begins.
    drone.position = (ship.x, ship.y)
    return True


def cancel_launch(drone_id: str) -> bool:
    """Abort a launching drone (during prep phase). Returns to hangar."""
    drone = get_drone_by_id(drone_id)
    if drone is None:
        return False
    if not _flight_deck.cancel_launch(drone_id):
        return False
    _launch_timers.pop(drone_id, None)
    _launch_phases.pop(drone_id, None)
    drone.status = "hangar"
    return True


def recall_drone(drone_id: str) -> bool:
    """Order a drone to RTB.  Cancels active mission."""
    drone = get_drone_by_id(drone_id)
    if drone is None or drone.status not in ("active",):
        return False
    drone.ai_behaviour = "rtb"
    # Abort active mission.
    mission = _missions.get(drone_id)
    if mission:
        mission.abort()
    return True


def assign_mission(drone_id: str, mission: DroneMission) -> bool:
    """Assign a mission to an active drone."""
    drone = get_drone_by_id(drone_id)
    if drone is None or drone.status != "active":
        return False
    mission.activate()
    _missions[drone_id] = mission
    drone.mission_type = mission.mission_type
    return True


def set_waypoint(drone_id: str, x: float, y: float) -> bool:
    """Set a single manual waypoint for a drone."""
    drone = get_drone_by_id(drone_id)
    if drone is None or drone.status != "active":
        return False
    drone.waypoints = [(x, y)]
    drone.waypoint_index = 0
    drone.loiter_point = (x, y)
    return True


def set_waypoints(drone_id: str, waypoints: list[tuple[float, float]]) -> bool:
    """Set a patrol route for a drone by creating a patrol mission."""
    drone = get_drone_by_id(drone_id)
    if drone is None or drone.status != "active":
        return False
    if len(waypoints) < 1:
        return False
    # Abort any existing mission before assigning the new patrol.
    old_mission = _missions.get(drone_id)
    if old_mission:
        old_mission.abort()
    mission = create_patrol_mission(drone_id, waypoints)
    mission.activate()
    _missions[drone_id] = mission
    drone.mission_type = mission.mission_type
    drone.waypoints = list(waypoints)
    drone.waypoint_index = 0
    return True


def set_engagement_rules(drone_id: str, rules: str) -> bool:
    """Set engagement rules for a drone."""
    drone = get_drone_by_id(drone_id)
    if drone is None:
        return False
    drone.engagement_rules = rules
    return True


def set_behaviour(drone_id: str, behaviour: str) -> bool:
    """Set AI behaviour for a drone."""
    drone = get_drone_by_id(drone_id)
    if drone is None:
        return False
    drone.ai_behaviour = behaviour
    return True


def designate_target(drone_id: str, target_id: str) -> bool:
    """Assign a contact for the drone to track/attack."""
    drone = get_drone_by_id(drone_id)
    if drone is None:
        return False
    drone.contact_of_interest = target_id
    return True


def clear_to_land(drone_id: str) -> bool:
    """Grant landing clearance to a drone in recovery orbit."""
    return _flight_deck.clear_to_land(drone_id)


def prioritise_recovery(order: list[str]) -> None:
    """Set recovery queue order."""
    _flight_deck.prioritise_recovery(order)


def rush_turnaround(drone_id: str, skip: list[str] | None = None) -> bool:
    """Launch drone before turnaround completes."""
    return _flight_deck.rush_turnaround(drone_id, skip)


def deploy_decoy_cmd(direction: float, ship: Ship) -> bool:
    """Launch a decoy in the given direction."""
    global _decoy_stock, _decoy_counter
    if _decoy_stock <= 0:
        return False
    _decoy_stock -= 1
    _decoy_counter += 1
    rad = math.radians(direction)
    dx = math.sin(rad) * 2000.0
    dy = -math.cos(rad) * 2000.0
    decoy = Decoy(
        id=f"decoy_{_decoy_counter}",
        position=(ship.x + dx, ship.y + dy),
        heading=direction,
    )
    _decoys.append(decoy)
    _pending_events.append({
        "type": "decoy_deployed",
        "decoy_id": decoy.id,
        "position": list(decoy.position),
    })
    return True


def deploy_buoy_cmd(drone_id: str) -> bool:
    """Order a survey drone to deploy a sensor buoy."""
    drone = get_drone_by_id(drone_id)
    if drone is None or drone.status != "active":
        return False
    buoy = deploy_buoy(drone)
    if buoy is None:
        return False
    _buoys.append(buoy)
    _pending_events.append({
        "type": "buoy_deployed",
        "buoy_id": buoy.id,
        "position": list(buoy.position),
        "deployed_by": buoy.deployed_by,
    })
    return True


def escort_assign(drone_id: str, escort_target: str) -> bool:
    """Assign a combat drone to escort a target."""
    drone = get_drone_by_id(drone_id)
    if drone is None or drone.drone_type != "combat":
        return False
    drone.escort_target = escort_target
    drone.ai_behaviour = "escort"
    return True


def abort_landing(drone_id: str) -> bool:
    """Wave off a landing drone."""
    return _flight_deck.abort_landing(drone_id)


# ---------------------------------------------------------------------------
# Tick — called each frame from game_loop.py
# ---------------------------------------------------------------------------


def tick(ship: Ship, dt: float, contacts: list[dict] | None = None,
         survivors: list[dict] | None = None, in_combat: bool = False,
         tick_num: int = 0) -> list[dict]:
    """Advance all flight ops state by dt seconds.

    Returns a list of events for broadcast.
    """
    events: list[dict] = []

    # Build world context for drone AI.
    ctx = DroneWorldContext(
        ship_x=ship.x,
        ship_y=ship.y,
        ship_heading=ship.heading,
        contacts=contacts or [],
        survivors=survivors or [],
        in_combat=in_combat,
        tick=tick_num,
    )

    # 1. Process launch queue → tubes → active.
    events.extend(_tick_launches(ship, dt, in_combat=in_combat))

    # 2. Process recovery queue → landing → hangar.
    events.extend(_tick_recoveries(ship, dt))

    # 3. Tick flight deck (turnarounds, crash block).
    deck_events = _flight_deck.tick(dt)
    for de in deck_events:
        if de.get("type") == "turnaround_complete":
            did = de["drone_id"]
            _flight_deck.finish_turnaround(did)
            drone = get_drone_by_id(did)
            if drone:
                drone.status = "hangar"
                # Restore drone stats after turnaround.
                if drone.fuel < 100.0:
                    drone.fuel = 100.0
                if drone.hull < drone.max_hull:
                    drone.hull = drone.max_hull
                if drone.ammo < 100.0 and drone.drone_type == "combat":
                    drone.ammo = 100.0
    events.extend({"type": de["type"], **de} for de in deck_events)

    # 4. Tick all active drones.
    for drone in _drones:
        if drone.status == "active":
            mission = _missions.get(drone.id)
            drone_events = tick_drone(drone, dt, ctx, mission)
            for dev in drone_events:
                events.append({
                    "type": dev.event_type,
                    "drone_id": dev.drone_id,
                    **dev.data,
                })

                # Handle mission-completing events.
                if dev.event_type in ("rescue_complete", "survey_complete"):
                    if mission and mission.is_active:
                        mission.complete()
                        events.append({
                            "type": "mission_complete",
                            "drone_id": drone.id,
                            "callsign": drone.callsign,
                            "mission_type": mission.mission_type,
                        })
                elif dev.event_type == "winchester":
                    # Out of ammo — mission effectively complete.
                    if mission and mission.is_active:
                        mission.complete()

            # Check mission timeout.
            if mission and mission.is_active and mission.timeout_tick is not None:
                if tick_num >= mission.timeout_tick:
                    mission.abort()
                    ev = initiate_rtb(drone)
                    events.append({
                        "type": ev.event_type,
                        "drone_id": ev.drone_id,
                        "reason": "timeout",
                        **ev.data,
                    })

            # Check mission route completion → auto-RTB.
            if mission and mission.is_active and mission.route_complete:
                if mission.all_required_complete:
                    mission.complete()
                    ev = initiate_rtb(drone)
                    events.append({
                        "type": "mission_complete",
                        "drone_id": drone.id,
                        "callsign": drone.callsign,
                        "mission_type": mission.mission_type,
                    })
                    events.append({
                        "type": ev.event_type,
                        "drone_id": ev.drone_id,
                        **ev.data,
                    })

            # Check bingo auto-recall.
            if drone.bingo_acknowledged:
                timer = _bingo_timers.get(drone.id, 0.0) + dt
                _bingo_timers[drone.id] = timer
                has_critical = drone.cargo_current > 0
                if should_auto_recall(drone, timer, has_critical):
                    ev = initiate_rtb(drone)
                    events.append({
                        "type": ev.event_type,
                        "drone_id": ev.drone_id,
                        **ev.data,
                    })
                    _bingo_timers.pop(drone.id, None)

        # Handle RTB arrival.
        if drone.status == "rtb":
            if _flight_deck.queue_recovery(drone.id):
                drone.status = "recovering"
                events.append({
                    "type": "drone_recovery_queued",
                    "drone_id": drone.id,
                    "callsign": drone.callsign,
                })

        # Handle lost/destroyed cleanup — mark mission as failed.
        if drone.status in ("lost", "destroyed"):
            lost_mission = _missions.pop(drone.id, None)
            if lost_mission and not lost_mission.is_over:
                lost_mission.fail()
                events.append({
                    "type": "mission_failed",
                    "drone_id": drone.id,
                    "callsign": drone.callsign,
                    "mission_type": lost_mission.mission_type,
                    "reason": drone.status,
                })
            _bingo_timers.pop(drone.id, None)

    # 5. Ditch check: drones with fuel=0 and deck unavailable are lost.
    deck_unavailable = _flight_deck.fire_active or _flight_deck.depressurised
    for drone in _drones:
        if drone.status in ("active", "rtb", "recovering"):
            if drone.fuel <= 0 and deck_unavailable:
                drone.status = "lost"
                events.append({
                    "type": "drone_ditched",
                    "drone_id": drone.id,
                    "callsign": drone.callsign,
                    "reason": "fuel_exhausted_deck_unavailable",
                })

    # 6. Tick decoys.
    decoy_events = tick_decoys(_decoys, dt)
    for dev in decoy_events:
        events.append({
            "type": dev.event_type,
            "drone_id": dev.drone_id,
            **dev.data,
        })
    # Remove expired decoys.
    _decoys[:] = [d for d in _decoys if d.active]

    # 6. Drain pending events.
    if _pending_events:
        events.extend(_pending_events)
        _pending_events.clear()

    return events


# ---------------------------------------------------------------------------
# Launch processing
# ---------------------------------------------------------------------------


def _tick_launches(ship: Ship, dt: float, in_combat: bool = False) -> list[dict]:
    """Process launch queue, tubes, and retry delays."""
    events: list[dict] = []
    fd = _flight_deck

    # Tick retry delays first — re-queue when delay expires.
    for drone_id in list(_retry_delays):
        _retry_delays[drone_id] -= dt
        if _retry_delays[drone_id] <= 0:
            _retry_delays.pop(drone_id)
            fd.queue_launch(drone_id)

    # Move drones from queue into available tubes.
    while fd.launch_queue and len(fd.tubes_in_use) < fd.launch_tubes:
        if not fd.can_launch:
            break
        drone_id = fd.launch_queue.pop(0)
        fd.tubes_in_use.append(drone_id)
        _launch_timers[drone_id] = LAUNCH_PREP_TIME
        _launch_phases[drone_id] = "prep"
        events.append({
            "type": "launch_prep",
            "drone_id": drone_id,
        })

    # Tick launch timers.
    phase_completed: list[str] = []
    for drone_id in list(_launch_timers):
        _launch_timers[drone_id] -= dt
        if _launch_timers[drone_id] <= 0:
            phase_completed.append(drone_id)

    for drone_id in phase_completed:
        phase = _launch_phases.get(drone_id, "launch")

        if phase == "prep":
            # Prep complete — carry overflow into launch phase.
            overflow = -_launch_timers[drone_id]  # positive leftover time
            catapult_time = fd.launch_time
            if fd.catapult_health < 100.0:
                factor = max(0.25, fd.catapult_health / 100.0)
                catapult_time = fd.launch_time / factor
            _launch_timers[drone_id] = catapult_time - overflow
            _launch_phases[drone_id] = "launch"
            if _launch_timers[drone_id] > 0:
                continue
            # Overflow consumed the launch phase too — fall through.

        # Launch phase complete.
        _launch_timers.pop(drone_id)
        _launch_phases.pop(drone_id, None)
        if drone_id in fd.tubes_in_use:
            fd.tubes_in_use.remove(drone_id)

        drone = get_drone_by_id(drone_id)
        if drone is None:
            continue

        # Roll for launch failure.
        if fd.roll_launch_failure():
            events.append({
                "type": "launch_failure",
                "drone_id": drone_id,
                "callsign": drone.callsign,
            })
            # Re-queue after retry delay (5s).
            _retry_delays[drone_id] = LAUNCH_RETRY_DELAY
            continue

        # Successful launch.
        drone.status = "active"
        drone.position = (ship.x, ship.y)
        drone.heading = ship.heading
        drone.speed = drone.effective_max_speed
        drone.bingo_acknowledged = False
        _bingo_timers.pop(drone_id, None)

        # Combat launch damage roll — only during active combat.
        if in_combat:
            hull_dmg = fd.roll_combat_launch_damage()
            if hull_dmg > 0:
                pct = (hull_dmg / 100.0) * drone.max_hull
                apply_damage_to_drone(drone, pct)
                events.append({
                    "type": "combat_launch_damage",
                    "drone_id": drone_id,
                    "callsign": drone.callsign,
                    "damage": pct,
                })

        events.append({
            "type": "drone_launched",
            "drone_id": drone_id,
            "callsign": drone.callsign,
            "drone_type": drone.drone_type,
        })

    return events


# ---------------------------------------------------------------------------
# Recovery processing
# ---------------------------------------------------------------------------


def _tick_recoveries(ship: Ship, dt: float) -> list[dict]:
    """Process recovery queue and landing drones."""
    events: list[dict] = []
    fd = _flight_deck

    # Auto-clear from queue to recovery if slots available.
    while fd.recovery_queue and fd.can_recover:
        drone_id = fd.recovery_queue[0]
        if fd.clear_to_land(drone_id):
            _recovery_timers[drone_id] = fd.get_effective_recovery_time()
            events.append({
                "type": "recovery_approach",
                "drone_id": drone_id,
            })

    # Tick recovery timers.
    completed: list[str] = []
    for drone_id in list(_recovery_timers):
        _recovery_timers[drone_id] -= dt
        if _recovery_timers[drone_id] <= 0:
            completed.append(drone_id)

    for drone_id in completed:
        _recovery_timers.pop(drone_id)
        if drone_id in fd.recovery_in_progress:
            fd.recovery_in_progress.remove(drone_id)

        drone = get_drone_by_id(drone_id)
        if drone is None:
            continue

        # Check crash risk for critically damaged drones.
        if fd.check_crash_risk(drone):
            drone.status = "destroyed"
            _missions.pop(drone_id, None)
            _bingo_timers.pop(drone_id, None)
            events.append({
                "type": "drone_crash_on_deck",
                "drone_id": drone_id,
                "callsign": drone.callsign,
            })
            continue

        # Roll for bolter.
        if fd.roll_bolter():
            # Bolter — drone goes around, 15s penalty via delayed re-queue.
            drone.status = "recovering"
            _recovery_timers[drone_id] = BOLTER_RETRY_DELAY
            events.append({
                "type": "bolter",
                "drone_id": drone_id,
                "callsign": drone.callsign,
            })
            continue

        # Successful recovery.
        drone.status = "maintenance"
        drone.speed = 0.0
        _missions.pop(drone_id, None)
        _bingo_timers.pop(drone_id, None)

        # Transfer survivors from rescue drones.
        if drone.cargo_current > 0 and drone.drone_type == "rescue":
            events.append({
                "type": "survivors_transferred",
                "drone_id": drone_id,
                "callsign": drone.callsign,
                "count": drone.cargo_current,
            })
            drone.cargo_current = 0

        # Start turnaround.
        fd.start_turnaround(drone)

        events.append({
            "type": "drone_recovered",
            "drone_id": drone_id,
            "callsign": drone.callsign,
        })

    return events


# ---------------------------------------------------------------------------
# Detection bubbles (used by sensors.py)
# ---------------------------------------------------------------------------


def get_detection_bubbles(deck_efficiency: float = 1.0) -> list[tuple[float, float, float]]:
    """Return (x, y, range) for all active drone + buoy sensor bubbles."""
    bubbles: list[tuple[float, float, float]] = []
    for drone in _drones:
        if drone.status == "active":
            r = drone.effective_sensor_range * max(0.01, deck_efficiency)
            bubbles.append((drone.position[0], drone.position[1], r))
    for buoy in _buoys:
        if buoy.active:
            bubbles.append((buoy.position[0], buoy.position[1], buoy.sensor_range))
    return bubbles


# ---------------------------------------------------------------------------
# State broadcast
# ---------------------------------------------------------------------------


def build_state(ship: Ship) -> dict:
    """Build the flight_ops.state payload for the Flight Ops client."""
    return {
        "drones": [
            {
                "id": d.id,
                "callsign": d.callsign,
                "drone_type": d.drone_type,
                "status": d.status,
                "x": round(d.position[0], 1),
                "y": round(d.position[1], 1),
                "heading": round(d.heading, 1),
                "speed": round(d.speed, 1),
                "max_speed": round(d.max_speed, 1),
                "hull": round(d.hull, 1),
                "max_hull": round(d.max_hull, 1),
                "fuel": round(d.fuel, 1),
                "ammo": round(d.ammo, 1),
                "sensor_range": round(d.effective_sensor_range, 1),
                "weapon_range": round(d.weapon_range, 1),
                "weapon_damage": round(d.effective_weapon_damage, 1),
                "ecm_strength": d.ecm_strength,
                "buoys_remaining": d.buoys_remaining,
                "buoy_capacity": d.buoy_capacity,
                "ai_behaviour": d.ai_behaviour,
                "engagement_rules": d.engagement_rules,
                "contact_of_interest": d.contact_of_interest,
                "escort_target": d.escort_target,
                "mission_type": d.mission_type,
                "cargo_current": d.cargo_current,
                "cargo_capacity": d.cargo_capacity,
                "bingo_acknowledged": d.bingo_acknowledged,
                "waypoints": [list(wp) for wp in d.waypoints],
                "waypoint_index": d.waypoint_index,
                "loiter_point": list(d.loiter_point) if d.loiter_point else None,
            }
            for d in _drones
        ],
        "flight_deck": {
            "launch_tubes": _flight_deck.launch_tubes,
            "tubes_in_use": len(_flight_deck.tubes_in_use),
            "launch_queue": len(_flight_deck.launch_queue),
            "recovery_slots": _flight_deck.recovery_slots,
            "recovery_in_progress": len(_flight_deck.recovery_in_progress),
            "recovery_queue": list(_flight_deck.recovery_queue),
            "deck_status": _flight_deck.deck_status,
            "fire_active": _flight_deck.fire_active,
            "depressurised": _flight_deck.depressurised,
            "power_available": _flight_deck.power_available,
            "crash_block_remaining": round(_flight_deck.crash_block_remaining, 1),
            "catapult_health": round(_flight_deck.catapult_health, 1),
            "recovery_health": round(_flight_deck.recovery_health, 1),
            "fuel_lines_health": round(_flight_deck.fuel_lines_health, 1),
            "control_tower_health": round(_flight_deck.control_tower_health, 1),
            "drone_fuel_reserve": round(_flight_deck.drone_fuel_reserve, 1),
            "drone_ammo_reserve": round(_flight_deck.drone_ammo_reserve, 1),
            "turnarounds": {
                k: {
                    "total_remaining": round(v.total_remaining, 1),
                    "needs_refuel": v.needs_refuel,
                    "needs_rearm": v.needs_rearm,
                    "needs_repair": v.needs_repair,
                    "refuel_remaining": round(v.refuel_remaining, 1),
                    "rearm_remaining": round(v.rearm_remaining, 1),
                    "repair_remaining": round(v.repair_remaining, 1),
                }
                for k, v in _flight_deck.turnarounds.items()
            },
        },
        "buoys": [
            {
                "id": b.id,
                "x": round(b.position[0], 1),
                "y": round(b.position[1], 1),
                "deployed_by": b.deployed_by,
                "active": b.active,
            }
            for b in _buoys
        ],
        "decoys": [
            {
                "id": d.id,
                "x": round(d.position[0], 1),
                "y": round(d.position[1], 1),
                "lifetime": round(d.lifetime, 1),
            }
            for d in _decoys
        ],
        "decoy_stock": _decoy_stock,
    }


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def serialise() -> dict:
    return {
        "drones": [serialise_drone(d) for d in _drones],
        "flight_deck": serialise_flight_deck(_flight_deck),
        "missions": {k: serialise_mission(v) for k, v in _missions.items()},
        "buoys": [serialise_buoy(b) for b in _buoys],
        "decoys": [serialise_decoy(d) for d in _decoys],
        "decoy_stock": _decoy_stock,
        "decoy_counter": _decoy_counter,
        "bingo_timers": dict(_bingo_timers),
        "launch_timers": dict(_launch_timers),
        "launch_phases": dict(_launch_phases),
        "retry_delays": dict(_retry_delays),
        "recovery_timers": dict(_recovery_timers),
    }


def deserialise(data: dict) -> None:
    global _drones, _flight_deck, _missions, _buoys, _decoys
    global _decoy_stock, _decoy_counter, _bingo_timers, _pending_events
    global _launch_timers, _launch_phases, _retry_delays, _recovery_timers

    _drones = [deserialise_drone(d) for d in data.get("drones", [])]

    fd_data = data.get("flight_deck")
    if fd_data:
        _flight_deck = deserialise_flight_deck(fd_data)
    else:
        _flight_deck = FlightDeck()

    _missions = {
        k: deserialise_mission(v)
        for k, v in data.get("missions", {}).items()
    }
    _buoys = [deserialise_buoy(b) for b in data.get("buoys", [])]
    _decoys = [deserialise_decoy(d) for d in data.get("decoys", [])]
    _decoy_stock = data.get("decoy_stock", 0)
    _decoy_counter = data.get("decoy_counter", 0)
    _bingo_timers = dict(data.get("bingo_timers", {}))
    _pending_events = []
    _launch_timers = {k: float(v) for k, v in data.get("launch_timers", {}).items()}
    _launch_phases = dict(data.get("launch_phases", {}))
    _retry_delays = {k: float(v) for k, v in data.get("retry_delays", {}).items()}
    _recovery_timers = {k: float(v) for k, v in data.get("recovery_timers", {}).items()}
