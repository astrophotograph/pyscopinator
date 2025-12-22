"""Base backend class.

All protocol backends must implement this abstract base class to provide
a unified interface for device discovery and instantiation.
"""

from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, Field

from scopinator.v2.core.devices import Camera, FilterWheel, Focuser, Mount
from scopinator.v2.core.events import UnifiedEventBus


class BackendInfo(BaseModel):
    """Information about a backend."""

    name: str = Field(..., description="Backend name")
    version: str = Field(default="1.0.0", description="Backend version")
    description: str = Field(default="", description="Backend description")
    protocol: str = Field(default="unknown", description="Protocol type")


class Backend(ABC):
    """Abstract base class for all backends.

    A backend represents a connection to a device control system
    (e.g., Seestar telescope, ASCOM Alpaca server, INDI server).

    Implementations must provide methods for:
    - Connecting to the backend
    - Discovering available devices
    - Creating device instances (Mount, Camera, etc.)

    Example:
        backend = SeestarBackend(host="192.168.1.100")
        await backend.connect()

        devices = await backend.discover_devices()
        # {'mount': ['seestar_mount'], 'camera': ['seestar_camera']}

        mount = await backend.get_mount('seestar_mount')
        await mount.connect()
    """

    def __init__(self, event_bus: Optional[UnifiedEventBus] = None) -> None:
        """Initialize backend.

        Args:
            event_bus: Optional shared event bus. If not provided, a new
                      one will be created.
        """
        self._event_bus = event_bus or UnifiedEventBus()
        self._connected = False

    @property
    def event_bus(self) -> UnifiedEventBus:
        """Get the event bus for this backend."""
        return self._event_bus

    @event_bus.setter
    def event_bus(self, value: UnifiedEventBus) -> None:
        """Set the event bus (used by DeviceManager)."""
        self._event_bus = value

    @property
    def is_connected(self) -> bool:
        """Check if backend is connected."""
        return self._connected

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the backend.

        For Seestar: Establish TCP connection
        For Alpaca: Initialize HTTP session
        For INDI: Connect to INDI server

        Raises:
            ConnectionError: If connection fails
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the backend."""
        pass

    @abstractmethod
    async def discover_devices(self) -> dict[str, list[str]]:
        """Discover available devices.

        Returns:
            Dict mapping device type to list of device IDs.
            Device types: "mount", "camera", "focuser", "filterwheel"

            Example:
                {
                    "mount": ["Celestron CGX"],
                    "camera": ["ZWO ASI294MC Pro"],
                    "focuser": ["ZWO EAF"]
                }
        """
        pass

    @abstractmethod
    async def get_mount(self, device_id: str) -> Mount:
        """Get a mount device by ID.

        Args:
            device_id: Device identifier from discover_devices()

        Returns:
            Mount instance (not yet connected)

        Raises:
            DeviceError: If device not found
        """
        pass

    @abstractmethod
    async def get_camera(self, device_id: str) -> Camera:
        """Get a camera device by ID.

        Args:
            device_id: Device identifier from discover_devices()

        Returns:
            Camera instance (not yet connected)

        Raises:
            DeviceError: If device not found
        """
        pass

    async def get_focuser(self, device_id: str) -> Focuser:
        """Get a focuser device by ID.

        Override if backend supports focusers.

        Args:
            device_id: Device identifier from discover_devices()

        Returns:
            Focuser instance (not yet connected)

        Raises:
            NotSupportedError: If backend doesn't support focusers
        """
        from scopinator.v2.core.exceptions import NotSupportedError

        raise NotSupportedError(f"{self.__class__.__name__} does not support focusers")

    async def get_filterwheel(self, device_id: str) -> FilterWheel:
        """Get a filter wheel device by ID.

        Override if backend supports filter wheels.

        Args:
            device_id: Device identifier from discover_devices()

        Returns:
            FilterWheel instance (not yet connected)

        Raises:
            NotSupportedError: If backend doesn't support filter wheels
        """
        from scopinator.v2.core.exceptions import NotSupportedError

        raise NotSupportedError(
            f"{self.__class__.__name__} does not support filter wheels"
        )

    @abstractmethod
    def get_info(self) -> BackendInfo:
        """Get backend information.

        Returns:
            BackendInfo with name, version, description
        """
        pass

    async def __aenter__(self) -> "Backend":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Async context manager exit."""
        await self.disconnect()
        return False
