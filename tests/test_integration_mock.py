"""Hardware-free integration tests using mocks."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call
import pytest
import json
from datetime import datetime
import numpy as np

from scopinator.seestar.client import SeestarClient, SeestarStatus
from scopinator.seestar.imaging_client import SeestarImagingClient
from scopinator.seestar.connection import SeestarConnection
from scopinator.seestar.commands.simple import (
    GetTime,
    GetDeviceState,
    GetViewState,
    GetFocuserPosition,
    ScopeGetEquCoord,
)
from scopinator.seestar.commands.parameterized import IscopeStartView, IscopeStartViewParams
from scopinator.seestar.commands.common import CommandResponse
from scopinator.seestar.events import InternalEvent, PiStatusEvent
from scopinator.util.eventbus import EventBus


class MockTelescopeServer:
    """Mock telescope server for testing."""
    
    def __init__(self):
        self.device_state = {
            "pi_status": {
                "temp": 25.0,
                "charger_status": "Full",
                "charge_online": True,
                "battery_capacity": 100
            }
        }
        self.view_state = {
            "View": {
                "stage": "Idle",
                "mode": "star",
                "state": "idle",
                "target_name": "",
                "gain": 80
            }
        }
        self.focuser_position = 5000
        self.coordinates = {"ra": 10.0, "dec": 45.0}
        self.message_counter = 0
        
    def handle_command(self, command_str: str) -> str:
        """Handle a command and return response."""
        try:
            cmd = json.loads(command_str)
            method = cmd.get("method", "")
            msg_id = cmd.get("id", self.message_counter)
            self.message_counter += 1
            
            response = {
                "id": msg_id,
                "Timestamp": datetime.now().isoformat(),
            }
            
            if method == "iscope_get_device_state":
                response["result"] = self.device_state
            elif method == "iscope_get_view_state":
                response["result"] = self.view_state
            elif method == "scope_get_focuser_position":
                response["result"] = self.focuser_position
            elif method == "scope_get_equ_coord":
                response["result"] = self.coordinates
            elif method == "get_time":
                response["result"] = {"time": datetime.now().isoformat()}
            elif method == "iscope_start_view":
                # Start goto
                self.view_state["View"]["stage"] = "AutoGoto"
                self.view_state["View"]["state"] = "working"
                response["result"] = {"success": True}
            elif method == "iscope_stop_view":
                # Stop operation
                self.view_state["View"]["stage"] = "Idle"
                self.view_state["View"]["state"] = "idle"
                response["result"] = {"success": True}
            else:
                response["error"] = f"Unknown method: {method}"
                
            return json.dumps(response)
        except Exception as e:
            return json.dumps({"error": str(e)})


class TestIntegratedSystem:
    """Test integrated system behavior without hardware."""
    
    @pytest.fixture
    def mock_server(self):
        """Create a mock telescope server."""
        return MockTelescopeServer()
    
    @pytest.fixture
    def event_bus(self):
        """Create shared event bus."""
        return EventBus()
    
    @pytest.fixture
    async def mock_connection_factory(self, mock_server):
        """Factory for creating mock connections."""
        def create_mock_connection():
            mock_conn = AsyncMock()
            mock_conn.is_connected = MagicMock(return_value=True)
            mock_conn.open = AsyncMock()
            mock_conn.close = AsyncMock()
            
            # Mock write to process commands through server
            async def mock_write(data):
                if isinstance(data, bytes):
                    data = data.decode()
                response = mock_server.handle_command(data)
                mock_conn.last_response = response
                
            mock_conn.write = AsyncMock(side_effect=mock_write)
            
            # Mock read to return last response
            async def mock_read():
                if hasattr(mock_conn, 'last_response'):
                    resp = mock_conn.last_response
                    delattr(mock_conn, 'last_response')
                    return resp
                return None
                
            mock_conn.read = AsyncMock(side_effect=mock_read)
            
            return mock_conn
            
        return create_mock_connection
    
    @pytest.mark.asyncio
    async def test_full_telescope_workflow(self, mock_server, event_bus, mock_connection_factory):
        """Test complete telescope operation workflow."""
        # Create mock connection
        mock_conn = mock_connection_factory()
        
        with patch("scopinator.seestar.client.SeestarConnection") as mock_conn_class:
            mock_conn_class.return_value = mock_conn
            
            # Create client
            client = SeestarClient(
                host="192.168.1.100",
                port=4700,
                event_bus=event_bus,
            )
            
            # Connect
            await client.connect()
            assert client.is_connected is True
            
            # Verify initial status was fetched
            assert client.status.battery_capacity == 100
            assert client.status.temp == 25.0
            
            # Test goto operation
            response = await client.goto("M31", 10.0, 45.0)
            assert response is not None
            
            # Verify state changed
            assert mock_server.view_state["View"]["stage"] == "AutoGoto"
            
            # Stop goto
            response = await client.stop_goto()
            assert response is not None
            
            # Verify state returned to idle
            assert mock_server.view_state["View"]["stage"] == "Idle"
            
            # Disconnect
            await client.disconnect()
            assert client.is_connected is False
    
    @pytest.mark.asyncio
    async def test_client_imaging_coordination(self, event_bus, mock_connection_factory):
        """Test coordination between main client and imaging client."""
        mock_conn1 = mock_connection_factory()
        mock_conn2 = mock_connection_factory()
        
        with patch("scopinator.seestar.client.SeestarConnection") as mock_conn_class1:
            mock_conn_class1.return_value = mock_conn1
            
            # Create main client
            main_client = SeestarClient(
                host="192.168.1.100",
                port=4700,
                event_bus=event_bus,
            )
            
            with patch("scopinator.seestar.imaging_client.SeestarConnection") as mock_conn_class2:
                mock_conn_class2.return_value = mock_conn2
                
                # Create imaging client
                imaging_client = SeestarImagingClient(
                    host="192.168.1.100",
                    port=5556,
                    event_bus=event_bus,
                )
                
                # Connect both
                await main_client.connect()
                await imaging_client.connect()
                
                # Simulate mode change event
                main_client._update_client_mode("ContinuousExposure", "working")
                
                # Give event handlers time to process
                await asyncio.sleep(0.1)
                
                # Imaging client should react to mode change
                assert imaging_client.client_mode == "ContinuousExposure"
                
                # Clean up
                await main_client.disconnect()
                await imaging_client.disconnect()
    
    @pytest.mark.asyncio
    async def test_event_flow(self, event_bus):
        """Test event flow through the system."""
        received_events = {
            "PiStatus": [],
            "Stack": [],
            "ClientModeChanged": []
        }
        
        # Set up event handlers
        async def pi_status_handler(event):
            received_events["PiStatus"].append(event)
            
        async def stack_handler(event):
            received_events["Stack"].append(event)
            
        async def mode_handler(event):
            received_events["ClientModeChanged"].append(event)
            
        event_bus.subscribe("PiStatus", pi_status_handler)
        event_bus.subscribe("Stack", stack_handler)
        event_bus.subscribe("ClientModeChanged", mode_handler)
        
        # Emit events
        pi_event = PiStatusEvent(
            Timestamp=datetime.now().isoformat(),
            temp=25.0,
            battery_capacity=100
        )
        event_bus.emit("PiStatus", pi_event)
        
        mode_event = InternalEvent(
            Timestamp=datetime.now().isoformat(),
            params={"existing": "Idle", "new_mode": "Stack"}
        )
        event_bus.emit("ClientModeChanged", mode_event)
        
        # Allow async handlers to process
        await asyncio.sleep(0.1)
        
        # Verify events were received
        assert len(received_events["PiStatus"]) == 1
        assert received_events["PiStatus"][0] == pi_event
        
        assert len(received_events["ClientModeChanged"]) == 1
        assert received_events["ClientModeChanged"][0] == mode_event
    
    @pytest.mark.asyncio
    async def test_reconnection_logic(self, mock_connection_factory, event_bus):
        """Test automatic reconnection behavior."""
        mock_conn = mock_connection_factory()
        
        # Simulate connection failure after initial connect
        call_count = 0
        original_open = mock_conn.open
        
        async def failing_open():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call succeeds
                return await original_open()
            elif call_count == 2:
                # Second call fails
                raise ConnectionError("Connection lost")
            else:
                # Subsequent calls succeed
                return await original_open()
                
        mock_conn.open = failing_open
        
        # Make is_connected return False after first check
        is_connected_count = 0
        def mock_is_connected():
            nonlocal is_connected_count
            is_connected_count += 1
            if is_connected_count <= 2:
                return True
            elif is_connected_count <= 4:
                return False  # Trigger reconnection
            else:
                return True
                
        mock_conn.is_connected = mock_is_connected
        
        with patch("scopinator.seestar.client.SeestarConnection") as mock_conn_class:
            mock_conn_class.return_value = mock_conn
            
            client = SeestarClient(
                host="192.168.1.100",
                port=4700,
                event_bus=event_bus,
            )
            
            # Set short check interval for testing
            client._connection_check_interval = 0.1
            
            # Connect
            await client.connect()
            assert client.is_connected is True
            
            # Wait for reconnection attempt
            await asyncio.sleep(0.5)
            
            # Should have attempted reconnection
            assert call_count >= 2
            
            # Clean up
            await client.disconnect()
    
    @pytest.mark.asyncio
    async def test_command_timeout_handling(self, mock_connection_factory, event_bus):
        """Test handling of command timeouts."""
        mock_conn = mock_connection_factory()
        
        # Make read return None to simulate timeout
        mock_conn.read = AsyncMock(return_value=None)
        
        with patch("scopinator.seestar.client.SeestarConnection") as mock_conn_class:
            mock_conn_class.return_value = mock_conn
            
            client = SeestarClient(
                host="192.168.1.100",
                port=4700,
                event_bus=event_bus,
            )
            
            # Set short timeout for testing
            client.text_protocol.response_timeout = 0.1
            
            await client.connect()
            
            # Send command that will timeout
            with pytest.raises(asyncio.TimeoutError):
                await client.send_and_recv(GetTime())
                
            # Client should still be connected
            assert client.is_connected is True
            
            # Clean up
            await client.disconnect()


class TestMockedDiscovery:
    """Test telescope discovery without network access."""
    
    @pytest.mark.asyncio
    async def test_discovery_simulation(self):
        """Test telescope discovery with mocked UDP."""
        from scopinator.seestar.commands.discovery import discover_telescopes
        
        # Mock socket operations
        with patch("socket.socket") as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            
            # Simulate receiving discovery response
            mock_sock.recvfrom.return_value = (
                json.dumps({
                    "name": "Seestar S50",
                    "ip": "192.168.1.100",
                    "port": 4700
                }).encode(),
                ("192.168.1.100", 4700)
            )
            
            # Run discovery
            telescopes = await discover_telescopes(timeout=0.1)
            
            # Should find mocked telescope
            assert len(telescopes) > 0
            assert telescopes[0]["ip"] == "192.168.1.100"