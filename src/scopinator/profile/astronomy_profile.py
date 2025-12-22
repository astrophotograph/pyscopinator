"""Main AstronomyProfile class for managing telescope setups.

The AstronomyProfile represents a complete telescope setup and provides
high-level methods for common operations like connecting, slewing,
and imaging.
"""

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Union

from pydantic import BaseModel, Field

from scopinator.profile.components.base import BaseComponent, ComponentState

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False


class ProfileState(str, Enum):
    """Overall profile state."""

    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    IMAGING = "imaging"
    SLEWING = "slewing"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class IntegratedDevice(BaseModel):
    """An integrated device that combines multiple components.

    This represents "smart scopes" like Seestar where mount, camera,
    and optics are combined into a single controllable unit.
    """

    name: str = Field(..., description="Device name")
    device_type: str = Field(default="integrated", description="Type identifier")
    manufacturer: Optional[str] = Field(None)
    model: Optional[str] = Field(None)

    # Connection info
    host: Optional[str] = Field(None)
    port: int = Field(default=4700)
    imaging_port: Optional[int] = Field(None)

    # What this device provides
    provides: list[str] = Field(
        default_factory=lambda: ["mount", "camera", "optics"]
    )

    model_config = {"extra": "allow"}


class SeestarDevice(IntegratedDevice):
    """Seestar-specific integrated device."""

    device_type: str = Field(default="seestar")
    manufacturer: str = Field(default="ZWO")
    model: str = Field(default="Seestar S50")
    provides: list[str] = Field(
        default_factory=lambda: ["mount", "camera", "optics", "focuser"]
    )
    port: int = Field(default=4700)
    imaging_port: int = Field(default=4800)

    # Seestar specs
    aperture_mm: float = Field(default=50.0)
    focal_length_mm: float = Field(default=250.0)
    has_lp_filter: bool = Field(default=True)


class AstronomyProfile(BaseModel):
    """Complete astronomy equipment profile.

    This is the main entry point for managing a telescope setup.
    It can contain individual components or an integrated device
    like a smart scope.

    Example:
        # Create from discovery
        devices = await AstronomyProfile.discover()
        profile = await AstronomyProfile.create_from_discovery(devices[0])

        # Or load from file
        profile = AstronomyProfile.load("my_telescope.yaml")

        # Connect and use
        async with profile:
            await profile.goto((83.63, 22.01))
            await profile.start_imaging()
    """

    # Profile metadata
    name: str = Field(..., description="Profile name")
    description: Optional[str] = Field(None)
    version: str = Field(default="1.0")

    # For integrated devices (smart scopes)
    integrated_device: Optional[IntegratedDevice] = Field(None)

    # Observer location
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    elevation_m: Optional[float] = Field(None)
    timezone: Optional[str] = Field(None)

    # State management (not persisted)
    state: ProfileState = Field(default=ProfileState.IDLE, exclude=True)

    # Runtime references (not persisted)
    _client: Any = None
    _imaging_client: Any = None

    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    # ========== Discovery Methods ==========

    @classmethod
    async def discover(cls, timeout: float = 10.0) -> list[dict[str, Any]]:
        """Discover available devices on the network.

        Returns:
            List of discovered devices with their connection info
        """
        from scopinator.seestar.commands.discovery import discover_seestars

        discovered = []

        # Discover Seestar devices
        try:
            seestars = await discover_seestars(timeout=timeout)
            for device in seestars:
                discovered.append({
                    "type": "seestar",
                    "manufacturer": "ZWO",
                    "model": "Seestar S50",
                    "host": device["address"],
                    "port": 4700,
                    "data": device.get("data", {}),
                })
        except Exception:
            pass  # Discovery failed, continue

        return discovered

    @classmethod
    async def create_from_discovery(
        cls,
        device_info: dict[str, Any],
        profile_name: Optional[str] = None,
    ) -> "AstronomyProfile":
        """Create a profile from a discovered device.

        Args:
            device_info: Device info from discover()
            profile_name: Optional custom profile name

        Returns:
            AstronomyProfile configured for the device
        """
        device_type = device_info.get("type", "unknown")

        if device_type == "seestar":
            return cls(
                name=profile_name or f"Seestar at {device_info['host']}",
                integrated_device=SeestarDevice(
                    name="Seestar S50",
                    host=device_info["host"],
                    port=device_info.get("port", 4700),
                ),
            )

        raise ValueError(f"Unknown device type: {device_type}")

    # ========== Connection Methods ==========

    async def connect(self) -> bool:
        """Connect all configured components.

        Returns:
            True if all components connected successfully
        """
        self.state = ProfileState.CONNECTING

        try:
            if self.integrated_device:
                device_type = self.integrated_device.device_type

                if device_type == "seestar":
                    from scopinator.seestar.client import SeestarClient
                    from scopinator.seestar.imaging_client import SeestarImagingClient
                    from scopinator.util.eventbus import EventBus

                    event_bus = EventBus()

                    self._client = SeestarClient(
                        host=self.integrated_device.host,
                        port=self.integrated_device.port,
                        event_bus=event_bus,
                    )

                    imaging_port = getattr(self.integrated_device, "imaging_port", None)
                    if imaging_port:
                        self._imaging_client = SeestarImagingClient(
                            host=self.integrated_device.host,
                            port=imaging_port,
                            event_bus=event_bus,
                        )

                    await self._client.connect()
                    if self._imaging_client:
                        await self._imaging_client.connect()

            self.state = ProfileState.CONNECTED
            return True

        except Exception as e:
            self.state = ProfileState.ERROR
            return False

    async def disconnect(self) -> None:
        """Disconnect all components."""
        try:
            if self._imaging_client:
                await self._imaging_client.disconnect()
            if self._client:
                await self._client.disconnect()
        finally:
            self._client = None
            self._imaging_client = None
            self.state = ProfileState.DISCONNECTED

    # ========== High-Level Operations ==========

    async def goto(
        self,
        target: Union[str, tuple[float, float]],
        target_name: Optional[str] = None,
    ) -> bool:
        """Slew to a target.

        Args:
            target: Either a target name or (ra, dec) tuple in degrees
            target_name: Optional display name for the target

        Returns:
            True if slew was successful
        """
        if isinstance(target, str):
            raise NotImplementedError("Target name resolution not yet implemented")
        else:
            ra, dec = target

        self.state = ProfileState.SLEWING

        if self._client:
            await self._client.goto(
                target_name=target_name or "Target",
                in_ra=ra,
                in_dec=dec,
            )
            self.state = ProfileState.CONNECTED
            return True

        return False

    async def start_imaging(
        self,
        target_name: Optional[str] = None,
    ) -> bool:
        """Start an imaging session.

        Args:
            target_name: Name for the imaging target

        Returns:
            True if imaging started successfully
        """
        self.state = ProfileState.IMAGING

        # Imaging is typically started after a goto
        # The Seestar handles this automatically
        return True

    async def stop_imaging(self) -> bool:
        """Stop the current imaging session."""
        if self._client:
            await self._client.stop_stack()

        self.state = ProfileState.CONNECTED
        return True

    async def get_status(self) -> dict[str, Any]:
        """Get status of all components."""
        status = {
            "profile_name": self.name,
            "profile_state": self.state.value,
            "integrated_device": None,
        }

        if self._client:
            status["integrated_device"] = {
                "connected": self._client.is_connected,
                "temperature": self._client.status.temp,
                "battery": self._client.status.battery_capacity,
                "ra": self._client.status.ra,
                "dec": self._client.status.dec,
                "stacked_frames": self._client.status.stacked_frame,
                "target_name": self._client.status.target_name,
            }

        return status

    # ========== Configuration Management ==========

    def save(self, path: Union[str, Path]) -> None:
        """Save profile to a file (JSON or YAML).

        Args:
            path: File path (extension determines format)
        """
        path = Path(path)

        # Serialize, excluding runtime fields
        data = self.model_dump(
            exclude={"state", "_client", "_imaging_client"},
            exclude_none=True,
            mode="json",
        )

        if path.suffix in (".yaml", ".yml"):
            if not HAS_YAML:
                raise ImportError("PyYAML required for YAML: pip install pyyaml")
            with open(path, "w") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        else:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: Union[str, Path]) -> "AstronomyProfile":
        """Load profile from a file (JSON or YAML).

        Args:
            path: File path

        Returns:
            AstronomyProfile instance
        """
        path = Path(path)

        if path.suffix in (".yaml", ".yml"):
            if not HAS_YAML:
                raise ImportError("PyYAML required for YAML: pip install pyyaml")
            with open(path, "r") as f:
                data = yaml.safe_load(f)
        else:
            with open(path, "r") as f:
                data = json.load(f)

        # Handle integrated device deserialization
        if "integrated_device" in data and data["integrated_device"]:
            device_data = data["integrated_device"]
            device_type = device_data.get("device_type", "integrated")

            if device_type == "seestar":
                data["integrated_device"] = SeestarDevice(**device_data)
            else:
                data["integrated_device"] = IntegratedDevice(**device_data)

        return cls(**data)

    # ========== Context Manager ==========

    async def __aenter__(self) -> "AstronomyProfile":
        """Async context manager entry - connects all components."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Async context manager exit - disconnects all components."""
        await self.disconnect()
        return False

    def __repr__(self) -> str:
        return f"AstronomyProfile(name={self.name!r}, state={self.state.value})"
