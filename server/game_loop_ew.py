"""
Electronic Warfare — Game Loop Integration.

Handles:
  - Sensor jamming: enemy.jam_factor buildup/decay based on ECM suite power
  - Countermeasure charge management (toggle/auto-off when charges exhaust)
  - System intrusion state tracking (puzzle creation handled by game_loop.py)
  - EW state payload construction for the electronic_warfare station

ECM suite power (Engineering allocation) scales jamming effectiveness and
range. At full power (efficiency=1.0) and full health: base values apply.
Overclocking to 150% gives efficiency=1.5 → extended range and faster buildup.

Constants are tuned for a 10 Hz game loop (TICK_DT = 0.1 s).
"""
from __future__ import annotations

import random as _rng

from server.models.ship import Ship
from server.models.world import World
from server.utils.math_helpers import distance

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: jam_factor increase per second when an enemy is within range and targeted.
JAM_BUILDUP_RATE: float = 0.25
#: jam_factor decrease per second when an enemy is NOT the active target.
JAM_DECAY_RATE: float = 0.15
#: Maximum achievable jam_factor (80% damage reduction at full ECM efficiency).
JAM_MAX_FACTOR: float = 0.80
#: Base jamming range in world units; scales with ECM efficiency.
JAM_BASE_RANGE: float = 15_000.0

#: Default countermeasure charges on game start.
COUNTERMEASURE_DEFAULT_CHARGES: int = 10

#: How long a successful network intrusion stuns enemy beam fire (ticks at 10 Hz).
INTRUSION_STUN_DURATION: int = 30  # 3 seconds

# --- Silent Running (v0.07 §2.1 — Scout only) ---
#: Seconds to fully engage stealth after toggle.
STEALTH_ACTIVATION_TIME: float = 5.0
#: Seconds to fully disengage stealth.
STEALTH_DEACTIVATION_TIME: float = 3.0
#: Enemy detection range multiplier when stealth is fully active.
STEALTH_DETECT_RANGE_MULT: float = 0.30
#: Maximum throttle (%) before stealth auto-breaks.
STEALTH_ENGINE_LIMIT: float = 50.0

# --- Corvette Advanced ECM (v0.07 §2.2) ---
#: Maximum simultaneous ghost contacts.
GHOST_MAX_COUNT: int = 3
#: Seconds before a ghost contact auto-expires.
GHOST_LIFETIME: float = 120.0
#: Seconds between passive comm intercept attempts.
INTERCEPT_SCAN_INTERVAL: float = 15.0
#: Probability per enemy per attempt of intercepting a signal.
INTERCEPT_CHANCE: float = 0.40
#: Valid ship classes for ghost mimic / sensor ghosting.
GHOST_CLASS_OPTIONS: list[str] = [
    "fighter", "scout", "cruiser", "destroyer", "freighter", "transport", "battleship",
]
#: Seconds to fully establish a frequency lock.
FREQ_LOCK_ENGAGE_TIME: float = 5.0
#: Base range for frequency lock (scales with ECM efficiency).
FREQ_LOCK_RANGE: float = 20_000.0


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_jam_target_id: str | None = None
_intrusion_target_id: str | None = None
_intrusion_target_system: str | None = None

# --- Silent Running state ---
_stealth_state: str = "inactive"      # inactive | activating | active | deactivating
_stealth_timer: float = 0.0           # seconds elapsed in current transition
_stealth_capable: bool = False         # True only for scout class
_stealth_break_reason: str | None = None  # set when stealth is force-broken

# --- Corvette Advanced ECM state ---
_corvette_ecm: bool = False
_ghosts: list[dict] = []               # [{id, x, y, mimic_class, lifetime_remaining}]
_ghost_counter: int = 0
_intercept_timer: float = 0.0
_intercepted_signals: list[dict] = []
_ghost_class: str | None = None
_freq_lock_target_id: str | None = None
_freq_lock_progress: float = 0.0
_freq_lock_active: bool = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset(ship_class: str = "") -> None:
    """Reset EW state to defaults. Called at game start."""
    global _jam_target_id, _intrusion_target_id, _intrusion_target_system
    global _stealth_state, _stealth_timer, _stealth_capable, _stealth_break_reason
    global _corvette_ecm, _ghosts, _ghost_counter, _intercept_timer
    global _intercepted_signals, _ghost_class
    global _freq_lock_target_id, _freq_lock_progress, _freq_lock_active
    _jam_target_id = None
    _intrusion_target_id = None
    _intrusion_target_system = None
    _stealth_state = "inactive"
    _stealth_timer = 0.0
    _stealth_capable = (ship_class == "scout")
    _stealth_break_reason = None
    # Corvette ECM
    _corvette_ecm = (ship_class == "corvette")
    _ghosts = []
    _ghost_counter = 0
    _intercept_timer = INTERCEPT_SCAN_INTERVAL
    _intercepted_signals = []
    _ghost_class = None
    _freq_lock_target_id = None
    _freq_lock_progress = 0.0
    _freq_lock_active = False


def set_jam_target(entity_id: str | None) -> None:
    """Set the enemy to jam. Pass None to stop active jamming."""
    global _jam_target_id
    _jam_target_id = entity_id


def toggle_countermeasures(active: bool, ship: Ship) -> None:
    """Enable or disable countermeasures.

    Enabling is silently ignored if countermeasure_charges are exhausted.
    """
    if active and ship.countermeasure_charges <= 0:
        return
    ship.ew_countermeasure_active = active


def set_intrusion_target(entity_id: str, target_system: str) -> None:
    """Record intrusion target. Called before the network_intrusion puzzle is created."""
    global _intrusion_target_id, _intrusion_target_system
    _intrusion_target_id = entity_id
    _intrusion_target_system = target_system


def get_intrusion_target() -> tuple[str | None, str | None]:
    """Return (entity_id, target_system) of the current intrusion target."""
    return _intrusion_target_id, _intrusion_target_system


def apply_intrusion_success(entity_id: str, world: World) -> None:
    """On intrusion puzzle success: stun enemy beam fire for INTRUSION_STUN_DURATION ticks."""
    for enemy in world.enemies:
        if enemy.id == entity_id:
            enemy.intrusion_stun_ticks = max(enemy.intrusion_stun_ticks, INTRUSION_STUN_DURATION)
            break


# ---------------------------------------------------------------------------
# Silent Running (v0.07 §2.1)
# ---------------------------------------------------------------------------


def toggle_stealth(active: bool) -> dict:
    """Start or stop silent running. Returns status dict."""
    global _stealth_state, _stealth_timer
    if not _stealth_capable:
        return {"ok": False, "reason": "not_capable"}
    if active:
        if _stealth_state in ("activating", "active"):
            return {"ok": False, "reason": "already_engaged"}
        _stealth_state = "activating"
        _stealth_timer = 0.0
        return {"ok": True, "state": "activating"}
    else:
        if _stealth_state == "inactive":
            return {"ok": False, "reason": "not_engaged"}
        if _stealth_state == "deactivating":
            return {"ok": False, "reason": "already_deactivating"}
        _stealth_state = "deactivating"
        _stealth_timer = 0.0
        return {"ok": True, "state": "deactivating"}


def break_stealth(reason: str) -> None:
    """Force-break stealth from activating/active to deactivating."""
    global _stealth_state, _stealth_timer, _stealth_break_reason
    if _stealth_state in ("activating", "active"):
        _stealth_state = "deactivating"
        _stealth_timer = 0.0
        _stealth_break_reason = reason


def is_stealth_active() -> bool:
    """True when stealth is fully active (invisible to passive sensors)."""
    return _stealth_state == "active"


def is_stealth_engaged() -> bool:
    """True when any stealth state is non-inactive (activating/active/deactivating)."""
    return _stealth_state != "inactive"


def is_stealth_capable() -> bool:
    """True when the current ship class supports silent running (scout only)."""
    return _stealth_capable


def get_stealth_state() -> str:
    """Return current stealth state string."""
    return _stealth_state


def get_stealth_sensor_modifier() -> float:
    """Return the enemy detection range multiplier due to stealth.

    1.0 when inactive, interpolates toward STEALTH_DETECT_RANGE_MULT during
    activation, STEALTH_DETECT_RANGE_MULT when fully active, interpolates back
    during deactivation.
    """
    if _stealth_state == "inactive":
        return 1.0
    if _stealth_state == "active":
        return STEALTH_DETECT_RANGE_MULT
    if _stealth_state == "activating":
        progress = min(_stealth_timer / STEALTH_ACTIVATION_TIME, 1.0)
        return 1.0 - progress * (1.0 - STEALTH_DETECT_RANGE_MULT)
    # deactivating — interpolate back toward 1.0
    progress = min(_stealth_timer / STEALTH_DEACTIVATION_TIME, 1.0)
    return STEALTH_DETECT_RANGE_MULT + progress * (1.0 - STEALTH_DETECT_RANGE_MULT)


def pop_stealth_break_reason() -> str | None:
    """Return and clear the stealth break reason, if any."""
    global _stealth_break_reason
    reason = _stealth_break_reason
    _stealth_break_reason = None
    return reason


# ---------------------------------------------------------------------------
# Corvette Advanced ECM (v0.07 §2.2)
# ---------------------------------------------------------------------------


def is_corvette_ecm() -> bool:
    """True when the current ship class has advanced ECM (corvette only)."""
    return _corvette_ecm


# --- Signal Spoofing (§2.2.2) ---

def deploy_ghost(x: float, y: float, mimic_class: str) -> dict:
    """Deploy a ghost contact at (x, y) mimicking the given class."""
    global _ghost_counter
    if not _corvette_ecm:
        return {"ok": False, "reason": "not_capable"}
    if len(_ghosts) >= GHOST_MAX_COUNT:
        return {"ok": False, "reason": "max_ghosts"}
    if mimic_class not in GHOST_CLASS_OPTIONS:
        return {"ok": False, "reason": "invalid_class"}
    _ghost_counter += 1
    ghost_id = f"ghost_{_ghost_counter}"
    _ghosts.append({
        "id": ghost_id,
        "x": x,
        "y": y,
        "mimic_class": mimic_class,
        "lifetime_remaining": GHOST_LIFETIME,
    })
    return {"ok": True, "id": ghost_id}


def recall_ghost(ghost_id: str) -> dict:
    """Remove a specific ghost by ID."""
    for i, g in enumerate(_ghosts):
        if g["id"] == ghost_id:
            _ghosts.pop(i)
            return {"ok": True}
    return {"ok": False, "reason": "not_found"}


def recall_all_ghosts() -> None:
    """Remove all active ghosts."""
    _ghosts.clear()


def get_ghosts() -> list[dict]:
    """Return the current ghost list."""
    return list(_ghosts)


def get_ghost_contacts() -> list[dict]:
    """Return ghost contacts formatted for sensor contact injection."""
    return [
        {
            "id": g["id"],
            "x": g["x"],
            "y": g["y"],
            "heading": 0.0,
            "kind": "enemy",
            "classification": "unknown",
            "scan_state": "unknown",
            "type": g["mimic_class"],
        }
        for g in _ghosts
    ]


# --- Comm Interception (§2.2.3) ---

def pop_intercepted_signals() -> list[dict]:
    """Drain and return intercepted signal parameter dicts."""
    global _intercepted_signals
    signals = _intercepted_signals
    _intercepted_signals = []
    return signals


# --- Sensor Ghosting (§2.2.4) ---

def set_ghost_class(class_name: str | None) -> dict:
    """Set what the corvette appears as on enemy sensors. None = true identity."""
    global _ghost_class
    if not _corvette_ecm:
        return {"ok": False, "reason": "not_capable"}
    if class_name is not None and class_name not in GHOST_CLASS_OPTIONS:
        return {"ok": False, "reason": "invalid_class"}
    _ghost_class = class_name
    return {"ok": True, "ghost_class": _ghost_class}


def get_ghost_class() -> str | None:
    """Return the current sensor disguise class, or None."""
    return _ghost_class


# --- Frequency Lock (§2.2.5) ---

def set_freq_lock_target(entity_id: str | None, frequency: str | None = None) -> dict:
    """Begin or cancel a frequency lock."""
    global _freq_lock_target_id, _freq_lock_progress, _freq_lock_active
    if not _corvette_ecm:
        return {"ok": False, "reason": "not_capable"}
    if entity_id is None:
        _freq_lock_target_id = None
        _freq_lock_progress = 0.0
        _freq_lock_active = False
        return {"ok": True, "state": "cancelled"}
    _freq_lock_target_id = entity_id
    _freq_lock_progress = 0.0
    _freq_lock_active = False
    return {"ok": True, "state": "engaging", "target": entity_id}


def is_freq_locked(entity_id: str) -> bool:
    """Return True if the given entity is under a full frequency lock."""
    return _freq_lock_active and _freq_lock_target_id == entity_id


def is_freq_lock_active() -> bool:
    """Return True if a frequency lock is fully established."""
    return _freq_lock_active


def get_freq_locked_ids() -> set[str]:
    """Return set of entity IDs under frequency lock (for station_ai)."""
    if _freq_lock_active and _freq_lock_target_id is not None:
        return {_freq_lock_target_id}
    return set()


# --- Corvette ECM tick helpers ---

def _tick_ghosts(dt: float) -> None:
    """Decay ghost lifetimes, remove expired ghosts."""
    for g in _ghosts:
        g["lifetime_remaining"] -= dt
    _ghosts[:] = [g for g in _ghosts if g["lifetime_remaining"] > 0]


def _tick_interception(world: World, ship: Ship, dt: float) -> None:
    """Periodically scan enemies in sensor range and generate intercept signals."""
    global _intercept_timer
    ecm_eff = ship.systems["ecm_suite"].efficiency
    if ecm_eff <= 0.0:
        return
    _intercept_timer -= dt
    if _intercept_timer > 0.0:
        return
    _intercept_timer = INTERCEPT_SCAN_INTERVAL
    # Check each enemy within sensor range
    from server.systems.sensors import sensor_range
    sr = sensor_range(ship)
    for enemy in world.enemies:
        dist = distance(ship.x, ship.y, enemy.x, enemy.y)
        if dist <= sr and _rng.random() < INTERCEPT_CHANCE:
            freq_hint = ""
            if enemy.scan_state == "scanned":
                freq_hint = f" [FREQ: {enemy.shield_frequency.upper()}]"
            _intercepted_signals.append({
                "source": f"intercept_{enemy.id}",
                "source_name": f"Intercepted {enemy.type.title()} Comms",
                "frequency": 0.5,
                "signal_type": "encrypted",
                "priority": "medium",
                "raw_content": f"[ENCRYPTED TACTICAL DATA]{freq_hint}",
                "decoded_content": f"Enemy {enemy.type} tactical transmission.{freq_hint} Position: ({int(enemy.x)}, {int(enemy.y)}).",
                "requires_decode": True,
                "faction": "hostile",
                "threat_level": "medium",
                "intel_value": f"enemy_{enemy.type}_position",
                "intel_category": "tactical",
            })


def _tick_freq_lock(world: World, ship: Ship, dt: float) -> None:
    """Advance frequency lock engagement progress."""
    global _freq_lock_progress, _freq_lock_active, _freq_lock_target_id
    if _freq_lock_target_id is None:
        return
    ecm_eff = ship.systems["ecm_suite"].efficiency
    effective_lock_range = FREQ_LOCK_RANGE * ecm_eff
    # Find target (enemy or station)
    target_pos = None
    for enemy in world.enemies:
        if enemy.id == _freq_lock_target_id:
            target_pos = (enemy.x, enemy.y)
            break
    if target_pos is None:
        for station in world.stations:
            if station.id == _freq_lock_target_id:
                target_pos = (station.x, station.y)
                break
    if target_pos is None:
        # Target gone — cancel lock
        _freq_lock_target_id = None
        _freq_lock_progress = 0.0
        _freq_lock_active = False
        return
    dist = distance(ship.x, ship.y, target_pos[0], target_pos[1])
    if dist > effective_lock_range:
        # Out of range — decay progress
        _freq_lock_progress = max(0.0, _freq_lock_progress - dt / FREQ_LOCK_ENGAGE_TIME)
        if _freq_lock_active:
            _freq_lock_active = False
        return
    if not _freq_lock_active:
        _freq_lock_progress = min(1.0, _freq_lock_progress + dt / FREQ_LOCK_ENGAGE_TIME)
        if _freq_lock_progress >= 1.0:
            _freq_lock_active = True


def tick(world: World, ship: Ship, dt: float) -> None:
    """Update jam_factor on all enemies each tick.

    The active jam target builds up toward JAM_MAX_FACTOR; all other enemies
    decay toward 0. Both the buildup rate and effective range scale with the
    ECM suite's efficiency (power × health).

    Also advances the stealth state machine timer and enforces stealth constraints.
    """
    global _stealth_state, _stealth_timer
    # --- Silent Running timer ---
    if _stealth_state == "activating":
        _stealth_timer += dt
        if _stealth_timer >= STEALTH_ACTIVATION_TIME:
            _stealth_state = "active"
            _stealth_timer = 0.0
        # Enforce: shields forced to 0 during activation
        for facing in ("fore", "aft", "port", "starboard"):
            setattr(ship.shields, facing, 0.0)
    elif _stealth_state == "active":
        # Enforce: shields forced to 0 while stealthed
        for facing in ("fore", "aft", "port", "starboard"):
            setattr(ship.shields, facing, 0.0)
        # Break stealth if throttle exceeds engine limit
        if ship.throttle > STEALTH_ENGINE_LIMIT:
            break_stealth("engine_power")
    elif _stealth_state == "deactivating":
        _stealth_timer += dt
        if _stealth_timer >= STEALTH_DEACTIVATION_TIME:
            _stealth_state = "inactive"
            _stealth_timer = 0.0

    ecm_eff = ship.systems["ecm_suite"].efficiency  # 0.0–1.5
    # Effective range and buildup both scale with ECM efficiency.
    # Use at least 0.01 guard so ecm_eff=0 gives zero effective range.
    effective_range = JAM_BASE_RANGE * ecm_eff
    buildup_rate = JAM_BUILDUP_RATE * ecm_eff

    for enemy in world.enemies:
        if enemy.id == _jam_target_id and effective_range > 0.0:
            dist = distance(ship.x, ship.y, enemy.x, enemy.y)
            if dist <= effective_range:
                enemy.jam_factor = min(JAM_MAX_FACTOR, enemy.jam_factor + buildup_rate * dt)
            else:
                # Out of jam range — decay even while targeted.
                enemy.jam_factor = max(0.0, enemy.jam_factor - JAM_DECAY_RATE * dt)
        else:
            # Not targeted (or ECM offline) — decay toward 0.
            enemy.jam_factor = max(0.0, enemy.jam_factor - JAM_DECAY_RATE * dt)

    # v0.05i — station sensor array jamming.
    # If the jam target is a station sensor component ("*_sensor"), mark it jammed.
    if _jam_target_id and _jam_target_id.endswith("_sensor") and effective_range > 0.0:
        for station in world.stations:
            if station.defenses is None:
                continue
            sa = station.defenses.sensor_array
            if sa.id == _jam_target_id:
                dist = distance(ship.x, ship.y, station.x, station.y)
                sa.jammed = dist <= effective_range
                break
    else:
        # Clear jammed flag when the sensor is no longer actively targeted.
        for station in world.stations:
            if station.defenses is not None:
                sa = station.defenses.sensor_array
                if sa.jammed and (_jam_target_id is None or sa.id != _jam_target_id):
                    sa.jammed = False

    # --- Corvette ECM tick ---
    if _corvette_ecm:
        _tick_ghosts(dt)
        _tick_interception(world, ship, dt)
        _tick_freq_lock(world, ship, dt)


def build_state(world: World, ship: Ship) -> dict:
    """Serialise EW state for broadcast to the electronic_warfare role."""
    ecm_eff = ship.systems["ecm_suite"].efficiency
    enemies_data = []
    for enemy in world.enemies:
        dist = distance(ship.x, ship.y, enemy.x, enemy.y)
        enemies_data.append({
            "id": enemy.id,
            "type": enemy.type,
            "x": round(enemy.x, 1),
            "y": round(enemy.y, 1),
            "jam_factor": round(enemy.jam_factor, 3),
            "intrusion_stun_ticks": enemy.intrusion_stun_ticks,
            "distance": round(dist, 1),
        })
    # Include detected creatures for EW interaction (sedate / disrupt).
    creatures_data = []
    for creature in world.creatures:
        if not creature.detected or creature.hull <= 0:
            continue
        dist = distance(ship.x, ship.y, creature.x, creature.y)
        creatures_data.append({
            "id": creature.id,
            "creature_type": creature.creature_type,
            "x": round(creature.x, 1),
            "y": round(creature.y, 1),
            "behaviour_state": creature.behaviour_state,
            "hull": round(creature.hull, 1),
            "hull_max": round(creature.hull_max, 1),
            "distance": round(dist, 1),
            "attached": creature.attached,
        })
    return {
        "jam_target_id": _jam_target_id,
        "countermeasures_active": ship.ew_countermeasure_active,
        "countermeasure_charges": ship.countermeasure_charges,
        "ecm_efficiency": round(ecm_eff, 3),
        "jam_base_range": JAM_BASE_RANGE,
        "effective_jam_range": round(JAM_BASE_RANGE * ecm_eff, 1),
        "enemies": enemies_data,
        "creatures": creatures_data,
        "intrusion_target_id": _intrusion_target_id,
        "intrusion_target_system": _intrusion_target_system,
        "stealth_state": _stealth_state,
        "stealth_timer": round(_stealth_timer, 2),
        "stealth_capable": _stealth_capable,
        # Corvette ECM (v0.07 §2.2)
        "corvette_ecm": _corvette_ecm,
        "ghosts": [
            {"id": g["id"], "x": g["x"], "y": g["y"],
             "mimic_class": g["mimic_class"],
             "lifetime": round(g["lifetime_remaining"], 1)}
            for g in _ghosts
        ],
        "ghost_class": _ghost_class,
        "freq_lock_target_id": _freq_lock_target_id,
        "freq_lock_progress": round(_freq_lock_progress, 3),
        "freq_lock_active": _freq_lock_active,
        "intercept_timer": round(_intercept_timer, 1),
    }


def serialise() -> dict:
    return {
        "jam_target_id": _jam_target_id,
        "intrusion_target_id": _intrusion_target_id,
        "intrusion_target_system": _intrusion_target_system,
        "stealth_state": _stealth_state,
        "stealth_timer": _stealth_timer,
        "stealth_capable": _stealth_capable,
        # Corvette ECM
        "corvette_ecm": _corvette_ecm,
        "ghosts": list(_ghosts),
        "ghost_counter": _ghost_counter,
        "intercept_timer": _intercept_timer,
        "ghost_class": _ghost_class,
        "freq_lock_target_id": _freq_lock_target_id,
        "freq_lock_progress": _freq_lock_progress,
        "freq_lock_active": _freq_lock_active,
    }


def deserialise(data: dict) -> None:
    global _jam_target_id, _intrusion_target_id, _intrusion_target_system
    global _stealth_state, _stealth_timer, _stealth_capable, _stealth_break_reason
    global _corvette_ecm, _ghosts, _ghost_counter, _intercept_timer
    global _intercepted_signals, _ghost_class
    global _freq_lock_target_id, _freq_lock_progress, _freq_lock_active
    _jam_target_id           = data.get("jam_target_id")
    _intrusion_target_id     = data.get("intrusion_target_id")
    _intrusion_target_system = data.get("intrusion_target_system")
    _stealth_state           = data.get("stealth_state", "inactive")
    _stealth_timer           = data.get("stealth_timer", 0.0)
    _stealth_capable         = data.get("stealth_capable", False)
    _stealth_break_reason    = None
    # Corvette ECM
    _corvette_ecm            = data.get("corvette_ecm", False)
    _ghosts                  = list(data.get("ghosts", []))
    _ghost_counter           = data.get("ghost_counter", 0)
    _intercept_timer         = data.get("intercept_timer", INTERCEPT_SCAN_INTERVAL)
    _intercepted_signals     = []
    _ghost_class             = data.get("ghost_class")
    _freq_lock_target_id     = data.get("freq_lock_target_id")
    _freq_lock_progress      = data.get("freq_lock_progress", 0.0)
    _freq_lock_active        = data.get("freq_lock_active", False)
