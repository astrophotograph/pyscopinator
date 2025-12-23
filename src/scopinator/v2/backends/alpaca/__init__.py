"""ASCOM Alpaca backend - HTTP REST client for ASCOM devices.

ASCOM Alpaca is the cross-platform HTTP REST API for controlling
astronomy equipment that was traditionally only accessible on Windows
via COM interfaces.

See: https://ascom-standards.org/Developer/Alpaca.htm
"""

from scopinator.v2.backends.alpaca.backend import AlpacaBackend
from scopinator.v2.backends.alpaca.camera import AlpacaCamera
from scopinator.v2.backends.alpaca.filterwheel import AlpacaFilterWheel
from scopinator.v2.backends.alpaca.focuser import AlpacaFocuser
from scopinator.v2.backends.alpaca.mount import AlpacaMount

__all__ = [
    "AlpacaBackend",
    "AlpacaCamera",
    "AlpacaFilterWheel",
    "AlpacaFocuser",
    "AlpacaMount",
]
