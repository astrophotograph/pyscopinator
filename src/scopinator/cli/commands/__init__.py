"""CLI commands module."""

from scopinator.cli.commands.discovery import discover_telescopes
from scopinator.cli.commands.profile import (
    profile,
    list_profiles,
    get_profile_path,
    load_profile,
    get_current_profile,
)

__all__ = [
    "discover_telescopes",
    "profile",
    "list_profiles",
    "get_profile_path",
    "load_profile",
    "get_current_profile",
]