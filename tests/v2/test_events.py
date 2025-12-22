"""Tests for V2 event system."""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

from scopinator.v2.core.events import (
    EventType,
    UnifiedEvent,
    SlewEvent,
    ExposureEvent,
    FocuserEvent,
    FilterEvent,
    UnifiedEventBus,
)
from scopinator.v2.core.types import Coordinates, SlewState


class TestEventTypes:
    """Tests for EventType enum."""

    def test_connection_event_types(self):
        """Test connection event types exist."""
        assert EventType.CONNECTED.value == "connected"
        assert EventType.DISCONNECTED.value == "disconnected"
        assert EventType.CONNECTION_ERROR.value == "connection_error"

    def test_mount_event_types(self):
        """Test mount event types exist."""
        assert EventType.SLEW_STARTED.value == "slew_started"
        assert EventType.SLEW_COMPLETED.value == "slew_completed"
        assert EventType.SLEW_ABORTED.value == "slew_aborted"
        assert EventType.TRACKING_CHANGED.value == "tracking_changed"
        assert EventType.PARK_STARTED.value == "park_started"
        assert EventType.PARK_COMPLETED.value == "park_completed"

    def test_camera_event_types(self):
        """Test camera event types exist."""
        assert EventType.EXPOSURE_STARTED.value == "exposure_started"
        assert EventType.EXPOSURE_COMPLETED.value == "exposure_completed"
        assert EventType.IMAGE_READY.value == "image_ready"

    def test_focuser_event_types(self):
        """Test focuser event types exist."""
        assert EventType.FOCUSER_MOVING.value == "focuser_moving"
        assert EventType.FOCUSER_STOPPED.value == "focuser_stopped"

    def test_filter_event_types(self):
        """Test filter wheel event types exist."""
        assert EventType.FILTER_CHANGING.value == "filter_changing"
        assert EventType.FILTER_CHANGED.value == "filter_changed"


class TestUnifiedEvent:
    """Tests for UnifiedEvent base class."""

    def test_create_event(self):
        """Test creating a basic event."""
        event = UnifiedEvent(
            event_type=EventType.CONNECTED,
            source_device="telescope",
        )
        assert event.event_type == EventType.CONNECTED
        assert event.source_device == "telescope"
        assert event.timestamp is not None

    def test_event_has_timestamp(self):
        """Test event has automatic timestamp."""
        before = datetime.utcnow()
        event = UnifiedEvent(
            event_type=EventType.CONNECTED,
            source_device="test",
        )
        after = datetime.utcnow()
        assert before <= event.timestamp <= after

    def test_event_with_data(self):
        """Test event with custom data."""
        event = UnifiedEvent(
            event_type=EventType.STATUS_UPDATE,
            source_device="mount",
            source_backend="seestar",
            data={"temperature": 25.5, "battery": 80},
        )
        assert event.data["temperature"] == 25.5
        assert event.data["battery"] == 80
        assert event.source_backend == "seestar"


class TestSlewEvent:
    """Tests for SlewEvent."""

    def test_slew_event_creation(self):
        """Test creating a slew event."""
        target = Coordinates(ra=83.63, dec=22.01)
        event = SlewEvent(
            event_type=EventType.SLEW_STARTED,
            source_device="mount",
            target_coordinates=target,
            state=SlewState.SLEWING,
        )
        assert event.event_type == EventType.SLEW_STARTED
        assert event.target_coordinates == target
        assert event.state == SlewState.SLEWING

    def test_slew_event_with_current_position(self):
        """Test slew event with current position."""
        target = Coordinates(ra=100.0, dec=30.0)
        current = Coordinates(ra=90.0, dec=25.0)
        event = SlewEvent(
            event_type=EventType.SLEW_PROGRESS,
            source_device="mount",
            target_coordinates=target,
            current_coordinates=current,
            distance_remaining=10.5,
        )
        assert event.current_coordinates == current
        assert event.distance_remaining == 10.5

    def test_slew_completed_event(self):
        """Test slew completed event."""
        final_pos = Coordinates(ra=83.63, dec=22.01)
        event = SlewEvent(
            event_type=EventType.SLEW_COMPLETED,
            source_device="mount",
            current_coordinates=final_pos,
            state=SlewState.TRACKING,
        )
        assert event.event_type == EventType.SLEW_COMPLETED
        assert event.state == SlewState.TRACKING


class TestExposureEvent:
    """Tests for ExposureEvent."""

    def test_exposure_started_event(self):
        """Test exposure started event."""
        event = ExposureEvent(
            event_type=EventType.EXPOSURE_STARTED,
            source_device="camera",
            duration_seconds=30.0,
        )
        assert event.event_type == EventType.EXPOSURE_STARTED
        assert event.duration_seconds == 30.0
        assert event.progress == 0.0

    def test_exposure_progress_event(self):
        """Test exposure progress event."""
        event = ExposureEvent(
            event_type=EventType.EXPOSURE_PROGRESS,
            source_device="camera",
            duration_seconds=30.0,
            elapsed_seconds=15.0,
            progress=0.5,
        )
        assert event.elapsed_seconds == 15.0
        assert event.progress == 0.5

    def test_exposure_completed_event(self):
        """Test exposure completed event."""
        event = ExposureEvent(
            event_type=EventType.EXPOSURE_COMPLETED,
            source_device="camera",
            duration_seconds=30.0,
            elapsed_seconds=30.0,
            progress=1.0,
            frames_captured=1,
        )
        assert event.progress == 1.0
        assert event.frames_captured == 1

    def test_stacking_event(self):
        """Test stacking progress event."""
        event = ExposureEvent(
            event_type=EventType.STACK_FRAME,
            source_device="camera",
            duration_seconds=10.0,
            frames_captured=50,
            frames_stacked=48,
            frames_dropped=2,
        )
        assert event.frames_captured == 50
        assert event.frames_stacked == 48
        assert event.frames_dropped == 2


class TestFocuserEvent:
    """Tests for FocuserEvent."""

    def test_focuser_moving_event(self):
        """Test focuser moving event."""
        event = FocuserEvent(
            event_type=EventType.FOCUSER_MOVING,
            source_device="focuser",
            position=4500,
            target_position=5000,
        )
        assert event.event_type == EventType.FOCUSER_MOVING
        assert event.position == 4500
        assert event.target_position == 5000

    def test_focuser_stopped_event(self):
        """Test focuser stopped event."""
        event = FocuserEvent(
            event_type=EventType.FOCUSER_STOPPED,
            source_device="focuser",
            position=5000,
            temperature=15.5,
        )
        assert event.position == 5000
        assert event.temperature == 15.5


class TestFilterEvent:
    """Tests for FilterEvent."""

    def test_filter_changing_event(self):
        """Test filter changing event."""
        event = FilterEvent(
            event_type=EventType.FILTER_CHANGING,
            source_device="filterwheel",
            position=2,
            filter_name="Red",
            previous_position=0,
        )
        assert event.event_type == EventType.FILTER_CHANGING
        assert event.position == 2
        assert event.filter_name == "Red"
        assert event.previous_position == 0

    def test_filter_changed_event(self):
        """Test filter changed event."""
        event = FilterEvent(
            event_type=EventType.FILTER_CHANGED,
            source_device="filterwheel",
            position=2,
            filter_name="Red",
        )
        assert event.event_type == EventType.FILTER_CHANGED
        assert event.position == 2


class TestUnifiedEventBus:
    """Tests for UnifiedEventBus."""

    @pytest.fixture
    def event_bus(self):
        """Create a fresh event bus for each test."""
        return UnifiedEventBus()

    def test_create_event_bus(self, event_bus):
        """Test creating an event bus."""
        assert event_bus is not None
        assert event_bus.handler_count() == 0

    def test_subscribe_handler(self, event_bus):
        """Test subscribing a handler."""
        handler = AsyncMock()
        event_bus.subscribe(EventType.SLEW_STARTED, handler)
        assert event_bus.handler_count(EventType.SLEW_STARTED) == 1

    def test_unsubscribe_handler(self, event_bus):
        """Test unsubscribing a handler."""
        handler = AsyncMock()
        event_bus.subscribe(EventType.SLEW_STARTED, handler)
        event_bus.unsubscribe(EventType.SLEW_STARTED, handler)
        assert event_bus.handler_count(EventType.SLEW_STARTED) == 0

    @pytest.mark.asyncio
    async def test_emit_event(self, event_bus):
        """Test emitting an event."""
        received_events = []

        async def handler(event):
            received_events.append(event)

        event_bus.subscribe(EventType.CONNECTED, handler)

        event = UnifiedEvent(
            event_type=EventType.CONNECTED,
            source_device="mount",
        )
        await event_bus.emit(event)

        assert len(received_events) == 1
        assert received_events[0] == event

    @pytest.mark.asyncio
    async def test_multiple_handlers(self, event_bus):
        """Test multiple handlers receive the same event."""
        received1 = []
        received2 = []

        async def handler1(event):
            received1.append(event)

        async def handler2(event):
            received2.append(event)

        event_bus.subscribe(EventType.EXPOSURE_COMPLETED, handler1)
        event_bus.subscribe(EventType.EXPOSURE_COMPLETED, handler2)

        event = ExposureEvent(
            event_type=EventType.EXPOSURE_COMPLETED,
            source_device="camera",
            duration_seconds=30.0,
        )
        await event_bus.emit(event)

        assert len(received1) == 1
        assert len(received2) == 1

    @pytest.mark.asyncio
    async def test_handler_exception_isolated(self, event_bus):
        """Test that one handler's exception doesn't affect others."""
        received = []

        async def bad_handler(event):
            raise ValueError("Handler error")

        async def good_handler(event):
            received.append(event)

        event_bus.subscribe(EventType.ERROR, bad_handler)
        event_bus.subscribe(EventType.ERROR, good_handler)

        event = UnifiedEvent(
            event_type=EventType.ERROR,
            source_device="test",
            data={"message": "Test error"},
        )
        await event_bus.emit(event)

        # Good handler should still receive the event
        assert len(received) == 1

    def test_subscribe_all(self, event_bus):
        """Test subscribing to all events."""
        handler = AsyncMock()
        event_bus.subscribe_all(handler)
        # handler_count() without arg counts all handlers
        assert event_bus.handler_count() > 0

    @pytest.mark.asyncio
    async def test_global_handler_receives_all(self, event_bus):
        """Test global handler receives all event types."""
        received = []

        async def global_handler(event):
            received.append(event)

        event_bus.subscribe_all(global_handler)

        # Emit different event types
        await event_bus.emit(UnifiedEvent(
            event_type=EventType.CONNECTED,
            source_device="mount",
        ))
        await event_bus.emit(ExposureEvent(
            event_type=EventType.EXPOSURE_STARTED,
            source_device="camera",
            duration_seconds=10.0,
        ))

        assert len(received) == 2

    def test_clear_handlers(self, event_bus):
        """Test clearing all handlers."""
        event_bus.subscribe(EventType.CONNECTED, AsyncMock())
        event_bus.subscribe(EventType.DISCONNECTED, AsyncMock())
        event_bus.subscribe_all(AsyncMock())

        event_bus.clear()

        assert event_bus.handler_count() == 0

    @pytest.mark.asyncio
    async def test_emit_no_handlers(self, event_bus):
        """Test emitting event with no handlers doesn't raise."""
        event = UnifiedEvent(
            event_type=EventType.STATUS_UPDATE,
            source_device="test",
        )
        # Should not raise
        await event_bus.emit(event)
