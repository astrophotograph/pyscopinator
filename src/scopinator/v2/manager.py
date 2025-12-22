"""Device manager for orchestrating multiple backends.

The DeviceManager provides a unified interface for working with devices
across multiple protocol backends (Seestar, Alpaca, INDI). It handles
backend lifecycle, device caching, and event bus distribution.
"""

from typing import Optional

from scopinator.v2.backends.base import Backend
from scopinator.v2.core.devices import Camera, FilterWheel, Focuser, Mount
from scopinator.v2.core.events import UnifiedEventBus


class DeviceManager:
    """Manages multiple backends and provides unified device access.

    The DeviceManager is the main entry point for multi-protocol telescope
    control. It allows registering multiple backends and provides a unified
    way to access devices regardless of their underlying protocol.

    Example:
        manager = DeviceManager()

        # Add backends
        await manager.add_backend("seestar", SeestarBackend("192.168.1.100"))
        await manager.add_backend("alpaca", AlpacaBackend("localhost"))

        # Discover devices from all backends
        all_devices = await manager.discover_all()
        # {
        #     "seestar": {"mount": ["seestar_mount"], "camera": ["seestar_camera"]},
        #     "alpaca": {"mount": ["mount_0"], "camera": ["camera_0"]}
        # }

        # Get a specific device
        mount = await manager.get_mount("seestar", "seestar_mount")
        await mount.slew_to_coordinates(Coordinates(ra=83.63, dec=22.01))
    """

    def __init__(self, event_bus: Optional[UnifiedEventBus] = None) -> None:
        """Initialize device manager.

        Args:
            event_bus: Optional shared event bus. If not provided, a new
                      one will be created and shared with all backends.
        """
        self._event_bus = event_bus or UnifiedEventBus()
        self._backends: dict[str, Backend] = {}
        self._mounts: dict[str, Mount] = {}
        self._cameras: dict[str, Camera] = {}
        self._focusers: dict[str, Focuser] = {}
        self._filterwheels: dict[str, FilterWheel] = {}

    @property
    def event_bus(self) -> UnifiedEventBus:
        """Get the shared event bus."""
        return self._event_bus

    @property
    def backends(self) -> dict[str, Backend]:
        """Get all registered backends."""
        return dict(self._backends)

    def get_backend(self, name: str) -> Optional[Backend]:
        """Get a backend by name.

        Args:
            name: Backend name

        Returns:
            Backend instance or None if not found
        """
        return self._backends.get(name)

    async def add_backend(self, name: str, backend: Backend) -> None:
        """Add and connect a backend.

        The backend will share the manager's event bus for unified
        event handling.

        Args:
            name: Unique name for this backend
            backend: Backend instance to add

        Raises:
            ValueError: If a backend with this name already exists
        """
        if name in self._backends:
            raise ValueError(f"Backend '{name}' already exists")

        # Share the event bus
        backend.event_bus = self._event_bus

        # Connect the backend
        await backend.connect()

        self._backends[name] = backend

    async def remove_backend(self, name: str) -> None:
        """Disconnect and remove a backend.

        Args:
            name: Backend name to remove
        """
        if name in self._backends:
            backend = self._backends[name]
            await backend.disconnect()
            del self._backends[name]

            # Remove cached devices from this backend
            prefix = f"{name}:"
            self._mounts = {k: v for k, v in self._mounts.items() if not k.startswith(prefix)}
            self._cameras = {k: v for k, v in self._cameras.items() if not k.startswith(prefix)}
            self._focusers = {k: v for k, v in self._focusers.items() if not k.startswith(prefix)}
            self._filterwheels = {
                k: v for k, v in self._filterwheels.items() if not k.startswith(prefix)
            }

    async def discover_all(self) -> dict[str, dict[str, list[str]]]:
        """Discover devices from all backends.

        Returns:
            Dict mapping backend name to device discovery results.

            Example:
                {
                    "seestar": {
                        "mount": ["seestar_mount"],
                        "camera": ["seestar_camera"]
                    },
                    "alpaca": {
                        "mount": ["mount_0"],
                        "camera": ["camera_0"]
                    }
                }
        """
        result: dict[str, dict[str, list[str]]] = {}
        for name, backend in self._backends.items():
            try:
                result[name] = await backend.discover_devices()
            except Exception:
                result[name] = {}
        return result

    async def get_mount(self, backend_name: str, device_id: str) -> Mount:
        """Get a mount from a specific backend.

        Devices are cached, so calling this multiple times with the same
        arguments returns the same instance.

        Args:
            backend_name: Name of the backend
            device_id: Device ID within that backend

        Returns:
            Mount instance

        Raises:
            ValueError: If backend not found
            DeviceError: If device not found
        """
        key = f"{backend_name}:{device_id}"

        if key not in self._mounts:
            backend = self._backends.get(backend_name)
            if not backend:
                raise ValueError(f"Unknown backend: {backend_name}")

            mount = await backend.get_mount(device_id)
            self._mounts[key] = mount

        return self._mounts[key]

    async def get_camera(self, backend_name: str, device_id: str) -> Camera:
        """Get a camera from a specific backend.

        Args:
            backend_name: Name of the backend
            device_id: Device ID within that backend

        Returns:
            Camera instance

        Raises:
            ValueError: If backend not found
            DeviceError: If device not found
        """
        key = f"{backend_name}:{device_id}"

        if key not in self._cameras:
            backend = self._backends.get(backend_name)
            if not backend:
                raise ValueError(f"Unknown backend: {backend_name}")

            camera = await backend.get_camera(device_id)
            self._cameras[key] = camera

        return self._cameras[key]

    async def get_focuser(self, backend_name: str, device_id: str) -> Focuser:
        """Get a focuser from a specific backend.

        Args:
            backend_name: Name of the backend
            device_id: Device ID within that backend

        Returns:
            Focuser instance

        Raises:
            ValueError: If backend not found
            DeviceError: If device not found
        """
        key = f"{backend_name}:{device_id}"

        if key not in self._focusers:
            backend = self._backends.get(backend_name)
            if not backend:
                raise ValueError(f"Unknown backend: {backend_name}")

            focuser = await backend.get_focuser(device_id)
            self._focusers[key] = focuser

        return self._focusers[key]

    async def get_filterwheel(self, backend_name: str, device_id: str) -> FilterWheel:
        """Get a filter wheel from a specific backend.

        Args:
            backend_name: Name of the backend
            device_id: Device ID within that backend

        Returns:
            FilterWheel instance

        Raises:
            ValueError: If backend not found
            DeviceError: If device not found
        """
        key = f"{backend_name}:{device_id}"

        if key not in self._filterwheels:
            backend = self._backends.get(backend_name)
            if not backend:
                raise ValueError(f"Unknown backend: {backend_name}")

            filterwheel = await backend.get_filterwheel(device_id)
            self._filterwheels[key] = filterwheel

        return self._filterwheels[key]

    async def disconnect_all(self) -> None:
        """Disconnect all backends and clear cached devices."""
        for name in list(self._backends.keys()):
            await self.remove_backend(name)

    async def __aenter__(self) -> "DeviceManager":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Async context manager exit - disconnects all backends."""
        await self.disconnect_all()
        return False

    def __repr__(self) -> str:
        backend_names = list(self._backends.keys())
        return f"DeviceManager(backends={backend_names})"
