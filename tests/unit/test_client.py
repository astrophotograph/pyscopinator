"""Unit tests for SeestarClient core logic.

These tests cover pure-logic methods that do NOT require a live connection.
All network I/O is mocked.
"""

import asyncio
import io
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scopinator.seestar.client import SeestarClient, SeestarStatus
from scopinator.seestar.commands.common import CommandResponse
from scopinator.util.eventbus import EventBus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_response(id: int = 1, method: str = "test", code: int = 0, result=None):
    return CommandResponse(
        id=id,
        jsonrpc="2.0",
        Timestamp="2024-01-01T00:00:00",
        method=method,
        code=code,
        result=result,
    )


@pytest.fixture
def client():
    """SeestarClient with a completely mocked connection."""
    with patch("scopinator.seestar.client.SeestarConnection") as MockConn:
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = False
        mock_conn.open = AsyncMock()
        mock_conn.close = AsyncMock()
        mock_conn.write = AsyncMock()
        MockConn.return_value = mock_conn
        c = SeestarClient("192.168.1.100", 4700)
        c.connection = mock_conn
        return c


@pytest.fixture
def connected_client(client):
    """Client marked as connected with send_and_recv mocked out."""
    client.is_connected = True
    client.send_and_recv = AsyncMock(return_value=None)
    return client


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestClientInit:
    def test_fields(self, client):
        assert client.host == "192.168.1.100"
        assert client.port == 4700
        assert client.is_connected is False
        assert client.client_mode == "Idle"
        assert client.verify_injection is True

    def test_creates_event_bus_if_none_provided(self, client):
        assert client.event_bus is not None
        assert isinstance(client.event_bus, EventBus)

    def test_accepts_external_event_bus(self):
        bus = EventBus()
        with patch("scopinator.seestar.client.SeestarConnection"):
            c = SeestarClient("127.0.0.1", 4700, event_bus=bus)
        assert c.event_bus is bus

    def test_status_initialized(self, client):
        assert isinstance(client.status, SeestarStatus)
        assert client.status.stacked_frame == 0
        assert client.status.dropped_frame == 0

    def test_message_history_deque(self, client):
        assert client.message_history.maxlen == 5000

    def test_recent_events_deque(self, client):
        assert client.recent_events.maxlen == 5


# ---------------------------------------------------------------------------
# SeestarStatus.reset()
# ---------------------------------------------------------------------------

class TestSeestarStatusReset:
    def test_reset_clears_all_fields(self):
        s = SeestarStatus(
            temp=25.0,
            stage="Stack",
            stacked_frame=100,
            dropped_frame=5,
            target_name="M31",
            focus_position=1234,
            ra=10.5,
            dec=45.0,
            lp_filter=True,
            gain=80,
            freeMB=1000,
            totalMB=32000,
        )
        s.reset()

        assert s.temp is None
        assert s.stage is None
        assert s.stacked_frame == 0
        assert s.dropped_frame == 0
        assert s.target_name == ""
        assert s.focus_position is None
        assert s.ra is None
        assert s.dec is None
        assert s.lp_filter is False
        assert s.gain is None
        assert s.freeMB is None
        assert s.totalMB is None

    def test_reset_idempotent(self):
        s = SeestarStatus()
        s.reset()
        s.reset()
        assert s.stacked_frame == 0


# ---------------------------------------------------------------------------
# _get_firmware_ver_int / _should_inject_verify
# ---------------------------------------------------------------------------

class TestFirmwareVersion:
    def test_no_device_state_returns_zero(self, client):
        assert client._get_firmware_ver_int() == 0

    def test_device_state_not_dict(self, client):
        client.status.device_state = "bad"
        assert client._get_firmware_ver_int() == 0

    def test_device_not_dict(self, client):
        client.status.device_state = {"device": "bad"}
        assert client._get_firmware_ver_int() == 0

    def test_firmware_ver_int_present(self, client):
        client.status.device_state = {"device": {"firmware_ver_int": 2600}}
        assert client._get_firmware_ver_int() == 2600

    def test_firmware_ver_int_missing(self, client):
        client.status.device_state = {"device": {"other_key": 1}}
        assert client._get_firmware_ver_int() == 0

    def test_should_inject_verify_disabled(self, client):
        client.verify_injection = False
        assert client._should_inject_verify() is False

    def test_should_inject_verify_firmware_zero(self, client):
        # firmware 0 (unknown) → should inject
        assert client._should_inject_verify() is True

    def test_should_inject_verify_firmware_high(self, client):
        client.status.device_state = {"device": {"firmware_ver_int": 2600}}
        assert client._should_inject_verify() is True

    def test_should_inject_verify_firmware_low(self, client):
        # firmware 2582 or below, but not 0 → no inject
        client.status.device_state = {"device": {"firmware_ver_int": 2582}}
        assert client._should_inject_verify() is False

    def test_should_inject_verify_firmware_boundary(self, client):
        client.status.device_state = {"device": {"firmware_ver_int": 2583}}
        assert client._should_inject_verify() is True

    def test_should_inject_verify_firmware_2706(self, client):
        # 7.06+ still passes _should_inject_verify (dict-param guard is in transform)
        client.status.device_state = {"device": {"firmware_ver_int": 2706}}
        assert client._should_inject_verify() is True


# ---------------------------------------------------------------------------
# _transform_message_for_verify
# ---------------------------------------------------------------------------

class TestTransformMessageForVerify:
    def _client_with_injection(self):
        with patch("scopinator.seestar.client.SeestarConnection"):
            c = SeestarClient("127.0.0.1", 4700)
        c.verify_injection = True
        # firmware 0 → inject
        return c

    def test_inject_disabled_passes_through(self, client):
        client.verify_injection = False
        data = {"method": "test", "params": {"foo": "bar"}}
        result = client._transform_message_for_verify(data)
        assert result == {"method": "test", "params": {"foo": "bar"}}

    def test_no_params_adds_verify_list(self, client):
        data = {"method": "test"}
        result = client._transform_message_for_verify(data)
        assert result["params"] == ["verify"]

    def test_dict_params_adds_verify_key(self, client):
        data = {"method": "test", "params": {"foo": "bar"}}
        result = client._transform_message_for_verify(data)
        assert result["params"]["verify"] is True
        assert result["params"]["foo"] == "bar"

    def test_dict_params_does_not_overwrite_existing_verify(self, client):
        data = {"method": "test", "params": {"foo": "bar", "verify": False}}
        result = client._transform_message_for_verify(data)
        # Should NOT overwrite existing 'verify'
        assert result["params"]["verify"] is False

    def test_list_params_set_wheel_position(self, client):
        data = {"method": "set_wheel_position", "params": [1]}
        result = client._transform_message_for_verify(data)
        assert result["params"] == [1, "verify"]

    def test_list_params_already_has_verify(self, client):
        """If the last element is already 'verify', don't add again."""
        data = {"method": "test", "params": ["something", "verify"]}
        result = client._transform_message_for_verify(data)
        assert result["params"].count("verify") == 1

    def test_list_params_other_method_wraps(self, client):
        data = {"method": "other_method", "params": [42]}
        result = client._transform_message_for_verify(data)
        assert result["params"] == [[42], "verify"]

    def test_empty_list_params_adds_verify(self, client):
        data = {"method": "test", "params": []}
        result = client._transform_message_for_verify(data)
        # Empty list: no "verify" at end, wraps as [[], "verify"]
        assert "verify" in result["params"]

    def test_firmware_2706_dict_params_not_modified(self, client):
        # 2706+ skips verify for dict params (device rejects it with code 109/107)
        client.status.device_state = {"device": {"firmware_ver_int": 2706}}
        data = {"method": "test", "params": {"foo": "bar"}}
        result = client._transform_message_for_verify(data)
        assert result["params"] == {"foo": "bar"}

    def test_firmware_2706_list_params_still_get_verify(self, client):
        # 2706+ only skips verify for dict params; list params still get it
        client.status.device_state = {"device": {"firmware_ver_int": 2706}}
        data = {"method": "test", "params": [42]}
        result = client._transform_message_for_verify(data)
        assert result["params"] == [[42], "verify"]

    def test_firmware_2706_no_params_still_get_verify(self, client):
        client.status.device_state = {"device": {"firmware_ver_int": 2706}}
        data = {"method": "test"}
        result = client._transform_message_for_verify(data)
        assert result["params"] == ["verify"]

    def test_firmware_2706_set_wheel_position_still_get_verify(self, client):
        client.status.device_state = {"device": {"firmware_ver_int": 2706}}
        data = {"method": "set_wheel_position", "params": [1]}
        result = client._transform_message_for_verify(data)
        assert result["params"] == [1, "verify"]


# ---------------------------------------------------------------------------
# _update_client_mode
# ---------------------------------------------------------------------------

class TestUpdateClientMode:
    def test_continuous_exposure(self, client):
        client._update_client_mode("ContinuousExposure", "start")
        assert client.client_mode == "ContinuousExposure"
        assert client.status.stage == "ContinuousExposure"

    def test_rtsp_sets_streaming(self, client):
        client._update_client_mode("RTSP", "start")
        assert client.client_mode == "Streaming"
        assert client.status.stage == "RTSP"

    def test_stack(self, client):
        client._update_client_mode("Stack", "start")
        assert client.client_mode == "Stacking"
        assert client.status.stage == "Stack"

    def test_autogoto(self, client):
        client._update_client_mode("AutoGoto", "start")
        assert client.client_mode == "AutoGoto"
        assert client.status.stage == "AutoGoto"

    def test_scope_goto_also_sets_autogoto(self, client):
        client._update_client_mode("ScopeGoto")
        assert client.client_mode == "AutoGoto"

    def test_autofocus(self, client):
        client._update_client_mode("AutoFocus", "start")
        assert client.client_mode == "AutoFocus"
        assert client.status.stage == "AutoFocus"

    def test_initialise(self, client):
        client._update_client_mode("Initialise", "start")
        assert client.client_mode == "Initialise"
        assert client.status.stage == "Initialise"

    def test_cancel_sets_idle(self, client):
        client.client_mode = "Stack"
        client._update_client_mode("Stack", "cancel")
        assert client.client_mode == "Idle"
        assert client.status.stage == "Idle"

    def test_unknown_stage_defaults_to_continuous_exposure_not_idle(self, client):
        """BUG: unknown stage should default to Idle per the comment,
        but the code defaults to ContinuousExposure."""
        client._update_client_mode("UnknownStage", "start")
        # Document the actual (buggy) behavior:
        assert client.client_mode == "ContinuousExposure"
        # This assertion demonstrates the bug - comment in source says "Idle"

    @pytest.mark.asyncio
    async def test_mode_change_emits_event(self, client):
        emitted = []

        async def handler(e):
            emitted.append(e)

        client.event_bus.subscribe("ClientModeChanged", handler)
        client.client_mode = "Idle"
        client._update_client_mode("Stack", "start")
        await asyncio.sleep(0.01)  # let tasks run

        assert len(emitted) == 1
        assert emitted[0].params["existing"] == "Idle"
        assert emitted[0].params["new_mode"] == "Stacking"

    @pytest.mark.asyncio
    async def test_no_event_when_mode_unchanged(self, client):
        emitted = []

        async def handler(e):
            emitted.append(e)

        client.event_bus.subscribe("ClientModeChanged", handler)
        client.client_mode = "Stacking"
        client._update_client_mode("Stack", "start")
        await asyncio.sleep(0.01)

        assert len(emitted) == 0


# ---------------------------------------------------------------------------
# _process_view_state
# ---------------------------------------------------------------------------

class TestProcessViewState:
    def test_none_response_is_safe(self, client):
        client._process_view_state(None)  # should not raise

    def test_no_view_key_in_result(self, client):
        resp = make_response(result={"Other": {}})
        client._process_view_state(resp)  # should not raise

    def test_empty_result(self, client):
        resp = make_response(result={})
        client._process_view_state(resp)  # should not raise

    def test_view_key_calls_process_view(self, client):
        with patch.object(client, "_process_view") as mock_pv:
            resp = make_response(result={"View": {"stage": "Stack", "state": "complete", "mode": "star"}})
            client._process_view_state(resp)
            mock_pv.assert_called_once_with({"stage": "Stack", "state": "complete", "mode": "star"})

    def test_null_result(self, client):
        resp = make_response(result=None)
        client._process_view_state(resp)  # should not raise


# ---------------------------------------------------------------------------
# _process_view
# ---------------------------------------------------------------------------

class TestProcessView:
    def test_none_data_is_safe(self, client):
        client._process_view(None)

    def test_empty_dict_is_safe(self, client):
        client._process_view({})

    def test_updates_target_name_and_gain(self, client):
        client._process_view({
            "target_name": "M42",
            "gain": 80,
            "stage": "Stack",
            "state": "working",
            "mode": "star",
        })
        assert client.status.target_name == "M42"
        assert client.status.gain == 80

    def test_updates_client_mode(self, client):
        with patch.object(client, "_update_client_mode") as mock_update:
            client._process_view({
                "stage": "Stack",
                "state": "working",
                "mode": "star",
                "gain": 0,
                "target_name": "",
            })
            mock_update.assert_called_once_with("Stack", "working", "star")


# ---------------------------------------------------------------------------
# _process_device_state
# ---------------------------------------------------------------------------

class TestProcessDeviceState:
    def test_none_is_safe(self, client):
        client._process_device_state(None)

    def test_updates_temperature(self, client):
        # pi_status must NOT include Event/Timestamp - those are added by the caller
        resp = make_response(result={
            "pi_status": {
                "temp": 42.5,
                "charger_status": "Charging",
                "charge_online": True,
                "battery_capacity": 75,
            }
        })
        client._process_device_state(resp)
        assert client.status.temp == 42.5
        assert client.status.charger_status == "Charging"
        assert client.status.battery_capacity == 75

    def test_null_result_logs_error(self, client):
        resp = make_response(result=None)
        client._process_device_state(resp)  # should not raise


# ---------------------------------------------------------------------------
# _process_focuser_position
# ---------------------------------------------------------------------------

class TestProcessFocuserPosition:
    def test_none_is_safe(self, client):
        client._process_focuser_position(None)

    def test_updates_focus_position(self, client):
        resp = make_response(result=5000)
        client._process_focuser_position(resp)
        assert client.status.focus_position == 5000

    def test_null_result_does_not_update(self, client):
        client.status.focus_position = 1234
        resp = make_response(result=None)
        client._process_focuser_position(resp)
        assert client.status.focus_position == 1234


# ---------------------------------------------------------------------------
# _process_current_coords
# ---------------------------------------------------------------------------

class TestProcessCurrentCoords:
    def test_none_is_safe(self, client):
        client._process_current_coords(None)

    def test_updates_ra_dec(self, client):
        resp = make_response(result={"ra": 1.5, "dec": 45.0})
        client._process_current_coords(resp)
        assert abs(client.status.ra - 22.5) < 0.001  # ra * 15.0
        assert client.status.dec == 45.0

    def test_ra_converts_hours_to_degrees(self, client):
        resp = make_response(result={"ra": 12.0, "dec": 0.0})
        client._process_current_coords(resp)
        assert client.status.ra == 180.0


# ---------------------------------------------------------------------------
# _handle_event (async)
# ---------------------------------------------------------------------------

class TestHandleEvent:
    @pytest.mark.asyncio
    async def test_pistatus_event_updates_status(self, client):
        event_str = json.dumps({
            "Event": "PiStatus",
            "Timestamp": "2024-01-01T00:00:00",
            "temp": 35.0,
            "charger_status": "Full",
            "charge_online": True,
            "battery_capacity": 100,
        })
        await client._handle_event(event_str)
        assert client.status.temp == 35.0
        assert client.status.charger_status == "Full"

    @pytest.mark.asyncio
    async def test_stack_event_updates_frame_counts(self, client):
        event_str = json.dumps({
            "Event": "Stack",
            "Timestamp": "2024-01-01T00:00:00",
            "stacked_frame": 42,
            "dropped_frame": 3,
        })
        await client._handle_event(event_str)
        assert client.status.stacked_frame == 42
        assert client.status.dropped_frame == 3

    @pytest.mark.asyncio
    async def test_stack_event_emits_to_bus(self, client):
        received = []

        async def handler(e):
            received.append(e)

        client.event_bus.subscribe("Stack", handler)

        event_str = json.dumps({
            "Event": "Stack",
            "Timestamp": "2024-01-01T00:00:00",
            "stacked_frame": 10,
            "dropped_frame": 0,
        })
        await client._handle_event(event_str)
        await asyncio.sleep(0.01)  # let emitted task run
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_focusermove_updates_position(self, client):
        event_str = json.dumps({
            "Event": "FocuserMove",
            "Timestamp": "2024-01-01T00:00:00",
            "position": 3000,
        })
        await client._handle_event(event_str)
        assert client.status.focus_position == 3000

    @pytest.mark.asyncio
    async def test_wheelmove_complete_sets_lp_filter(self, client):
        event_str = json.dumps({
            "Event": "WheelMove",
            "Timestamp": "2024-01-01T00:00:00",
            "state": "complete",
            "position": 2,
        })
        await client._handle_event(event_str)
        assert client.status.lp_filter is True

    @pytest.mark.asyncio
    async def test_wheelmove_complete_position_1_clears_lp_filter(self, client):
        client.status.lp_filter = True
        event_str = json.dumps({
            "Event": "WheelMove",
            "Timestamp": "2024-01-01T00:00:00",
            "state": "complete",
            "position": 1,
        })
        await client._handle_event(event_str)
        assert client.status.lp_filter is False

    @pytest.mark.asyncio
    async def test_view_event_calls_process_view(self, client):
        """BUG TEST: View event handler calls parser.event.dict() which is
        deprecated in Pydantic v2 (should be model_dump()). It still works
        but emits a deprecation warning. This test documents the current behavior."""
        with patch.object(client, "_process_view") as mock_pv:
            event_str = json.dumps({
                "Event": "View",
                "Timestamp": "2024-01-01T00:00:00",
                "state": "working",
                "mode": "star",
                "cam_id": 0,
                "lp_filter": False,
                "gain": 0,
            })
            await client._handle_event(event_str)
            mock_pv.assert_called_once()

    @pytest.mark.asyncio
    async def test_malformed_json_does_not_crash(self, client):
        await client._handle_event("not json {{{")
        # Should log error and continue, not raise

    @pytest.mark.asyncio
    async def test_unknown_event_emits_to_bus(self, client):
        received = []
        client.event_bus.subscribe("SelectCamera", lambda e: received.append(e))

        event_str = json.dumps({
            "Event": "SelectCamera",
            "Timestamp": "2024-01-01T00:00:00",
            "selected_cam": "View",
        })
        await client._handle_event(event_str)
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_event_added_to_recent_events(self, client):
        event_str = json.dumps({
            "Event": "PiStatus",
            "Timestamp": "2024-01-01T00:00:00",
        })
        await client._handle_event(event_str)
        assert len(client.recent_events) == 1

    @pytest.mark.asyncio
    async def test_recent_events_capped_at_maxlen(self, client):
        for i in range(10):
            event_str = json.dumps({
                "Event": "PiStatus",
                "Timestamp": f"2024-01-01T00:00:0{i % 10}",
            })
            await client._handle_event(event_str)
        assert len(client.recent_events) == 5  # deque maxlen


# ---------------------------------------------------------------------------
# send() - debug print bug
# ---------------------------------------------------------------------------

class TestSendDebugPrint:
    @pytest.mark.asyncio
    async def test_send_contains_debug_print(self, client, capsys):
        """BUG: client.send() contains a bare print() statement.
        This test documents the bug - remove when print() is removed."""
        from scopinator.seestar.commands.simple import GetTime

        cmd = GetTime()
        client.connection.write = AsyncMock()
        await client.send(cmd)

        captured = capsys.readouterr()
        assert "sending" in captured.out  # Bug: print() exists in production code


# ---------------------------------------------------------------------------
# send_and_validate - non-dict result bug
# ---------------------------------------------------------------------------

class TestSendAndValidate:
    # patch.object on Pydantic model instances fails (Pydantic rejects non-field setattr).
    # We patch at the class level instead, using a lambda to return per-test values.

    @pytest.mark.asyncio
    async def test_valid_dict_result_with_success(self, client):
        resp = make_response(result={"success": True})

        from scopinator.seestar.commands.simple import GetTime
        from scopinator.seestar.client import SeestarClient
        with patch.object(SeestarClient, "send_and_recv", new=AsyncMock(return_value=resp)):
            result = await client.send_and_validate(GetTime())
        assert result is resp

    @pytest.mark.asyncio
    async def test_non_dict_result_raises_attribute_error(self, client):
        """BUG: send_and_validate calls result.get('success') but result can be an int."""
        resp = make_response(result=42)  # int, not dict

        from scopinator.seestar.commands.simple import GetTime
        from scopinator.seestar.client import SeestarClient
        with patch.object(SeestarClient, "send_and_recv", new=AsyncMock(return_value=resp)):
            with pytest.raises(AttributeError):
                await client.send_and_validate(GetTime())

    @pytest.mark.asyncio
    async def test_none_response_returns_none(self, client):
        from scopinator.seestar.commands.simple import GetTime
        from scopinator.seestar.client import SeestarClient
        with patch.object(SeestarClient, "send_and_recv", new=AsyncMock(return_value=None)):
            result = await client.send_and_validate(GetTime())
        assert result is None

    @pytest.mark.asyncio
    async def test_result_success_false_returns_none(self, client):
        resp = make_response(result={"success": False, "error": "something failed"})

        from scopinator.seestar.commands.simple import GetTime
        from scopinator.seestar.client import SeestarClient
        with patch.object(SeestarClient, "send_and_recv", new=AsyncMock(return_value=resp)):
            result = await client.send_and_validate(GetTime())
        assert result is None


# ---------------------------------------------------------------------------
# get_message_history / analytics
# ---------------------------------------------------------------------------

class TestMessageHistory:
    def test_get_message_history_empty(self, client):
        assert client.get_message_history() == []

    def test_message_history_returns_list_of_dicts(self, client):
        from scopinator.seestar.client import TelescopeMessage
        from datetime import datetime

        client.message_history.append(TelescopeMessage(
            timestamp=datetime.now().isoformat(),
            direction="sent",
            message='{"method":"test"}',
        ))
        history = client.get_message_history()
        assert len(history) == 1
        assert history[0]["direction"] == "sent"

    def test_get_message_analytics_empty(self, client):
        # Should return a dict (may be empty or have zero counts)
        analytics = client.get_message_analytics()
        assert isinstance(analytics, dict)


# ---------------------------------------------------------------------------
# wait_for_event_completion
# ---------------------------------------------------------------------------

class TestWaitForEventCompletion:
    @pytest.mark.asyncio
    async def test_raises_if_no_event_bus(self, client):
        client.event_bus = None
        with pytest.raises(ValueError, match="No event bus"):
            await client.wait_for_event_completion("AutoGoto")

    @pytest.mark.asyncio
    async def test_complete_state_returns_success(self, client):
        from scopinator.seestar.events import AutoGotoEvent

        async def trigger():
            await asyncio.sleep(0.01)
            event = AutoGotoEvent(Timestamp="2024-01-01T00:00:00", state="complete")
            client.event_bus.emit("AutoGoto", event)

        asyncio.create_task(trigger())
        success, error = await client.wait_for_event_completion("AutoGoto", timeout=1.0)
        assert success is True
        assert error is None

    @pytest.mark.asyncio
    async def test_fail_state_returns_failure(self, client):
        from scopinator.seestar.events import AutoGotoEvent

        async def trigger():
            await asyncio.sleep(0.01)
            event = AutoGotoEvent(
                Timestamp="2024-01-01T00:00:00",
                state="fail",
                error="object below horizon",
            )
            client.event_bus.emit("AutoGoto", event)

        asyncio.create_task(trigger())
        success, error = await client.wait_for_event_completion("AutoGoto", timeout=1.0)
        assert success is False
        assert error == "object below horizon"

    @pytest.mark.asyncio
    async def test_timeout_raises(self, client):
        with pytest.raises(asyncio.TimeoutError):
            await client.wait_for_event_completion("AutoGoto", timeout=0.05)

    @pytest.mark.asyncio
    async def test_listener_cleaned_up_after_completion(self, client):
        from scopinator.seestar.events import AutoGotoEvent

        async def trigger():
            await asyncio.sleep(0.01)
            event = AutoGotoEvent(Timestamp="2024-01-01T00:00:00", state="complete")
            client.event_bus.emit("AutoGoto", event)

        asyncio.create_task(trigger())
        await client.wait_for_event_completion("AutoGoto", timeout=1.0)
        # Listener should be removed after completion
        assert "AutoGoto" not in client.event_bus.listeners
