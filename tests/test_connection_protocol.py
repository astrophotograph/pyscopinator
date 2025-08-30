"""Mock-based tests for connection and protocol handlers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call
import pytest
import json
import struct
import numpy as np
from datetime import datetime

from scopinator.seestar.connection import SeestarConnection
from scopinator.seestar.protocol_handlers import (
    TextProtocol,
    BinaryProtocol,
    ScopeImage,
)
from scopinator.seestar.commands.common import CommandResponse
from scopinator.seestar.commands.simple import GetTime, GetDeviceState


class TestSeestarConnection:
    """Test SeestarConnection with mocks."""
    
    @pytest.fixture
    def connection(self):
        """Create a connection instance."""
        return SeestarConnection(
            host="192.168.1.100",
            port=4700,
            connection_timeout=1.0,
            read_timeout=1.0,
            write_timeout=1.0,
        )
    
    def test_connection_initialization(self, connection):
        """Test connection initialization."""
        assert connection.host == "192.168.1.100"
        assert connection.port == 4700
        assert connection.connection_timeout == 1.0
        assert connection.read_timeout == 1.0
        assert connection.write_timeout == 1.0
        assert connection.reader is None
        assert connection.writer is None
        assert connection._reconnect_attempts == 0
        
    @pytest.mark.asyncio
    async def test_open_success(self, connection):
        """Test successful connection opening."""
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        
        with patch('asyncio.wait_for') as mock_wait_for:
            with patch('asyncio.open_connection') as mock_open:
                mock_open.return_value = (mock_reader, mock_writer)
                mock_wait_for.return_value = (mock_reader, mock_writer)
                
                await connection.open()
                
                assert connection.reader == mock_reader
                assert connection.writer == mock_writer
                assert connection._reconnect_attempts == 0
                mock_open.assert_called_once_with(
                    connection.host,
                    connection.port
                )
                
    @pytest.mark.asyncio
    async def test_open_timeout(self, connection):
        """Test connection opening with timeout."""
        with patch('asyncio.wait_for') as mock_wait_for:
            mock_wait_for.side_effect = asyncio.TimeoutError()
            
            with pytest.raises(asyncio.TimeoutError):
                await connection.open()
                
            assert connection.reader is None
            assert connection.writer is None
            
    @pytest.mark.asyncio
    async def test_close(self, connection):
        """Test connection closing."""
        mock_writer = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        
        connection.writer = mock_writer
        connection.reader = AsyncMock()
        
        await connection.close()
        
        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_called_once()
        assert connection.reader is None
        assert connection.writer is None
        
    @pytest.mark.asyncio
    async def test_write_success(self, connection):
        """Test successful write operation."""
        mock_writer = AsyncMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        
        connection.writer = mock_writer
        
        test_data = '{"test": "data"}'
        await connection.write(test_data)
        
        mock_writer.write.assert_called_once_with(test_data.encode())
        mock_writer.drain.assert_called_once()
        
    @pytest.mark.asyncio
    async def test_write_no_connection(self, connection):
        """Test write with no connection."""
        connection.writer = None
        
        with pytest.raises(Exception):
            await connection.write("test")
            
    @pytest.mark.asyncio
    async def test_read_success(self, connection):
        """Test successful read operation."""
        mock_reader = AsyncMock()
        test_data = b'{"result": "success"}\n'
        mock_reader.readline = AsyncMock(return_value=test_data)
        
        connection.reader = mock_reader
        
        result = await connection.read()
        
        assert result == test_data.decode().strip()
        mock_reader.readline.assert_called_once()
        
    @pytest.mark.asyncio
    async def test_read_empty(self, connection):
        """Test read with empty response."""
        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(return_value=b'')
        
        connection.reader = mock_reader
        
        result = await connection.read()
        
        assert result is None
        
    @pytest.mark.asyncio
    async def test_read_exactly_success(self, connection):
        """Test read_exactly operation."""
        mock_reader = AsyncMock()
        test_data = b'\x00\x01\x02\x03'
        mock_reader.readexactly = AsyncMock(return_value=test_data)
        
        connection.reader = mock_reader
        
        result = await connection.read_exactly(4)
        
        assert result == test_data
        mock_reader.readexactly.assert_called_once_with(4)
        
    @pytest.mark.asyncio
    async def test_is_connected(self, connection):
        """Test is_connected method."""
        # Not connected
        assert not connection.is_connected()
        
        # Connected
        connection.reader = AsyncMock()
        connection.writer = AsyncMock()
        assert connection.is_connected()
        
        # Writer closed
        connection.writer.is_closing.return_value = True
        assert not connection.is_connected()
        
    @pytest.mark.asyncio
    async def test_reconnect_with_backoff(self, connection):
        """Test reconnection with exponential backoff."""
        connection._max_reconnect_attempts = 3
        connection._reconnect_attempts = 0
        
        with patch('asyncio.sleep') as mock_sleep:
            with patch.object(connection, 'open') as mock_open:
                mock_open.side_effect = [
                    ConnectionError("Failed 1"),
                    ConnectionError("Failed 2"),
                    None  # Success on third attempt
                ]
                
                # Mock should_reconnect callback
                should_reconnect = MagicMock(return_value=True)
                connection.should_reconnect_callback = should_reconnect
                
                await connection._reconnect_with_backoff()
                
                # Verify backoff delays
                assert mock_sleep.call_count == 2
                delays = [call[0][0] for call in mock_sleep.call_args_list]
                assert delays[0] == 1.0  # First retry
                assert delays[1] == 2.0  # Second retry (exponential)
                
                # Verify reconnect attempts
                assert mock_open.call_count == 3
                assert connection._reconnect_attempts == 0  # Reset after success


class TestTextProtocol:
    """Test TextProtocol handler."""
    
    @pytest.fixture
    def protocol(self):
        """Create a TextProtocol instance."""
        return TextProtocol()
    
    def test_initialization(self, protocol):
        """Test protocol initialization."""
        assert protocol.pending_responses == {}
        assert protocol.response_timeout == 30.0
        
    def test_handle_incoming_message_with_id(self, protocol):
        """Test handling message with ID."""
        response = CommandResponse(
            id=123,
            Timestamp=datetime.now().isoformat(),
            result={"status": "ok"}
        )
        
        # Create a future for this ID
        future = asyncio.Future()
        protocol.pending_responses[123] = future
        
        protocol.handle_incoming_message(response)
        
        # Future should be resolved
        assert future.done()
        assert future.result() == response
        assert 123 not in protocol.pending_responses
        
    def test_handle_incoming_message_without_id(self, protocol):
        """Test handling message without matching ID."""
        response = CommandResponse(
            id=999,
            Timestamp=datetime.now().isoformat(),
            result={"status": "ok"}
        )
        
        # No exception should be raised
        protocol.handle_incoming_message(response)
        
    def test_handle_incoming_message_cancelled_future(self, protocol):
        """Test handling message with cancelled future."""
        response = CommandResponse(
            id=123,
            Timestamp=datetime.now().isoformat(),
            result={"status": "ok"}
        )
        
        # Create and cancel a future
        future = asyncio.Future()
        future.cancel()
        protocol.pending_responses[123] = future
        
        protocol.handle_incoming_message(response)
        
        # Should clean up cancelled future
        assert 123 not in protocol.pending_responses
        
    @pytest.mark.asyncio
    async def test_recv_message_success(self, protocol):
        """Test receiving message successfully."""
        message_id = 123
        test_response = CommandResponse(
            id=message_id,
            Timestamp=datetime.now().isoformat(),
            result={"status": "ok"}
        )
        
        # Mock client
        mock_client = MagicMock()
        
        # Start recv_message in background
        recv_task = asyncio.create_task(
            protocol.recv_message(mock_client, message_id)
        )
        
        # Give it time to register
        await asyncio.sleep(0.01)
        
        # Simulate incoming message
        protocol.handle_incoming_message(test_response)
        
        # Get result
        result = await recv_task
        assert result == test_response
        
    @pytest.mark.asyncio
    async def test_recv_message_timeout(self, protocol):
        """Test receiving message with timeout."""
        protocol.response_timeout = 0.1  # Short timeout for testing
        
        mock_client = MagicMock()
        
        with pytest.raises(asyncio.TimeoutError):
            await protocol.recv_message(mock_client, 123)
            
        # Future should be cleaned up
        assert 123 not in protocol.pending_responses
        
    @pytest.mark.asyncio
    async def test_cleanup_expired_futures(self, protocol):
        """Test cleanup of expired futures."""
        # Add some futures
        future1 = asyncio.Future()
        future2 = asyncio.Future()
        future2.cancel()
        
        protocol.pending_responses[1] = future1
        protocol.pending_responses[2] = future2
        
        # Clean up
        protocol._cleanup_expired_futures()
        
        # Cancelled future should be removed
        assert 1 in protocol.pending_responses
        assert 2 not in protocol.pending_responses


class TestBinaryProtocol:
    """Test BinaryProtocol handler."""
    
    @pytest.fixture
    def protocol(self):
        """Create a BinaryProtocol instance."""
        return BinaryProtocol()
    
    def test_initialization(self, protocol):
        """Test protocol initialization."""
        assert protocol is not None
        
    def test_parse_header_valid(self, protocol):
        """Test parsing valid header."""
        # Create a test header (80 bytes)
        # Format: various fields including size, id, width, height
        size = 10000
        msg_id = 123
        width = 1920
        height = 1080
        
        # Create header with proper structure
        header = struct.pack('<I', size)  # Size (4 bytes)
        header += b'\x00' * 12  # Padding
        header += struct.pack('<I', msg_id)  # ID (4 bytes)
        header += b'\x00' * 24  # More padding
        header += struct.pack('<I', width)  # Width (4 bytes)
        header += struct.pack('<I', height)  # Height (4 bytes)
        header += b'\x00' * (80 - len(header))  # Pad to 80 bytes
        
        parsed_size, parsed_id, parsed_width, parsed_height = protocol.parse_header(header)
        
        assert parsed_size == size
        assert parsed_id == msg_id
        assert parsed_width == width
        assert parsed_height == height
        
    def test_parse_header_invalid(self, protocol):
        """Test parsing invalid header."""
        # Too short header
        short_header = b'\x00' * 50
        
        with pytest.raises(Exception):
            protocol.parse_header(short_header)
            
    @pytest.mark.asyncio
    async def test_handle_incoming_message_jpeg(self, protocol):
        """Test handling incoming JPEG message."""
        width = 1920
        height = 1080
        msg_id = 123
        
        # Create fake JPEG data (starts with JPEG magic bytes)
        jpeg_data = b'\xff\xd8\xff\xe0' + b'\x00' * 1000
        
        with patch('cv2.imdecode') as mock_decode:
            # Mock OpenCV decode
            fake_image = np.zeros((height, width, 3), dtype=np.uint8)
            mock_decode.return_value = fake_image
            
            result = await protocol.handle_incoming_message(
                width, height, jpeg_data, msg_id
            )
            
            assert isinstance(result, ScopeImage)
            assert result.width == width
            assert result.height == height
            assert result.image.shape == (height, width, 3)
            
    @pytest.mark.asyncio
    async def test_handle_incoming_message_non_image(self, protocol):
        """Test handling non-image data."""
        width = 0
        height = 0
        msg_id = 123
        
        # Non-image data
        data = b'{"result": "ok"}'
        
        result = await protocol.handle_incoming_message(
            width, height, data, msg_id
        )
        
        # Should return None for non-image data
        assert result is None
        
    def test_is_jpeg_data(self, protocol):
        """Test JPEG data detection."""
        # Valid JPEG data
        jpeg_data = b'\xff\xd8\xff\xe0' + b'\x00' * 100
        assert protocol._is_jpeg_data(jpeg_data)
        
        # Invalid data
        non_jpeg = b'NOT_A_JPEG'
        assert not protocol._is_jpeg_data(non_jpeg)
        
        # Empty data
        assert not protocol._is_jpeg_data(b'')
        
        # Too short
        assert not protocol._is_jpeg_data(b'\xff')


class TestScopeImage:
    """Test ScopeImage model."""
    
    def test_scope_image_creation(self):
        """Test creating ScopeImage."""
        image_data = np.zeros((1080, 1920, 3), dtype=np.uint8)
        
        scope_image = ScopeImage(
            width=1920,
            height=1080,
            image=image_data
        )
        
        assert scope_image.width == 1920
        assert scope_image.height == 1080
        assert scope_image.image.shape == (1080, 1920, 3)
        
    def test_scope_image_with_none(self):
        """Test ScopeImage with None image."""
        scope_image = ScopeImage(
            width=1920,
            height=1080,
            image=None
        )
        
        assert scope_image.width == 1920
        assert scope_image.height == 1080
        assert scope_image.image is None