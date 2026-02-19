"""
Security station data models — Marine squads, intruders, and related constants.

These models are used by:
  server/models/interior.py  — ShipInterior.marine_squads / .intruders fields
  server/game_loop_security.py — tick logic (AP regen, combat, intruder movement)
  server/security.py          — WebSocket handler (move/door commands)

AP economy
----------
  AP_MAX           = 10      — pool capacity
  AP_REGEN_PER_TICK= 0.2     — 1 AP per 5 ticks; full pool fills in 50 ticks = 5 s
  AP_COST_MOVE     = 3       — move one room; squad can move from empty after 15 ticks
  AP_COST_DOOR     = 2       — seal / unseal a door

Intruder movement
-----------------
  INTRUDER_MOVE_INTERVAL = 30 ticks = 3 s between moves (one room per step)

Combat (same room = active combat)
-----------------------------------
  MARINE_DAMAGE_PER_TICK   = 0.2  — health lost by intruder per marine per tick
  INTRUDER_DAMAGE_PER_TICK = 0.15 — health lost by squad per intruder per tick
  SQUAD_CASUALTY_THRESHOLD = 25.0 — squad loses a member (count -= 1) when health
                                     falls below this level and is then healed back
                                     above it (one casualty event per threshold cross)

Fog of war
----------
  SENSOR_FOW_THRESHOLD = 0.5 — sensors.efficiency below this means intruders are
                                 only visible in rooms that share a marine squad
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AP_MAX: float = 10.0
AP_REGEN_PER_TICK: float = 1.0 / 5          # 0.2 — one point every 5 ticks
AP_COST_MOVE: int = 3
AP_COST_DOOR: int = 2

INTRUDER_MOVE_INTERVAL: int = 30             # ticks between intruder steps

MARINE_DAMAGE_PER_TICK: float = 0.2         # damage dealt TO intruder per marine per tick
INTRUDER_DAMAGE_PER_TICK: float = 0.15      # damage dealt TO squad per intruder per tick
SQUAD_CASUALTY_THRESHOLD: float = 25.0      # squad takes a casualty when health drops here

SENSOR_FOW_THRESHOLD: float = 0.5           # sensors.efficiency < this → fog of war active


# ---------------------------------------------------------------------------
# Marine squad
# ---------------------------------------------------------------------------


@dataclass
class MarineSquad:
    """One marine squad aboard the ship."""

    id: str                           # "squad_1", "squad_2", etc.
    room_id: str                      # Current room (interior room id)
    health: float = 100.0             # Squad health 0–100
    action_points: float = AP_MAX     # Current AP pool
    count: int = 4                    # Active marines in squad

    # Track whether this squad has crossed the casualty threshold (prevents
    # repeated casualties from a single hit event).
    _casualty_pending: bool = field(default=False, repr=False, compare=False)

    # ------------------------------------------------------------------
    # AP helpers
    # ------------------------------------------------------------------

    def regen_ap(self) -> None:
        """Add one tick's worth of AP, capped at AP_MAX."""
        self.action_points = min(AP_MAX, self.action_points + AP_REGEN_PER_TICK)

    def can_move(self) -> bool:
        return self.action_points >= AP_COST_MOVE

    def deduct_move_ap(self) -> None:
        """Deduct AP for a move. Caller must check can_move() first."""
        self.action_points -= AP_COST_MOVE

    def can_seal_door(self) -> bool:
        return self.action_points >= AP_COST_DOOR

    def deduct_door_ap(self) -> None:
        """Deduct AP for door control. Caller must check can_seal_door() first."""
        self.action_points -= AP_COST_DOOR

    # ------------------------------------------------------------------
    # Combat + casualties
    # ------------------------------------------------------------------

    def take_damage(self, amount: float) -> bool:
        """Reduce health by amount. Returns True if a casualty occurred.

        A casualty occurs the first time health falls to or below
        SQUAD_CASUALTY_THRESHOLD and count > 0. Subsequent ticks at low
        health do not generate additional casualties until health recovers
        above the threshold (the _casualty_pending flag tracks this).
        """
        self.health = max(0.0, self.health - amount)
        casualty = False

        if self.health <= SQUAD_CASUALTY_THRESHOLD and not self._casualty_pending and self.count > 0:
            self.count -= 1
            self._casualty_pending = True
            casualty = True
        elif self.health > SQUAD_CASUALTY_THRESHOLD:
            # Health recovered — next dip below threshold can cause another casualty.
            self._casualty_pending = False

        return casualty

    def is_eliminated(self) -> bool:
        """True when the squad has no marines left."""
        return self.count <= 0


# ---------------------------------------------------------------------------
# Intruder
# ---------------------------------------------------------------------------


@dataclass
class Intruder:
    """One hostile boarding party moving through the ship."""

    id: str                                      # "intruder_1", etc.
    room_id: str                                 # Current room
    objective_id: str                            # Target room id
    health: float = 100.0                        # Health 0–100
    move_timer: int = INTRUDER_MOVE_INTERVAL     # Ticks until next move (0 = ready)

    # ------------------------------------------------------------------
    # Movement timer
    # ------------------------------------------------------------------

    def tick_move_timer(self) -> None:
        """Decrement the move timer by one tick (floor at 0)."""
        self.move_timer = max(0, self.move_timer - 1)

    def is_ready_to_move(self) -> bool:
        return self.move_timer <= 0

    def reset_move_timer(self) -> None:
        self.move_timer = INTRUDER_MOVE_INTERVAL

    # ------------------------------------------------------------------
    # Combat
    # ------------------------------------------------------------------

    def take_damage(self, amount: float) -> None:
        self.health = max(0.0, self.health - amount)

    def is_defeated(self) -> bool:
        return self.health <= 0.0


# ---------------------------------------------------------------------------
# Fog-of-war helper
# ---------------------------------------------------------------------------


def is_intruder_visible(
    intruder: Intruder,
    marine_squads: list[MarineSquad],
    sensor_efficiency: float,
) -> bool:
    """Return True if the intruder should be visible to the Security station.

    Visibility rules:
      1. Always visible if a marine squad occupies the same room.
      2. Always visible if sensor efficiency >= SENSOR_FOW_THRESHOLD.
      3. Otherwise invisible (fog of war active).
    """
    # Rule 1: line-of-sight via squad presence.
    if any(sq.room_id == intruder.room_id for sq in marine_squads):
        return True
    # Rule 2: sensors are healthy enough to detect throughout the ship.
    if sensor_efficiency >= SENSOR_FOW_THRESHOLD:
        return True
    return False
