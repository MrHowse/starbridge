"""Tests for message routing completeness.

Programmatically verifies that every registered schema has a route,
every _drain_queue handler has a schema, no duplicates slip through
unintentionally, and station handler modules expose the expected API.
"""
from __future__ import annotations

import inspect
import re

import pytest
from pydantic import BaseModel

from server.models.messages.base import Message, _PAYLOAD_SCHEMAS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_handlers() -> dict:
    """Import and return _HANDLERS from main without triggering side effects
    beyond module init (which has already happened at import time)."""
    from server.main import _HANDLERS
    return _HANDLERS


def _get_drain_queue_msg_types() -> list[str]:
    """Parse _drain_queue source and extract every msg_type == '...' string."""
    import server.game_loop as gl
    source = inspect.getsource(gl._drain_queue)
    # Match both `msg_type == "x.y"` and `msg_type in ("x.y", "a.b")` forms.
    single = re.findall(r'msg_type == "([^"]+)"', source)
    multi = re.findall(r'msg_type in \(([^)]+)\)', source)
    in_types: list[str] = []
    for group in multi:
        in_types.extend(re.findall(r'"([^"]+)"', group))
    return single + in_types


def _get_queue_forwarded_types() -> frozenset[str]:
    """Return the set of message types captain.py forwards to the queue."""
    from server.captain import _QUEUE_FORWARDED_TYPES
    return _QUEUE_FORWARDED_TYPES


# Station handler modules and their expected prefix in _HANDLERS.
_STATION_MODULES = {
    "helm":           "server.helm",
    "engineering":    "server.engineering",
    "weapons":        "server.weapons",
    "science":        "server.science",
    "medical":        "server.medical",
    "security":       "server.security",
    "comms":          "server.comms",
    "captain":        "server.captain",
    "flight_ops":     "server.flight_ops",
    "ew":             "server.ew",
    "operations":     "server.operations",
    "damage_control": "server.damage_control",
    "lobby":          "server.lobby",
}


# ---------------------------------------------------------------------------
# Test 1: Every _PAYLOAD_SCHEMAS entry has a routable prefix
# ---------------------------------------------------------------------------


def test_all_schemas_have_routing():
    """Every key in _PAYLOAD_SCHEMAS must have its prefix present in _HANDLERS."""
    handlers = _get_handlers()
    missing = []
    for msg_type in _PAYLOAD_SCHEMAS:
        prefix = msg_type.split(".")[0]
        if prefix not in handlers:
            missing.append((msg_type, prefix))
    assert not missing, (
        "Schema(s) registered but no _HANDLERS prefix:\n"
        + "\n".join(f"  '{t}' -> missing prefix '{p}'" for t, p in missing)
    )


# ---------------------------------------------------------------------------
# Test 2: Every _drain_queue handler has a _PAYLOAD_SCHEMAS entry
# ---------------------------------------------------------------------------


def test_all_drain_queue_types_have_schemas():
    """Every msg_type string matched in _drain_queue must have a registered schema."""
    types_in_queue = _get_drain_queue_msg_types()
    assert len(types_in_queue) > 0, "_drain_queue appears to handle zero message types"
    missing = [t for t in types_in_queue if t not in _PAYLOAD_SCHEMAS]
    assert not missing, (
        "_drain_queue handles these types with no schema:\n"
        + "\n".join(f"  '{t}'" for t in missing)
    )


# ---------------------------------------------------------------------------
# Test 3: No duplicate message type handling (except explicit forwarding)
# ---------------------------------------------------------------------------


def test_no_unintended_duplicate_handling():
    """No message type should be handled in both a station handler AND
    _drain_queue unless it is explicitly forwarded (like captain.authorize)."""
    queue_types = set(_get_drain_queue_msg_types())
    forwarded = _get_queue_forwarded_types()

    # Types handled directly in station modules (not forwarded to queue).
    # Station handlers that validate-and-queue ALL their messages are fine --
    # we only flag types that are handled with business logic in BOTH places.
    #
    # The "captain" module handles some types directly and forwards others.
    # Forwarded types are expected to appear in _drain_queue.
    # Direct captain types should NOT appear in _drain_queue.
    import server.captain as cap_mod
    cap_source = inspect.getsource(cap_mod.handle_captain_message)
    direct_captain_types = set(re.findall(r'message\.type == "([^"]+)"', cap_source))
    # Remove forwarded types -- those are expected in _drain_queue.
    direct_captain_types -= forwarded

    duplicates = direct_captain_types & queue_types
    assert not duplicates, (
        "These captain types are handled directly AND in _drain_queue:\n"
        + "\n".join(f"  '{t}'" for t in sorted(duplicates))
    )


# ---------------------------------------------------------------------------
# Test 4: All _HANDLERS prefixes correspond to at least one schema entry
# ---------------------------------------------------------------------------


def test_all_handler_prefixes_have_schemas():
    """Every prefix in _HANDLERS must have at least one _PAYLOAD_SCHEMAS entry."""
    handlers = _get_handlers()
    schemas_by_prefix: dict[str, list[str]] = {}
    for msg_type in _PAYLOAD_SCHEMAS:
        prefix = msg_type.split(".")[0]
        schemas_by_prefix.setdefault(prefix, []).append(msg_type)

    missing = []
    for prefix in handlers:
        if prefix not in schemas_by_prefix:
            missing.append(prefix)

    # 'game' is special-cased in main.py (_handle_game_message) but
    # should still have at least game.briefing_launch in _PAYLOAD_SCHEMAS.
    assert not missing, (
        "Handler prefix(es) with no corresponding schema:\n"
        + "\n".join(f"  '{p}'" for p in missing)
    )


# ---------------------------------------------------------------------------
# Test 5: Station handler modules have init() and handle_*_message()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prefix,module_path", list(_STATION_MODULES.items()))
def test_station_handler_has_init(prefix, module_path):
    """Every station handler module must expose an init() function."""
    import importlib
    mod = importlib.import_module(module_path)
    assert hasattr(mod, "init"), f"{module_path} is missing init() function"
    assert callable(mod.init), f"{module_path}.init is not callable"


@pytest.mark.parametrize("prefix,module_path", list(_STATION_MODULES.items()))
def test_station_handler_has_handle_function(prefix, module_path):
    """Every station handler module must expose a handle_<prefix>_message() function."""
    import importlib
    mod = importlib.import_module(module_path)
    handler_name = f"handle_{prefix}_message"
    assert hasattr(mod, handler_name), (
        f"{module_path} is missing {handler_name}() function"
    )
    fn = getattr(mod, handler_name)
    assert callable(fn), f"{module_path}.{handler_name} is not callable"
    assert inspect.iscoroutinefunction(fn), (
        f"{module_path}.{handler_name} must be an async function"
    )


# ---------------------------------------------------------------------------
# Test 6: _PAYLOAD_SCHEMAS values are all Pydantic BaseModel subclasses
# ---------------------------------------------------------------------------


def test_all_schemas_are_pydantic_models():
    """Every value in _PAYLOAD_SCHEMAS must be a class that inherits from BaseModel."""
    non_models = []
    for msg_type, schema_cls in _PAYLOAD_SCHEMAS.items():
        if not (isinstance(schema_cls, type) and issubclass(schema_cls, BaseModel)):
            non_models.append((msg_type, schema_cls))
    assert not non_models, (
        "These _PAYLOAD_SCHEMAS values are not Pydantic BaseModel subclasses:\n"
        + "\n".join(f"  '{t}' -> {cls}" for t, cls in non_models)
    )


# ---------------------------------------------------------------------------
# Test 7: Message.build creates valid messages
# ---------------------------------------------------------------------------


def test_message_build_produces_valid_message():
    """Message.build should create a Message with correct type and payload."""
    msg = Message.build("test.example", {"key": "value"})
    assert isinstance(msg, Message)
    assert msg.type == "test.example"
    assert msg.payload == {"key": "value"}
    assert msg.tick is None
    assert isinstance(msg.timestamp, float)


def test_message_build_with_tick():
    """Message.build with tick should populate the tick field."""
    msg = Message.build("ship.update", {"hull": 100}, tick=42)
    assert msg.tick == 42
    assert msg.type == "ship.update"
    assert msg.payload == {"hull": 100}


def test_message_build_empty_payload():
    """Message.build with no payload should default to empty dict."""
    msg = Message.build("ping.test")
    assert msg.payload == {}


# ---------------------------------------------------------------------------
# Test 8: _drain_queue handles a substantial number of types
# ---------------------------------------------------------------------------


def test_drain_queue_coverage_minimum():
    """_drain_queue should handle at least 30 distinct message types
    (sanity check that our regex extraction is working)."""
    types_in_queue = _get_drain_queue_msg_types()
    unique = set(types_in_queue)
    assert len(unique) >= 30, (
        f"Expected at least 30 message types in _drain_queue, found {len(unique)}: "
        + ", ".join(sorted(unique))
    )


# ---------------------------------------------------------------------------
# Test 9: Forwarded captain types are in both _PAYLOAD_SCHEMAS and _drain_queue
# ---------------------------------------------------------------------------


def test_captain_forwarded_types_are_complete():
    """Every type in captain._QUEUE_FORWARDED_TYPES must exist in both
    _PAYLOAD_SCHEMAS and be handled in _drain_queue."""
    forwarded = _get_queue_forwarded_types()
    queue_types = set(_get_drain_queue_msg_types())
    assert len(forwarded) > 0, "captain._QUEUE_FORWARDED_TYPES is empty"
    for t in forwarded:
        assert t in _PAYLOAD_SCHEMAS, (
            f"Forwarded type '{t}' has no schema in _PAYLOAD_SCHEMAS"
        )
        assert t in queue_types, (
            f"Forwarded type '{t}' is not handled in _drain_queue"
        )


# ---------------------------------------------------------------------------
# Test 10: Schema type strings use valid dot-separated format
# ---------------------------------------------------------------------------


def test_schema_type_format():
    """All _PAYLOAD_SCHEMAS keys must be 'prefix.action' dot-separated strings."""
    invalid = []
    for msg_type in _PAYLOAD_SCHEMAS:
        parts = msg_type.split(".")
        if len(parts) < 2:
            invalid.append(msg_type)
        elif not all(part.isidentifier() or "_" in part for part in parts):
            invalid.append(msg_type)
    assert not invalid, (
        "These schema keys have invalid format (expected 'prefix.action'):\n"
        + "\n".join(f"  '{t}'" for t in invalid)
    )


# ---------------------------------------------------------------------------
# Test 11: No orphaned schemas (every schema is handled somewhere)
# ---------------------------------------------------------------------------


def test_no_orphaned_schemas():
    """Every _PAYLOAD_SCHEMAS entry must be handled either in _drain_queue,
    in a station handler, or in a special handler (_handle_game_message)."""
    queue_types = set(_get_drain_queue_msg_types())

    # Collect types handled directly in station handlers or special handlers.
    # Station handlers that validate-and-queue forward ALL their types to
    # _drain_queue, so those are covered by queue_types.  We also check for
    # types handled directly in captain.py and lobby.py.
    import server.captain as cap_mod
    import server.lobby as lobby_mod

    cap_source = inspect.getsource(cap_mod.handle_captain_message)
    cap_direct = set(re.findall(r'message\.type == "([^"]+)"', cap_source))
    # Also check for types in if-chains inside _QUEUE_FORWARDED_TYPES
    cap_direct |= _get_queue_forwarded_types()

    lobby_source = inspect.getsource(lobby_mod.handle_lobby_message)
    lobby_direct = set(re.findall(r'message\.type == "([^"]+)"', lobby_source))

    # game.briefing_launch is handled by _handle_game_message in main.py.
    game_direct = {"game.briefing_launch"}

    all_handled = queue_types | cap_direct | lobby_direct | game_direct

    orphaned = [t for t in _PAYLOAD_SCHEMAS if t not in all_handled]
    assert not orphaned, (
        "These schemas are registered but never handled anywhere:\n"
        + "\n".join(f"  '{t}'" for t in sorted(orphaned))
    )


# ---------------------------------------------------------------------------
# Test 12: Message.to_json omits None fields
# ---------------------------------------------------------------------------


def test_message_to_json_omits_none():
    """Message.to_json() should omit tick when it is None."""
    msg = Message.build("test.msg", {"a": 1})
    json_str = msg.to_json()
    assert '"tick"' not in json_str, "to_json should omit tick when None"
    assert '"type"' in json_str
    assert '"payload"' in json_str
