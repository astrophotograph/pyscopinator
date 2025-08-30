"""Fixed tests for SeestarClient with proper mocking."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import pytest
from datetime import datetime

# Try importing Seestar modules
try:
    from scopinator.seestar.client import SeestarClient, SeestarStatus
    from scopinator.seestar.connection import SeestarConnection
    from scopinator.util.eventbus import EventBus
    SEESTAR_AVAILABLE = True
except ImportError:
    SEESTAR_AVAILABLE = False


@pytest.mark.skipif(not SEESTAR_AVAILABLE, reason="Seestar modules not available")
class TestSeestarClientFixed:
    """Fixed tests for SeestarClient."""
    
    @pytest.fixture
    def mock_connection(self):
        """Create a properly mocked connection."""
        mock = MagicMock()
        mock.open = AsyncMock()
        mock.close = AsyncMock()
        mock.is_connected = MagicMock(return_value=True)
        mock.read = AsyncMock(return_value=None)  # Return None to stop reader loop
        mock.write = AsyncMock()
        return mock
    
    @pytest.fixture
    def event_bus(self):
        """Create an EventBus instance."""
        return EventBus()
    
    @pytest.fixture
    def client(self, mock_connection, event_bus):
        """Create a client with mocked connection."""
        with patch("scopinator.seestar.client.SeestarConnection") as mock_conn_class:
            mock_conn_class.return_value = mock_connection
            client = SeestarClient(
                host="192.168.1.100",
                port=4700,
                event_bus=event_bus,
            )
            return client
    
    @pytest.mark.asyncio
    async def test_client_connect(self, client, mock_connection):
        """Test client connection without background tasks running forever."""
        # Mock the send_and_recv to return quickly
        async def mock_send_recv(cmd):
            from scopinator.seestar.commands.common import CommandResponse
            return CommandResponse(
                id=1,
                Timestamp=datetime.now().isoformat(),
                result={"pi_status": {
                    "temp": 25.0,
                    "charger_status": "Full",
                    "charge_online": True,
                    "battery_capacity": 100
                }}
            )
        
        client.send_and_recv = mock_send_recv
        
        # Connect
        await client.connect()
        
        # Verify connection state
        assert client.is_connected is True
        mock_connection.open.assert_called_once()
        
        # Verify background tasks started
        assert client.background_task is not None
        assert client.reader_task is not None
        assert client.pattern_monitor_task is not None
        assert client.view_refresh_task is not None
        assert client.connection_monitor_task is not None
        
        # Clean up - disconnect to stop background tasks
        await client.disconnect()
        
    @pytest.mark.asyncio
    async def test_client_disconnect(self, client, mock_connection):
        """Test client disconnection."""
        # First connect
        async def mock_send_recv(cmd):
            from scopinator.seestar.commands.common import CommandResponse
            return CommandResponse(
                id=1,
                Timestamp=datetime.now().isoformat(),
                result={"pi_status": {
                    "temp": 25.0,
                    "charger_status": "Full",
                    "charge_online": True,
                    "battery_capacity": 100
                }}
            )
        
        client.send_and_recv = mock_send_recv
        await client.connect()
        
        # Now disconnect
        await client.disconnect()
        
        # Verify disconnection
        assert client.is_connected is False
        mock_connection.close.assert_called_once()
        
        # Verify tasks are cleaned up
        assert client.background_task is None
        assert client.reader_task is None
        assert client.pattern_monitor_task is None
        assert client.view_refresh_task is None
        assert client.connection_monitor_task is None
        
    @pytest.mark.asyncio
    async def test_client_context_manager(self, mock_connection, event_bus):
        """Test client as async context manager."""
        with patch("scopinator.seestar.client.SeestarConnection") as mock_conn_class:
            mock_conn_class.return_value = mock_connection
            
            async with SeestarClient(
                host="192.168.1.100",
                port=4700,
                event_bus=event_bus,
            ) as client:
                # Mock send_and_recv
                async def mock_send_recv(cmd):
                    from scopinator.seestar.commands.common import CommandResponse
                    return CommandResponse(
                        id=1,
                        Timestamp=datetime.now().isoformat(),
                        result={"pi_status": {
                            "temp": 25.0,
                            "charger_status": "Full",
                            "charge_online": True,
                            "battery_capacity": 100
                        }}
                    )
                
                client.send_and_recv = mock_send_recv
                
                # Should be connected inside context
                assert client.is_connected is True
                
            # Should be disconnected after context exit
            assert client.is_connected is False


@pytest.mark.skipif(not SEESTAR_AVAILABLE, reason="Seestar modules not available")
class TestEventBusFixed:
    """Fixed tests for EventBus."""
    
    @pytest.fixture
    def event_bus(self):
        """Create an EventBus instance."""
        return EventBus()
    
    @pytest.mark.asyncio
    async def test_eventbus_subscribe_publish(self, event_bus):
        """Test event subscription and publishing."""
        received_events = []
        
        # Create an async handler
        async def handler(event):
            received_events.append(event)
        
        # Subscribe
        event_bus.subscribe("test_event", handler)
        
        # Publish event
        test_data = {"message": "test"}
        event_bus.emit("test_event", test_data)
        
        # Give async handler time to process
        await asyncio.sleep(0.1)
        
        # Verify event was received
        assert len(received_events) == 1
        assert received_events[0] == test_data
        
    def test_eventbus_sync_handler(self, event_bus):
        """Test synchronous event handler."""
        received_events = []
        
        # Create a sync handler
        def handler(event):
            received_events.append(event)
        
        # Subscribe
        event_bus.subscribe("test_event", handler)
        
        # Publish event
        test_data = {"message": "test"}
        event_bus.emit("test_event", test_data)
        
        # Verify event was received immediately
        assert len(received_events) == 1
        assert received_events[0] == test_data
        
    def test_eventbus_remove_listener(self, event_bus):
        """Test removing event listener."""
        received_events = []
        
        def handler(event):
            received_events.append(event)
        
        # Subscribe
        event_bus.subscribe("test_event", handler)
        
        # Remove listener
        event_bus.remove_listener("test_event", handler)
        
        # Publish event
        event_bus.emit("test_event", {"message": "test"})
        
        # Should not receive event
        assert len(received_events) == 0
        
    def test_eventbus_multiple_handlers(self, event_bus):
        """Test multiple handlers for same event."""
        results = {"handler1": [], "handler2": []}
        
        def handler1(event):
            results["handler1"].append(event)
        
        def handler2(event):
            results["handler2"].append(event)
        
        # Subscribe both
        event_bus.subscribe("test_event", handler1)
        event_bus.subscribe("test_event", handler2)
        
        # Publish event
        test_data = {"message": "test"}
        event_bus.emit("test_event", test_data)
        
        # Both should receive
        assert len(results["handler1"]) == 1
        assert len(results["handler2"]) == 1
        assert results["handler1"][0] == test_data
        assert results["handler2"][0] == test_data