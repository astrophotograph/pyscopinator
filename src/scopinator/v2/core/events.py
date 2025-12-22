"""Unified event system for V2.

This module provides a protocol-agnostic event system that normalizes
events from different backends (Seestar, ASCOM Alpaca, INDI) into a
common format.
"""

import asyncio
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

from pydantic import BaseModel, Field

from scopinator.v2.core.types import Coordinates, SlewState


class EventType(str, Enum):
    """Unified event types."""

    # Connection events
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTION_ERROR = "connection_error"
    RECONNECTING = "reconnecting"

    # Mount events
    SLEW_STARTED = "slew_started"
    SLEW_PROGRESS = "slew_progress"
    SLEW_COMPLETED = "slew_completed"
    SLEW_ABORTED = "slew_aborted"
    TRACKING_CHANGED = "tracking_changed"
    COORDINATES_UPDATED = "coordinates_updated"
    PARK_STARTED = "park_started"
    PARK_COMPLETED = "park_completed"
    UNPARK_COMPLETED = "unpark_completed"

    # Camera events
    EXPOSURE_STARTED = "exposure_started"
    EXPOSURE_PROGRESS = "exposure_progress"
    EXPOSURE_COMPLETED = "exposure_completed"
    EXPOSURE_ABORTED = "exposure_aborted"
    IMAGE_READY = "image_ready"
    DOWNLOAD_PROGRESS = "download_progress"
    COOLER_CHANGED = "cooler_changed"

    # Stacking events (for smart scopes)
    STACK_STARTED = "stack_started"
    STACK_FRAME = "stack_frame"
    STACK_COMPLETED = "stack_completed"

    # Focuser events
    FOCUSER_MOVING = "focuser_moving"
    FOCUSER_STOPPED = "focuser_stopped"
    FOCUSER_POSITION_CHANGED = "focuser_position_changed"

    # Filter wheel events
    FILTER_CHANGING = "filter_changing"
    FILTER_CHANGED = "filter_changed"

    # General events
    STATUS_UPDATE = "status_update"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class UnifiedEvent(BaseModel):
    """Base unified event."""

    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source_device: str = Field(default="", description="Device that generated the event")
    source_backend: str = Field(default="", description="Backend type (seestar, alpaca, indi)")
    data: dict[str, Any] = Field(default_factory=dict, description="Event-specific data")

    model_config = {"use_enum_values": False}


class SlewEvent(UnifiedEvent):
    """Slew-related event with coordinate information."""

    target_coordinates: Optional[Coordinates] = None
    current_coordinates: Optional[Coordinates] = None
    state: SlewState = SlewState.IDLE
    distance_remaining: Optional[float] = Field(
        None, description="Remaining distance in degrees"
    )


class ExposureEvent(UnifiedEvent):
    """Exposure-related event with progress information."""

    duration_seconds: float = Field(default=0.0, description="Total exposure duration")
    elapsed_seconds: float = Field(default=0.0, description="Elapsed time")
    progress: float = Field(default=0.0, ge=0.0, le=1.0, description="Progress 0.0 to 1.0")
    frames_captured: int = Field(default=0, description="Number of frames captured")
    frames_stacked: int = Field(default=0, description="Number of frames stacked")
    frames_dropped: int = Field(default=0, description="Number of frames dropped")


class FocuserEvent(UnifiedEvent):
    """Focuser-related event with position information."""

    position: int = Field(default=0, description="Current position")
    target_position: Optional[int] = Field(None, description="Target position if moving")
    temperature: Optional[float] = Field(None, description="Temperature in Celsius")


class FilterEvent(UnifiedEvent):
    """Filter wheel-related event."""

    position: int = Field(default=0, description="Filter position (0-indexed)")
    filter_name: Optional[str] = Field(None, description="Filter name")
    previous_position: Optional[int] = Field(None, description="Previous position")


# Type alias for event handlers
EventHandler = Callable[[UnifiedEvent], Coroutine[Any, Any, None]]


class UnifiedEventBus:
    """Unified event bus that normalizes events from different backends.

    This event bus provides a common interface for subscribing to and
    emitting events, regardless of the underlying protocol.

    Example:
        bus = UnifiedEventBus()

        async def on_slew(event: SlewEvent):
            print(f"Slewing to {event.target_coordinates}")

        bus.subscribe(EventType.SLEW_STARTED, on_slew)
        await bus.emit(SlewEvent(event_type=EventType.SLEW_STARTED, ...))
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, set[EventHandler]] = {}
        self._global_handlers: set[EventHandler] = set()
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe to a specific event type.

        Args:
            event_type: The type of event to subscribe to
            handler: Async function to call when event is emitted
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = set()
        self._handlers[event_type].add(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to all events.

        Args:
            handler: Async function to call for all events
        """
        self._global_handlers.add(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Unsubscribe from a specific event type.

        Args:
            event_type: The type of event to unsubscribe from
            handler: The handler to remove
        """
        if event_type in self._handlers:
            self._handlers[event_type].discard(handler)

    def unsubscribe_all(self, handler: EventHandler) -> None:
        """Unsubscribe from all events.

        Args:
            handler: The handler to remove
        """
        self._global_handlers.discard(handler)

    def clear(self) -> None:
        """Remove all handlers."""
        self._handlers.clear()
        self._global_handlers.clear()

    async def emit(self, event: UnifiedEvent) -> None:
        """Emit an event to all subscribers.

        Handlers are called concurrently. Exceptions in handlers are
        caught and logged but do not prevent other handlers from running.

        Args:
            event: The event to emit
        """
        handlers: set[EventHandler] = set(self._global_handlers)
        if event.event_type in self._handlers:
            handlers.update(self._handlers[event.event_type])

        if not handlers:
            return

        # Run all handlers concurrently, catching exceptions
        results = await asyncio.gather(
            *[self._safe_call(handler, event) for handler in handlers],
            return_exceptions=True,
        )

        # Log any exceptions (but don't raise)
        for result in results:
            if isinstance(result, Exception):
                # In production, this would use proper logging
                pass

    async def _safe_call(self, handler: EventHandler, event: UnifiedEvent) -> None:
        """Safely call a handler, catching exceptions."""
        try:
            await handler(event)
        except Exception:
            # Re-raise to be caught by gather
            raise

    def emit_nowait(self, event: UnifiedEvent) -> None:
        """Emit an event without waiting for handlers to complete.

        Creates an asyncio task to emit the event in the background.

        Args:
            event: The event to emit
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.emit(event))
        except RuntimeError:
            # No running loop - skip emission
            pass

    def handler_count(self, event_type: Optional[EventType] = None) -> int:
        """Get number of registered handlers.

        Args:
            event_type: If provided, count handlers for this type only.
                       If None, count all handlers.

        Returns:
            Number of registered handlers
        """
        if event_type is None:
            total = len(self._global_handlers)
            for handlers in self._handlers.values():
                total += len(handlers)
            return total
        return len(self._handlers.get(event_type, set())) + len(self._global_handlers)
