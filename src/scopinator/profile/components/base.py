"""Base component interface for profile components.

All telescope equipment components (mount, camera, etc.) inherit from
BaseComponent to provide a common interface for connection management
and status reporting.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ComponentState(str, Enum):
    """State of a component."""

    UNKNOWN = "unknown"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    BUSY = "busy"


class BaseComponent(BaseModel, ABC):
    """Base class for all profile components.

    Components represent individual pieces of equipment in a telescope
    setup. They provide a common interface for connection management,
    configuration, and status reporting.
    """

    name: str = Field(..., description="User-friendly name for this component")
    device_type: str = Field(..., description="Type identifier (e.g., 'seestar', 'asi294')")
    manufacturer: Optional[str] = Field(None, description="Device manufacturer")
    model: Optional[str] = Field(None, description="Device model")

    # Connection info
    connection_type: str = Field(
        default="tcp", description="Connection type: tcp, usb, serial, indi, alpaca"
    )
    host: Optional[str] = Field(None, description="Host address for network devices")
    port: Optional[int] = Field(None, description="Port for network devices")

    # State tracking (not persisted)
    state: ComponentState = Field(default=ComponentState.DISCONNECTED, exclude=True)
    last_error: Optional[str] = Field(None, exclude=True)

    # Metadata
    firmware_version: Optional[str] = Field(None)
    serial_number: Optional[str] = Field(None)

    model_config = {"use_enum_values": False, "extra": "allow"}

    @abstractmethod
    async def connect(self) -> bool:
        """Connect to the device.

        Returns:
            True on success, False on failure
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the device."""
        pass

    @abstractmethod
    async def get_status(self) -> dict[str, Any]:
        """Get current device status.

        Returns:
            Dict with status information
        """
        pass
