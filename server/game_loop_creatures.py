"""Space Creature Game Loop Module (v0.05k).

Module-level state and public API for creature interactions.

Public API
----------
    reset()
    tick(world, dt) -> tuple[list[BeamHitEvent], list[dict]]
    advance_bio_study(creatures, dt)
    sedate_creature(creature_id, world) -> bool
    ew_disrupt_swarm(creature_id, world) -> bool
    set_comm_progress(creature_id, progress, world) -> bool
    remove_leech_depressurise(creature_id, world) -> bool
    remove_leech_electrical(creature_id, world) -> bool
    remove_leech_eva(creature_id, world) -> bool
    notify_weapon_hit(creature_id, weapon_type, world)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from server.models.world import CREATURE_TYPE_PARAMS

if TYPE_CHECKING:
    from server.models.world import Creature, World
    from server.systems.ai import BeamHitEvent


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_studied_ids: set[str] = set()       # creatures whose study_progress reached 100
_comm_complete_ids: set[str] = set() # creatures whose communication_progress reached 100
_leech_attached_ids: set[str] = set()  # leech IDs already broadcast as attached
_wake_was_active: bool = False        # previous-tick wake state for edge detection


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset() -> None:
    """Clear all creature module state. Called at game start / resume."""
    global _wake_was_active
    _studied_ids.clear()
    _comm_complete_ids.clear()
    _leech_attached_ids.clear()
    _wake_was_active = False


def tick(world: "World", dt: float) -> "tuple[list[BeamHitEvent], list[dict]]":
    """Tick all creatures; return (beam_hits, events).

    Events are dicts with a ``type`` key for game_loop.py to broadcast.
    Beam hits are passed to handle_enemy_beam_hits for damage application.
    Dead (hull <= 0, not attached) creatures are removed from world.creatures.
    """
    from server.systems.creature_ai import tick_creatures
    global _wake_was_active

    events: list[dict] = []

    # Run per-creature AI.
    beam_hits = tick_creatures(world.creatures, world.ship, dt)

    # Wake state-change events (void whale flee disrupts sector scans).
    wake_now = any(
        c.wake_active for c in world.creatures if c.creature_type == "void_whale"
    )
    if wake_now != _wake_was_active:
        _wake_was_active = wake_now
        if wake_now:
            events.append({"type": "creature.wake_started"})
        else:
            events.append({"type": "creature.wake_ended"})

    # Hull leech attachment event (first time attached).
    for c in world.creatures:
        if c.creature_type == "hull_leech" and c.attached and c.id not in _leech_attached_ids:
            _leech_attached_ids.add(c.id)
            events.append({"type": "creature.leech_attached", "creature_id": c.id})

    # Study completion events (fire once per creature).
    for c in world.creatures:
        if c.study_progress >= 100.0 and c.id not in _studied_ids:
            _studied_ids.add(c.id)
            events.append({
                "type": "creature.study_complete",
                "creature_id": c.id,
                "creature_type": c.creature_type,
            })

    # Communication completion events (fire once per creature).
    for c in world.creatures:
        if c.communication_progress >= 100.0 and c.id not in _comm_complete_ids:
            _comm_complete_ids.add(c.id)
            events.append({
                "type": "creature.communication_complete",
                "creature_id": c.id,
                "creature_type": c.creature_type,
            })

    # Creature destroyed events + removal from world list.
    dead = [c for c in world.creatures if c.hull <= 0.0 and not c.attached]
    for c in dead:
        events.append({
            "type": "creature.destroyed",
            "creature_id": c.id,
            "creature_type": c.creature_type,
        })
    world.creatures = [c for c in world.creatures if not (c.hull <= 0.0 and not c.attached)]

    return beam_hits, events


def advance_bio_study(creatures: "list[Creature]", dt: float) -> None:
    """Advance study_progress on all creatures while BIO sector scan is active.

    Hull leeches become detected (visible on sensors) as soon as study begins.
    Progress rate is creature-type dependent (100 / study_duration % per second).
    """
    for c in creatures:
        if c.study_progress >= 100.0:
            continue
        study_duration = CREATURE_TYPE_PARAMS[c.creature_type].get("study_duration", 60.0)
        rate = 100.0 / study_duration
        c.study_progress = min(100.0, c.study_progress + rate * dt)
        # Hull leech becomes detectable as soon as BIO scan begins.
        if c.creature_type == "hull_leech" and c.study_progress > 0.0:
            c.detected = True


def sedate_creature(creature_id: str, world: "World") -> bool:
    """Sedate a rift stalker (Comms broadcasts sedation frequency after BIO study).

    Returns True if the creature was found and sedated.
    """
    for c in world.creatures:
        if c.id == creature_id and c.creature_type == "rift_stalker":
            params = CREATURE_TYPE_PARAMS["rift_stalker"]
            c.sedated_timer = params["sedate_duration"]
            c.behaviour_state = "sedated"
            c.velocity = 0.0
            return True
    return False


def ew_disrupt_swarm(creature_id: str, world: "World") -> bool:
    """EW disrupts swarm communication frequency, causing dispersal.

    Returns True if the swarm was found and dispersed.
    """
    for c in world.creatures:
        if c.id == creature_id and c.creature_type == "swarm":
            c.behaviour_state = "dispersed"
            return True
    return False


def set_comm_progress(creature_id: str, progress: float, world: "World") -> bool:
    """Set communication progress (0–100) for a creature.

    Returns True if the creature was found.
    """
    for c in world.creatures:
        if c.id == creature_id:
            c.communication_progress = min(100.0, max(0.0, progress))
            return True
    return False


def remove_leech_depressurise(creature_id: str, world: "World") -> bool:
    """Remove a hull leech by depressurising the affected section (instant).

    Returns True if the leech was found and removed.
    """
    return _remove_leech(creature_id, world)


def remove_leech_electrical(creature_id: str, world: "World") -> bool:
    """Remove a hull leech by electrical discharge through hull plating (instant).

    Returns True if the leech was found and removed.
    """
    return _remove_leech(creature_id, world)


def remove_leech_eva(creature_id: str, world: "World") -> bool:
    """Remove a hull leech via EVA repair team (instant in this model).

    Returns True if the leech was found and removed.
    """
    return _remove_leech(creature_id, world)


def notify_weapon_hit(creature_id: str, weapon_type: str, world: "World") -> None:
    """Record the weapon type used against a swarm to update adaptation_state.

    ``weapon_type`` should be ``"beam"`` or ``"torpedo"``.
    """
    for c in world.creatures:
        if c.id == creature_id and c.creature_type == "swarm":
            if weapon_type == "beam":
                c.adaptation_state = "spread"
            elif weapon_type == "torpedo":
                c.adaptation_state = "clustered"
            break


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _remove_leech(creature_id: str, world: "World") -> bool:
    """Remove a hull leech by ID from world.creatures."""
    before = len(world.creatures)
    world.creatures = [
        c for c in world.creatures
        if not (c.id == creature_id and c.creature_type == "hull_leech")
    ]
    return len(world.creatures) < before
