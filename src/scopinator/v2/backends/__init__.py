"""V2 Backend implementations.

This module provides backend implementations for different telescope
control protocols:

- **Seestar**: Native protocol for ZWO Seestar smart telescopes
- **Alpaca**: ASCOM Alpaca HTTP REST API for Windows ASCOM devices
- **INDI**: INDI protocol via pyindi-client for Linux/macOS

Each backend implements the abstract Backend interface and provides
concrete implementations of the device interfaces (Mount, Camera, etc.).
"""

from scopinator.v2.backends.base import Backend, BackendInfo

__all__ = [
    "Backend",
    "BackendInfo",
]
