"""Example sequences for demonstration purposes."""

from datetime import datetime, timedelta

from scopinator.sequencer import (
    GoToTargetCommand,
    Sequence,
    SequenceCommand,
    StartImagingCommand,
    StopImagingCommand,
    WaitMinutesCommand,
    WaitUntilEventCommand,
    WaitUntilTimeCommand,
)
from scopinator.sequencer.events import AstronomicalEvent


def create_simple_imaging_sequence() -> Sequence:
    """Create a simple imaging sequence.

    This sequence:
    1. Waits 5 minutes
    2. Goes to a target (M31)
    3. Starts imaging
    4. Waits 60 minutes
    5. Stops imaging

    Returns:
        Sequence: A configured sequence
    """
    return Sequence(
        name="Simple M31 Imaging",
        description="Basic imaging sequence for M31 (Andromeda Galaxy)",
        commands=[
            WaitMinutesCommand(name="Initial wait", minutes=5),
            GoToTargetCommand(
                name="Slew to M31",
                ra=10.6847,  # M31 RA in degrees
                dec=41.2689,  # M31 Dec in degrees
                target_name="M31 (Andromeda Galaxy)",
            ),
            StartImagingCommand(
                name="Start imaging",
                exposure_time=300.0,  # 5 minute exposures
                gain=100,
                count=12,  # 12 exposures = 1 hour
            ),
            WaitMinutesCommand(name="Wait for imaging", minutes=60),
            StopImagingCommand(name="Stop imaging"),
        ],
    )


def create_dawn_sequence() -> Sequence:
    """Create a sequence that runs until astronomical dawn.

    This sequence:
    1. Waits until sunset
    2. Goes to target
    3. Starts imaging
    4. Waits until astronomical dawn
    5. Stops imaging

    Returns:
        Sequence: A configured sequence
    """
    # Example coordinates (San Francisco)
    latitude = 37.7749
    longitude = -122.4194

    return Sequence(
        name="All Night Imaging",
        description="Imaging sequence that runs from sunset to dawn",
        commands=[
            WaitUntilEventCommand(
                name="Wait for sunset",
                event=AstronomicalEvent.SUNSET,
                latitude=latitude,
                longitude=longitude,
            ),
            GoToTargetCommand(
                name="Slew to target",
                ra=83.8221,  # M42 RA
                dec=-5.3911,  # M42 Dec
                target_name="M42 (Orion Nebula)",
            ),
            StartImagingCommand(
                name="Start imaging",
                exposure_time=600.0,  # 10 minute exposures
                gain=120,
            ),
            WaitUntilEventCommand(
                name="Wait until dawn",
                event=AstronomicalEvent.ASTRONOMICAL_DAWN,
                latitude=latitude,
                longitude=longitude,
            ),
            StopImagingCommand(name="Stop imaging"),
        ],
    )


def create_multi_target_sequence() -> Sequence:
    """Create a sequence that images multiple targets.

    This sequence uses nested SequenceCommand to organize steps.

    Returns:
        Sequence: A configured multi-target sequence
    """
    # Helper function to create a target imaging sub-sequence
    def create_target_sequence(name: str, ra: float, dec: float, duration_minutes: float) -> SequenceCommand:
        return SequenceCommand(
            name=f"Image {name}",
            description=f"Complete imaging sequence for {name}",
            commands=[
                GoToTargetCommand(
                    name=f"Slew to {name}",
                    ra=ra,
                    dec=dec,
                    target_name=name,
                ),
                StartImagingCommand(
                    name=f"Start imaging {name}",
                    exposure_time=300.0,
                    gain=100,
                ),
                WaitMinutesCommand(
                    name=f"Image {name} for {duration_minutes} minutes",
                    minutes=duration_minutes,
                ),
                StopImagingCommand(name=f"Stop imaging {name}"),
            ],
        )

    return Sequence(
        name="Multi-Target Imaging",
        description="Image multiple deep sky objects in sequence",
        commands=[
            WaitUntilEventCommand(
                name="Wait for astronomical dusk",
                event=AstronomicalEvent.ASTRONOMICAL_DUSK,
                latitude=37.7749,
                longitude=-122.4194,
            ),
            create_target_sequence("M31 (Andromeda)", 10.6847, 41.2689, 90),
            create_target_sequence("M42 (Orion Nebula)", 83.8221, -5.3911, 60),
            create_target_sequence("M45 (Pleiades)", 56.75, 24.1167, 45),
        ],
    )


def create_timed_sequence() -> Sequence:
    """Create a sequence that starts at a specific time.

    Returns:
        Sequence: A configured timed sequence
    """
    # Start imaging at 10 PM tonight
    tonight_10pm = datetime.now().replace(hour=22, minute=0, second=0, microsecond=0)
    if tonight_10pm < datetime.now():
        tonight_10pm += timedelta(days=1)

    return Sequence(
        name="Timed Imaging Session",
        description="Start imaging at a specific time",
        commands=[
            WaitUntilTimeCommand(
                name="Wait until 10 PM",
                target_time=tonight_10pm,
            ),
            GoToTargetCommand(
                name="Slew to NGC 7000",
                ra=312.25,
                dec=44.5,
                target_name="NGC 7000 (North America Nebula)",
            ),
            StartImagingCommand(
                name="Start imaging",
                exposure_time=600.0,
                gain=100,
                count=30,  # 30 x 10min = 5 hours
            ),
            WaitMinutesCommand(name="Image for 5 hours", minutes=300),
            StopImagingCommand(name="Stop imaging"),
        ],
    )


# Example of saving and loading sequences
if __name__ == "__main__":
    # Create a sequence
    seq = create_simple_imaging_sequence()

    # Save to JSON
    json_str = seq.to_json(file_path="simple_imaging.json")
    print("Saved sequence to simple_imaging.json")
    print(f"\nJSON:\n{json_str}")

    # Load from JSON
    loaded_seq = Sequence.from_json(file_path="simple_imaging.json")
    print(f"\nLoaded sequence: {loaded_seq.name}")
    print(f"Number of commands: {len(loaded_seq.commands)}")
