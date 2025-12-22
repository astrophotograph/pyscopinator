"""Connection state persistence for CLI.

Saves and loads connection state between CLI invocations.
"""

import json
from pathlib import Path
from typing import Any, Optional

# State file location
SCOPINATOR_DIR = Path.home() / ".scopinator"
CONNECTION_STATE_FILE = SCOPINATOR_DIR / "connection.json"


def ensure_state_dir() -> Path:
    """Ensure the state directory exists."""
    SCOPINATOR_DIR.mkdir(parents=True, exist_ok=True)
    return SCOPINATOR_DIR


def save_connection_state(
    protocol: str,
    host: str,
    port: int,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """Save connection state to disk.

    Args:
        protocol: Protocol name (seestar, alpaca, indi)
        host: Telescope host/IP
        port: Telescope port
        extra: Optional extra data to save
    """
    ensure_state_dir()

    state = {
        "protocol": protocol,
        "host": host,
        "port": port,
    }
    if extra:
        state.update(extra)

    with open(CONNECTION_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_connection_state() -> Optional[dict[str, Any]]:
    """Load connection state from disk.

    Returns:
        Connection state dict or None if no state saved
    """
    if not CONNECTION_STATE_FILE.exists():
        return None

    try:
        with open(CONNECTION_STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def clear_connection_state() -> None:
    """Clear saved connection state."""
    if CONNECTION_STATE_FILE.exists():
        CONNECTION_STATE_FILE.unlink()


def get_saved_host() -> Optional[str]:
    """Get saved host from connection state."""
    state = load_connection_state()
    return state.get("host") if state else None


def get_saved_port() -> Optional[int]:
    """Get saved port from connection state."""
    state = load_connection_state()
    return state.get("port") if state else None


def get_saved_protocol() -> Optional[str]:
    """Get saved protocol from connection state."""
    state = load_connection_state()
    return state.get("protocol") if state else None
