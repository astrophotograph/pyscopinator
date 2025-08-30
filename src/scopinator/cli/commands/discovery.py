"""Discovery-related CLI commands."""

import asyncio
import click
from typing import List, Tuple


async def discover_telescopes(timeout: float = 10.0) -> List[Tuple[str, int]]:
    """Discover telescopes on the network.
    
    This is a simplified discovery function that attempts to connect to 
    common Seestar ports on the local network.
    """
    # For now, return empty list - actual discovery would scan network
    # This would be implemented using the discovery module
    return []