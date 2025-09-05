"""Centralized logging configuration for scopinator using loguru.

Supports configuration via:
1. Environment variables: SCOPINATOR_LOG_LEVEL, SCOPINATOR_DEBUG, SCOPINATOR_TRACE
2. CLI flags: --debug, --trace, --quiet
3. Programmatic configuration

Log levels (loguru):
- TRACE (5): Most verbose, includes all internal state changes
- DEBUG (10): Detailed debugging information  
- INFO (20): General informational messages
- SUCCESS (25): Success messages (loguru specific)
- WARNING (30): Warning messages
- ERROR (40): Error messages
- CRITICAL (50): Critical errors
"""

import os
import sys
from typing import Optional
from loguru import logger

# Remove default logger
logger.remove()


class LoggingConfig:
    """Manage logging configuration for scopinator using loguru."""
    
    _initialized = False
    _current_mode = "default"
    _current_level = "INFO"
    
    @classmethod
    def configure(
        cls,
        debug: bool = False,
        trace: bool = False,
        quiet: bool = False,
        level: Optional[str] = None,
        force: bool = False,
    ) -> None:
        """Configure logging based on flags and environment variables.
        
        Args:
            debug: Enable debug logging
            trace: Enable trace logging (most verbose)
            quiet: Reduce logging to warnings and errors only
            level: Explicit log level (overrides other flags)
            force: Force reconfiguration even if already initialized
        """
        if cls._initialized and not force:
            return
        
        # Remove any existing handlers
        logger.remove()
        
        # Check environment variables (lowest priority)
        env_level = os.environ.get("SCOPINATOR_LOG_LEVEL", "").upper()
        env_debug = os.environ.get("SCOPINATOR_DEBUG", "").lower() in ("true", "1", "yes")
        env_trace = os.environ.get("SCOPINATOR_TRACE", "").lower() in ("true", "1", "yes")
        env_quiet = os.environ.get("SCOPINATOR_QUIET", "").lower() in ("true", "1", "yes")
        
        # Apply environment settings if not overridden by arguments
        if not any([debug, trace, quiet, level]):
            debug = env_debug
            trace = env_trace
            quiet = env_quiet
            if env_level:
                level = env_level
        
        # Determine log level
        if level:
            # Explicit level overrides everything
            log_level = level.upper()
            cls._current_mode = f"custom-{level.lower()}"
        elif trace:
            log_level = "TRACE"
            cls._current_mode = "trace"
        elif debug:
            log_level = "DEBUG"
            cls._current_mode = "debug"
        elif quiet:
            log_level = "WARNING"
            cls._current_mode = "quiet"
        else:
            log_level = "INFO"
            cls._current_mode = "default"
        
        cls._current_level = log_level
        
        # Configure format based on verbosity
        if trace or cls._current_mode == "trace":
            # Most detailed format for trace mode
            log_format = (
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
            )
        elif debug or cls._current_mode == "debug":
            # Detailed format for debug mode
            log_format = (
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan> - "
                "<level>{message}</level>"
            )
        elif quiet or cls._current_mode == "quiet":
            # Minimal format for quiet mode
            log_format = "<level>{level}: {message}</level>"
        else:
            # Standard format for normal mode
            log_format = (
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level}</level> | "
                "<level>{message}</level>"
            )
        
        # Add console handler with configured format and level
        logger.add(
            sys.stderr,
            format=log_format,
            level=log_level,
            colorize=True,
            backtrace=(trace or cls._current_mode == "trace"),
            diagnose=(trace or cls._current_mode == "trace"),
        )
        
        # Add filter for specific modules based on mode
        if cls._current_mode == "quiet":
            # In quiet mode, suppress info from noisy modules
            logger.disable("scopinator.seestar.rtspclient")
            logger.disable("scopinator.util.eventbus")
        elif cls._current_mode not in ("debug", "trace"):
            # In normal mode, reduce verbosity of some modules
            def module_filter(record):
                # Reduce RTSP client noise
                if record["name"].startswith("scopinator.seestar.rtspclient"):
                    return record["level"].no >= logger.level("WARNING").no
                # Reduce eventbus noise
                if record["name"].startswith("scopinator.util.eventbus"):
                    return record["level"].no >= logger.level("WARNING").no
                return True
            
            logger.add(
                lambda msg: None,  # Null sink
                filter=module_filter,
                level=0
            )
        
        cls._initialized = True
        
        # Log the configuration (only if not quiet)
        if not quiet and cls._current_mode != "quiet":
            logger.debug(f"Logging configured: mode={cls._current_mode}, level={log_level}")
    
    @classmethod
    def get_current_mode(cls) -> str:
        """Get the current logging mode."""
        return cls._current_mode
    
    @classmethod
    def get_current_level(cls) -> str:
        """Get the current logging level."""
        return cls._current_level
    
    @classmethod
    def is_debug_enabled(cls) -> bool:
        """Check if debug logging is enabled."""
        return cls._current_mode in ("debug", "trace") or cls._current_level in ("DEBUG", "TRACE")
    
    @classmethod
    def is_trace_enabled(cls) -> bool:
        """Check if trace logging is enabled."""
        return cls._current_mode == "trace" or cls._current_level == "TRACE"
    
    @classmethod
    def reset(cls) -> None:
        """Reset logging configuration to allow reconfiguration."""
        logger.remove()
        cls._initialized = False
        cls._current_mode = "default"
        cls._current_level = "INFO"


def setup_logging(
    debug: bool = False,
    trace: bool = False,
    quiet: bool = False,
    level: Optional[str] = None,
) -> None:
    """Convenience function to set up logging.
    
    Args:
        debug: Enable debug logging
        trace: Enable trace logging (most verbose)
        quiet: Reduce logging to warnings and errors only
        level: Explicit log level string
    """
    LoggingConfig.configure(debug=debug, trace=trace, quiet=quiet, level=level)


def get_logger(name: Optional[str] = None):
    """Get the loguru logger instance.
    
    Args:
        name: Logger name (not used by loguru, kept for compatibility)
        
    Returns:
        The loguru logger instance
    """
    # Ensure logging is configured
    if not LoggingConfig._initialized:
        LoggingConfig.configure()
    
    # Loguru uses a single logger instance
    return logger