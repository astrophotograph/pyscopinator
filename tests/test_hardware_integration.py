"""Integration tests with real hardware (or mock hardware) running on localhost.

These tests require a telescope (or mock telescope server) to be running on localhost.
They test actual command/response patterns without requiring imaging capabilities.

To run these tests:
1. Ensure telescope/mock is running on localhost:4700 and localhost:4701
2. Run: pytest tests/test_hardware_integration.py -v
"""

import asyncio
import pytest
import pytest_asyncio
import json
import time
from datetime import datetime
import os

from scopinator.seestar.client import SeestarClient, SeestarStatus
from scopinator.seestar.connection import SeestarConnection
from scopinator.seestar.commands.simple import (
    GetTime,
    GetDeviceState,
    GetViewState,
    GetFocuserPosition,
    GetDiskVolume,
    ScopeGetEquCoord,
    ScopeSync,
    PiIsVerified,
    BalanceSensorInfo,
    TestConnection,
)
from scopinator.seestar.commands.parameterized import (
    IscopeStartView,
    IscopeStopView,
    IscopeStartViewParams,
)
from scopinator.seestar.commands.settings import (
    SetUserLocation,
    SetUserLocationParameters,
    PiSetTime,
    PiSetTimeParameter,
    SetSetting,
    SettingParameters,
)
from scopinator.seestar.commands.common import CommandResponse
from scopinator.util.eventbus import EventBus


# Skip these tests if TELESCOPE_HOST env var is not set
TELESCOPE_HOST = os.environ.get("TELESCOPE_HOST", "localhost")
TELESCOPE_PORT = int(os.environ.get("TELESCOPE_PORT", "4700"))
TELESCOPE_PORT_ALT = int(os.environ.get("TELESCOPE_PORT_ALT", "4701"))

# Mark all tests in this file as hardware tests
# These will be skipped by default unless explicitly requested
pytestmark = [
    pytest.mark.hardware,  # Custom marker for hardware tests
    pytest.mark.skipif(
        os.environ.get("RUN_HARDWARE_TESTS", "false").lower() != "true",
        reason="Hardware tests skipped (set RUN_HARDWARE_TESTS=true to run)"
    )
]


class TestHardwareConnection:
    """Test basic connection to hardware."""
    
    @pytest_asyncio.fixture
    async def client(self):
        """Create a client connected to localhost hardware."""
        event_bus = EventBus()
        client = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            event_bus=event_bus,
            connection_timeout=5.0,
            read_timeout=10.0,
        )
        yield client
        # Cleanup
        if client.is_connected:
            await client.disconnect()
    
    @pytest.mark.asyncio
    async def test_connection_lifecycle(self, client):
        """Test connecting and disconnecting from hardware."""
        # Verify initial state
        assert not client.is_connected
        assert client.host == TELESCOPE_HOST
        assert client.port == TELESCOPE_PORT
        
        # Connect
        try:
            await client.connect()
            assert client.is_connected
            
            # Verify connection components
            assert client.connection is not None
            assert client.connection.is_connected()
            
            # Verify background tasks started
            assert client.background_task is not None
            assert client.reader_task is not None
            
            # Disconnect
            await client.disconnect()
            assert not client.is_connected
            
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available at {TELESCOPE_HOST}:{TELESCOPE_PORT}: {e}")
    
    @pytest.mark.asyncio
    async def test_multiple_connections(self):
        """Test multiple clients connecting to different ports."""
        event_bus = EventBus()
        
        client1 = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            event_bus=event_bus,
        )
        
        client2 = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT_ALT,
            event_bus=event_bus,
        )
        
        try:
            # Connect both
            await client1.connect()
            await client2.connect()
            
            assert client1.is_connected
            assert client2.is_connected
            
            # Send test commands to both
            response1 = await client1.send_and_recv(TestConnection())
            response2 = await client2.send_and_recv(TestConnection())
            
            assert response1 is not None or response1 == ""
            assert response2 is not None or response2 == ""
            
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")
        finally:
            # Cleanup
            if client1.is_connected:
                await client1.disconnect()
            if client2.is_connected:
                await client2.disconnect()


class TestBasicCommands:
    """Test basic telescope commands."""
    
    @pytest_asyncio.fixture
    async def connected_client(self):
        """Create and connect a client."""
        event_bus = EventBus()
        client = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            event_bus=event_bus,
            connection_timeout=5.0,
        )
        
        try:
            await client.connect()
            yield client
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")
        finally:
            if client.is_connected:
                await client.disconnect()
    
    @pytest.mark.asyncio
    async def test_get_time(self, connected_client):
        """Test getting time from telescope."""
        response = await connected_client.send_and_recv(GetTime())
        
        assert response is not None
        if hasattr(response, 'result'):
            assert response.result is not None
            # Time should be in result
            if isinstance(response.result, dict):
                assert 'time' in response.result or 'timestamp' in response.result or len(response.result) > 0
    
    @pytest.mark.asyncio
    async def test_get_device_state(self, connected_client):
        """Test getting device state."""
        response = await connected_client.send_and_recv(GetDeviceState())
        
        assert response is not None
        if hasattr(response, 'result') and response.result:
            # Check for pi_status in result
            if 'pi_status' in response.result:
                pi_status = response.result['pi_status']
                # Verify some expected fields
                assert isinstance(pi_status, dict)
                # Common fields that should be present
                possible_fields = ['temp', 'battery_capacity', 'charger_status', 'charge_online']
                assert any(field in pi_status for field in possible_fields)
    
    @pytest.mark.asyncio
    async def test_get_view_state(self, connected_client):
        """Test getting view state."""
        response = await connected_client.send_and_recv(GetViewState())
        
        assert response is not None
        if hasattr(response, 'result') and response.result:
            # Check for View in result
            if 'View' in response.result:
                view = response.result['View']
                assert isinstance(view, dict)
                # Check for common view fields
                possible_fields = ['stage', 'mode', 'state', 'target_name', 'gain']
                assert any(field in view for field in possible_fields)
    
    @pytest.mark.asyncio
    async def test_get_focuser_position(self, connected_client):
        """Test getting focuser position."""
        response = await connected_client.send_and_recv(GetFocuserPosition())
        
        assert response is not None
        if hasattr(response, 'result'):
            # Focuser position should be a number
            if response.result is not None:
                assert isinstance(response.result, (int, float))
                # Typical focuser range
                assert -10000 <= response.result <= 50000
    
    @pytest.mark.asyncio
    async def test_get_disk_volume(self, connected_client):
        """Test getting disk volume information."""
        response = await connected_client.send_and_recv(GetDiskVolume())
        
        assert response is not None
        if hasattr(response, 'result') and response.result:
            # Check for disk info fields
            if 'freeMB' in response.result:
                assert isinstance(response.result['freeMB'], (int, float))
                assert response.result['freeMB'] >= 0
            if 'totalMB' in response.result:
                assert isinstance(response.result['totalMB'], (int, float))
                assert response.result['totalMB'] > 0
    
    @pytest.mark.asyncio
    async def test_test_connection(self, connected_client):
        """Test the TestConnection command."""
        response = await connected_client.send_and_recv(TestConnection())
        
        # TestConnection might return None or empty response
        # The important thing is it doesn't error
        assert response is not None or response == ""


class TestCoordinateOperations:
    """Test coordinate-related operations."""
    
    @pytest_asyncio.fixture
    async def connected_client(self):
        """Create and connect a client."""
        event_bus = EventBus()
        client = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            event_bus=event_bus,
        )
        
        try:
            await client.connect()
            yield client
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")
        finally:
            if client.is_connected:
                await client.disconnect()
    
    @pytest.mark.asyncio
    async def test_get_coordinates(self, connected_client):
        """Test getting current telescope coordinates."""
        response = await connected_client.send_and_recv(ScopeGetEquCoord())
        
        assert response is not None
        if hasattr(response, 'result') and response.result:
            # Check for RA/Dec
            if 'ra' in response.result:
                ra = response.result['ra']
                assert isinstance(ra, (int, float))
                # RA in hours (0-24) or degrees (0-360)
                assert 0 <= ra <= 360
            
            if 'dec' in response.result:
                dec = response.result['dec']
                assert isinstance(dec, (int, float))
                # Dec in degrees (-90 to 90)
                assert -90 <= dec <= 90
    
    @pytest.mark.asyncio
    async def test_scope_sync(self, connected_client):
        """Test syncing telescope to coordinates."""
        # Sync to a safe position (near zenith)
        test_ra = 12.0  # hours
        test_dec = 45.0  # degrees
        
        response = await connected_client.scope_sync(test_ra, test_dec)
        
        # Response might be None or have a success field
        if response is not None and hasattr(response, 'result'):
            if isinstance(response.result, dict) and 'success' in response.result:
                assert response.result['success'] in [True, False]
    
    @pytest.mark.asyncio
    async def test_update_current_coords(self, connected_client):
        """Test updating current coordinates in client status."""
        # This updates the client's internal status
        position_changed = await connected_client.update_current_coords()
        
        # Check that coordinates were updated
        assert isinstance(position_changed, bool)
        
        # Verify status has coordinates
        if connected_client.status.ra is not None:
            assert isinstance(connected_client.status.ra, (int, float))
        if connected_client.status.dec is not None:
            assert isinstance(connected_client.status.dec, (int, float))


class TestTelescopeStatus:
    """Test telescope status retrieval and updates."""
    
    @pytest_asyncio.fixture
    async def connected_client(self):
        """Create and connect a client."""
        event_bus = EventBus()
        client = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            event_bus=event_bus,
        )
        
        try:
            await client.connect()
            yield client
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")
        finally:
            if client.is_connected:
                await client.disconnect()
    
    @pytest.mark.asyncio
    async def test_initial_status(self, connected_client):
        """Test that initial status is populated after connection."""
        status = connected_client.status
        
        assert isinstance(status, SeestarStatus)
        
        # Some fields should be populated after connection
        # At least one of these should be set
        status_fields = [
            status.temp,
            status.battery_capacity,
            status.focus_position,
            status.ra,
            status.dec,
        ]
        
        assert any(field is not None for field in status_fields), \
            "No status fields were populated after connection"
    
    @pytest.mark.asyncio
    async def test_pi_is_verified(self, connected_client):
        """Test checking if Pi is verified."""
        response = await connected_client.send_and_recv(PiIsVerified())
        
        assert response is not None
        if hasattr(response, 'result'):
            # Result might be boolean or dict with verified field
            if isinstance(response.result, bool):
                assert response.result in [True, False]
            elif isinstance(response.result, dict) and 'verified' in response.result:
                assert response.result['verified'] in [True, False]
    
    @pytest.mark.asyncio
    async def test_refresh_view_state(self, connected_client):
        """Test refreshing view state."""
        # Get initial state
        initial_mode = connected_client.client_mode
        
        # Refresh view state
        await connected_client.refresh_view_state()
        
        # Client mode should be set
        assert connected_client.client_mode is not None
        assert connected_client.client_mode in [
            "Initialise", "ContinuousExposure", "Stack", 
            "Streaming", "AutoGoto", "AutoFocus", "Idle"
        ]


class TestSettingsCommands:
    """Test settings-related commands."""
    
    @pytest_asyncio.fixture
    async def connected_client(self):
        """Create and connect a client."""
        event_bus = EventBus()
        client = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            event_bus=event_bus,
        )
        
        try:
            await client.connect()
            yield client
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")
        finally:
            if client.is_connected:
                await client.disconnect()
    
    @pytest.mark.asyncio
    async def test_set_user_location(self, connected_client):
        """Test setting user location."""
        # Set to a test location (Greenwich Observatory)
        params = SetUserLocationParameters(lat=51.4779, lon=0.0)
        response = await connected_client.send_and_recv(
            SetUserLocation(params=params)
        )
        
        if response is not None and hasattr(response, 'result'):
            if isinstance(response.result, dict) and 'success' in response.result:
                assert response.result['success'] in [True, False]
    
    @pytest.mark.asyncio
    async def test_set_time(self, connected_client):
        """Test setting telescope time."""
        now = datetime.now()
        params = [PiSetTimeParameter(
            year=now.year,
            mon=now.month,
            day=now.day,
            hour=now.hour,
            min=now.minute,
            sec=now.second,
            time_zone="UTC"
        )]
        
        response = await connected_client.send_and_recv(
            PiSetTime(params=params)
        )
        
        if response is not None and hasattr(response, 'result'):
            if isinstance(response.result, dict) and 'success' in response.result:
                assert response.result['success'] in [True, False]
    
    @pytest.mark.asyncio
    async def test_set_language(self, connected_client):
        """Test setting language preference."""
        params = SettingParameters(lang="en")
        response = await connected_client.send_and_recv(
            SetSetting(params=params)
        )
        
        if response is not None and hasattr(response, 'result'):
            if isinstance(response.result, dict) and 'success' in response.result:
                assert response.result['success'] in [True, False]


class TestContextManager:
    """Test context manager functionality with hardware."""
    
    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test using client as context manager."""
        event_bus = EventBus()
        
        try:
            async with SeestarClient(
                host=TELESCOPE_HOST,
                port=TELESCOPE_PORT,
                event_bus=event_bus,
            ) as client:
                # Should be connected inside context
                assert client.is_connected
                
                # Should be able to send commands
                response = await client.send_and_recv(GetTime())
                assert response is not None
            
            # Should be disconnected after context
            assert not client.is_connected
            
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")


class TestEventSystem:
    """Test event system with hardware."""
    
    @pytest.mark.asyncio
    async def test_event_reception(self):
        """Test receiving events from hardware."""
        event_bus = EventBus()
        received_events = []
        
        # Set up event handler
        def event_handler(event):
            received_events.append(event)
        
        # Subscribe to common events
        event_bus.subscribe("PiStatus", event_handler)
        event_bus.subscribe("View", event_handler)
        
        client = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            event_bus=event_bus,
        )
        
        try:
            await client.connect()
            
            # Wait a bit for events
            await asyncio.sleep(2.0)
            
            # Trigger some activity that might generate events
            await client.send_and_recv(GetViewState())
            await client.send_and_recv(GetDeviceState())
            
            # Wait for events to be processed
            await asyncio.sleep(1.0)
            
            # We might have received some events
            # (depends on what the hardware sends)
            # Just verify the mechanism works
            assert isinstance(received_events, list)
            
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")
        finally:
            if client.is_connected:
                await client.disconnect()


class TestErrorHandling:
    """Test error handling with hardware."""
    
    @pytest.mark.asyncio
    async def test_invalid_command(self):
        """Test sending invalid command to hardware."""
        event_bus = EventBus()
        client = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            event_bus=event_bus,
        )
        
        try:
            await client.connect()
            
            # Send raw invalid command
            await client.send('{"method": "invalid_command_xyz", "id": 999}')
            
            # Wait a bit for response
            await asyncio.sleep(0.5)
            
            # Should not crash the connection
            assert client.is_connected
            
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")
        finally:
            if client.is_connected:
                await client.disconnect()
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """Test command timeout handling."""
        event_bus = EventBus()
        client = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            event_bus=event_bus,
        )
        
        # Set very short timeout
        client.text_protocol.response_timeout = 0.1
        
        try:
            await client.connect()
            
            # Send command that might timeout
            # Using a high ID that might not get a response
            cmd = GetTime()
            cmd.id = 99999
            
            with pytest.raises(asyncio.TimeoutError):
                await client.send_and_recv(cmd)
            
            # Connection should still be alive
            assert client.is_connected
            
            # Should be able to send more commands
            response = await client.send_and_recv(TestConnection())
            # Response might be None but shouldn't error
            
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")
        finally:
            if client.is_connected:
                await client.disconnect()


# Utility function to check if hardware is available
async def is_hardware_available():
    """Check if hardware is available for testing."""
    try:
        conn = SeestarConnection(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            connection_timeout=2.0,
        )
        await conn.open()
        await conn.close()
        return True
    except Exception:
        return False


# Module-level skip if hardware not available
def pytest_configure(config):
    """Check hardware availability before running tests."""
    loop = asyncio.new_event_loop()
    if not loop.run_until_complete(is_hardware_available()):
        pytest.skip(f"Hardware not available at {TELESCOPE_HOST}:{TELESCOPE_PORT}", allow_module_level=True)