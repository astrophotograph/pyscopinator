"""Translates Seestar events to unified V2 events.

This module bridges the existing Seestar event system to the unified
V2 event system, allowing V2 consumers to receive events in a
protocol-agnostic format.
"""

from typing import Any

from scopinator.seestar.events import (
    AutoGotoEvent,
    ContinuousExposureEvent,
    FocuserMoveEvent,
    PiStatusEvent,
    StackEvent,
    ScopeGotoEvent,
    BaseEvent,
)
from scopinator.util.eventbus import EventBus as SeestarEventBus
from scopinator.v2.core.events import (
    EventType,
    ExposureEvent,
    FocuserEvent,
    SlewEvent,
    UnifiedEvent,
    UnifiedEventBus,
)
from scopinator.v2.core.types import Coordinates, SlewState


class SeestarEventTranslator:
    """Bridges Seestar events to the unified V2 event system.

    This translator subscribes to events from the existing Seestar
    EventBus and translates them to UnifiedEvent instances, which
    are then emitted on the V2 UnifiedEventBus.

    Example:
        translator = SeestarEventTranslator(unified_bus)

        # Pass translator.seestar_event_bus to SeestarClient
        client = SeestarClient(
            host="192.168.1.100",
            event_bus=translator.seestar_event_bus
        )
    """

    def __init__(self, unified_event_bus: UnifiedEventBus) -> None:
        """Initialize translator.

        Args:
            unified_event_bus: The V2 event bus to emit translated events to
        """
        self._unified_bus = unified_event_bus

        # Create a Seestar event bus for the client to use
        self._seestar_bus = SeestarEventBus()

        # Subscribe to Seestar events
        self._seestar_bus.add_listener("AutoGoto", self._handle_autogoto)
        self._seestar_bus.add_listener("ScopeGoto", self._handle_scope_goto)
        self._seestar_bus.add_listener("Stack", self._handle_stack)
        self._seestar_bus.add_listener("ContinuousExposure", self._handle_continuous_exposure)
        self._seestar_bus.add_listener("FocuserMove", self._handle_focuser)
        self._seestar_bus.add_listener("PiStatus", self._handle_status)

    @property
    def seestar_event_bus(self) -> SeestarEventBus:
        """Get the Seestar event bus to pass to SeestarClient."""
        return self._seestar_bus

    async def _handle_autogoto(self, event: AutoGotoEvent) -> None:
        """Translate AutoGoto events to SlewEvents."""
        if event.state == "start":
            unified = SlewEvent(
                event_type=EventType.SLEW_STARTED,
                source_device="seestar_mount",
                source_backend="seestar",
                state=SlewState.SLEWING,
            )
        elif event.state == "complete":
            unified = SlewEvent(
                event_type=EventType.SLEW_COMPLETED,
                source_device="seestar_mount",
                source_backend="seestar",
                state=SlewState.TRACKING,
            )
        elif event.state in ("cancel", "fail"):
            unified = SlewEvent(
                event_type=EventType.SLEW_ABORTED,
                source_device="seestar_mount",
                source_backend="seestar",
                state=SlewState.ERROR if event.state == "fail" else SlewState.IDLE,
                data={"error": event.error, "code": event.code},
            )
        else:
            # "working" state - emit progress event
            unified = SlewEvent(
                event_type=EventType.SLEW_PROGRESS,
                source_device="seestar_mount",
                source_backend="seestar",
                state=SlewState.SLEWING,
                data={"lapse_ms": event.lapse_ms},
            )

        await self._unified_bus.emit(unified)

    async def _handle_scope_goto(self, event: ScopeGotoEvent) -> None:
        """Translate ScopeGoto progress events to SlewEvents."""
        coords = None
        if event.cur_ra_dec:
            # Convert RA from hours to degrees
            coords = Coordinates(
                ra=event.cur_ra_dec.ra * 15.0,
                dec=event.cur_ra_dec.dec,
            )

        unified = SlewEvent(
            event_type=EventType.COORDINATES_UPDATED,
            source_device="seestar_mount",
            source_backend="seestar",
            current_coordinates=coords,
            state=SlewState.SLEWING,
            distance_remaining=event.dist_deg,
            data={"percent": getattr(event, "percent", None)},
        )
        await self._unified_bus.emit(unified)

    async def _handle_stack(self, event: StackEvent) -> None:
        """Translate Stack events to ExposureEvents."""
        if event.state == "start":
            event_type = EventType.STACK_STARTED
        elif event.state == "frame_complete":
            event_type = EventType.STACK_FRAME
        elif event.state == "complete":
            event_type = EventType.STACK_COMPLETED
        elif event.state == "cancel":
            event_type = EventType.EXPOSURE_ABORTED
        else:
            event_type = EventType.EXPOSURE_PROGRESS

        unified = ExposureEvent(
            event_type=event_type,
            source_device="seestar_camera",
            source_backend="seestar",
            frames_stacked=event.stacked_frame,
            frames_dropped=event.dropped_frame,
            data={
                "exp_ms": event.exp_ms,
                "dead_time_ms": event.dead_time_ms,
                "reject_type": event.reject_type,
            },
        )
        await self._unified_bus.emit(unified)

    async def _handle_continuous_exposure(self, event: ContinuousExposureEvent) -> None:
        """Translate ContinuousExposure events to ExposureEvents."""
        if event.state == "start":
            event_type = EventType.EXPOSURE_STARTED
        elif event.state == "complete":
            event_type = EventType.EXPOSURE_COMPLETED
        elif event.state == "cancel":
            event_type = EventType.EXPOSURE_ABORTED
        else:
            event_type = EventType.EXPOSURE_PROGRESS

        unified = ExposureEvent(
            event_type=event_type,
            source_device="seestar_camera",
            source_backend="seestar",
            data={"fps": event.fps, "lapse_ms": event.lapse_ms},
        )
        await self._unified_bus.emit(unified)

    async def _handle_focuser(self, event: FocuserMoveEvent) -> None:
        """Translate FocuserMove events to FocuserEvents."""
        if event.state == "complete":
            event_type = EventType.FOCUSER_STOPPED
        elif event.state == "start":
            event_type = EventType.FOCUSER_MOVING
        else:
            event_type = EventType.FOCUSER_POSITION_CHANGED

        unified = FocuserEvent(
            event_type=event_type,
            source_device="seestar_focuser",
            source_backend="seestar",
            position=event.position,
        )
        await self._unified_bus.emit(unified)

    async def _handle_status(self, event: PiStatusEvent) -> None:
        """Translate PiStatus events to generic status updates."""
        unified = UnifiedEvent(
            event_type=EventType.STATUS_UPDATE,
            source_device="seestar",
            source_backend="seestar",
            data={
                "temperature": event.temp,
                "battery_capacity": event.battery_capacity,
                "charger_status": event.charger_status,
                "charge_online": event.charge_online,
            },
        )
        await self._unified_bus.emit(unified)
