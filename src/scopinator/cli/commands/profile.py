"""Profile management CLI commands.

Commands for creating, listing, showing, and managing telescope profiles.
Profiles store telescope configuration for easy reconnection.
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

import click

from scopinator.util.logging_config import get_logger

logger = get_logger(__name__)

# Profile storage directory
PROFILES_DIR = Path.home() / ".scopinator" / "profiles"


def ensure_profiles_dir() -> Path:
    """Ensure the profiles directory exists."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return PROFILES_DIR


def get_profile_path(name: str) -> Path:
    """Get the path for a profile by name."""
    # Support both .json and .yaml extensions
    profiles_dir = ensure_profiles_dir()

    # Check for existing profile with either extension
    for ext in (".json", ".yaml", ".yml"):
        path = profiles_dir / f"{name}{ext}"
        if path.exists():
            return path

    # Default to .json for new profiles
    return profiles_dir / f"{name}.json"


def list_profiles() -> list[tuple[str, Path]]:
    """List all saved profiles.

    Returns:
        List of (profile_name, profile_path) tuples
    """
    profiles_dir = ensure_profiles_dir()
    profiles = []

    for ext in ("*.json", "*.yaml", "*.yml"):
        for path in profiles_dir.glob(ext):
            name = path.stem
            profiles.append((name, path))

    return sorted(profiles, key=lambda x: x[0])


@click.group()
def profile():
    """Manage telescope profiles.

    Profiles store telescope configuration for easy reconnection.
    They can be created manually or from discovered devices.
    """
    pass


@profile.command("list")
def list_cmd():
    """List all saved profiles."""
    profiles = list_profiles()

    if not profiles:
        click.echo("No profiles found.")
        click.echo("\nCreate one with: scopinator profile create -n <name> ...")
        click.echo("Or discover devices: scopinator profile discover")
        return

    click.echo(f"Found {len(profiles)} profile(s):\n")

    for name, path in profiles:
        # Load profile to show summary
        try:
            from scopinator.profile import AstronomyProfile
            prof = AstronomyProfile.load(path)

            # Format device info
            if prof.integrated_device:
                device_info = f"{prof.integrated_device.manufacturer or ''} {prof.integrated_device.model or ''}".strip()
                host = prof.integrated_device.host or "unknown"
                click.echo(f"  {name}")
                click.echo(f"    Type: {device_info or 'Integrated'}")
                click.echo(f"    Host: {host}")
            else:
                click.echo(f"  {name}")
                click.echo(f"    Type: Component-based profile")

            if prof.description:
                click.echo(f"    Description: {prof.description}")
            click.echo()

        except Exception as e:
            click.echo(f"  {name}")
            click.echo(f"    Error loading profile: {e}")
            click.echo()


@profile.command("show")
@click.argument("name")
def show(name: str):
    """Show details of a specific profile."""
    path = get_profile_path(name)

    if not path.exists():
        click.echo(f"Profile '{name}' not found.")
        click.echo(f"\nAvailable profiles:")
        for pname, _ in list_profiles():
            click.echo(f"  - {pname}")
        return

    try:
        from scopinator.profile import AstronomyProfile
        prof = AstronomyProfile.load(path)

        click.echo(f"Profile: {prof.name}")
        click.echo(f"Version: {prof.version}")
        if prof.description:
            click.echo(f"Description: {prof.description}")
        click.echo()

        if prof.integrated_device:
            click.echo("Integrated Device:")
            dev = prof.integrated_device
            click.echo(f"  Type: {dev.device_type}")
            click.echo(f"  Manufacturer: {dev.manufacturer or 'N/A'}")
            click.echo(f"  Model: {dev.model or 'N/A'}")
            click.echo(f"  Host: {dev.host or 'N/A'}")
            click.echo(f"  Port: {dev.port}")
            if hasattr(dev, 'imaging_port') and dev.imaging_port:
                click.echo(f"  Imaging Port: {dev.imaging_port}")
            click.echo(f"  Provides: {', '.join(dev.provides)}")

            # Show additional specs for Seestar
            if hasattr(dev, 'aperture_mm'):
                click.echo(f"  Aperture: {dev.aperture_mm}mm")
            if hasattr(dev, 'focal_length_mm'):
                click.echo(f"  Focal Length: {dev.focal_length_mm}mm")

        click.echo()

        if prof.latitude is not None:
            click.echo("Observer Location:")
            click.echo(f"  Latitude: {prof.latitude}")
            click.echo(f"  Longitude: {prof.longitude}")
            if prof.elevation_m:
                click.echo(f"  Elevation: {prof.elevation_m}m")
            if prof.timezone:
                click.echo(f"  Timezone: {prof.timezone}")

        click.echo(f"\nFile: {path}")

    except Exception as e:
        click.echo(f"Error loading profile: {e}")


@profile.command("create")
@click.option("--name", "-n", required=True, help="Profile name")
@click.option("--protocol", "-P", type=click.Choice(["seestar", "alpaca", "indi"]),
              default="seestar", help="Protocol to use")
@click.option("--host", "-h", required=True, help="Device host address")
@click.option("--port", "-p", type=int, help="Device port (uses protocol default if not specified)")
@click.option("--description", "-d", help="Profile description")
@click.option("--latitude", type=float, help="Observer latitude (-90 to 90)")
@click.option("--longitude", type=float, help="Observer longitude (-180 to 180)")
@click.option("--elevation", type=float, help="Observer elevation in meters")
@click.option("--format", "-f", type=click.Choice(["json", "yaml"]), default="json",
              help="Output format")
def create(name: str, protocol: str, host: str, port: Optional[int],
           description: Optional[str], latitude: Optional[float],
           longitude: Optional[float], elevation: Optional[float], format: str):
    """Create a new profile manually."""
    from scopinator.profile import AstronomyProfile
    from scopinator.profile.astronomy_profile import SeestarDevice, IntegratedDevice

    # Check if profile already exists
    existing_path = get_profile_path(name)
    if existing_path.exists():
        if not click.confirm(f"Profile '{name}' already exists. Overwrite?"):
            click.echo("Cancelled.")
            return

    # Create profile based on protocol
    if protocol == "seestar":
        device = SeestarDevice(
            name="Seestar S50",
            host=host,
            port=port or 4700,
        )
    else:
        # Generic integrated device for other protocols
        device = IntegratedDevice(
            name=f"{protocol.upper()} Device",
            device_type=protocol,
            host=host,
            port=port or (11111 if protocol == "alpaca" else 7624),
        )

    profile = AstronomyProfile(
        name=name,
        description=description,
        integrated_device=device,
        latitude=latitude,
        longitude=longitude,
        elevation_m=elevation,
    )

    # Determine save path
    profiles_dir = ensure_profiles_dir()
    ext = ".yaml" if format == "yaml" else ".json"
    save_path = profiles_dir / f"{name}{ext}"

    try:
        profile.save(save_path)
        click.echo(f"Profile '{name}' created successfully.")
        click.echo(f"Saved to: {save_path}")
        click.echo(f"\nTo use: scopinator --profile {name} status")
    except Exception as e:
        click.echo(f"Error saving profile: {e}")


@profile.command("delete")
@click.argument("name")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
def delete(name: str, force: bool):
    """Delete a profile."""
    path = get_profile_path(name)

    if not path.exists():
        click.echo(f"Profile '{name}' not found.")
        return

    if not force:
        if not click.confirm(f"Delete profile '{name}'?"):
            click.echo("Cancelled.")
            return

    try:
        path.unlink()
        click.echo(f"Profile '{name}' deleted.")
    except Exception as e:
        click.echo(f"Error deleting profile: {e}")


@profile.command("discover")
@click.option("--timeout", "-t", default=10.0, help="Discovery timeout in seconds")
@click.option("--save", "-s", is_flag=True, help="Save discovered devices as profiles")
def discover(timeout: float, save: bool):
    """Discover devices and optionally create profiles."""
    from scopinator.profile import AstronomyProfile

    async def run_discovery():
        click.echo(f"Discovering devices (timeout: {timeout}s)...")
        devices = await AstronomyProfile.discover(timeout=timeout)
        return devices

    devices = asyncio.run(run_discovery())

    if not devices:
        click.echo("\nNo devices found.")
        click.echo("Make sure devices are powered on and on the same network.")
        return

    click.echo(f"\nFound {len(devices)} device(s):\n")

    for idx, device in enumerate(devices, 1):
        device_type = device.get("type", "unknown")
        manufacturer = device.get("manufacturer", "Unknown")
        model = device.get("model", "Unknown")
        host = device.get("host", "unknown")
        port = device.get("port", "N/A")

        click.echo(f"  {idx}. {manufacturer} {model}")
        click.echo(f"     Type: {device_type}")
        click.echo(f"     Host: {host}:{port}")
        click.echo()

        if save:
            # Create profile from discovered device
            async def create_profile():
                return await AstronomyProfile.create_from_discovery(device)

            try:
                profile = asyncio.run(create_profile())
                profile_name = f"{device_type}_{host.replace('.', '_')}"
                profiles_dir = ensure_profiles_dir()
                save_path = profiles_dir / f"{profile_name}.json"
                profile.save(save_path)
                click.echo(f"     Saved as profile: {profile_name}")
            except Exception as e:
                click.echo(f"     Error saving profile: {e}")


@profile.command("test")
@click.argument("name")
@click.option("--timeout", "-t", default=10.0, help="Connection timeout")
def test(name: str, timeout: float):
    """Test connection to a profile's device."""
    path = get_profile_path(name)

    if not path.exists():
        click.echo(f"Profile '{name}' not found.")
        return

    try:
        from scopinator.profile import AstronomyProfile
        profile = AstronomyProfile.load(path)

        click.echo(f"Testing connection to '{profile.name}'...")

        async def test_connection():
            try:
                success = await asyncio.wait_for(
                    profile.connect(),
                    timeout=timeout
                )
                if success:
                    status = await profile.get_status()
                    await profile.disconnect()
                    return True, status
                return False, None
            except asyncio.TimeoutError:
                return False, "Connection timed out"
            except Exception as e:
                return False, str(e)

        success, result = asyncio.run(test_connection())

        if success:
            click.echo("Connection successful!")
            if isinstance(result, dict):
                click.echo("\nDevice Status:")
                for key, value in result.items():
                    if value is not None:
                        click.echo(f"  {key}: {value}")
        else:
            click.echo(f"Connection failed: {result}")

    except Exception as e:
        click.echo(f"Error: {e}")


@profile.command("use")
@click.argument("name")
def use(name: str):
    """Set a profile as the default for this session.

    This saves the profile name to a temporary file that other
    commands will read from.
    """
    path = get_profile_path(name)

    if not path.exists():
        click.echo(f"Profile '{name}' not found.")
        return

    # Save as current profile
    current_file = PROFILES_DIR / ".current"
    current_file.write_text(name)

    click.echo(f"Using profile '{name}' for this session.")
    click.echo(f"\nCommands will now use this profile by default.")
    click.echo(f"Override with --profile <name> on any command.")


def get_current_profile() -> Optional[str]:
    """Get the currently selected profile name, if any."""
    current_file = PROFILES_DIR / ".current"
    if current_file.exists():
        return current_file.read_text().strip()
    return None


def load_profile(name: Optional[str] = None) -> Optional["AstronomyProfile"]:
    """Load a profile by name or get the current profile.

    Args:
        name: Profile name, or None to use current

    Returns:
        Loaded AstronomyProfile or None
    """
    from scopinator.profile import AstronomyProfile

    if name is None:
        name = get_current_profile()

    if name is None:
        return None

    path = get_profile_path(name)
    if not path.exists():
        return None

    return AstronomyProfile.load(path)
