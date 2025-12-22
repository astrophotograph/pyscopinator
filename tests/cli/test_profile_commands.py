"""Tests for CLI profile commands."""

import pytest
import tempfile
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from click.testing import CliRunner

from scopinator.cli.main import cli


@pytest.fixture
def runner():
    """Create a CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_profiles_dir(tmp_path):
    """Create a temporary profiles directory."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    return profiles_dir


class TestProfileCommands:
    """Tests for profile commands."""

    def test_profile_help(self, runner):
        """Test profile help command."""
        result = runner.invoke(cli, ["profile", "--help"])
        assert result.exit_code == 0
        assert "Manage telescope profiles" in result.output

    def test_profile_list_help(self, runner):
        """Test profile list help."""
        result = runner.invoke(cli, ["profile", "list", "--help"])
        assert result.exit_code == 0
        assert "List all saved profiles" in result.output

    def test_profile_create_help(self, runner):
        """Test profile create help."""
        result = runner.invoke(cli, ["profile", "create", "--help"])
        assert result.exit_code == 0
        assert "--name" in result.output
        assert "--host" in result.output
        assert "--protocol" in result.output

    def test_profile_show_help(self, runner):
        """Test profile show help."""
        result = runner.invoke(cli, ["profile", "show", "--help"])
        assert result.exit_code == 0
        assert "NAME" in result.output

    def test_profile_delete_help(self, runner):
        """Test profile delete help."""
        result = runner.invoke(cli, ["profile", "delete", "--help"])
        assert result.exit_code == 0
        assert "--force" in result.output

    def test_profile_discover_help(self, runner):
        """Test profile discover help."""
        result = runner.invoke(cli, ["profile", "discover", "--help"])
        assert result.exit_code == 0
        assert "--timeout" in result.output

    def test_profile_use_help(self, runner):
        """Test profile use help."""
        result = runner.invoke(cli, ["profile", "use", "--help"])
        assert result.exit_code == 0
        assert "Set a profile as the default" in result.output

    def test_profile_test_help(self, runner):
        """Test profile test help."""
        result = runner.invoke(cli, ["profile", "test", "--help"])
        assert result.exit_code == 0
        assert "Test connection" in result.output


class TestProfileListCommand:
    """Tests for profile list command."""

    def test_list_no_profiles(self, runner, temp_profiles_dir):
        """Test listing with no profiles."""
        with patch('scopinator.cli.commands.profile.PROFILES_DIR', temp_profiles_dir):
            result = runner.invoke(cli, ["profile", "list"])
            assert result.exit_code == 0
            assert "No profiles found" in result.output

    def test_list_with_profiles(self, runner, temp_profiles_dir):
        """Test listing with profiles."""
        # Create a valid profile
        from scopinator.profile import AstronomyProfile
        from scopinator.profile.astronomy_profile import SeestarDevice

        profile = AstronomyProfile(
            name="Test Profile",
            integrated_device=SeestarDevice(name="Seestar", host="192.168.1.1"),
        )
        profile.save(temp_profiles_dir / "test.json")

        with patch('scopinator.cli.commands.profile.PROFILES_DIR', temp_profiles_dir):
            result = runner.invoke(cli, ["profile", "list"])
            assert result.exit_code == 0
            # Should show the profile
            assert "test" in result.output.lower() or "1 profile" in result.output.lower()


class TestProfileCreateCommand:
    """Tests for profile create command."""

    def test_create_seestar_profile(self, runner, temp_profiles_dir):
        """Test creating a Seestar profile."""
        with patch('scopinator.cli.commands.profile.PROFILES_DIR', temp_profiles_dir):
            result = runner.invoke(cli, [
                "profile", "create",
                "-n", "myseestar",
                "-P", "seestar",
                "-h", "192.168.1.50",
            ])
            assert result.exit_code == 0
            assert "created successfully" in result.output

            # Verify file was created
            profile_path = temp_profiles_dir / "myseestar.json"
            assert profile_path.exists()

    def test_create_with_location(self, runner, temp_profiles_dir):
        """Test creating profile with location."""
        with patch('scopinator.cli.commands.profile.PROFILES_DIR', temp_profiles_dir):
            result = runner.invoke(cli, [
                "profile", "create",
                "-n", "withlocation",
                "-P", "seestar",
                "-h", "192.168.1.50",
                "--latitude", "40.7128",
                "--longitude", "-74.0060",
                "--elevation", "10",
            ])
            assert result.exit_code == 0

            # Verify location was saved
            from scopinator.profile import AstronomyProfile
            profile = AstronomyProfile.load(temp_profiles_dir / "withlocation.json")
            assert profile.latitude == 40.7128
            assert profile.longitude == -74.0060


class TestProfileShowCommand:
    """Tests for profile show command."""

    def test_show_not_found(self, runner, temp_profiles_dir):
        """Test showing non-existent profile."""
        with patch('scopinator.cli.commands.profile.PROFILES_DIR', temp_profiles_dir):
            result = runner.invoke(cli, ["profile", "show", "nonexistent"])
            assert result.exit_code == 0
            assert "not found" in result.output.lower()

    def test_show_profile(self, runner, temp_profiles_dir):
        """Test showing a profile."""
        from scopinator.profile import AstronomyProfile
        from scopinator.profile.astronomy_profile import SeestarDevice

        profile = AstronomyProfile(
            name="Show Test",
            description="A test profile",
            integrated_device=SeestarDevice(name="Seestar", host="192.168.1.100"),
        )
        profile.save(temp_profiles_dir / "showtest.json")

        with patch('scopinator.cli.commands.profile.PROFILES_DIR', temp_profiles_dir):
            result = runner.invoke(cli, ["profile", "show", "showtest"])
            assert result.exit_code == 0
            assert "Show Test" in result.output
            assert "192.168.1.100" in result.output


class TestProfileDeleteCommand:
    """Tests for profile delete command."""

    def test_delete_not_found(self, runner, temp_profiles_dir):
        """Test deleting non-existent profile."""
        with patch('scopinator.cli.commands.profile.PROFILES_DIR', temp_profiles_dir):
            result = runner.invoke(cli, ["profile", "delete", "nonexistent"])
            assert "not found" in result.output.lower()

    def test_delete_force(self, runner, temp_profiles_dir):
        """Test deleting with --force flag."""
        # Create a profile
        (temp_profiles_dir / "forcedelete.json").write_text('{"name": "forcedelete", "version": "1.0"}')

        with patch('scopinator.cli.commands.profile.PROFILES_DIR', temp_profiles_dir):
            result = runner.invoke(cli, ["profile", "delete", "forcedelete", "-f"])
            assert result.exit_code == 0
            assert "deleted" in result.output.lower()


class TestProfileDiscoverCommand:
    """Tests for profile discover command."""

    def test_discover_no_devices(self, runner):
        """Test discovery with no devices found."""
        with patch('scopinator.profile.AstronomyProfile.discover', new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = []

            result = runner.invoke(cli, ["profile", "discover"])
            assert result.exit_code == 0
            assert "No devices found" in result.output

    def test_discover_with_devices(self, runner):
        """Test discovery with devices found."""
        with patch('scopinator.profile.AstronomyProfile.discover', new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = [
                {
                    "type": "seestar",
                    "manufacturer": "ZWO",
                    "model": "Seestar S50",
                    "host": "192.168.1.100",
                    "port": 4700,
                }
            ]

            result = runner.invoke(cli, ["profile", "discover"])
            assert result.exit_code == 0
            assert "Found 1 device" in result.output
            assert "Seestar" in result.output


class TestGlobalProfileOption:
    """Tests for the global --profile option."""

    def test_profile_option_in_help(self, runner):
        """Test that --profile option appears in help."""
        result = runner.invoke(cli, ["--help"])
        assert "--profile" in result.output or "-p" in result.output

    def test_protocol_option_in_help(self, runner):
        """Test that --protocol option appears in help."""
        result = runner.invoke(cli, ["--help"])
        assert "--protocol" in result.output or "-P" in result.output


class TestProfileHelperFunctions:
    """Tests for profile helper functions imported from the module."""

    def test_ensure_profiles_dir(self, temp_profiles_dir):
        """Test ensure_profiles_dir creates directory."""
        from scopinator.cli.commands.profile import ensure_profiles_dir
        with patch('scopinator.cli.commands.profile.PROFILES_DIR', temp_profiles_dir):
            result = ensure_profiles_dir()
            assert result.exists()

    def test_get_profile_path_new(self, temp_profiles_dir):
        """Test get_profile_path for new profile."""
        from scopinator.cli.commands.profile import get_profile_path
        with patch('scopinator.cli.commands.profile.PROFILES_DIR', temp_profiles_dir):
            path = get_profile_path("test_profile")
            assert path.suffix == ".json"
            assert "test_profile" in path.name

    def test_get_profile_path_existing_json(self, temp_profiles_dir):
        """Test get_profile_path finds existing JSON file."""
        from scopinator.cli.commands.profile import get_profile_path
        # Create a JSON profile
        profile_path = temp_profiles_dir / "existing.json"
        profile_path.write_text('{"name": "existing"}')

        with patch('scopinator.cli.commands.profile.PROFILES_DIR', temp_profiles_dir):
            path = get_profile_path("existing")
            assert path == profile_path

    def test_list_profiles_empty(self, temp_profiles_dir):
        """Test list_profiles with no profiles."""
        from scopinator.cli.commands.profile import list_profiles
        with patch('scopinator.cli.commands.profile.PROFILES_DIR', temp_profiles_dir):
            profiles = list_profiles()
            assert profiles == []

    def test_list_profiles_with_profiles(self, temp_profiles_dir):
        """Test list_profiles with multiple profiles."""
        from scopinator.cli.commands.profile import list_profiles
        # Create some profiles
        (temp_profiles_dir / "profile1.json").write_text('{"name": "profile1"}')
        (temp_profiles_dir / "profile2.yaml").write_text("name: profile2")

        with patch('scopinator.cli.commands.profile.PROFILES_DIR', temp_profiles_dir):
            profiles = list_profiles()
            assert len(profiles) == 2
            names = [p[0] for p in profiles]
            assert "profile1" in names
            assert "profile2" in names
