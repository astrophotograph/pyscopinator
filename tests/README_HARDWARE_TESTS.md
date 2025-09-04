# Hardware Integration Tests

This directory contains integration tests that require real Seestar telescope hardware.

## Prerequisites

1. **Seestar Telescope**: You need a real Seestar telescope connected to your network
2. **Network Access**: The telescope must be accessible from your test machine
3. **Python Environment**: Tests run using pytest with the scopinator package installed

## Test Files

### `test_hardware_restart.py`
Tests for device restart scenarios and connection recovery:
- **test_restart_with_monitoring**: Connects, starts streaming, restarts the telescope, and monitors recovery for 60 seconds
- **test_disconnect_during_command_series**: Tests resilience when telescope disconnects during command execution

### `test_hardware_integration.py`
Basic hardware integration tests for command execution

### `test_hardware_resilience.py`
Tests for connection resilience and error recovery

## Running the Tests

### Environment Setup

```bash
# Install the package and test dependencies
uv sync

# Set the telescope host (optional, defaults to localhost)
export TELESCOPE_HOST=192.168.1.100  # Replace with your telescope's IP

# Optional: Set custom ports (defaults shown)
export TELESCOPE_PORT=4700  # Regular client port
export IMAGING_PORT=4800    # Imaging client port
```

### Running Specific Tests

#### 1. Restart Monitoring Test (Main Test)
This test connects to the telescope, starts streaming, sends a restart command, and monitors the connection status for 60 seconds:

```bash
# Run with full output
RUN_HARDWARE_TESTS=true uv run pytest tests/test_hardware_restart.py::TestRestartScenarios::test_restart_with_monitoring -xvs --override-ini="addopts="

# Run with captured output (less verbose)
RUN_HARDWARE_TESTS=true uv run pytest tests/test_hardware_restart.py::TestRestartScenarios::test_restart_with_monitoring -v --override-ini="addopts="
```

#### 2. Disconnect During Commands Test
Tests behavior when the telescope disconnects during a series of commands:

```bash
RUN_HARDWARE_TESTS=true uv run pytest tests/test_hardware_restart.py::TestDisconnectScenarios::test_disconnect_during_command_series -xvs --override-ini="addopts="
```

#### 3. Run All Restart Tests
```bash
RUN_HARDWARE_TESTS=true uv run pytest tests/test_hardware_restart.py -xvs --override-ini="addopts="
```

#### 4. Run All Hardware Tests
```bash
# All hardware tests (includes restart, integration, and resilience tests)
RUN_HARDWARE_TESTS=true uv run pytest tests/ -k hardware -xvs --override-ini="addopts="
```

### Test Output Explanation

The restart monitoring test provides detailed output including:

1. **Connection Status Changes**: Shows when clients connect/disconnect
2. **Device State**: Tracks device_state, view_state changes  
3. **Pi Status**: Monitors battery level and temperature
4. **Streaming Stats**: Tracks stacked/dropped/skipped frames
5. **Timestamps**: Each change shows both wall clock time and elapsed seconds

Example output:
```
[14:23:45.123] [  0.52s] Client.is_connected: True
[14:23:47.456] [  2.85s] Client.device_state: ready
[14:23:48.789] [  4.18s] ImagingClient.client_mode: Stack
[14:24:15.234] [ 30.63s] Client.is_connected: False  # Restart begins
[14:24:45.678] [ 61.08s] Client.is_connected: True   # Recovery complete
```

## Important Notes

⚠️ **WARNING**: These tests will control your telescope hardware!
- The restart test will actually restart your telescope
- The telescope will be unavailable for ~30-40 seconds during restart
- Ensure the telescope is in a safe position before running tests

## Troubleshooting

### Connection Issues
- Verify telescope IP: `scopinator discover`
- Check network connectivity: `ping <telescope_ip>`
- Ensure no other applications are connected to the telescope

### Test Failures
- Check telescope is powered on and ready
- Verify correct IP address in TELESCOPE_HOST
- Look for firewall or network isolation issues
- Try connecting with the CLI first: `scopinator connect --host <ip>`

### Timeout Issues
If tests timeout, the telescope might be:
- Still booting up (wait 1-2 minutes after power on)
- In an error state (check telescope LED indicators)
- Already connected to another client (disconnect other apps)

## CI/CD Integration

These tests are marked with `@pytest.mark.hardware` and skip by default.
To run in CI with real hardware:

```yaml
# GitHub Actions example
- name: Run Hardware Tests
  env:
    RUN_HARDWARE_TESTS: true
    TELESCOPE_HOST: ${{ secrets.TELESCOPE_HOST }}
  run: |
    pytest tests/test_hardware_restart.py -xvs
```