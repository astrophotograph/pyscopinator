"""INDI mount implementation.

Implements the V2 Mount interface using INDI properties and switches.
"""

import asyncio
from typing import TYPE_CHECKING, Optional

from scopinator.v2.core.capabilities import MountCapabilities
from scopinator.v2.core.devices import Mount, MountStatus
from scopinator.v2.core.events import EventType, SlewEvent, UnifiedEventBus
from scopinator.v2.core.exceptions import DeviceError, NotConnectedError
from scopinator.v2.core.types import Coordinates, PierSide, SlewState, TrackingRate

if TYPE_CHECKING:
    from scopinator.v2.backends.indi.backend import INDIClient

try:
    import PyIndi

    INDI_AVAILABLE = True
except ImportError:
    INDI_AVAILABLE = False
    PyIndi = None


class INDIMount(Mount):
    """Mount implementation using INDI protocol.

    INDI uses a property-based system where devices expose their state
    and controls via numbered/text/switch/light/blob properties.

    Key INDI properties for telescopes:
    - EQUATORIAL_EOD_COORD: Current RA/Dec (number)
    - ON_COORD_SET: What to do on coordinate set (switch: TRACK/SLEW/SYNC)
    - TELESCOPE_ABORT_MOTION: Abort (switch)
    - TELESCOPE_PARK: Park switch
    - TELESCOPE_TRACK_STATE: Tracking on/off
    """

    def __init__(
        self,
        client: "INDIClient",
        device_name: str,
        event_bus: Optional[UnifiedEventBus] = None,
    ) -> None:
        """Initialize INDI mount.

        Args:
            client: INDI client connection
            device_name: INDI device name
            event_bus: Optional event bus for mount events
        """
        super().__init__(event_bus)
        self._client = client
        self._device_name = device_name
        self._device: Optional["PyIndi.BaseDevice"] = None

    def _get_device(self) -> "PyIndi.BaseDevice":
        """Get the INDI device, connecting if needed."""
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

    async def _wait_for_property(
        self, property_name: str, timeout: float = 5.0
    ) -> bool:
        """Wait for a property to become available."""
        end_time = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end_time:
            device = self._get_device()
            if device.getNumber(property_name) or device.getSwitch(property_name):
                return True
            await asyncio.sleep(0.1)
        return False

    async def connect(self) -> None:
        """Connect to the mount (enable connection in INDI)."""
        device = self._get_device()

        # Get the CONNECTION switch
        connection = device.getSwitch("CONNECTION")
        if connection is None:
            await self._wait_for_property("CONNECTION")
            connection = device.getSwitch("CONNECTION")

        if connection:
            # Find CONNECT switch and turn it on
            for i in range(connection.nsp):
                if connection[i].name == "CONNECT":
                    connection[i].s = PyIndi.ISS_ON
                else:
                    connection[i].s = PyIndi.ISS_OFF
            self._client.sendNewSwitch(connection)

            # Wait for connection
            await asyncio.sleep(1.0)

        self._connected = True

    async def disconnect(self) -> None:
        """Disconnect from the mount."""
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

    async def get_capabilities(self) -> MountCapabilities:
        """Get mount capabilities by checking available properties."""
        device = self._get_device()

        return MountCapabilities(
            can_slew=device.getNumber("EQUATORIAL_EOD_COORD") is not None,
            can_slew_async=True,
            can_sync=device.getSwitch("ON_COORD_SET") is not None,
            can_park=device.getSwitch("TELESCOPE_PARK") is not None,
            can_unpark=device.getSwitch("TELESCOPE_PARK") is not None,
            can_find_home=False,  # Would need to check
            can_pulse_guide=device.getNumber("TELESCOPE_TIMED_GUIDE_NS") is not None,
            can_set_tracking=device.getSwitch("TELESCOPE_TRACK_STATE") is not None,
            can_set_tracking_rate=device.getSwitch("TELESCOPE_TRACK_RATE") is not None,
            has_pier_side=device.getSwitch("TELESCOPE_PIER_SIDE") is not None,
            alignment_mode="unknown",
        )

    async def get_coordinates(self) -> Coordinates:
        """Get current RA/Dec coordinates."""
        coords = self._get_number("EQUATORIAL_EOD_COORD")
        if coords is None:
            raise DeviceError("EQUATORIAL_EOD_COORD property not available")

        ra_hours = 0.0
        dec = 0.0
        for i in range(coords.nnp):
            if coords[i].name == "RA":
                ra_hours = coords[i].value
            elif coords[i].name == "DEC":
                dec = coords[i].value

        return Coordinates(ra=ra_hours * 15.0, dec=dec)

    async def slew_to_coordinates(
        self,
        coords: Coordinates,
        *,
        wait: bool = True,
    ) -> None:
        """Slew to coordinates."""
        # Set coord mode to SLEW or TRACK
        on_coord_set = self._get_switch("ON_COORD_SET")
        if on_coord_set:
            for i in range(on_coord_set.nsp):
                if on_coord_set[i].name in ("SLEW", "TRACK"):
                    on_coord_set[i].s = PyIndi.ISS_ON
                else:
                    on_coord_set[i].s = PyIndi.ISS_OFF
            self._client.sendNewSwitch(on_coord_set)

        # Emit slew started event
        event = SlewEvent(
            event_type=EventType.SLEW_STARTED,
            source_device=self._device_name,
            source_backend="indi",
            target_coordinates=coords,
            state=SlewState.SLEWING,
        )
        self._event_bus.emit_nowait(event)

        # Set target coordinates
        eq_coords = self._get_number("EQUATORIAL_EOD_COORD")
        if eq_coords is None:
            raise DeviceError("EQUATORIAL_EOD_COORD property not available")

        ra_hours = coords.ra / 15.0
        for i in range(eq_coords.nnp):
            if eq_coords[i].name == "RA":
                eq_coords[i].value = ra_hours
            elif eq_coords[i].name == "DEC":
                eq_coords[i].value = coords.dec

        self._client.sendNewNumber(eq_coords)

        if wait:
            # Wait for slew to complete by monitoring property state
            while True:
                eq_coords = self._get_number("EQUATORIAL_EOD_COORD")
                if eq_coords and eq_coords.s == PyIndi.IPS_OK:
                    break
                if eq_coords and eq_coords.s == PyIndi.IPS_ALERT:
                    raise DeviceError("Slew failed")
                await asyncio.sleep(0.5)

            event = SlewEvent(
                event_type=EventType.SLEW_COMPLETED,
                source_device=self._device_name,
                source_backend="indi",
                target_coordinates=coords,
                state=SlewState.TRACKING,
            )
            self._event_bus.emit_nowait(event)

    async def abort_slew(self) -> None:
        """Abort slew."""
        abort = self._get_switch("TELESCOPE_ABORT_MOTION")
        if abort:
            for i in range(abort.nsp):
                if abort[i].name == "ABORT":
                    abort[i].s = PyIndi.ISS_ON
            self._client.sendNewSwitch(abort)

        event = SlewEvent(
            event_type=EventType.SLEW_ABORTED,
            source_device=self._device_name,
            source_backend="indi",
            state=SlewState.IDLE,
        )
        self._event_bus.emit_nowait(event)

    async def sync_to_coordinates(self, coords: Coordinates) -> None:
        """Sync to coordinates."""
        # Set coord mode to SYNC
        on_coord_set = self._get_switch("ON_COORD_SET")
        if on_coord_set:
            for i in range(on_coord_set.nsp):
                if on_coord_set[i].name == "SYNC":
                    on_coord_set[i].s = PyIndi.ISS_ON
                else:
                    on_coord_set[i].s = PyIndi.ISS_OFF
            self._client.sendNewSwitch(on_coord_set)

        # Set coordinates
        eq_coords = self._get_number("EQUATORIAL_EOD_COORD")
        if eq_coords:
            ra_hours = coords.ra / 15.0
            for i in range(eq_coords.nnp):
                if eq_coords[i].name == "RA":
                    eq_coords[i].value = ra_hours
                elif eq_coords[i].name == "DEC":
                    eq_coords[i].value = coords.dec
            self._client.sendNewNumber(eq_coords)

    async def park(self) -> None:
        """Park the mount."""
        park = self._get_switch("TELESCOPE_PARK")
        if park:
            for i in range(park.nsp):
                if park[i].name == "PARK":
                    park[i].s = PyIndi.ISS_ON
                else:
                    park[i].s = PyIndi.ISS_OFF
            self._client.sendNewSwitch(park)

    async def unpark(self) -> None:
        """Unpark the mount."""
        park = self._get_switch("TELESCOPE_PARK")
        if park:
            for i in range(park.nsp):
                if park[i].name == "UNPARK":
                    park[i].s = PyIndi.ISS_ON
                else:
                    park[i].s = PyIndi.ISS_OFF
            self._client.sendNewSwitch(park)

    async def set_tracking(self, enabled: bool) -> None:
        """Enable/disable tracking."""
        track = self._get_switch("TELESCOPE_TRACK_STATE")
        if track:
            for i in range(track.nsp):
                if enabled and track[i].name == "TRACK_ON":
                    track[i].s = PyIndi.ISS_ON
                elif not enabled and track[i].name == "TRACK_OFF":
                    track[i].s = PyIndi.ISS_ON
                else:
                    track[i].s = PyIndi.ISS_OFF
            self._client.sendNewSwitch(track)

    async def get_tracking(self) -> bool:
        """Get tracking state."""
        track = self._get_switch("TELESCOPE_TRACK_STATE")
        if track:
            for i in range(track.nsp):
                if track[i].name == "TRACK_ON" and track[i].s == PyIndi.ISS_ON:
                    return True
        return False

    async def get_status(self) -> MountStatus:
        """Get mount status."""
        try:
            coords = await self.get_coordinates()
        except Exception:
            coords = None

        tracking = False
        try:
            tracking = await self.get_tracking()
        except Exception:
            pass

        # Check if slewing
        eq_coords = self._get_number("EQUATORIAL_EOD_COORD")
        slewing = eq_coords is not None and eq_coords.s == PyIndi.IPS_BUSY

        # Determine state
        if slewing:
            state = SlewState.SLEWING
        elif tracking:
            state = SlewState.TRACKING
        else:
            state = SlewState.IDLE

        return MountStatus(
            connected=self._connected,
            name=self._device_name,
            driver_info="INDI",
            driver_version="1.0.0",
            coordinates=coords,
            state=state,
            tracking=tracking,
            slewing=slewing,
            pier_side=PierSide.UNKNOWN,
        )
