# Hardware Integration Tests

This document describes the hardware integration tests for the Scopinator project.

## Overview

The hardware integration tests are designed to test the telescope control library against real hardware or mock hardware servers. These tests are kept separate from unit tests to avoid requiring hardware for regular CI/CD runs.

## Test Structure

Tests are located in:
- `tests/test_hardware_integration.py` - Basic hardware integration tests
- `tests/test_hardware_resilience.py` - Network resilience and error recovery tests

### Test Categories:
1. **Connection Tests** - Basic connection/disconnection lifecycle
2. **Basic Commands** - Simple commands like GetTime, GetDeviceState
3. **Coordinate Operations** - RA/Dec operations and syncing
4. **Status Retrieval** - Getting and updating telescope status
5. **Settings Commands** - Configuring telescope settings
6. **Context Manager** - Testing async context manager support
7. **Event System** - Testing event reception from hardware
8. **Error Handling** - Testing error conditions and recovery
9. **Network Resilience** - Testing disconnects, slow connections, packet loss
10. **Concurrent Operations** - Testing thread safety and concurrent commands

## Running Hardware Tests

### Method 1: Using the Helper Script
```bash
./run_hardware_tests.sh
```

### Method 2: Using Environment Variable
```bash
RUN_HARDWARE_TESTS=true uv run pytest tests/test_hardware_integration.py -v --override-ini="addopts="
```

### Method 3: Using Pytest Marker
```bash
uv run pytest -m hardware --override-ini="addopts=" -v
```

## Configuration

### Environment Variables:
- `RUN_HARDWARE_TESTS` - Set to "true" to enable hardware tests
- `TELESCOPE_HOST` - Telescope host (default: localhost)
- `TELESCOPE_PORT` - Primary telescope port (default: 4700)
- `TELESCOPE_PORT_ALT` - Alternative telescope port (default: 4701)

### Pytest Configuration:
Hardware tests are marked with `@pytest.mark.hardware` and are excluded by default in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = ["hardware: marks tests that require real hardware or mock hardware server"]
addopts = "-m 'not hardware'"  # Exclude hardware tests by default
```

## Mock Hardware Server

For testing without real hardware, you can use a mock telescope server running on localhost. The mock should:
- Listen on port 4700 (and optionally 4701)
- Respond to basic JSON-RPC commands
- Return appropriate responses for telescope commands

## Test Coverage

Hardware tests cover:
- ✅ Connection management (connect/disconnect/reconnect)
- ✅ Basic telescope commands (time, state, status)
- ✅ Coordinate operations (get/set RA/Dec)
- ✅ Focus control
- ✅ Settings management
- ✅ Event handling
- ✅ Error recovery
- ✅ Context manager support
- ✅ **Disconnect during operations** - Tests behavior when connection drops mid-command
- ✅ **Slow connection handling** - Tests with artificial delays and slow networks
- ✅ **Packet loss simulation** - Tests resilience to network packet loss
- ✅ **Rapid connect/disconnect cycles** - Tests stability with rapid connection changes
- ✅ **Concurrent command execution** - Tests thread safety with multiple simultaneous commands
- ✅ **Automatic reconnection** - Tests recovery after network interruptions

## Notes

1. **Hardware tests are excluded from normal test runs** - They won't run with `pytest` or `uv run pytest` unless explicitly requested
2. **Tests handle missing hardware gracefully** - Tests will skip if hardware is not available
3. **No imaging required** - These tests only use non-imaging commands
4. **Works with mock servers** - Tests are designed to work with mock telescope servers for CI/CD

## Example Test Output

```bash
$ ./run_hardware_tests.sh
===================================
Running Hardware Integration Tests
===================================

Requirements:
- Telescope/mock server running on localhost:4700
- Optional: Secondary server on localhost:4701

Starting hardware tests...

tests/test_hardware_integration.py::TestHardwareConnection::test_connection_lifecycle PASSED
tests/test_hardware_integration.py::TestBasicCommands::test_get_time PASSED
tests/test_hardware_integration.py::TestBasicCommands::test_get_device_state PASSED
... (more tests)

===================== 21 passed in 10.25s =====================

Hardware tests completed!
```