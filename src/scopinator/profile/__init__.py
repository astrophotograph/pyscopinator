"""Astronomy profile system for managing telescope setups.

This module provides a high-level abstraction for managing complete
telescope setups, including mounts, cameras, filter wheels, and other
accessories. Profiles can be saved to and loaded from JSON/YAML files.

Example:
    # Discover and create a profile
    devices = await AstronomyProfile.discover()
    profile = await AstronomyProfile.create_from_discovery(devices[0])

    # Connect and use
    async with profile:
        await profile.goto((83.63, 22.01), target_name="M42")
        await profile.start_imaging()

    # Save for later
    profile.save("my_telescope.yaml")
"""

from scopinator.profile.astronomy_profile import AstronomyProfile, ProfileState
from scopinator.profile.components.base import BaseComponent, ComponentState

__all__ = [
    "AstronomyProfile",
    "ProfileState",
    "BaseComponent",
    "ComponentState",
]
