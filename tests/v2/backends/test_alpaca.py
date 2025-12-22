"""Tests for ASCOM Alpaca backend."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
from contextlib import asynccontextmanager

from scopinator.v2.core.types import Coordinates, SlewState, TrackingRate, ExposureSettings
from scopinator.v2.core.events import UnifiedEventBus


# Helper for generating transaction IDs in tests
def make_transaction_id_generator():
    """Create a transaction ID generator for tests."""
    counter = [0]
    def get_id():
        counter[0] += 1
        return counter[0]
    return get_id


def create_mock_response(json_data):
    """Create a mock response that works as an async context manager."""
    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value=json_data)
    return mock_resp


def create_mock_session():
    """Create a mock aiohttp session with proper async context manager support."""
    session = MagicMock()

    def make_context_manager(response):
        @asynccontextmanager
        async def cm(*args, **kwargs):
            yield response
        return cm

    return session, make_context_manager


class TestAlpacaMount:
    """Tests for AlpacaMount."""

    @pytest.fixture
    def event_bus(self):
        """Create an event bus."""
        return UnifiedEventBus()

    @pytest.fixture
    def mock_session_and_helper(self):
        """Create mock session and helper function."""
        return create_mock_session()

    @pytest.fixture
    def mount(self, mock_session_and_helper, event_bus):
        """Create an AlpacaMount with mocked session."""
        from scopinator.v2.backends.alpaca.mount import AlpacaMount
        session, _ = mock_session_and_helper
        return AlpacaMount(
            session=session,
            base_url="http://localhost:11111",
            device_number=0,
            client_id=1,
            get_transaction_id=make_transaction_id_generator(),
            event_bus=event_bus,
        )

    def test_mount_initialization(self, mount):
        """Test mount initialization."""
        assert mount is not None
        # Check that base URL was constructed correctly
        assert "telescope/0" in mount._base_url

    @pytest.mark.asyncio
    async def test_get_coordinates(self, mock_session_and_helper, event_bus):
        """Test getting current coordinates."""
        from scopinator.v2.backends.alpaca.mount import AlpacaMount

        session, make_cm = mock_session_and_helper

        # Create responses for RA and Dec
        ra_response = create_mock_response({"Value": 5.575, "ErrorNumber": 0})
        dec_response = create_mock_response({"Value": 22.01, "ErrorNumber": 0})

        call_count = [0]

        @asynccontextmanager
        async def mock_get(url, **kwargs):
            call_count[0] += 1
            if "rightascension" in url:
                yield ra_response
            else:
                yield dec_response

        session.get = mock_get

        mount = AlpacaMount(
            session=session,
            base_url="http://localhost:11111",
            device_number=0,
            client_id=1,
            get_transaction_id=make_transaction_id_generator(),
            event_bus=event_bus,
        )

        coords = await mount.get_coordinates()
        assert coords is not None
        assert isinstance(coords, Coordinates)
        # RA should be converted from hours to degrees
        assert abs(coords.ra - 5.575 * 15) < 0.01

    @pytest.mark.asyncio
    async def test_slew_to_coordinates(self, mock_session_and_helper, event_bus):
        """Test slewing to coordinates."""
        from scopinator.v2.backends.alpaca.mount import AlpacaMount

        session, make_cm = mock_session_and_helper

        put_response = create_mock_response({"ErrorNumber": 0})

        @asynccontextmanager
        async def mock_put(url, **kwargs):
            yield put_response

        session.put = mock_put

        mount = AlpacaMount(
            session=session,
            base_url="http://localhost:11111",
            device_number=0,
            client_id=1,
            get_transaction_id=make_transaction_id_generator(),
            event_bus=event_bus,
        )

        target = Coordinates(ra=100.0, dec=30.0)
        await mount.slew_to_coordinates(target, wait=False)
        # If we got here without exception, the test passes

    @pytest.mark.asyncio
    async def test_sync_to_coordinates(self, mock_session_and_helper, event_bus):
        """Test syncing to coordinates."""
        from scopinator.v2.backends.alpaca.mount import AlpacaMount

        session, make_cm = mock_session_and_helper

        put_response = create_mock_response({"ErrorNumber": 0})

        @asynccontextmanager
        async def mock_put(url, **kwargs):
            yield put_response

        session.put = mock_put

        mount = AlpacaMount(
            session=session,
            base_url="http://localhost:11111",
            device_number=0,
            client_id=1,
            get_transaction_id=make_transaction_id_generator(),
            event_bus=event_bus,
        )

        coords = Coordinates(ra=83.63, dec=22.01)
        await mount.sync_to_coordinates(coords)
        # If we got here without exception, the test passes

    @pytest.mark.asyncio
    async def test_park(self, mock_session_and_helper, event_bus):
        """Test parking the mount."""
        from scopinator.v2.backends.alpaca.mount import AlpacaMount

        session, make_cm = mock_session_and_helper

        put_calls = []
        put_response = create_mock_response({"ErrorNumber": 0})

        @asynccontextmanager
        async def mock_put(url, **kwargs):
            put_calls.append(url)
            yield put_response

        session.put = mock_put

        mount = AlpacaMount(
            session=session,
            base_url="http://localhost:11111",
            device_number=0,
            client_id=1,
            get_transaction_id=make_transaction_id_generator(),
            event_bus=event_bus,
        )

        await mount.park()

        # Check that park endpoint was called
        assert any("park" in url.lower() for url in put_calls)


class TestAlpacaCamera:
    """Tests for AlpacaCamera."""

    @pytest.fixture
    def event_bus(self):
        """Create an event bus."""
        return UnifiedEventBus()

    @pytest.fixture
    def mock_session_and_helper(self):
        """Create mock session and helper function."""
        return create_mock_session()

    @pytest.fixture
    def camera(self, mock_session_and_helper, event_bus):
        """Create an AlpacaCamera with mocked session."""
        from scopinator.v2.backends.alpaca.camera import AlpacaCamera
        session, _ = mock_session_and_helper
        return AlpacaCamera(
            session=session,
            base_url="http://localhost:11111",
            device_number=0,
            client_id=1,
            get_transaction_id=make_transaction_id_generator(),
            event_bus=event_bus,
        )

    def test_camera_initialization(self, camera):
        """Test camera initialization."""
        assert camera is not None
        assert "camera/0" in camera._base_url

    @pytest.mark.asyncio
    async def test_start_exposure(self, mock_session_and_helper, event_bus):
        """Test starting an exposure."""
        from scopinator.v2.backends.alpaca.camera import AlpacaCamera

        session, make_cm = mock_session_and_helper

        put_response = create_mock_response({"ErrorNumber": 0})

        @asynccontextmanager
        async def mock_put(url, **kwargs):
            yield put_response

        session.put = mock_put

        camera = AlpacaCamera(
            session=session,
            base_url="http://localhost:11111",
            device_number=0,
            client_id=1,
            get_transaction_id=make_transaction_id_generator(),
            event_bus=event_bus,
        )

        settings = ExposureSettings(duration_seconds=30.0)
        await camera.start_exposure(settings)

    @pytest.mark.asyncio
    async def test_abort_exposure(self, mock_session_and_helper, event_bus):
        """Test aborting exposure."""
        from scopinator.v2.backends.alpaca.camera import AlpacaCamera

        session, make_cm = mock_session_and_helper

        put_response = create_mock_response({"ErrorNumber": 0})

        @asynccontextmanager
        async def mock_put(url, **kwargs):
            yield put_response

        session.put = mock_put

        camera = AlpacaCamera(
            session=session,
            base_url="http://localhost:11111",
            device_number=0,
            client_id=1,
            get_transaction_id=make_transaction_id_generator(),
            event_bus=event_bus,
        )

        await camera.abort_exposure()

    @pytest.mark.asyncio
    async def test_is_exposing(self, mock_session_and_helper, event_bus):
        """Test checking if camera is exposing."""
        from scopinator.v2.backends.alpaca.camera import AlpacaCamera

        session, make_cm = mock_session_and_helper

        # CameraState enum: 0=Idle, 2=Exposing
        get_response = create_mock_response({"Value": 0, "ErrorNumber": 0})

        @asynccontextmanager
        async def mock_get(url, **kwargs):
            yield get_response

        session.get = mock_get

        camera = AlpacaCamera(
            session=session,
            base_url="http://localhost:11111",
            device_number=0,
            client_id=1,
            get_transaction_id=make_transaction_id_generator(),
            event_bus=event_bus,
        )

        result = await camera.is_exposing()
        assert isinstance(result, bool)
        assert result is False


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
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            backend = AlpacaBackend(host="localhost", port=11111)
            await backend.connect()

            assert backend._session is not None

    @pytest.mark.asyncio
    async def test_backend_disconnect(self):
        """Test backend disconnection closes session."""
        from scopinator.v2.backends.alpaca import AlpacaBackend

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = MagicMock()
            mock_session.close = AsyncMock()
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
        from scopinator.v2.backends.alpaca.discovery import AlpacaDiscovery

        mock_response = create_mock_response({
            "Value": [
                {"DeviceType": "Telescope", "DeviceNumber": 0, "DeviceName": "Simulator"},
                {"DeviceType": "Camera", "DeviceNumber": 0, "DeviceName": "Camera Sim"},
            ],
        })

        session = MagicMock()

        @asynccontextmanager
        async def mock_get(url, **kwargs):
            yield mock_response

        session.get = mock_get

        discovery = AlpacaDiscovery(session, "http://localhost:11111", timeout=5.0)
        devices = await discovery.get_configured_devices()

        assert "mount" in devices  # Telescope gets normalized to mount
        assert "camera" in devices
        assert len(devices["mount"]) == 1
        assert len(devices["camera"]) == 1

    @pytest.mark.asyncio
    async def test_discover_devices_error(self):
        """Test discovery handles errors gracefully."""
        from scopinator.v2.backends.alpaca.discovery import discover_alpaca_devices

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = MagicMock()

            @asynccontextmanager
            async def mock_get(url, **kwargs):
                raise Exception("Connection failed")
                yield  # Never reached, but needed for generator

            mock_session.get = mock_get
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            devices = await discover_alpaca_devices("localhost", 11111)
            assert devices == []
