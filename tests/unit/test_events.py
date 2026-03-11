"""Unit tests for event models and parsing via ParsedEvent discriminated union."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from scopinator.seestar.client import ParsedEvent
from scopinator.seestar.events import (
    AlertEvent,
    AnnotateEvent,
    AnnotateResult,
    AutoFocusEvent,
    AutoGotoEvent,
    AutoGotoStepEvent,
    BaseEvent,
    BatchStackEvent,
    ClientEvent,
    ContinuousExposureEvent,
    DarkLibraryEvent,
    DiskSpaceEvent,
    ExposureEvent,
    FocuserMoveEvent,
    GoPixelEvent,
    InitialiseEvent,
    InternalEvent,
    PiStatusEvent,
    PlateSolveEvent,
    RTSPEvent,
    ScanSunEvent,
    ScopeGotoEvent,
    ScopeHomeEvent,
    ScopeMoveToHorizonEvent,
    ScopeTrackEvent,
    SecondViewEvent,
    SelectCameraEvent,
    SettingEvent,
    StackEvent,
    ThreePPAEvent,
    ViewEvent,
    ViewPlanEvent,
    WheelMoveEvent,
)


def parse(data: dict) -> Any:
    """Parse a dict into a typed event via ParsedEvent discriminator."""
    return ParsedEvent(event=data).event


TIMESTAMP = "2024-01-01T12:00:00"


# ---------------------------------------------------------------------------
# BaseEvent
# ---------------------------------------------------------------------------

class TestBaseEvent:
    def test_requires_event_and_timestamp(self):
        with pytest.raises(ValidationError):
            BaseEvent(Timestamp=TIMESTAMP)  # missing Event

    def test_minimal_construction(self):
        # BaseEvent itself requires Event, but it's overridden by subclasses
        # We test via a concrete subclass
        e = PiStatusEvent(Timestamp=TIMESTAMP)
        assert e.Event == "PiStatus"
        assert e.Timestamp == TIMESTAMP


# ---------------------------------------------------------------------------
# Discriminated union parsing
# ---------------------------------------------------------------------------

class TestParsedEventDiscriminator:
    def test_pistatus(self):
        e = parse({"Event": "PiStatus", "Timestamp": TIMESTAMP})
        assert isinstance(e, PiStatusEvent)

    def test_autogoto(self):
        e = parse({"Event": "AutoGoto", "Timestamp": TIMESTAMP})
        assert isinstance(e, AutoGotoEvent)

    def test_stack(self):
        e = parse({"Event": "Stack", "Timestamp": TIMESTAMP})
        assert isinstance(e, StackEvent)

    def test_focusermove(self):
        e = parse({"Event": "FocuserMove", "Timestamp": TIMESTAMP})
        assert isinstance(e, FocuserMoveEvent)

    def test_wheelmove(self):
        e = parse({"Event": "WheelMove", "Timestamp": TIMESTAMP})
        assert isinstance(e, WheelMoveEvent)

    def test_view(self):
        e = parse({"Event": "View", "Timestamp": TIMESTAMP})
        assert isinstance(e, ViewEvent)

    def test_rtsp(self):
        e = parse({"Event": "RTSP", "Timestamp": TIMESTAMP})
        assert isinstance(e, RTSPEvent)

    def test_autofocus(self):
        e = parse({"Event": "AutoFocus", "Timestamp": TIMESTAMP})
        assert isinstance(e, AutoFocusEvent)

    def test_scopegoto(self):
        e = parse({"Event": "ScopeGoto", "Timestamp": TIMESTAMP})
        assert isinstance(e, ScopeGotoEvent)

    def test_initialise(self):
        e = parse({"Event": "Initialise", "Timestamp": TIMESTAMP})
        assert isinstance(e, InitialiseEvent)

    def test_darklibrary(self):
        e = parse({"Event": "DarkLibrary", "Timestamp": TIMESTAMP})
        assert isinstance(e, DarkLibraryEvent)

    def test_annotate(self):
        e = parse({"Event": "Annotate", "Timestamp": TIMESTAMP})
        assert isinstance(e, AnnotateEvent)

    def test_client_event(self):
        e = parse({"Event": "Client", "Timestamp": TIMESTAMP})
        assert isinstance(e, ClientEvent)

    def test_continuousexposure(self):
        e = parse({"Event": "ContinuousExposure", "Timestamp": TIMESTAMP})
        assert isinstance(e, ContinuousExposureEvent)

    def test_alert(self):
        e = parse({"Event": "Alert", "Timestamp": TIMESTAMP})
        assert isinstance(e, AlertEvent)

    def test_diskspace(self):
        e = parse({"Event": "DiskSpace", "Timestamp": TIMESTAMP})
        assert isinstance(e, DiskSpaceEvent)

    def test_plateSolve(self):
        e = parse({"Event": "PlateSolve", "Timestamp": TIMESTAMP})
        assert isinstance(e, PlateSolveEvent)

    def test_selectcamera(self):
        e = parse({"Event": "SelectCamera", "Timestamp": TIMESTAMP})
        assert isinstance(e, SelectCameraEvent)

    def test_batchstack(self):
        e = parse({"Event": "BatchStack", "Timestamp": TIMESTAMP})
        assert isinstance(e, BatchStackEvent)

    def test_unknown_event_raises_validation_error(self):
        with pytest.raises(ValidationError):
            parse({"Event": "UnknownXYZ", "Timestamp": TIMESTAMP})

    def test_missing_timestamp_raises_validation_error(self):
        with pytest.raises(ValidationError):
            parse({"Event": "PiStatus"})

    def test_missing_event_field_raises_validation_error(self):
        with pytest.raises(ValidationError):
            parse({"Timestamp": TIMESTAMP})


# ---------------------------------------------------------------------------
# PiStatusEvent
# ---------------------------------------------------------------------------

class TestPiStatusEvent:
    def test_minimal(self):
        e = PiStatusEvent(Timestamp=TIMESTAMP)
        assert e.temp is None
        assert e.charger_status is None
        assert e.charge_online is None
        assert e.battery_capacity is None

    def test_full(self):
        e = PiStatusEvent(
            Timestamp=TIMESTAMP,
            temp=35.2,
            charger_status="Charging",
            charge_online=True,
            battery_capacity=80,
        )
        assert e.temp == 35.2
        assert e.charger_status == "Charging"
        assert e.charge_online is True
        assert e.battery_capacity == 80

    def test_invalid_charger_status(self):
        with pytest.raises(ValidationError):
            PiStatusEvent(Timestamp=TIMESTAMP, charger_status="InvalidStatus")

    def test_via_discriminator(self):
        e = parse({
            "Event": "PiStatus",
            "Timestamp": TIMESTAMP,
            "temp": 25.0,
            "charger_status": "Full",
        })
        assert isinstance(e, PiStatusEvent)
        assert e.temp == 25.0


# ---------------------------------------------------------------------------
# StackEvent
# ---------------------------------------------------------------------------

class TestStackEvent:
    def test_defaults(self):
        e = StackEvent(Timestamp=TIMESTAMP)
        assert e.stacked_frame == 0
        assert e.dropped_frame == 0
        assert e.can_annotate is False

    def test_with_frames(self):
        e = StackEvent(
            Timestamp=TIMESTAMP,
            stacked_frame=50,
            dropped_frame=2,
            can_annotate=True,
        )
        assert e.stacked_frame == 50
        assert e.dropped_frame == 2

    def test_frame_complete_state(self):
        e = StackEvent(Timestamp=TIMESTAMP, state="frame_complete")
        assert e.state == "frame_complete"


# ---------------------------------------------------------------------------
# AutoGotoEvent
# ---------------------------------------------------------------------------

class TestAutoGotoEvent:
    def test_defaults(self):
        e = AutoGotoEvent(Timestamp=TIMESTAMP)
        assert e.state is None
        assert e.error is None
        assert e.route == []

    def test_with_error(self):
        e = AutoGotoEvent(Timestamp=TIMESTAMP, state="fail", error="below horizon")
        assert e.state == "fail"
        assert e.error == "below horizon"

    def test_complete_state(self):
        e = AutoGotoEvent(Timestamp=TIMESTAMP, state="complete")
        assert e.state == "complete"


# ---------------------------------------------------------------------------
# FocuserMoveEvent
# ---------------------------------------------------------------------------

class TestFocuserMoveEvent:
    def test_defaults(self):
        e = FocuserMoveEvent(Timestamp=TIMESTAMP)
        assert e.position == 0
        assert e.state is None

    def test_with_position(self):
        e = FocuserMoveEvent(Timestamp=TIMESTAMP, state="complete", position=4500)
        assert e.position == 4500


# ---------------------------------------------------------------------------
# WheelMoveEvent
# ---------------------------------------------------------------------------

class TestWheelMoveEvent:
    def test_defaults(self):
        e = WheelMoveEvent(Timestamp=TIMESTAMP)
        assert e.position == 0
        assert e.state is None

    def test_filter_position_2(self):
        e = WheelMoveEvent(Timestamp=TIMESTAMP, state="complete", position=2)
        assert e.position == 2


# ---------------------------------------------------------------------------
# AnnotateEvent / AnnotateResult
# ---------------------------------------------------------------------------

class TestAnnotateEvent:
    def test_defaults(self):
        e = AnnotateEvent(Timestamp=TIMESTAMP)
        assert e.result is None

    def test_with_result(self):
        result = AnnotateResult(image_size=[1920, 1080], image_id=1)
        e = AnnotateEvent(Timestamp=TIMESTAMP, result=result)
        assert e.result.image_id == 1
        assert e.result.image_size == [1920, 1080]


class TestAnnotateResult:
    def test_empty(self):
        r = AnnotateResult()
        assert r.image_size == []
        assert r.annotations == []
        assert r.image_id == 0


# ---------------------------------------------------------------------------
# ScopeGotoEvent
# ---------------------------------------------------------------------------

class TestScopeGotoEvent:
    def test_defaults(self):
        e = ScopeGotoEvent(Timestamp=TIMESTAMP)
        assert e.cur_ra_dec is None
        assert e.dist_deg == 0.0

    def test_with_coordinates(self):
        e = ScopeGotoEvent(
            Timestamp=TIMESTAMP,
            cur_ra_dec={"ra": 10.5, "dec": 45.0},
            dist_deg=2.5,
        )
        assert e.cur_ra_dec.ra == 10.5
        assert e.cur_ra_dec.dec == 45.0
        assert e.dist_deg == 2.5


# ---------------------------------------------------------------------------
# ViewEvent
# ---------------------------------------------------------------------------

class TestViewEvent:
    def test_defaults(self):
        e = ViewEvent(Timestamp=TIMESTAMP)
        assert e.lp_filter is False
        assert e.gain == 0
        assert e.mode == "star"

    def test_lp_filter_set(self):
        e = ViewEvent(Timestamp=TIMESTAMP, lp_filter=True, gain=80)
        assert e.lp_filter is True
        assert e.gain == 80


# ---------------------------------------------------------------------------
# InternalEvent (not in discriminated union - used internally)
# ---------------------------------------------------------------------------

class TestInternalEvent:
    def test_construction(self):
        e = InternalEvent(Timestamp=TIMESTAMP, params={"key": "value"})
        assert e.params["key"] == "value"
        assert e.Event == "Internal"

    def test_internal_not_in_discriminated_union(self):
        """InternalEvent is not part of EventTypes and should not be parseable
        via the discriminated union."""
        with pytest.raises(ValidationError):
            parse({"Event": "Internal", "Timestamp": TIMESTAMP})


# ---------------------------------------------------------------------------
# EventState values
# ---------------------------------------------------------------------------

class TestEventStates:
    @pytest.mark.parametrize("state", ["start", "cancel", "working", "complete", "fail", None])
    def test_valid_states(self, state):
        e = AutoGotoEvent(Timestamp=TIMESTAMP, state=state)
        assert e.state == state

    def test_invalid_state_raises(self):
        with pytest.raises(ValidationError):
            AutoGotoEvent(Timestamp=TIMESTAMP, state="invalid_state_xyz")


# ---------------------------------------------------------------------------
# DiskSpaceEvent
# ---------------------------------------------------------------------------

class TestDiskSpaceEvent:
    def test_defaults(self):
        e = DiskSpaceEvent(Timestamp=TIMESTAMP)
        assert e.used_percent == 0

    def test_with_value(self):
        e = DiskSpaceEvent(Timestamp=TIMESTAMP, used_percent=75)
        assert e.used_percent == 75


# ---------------------------------------------------------------------------
# ClientEvent
# ---------------------------------------------------------------------------

class TestClientEvent:
    def test_defaults(self):
        e = ClientEvent(Timestamp=TIMESTAMP)
        assert e.connected == []
        assert e.master_index is None
        assert e.is_master is None

    def test_with_clients(self):
        e = ClientEvent(Timestamp=TIMESTAMP, connected=["client1", "client2"], is_master=True)
        assert len(e.connected) == 2
        assert e.is_master is True


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

class TestEventSerialization:
    def test_model_dump_roundtrip(self):
        e = PiStatusEvent(
            Timestamp=TIMESTAMP,
            temp=30.0,
            charger_status="Discharging",
            battery_capacity=50,
        )
        data = e.model_dump()
        assert data["temp"] == 30.0
        assert data["Event"] == "PiStatus"

    def test_json_roundtrip(self):
        original = StackEvent(
            Timestamp=TIMESTAMP,
            stacked_frame=10,
            dropped_frame=1,
        )
        json_str = original.model_dump_json()
        restored = StackEvent.model_validate_json(json_str)
        assert restored.stacked_frame == original.stacked_frame
        assert restored.dropped_frame == original.dropped_frame
