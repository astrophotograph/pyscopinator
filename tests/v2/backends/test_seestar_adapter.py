"""Tests for Seestar backend adapter."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from scopinator.v2.core.types import Coordinates, SlewState, TrackingRate, AltAzCoordinates
from scopinator.v2.core.events import UnifiedEventBus, EventType


class MockResponse:
    """Mock response from send_and_recv."""
    def __init__(self, result=None):
        self.result = result or {}


class TestSeestarMount:
    """Tests for SeestarMount adapter."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock SeestarClient."""
        client = MagicMock()
        client.is_connected = True
        client.client_mode = "Idle"
        client.status = MagicMock()
        client.status.ra = 5.575  # hours
        client.status.dec = 22.01
        client.status.alt = 45.0
        client.status.az = 180.0
        client.status.tracking_state = "tracking"

        # Make async methods return coroutines
        async def mock_send_and_recv(cmd):
            return MockResponse(result={"ra": 5.575, "dec": 22.01})

        client.send_and_recv = AsyncMock(side_effect=mock_send_and_recv)
        client.goto = AsyncMock()
        client.stop_goto = AsyncMock()
        client.wait_for_event_completion = AsyncMock(return_value=(True, None))

        return client

    @pytest.fixture
    def event_bus(self):
        """Create an event bus."""
        return UnifiedEventBus()

    @pytest.fixture
    def mount(self, mock_client, event_bus):
        """Create a SeestarMount with mocked client."""
        from scopinator.v2.backends.seestar.mount import SeestarMount
        return SeestarMount(client=mock_client, event_bus=event_bus)

    def test_mount_initialization(self, mount):
        """Test mount initialization."""
        assert mount is not None
        assert mount._client is not None

    @pytest.mark.asyncio
    async def test_get_coordinates(self, mount, mock_client):
        """Test getting current coordinates."""
        coords = await mount.get_coordinates()
        # RA is returned in hours and converted to degrees (5.575 * 15 = 83.625)
        assert abs(coords.ra - 83.625) < 0.01
        assert coords.dec == 22.01

    @pytest.mark.asyncio
    async def test_get_altaz(self, mount, mock_client):
        """Test getting alt/az coordinates."""
        # Base class get_altaz returns None if not overridden
        coords = await mount.get_altaz()
        # SeestarMount doesn't override get_altaz, so it returns None
        assert coords is None

    @pytest.mark.asyncio
    async def test_slew_to_coordinates(self, mount, mock_client, event_bus):
        """Test slewing to coordinates."""
        received_events = []

        async def capture_events(event):
            received_events.append(event)

        event_bus.subscribe(EventType.SLEW_STARTED, capture_events)
        event_bus.subscribe(EventType.SLEW_COMPLETED, capture_events)

        target = Coordinates(ra=100.0, dec=30.0)
        await mount.slew_to_coordinates(target, wait=False)

        # Client's goto should have been called
        mock_client.goto.assert_called_once()
        call_kwargs = mock_client.goto.call_args.kwargs

        # Verify coordinates were passed
        assert call_kwargs.get('in_ra') == 100.0
        assert call_kwargs.get('in_dec') == 30.0

    @pytest.mark.asyncio
    async def test_sync_to_coordinates(self, mount, mock_client):
        """Test syncing to coordinates."""
        coords = Coordinates(ra=83.63, dec=22.01)
        await mount.sync_to_coordinates(coords)

        # send_and_recv should have been called with ScopeSync
        mock_client.send_and_recv.assert_called()

    @pytest.mark.asyncio
    async def test_park(self, mount, mock_client):
        """Test parking the mount."""
        await mount.park()
        # send_and_recv should have been called with ScopePark
        mock_client.send_and_recv.assert_called()

    @pytest.mark.asyncio
    async def test_set_tracking(self, mount, mock_client):
        """Test setting tracking rate (no-op for Seestar)."""
        # Seestar handles tracking implicitly, so this is a no-op
        await mount.set_tracking(True)
        # Nothing specific to assert - just verify it doesn't fail

    @pytest.mark.asyncio
    async def test_abort_slew(self, mount, mock_client):
        """Test aborting slew."""
        await mount.abort_slew()
        mock_client.stop_goto.assert_called_once()


class TestSeestarCamera:
    """Tests for SeestarCamera adapter."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock SeestarClient."""
        client = MagicMock()
        client.is_connected = True
        client.client_mode = "Idle"
        client.stop_stack = AsyncMock()
        return client

    @pytest.fixture
    def mock_imaging_client(self):
        """Create a mock SeestarImagingClient."""
        client = MagicMock()
        client.is_connected = True
        return client

    @pytest.fixture
    def event_bus(self):
        """Create an event bus."""
        return UnifiedEventBus()

    @pytest.fixture
    def camera(self, mock_client, mock_imaging_client, event_bus):
        """Create a SeestarCamera with mocked clients."""
        from scopinator.v2.backends.seestar.camera import SeestarCamera
        return SeestarCamera(
            client=mock_client,
            imaging_client=mock_imaging_client,
            event_bus=event_bus,
        )

    def test_camera_initialization(self, camera):
        """Test camera initialization."""
        assert camera is not None

    @pytest.mark.asyncio
    async def test_start_exposure(self, camera, mock_client, event_bus):
        """Test starting an exposure."""
        from scopinator.v2.core.types import ExposureSettings

        received_events = []

        async def capture_events(event):
            received_events.append(event)

        event_bus.subscribe(EventType.EXPOSURE_STARTED, capture_events)

        settings = ExposureSettings(duration_seconds=10.0, gain=100)
        await camera.start_exposure(settings)

        # Should have started exposure - give async ops time to complete
        await asyncio.sleep(0.01)

    @pytest.mark.asyncio
    async def test_abort_exposure(self, camera, mock_client):
        """Test aborting exposure."""
        await camera.abort_exposure()
        mock_client.stop_stack.assert_called()

    @pytest.mark.asyncio
    async def test_is_exposing(self, camera):
        """Test checking if camera is exposing."""
        result = await camera.is_exposing()
        assert isinstance(result, bool)


class TestSeestarBackend:
    """Tests for SeestarBackend."""

    @pytest.fixture
    def mock_seestar_client_class(self):
        """Mock the SeestarClient class."""
        with patch('scopinator.v2.backends.seestar.backend.SeestarClient') as mock:
            instance = MagicMock()
            instance.is_connected = True
            instance.connect = AsyncMock()
            instance.disconnect = AsyncMock()
            mock.return_value = instance
            yield mock, instance

    @pytest.fixture
    def mock_imaging_client_class(self):
        """Mock the SeestarImagingClient class."""
        with patch('scopinator.v2.backends.seestar.backend.SeestarImagingClient') as mock:
            instance = MagicMock()
            instance.is_connected = True
            instance.connect = AsyncMock()
            instance.disconnect = AsyncMock()
            mock.return_value = instance
            yield mock, instance

    @pytest.fixture
    def event_bus(self):
        """Create an event bus."""
        return UnifiedEventBus()

    def test_backend_initialization(self):
        """Test backend initialization."""
        from scopinator.v2.backends.seestar import SeestarBackend
        backend = SeestarBackend(host="192.168.1.100")
        assert backend.host == "192.168.1.100"
        assert backend.port == 4700

    @pytest.mark.asyncio
    async def test_backend_connect(self, mock_seestar_client_class, mock_imaging_client_class):
        """Test backend connection."""
        from scopinator.v2.backends.seestar import SeestarBackend

        backend = SeestarBackend(host="192.168.1.100")
        await backend.connect()

        # Client should have been created and connected
        mock_class, mock_instance = mock_seestar_client_class
        mock_class.assert_called()
        mock_instance.connect.assert_called()

    @pytest.mark.asyncio
    async def test_backend_disconnect(self, mock_seestar_client_class, mock_imaging_client_class):
        """Test backend disconnection."""
        from scopinator.v2.backends.seestar import SeestarBackend

        backend = SeestarBackend(host="192.168.1.100")
        await backend.connect()
        await backend.disconnect()

        mock_class, mock_instance = mock_seestar_client_class
        mock_instance.disconnect.assert_called()

    @pytest.mark.asyncio
    async def test_discover_devices(self, mock_seestar_client_class, mock_imaging_client_class):
        """Test device discovery returns single device."""
        from scopinator.v2.backends.seestar import SeestarBackend

        backend = SeestarBackend(host="192.168.1.100")
        await backend.connect()

        devices = await backend.discover_devices()
        assert "mount" in devices
        assert "camera" in devices

    @pytest.mark.asyncio
    async def test_get_mount(self, mock_seestar_client_class, mock_imaging_client_class):
        """Test getting mount device."""
        from scopinator.v2.backends.seestar import SeestarBackend
        from scopinator.v2.backends.seestar.mount import SeestarMount

        backend = SeestarBackend(host="192.168.1.100")
        await backend.connect()

        mount = await backend.get_mount("seestar_mount")
        assert isinstance(mount, SeestarMount)

    @pytest.mark.asyncio
    async def test_get_camera(self, mock_seestar_client_class, mock_imaging_client_class):
        """Test getting camera device."""
        from scopinator.v2.backends.seestar import SeestarBackend
        from scopinator.v2.backends.seestar.camera import SeestarCamera

        backend = SeestarBackend(host="192.168.1.100")
        await backend.connect()

        camera = await backend.get_camera("seestar_camera")
        assert isinstance(camera, SeestarCamera)
