"""Tests for WebSocket message routing — end-to-end message paths.

Verifies that every critical message route works:
1. The prefix is registered in _HANDLERS
2. validate_payload returns the correct Pydantic model
3. Messages reach the game loop input queue (or are handled directly)
4. Schema completeness: every msg_type handled in _drain_queue has a _PAYLOAD_SCHEMAS entry

This prevents the class of bug where a new message type is added to one layer
(handler, schema, or _drain_queue) but not the others.
"""
from __future__ import annotations

import asyncio
import re

import pytest

from server.main import _HANDLERS, _queue_forward_handler, input_queue
from server.models.messages import Message, validate_payload
from server.models.messages.base import _PAYLOAD_SCHEMAS

# Payload model imports — used in isinstance checks
from server.models.messages.lobby import LobbyClaimRolePayload
from server.models.messages.helm import HelmSetHeadingPayload, HelmSetThrottlePayload
from server.models.messages.engineering import EngineeringSetPowerPayload, EngineeringSetRepairPayload
from server.models.messages.weapons import WeaponsSelectTargetPayload, WeaponsFireBeamsPayload
from server.models.messages.science import ScienceStartScanPayload, ScienceScanInterruptResponsePayload
from server.models.messages.captain import (
    CaptainSetAlertPayload,
    CaptainAuthorizePayload,
    CaptainAddLogPayload,
    CaptainSystemOverridePayload,
    CaptainReassignCrewPayload,
)
from server.models.messages.medical import MedicalTreatCrewPayload, MedicalAdmitPayload
from server.models.messages.security import SecurityMoveSquadPayload, SecurityToggleDoorPayload
from server.models.messages.comms import CommsTuneFrequencyPayload, CommsHailPayload
from server.models.messages.flight_ops import FlightOpsLaunchDronePayload, FlightOpsDeployDecoyPayload
from server.models.messages.ew import EWSetJamTargetPayload, EWToggleCountermeasuresPayload
from server.models.messages.tactical import TacticalSetEngagementPriorityPayload, TacticalAddAnnotationPayload
from server.models.messages.puzzle import PuzzleSubmitPayload, PuzzleCancelPayload
from server.models.messages.creatures import CreatureSedatePayload, CreatureEWDisruptPayload
from server.models.messages.docking import (
    CaptainUndockPayload,
    DockingRequestClearancePayload,
    DockingStartServicePayload,
)
from server.models.messages.navigation import MapPlotRoutePayload, MapClearRoutePayload
from server.models.messages.crew import CrewNotifyPayload
from server.models.messages.game import GameBriefingLaunchPayload

from server import captain
from server.models.ship import Ship


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(type_: str, payload: dict | None = None) -> Message:
    """Build a Message envelope for testing."""
    return Message(type=type_, payload=payload or {}, tick=None, timestamp=0.0)


class MockManager:
    """Captures both individual sends and broadcasts."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, Message]] = []
        self.broadcast_msgs: list[Message] = []

    async def send(self, connection_id: str, message: Message) -> None:
        self.sent.append((connection_id, message))

    async def broadcast(self, message: Message) -> None:
        self.broadcast_msgs.append(message)


def _drain_test_queue(queue: asyncio.Queue) -> list[tuple[str, object]]:
    """Pull all items from a queue synchronously (non-blocking)."""
    items = []
    while True:
        try:
            items.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return items


# ===========================================================================
# 1. HANDLER REGISTRATION — every expected prefix is in _HANDLERS
# ===========================================================================


_STATION_PREFIXES = [
    "lobby", "helm", "engineering", "weapons", "science", "captain",
    "medical", "security", "comms", "flight_ops", "ew", "tactical",
    "damage_control",
]

_GENERIC_PREFIXES = ["puzzle", "creature", "docking", "map", "crew"]


class TestHandlerRegistration:
    """Every expected prefix has an entry in _HANDLERS."""

    @pytest.mark.parametrize("prefix", _STATION_PREFIXES)
    def test_station_prefix_registered(self, prefix: str):
        assert prefix in _HANDLERS, f"Missing _HANDLERS entry for '{prefix}'"

    @pytest.mark.parametrize("prefix", _GENERIC_PREFIXES)
    def test_generic_prefix_registered(self, prefix: str):
        assert prefix in _HANDLERS, f"Missing _HANDLERS entry for '{prefix}'"

    def test_game_prefix_registered(self):
        assert "game" in _HANDLERS

    @pytest.mark.parametrize("prefix", _GENERIC_PREFIXES)
    def test_generic_prefixes_use_queue_forward_handler(self, prefix: str):
        assert _HANDLERS[prefix] is _queue_forward_handler, (
            f"'{prefix}' should use _queue_forward_handler"
        )


# ===========================================================================
# 2. SCHEMA VALIDATION — validate_payload returns the correct model
# ===========================================================================


class TestLobbyValidation:
    def test_lobby_claim_role(self):
        msg = _msg("lobby.claim_role", {"role": "helm", "player_name": "Alice"})
        result = validate_payload(msg)
        assert isinstance(result, LobbyClaimRolePayload)
        assert result.role == "helm"
        assert result.player_name == "Alice"

    def test_lobby_prefix_in_handlers(self):
        assert "lobby" in _HANDLERS


class TestHelmValidation:
    def test_helm_set_heading(self):
        msg = _msg("helm.set_heading", {"heading": 90.0})
        result = validate_payload(msg)
        assert isinstance(result, HelmSetHeadingPayload)
        assert result.heading == 90.0

    def test_helm_set_throttle(self):
        msg = _msg("helm.set_throttle", {"throttle": 75.0})
        result = validate_payload(msg)
        assert isinstance(result, HelmSetThrottlePayload)
        assert result.throttle == 75.0


class TestEngineeringValidation:
    def test_engineering_set_power(self):
        msg = _msg("engineering.set_power", {"system": "engines", "level": 120.0})
        result = validate_payload(msg)
        assert isinstance(result, EngineeringSetPowerPayload)
        assert result.system == "engines"
        assert result.level == 120.0

    def test_engineering_set_repair(self):
        msg = _msg("engineering.set_repair", {"system": "shields"})
        result = validate_payload(msg)
        assert isinstance(result, EngineeringSetRepairPayload)
        assert result.system == "shields"


class TestWeaponsValidation:
    def test_weapons_select_target(self):
        msg = _msg("weapons.select_target", {"entity_id": "enemy_1"})
        result = validate_payload(msg)
        assert isinstance(result, WeaponsSelectTargetPayload)
        assert result.entity_id == "enemy_1"

    def test_weapons_fire_beams(self):
        msg = _msg("weapons.fire_beams", {"beam_frequency": "alpha"})
        result = validate_payload(msg)
        assert isinstance(result, WeaponsFireBeamsPayload)
        assert result.beam_frequency == "alpha"


class TestScienceValidation:
    def test_science_start_scan(self):
        msg = _msg("science.start_scan", {"entity_id": "signal_1"})
        result = validate_payload(msg)
        assert isinstance(result, ScienceStartScanPayload)
        assert result.entity_id == "signal_1"

    def test_science_scan_interrupt_response(self):
        msg = _msg("science.scan_interrupt_response", {"continue_scan": True})
        result = validate_payload(msg)
        assert isinstance(result, ScienceScanInterruptResponsePayload)
        assert result.continue_scan is True


class TestCaptainValidation:
    def test_captain_set_alert(self):
        msg = _msg("captain.set_alert", {"level": "red"})
        result = validate_payload(msg)
        assert isinstance(result, CaptainSetAlertPayload)
        assert result.level == "red"

    def test_captain_undock(self):
        msg = _msg("captain.undock", {"emergency": False})
        result = validate_payload(msg)
        assert isinstance(result, CaptainUndockPayload)
        assert result.emergency is False

    def test_captain_undock_default(self):
        """captain.undock with empty payload should default emergency=False."""
        msg = _msg("captain.undock", {})
        result = validate_payload(msg)
        assert isinstance(result, CaptainUndockPayload)
        assert result.emergency is False


class TestMedicalValidation:
    def test_medical_treat_crew(self):
        msg = _msg("medical.treat_crew", {"deck": "deck_1", "injury_type": "injured"})
        result = validate_payload(msg)
        assert isinstance(result, MedicalTreatCrewPayload)
        assert result.deck == "deck_1"

    def test_medical_admit(self):
        msg = _msg("medical.admit", {"crew_id": "crew_42"})
        result = validate_payload(msg)
        assert isinstance(result, MedicalAdmitPayload)
        assert result.crew_id == "crew_42"


class TestSecurityValidation:
    def test_security_move_squad(self):
        msg = _msg("security.move_squad", {"squad_id": "alpha", "room_id": "room_1"})
        result = validate_payload(msg)
        assert isinstance(result, SecurityMoveSquadPayload)
        assert result.squad_id == "alpha"

    def test_security_toggle_door(self):
        msg = _msg("security.toggle_door", {"squad_id": "alpha", "room_id": "room_2"})
        result = validate_payload(msg)
        assert isinstance(result, SecurityToggleDoorPayload)


class TestCommsValidation:
    def test_comms_tune_frequency(self):
        msg = _msg("comms.tune_frequency", {"frequency": 0.42})
        result = validate_payload(msg)
        assert isinstance(result, CommsTuneFrequencyPayload)
        assert result.frequency == pytest.approx(0.42)

    def test_comms_hail(self):
        msg = _msg("comms.hail", {"contact_id": "rebel_1", "message_type": "negotiate"})
        result = validate_payload(msg)
        assert isinstance(result, CommsHailPayload)


class TestFlightOpsValidation:
    def test_flight_ops_launch_drone(self):
        msg = _msg("flight_ops.launch_drone", {"drone_id": "drone_1"})
        result = validate_payload(msg)
        assert isinstance(result, FlightOpsLaunchDronePayload)
        assert result.drone_id == "drone_1"

    def test_flight_ops_deploy_decoy(self):
        msg = _msg("flight_ops.deploy_decoy", {"direction": 90.0})
        result = validate_payload(msg)
        assert isinstance(result, FlightOpsDeployDecoyPayload)
        assert result.direction == 90.0


class TestEWValidation:
    def test_ew_set_jam_target(self):
        msg = _msg("ew.set_jam_target", {"entity_id": "enemy_3"})
        result = validate_payload(msg)
        assert isinstance(result, EWSetJamTargetPayload)
        assert result.entity_id == "enemy_3"

    def test_ew_toggle_countermeasures(self):
        msg = _msg("ew.toggle_countermeasures", {"active": True})
        result = validate_payload(msg)
        assert isinstance(result, EWToggleCountermeasuresPayload)
        assert result.active is True


class TestTacticalValidation:
    def test_tactical_set_engagement_priority(self):
        msg = _msg("tactical.set_engagement_priority", {
            "entity_id": "enemy_1", "priority": "primary",
        })
        result = validate_payload(msg)
        assert isinstance(result, TacticalSetEngagementPriorityPayload)

    def test_tactical_add_annotation(self):
        msg = _msg("tactical.add_annotation", {
            "annotation_type": "waypoint", "x": 100.0, "y": 200.0,
            "label": "Target", "text": "Attack here",
        })
        result = validate_payload(msg)
        assert isinstance(result, TacticalAddAnnotationPayload)


class TestDamageControlValidation:
    def test_damage_control_dispatch_dct(self):
        msg = _msg("damage_control.dispatch_dct", {"room_id": "room_3"})
        result = validate_payload(msg)
        assert result is not None
        assert result.room_id == "room_3"

    def test_damage_control_cancel_dct(self):
        msg = _msg("damage_control.cancel_dct", {"room_id": "room_3"})
        result = validate_payload(msg)
        assert result is not None


# ===========================================================================
# 3. GENERIC FORWARDER TESTS — queue_forward_handler routes to input_queue
# ===========================================================================


class TestQueueForwardHandler:
    """Messages sent via _queue_forward_handler end up in the input queue."""

    @pytest.mark.asyncio
    async def test_puzzle_submit_queued(self):
        # Drain any leftover items
        _drain_test_queue(input_queue)
        msg = _msg("puzzle.submit", {"puzzle_id": "p1", "submission": {"answer": 42}})
        await _queue_forward_handler("conn_test", msg)
        items = _drain_test_queue(input_queue)
        assert len(items) == 1
        msg_type, payload = items[0]
        assert msg_type == "puzzle.submit"
        assert isinstance(payload, PuzzleSubmitPayload)
        assert payload.puzzle_id == "p1"

    @pytest.mark.asyncio
    async def test_puzzle_cancel_queued(self):
        _drain_test_queue(input_queue)
        msg = _msg("puzzle.cancel", {"puzzle_id": "p2"})
        await _queue_forward_handler("conn_test", msg)
        items = _drain_test_queue(input_queue)
        assert len(items) == 1
        assert items[0][0] == "puzzle.cancel"
        assert isinstance(items[0][1], PuzzleCancelPayload)

    @pytest.mark.asyncio
    async def test_creature_sedate_queued(self):
        _drain_test_queue(input_queue)
        msg = _msg("creature.sedate", {"creature_id": "void_whale_1"})
        await _queue_forward_handler("conn_test", msg)
        items = _drain_test_queue(input_queue)
        assert len(items) == 1
        assert items[0][0] == "creature.sedate"
        assert isinstance(items[0][1], CreatureSedatePayload)

    @pytest.mark.asyncio
    async def test_creature_ew_disrupt_queued(self):
        _drain_test_queue(input_queue)
        msg = _msg("creature.ew_disrupt", {"creature_id": "swarm_1"})
        await _queue_forward_handler("conn_test", msg)
        items = _drain_test_queue(input_queue)
        assert len(items) == 1
        assert isinstance(items[0][1], CreatureEWDisruptPayload)

    @pytest.mark.asyncio
    async def test_docking_request_clearance_queued(self):
        _drain_test_queue(input_queue)
        msg = _msg("docking.request_clearance", {"station_id": "station_1"})
        await _queue_forward_handler("conn_test", msg)
        items = _drain_test_queue(input_queue)
        assert len(items) == 1
        assert items[0][0] == "docking.request_clearance"
        assert isinstance(items[0][1], DockingRequestClearancePayload)

    @pytest.mark.asyncio
    async def test_docking_start_service_queued(self):
        _drain_test_queue(input_queue)
        msg = _msg("docking.start_service", {"service": "repair"})
        await _queue_forward_handler("conn_test", msg)
        items = _drain_test_queue(input_queue)
        assert len(items) == 1
        assert isinstance(items[0][1], DockingStartServicePayload)

    @pytest.mark.asyncio
    async def test_map_plot_route_queued(self):
        _drain_test_queue(input_queue)
        msg = _msg("map.plot_route", {"to_x": 50000.0, "to_y": 50000.0})
        await _queue_forward_handler("conn_test", msg)
        items = _drain_test_queue(input_queue)
        assert len(items) == 1
        assert items[0][0] == "map.plot_route"
        assert isinstance(items[0][1], MapPlotRoutePayload)

    @pytest.mark.asyncio
    async def test_map_clear_route_queued(self):
        _drain_test_queue(input_queue)
        msg = _msg("map.clear_route", {})
        await _queue_forward_handler("conn_test", msg)
        items = _drain_test_queue(input_queue)
        assert len(items) == 1
        assert isinstance(items[0][1], MapClearRoutePayload)

    @pytest.mark.asyncio
    async def test_crew_notify_queued(self):
        _drain_test_queue(input_queue)
        msg = _msg("crew.notify", {"message": "Brace for impact!", "from_role": "captain"})
        await _queue_forward_handler("conn_test", msg)
        items = _drain_test_queue(input_queue)
        assert len(items) == 1
        assert items[0][0] == "crew.notify"
        assert isinstance(items[0][1], CrewNotifyPayload)
        assert items[0][1].message == "Brace for impact!"

    @pytest.mark.asyncio
    async def test_forward_handler_rejects_invalid_payload(self):
        """Invalid payload should send an error.validation back, not queue."""
        _drain_test_queue(input_queue)
        # puzzle.submit requires puzzle_id (str) and submission (dict)
        msg = _msg("puzzle.submit", {"bad_field": True})
        # _queue_forward_handler calls manager.send on validation error,
        # but we imported it directly, so it uses main.manager.
        # We just verify nothing was queued.
        try:
            await _queue_forward_handler("conn_test", msg)
        except Exception:
            pass  # May raise if manager is not connected; that's OK
        items = _drain_test_queue(input_queue)
        assert len(items) == 0, "Invalid payload should not be queued"

    @pytest.mark.asyncio
    async def test_forward_handler_ignores_unknown_type(self):
        """Unknown message types within a valid prefix should not be queued."""
        _drain_test_queue(input_queue)
        msg = _msg("puzzle.nonexistent_action", {"data": 1})
        await _queue_forward_handler("conn_test", msg)
        items = _drain_test_queue(input_queue)
        assert len(items) == 0, "Unknown type should not be queued"


# ===========================================================================
# 4. CAPTAIN ROUTING — direct vs queued handling
# ===========================================================================


class TestCaptainRouting:
    """Captain messages are split between direct handling and queue forwarding."""

    def _setup(self) -> tuple[MockManager, Ship, asyncio.Queue]:
        mgr = MockManager()
        ship = Ship()
        queue: asyncio.Queue = asyncio.Queue()
        captain.init(mgr, ship, queue)
        return mgr, ship, queue

    @pytest.mark.asyncio
    async def test_set_alert_direct_broadcast(self):
        """captain.set_alert is handled directly — broadcasts immediately."""
        mgr, ship, queue = self._setup()
        msg = _msg("captain.set_alert", {"level": "red"})
        await captain.handle_captain_message("conn1", msg)
        # Should broadcast, not queue
        assert len(mgr.broadcast_msgs) == 1
        assert mgr.broadcast_msgs[0].type == "ship.alert_changed"
        assert mgr.broadcast_msgs[0].payload["level"] == "red"
        assert queue.empty(), "set_alert should NOT be queued"

    @pytest.mark.asyncio
    async def test_set_alert_updates_ship_state(self):
        """captain.set_alert should mutate ship.alert_level."""
        mgr, ship, queue = self._setup()
        assert ship.alert_level == "green"  # default
        msg = _msg("captain.set_alert", {"level": "yellow"})
        await captain.handle_captain_message("conn1", msg)
        assert ship.alert_level == "yellow"

    @pytest.mark.asyncio
    async def test_system_override_direct_broadcast(self):
        """captain.system_override is handled directly — broadcasts immediately."""
        mgr, ship, queue = self._setup()
        msg = _msg("captain.system_override", {"system": "engines", "online": False})
        await captain.handle_captain_message("conn1", msg)
        assert len(mgr.broadcast_msgs) == 1
        assert mgr.broadcast_msgs[0].type == "captain.override_changed"
        assert queue.empty(), "system_override should NOT be queued"

    @pytest.mark.asyncio
    async def test_authorize_forwarded_to_queue(self):
        """captain.authorize should be forwarded to the game loop queue."""
        mgr, ship, queue = self._setup()
        msg = _msg("captain.authorize", {"request_id": "req_1", "approved": True})
        await captain.handle_captain_message("conn1", msg)
        assert not queue.empty()
        msg_type, payload = queue.get_nowait()
        assert msg_type == "captain.authorize"
        assert isinstance(payload, CaptainAuthorizePayload)
        assert payload.approved is True
        # Should NOT broadcast
        assert len(mgr.broadcast_msgs) == 0

    @pytest.mark.asyncio
    async def test_add_log_forwarded_to_queue(self):
        """captain.add_log should be forwarded to the game loop queue."""
        mgr, ship, queue = self._setup()
        msg = _msg("captain.add_log", {"text": "All systems nominal."})
        await captain.handle_captain_message("conn1", msg)
        assert not queue.empty()
        msg_type, payload = queue.get_nowait()
        assert msg_type == "captain.add_log"
        assert isinstance(payload, CaptainAddLogPayload)
        assert payload.text == "All systems nominal."

    @pytest.mark.asyncio
    async def test_undock_forwarded_to_queue(self):
        """captain.undock should be forwarded to the game loop queue (was previously broken)."""
        mgr, ship, queue = self._setup()
        msg = _msg("captain.undock", {"emergency": True})
        await captain.handle_captain_message("conn1", msg)
        assert not queue.empty()
        msg_type, payload = queue.get_nowait()
        assert msg_type == "captain.undock"
        assert isinstance(payload, CaptainUndockPayload)
        assert payload.emergency is True

    @pytest.mark.asyncio
    async def test_reassign_crew_handled_directly(self):
        """captain.reassign_crew is handled directly (not queued)."""
        mgr, ship, queue = self._setup()
        msg = _msg("captain.reassign_crew", {
            "crew_id": "crew_1", "new_duty_station": "engineering",
        })
        # This will attempt to call glmed.get_roster() which may return None
        # and send an error — that's fine, we just verify it's not queued.
        await captain.handle_captain_message("conn1", msg)
        assert queue.empty(), "reassign_crew should NOT be queued"

    @pytest.mark.asyncio
    async def test_save_game_handled_directly(self):
        """captain.save_game is handled directly (not queued)."""
        mgr, ship, queue = self._setup()
        msg = _msg("captain.save_game", {})
        # Will send error because no game is running — that's expected.
        await captain.handle_captain_message("conn1", msg)
        assert queue.empty(), "save_game should NOT be queued"

    @pytest.mark.asyncio
    async def test_captain_validation_error_sends_error(self):
        """Invalid captain payload should send an error.validation message."""
        mgr, ship, queue = self._setup()
        msg = _msg("captain.set_alert", {"level": "INVALID_LEVEL"})
        await captain.handle_captain_message("conn1", msg)
        assert len(mgr.sent) == 1
        err_msg = mgr.sent[0][1]
        assert err_msg.type == "error.validation"
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_captain_unknown_type_ignored(self):
        """Unknown captain message type should not queue or broadcast."""
        mgr, ship, queue = self._setup()
        msg = _msg("captain.nonexistent_command", {"data": 1})
        await captain.handle_captain_message("conn1", msg)
        assert queue.empty()
        assert len(mgr.broadcast_msgs) == 0
        assert len(mgr.sent) == 0


# ===========================================================================
# 5. SCHEMA COMPLETENESS — every _drain_queue msg_type has a _PAYLOAD_SCHEMAS entry
# ===========================================================================


class TestSchemaCompleteness:
    """Systematic check that prevents the missing-schema bug class."""

    def _extract_drain_queue_msg_types(self) -> set[str]:
        """Parse _drain_queue source to extract all msg_type string literals.

        This finds all patterns like:
            msg_type == "foo.bar"
            msg_type in ("foo.bar", "baz.qux")
        """
        import inspect
        import server.game_loop as gl_module
        source = inspect.getsource(gl_module._drain_queue)

        # Match `msg_type == "some.type"`
        eq_pattern = re.findall(r'msg_type\s*==\s*"([^"]+)"', source)
        # Match `msg_type in ("some.type", "other.type")`  or  `msg_type in (...)`
        in_blocks = re.findall(r'msg_type\s+in\s+\(([^)]+)\)', source)
        in_types = []
        for block in in_blocks:
            in_types.extend(re.findall(r'"([^"]+)"', block))

        return set(eq_pattern) | set(in_types)

    def test_all_drain_queue_types_have_schemas(self):
        """Every message type handled in _drain_queue must have a _PAYLOAD_SCHEMAS entry."""
        drain_types = self._extract_drain_queue_msg_types()
        assert len(drain_types) > 30, (
            f"Expected to find >30 msg types in _drain_queue, found {len(drain_types)}. "
            "The source parsing may be broken."
        )

        missing = drain_types - set(_PAYLOAD_SCHEMAS.keys())
        assert not missing, (
            f"Message types handled in _drain_queue but missing from _PAYLOAD_SCHEMAS: "
            f"{sorted(missing)}"
        )

    def test_all_schemas_have_valid_prefix_handler(self):
        """Every schema in _PAYLOAD_SCHEMAS should have its prefix registered in _HANDLERS."""
        for msg_type in _PAYLOAD_SCHEMAS:
            prefix = msg_type.split(".")[0]
            assert prefix in _HANDLERS, (
                f"Schema for '{msg_type}' exists but prefix '{prefix}' "
                f"is not in _HANDLERS"
            )

    def test_payload_schemas_nonempty(self):
        """Sanity: _PAYLOAD_SCHEMAS should have a meaningful number of entries."""
        assert len(_PAYLOAD_SCHEMAS) >= 50, (
            f"Expected >= 50 schema entries, found {len(_PAYLOAD_SCHEMAS)}"
        )

    def test_no_duplicate_schema_coverage(self):
        """Each message type should appear exactly once in _PAYLOAD_SCHEMAS."""
        # _PAYLOAD_SCHEMAS is a dict so keys are unique by construction.
        # This test verifies the dict is well-formed (no accidental overwrite
        # would be silent in Python).
        types = list(_PAYLOAD_SCHEMAS.keys())
        assert len(types) == len(set(types))


# ===========================================================================
# 6. STATION HANDLER QUEUE INTEGRATION — messages reach the queue
# ===========================================================================


class TestStationHandlerQueueIntegration:
    """Test that station handlers validate and queue messages correctly."""

    @pytest.mark.asyncio
    async def test_helm_handler_queues_message(self):
        """helm.handle_helm_message should validate and put in the queue."""
        from server import helm
        mock_sender = MockManager()
        queue: asyncio.Queue = asyncio.Queue()
        helm.init(mock_sender, queue)
        msg = _msg("helm.set_heading", {"heading": 180.0})
        await helm.handle_helm_message("conn1", msg)
        assert not queue.empty()
        msg_type, payload = queue.get_nowait()
        assert msg_type == "helm.set_heading"
        assert isinstance(payload, HelmSetHeadingPayload)
        assert payload.heading == 180.0

    @pytest.mark.asyncio
    async def test_engineering_handler_queues_message(self):
        from server import engineering
        mock_sender = MockManager()
        queue: asyncio.Queue = asyncio.Queue()
        engineering.init(mock_sender, queue)
        msg = _msg("engineering.set_power", {"system": "shields", "level": 100.0})
        await engineering.handle_engineering_message("conn1", msg)
        assert not queue.empty()
        msg_type, payload = queue.get_nowait()
        assert msg_type == "engineering.set_power"
        assert isinstance(payload, EngineeringSetPowerPayload)

    @pytest.mark.asyncio
    async def test_weapons_handler_queues_message(self):
        from server import weapons
        mock_sender = MockManager()
        queue: asyncio.Queue = asyncio.Queue()
        weapons.init(mock_sender, queue)
        msg = _msg("weapons.select_target", {"entity_id": "enemy_1"})
        await weapons.handle_weapons_message("conn1", msg)
        assert not queue.empty()
        msg_type, payload = queue.get_nowait()
        assert msg_type == "weapons.select_target"
        assert isinstance(payload, WeaponsSelectTargetPayload)

    @pytest.mark.asyncio
    async def test_science_handler_queues_message(self):
        from server import science
        mock_sender = MockManager()
        queue: asyncio.Queue = asyncio.Queue()
        science.init(mock_sender, queue)
        msg = _msg("science.start_scan", {"entity_id": "anomaly_1"})
        await science.handle_science_message("conn1", msg)
        assert not queue.empty()
        msg_type, payload = queue.get_nowait()
        assert msg_type == "science.start_scan"
        assert isinstance(payload, ScienceStartScanPayload)

    @pytest.mark.asyncio
    async def test_medical_handler_queues_message(self):
        from server import medical
        mock_sender = MockManager()
        queue: asyncio.Queue = asyncio.Queue()
        medical.init(mock_sender, queue)
        msg = _msg("medical.treat_crew", {"deck": "deck_0", "injury_type": "injured"})
        await medical.handle_medical_message("conn1", msg)
        assert not queue.empty()
        msg_type, payload = queue.get_nowait()
        assert msg_type == "medical.treat_crew"
        assert isinstance(payload, MedicalTreatCrewPayload)

    @pytest.mark.asyncio
    async def test_security_handler_queues_message(self):
        from server import security
        mock_sender = MockManager()
        queue: asyncio.Queue = asyncio.Queue()
        security.init(mock_sender, queue)
        msg = _msg("security.move_squad", {"squad_id": "bravo", "room_id": "room_5"})
        await security.handle_security_message("conn1", msg)
        assert not queue.empty()
        msg_type, payload = queue.get_nowait()
        assert msg_type == "security.move_squad"
        assert isinstance(payload, SecurityMoveSquadPayload)

    @pytest.mark.asyncio
    async def test_comms_handler_queues_message(self):
        from server import comms
        mock_sender = MockManager()
        queue: asyncio.Queue = asyncio.Queue()
        comms.init(mock_sender, queue)
        msg = _msg("comms.tune_frequency", {"frequency": 0.15})
        await comms.handle_comms_message("conn1", msg)
        assert not queue.empty()
        msg_type, payload = queue.get_nowait()
        assert msg_type == "comms.tune_frequency"
        assert isinstance(payload, CommsTuneFrequencyPayload)

    @pytest.mark.asyncio
    async def test_flight_ops_handler_queues_message(self):
        from server import flight_ops
        mock_sender = MockManager()
        queue: asyncio.Queue = asyncio.Queue()
        flight_ops.init(mock_sender, queue)
        msg = _msg("flight_ops.deploy_decoy", {"direction": 180.0})
        await flight_ops.handle_flight_ops_message("conn1", msg)
        assert not queue.empty()
        msg_type, payload = queue.get_nowait()
        assert msg_type == "flight_ops.deploy_decoy"
        assert isinstance(payload, FlightOpsDeployDecoyPayload)

    @pytest.mark.asyncio
    async def test_ew_handler_queues_message(self):
        from server import ew
        mock_sender = MockManager()
        queue: asyncio.Queue = asyncio.Queue()
        ew.init(mock_sender, queue)
        msg = _msg("ew.set_jam_target", {"entity_id": "enemy_2"})
        await ew.handle_ew_message("conn1", msg)
        assert not queue.empty()
        msg_type, payload = queue.get_nowait()
        assert msg_type == "ew.set_jam_target"
        assert isinstance(payload, EWSetJamTargetPayload)

    @pytest.mark.asyncio
    async def test_tactical_handler_queues_message(self):
        from server import tactical
        mock_sender = MockManager()
        queue: asyncio.Queue = asyncio.Queue()
        tactical.init(mock_sender, queue)
        msg = _msg("tactical.set_engagement_priority", {
            "entity_id": "enemy_1", "priority": "primary",
        })
        await tactical.handle_tactical_message("conn1", msg)
        assert not queue.empty()
        msg_type, payload = queue.get_nowait()
        assert msg_type == "tactical.set_engagement_priority"
        assert isinstance(payload, TacticalSetEngagementPriorityPayload)

    @pytest.mark.asyncio
    async def test_damage_control_handler_queues_message(self):
        from server import damage_control
        mock_sender = MockManager()
        queue: asyncio.Queue = asyncio.Queue()
        damage_control.init(mock_sender, queue)
        msg = _msg("damage_control.dispatch_dct", {"room_id": "room_7"})
        await damage_control.handle_damage_control_message("conn1", msg)
        assert not queue.empty()
        msg_type, payload = queue.get_nowait()
        assert msg_type == "damage_control.dispatch_dct"

    @pytest.mark.asyncio
    async def test_handler_rejects_invalid_payload(self):
        """Station handlers should send validation error on bad payload."""
        from server import helm
        mock_sender = MockManager()
        queue: asyncio.Queue = asyncio.Queue()
        helm.init(mock_sender, queue)
        # heading must be >= 0.0 and < 360.0
        msg = _msg("helm.set_heading", {"heading": 999.0})
        await helm.handle_helm_message("conn1", msg)
        # Should NOT be queued
        assert queue.empty()
        # Should have sent an error
        assert len(mock_sender.sent) == 1
        assert mock_sender.sent[0][1].type == "error.validation"


# ===========================================================================
# 7. GAME BRIEFING LAUNCH — game prefix routing
# ===========================================================================


class TestGameRouting:
    def test_game_briefing_launch_schema(self):
        msg = _msg("game.briefing_launch", {})
        result = validate_payload(msg)
        assert isinstance(result, GameBriefingLaunchPayload)

    def test_game_prefix_in_handlers(self):
        assert "game" in _HANDLERS
