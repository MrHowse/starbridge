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
DEFAULT_COOLDOWN: float = 180.0
#: Default buff duration in seconds.
DEFAULT_BUFF_DURATION: float = 120.0

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
# Action map — {task_id: {label, flavour, category, cooldown, effect_type, ...}}
# ---------------------------------------------------------------------------

JANITOR_ACTION_MAP: dict[str, dict] = {
    # === PLUMBING === (maps to Engineering/Power)
    "fix_toilet_deck1": {
        "label": "Fix the toilet on Deck 1 (Bridge)",
        "flavour": "The Captain has been complaining again.",
        "category": "plumbing", "cooldown": 180.0,
        "effect": "boost_system", "system": "sensors", "amount": 0.05, "duration": 120.0,
    },
    "fix_toilet_deck2": {
        "label": "Fix the toilet on Deck 2 (Weapons)",
        "flavour": "Something is very wrong in there.",
        "category": "plumbing", "cooldown": 180.0,
        "effect": "boost_system", "system": "beams", "amount": 0.05, "duration": 120.0,
    },
    "fix_toilet_deck3": {
        "label": "Fix the toilet on Deck 3 (Engineering)",
        "flavour": "The U-bend is making ominous noises.",
        "category": "plumbing", "cooldown": 180.0,
        "effect": "boost_system", "system": "engines", "amount": 0.05, "duration": 120.0,
    },
    "unclog_main_sewage": {
        "label": "Unclog the main sewage line",
        "flavour": "Nobody else is going to do this.",
        "category": "plumbing", "cooldown": 240.0,
        "effect": "boost_system", "system": "engines", "amount": 0.10, "duration": 120.0,
    },
    # === MOPPING === (maps to Hazard Clearance)
    "mop_deck1": {
        "label": "Mop the Bridge corridor",
        "flavour": "Someone tracked nebula residue everywhere.",
        "category": "mopping", "cooldown": 120.0,
        "effect": "reduce_hazard", "hazard": "radiation", "reduction": 0.20,
    },
    "mop_deck2": {
        "label": "Mop the Weapons bay floor",
        "flavour": "Torpedo lubricant everywhere. Again.",
        "category": "mopping", "cooldown": 120.0,
        "effect": "reduce_hazard", "hazard": "fire", "reduction": 0.15,
    },
    "mop_deck3": {
        "label": "Mop Engineering",
        "flavour": "Coolant leak. Smells like regret.",
        "category": "mopping", "cooldown": 120.0,
        "effect": "reduce_hazard", "hazard": "coolant", "reduction": 0.20,
    },
    "clean_biohazard": {
        "label": "Clean up the biohazard in Medical",
        "flavour": "You don't want to know. Trust me.",
        "category": "mopping", "cooldown": 180.0,
        "effect": "reduce_contagion", "reduction": 0.25,
    },
    # === RESTOCKING === (maps to Resources/Morale)
    "restock_toilet_paper": {
        "label": "Restock toilet paper (ALL decks)",
        "flavour": "The most critical supply on the ship.",
        "category": "restocking", "cooldown": 300.0,
        "effect": "crew_morale_boost", "system": "all", "amount": 0.03, "duration": 180.0,
    },
    "restock_coffee": {
        "label": "Restock the coffee machine",
        "flavour": "Engineering has been through 40 cups today.",
        "category": "restocking", "cooldown": 180.0,
        "effect": "boost_system", "system": "engines", "amount": 0.08, "duration": 120.0,
    },
    "restock_snacks": {
        "label": "Restock the Bridge snack drawer",
        "flavour": "The Captain gets cranky without biscuits.",
        "category": "restocking", "cooldown": 180.0,
        "effect": "boost_system", "system": "sensors", "amount": 0.08, "duration": 120.0,
    },
    "restock_medical_soap": {
        "label": "Restock antibacterial soap in Medical",
        "flavour": "Hygiene is the first line of defence.",
        "category": "restocking", "cooldown": 180.0,
        "effect": "medical_supplies", "amount": 2,
    },
    # === MAINTENANCE TUNNELS === (maps to Intelligence)
    "inspect_ventilation": {
        "label": "Inspect the ventilation ducts",
        "flavour": "Routine maintenance. Definitely not spying.",
        "category": "maintenance", "cooldown": 120.0,
        "effect": "detect_boarders", "duration": 30.0,
    },
    "check_cable_runs": {
        "label": "Check the cable runs between decks",
        "flavour": "Someone has been tapping the comms lines.",
        "category": "maintenance", "cooldown": 240.0,
        "effect": "intel_boost", "duration": 30.0,
    },
    "maintenance_tunnel_shortcut": {
        "label": "Use the maintenance tunnels",
        "flavour": "You know ways through this ship that the blueprints don't show.",
        "category": "maintenance", "cooldown": 180.0,
        "effect": "repair_team_boost", "amount": 0.30, "duration": 60.0,
    },
    # === PEST CONTROL === (maps to Creature/Boarding)
    "set_rat_traps": {
        "label": "Set rat traps in the cargo hold",
        "flavour": "Something has been getting into the supplies.",
        "category": "pest_control", "cooldown": 180.0,
        "effect": "boost_system", "system": "torpedoes", "amount": 0.05, "duration": 120.0,
    },
    "fumigate_deck": {
        "label": "Fumigate the lower decks",
        "flavour": "The smell is... concerning.",
        "category": "pest_control", "cooldown": 300.0,
        "effect": "damage_boarders", "damage": 10,
    },
    # === THE BIG ONES === (powerful, long cooldown)
    "fix_everything": {
        "label": "The Big Clean",
        "flavour": "Lock yourself in. Put on the music. Clean EVERYTHING.",
        "category": "special", "cooldown": 600.0,
        "effect": "global_boost", "amount": 0.03, "duration": 60.0,
    },
    "plumbers_intuition": {
        "label": "Listen to the Pipes",
        "flavour": "The pipes tell you things. Where the pressure is wrong. "
                   "Where something is about to break.",
        "category": "special", "cooldown": 300.0,
        "effect": "predict_damage",
    },
    "the_secret_stash": {
        "label": "Check The Secret Stash",
        "flavour": "Behind the false wall in Supply Closet 3B. "
                   "Every janitor knows about it. Nobody else does.",
        "category": "special", "cooldown": 480.0,
        "effect": "random_bonus",
    },
}

# Lore text for "Listen to the Pipes" (rotated through).
_PIPE_LORE: list[str] = [
    "The pipes whisper of an attack from the north. They're never wrong.",
    "Something is rattling in the port-side conduits. Shields, maybe.",
    "The water pressure dropped on Deck 3. Something is pulling power.",
    "You hear a faint hum. The engines are about to have a bad day.",
    "The pipes are quiet. Too quiet. That's never good.",
    "There's a vibration in the hull. Something big is coming.",
]

# Lore text for "The Secret Stash" (appended to result occasionally).
_STASH_LORE: list[str] = [
    " A note reads: 'Left by the previous Janitor. And the one before that. "
    "And the one before that. The Janitor is eternal.'",
    " Someone scratched into the wall: 'The Janitor sees all.'",
    "",
    "",
    "",
]

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


# ---------------------------------------------------------------------------
# Result message helpers (flavourful, in-character)
# ---------------------------------------------------------------------------

_RESULT_MESSAGES: dict[str, list[str]] = {
    "fix_toilet_deck1":     ["Toilet fixed. You're a hero.", "The Captain will never know. Or thank you."],
    "fix_toilet_deck2":     ["Fixed. The Weapons bay smells almost tolerable now.", "Plumbing restored. Nobody noticed."],
    "fix_toilet_deck3":     ["U-bend secured. Engineering owes you one.", "Fixed. The ominous noises have stopped. For now."],
    "unclog_main_sewage":   ["Main line clear. You don't want to know what was in there.", "Sewage flowing freely. You are a champion of infrastructure."],
    "mop_deck1":            ["Floor mopped. Spotless.", "Bridge corridor gleaming. Someone will track mud through it in 5 minutes."],
    "mop_deck2":            ["Torpedo lubricant cleaned up. Again.", "Floor's clean. They'll mess it up by next shift."],
    "mop_deck3":            ["Coolant mopped. Your shoes may never recover.", "Engineering floor clean. Smells like regret and pine cleaner."],
    "clean_biohazard":      ["Biohazard contained. You don't get paid enough for this.", "Medical bay sanitised. Please wash your hands. Twice."],
    "restock_toilet_paper":  ["TP restocked on all decks. Crisis averted.", "The most important resupply mission of the war."],
    "restock_coffee":       ["Coffee machine loaded. Engineering owes you one.", "40 cups and counting. They'd mutiny without you."],
    "restock_snacks":       ["Snack drawer full. The Captain's mood will improve shortly.", "Biscuits deployed. Bridge morale holding."],
    "restock_medical_soap": ["Soap restocked. Hygiene is the first line of defence.", "Medical supplies topped up. Doctor might actually say thank you. (They won't.)"],
    "inspect_ventilation":  ["Ducts inspected. You see everything from up here.", "Routine maintenance. Definitely not spying."],
    "check_cable_runs":     ["Cables checked. Someone HAS been tapping the comms lines.", "Found some interesting wiring. Comms should work better now."],
    "maintenance_tunnel_shortcut": ["Shortcut opened. You know this ship better than the blueprints.", "Tunnel clear. The repair crews will thank you. (They won't know why.)"],
    "set_rat_traps":        ["Traps set. Whatever's in the cargo hold, you'll get it.", "Rat traps deployed. The supplies should be safe now."],
    "fumigate_deck":        ["Deck fumigated. Everything down there got a faceful.", "Lower decks fumigated. The smell will clear eventually."],
    "fix_everything":       ["THE BIG CLEAN IS DONE. The ship has never been this clean.", "Everything. Is. Clean. For one perfect moment."],
}


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

    # Pick a flavourful result message.
    msgs = _RESULT_MESSAGES.get(task_id)
    result_msg = random.choice(msgs) if msgs else f"Done: {action['label']}"

    if effect == "boost_system":
        _buffs.append(TemporaryBuff(
            system=action["system"],
            amount=action["amount"],
            remaining=action.get("duration", DEFAULT_BUFF_DURATION),
        ))

    elif effect == "crew_morale_boost":
        _buffs.append(TemporaryBuff(
            system="all",
            amount=action["amount"],
            remaining=action.get("duration", DEFAULT_BUFF_DURATION),
        ))

    elif effect == "global_boost":
        for sys_name in ship.systems:
            _buffs.append(TemporaryBuff(
                system=sys_name,
                amount=action["amount"],
                remaining=action.get("duration", DEFAULT_BUFF_DURATION),
            ))

    elif effect == "reduce_hazard":
        _buffs.append(TemporaryBuff(
            system="shields",
            amount=action.get("reduction", 0.05),
            remaining=DEFAULT_BUFF_DURATION,
        ))

    elif effect == "reduce_contagion":
        _buffs.append(TemporaryBuff(
            system="sensors",
            amount=0.05,
            remaining=DEFAULT_BUFF_DURATION,
        ))

    elif effect == "medical_supplies":
        ship.medical_supplies = min(ship.medical_supplies + action["amount"], 50)

    elif effect == "detect_boarders":
        _detect_boarders_remaining = action.get("duration", 30.0)

    elif effect == "intel_boost":
        _intel_boost_remaining = action.get("duration", 30.0)

    elif effect == "repair_team_boost":
        _repair_boost_remaining = action.get("duration", 60.0)
        _repair_boost_amount = action.get("amount", 0.30)

    elif effect == "damage_boarders":
        damage = action.get("damage", 10)
        hit_count = 0
        for room in ship.interior.rooms.values():
            for intruder in getattr(room, "intruders", []):
                intruder.health = max(0, intruder.health - damage)
                hit_count += 1
        if hit_count > 0:
            result_msg = f"Deck fumigated. {hit_count} intruder(s) got a faceful."
        else:
            result_msg = "Deck fumigated. Nothing down there. This time."

    elif effect == "predict_damage":
        weakest = min(ship.systems.values(), key=lambda s: s.health)
        # Lore text + practical info
        lore = random.choice(_PIPE_LORE)
        result_msg = f"{lore} ({weakest.name} at {weakest.health:.0f}%)"

    elif effect == "random_bonus":
        bonus = random.choice(["hull", "medical", "torpedo", "morale"])
        if bonus == "hull":
            ship.hull = min(ship.hull + 5, ship.hull_max)
            result_msg = "Found some spare hull plating behind the boiler! (+5 hull)"
        elif bonus == "medical":
            ship.medical_supplies = min(ship.medical_supplies + 3, 50)
            result_msg = "Found a first aid kit wedged behind the pipes! (+3 medical supplies)"
        elif bonus == "torpedo":
            result_msg = "Found... a torpedo? In the cleaning closet? How did that get there?"
        elif bonus == "morale":
            _buffs.append(TemporaryBuff(system="all", amount=0.05, remaining=120.0))
            result_msg = "Found a motivational poster: 'YOU'RE DOING GREAT'. Crew morale surged!"
        # Occasionally append lore note
        result_msg += random.choice(_STASH_LORE)

    # Set cooldown and increment count.
    _cooldowns[task_id] = action.get("cooldown", DEFAULT_COOLDOWN)
    _task_counts[task_id] = _task_counts.get(task_id, 0) + 1
    _total_tasks_completed += 1

    # Check for all-clean achievement.
    _check_all_clean()

    return {"ok": True, "message": result_msg, "task_id": task_id}


def _check_all_clean() -> None:
    """If all toilets fixed and all decks mopped this session, generate the all-clean note."""
    toilet_ids = {"fix_toilet_deck1", "fix_toilet_deck2", "fix_toilet_deck3"}
    mop_ids = {"mop_deck1", "mop_deck2", "mop_deck3"}
    all_done = all(_task_counts.get(tid, 0) > 0 for tid in toilet_ids | mop_ids)
    # Only fire once — check if already posted.
    if all_done and not any(n.get("source") == "all_clean" for n in _sticky_notes):
        generate_sticky_note("all_clean")


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
                "label": f"URGENT: Fire extinguisher refill \u2014 {room.name}",
                "category": "urgent",
            })
            break  # One fire alert is enough

    # Low hull — "Hold It Together"
    if ship.hull < ship.hull_max * 0.20:
        urgents.append({
            "id": "urgent_low_hull",
            "label": "URGENT: Hold It Together",
            "flavour": "Sometimes, a ship survives because someone in the depths "
                       "holds a pipe together with both hands and refuses to let go.",
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
        "hull_hit":       "Dear Janitor, there's a mess on Deck {deck}. Please clean it up. \u2014 Bridge",
        "system_damage":  "The {system} is acting up. Did you touch the cables again? \u2014 Science Officer",
        "boarding":       "Dear Janitor, there is a LOT of mess on Deck 2. Sorry. \u2014 Marine Alpha Squad",
        "creature_attack": "What IS that smell on the hull? Can you do something? \u2014 Helm",
        "coffee_request":  "The coffee machine on Deck 3 is making a sound like a dying whale. "
                          "Please investigate. \u2014 Chief Engineer",
        "airlock_note":    "To whoever keeps leaving the airlock inner door open: STOP. \u2014 Security",
        "toilet_thanks":   "Thank you for fixing the toilet. You saved the ship today and "
                          "nobody will ever know. \u2014 Anonymous",
        "employee_month":  "EMPLOYEE OF THE MONTH: The Janitor (14 months running)",
        "all_clean":       "THE SHIP IS CLEAN. For a moment, everything is perfect. "
                          "The crew breathes easier. Nobody knows why.",
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
            "flavour": action.get("flavour", ""),
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

    # Ship condition from the janitor's perspective.
    deck_conditions = _build_deck_conditions(ship)

    # Category-specific task counts for the flavoured stats bar.
    toilets_fixed = sum(_task_counts.get(t, 0) for t in
                        ("fix_toilet_deck1", "fix_toilet_deck2", "fix_toilet_deck3", "unclog_main_sewage"))
    floors_mopped = sum(_task_counts.get(t, 0) for t in
                        ("mop_deck1", "mop_deck2", "mop_deck3", "clean_biohazard"))
    coffee_restocked = _task_counts.get("restock_coffee", 0)
    rat_traps_set = _task_counts.get("set_rat_traps", 0)

    return {
        "tasks": tasks,
        "active_buffs": active_buffs,
        "sticky_notes": list(_sticky_notes),
        "urgent_tasks": urgents,
        "total_tasks_completed": _total_tasks_completed,
        "intel_boost_active": _intel_boost_remaining > 0,
        "repair_boost_active": _repair_boost_remaining > 0,
        "detect_boarders_active": _detect_boarders_remaining > 0,
        "deck_conditions": deck_conditions,
        "stats": {
            "toilets_fixed": toilets_fixed,
            "floors_mopped": floors_mopped,
            "coffee_restocked": coffee_restocked,
            "rat_traps_set": rat_traps_set,
        },
    }


def _build_deck_conditions(ship: Ship) -> list[dict]:
    """Build deck condition summary from ship state (janitor perspective)."""
    conditions = []
    # Group rooms by deck number (first char of room name if numeric, else "Other").
    decks: dict[str, list] = {}
    for room in ship.interior.rooms.values():
        # Extract deck identifier from room name (e.g., "Deck 1 Bridge" → "1").
        name = getattr(room, "name", "Unknown")
        parts = name.split()
        deck_num = "?"
        for i, p in enumerate(parts):
            if p.lower() == "deck" and i + 1 < len(parts):
                deck_num = parts[i + 1]
                break
        decks.setdefault(deck_num, []).append(room)

    for deck_id in sorted(decks.keys()):
        rooms = decks[deck_id]
        has_fire = any(getattr(r, "fire", False) for r in rooms)
        has_intruders = any(getattr(r, "intruders", []) for r in rooms)
        has_damage = any(getattr(r, "hull_breach", False) for r in rooms)

        if has_fire:
            status, icon = "FIRE!", "fire"
        elif has_intruders:
            status, icon = "Biohazard", "biohazard"
        elif has_damage:
            status, icon = "Disaster", "disaster"
        else:
            status, icon = "Tidy", "tidy"

        conditions.append({
            "deck": deck_id,
            "status": status,
            "icon": icon,
        })

    # If no deck info available, provide defaults.
    if not conditions:
        for i in range(1, 6):
            conditions.append({"deck": str(i), "status": "Tidy", "icon": "tidy"})

    return conditions


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
