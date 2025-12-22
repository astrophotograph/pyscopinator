"""Seestar backend - adapts existing SeestarClient to V2 interface.

This backend wraps the existing Seestar protocol implementation to
provide the V2 abstraction layer, enabling multi-protocol support
without breaking existing code.
"""

from typing import Optional

from scopinator.seestar.client import SeestarClient
from scopinator.seestar.imaging_client import SeestarImagingClient
from scopinator.v2.backends.base import Backend, BackendInfo
from scopinator.v2.backends.seestar.camera import SeestarCamera
from scopinator.v2.backends.seestar.event_translator import SeestarEventTranslator
from scopinator.v2.backends.seestar.mount import SeestarMount
from scopinator.v2.core.devices import Camera, Focuser, Mount
from scopinator.v2.core.events import EventType, UnifiedEvent, UnifiedEventBus
from scopinator.v2.core.exceptions import ConnectionError, DeviceError


class SeestarBackend(Backend):
    """Backend for Seestar telescopes.

    This is an adapter that wraps the existing SeestarClient and
    SeestarImagingClient to provide the V2 interface. The underlying
    Seestar protocol implementation is preserved and reused.

    Example:
        backend = SeestarBackend(host="192.168.1.100")
        await backend.connect()

        mount = await backend.get_mount("seestar_mount")
        await mount.slew_to_coordinates(Coordinates(ra=83.63, dec=22.01))

        camera = await backend.get_camera("seestar_camera")
        await camera.start_exposure(ExposureSettings(duration_seconds=10.0))
    """

    def __init__(
        self,
        host: str,
        port: int = 4700,
        imaging_port: int = 4800,
        event_bus: Optional[UnifiedEventBus] = None,
    ) -> None:
        """Initialize Seestar backend.

        Args:
            host: Seestar telescope IP address
            port: Control port (default 4700)
            imaging_port: Imaging port (default 4800)
            event_bus: Optional shared event bus
        """
        super().__init__(event_bus)
        self._host = host
        self._port = port
        self._imaging_port = imaging_port

        # The underlying Seestar clients
        self._client: Optional[SeestarClient] = None
        self._imaging_client: Optional[SeestarImagingClient] = None

        # Event translator bridges Seestar events to unified events
        self._event_translator: Optional[SeestarEventTranslator] = None

        # Cached device instances
        self._mount: Optional[SeestarMount] = None
        self._camera: Optional[SeestarCamera] = None

    @property
    def host(self) -> str:
        """Get the Seestar host address."""
        return self._host

    @property
    def port(self) -> int:
        """Get the control port."""
        return self._port

    @property
    def client(self) -> Optional[SeestarClient]:
        """Get the underlying SeestarClient (for advanced use)."""
        return self._client

    @property
    def imaging_client(self) -> Optional[SeestarImagingClient]:
        """Get the underlying SeestarImagingClient (for advanced use)."""
        return self._imaging_client

    async def connect(self) -> None:
        """Connect to Seestar telescope."""
        try:
            # Create the translator first so it can receive events
            self._event_translator = SeestarEventTranslator(self._event_bus)

            # Create clients with the translator's event bus
            self._client = SeestarClient(
                host=self._host,
                port=self._port,
                event_bus=self._event_translator.seestar_event_bus,
            )

            self._imaging_client = SeestarImagingClient(
                host=self._host,
                port=self._imaging_port,
                event_bus=self._event_translator.seestar_event_bus,
            )

            # Connect both clients
            await self._client.connect()
            await self._imaging_client.connect()

            self._connected = True

            # Emit connected event
            event = UnifiedEvent(
                event_type=EventType.CONNECTED,
                source_device="seestar",
                source_backend="seestar",
                data={"host": self._host, "port": self._port},
            )
            self._event_bus.emit_nowait(event)

        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Failed to connect to Seestar at {self._host}: {e}")

    async def disconnect(self) -> None:
        """Disconnect from Seestar telescope."""
        try:
            if self._client:
                await self._client.disconnect()
            if self._imaging_client:
                await self._imaging_client.disconnect()
        finally:
            self._connected = False
            self._client = None
            self._imaging_client = None
            self._mount = None
            self._camera = None

            # Emit disconnected event
            event = UnifiedEvent(
                event_type=EventType.DISCONNECTED,
                source_device="seestar",
                source_backend="seestar",
            )
            self._event_bus.emit_nowait(event)

    async def discover_devices(self) -> dict[str, list[str]]:
        """Discover available devices.

        Seestar is a combined mount+camera device, so discovery always
        returns the same set of virtual devices.

        Returns:
            Dict with mount, camera, and focuser device IDs
        """
        if not self._connected:
            return {}

        return {
            "mount": ["seestar_mount"],
            "camera": ["seestar_camera"],
            "focuser": ["seestar_focuser"],  # Seestar has built-in focuser
        }

    async def get_mount(self, device_id: str) -> Mount:
        """Get Seestar mount interface.

        Args:
            device_id: Device ID (typically "seestar_mount")

        Returns:
            SeestarMount instance
        """
        if not self._client:
            raise DeviceError("Not connected to Seestar")

        if self._mount is None:
            self._mount = SeestarMount(
                client=self._client,
                event_bus=self._event_bus,
            )
            await self._mount.connect()

        return self._mount

    async def get_camera(self, device_id: str) -> Camera:
        """Get Seestar camera interface.

        Args:
            device_id: Device ID (typically "seestar_camera")

        Returns:
            SeestarCamera instance
        """
        if not self._client:
            raise DeviceError("Not connected to Seestar")

        if self._camera is None:
            self._camera = SeestarCamera(
                client=self._client,
                imaging_client=self._imaging_client,
                event_bus=self._event_bus,
            )
            await self._camera.connect()

        return self._camera

    async def get_focuser(self, device_id: str) -> Focuser:
        """Get Seestar focuser interface.

        Note: Seestar focuser support is not yet fully implemented
        in the V2 layer. The underlying client supports focuser
        commands, but the V2 Focuser adapter needs to be created.

        Args:
            device_id: Device ID (typically "seestar_focuser")

        Raises:
            NotSupportedError: Focuser V2 adapter not yet implemented
        """
        from scopinator.v2.core.exceptions import NotSupportedError

        raise NotSupportedError("Seestar focuser not yet implemented in V2")

    def get_info(self) -> BackendInfo:
        """Get backend information."""
        return BackendInfo(
            name="Seestar",
            version="1.0.0",
            description="ZWO Seestar smart telescope backend",
            protocol="seestar",
        )

    def __repr__(self) -> str:
        return f"SeestarBackend(host={self._host}, port={self._port}, connected={self._connected})"
