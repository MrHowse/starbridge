"""
Janitor Station — Game Loop Integration.

Secret station unlocked by setting player name to "The Janitor" (or "thejanitor").
Maps mundane janitorial tasks to real game mechanics: system buffs, hazard
reduction, crew morale. Effects are real but invisible to other players.

Module-level state pattern (same as game_loop_ew.py).
"""
from __future__ import annotations

import random
import time as _time
from dataclasses import dataclass, field

from server.models.ship import Ship

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JANITOR_NAMES: frozenset[str] = frozenset({"the janitor", "thejanitor"})

#: Default cooldown for each task in seconds.
DEFAULT_COOLDOWN: float = 30.0
#: Default buff duration in seconds.
DEFAULT_BUFF_DURATION: float = 60.0

# ---------------------------------------------------------------------------
# Buff tracking
# ---------------------------------------------------------------------------


@dataclass
class TemporaryBuff:
    """Active efficiency buff applied by a maintenance task."""
    system: str          # system name or "all"
    amount: float        # additive efficiency bonus
    remaining: float     # seconds until expiry
    source: str = "maintenance"


# ---------------------------------------------------------------------------
# Action map — {task_id: {label, category, cooldown, effect_type, ...}}
# ---------------------------------------------------------------------------

JANITOR_ACTION_MAP: dict[str, dict] = {
    # Plumbing
    "fix_toilet_deck1":     {"label": "Fix Toilet (Deck 1)", "category": "plumbing", "cooldown": 30.0,
                             "effect": "boost_system", "system": "sensors", "amount": 0.05, "duration": 60.0},
    "fix_toilet_deck2":     {"label": "Fix Toilet (Deck 2)", "category": "plumbing", "cooldown": 30.0,
                             "effect": "boost_system", "system": "beams", "amount": 0.05, "duration": 60.0},
    "fix_toilet_deck3":     {"label": "Fix Toilet (Deck 3)", "category": "plumbing", "cooldown": 30.0,
                             "effect": "boost_system", "system": "engines", "amount": 0.05, "duration": 60.0},
    "unclog_main_sewage":   {"label": "Unclog Main Sewage Line", "category": "plumbing", "cooldown": 45.0,
                             "effect": "boost_system", "system": "engines", "amount": 0.10, "duration": 45.0},
    # Mopping
    "mop_deck1":            {"label": "Mop Deck 1", "category": "mopping", "cooldown": 25.0,
                             "effect": "reduce_hazard", "hazard": "radiation", "reduction": 0.10},
    "mop_deck2":            {"label": "Mop Deck 2", "category": "mopping", "cooldown": 25.0,
                             "effect": "reduce_hazard", "hazard": "fire", "reduction": 0.10},
    "mop_deck3":            {"label": "Mop Deck 3", "category": "mopping", "cooldown": 25.0,
                             "effect": "reduce_hazard", "hazard": "coolant", "reduction": 0.10},
    "clean_biohazard":      {"label": "Clean Biohazard", "category": "mopping", "cooldown": 40.0,
                             "effect": "reduce_contagion", "reduction": 0.25},
    # Restocking
    "restock_toilet_paper": {"label": "Restock Toilet Paper", "category": "restocking", "cooldown": 35.0,
                             "effect": "crew_morale_boost", "system": "all", "amount": 0.03, "duration": 90.0},
    "restock_coffee":       {"label": "Restock Coffee Machine", "category": "restocking", "cooldown": 35.0,
                             "effect": "boost_system", "system": "engines", "amount": 0.08, "duration": 60.0},
    "restock_snacks":       {"label": "Restock Bridge Snacks", "category": "restocking", "cooldown": 35.0,
                             "effect": "boost_system", "system": "sensors", "amount": 0.08, "duration": 60.0},
    "restock_medical_soap": {"label": "Restock Medical Soap", "category": "restocking", "cooldown": 35.0,
                             "effect": "medical_supplies", "amount": 2},
    # Maintenance
    "inspect_ventilation":  {"label": "Inspect Ventilation Ducts", "category": "maintenance", "cooldown": 60.0,
                             "effect": "detect_boarders", "duration": 30.0},
    "check_cable_runs":     {"label": "Check Cable Runs", "category": "maintenance", "cooldown": 45.0,
                             "effect": "intel_boost", "duration": 30.0},
    "maintenance_tunnel_shortcut": {"label": "Open Maintenance Tunnel Shortcut", "category": "maintenance", "cooldown": 60.0,
                             "effect": "repair_team_boost", "amount": 0.30, "duration": 30.0},
    # Pest Control
    "set_rat_traps":        {"label": "Set Rat Traps", "category": "pest_control", "cooldown": 50.0,
                             "effect": "boost_system", "system": "torpedoes", "amount": 0.05, "duration": 60.0},
    "fumigate_deck":        {"label": "Fumigate Deck", "category": "pest_control", "cooldown": 60.0,
                             "effect": "damage_boarders", "damage": 10},
    # Special
    "fix_everything":       {"label": "\"Fix Everything\"", "category": "special", "cooldown": 120.0,
                             "effect": "global_boost", "amount": 0.03, "duration": 30.0},
    "plumbers_intuition":   {"label": "Plumber's Intuition", "category": "special", "cooldown": 90.0,
                             "effect": "predict_damage"},
    "the_secret_stash":     {"label": "The Secret Stash", "category": "special", "cooldown": 120.0,
                             "effect": "random_bonus"},
}

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_buffs: list[TemporaryBuff] = []
_cooldowns: dict[str, float] = {}       # task_id → remaining cooldown seconds
_task_counts: dict[str, int] = {}       # task_id → times performed
_sticky_notes: list[dict] = []          # {id, text, source, ts}
_sticky_counter: int = 0
_pending_events: list[dict] = []        # events to broadcast this tick
_intel_boost_remaining: float = 0.0     # decode speed boost timer
_repair_boost_remaining: float = 0.0    # repair speed boost timer
_repair_boost_amount: float = 0.0
_detect_boarders_remaining: float = 0.0 # boarder detection timer
_total_tasks_completed: int = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_janitor_name(name: str) -> bool:
    """Return True if *name* qualifies for the janitor station."""
    return name.strip().lower() in JANITOR_NAMES


def reset() -> None:
    """Clear all state. Called at game start."""
    global _sticky_counter, _intel_boost_remaining, _repair_boost_remaining
    global _repair_boost_amount, _detect_boarders_remaining, _total_tasks_completed
    _buffs.clear()
    _cooldowns.clear()
    _task_counts.clear()
    _sticky_notes.clear()
    _sticky_counter = 0
    _pending_events.clear()
    _intel_boost_remaining = 0.0
    _repair_boost_remaining = 0.0
    _repair_boost_amount = 0.0
    _detect_boarders_remaining = 0.0
    _total_tasks_completed = 0


def perform_task(task_id: str, ship: Ship, world: object | None = None) -> dict:
    """Execute a janitor action. Returns {ok, message} or {ok: False, error}."""
    global _intel_boost_remaining, _repair_boost_remaining
    global _repair_boost_amount, _detect_boarders_remaining, _total_tasks_completed

    action = JANITOR_ACTION_MAP.get(task_id)
    if action is None:
        return {"ok": False, "error": "Unknown task."}

    # Check cooldown.
    if _cooldowns.get(task_id, 0) > 0:
        return {"ok": False, "error": "Task on cooldown.", "remaining": round(_cooldowns[task_id], 1)}

    effect = action["effect"]
    result_msg = f"Completed: {action['label']}"

    if effect == "boost_system":
        _buffs.append(TemporaryBuff(
            system=action["system"],
            amount=action["amount"],
            remaining=action.get("duration", DEFAULT_BUFF_DURATION),
        ))
        result_msg = f"{action['label']} — {action['system']} +{int(action['amount']*100)}%"

    elif effect == "crew_morale_boost":
        _buffs.append(TemporaryBuff(
            system="all",
            amount=action["amount"],
            remaining=action.get("duration", DEFAULT_BUFF_DURATION),
        ))
        result_msg = f"{action['label']} — crew morale boosted"

    elif effect == "global_boost":
        for sys_name in ship.systems:
            _buffs.append(TemporaryBuff(
                system=sys_name,
                amount=action["amount"],
                remaining=action.get("duration", DEFAULT_BUFF_DURATION),
            ))
        result_msg = f"{action['label']} — all systems +{int(action['amount']*100)}%"

    elif effect == "reduce_hazard":
        # Reduce hazard effect — real effect tracked via buff on shields
        _buffs.append(TemporaryBuff(
            system="shields",
            amount=action.get("reduction", 0.05),
            remaining=60.0,
        ))
        result_msg = f"{action['label']} — {action['hazard']} hazard reduced"

    elif effect == "reduce_contagion":
        # Add a medical buff as proxy for contagion reduction
        _buffs.append(TemporaryBuff(
            system="sensors",
            amount=0.05,
            remaining=60.0,
        ))
        result_msg = f"{action['label']} — contagion risk reduced by {int(action['reduction']*100)}%"

    elif effect == "medical_supplies":
        ship.medical_supplies = min(ship.medical_supplies + action["amount"], 50)
        result_msg = f"{action['label']} — +{action['amount']} medical supplies"

    elif effect == "detect_boarders":
        _detect_boarders_remaining = action.get("duration", 30.0)
        result_msg = f"{action['label']} — intruder detection active for {int(_detect_boarders_remaining)}s"

    elif effect == "intel_boost":
        _intel_boost_remaining = action.get("duration", 30.0)
        result_msg = f"{action['label']} — decode speed boosted for {int(_intel_boost_remaining)}s"

    elif effect == "repair_team_boost":
        _repair_boost_remaining = action.get("duration", 30.0)
        _repair_boost_amount = action.get("amount", 0.30)
        result_msg = f"{action['label']} — repair teams +{int(_repair_boost_amount*100)}% speed"

    elif effect == "damage_boarders":
        # Apply damage to boarders (if any exist on ship interior)
        damage = action.get("damage", 10)
        hit_count = 0
        for room in ship.interior.rooms.values():
            for intruder in getattr(room, "intruders", []):
                intruder.health = max(0, intruder.health - damage)
                hit_count += 1
        result_msg = f"{action['label']} — {hit_count} intruder(s) fumigated ({damage} dmg each)"

    elif effect == "predict_damage":
        # Peek at ship state — predict next system failure
        weakest = min(ship.systems.values(), key=lambda s: s.health)
        result_msg = f"Plumber's Intuition: {weakest.name} looks dodgy ({weakest.health:.0f}% health)"

    elif effect == "random_bonus":
        bonus = random.choice(["hull", "medical", "torpedo", "morale"])
        if bonus == "hull":
            ship.hull = min(ship.hull + 5, ship.hull_max)
            result_msg = "Found some spare hull plating! (+5 hull)"
        elif bonus == "medical":
            ship.medical_supplies = min(ship.medical_supplies + 3, 50)
            result_msg = "Found a first aid kit behind the pipes! (+3 medical supplies)"
        elif bonus == "torpedo":
            result_msg = "Found... a torpedo? In the cleaning closet? (How did that get there?)"
        elif bonus == "morale":
            _buffs.append(TemporaryBuff(system="all", amount=0.05, remaining=90.0))
            result_msg = "Found a motivational poster. Crew morale improved!"

    # Set cooldown and increment count.
    _cooldowns[task_id] = action.get("cooldown", DEFAULT_COOLDOWN)
    _task_counts[task_id] = _task_counts.get(task_id, 0) + 1
    _total_tasks_completed += 1

    return {"ok": True, "message": result_msg, "task_id": task_id}


def tick(ship: Ship, dt: float, world: object | None = None) -> list[dict]:
    """Decay cooldowns and buffs. Called once per game tick."""
    global _intel_boost_remaining, _repair_boost_remaining, _detect_boarders_remaining
    events: list[dict] = []

    # Decay cooldowns.
    expired_keys = []
    for task_id in list(_cooldowns):
        _cooldowns[task_id] -= dt
        if _cooldowns[task_id] <= 0:
            expired_keys.append(task_id)
    for k in expired_keys:
        del _cooldowns[k]

    # Decay buffs.
    still_active: list[TemporaryBuff] = []
    for buff in _buffs:
        buff.remaining -= dt
        if buff.remaining > 0:
            still_active.append(buff)
    _buffs.clear()
    _buffs.extend(still_active)

    # Decay special timers.
    if _intel_boost_remaining > 0:
        _intel_boost_remaining = max(0.0, _intel_boost_remaining - dt)
    if _repair_boost_remaining > 0:
        _repair_boost_remaining = max(0.0, _repair_boost_remaining - dt)
    if _detect_boarders_remaining > 0:
        _detect_boarders_remaining = max(0.0, _detect_boarders_remaining - dt)

    # Generate urgent tasks based on ship state.
    urgents = generate_urgent_tasks(ship, world)
    if urgents:
        events.append({"type": "janitor.urgent_tasks", "tasks": urgents})

    # Drain pending events.
    events.extend(_pending_events)
    _pending_events.clear()

    return events


def apply_buffs(ship: Ship) -> None:
    """Write _maintenance_buff onto each ship system from active buffs.

    Called once per tick, after update_crew_factors().
    Resets all buffs to 0 first, then sums active buffs.
    """
    for sys_obj in ship.systems.values():
        sys_obj._maintenance_buff = 0.0

    for buff in _buffs:
        if buff.system == "all":
            for sys_obj in ship.systems.values():
                sys_obj._maintenance_buff += buff.amount
        else:
            sys_obj = ship.systems.get(buff.system)
            if sys_obj is not None:
                sys_obj._maintenance_buff += buff.amount


def dismiss_sticky(sticky_id: str) -> None:
    """Remove a sticky note by ID."""
    for i, note in enumerate(_sticky_notes):
        if note.get("id") == sticky_id:
            _sticky_notes.pop(i)
            return


def generate_urgent_tasks(ship: Ship, world: object | None = None) -> list[dict]:
    """Check ship state and return urgent task suggestions."""
    urgents: list[dict] = []

    # Fire on any deck
    for room in ship.interior.rooms.values():
        if getattr(room, "fire", False):
            urgents.append({
                "id": f"urgent_fire_{room.name}",
                "label": f"URGENT: Fire extinguisher refill — {room.name}",
                "category": "urgent",
            })
            break  # One fire alert is enough

    # Low hull
    if ship.hull < ship.hull_max * 0.20:
        urgents.append({
            "id": "urgent_low_hull",
            "label": "URGENT: Hold It Together (+5% hull for 60s)",
            "category": "urgent",
        })

    # Boarding
    for room in ship.interior.rooms.values():
        if getattr(room, "intruders", []):
            urgents.append({
                "id": "urgent_boarding",
                "label": "URGENT: Lock supply closets (boarders detected)",
                "category": "urgent",
            })
            break

    return urgents


def generate_sticky_note(event_type: str, data: dict | None = None) -> dict:
    """Create a flavour sticky note from a game event."""
    global _sticky_counter
    _sticky_counter += 1
    data = data or {}

    texts = {
        "hull_hit":       "Dear Janitor, there's a mess on Deck {deck}. Please clean it up. — Bridge",
        "system_damage":  "The {system} is acting up. Did you touch the cables? — Science",
        "boarding":       "Lot of mess on Deck 2. Sorry. — Marine Alpha",
        "all_clean":      "THE SHIP IS CLEAN. For a moment, everything is perfect.",
    }

    template = texts.get(event_type, "Maintenance requested.")
    try:
        text = template.format(**data)
    except (KeyError, IndexError):
        text = template

    note = {
        "id": f"sticky_{_sticky_counter}",
        "text": text,
        "source": event_type,
        "ts": _time.time(),
    }
    _sticky_notes.append(note)
    return note


def build_state(ship: Ship, world: object | None = None) -> dict:
    """Build full state payload for the janitor station."""
    tasks = []
    for task_id, action in JANITOR_ACTION_MAP.items():
        cd = _cooldowns.get(task_id, 0)
        tasks.append({
            "id": task_id,
            "label": action["label"],
            "category": action["category"],
            "cooldown_remaining": round(max(0, cd), 1),
            "cooldown_total": action.get("cooldown", DEFAULT_COOLDOWN),
            "ready": cd <= 0,
            "times_performed": _task_counts.get(task_id, 0),
        })

    active_buffs = [
        {
            "system": b.system,
            "amount": round(b.amount, 3),
            "remaining": round(b.remaining, 1),
        }
        for b in _buffs
    ]

    urgents = generate_urgent_tasks(ship, world)

    return {
        "tasks": tasks,
        "active_buffs": active_buffs,
        "sticky_notes": list(_sticky_notes),
        "urgent_tasks": urgents,
        "total_tasks_completed": _total_tasks_completed,
        "intel_boost_active": _intel_boost_remaining > 0,
        "repair_boost_active": _repair_boost_remaining > 0,
        "detect_boarders_active": _detect_boarders_remaining > 0,
    }


def has_intel_boost() -> bool:
    """Return True if decode speed boost is active."""
    return _intel_boost_remaining > 0


def has_repair_boost() -> float:
    """Return repair speed multiplier (0.0 if inactive)."""
    return _repair_boost_amount if _repair_boost_remaining > 0 else 0.0


def has_detect_boarders() -> bool:
    """Return True if boarder detection is active."""
    return _detect_boarders_remaining > 0


def get_total_tasks() -> int:
    """Return total tasks completed this session."""
    return _total_tasks_completed


def serialise() -> dict:
    """Serialise state for save system."""
    return {
        "buffs": [
            {"system": b.system, "amount": b.amount, "remaining": b.remaining}
            for b in _buffs
        ],
        "cooldowns": dict(_cooldowns),
        "task_counts": dict(_task_counts),
        "sticky_notes": list(_sticky_notes),
        "sticky_counter": _sticky_counter,
        "intel_boost_remaining": _intel_boost_remaining,
        "repair_boost_remaining": _repair_boost_remaining,
        "repair_boost_amount": _repair_boost_amount,
        "detect_boarders_remaining": _detect_boarders_remaining,
        "total_tasks_completed": _total_tasks_completed,
    }


def deserialise(data: dict) -> None:
    """Restore state from save data."""
    global _sticky_counter, _intel_boost_remaining, _repair_boost_remaining
    global _repair_boost_amount, _detect_boarders_remaining, _total_tasks_completed
    reset()

    for bd in data.get("buffs", []):
        _buffs.append(TemporaryBuff(
            system=bd["system"],
            amount=bd["amount"],
            remaining=bd["remaining"],
        ))

    _cooldowns.update(data.get("cooldowns", {}))
    _task_counts.update(data.get("task_counts", {}))
    _sticky_notes.extend(data.get("sticky_notes", []))
    _sticky_counter = data.get("sticky_counter", 0)
    _intel_boost_remaining = data.get("intel_boost_remaining", 0.0)
    _repair_boost_remaining = data.get("repair_boost_remaining", 0.0)
    _repair_boost_amount = data.get("repair_boost_amount", 0.0)
    _detect_boarders_remaining = data.get("detect_boarders_remaining", 0.0)
    _total_tasks_completed = data.get("total_tasks_completed", 0)
