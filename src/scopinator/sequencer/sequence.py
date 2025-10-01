"""Sequence management and execution."""

import asyncio
import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from scopinator.sequencer.base import Command, CommandStatus
from scopinator.sequencer.commands import (
    GoToTargetCommand,
    SequenceCommand,
    StartImagingCommand,
    StopImagingCommand,
    WaitMinutesCommand,
    WaitUntilEventCommand,
    WaitUntilTimeCommand,
)


class SequenceState(str, Enum):
    """State of sequence execution."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Sequence(BaseModel):
    """A sequence of commands for telescope and imaging automation.

    Sequences can be saved to and loaded from JSON files.
    """

    name: str = Field(..., description="Name of the sequence")
    description: Optional[str] = Field(None, description="Description of the sequence")
    commands: list[Command] = Field(default_factory=list, description="List of commands to execute")
    state: SequenceState = Field(default=SequenceState.IDLE, description="Current sequence state")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="When sequence was created")
    started_at: Optional[datetime] = Field(None, description="When sequence started")
    completed_at: Optional[datetime] = Field(None, description="When sequence completed")
    current_command_index: int = Field(0, description="Index of currently executing command")
    _execution_task: Optional[asyncio.Task] = None

    class Config:
        """Pydantic configuration."""

        arbitrary_types_allowed = True
        use_enum_values = False

    async def start(self, context: dict[str, Any]) -> None:
        """Start executing the sequence.

        Args:
            context: Execution context containing telescope client, state, etc.

        Raises:
            RuntimeError: If sequence is already running
        """
        if self.state == SequenceState.RUNNING:
            raise RuntimeError("Sequence is already running")

        self.state = SequenceState.RUNNING
        self.started_at = datetime.utcnow()
        self._execution_task = asyncio.create_task(self._execute(context))

    async def stop(self) -> None:
        """Stop the sequence execution."""
        if self.state == SequenceState.RUNNING:
            self.state = SequenceState.CANCELLED

            # Cancel currently running command
            if 0 <= self.current_command_index < len(self.commands):
                current_cmd = self.commands[self.current_command_index]
                if current_cmd.status == CommandStatus.RUNNING:
                    await current_cmd.cancel()

            if self._execution_task and not self._execution_task.done():
                self._execution_task.cancel()
                try:
                    await self._execution_task
                except asyncio.CancelledError:
                    pass

            self.completed_at = datetime.utcnow()

    async def pause(self) -> None:
        """Pause the sequence execution."""
        if self.state == SequenceState.RUNNING:
            self.state = SequenceState.PAUSED

            # Pause currently running command
            if 0 <= self.current_command_index < len(self.commands):
                current_cmd = self.commands[self.current_command_index]
                if current_cmd.status == CommandStatus.RUNNING:
                    await current_cmd.pause()

    async def resume(self, context: dict[str, Any]) -> None:
        """Resume the sequence execution.

        Args:
            context: Execution context

        Raises:
            RuntimeError: If sequence is not paused
        """
        if self.state != SequenceState.PAUSED:
            raise RuntimeError("Sequence is not paused")

        self.state = SequenceState.RUNNING

        # Resume currently paused command
        if 0 <= self.current_command_index < len(self.commands):
            current_cmd = self.commands[self.current_command_index]
            if current_cmd.status == CommandStatus.PAUSED:
                await current_cmd.resume()

        # Restart execution task
        self._execution_task = asyncio.create_task(self._execute(context))

    async def _execute(self, context: dict[str, Any]) -> None:
        """Internal execution loop.

        Args:
            context: Execution context
        """
        try:
            while self.current_command_index < len(self.commands):
                if self.state == SequenceState.CANCELLED:
                    break

                if self.state == SequenceState.PAUSED:
                    # Wait until resumed
                    while self.state == SequenceState.PAUSED:
                        await asyncio.sleep(0.1)

                cmd = self.commands[self.current_command_index]

                # Skip already completed commands (in case of resume)
                if cmd.status == CommandStatus.COMPLETED:
                    self.current_command_index += 1
                    continue

                try:
                    await cmd.execute(context)

                    if cmd.status == CommandStatus.FAILED:
                        self.state = SequenceState.FAILED
                        self.completed_at = datetime.utcnow()
                        return

                except asyncio.CancelledError:
                    self.state = SequenceState.CANCELLED
                    raise
                except Exception as e:
                    cmd.mark_failed(str(e))
                    self.state = SequenceState.FAILED
                    self.completed_at = datetime.utcnow()
                    raise

                self.current_command_index += 1

            if self.state == SequenceState.RUNNING:
                self.state = SequenceState.COMPLETED
                self.completed_at = datetime.utcnow()

        except asyncio.CancelledError:
            self.state = SequenceState.CANCELLED
            self.completed_at = datetime.utcnow()

    def to_json(self, file_path: Optional[str] = None) -> str:
        """Serialize sequence to JSON.

        Args:
            file_path: Optional path to save JSON file

        Returns:
            str: JSON representation of the sequence
        """
        # Use Pydantic's model_dump with custom serialization
        data = self.model_dump(mode="json", exclude={"_execution_task"})

        # Convert to JSON string
        json_str = json.dumps(data, indent=2, default=str)

        # Optionally save to file
        if file_path:
            Path(file_path).write_text(json_str)

        return json_str

    @classmethod
    def from_json(cls, json_str: Optional[str] = None, file_path: Optional[str] = None) -> "Sequence":
        """Deserialize sequence from JSON.

        Args:
            json_str: JSON string to deserialize
            file_path: Optional path to load JSON file from

        Returns:
            Sequence: Deserialized sequence

        Raises:
            ValueError: If neither json_str nor file_path is provided
        """
        if file_path:
            json_str = Path(file_path).read_text()
        elif json_str is None:
            raise ValueError("Either json_str or file_path must be provided")

        data = json.loads(json_str)

        # Reconstruct command objects from discriminated union
        commands = []
        for cmd_data in data.get("commands", []):
            cmd_type = cmd_data.get("name")  # Use name field to determine type
            # You could also add a 'type' field for more explicit typing

            # Map command data to appropriate class
            # This is a simple approach - for production use discriminated unions
            commands.append(_deserialize_command(cmd_data))

        data["commands"] = commands
        return cls(**data)


def _deserialize_command(cmd_data: dict[str, Any]) -> Command:
    """Deserialize a command from dictionary.

    Args:
        cmd_data: Command data dictionary

    Returns:
        Command: Deserialized command instance
    """
    # Map of command types - in production, use Pydantic discriminated unions
    command_classes = {
        "WaitMinutesCommand": WaitMinutesCommand,
        "WaitUntilTimeCommand": WaitUntilTimeCommand,
        "WaitUntilEventCommand": WaitUntilEventCommand,
        "GoToTargetCommand": GoToTargetCommand,
        "StartImagingCommand": StartImagingCommand,
        "StopImagingCommand": StopImagingCommand,
        "SequenceCommand": SequenceCommand,
    }

    # Determine command type from the data
    # Try to infer from field presence or use explicit 'command_type' field
    cmd_type = cmd_data.get("command_type")

    if not cmd_type:
        # Infer type from fields
        if "minutes" in cmd_data:
            cmd_type = "WaitMinutesCommand"
        elif "target_time" in cmd_data:
            cmd_type = "WaitUntilTimeCommand"
        elif "event" in cmd_data:
            cmd_type = "WaitUntilEventCommand"
        elif "ra" in cmd_data and "dec" in cmd_data:
            cmd_type = "GoToTargetCommand"
        elif "exposure_time" in cmd_data:
            cmd_type = "StartImagingCommand"
        elif "commands" in cmd_data:
            cmd_type = "SequenceCommand"
        else:
            cmd_type = "StopImagingCommand"

    command_class = command_classes.get(cmd_type)
    if not command_class:
        raise ValueError(f"Unknown command type: {cmd_type}")

    # Handle nested commands for SequenceCommand
    if cmd_type == "SequenceCommand":
        nested_commands = [_deserialize_command(c) for c in cmd_data.get("commands", [])]
        cmd_data["commands"] = nested_commands

    return command_class(**cmd_data)
