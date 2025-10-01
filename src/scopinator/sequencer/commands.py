"""Sequencer command implementations."""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional

from astropy.coordinates import EarthLocation
from pydantic import Field

from scopinator.sequencer.base import Command, CommandStatus
from scopinator.sequencer.events import AstronomicalEvent, calculate_event_time


class WaitMinutesCommand(Command):
    """Wait for a specified number of minutes."""

    command_type: str = Field(default="WaitMinutesCommand", description="Command type identifier")
    minutes: float = Field(..., description="Number of minutes to wait", gt=0)
    _task: Optional[asyncio.Task] = None

    class Config:
        """Pydantic configuration."""

        arbitrary_types_allowed = True

    async def execute(self, context: dict[str, Any]) -> None:
        """Wait for the specified duration.

        Args:
            context: Execution context
        """
        self.mark_started()
        try:
            await asyncio.sleep(self.minutes * 60)
            self.mark_completed()
        except asyncio.CancelledError:
            self.status = CommandStatus.CANCELLED
            raise
        except Exception as e:
            self.mark_failed(str(e))
            raise

    async def cancel(self) -> None:
        """Cancel the wait."""
        await super().cancel()
        if self._task and not self._task.done():
            self._task.cancel()


class WaitUntilTimeCommand(Command):
    """Wait until a specific date/time."""

    command_type: str = Field(default="WaitUntilTimeCommand", description="Command type identifier")
    target_time: datetime = Field(..., description="Target date/time to wait until")

    async def execute(self, context: dict[str, Any]) -> None:
        """Wait until the target time.

        Args:
            context: Execution context
        """
        self.mark_started()
        try:
            now = datetime.utcnow()
            if self.target_time > now:
                wait_seconds = (self.target_time - now).total_seconds()
                await asyncio.sleep(wait_seconds)
            self.mark_completed()
        except asyncio.CancelledError:
            self.status = CommandStatus.CANCELLED
            raise
        except Exception as e:
            self.mark_failed(str(e))
            raise


class WaitUntilEventCommand(Command):
    """Wait until an astronomical event occurs."""

    command_type: str = Field(default="WaitUntilEventCommand", description="Command type identifier")
    event: AstronomicalEvent = Field(..., description="Astronomical event to wait for")
    latitude: float = Field(..., description="Observer latitude in degrees")
    longitude: float = Field(..., description="Observer longitude in degrees")
    elevation: float = Field(0.0, description="Observer elevation in meters")

    async def execute(self, context: dict[str, Any]) -> None:
        """Wait until the astronomical event occurs.

        Args:
            context: Execution context
        """
        self.mark_started()
        try:
            location = EarthLocation(
                lat=self.latitude,
                lon=self.longitude,
                height=self.elevation,
            )

            event_time = calculate_event_time(self.event, location)
            now = datetime.utcnow()

            if event_time > now:
                wait_seconds = (event_time - now).total_seconds()
                await asyncio.sleep(wait_seconds)

            self.mark_completed()
        except asyncio.CancelledError:
            self.status = CommandStatus.CANCELLED
            raise
        except Exception as e:
            self.mark_failed(str(e))
            raise


class GoToTargetCommand(Command):
    """Slew telescope to a target."""

    command_type: str = Field(default="GoToTargetCommand", description="Command type identifier")
    ra: float = Field(..., description="Right Ascension in degrees")
    dec: float = Field(..., description="Declination in degrees")
    target_name: Optional[str] = Field(None, description="Optional target name")

    async def execute(self, context: dict[str, Any]) -> None:
        """Slew to the target coordinates.

        Args:
            context: Execution context (must contain 'client' key with SeestarClient)
        """
        self.mark_started()
        try:
            client = context.get("client")
            if not client:
                raise ValueError("No telescope client in context")

            # Use the Seestar client to slew to target
            from scopinator.seestar.commands.parameterized import GotoTargetCommand as GotoCmd

            goto_cmd = GotoCmd(ra=self.ra, dec=self.dec, target_name=self.target_name or "Target")
            await client.execute_command(goto_cmd)

            self.mark_completed()
        except Exception as e:
            self.mark_failed(str(e))
            raise


class StartImagingCommand(Command):
    """Start imaging session."""

    command_type: str = Field(default="StartImagingCommand", description="Command type identifier")
    exposure_time: float = Field(..., description="Exposure time in seconds", gt=0)
    gain: int = Field(80, description="Camera gain", ge=0, le=200)
    count: Optional[int] = Field(None, description="Number of exposures (None = unlimited)")

    async def execute(self, context: dict[str, Any]) -> None:
        """Start imaging.

        Args:
            context: Execution context (must contain 'imaging_client' key)
        """
        self.mark_started()
        try:
            imaging_client = context.get("imaging_client")
            if not imaging_client:
                raise ValueError("No imaging client in context")

            # Start imaging using the imaging client
            # Note: Actual implementation depends on SeestarImagingClient API
            # This is a placeholder for the actual imaging start logic
            await imaging_client.start_imaging(
                exposure_time=self.exposure_time,
                gain=self.gain,
                count=self.count,
            )

            self.mark_completed()
        except Exception as e:
            self.mark_failed(str(e))
            raise


class StopImagingCommand(Command):
    """Stop imaging session."""

    command_type: str = Field(default="StopImagingCommand", description="Command type identifier")

    async def execute(self, context: dict[str, Any]) -> None:
        """Stop imaging.

        Args:
            context: Execution context (must contain 'imaging_client' key)
        """
        self.mark_started()
        try:
            imaging_client = context.get("imaging_client")
            if not imaging_client:
                raise ValueError("No imaging client in context")

            # Stop imaging using the imaging client
            await imaging_client.stop_imaging()

            self.mark_completed()
        except Exception as e:
            self.mark_failed(str(e))
            raise


class SequenceCommand(Command):
    """A command that contains a sequence of other commands.

    This allows building hierarchical sequences where a step can itself
    be a sequence of steps.
    """

    command_type: str = Field(default="SequenceCommand", description="Command type identifier")
    commands: list[Command] = Field(default_factory=list, description="List of commands to execute")
    stop_on_error: bool = Field(True, description="Stop sequence if a command fails")

    async def execute(self, context: dict[str, Any]) -> None:
        """Execute all commands in sequence.

        Args:
            context: Execution context
        """
        self.mark_started()
        try:
            for cmd in self.commands:
                if self.status == CommandStatus.CANCELLED:
                    break

                await cmd.execute(context)

                if cmd.status == CommandStatus.FAILED and self.stop_on_error:
                    self.mark_failed(f"Command '{cmd.name}' failed: {cmd.error}")
                    return

            self.mark_completed()
        except asyncio.CancelledError:
            self.status = CommandStatus.CANCELLED
            raise
        except Exception as e:
            self.mark_failed(str(e))
            raise

    async def cancel(self) -> None:
        """Cancel all commands in the sequence."""
        await super().cancel()
        for cmd in self.commands:
            if cmd.status == CommandStatus.RUNNING:
                await cmd.cancel()

    async def pause(self) -> None:
        """Pause the sequence."""
        await super().pause()
        for cmd in self.commands:
            if cmd.status == CommandStatus.RUNNING:
                await cmd.pause()

    async def resume(self) -> None:
        """Resume the sequence."""
        await super().resume()
        for cmd in self.commands:
            if cmd.status == CommandStatus.PAUSED:
                await cmd.resume()
