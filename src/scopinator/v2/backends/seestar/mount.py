"""Seestar mount implementation.

Wraps the existing SeestarClient to provide the V2 Mount interface.
"""

from typing import TYPE_CHECKING, Optional

from scopinator.seestar.commands.simple import ScopeGetEquCoord, ScopePark, ScopeSync
from scopinator.v2.core.capabilities import MountCapabilities
from scopinator.v2.core.devices import Mount, MountStatus
from scopinator.v2.core.events import EventType, SlewEvent, UnifiedEventBus
from scopinator.v2.core.exceptions import DeviceError, NotConnectedError
from scopinator.v2.core.types import Coordinates, PierSide, SlewState, TrackingRate

if TYPE_CHECKING:
    from scopinator.seestar.client import SeestarClient


class SeestarMount(Mount):
    """Mount implementation for Seestar using existing client.

    This is an adapter that wraps the existing SeestarClient to provide
    the V2 Mount interface. It delegates all operations to the underlying
    client while translating data types and emitting unified events.
    """

    def __init__(
        self,
        client: "SeestarClient",
        event_bus: Optional[UnifiedEventBus] = None,
    ) -> None:
        """Initialize Seestar mount adapter.

        Args:
            client: Existing SeestarClient instance (should already be connected)
            event_bus: Optional event bus for emitting mount events
        """
        super().__init__(event_bus)
        self._client = client

    async def connect(self) -> None:
        """Mount connection is handled by backend/client."""
        self._connected = self._client.is_connected

    async def disconnect(self) -> None:
        """Mount disconnection is handled by backend/client."""
        pass

    async def get_capabilities(self) -> MountCapabilities:
        """Get Seestar mount capabilities."""
        return MountCapabilities(
            can_slew=True,
            can_slew_async=True,
            can_sync=True,
            can_park=True,
            can_unpark=False,  # Seestar doesn't support unpark
            can_find_home=False,
            can_pulse_guide=False,
            can_set_tracking=True,  # Implicitly via start/stop view
            can_set_tracking_rate=False,
            can_slew_altaz=False,
            has_pier_side=False,
            alignment_mode="altaz",
            max_slew_rate=4.0,  # Approximate
        )

    async def get_coordinates(self) -> Coordinates:
        """Get current coordinates from Seestar."""
        if not self._client.is_connected:
            raise NotConnectedError("Seestar is not connected")

        response = await self._client.send_and_recv(ScopeGetEquCoord())
        if response and response.result:
            # Seestar returns RA in hours (0-24), convert to degrees (0-360)
            ra_hours = response.result.get("ra", 0)
            dec = response.result.get("dec", 0)
            return Coordinates(ra=ra_hours * 15.0, dec=dec)

        # Fallback to status if command fails
        if self._client.status.ra is not None:
            return Coordinates(
                ra=self._client.status.ra * 15.0,
                dec=self._client.status.dec or 0.0,
            )

        raise DeviceError("Failed to get coordinates from Seestar")

    async def slew_to_coordinates(
        self,
        coords: Coordinates,
        *,
        wait: bool = True,
    ) -> None:
        """Slew to coordinates.

        Args:
            coords: Target coordinates (RA in degrees)
            wait: If True, wait for slew to complete
        """
        if not self._client.is_connected:
            raise NotConnectedError("Seestar is not connected")

        # Emit slew started event
        event = SlewEvent(
            event_type=EventType.SLEW_STARTED,
            source_device="seestar_mount",
            source_backend="seestar",
            target_coordinates=coords,
            state=SlewState.SLEWING,
        )
        self._event_bus.emit_nowait(event)

        # Use existing goto method - it expects RA in degrees
        # but the internal method handles conversion
        await self._client.goto(
            target_name="V2 Target",
            in_ra=coords.ra,  # Degrees
            in_dec=coords.dec,
            mode="star",
        )

        if wait:
            # Wait for AutoGoto event to complete
            success, error = await self._client.wait_for_event_completion(
                "AutoGoto", timeout=120.0
            )

            if success:
                event = SlewEvent(
                    event_type=EventType.SLEW_COMPLETED,
                    source_device="seestar_mount",
                    source_backend="seestar",
                    target_coordinates=coords,
                    state=SlewState.TRACKING,
                )
            else:
                event = SlewEvent(
                    event_type=EventType.SLEW_ABORTED,
                    source_device="seestar_mount",
                    source_backend="seestar",
                    target_coordinates=coords,
                    state=SlewState.ERROR,
                    data={"error": error},
                )

            self._event_bus.emit_nowait(event)

            if not success:
                raise DeviceError(f"Slew failed: {error}")

    async def abort_slew(self) -> None:
        """Abort current slew."""
        if not self._client.is_connected:
            raise NotConnectedError("Seestar is not connected")

        await self._client.stop_goto()

        event = SlewEvent(
            event_type=EventType.SLEW_ABORTED,
            source_device="seestar_mount",
            source_backend="seestar",
            state=SlewState.IDLE,
        )
        self._event_bus.emit_nowait(event)

    async def sync_to_coordinates(self, coords: Coordinates) -> None:
        """Sync mount to coordinates."""
        if not self._client.is_connected:
            raise NotConnectedError("Seestar is not connected")

        # Convert from degrees to hours for Seestar
        # ScopeSync expects params as (ra_hours, dec_degrees) tuple
        ra_hours = coords.ra / 15.0
        await self._client.send_and_recv(
            ScopeSync(params=(ra_hours, coords.dec))
        )

    async def park(self) -> None:
        """Park the Seestar."""
        if not self._client.is_connected:
            raise NotConnectedError("Seestar is not connected")

        await self._client.send_and_recv(ScopePark())

    async def set_tracking(self, enabled: bool) -> None:
        """Enable/disable tracking.

        Seestar manages tracking automatically - it tracks when observing
        and stops when idle. This method is a no-op.
        """
        # Seestar handles tracking implicitly
        pass

    async def get_tracking(self) -> bool:
        """Get current tracking state."""
        # Seestar tracks when in observation mode
        return self._client.client_mode in ("Stack", "ContinuousExposure", "AutoGoto")

    async def get_status(self) -> MountStatus:
        """Get comprehensive mount status."""
        try:
            coords = await self.get_coordinates()
        except Exception:
            coords = None

        tracking = await self.get_tracking()

        # Map client mode to slew state
        client_mode = self._client.client_mode
        if client_mode == "AutoGoto":
            state = SlewState.SLEWING
        elif client_mode in ("Stack", "ContinuousExposure"):
            state = SlewState.TRACKING
        elif client_mode == "Idle":
            state = SlewState.IDLE
        else:
            state = SlewState.IDLE

        return MountStatus(
            connected=self._client.is_connected,
            name="Seestar Mount",
            driver_info="Seestar V2 Adapter",
            driver_version="1.0.0",
            coordinates=coords,
            state=state,
            tracking=tracking,
            tracking_rate=TrackingRate.SIDEREAL,
            pier_side=PierSide.UNKNOWN,
            at_park=False,
            at_home=False,
            slewing=client_mode == "AutoGoto",
            target_coordinates=None,  # Could be extracted from status
        )
