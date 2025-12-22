"""Abstract device interfaces.

This module defines the abstract base classes for all device types.
Backend implementations (Seestar, Alpaca, INDI) must implement these
interfaces to provide a unified API.
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

from pydantic import BaseModel, Field

from scopinator.v2.core.capabilities import (
    CameraCapabilities,
    FilterWheelCapabilities,
    FocuserCapabilities,
    MountCapabilities,
)
from scopinator.v2.core.events import UnifiedEventBus
from scopinator.v2.core.types import (
    AltAzCoordinates,
    CameraState,
    Coordinates,
    ExposureSettings,
    FilterPosition,
    FocuserPosition,
    ImageData,
    PierSide,
    SlewState,
    TrackingRate,
)


class DeviceStatus(BaseModel):
    """Base device status."""

    connected: bool = Field(default=False, description="Connection state")
    name: str = Field(default="", description="Device name")
    driver_info: str = Field(default="", description="Driver/backend info")
    driver_version: str = Field(default="", description="Driver version")
    description: str = Field(default="", description="Device description")


class Device(ABC):
    """Base class for all devices.

    All device implementations must inherit from this class and implement
    the abstract methods for connection management and status retrieval.
    """

    def __init__(self, event_bus: Optional[UnifiedEventBus] = None) -> None:
        """Initialize device.

        Args:
            event_bus: Optional event bus for emitting device events
        """
        self._event_bus = event_bus or UnifiedEventBus()
        self._connected = False

    @property
    def event_bus(self) -> UnifiedEventBus:
        """Get the event bus for this device."""
        return self._event_bus

    @property
    def is_connected(self) -> bool:
        """Check if device is connected."""
        return self._connected

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the device.

        Raises:
            ConnectionError: If connection fails
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the device."""
        pass

    @abstractmethod
    async def get_status(self) -> DeviceStatus:
        """Get current device status.

        Returns:
            DeviceStatus with current state
        """
        pass


# =============================================================================
# Mount
# =============================================================================


class MountStatus(DeviceStatus):
    """Mount-specific status."""

    coordinates: Optional[Coordinates] = Field(None, description="Current RA/Dec")
    altaz: Optional[AltAzCoordinates] = Field(None, description="Current Alt/Az")
    state: SlewState = Field(default=SlewState.IDLE, description="Current slew state")
    tracking: bool = Field(default=False, description="Tracking enabled")
    tracking_rate: TrackingRate = Field(
        default=TrackingRate.SIDEREAL, description="Tracking rate"
    )
    pier_side: PierSide = Field(default=PierSide.UNKNOWN, description="Pier side (GEM)")
    at_park: bool = Field(default=False, description="Is parked")
    at_home: bool = Field(default=False, description="Is at home position")
    slewing: bool = Field(default=False, description="Is slewing")
    target_coordinates: Optional[Coordinates] = Field(None, description="Target coordinates")


class Mount(Device):
    """Abstract mount interface.

    Provides unified control for telescope mounts across different protocols.
    All coordinate-based methods use degrees for RA (0-360) and Dec (-90 to 90).
    """

    @abstractmethod
    async def get_capabilities(self) -> MountCapabilities:
        """Get mount capabilities.

        Returns:
            MountCapabilities describing what this mount can do
        """
        pass

    @abstractmethod
    async def get_coordinates(self) -> Coordinates:
        """Get current equatorial coordinates.

        Returns:
            Current RA/Dec position

        Raises:
            DeviceError: If coordinates cannot be read
        """
        pass

    async def get_altaz(self) -> Optional[AltAzCoordinates]:
        """Get current altitude-azimuth coordinates.

        Override if supported by the backend.

        Returns:
            Current Alt/Az position, or None if not supported
        """
        return None

    @abstractmethod
    async def slew_to_coordinates(
        self,
        coords: Coordinates,
        *,
        wait: bool = True,
    ) -> None:
        """Slew to equatorial coordinates.

        Args:
            coords: Target coordinates
            wait: If True, wait for slew to complete before returning

        Raises:
            DeviceError: If slew fails
            TimeoutError: If wait=True and slew doesn't complete
        """
        pass

    async def slew_to_altaz(
        self,
        coords: AltAzCoordinates,
        *,
        wait: bool = True,
    ) -> None:
        """Slew to altitude-azimuth coordinates.

        Override if supported by the backend.

        Args:
            coords: Target Alt/Az coordinates
            wait: If True, wait for slew to complete

        Raises:
            NotSupportedError: If Alt/Az slewing not supported
        """
        from scopinator.v2.core.exceptions import NotSupportedError

        raise NotSupportedError("Alt/Az slewing not supported by this mount")

    @abstractmethod
    async def abort_slew(self) -> None:
        """Abort any current slew operation."""
        pass

    @abstractmethod
    async def sync_to_coordinates(self, coords: Coordinates) -> None:
        """Sync mount to given coordinates.

        This tells the mount that it is currently pointing at the given
        coordinates, for alignment correction.

        Args:
            coords: Coordinates to sync to

        Raises:
            DeviceError: If sync fails
        """
        pass

    @abstractmethod
    async def park(self) -> None:
        """Park the mount.

        Raises:
            DeviceError: If parking fails
        """
        pass

    async def unpark(self) -> None:
        """Unpark the mount.

        Override if supported by the backend.

        Raises:
            NotSupportedError: If unparking not supported
        """
        from scopinator.v2.core.exceptions import NotSupportedError

        raise NotSupportedError("Unpark not supported by this mount")

    @abstractmethod
    async def set_tracking(self, enabled: bool) -> None:
        """Enable or disable tracking.

        Args:
            enabled: True to enable tracking, False to disable
        """
        pass

    @abstractmethod
    async def get_tracking(self) -> bool:
        """Get current tracking state.

        Returns:
            True if tracking is enabled
        """
        pass

    async def set_tracking_rate(self, rate: TrackingRate) -> None:
        """Set tracking rate.

        Override if supported by the backend.

        Args:
            rate: Desired tracking rate

        Raises:
            NotSupportedError: If custom tracking rates not supported
        """
        from scopinator.v2.core.exceptions import NotSupportedError

        raise NotSupportedError("Custom tracking rates not supported by this mount")

    async def find_home(self) -> None:
        """Find home position.

        Override if supported by the backend.

        Raises:
            NotSupportedError: If homing not supported
        """
        from scopinator.v2.core.exceptions import NotSupportedError

        raise NotSupportedError("Homing not supported by this mount")

    async def pulse_guide(self, direction: str, duration_ms: int) -> None:
        """Pulse guide in a direction.

        Override if supported by the backend.

        Args:
            direction: One of "north", "south", "east", "west"
            duration_ms: Duration in milliseconds

        Raises:
            NotSupportedError: If pulse guiding not supported
        """
        from scopinator.v2.core.exceptions import NotSupportedError

        raise NotSupportedError("Pulse guiding not supported by this mount")

    async def is_slewing(self) -> bool:
        """Check if mount is currently slewing.

        Returns:
            True if slewing
        """
        status = await self.get_status()
        return status.slewing

    @abstractmethod
    async def get_status(self) -> MountStatus:
        """Get current mount status.

        Returns:
            MountStatus with current state
        """
        pass


# =============================================================================
# Camera
# =============================================================================


class CameraStatus(DeviceStatus):
    """Camera-specific status."""

    state: CameraState = Field(default=CameraState.IDLE, description="Camera state")
    exposure_progress: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Exposure progress (0.0 to 1.0)"
    )
    cooler_on: bool = Field(default=False, description="Cooler enabled")
    cooler_setpoint: Optional[float] = Field(None, description="Target temperature")
    temperature: Optional[float] = Field(None, description="Current sensor temperature")
    cooler_power: Optional[float] = Field(None, description="Cooler power percentage")
    gain: Optional[int] = Field(None, description="Current gain setting")
    offset: Optional[int] = Field(None, description="Current offset setting")
    binning: tuple[int, int] = Field(default=(1, 1), description="Current binning (x, y)")
    last_exposure_duration: Optional[float] = Field(None, description="Last exposure duration")


class Camera(Device):
    """Abstract camera interface.

    Provides unified control for cameras across different protocols.
    Supports both single exposure and continuous/stacking modes.
    """

    @abstractmethod
    async def get_capabilities(self) -> CameraCapabilities:
        """Get camera capabilities.

        Returns:
            CameraCapabilities describing what this camera can do
        """
        pass

    @abstractmethod
    async def start_exposure(self, settings: ExposureSettings) -> None:
        """Start an exposure.

        Args:
            settings: Exposure settings

        Raises:
            DeviceError: If exposure cannot be started
        """
        pass

    @abstractmethod
    async def abort_exposure(self) -> None:
        """Abort current exposure."""
        pass

    async def stop_exposure(self) -> None:
        """Stop exposure early and read out.

        Override if supported by the backend.

        Raises:
            NotSupportedError: If stop not supported (use abort instead)
        """
        from scopinator.v2.core.exceptions import NotSupportedError

        raise NotSupportedError("Stop exposure not supported - use abort")

    @abstractmethod
    async def get_image(self) -> ImageData:
        """Get the last captured image.

        Returns:
            ImageData containing the image

        Raises:
            DeviceError: If no image available
        """
        pass

    @abstractmethod
    async def is_exposing(self) -> bool:
        """Check if camera is currently exposing.

        Returns:
            True if exposing
        """
        pass

    async def is_image_ready(self) -> bool:
        """Check if an image is ready to download.

        Returns:
            True if image ready
        """
        return not await self.is_exposing()

    async def stream_images(
        self, settings: ExposureSettings
    ) -> AsyncIterator[ImageData]:
        """Stream continuous images.

        Override if supported by the backend. Default implementation
        takes single exposures in a loop.

        Args:
            settings: Exposure settings for each frame

        Yields:
            ImageData for each captured frame
        """
        while True:
            await self.start_exposure(settings)
            while await self.is_exposing():
                import asyncio
                await asyncio.sleep(0.1)
            yield await self.get_image()

    async def set_cooler(
        self, enabled: bool, setpoint: Optional[float] = None
    ) -> None:
        """Control cooler.

        Override if supported by the backend.

        Args:
            enabled: True to enable cooler
            setpoint: Target temperature in Celsius

        Raises:
            NotSupportedError: If camera has no cooler
        """
        from scopinator.v2.core.exceptions import NotSupportedError

        raise NotSupportedError("This camera does not have a cooler")

    async def get_temperature(self) -> Optional[float]:
        """Get current sensor temperature.

        Returns:
            Temperature in Celsius, or None if not available
        """
        status = await self.get_status()
        return status.temperature

    async def set_gain(self, gain: int) -> None:
        """Set camera gain.

        Args:
            gain: Gain value

        Raises:
            DeviceError: If gain cannot be set
        """
        pass

    async def set_binning(self, bin_x: int, bin_y: int) -> None:
        """Set camera binning.

        Args:
            bin_x: Horizontal binning
            bin_y: Vertical binning

        Raises:
            DeviceError: If binning cannot be set
        """
        pass

    @abstractmethod
    async def get_status(self) -> CameraStatus:
        """Get current camera status.

        Returns:
            CameraStatus with current state
        """
        pass


# =============================================================================
# Focuser
# =============================================================================


class FocuserStatus(DeviceStatus):
    """Focuser-specific status."""

    position: int = Field(default=0, description="Current position in steps")
    max_position: int = Field(default=0, description="Maximum position")
    is_moving: bool = Field(default=False, description="Is currently moving")
    temperature: Optional[float] = Field(None, description="Temperature in Celsius")
    temp_comp_enabled: bool = Field(default=False, description="Temp compensation enabled")


class Focuser(Device):
    """Abstract focuser interface."""

    @abstractmethod
    async def get_capabilities(self) -> FocuserCapabilities:
        """Get focuser capabilities.

        Returns:
            FocuserCapabilities describing what this focuser can do
        """
        pass

    @abstractmethod
    async def get_position(self) -> FocuserPosition:
        """Get current focuser position.

        Returns:
            Current position information
        """
        pass

    @abstractmethod
    async def move_to(self, position: int, *, wait: bool = True) -> None:
        """Move to absolute position.

        Args:
            position: Target position in steps
            wait: If True, wait for move to complete

        Raises:
            DeviceError: If move fails
            ValueError: If position out of range
        """
        pass

    @abstractmethod
    async def move_relative(self, steps: int, *, wait: bool = True) -> None:
        """Move relative to current position.

        Args:
            steps: Number of steps (positive = out, negative = in)
            wait: If True, wait for move to complete

        Raises:
            DeviceError: If move fails
        """
        pass

    @abstractmethod
    async def halt(self) -> None:
        """Halt any movement."""
        pass

    async def is_moving(self) -> bool:
        """Check if focuser is moving.

        Returns:
            True if moving
        """
        status = await self.get_status()
        return status.is_moving

    async def get_temperature(self) -> Optional[float]:
        """Get focuser temperature.

        Returns:
            Temperature in Celsius, or None if not available
        """
        position = await self.get_position()
        return position.temperature

    @abstractmethod
    async def get_status(self) -> FocuserStatus:
        """Get current focuser status.

        Returns:
            FocuserStatus with current state
        """
        pass


# =============================================================================
# Filter Wheel
# =============================================================================


class FilterWheelStatus(DeviceStatus):
    """Filter wheel-specific status."""

    position: int = Field(default=0, description="Current position (0-indexed)")
    filter_name: Optional[str] = Field(None, description="Current filter name")
    is_moving: bool = Field(default=False, description="Is currently moving")
    num_positions: int = Field(default=0, description="Number of filter slots")


class FilterWheel(Device):
    """Abstract filter wheel interface."""

    @abstractmethod
    async def get_capabilities(self) -> FilterWheelCapabilities:
        """Get filter wheel capabilities.

        Returns:
            FilterWheelCapabilities describing this filter wheel
        """
        pass

    @abstractmethod
    async def get_position(self) -> FilterPosition:
        """Get current filter position.

        Returns:
            Current filter position and name
        """
        pass

    @abstractmethod
    async def set_position(self, position: int, *, wait: bool = True) -> None:
        """Move to filter position.

        Args:
            position: Target position (0-indexed)
            wait: If True, wait for move to complete

        Raises:
            DeviceError: If move fails
            ValueError: If position out of range
        """
        pass

    async def set_filter_by_name(self, name: str, *, wait: bool = True) -> None:
        """Move to filter by name.

        Args:
            name: Filter name
            wait: If True, wait for move to complete

        Raises:
            ValueError: If filter name not found
        """
        names = await self.get_filter_names()
        try:
            position = names.index(name)
        except ValueError:
            raise ValueError(f"Filter '{name}' not found. Available: {names}")
        await self.set_position(position, wait=wait)

    @abstractmethod
    async def get_filter_names(self) -> list[str]:
        """Get list of filter names.

        Returns:
            List of filter names by position
        """
        pass

    async def is_moving(self) -> bool:
        """Check if filter wheel is moving.

        Returns:
            True if moving
        """
        status = await self.get_status()
        return status.is_moving

    @abstractmethod
    async def get_status(self) -> FilterWheelStatus:
        """Get current filter wheel status.

        Returns:
            FilterWheelStatus with current state
        """
        pass
