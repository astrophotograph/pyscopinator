"""Pyscopinator V2 - Multi-protocol telescope control abstraction layer.

This module provides a unified interface for controlling telescopes via
multiple protocols: Seestar (native), ASCOM Alpaca (HTTP), and INDI.

Example usage:
    from scopinator.v2 import DeviceManager, SeestarBackend

    manager = DeviceManager()
    await manager.add_backend("seestar", SeestarBackend("192.168.1.100"))

    devices = await manager.discover_all()
    mount = await manager.get_mount("seestar", "seestar_mount")

    await mount.connect()
    await mount.slew_to_coordinates(Coordinates(ra=83.63, dec=22.01))
"""

from scopinator.v2.core.types import (
    Coordinates,
    AltAzCoordinates,
    TrackingRate,
    PierSide,
    SlewState,
    ExposureSettings,
    ImageData,
    FilterPosition,
    FocuserPosition,
)
from scopinator.v2.core.capabilities import (
    MountCapabilities,
    CameraCapabilities,
    FocuserCapabilities,
    FilterWheelCapabilities,
)
from scopinator.v2.core.devices import (
    Device,
    DeviceStatus,
    Mount,
    MountStatus,
    Camera,
    CameraStatus,
    Focuser,
    FocuserStatus,
    FilterWheel,
    FilterWheelStatus,
)
from scopinator.v2.core.events import (
    EventType,
    UnifiedEvent,
    SlewEvent,
    ExposureEvent,
    FocuserEvent,
    FilterEvent,
    UnifiedEventBus,
)
from scopinator.v2.core.exceptions import (
    V2Error,
    ConnectionError,
    DeviceError,
    BackendError,
    TimeoutError,
)

__all__ = [
    # Types
    "Coordinates",
    "AltAzCoordinates",
    "TrackingRate",
    "PierSide",
    "SlewState",
    "ExposureSettings",
    "ImageData",
    "FilterPosition",
    "FocuserPosition",
    # Capabilities
    "MountCapabilities",
    "CameraCapabilities",
    "FocuserCapabilities",
    "FilterWheelCapabilities",
    # Devices
    "Device",
    "DeviceStatus",
    "Mount",
    "MountStatus",
    "Camera",
    "CameraStatus",
    "Focuser",
    "FocuserStatus",
    "FilterWheel",
    "FilterWheelStatus",
    # Events
    "EventType",
    "UnifiedEvent",
    "SlewEvent",
    "ExposureEvent",
    "FocuserEvent",
    "FilterEvent",
    "UnifiedEventBus",
    # Exceptions
    "V2Error",
    "ConnectionError",
    "DeviceError",
    "BackendError",
    "TimeoutError",
]
