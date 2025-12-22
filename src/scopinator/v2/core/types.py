"""Common types for V2 abstraction layer."""

from enum import Enum
from typing import Any, Optional

import numpy.typing as npt
from pydantic import BaseModel, Field


class Coordinates(BaseModel):
    """Equatorial coordinates.

    RA and Dec are stored in degrees for consistency across protocols.
    Use the convenience methods to convert to/from hours.
    """

    ra: float = Field(..., ge=0, lt=360, description="Right Ascension in degrees")
    dec: float = Field(..., ge=-90, le=90, description="Declination in degrees")
    epoch: str = Field(default="J2000", description="Coordinate epoch")

    @property
    def ra_hours(self) -> float:
        """Get RA in hours (0-24)."""
        return self.ra / 15.0

    @classmethod
    def from_hours(cls, ra_hours: float, dec: float, epoch: str = "J2000") -> "Coordinates":
        """Create coordinates from RA in hours."""
        return cls(ra=ra_hours * 15.0, dec=dec, epoch=epoch)

    def __str__(self) -> str:
        return f"RA: {self.ra_hours:.4f}h, Dec: {self.dec:.4f}° ({self.epoch})"


class AltAzCoordinates(BaseModel):
    """Horizontal (altitude-azimuth) coordinates."""

    altitude: float = Field(..., ge=-90, le=90, description="Altitude in degrees")
    azimuth: float = Field(..., ge=0, lt=360, description="Azimuth in degrees (N=0, E=90)")

    def __str__(self) -> str:
        return f"Alt: {self.altitude:.2f}°, Az: {self.azimuth:.2f}°"


class TrackingRate(str, Enum):
    """Standard tracking rates."""

    SIDEREAL = "sidereal"
    LUNAR = "lunar"
    SOLAR = "solar"
    KING = "king"
    CUSTOM = "custom"
    OFF = "off"


class PierSide(str, Enum):
    """German equatorial mount pier side."""

    EAST = "east"
    WEST = "west"
    UNKNOWN = "unknown"


class SlewState(str, Enum):
    """Mount slew state."""

    IDLE = "idle"
    SLEWING = "slewing"
    TRACKING = "tracking"
    PARKED = "parked"
    HOMING = "homing"
    ERROR = "error"


class CameraState(str, Enum):
    """Camera state."""

    IDLE = "idle"
    WAITING = "waiting"
    EXPOSING = "exposing"
    READING = "reading"
    DOWNLOADING = "downloading"
    ERROR = "error"


class ExposureSettings(BaseModel):
    """Camera exposure settings."""

    duration_seconds: float = Field(..., gt=0, description="Exposure duration in seconds")
    gain: Optional[int] = Field(None, ge=0, description="Camera gain")
    offset: Optional[int] = Field(None, ge=0, description="Camera offset/brightness")
    bin_x: int = Field(default=1, ge=1, description="Horizontal binning")
    bin_y: int = Field(default=1, ge=1, description="Vertical binning")
    subframe: Optional[tuple[int, int, int, int]] = Field(
        None, description="Subframe region (x, y, width, height)"
    )
    light: bool = Field(default=True, description="True for light frame, False for dark")

    model_config = {"frozen": False}


class ImageData(BaseModel):
    """Container for image data."""

    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    data: bytes = Field(..., description="Raw image bytes")
    bit_depth: int = Field(default=16, description="Bits per pixel")
    is_color: bool = Field(default=False, description="True if color (RGB/Bayer)")
    bayer_pattern: Optional[str] = Field(None, description="Bayer pattern if applicable")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    # numpy array is stored separately (not serialized)
    _array: Optional[npt.NDArray[Any]] = None

    model_config = {"arbitrary_types_allowed": True}

    @property
    def array(self) -> Optional[npt.NDArray[Any]]:
        """Get image as numpy array if available."""
        return self._array

    @array.setter
    def array(self, value: npt.NDArray[Any]) -> None:
        """Set numpy array."""
        self._array = value


class FilterPosition(BaseModel):
    """Filter wheel position."""

    position: int = Field(..., ge=0, description="Filter slot number (0-indexed)")
    name: Optional[str] = Field(None, description="Filter name")


class FocuserPosition(BaseModel):
    """Focuser position and status."""

    position: int = Field(..., ge=0, description="Current position in steps")
    max_position: int = Field(..., ge=1, description="Maximum position in steps")
    temperature: Optional[float] = Field(None, description="Focuser temperature in Celsius")
    is_moving: bool = Field(default=False, description="True if currently moving")

    @property
    def position_percent(self) -> float:
        """Get position as percentage of travel."""
        return (self.position / self.max_position) * 100.0
