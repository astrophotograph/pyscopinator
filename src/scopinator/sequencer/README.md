# Scopinator Sequencer

A flexible, async-based sequencer for telescope and astrophotography automation. Build complex imaging sequences with hierarchical steps, wait conditions, and full JSON serialization support.

## Features

- **Hierarchical Sequences**: Commands can contain other commands, allowing complex nested sequences
- **Multiple Wait Conditions**: Wait for minutes, specific times, or astronomical events (dawn/dusk)
- **Telescope Control**: Go to targets, start/stop imaging with configurable parameters
- **State Management**: Start, stop, pause, and resume sequences
- **JSON Serialization**: Save and load sequences from JSON files
- **Async Execution**: Built on asyncio for non-blocking operation
- **Type Safety**: Full Pydantic models with type checking

## Command Types

### Wait Commands

- **WaitMinutesCommand**: Wait for a specified duration
  ```python
  WaitMinutesCommand(name="Wait 10 minutes", minutes=10)
  ```

- **WaitUntilTimeCommand**: Wait until a specific date/time
  ```python
  WaitUntilTimeCommand(name="Wait until midnight", target_time=datetime(2025, 1, 1, 0, 0))
  ```

- **WaitUntilEventCommand**: Wait for astronomical events
  ```python
  WaitUntilEventCommand(
      name="Wait for sunset",
      event=AstronomicalEvent.SUNSET,
      latitude=37.7749,
      longitude=-122.4194
  )
  ```

### Telescope Commands

- **GoToTargetCommand**: Slew to RA/Dec coordinates
  ```python
  GoToTargetCommand(
      name="Slew to M31",
      ra=10.6847,
      dec=41.2689,
      target_name="M31 (Andromeda Galaxy)"
  )
  ```

### Imaging Commands

- **StartImagingCommand**: Start an imaging session
  ```python
  StartImagingCommand(
      name="Start imaging",
      exposure_time=300.0,  # seconds
      gain=100,
      count=12  # number of exposures (None = unlimited)
  )
  ```

- **StopImagingCommand**: Stop imaging
  ```python
  StopImagingCommand(name="Stop imaging")
  ```

### Container Commands

- **SequenceCommand**: A command containing other commands
  ```python
  SequenceCommand(
      name="Image M31",
      commands=[
          GoToTargetCommand(...),
          StartImagingCommand(...),
          WaitMinutesCommand(...),
          StopImagingCommand(...)
      ]
  )
  ```

## Astronomical Events

The sequencer supports waiting for these astronomical events:

- `ASTRONOMICAL_DAWN` / `ASTRONOMICAL_DUSK` (sun at -18°)
- `NAUTICAL_DAWN` / `NAUTICAL_DUSK` (sun at -12°)
- `CIVIL_DAWN` / `CIVIL_DUSK` (sun at -6°)
- `SUNRISE` / `SUNSET`

## Usage Examples

### Simple Imaging Sequence

```python
from scopinator.sequencer import (
    Sequence,
    GoToTargetCommand,
    StartImagingCommand,
    WaitMinutesCommand,
    StopImagingCommand
)

# Create sequence
sequence = Sequence(
    name="M31 Imaging",
    description="Image M31 for 1 hour",
    commands=[
        GoToTargetCommand(
            name="Slew to M31",
            ra=10.6847,
            dec=41.2689,
            target_name="M31"
        ),
        StartImagingCommand(
            name="Start imaging",
            exposure_time=300.0,
            gain=100,
            count=12
        ),
        WaitMinutesCommand(name="Wait 1 hour", minutes=60),
        StopImagingCommand(name="Stop imaging")
    ]
)

# Execute sequence
context = {
    "client": seestar_client,
    "imaging_client": imaging_client
}
await sequence.start(context)
```

### All-Night Imaging

```python
from scopinator.sequencer import WaitUntilEventCommand
from scopinator.sequencer.events import AstronomicalEvent

sequence = Sequence(
    name="All Night Imaging",
    commands=[
        WaitUntilEventCommand(
            name="Wait for sunset",
            event=AstronomicalEvent.SUNSET,
            latitude=37.7749,
            longitude=-122.4194
        ),
        GoToTargetCommand(name="Slew to target", ...),
        StartImagingCommand(name="Start imaging", ...),
        WaitUntilEventCommand(
            name="Wait until dawn",
            event=AstronomicalEvent.ASTRONOMICAL_DAWN,
            latitude=37.7749,
            longitude=-122.4194
        ),
        StopImagingCommand(name="Stop imaging")
    ]
)
```

### Multi-Target Sequence

```python
from scopinator.sequencer import SequenceCommand

def create_target_sequence(name, ra, dec, duration_minutes):
    return SequenceCommand(
        name=f"Image {name}",
        commands=[
            GoToTargetCommand(name=f"Slew to {name}", ra=ra, dec=dec, target_name=name),
            StartImagingCommand(name="Start imaging", exposure_time=300, gain=100),
            WaitMinutesCommand(name=f"Wait {duration_minutes} min", minutes=duration_minutes),
            StopImagingCommand(name="Stop imaging")
        ]
    )

sequence = Sequence(
    name="Multi-Target Night",
    commands=[
        create_target_sequence("M31", 10.6847, 41.2689, 90),
        create_target_sequence("M42", 83.8221, -5.3911, 60),
        create_target_sequence("M45", 56.75, 24.1167, 45)
    ]
)
```

### Save and Load Sequences

```python
# Save to JSON
sequence.to_json(file_path="my_sequence.json")

# Load from JSON
loaded_sequence = Sequence.from_json(file_path="my_sequence.json")

# Or work with JSON strings
json_str = sequence.to_json()
loaded_sequence = Sequence.from_json(json_str=json_str)
```

### Sequence Control

```python
# Start sequence
await sequence.start(context)

# Pause sequence
await sequence.pause()

# Resume sequence
await sequence.resume(context)

# Stop sequence
await sequence.stop()

# Check status
print(f"State: {sequence.state}")
print(f"Current command: {sequence.current_command_index}")
```

## Command Status

Each command tracks its execution status:

- `PENDING`: Not yet started
- `RUNNING`: Currently executing
- `COMPLETED`: Successfully completed
- `FAILED`: Execution failed
- `CANCELLED`: Cancelled by user
- `PAUSED`: Paused and waiting to resume

## Execution Context

Commands receive an execution context dictionary that should contain:

- `client`: SeestarClient instance for telescope control
- `imaging_client`: SeestarImagingClient instance for imaging operations

Additional context items can be added as needed by your application.

## Examples

See `examples.py` for complete working examples:

- Simple imaging sequence
- Dawn-to-dusk imaging
- Multi-target sequences
- Timed sequences

## Integration with Scopinator

The sequencer integrates with the existing Scopinator telescope control system:

- Uses `SeestarClient` for telescope commands
- Uses `SeestarImagingClient` for imaging operations
- Compatible with the async event system
- Follows the Pydantic-based architecture

## Future Enhancements

Potential additions:

- Weather monitoring and conditional execution
- Auto-focus commands
- Dithering support
- Plate solving integration
- Meridian flip handling
- Progress callbacks and notifications
- Dry-run/validation mode
