"""V2-specific exceptions."""


class V2Error(Exception):
    """Base exception for V2 module."""

    pass


class ConnectionError(V2Error):
    """Connection-related errors."""

    pass


class DeviceError(V2Error):
    """Device operation errors."""

    pass


class BackendError(V2Error):
    """Backend-related errors."""

    pass


class TimeoutError(V2Error):
    """Operation timeout errors."""

    pass


class NotConnectedError(V2Error):
    """Operation attempted on disconnected device."""

    pass


class NotSupportedError(V2Error):
    """Operation not supported by this device/backend."""

    pass


class CommandError(V2Error):
    """Command execution failed."""

    def __init__(self, message: str, code: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}
