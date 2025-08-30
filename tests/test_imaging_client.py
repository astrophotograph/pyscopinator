"""Comprehensive unit tests for SeestarImagingClient."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call
import pytest
import numpy as np
from datetime import datetime
import json
import threading

from scopinator.seestar.imaging_client import (
    SeestarImagingClient,
    SeestarImagingStatus,
    ParsedEvent,
)
from scopinator.seestar.protocol_handlers import BinaryProtocol, ScopeImage
from scopinator.seestar.events import InternalEvent, BaseEvent, AnnotateResult
from scopinator.seestar.commands.imaging import BeginStreaming, StopStreaming, GetStackedImage
from scopinator.seestar.commands.simple import TestConnection
from scopinator.util.eventbus import EventBus


class TestSeestarImagingStatus:
    """Test SeestarImagingStatus model."""
    
    def test_status_initialization(self):
        """Test status model initialization with defaults."""
        status = SeestarImagingStatus()
        
        assert status.temp is None
        assert status.battery_capacity is None
        assert status.stacked_frame == 0
        assert status.dropped_frame == 0
        assert status.skipped_frame == 0
        assert status.target_name == ""
        assert status.is_streaming is False
        assert status.is_fetching_images is False
        assert status.is_receiving_image is False
        assert status.last_image_elapsed_ms is None
        
    def test_status_reset(self):
        """Test status reset functionality."""
        status = SeestarImagingStatus()
        
        # Set some values
        status.temp = 25.5
        status.battery_capacity = 80
        status.stacked_frame = 10
        status.is_streaming = True
        status.last_image_elapsed_ms = 100.5
        
        # Reset
        status.reset()
        
        # Verify reset
        assert status.temp is None
        assert status.battery_capacity is None
        assert status.stacked_frame == 0
        assert status.is_streaming is False
        assert status.last_image_elapsed_ms is None


class TestSeestarImagingClient:
    """Test SeestarImagingClient functionality."""
    
    @pytest.fixture
    def event_bus(self):
        """Create an EventBus instance."""
        return EventBus()
    
    @pytest.fixture
    def mock_connection(self):
        """Create a mock connection."""
        mock = AsyncMock()
        mock.is_connected.return_value = True
        mock.open = AsyncMock()
        mock.close = AsyncMock()
        mock.read = AsyncMock(return_value=None)
        mock.read_exactly = AsyncMock(return_value=None)
        mock.write = AsyncMock()
        return mock
    
    @pytest.fixture
    def client(self, event_bus, mock_connection):
        """Create an imaging client with mocked connection."""
        client = SeestarImagingClient(
            host="192.168.1.100",
            port=5556,
            event_bus=event_bus,
            connection_timeout=1.0,
            read_timeout=1.0,
            write_timeout=1.0,
        )
        # Replace connection with mock
        client.connection = mock_connection
        return client
    
    def test_client_initialization(self, event_bus):
        """Test client initialization."""
        client = SeestarImagingClient(
            host="192.168.1.100",
            port=5556,
            event_bus=event_bus,
        )
        
        assert client.host == "192.168.1.100"
        assert client.port == 5556
        assert client.event_bus == event_bus
        assert client.is_connected is False
        assert client.status.is_streaming is False
        assert client.cached_raw_image is None
        assert isinstance(client.binary_protocol, BinaryProtocol)
        
    @pytest.mark.asyncio
    async def test_connect(self, client, mock_connection):
        """Test client connection."""
        await client.connect()
        
        assert client.is_connected is True
        mock_connection.open.assert_called_once()
        assert client.background_task is not None
        assert client.reader_task is not None
        assert client.connection_monitor_task is not None
        
        # Clean up tasks
        await client.disconnect()
        
    @pytest.mark.asyncio
    async def test_disconnect(self, client, mock_connection):
        """Test client disconnection."""
        # First connect
        await client.connect()
        client.status.is_streaming = True
        
        # Mock stop_streaming
        client.stop_streaming = AsyncMock()
        
        await client.disconnect()
        
        assert client.is_connected is False
        client.stop_streaming.assert_called_once()
        mock_connection.close.assert_called_once()
        assert client.background_task is None
        assert client.reader_task is None
            
    @pytest.mark.asyncio
    async def test_context_manager(self, event_bus, mock_connection):
        """Test async context manager support."""
        async with SeestarImagingClient(
            host="192.168.1.100",
            port=5556,
            event_bus=event_bus,
        ) as client:
            # Replace connection with mock after creation
            client.connection = mock_connection
            await client.connect()
            assert client.is_connected is True
        
        # After context exit, should be disconnected
        assert client.is_connected is False
    
    @pytest.mark.asyncio
    async def test_send_command(self, client, mock_connection):
        """Test sending commands."""
        # Test with BaseModel command
        cmd = TestConnection()
        cmd.id = 123
        
        await client.send(cmd)
        
        expected_json = cmd.model_dump_json()
        mock_connection.write.assert_called_once_with(expected_json)
        
    @pytest.mark.asyncio
    async def test_send_string_command(self, client, mock_connection):
        """Test sending string commands."""
        await client.send('{"test": "command"}')
        
        mock_connection.write.assert_called_once_with('{"test": "command"}')
        
    @pytest.mark.asyncio
    async def test_start_streaming(self, client, mock_connection):
        """Test starting streaming."""
        assert client.status.is_streaming is False
        
        await client.start_streaming()
        
        assert client.status.is_streaming is True
        # Verify BeginStreaming command was sent
        assert mock_connection.write.called
        
    @pytest.mark.asyncio
    async def test_start_streaming_already_streaming(self, client, mock_connection):
        """Test starting streaming when already streaming."""
        client.status.is_streaming = True
        
        await client.start_streaming()
        
        # Should not send command if already streaming
        mock_connection.write.assert_not_called()
        
    @pytest.mark.asyncio
    async def test_stop_streaming(self, client, mock_connection):
        """Test stopping streaming."""
        client.status.is_streaming = True
        
        await client.stop_streaming()
        
        assert client.status.is_streaming is False
        # Verify StopStreaming command was sent
        assert mock_connection.write.called
        
    @pytest.mark.asyncio
    async def test_handle_stack_event_frame_complete(self, client):
        """Test handling stack event with frame_complete state."""
        client.status.is_fetching_images = True
        client.status.is_receiving_image = False
        
        event = MagicMock()
        event.state = "frame_complete"
        
        with patch.object(client, 'send', new_callable=AsyncMock) as mock_send:
            await client._handle_stack_event(event)
            
            # Should send GetStackedImage command
            mock_send.assert_called_once()
            call_args = mock_send.call_args[0][0]
            assert isinstance(call_args, GetStackedImage)
            
    @pytest.mark.asyncio
    async def test_handle_stack_event_skip_when_receiving(self, client):
        """Test skipping frame request when already receiving image."""
        client.status.is_fetching_images = True
        client.status.is_receiving_image = True
        client.status.skipped_frame = 0
        
        event = MagicMock()
        event.state = "frame_complete"
        
        with patch.object(client, 'send', new_callable=AsyncMock) as mock_send:
            await client._handle_stack_event(event)
            
            # Should not send command when already receiving
            mock_send.assert_not_called()
            assert client.status.skipped_frame == 1
            
    @pytest.mark.asyncio
    async def test_handle_client_mode_change(self, client, mock_connection):
        """Test handling client mode changes."""
        event = InternalEvent(
            Timestamp=datetime.now().isoformat(),
            params={"existing": "Idle", "new_mode": "ContinuousExposure"}
        )
        
        with patch.object(client, 'start_streaming', new_callable=AsyncMock) as mock_start:
            await client._handle_client_mode(event)
            
            mock_start.assert_called_once()
            assert client.client_mode == "ContinuousExposure"
            
    @pytest.mark.asyncio
    async def test_handle_client_mode_stop_streaming(self, client):
        """Test stopping streaming on mode change."""
        client.client_mode = "ContinuousExposure"
        
        event = InternalEvent(
            Timestamp=datetime.now().isoformat(),
            params={"existing": "ContinuousExposure", "new_mode": "Idle"}
        )
        
        with patch.object(client, 'stop_streaming', new_callable=AsyncMock) as mock_stop:
            await client._handle_client_mode(event)
            
            mock_stop.assert_called_once()
            assert client.client_mode == "Idle"
            
    def test_trigger_enhancement_settings_changed(self, client):
        """Test triggering enhancement settings change."""
        assert client.enhancement_settings_changed_event is not None
        assert not client.enhancement_settings_changed_event.is_set()
        
        client.trigger_enhancement_settings_changed()
        
        assert client.enhancement_settings_changed_event.is_set()
        
    def test_get_cached_raw_image(self, client):
        """Test getting cached raw image."""
        # Initially None
        assert client.get_cached_raw_image() is None
        
        # Set a cached image
        test_image = ScopeImage(width=100, height=100, image=np.zeros((100, 100, 3)))
        client.cached_raw_image = test_image
        
        result = client.get_cached_raw_image()
        assert result == test_image
        
    @pytest.mark.asyncio
    async def test_reader_with_image_data(self, client, mock_connection):
        """Test reader task with image data."""
        # Mock header and data
        header = b'\x00' * 80  # Dummy header
        image_data = b'\x00' * 10000  # Dummy image data
        
        # Mock binary protocol parsing
        with patch.object(client.binary_protocol, 'parse_header') as mock_parse:
            mock_parse.return_value = (10000, 1, 1920, 1080)  # size, id, width, height
            
            with patch.object(client.binary_protocol, 'handle_incoming_message') as mock_handle:
                test_image = ScopeImage(width=1920, height=1080, image=np.zeros((1080, 1920, 3)))
                mock_handle.return_value = test_image
                
                # Set up mock connection to return data once then None
                mock_connection.read_exactly.side_effect = [header, image_data, None]
                
                # Start reader briefly
                client.is_connected = True
                reader_task = asyncio.create_task(client._reader())
                
                # Let it process
                await asyncio.sleep(0.1)
                
                # Stop reader
                client.is_connected = False
                reader_task.cancel()
                try:
                    await reader_task
                except asyncio.CancelledError:
                    pass
                
                # Verify image was processed
                assert client.image == test_image
                assert client.status.last_image_elapsed_ms is not None
                assert client.status.last_image_size_bytes == 10000
                
    @pytest.mark.asyncio
    async def test_heartbeat(self, client, mock_connection):
        """Test heartbeat task."""
        client.is_connected = True
        
        # Run heartbeat briefly
        heartbeat_task = asyncio.create_task(client._heartbeat())
        
        # Wait briefly
        await asyncio.sleep(0.1)
        
        # Stop heartbeat
        client.is_connected = False
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
            
    @pytest.mark.asyncio
    async def test_connection_monitor(self, client, mock_connection):
        """Test connection monitor task."""
        client.is_connected = True
        client._connection_check_interval = 0.1  # Speed up for testing
        
        # Mock should_attempt_reconnection
        with patch.object(client, '_should_attempt_reconnection') as mock_should:
            mock_should.return_value = False
            
            # Run monitor briefly
            monitor_task = asyncio.create_task(client._connection_monitor())
            
            # Wait briefly
            await asyncio.sleep(0.2)
            
            # Stop monitor
            client.is_connected = False
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
                
            # Verify it checked reconnection
            assert mock_should.called
            
    def test_should_attempt_reconnection(self, client):
        """Test reconnection logic."""
        # Should not reconnect in Idle mode
        client.client_mode = "Idle"
        assert not client._should_attempt_reconnection()
        
        # Should not reconnect in None mode
        client.client_mode = None
        assert not client._should_attempt_reconnection()
        
        # Should reconnect in active modes
        client.client_mode = "ContinuousExposure"
        assert client._should_attempt_reconnection()
        
        client.client_mode = "Streaming"
        assert client._should_attempt_reconnection()
        
        client.client_mode = "Stacking"
        assert client._should_attempt_reconnection()


class TestImagingClientImageProcessing:
    """Test image processing functionality."""
    
    @pytest.fixture
    def client(self):
        """Create a client for testing."""
        event_bus = EventBus()
        return SeestarImagingClient(
            host="192.168.1.100",
            port=5556,
            event_bus=event_bus,
        )
    
    @pytest.mark.asyncio
    async def test_get_next_image_continuous(self, client):
        """Test getting next image in continuous mode."""
        client.is_connected = True
        client.client_mode = "ContinuousExposure"
        
        # Create a test image
        test_image = ScopeImage(
            width=1920,
            height=1080,
            image=np.ones((1080, 1920, 3), dtype=np.uint8) * 128
        )
        
        # Set the image
        client.image = test_image
        
        # Get images
        image_gen = client.get_next_image(camera_id=0)
        
        # Get one image
        received_image = await anext(image_gen.__aiter__())
        assert received_image == test_image
        
        # Clean up
        client.is_connected = False
        
    @pytest.mark.asyncio 
    async def test_get_next_image_streaming_mode(self, client):
        """Test getting images in streaming mode with RTSP."""
        client.is_connected = True
        client.client_mode = "Streaming"
        
        # Mock RtspClient
        with patch('scopinator.seestar.imaging_client.RtspClient') as MockRtsp:
            mock_rtsp = MagicMock()
            mock_rtsp.__enter__ = MagicMock(return_value=mock_rtsp)
            mock_rtsp.__exit__ = MagicMock(return_value=None)
            mock_rtsp.finish_opening = AsyncMock()
            mock_rtsp.is_opened.side_effect = [True, False]  # Open then close
            mock_rtsp.read.return_value = np.zeros((1080, 1920, 3))
            MockRtsp.return_value = mock_rtsp
            
            # Get images
            image_gen = client.get_next_image(camera_id=0)
            
            # Should use RTSP
            async for _ in image_gen:
                break  # Just get one
                
            # Verify RTSP was used
            MockRtsp.assert_called_once_with(
                rtsp_server_uri="rtsp://192.168.1.100:4554/stream"
            )
            
        # Clean up
        client.is_connected = False


class TestImagingClientEventHandling:
    """Test event handling in imaging client."""
    
    @pytest.fixture
    def client(self):
        """Create a client for testing."""
        event_bus = EventBus()
        return SeestarImagingClient(
            host="192.168.1.100",
            port=5556,
            event_bus=event_bus,
        )
    
    def test_event_listener_registration(self, client):
        """Test that event listeners are registered."""
        # Verify listeners are added
        assert len(client.event_bus.listeners) > 0
        assert "Stack" in client.event_bus.listeners
        assert "ClientModeChanged" in client.event_bus.listeners
        
    @pytest.mark.asyncio
    async def test_stack_event_handling(self, client):
        """Test handling of Stack events."""
        client.status.is_fetching_images = True
        
        # Create a stack event
        event = MagicMock()
        event.state = "frame_complete"
        
        # Emit event
        client.event_bus.emit("Stack", event)
        
        # Give event handler time to process
        await asyncio.sleep(0.1)
        
    @pytest.mark.asyncio
    async def test_client_mode_event_handling(self, client):
        """Test handling of ClientModeChanged events."""
        # Create mode change event
        event = InternalEvent(
            Timestamp=datetime.now().isoformat(),
            params={"existing": "Idle", "new_mode": "ContinuousExposure"}
        )
        
        # Emit event
        client.event_bus.emit("ClientModeChanged", event)
        
        # Give event handler time to process
        await asyncio.sleep(0.1)


class TestImagingClientTimingMetrics:
    """Test image timing and metrics functionality."""
    
    @pytest.fixture
    def client(self):
        """Create a client for testing."""
        event_bus = EventBus()
        return SeestarImagingClient(
            host="192.168.1.100",
            port=5556,
            event_bus=event_bus,
        )
    
    def test_timing_history_initialization(self, client):
        """Test timing history is properly initialized."""
        assert len(client._image_timing_history) == 0
        assert client._image_timing_history.maxlen == 20
        
    def test_timing_metrics_update(self, client):
        """Test updating timing metrics."""
        # Add some timing samples
        client._image_timing_history.append(100.0)
        client._image_timing_history.append(150.0)
        client._image_timing_history.append(120.0)
        
        # Calculate average
        avg = sum(client._image_timing_history) / len(client._image_timing_history)
        
        assert avg == 123.33333333333333
        assert len(client._image_timing_history) == 3
        
    def test_timing_history_max_length(self, client):
        """Test timing history respects max length."""
        # Add more than max samples
        for i in range(25):
            client._image_timing_history.append(float(i))
            
        # Should only keep last 20
        assert len(client._image_timing_history) == 20
        assert list(client._image_timing_history) == list(range(5, 25))