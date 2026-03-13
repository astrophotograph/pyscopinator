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

        connection._is_connected = True
        connection.reader = MagicMock()
        connection.writer = mock_writer

        test_data = '{"test": "data"}'
        await connection.write(test_data)

        mock_writer.write.assert_called_once_with((test_data + "\r\n").encode())
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
        mock_reader.readuntil = AsyncMock(return_value=test_data)

        connection._is_connected = True
        connection.reader = mock_reader
        connection.writer = MagicMock()

        result = await connection.read()

        assert result == test_data.decode().strip()
        mock_reader.readuntil.assert_called_once()
        
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

        connection._is_connected = True
        connection.reader = mock_reader
        connection.writer = MagicMock()

        result = await connection.read_exactly(4)

        assert result == test_data
        mock_reader.readexactly.assert_called_once_with(4)
        
    @pytest.mark.asyncio
    async def test_is_connected(self, connection):
        """Test is_connected method."""
        # Not connected by default
        assert not connection.is_connected()

        # All three conditions needed: _is_connected flag, reader, and writer
        connection._is_connected = True
        connection.reader = AsyncMock()
        connection.writer = AsyncMock()
        assert connection.is_connected()

        # Missing any one of the three makes it not connected
        connection._is_connected = False
        assert not connection.is_connected()
        
    @pytest.mark.asyncio
    async def test_reconnect_with_backoff(self, connection):
        """Test reconnection with backoff: sleeps then opens connection."""
        with patch('asyncio.sleep') as mock_sleep:
            with patch.object(connection, 'open') as mock_open:
                mock_open.return_value = None  # Success

                result = await connection._reconnect_with_backoff()

                assert result is True
                # Should have slept with some backoff delay
                mock_sleep.assert_called_once()
                # Attempts reset to 0 after success
                assert connection._reconnect_attempts == 0


class TestTextProtocol:
    """Test TextProtocol handler."""
    
    @pytest.fixture
    def protocol(self):
        """Create a TextProtocol instance."""
        return TextProtocol()
    
    def test_initialization(self, protocol):
        """Test protocol initialization."""
        assert protocol._pending_futures == {}
        assert protocol.response_timeout == 30.0
        
    def test_handle_incoming_message_with_id(self, protocol):
        """Test handling message with ID."""
        response = CommandResponse(
            id=123,
            jsonrpc="2.0",
            Timestamp=datetime.now().isoformat(),
            method="test_method",
            code=0,
            result={"status": "ok"}
        )

        loop = asyncio.new_event_loop()
        try:
            future = loop.create_future()
            protocol._pending_futures[123] = future

            protocol.handle_incoming_message(response)

            # Future should be resolved
            assert future.done()
            assert future.result() == response
            # Note: handle_incoming_message does NOT remove futures from the dict
        finally:
            loop.close()
        
    def test_handle_incoming_message_without_id(self, protocol):
        """Test handling message without matching ID."""
        response = CommandResponse(
            id=999,
            jsonrpc="2.0",
            Timestamp=datetime.now().isoformat(),
            method="test_method",
            code=0,
            result={"status": "ok"}
        )

        # No exception should be raised; returns False when no pending future
        result = protocol.handle_incoming_message(response)
        assert result is False
        
    def test_handle_incoming_message_cancelled_future(self, protocol):
        """Test handling message with already-done (cancelled) future."""
        response = CommandResponse(
            id=123,
            jsonrpc="2.0",
            Timestamp=datetime.now().isoformat(),
            method="test_method",
            code=0,
            result={"status": "ok"}
        )

        loop = asyncio.new_event_loop()
        try:
            # Create and cancel a future (it's already done)
            future = loop.create_future()
            future.cancel()
            protocol._pending_futures[123] = future

            # Already-done futures are skipped; returns False
            result = protocol.handle_incoming_message(response)
            assert result is False
        finally:
            loop.close()
        
    @pytest.mark.asyncio
    async def test_recv_message_success(self, protocol):
        """Test receiving message successfully."""
        message_id = 123
        test_response = CommandResponse(
            id=message_id,
            jsonrpc="2.0",
            Timestamp=datetime.now().isoformat(),
            method="test_method",
            code=0,
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
            
        # Future should be cleaned up by recv_message's finally block
        assert 123 not in protocol._pending_futures
        
    @pytest.mark.asyncio
    async def test_pending_futures_are_accessible(self, protocol):
        """Test that pending futures dict is accessible and works correctly."""
        # Register a future
        future = asyncio.get_running_loop().create_future()
        protocol._pending_futures[1] = future

        assert 1 in protocol._pending_futures
        assert not future.done()

        # Resolve it
        future.set_result(None)
        assert future.done()


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
        """Test parsing valid header using the actual big-endian format '>HHHIHHBBHH'."""
        size = 10000
        msg_id = 21  # preview frame ID
        width = 1920
        height = 1080

        # Format: >HHHIHHBBHH = 2+2+2+4+2+2+1+1+2+2 = 20 bytes; needs >20 bytes
        header = struct.pack(">HHHIHHBBHH", 0, 0, 0, size, 0, 0, 0, msg_id, width, height)
        header += b"\x00"  # pad to 21 bytes (must be > 20)

        parsed_size, parsed_id, parsed_width, parsed_height = protocol.parse_header(header)

        assert parsed_size == size
        assert parsed_id == msg_id
        assert parsed_width == width
        assert parsed_height == height
        
    def test_parse_header_invalid(self, protocol):
        """Test parsing too-short header: returns zero sentinel values, no exception."""
        # Header must be > 20 bytes to parse; exactly 20 bytes returns zeros
        short_header = b'\x00' * 20
        size, msg_id, width, height = protocol.parse_header(short_header)
        assert size == 0
        assert msg_id is None
            
    @pytest.mark.asyncio
    async def test_handle_incoming_message_preview(self, protocol):
        """Test handling a preview frame (id=21) with raw bayer data."""
        width = 4
        height = 4
        # id=21 is preview frame; raw data is width*height*2 bytes (bayer)
        raw_data = bytes(width * height * 2)

        result = await protocol.handle_incoming_message(width, height, raw_data, id=21)

        assert isinstance(result, ScopeImage)
        assert result.width == width
        assert result.height == height
            
    @pytest.mark.asyncio
    async def test_handle_incoming_message_non_image(self, protocol):
        """Test handling unknown message ID: returns ScopeImage with no image."""
        data = b'{"result": "ok"}'

        result = await protocol.handle_incoming_message(0, 0, data, id=99)

        assert isinstance(result, ScopeImage)
        assert result.image is None
        
    def test_binary_protocol_is_not_none(self, protocol):
        """Basic sanity check that BinaryProtocol can be instantiated."""
        assert protocol is not None


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