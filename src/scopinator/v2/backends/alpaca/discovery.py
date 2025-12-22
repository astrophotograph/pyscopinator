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


async def discover_alpaca_servers(
    timeout: float = 5.0,
    num_queries: int = 2,
) -> list[dict[str, Any]]:
    """Discover Alpaca servers on the local network via UDP broadcast.

    Sends the "alpacadiscovery1" message to UDP port 32227 and collects
    responses containing {"AlpacaPort": <port>}.

    See: https://ascom-standards.org/AlpacaDeveloper/ASCOMAlpacaAPIReference.html

    Args:
        timeout: Discovery timeout in seconds
        num_queries: Number of discovery broadcasts to send

    Returns:
        List of discovered server info dicts with 'host' and 'AlpacaPort'
    """
    import json

    discovered: dict[str, dict[str, Any]] = {}  # keyed by host to dedupe

    # Create UDP socket for sending broadcasts
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Enable port reuse on non-Windows
    if hasattr(socket, "SO_REUSEPORT"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

    sock.setblocking(False)

    # Bind to any available port to receive responses
    sock.bind(("", 0))

    loop = asyncio.get_event_loop()

    try:
        # Send discovery broadcasts
        message = b"alpacadiscovery1"
        broadcast_addr = ("<broadcast>", AlpacaDiscovery.ALPACA_DISCOVERY_PORT)

        for _ in range(num_queries):
            sock.sendto(message, broadcast_addr)
            await asyncio.sleep(0.1)  # Small delay between queries

        # Collect responses until timeout
        end_time = loop.time() + timeout

        while loop.time() < end_time:
            remaining = end_time - loop.time()
            if remaining <= 0:
                break

            try:
                # Use asyncio to wait for data with timeout
                data, addr = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: sock.recvfrom(1024)),
                    timeout=min(remaining, 0.5),
                )
                response = data.decode("utf-8")

                try:
                    info = json.loads(response)
                    host = addr[0]
                    # Standard response format: {"AlpacaPort": <port>}
                    if "AlpacaPort" in info:
                        info["host"] = host
                        discovered[host] = info
                except json.JSONDecodeError:
                    # Non-JSON response, store raw
                    discovered[addr[0]] = {"host": addr[0], "raw": response}

            except asyncio.TimeoutError:
                continue
            except BlockingIOError:
                await asyncio.sleep(0.1)
                continue
            except OSError:
                break

    finally:
        sock.close()

    return list(discovered.values())


async def discover_alpaca_devices(
    host: str,
    port: int = 11111,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Discover devices on a specific Alpaca server.

    Queries the management API to get configured devices.

    Args:
        host: Alpaca server hostname or IP
        port: Alpaca server port
        timeout: Request timeout in seconds

    Returns:
        List of device info dicts with device_type, device_name, device_number
    """
    try:
        async with aiohttp.ClientSession() as session:
            discovery = AlpacaDiscovery(session, f"http://{host}:{port}", timeout=timeout)
            devices = await discovery.get_configured_devices()

            result = []
            for device_type, device_list in devices.items():
                for d in device_list:
                    result.append({
                        "device_type": device_type,
                        "device_name": d.get("DeviceName", ""),
                        "device_number": d.get("DeviceNumber", 0),
                    })
            return result
    except Exception:
        return []
