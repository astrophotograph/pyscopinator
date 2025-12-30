"""ASCOM Alpaca mount implementation.

Implements the V2 Mount interface using the Alpaca HTTP REST API
for telescope/mount control.

API Reference: https://ascom-standards.org/api/
"""

import asyncio
from typing import Callable, Optional

import aiohttp

from scopinator.v2.core.capabilities import MountCapabilities
from scopinator.v2.core.devices import Mount, MountStatus
from scopinator.v2.core.events import EventType, SlewEvent, UnifiedEventBus
from scopinator.v2.core.exceptions import CommandError, DeviceError, NotConnectedError
from scopinator.v2.core.types import (
    AltAzCoordinates,
    Coordinates,
    PierSide,
    SlewState,
    TrackingRate,
)


class AlpacaMount(Mount):
    """Mount implementation using ASCOM Alpaca REST API.

    All Alpaca telescope endpoints follow the pattern:
    GET/PUT /api/v1/telescope/{device_number}/{property}
    """

    # Map TrackingRate to Alpaca DriveRate enum
    TRACKING_RATE_MAP = {
        TrackingRate.SIDEREAL: 0,
        TrackingRate.LUNAR: 1,
        TrackingRate.SOLAR: 2,
        TrackingRate.KING: 3,
    }

    # Map Alpaca SideOfPier enum to PierSide
    PIER_SIDE_MAP = {
        0: PierSide.EAST,
        1: PierSide.WEST,
        -1: PierSide.UNKNOWN,
    }

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        device_number: int,
        client_id: int,
        get_transaction_id: Callable[[], int],
        event_bus: Optional[UnifiedEventBus] = None,
    ) -> None:
        """Initialize Alpaca mount.

        Args:
            session: aiohttp session for HTTP requests
            base_url: Base URL of Alpaca server
            device_number: Alpaca device number
            client_id: Alpaca client ID
            get_transaction_id: Function to get next transaction ID
            event_bus: Optional event bus for mount events
        """
        super().__init__(event_bus)
        self._session = session
        self._base_url = f"{base_url}/api/v1/telescope/{device_number}"
        self._client_id = client_id
        self._get_tid = get_transaction_id
        self._timeout = aiohttp.ClientTimeout(total=30)

    async def _get(self, endpoint: str) -> dict:
        """Make GET request to Alpaca endpoint."""
        params = {
            "ClientID": self._client_id,
            "ClientTransactionID": self._get_tid(),
        }
        async with self._session.get(
            f"{self._base_url}/{endpoint}",
            params=params,
            timeout=self._timeout,
        ) as resp:
            data = await resp.json()
            self._check_error(data)
            return data

    async def _put(self, endpoint: str, form_data: Optional[dict] = None) -> dict:
        """Make PUT request to Alpaca endpoint."""
        data = form_data or {}
        data["ClientID"] = self._client_id
        data["ClientTransactionID"] = self._get_tid()

        async with self._session.put(
            f"{self._base_url}/{endpoint}",
            data=data,
            timeout=self._timeout,
        ) as resp:
            result = await resp.json()
            self._check_error(result)
            return result

    def _check_error(self, data: dict) -> None:
        """Check Alpaca response for errors."""
        error_number = data.get("ErrorNumber", 0)
        if error_number != 0:
            error_message = data.get("ErrorMessage", "Unknown error")
            raise CommandError(error_message, code=error_number)

    async def connect(self) -> None:
        """Connect to the telescope."""
        await self._put("connected", {"Connected": "true"})
        self._connected = True

    async def disconnect(self) -> None:
        """Disconnect from the telescope."""
        try:
            await self._put("connected", {"Connected": "false"})
        finally:
            self._connected = False

    async def get_capabilities(self) -> MountCapabilities:
        """Query telescope capabilities."""
        # Query various capability properties in parallel
        results = await asyncio.gather(
            self._get("canslew"),
            self._get("canslewasync"),
            self._get("cansync"),
            self._get("canpark"),
            self._get("canunpark"),
            self._get("canfindhome"),
            self._get("canpulseguide"),
            self._get("cansettracking"),
            return_exceptions=True,
        )

        def get_value(result, default=False):
            if isinstance(result, Exception):
                return default
            return result.get("Value", default)

        return MountCapabilities(
            can_slew=get_value(results[0], True),
            can_slew_async=get_value(results[1], True),
            can_sync=get_value(results[2], True),
            can_park=get_value(results[3], True),
            can_unpark=get_value(results[4], False),
            can_find_home=get_value(results[5], False),
            can_pulse_guide=get_value(results[6], False),
            can_set_tracking=get_value(results[7], True),
            can_set_tracking_rate=True,
            has_pier_side=True,
            alignment_mode="unknown",
        )

    async def get_coordinates(self) -> Coordinates:
        """Get current RA/Dec coordinates."""
        ra_result, dec_result = await asyncio.gather(
            self._get("rightascension"),
            self._get("declination"),
        )

        # Alpaca returns RA in hours (0-24)
        ra_hours = ra_result["Value"]
        dec_deg = dec_result["Value"]

        return Coordinates(ra=ra_hours * 15.0, dec=dec_deg)

    async def get_altaz(self) -> Optional[AltAzCoordinates]:
        """Get current Alt/Az coordinates."""
        try:
            alt_result, az_result = await asyncio.gather(
                self._get("altitude"),
                self._get("azimuth"),
            )
            return AltAzCoordinates(
                altitude=alt_result["Value"],
                azimuth=az_result["Value"],
            )
        except Exception:
            return None

    async def slew_to_coordinates(
        self,
        coords: Coordinates,
        *,
        wait: bool = True,
    ) -> None:
        """Slew to coordinates asynchronously."""
        # Convert degrees to hours for RA
        ra_hours = coords.ra / 15.0

        # Emit start event
        event = SlewEvent(
            event_type=EventType.SLEW_STARTED,
            source_device="alpaca_mount",
            source_backend="alpaca",
            target_coordinates=coords,
            state=SlewState.SLEWING,
        )
        self._event_bus.emit_nowait(event)

        try:
            # Start async slew
            await self._put(
                "slewtocoordinatesasync",
                {
                    "RightAscension": str(ra_hours),
                    "Declination": str(coords.dec),
                },
            )

            if wait:
                # Poll until slewing is complete
                while True:
                    result = await self._get("slewing")
                    if not result["Value"]:
                        break
                    await asyncio.sleep(0.5)

                event = SlewEvent(
                    event_type=EventType.SLEW_COMPLETED,
                    source_device="alpaca_mount",
                    source_backend="alpaca",
                    target_coordinates=coords,
                    state=SlewState.TRACKING,
                )
                self._event_bus.emit_nowait(event)

        except Exception as e:
            event = SlewEvent(
                event_type=EventType.SLEW_ABORTED,
                source_device="alpaca_mount",
                source_backend="alpaca",
                target_coordinates=coords,
                state=SlewState.ERROR,
                data={"error": str(e)},
            )
            self._event_bus.emit_nowait(event)
            raise

    async def slew_to_altaz(
        self,
        coords: AltAzCoordinates,
        *,
        wait: bool = True,
    ) -> None:
        """Slew to Alt/Az coordinates."""
        await self._put(
            "slewtoaltazasync",
            {
                "Altitude": str(coords.altitude),
                "Azimuth": str(coords.azimuth),
            },
        )

        if wait:
            while True:
                result = await self._get("slewing")
                if not result["Value"]:
                    break
                await asyncio.sleep(0.5)

    async def abort_slew(self) -> None:
        """Abort slew."""
        await self._put("abortslew")

        event = SlewEvent(
            event_type=EventType.SLEW_ABORTED,
            source_device="alpaca_mount",
            source_backend="alpaca",
            state=SlewState.IDLE,
        )
        self._event_bus.emit_nowait(event)

    async def sync_to_coordinates(self, coords: Coordinates) -> None:
        """Sync to coordinates."""
        ra_hours = coords.ra / 15.0
        await self._put(
            "synctocoordinates",
            {
                "RightAscension": str(ra_hours),
                "Declination": str(coords.dec),
            },
        )

    async def park(self) -> None:
        """Park the telescope."""
        await self._put("park")

    async def unpark(self) -> None:
        """Unpark the telescope."""
        await self._put("unpark")

    async def set_tracking(self, enabled: bool) -> None:
        """Enable/disable tracking."""
        await self._put("tracking", {"Tracking": str(enabled).lower()})

    async def get_tracking(self) -> bool:
        """Get tracking state."""
        result = await self._get("tracking")
        return result["Value"]

    async def set_tracking_rate(self, rate: TrackingRate) -> None:
        """Set tracking rate."""
        if rate in (TrackingRate.CUSTOM, TrackingRate.OFF):
            raise ValueError(f"Tracking rate {rate} not supported via this method")

        alpaca_rate = self.TRACKING_RATE_MAP.get(rate)
        if alpaca_rate is None:
            raise ValueError(f"Unknown tracking rate: {rate}")

        await self._put("trackingrate", {"TrackingRate": str(alpaca_rate)})

    async def find_home(self) -> None:
        """Find home position."""
        await self._put("findhome")

    async def pulse_guide(self, direction: str, duration_ms: int) -> None:
        """Pulse guide in a direction."""
        # Map direction to Alpaca GuideDirection enum
        direction_map = {"north": 0, "south": 1, "east": 2, "west": 3}
        alpaca_dir = direction_map.get(direction.lower())
        if alpaca_dir is None:
            raise ValueError(f"Invalid direction: {direction}")

        await self._put(
            "pulseguide",
            {
                "Direction": str(alpaca_dir),
                "Duration": str(duration_ms),
            },
        )

    async def move_axis(self, axis: int, rate: float) -> None:
        """Move an axis at a specified rate.

        Args:
            axis: 0 for RA/primary axis, 1 for Dec/secondary axis
            rate: Rate in degrees per second. Positive values move in one
                  direction, negative in the opposite. 0 stops the axis.
        """
        await self._put(
            "moveaxis",
            {
                "Axis": str(axis),
                "Rate": str(rate),
            },
        )

    async def can_move_axis(self, axis: int) -> bool:
        """Check if the mount supports moving the specified axis.

        Args:
            axis: 0 for RA/primary axis, 1 for Dec/secondary axis

        Returns:
            True if the axis can be moved
        """
        try:
            result = await self._get(f"canmoveaxis?Axis={axis}")
            return result.get("Value", False)
        except Exception:
            return False

    async def is_slewing(self) -> bool:
        """Check if mount is slewing."""
        result = await self._get("slewing")
        return result["Value"]

    async def get_status(self) -> MountStatus:
        """Get comprehensive mount status."""
        # Fetch multiple properties in parallel
        results = await asyncio.gather(
            self.get_coordinates(),
            self.get_tracking(),
            self._get("slewing"),
            self._get("atpark"),
            self._get("athome"),
            self._get("sideofpier"),
            return_exceptions=True,
        )

        coords = results[0] if not isinstance(results[0], Exception) else None
        tracking = results[1] if not isinstance(results[1], Exception) else False
        slewing = (
            results[2]["Value"]
            if not isinstance(results[2], Exception)
            else False
        )
        at_park = (
            results[3]["Value"]
            if not isinstance(results[3], Exception)
            else False
        )
        at_home = (
            results[4]["Value"]
            if not isinstance(results[4], Exception)
            else False
        )
        pier_side_val = (
            results[5]["Value"]
            if not isinstance(results[5], Exception)
            else -1
        )

        # Determine state
        if slewing:
            state = SlewState.SLEWING
        elif at_park:
            state = SlewState.PARKED
        elif tracking:
            state = SlewState.TRACKING
        else:
            state = SlewState.IDLE

        return MountStatus(
            connected=self._connected,
            name="Alpaca Telescope",
            driver_info="ASCOM Alpaca",
            driver_version="1.0.0",
            coordinates=coords,
            state=state,
            tracking=tracking,
            at_park=at_park,
            at_home=at_home,
            slewing=slewing,
            pier_side=self.PIER_SIDE_MAP.get(pier_side_val, PierSide.UNKNOWN),
        )
