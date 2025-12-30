"""ASCOM Alpaca focuser implementation.

Implements the V2 Focuser interface using the Alpaca HTTP REST API
for focuser control.

API Reference: https://ascom-standards.org/api/
"""

import asyncio
from typing import Callable, Optional

import aiohttp

from scopinator.v2.core.capabilities import FocuserCapabilities
from scopinator.v2.core.devices import Focuser, FocuserStatus
from scopinator.v2.core.events import EventType, UnifiedEvent, UnifiedEventBus
from scopinator.v2.core.exceptions import CommandError
from scopinator.v2.core.types import FocuserPosition


class AlpacaFocuser(Focuser):
    """Focuser implementation using ASCOM Alpaca REST API.

    All Alpaca focuser endpoints follow the pattern:
    GET/PUT /api/v1/focuser/{device_number}/{property}
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
        """Initialize Alpaca focuser.

        Args:
            session: aiohttp session for HTTP requests
            base_url: Base URL of Alpaca server
            device_number: Alpaca device number
            client_id: Alpaca client ID
            get_transaction_id: Function to get next transaction ID
            event_bus: Optional event bus for focuser events
        """
        super().__init__(event_bus)
        self._session = session
        self._base_url = f"{base_url}/api/v1/focuser/{device_number}"
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
        """Connect to the focuser."""
        await self._put("connected", {"Connected": "true"})
        self._connected = True

    async def disconnect(self) -> None:
        """Disconnect from the focuser."""
        try:
            await self._put("connected", {"Connected": "false"})
        finally:
            self._connected = False

    async def get_capabilities(self) -> FocuserCapabilities:
        """Query focuser capabilities."""
        results = await asyncio.gather(
            self._get("maxstep"),
            self._get("stepsize"),
            self._get("tempcompavailable"),
            self._get("tempcomp"),
            return_exceptions=True,
        )

        def get_value(result, default):
            if isinstance(result, Exception):
                return default
            return result.get("Value", default)

        max_step = get_value(results[0], 0)
        step_size = get_value(results[1], 0.0)
        temp_comp_available = get_value(results[2], False)

        # Check if temperature is available by trying to read it
        has_temperature = False
        try:
            temp_result = await self._get("temperature")
            if temp_result.get("Value") is not None:
                has_temperature = True
        except Exception:
            pass

        return FocuserCapabilities(
            can_absolute=True,
            can_relative=True,
            can_halt=True,
            has_temperature=has_temperature,
            has_temp_compensation=temp_comp_available,
            max_step=max_step,
            step_size=float(step_size),
        )

    async def get_position(self) -> FocuserPosition:
        """Get current focuser position."""
        results = await asyncio.gather(
            self._get("position"),
            self._get("maxstep"),
            self._get("ismoving"),
            return_exceptions=True,
        )

        def get_value(result, default):
            if isinstance(result, Exception):
                return default
            return result.get("Value", default)

        position = get_value(results[0], 0)
        max_position = get_value(results[1], 1)
        is_moving = get_value(results[2], False)

        # Try to get temperature
        temperature = None
        try:
            temp_result = await self._get("temperature")
            temperature = temp_result.get("Value")
        except Exception:
            pass

        return FocuserPosition(
            position=position,
            max_position=max_position,
            temperature=temperature,
            is_moving=is_moving,
        )

    async def move_to(self, position: int, *, wait: bool = True) -> None:
        """Move to absolute position.

        Args:
            position: Target position in steps
            wait: If True, wait for move to complete
        """
        # Validate position
        max_step = (await self._get("maxstep"))["Value"]
        if position < 0 or position > max_step:
            raise ValueError(f"Position {position} out of range (0-{max_step})")

        await self._put("move", {"Position": str(position)})

        if wait:
            # Poll until movement is complete
            while True:
                result = await self._get("ismoving")
                if not result["Value"]:
                    break
                await asyncio.sleep(0.2)

            # Emit event
            event = UnifiedEvent(
                event_type=EventType.STATUS_UPDATE,
                source_device="alpaca_focuser",
                source_backend="alpaca",
                data={"position": position, "action": "move_complete"},
            )
            self._event_bus.emit_nowait(event)

    async def move_relative(self, steps: int, *, wait: bool = True) -> None:
        """Move relative to current position.

        Args:
            steps: Number of steps (positive = out, negative = in)
            wait: If True, wait for move to complete
        """
        current_pos = (await self._get("position"))["Value"]
        new_pos = current_pos + steps
        await self.move_to(new_pos, wait=wait)

    async def halt(self) -> None:
        """Halt any movement."""
        await self._put("halt")

    async def get_status(self) -> FocuserStatus:
        """Get current focuser status."""
        results = await asyncio.gather(
            self._get("position"),
            self._get("maxstep"),
            self._get("ismoving"),
            return_exceptions=True,
        )

        def get_value(result, default):
            if isinstance(result, Exception):
                return default
            return result.get("Value", default)

        position = get_value(results[0], 0)
        max_position = get_value(results[1], 0)
        is_moving = get_value(results[2], False)

        # Try to get temperature and temp comp status
        temperature = None
        temp_comp_enabled = False
        try:
            temp_result = await self._get("temperature")
            temperature = temp_result.get("Value")
        except Exception:
            pass
        try:
            temp_comp_result = await self._get("tempcomp")
            temp_comp_enabled = temp_comp_result.get("Value", False)
        except Exception:
            pass

        return FocuserStatus(
            connected=self._connected,
            name="Alpaca Focuser",
            driver_info="ASCOM Alpaca",
            driver_version="1.0.0",
            position=position,
            max_position=max_position,
            is_moving=is_moving,
            temperature=temperature,
            temp_comp_enabled=temp_comp_enabled,
        )
