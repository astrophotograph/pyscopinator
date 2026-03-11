"""Utilities for the project."""

from typing import NamedTuple


class RaDecTuple(NamedTuple):
    """Ra Dec tuple."""

    ra: float
    dec: float


# async def sleep_until(when):
#     """Sleep until a given time."""
#     loop = asyncio.get_running_loop()
#     end_time = loop.time() + 5.0
#     now = await when()
#     await asyncio.sleep(when() - now)
