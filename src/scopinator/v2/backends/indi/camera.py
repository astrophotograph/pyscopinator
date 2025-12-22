"""INDI camera implementation.

Implements the V2 Camera interface using INDI CCD properties.
"""

import asyncio
from typing import TYPE_CHECKING, Optional

from scopinator.v2.core.capabilities import CameraCapabilities
from scopinator.v2.core.devices import Camera, CameraStatus
from scopinator.v2.core.events import EventType, ExposureEvent, UnifiedEventBus
from scopinator.v2.core.exceptions import DeviceError, NotConnectedError
from scopinator.v2.core.types import CameraState, ExposureSettings, ImageData

if TYPE_CHECKING:
    from scopinator.v2.backends.indi.backend import INDIClient

try:
    import PyIndi

    INDI_AVAILABLE = True
except ImportError:
    INDI_AVAILABLE = False
    PyIndi = None


class INDICamera(Camera):
    """Camera implementation using INDI protocol.

    Key INDI properties for CCDs:
    - CCD_EXPOSURE: Exposure control (number)
    - CCD_FRAME: Frame size (number)
    - CCD_BINNING: Binning (number)
    - CCD1: Image data (blob)
    - CCD_TEMPERATURE: Cooler temperature (number)
    - CCD_COOLER: Cooler on/off (switch)
    """

    def __init__(
        self,
        client: "INDIClient",
        device_name: str,
        event_bus: Optional[UnifiedEventBus] = None,
    ) -> None:
        """Initialize INDI camera.

        Args:
            client: INDI client connection
            device_name: INDI device name
            event_bus: Optional event bus for camera events
        """
        super().__init__(event_bus)
        self._client = client
        self._device_name = device_name
        self._device: Optional["PyIndi.BaseDevice"] = None
        self._last_blob: Optional[bytes] = None
        self._last_blob_width: int = 0
        self._last_blob_height: int = 0

    def _get_device(self) -> "PyIndi.BaseDevice":
        """Get the INDI device."""
        if self._device is None:
            self._device = self._client.get_device(self._device_name)
        if self._device is None:
            raise NotConnectedError(f"Device {self._device_name} not found")
        return self._device

    def _get_number(self, property_name: str) -> Optional["PyIndi.INumberVectorProperty"]:
        """Get a number property."""
        device = self._get_device()
        return device.getNumber(property_name)

    def _get_switch(self, property_name: str) -> Optional["PyIndi.ISwitchVectorProperty"]:
        """Get a switch property."""
        device = self._get_device()
        return device.getSwitch(property_name)

    async def connect(self) -> None:
        """Connect to the camera."""
        device = self._get_device()

        connection = device.getSwitch("CONNECTION")
        if connection:
            for i in range(connection.nsp):
                if connection[i].name == "CONNECT":
                    connection[i].s = PyIndi.ISS_ON
                else:
                    connection[i].s = PyIndi.ISS_OFF
            self._client.sendNewSwitch(connection)
            await asyncio.sleep(1.0)

        # Enable blob reception
        self._client.setBLOBMode(PyIndi.B_ALSO, self._device_name, None)

        self._connected = True

    async def disconnect(self) -> None:
        """Disconnect from the camera."""
        try:
            device = self._get_device()
            connection = device.getSwitch("CONNECTION")
            if connection:
                for i in range(connection.nsp):
                    if connection[i].name == "DISCONNECT":
                        connection[i].s = PyIndi.ISS_ON
                    else:
                        connection[i].s = PyIndi.ISS_OFF
                self._client.sendNewSwitch(connection)
        finally:
            self._connected = False

    async def get_capabilities(self) -> CameraCapabilities:
        """Get camera capabilities."""
        device = self._get_device()

        # Get frame info
        frame = self._get_number("CCD_FRAME")
        width = 0
        height = 0
        if frame:
            for i in range(frame.nnp):
                if frame[i].name == "WIDTH":
                    width = int(frame[i].value)
                elif frame[i].name == "HEIGHT":
                    height = int(frame[i].value)

        return CameraCapabilities(
            can_abort_exposure=True,
            can_set_gain=device.getNumber("CCD_GAIN") is not None,
            can_set_binning=device.getNumber("CCD_BINNING") is not None,
            can_subframe=frame is not None,
            has_cooler=device.getSwitch("CCD_COOLER") is not None,
            sensor_width=width,
            sensor_height=height,
        )

    async def start_exposure(self, settings: ExposureSettings) -> None:
        """Start an exposure."""
        # Set binning if available
        if settings.bin_x != 1 or settings.bin_y != 1:
            binning = self._get_number("CCD_BINNING")
            if binning:
                for i in range(binning.nnp):
                    if binning[i].name == "HOR_BIN":
                        binning[i].value = settings.bin_x
                    elif binning[i].name == "VER_BIN":
                        binning[i].value = settings.bin_y
                self._client.sendNewNumber(binning)

        # Emit exposure started event
        event = ExposureEvent(
            event_type=EventType.EXPOSURE_STARTED,
            source_device=self._device_name,
            source_backend="indi",
            duration_seconds=settings.duration_seconds,
        )
        self._event_bus.emit_nowait(event)

        # Start exposure
        exposure = self._get_number("CCD_EXPOSURE")
        if exposure is None:
            raise DeviceError("CCD_EXPOSURE property not available")

        for i in range(exposure.nnp):
            if exposure[i].name == "CCD_EXPOSURE_VALUE":
                exposure[i].value = settings.duration_seconds
        self._client.sendNewNumber(exposure)

    async def abort_exposure(self) -> None:
        """Abort current exposure."""
        abort = self._get_switch("CCD_ABORT_EXPOSURE")
        if abort:
            for i in range(abort.nsp):
                if abort[i].name == "ABORT":
                    abort[i].s = PyIndi.ISS_ON
            self._client.sendNewSwitch(abort)

        event = ExposureEvent(
            event_type=EventType.EXPOSURE_ABORTED,
            source_device=self._device_name,
            source_backend="indi",
        )
        self._event_bus.emit_nowait(event)

    async def is_exposing(self) -> bool:
        """Check if currently exposing."""
        exposure = self._get_number("CCD_EXPOSURE")
        if exposure:
            return exposure.s == PyIndi.IPS_BUSY
        return False

    async def get_image(self) -> ImageData:
        """Get the last captured image.

        Note: INDI sends images as BLOBs which need to be caught
        by a callback. This is a simplified implementation.
        """
        if self._last_blob is None:
            raise DeviceError("No image available")

        return ImageData(
            width=self._last_blob_width or 1,
            height=self._last_blob_height or 1,
            data=self._last_blob,
            bit_depth=16,
            is_color=False,
        )

    async def set_cooler(
        self, enabled: bool, setpoint: Optional[float] = None
    ) -> None:
        """Control cooler."""
        cooler = self._get_switch("CCD_COOLER")
        if cooler:
            for i in range(cooler.nsp):
                if enabled and cooler[i].name == "COOLER_ON":
                    cooler[i].s = PyIndi.ISS_ON
                elif not enabled and cooler[i].name == "COOLER_OFF":
                    cooler[i].s = PyIndi.ISS_ON
                else:
                    cooler[i].s = PyIndi.ISS_OFF
            self._client.sendNewSwitch(cooler)

        if setpoint is not None and enabled:
            temp = self._get_number("CCD_TEMPERATURE")
            if temp:
                for i in range(temp.nnp):
                    if temp[i].name == "CCD_TEMPERATURE_VALUE":
                        temp[i].value = setpoint
                self._client.sendNewNumber(temp)

    async def get_temperature(self) -> Optional[float]:
        """Get sensor temperature."""
        temp = self._get_number("CCD_TEMPERATURE")
        if temp:
            for i in range(temp.nnp):
                if temp[i].name == "CCD_TEMPERATURE_VALUE":
                    return temp[i].value
        return None

    async def get_status(self) -> CameraStatus:
        """Get camera status."""
        exposure = self._get_number("CCD_EXPOSURE")
        exposing = exposure is not None and exposure.s == PyIndi.IPS_BUSY

        temp = await self.get_temperature()

        cooler = self._get_switch("CCD_COOLER")
        cooler_on = False
        if cooler:
            for i in range(cooler.nsp):
                if cooler[i].name == "COOLER_ON" and cooler[i].s == PyIndi.ISS_ON:
                    cooler_on = True
                    break

        state = CameraState.EXPOSING if exposing else CameraState.IDLE

        return CameraStatus(
            connected=self._connected,
            name=self._device_name,
            driver_info="INDI",
            driver_version="1.0.0",
            state=state,
            temperature=temp,
            cooler_on=cooler_on,
        )
