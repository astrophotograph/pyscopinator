"""ASCOM Alpaca backend using HTTP REST API.

This backend connects to ASCOM Alpaca servers and provides access to
devices exposed via the Alpaca REST API.
"""

from typing import Optional

import aiohttp

from scopinator.v2.backends.alpaca.camera import AlpacaCamera
from scopinator.v2.backends.alpaca.discovery import AlpacaDiscovery
from scopinator.v2.backends.alpaca.filterwheel import AlpacaFilterWheel
from scopinator.v2.backends.alpaca.focuser import AlpacaFocuser
from scopinator.v2.backends.alpaca.mount import AlpacaMount
from scopinator.v2.backends.base import Backend, BackendInfo
from scopinator.v2.core.devices import Camera, Focuser, FilterWheel, Mount
from scopinator.v2.core.events import EventType, UnifiedEvent, UnifiedEventBus
from scopinator.v2.core.exceptions import ConnectionError, DeviceError


class AlpacaBackend(Backend):
    """Backend for ASCOM Alpaca devices via HTTP REST.

    ASCOM Alpaca provides a cross-platform HTTP REST API for controlling
    astronomy equipment. This backend connects to an Alpaca server and
    provides access to telescopes, cameras, focusers, and filter wheels.

    Example:
        backend = AlpacaBackend(host="localhost", port=11111)
        await backend.connect()

        devices = await backend.discover_devices()
        mount = await backend.get_mount("mount_0")
        await mount.connect()

        await mount.slew_to_coordinates(Coordinates(ra=83.63, dec=22.01))
    """

    def __init__(
        self,
        host: str,
        port: int = 11111,
        event_bus: Optional[UnifiedEventBus] = None,
    ) -> None:
        """Initialize Alpaca backend.

        Args:
            host: Alpaca server hostname or IP
            port: Alpaca server port (default 11111)
            event_bus: Optional shared event bus
        """
        super().__init__(event_bus)
        self._host = host
        self._port = port
        self._base_url = f"http://{host}:{port}"
        self._session: Optional[aiohttp.ClientSession] = None
        self._client_id = 1
        self._transaction_id = 0

        # Discovered devices cache
        self._discovered_devices: dict[str, list[dict]] = {}

        # Cached device instances
        self._mounts: dict[str, AlpacaMount] = {}
        self._cameras: dict[str, AlpacaCamera] = {}
        self._focusers: dict[str, AlpacaFocuser] = {}
        self._filterwheels: dict[str, AlpacaFilterWheel] = {}

    @property
    def host(self) -> str:
        """Get the Alpaca server host."""
        return self._host

    @property
    def port(self) -> int:
        """Get the Alpaca server port."""
        return self._port

    @property
    def base_url(self) -> str:
        """Get the base URL for API requests."""
        return self._base_url

    def _next_transaction_id(self) -> int:
        """Get next transaction ID for Alpaca requests."""
        self._transaction_id += 1
        return self._transaction_id

    async def connect(self) -> None:
        """Initialize HTTP session and verify connection."""
        try:
            self._session = aiohttp.ClientSession()

            # Verify connection by getting API versions
            discovery = AlpacaDiscovery(self._session, self._base_url)
            await discovery.get_api_versions()

            self._connected = True

            # Emit connected event
            event = UnifiedEvent(
                event_type=EventType.CONNECTED,
                source_device="alpaca",
                source_backend="alpaca",
                data={"host": self._host, "port": self._port},
            )
            self._event_bus.emit_nowait(event)

        except Exception as e:
            if self._session:
                await self._session.close()
                self._session = None
            self._connected = False
            raise ConnectionError(
                f"Failed to connect to Alpaca server at {self._base_url}: {e}"
            )

    async def disconnect(self) -> None:
        """Close HTTP session."""
        try:
            # Disconnect all cached devices
            for mount in self._mounts.values():
                try:
                    await mount.disconnect()
                except Exception:
                    pass
            for camera in self._cameras.values():
                try:
                    await camera.disconnect()
                except Exception:
                    pass
            for focuser in self._focusers.values():
                try:
                    await focuser.disconnect()
                except Exception:
                    pass
            for filterwheel in self._filterwheels.values():
                try:
                    await filterwheel.disconnect()
                except Exception:
                    pass

            if self._session:
                await self._session.close()
        finally:
            self._session = None
            self._connected = False
            self._mounts.clear()
            self._cameras.clear()
            self._focusers.clear()
            self._filterwheels.clear()
            self._discovered_devices.clear()

            # Emit disconnected event
            event = UnifiedEvent(
                event_type=EventType.DISCONNECTED,
                source_device="alpaca",
                source_backend="alpaca",
            )
            self._event_bus.emit_nowait(event)

    async def discover_devices(self) -> dict[str, list[str]]:
        """Discover available Alpaca devices via management API.

        Returns:
            Dict mapping device type to list of device IDs
        """
        if not self._session:
            return {}

        discovery = AlpacaDiscovery(self._session, self._base_url)
        self._discovered_devices = await discovery.get_configured_devices()

        # Convert to simple device ID list
        result: dict[str, list[str]] = {}
        for device_type, devices in self._discovered_devices.items():
            result[device_type] = [
                f"{device_type}_{d['DeviceNumber']}" for d in devices
            ]

        return result

    async def get_mount(self, device_id: str) -> Mount:
        """Get Alpaca telescope/mount.

        Args:
            device_id: Device ID (e.g., "mount_0")

        Returns:
            AlpacaMount instance
        """
        if not self._session:
            raise DeviceError("Not connected to Alpaca server")

        if device_id in self._mounts:
            return self._mounts[device_id]

        # Parse device number from ID
        try:
            device_num = int(device_id.split("_")[-1])
        except ValueError:
            device_num = 0

        mount = AlpacaMount(
            session=self._session,
            base_url=self._base_url,
            device_number=device_num,
            client_id=self._client_id,
            get_transaction_id=self._next_transaction_id,
            event_bus=self._event_bus,
        )

        self._mounts[device_id] = mount
        return mount

    async def get_camera(self, device_id: str) -> Camera:
        """Get Alpaca camera.

        Args:
            device_id: Device ID (e.g., "camera_0")

        Returns:
            AlpacaCamera instance
        """
        if not self._session:
            raise DeviceError("Not connected to Alpaca server")

        if device_id in self._cameras:
            return self._cameras[device_id]

        # Parse device number from ID
        try:
            device_num = int(device_id.split("_")[-1])
        except ValueError:
            device_num = 0

        camera = AlpacaCamera(
            session=self._session,
            base_url=self._base_url,
            device_number=device_num,
            client_id=self._client_id,
            get_transaction_id=self._next_transaction_id,
            event_bus=self._event_bus,
        )

        self._cameras[device_id] = camera
        return camera

    async def get_focuser(self, device_id: str) -> Focuser:
        """Get Alpaca focuser.

        Args:
            device_id: Device ID (e.g., "focuser_0")

        Returns:
            AlpacaFocuser instance
        """
        if not self._session:
            raise DeviceError("Not connected to Alpaca server")

        if device_id in self._focusers:
            return self._focusers[device_id]

        # Parse device number from ID
        try:
            device_num = int(device_id.split("_")[-1])
        except ValueError:
            device_num = 0

        focuser = AlpacaFocuser(
            session=self._session,
            base_url=self._base_url,
            device_number=device_num,
            client_id=self._client_id,
            get_transaction_id=self._next_transaction_id,
            event_bus=self._event_bus,
        )

        self._focusers[device_id] = focuser
        return focuser

    async def get_filterwheel(self, device_id: str) -> FilterWheel:
        """Get Alpaca filter wheel.

        Args:
            device_id: Device ID (e.g., "filterwheel_0")

        Returns:
            AlpacaFilterWheel instance
        """
        if not self._session:
            raise DeviceError("Not connected to Alpaca server")

        if device_id in self._filterwheels:
            return self._filterwheels[device_id]

        # Parse device number from ID
        try:
            device_num = int(device_id.split("_")[-1])
        except ValueError:
            device_num = 0

        filterwheel = AlpacaFilterWheel(
            session=self._session,
            base_url=self._base_url,
            device_number=device_num,
            client_id=self._client_id,
            get_transaction_id=self._next_transaction_id,
            event_bus=self._event_bus,
        )

        self._filterwheels[device_id] = filterwheel
        return filterwheel

    def get_info(self) -> BackendInfo:
        """Get backend information."""
        return BackendInfo(
            name="ASCOM Alpaca",
            version="1.0.0",
            description="ASCOM Alpaca HTTP REST backend",
            protocol="alpaca",
        )

    def __repr__(self) -> str:
        return f"AlpacaBackend(host={self._host}, port={self._port}, connected={self._connected})"
