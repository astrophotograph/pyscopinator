"""INDI backend - pyindi-client wrapper for INDI protocol support.

INDI (Instrument-Neutral Distributed Interface) is an open protocol
for controlling astronomy equipment, primarily used on Linux and macOS.

This backend requires the pyindi-client package:
    pip install pyindi-client

See: https://indilib.org/
"""

try:
    from scopinator.v2.backends.indi.backend import INDIBackend
    from scopinator.v2.backends.indi.mount import INDIMount
    from scopinator.v2.backends.indi.camera import INDICamera

    INDI_AVAILABLE = True
    __all__ = [
        "INDIBackend",
        "INDIMount",
        "INDICamera",
        "INDI_AVAILABLE",
    ]
except ImportError:
    INDI_AVAILABLE = False
    __all__ = ["INDI_AVAILABLE"]
