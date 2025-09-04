#!/bin/bash
# Run hardware integration tests for Seestar telescope
# This script provides an easy way to run the hardware tests with proper configuration

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
DEFAULT_HOST="localhost"
DEFAULT_PORT="4700"
DEFAULT_IMAGING_PORT="4800"

# Parse command line arguments
TEST_TYPE="restart"  # Default test type
VERBOSE="-xvs"      # Default to verbose output

usage() {
    echo "Usage: $0 [restart|disconnect|all] [options]"
    echo ""
    echo "Test Types:"
    echo "  restart     - Run restart monitoring test (default)"
    echo "  disconnect  - Run disconnect scenario test"
    echo "  all         - Run all hardware tests"
    echo ""
    echo "Options:"
    echo "  -h, --host HOST         Telescope IP address (default: $DEFAULT_HOST)"
    echo "  -p, --port PORT         Telescope port (default: $DEFAULT_PORT)"
    echo "  -i, --imaging PORT      Imaging port (default: $DEFAULT_IMAGING_PORT)"
    echo "  -q, --quiet             Less verbose output"
    echo "  --help                  Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 restart --host 192.168.1.100"
    echo "  $0 disconnect --quiet"
    echo "  $0 all"
}

# Check if first argument is test type
if [[ "$1" == "restart" || "$1" == "disconnect" || "$1" == "all" ]]; then
    TEST_TYPE=$1
    shift
fi

# Parse remaining arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--host)
            TELESCOPE_HOST="$2"
            shift 2
            ;;
        -p|--port)
            TELESCOPE_PORT="$2"
            shift 2
            ;;
        -i|--imaging)
            IMAGING_PORT="$2"
            shift 2
            ;;
        -q|--quiet)
            VERBOSE="-v"
            shift
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            usage
            exit 1
            ;;
    esac
done

# Use environment variables or defaults
TELESCOPE_HOST=${TELESCOPE_HOST:-$DEFAULT_HOST}
TELESCOPE_PORT=${TELESCOPE_PORT:-$DEFAULT_PORT}
IMAGING_PORT=${IMAGING_PORT:-$DEFAULT_IMAGING_PORT}

# Print configuration
echo -e "${GREEN}==================================${NC}"
echo -e "${GREEN}Hardware Integration Test Runner${NC}"
echo -e "${GREEN}==================================${NC}"
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  Telescope Host: $TELESCOPE_HOST"
echo "  Telescope Port: $TELESCOPE_PORT"
echo "  Imaging Port:   $IMAGING_PORT"
echo "  Test Type:      $TEST_TYPE"
echo "  Verbosity:      $VERBOSE"
echo ""

# Warn user about restart test
if [[ "$TEST_TYPE" == "restart" || "$TEST_TYPE" == "all" ]]; then
    echo -e "${YELLOW}⚠️  WARNING: This test will restart your telescope!${NC}"
    echo -e "${YELLOW}   The telescope will be unavailable for ~30-40 seconds.${NC}"
    echo ""
    read -p "Continue? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Test cancelled."
        exit 0
    fi
fi

# Export environment variables
export RUN_HARDWARE_TESTS=true
export TELESCOPE_HOST
export TELESCOPE_PORT
export IMAGING_PORT

# Run the appropriate test
echo ""
echo -e "${GREEN}Starting test...${NC}"
echo ""

case $TEST_TYPE in
    restart)
        uv run pytest tests/test_hardware_restart.py::TestRestartScenarios::test_restart_with_monitoring $VERBOSE --override-ini="addopts="
        ;;
    disconnect)
        uv run pytest tests/test_hardware_restart.py::TestDisconnectScenarios::test_disconnect_during_command_series $VERBOSE --override-ini="addopts="
        ;;
    all)
        uv run pytest tests/test_hardware_restart.py $VERBOSE --override-ini="addopts="
        ;;
esac

# Check test result
if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✅ Tests completed successfully!${NC}"
else
    echo ""
    echo -e "${RED}❌ Tests failed!${NC}"
    exit 1
fi