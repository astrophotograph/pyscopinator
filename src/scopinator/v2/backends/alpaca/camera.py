"""ASCOM Alpaca camera implementation.

Implements the V2 Camera interface using the Alpaca HTTP REST API
for CCD/CMOS camera control.
"""

import asyncio
import base64
from typing import Callable, Optional

import aiohttp

from scopinator.v2.core.capabilities import CameraCapabilities
from scopinator.v2.core.devices import Camera, CameraStatus
from scopinator.v2.core.events import EventType, ExposureEvent, UnifiedEventBus
from scopinator.v2.core.exceptions import CommandError, DeviceError
from scopinator.v2.core.types import CameraState, ExposureSettings, ImageData


class AlpacaCamera(Camera):
    """Camera implementation using ASCOM Alpaca REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        device_number: int,
        client_id: int,
        get_transaction_id: Callable[[], int],
        event_bus: Optional[UnifiedEventBus] = None,
    ) -> None:
        """Initialize Alpaca camera.

        Args:
            session: aiohttp session for HTTP requests
            base_url: Base URL of Alpaca server
            device_number: Alpaca device number
            client_id: Alpaca client ID
            get_transaction_id: Function to get next transaction ID
            event_bus: Optional event bus for camera events
        """
        super().__init__(event_bus)
        self._session = session
        self._base_url = f"{base_url}/api/v1/camera/{device_number}"
        self._client_id = client_id
        self._get_tid = get_transaction_id
        self._timeout = aiohttp.ClientTimeout(total=60)
        self._current_exposure: Optional[ExposureSettings] = None

    async def _get(self, endpoint: str) -> dict:
        """Make GET request to Alpaca endpoint."""
        params = {
            "ClientID": self._client_id,
            "ClientTransactionID": self._get_tid(),
        }
        async with self._session.get(
            f"{self._base_url}/{endpoint}",
            params=params,
            timeout=self._timeout,
        ) as resp:
            data = await resp.json()
            self._check_error(data)
            return data

    async def _put(self, endpoint: str, form_data: Optional[dict] = None) -> dict:
        """Make PUT request to Alpaca endpoint."""
        data = form_data or {}
        data["ClientID"] = self._client_id
        data["ClientTransactionID"] = self._get_tid()

        async with self._session.put(
            f"{self._base_url}/{endpoint}",
            data=data,
            timeout=self._timeout,
        ) as resp:
            result = await resp.json()
            self._check_error(result)
            return result

    def _check_error(self, data: dict) -> None:
        """Check Alpaca response for errors."""
        error_number = data.get("ErrorNumber", 0)
        if error_number != 0:
            error_message = data.get("ErrorMessage", "Unknown error")
            raise CommandError(error_message, code=error_number)

    async def connect(self) -> None:
        """Connect to the camera."""
        await self._put("connected", {"Connected": "true"})
        self._connected = True

    async def disconnect(self) -> None:
        """Disconnect from the camera."""
        try:
            await self._put("connected", {"Connected": "false"})
        finally:
            self._connected = False

    async def get_capabilities(self) -> CameraCapabilities:
        """Get camera capabilities."""
        results = await asyncio.gather(
            self._get("canabortexposure"),
            self._get("canstopexposure"),
            self._get("maxbinx"),
            self._get("maxbiny"),
            self._get("cameraxsize"),
            self._get("cameraysize"),
            self._get("pixelsizex"),
            self._get("pixelsizey"),
            self._get("sensortype"),
            return_exceptions=True,
        )

        def get_value(result, default):
            if isinstance(result, Exception):
                return default
            return result.get("Value", default)

        # Sensor type: 0=Mono, 1=Color, 2-4=Various Bayer patterns
        sensor_type = get_value(results[8], 0)
        is_color = sensor_type > 0

        return CameraCapabilities(
            can_abort_exposure=get_value(results[0], True),
            can_stop_exposure=get_value(results[1], False),
            can_set_gain=True,  # Most cameras support
            can_set_binning=True,
            can_subframe=True,
            max_bin_x=get_value(results[2], 1),
            max_bin_y=get_value(results[3], 1),
            sensor_width=get_value(results[4], 0),
            sensor_height=get_value(results[5], 0),
            pixel_size_x=get_value(results[6], 0.0),
            pixel_size_y=get_value(results[7], 0.0),
            is_color=is_color,
        )

    async def start_exposure(self, settings: ExposureSettings) -> None:
        """Start an exposure."""
        self._current_exposure = settings

        # Set binning if needed
        if settings.bin_x != 1 or settings.bin_y != 1:
            await self._put("binx", {"BinX": str(settings.bin_x)})
            await self._put("biny", {"BinY": str(settings.bin_y)})

        # Set subframe if specified
        if settings.subframe:
            x, y, width, height = settings.subframe
            await self._put("startx", {"StartX": str(x)})
            await self._put("starty", {"StartY": str(y)})
            await self._put("numx", {"NumX": str(width)})
            await self._put("numy", {"NumY": str(height)})

        # Emit exposure started event
        event = ExposureEvent(
            event_type=EventType.EXPOSURE_STARTED,
            source_device="alpaca_camera",
            source_backend="alpaca",
            duration_seconds=settings.duration_seconds,
        )
        self._event_bus.emit_nowait(event)

        # Start the exposure
        await self._put(
            "startexposure",
            {
                "Duration": str(settings.duration_seconds),
                "Light": str(settings.light).lower(),
            },
        )

    async def abort_exposure(self) -> None:
        """Abort current exposure."""
        await self._put("abortexposure")

        event = ExposureEvent(
            event_type=EventType.EXPOSURE_ABORTED,
            source_device="alpaca_camera",
            source_backend="alpaca",
        )
        self._event_bus.emit_nowait(event)

    async def stop_exposure(self) -> None:
        """Stop exposure early and read out."""
        await self._put("stopexposure")

    async def is_exposing(self) -> bool:
        """Check if camera is currently exposing."""
        result = await self._get("camerastate")
        # CameraState: 0=Idle, 1=Waiting, 2=Exposing, 3=Reading, 4=Download, 5=Error
        return result["Value"] in (1, 2)

    async def is_image_ready(self) -> bool:
        """Check if an image is ready to download."""
        result = await self._get("imageready")
        return result["Value"]

    async def get_image(self) -> ImageData:
        """Get the last captured image.

        Note: Alpaca returns image data as base64-encoded in the imagearray
        endpoint, or via imagearrayvariant.
        """
        # Check if image is ready
        if not await self.is_image_ready():
            raise DeviceError("No image ready")

        # Get image dimensions
        width_result = await self._get("numx")
        height_result = await self._get("numy")
        width = width_result["Value"]
        height = height_result["Value"]

        # Get image array - this can be large
        # Using imagearrayvariant which returns base64-encoded data
        result = await self._get("imagearray")

        # The image data format depends on the Alpaca server
        # Typically it's a 2D array of pixel values
        image_array = result.get("Value", [])

        # Convert to bytes - format varies by implementation
        # For now, we'll return raw bytes
        import struct

        if isinstance(image_array, list) and len(image_array) > 0:
            if isinstance(image_array[0], list):
                # 2D array
                flat = [pixel for row in image_array for pixel in row]
                data = struct.pack(f">{len(flat)}H", *flat)
            else:
                # 1D array
                data = struct.pack(f">{len(image_array)}H", *image_array)
        else:
            data = b""

        event = ExposureEvent(
            event_type=EventType.IMAGE_READY,
            source_device="alpaca_camera",
            source_backend="alpaca",
        )
        self._event_bus.emit_nowait(event)

        return ImageData(
            width=width,
            height=height,
            data=data,
            bit_depth=16,
            is_color=False,  # Would need to query sensortype
        )

    async def set_cooler(
        self, enabled: bool, setpoint: Optional[float] = None
    ) -> None:
        """Control cooler."""
        await self._put("cooleron", {"CoolerOn": str(enabled).lower()})

        if setpoint is not None and enabled:
            await self._put(
                "setccdtemperature", {"SetCCDTemperature": str(setpoint)}
            )

    async def get_temperature(self) -> Optional[float]:
        """Get current sensor temperature."""
        try:
            result = await self._get("ccdtemperature")
            return result["Value"]
        except Exception:
            return None

    async def set_gain(self, gain: int) -> None:
        """Set camera gain."""
        await self._put("gain", {"Gain": str(gain)})

    async def set_binning(self, bin_x: int, bin_y: int) -> None:
        """Set camera binning."""
        await self._put("binx", {"BinX": str(bin_x)})
        await self._put("biny", {"BinY": str(bin_y)})

    async def get_status(self) -> CameraStatus:
        """Get current camera status."""
        results = await asyncio.gather(
            self._get("camerastate"),
            self._get("percentcompleted"),
            self._get("cooleron"),
            self._get("ccdtemperature"),
            self._get("setccdtemperature"),
            self._get("coolerpower"),
            self._get("gain"),
            self._get("binx"),
            self._get("biny"),
            return_exceptions=True,
        )

        def get_value(result, default):
            if isinstance(result, Exception):
                return default
            return result.get("Value", default)

        # Map Alpaca CameraState to our CameraState
        alpaca_state = get_value(results[0], 0)
        state_map = {
            0: CameraState.IDLE,
            1: CameraState.WAITING,
            2: CameraState.EXPOSING,
            3: CameraState.READING,
            4: CameraState.DOWNLOADING,
            5: CameraState.ERROR,
        }
        state = state_map.get(alpaca_state, CameraState.IDLE)

        return CameraStatus(
            connected=self._connected,
            name="Alpaca Camera",
            driver_info="ASCOM Alpaca",
            driver_version="1.0.0",
            state=state,
            exposure_progress=get_value(results[1], 0) / 100.0,
            cooler_on=get_value(results[2], False),
            temperature=get_value(results[3], None),
            cooler_setpoint=get_value(results[4], None),
            cooler_power=get_value(results[5], None),
            gain=get_value(results[6], None),
            binning=(get_value(results[7], 1), get_value(results[8], 1)),
        )
