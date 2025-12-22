"""Seestar camera implementation.

Wraps the existing SeestarClient and SeestarImagingClient to provide
the V2 Camera interface.
"""

from typing import TYPE_CHECKING, AsyncIterator, Optional

from scopinator.v2.core.capabilities import CameraCapabilities
from scopinator.v2.core.devices import Camera, CameraStatus
from scopinator.v2.core.events import EventType, ExposureEvent, UnifiedEventBus
from scopinator.v2.core.exceptions import DeviceError, NotConnectedError
from scopinator.v2.core.types import CameraState, ExposureSettings, ImageData

if TYPE_CHECKING:
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.imaging_client import SeestarImagingClient


class SeestarCamera(Camera):
    """Camera implementation for Seestar.

    This adapter wraps both the SeestarClient (for control commands)
    and SeestarImagingClient (for image data) to provide the V2
    Camera interface.

    Note: Seestar operates primarily in stacking mode, where the
    telescope continuously captures and stacks frames. This adapter
    maps that workflow to the Camera interface.
    """

    def __init__(
        self,
        client: "SeestarClient",
        imaging_client: Optional["SeestarImagingClient"] = None,
        event_bus: Optional[UnifiedEventBus] = None,
    ) -> None:
        """Initialize Seestar camera adapter.

        Args:
            client: Main SeestarClient for control
            imaging_client: Optional imaging client for image data
            event_bus: Optional event bus for emitting camera events
        """
        super().__init__(event_bus)
        self._client = client
        self._imaging_client = imaging_client
        self._current_settings: Optional[ExposureSettings] = None

    async def connect(self) -> None:
        """Camera connection is handled by backend/client."""
        self._connected = self._client.is_connected

    async def disconnect(self) -> None:
        """Camera disconnection is handled by backend/client."""
        pass

    async def get_capabilities(self) -> CameraCapabilities:
        """Get Seestar camera capabilities."""
        return CameraCapabilities(
            can_abort_exposure=True,
            can_stop_exposure=False,
            can_set_gain=True,
            can_set_offset=False,
            can_set_binning=False,  # Seestar has fixed binning
            can_subframe=False,
            can_fast_readout=False,
            has_shutter=False,
            has_cooler=False,
            has_filter_wheel=True,  # LP filter
            is_color=True,  # Bayer sensor
            max_bin_x=1,
            max_bin_y=1,
            sensor_width=1920,  # Seestar S50 resolution
            sensor_height=1080,
            pixel_size_x=3.0,  # Approximate
            pixel_size_y=3.0,
            min_exposure=0.01,
            max_exposure=20.0,  # Seestar typical max
            supported_gains=[],  # Gain is managed automatically
            bit_depth=12,
        )

    async def start_exposure(self, settings: ExposureSettings) -> None:
        """Start an exposure/stacking session.

        For Seestar, this starts the stacking mode with the given
        exposure settings.

        Args:
            settings: Exposure settings
        """
        if not self._client.is_connected:
            raise NotConnectedError("Seestar is not connected")

        self._current_settings = settings

        # Emit exposure started event
        event = ExposureEvent(
            event_type=EventType.EXPOSURE_STARTED,
            source_device="seestar_camera",
            source_backend="seestar",
            duration_seconds=settings.duration_seconds,
        )
        self._event_bus.emit_nowait(event)

        # For Seestar, stacking is typically started via goto
        # or scope_view command. The exposure settings are applied
        # automatically by the telescope.

        # If we have a current view, we're already exposing
        # Otherwise, this is typically called after a goto

    async def abort_exposure(self) -> None:
        """Abort current exposure/stacking."""
        if not self._client.is_connected:
            raise NotConnectedError("Seestar is not connected")

        await self._client.stop_stack()

        event = ExposureEvent(
            event_type=EventType.EXPOSURE_ABORTED,
            source_device="seestar_camera",
            source_backend="seestar",
        )
        self._event_bus.emit_nowait(event)

    async def get_image(self) -> ImageData:
        """Get the last captured/stacked image.

        Returns:
            ImageData containing the stacked image

        Raises:
            DeviceError: If no image available
        """
        if self._imaging_client is None:
            raise DeviceError("Imaging client not configured")

        if not self._imaging_client.is_connected:
            raise NotConnectedError("Imaging client is not connected")

        # Get the last image from the imaging client
        scope_image = await self._imaging_client.get_last_image()

        if scope_image is None or scope_image.data is None:
            raise DeviceError("No image available")

        return ImageData(
            width=scope_image.width or 1920,
            height=scope_image.height or 1080,
            data=scope_image.data,
            bit_depth=12,
            is_color=True,
            bayer_pattern="GRBG",
            metadata={
                "stacked_frames": self._client.status.stacked_frame,
                "dropped_frames": self._client.status.dropped_frame,
                "target_name": self._client.status.target_name,
            },
        )

    async def is_exposing(self) -> bool:
        """Check if camera is currently exposing/stacking."""
        return self._client.client_mode in ("Stack", "ContinuousExposure")

    async def stream_images(
        self, settings: ExposureSettings
    ) -> AsyncIterator[ImageData]:
        """Stream images from the camera.

        Yields stacked images as they become available.

        Args:
            settings: Exposure settings (not all may be applicable)

        Yields:
            ImageData for each captured/stacked frame
        """
        if self._imaging_client is None:
            raise DeviceError("Imaging client not configured")

        if not self._imaging_client.is_connected:
            raise NotConnectedError("Imaging client is not connected")

        # Use the imaging client's image generator
        async for scope_image in self._imaging_client.get_next_image():
            if scope_image.data is not None:
                yield ImageData(
                    width=scope_image.width or 1920,
                    height=scope_image.height or 1080,
                    data=scope_image.data,
                    bit_depth=12,
                    is_color=True,
                    bayer_pattern="GRBG",
                    metadata={
                        "stacked_frames": self._client.status.stacked_frame,
                        "dropped_frames": self._client.status.dropped_frame,
                    },
                )

    async def set_gain(self, gain: int) -> None:
        """Set camera gain.

        Seestar manages gain automatically, but this can override.
        """
        # Seestar has automatic gain control
        # Could implement via SetSetting command if needed
        pass

    async def get_status(self) -> CameraStatus:
        """Get current camera status."""
        client_mode = self._client.client_mode

        # Map client mode to camera state
        if client_mode == "Stack":
            state = CameraState.EXPOSING
        elif client_mode == "ContinuousExposure":
            state = CameraState.EXPOSING
        elif client_mode == "Idle":
            state = CameraState.IDLE
        else:
            state = CameraState.IDLE

        return CameraStatus(
            connected=self._client.is_connected,
            name="Seestar Camera",
            driver_info="Seestar V2 Adapter",
            driver_version="1.0.0",
            state=state,
            exposure_progress=0.0,  # Could calculate from frame count
            cooler_on=False,
            cooler_setpoint=None,
            temperature=self._client.status.temp,
            cooler_power=None,
            gain=self._client.status.gain,
            offset=None,
            binning=(1, 1),
            last_exposure_duration=None,
        )
