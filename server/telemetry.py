"""Enhanced Telemetry — player engagement, coordination, combat, resources, environment, phases.

Fire-and-forget module that emits detailed telemetry events to the game log
for post-game analysis.  All methods are safe to call even when logging is
disabled — the underlying game_logger silently discards events.

Section 1.1: Player engagement metrics (30 s summaries, idle detection).
Section 1.2: Cross-station coordination tracking (10 chains with timeouts).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from server.game_logger import log_event as _log

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENGAGEMENT_INTERVAL_TICKS: int = 300   # 30 s at 10 Hz
IDLE_THRESHOLD_S: float = 30.0         # seconds of no input before idle event

# Map message-type prefix → canonical station name.
_PREFIX_TO_STATION: dict[str, str] = {
    "helm": "helm",
    "engineering": "engineering",
    "weapons": "weapons",
    "science": "science",
    "captain": "captain",
    "medical": "medical",
    "security": "security",
    "comms": "comms",
    "flight_ops": "flight_ops",
    "ew": "ew",
    "operations": "operations",
    "hazard_control": "hazard_control",
    "quartermaster": "quartermaster",
    "janitor": "janitor",
    "negotiation": "quartermaster",
    "salvage": "quartermaster",
    "rationing": "quartermaster",
    "carrier": "flight_ops",
    "map": "helm",
    "docking": "helm",
    "creature": "science",
}

# Message types that are NOT player actions (system/lifecycle).
_IGNORED_TYPES: set[str] = {
    "game.briefing_launch",
    "game.briefing_ready",
    "crew.notify",
    "puzzle.submit",
    "puzzle.request_assist",
    "puzzle.cancel",
}


# ---------------------------------------------------------------------------
# Per-player engagement state
# ---------------------------------------------------------------------------


@dataclass
class _PlayerState:
    """Mutable per-player engagement tracking."""

    station: str = ""
    actions_window: int = 0        # actions in current 30 s window
    total_actions: int = 0
    stations_visited: list[str] = field(default_factory=list)
    station_visit_count: int = 0
    last_action_ts: float = -1.0   # game-time (seconds since start), -1 = never
    station_start_ts: float = 0.0  # when they started on current station
    is_idle: bool = False
    idle_start_ts: float = 0.0


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_players: dict[str, _PlayerState] = {}  # player_name → state
_role_to_player: dict[str, str] = {}    # role → player_name
_game_time: float = 0.0                 # seconds since game start
_last_engagement_tick: int = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init(players: dict[str, str]) -> None:
    """Initialise telemetry for a new game session.

    *players* maps role → player_name (same dict passed to game_logger.start).
    """
    global _game_time, _last_engagement_tick
    _players.clear()
    _role_to_player.clear()
    _game_time = 0.0
    _last_engagement_tick = 0

    for role, name in players.items():
        _role_to_player[role] = name
        if name not in _players:
            _players[name] = _PlayerState(
                station=role,
                stations_visited=[role],
                station_visit_count=1,
                station_start_ts=0.0,
            )


def reset() -> None:
    """Clear all telemetry state (for tests)."""
    global _game_time, _last_engagement_tick, _last_combat_tick, _in_combat
    global _last_resource_tick, _last_env_tick, _current_phase
    global _combat_start_tick, _no_enemies_since_tick
    _players.clear()
    _role_to_player.clear()
    _pending_coordinations.clear()
    _game_time = 0.0
    _last_engagement_tick = 0
    _last_combat_tick = 0
    _in_combat = False
    _combat.__init__()  # type: ignore[misc]
    _prev_ammo.clear()
    _last_resource_tick = 0
    _last_env_tick = 0
    _current_phase = "all_clear"
    _combat_start_tick = 0
    _no_enemies_since_tick = 0


def record_action(msg_type: str) -> None:
    """Record a player action from _drain_queue.

    Called once per message processed.  Derives the station from the message
    type prefix and credits the player currently assigned to that role.
    """
    if msg_type in _IGNORED_TYPES:
        return

    station = _station_from_type(msg_type)
    if station is None:
        return

    player_name = _role_to_player.get(station)
    if player_name is None:
        return

    ps = _players.get(player_name)
    if ps is None:
        return

    ps.actions_window += 1
    ps.total_actions += 1
    ps.last_action_ts = _game_time

    # Station change detection.
    if station != ps.station:
        ps.station = station
        if station not in ps.stations_visited:
            ps.stations_visited.append(station)
        ps.station_visit_count += 1
        ps.station_start_ts = _game_time

    # Resume from idle.
    if ps.is_idle:
        idle_duration = _game_time - ps.idle_start_ts
        _log("telemetry", "player_active", {
            "player": player_name,
            "station": station,
            "was_idle_seconds": round(idle_duration, 1),
        })
        ps.is_idle = False


def tick(tick_num: int, dt: float, *,
         enemy_count: int = 0, ship=None,
         hull_pct: float = 100.0, mission_active: bool = False) -> None:
    """Called every game tick.  Emits periodic engagement/combat/resource/env/phase events."""
    global _game_time, _last_engagement_tick
    _game_time += dt

    # --- Coordination timeout check ---
    _tick_coordinations()

    # --- Combat summary (1.3) ---
    _tick_combat(tick_num, enemy_count)

    # --- Resource snapshot (1.4) ---
    if ship is not None:
        tick_resources(tick_num, ship)

    # --- Environment snapshot (1.5) ---
    if ship is not None:
        tick_environment(tick_num, ship)

    # --- Phase tracking (1.7) ---
    tick_phase(tick_num, enemy_count, hull_pct, mission_active)

    # --- Idle detection (check every tick) ---
    for name, ps in _players.items():
        if ps.is_idle:
            continue
        if ps.last_action_ts < 0.0:
            # Player hasn't acted yet — don't flag idle before first action.
            continue
        since_last = _game_time - ps.last_action_ts
        if since_last >= IDLE_THRESHOLD_S:
            ps.is_idle = True
            ps.idle_start_ts = _game_time
            _log("telemetry", "player_idle", {
                "player": name,
                "station": ps.station,
                "idle_seconds": round(since_last, 1),
            })

    # --- 30 s engagement summary ---
    if tick_num - _last_engagement_tick >= ENGAGEMENT_INTERVAL_TICKS:
        _last_engagement_tick = tick_num
        for name, ps in _players.items():
            _log("telemetry", "player_engagement", {
                "player": name,
                "current_station": ps.station,
                "seconds_on_station": round(_game_time - ps.station_start_ts, 1),
                "actions_last_30s": ps.actions_window,
                "seconds_since_last_action": round(
                    _game_time - ps.last_action_ts, 1
                ) if ps.last_action_ts >= 0 else round(_game_time, 1),
                "total_actions_this_game": ps.total_actions,
                "stations_visited": list(ps.stations_visited),
                "station_visit_count": ps.station_visit_count,
            })
            ps.actions_window = 0


def get_player_states() -> dict[str, _PlayerState]:
    """Return a copy of per-player states (for testing / analysis)."""
    return dict(_players)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _station_from_type(msg_type: str) -> str | None:
    """Extract canonical station name from a message type like 'helm.set_heading'."""
    prefix = msg_type.split(".")[0] if "." in msg_type else msg_type
    return _PREFIX_TO_STATION.get(prefix)


# ===================================================================
# Section 1.2 — Cross-Station Coordination Tracking
# ===================================================================

# Each coordination chain: (chain_name, initiator_station, responder_station, timeout_s)
_COORDINATION_CHAINS: list[tuple[str, str, str, float]] = [
    ("captain_priority_target",    "captain",        "weapons",        30.0),
    ("captain_general_order",      "captain",        "*",              30.0),  # any station
    ("science_scan_to_ops",        "science",        "operations",     60.0),
    ("ops_assessment_to_weapons",  "operations",     "weapons",        60.0),
    ("engineering_overclock_fire", "engineering",     "hazard_control", 30.0),
    ("fire_to_hazcon",             "*",              "hazard_control", 45.0),
    ("casualty_to_medical",        "*",              "medical",        60.0),
    ("boarding_to_security",       "*",              "security",       30.0),
    ("mission_to_comms",           "*",              "comms",          90.0),
    ("distress_to_helm",           "*",              "helm",           120.0),
]

# Map chain_name → (initiator, responder, timeout_s)
_CHAIN_DEFS: dict[str, tuple[str, str, float]] = {
    c[0]: (c[1], c[2], c[3]) for c in _COORDINATION_CHAINS
}


@dataclass
class _PendingCoordination:
    """An active coordination chain awaiting response."""
    chain: str
    initiator: str
    responder: str
    initiated_at: float
    timeout_s: float


_pending_coordinations: list[_PendingCoordination] = []


def coordination_initiated(chain: str) -> None:
    """Record that a coordination chain has been initiated.

    Called from game_loop.py when a log event matches an initiator pattern.
    """
    defn = _CHAIN_DEFS.get(chain)
    if defn is None:
        return
    initiator, responder, timeout_s = defn
    _pending_coordinations.append(_PendingCoordination(
        chain=chain,
        initiator=initiator,
        responder=responder,
        initiated_at=_game_time,
        timeout_s=timeout_s,
    ))


def coordination_responded(chain: str) -> None:
    """Record that a responder acted on a pending coordination chain.

    Finds the oldest pending entry for this chain and logs the result.
    """
    for i, pc in enumerate(_pending_coordinations):
        if pc.chain == chain:
            response_time = _game_time - pc.initiated_at
            _log("telemetry", "coordination_check", {
                "chain": pc.chain,
                "initiator": pc.initiator,
                "responder": pc.responder,
                "initiated_at": round(pc.initiated_at, 1),
                "responded": True,
                "response_time_seconds": round(response_time, 1),
            })
            _pending_coordinations.pop(i)
            return


def _tick_coordinations() -> None:
    """Check for timed-out coordination chains."""
    expired: list[int] = []
    for i, pc in enumerate(_pending_coordinations):
        if _game_time - pc.initiated_at >= pc.timeout_s:
            # Check if the responder station is manned.
            manned = pc.responder in _role_to_player if pc.responder != "*" else True
            _log("telemetry", "coordination_timeout", {
                "chain": pc.chain,
                "initiator": pc.initiator,
                "responder": pc.responder,
                "initiated_at": round(pc.initiated_at, 1),
                "timeout_seconds": pc.timeout_s,
                "responder_station_manned": manned,
            })
            expired.append(i)
    for i in reversed(expired):
        _pending_coordinations.pop(i)


def get_pending_coordinations() -> list[_PendingCoordination]:
    """Return pending coordination chains (for testing)."""
    return list(_pending_coordinations)


# ===================================================================
# Section 1.3 — Combat Effectiveness Metrics
# ===================================================================

COMBAT_SUMMARY_INTERVAL_TICKS: int = 300  # 30 s


@dataclass
class _CombatWindow:
    """Counters for the current 30 s combat window."""
    torpedoes_fired: int = 0
    torpedoes_hit: int = 0
    beam_shots_fired: int = 0
    beam_damage_dealt: float = 0.0
    enemies_destroyed: int = 0
    damage_taken_hull: float = 0.0
    damage_taken_shields: float = 0.0


_combat: _CombatWindow = _CombatWindow()
_last_combat_tick: int = 0
_in_combat: bool = False  # True when enemies > 0


def record_torpedo_fired() -> None:
    """Called when a torpedo is fired."""
    _combat.torpedoes_fired += 1


def record_torpedo_hit(torpedo_type: str, target_id: str, damage: float) -> None:
    """Called when a torpedo hits its target."""
    _combat.torpedoes_hit += 1


def record_torpedo_outcome(torpedo_type: str, target_id: str, hit: bool,
                           miss_reason: str = "", distance: float = 0.0,
                           flight_time: float = 0.0) -> None:
    """Log individual torpedo outcome event."""
    _log("telemetry", "torpedo_outcome", {
        "torpedo_type": torpedo_type,
        "target_id": target_id,
        "target_distance_at_fire": round(distance, 0),
        "hit": hit,
        "miss_reason": miss_reason,
        "flight_time": round(flight_time, 1),
    })


def record_beam_fired(damage: float = 0.0) -> None:
    """Called when beams are fired."""
    _combat.beam_shots_fired += 1
    _combat.beam_damage_dealt += damage


def record_enemy_destroyed() -> None:
    """Called when an enemy is destroyed."""
    _combat.enemies_destroyed += 1


def record_damage_taken(hull_damage: float, shield_damage: float) -> None:
    """Called after each combat tick with hull/shield damage taken."""
    _combat.damage_taken_hull += hull_damage
    _combat.damage_taken_shields += shield_damage


def set_combat_state(enemy_count: int) -> None:
    """Update whether the ship is in combat (enemies > 0)."""
    global _in_combat
    _in_combat = enemy_count > 0


def _tick_combat(tick_num: int, enemy_count: int) -> None:
    """Emit 30 s combat summary when in combat."""
    global _last_combat_tick, _in_combat
    _in_combat = enemy_count > 0

    if tick_num - _last_combat_tick < COMBAT_SUMMARY_INTERVAL_TICKS:
        return
    _last_combat_tick = tick_num

    if not _in_combat and _combat.torpedoes_fired == 0 and _combat.beam_shots_fired == 0:
        return  # no combat activity

    hit_rate = (_combat.torpedoes_hit / _combat.torpedoes_fired
                if _combat.torpedoes_fired > 0 else 0.0)
    total_incoming = _combat.damage_taken_hull + _combat.damage_taken_shields
    shield_eff = (_combat.damage_taken_shields / total_incoming
                  if total_incoming > 0 else 1.0)

    _log("telemetry", "combat_summary", {
        "torpedoes_fired": _combat.torpedoes_fired,
        "torpedoes_hit": _combat.torpedoes_hit,
        "torpedo_hit_rate": round(hit_rate, 2),
        "beam_shots_fired": _combat.beam_shots_fired,
        "beam_damage_dealt": round(_combat.beam_damage_dealt, 1),
        "enemies_destroyed": _combat.enemies_destroyed,
        "enemies_active": enemy_count,
        "damage_taken_hull": round(_combat.damage_taken_hull, 1),
        "damage_taken_shields": round(_combat.damage_taken_shields, 1),
        "shield_efficiency": round(shield_eff, 2),
    })

    # Reset window counters.
    _combat.torpedoes_fired = 0
    _combat.torpedoes_hit = 0
    _combat.beam_shots_fired = 0
    _combat.beam_damage_dealt = 0.0
    _combat.enemies_destroyed = 0
    _combat.damage_taken_hull = 0.0
    _combat.damage_taken_shields = 0.0


def get_combat_window() -> _CombatWindow:
    """Return current combat window state (for testing)."""
    return _combat


# ===================================================================
# Section 1.4 — Resource Tracking
# ===================================================================

RESOURCE_SNAPSHOT_INTERVAL_TICKS: int = 600  # 60 s

_last_resource_tick: int = 0
_prev_ammo: dict[str, int] = {}


def tick_resources(tick_num: int, ship) -> None:
    """Emit 60 s resource snapshot."""
    global _last_resource_tick, _prev_ammo
    if tick_num - _last_resource_tick < RESOURCE_SNAPSHOT_INTERVAL_TICKS:
        return
    _last_resource_tick = tick_num

    ammo = {}
    consumed = {}
    try:
        from server.game_loop_weapons import get_ammo
        ammo = get_ammo()
        if _prev_ammo:
            consumed = {k: _prev_ammo.get(k, 0) - ammo.get(k, 0)
                        for k in _prev_ammo if _prev_ammo.get(k, 0) - ammo.get(k, 0) > 0}
        _prev_ammo = dict(ammo)
    except Exception:
        pass

    fuel_pct = 0.0
    res = getattr(ship, "resources", None)
    if res is not None:
        fuel_pct = round((res.fuel / res.fuel_max * 100) if res.fuel_max > 0 else 0, 1)

    power_alloc = {}
    systems_below_80 = []
    for name, sys in ship.systems.items():
        power_alloc[name] = sys.power
        if sys.health < 80:
            systems_below_80.append(name)

    _log("telemetry", "resource_snapshot", {
        "ammo": ammo,
        "ammo_consumed_last_60s": consumed,
        "fuel_percent": fuel_pct,
        "power_allocation": power_alloc,
        "systems_below_80": systems_below_80,
    })


# ===================================================================
# Section 1.5 — Hazard/Environment State Tracking
# ===================================================================

ENVIRONMENT_SNAPSHOT_INTERVAL_TICKS: int = 300  # 30 s

_last_env_tick: int = 0


def tick_environment(tick_num: int, ship) -> None:
    """Emit 30 s environment state snapshot."""
    global _last_env_tick
    if tick_num - _last_env_tick < ENVIRONMENT_SNAPSHOT_INTERVAL_TICKS:
        return
    _last_env_tick = tick_num

    interior = getattr(ship, "interior", None)
    if interior is None:
        return

    fires: list[dict] = []
    breaches: list[dict] = []
    rooms_evacuated: list[str] = []

    try:
        from server.game_loop_hazard_control import get_fires
        for room_id, fire in get_fires().items():
            fires.append({
                "room": room_id,
                "intensity": fire.intensity,
            })
    except Exception:
        pass

    try:
        from server.game_loop_atmosphere import get_breaches
        for room_id, b in get_breaches().items():
            breaches.append({
                "room": room_id,
                "severity": b.severity,
            })
    except Exception:
        pass

    for room_id, room in interior.rooms.items():
        if getattr(room, "evacuated", False):
            rooms_evacuated.append(room_id)

    structural: dict[str, float] = {}
    try:
        from server.game_loop_hazard_control import get_sections
        for sec_id, sec in get_sections().items():
            structural[sec_id] = round(sec.integrity, 1)
    except Exception:
        pass

    _log("telemetry", "environment_snapshot", {
        "active_fires": fires,
        "breaches": breaches,
        "rooms_evacuated": rooms_evacuated,
        "structural_integrity": structural,
    })


# ===================================================================
# Section 1.6 — UI Interaction Quality (server-side logging)
# ===================================================================


def record_rapid_click(station: str, element: str, click_count: int,
                       duration_seconds: float) -> None:
    """Log a rapid-click frustration signal (sent from client via WebSocket)."""
    _log("telemetry", "rapid_click", {
        "station": station,
        "element": element,
        "click_count": click_count,
        "duration_seconds": round(duration_seconds, 1),
    })


def record_station_hopping(player: str, switches: int,
                           stations: list[str]) -> None:
    """Log station hopping (sent from client via WebSocket)."""
    _log("telemetry", "station_hopping", {
        "player": player,
        "switches_last_60s": switches,
        "stations_visited": stations,
    })


# ===================================================================
# Section 1.7 — Game Phase Tracking
# ===================================================================

_current_phase: str = "all_clear"
_combat_start_tick: int = 0
_no_enemies_since_tick: int = 0


def tick_phase(tick_num: int, enemy_count: int, hull_pct: float,
               mission_active: bool) -> None:
    """Detect and emit game phase transitions."""
    global _current_phase, _combat_start_tick, _no_enemies_since_tick

    new_phase = _current_phase

    if hull_pct < 50 and _current_phase != "crisis":
        new_phase = "crisis"
    elif enemy_count > 0 and _current_phase == "all_clear":
        new_phase = "first_contact"
        _combat_start_tick = tick_num
    elif enemy_count > 0 and _current_phase in ("first_contact", "all_clear"):
        new_phase = "combat_engaged"
    elif enemy_count == 0 and _current_phase in ("combat_engaged", "first_contact", "crisis"):
        if _no_enemies_since_tick == 0:
            _no_enemies_since_tick = tick_num
        elif tick_num - _no_enemies_since_tick >= 600:  # 60s
            new_phase = "all_clear"
    elif enemy_count > 0:
        _no_enemies_since_tick = 0

    if mission_active and _current_phase != "mission_active" and new_phase == "all_clear":
        new_phase = "mission_active"

    if new_phase != _current_phase:
        trigger_map = {
            "first_contact": "enemy_detected",
            "combat_engaged": "weapons_fired",
            "crisis": "hull_below_50",
            "mission_active": "mission_accepted",
            "all_clear": "no_enemies_60s",
        }
        _log("telemetry", "phase_change", {
            "phase": new_phase,
            "trigger": trigger_map.get(new_phase, "unknown"),
        })
        _current_phase = new_phase


def get_current_phase() -> str:
    """Return current game phase (for testing)."""
    return _current_phase
