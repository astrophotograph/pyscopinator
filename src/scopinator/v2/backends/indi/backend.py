"""INDI backend using pyindi-client.

INDI uses a client-server architecture where an INDI server hosts
device drivers and clients connect to it to control devices.
"""

import asyncio
from typing import Any, Optional

from scopinator.v2.backends.base import Backend, BackendInfo
from scopinator.v2.core.devices import Camera, Focuser, FilterWheel, Mount
from scopinator.v2.core.events import EventType, UnifiedEvent, UnifiedEventBus
from scopinator.v2.core.exceptions import ConnectionError, NotSupportedError

# Try to import pyindi-client
try:
    import PyIndi

    INDI_AVAILABLE = True
except ImportError:
    INDI_AVAILABLE = False
    PyIndi = None


class INDIBackend(Backend):
    """Backend for INDI devices via pyindi-client.

    INDI uses a different paradigm than Alpaca - a central server (indiserver)
    hosts device drivers, and clients connect to receive property updates
    via callbacks.

    Example:
        backend = INDIBackend(host="localhost", port=7624)
        await backend.connect()

        devices = await backend.discover_devices()
        mount = await backend.get_mount("EQMod Mount")
        await mount.connect()

    Note: Requires pyindi-client to be installed.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 7624,
        event_bus: Optional[UnifiedEventBus] = None,
    ) -> None:
        """Initialize INDI backend.

        Args:
            host: INDI server hostname
            port: INDI server port (default 7624)
            event_bus: Optional shared event bus

        Raises:
            ImportError: If pyindi-client is not installed
        """
        if not INDI_AVAILABLE:
            raise ImportError(
                "pyindi-client is not installed. "
                "Install with: pip install pyindi-client"
            )

        super().__init__(event_bus)
        self._host = host
        self._port = port
        self._client: Optional["INDIClient"] = None
        self._discovered_devices: dict[str, list[str]] = {}

    @property
    def host(self) -> str:
        """Get the INDI server host."""
        return self._host

    @property
    def port(self) -> int:
        """Get the INDI server port."""
        return self._port

    async def connect(self) -> None:
        """Connect to INDI server."""
        try:
            self._client = INDIClient(self._host, self._port, self._event_bus)
            connected = self._client.connectServer()

            if not connected:
                raise ConnectionError(
                    f"Failed to connect to INDI server at {self._host}:{self._port}"
                )

            # Wait a moment for device discovery
            await asyncio.sleep(1.0)

            self._connected = True

            # Emit connected event
            event = UnifiedEvent(
                event_type=EventType.CONNECTED,
                source_device="indi",
                source_backend="indi",
                data={"host": self._host, "port": self._port},
            )
            self._event_bus.emit_nowait(event)

        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Failed to connect to INDI server: {e}")

    async def disconnect(self) -> None:
        """Disconnect from INDI server."""
        try:
            if self._client:
                self._client.disconnectServer()
        finally:
            self._client = None
            self._connected = False
            self._discovered_devices.clear()

            # Emit disconnected event
            event = UnifiedEvent(
                event_type=EventType.DISCONNECTED,
                source_device="indi",
                source_backend="indi",
            )
            self._event_bus.emit_nowait(event)

    async def discover_devices(self) -> dict[str, list[str]]:
        """Get list of devices from INDI server.

        Returns:
            Dict mapping device type to list of device names
        """
        if not self._client:
            return {}

        result: dict[str, list[str]] = {
            "mount": [],
            "camera": [],
            "focuser": [],
            "filterwheel": [],
        }

        # Get devices from the client
        devices = self._client.getDevices()
        for device in devices:
            name = device.getDeviceName()
            interfaces = device.getDriverInterface()

            # Check device type via interface flags
            if interfaces & PyIndi.BaseDevice.TELESCOPE_INTERFACE:
                result["mount"].append(name)
            if interfaces & PyIndi.BaseDevice.CCD_INTERFACE:
                result["camera"].append(name)
            if interfaces & PyIndi.BaseDevice.FOCUSER_INTERFACE:
                result["focuser"].append(name)
            if interfaces & PyIndi.BaseDevice.FILTER_INTERFACE:
                result["filterwheel"].append(name)

        self._discovered_devices = result
        return result

    async def get_mount(self, device_id: str) -> Mount:
        """Get INDI telescope.

        Args:
            device_id: Device name as shown in INDI

        Returns:
            INDIMount instance
        """
        if not self._client:
            raise ConnectionError("Not connected to INDI server")

        from scopinator.v2.backends.indi.mount import INDIMount

        return INDIMount(
            client=self._client,
            device_name=device_id,
            event_bus=self._event_bus,
        )

    async def get_camera(self, device_id: str) -> Camera:
        """Get INDI camera.

        Args:
            device_id: Device name as shown in INDI

        Returns:
            INDICamera instance
        """
        if not self._client:
            raise ConnectionError("Not connected to INDI server")

        from scopinator.v2.backends.indi.camera import INDICamera

        return INDICamera(
            client=self._client,
            device_name=device_id,
            event_bus=self._event_bus,
        )

    async def get_focuser(self, device_id: str) -> Focuser:
        """Get INDI focuser."""
        raise NotSupportedError("INDI focuser not yet implemented")

    async def get_filterwheel(self, device_id: str) -> FilterWheel:
        """Get INDI filter wheel."""
        raise NotSupportedError("INDI filter wheel not yet implemented")

    def get_info(self) -> BackendInfo:
        """Get backend information."""
        return BackendInfo(
            name="INDI",
            version="1.0.0",
            description="INDI protocol backend via pyindi-client",
            protocol="indi",
        )

    def __repr__(self) -> str:
        return f"INDIBackend(host={self._host}, port={self._port}, connected={self._connected})"


if INDI_AVAILABLE:

    class INDIClient(PyIndi.BaseClient):
        """INDI client wrapper with event bus integration."""

        def __init__(
            self,
            host: str,
            port: int,
            event_bus: UnifiedEventBus,
        ) -> None:
            """Initialize INDI client.

            Args:
                host: INDI server hostname
                port: INDI server port
                event_bus: Event bus for emitting INDI events
            """
            super().__init__()
            self._event_bus = event_bus
            self._devices: dict[str, "PyIndi.BaseDevice"] = {}

            self.setServer(host, port)

        def get_device(self, name: str) -> Optional["PyIndi.BaseDevice"]:
            """Get a device by name."""
            return self._devices.get(name)

        # PyIndi callback implementations

        def newDevice(self, d: "PyIndi.BaseDevice") -> None:
            """Called when a new device is discovered."""
            self._devices[d.getDeviceName()] = d

        def removeDevice(self, d: "PyIndi.BaseDevice") -> None:
            """Called when a device is removed."""
            self._devices.pop(d.getDeviceName(), None)

        def newProperty(self, p: "PyIndi.Property") -> None:
            """Called when a new property is defined."""
            pass

        def updateProperty(self, p: "PyIndi.Property") -> None:
            """Called when a property is updated."""
            # Could translate to unified events here
            pass

        def removeProperty(self, p: "PyIndi.Property") -> None:
            """Called when a property is removed."""
            pass

        def newMessage(self, d: "PyIndi.BaseDevice", m: int) -> None:
            """Called when a message is received."""
            pass

        def serverConnected(self) -> None:
            """Called when connected to server."""
            pass

        def serverDisconnected(self, code: int) -> None:
            """Called when disconnected from server."""
            pass
