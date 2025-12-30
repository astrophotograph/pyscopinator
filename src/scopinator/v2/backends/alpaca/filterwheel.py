"""ASCOM Alpaca filter wheel implementation.

Implements the V2 FilterWheel interface using the Alpaca HTTP REST API
for filter wheel control.

API Reference: https://ascom-standards.org/api/
"""

import asyncio
from typing import Callable, Optional

import aiohttp

from scopinator.v2.core.capabilities import FilterWheelCapabilities
from scopinator.v2.core.devices import FilterWheel, FilterWheelStatus
from scopinator.v2.core.events import EventType, UnifiedEvent, UnifiedEventBus
from scopinator.v2.core.exceptions import CommandError
from scopinator.v2.core.types import FilterPosition


class AlpacaFilterWheel(FilterWheel):
    """Filter wheel implementation using ASCOM Alpaca REST API.

    All Alpaca filter wheel endpoints follow the pattern:
    GET/PUT /api/v1/filterwheel/{device_number}/{property}
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        device_number: int,
        client_id: int,
        get_transaction_id: Callable[[], int],
        event_bus: Optional[UnifiedEventBus] = None,
    ) -> None:
        """Initialize Alpaca filter wheel.

        Args:
            session: aiohttp session for HTTP requests
            base_url: Base URL of Alpaca server
            device_number: Alpaca device number
            client_id: Alpaca client ID
            get_transaction_id: Function to get next transaction ID
            event_bus: Optional event bus for filter wheel events
        """
        super().__init__(event_bus)
        self._session = session
        self._base_url = f"{base_url}/api/v1/filterwheel/{device_number}"
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
        """Connect to the filter wheel."""
        await self._put("connected", {"Connected": "true"})
        self._connected = True

    async def disconnect(self) -> None:
        """Disconnect from the filter wheel."""
        try:
            await self._put("connected", {"Connected": "false"})
        finally:
            self._connected = False

    async def get_capabilities(self) -> FilterWheelCapabilities:
        """Query filter wheel capabilities."""
        results = await asyncio.gather(
            self._get("names"),
            self._get("focusoffsets"),
            return_exceptions=True,
        )

        def get_value(result, default):
            if isinstance(result, Exception):
                return default
            return result.get("Value", default)

        names = get_value(results[0], [])
        focus_offsets = get_value(results[1], [])

        return FilterWheelCapabilities(
            num_positions=len(names),
            filter_names=names,
            has_focus_offsets=len(focus_offsets) > 0,
            focus_offsets=focus_offsets,
        )

    async def get_position(self) -> FilterPosition:
        """Get current filter position."""
        results = await asyncio.gather(
            self._get("position"),
            self._get("names"),
            return_exceptions=True,
        )

        def get_value(result, default):
            if isinstance(result, Exception):
                return default
            return result.get("Value", default)

        position = get_value(results[0], -1)
        names = get_value(results[1], [])

        # Position -1 means filter wheel is moving
        is_moving = position == -1
        filter_name = None
        if not is_moving and 0 <= position < len(names):
            filter_name = names[position]

        return FilterPosition(
            position=max(0, position),  # Return 0 if moving
            name=filter_name,
        )

    async def set_position(self, position: int, *, wait: bool = True) -> None:
        """Move to filter position.

        Args:
            position: Target position (0-indexed)
            wait: If True, wait for move to complete
        """
        # Validate position
        names_result = await self._get("names")
        names = names_result.get("Value", [])
        if position < 0 or position >= len(names):
            raise ValueError(f"Position {position} out of range (0-{len(names) - 1})")

        await self._put("position", {"Position": str(position)})

        if wait:
            # Poll until movement is complete (position != -1)
            while True:
                result = await self._get("position")
                current_pos = result["Value"]
                if current_pos != -1:
                    break
                await asyncio.sleep(0.2)

            # Emit event
            filter_name = names[position] if position < len(names) else None
            event = UnifiedEvent(
                event_type=EventType.STATUS_UPDATE,
                source_device="alpaca_filterwheel",
                source_backend="alpaca",
                data={
                    "position": position,
                    "filter_name": filter_name,
                    "action": "filter_changed",
                },
            )
            self._event_bus.emit_nowait(event)

    async def get_filter_names(self) -> list[str]:
        """Get list of filter names."""
        result = await self._get("names")
        return result.get("Value", [])

    async def get_status(self) -> FilterWheelStatus:
        """Get current filter wheel status."""
        results = await asyncio.gather(
            self._get("position"),
            self._get("names"),
            return_exceptions=True,
        )

        def get_value(result, default):
            if isinstance(result, Exception):
                return default
            return result.get("Value", default)

        position = get_value(results[0], -1)
        names = get_value(results[1], [])

        # Position -1 means filter wheel is moving
        is_moving = position == -1
        filter_name = None
        if not is_moving and 0 <= position < len(names):
            filter_name = names[position]

        return FilterWheelStatus(
            connected=self._connected,
            name="Alpaca Filter Wheel",
            driver_info="ASCOM Alpaca",
            driver_version="1.0.0",
            position=max(0, position),
            filter_name=filter_name,
            is_moving=is_moving,
            num_positions=len(names),
        )
