"""Tests for AstronomyProfile."""

import pytest
import tempfile
import json
from pathlib import Path

from scopinator.profile import AstronomyProfile, ProfileState
from scopinator.profile.astronomy_profile import (
    IntegratedDevice,
    SeestarDevice,
)


class TestIntegratedDevice:
    """Tests for IntegratedDevice model."""

    def test_create_integrated_device(self):
        """Test creating an integrated device."""
        device = IntegratedDevice(
            name="Test Device",
            host="192.168.1.100",
            port=4700,
        )
        assert device.name == "Test Device"
        assert device.host == "192.168.1.100"
        assert device.port == 4700
        assert device.device_type == "integrated"

    def test_default_provides(self):
        """Test default provides list."""
        device = IntegratedDevice(name="Test")
        assert "mount" in device.provides
        assert "camera" in device.provides
        assert "optics" in device.provides


class TestSeestarDevice:
    """Tests for SeestarDevice model."""

    def test_create_seestar_device(self):
        """Test creating a Seestar device."""
        device = SeestarDevice(
            name="My Seestar",
            host="192.168.1.50",
        )
        assert device.name == "My Seestar"
        assert device.host == "192.168.1.50"
        assert device.port == 4700  # Default
        assert device.imaging_port == 4800  # Default
        assert device.device_type == "seestar"
        assert device.manufacturer == "ZWO"
        assert device.model == "Seestar S50"

    def test_seestar_specs(self):
        """Test Seestar default specs."""
        device = SeestarDevice(name="Test")
        assert device.aperture_mm == 50.0
        assert device.focal_length_mm == 250.0
        assert device.has_lp_filter is True

    def test_seestar_provides(self):
        """Test Seestar provides list includes focuser."""
        device = SeestarDevice(name="Test")
        assert "mount" in device.provides
        assert "camera" in device.provides
        assert "optics" in device.provides
        assert "focuser" in device.provides


class TestAstronomyProfile:
    """Tests for AstronomyProfile."""

    def test_create_profile(self):
        """Test creating a basic profile."""
        profile = AstronomyProfile(name="Test Profile")
        assert profile.name == "Test Profile"
        assert profile.state == ProfileState.IDLE
        assert profile.version == "1.0"

    def test_profile_with_device(self):
        """Test profile with integrated device."""
        device = SeestarDevice(name="Seestar", host="192.168.1.50")
        profile = AstronomyProfile(
            name="My Scope",
            integrated_device=device,
        )
        assert profile.integrated_device is not None
        assert profile.integrated_device.host == "192.168.1.50"

    def test_profile_with_location(self):
        """Test profile with observer location."""
        profile = AstronomyProfile(
            name="Home Setup",
            latitude=40.7128,
            longitude=-74.0060,
            elevation_m=10.0,
            timezone="America/New_York",
        )
        assert profile.latitude == 40.7128
        assert profile.longitude == -74.0060
        assert profile.elevation_m == 10.0
        assert profile.timezone == "America/New_York"

    def test_latitude_validation(self):
        """Test latitude must be -90 to 90."""
        with pytest.raises(ValueError):
            AstronomyProfile(name="Test", latitude=91.0)

        with pytest.raises(ValueError):
            AstronomyProfile(name="Test", latitude=-91.0)

    def test_longitude_validation(self):
        """Test longitude must be -180 to 180."""
        with pytest.raises(ValueError):
            AstronomyProfile(name="Test", longitude=181.0)

        with pytest.raises(ValueError):
            AstronomyProfile(name="Test", longitude=-181.0)


class TestProfileSerialization:
    """Tests for profile save/load."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_save_load_json(self, temp_dir):
        """Test saving and loading JSON profile."""
        device = SeestarDevice(name="Seestar", host="192.168.1.50")
        profile = AstronomyProfile(
            name="Test Profile",
            description="A test profile",
            integrated_device=device,
            latitude=40.0,
            longitude=-74.0,
        )

        path = temp_dir / "test_profile.json"
        profile.save(path)

        # Verify file exists
        assert path.exists()

        # Load and verify
        loaded = AstronomyProfile.load(path)
        assert loaded.name == "Test Profile"
        assert loaded.description == "A test profile"
        assert loaded.integrated_device is not None
        assert loaded.integrated_device.host == "192.168.1.50"
        assert loaded.latitude == 40.0
        assert loaded.longitude == -74.0

    def test_save_load_yaml(self, temp_dir):
        """Test saving and loading YAML profile."""
        pytest.importorskip("yaml")

        device = SeestarDevice(name="Seestar", host="192.168.1.100")
        profile = AstronomyProfile(
            name="YAML Profile",
            integrated_device=device,
        )

        path = temp_dir / "test_profile.yaml"
        profile.save(path)

        assert path.exists()

        loaded = AstronomyProfile.load(path)
        assert loaded.name == "YAML Profile"
        assert loaded.integrated_device.host == "192.168.1.100"

    def test_load_preserves_device_type(self, temp_dir):
        """Test that loading preserves the correct device type."""
        device = SeestarDevice(name="Seestar", host="192.168.1.50")
        profile = AstronomyProfile(
            name="Seestar Profile",
            integrated_device=device,
        )

        path = temp_dir / "seestar.json"
        profile.save(path)

        loaded = AstronomyProfile.load(path)
        # Should be deserialized as SeestarDevice, not generic IntegratedDevice
        assert loaded.integrated_device.device_type == "seestar"
        assert hasattr(loaded.integrated_device, "aperture_mm")

    def test_json_format(self, temp_dir):
        """Test JSON file format is valid."""
        profile = AstronomyProfile(
            name="JSON Test",
            integrated_device=SeestarDevice(name="Seestar", host="192.168.1.1"),
        )

        path = temp_dir / "format_test.json"
        profile.save(path)

        # Read raw JSON and verify structure
        with open(path) as f:
            data = json.load(f)

        assert data["name"] == "JSON Test"
        assert "integrated_device" in data
        assert data["integrated_device"]["device_type"] == "seestar"
        # State should NOT be persisted
        assert "state" not in data


class TestProfileState:
    """Tests for ProfileState enum."""

    def test_state_values(self):
        """Test all profile states exist."""
        assert ProfileState.IDLE.value == "idle"
        assert ProfileState.CONNECTING.value == "connecting"
        assert ProfileState.CONNECTED.value == "connected"
        assert ProfileState.IMAGING.value == "imaging"
        assert ProfileState.SLEWING.value == "slewing"
        assert ProfileState.ERROR.value == "error"
        assert ProfileState.DISCONNECTED.value == "disconnected"


class TestProfileRepr:
    """Tests for profile representation."""

    def test_repr(self):
        """Test profile string representation."""
        profile = AstronomyProfile(name="My Scope")
        repr_str = repr(profile)
        assert "AstronomyProfile" in repr_str
        assert "My Scope" in repr_str
        assert "idle" in repr_str
