"""ASCOM Alpaca device discovery.

Alpaca servers expose a management API for discovering configured devices.
This module handles querying that API to find available devices.
"""

import asyncio
import socket
from typing import Any, Optional

import aiohttp

from scopinator.v2.core.exceptions import ConnectionError


class AlpacaDiscovery:
    """Discover Alpaca devices via management API and UDP broadcast."""

    ALPACA_DISCOVERY_PORT = 32227

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        timeout: float = 5.0,
    ) -> None:
        """Initialize discovery.

        Args:
            session: aiohttp session for HTTP requests
            base_url: Base URL of Alpaca server (e.g., http://localhost:11111)
            timeout: Request timeout in seconds
        """
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def get_api_versions(self) -> list[int]:
        """Get supported API versions from server.

        Returns:
            List of supported API version numbers
        """
        try:
            async with self._session.get(
                f"{self._base_url}/management/apiversions",
                timeout=self._timeout,
            ) as resp:
                data = await resp.json()
                return data.get("Value", [1])
        except Exception:
            return [1]

    async def get_configured_devices(self) -> dict[str, list[dict[str, Any]]]:
        """Get all configured devices from the Alpaca server.

        Returns:
            Dict mapping device type to list of device info dicts.
            Each device info contains: DeviceName, DeviceType, DeviceNumber

        Example return:
            {
                "telescope": [
                    {"DeviceName": "Simulator", "DeviceType": "Telescope", "DeviceNumber": 0}
                ],
                "camera": [
                    {"DeviceName": "CCD Simulator", "DeviceType": "Camera", "DeviceNumber": 0}
                ]
            }
        """
        try:
            async with self._session.get(
                f"{self._base_url}/management/v1/configureddevices",
                timeout=self._timeout,
            ) as resp:
                data = await resp.json()
                devices = data.get("Value", [])

                # Organize by device type
                result: dict[str, list[dict[str, Any]]] = {}
                for device in devices:
                    device_type = device.get("DeviceType", "").lower()
                    # Normalize type names
                    if device_type == "telescope":
                        device_type = "mount"
                    if device_type not in result:
                        result[device_type] = []
                    result[device_type].append(device)

                return result
        except Exception as e:
            raise ConnectionError(f"Failed to get configured devices: {e}")

    async def get_server_description(self) -> dict[str, Any]:
        """Get server description.

        Returns:
            Dict with ServerName, Manufacturer, ManufacturerVersion, Location
        """
        try:
            async with self._session.get(
                f"{self._base_url}/management/v1/description",
                timeout=self._timeout,
            ) as resp:
                data = await resp.json()
                return data.get("Value", {})
        except Exception:
            return {}


async def discover_alpaca_servers(timeout: float = 5.0) -> list[dict[str, Any]]:
    """Discover Alpaca servers on the local network via UDP broadcast.

    Alpaca servers respond to UDP broadcasts on port 32227 with their
    location information.

    Args:
        timeout: Discovery timeout in seconds

    Returns:
        List of discovered server info dicts with 'host' and 'port'
    """
    discovered: list[dict[str, Any]] = []

    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)

    try:
        # Send discovery broadcast
        # Alpaca discovery uses "alpacadiscovery1" as the message
        message = b"alpacadiscovery1"
        sock.sendto(message, ("<broadcast>", AlpacaDiscovery.ALPACA_DISCOVERY_PORT))

        # Collect responses
        end_time = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end_time:
            try:
                data, addr = sock.recvfrom(1024)
                response = data.decode("utf-8")

                # Parse response - format is typically JSON
                import json

                try:
                    info = json.loads(response)
                    info["host"] = addr[0]
                    discovered.append(info)
                except json.JSONDecodeError:
                    # Response might be plain text with port
                    discovered.append({"host": addr[0], "raw": response})
            except socket.timeout:
                break
    finally:
        sock.close()

    return discovered
