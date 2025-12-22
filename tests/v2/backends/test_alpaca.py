"""Tests for ASCOM Alpaca backend."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from scopinator.v2.core.types import Coordinates, SlewState, TrackingRate, ExposureSettings
from scopinator.v2.core.events import UnifiedEventBus


class TestAlpacaMount:
    """Tests for AlpacaMount."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock aiohttp session."""
        session = AsyncMock()
        return session

    @pytest.fixture
    def event_bus(self):
        """Create an event bus."""
        return UnifiedEventBus()

    @pytest.fixture
    def mount(self, mock_session, event_bus):
        """Create an AlpacaMount with mocked session."""
        from scopinator.v2.backends.alpaca.mount import AlpacaMount
        return AlpacaMount(
            session=mock_session,
            base_url="http://localhost:11111/api/v1",
            device_number=0,
            event_bus=event_bus,
        )

    def test_mount_initialization(self, mount):
        """Test mount initialization."""
        assert mount is not None
        assert mount.device_number == 0

    @pytest.mark.asyncio
    async def test_get_coordinates(self, mount, mock_session):
        """Test getting current coordinates."""
        # Mock the response
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={
            "Value": 5.575,  # RA in hours
            "ErrorNumber": 0,
        })
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_dec_response = AsyncMock()
        mock_dec_response.json = AsyncMock(return_value={
            "Value": 22.01,  # Dec in degrees
            "ErrorNumber": 0,
        })
        mock_dec_response.__aenter__ = AsyncMock(return_value=mock_dec_response)
        mock_dec_response.__aexit__ = AsyncMock(return_value=None)

        # Configure session to return different responses for RA and Dec
        call_count = [0]

        async def mock_get(url, **kwargs):
            call_count[0] += 1
            if "rightascension" in url:
                return mock_response
            elif "declination" in url:
                return mock_dec_response
            return mock_response

        mock_session.get = mock_get

        coords = await mount.get_coordinates()
        assert coords is not None
        assert isinstance(coords, Coordinates)

    @pytest.mark.asyncio
    async def test_slew_to_coordinates(self, mount, mock_session):
        """Test slewing to coordinates."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={"ErrorNumber": 0})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.put = AsyncMock(return_value=mock_response)

        target = Coordinates(ra=100.0, dec=30.0)
        await mount.slew_to_coordinates(target, wait=False)

        mock_session.put.assert_called()

    @pytest.mark.asyncio
    async def test_sync_to_coordinates(self, mount, mock_session):
        """Test syncing to coordinates."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={"ErrorNumber": 0})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.put = AsyncMock(return_value=mock_response)

        coords = Coordinates(ra=83.63, dec=22.01)
        await mount.sync_to_coordinates(coords)

        mock_session.put.assert_called()

    @pytest.mark.asyncio
    async def test_park(self, mount, mock_session):
        """Test parking the mount."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={"ErrorNumber": 0})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.put = AsyncMock(return_value=mock_response)

        await mount.park()

        # Should have called park endpoint
        call_args = mock_session.put.call_args
        assert "park" in str(call_args).lower()


class TestAlpacaCamera:
    """Tests for AlpacaCamera."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock aiohttp session."""
        return AsyncMock()

    @pytest.fixture
    def event_bus(self):
        """Create an event bus."""
        return UnifiedEventBus()

    @pytest.fixture
    def camera(self, mock_session, event_bus):
        """Create an AlpacaCamera with mocked session."""
        from scopinator.v2.backends.alpaca.camera import AlpacaCamera
        return AlpacaCamera(
            session=mock_session,
            base_url="http://localhost:11111/api/v1",
            device_number=0,
            event_bus=event_bus,
        )

    def test_camera_initialization(self, camera):
        """Test camera initialization."""
        assert camera is not None
        assert camera.device_number == 0

    @pytest.mark.asyncio
    async def test_start_exposure(self, camera, mock_session):
        """Test starting an exposure."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={"ErrorNumber": 0})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.put = AsyncMock(return_value=mock_response)

        settings = ExposureSettings(duration=30.0)
        await camera.start_exposure(settings)

        mock_session.put.assert_called()

    @pytest.mark.asyncio
    async def test_abort_exposure(self, camera, mock_session):
        """Test aborting exposure."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={"ErrorNumber": 0})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.put = AsyncMock(return_value=mock_response)

        await camera.abort_exposure()

        mock_session.put.assert_called()

    @pytest.mark.asyncio
    async def test_is_exposing(self, camera, mock_session):
        """Test checking if camera is exposing."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={
            "Value": "Idle",
            "ErrorNumber": 0,
        })
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.get = AsyncMock(return_value=mock_response)

        result = await camera.is_exposing()
        assert isinstance(result, bool)


class TestAlpacaBackend:
    """Tests for AlpacaBackend."""

    @pytest.fixture
    def event_bus(self):
        """Create an event bus."""
        return UnifiedEventBus()

    def test_backend_initialization(self):
        """Test backend initialization."""
        from scopinator.v2.backends.alpaca import AlpacaBackend
        backend = AlpacaBackend(host="localhost", port=11111)
        assert backend.host == "localhost"
        assert backend.port == 11111

    @pytest.mark.asyncio
    async def test_backend_connect(self):
        """Test backend connection creates session."""
        from scopinator.v2.backends.alpaca import AlpacaBackend

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value = mock_session

            backend = AlpacaBackend(host="localhost", port=11111)
            await backend.connect()

            assert backend._session is not None

    @pytest.mark.asyncio
    async def test_backend_disconnect(self):
        """Test backend disconnection closes session."""
        from scopinator.v2.backends.alpaca import AlpacaBackend

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value = mock_session

            backend = AlpacaBackend(host="localhost", port=11111)
            await backend.connect()
            await backend.disconnect()

            mock_session.close.assert_called()


class TestAlpacaDiscovery:
    """Tests for Alpaca device discovery."""

    @pytest.mark.asyncio
    async def test_discover_devices(self):
        """Test discovering Alpaca devices."""
        from scopinator.v2.backends.alpaca.discovery import discover_alpaca_devices

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()

            # Mock response for configureddevices
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value={
                "Value": [
                    {"DeviceType": "Telescope", "DeviceNumber": 0, "DeviceName": "Simulator"},
                    {"DeviceType": "Camera", "DeviceNumber": 0, "DeviceName": "Camera Sim"},
                ],
            })
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = AsyncMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            devices = await discover_alpaca_devices("localhost", 11111)
            assert len(devices) == 2
            assert any(d["device_type"] == "telescope" for d in devices)
            assert any(d["device_type"] == "camera" for d in devices)

    @pytest.mark.asyncio
    async def test_discover_devices_error(self):
        """Test discovery handles errors gracefully."""
        from scopinator.v2.backends.alpaca.discovery import discover_alpaca_devices

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.get = AsyncMock(side_effect=Exception("Connection failed"))
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            devices = await discover_alpaca_devices("localhost", 11111)
            assert devices == []
