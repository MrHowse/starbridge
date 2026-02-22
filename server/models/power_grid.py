"""
Power Grid Model.

Manages reactor output, battery storage, emergency power, and bus routing
for the ship's power distribution system.

The reactor produces power scaled by its health. A battery can store surplus
power and discharge when demand exceeds reactor output. Emergency reserves
provide a small backup budget when the reactor goes offline. Nine ship systems
are split across two power buses; rerouting takes 10 seconds.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Bus assignments — which systems are on which power bus
# ---------------------------------------------------------------------------

PRIMARY_BUS_SYSTEMS: frozenset[str] = frozenset({
    "engines", "shields", "sensors", "manoeuvring",
})
SECONDARY_BUS_SYSTEMS: frozenset[str] = frozenset({
    "beams", "torpedoes", "flight_deck", "ecm_suite", "point_defence",
})
ALL_BUS_SYSTEMS: frozenset[str] = PRIMARY_BUS_SYSTEMS | SECONDARY_BUS_SYSTEMS

# ---------------------------------------------------------------------------
# Defaults (overridden by ship class JSON power_grid section)
# ---------------------------------------------------------------------------

DEFAULT_REACTOR_MAX: float = 700.0
DEFAULT_BATTERY_CAPACITY: float = 500.0
DEFAULT_BATTERY_CHARGE_RATE: float = 50.0      # power units per second
DEFAULT_BATTERY_DISCHARGE_RATE: float = 100.0   # power units per second
DEFAULT_EMERGENCY_RESERVE: float = 100.0        # flat backup budget

REROUTE_DURATION: float = 10.0  # seconds to complete a bus reroute

BATTERY_MODES: tuple[str, ...] = ("charging", "discharging", "standby", "auto")


# ---------------------------------------------------------------------------
# PowerGrid dataclass
# ---------------------------------------------------------------------------


@dataclass
class PowerGrid:
    """Power generation, storage, and distribution for the ship.

    Power flows: Reactor → Buses → Systems.
    Battery supplements or absorbs surplus. Emergency provides backup
    when the reactor is offline.
    """

    # Reactor
    reactor_max: float = DEFAULT_REACTOR_MAX
    reactor_health: float = 100.0   # 0-100%

    # Battery
    battery_capacity: float = DEFAULT_BATTERY_CAPACITY
    battery_charge: float = 250.0   # current energy stored
    battery_charge_rate: float = DEFAULT_BATTERY_CHARGE_RATE
    battery_discharge_rate: float = DEFAULT_BATTERY_DISCHARGE_RATE
    battery_mode: str = "auto"

    # Emergency — flat backup budget when reactor is offline
    emergency_reserve: float = DEFAULT_EMERGENCY_RESERVE
    emergency_active: bool = False

    # Power buses
    primary_bus_online: bool = True
    secondary_bus_online: bool = True
    reroute_active: bool = False
    reroute_timer: float = 0.0
    reroute_target_bus: str | None = None

    # ---- Properties ----

    @property
    def reactor_output(self) -> float:
        """Instantaneous power output, scaled by reactor health."""
        return self.reactor_max * (self.reactor_health / 100.0)

    # ---- Tick ----

    def tick(self, dt: float, system_demands: dict[str, float]) -> dict[str, float]:
        """Process one power tick. Returns actual power delivered per system.

        Args:
            dt: Time step in seconds (typically 0.1 for 10 Hz).
            system_demands: {system_name: requested_power_level} on 0-150 scale.

        Returns:
            {system_name: delivered_power} — may be reduced in brownout.
        """
        if dt <= 0.0:
            return {s: 0.0 for s in system_demands}

        # Advance reroute timer
        if self.reroute_active:
            self.reroute_timer -= dt
            if self.reroute_timer <= 0.0:
                self._complete_reroute()

        # Classify systems by bus status
        active_demands: dict[str, float] = {}
        zeroed: dict[str, float] = {}

        rerouting = self._get_rerouting_systems()

        for sys_name, demand in system_demands.items():
            if sys_name in rerouting:
                zeroed[sys_name] = 0.0
            elif sys_name in PRIMARY_BUS_SYSTEMS and not self.primary_bus_online:
                zeroed[sys_name] = 0.0
            elif sys_name in SECONDARY_BUS_SYSTEMS and not self.secondary_bus_online:
                zeroed[sys_name] = 0.0
            else:
                active_demands[sys_name] = max(0.0, demand)

        total_demand = sum(active_demands.values())

        # Determine available power
        reactor = self.reactor_output

        if reactor <= 0.0:
            # Emergency mode
            self.emergency_active = self.emergency_reserve > 0.0
            base = self.emergency_reserve if self.emergency_active else 0.0
            battery_delta = self._battery_tick(base, total_demand, dt)
            available = base + battery_delta
        else:
            self.emergency_active = False
            battery_delta = self._battery_tick(reactor, total_demand, dt)
            available = reactor + battery_delta

        available = max(0.0, available)

        # Brownout: proportional scaling
        delivered: dict[str, float] = {}
        if total_demand > 0.0 and available < total_demand:
            scale = available / total_demand
            for sys_name, demand in active_demands.items():
                delivered[sys_name] = demand * scale
        else:
            delivered = dict(active_demands)

        # Merge zeroed systems
        delivered.update(zeroed)

        return delivered

    # ---- Battery ----

    def _battery_tick(self, base_power: float, total_demand: float,
                      dt: float) -> float:
        """Handle battery for this tick. Returns power added to budget.

        Positive = discharge (adds power). Negative = charging (subtracts).
        """
        if self.battery_mode == "standby":
            return 0.0

        if self.battery_mode == "discharging":
            return self._discharge(dt)

        if self.battery_mode == "charging":
            return -self._charge(base_power, dt)

        # Auto mode: discharge when deficit, charge from surplus
        if total_demand > base_power and self.battery_charge > 0.0:
            return self._discharge(dt)
        elif total_demand < base_power and self.battery_charge < self.battery_capacity:
            surplus = base_power - total_demand
            self._charge_surplus(surplus, dt)
        return 0.0

    def _discharge(self, dt: float) -> float:
        """Discharge battery. Returns power units added to budget."""
        max_rate = min(self.battery_discharge_rate,
                       self.battery_charge / dt)
        energy = max_rate * dt
        self.battery_charge = max(0.0, self.battery_charge - energy)
        return max_rate

    def _charge(self, available: float, dt: float) -> float:
        """Charge battery from available power. Returns power consumed."""
        room = self.battery_capacity - self.battery_charge
        if room <= 0.0:
            return 0.0
        max_rate = min(self.battery_charge_rate, room / dt, available)
        max_rate = max(0.0, max_rate)
        energy = max_rate * dt
        self.battery_charge = min(self.battery_capacity,
                                  self.battery_charge + energy)
        return max_rate

    def _charge_surplus(self, surplus: float, dt: float) -> None:
        """Charge battery from surplus power (doesn't reduce available)."""
        room = self.battery_capacity - self.battery_charge
        if room <= 0.0:
            return
        rate = min(surplus, self.battery_charge_rate, room / dt)
        rate = max(0.0, rate)
        self.battery_charge = min(self.battery_capacity,
                                  self.battery_charge + rate * dt)

    def set_battery_mode(self, mode: str) -> bool:
        """Set battery mode. Returns True if mode is valid."""
        if mode not in BATTERY_MODES:
            return False
        self.battery_mode = mode
        return True

    # ---- Bus routing ----

    def start_reroute(self, target_bus: str) -> bool:
        """Begin rerouting a bus (takes REROUTE_DURATION seconds).

        During reroute, systems on the target bus receive no power.
        On completion, the bus toggles online/offline.
        """
        if target_bus not in ("primary", "secondary"):
            return False
        if self.reroute_active:
            return False
        self.reroute_active = True
        self.reroute_timer = REROUTE_DURATION
        self.reroute_target_bus = target_bus
        return True

    def _complete_reroute(self) -> None:
        """Complete the reroute: toggle the target bus."""
        if self.reroute_target_bus == "primary":
            self.primary_bus_online = not self.primary_bus_online
        elif self.reroute_target_bus == "secondary":
            self.secondary_bus_online = not self.secondary_bus_online
        self.reroute_active = False
        self.reroute_timer = 0.0
        self.reroute_target_bus = None

    def _get_rerouting_systems(self) -> frozenset[str]:
        """Systems on the bus being rerouted (receive 0 power)."""
        if not self.reroute_active or self.reroute_target_bus is None:
            return frozenset()
        if self.reroute_target_bus == "primary":
            return PRIMARY_BUS_SYSTEMS
        return SECONDARY_BUS_SYSTEMS

    def set_bus_online(self, bus: str, online: bool) -> None:
        """Directly set a bus online/offline."""
        if bus == "primary":
            self.primary_bus_online = online
        elif bus == "secondary":
            self.secondary_bus_online = online

    # ---- Reactor ----

    def damage_reactor(self, amount: float) -> None:
        """Reduce reactor health."""
        self.reactor_health = max(0.0, self.reactor_health - amount)

    def repair_reactor(self, amount: float) -> None:
        """Restore reactor health."""
        self.reactor_health = min(100.0, self.reactor_health + amount)

    # ---- Query ----

    def get_available_budget(self) -> float:
        """Read-only snapshot of current available power budget."""
        reactor = self.reactor_output
        if reactor <= 0.0:
            base = self.emergency_reserve
        else:
            base = reactor

        if self.battery_mode == "discharging" and self.battery_charge > 0.0:
            base += self.battery_discharge_rate
        elif self.battery_mode == "charging":
            base = max(0.0, base - self.battery_charge_rate)

        return max(0.0, base)

    # ---- Serialisation ----

    def serialise(self) -> dict:
        """Serialise power grid state for save/resume."""
        return {
            "reactor_max": self.reactor_max,
            "reactor_health": round(self.reactor_health, 2),
            "battery_capacity": self.battery_capacity,
            "battery_charge": round(self.battery_charge, 2),
            "battery_charge_rate": self.battery_charge_rate,
            "battery_discharge_rate": self.battery_discharge_rate,
            "battery_mode": self.battery_mode,
            "emergency_reserve": self.emergency_reserve,
            "emergency_active": self.emergency_active,
            "primary_bus_online": self.primary_bus_online,
            "secondary_bus_online": self.secondary_bus_online,
            "reroute_active": self.reroute_active,
            "reroute_timer": round(self.reroute_timer, 2),
            "reroute_target_bus": self.reroute_target_bus,
        }

    @classmethod
    def deserialise(cls, data: dict) -> PowerGrid:
        """Restore power grid from saved data."""
        return cls(
            reactor_max=data.get("reactor_max", DEFAULT_REACTOR_MAX),
            reactor_health=data.get("reactor_health", 100.0),
            battery_capacity=data.get("battery_capacity", DEFAULT_BATTERY_CAPACITY),
            battery_charge=data.get("battery_charge", 250.0),
            battery_charge_rate=data.get("battery_charge_rate",
                                        DEFAULT_BATTERY_CHARGE_RATE),
            battery_discharge_rate=data.get("battery_discharge_rate",
                                           DEFAULT_BATTERY_DISCHARGE_RATE),
            battery_mode=data.get("battery_mode", "auto"),
            emergency_reserve=data.get("emergency_reserve",
                                       DEFAULT_EMERGENCY_RESERVE),
            emergency_active=data.get("emergency_active", False),
            primary_bus_online=data.get("primary_bus_online", True),
            secondary_bus_online=data.get("secondary_bus_online", True),
            reroute_active=data.get("reroute_active", False),
            reroute_timer=data.get("reroute_timer", 0.0),
            reroute_target_bus=data.get("reroute_target_bus"),
        )

    @classmethod
    def from_ship_class(cls, config: dict) -> PowerGrid:
        """Create PowerGrid from a ship class JSON power_grid section.

        Battery starts at 50% capacity.
        """
        cap = config.get("battery_capacity", DEFAULT_BATTERY_CAPACITY)
        return cls(
            reactor_max=config.get("reactor_max", DEFAULT_REACTOR_MAX),
            battery_capacity=cap,
            battery_charge=cap / 2.0,
            battery_charge_rate=config.get("battery_charge_rate",
                                           DEFAULT_BATTERY_CHARGE_RATE),
            battery_discharge_rate=config.get("battery_discharge_rate",
                                              DEFAULT_BATTERY_DISCHARGE_RATE),
            emergency_reserve=config.get("emergency_reserve",
                                         DEFAULT_EMERGENCY_RESERVE),
        )
