"""Tests for V2 core types."""

import pytest
from datetime import datetime

from scopinator.v2.core.types import (
    Coordinates,
    AltAzCoordinates,
    TrackingRate,
    SlewState,
    PierSide,
    CameraState,
    ExposureSettings,
    ImageData,
    FilterPosition,
    FocuserPosition,
)


class TestCoordinates:
    """Tests for Coordinates type."""

    def test_create_coordinates(self):
        """Test creating valid coordinates."""
        coords = Coordinates(ra=10.5, dec=45.0)
        assert coords.ra == 10.5
        assert coords.dec == 45.0
        assert coords.epoch == "J2000"

    def test_ra_validation(self):
        """Test RA validation (0-360 degrees)."""
        # Valid RA
        coords = Coordinates(ra=0.0, dec=0.0)
        assert coords.ra == 0.0

        coords = Coordinates(ra=359.99, dec=0.0)
        assert coords.ra == 359.99

        # Invalid RA
        with pytest.raises(ValueError):
            Coordinates(ra=-1.0, dec=0.0)

        with pytest.raises(ValueError):
            Coordinates(ra=360.0, dec=0.0)

    def test_dec_validation(self):
        """Test Dec validation (-90 to 90 degrees)."""
        # Valid Dec
        coords = Coordinates(ra=0.0, dec=-90.0)
        assert coords.dec == -90.0

        coords = Coordinates(ra=0.0, dec=90.0)
        assert coords.dec == 90.0

        # Invalid Dec
        with pytest.raises(ValueError):
            Coordinates(ra=0.0, dec=-91.0)

        with pytest.raises(ValueError):
            Coordinates(ra=0.0, dec=91.0)

    def test_from_hours(self):
        """Test creating coordinates from RA hours."""
        coords = Coordinates.from_hours(ra_hours=6.0, dec=45.0)
        assert coords.ra == 90.0  # 6 hours * 15 = 90 degrees
        assert coords.dec == 45.0

    def test_ra_hours_property(self):
        """Test RA hours property."""
        coords = Coordinates(ra=90.0, dec=45.0)
        assert coords.ra_hours == 6.0

    def test_str_representation(self):
        """Test string representation."""
        coords = Coordinates(ra=90.0, dec=45.0)
        s = str(coords)
        assert "RA" in s
        assert "Dec" in s


class TestAltAzCoordinates:
    """Tests for AltAzCoordinates type."""

    def test_create_altaz(self):
        """Test creating valid alt/az coordinates."""
        coords = AltAzCoordinates(altitude=45.0, azimuth=180.0)
        assert coords.altitude == 45.0
        assert coords.azimuth == 180.0

    def test_altitude_validation(self):
        """Test altitude validation (-90 to 90)."""
        with pytest.raises(ValueError):
            AltAzCoordinates(altitude=-91.0, azimuth=0.0)

        with pytest.raises(ValueError):
            AltAzCoordinates(altitude=91.0, azimuth=0.0)

    def test_azimuth_validation(self):
        """Test azimuth validation (0 to 360)."""
        # Valid range is 0 to <360
        coords = AltAzCoordinates(altitude=0.0, azimuth=0.0)
        assert coords.azimuth == 0.0

        coords = AltAzCoordinates(altitude=0.0, azimuth=359.99)
        assert coords.azimuth == 359.99

        with pytest.raises(ValueError):
            AltAzCoordinates(altitude=0.0, azimuth=-1.0)

        with pytest.raises(ValueError):
            AltAzCoordinates(altitude=0.0, azimuth=360.0)


class TestTrackingRate:
    """Tests for TrackingRate enum."""

    def test_tracking_rates(self):
        """Test tracking rate values."""
        assert TrackingRate.SIDEREAL.value == "sidereal"
        assert TrackingRate.LUNAR.value == "lunar"
        assert TrackingRate.SOLAR.value == "solar"
        assert TrackingRate.KING.value == "king"
        assert TrackingRate.OFF.value == "off"


class TestSlewState:
    """Tests for SlewState enum."""

    def test_slew_states(self):
        """Test slew state values."""
        assert SlewState.IDLE.value == "idle"
        assert SlewState.SLEWING.value == "slewing"
        assert SlewState.TRACKING.value == "tracking"
        assert SlewState.PARKED.value == "parked"
        assert SlewState.ERROR.value == "error"


class TestPierSide:
    """Tests for PierSide enum."""

    def test_pier_sides(self):
        """Test pier side values."""
        assert PierSide.EAST.value == "east"
        assert PierSide.WEST.value == "west"
        assert PierSide.UNKNOWN.value == "unknown"


class TestCameraState:
    """Tests for CameraState enum."""

    def test_camera_states(self):
        """Test camera state values."""
        assert CameraState.IDLE.value == "idle"
        assert CameraState.EXPOSING.value == "exposing"
        assert CameraState.READING.value == "reading"
        assert CameraState.ERROR.value == "error"


class TestExposureSettings:
    """Tests for ExposureSettings type."""

    def test_create_exposure_settings(self):
        """Test creating exposure settings."""
        settings = ExposureSettings(duration_seconds=30.0)
        assert settings.duration_seconds == 30.0
        assert settings.gain is None
        assert settings.bin_x == 1
        assert settings.bin_y == 1

    def test_with_all_options(self):
        """Test exposure settings with all options."""
        settings = ExposureSettings(
            duration_seconds=120.0,
            gain=200,
            offset=10,
            bin_x=2,
            bin_y=2,
            subframe=(0, 0, 1920, 1080),
        )
        assert settings.duration_seconds == 120.0
        assert settings.gain == 200
        assert settings.offset == 10
        assert settings.bin_x == 2
        assert settings.bin_y == 2
        assert settings.subframe == (0, 0, 1920, 1080)

    def test_duration_validation(self):
        """Test duration must be positive."""
        with pytest.raises(ValueError):
            ExposureSettings(duration_seconds=-1.0)

        with pytest.raises(ValueError):
            ExposureSettings(duration_seconds=0.0)


class TestImageData:
    """Tests for ImageData type."""

    def test_create_image_data(self):
        """Test creating image data."""
        data = b"\x00" * 1000
        img = ImageData(
            data=data,
            width=100,
            height=10,
        )
        assert len(img.data) == 1000
        assert img.width == 100
        assert img.height == 10
        assert img.bit_depth == 16  # default

    def test_with_metadata(self):
        """Test image data with metadata."""
        img = ImageData(
            data=b"\x00",
            width=1,
            height=1,
            bit_depth=16,
            is_color=True,
            bayer_pattern="RGGB",
            metadata={"exposure": 30.0, "gain": 100},
        )
        assert img.bit_depth == 16
        assert img.is_color is True
        assert img.bayer_pattern == "RGGB"
        assert img.metadata["exposure"] == 30.0


class TestFilterPosition:
    """Tests for FilterPosition type."""

    def test_create_filter_position(self):
        """Test creating filter position."""
        pos = FilterPosition(position=0, name="Luminance")
        assert pos.position == 0
        assert pos.name == "Luminance"

    def test_without_name(self):
        """Test filter position without name."""
        pos = FilterPosition(position=3)
        assert pos.position == 3
        assert pos.name is None


class TestFocuserPosition:
    """Tests for FocuserPosition type."""

    def test_create_focuser_position(self):
        """Test creating focuser position."""
        pos = FocuserPosition(position=5000, max_position=10000)
        assert pos.position == 5000
        assert pos.max_position == 10000
        assert pos.temperature is None

    def test_with_temperature(self):
        """Test focuser position with temperature."""
        pos = FocuserPosition(
            position=5000,
            max_position=10000,
            temperature=15.5,
        )
        assert pos.temperature == 15.5

    def test_position_percent(self):
        """Test position percentage calculation."""
        pos = FocuserPosition(position=5000, max_position=10000)
        assert pos.position_percent == 50.0

    def test_is_moving(self):
        """Test is_moving flag."""
        pos = FocuserPosition(position=5000, max_position=10000, is_moving=True)
        assert pos.is_moving is True
