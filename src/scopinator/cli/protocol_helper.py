"""Protocol helper for CLI commands.

Provides unified access to different telescope protocols (Seestar, Alpaca, INDI)
based on CLI options and profiles.
"""

import asyncio
from typing import Any, Optional, Union

import click

from scopinator.util.logging_config import get_logger

logger = get_logger(__name__)

# Default ports for each protocol
DEFAULT_PORTS = {
    "seestar": 4700,
    "alpaca": 11111,
    "indi": 7624,
}


class ProtocolClient:
    """Unified client wrapper for different protocols.

    This provides a common interface for CLI commands regardless of
    the underlying protocol.
    """

    def __init__(
        self,
        protocol: str,
        host: str,
        port: int,
        backend: Any = None,
        mount: Any = None,
        camera: Any = None,
    ):
        self.protocol = protocol
        self.host = host
        self.port = port
        self._backend = backend
        self._mount = mount
        self._camera = camera
        self._connected = False

        # For Seestar, we also keep a reference to the raw client
        self._seestar_client = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        """Connect to the device."""
        try:
            if self.protocol == "seestar":
                from scopinator.seestar.client import SeestarClient
                from scopinator.util.eventbus import EventBus

                event_bus = EventBus()
                self._seestar_client = SeestarClient(
                    host=self.host,
                    port=self.port,
                    event_bus=event_bus,
                )
                await self._seestar_client.connect()
                self._connected = True

            elif self.protocol == "alpaca":
                from scopinator.v2.backends.alpaca import AlpacaBackend

                self._backend = AlpacaBackend(host=self.host, port=self.port)
                await self._backend.connect()
                self._connected = True

            elif self.protocol == "indi":
                from scopinator.v2.backends.indi import INDIBackend

                self._backend = INDIBackend(host=self.host, port=self.port)
                await self._backend.connect()
                self._connected = True

            return True

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._connected = False
            raise

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        try:
            if self._seestar_client:
                await self._seestar_client.disconnect()
            if self._backend:
                await self._backend.disconnect()
        finally:
            self._connected = False

    async def get_mount(self) -> Any:
        """Get the mount device."""
        if self._mount:
            return self._mount

        if self.protocol == "seestar":
            if self._backend:
                self._mount = await self._backend.get_mount("seestar_mount")
            # For direct Seestar client, return it as the "mount"
            return self._seestar_client

        elif self.protocol == "alpaca":
            # Discover and get first telescope
            devices = await self._backend.discover_devices()
            if "mount" in devices and devices["mount"]:
                self._mount = await self._backend.get_mount(devices["mount"][0])
            return self._mount

        elif self.protocol == "indi":
            devices = await self._backend.discover_devices()
            if "mount" in devices and devices["mount"]:
                self._mount = await self._backend.get_mount(devices["mount"][0])
            return self._mount

        return None

    async def get_camera(self) -> Any:
        """Get the camera device."""
        if self._camera:
            return self._camera

        if self.protocol == "seestar":
            # Seestar camera is integrated
            return self._seestar_client

        elif self.protocol in ("alpaca", "indi"):
            devices = await self._backend.discover_devices()
            if "camera" in devices and devices["camera"]:
                self._camera = await self._backend.get_camera(devices["camera"][0])
            return self._camera

        return None

    async def get_status(self) -> dict[str, Any]:
        """Get device status."""
        status = {
            "protocol": self.protocol,
            "host": self.host,
            "port": self.port,
            "connected": self._connected,
        }

        if self.protocol == "seestar" and self._seestar_client:
            client = self._seestar_client
            if client.status:
                status.update({
                    "battery": client.status.battery_capacity,
                    "temperature": client.status.temp,
                    "ra": client.status.ra,
                    "dec": client.status.dec,
                    "alt": client.status.alt,
                    "az": client.status.az,
                    "tracking": client.status.tracking_state,
                    "target_name": client.status.target_name,
                    "stacked_frames": client.status.stacked_frame,
                })

        elif self.protocol in ("alpaca", "indi"):
            mount = await self.get_mount()
            if mount:
                try:
                    coords = await mount.get_coordinates()
                    status["ra"] = coords.ra
                    status["dec"] = coords.dec
                except Exception:
                    pass

                try:
                    state = await mount.get_slew_state()
                    status["slew_state"] = state.value if hasattr(state, 'value') else str(state)
                except Exception:
                    pass

        return status

    async def goto(self, ra: float, dec: float, name: Optional[str] = None) -> bool:
        """Slew to coordinates."""
        if self.protocol == "seestar" and self._seestar_client:
            await self._seestar_client.goto(
                target_name=name or "Target",
                in_ra=ra,
                in_dec=dec,
            )
            return True

        elif self.protocol in ("alpaca", "indi"):
            from scopinator.v2.core.types import Coordinates
            mount = await self.get_mount()
            if mount:
                target = Coordinates(ra=ra, dec=dec)
                await mount.slew_to_coordinates(target, wait=False)
                return True

        return False

    async def park(self) -> bool:
        """Park the mount."""
        if self.protocol == "seestar" and self._seestar_client:
            await self._seestar_client.goto_home()
            return True

        elif self.protocol in ("alpaca", "indi"):
            mount = await self.get_mount()
            if mount:
                await mount.park()
                return True

        return False

    # Seestar-specific methods (for backwards compatibility)

    @property
    def status(self) -> Any:
        """Get Seestar client status (for backwards compatibility)."""
        if self._seestar_client:
            return self._seestar_client.status
        return None

    async def send_and_recv(self, command: Any) -> Any:
        """Send command to Seestar (for backwards compatibility)."""
        if self._seestar_client:
            return await self._seestar_client.send_and_recv(command)
        raise NotImplementedError(f"send_and_recv not supported for {self.protocol}")


def get_protocol_and_connection(ctx: click.Context, host: Optional[str], port: Optional[int]) -> tuple[str, str, int]:
    """Get protocol, host, and port from context and options.

    Priority:
    1. Explicit --host/--port options
    2. Profile settings
    3. Saved connection state
    4. Context defaults

    Args:
        ctx: Click context
        host: Host from command option
        port: Port from command option

    Returns:
        Tuple of (protocol, host, port)
    """
    from scopinator.cli.connection_state import load_connection_state

    ctx_obj = ctx.obj or {}

    # Get protocol from CLI option
    protocol = ctx_obj.get("protocol", "auto")

    # Check if we have a loaded profile
    profile = ctx_obj.get("profile")
    if profile and profile.integrated_device:
        device = profile.integrated_device
        profile_protocol = device.device_type
        profile_host = device.host
        profile_port = device.port
    else:
        profile_protocol = None
        profile_host = None
        profile_port = None

    # Load saved connection state
    saved_state = load_connection_state()
    saved_host = saved_state.get("host") if saved_state else None
    saved_port = saved_state.get("port") if saved_state else None
    saved_protocol = saved_state.get("protocol") if saved_state else None

    # Determine final values
    # Host: command option > profile > saved state > context
    final_host = host or profile_host or saved_host or ctx_obj.get("host")

    # Protocol: explicit option > profile > saved state > auto-detect
    if protocol == "auto":
        if profile_protocol:
            final_protocol = profile_protocol
        elif saved_protocol:
            final_protocol = saved_protocol
        else:
            # Default to seestar for backwards compatibility
            final_protocol = "seestar"
    else:
        final_protocol = protocol

    # Port: command option > profile > saved state > protocol default
    if port:
        final_port = port
    elif profile_port:
        final_port = profile_port
    elif saved_port:
        final_port = saved_port
    else:
        final_port = DEFAULT_PORTS.get(final_protocol, 4700)

    return final_protocol, final_host, final_port


async def create_client(
    protocol: str,
    host: str,
    port: int,
) -> ProtocolClient:
    """Create and connect a protocol client.

    Args:
        protocol: Protocol name (seestar, alpaca, indi)
        host: Device host
        port: Device port

    Returns:
        Connected ProtocolClient
    """
    client = ProtocolClient(protocol=protocol, host=host, port=port)
    await client.connect()
    return client


def require_host(host: Optional[str], ctx: click.Context) -> None:
    """Check that host is provided, show error if not."""
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first, provide --host, or use --profile")
        ctx.exit(1)
