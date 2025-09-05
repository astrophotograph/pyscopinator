"""Discovery-related CLI commands."""

import asyncio
import click
from typing import List, Tuple
from scopinator.util.logging_config import get_logger
logger = get_logger(__name__)


async def discover_telescopes(timeout: float = 10.0) -> List[Tuple[str, int]]:
    """Discover telescopes on the network using broadcast discovery.
    
    Args:
        timeout: Maximum time to wait for discovery responses
        
    Returns:
        List of (ip, port) tuples for discovered telescopes
    """
    try:
        # Try to use the actual discovery module if available
        from scopinator.seestar.commands.discovery import discover_seestars
        
        logger.info(f"Starting telescope discovery with {timeout}s timeout...")
        discovered = await discover_seestars(timeout=timeout)
        
        # Convert to expected format
        telescopes = []
        for device in discovered:
            if isinstance(device, dict):
                ip = device.get('address')
                port = 4700  # Seestar uses port 4700 for control
                if ip:
                    telescopes.append((ip, port))
            elif isinstance(device, tuple) and len(device) >= 2:
                telescopes.append((device[0], device[1]))
        
        return telescopes
        
    except ImportError as e:
        # Fallback to network scanning if discovery module not available
        logger.debug(f"Discovery module not available ({e}), using network scan")
        return await scan_for_telescopes(timeout)
    except asyncio.TimeoutError:
        logger.info("Discovery timeout reached")
        return []
    except Exception as e:
        logger.error(f"Discovery error: {e}")
        return []


async def scan_for_telescopes(timeout: float = 10.0) -> List[Tuple[str, int]]:
    """Scan local network for telescopes by attempting connections.
    
    This is a fallback method that scans common ports.
    """
    import socket
    telescopes = []
    common_ports = [4700, 4800, 4900]  # Common Seestar ports
    
    # Limit concurrent connections to avoid "Too many open files" error
    max_concurrent = 20  # Reduced to be more conservative
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def check_with_limit(host: str, port: int) -> Tuple[str, int] | None:
        async with semaphore:
            return await check_telescope(host, port, timeout=1.0)
    
    # Get local network range
    try:
        # Get local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        
        # Generate IP range (simplified - just check .1 to .254)
        ip_parts = local_ip.split('.')
        base_ip = '.'.join(ip_parts[:3])
        
        # Create tasks to check multiple IPs concurrently (with limit)
        tasks = []
        for i in range(1, 255):
            ip = f"{base_ip}.{i}"
            for port in common_ports:
                tasks.append(check_with_limit(ip, port))
        
        # Run with overall timeout
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=timeout
        )
        
        # Collect successful connections
        for result in results:
            if isinstance(result, tuple):
                telescopes.append(result)
                
    except Exception as e:
        logger.debug(f"Network scan error: {e}")
    
    return telescopes


async def check_telescope(host: str, port: int, timeout: float = 1.0) -> Tuple[str, int] | None:
    """Check if a telescope is available at the given host and port."""
    conn = None
    try:
        from scopinator.seestar.connection import SeestarConnection
        
        # Temporarily disable loguru logging during discovery scan
        logger.disable("scopinator.seestar.connection")
        try:
            conn = SeestarConnection(host=host, port=port, connection_timeout=timeout)
            await conn.open()
            logger.enable("scopinator.seestar.connection")
            logger.info(f"Found telescope at {host}:{port}")
            return (host, port)
        finally:
            logger.enable("scopinator.seestar.connection")
    except:
        return None
    finally:
        # Always close the connection to avoid file descriptor leaks
        if conn:
            try:
                await conn.close()
            except:
                pass