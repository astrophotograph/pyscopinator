# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Development
- Install dependencies: `uv sync`
- Run tests: `pytest tests/`
- Run specific test: `pytest tests/test_seestar_client.py::TestName`

### Linting and Formatting
- Use `ruff` for linting and formatting Python code
- Run linter: `ruff check src/`
- Format code: `ruff format src/`

## Architecture Overview

### Project Structure
The codebase implements a client library for controlling Seestar telescopes. It uses an async architecture built on asyncio for handling concurrent operations and real-time communication with telescope hardware.

### Core Components

**SeestarClient** (`src/scopinator/seestar/client.py`)
- Main client interface for telescope control
- Manages connection state, command execution, and event handling
- Maintains telescope status and handles both text and binary protocol messages
- Implements command queuing and response correlation

**SeestarImagingClient** (`src/scopinator/seestar/imaging_client.py`)
- Specialized client for imaging operations
- Handles streaming, image fetching, and RTSP video streams
- Manages binary protocol for image data transfer

**Connection Layer** (`src/scopinator/seestar/connection.py`)
- TCP socket connection management with automatic reconnection
- Configurable timeouts and retry logic
- Handles connection failures and telescope reboots

**Command System** (`src/scopinator/seestar/commands/`)
- Pydantic-based command models with type safety
- Categories: simple, parameterized, imaging, settings, discovery, planner
- Each command class handles serialization and response parsing

**Event System** (`src/scopinator/seestar/events/`)
- Event-driven architecture using EventBus
- Handles telescope status updates, imaging events, and internal notifications
- Supports async event handlers and subscriptions

**Protocol Handlers** (`src/scopinator/seestar/protocol_handlers.py`)
- TextProtocol: JSON-based command/response handling
- BinaryProtocol: Binary data transfer for images
- Message parsing and validation

### Key Design Patterns
- All classes use Pydantic models for data validation and serialization
- Beartype runtime type checking is enabled for the seestar package
- Async/await pattern throughout for non-blocking operations
- Event-driven communication between components
- Command-response correlation using unique message IDs

### Testing
- Integration tests in `tests/test_seestar_integration.py`
- Unit tests in `tests/test_seestar_client.py`
- Tests use asyncio and mock telescope connections