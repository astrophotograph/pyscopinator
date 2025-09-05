# Logging Configuration

Scopinator provides flexible logging configuration through CLI flags and environment variables.

## Quick Start

### CLI Flags

```bash
# Normal operation (default)
scopinator connect --host 192.168.1.100

# Debug mode - shows connection details and protocol messages
scopinator --debug connect --host 192.168.1.100

# Trace mode - shows everything including internal state changes
scopinator --trace connect --host 192.168.1.100  

# Quiet mode - only warnings and errors
scopinator --quiet connect --host 192.168.1.100

# Explicit log level
scopinator --log-level=WARNING connect --host 192.168.1.100
```

### Environment Variables

```bash
# Enable debug logging
export SCOPINATOR_DEBUG=true
scopinator connect --host 192.168.1.100

# Enable trace logging  
export SCOPINATOR_TRACE=true
scopinator connect --host 192.168.1.100

# Set explicit log level
export SCOPINATOR_LOG_LEVEL=DEBUG
scopinator connect --host 192.168.1.100

# Quiet mode
export SCOPINATOR_QUIET=true
scopinator connect --host 192.168.1.100
```

## Log Levels

| Level | Value | Description |
|-------|-------|-------------|
| TRACE | 5 | Most verbose - shows all internal operations, state changes, and protocol details |
| DEBUG | 10 | Detailed debugging - shows connection events, command/response cycles |
| INFO | 20 | Normal operation - shows important events and status updates |
| SUCCESS | 25 | Success messages (loguru specific) |
| WARNING | 30 | Warning messages - potential issues that don't prevent operation |
| ERROR | 40 | Error messages - failures that may affect functionality |
| CRITICAL | 50 | Critical errors - severe failures |

## Logging Modes

### Default Mode
- Level: INFO
- Shows important operational messages
- Suppresses verbose connection details
- Good for normal usage

### Debug Mode (`--debug` or `SCOPINATOR_DEBUG=true`)
- Level: DEBUG  
- Shows connection events, reconnection attempts
- Displays command/response details
- Useful for troubleshooting connection issues

### Trace Mode (`--trace` or `SCOPINATOR_TRACE=true`)
- Level: TRACE
- Shows everything including internal state changes
- Displays full stack traces on errors
- Includes timing information
- Best for deep debugging

### Quiet Mode (`--quiet` or `SCOPINATOR_QUIET=true`)
- Level: WARNING
- Only shows warnings and errors
- Suppresses all informational messages
- Good for scripts and automation

## Examples

### Debugging Connection Issues
```bash
# See what's happening during connection
scopinator --debug connect --host 192.168.1.100

# Even more detail
scopinator --trace connect --host 192.168.1.100
```

### Monitoring During Restart
```bash
# Normal monitoring
scopinator monitor --host 192.168.1.100

# See reconnection attempts
SCOPINATOR_DEBUG=true scopinator monitor --host 192.168.1.100

# See all internal state changes
SCOPINATOR_TRACE=true scopinator monitor --host 192.168.1.100
```

### Running Tests
```bash
# Run hardware tests with debug output
SCOPINATOR_DEBUG=true RUN_HARDWARE_TESTS=true pytest tests/test_hardware_restart.py -xvs

# Maximum verbosity for troubleshooting
SCOPINATOR_TRACE=true RUN_HARDWARE_TESTS=true pytest tests/test_hardware_restart.py -xvs
```

### Scripting
```bash
# Quiet mode for scripts - only show errors
scopinator --quiet connect --host 192.168.1.100

# Or via environment
export SCOPINATOR_QUIET=true
scopinator status
```

## Log Output Format

### Default Format
```
HH:MM:SS | LEVEL | message
```

### Debug Format
```
YYYY-MM-DD HH:MM:SS | LEVEL    | module.name - message
```

### Trace Format
```
YYYY-MM-DD HH:MM:SS.SSS | LEVEL    | module.name:function:line - message
```

### Quiet Format
```
LEVEL: message
```

## Module-Specific Behavior

Some modules have special handling to reduce noise:

| Module | Default Behavior | Debug/Trace Behavior |
|--------|-----------------|---------------------|
| `scopinator.seestar.connection` | INFO level, connection resets logged at DEBUG | Full details of all operations |
| `scopinator.seestar.rtspclient` | WARNING level to suppress H.264 warnings | Full RTSP protocol details |
| `scopinator.util.eventbus` | WARNING level to reduce event noise | All event dispatches shown |

## Priority Order

When multiple logging configurations are specified, they are applied in this order:

1. CLI `--log-level` flag (highest priority)
2. CLI `--trace` flag
3. CLI `--debug` flag  
4. CLI `--quiet` flag
5. `SCOPINATOR_LOG_LEVEL` environment variable
6. `SCOPINATOR_TRACE` environment variable
7. `SCOPINATOR_DEBUG` environment variable
8. `SCOPINATOR_QUIET` environment variable (lowest priority)

CLI flags always override environment variables.

## Programmatic Usage

```python
from scopinator.util.logging_config import setup_logging

# Configure logging before using any scopinator modules
setup_logging(debug=True)

# Or with explicit level
setup_logging(level="TRACE")

# Check current configuration
from scopinator.util.logging_config import LoggingConfig

if LoggingConfig.is_debug_enabled():
    print("Debug logging is active")

current_mode = LoggingConfig.get_current_mode()
current_level = LoggingConfig.get_current_level()
```

## Troubleshooting

### Too Much Output
- Use `--quiet` to reduce to warnings/errors only
- Default mode (no flags) should be suitable for most users

### Not Enough Detail
- Use `--debug` to see connection events and protocol messages
- Use `--trace` for maximum detail including internal state

### RTSP/H.264 Warnings
- These are suppressed by default
- Use `--debug` to see them if needed
- Use `--trace` to see full RTSP protocol details

### Connection Reset Messages
- Normal during telescope restart
- Logged at DEBUG level to reduce noise
- Use `--debug` to see reconnection attempts