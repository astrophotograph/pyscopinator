"""Unit tests for TextProtocol and BinaryProtocol."""

import asyncio
import io
import struct
import zipfile
from struct import calcsize, pack
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from scopinator.seestar.commands.common import CommandResponse
from scopinator.seestar.protocol_handlers import BinaryProtocol, ScopeImage, TextProtocol


def make_response(id: int, method: str = "test_method", code: int = 0, result=None):
    return CommandResponse(
        id=id,
        jsonrpc="2.0",
        Timestamp="2024-01-01T00:00:00",
        method=method,
        code=code,
        result=result,
    )


# ---------------------------------------------------------------------------
# TextProtocol
# ---------------------------------------------------------------------------

class TestTextProtocolInit:
    def test_default_timeout(self):
        p = TextProtocol()
        assert p.response_timeout == 30.0
        assert p._pending_futures == {}
        assert p._drop_next_response is False
        assert p._delay_time_toggle is False

    def test_custom_timeout(self):
        p = TextProtocol(response_timeout=5.0)
        assert p.response_timeout == 5.0


class TestTextProtocolHandleIncoming:
    def test_resolves_matching_future(self):
        p = TextProtocol()
        loop = asyncio.new_event_loop()
        try:
            future = loop.create_future()
            p._pending_futures[42] = future
            response = make_response(42)

            result = p.handle_incoming_message(response)

            assert result is True
            assert future.done()
            assert future.result() is response
        finally:
            loop.close()

    def test_returns_false_when_no_pending_future(self):
        p = TextProtocol()
        response = make_response(99)
        result = p.handle_incoming_message(response)
        assert result is False

    def test_skips_already_done_future(self):
        p = TextProtocol()
        loop = asyncio.new_event_loop()
        try:
            future = loop.create_future()
            future.set_result(None)
            p._pending_futures[42] = future
            response = make_response(42)

            result = p.handle_incoming_message(response)
            assert result is False
        finally:
            loop.close()

    def test_drop_next_response(self):
        """When _drop_next_response is True, the response is discarded and the flag cleared."""
        p = TextProtocol()
        p._drop_next_response = True
        loop = asyncio.new_event_loop()
        try:
            future = loop.create_future()
            p._pending_futures[42] = future
            response = make_response(42)

            result = p.handle_incoming_message(response)

            assert result is True
            assert p._drop_next_response is False
            # Future should NOT be resolved (response was dropped)
            assert not future.done()
        finally:
            loop.close()

    def test_response_without_id_returns_false(self):
        p = TextProtocol()
        # Build a response with no ID by bypassing pydantic (use id=0 as no-match)
        response = make_response(0)
        result = p.handle_incoming_message(response)
        assert result is False  # no pending future for 0

    @pytest.mark.asyncio
    async def test_delay_toggle_for_short_timeout_pi_get_time(self):
        """With response_timeout < 1.0, every other pi_get_time response is delayed."""
        p = TextProtocol(response_timeout=0.01)
        loop = asyncio.get_running_loop()

        # First call: toggle goes True → delayed via loop.call_later
        future1 = loop.create_future()
        p._pending_futures[1] = future1
        response1 = make_response(1, method="pi_get_time")
        p.handle_incoming_message(response1)
        assert not future1.done()  # was delayed
        assert p._delay_time_toggle is True

        # Second call: toggle goes False → resolved immediately
        future2 = loop.create_future()
        p._pending_futures[2] = future2
        response2 = make_response(2, method="pi_get_time")
        p.handle_incoming_message(response2)
        assert future2.done()  # was resolved immediately
        assert p._delay_time_toggle is False


class TestTextProtocolRecvMessage:
    @pytest.mark.asyncio
    async def test_success(self):
        p = TextProtocol()
        response = make_response(10)

        async def deliver():
            await asyncio.sleep(0.01)
            p.handle_incoming_message(response)

        asyncio.create_task(deliver())
        result = await p.recv_message(MagicMock(), 10)
        assert result is response

    @pytest.mark.asyncio
    async def test_timeout_long_raises_connection_error(self):
        """response_timeout >= 1.0 → raises ConnectionError on timeout."""
        p = TextProtocol(response_timeout=0.05)
        # Patch response_timeout to just above 1.0 for the raise-ConnectionError branch
        p.response_timeout = 1.0
        with pytest.raises(ConnectionError, match="Timeout"):
            await p.recv_message(MagicMock(), 999)

    @pytest.mark.asyncio
    async def test_timeout_short_raises_timeout_error(self):
        """response_timeout < 1.0 → re-raises TimeoutError directly."""
        p = TextProtocol(response_timeout=0.01)
        with pytest.raises(asyncio.TimeoutError):
            await p.recv_message(MagicMock(), 888)

    @pytest.mark.asyncio
    async def test_cleans_up_future_on_timeout(self):
        p = TextProtocol(response_timeout=0.01)
        try:
            await p.recv_message(MagicMock(), 77)
        except (asyncio.TimeoutError, ConnectionError):
            pass
        assert 77 not in p._pending_futures

    @pytest.mark.asyncio
    async def test_cleans_up_future_on_success(self):
        p = TextProtocol()
        response = make_response(55)

        async def deliver():
            await asyncio.sleep(0.01)
            p.handle_incoming_message(response)

        asyncio.create_task(deliver())
        await p.recv_message(MagicMock(), 55)
        assert 55 not in p._pending_futures


class TestTextProtocolResolveAnyPendingAsNone:
    def test_resolves_first_pending(self):
        p = TextProtocol()
        loop = asyncio.new_event_loop()
        try:
            f = loop.create_future()
            p._pending_futures[1] = f

            result = p.resolve_any_pending_as_none()

            assert result is True
            assert f.done()
            assert f.result() is None
        finally:
            loop.close()

    def test_returns_false_when_no_pending(self):
        p = TextProtocol()
        assert p.resolve_any_pending_as_none() is False

    def test_skips_done_futures(self):
        p = TextProtocol()
        loop = asyncio.new_event_loop()
        try:
            done_future = loop.create_future()
            done_future.set_result("already done")
            p._pending_futures[1] = done_future

            result = p.resolve_any_pending_as_none()
            # All futures are already done, so returns False
            assert result is False
        finally:
            loop.close()

    def test_future_remains_in_dict_after_resolve(self):
        """Confirm current behavior: resolved future stays in _pending_futures.

        This is a known limitation - recv_message cleans up its own future
        in its finally block, but callers of resolve_any_pending_as_none
        directly must be aware the dict is not cleaned up.
        """
        p = TextProtocol()
        loop = asyncio.new_event_loop()
        try:
            f = loop.create_future()
            p._pending_futures[1] = f
            p.resolve_any_pending_as_none()
            # Future is still in the dict after resolution
            assert 1 in p._pending_futures
        finally:
            loop.close()


class TestTextProtocolNoteReadDrop:
    def test_sets_drop_flag(self):
        p = TextProtocol()
        assert p._drop_next_response is False
        p.note_read_drop()
        assert p._drop_next_response is True

    def test_calling_twice_stays_true(self):
        p = TextProtocol()
        p.note_read_drop()
        p.note_read_drop()
        assert p._drop_next_response is True


# ---------------------------------------------------------------------------
# BinaryProtocol
# ---------------------------------------------------------------------------

def make_binary_header(size: int, msg_id: int, width: int, height: int) -> bytes:
    """Build a 21-byte binary header matching the parse_header format '>HHHIHHBBHH'."""
    # Format ">HHHIHHBBHH" = 2+2+2+4+2+2+1+1+2+2 = 20 bytes
    fmt = ">HHHIHHBBHH"
    header = pack(fmt, 0, 0, 0, size, 0, 0, 0, msg_id, width, height)
    # parse_header requires len > 20, so pad to 21
    return header + b"\x00"


class TestBinaryProtocolParseHeader:
    def test_valid_header(self):
        p = BinaryProtocol()
        header = make_binary_header(size=50000, msg_id=21, width=1920, height=1080)
        size, msg_id, width, height = p.parse_header(header)
        assert size == 50000
        assert msg_id == 21
        assert width == 1920
        assert height == 1080

    def test_header_exactly_20_bytes_returns_zeros(self):
        """Header must be > 20 bytes; exactly 20 returns zero sentinel."""
        p = BinaryProtocol()
        header = b"\x00" * 20
        size, msg_id, width, height = p.parse_header(header)
        assert size == 0
        assert msg_id is None

    def test_header_too_short_returns_zeros(self):
        p = BinaryProtocol()
        header = b"\x00" * 5
        size, msg_id, width, height = p.parse_header(header)
        assert size == 0
        assert msg_id is None

    def test_header_none_raises_type_error(self):
        """beartype enforces the bytes type hint: None is rejected at the call site."""
        import beartype.roar
        p = BinaryProtocol()
        with pytest.raises(beartype.roar.BeartypeException):
            p.parse_header(None)

    def test_header_21_bytes(self):
        """Boundary: exactly 21 bytes should parse successfully."""
        p = BinaryProtocol()
        header = make_binary_header(size=100, msg_id=23, width=1080, height=1920)
        assert len(header) == 21
        size, msg_id, width, height = p.parse_header(header)
        assert size == 100
        assert msg_id == 23


class TestBinaryProtocolHandleIncoming:
    @pytest.mark.asyncio
    async def test_preview_frame_id_21(self):
        p = BinaryProtocol()
        w, h = 4, 4
        raw = bytes([0] * (w * h * 2))  # 2 bytes/pixel bayer
        result = await p.handle_incoming_message(w, h, raw, id=21)
        assert isinstance(result, ScopeImage)
        assert result.width == w
        assert result.height == h

    @pytest.mark.asyncio
    async def test_stack_id_23(self):
        p = BinaryProtocol()
        w, h = 4, 4
        raw_img = bytes(w * h * 2)

        # Build a valid zip with 'raw_data' entry
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("raw_data", raw_img)
        zip_bytes = buf.getvalue()

        result = await p.handle_incoming_message(w, h, zip_bytes, id=23)
        assert isinstance(result, ScopeImage)

    @pytest.mark.asyncio
    async def test_unknown_id_returns_scope_image_no_image(self):
        p = BinaryProtocol()
        data = b"some data"
        result = await p.handle_incoming_message(10, 10, data, id=99)
        assert isinstance(result, ScopeImage)
        assert result.image is None

    @pytest.mark.asyncio
    async def test_stack_invalid_zip_returns_empty_scope_image(self):
        p = BinaryProtocol()
        result = await p.handle_incoming_message(100, 100, b"not a zip", id=23)
        assert isinstance(result, ScopeImage)
        assert result.image is None


class TestBinaryProtocolConvertStarImage:
    def test_6_bytes_per_pixel(self):
        p = BinaryProtocol()
        w, h = 4, 4
        raw = bytes(w * h * 6)
        img = p._convert_star_image(raw, w, h)
        assert img is not None
        assert img.shape == (h, w, 3)

    def test_2_bytes_per_pixel_bayer(self):
        p = BinaryProtocol()
        w, h = 4, 4
        raw = bytes(w * h * 2)
        img = p._convert_star_image(raw, w, h)
        assert img is not None

    def test_wrong_size_returns_none(self):
        p = BinaryProtocol()
        raw = bytes(10)  # garbage size
        img = p._convert_star_image(raw, 100, 100)
        assert img is None

    def test_uses_default_dimensions_when_zero(self):
        """Width/height of 0 should fall back to defaults (1080x1920)."""
        p = BinaryProtocol()
        w, h = 1080, 1920
        raw = bytes(w * h * 2)
        # Pass width=0, height=0 - defaults are used
        img = p._convert_star_image(raw, 0, 0)
        assert img is not None


class TestBinaryProtocolHandleStack:
    def test_valid_zip_returns_scope_image(self):
        p = BinaryProtocol()
        w, h = 4, 4
        raw_img = bytes(w * h * 2)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("raw_data", raw_img)
        zip_bytes = buf.getvalue()

        result = p._handle_stack(w, h, zip_bytes)
        assert isinstance(result, ScopeImage)

    def test_invalid_zip_returns_empty_scope_image(self):
        p = BinaryProtocol()
        result = p._handle_stack(100, 100, b"not-a-zip")
        assert isinstance(result, ScopeImage)
        assert result.data is None
        assert result.image is None

    def test_zip_missing_raw_data_key(self):
        p = BinaryProtocol()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("other_file.txt", b"hello")
        zip_bytes = buf.getvalue()

        result = p._handle_stack(100, 100, zip_bytes)
        # KeyError on 'raw_data' - should be caught and return empty ScopeImage
        assert isinstance(result, ScopeImage)
        assert result.image is None


class TestScopeImage:
    def test_default_fields(self):
        img = ScopeImage()
        assert img.width is None
        assert img.height is None
        assert img.data is None
        assert img.image is None

    def test_with_numpy_image(self):
        arr = np.zeros((10, 10, 3), dtype=np.uint8)
        img = ScopeImage(width=10, height=10, image=arr)
        assert img.width == 10
        assert img.height == 10
        assert img.image is not None
