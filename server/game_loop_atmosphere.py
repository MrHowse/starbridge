"""
Atmosphere System — per-room atmospheric simulation (v0.08 B.3).

Tracks oxygen, pressure, temperature, and contamination (smoke/coolant/
radiation/chemical) for every room in the ship interior.  Hull breaches cause
decompression; fires consume oxygen and produce smoke; ventilation controls
allow routing atmosphere between rooms; life support restores atmosphere.

Cross-station effects penalise crew and equipment in hazardous conditions.

Life support efficiency = average health of all 9 ship systems — damage
naturally degrades life support without requiring a 10th system.

State is module-level; reset() is called at game start.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from server.models.interior import ShipInterior

logger = logging.getLogger("starbridge.atmosphere")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Normal atmosphere
NORMAL_O2: float = 21.0
NORMAL_PRESSURE: float = 101.3
NORMAL_TEMP: float = 22.0

# Life support restoration (per second at full efficiency)
LS_O2_RATE: float = 0.2          # 2%/10s
LS_PRESSURE_RATE: float = 0.5    # 5kPa/10s
LS_TEMP_RATE: float = 0.1        # 1°C/10s toward normal

# Breach decompression (kPa/s)
MAJOR_BREACH_RATE: float = 10.0       # 10s to vacuum
MINOR_BREACH_RATE: float = 3.38       # 30s to vacuum
BREACH_TEMP_RATE: float = 2.0         # °C/s cooling

# Breach response
FORCE_FIELD_DURATION: float = 120.0
BULKHEAD_SEAL_TIME: float = 5.0
EVACUATION_TIME: float = 10.0
TORPEDO_BREACH_CHANCE: float = 0.70
HEAVY_BEAM_BREACH_CHANCE: float = 0.30

# Vacuum effects (per second)
VACUUM_CREW_DAMAGE: float = 10.0
VACUUM_EQUIP_DAMAGE: float = 3.0
EVA_REPAIR_MULT: float = 2.0

# Fire → atmosphere (per second, per intensity level)
FIRE_TEMP_RATE: float = 0.1       # 3°C/int/30s
FIRE_O2_RATE: float = 0.033       # 1%/int/30s
FIRE_SMOKE_RATE: float = 0.167    # 5%/int/30s

# Coolant leak (per second)
COOLANT_CONTAM_RATE: float = 0.333    # 10%/30s
COOLANT_DAMAGE_THRESHOLD: float = 30.0

# Ventilation
FILTERED_SCRUB_RATE: float = 0.167    # 5%/30s
VENT_EXCHANGE_RATE: float = 0.10      # 10% of difference per second
SPACE_VENT_REPRESSURE_TIME: float = 75.0  # seconds to repressurise

# Cross-station thresholds
LOW_O2_THRESHOLD: float = 15.0
LOW_O2_PENALTY: float = 0.40
LOW_O2_HP_RATE: float = 0.033         # 1 HP/30s
LOW_O2_REPAIR_PENALTY: float = 0.50
HIGH_TEMP_THRESHOLD: float = 40.0
HIGH_TEMP_PENALTY: float = 0.20
HIGH_TEMP_EQUIP_RATE: float = 0.033   # 1%/30s
HIGH_CONTAM_THRESHOLD: float = 50.0

# Fire oxygen starvation threshold
FIRE_O2_STARVATION: float = 5.0

# ---------------------------------------------------------------------------
# Radiation constants (B.4)
# ---------------------------------------------------------------------------

# Reactor leak
REACTOR_LEAK_THRESHOLD: float = 60.0
REACTOR_SERIOUS_THRESHOLD: float = 30.0
REACTOR_LEAK_RATE: float = 0.5          # radiation/s to engineering rooms
REACTOR_SERIOUS_LEAK_RATE: float = 2.0  # radiation/s to eng + adjacent

# Shield leak
SHIELD_LEAK_THRESHOLD: float = 25.0
SHIELD_LEAK_RATE: float = 0.1           # radiation/s to outer decks

# Nuclear torpedo
NUCLEAR_HIT_RADIATION: float = 80.0     # contamination on hit deck
NUCLEAR_ADJACENT_RADIATION: float = 40.0

# Decontamination teams
DECON_INTERVAL: float = 30.0
DECON_REDUCTION: float = 10.0           # % per interval
DECON_TEAM_DAMAGE_REDUCTION: float = 0.50

# Radiation zone tiers
RAD_AMBER_THRESHOLD: float = 11.0
RAD_ORANGE_THRESHOLD: float = 31.0
RAD_RED_THRESHOLD: float = 61.0
RAD_AMBER_HP_RATE: float = 0.0083       # 0.5 HP/60s
RAD_ORANGE_HP_RATE: float = 0.033       # 1 HP/30s
RAD_RED_HP_RATE: float = 0.3            # 3 HP/10s

# Radiation sickness timers (seconds of exposure)
RAD_AMBER_SICKNESS_TIME: float = 180.0  # 3 minutes
RAD_ORANGE_SICKNESS_TIME: float = 60.0  # 1 minute

# Cross-station
RAD_ENGINEERING_EFF_PENALTY: float = 0.30
RAD_SENSOR_MAX_PENALTY: float = 0.30


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AtmosphereState:
    """Atmospheric conditions in a single room."""

    oxygen_percent: float = 21.0     # 0–100
    pressure_kpa: float = 101.3      # 0–101.3
    temperature_c: float = 22.0      # normal 22
    smoke: float = 0.0               # 0–100
    coolant: float = 0.0             # 0–100
    radiation: float = 0.0           # 0–100
    chemical: float = 0.0            # 0–100

    @property
    def contamination_level(self) -> float:
        return max(self.smoke, self.coolant, self.radiation, self.chemical)

    @property
    def contamination_type(self) -> str:
        vals = {"smoke": self.smoke, "coolant": self.coolant,
                "radiation": self.radiation, "chemical": self.chemical}
        best = max(vals, key=lambda k: vals[k])
        return best if vals[best] > 0 else "none"


@dataclass
class Breach:
    """One active hull breach in a room."""

    room_id: str
    severity: str                      # "minor" / "major"
    force_field_active: bool = False
    force_field_timer: float = 0.0     # seconds remaining
    bulkhead_sealed: bool = False
    bulkhead_timer: float = 0.0        # 5s countdown (>0 = sealing in progress)
    evacuating: bool = False
    evacuation_timer: float = 0.0      # 10s countdown


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_atmosphere: dict[str, AtmosphereState] = {}   # room_id → state
_breaches: dict[str, Breach] = {}              # room_id → breach
_vent_states: dict[tuple[str, str], str] = {}  # sorted (room_a, room_b) → "open"/"filtered"/"sealed"
_space_vent_rooms: set[str] = set()            # rooms being vented to space
_coolant_leaks: set[str] = set()               # rooms with active coolant leaks
_decon_teams: dict[str, float] = {}            # room_id → elapsed seconds (B.4)
_radiation_exposure: dict[str, float] = {}     # deck_name → cumulative seconds in radiation zone (B.4)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def reset() -> None:
    """Clear all module state. Called at game start / resume."""
    _atmosphere.clear()
    _breaches.clear()
    _vent_states.clear()
    _space_vent_rooms.clear()
    _coolant_leaks.clear()
    _decon_teams.clear()
    _radiation_exposure.clear()


def init_atmosphere(interior: ShipInterior) -> None:
    """Initialise atmosphere for all rooms in the interior to normal values."""
    _atmosphere.clear()
    for room_id in interior.rooms:
        _atmosphere[room_id] = AtmosphereState()
    # Initialise ventilation connections as open for all adjacent room pairs.
    _vent_states.clear()
    for room_id, room in interior.rooms.items():
        for conn_id in room.connections:
            key = _vent_key(room_id, conn_id)
            if key not in _vent_states:
                _vent_states[key] = "open"


def _vent_key(a: str, b: str) -> tuple[str, str]:
    """Canonical sorted key for a vent connection."""
    return (min(a, b), max(a, b))


# ---------------------------------------------------------------------------
# Serialise / Deserialise
# ---------------------------------------------------------------------------

def serialise() -> dict:
    """Serialise atmosphere state for save system."""
    atm_data = {}
    for rid, a in _atmosphere.items():
        atm_data[rid] = {
            "oxygen_percent": a.oxygen_percent,
            "pressure_kpa": a.pressure_kpa,
            "temperature_c": a.temperature_c,
            "smoke": a.smoke,
            "coolant": a.coolant,
            "radiation": a.radiation,
            "chemical": a.chemical,
        }
    breach_data = {}
    for rid, b in _breaches.items():
        breach_data[rid] = {
            "severity": b.severity,
            "force_field_active": b.force_field_active,
            "force_field_timer": b.force_field_timer,
            "bulkhead_sealed": b.bulkhead_sealed,
            "bulkhead_timer": b.bulkhead_timer,
            "evacuating": b.evacuating,
            "evacuation_timer": b.evacuation_timer,
        }
    vent_data = {f"{k[0]}|{k[1]}": v for k, v in _vent_states.items()}
    return {
        "atmosphere": atm_data,
        "breaches": breach_data,
        "vent_states": vent_data,
        "space_vent_rooms": list(_space_vent_rooms),
        "coolant_leaks": list(_coolant_leaks),
        "decon_teams": dict(_decon_teams),
        "radiation_exposure": dict(_radiation_exposure),
    }


def deserialise(data: dict) -> None:
    """Restore atmosphere state from save data."""
    _atmosphere.clear()
    for rid, ad in data.get("atmosphere", {}).items():
        _atmosphere[rid] = AtmosphereState(
            oxygen_percent=ad.get("oxygen_percent", NORMAL_O2),
            pressure_kpa=ad.get("pressure_kpa", NORMAL_PRESSURE),
            temperature_c=ad.get("temperature_c", NORMAL_TEMP),
            smoke=ad.get("smoke", 0.0),
            coolant=ad.get("coolant", 0.0),
            radiation=ad.get("radiation", 0.0),
            chemical=ad.get("chemical", 0.0),
        )
    _breaches.clear()
    for rid, bd in data.get("breaches", {}).items():
        _breaches[rid] = Breach(
            room_id=rid,
            severity=bd.get("severity", "minor"),
            force_field_active=bd.get("force_field_active", False),
            force_field_timer=bd.get("force_field_timer", 0.0),
            bulkhead_sealed=bd.get("bulkhead_sealed", False),
            bulkhead_timer=bd.get("bulkhead_timer", 0.0),
            evacuating=bd.get("evacuating", False),
            evacuation_timer=bd.get("evacuation_timer", 0.0),
        )
    _vent_states.clear()
    for key_str, state in data.get("vent_states", {}).items():
        parts = key_str.split("|")
        if len(parts) == 2:
            _vent_states[(parts[0], parts[1])] = state
    _space_vent_rooms.clear()
    _space_vent_rooms.update(data.get("space_vent_rooms", []))
    _coolant_leaks.clear()
    _coolant_leaks.update(data.get("coolant_leaks", []))
    _decon_teams.clear()
    _decon_teams.update(data.get("decon_teams", {}))
    _radiation_exposure.clear()
    _radiation_exposure.update(data.get("radiation_exposure", {}))


# ---------------------------------------------------------------------------
# Breach management
# ---------------------------------------------------------------------------

def create_breach(room_id: str, severity: str, interior: ShipInterior) -> None:
    """Create a hull breach in a room. Severity: 'minor' or 'major'."""
    if room_id not in interior.rooms:
        return
    if room_id in _breaches:
        # Upgrade minor → major if new breach is major.
        if severity == "major" and _breaches[room_id].severity == "minor":
            _breaches[room_id].severity = "major"
            _breaches[room_id].force_field_active = False
            _breaches[room_id].force_field_timer = 0.0
        return
    _breaches[room_id] = Breach(room_id=room_id, severity=severity)
    interior.rooms[room_id].state = "damaged"
    logger.info("Hull breach (%s) in room %s", severity, room_id)


def apply_force_field(room_id: str) -> bool:
    """Activate force field on a breach. Returns True if successful."""
    breach = _breaches.get(room_id)
    if breach is None or breach.bulkhead_sealed:
        return False
    breach.force_field_active = True
    breach.force_field_timer = FORCE_FIELD_DURATION
    logger.info("Force field activated in room %s", room_id)
    return True


def seal_bulkhead(room_id: str) -> bool:
    """Begin sealing bulkhead on a breach. 5s delay. Returns True if started."""
    breach = _breaches.get(room_id)
    if breach is None or breach.bulkhead_sealed:
        return False
    if breach.bulkhead_timer > 0:
        return False  # Already sealing
    breach.bulkhead_timer = BULKHEAD_SEAL_TIME
    logger.info("Bulkhead seal started in room %s", room_id)
    return True


def unseal_bulkhead(room_id: str) -> bool:
    """Remove bulkhead seal from a breach. Returns True if successful."""
    breach = _breaches.get(room_id)
    if breach is None or not breach.bulkhead_sealed:
        return False
    breach.bulkhead_sealed = False
    logger.info("Bulkhead unsealed in room %s", room_id)
    return True


def order_evacuation(room_id: str, interior: ShipInterior) -> bool:
    """Order crew evacuation from a room. 10s delay. Returns True if started."""
    breach = _breaches.get(room_id)
    if breach is None:
        return False
    if room_id not in interior.rooms:
        return False
    breach.evacuating = True
    breach.evacuation_timer = EVACUATION_TIME
    logger.info("Evacuation ordered in room %s", room_id)
    return True


# ---------------------------------------------------------------------------
# Ventilation management
# ---------------------------------------------------------------------------

def cycle_vent_state(room_a: str, room_b: str) -> str:
    """Cycle vent between two rooms: open → filtered → sealed → open."""
    key = _vent_key(room_a, room_b)
    current = _vent_states.get(key, "open")
    cycle = {"open": "filtered", "filtered": "sealed", "sealed": "open"}
    new_state = cycle[current]
    _vent_states[key] = new_state
    return new_state


def set_vent_state(room_a: str, room_b: str, state: str) -> None:
    """Set vent state explicitly."""
    key = _vent_key(room_a, room_b)
    _vent_states[key] = state


def emergency_vent_to_space(room_id: str) -> None:
    """Vent a room to space — clears atmosphere instantly."""
    _space_vent_rooms.add(room_id)
    atm = _atmosphere.get(room_id)
    if atm:
        atm.pressure_kpa = 0.0
        atm.oxygen_percent = 0.0
        atm.smoke = 0.0
        atm.coolant = 0.0
        atm.radiation = 0.0
        atm.chemical = 0.0
        atm.temperature_c = -270.0  # near absolute zero
    logger.info("Emergency vent to space: room %s", room_id)


def cancel_space_vent(room_id: str) -> None:
    """Stop venting to space and begin repressurisation."""
    _space_vent_rooms.discard(room_id)
    logger.info("Space vent cancelled: room %s — repressurising", room_id)


# ---------------------------------------------------------------------------
# Coolant leak management
# ---------------------------------------------------------------------------

def start_coolant_leak(room_id: str) -> None:
    """Start a coolant leak in a room."""
    _coolant_leaks.add(room_id)


def stop_coolant_leak(room_id: str) -> None:
    """Stop a coolant leak in a room."""
    _coolant_leaks.discard(room_id)


# ---------------------------------------------------------------------------
# Decon team management (B.4)
# ---------------------------------------------------------------------------

def dispatch_decon_team(room_id: str) -> bool:
    """Dispatch a decontamination team to a room. Returns True if created."""
    if room_id not in _atmosphere:
        return False
    if room_id in _decon_teams:
        return False  # already dispatched
    _decon_teams[room_id] = 0.0
    logger.info("Decon team dispatched to room %s", room_id)
    return True


def cancel_decon_team(room_id: str) -> bool:
    """Recall a decontamination team. Returns True if cancelled."""
    if room_id in _decon_teams:
        del _decon_teams[room_id]
        logger.info("Decon team recalled from room %s", room_id)
        return True
    return False


def get_decon_teams() -> dict[str, float]:
    """Return current decon team state (read-only intent)."""
    return _decon_teams


# ---------------------------------------------------------------------------
# Nuclear torpedo radiation (B.4)
# ---------------------------------------------------------------------------

def apply_nuclear_radiation(interior: ShipInterior, deck_name: str) -> None:
    """Apply radiation from nuclear torpedo detonation.

    Hit deck rooms → NUCLEAR_HIT_RADIATION, adjacent deck rooms → NUCLEAR_ADJACENT_RADIATION.
    """
    hit_deck_number: int | None = None
    for room in interior.rooms.values():
        if room.deck == deck_name:
            hit_deck_number = room.deck_number
            break
    if hit_deck_number is None:
        return

    for room_id, room in interior.rooms.items():
        atm = _atmosphere.get(room_id)
        if atm is None:
            continue
        if room.deck == deck_name:
            atm.radiation = min(100.0, max(atm.radiation, NUCLEAR_HIT_RADIATION))
        elif abs(room.deck_number - hit_deck_number) == 1:
            atm.radiation = min(100.0, max(atm.radiation, NUCLEAR_ADJACENT_RADIATION))
    logger.info("Nuclear radiation applied: deck %s (hit), adjacent decks", deck_name)


# ---------------------------------------------------------------------------
# Query API
# ---------------------------------------------------------------------------

def get_atmosphere(room_id: str) -> AtmosphereState | None:
    """Return atmospheric state for a room, or None if not tracked."""
    return _atmosphere.get(room_id)


def get_breaches() -> dict[str, Breach]:
    """Return all active breaches (read-only intent)."""
    return _breaches


def is_vacuum(room_id: str) -> bool:
    """True if room is at vacuum (0 kPa)."""
    atm = _atmosphere.get(room_id)
    return atm is not None and atm.pressure_kpa <= 0.0


def get_repair_speed_modifier(room_id: str) -> float:
    """Return repair speed modifier for a room. 1.0 = normal, 0.5 = low O2, 2.0 = EVA."""
    if is_vacuum(room_id):
        return EVA_REPAIR_MULT
    atm = _atmosphere.get(room_id)
    if atm and atm.oxygen_percent < LOW_O2_THRESHOLD:
        return 1.0 + LOW_O2_REPAIR_PENALTY  # 1.5× duration (slower)
    return 1.0


def get_sensor_radiation_penalty(interior: ShipInterior) -> float:
    """Return sensor accuracy penalty (0.0–0.30) from radiation on the sensors deck."""
    max_rad = 0.0
    for room_id, room in interior.rooms.items():
        if room.deck != "sensors":
            continue
        atm = _atmosphere.get(room_id)
        if atm is not None and atm.radiation > max_rad:
            max_rad = atm.radiation
    if max_rad <= RAD_AMBER_THRESHOLD:
        return 0.0
    # Scale linearly from 0 at AMBER threshold to RAD_SENSOR_MAX_PENALTY at 100
    return min(RAD_SENSOR_MAX_PENALTY,
               RAD_SENSOR_MAX_PENALTY * (max_rad - RAD_AMBER_THRESHOLD) / (100.0 - RAD_AMBER_THRESHOLD))


def get_radiation_exposure() -> dict[str, float]:
    """Return current radiation exposure tracking (read-only intent)."""
    return _radiation_exposure


def get_atmosphere_penalties(interior: ShipInterior | None = None) -> dict[str, dict]:
    """Return per-room atmosphere penalties for cross-station effects.

    Returns {room_id: {"crew_eff_penalty": float, "crew_hp_rate": float,
                        "equip_degrade_rate": float}}.
    """
    penalties: dict[str, dict] = {}
    for room_id, atm in _atmosphere.items():
        p: dict[str, float] = {"crew_eff_penalty": 0.0, "crew_hp_rate": 0.0,
                                "equip_degrade_rate": 0.0}
        # Low O2
        if atm.oxygen_percent < LOW_O2_THRESHOLD:
            p["crew_eff_penalty"] = max(p["crew_eff_penalty"], LOW_O2_PENALTY)
            p["crew_hp_rate"] += LOW_O2_HP_RATE
        # High temp
        if atm.temperature_c > HIGH_TEMP_THRESHOLD:
            p["crew_eff_penalty"] = max(p["crew_eff_penalty"], HIGH_TEMP_PENALTY)
            p["equip_degrade_rate"] += HIGH_TEMP_EQUIP_RATE
        # High contamination (non-radiation types use old flat thresholds)
        if atm.contamination_level > HIGH_CONTAM_THRESHOLD:
            ctype = atm.contamination_type
            if ctype == "smoke":
                p["crew_hp_rate"] += 0.017    # minor: ~0.5 HP/30s
            elif ctype == "coolant":
                p["crew_hp_rate"] += 0.033    # moderate: 1 HP/30s
            elif ctype == "chemical":
                p["crew_hp_rate"] += 0.050    # 1.5 HP/30s
        # B.4: Tiered radiation damage (replaces flat radiation penalty)
        if atm.radiation >= RAD_RED_THRESHOLD:
            p["crew_hp_rate"] += RAD_RED_HP_RATE
        elif atm.radiation >= RAD_ORANGE_THRESHOLD:
            p["crew_hp_rate"] += RAD_ORANGE_HP_RATE
        elif atm.radiation >= RAD_AMBER_THRESHOLD:
            p["crew_hp_rate"] += RAD_AMBER_HP_RATE
        # B.4: Engineering deck radiation → crew efficiency penalty
        if interior is not None and atm.radiation >= RAD_AMBER_THRESHOLD:
            room = interior.rooms.get(room_id)
            if room is not None and room.deck == "engineering":
                p["crew_eff_penalty"] = max(p["crew_eff_penalty"], RAD_ENGINEERING_EFF_PENALTY)
        # Decon team: 50% reduced crew damage in room
        if room_id in _decon_teams:
            p["crew_hp_rate"] *= (1.0 - DECON_TEAM_DAMAGE_REDUCTION)
        # Vacuum
        if atm.pressure_kpa <= 0.0:
            p["crew_hp_rate"] = VACUUM_CREW_DAMAGE
            p["equip_degrade_rate"] = VACUUM_EQUIP_DAMAGE
            p["crew_eff_penalty"] = 1.0  # 100% penalty
        if p["crew_eff_penalty"] > 0 or p["crew_hp_rate"] > 0 or p["equip_degrade_rate"] > 0:
            penalties[room_id] = p
    return penalties


def get_deck_atmosphere_summary(interior: ShipInterior) -> dict[str, dict]:
    """Return per-deck atmosphere summary for Medical station display.

    Returns {deck_name: {"avg_o2": float, "avg_pressure": float,
                          "avg_temp": float, "max_contam": float,
                          "contam_type": str, "breach_count": int}}.
    """
    decks: dict[str, list[AtmosphereState]] = {}
    for room_id, atm in _atmosphere.items():
        room = interior.rooms.get(room_id)
        if room is None:
            continue
        decks.setdefault(room.deck, []).append(atm)
    # Count breaches per deck
    breach_counts: dict[str, int] = {}
    for rid in _breaches:
        room = interior.rooms.get(rid)
        if room:
            breach_counts[room.deck] = breach_counts.get(room.deck, 0) + 1
    summary: dict[str, dict] = {}
    for deck_name, atm_list in decks.items():
        n = len(atm_list)
        avg_o2 = sum(a.oxygen_percent for a in atm_list) / n
        avg_pressure = sum(a.pressure_kpa for a in atm_list) / n
        avg_temp = sum(a.temperature_c for a in atm_list) / n
        max_contam = max(a.contamination_level for a in atm_list)
        # Find dominant contam type across deck
        worst_atm = max(atm_list, key=lambda a: a.contamination_level)
        summary[deck_name] = {
            "avg_o2": round(avg_o2, 1),
            "avg_pressure": round(avg_pressure, 1),
            "avg_temp": round(avg_temp, 1),
            "max_contam": round(max_contam, 1),
            "contam_type": worst_atm.contamination_type,
            "breach_count": breach_counts.get(deck_name, 0),
        }
    return summary


# ---------------------------------------------------------------------------
# Broadcast state builder
# ---------------------------------------------------------------------------

def build_atmosphere_state(interior: ShipInterior) -> dict:
    """Build atmosphere state dict for broadcasting to Hazard Control."""
    rooms: dict[str, dict] = {}
    for room_id, atm in _atmosphere.items():
        room = interior.rooms.get(room_id)
        if room is None:
            continue
        rooms[room_id] = {
            "name": room.name,
            "deck": room.deck,
            "o2": round(atm.oxygen_percent, 1),
            "pressure": round(atm.pressure_kpa, 1),
            "temp": round(atm.temperature_c, 1),
            "smoke": round(atm.smoke, 1),
            "coolant": round(atm.coolant, 1),
            "radiation": round(atm.radiation, 1),
            "chemical": round(atm.chemical, 1),
            "contam_level": round(atm.contamination_level, 1),
            "contam_type": atm.contamination_type,
        }
    breaches_out: dict[str, dict] = {}
    for rid, b in _breaches.items():
        breaches_out[rid] = {
            "severity": b.severity,
            "force_field": b.force_field_active,
            "force_field_timer": round(b.force_field_timer, 1),
            "bulkhead_sealed": b.bulkhead_sealed,
            "bulkhead_timer": round(b.bulkhead_timer, 1),
            "evacuating": b.evacuating,
            "evacuation_timer": round(b.evacuation_timer, 1),
        }
    vents_out: dict[str, str] = {}
    for key, state in _vent_states.items():
        vents_out[f"{key[0]}|{key[1]}"] = state
    # B.4: Radiation zone tier per room
    for room_id in rooms:
        rad = rooms[room_id]["radiation"]
        if rad >= RAD_RED_THRESHOLD:
            rooms[room_id]["rad_zone"] = "red"
        elif rad >= RAD_ORANGE_THRESHOLD:
            rooms[room_id]["rad_zone"] = "orange"
        elif rad >= RAD_AMBER_THRESHOLD:
            rooms[room_id]["rad_zone"] = "amber"
        else:
            rooms[room_id]["rad_zone"] = "green"
    return {
        "rooms": rooms,
        "breaches": breaches_out,
        "vents": vents_out,
        "space_venting": list(_space_vent_rooms),
        "coolant_leaks": list(_coolant_leaks),
        "decon_teams": {rid: round(elapsed, 1) for rid, elapsed in _decon_teams.items()},
    }


# ---------------------------------------------------------------------------
# Tick — main simulation step
# ---------------------------------------------------------------------------

def _get_life_support_efficiency(ship) -> float:
    """Life support efficiency = average efficiency of all ship systems."""
    systems = getattr(ship, "systems", None)
    if not systems:
        return 1.0
    efficiencies = [sys.efficiency for sys in systems.values()]
    if not efficiencies:
        return 1.0
    return sum(efficiencies) / len(efficiencies)


def tick(interior: ShipInterior, dt: float, ship=None, fires: dict | None = None) -> list[dict]:
    """Advance atmosphere simulation for one tick.

    Parameters:
        interior: Ship interior layout.
        dt: Time step in seconds.
        ship: Ship object (for life support efficiency).
        fires: dict of room_id → Fire objects from glhc.

    Returns list of event dicts for broadcasting.
    """
    events: list[dict] = []
    if fires is None:
        fires = {}

    # 1. Breach decompression
    _tick_breaches(interior, dt, events)

    # 2. Fire effects (temp/O2/smoke)
    _tick_fire_effects(dt, fires)

    # 3. Coolant leak effects
    _tick_coolant_leaks(dt)

    # 3.5. Radiation sources (B.4)
    _tick_radiation_sources(interior, dt, ship)

    # 3.6. Decontamination teams (B.4)
    _tick_decon_teams(dt, events)

    # 3.7. Radiation exposure tracking (B.4)
    _tick_radiation_exposure(interior, dt, events)

    # 4. Ventilation exchange between open-connected rooms
    _tick_vent_exchange(dt)

    # 5. Filtered ventilation scrubbing
    _tick_filtered_scrub(dt)

    # 6. Life support restoration
    ls_eff = _get_life_support_efficiency(ship) if ship else 1.0
    _tick_life_support(dt, ls_eff)

    # 7. Force field / bulkhead / evacuation timers
    _tick_breach_timers(dt, events)

    # 8. Vacuum damage (crew/equipment at 0 kPa)
    _tick_vacuum_damage(interior, dt, events)

    # 9. Space vent — rooms being vented stay at vacuum
    _tick_space_vent()

    # 10. Fire oxygen starvation (O2 < 5% → extinguish)
    _tick_fire_starvation(fires, events)

    # Clamp all values
    _clamp_all()

    return events


# ---------------------------------------------------------------------------
# Tick helpers
# ---------------------------------------------------------------------------

def _tick_breaches(interior: ShipInterior, dt: float, events: list[dict]) -> None:
    """Apply decompression from active breaches."""
    for rid, breach in _breaches.items():
        if breach.force_field_active or breach.bulkhead_sealed:
            continue
        atm = _atmosphere.get(rid)
        if atm is None or atm.pressure_kpa <= 0.0:
            continue
        rate = MAJOR_BREACH_RATE if breach.severity == "major" else MINOR_BREACH_RATE
        # Pressure drops
        pressure_loss = rate * dt
        old_pressure = atm.pressure_kpa
        atm.pressure_kpa = max(0.0, atm.pressure_kpa - pressure_loss)
        # O2 drops proportionally to pressure loss
        if old_pressure > 0:
            o2_loss = (pressure_loss / old_pressure) * atm.oxygen_percent
            atm.oxygen_percent = max(0.0, atm.oxygen_percent - o2_loss)
        # Temperature drops toward space
        atm.temperature_c -= BREACH_TEMP_RATE * dt
        # Check if room just reached vacuum
        if atm.pressure_kpa <= 0.0:
            atm.pressure_kpa = 0.0
            atm.oxygen_percent = 0.0
            room = interior.rooms.get(rid)
            if room and room.state != "decompressed":
                room.state = "decompressed"
                events.append({"type": "breach_vacuum", "room_id": rid})
                logger.info("Room %s reached vacuum", rid)


def _tick_fire_effects(dt: float, fires: dict) -> None:
    """Apply fire effects on atmosphere: raise temp, drop O2, raise smoke."""
    for rid, fire in fires.items():
        atm = _atmosphere.get(rid)
        if atm is None:
            continue
        intensity = getattr(fire, "intensity", 1)
        atm.temperature_c += FIRE_TEMP_RATE * intensity * dt
        atm.oxygen_percent = max(0.0, atm.oxygen_percent - FIRE_O2_RATE * intensity * dt)
        atm.smoke = min(100.0, atm.smoke + FIRE_SMOKE_RATE * intensity * dt)


def _tick_coolant_leaks(dt: float) -> None:
    """Apply coolant contamination from active leaks."""
    for rid in _coolant_leaks:
        atm = _atmosphere.get(rid)
        if atm is None:
            continue
        atm.coolant = min(100.0, atm.coolant + COOLANT_CONTAM_RATE * dt)


def _tick_vent_exchange(dt: float) -> None:
    """Exchange atmosphere between open-connected rooms."""
    for (room_a, room_b), state in _vent_states.items():
        if state != "open":
            continue
        atm_a = _atmosphere.get(room_a)
        atm_b = _atmosphere.get(room_b)
        if atm_a is None or atm_b is None:
            continue
        rate = VENT_EXCHANGE_RATE * dt
        # Exchange each atmospheric property toward equalisation
        for attr in ("oxygen_percent", "pressure_kpa", "temperature_c",
                     "smoke", "coolant", "radiation", "chemical"):
            val_a = getattr(atm_a, attr)
            val_b = getattr(atm_b, attr)
            diff = val_b - val_a
            transfer = diff * rate
            setattr(atm_a, attr, val_a + transfer)
            setattr(atm_b, attr, val_b - transfer)


def _tick_filtered_scrub(dt: float) -> None:
    """Filtered vents scrub contaminants from connected rooms."""
    for (room_a, room_b), state in _vent_states.items():
        if state != "filtered":
            continue
        for rid in (room_a, room_b):
            atm = _atmosphere.get(rid)
            if atm is None:
                continue
            scrub = FILTERED_SCRUB_RATE * dt
            atm.smoke = max(0.0, atm.smoke - scrub)
            atm.coolant = max(0.0, atm.coolant - scrub)
            atm.radiation = max(0.0, atm.radiation - scrub)
            atm.chemical = max(0.0, atm.chemical - scrub)


def _tick_life_support(dt: float, ls_eff: float) -> None:
    """Life support restores O2, pressure, and temperature toward normal."""
    for rid, atm in _atmosphere.items():
        # Skip rooms being vented to space or at vacuum with active breach
        if rid in _space_vent_rooms:
            continue
        breach = _breaches.get(rid)
        if breach and not breach.force_field_active and not breach.bulkhead_sealed:
            continue  # Can't restore while actively breached
        # Restore O2
        if atm.oxygen_percent < NORMAL_O2:
            atm.oxygen_percent = min(NORMAL_O2, atm.oxygen_percent + LS_O2_RATE * ls_eff * dt)
        # Restore pressure
        if atm.pressure_kpa < NORMAL_PRESSURE:
            atm.pressure_kpa = min(NORMAL_PRESSURE, atm.pressure_kpa + LS_PRESSURE_RATE * ls_eff * dt)
        # Restore temperature toward normal
        if atm.temperature_c != NORMAL_TEMP:
            diff = NORMAL_TEMP - atm.temperature_c
            step = LS_TEMP_RATE * ls_eff * dt
            if abs(diff) <= step:
                atm.temperature_c = NORMAL_TEMP
            elif diff > 0:
                atm.temperature_c += step
            else:
                atm.temperature_c -= step


def _tick_breach_timers(dt: float, events: list[dict]) -> None:
    """Update force field, bulkhead, and evacuation timers."""
    for rid, breach in _breaches.items():
        # Force field countdown
        if breach.force_field_active:
            breach.force_field_timer -= dt
            if breach.force_field_timer <= 0:
                breach.force_field_active = False
                breach.force_field_timer = 0.0
                events.append({"type": "force_field_expired", "room_id": rid})
                logger.info("Force field expired in room %s", rid)
        # Bulkhead seal countdown
        if breach.bulkhead_timer > 0 and not breach.bulkhead_sealed:
            breach.bulkhead_timer -= dt
            if breach.bulkhead_timer <= 0:
                breach.bulkhead_sealed = True
                breach.bulkhead_timer = 0.0
                # Bulkhead seal is permanent — also deactivate force field
                breach.force_field_active = False
                breach.force_field_timer = 0.0
                events.append({"type": "bulkhead_sealed", "room_id": rid})
                logger.info("Bulkhead sealed in room %s", rid)
        # Evacuation countdown
        if breach.evacuating and breach.evacuation_timer > 0:
            breach.evacuation_timer -= dt
            if breach.evacuation_timer <= 0:
                breach.evacuating = False
                breach.evacuation_timer = 0.0
                events.append({"type": "evacuation_complete", "room_id": rid})
                logger.info("Evacuation complete in room %s", rid)


def _tick_vacuum_damage(interior: ShipInterior, dt: float, events: list[dict]) -> None:
    """Emit vacuum damage events for rooms at 0 kPa."""
    for rid, atm in _atmosphere.items():
        if atm.pressure_kpa > 0.0:
            continue
        room = interior.rooms.get(rid)
        if room is None:
            continue
        events.append({"type": "vacuum_damage", "room_id": rid, "dt": dt})


def _tick_space_vent() -> None:
    """Rooms being vented to space stay at vacuum."""
    for rid in _space_vent_rooms:
        atm = _atmosphere.get(rid)
        if atm is None:
            continue
        atm.pressure_kpa = 0.0
        atm.oxygen_percent = 0.0
        atm.temperature_c = -270.0


def _tick_fire_starvation(fires: dict, events: list[dict]) -> None:
    """Extinguish fires in rooms where O2 < 5%."""
    for rid in list(fires.keys()):
        atm = _atmosphere.get(rid)
        if atm is None:
            continue
        if atm.oxygen_percent < FIRE_O2_STARVATION:
            fire = fires[rid]
            if hasattr(fire, "intensity"):
                fire.intensity = 0
            events.append({"type": "fire_starved", "room_id": rid})
            logger.info("Fire starved of oxygen in room %s", rid)


# ---------------------------------------------------------------------------
# Tick helpers — Radiation (B.4)
# ---------------------------------------------------------------------------

def _tick_radiation_sources(interior: ShipInterior, dt: float, ship) -> None:
    """Generate radiation from reactor damage and weak shields."""
    if ship is None:
        return

    # Reactor leak
    systems = getattr(ship, "systems", None)
    if systems:
        # Use power grid reactor_health if available
        pg = None
        try:
            import server.game_loop_engineering as _gle
            pg = _gle.get_power_grid()
        except Exception:
            pass
        reactor_health = pg.reactor_health if pg else 100.0
        if reactor_health < REACTOR_LEAK_THRESHOLD:
            _apply_reactor_leak(interior, reactor_health, dt)

        # Shield system leak
        shield_sys = systems.get("shields")
        if shield_sys is not None and shield_sys.health < SHIELD_LEAK_THRESHOLD:
            _apply_shield_leak(interior, shield_sys.health, dt)


def _apply_reactor_leak(interior: ShipInterior, reactor_health: float, dt: float) -> None:
    """Apply reactor radiation leak to engineering rooms (+ adjacent if serious)."""
    serious = reactor_health < REACTOR_SERIOUS_THRESHOLD
    rate = REACTOR_SERIOUS_LEAK_RATE if serious else REACTOR_LEAK_RATE
    eng_deck_number: int | None = None

    for room_id, room in interior.rooms.items():
        if room.deck == "engineering":
            if eng_deck_number is None:
                eng_deck_number = room.deck_number
            atm = _atmosphere.get(room_id)
            if atm is not None:
                atm.radiation = min(100.0, atm.radiation + rate * dt)

    # Serious leak: also affect adjacent deck rooms
    if serious and eng_deck_number is not None:
        for room_id, room in interior.rooms.items():
            if room.deck != "engineering" and abs(room.deck_number - eng_deck_number) == 1:
                atm = _atmosphere.get(room_id)
                if atm is not None:
                    atm.radiation = min(100.0, atm.radiation + rate * dt)


def _apply_shield_leak(interior: ShipInterior, shield_health: float, dt: float) -> None:
    """Apply shield radiation leak to outer deck rooms (weapons/shields deck)."""
    for room_id, room in interior.rooms.items():
        if room.deck in ("weapons", "shields"):
            atm = _atmosphere.get(room_id)
            if atm is not None:
                atm.radiation = min(100.0, atm.radiation + SHIELD_LEAK_RATE * dt)


def _tick_decon_teams(dt: float, events: list[dict]) -> None:
    """Decontamination teams: reduce radiation by DECON_REDUCTION every DECON_INTERVAL."""
    completed: list[str] = []
    for room_id in list(_decon_teams):
        atm = _atmosphere.get(room_id)
        if atm is None or atm.radiation <= 0.0:
            completed.append(room_id)
            continue

        _decon_teams[room_id] += dt
        prev_intervals = int((_decon_teams[room_id] - dt) / DECON_INTERVAL)
        cur_intervals = int(_decon_teams[room_id] / DECON_INTERVAL)

        if cur_intervals > prev_intervals:
            atm.radiation = max(0.0, atm.radiation - DECON_REDUCTION)
            events.append({"type": "decon_progress", "room_id": room_id,
                           "radiation": round(atm.radiation, 1)})
            if atm.radiation <= 0.0:
                completed.append(room_id)

    for room_id in completed:
        _decon_teams.pop(room_id, None)


def _tick_radiation_exposure(interior: ShipInterior, dt: float, events: list[dict]) -> None:
    """Track cumulative radiation exposure per deck and emit sickness events."""
    # Aggregate max radiation per deck
    deck_max_rad: dict[str, float] = {}
    for room_id, atm in _atmosphere.items():
        room = interior.rooms.get(room_id)
        if room is None:
            continue
        deck_max_rad[room.deck] = max(deck_max_rad.get(room.deck, 0.0), atm.radiation)

    for deck_name, max_rad in deck_max_rad.items():
        if max_rad < RAD_AMBER_THRESHOLD:
            # Reset exposure when below threshold
            _radiation_exposure.pop(deck_name, None)
            continue

        prev_exposure = _radiation_exposure.get(deck_name, 0.0)
        new_exposure = prev_exposure + dt
        _radiation_exposure[deck_name] = new_exposure

        # Determine sickness threshold for current tier
        if max_rad >= RAD_RED_THRESHOLD:
            threshold = 0.0  # immediate
        elif max_rad >= RAD_ORANGE_THRESHOLD:
            threshold = RAD_ORANGE_SICKNESS_TIME
        else:
            threshold = RAD_AMBER_SICKNESS_TIME

        # Emit sickness event at threshold crossing
        if prev_exposure < threshold <= new_exposure or (threshold == 0.0 and prev_exposure == 0.0):
            events.append({
                "type": "radiation_sickness",
                "deck": deck_name,
                "severity": "red" if max_rad >= RAD_RED_THRESHOLD
                           else "orange" if max_rad >= RAD_ORANGE_THRESHOLD
                           else "amber",
            })


def _clamp_all() -> None:
    """Clamp all atmospheric values to valid ranges."""
    for atm in _atmosphere.values():
        atm.oxygen_percent = max(0.0, min(100.0, atm.oxygen_percent))
        atm.pressure_kpa = max(0.0, min(NORMAL_PRESSURE, atm.pressure_kpa))
        atm.smoke = max(0.0, min(100.0, atm.smoke))
        atm.coolant = max(0.0, min(100.0, atm.coolant))
        atm.radiation = max(0.0, min(100.0, atm.radiation))
        atm.chemical = max(0.0, min(100.0, atm.chemical))
        # Temperature: no upper clamp (fires can raise arbitrarily), floor at -270
        atm.temperature_c = max(-270.0, atm.temperature_c)
