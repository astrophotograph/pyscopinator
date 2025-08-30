#!/bin/bash

# Script to run hardware integration tests
# These tests require a telescope or mock telescope server running on localhost

echo "==================================="
echo "Running Hardware Integration Tests"
echo "==================================="
echo ""
echo "Requirements:"
echo "- Telescope/mock server running on localhost:4700"
echo "- Optional: Secondary server on localhost:4701"
echo ""

# Set environment variable to enable hardware tests
export RUN_HARDWARE_TESTS=true

# Optional: Override host and ports
# export TELESCOPE_HOST=localhost
# export TELESCOPE_PORT=4700
# export TELESCOPE_PORT_ALT=4701

# Run only hardware tests with verbose output
echo "Starting hardware tests..."
echo ""

# Run hardware integration tests
uv run pytest tests/test_hardware_integration.py tests/test_hardware_resilience.py -v -m hardware --override-ini="addopts=" "$@"

echo ""
echo "Hardware tests completed!"