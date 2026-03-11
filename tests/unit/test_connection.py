"""Unit tests for SeestarConnection."""

import asyncio
from asyncio import IncompleteReadError
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scopinator.seestar.connection import SeestarConnection


@pytest.fixture
def connection():
    return SeestarConnection(
        host="192.168.1.100",
        port=4700,
        connection_timeout=5.0,
        read_timeout=5.0,
        write_timeout=5.0,
    )


def make_writer():
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    return writer


def make_reader():
    return AsyncMock()


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestConnectionInit:
    def test_fields(self, connection):
        assert connection.host == "192.168.1.100"
        assert connection.port == 4700
        assert connection.connection_timeout == 5.0
        assert connection.read_timeout == 5.0
        assert connection.write_timeout == 5.0
        assert connection.reader is None
        assert connection.writer is None
        assert connection.written_messages == 0
        assert connection.read_messages == 0
        assert connection._reconnect_attempts == 0
        assert connection._reconnect_lock is not None

    def test_str(self, connection):
        assert str(connection) == "192.168.1.100:4700"

    def test_repr(self, connection):
        assert "192.168.1.100" in repr(connection)
        assert "4700" in repr(connection)

    def test_get_connection_stats(self, connection):
        stats = connection.get_connection_stats()
        assert stats["host"] == "192.168.1.100"
        assert stats["port"] == 4700
        assert stats["is_connected"] is False
        assert stats["written_messages"] == 0
        assert stats["read_messages"] == 0


# ---------------------------------------------------------------------------
# is_connected
# ---------------------------------------------------------------------------

class TestIsConnected:
    def test_no_reader_writer(self, connection):
        assert connection.is_connected() is False

    def test_flag_false_with_streams(self, connection):
        connection.reader = make_reader()
        connection.writer = make_writer()
        # _is_connected is still False
        assert connection.is_connected() is False

    def test_all_set(self, connection):
        connection.reader = make_reader()
        connection.writer = make_writer()
        connection._is_connected = True
        assert connection.is_connected() is True

    def test_missing_reader(self, connection):
        connection.writer = make_writer()
        connection._is_connected = True
        assert connection.is_connected() is False

    def test_missing_writer(self, connection):
        connection.reader = make_reader()
        connection._is_connected = True
        assert connection.is_connected() is False


# ---------------------------------------------------------------------------
# _is_connection_reset_error
# ---------------------------------------------------------------------------

class TestIsConnectionResetError:
    def test_connection_reset_error(self, connection):
        assert connection._is_connection_reset_error(ConnectionResetError()) is True

    def test_connection_aborted_error(self, connection):
        assert connection._is_connection_reset_error(ConnectionAbortedError()) is True

    def test_broken_pipe_error(self, connection):
        assert connection._is_connection_reset_error(BrokenPipeError()) is True

    def test_incomplete_read_error(self, connection):
        assert connection._is_connection_reset_error(IncompleteReadError(b"", 10)) is True

    def test_os_error(self, connection):
        assert connection._is_connection_reset_error(OSError()) is True

    def test_asyncio_timeout(self, connection):
        assert connection._is_connection_reset_error(asyncio.TimeoutError()) is True

    def test_value_error(self, connection):
        assert connection._is_connection_reset_error(ValueError("other")) is False

    def test_runtime_error(self, connection):
        assert connection._is_connection_reset_error(RuntimeError("other")) is False


# ---------------------------------------------------------------------------
# open()
# ---------------------------------------------------------------------------

class TestOpen:
    @pytest.mark.asyncio
    async def test_open_success(self, connection):
        mock_reader = make_reader()
        mock_writer = make_writer()

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await connection.open()

        assert connection.reader is mock_reader
        assert connection.writer is mock_writer
        assert connection._is_connected is True
        assert connection._reconnect_attempts == 0
        assert connection.written_messages == 0
        assert connection.read_messages == 0

    @pytest.mark.asyncio
    async def test_open_timeout(self, connection):
        with patch("asyncio.open_connection", side_effect=asyncio.TimeoutError()):
            with pytest.raises(asyncio.TimeoutError):
                await connection.open()

        assert connection._is_connected is False
        assert connection.reader is None

    @pytest.mark.asyncio
    async def test_open_os_error(self, connection):
        with patch("asyncio.open_connection", side_effect=OSError("refused")):
            with pytest.raises(OSError):
                await connection.open()

        assert connection._is_connected is False


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------

class TestClose:
    @pytest.mark.asyncio
    async def test_close_sets_disconnected(self, connection):
        connection.reader = make_reader()
        connection.writer = make_writer()
        connection._is_connected = True

        await connection.close()

        assert connection._is_connected is False
        assert connection.reader is None
        assert connection.writer is None

    @pytest.mark.asyncio
    async def test_close_calls_writer_close(self, connection):
        writer = make_writer()
        connection.writer = writer
        connection.reader = make_reader()
        connection._is_connected = True

        await connection.close()

        writer.close.assert_called_once()
        writer.wait_closed.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_handles_connection_reset_on_wait_closed(self, connection):
        writer = make_writer()
        writer.wait_closed = AsyncMock(side_effect=ConnectionResetError())
        connection.writer = writer
        connection.reader = make_reader()
        connection._is_connected = True

        # Should not raise
        await connection.close()
        assert connection.reader is None
        assert connection.writer is None

    @pytest.mark.asyncio
    async def test_close_without_writer(self, connection):
        connection._is_connected = True
        # Should not raise even with no writer
        await connection.close()
        assert connection._is_connected is False


# ---------------------------------------------------------------------------
# write()
# ---------------------------------------------------------------------------

class TestWrite:
    @pytest.mark.asyncio
    async def test_write_success(self, connection):
        writer = make_writer()
        connection.writer = writer
        connection.reader = make_reader()
        connection._is_connected = True

        await connection.write('{"method":"test"}')

        # Should append \r\n
        writer.write.assert_called_once_with('{"method":"test"}\r\n'.encode())
        writer.drain.assert_called_once()
        assert connection.written_messages == 1

    @pytest.mark.asyncio
    async def test_write_increments_counter(self, connection):
        writer = make_writer()
        connection.writer = writer
        connection.reader = make_reader()
        connection._is_connected = True

        await connection.write("msg1")
        await connection.write("msg2")
        assert connection.written_messages == 2

    @pytest.mark.asyncio
    async def test_write_not_connected_raises(self, connection):
        # When not connected, write() raises ConnectionError internally, which is caught
        # by the exception handler (ConnectionError is an OSError subclass), triggers a
        # reconnect attempt, and ultimately raises "Failed to reconnect" if that fails.
        with pytest.raises(ConnectionError):
            await connection.write("test")

    @pytest.mark.asyncio
    async def test_write_connection_reset_then_reconnect_success(self, connection):
        # Use a list to provide a new writer after reconnect
        writers = []

        async def fake_reconnect():
            # Simulate successful reconnect by providing a new working writer
            new_writer = make_writer()
            connection.writer = new_writer
            connection._is_connected = True
            writers.append(new_writer)
            return True

        writer = make_writer()
        writer.drain = AsyncMock(side_effect=ConnectionResetError())
        connection.writer = writer
        connection.reader = make_reader()
        connection._is_connected = True

        with patch.object(connection, "_reconnect_with_backoff", side_effect=fake_reconnect) as mock_reconnect:
            with patch.object(connection, "close", new_callable=AsyncMock):
                await connection.write("test")

        mock_reconnect.assert_called_once()
        # Verify the retry write went to the new writer
        assert len(writers) == 1
        writers[0].write.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_connection_reset_reconnect_fails(self, connection):
        writer = make_writer()
        writer.drain = AsyncMock(side_effect=ConnectionResetError())
        connection.writer = writer
        connection.reader = make_reader()
        connection._is_connected = True

        with patch.object(connection, "_reconnect_with_backoff", return_value=False):
            with patch.object(connection, "close", new_callable=AsyncMock):
                with pytest.raises(ConnectionError, match="Failed to reconnect"):
                    await connection.write("test")

    @pytest.mark.asyncio
    async def test_write_unexpected_error_closes_connection(self, connection):
        writer = make_writer()
        writer.drain = AsyncMock(side_effect=RuntimeError("unexpected"))
        connection.writer = writer
        connection.reader = make_reader()
        connection._is_connected = True

        with patch.object(connection, "close", new_callable=AsyncMock) as mock_close:
            with pytest.raises(RuntimeError):
                await connection.write("test")
        mock_close.assert_called_once()


# ---------------------------------------------------------------------------
# read()
# ---------------------------------------------------------------------------

class TestRead:
    @pytest.mark.asyncio
    async def test_read_not_connected_returns_none(self, connection):
        result = await connection.read()
        assert result is None

    @pytest.mark.asyncio
    async def test_read_success(self, connection):
        reader = make_reader()
        reader.readuntil = AsyncMock(return_value=b'{"Event":"PiStatus"}\r\n')
        connection.reader = reader
        connection.writer = make_writer()
        connection._is_connected = True

        result = await connection.read()
        assert result == '{"Event":"PiStatus"}'
        assert connection.read_messages == 1

    @pytest.mark.asyncio
    async def test_read_strips_whitespace(self, connection):
        reader = make_reader()
        reader.readuntil = AsyncMock(return_value=b"  hello  \r\n")
        connection.reader = reader
        connection.writer = make_writer()
        connection._is_connected = True

        result = await connection.read()
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_read_connection_reset_triggers_reconnect(self, connection):
        reader = make_reader()
        reader.readuntil = AsyncMock(side_effect=ConnectionResetError())
        connection.reader = reader
        connection.writer = make_writer()
        connection._is_connected = True

        with patch.object(connection, "_reconnect_with_backoff", return_value=True) as mock_reconnect:
            with patch.object(connection, "close", new_callable=AsyncMock):
                result = await connection.read()

        mock_reconnect.assert_called_once()
        assert result is None  # read returns None after reconnect, caller retries

    @pytest.mark.asyncio
    async def test_read_unexpected_error_returns_none(self, connection):
        reader = make_reader()
        reader.readuntil = AsyncMock(side_effect=RuntimeError("boom"))
        connection.reader = reader
        connection.writer = make_writer()
        connection._is_connected = True

        with patch.object(connection, "close", new_callable=AsyncMock):
            result = await connection.read()
        assert result is None


# ---------------------------------------------------------------------------
# read_exactly()
# ---------------------------------------------------------------------------

class TestReadExactly:
    @pytest.mark.asyncio
    async def test_read_exactly_not_connected_returns_none(self, connection):
        result = await connection.read_exactly(10)
        assert result is None

    @pytest.mark.asyncio
    async def test_read_exactly_success(self, connection):
        reader = make_reader()
        data = b"\x00\x01\x02\x03"
        reader.readexactly = AsyncMock(return_value=data)
        connection.reader = reader
        connection.writer = make_writer()
        connection._is_connected = True

        result = await connection.read_exactly(4)
        assert result == data
        reader.readexactly.assert_called_once_with(4)
        assert connection.read_messages == 1

    @pytest.mark.asyncio
    async def test_read_exactly_connection_reset_triggers_reconnect(self, connection):
        reader = make_reader()
        reader.readexactly = AsyncMock(side_effect=IncompleteReadError(b"", 80))
        connection.reader = reader
        connection.writer = make_writer()
        connection._is_connected = True

        with patch.object(connection, "_reconnect_with_backoff", return_value=True) as mock_reconnect:
            with patch.object(connection, "close", new_callable=AsyncMock):
                result = await connection.read_exactly(80)

        mock_reconnect.assert_called_once()
        assert result is None


# ---------------------------------------------------------------------------
# _reconnect_with_backoff()
# ---------------------------------------------------------------------------

class TestReconnectWithBackoff:
    @pytest.mark.asyncio
    async def test_already_connected_returns_true(self, connection):
        connection.reader = make_reader()
        connection.writer = make_writer()
        connection._is_connected = True

        result = await connection._reconnect_with_backoff()
        assert result is True

    @pytest.mark.asyncio
    async def test_callback_returns_false_skips_reconnect(self, connection):
        connection._should_reconnect_callback = MagicMock(return_value=False)

        result = await connection._reconnect_with_backoff()
        assert result is False

    @pytest.mark.asyncio
    async def test_successful_reconnect(self, connection):
        connect_calls = []

        async def fake_open():
            connect_calls.append(1)
            connection._is_connected = True
            connection.reader = make_reader()
            connection.writer = make_writer()

        with patch.object(connection, "open", side_effect=fake_open):
            with patch.object(connection, "close", new_callable=AsyncMock):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await connection._reconnect_with_backoff()

        assert result is True
        assert len(connect_calls) == 1

    @pytest.mark.asyncio
    async def test_failed_reconnect_returns_false(self, connection):
        with patch.object(connection, "open", side_effect=OSError("refused")):
            with patch.object(connection, "close", new_callable=AsyncMock):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await connection._reconnect_with_backoff()

        assert result is False

    @pytest.mark.asyncio
    async def test_reboot_detection_after_3_attempts(self, connection):
        """After 3+ failed attempts, reboot detection flag is set."""
        attempt_count = [0]

        async def fake_open():
            attempt_count[0] += 1
            raise OSError("refused")

        with patch.object(connection, "open", side_effect=fake_open):
            with patch.object(connection, "close", new_callable=AsyncMock):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    # Need at least 3 calls to trigger reboot detection
                    for _ in range(3):
                        await connection._do_reconnect_with_backoff()

        assert connection._reconnect_attempts >= 3
