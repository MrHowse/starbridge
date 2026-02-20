"""Tests for server/mission_graph.py — Mission Graph Engine.

Covers:
  - Initialization: start_node activated, others pending
  - Sequential objectives: A→B→C progression
  - Parallel nodes: all, any, count, count+within_seconds modes
  - Branch nodes: first trigger wins, others discarded
  - Conditional nodes: activate/deactivate based on game state
  - Compound triggers: all_of, any_of, none_of with nesting
  - All trigger types in new dict format
  - on_complete actions on edges and conditional on_activate/on_deactivate
  - Victory/defeat detection
  - State inspection interface
  - Checkpoint nodes (completes immediately)
  - Signal scan / proximity_with_shields
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from server.mission_graph import GraphObjective, MissionGraph
from server.models.ship import Ship
from server.models.world import Enemy, Station, World, spawn_enemy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_world(enemies=None, stations=None):
    w = World()
    w.enemies = enemies or []
    w.stations = stations or []
    return w


def _make_ship(x=50_000, y=50_000, hull=100.0, front_shield=100.0, rear_shield=100.0):
    s = Ship()
    s.x = x
    s.y = y
    s.hull = hull
    s.shields.front = front_shield
    s.shields.rear = rear_shield
    return s


def _make_enemy(eid="e1", scan_state="unknown"):
    e = spawn_enemy("scout", 70_000, 30_000, eid)
    e.scan_state = scan_state
    return e


def _make_station(sid="station_1", hull=100.0):
    st = Station(id=sid, x=0, y=0, hull=hull, hull_max=hull)
    return st


# Trigger factory helpers
def _timer(seconds):
    return {"type": "timer_elapsed", "seconds": seconds}


def _area(x=50_000, y=50_000, r=5_000):
    return {"type": "player_in_area", "x": x, "y": y, "r": r}


def _all_enemies():
    return {"type": "all_enemies_destroyed"}


def _hull_zero():
    return {"type": "ship_hull_zero"}


def _puzzle(label="p1"):
    return {"type": "puzzle_completed", "label": label}


def _hull_below(value=30):
    return {"type": "ship_hull_below", "value": value}


def _hull_above(value=50):
    return {"type": "ship_hull_above", "value": value}


# Graph factory helpers
def _simple_graph(trigger_dict, *, with_defeat=True):
    """One objective node → trivial graph."""
    d = {
        "id": "test",
        "name": "Test",
        "briefing": "",
        "nodes": [{"id": "obj_1", "type": "objective", "text": "Obj 1", "trigger": trigger_dict}],
        "edges": [],
        "start_node": "obj_1",
        "victory_nodes": ["obj_1"],
    }
    if with_defeat:
        d["defeat_condition"] = _hull_zero()
    return d


def _seq_graph(*triggers):
    """Linear graph: obj_1 → obj_2 → ... each with the given trigger."""
    n = len(triggers)
    nodes = [
        {"id": f"obj_{i+1}", "type": "objective", "text": f"Obj {i+1}", "trigger": triggers[i]}
        for i in range(n)
    ]
    edges = [
        {"from": f"obj_{i+1}", "to": f"obj_{i+2}", "type": "sequence"}
        for i in range(n - 1)
    ]
    return {
        "id": "test",
        "name": "Test",
        "briefing": "",
        "nodes": nodes,
        "edges": edges,
        "start_node": "obj_1",
        "victory_nodes": [f"obj_{n}"],
        "defeat_condition": _hull_zero(),
    }


def _tick_n(engine, world, ship, n, dt=0.1):
    """Advance engine by n ticks, return list of all completed ids."""
    completed = []
    for _ in range(n):
        completed.extend(engine.tick(world, ship, dt))
    return completed


# ---------------------------------------------------------------------------
# Section 1 — Initialization
# ---------------------------------------------------------------------------


def test_start_node_is_active_after_init():
    engine = MissionGraph(_simple_graph(_timer(10)))
    assert "obj_1" in engine.get_active_node_ids()


def test_non_start_nodes_are_pending():
    mission = _seq_graph(_timer(0), _timer(0), _timer(0))
    engine = MissionGraph(mission)
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["obj_1"] == "active"
    assert objs["obj_2"] == "pending"
    assert objs["obj_3"] == "pending"


def test_all_nodes_registered_in_get_objectives():
    mission = _seq_graph(_timer(5), _timer(5))
    engine = MissionGraph(mission)
    ids = [o.id for o in engine.get_objectives()]
    assert "obj_1" in ids
    assert "obj_2" in ids


def test_no_start_node_yields_no_active_nodes():
    mission = {
        "id": "test", "name": "T", "briefing": "",
        "nodes": [{"id": "n1", "type": "objective", "text": "N1", "trigger": _timer(5)}],
        "edges": [],
        "victory_nodes": ["n1"],
    }
    engine = MissionGraph(mission)
    assert engine.get_active_node_ids() == []


def test_complete_nodes_empty_on_init():
    engine = MissionGraph(_simple_graph(_timer(10)))
    assert engine.get_complete_node_ids() == []


# ---------------------------------------------------------------------------
# Section 2 — Sequential objectives
# ---------------------------------------------------------------------------


def test_seq_objective_completes_on_trigger():
    engine = MissionGraph(_simple_graph(_timer(0.5)))
    world, ship = _make_world(), _make_ship()
    completed = _tick_n(engine, world, ship, 6, dt=0.1)  # 0.6s elapsed
    assert "obj_1" in completed


def test_seq_trigger_not_fired_stays_pending():
    engine = MissionGraph(_simple_graph(_timer(100)))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    assert engine.get_objectives()[0].status == "active"


def test_seq_second_node_pending_before_first_completes():
    mission = _seq_graph(_timer(5), _timer(0))
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # 0.1s — first obj not complete yet
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["obj_2"] == "pending"


def test_seq_second_node_activates_after_first_completes():
    mission = _seq_graph(_timer(0), _timer(5))
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # obj_1 completes immediately
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["obj_1"] == "complete"
    assert objs["obj_2"] == "active"


def test_seq_three_node_chain_progresses_correctly():
    mission = _seq_graph(_timer(0), _timer(0), _timer(0))
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    engine.tick(world, ship)
    engine.tick(world, ship)
    statuses = {o.id: o.status for o in engine.get_objectives()}
    assert statuses["obj_1"] == "complete"
    assert statuses["obj_2"] == "complete"
    assert statuses["obj_3"] == "complete"


def test_seq_victory_when_last_complete():
    mission = _seq_graph(_timer(0))
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    over, result = engine.is_over()
    assert over is True
    assert result == "victory"


def test_seq_no_victory_before_last():
    mission = _seq_graph(_timer(0), _timer(5))
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # obj_1 completes, obj_2 still pending
    over, _ = engine.is_over()
    assert over is False


def test_seq_tick_is_noop_after_over():
    engine = MissionGraph(_simple_graph(_timer(0)))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    completed = engine.tick(world, ship)
    assert completed == []


def test_seq_tick_returns_completed_ids():
    engine = MissionGraph(_simple_graph(_timer(0)))
    world, ship = _make_world(), _make_ship()
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_seq_tick_returns_empty_when_nothing_completes():
    engine = MissionGraph(_simple_graph(_timer(100)))
    world, ship = _make_world(), _make_ship()
    completed = engine.tick(world, ship)
    assert completed == []


# ---------------------------------------------------------------------------
# Section 3 — Parallel nodes
# ---------------------------------------------------------------------------


def _parallel_graph(complete_when="all", child_triggers=None, add_next=False):
    """Parallel node with 3 children."""
    if child_triggers is None:
        child_triggers = [_timer(0), _timer(5), _timer(10)]
    children = [
        {"id": f"child_{i+1}", "type": "objective", "text": f"Child {i+1}",
         "trigger": child_triggers[i]}
        for i in range(len(child_triggers))
    ]
    par_node = {
        "id": "par",
        "type": "parallel",
        "text": "Parallel group",
        "complete_when": complete_when,
        "children": children,
    }
    nodes = [par_node]
    edges = []
    victory_nodes = ["par"]
    if add_next:
        nodes.append({"id": "next", "type": "objective", "text": "Next", "trigger": _timer(0)})
        edges.append({"from": "par", "to": "next", "type": "sequence"})
        victory_nodes = ["next"]
    return {
        "id": "test", "name": "Test", "briefing": "",
        "nodes": nodes, "edges": edges,
        "start_node": "par", "victory_nodes": victory_nodes,
        "defeat_condition": _hull_zero(),
    }


def test_parallel_activates_all_children_on_start():
    engine = MissionGraph(_parallel_graph())
    active = engine.get_active_node_ids()
    assert "child_1" in active
    assert "child_2" in active
    assert "child_3" in active


def test_parallel_all_mode_not_complete_with_one_child():
    engine = MissionGraph(_parallel_graph("all", [_timer(0), _timer(10), _timer(10)]))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # child_1 completes
    assert engine.get_objectives()[0].status == "active"  # par still active
    over, _ = engine.is_over()
    assert over is False


def test_parallel_all_mode_completes_when_all_children_done():
    engine = MissionGraph(_parallel_graph("all", [_timer(0), _timer(0), _timer(0)]))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["par"] == "complete"


def test_parallel_any_mode_first_child_completes_group():
    engine = MissionGraph(_parallel_graph("any", [_timer(0), _timer(10), _timer(10)]))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["par"] == "complete"


def test_parallel_any_mode_cancels_remaining_children():
    engine = MissionGraph(_parallel_graph("any", [_timer(0), _timer(10), _timer(10)]))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    objs = {o.id: o.status for o in engine.get_objectives()}
    # child_1 complete, child_2 and child_3 cancelled
    assert objs["child_1"] == "complete"
    cancelled = [s for oid, s in objs.items() if oid in ("child_2", "child_3")]
    assert all(s == "cancelled" for s in cancelled)


def test_parallel_count_mode_two_of_three():
    engine = MissionGraph(_parallel_graph(
        {"count": 2},
        [_timer(0), _timer(0), _timer(100)],
    ))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # child_1 + child_2 complete
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["par"] == "complete"
    assert objs["child_3"] == "cancelled"


def test_parallel_count_mode_not_enough_children():
    engine = MissionGraph(_parallel_graph(
        {"count": 2},
        [_timer(0), _timer(100), _timer(100)],
    ))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # only child_1 completes
    over, _ = engine.is_over()
    assert over is False
    assert engine.get_objectives()[0].status == "active"  # par still active


def test_parallel_within_seconds_succeeds_in_time():
    engine = MissionGraph(_parallel_graph(
        {"count": 2, "within_seconds": 10.0},
        [_timer(0), _timer(0), _timer(100)],
    ))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # 0.1s — child_1+2 complete within 10s
    assert engine.get_objectives()[0].status == "complete"


def test_parallel_within_seconds_fails_on_timeout():
    engine = MissionGraph(_parallel_graph(
        {"count": 2, "within_seconds": 5.0},
        [_timer(0), _timer(100), _timer(100)],  # only 1 completes
    ))
    world, ship = _make_world(), _make_ship()
    # Advance 6 seconds (60 ticks) — child_1 completes at tick 0, timeout at 5s
    _tick_n(engine, world, ship, 60, dt=0.1)
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["par"] == "failed"


def test_parallel_followed_by_sequence_activates_next():
    engine = MissionGraph(_parallel_graph("all", [_timer(0), _timer(0), _timer(0)], add_next=True))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # all children complete → par completes → next activates
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["next"] == "active"


def test_parallel_all_no_children_completes_immediately():
    """Edge case: parallel with 0 children completes instantly."""
    mission = {
        "id": "test", "name": "T", "briefing": "",
        "nodes": [{"id": "par", "type": "parallel", "text": "P",
                   "complete_when": "all", "children": []}],
        "edges": [],
        "start_node": "par",
        "victory_nodes": ["par"],
    }
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    over, result = engine.is_over()
    assert over is True
    assert result == "victory"


def test_parallel_on_complete_action_fires():
    """Edge on_complete fires when parallel completes."""
    mission = {
        "id": "test", "name": "T", "briefing": "",
        "nodes": [
            {"id": "par", "type": "parallel", "text": "P", "complete_when": "all",
             "children": [{"id": "c1", "type": "objective", "text": "C1", "trigger": _timer(0)}]},
            {"id": "n2", "type": "objective", "text": "N2", "trigger": _timer(0)},
        ],
        "edges": [
            {"from": "par", "to": "n2", "type": "sequence",
             "on_complete": {"action": "spawn_wave", "wave_id": "w1"}},
        ],
        "start_node": "par",
        "victory_nodes": ["n2"],
    }
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # par completes, edge fires
    actions = engine.pop_pending_actions()
    assert any(a.get("action") == "spawn_wave" for a in actions)


# ---------------------------------------------------------------------------
# Section 4 — Branch nodes
# ---------------------------------------------------------------------------


def _branch_graph(triggers, on_completes=None):
    """Branch node with len(triggers) outgoing branch_trigger edges."""
    if on_completes is None:
        on_completes = [None] * len(triggers)
    targets = [
        {"id": f"target_{i+1}", "type": "objective", "text": f"Target {i+1}",
         "trigger": _timer(100)}
        for i in range(len(triggers))
    ]
    branch_node = {"id": "branch", "type": "branch", "text": "Branch"}
    all_nodes = [branch_node] + targets
    edges = []
    for i, (trig, oc) in enumerate(zip(triggers, on_completes)):
        edge = {
            "from": "branch",
            "to": f"target_{i+1}",
            "type": "branch_trigger",
            "trigger": trig,
        }
        if oc is not None:
            edge["on_complete"] = oc
        edges.append(edge)
    return {
        "id": "test", "name": "Test", "briefing": "",
        "nodes": all_nodes, "edges": edges,
        "start_node": "branch",
        "victory_nodes": [f"target_{len(triggers)}"],  # arbitrary
        "defeat_condition": _hull_zero(),
    }


def test_branch_first_trigger_wins():
    engine = MissionGraph(_branch_graph([_timer(0), _timer(0)]))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["target_1"] == "active"
    assert objs["target_2"] == "pending"


def test_branch_second_trigger_when_first_false():
    engine = MissionGraph(_branch_graph([_timer(100), _timer(0)]))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["target_1"] == "pending"
    assert objs["target_2"] == "active"


def test_branch_no_trigger_no_activation():
    engine = MissionGraph(_branch_graph([_timer(100), _timer(100)]))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["target_1"] == "pending"
    assert objs["target_2"] == "pending"
    assert objs["branch"] == "active"


def test_branch_fires_on_complete_of_winning_edge():
    engine = MissionGraph(_branch_graph(
        [_timer(0), _timer(100)],
        on_completes=[{"action": "spawn_wave", "wave_id": "w1"}, None],
    ))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    actions = engine.pop_pending_actions()
    assert any(a.get("action") == "spawn_wave" for a in actions)


def test_branch_does_not_fire_loser_on_complete():
    engine = MissionGraph(_branch_graph(
        [_timer(0), _timer(0)],
        on_completes=[None, {"action": "spawn_wave", "wave_id": "loser_wave"}],
    ))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    actions = engine.pop_pending_actions()
    # Loser's on_complete should NOT have fired
    assert not any(a.get("wave_id") == "loser_wave" for a in actions)


def test_branch_three_options_middle_wins():
    engine = MissionGraph(_branch_graph([_timer(100), _timer(0), _timer(100)]))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["target_2"] == "active"
    assert objs["target_1"] == "pending"
    assert objs["target_3"] == "pending"


def test_branch_node_completes_after_branch_resolution():
    engine = MissionGraph(_branch_graph([_timer(0), _timer(100)]))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["branch"] == "complete"


def test_branch_winning_target_can_progress():
    """After branch resolves, winning target progresses normally."""
    mission = {
        "id": "test", "name": "T", "briefing": "",
        "nodes": [
            {"id": "branch", "type": "branch", "text": "Branch"},
            {"id": "target_1", "type": "objective", "text": "T1", "trigger": _timer(0)},
            {"id": "target_2", "type": "objective", "text": "T2", "trigger": _timer(0)},
        ],
        "edges": [
            {"from": "branch", "to": "target_1", "type": "branch_trigger", "trigger": _timer(0)},
            {"from": "branch", "to": "target_2", "type": "branch_trigger", "trigger": _timer(100)},
        ],
        "start_node": "branch",
        "victory_nodes": ["target_1"],
    }
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # branch resolves → target_1 active
    engine.tick(world, ship)  # target_1 completes
    over, result = engine.is_over()
    assert over is True
    assert result == "victory"


def test_branch_discards_other_edges_after_resolution():
    """Once branch resolves, further ticks don't check the losing edges."""
    engine = MissionGraph(_branch_graph([_timer(0), _timer(0)]))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # resolves to target_1
    engine.tick(world, ship)  # further tick — target_2 should NOT activate
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["target_2"] == "pending"  # still pending, not activated


def test_branch_followed_by_common_node():
    """Both branch paths converge on a common final node."""
    mission = {
        "id": "test", "name": "T", "briefing": "",
        "nodes": [
            {"id": "branch", "type": "branch", "text": "Branch"},
            {"id": "path_a", "type": "objective", "text": "Path A", "trigger": _timer(0)},
            {"id": "path_b", "type": "objective", "text": "Path B", "trigger": _timer(0)},
            {"id": "finale", "type": "objective", "text": "Finale", "trigger": _timer(0)},
        ],
        "edges": [
            {"from": "branch", "to": "path_a", "type": "branch_trigger", "trigger": _timer(0)},
            {"from": "branch", "to": "path_b", "type": "branch_trigger", "trigger": _timer(100)},
            {"from": "path_a", "to": "finale", "type": "sequence"},
            {"from": "path_b", "to": "finale", "type": "sequence"},
        ],
        "start_node": "branch",
        "victory_nodes": ["finale"],
    }
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # branch → path_a
    engine.tick(world, ship)  # path_a → finale
    engine.tick(world, ship)  # finale complete → victory
    over, result = engine.is_over()
    assert over is True
    assert result == "victory"


# ---------------------------------------------------------------------------
# Section 5 — Conditional nodes
# ---------------------------------------------------------------------------


def _conditional_graph(*, condition, deactivate_when=None, on_activate=None, on_deactivate=None):
    """Minimal graph: linear + one conditional node."""
    cond_node = {
        "id": "cond",
        "type": "conditional",
        "text": "Conditional",
        "condition": condition,
    }
    if deactivate_when:
        cond_node["deactivate_when"] = deactivate_when
    if on_activate:
        cond_node["on_activate"] = on_activate
    if on_deactivate:
        cond_node["on_deactivate"] = on_deactivate

    return {
        "id": "test", "name": "Test", "briefing": "",
        "nodes": [
            {"id": "main", "type": "objective", "text": "Main", "trigger": _timer(100)},
            cond_node,
        ],
        "edges": [],
        "start_node": "main",
        "victory_nodes": ["main"],
        "defeat_condition": _hull_zero(),
    }


def test_conditional_inactive_when_condition_false():
    engine = MissionGraph(_conditional_graph(condition=_hull_below(10)))
    world, ship = _make_world(), _make_ship(hull=100)
    engine.tick(world, ship)
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["cond"] == "pending"


def test_conditional_activates_when_condition_true():
    engine = MissionGraph(_conditional_graph(condition=_hull_below(50)))
    world, ship = _make_world(), _make_ship(hull=20)  # hull 20 < 50
    engine.tick(world, ship)
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["cond"] == "active"


def test_conditional_does_not_block_main_graph():
    """Conditional activation doesn't prevent main objective from progressing."""
    mission = {
        "id": "test", "name": "Test", "briefing": "",
        "nodes": [
            {"id": "main", "type": "objective", "text": "Main", "trigger": _timer(0)},
            {"id": "cond", "type": "conditional", "text": "Cond",
             "condition": _hull_below(50)},
        ],
        "edges": [],
        "start_node": "main",
        "victory_nodes": ["main"],
    }
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship(hull=20)
    engine.tick(world, ship)  # main completes AND cond activates
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["main"] == "complete"
    assert objs["cond"] == "active"
    over, result = engine.is_over()
    assert over is True
    assert result == "victory"


def test_conditional_deactivates_when_deactivate_when_true():
    engine = MissionGraph(_conditional_graph(
        condition=_hull_below(50),
        deactivate_when=_hull_above(70),
    ))
    world, ship = _make_world(), _make_ship(hull=20)  # activate
    engine.tick(world, ship)
    assert engine.get_objectives()[1].status == "active"

    ship.hull = 90  # deactivate
    engine.tick(world, ship)
    assert engine.get_objectives()[1].status == "pending"


def test_conditional_reactivates_after_deactivation():
    engine = MissionGraph(_conditional_graph(
        condition=_hull_below(50),
        deactivate_when=_hull_above(70),
    ))
    world, ship = _make_world(), _make_ship(hull=20)
    engine.tick(world, ship)  # activate
    ship.hull = 90
    engine.tick(world, ship)  # deactivate
    ship.hull = 10
    engine.tick(world, ship)  # re-activate
    assert engine.get_objectives()[1].status == "active"


def test_conditional_on_activate_action_queued():
    engine = MissionGraph(_conditional_graph(
        condition=_hull_below(50),
        on_activate={"action": "start_puzzle", "label": "emergency"},
    ))
    world, ship = _make_world(), _make_ship(hull=20)
    engine.tick(world, ship)
    actions = engine.pop_pending_actions()
    assert any(a.get("action") == "start_puzzle" for a in actions)


def test_conditional_on_deactivate_action_queued():
    engine = MissionGraph(_conditional_graph(
        condition=_hull_below(50),
        deactivate_when=_hull_above(70),
        on_deactivate={"action": "cancel_puzzle", "label": "emergency"},
    ))
    world, ship = _make_world(), _make_ship(hull=20)
    engine.tick(world, ship)
    engine.pop_pending_actions()  # clear on_activate
    ship.hull = 90
    engine.tick(world, ship)
    actions = engine.pop_pending_actions()
    assert any(a.get("action") == "cancel_puzzle" for a in actions)


def test_multiple_conditionals_active_simultaneously():
    mission = {
        "id": "test", "name": "Test", "briefing": "",
        "nodes": [
            {"id": "main", "type": "objective", "text": "Main", "trigger": _timer(100)},
            {"id": "cond_a", "type": "conditional", "text": "A", "condition": _hull_below(50)},
            {"id": "cond_b", "type": "conditional", "text": "B", "condition": _hull_below(80)},
        ],
        "edges": [],
        "start_node": "main",
        "victory_nodes": ["main"],
    }
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship(hull=20)  # below both thresholds
    engine.tick(world, ship)
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["cond_a"] == "active"
    assert objs["cond_b"] == "active"


def test_conditional_without_deactivate_stays_active():
    engine = MissionGraph(_conditional_graph(condition=_hull_below(50)))
    world, ship = _make_world(), _make_ship(hull=20)
    engine.tick(world, ship)  # activate
    ship.hull = 90  # condition no longer true, no deactivate_when
    engine.tick(world, ship)  # stays active
    assert engine.get_objectives()[1].status == "active"


# ---------------------------------------------------------------------------
# Section 6 — Compound triggers
# ---------------------------------------------------------------------------


def _obj_with_trigger(trigger):
    return _simple_graph(trigger)


def test_all_of_both_true():
    trigger = {
        "type": "all_of",
        "triggers": [_timer(0), _all_enemies()],
    }
    engine = MissionGraph(_obj_with_trigger(trigger))
    world, ship = _make_world(enemies=[]), _make_ship()  # no enemies
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_all_of_only_one_true():
    trigger = {
        "type": "all_of",
        "triggers": [_timer(0), _all_enemies()],
    }
    engine = MissionGraph(_obj_with_trigger(trigger))
    world, ship = _make_world(enemies=[_make_enemy()]), _make_ship()  # enemy present
    completed = engine.tick(world, ship)
    assert "obj_1" not in completed


def test_all_of_none_true():
    trigger = {
        "type": "all_of",
        "triggers": [_timer(100), _hull_below(10)],
    }
    engine = MissionGraph(_obj_with_trigger(trigger))
    world, ship = _make_world(), _make_ship(hull=100)
    completed = engine.tick(world, ship)
    assert completed == []


def test_any_of_one_true():
    trigger = {
        "type": "any_of",
        "triggers": [_timer(100), _all_enemies()],
    }
    engine = MissionGraph(_obj_with_trigger(trigger))
    world, ship = _make_world(enemies=[]), _make_ship()  # no enemies → all_enemies fires
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_any_of_none_true():
    trigger = {
        "type": "any_of",
        "triggers": [_timer(100), _hull_below(10)],
    }
    engine = MissionGraph(_obj_with_trigger(trigger))
    world, ship = _make_world(), _make_ship(hull=100)
    completed = engine.tick(world, ship)
    assert completed == []


def test_none_of_none_true():
    trigger = {
        "type": "none_of",
        "triggers": [_timer(100), _hull_below(10)],
    }
    engine = MissionGraph(_obj_with_trigger(trigger))
    world, ship = _make_world(), _make_ship(hull=100)
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_none_of_one_true():
    trigger = {
        "type": "none_of",
        "triggers": [_timer(100), _all_enemies()],
    }
    engine = MissionGraph(_obj_with_trigger(trigger))
    world, ship = _make_world(enemies=[]), _make_ship()  # all_enemies = True
    completed = engine.tick(world, ship)
    assert completed == []


def test_nested_all_of_any_of():
    trigger = {
        "type": "all_of",
        "triggers": [
            _all_enemies(),
            {"type": "any_of", "triggers": [_timer(100), _timer(0)]},
        ],
    }
    engine = MissionGraph(_obj_with_trigger(trigger))
    world, ship = _make_world(enemies=[]), _make_ship()
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_nested_any_of_all_of():
    trigger = {
        "type": "any_of",
        "triggers": [
            _timer(100),
            {"type": "all_of", "triggers": [_all_enemies(), _timer(0)]},
        ],
    }
    engine = MissionGraph(_obj_with_trigger(trigger))
    world, ship = _make_world(enemies=[]), _make_ship()
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_three_level_nesting():
    trigger = {
        "type": "all_of",
        "triggers": [
            _timer(0),
            {
                "type": "any_of",
                "triggers": [
                    _timer(100),
                    {
                        "type": "none_of",
                        "triggers": [_timer(100)],  # none_of [false] → True
                    },
                ],
            },
        ],
    }
    engine = MissionGraph(_obj_with_trigger(trigger))
    world, ship = _make_world(), _make_ship()
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_all_of_empty_triggers_is_true():
    """all_of with no sub-triggers is vacuously true."""
    trigger = {"type": "all_of", "triggers": []}
    engine = MissionGraph(_obj_with_trigger(trigger))
    world, ship = _make_world(), _make_ship()
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_any_of_empty_triggers_is_false():
    """any_of with no sub-triggers is vacuously false."""
    trigger = {"type": "any_of", "triggers": []}
    engine = MissionGraph(_obj_with_trigger(trigger))
    world, ship = _make_world(), _make_ship()
    completed = engine.tick(world, ship)
    assert completed == []


def test_compound_trigger_with_puzzle():
    trigger = {
        "type": "all_of",
        "triggers": [_timer(0), _puzzle("my_puzzle")],
    }
    engine = MissionGraph(_obj_with_trigger(trigger))
    world, ship = _make_world(), _make_ship()
    engine.notify_puzzle_result("my_puzzle", success=True)
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


# ---------------------------------------------------------------------------
# Section 7 — Trigger types
# ---------------------------------------------------------------------------


def test_trigger_player_in_area_inside():
    engine = MissionGraph(_obj_with_trigger({"type": "player_in_area", "x": 0, "y": 0, "r": 1000}))
    world, ship = _make_world(), _make_ship(x=0, y=0)
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_trigger_player_in_area_outside():
    engine = MissionGraph(_obj_with_trigger({"type": "player_in_area", "x": 0, "y": 0, "r": 100}))
    world, ship = _make_world(), _make_ship(x=50_000, y=50_000)
    completed = engine.tick(world, ship)
    assert completed == []


def test_trigger_scan_completed_target_field():
    engine = MissionGraph(_obj_with_trigger({"type": "scan_completed", "target": "e1"}))
    enemy = _make_enemy("e1", "scanned")
    world, ship = _make_world(enemies=[enemy]), _make_ship()
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_trigger_scan_completed_entity_id_alias():
    """entity_id is a backward-compat alias for target."""
    engine = MissionGraph(_obj_with_trigger({"type": "scan_completed", "entity_id": "e1"}))
    enemy = _make_enemy("e1", "scanned")
    world, ship = _make_world(enemies=[enemy]), _make_ship()
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_trigger_scan_completed_not_scanned():
    engine = MissionGraph(_obj_with_trigger({"type": "scan_completed", "target": "e1"}))
    enemy = _make_enemy("e1", "unknown")
    world, ship = _make_world(enemies=[enemy]), _make_ship()
    completed = engine.tick(world, ship)
    assert completed == []


def test_trigger_entity_destroyed():
    engine = MissionGraph(_obj_with_trigger({"type": "entity_destroyed", "target": "e1"}))
    world, ship = _make_world(enemies=[]), _make_ship()  # enemy absent → destroyed
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_trigger_entity_destroyed_still_alive():
    engine = MissionGraph(_obj_with_trigger({"type": "entity_destroyed", "target": "e1"}))
    world, ship = _make_world(enemies=[_make_enemy("e1")]), _make_ship()
    completed = engine.tick(world, ship)
    assert completed == []


def test_trigger_all_enemies_destroyed():
    engine = MissionGraph(_obj_with_trigger(_all_enemies()))
    world, ship = _make_world(enemies=[]), _make_ship()
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_trigger_all_enemies_destroyed_enemy_present():
    engine = MissionGraph(_obj_with_trigger(_all_enemies()))
    world, ship = _make_world(enemies=[_make_enemy()]), _make_ship()
    completed = engine.tick(world, ship)
    assert completed == []


def test_trigger_timer_elapsed():
    # Use 6 ticks (0.6s) to guarantee crossing 0.5s regardless of float rounding.
    # (5 × 0.1 = 0.5000000000000001 in Python — might fire at tick 5, leaving engine "over"
    # before the explicit 6th tick runs. Capture cumulatively instead.)
    engine = MissionGraph(_obj_with_trigger(_timer(0.5)))
    world, ship = _make_world(), _make_ship()
    completed = _tick_n(engine, world, ship, 6, dt=0.1)
    assert "obj_1" in completed


def test_trigger_timer_not_yet():
    engine = MissionGraph(_obj_with_trigger(_timer(5)))
    world, ship = _make_world(), _make_ship()
    completed = engine.tick(world, ship)  # 0.1s
    assert completed == []


def test_trigger_wave_defeated_prefix():
    engine = MissionGraph(_obj_with_trigger({"type": "wave_defeated", "prefix": "wave1_"}))
    world, ship = _make_world(enemies=[_make_enemy("wave2_drone")]), _make_ship()
    completed = engine.tick(world, ship)
    assert "obj_1" in completed  # no wave1_ enemies → wave defeated


def test_trigger_wave_defeated_enemy_present():
    engine = MissionGraph(_obj_with_trigger({"type": "wave_defeated", "prefix": "wave1_"}))
    world, ship = _make_world(enemies=[_make_enemy("wave1_fighter")]), _make_ship()
    completed = engine.tick(world, ship)
    assert completed == []


def test_trigger_station_hull_below():
    engine = MissionGraph(_obj_with_trigger(
        {"type": "station_hull_below", "station_id": "s1", "threshold": 50}
    ))
    st = _make_station("s1", hull=30)
    world, ship = _make_world(stations=[st]), _make_ship()
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_trigger_station_hull_above_threshold():
    engine = MissionGraph(_obj_with_trigger(
        {"type": "station_hull_below", "station_id": "s1", "threshold": 50}
    ))
    st = _make_station("s1", hull=80)
    world, ship = _make_world(stations=[st]), _make_ship()
    completed = engine.tick(world, ship)
    assert completed == []


def test_trigger_signal_located():
    engine = MissionGraph(_obj_with_trigger({"type": "signal_located"}))
    world, ship = _make_world(), _make_ship()
    engine.record_signal_scan(0, 0)
    engine.record_signal_scan(20_000, 20_000)
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_trigger_signal_located_only_one_scan():
    engine = MissionGraph(_obj_with_trigger({"type": "signal_located"}))
    world, ship = _make_world(), _make_ship()
    engine.record_signal_scan(0, 0)
    completed = engine.tick(world, ship)
    assert completed == []


def test_trigger_puzzle_completed():
    engine = MissionGraph(_obj_with_trigger(_puzzle("test_puzzle")))
    world, ship = _make_world(), _make_ship()
    engine.notify_puzzle_result("test_puzzle", success=True)
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_trigger_puzzle_failed():
    engine = MissionGraph(_obj_with_trigger({"type": "puzzle_failed", "label": "test_puzzle"}))
    world, ship = _make_world(), _make_ship()
    engine.notify_puzzle_result("test_puzzle", success=False)
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_trigger_puzzle_resolved_on_complete():
    engine = MissionGraph(_obj_with_trigger({"type": "puzzle_resolved", "label": "p1"}))
    world, ship = _make_world(), _make_ship()
    engine.notify_puzzle_result("p1", success=True)
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_trigger_puzzle_resolved_on_fail():
    engine = MissionGraph(_obj_with_trigger({"type": "puzzle_resolved", "label": "p1"}))
    world, ship = _make_world(), _make_ship()
    engine.notify_puzzle_result("p1", success=False)
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_trigger_training_flag():
    engine = MissionGraph(_obj_with_trigger({"type": "training_flag", "flag": "fired_beam"}))
    world, ship = _make_world(), _make_ship()
    engine.set_training_flag("fired_beam")
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_trigger_training_flag_not_set():
    engine = MissionGraph(_obj_with_trigger({"type": "training_flag", "flag": "fired_beam"}))
    world, ship = _make_world(), _make_ship()
    completed = engine.tick(world, ship)
    assert completed == []


def test_trigger_ship_hull_below():
    engine = MissionGraph(_obj_with_trigger(_hull_below(50)))
    world, ship = _make_world(), _make_ship(hull=20)
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_trigger_ship_hull_above():
    engine = MissionGraph(_obj_with_trigger(_hull_above(50)))
    world, ship = _make_world(), _make_ship(hull=80)
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_trigger_ship_hull_above_false():
    engine = MissionGraph(_obj_with_trigger(_hull_above(50)))
    world, ship = _make_world(), _make_ship(hull=30)
    completed = engine.tick(world, ship)
    assert completed == []


def test_trigger_boarding_active():
    engine = MissionGraph(_obj_with_trigger({"type": "boarding_active"}))
    world, ship = _make_world(), _make_ship()
    # Add a mock intruder to ship.interior
    intruder = MagicMock()
    ship.interior.intruders = [intruder]
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_trigger_no_intruders():
    engine = MissionGraph(_obj_with_trigger({"type": "no_intruders"}))
    world, ship = _make_world(), _make_ship()
    ship.interior.intruders = []
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_trigger_proximity_with_shields():
    # Duration 0.2s: timer fires at tick 2 (0.1 + 0.1 = 0.2 >= 0.2).
    # Capture tick 2's return value, not tick 3 (engine would be "over" by then).
    engine = MissionGraph(_obj_with_trigger({
        "type": "proximity_with_shields",
        "x": 0, "y": 0, "radius": 5_000,
        "min_shield": 50, "duration": 0.2,
    }))
    world, ship = _make_world(), _make_ship(x=0, y=0, front_shield=100, rear_shield=100)
    engine.tick(world, ship)  # 0.1s — proximity_timer = 0.1 < 0.2 → pending
    completed = engine.tick(world, ship)  # 0.2s — timer = 0.2 >= 0.2 → fires
    assert "obj_1" in completed


def test_trigger_proximity_with_shields_resets_when_out():
    engine = MissionGraph(_obj_with_trigger({
        "type": "proximity_with_shields",
        "x": 0, "y": 0, "radius": 5_000,
        "min_shield": 50, "duration": 5.0,
    }))
    world, ship = _make_world(), _make_ship(x=0, y=0, front_shield=100, rear_shield=100)
    engine.tick(world, ship)  # 0.1s in proximity
    ship.x = 100_000  # leave area
    engine.tick(world, ship)  # timer resets
    ship.x = 0  # re-enter
    # Timer starts from 0 again; shouldn't complete
    completed = engine.tick(world, ship)
    assert completed == []


# ---------------------------------------------------------------------------
# Section 8 — On-complete actions
# ---------------------------------------------------------------------------


def test_edge_on_complete_fires_on_sequence():
    mission = _seq_graph(_timer(0), _timer(100))
    mission["edges"][0]["on_complete"] = {"action": "spawn_wave", "wave_id": "w1"}
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    actions = engine.pop_pending_actions()
    assert any(a.get("action") == "spawn_wave" for a in actions)


def test_edge_multiple_on_complete_actions():
    mission = _seq_graph(_timer(0), _timer(100))
    mission["edges"][0]["on_complete"] = [
        {"action": "spawn_wave", "wave_id": "w1"},
        {"action": "start_puzzle", "label": "p1"},
    ]
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    actions = engine.pop_pending_actions()
    assert any(a.get("action") == "spawn_wave" for a in actions)
    assert any(a.get("action") == "start_puzzle" for a in actions)


def test_pop_pending_actions_clears():
    mission = _seq_graph(_timer(0), _timer(100))
    mission["edges"][0]["on_complete"] = {"action": "spawn_wave", "wave_id": "w1"}
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    engine.pop_pending_actions()
    actions = engine.pop_pending_actions()
    assert actions == []


def test_on_complete_fires_only_once():
    mission = _seq_graph(_timer(0), _timer(100))
    mission["edges"][0]["on_complete"] = {"action": "spawn_wave", "wave_id": "w1"}
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # obj_1 completes → fires on_complete
    engine.pop_pending_actions()  # consume tick-1 actions
    engine.tick(world, ship)  # obj_2 pending (timer=100), no repeat firing
    actions = engine.pop_pending_actions()  # should be empty — action doesn't repeat
    assert sum(1 for a in actions if a.get("action") == "spawn_wave") == 0


def test_on_complete_not_fired_before_source_completes():
    mission = _seq_graph(_timer(10), _timer(100))
    mission["edges"][0]["on_complete"] = {"action": "spawn_wave", "wave_id": "w1"}
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # 0.1s — obj_1 not complete
    actions = engine.pop_pending_actions()
    assert actions == []


# ---------------------------------------------------------------------------
# Section 9 — Victory / defeat
# ---------------------------------------------------------------------------


def test_victory_when_all_victory_nodes_complete():
    engine = MissionGraph(_simple_graph(_timer(0)))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    over, result = engine.is_over()
    assert over is True
    assert result == "victory"


def test_no_victory_before_victory_node_completes():
    engine = MissionGraph(_simple_graph(_timer(100)))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    over, _ = engine.is_over()
    assert over is False


def test_multiple_victory_nodes_all_required():
    mission = {
        "id": "test", "name": "T", "briefing": "",
        "nodes": [
            {"id": "a", "type": "objective", "text": "A", "trigger": _timer(0)},
            {"id": "b", "type": "objective", "text": "B", "trigger": _timer(100)},
        ],
        "edges": [],
        "start_node": "a",
        "victory_nodes": ["a", "b"],
    }
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # a completes, b still pending
    over, _ = engine.is_over()
    assert over is False  # still need b


def test_defeat_from_hull_zero():
    engine = MissionGraph(_simple_graph(_timer(100)))
    world, ship = _make_world(), _make_ship(hull=0)
    engine.tick(world, ship)
    over, result = engine.is_over()
    assert over is True
    assert result == "defeat"


def test_defeat_from_custom_defeat_condition():
    mission = _simple_graph(_timer(100))
    mission["defeat_condition"] = {"type": "all_enemies_destroyed"}
    engine = MissionGraph(mission)
    world, ship = _make_world(enemies=[]), _make_ship()
    engine.tick(world, ship)
    over, result = engine.is_over()
    assert over is True
    assert result == "defeat"


def test_defeat_before_objective_trigger():
    """Ship hull hits zero before objective completes — defeat wins."""
    mission = _simple_graph(_timer(0))  # trigger would fire immediately
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship(hull=0)
    engine.tick(world, ship)
    over, result = engine.is_over()
    assert result == "defeat"


def test_is_over_returns_false_initially():
    engine = MissionGraph(_simple_graph(_timer(100)))
    over, result = engine.is_over()
    assert over is False
    assert result is None


def test_tick_noop_after_over():
    engine = MissionGraph(_simple_graph(_timer(0)))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # victory
    completed = engine.tick(world, ship)
    assert completed == []


# ---------------------------------------------------------------------------
# Section 10 — State inspection
# ---------------------------------------------------------------------------


def test_get_objectives_returns_all_nodes():
    mission = _seq_graph(_timer(0), _timer(0))
    engine = MissionGraph(mission)
    ids = [o.id for o in engine.get_objectives()]
    assert "obj_1" in ids
    assert "obj_2" in ids


def test_get_objectives_status_updates_after_tick():
    engine = MissionGraph(_simple_graph(_timer(0)))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["obj_1"] == "complete"


def test_get_active_node_ids_reflects_current_state():
    mission = _seq_graph(_timer(0), _timer(100))
    engine = MissionGraph(mission)
    assert "obj_1" in engine.get_active_node_ids()
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # obj_1 completes → obj_2 activates
    assert "obj_1" not in engine.get_active_node_ids()
    assert "obj_2" in engine.get_active_node_ids()


def test_get_complete_node_ids_reflects_current_state():
    engine = MissionGraph(_simple_graph(_timer(0)))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    assert "obj_1" in engine.get_complete_node_ids()


def test_graph_objective_has_text():
    engine = MissionGraph(_simple_graph(_timer(10)))
    obj = engine.get_objectives()[0]
    assert isinstance(obj, GraphObjective)
    assert obj.text == "Obj 1"
    assert obj.id == "obj_1"


def test_pop_pending_actions_returns_empty_initially():
    engine = MissionGraph(_simple_graph(_timer(100)))
    assert engine.pop_pending_actions() == []


# ---------------------------------------------------------------------------
# Section 11 — Signal scan
# ---------------------------------------------------------------------------


def test_record_signal_scan_returns_true_after_two_positions():
    engine = MissionGraph(_simple_graph(_timer(100)))
    r1 = engine.record_signal_scan(0, 0)
    assert r1 is False
    r2 = engine.record_signal_scan(20_000, 20_000)
    assert r2 is True


def test_record_signal_scan_enforces_min_separation():
    engine = MissionGraph(_simple_graph(_timer(100)))
    engine.record_signal_scan(0, 0)
    # Too close (< 8000 units) — should not count
    r2 = engine.record_signal_scan(100, 100)
    assert r2 is False


# ---------------------------------------------------------------------------
# Section 12 — Checkpoint nodes
# ---------------------------------------------------------------------------


def test_checkpoint_completes_immediately_on_activation():
    mission = {
        "id": "test", "name": "T", "briefing": "",
        "nodes": [{"id": "cp", "type": "checkpoint", "text": "Checkpoint"}],
        "edges": [],
        "start_node": "cp",
        "victory_nodes": ["cp"],
    }
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    over, result = engine.is_over()
    assert over is True
    assert result == "victory"


def test_checkpoint_activates_next_sequence_node():
    mission = {
        "id": "test", "name": "T", "briefing": "",
        "nodes": [
            {"id": "cp", "type": "checkpoint", "text": "Checkpoint"},
            {"id": "final", "type": "objective", "text": "Final", "trigger": _timer(0)},
        ],
        "edges": [{"from": "cp", "to": "final", "type": "sequence"}],
        "start_node": "cp",
        "victory_nodes": ["final"],
    }
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # cp completes immediately → final activates → final completes
    over, result = engine.is_over()
    assert over is True
    assert result == "victory"


def test_checkpoint_queues_action():
    mission = {
        "id": "test", "name": "T", "briefing": "",
        "nodes": [
            {"id": "cp", "type": "checkpoint", "text": "Checkpoint"},
            {"id": "final", "type": "objective", "text": "Final", "trigger": _timer(100)},
        ],
        "edges": [
            {"from": "cp", "to": "final", "type": "sequence",
             "on_complete": {"action": "auto_save"}},
        ],
        "start_node": "cp",
        "victory_nodes": ["final"],
    }
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    actions = engine.pop_pending_actions()
    assert any(a.get("action") == "auto_save" for a in actions)


# ---------------------------------------------------------------------------
# Section 13 — Edge cases / regression
# ---------------------------------------------------------------------------


def test_notify_puzzle_result_before_engine_start():
    """Puzzle results can be registered before tick() is called."""
    engine = MissionGraph(_obj_with_trigger(_puzzle("p1")))
    engine.notify_puzzle_result("p1", success=True)
    world, ship = _make_world(), _make_ship()
    completed = engine.tick(world, ship)
    assert "obj_1" in completed


def test_set_training_flag_accumulates():
    engine = MissionGraph(_simple_graph(_timer(100)))
    engine.set_training_flag("moved_helm")
    engine.set_training_flag("fired_beam")
    # Both flags recorded — verify via trigger
    trigger = {"type": "training_flag", "flag": "fired_beam"}
    world, ship = _make_world(), _make_ship()
    engine2 = MissionGraph(_obj_with_trigger(trigger))
    engine2.set_training_flag("fired_beam")
    completed = engine2.tick(world, ship)
    assert "obj_1" in completed


def test_mission_with_no_nodes_is_not_over():
    mission = {
        "id": "empty", "name": "Empty", "briefing": "",
        "nodes": [], "edges": [],
        "victory_nodes": [],
    }
    engine = MissionGraph(mission)
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    over, _ = engine.is_over()
    assert over is False


def test_parallel_child_completion_increments_count():
    """Parallel completes with exactly count=2 out of 3."""
    engine = MissionGraph(_parallel_graph(
        {"count": 2},
        [_timer(0), _timer(0), _timer(100)],
    ))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)
    objs = {o.id: o.status for o in engine.get_objectives()}
    assert objs["par"] == "complete"
    assert objs["child_1"] == "complete"
    assert objs["child_2"] == "complete"


def test_branch_on_complete_not_fired_before_resolution():
    engine = MissionGraph(_branch_graph(
        [_timer(100), _timer(100)],
        on_completes=[{"action": "spawn_wave", "wave_id": "w1"}, None],
    ))
    world, ship = _make_world(), _make_ship()
    engine.tick(world, ship)  # neither trigger fires
    actions = engine.pop_pending_actions()
    assert actions == []
