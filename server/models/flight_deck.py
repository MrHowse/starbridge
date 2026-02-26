"""
Flight Deck Model — v0.06.5 Flight Ops Overhaul.

The flight deck is a physical system with launch tubes, recovery systems,
and turnaround processes.  Managing the deck is part of the gameplay.

Launch sequence:  hangar slot → launch tube → prep (3s) → launch
Recovery sequence: orbit → clearance → approach (5s) → catch (5s) → hangar
Turnaround:       refuel (15s) + rearm (20s) + repair (variable) — parallel

Deck emergencies: fire, hull breach (depressurised), power loss.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from server.models.drones import Drone


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Launch timing.
LAUNCH_PREP_TIME: float = 3.0          # seconds of pre-flight checks
BASE_LAUNCH_TIME: float = 8.0          # seconds for catapult launch
LAUNCH_FAIL_HEALTH_THRESHOLD: float = 50.0   # catapult health % below which failures occur
LAUNCH_FAIL_CHANCE: float = 0.20       # 20% fail chance when catapult damaged
LAUNCH_RETRY_DELAY: float = 5.0        # seconds before retry after failure
COMBAT_LAUNCH_DAMAGE_CHANCE: float = 0.05    # 5% chance of 20% hull damage on launch in combat
COMBAT_LAUNCH_DAMAGE_AMOUNT: float = 20.0    # % hull damage from near-miss

# Recovery timing.
BASE_RECOVERY_APPROACH_TIME: float = 5.0     # seconds to align
BASE_RECOVERY_CATCH_TIME: float = 5.0        # seconds to catch
BOLTER_HEALTH_THRESHOLD_LOW: float = 25.0    # recovery health % for 30% bolter
BOLTER_HEALTH_THRESHOLD_MID: float = 50.0    # recovery health % for 15% bolter
BOLTER_CHANCE_MID: float = 0.15
BOLTER_CHANCE_LOW: float = 0.30
BOLTER_RETRY_DELAY: float = 15.0       # seconds before retry after bolter
RECOVERY_ORBIT_DIST: float = 2000.0    # orbit distance for drones waiting to land
EVASIVE_MANOEUVRE_RECOVERY_PENALTY: float = 0.30  # 30% worse recovery during evasion

# Crash risk.
CRASH_HULL_THRESHOLD: float = 10.0     # hull % below which crash risk exists
CRASH_RECOVERY_BLOCK_TIME: float = 30.0  # seconds to clear wreckage
CRASH_RECOVERY_DAMAGE: float = 15.0    # recovery_health lost on crash
CRASH_FIRE_CHANCE: float = 0.30        # 30% chance crash starts a fire

# Turnaround timing.
REFUEL_TIME: float = 15.0              # seconds to refuel fully
REARM_TIME: float = 20.0               # seconds to rearm fully
REPAIR_TIME_PER_PERCENT: float = 0.5   # seconds per 1% hull repair

# Reserve consumption per turnaround.
REFUEL_RESERVE_COST: float = 10.0      # % of fuel reserve per refuel
REARM_RESERVE_COST: float = 15.0       # % of ammo reserve per rearm

# Deck statuses.
DECK_STATUSES = ("operational", "damaged", "fire", "depressurised", "power_loss")


# ---------------------------------------------------------------------------
# Flight Deck dataclass
# ---------------------------------------------------------------------------


@dataclass
class FlightDeck:
    """Physical flight deck with launch/recovery/turnaround systems."""

    # Launch capability.
    launch_tubes: int = 1
    launch_time: float = BASE_LAUNCH_TIME
    tubes_in_use: list[str] = field(default_factory=list)      # drone_ids launching
    launch_queue: list[str] = field(default_factory=list)       # drone_ids waiting

    # Recovery capability.
    recovery_slots: int = 1
    recovery_time: float = BASE_RECOVERY_CATCH_TIME
    recovery_in_progress: list[str] = field(default_factory=list)  # drone_ids landing
    recovery_queue: list[str] = field(default_factory=list)        # drone_ids in orbit

    # Hangar.
    hangar_slots: int = 4

    # Turnaround tracking: drone_id → TurnaroundState.
    turnarounds: dict[str, TurnaroundState] = field(default_factory=dict)

    # Resources.
    drone_fuel_reserve: float = 100.0     # 0-100 %, shared fuel pool
    drone_ammo_reserve: float = 100.0     # 0-100 %, shared ammo pool

    # Deck status.
    deck_status: str = "operational"

    # Component health (0-100 %, mirrors Engineering).
    catapult_health: float = 100.0
    recovery_health: float = 100.0
    fuel_lines_health: float = 100.0
    control_tower_health: float = 100.0

    # Turnaround speed multiplier (0.5 = 50% of normal time for carrier).
    turnaround_multiplier: float = 1.0

    # Deck emergency state.
    fire_active: bool = False
    depressurised: bool = False
    power_available: bool = True
    crash_block_remaining: float = 0.0    # seconds of wreckage blockage

    # Pending events for broadcast.
    pending_events: list[dict] = field(default_factory=list)

    # -----------------------------------------------------------------------
    # Status queries
    # -----------------------------------------------------------------------

    @property
    def can_launch(self) -> bool:
        """True if the deck can currently launch drones."""
        if self.fire_active or not self.power_available:
            return False
        if self.deck_status in ("fire", "power_loss"):
            return False
        return len(self.tubes_in_use) < self.launch_tubes

    @property
    def can_recover(self) -> bool:
        """True if the deck can currently recover drones."""
        if self.fire_active or self.depressurised:
            return False
        if self.crash_block_remaining > 0:
            return False
        if self.deck_status in ("fire", "depressurised"):
            return False
        return len(self.recovery_in_progress) < self.recovery_slots

    @property
    def launch_queue_count(self) -> int:
        return len(self.launch_queue)

    @property
    def recovery_queue_count(self) -> int:
        return len(self.recovery_queue)

    # -----------------------------------------------------------------------
    # Launch operations
    # -----------------------------------------------------------------------

    def queue_launch(self, drone_id: str) -> bool:
        """Add a drone to the launch queue.  Returns False if deck can't launch."""
        if self.fire_active or not self.power_available:
            return False
        if drone_id in self.tubes_in_use or drone_id in self.launch_queue:
            return False
        self.launch_queue.append(drone_id)
        return True

    def cancel_launch(self, drone_id: str) -> bool:
        """Remove a drone from the launch queue or tube (abort during prep)."""
        if drone_id in self.launch_queue:
            self.launch_queue.remove(drone_id)
            return True
        if drone_id in self.tubes_in_use:
            self.tubes_in_use.remove(drone_id)
            return True
        return False

    # -----------------------------------------------------------------------
    # Recovery operations
    # -----------------------------------------------------------------------

    def queue_recovery(self, drone_id: str) -> bool:
        """Add a drone to the recovery orbit queue."""
        if drone_id in self.recovery_in_progress or drone_id in self.recovery_queue:
            return False
        self.recovery_queue.append(drone_id)
        return True

    def clear_to_land(self, drone_id: str) -> bool:
        """Grant landing clearance — move from orbit queue to recovery slot."""
        if drone_id not in self.recovery_queue:
            return False
        if not self.can_recover:
            return False
        self.recovery_queue.remove(drone_id)
        self.recovery_in_progress.append(drone_id)
        return True

    def prioritise_recovery(self, order: list[str]) -> None:
        """Reorder the recovery queue."""
        current = set(self.recovery_queue)
        new_order = [d for d in order if d in current]
        remaining = [d for d in self.recovery_queue if d not in set(new_order)]
        self.recovery_queue = new_order + remaining

    def abort_landing(self, drone_id: str) -> bool:
        """Wave off a landing drone — back to orbit queue."""
        if drone_id in self.recovery_in_progress:
            self.recovery_in_progress.remove(drone_id)
            self.recovery_queue.insert(0, drone_id)
            return True
        return False

    # -----------------------------------------------------------------------
    # Turnaround operations
    # -----------------------------------------------------------------------

    def start_turnaround(self, drone: Drone) -> None:
        """Begin turnaround for a recovered drone."""
        needs_refuel = drone.fuel < 100.0 and self.drone_fuel_reserve > 0
        needs_rearm = (drone.ammo < 100.0 and drone.drone_type == "combat"
                       and self.drone_ammo_reserve > 0)
        needs_repair = drone.hull < drone.max_hull

        # Consume reserves.
        if needs_refuel:
            self.drone_fuel_reserve = max(0.0, self.drone_fuel_reserve - REFUEL_RESERVE_COST)
        if needs_rearm:
            self.drone_ammo_reserve = max(0.0, self.drone_ammo_reserve - REARM_RESERVE_COST)

        repair_time = 0.0
        if needs_repair:
            damage_pct = ((drone.max_hull - drone.hull) / drone.max_hull) * 100.0
            repair_time = damage_pct * REPAIR_TIME_PER_PERCENT

        total = max(
            REFUEL_TIME if needs_refuel else 0.0,
            REARM_TIME if needs_rearm else 0.0,
            repair_time,
        )

        self.turnarounds[drone.id] = TurnaroundState(
            drone_id=drone.id,
            needs_refuel=needs_refuel,
            needs_rearm=needs_rearm,
            needs_repair=needs_repair,
            refuel_remaining=REFUEL_TIME if needs_refuel else 0.0,
            rearm_remaining=REARM_TIME if needs_rearm else 0.0,
            repair_remaining=repair_time,
            total_remaining=total,
        )

    def rush_turnaround(self, drone_id: str, skip: list[str] | None = None) -> bool:
        """Mark turnaround as complete, optionally skipping steps.

        The drone launches with whatever state it currently has.
        Returns False if no turnaround is active for this drone.
        """
        if drone_id not in self.turnarounds:
            return False
        ta = self.turnarounds[drone_id]
        if skip:
            for step in skip:
                if step == "refuel":
                    ta.needs_refuel = False
                    ta.refuel_remaining = 0.0
                elif step == "rearm":
                    ta.needs_rearm = False
                    ta.rearm_remaining = 0.0
                elif step == "repair":
                    ta.needs_repair = False
                    ta.repair_remaining = 0.0
        # Force complete.
        ta.total_remaining = 0.0
        ta.refuel_remaining = 0.0
        ta.rearm_remaining = 0.0
        ta.repair_remaining = 0.0
        # Emit event so game loop processes the completion.
        self.pending_events.append({"type": "turnaround_complete", "drone_id": drone_id})
        return True

    def is_turnaround_complete(self, drone_id: str) -> bool:
        """True if the drone's turnaround is done (or was never started)."""
        if drone_id not in self.turnarounds:
            return True
        return self.turnarounds[drone_id].total_remaining <= 0

    def finish_turnaround(self, drone_id: str) -> None:
        """Remove turnaround state after drone is ready."""
        self.turnarounds.pop(drone_id, None)

    # -----------------------------------------------------------------------
    # Deck emergencies
    # -----------------------------------------------------------------------

    def set_fire(self, active: bool) -> None:
        """Set or clear flight deck fire."""
        self.fire_active = active
        self.deck_status = "fire" if active else "operational"

    def set_depressurised(self, active: bool) -> None:
        """Set or clear hull breach / depressurisation."""
        self.depressurised = active
        if active:
            self.deck_status = "depressurised"
        elif not self.fire_active:
            self.deck_status = "operational"

    def set_power(self, available: bool) -> None:
        """Set or clear power availability."""
        self.power_available = available
        if not available:
            self.deck_status = "power_loss"
        elif not self.fire_active and not self.depressurised:
            self.deck_status = "operational"

    def start_crash_block(self, rng: random.Random | None = None) -> None:
        """Block recovery slot due to deck crash.

        Also damages recovery system and may start a fire.
        """
        self.crash_block_remaining = CRASH_RECOVERY_BLOCK_TIME
        # Crash damages recovery system.
        self.recovery_health = max(0.0, self.recovery_health - CRASH_RECOVERY_DAMAGE)
        # Chance to start fire.
        r = rng.random() if rng else random.random()
        if r < CRASH_FIRE_CHANCE:
            self.set_fire(True)
            self.pending_events.append({"type": "crash_fire"})
        self.pending_events.append({"type": "deck_crash"})

    def check_crash_risk(self, drone: Drone, rng: random.Random | None = None) -> bool:
        """Check if a recovering drone crashes on deck (hull < threshold).

        Returns True if crash occurs.
        """
        if drone.max_hull <= 0:
            return False
        hull_pct = (drone.hull / drone.max_hull) * 100.0
        if hull_pct >= CRASH_HULL_THRESHOLD:
            return False
        # Drone is critically damaged — crash on deck.
        self.start_crash_block(rng)
        return True

    # -----------------------------------------------------------------------
    # Tick
    # -----------------------------------------------------------------------

    def tick(self, dt: float, rng: random.Random | None = None) -> list[dict]:
        """Advance all flight deck operations by dt seconds.

        Returns a list of events that occurred this tick.
        """
        events: list[dict] = []

        # Crash block countdown.
        if self.crash_block_remaining > 0:
            self.crash_block_remaining = max(0.0, self.crash_block_remaining - dt)
            if self.crash_block_remaining <= 0:
                events.append({"type": "crash_cleared"})

        # Turnaround ticks.
        # turnaround_multiplier < 1.0 means faster (carrier = 0.5 → 2× speed).
        ta_dt = dt / self.turnaround_multiplier if self.turnaround_multiplier > 0 else dt
        for ta in list(self.turnarounds.values()):
            if ta.total_remaining > 0:
                fuel_rate = 1.0
                if self.fuel_lines_health < 100.0:
                    fuel_rate = max(0.1, self.fuel_lines_health / 100.0)

                if ta.needs_refuel and ta.refuel_remaining > 0:
                    ta.refuel_remaining = max(0.0, ta.refuel_remaining - ta_dt * fuel_rate)
                if ta.needs_rearm and ta.rearm_remaining > 0:
                    ta.rearm_remaining = max(0.0, ta.rearm_remaining - ta_dt)
                if ta.needs_repair and ta.repair_remaining > 0:
                    ta.repair_remaining = max(0.0, ta.repair_remaining - ta_dt)

                ta.total_remaining = max(
                    ta.refuel_remaining,
                    ta.rearm_remaining,
                    ta.repair_remaining,
                )
                if ta.total_remaining <= 0:
                    events.append({"type": "turnaround_complete", "drone_id": ta.drone_id})

        # Drain pending events.
        if self.pending_events:
            events.extend(self.pending_events)
            self.pending_events.clear()

        return events

    # -----------------------------------------------------------------------
    # Launch helpers (used by game loop tick)
    # -----------------------------------------------------------------------

    def get_effective_launch_time(self) -> float:
        """Total launch time: prep (3s fixed) + catapult launch (affected by health)."""
        catapult_time = self.launch_time
        if self.catapult_health < 100.0:
            factor = max(0.25, self.catapult_health / 100.0)
            catapult_time = self.launch_time / factor  # damaged = slower
        return LAUNCH_PREP_TIME + catapult_time

    def get_effective_recovery_time(self) -> float:
        """Total recovery time: approach (5s) + catch (5s)."""
        return BASE_RECOVERY_APPROACH_TIME + BASE_RECOVERY_CATCH_TIME

    def roll_launch_failure(self, rng: random.Random | None = None) -> bool:
        """Roll for catapult failure.  Returns True if launch fails."""
        if self.catapult_health >= LAUNCH_FAIL_HEALTH_THRESHOLD:
            return False
        r = rng.random() if rng else random.random()
        return r < LAUNCH_FAIL_CHANCE

    def roll_bolter(self, rng: random.Random | None = None) -> bool:
        """Roll for bolter (missed recovery catch).  Returns True if bolter."""
        chance = 0.0
        if self.recovery_health < BOLTER_HEALTH_THRESHOLD_LOW:
            chance = BOLTER_CHANCE_LOW
        elif self.recovery_health < BOLTER_HEALTH_THRESHOLD_MID:
            chance = BOLTER_CHANCE_MID
        if chance <= 0:
            return False
        r = rng.random() if rng else random.random()
        return r < chance

    def roll_combat_launch_damage(self, rng: random.Random | None = None) -> float:
        """Roll for combat launch damage.  Returns hull damage % (0 if no hit)."""
        r = rng.random() if rng else random.random()
        if r < COMBAT_LAUNCH_DAMAGE_CHANCE:
            return COMBAT_LAUNCH_DAMAGE_AMOUNT
        return 0.0


# ---------------------------------------------------------------------------
# Turnaround state
# ---------------------------------------------------------------------------


@dataclass
class TurnaroundState:
    """Tracks refuel/rearm/repair progress for a single drone."""

    drone_id: str
    needs_refuel: bool = False
    needs_rearm: bool = False
    needs_repair: bool = False
    refuel_remaining: float = 0.0
    rearm_remaining: float = 0.0
    repair_remaining: float = 0.0
    total_remaining: float = 0.0


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_flight_deck(ship_class_id: str) -> FlightDeck:
    """Create a FlightDeck configured for a ship class."""
    from server.models.drones import HANGAR_SLOTS

    slots = HANGAR_SLOTS.get(ship_class_id, 4)

    # Launch tubes and recovery slots scale with hangar size.
    tubes = 1
    rec_slots = 1
    if slots >= 6:
        tubes = 2
        rec_slots = 2
    if slots >= 12:
        tubes = 3
        rec_slots = 2

    # Carrier turnaround is 50% faster (v0.07 §2.6.5).
    ta_mult = 0.5 if ship_class_id == "carrier" else 1.0

    return FlightDeck(
        launch_tubes=tubes,
        recovery_slots=rec_slots,
        hangar_slots=slots,
        turnaround_multiplier=ta_mult,
    )


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def serialise_turnaround(ta: TurnaroundState) -> dict:
    return {
        "drone_id": ta.drone_id,
        "needs_refuel": ta.needs_refuel,
        "needs_rearm": ta.needs_rearm,
        "needs_repair": ta.needs_repair,
        "refuel_remaining": ta.refuel_remaining,
        "rearm_remaining": ta.rearm_remaining,
        "repair_remaining": ta.repair_remaining,
        "total_remaining": ta.total_remaining,
    }


def deserialise_turnaround(data: dict) -> TurnaroundState:
    return TurnaroundState(
        drone_id=data["drone_id"],
        needs_refuel=data.get("needs_refuel", False),
        needs_rearm=data.get("needs_rearm", False),
        needs_repair=data.get("needs_repair", False),
        refuel_remaining=data.get("refuel_remaining", 0.0),
        rearm_remaining=data.get("rearm_remaining", 0.0),
        repair_remaining=data.get("repair_remaining", 0.0),
        total_remaining=data.get("total_remaining", 0.0),
    )


def serialise_flight_deck(fd: FlightDeck) -> dict:
    return {
        "launch_tubes": fd.launch_tubes,
        "launch_time": fd.launch_time,
        "tubes_in_use": list(fd.tubes_in_use),
        "launch_queue": list(fd.launch_queue),
        "recovery_slots": fd.recovery_slots,
        "recovery_time": fd.recovery_time,
        "recovery_in_progress": list(fd.recovery_in_progress),
        "recovery_queue": list(fd.recovery_queue),
        "hangar_slots": fd.hangar_slots,
        "turnarounds": {
            k: serialise_turnaround(v) for k, v in fd.turnarounds.items()
        },
        "drone_fuel_reserve": fd.drone_fuel_reserve,
        "drone_ammo_reserve": fd.drone_ammo_reserve,
        "deck_status": fd.deck_status,
        "catapult_health": fd.catapult_health,
        "recovery_health": fd.recovery_health,
        "fuel_lines_health": fd.fuel_lines_health,
        "control_tower_health": fd.control_tower_health,
        "fire_active": fd.fire_active,
        "depressurised": fd.depressurised,
        "power_available": fd.power_available,
        "crash_block_remaining": fd.crash_block_remaining,
        "turnaround_multiplier": fd.turnaround_multiplier,
    }


def deserialise_flight_deck(data: dict) -> FlightDeck:
    fd = FlightDeck(
        launch_tubes=data.get("launch_tubes", 1),
        launch_time=data.get("launch_time", BASE_LAUNCH_TIME),
        hangar_slots=data.get("hangar_slots", 4),
        recovery_slots=data.get("recovery_slots", 1),
        recovery_time=data.get("recovery_time", BASE_RECOVERY_CATCH_TIME),
    )
    fd.tubes_in_use = list(data.get("tubes_in_use", []))
    fd.launch_queue = list(data.get("launch_queue", []))
    fd.recovery_in_progress = list(data.get("recovery_in_progress", []))
    fd.recovery_queue = list(data.get("recovery_queue", []))
    fd.drone_fuel_reserve = data.get("drone_fuel_reserve", 100.0)
    fd.drone_ammo_reserve = data.get("drone_ammo_reserve", 100.0)
    fd.deck_status = data.get("deck_status", "operational")
    fd.catapult_health = data.get("catapult_health", 100.0)
    fd.recovery_health = data.get("recovery_health", 100.0)
    fd.fuel_lines_health = data.get("fuel_lines_health", 100.0)
    fd.control_tower_health = data.get("control_tower_health", 100.0)
    fd.fire_active = data.get("fire_active", False)
    fd.depressurised = data.get("depressurised", False)
    fd.power_available = data.get("power_available", True)
    fd.crash_block_remaining = data.get("crash_block_remaining", 0.0)
    fd.turnaround_multiplier = data.get("turnaround_multiplier", 1.0)
    ta_data = data.get("turnarounds", {})
    fd.turnarounds = {k: deserialise_turnaround(v) for k, v in ta_data.items()}
    return fd
