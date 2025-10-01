"""Base classes for sequencer commands."""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class CommandStatus(str, Enum):
    """Status of a command execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class Command(BaseModel, ABC):
    """Base class for all sequencer commands.

    All commands inherit from this class and must implement the execute method.
    Commands can be serialized to/from JSON using Pydantic.
    """

    name: str = Field(..., description="Name of the command")
    description: Optional[str] = Field(None, description="Optional description of the command")
    status: CommandStatus = Field(default=CommandStatus.PENDING, description="Current execution status")
    error: Optional[str] = Field(None, description="Error message if command failed")
    started_at: Optional[datetime] = Field(None, description="When the command started executing")
    completed_at: Optional[datetime] = Field(None, description="When the command completed")

    class Config:
        """Pydantic configuration."""

        use_enum_values = False

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> None:
        """Execute the command.

        Args:
            context: Execution context containing telescope client, state, etc.

        Raises:
            Exception: If command execution fails
        """
        pass

    async def cancel(self) -> None:
        """Cancel the command execution.

        Override this method if the command needs custom cancellation logic.
        """
        if self.status == CommandStatus.RUNNING:
            self.status = CommandStatus.CANCELLED

    async def pause(self) -> None:
        """Pause the command execution.

        Override this method if the command supports pausing.
        """
        if self.status == CommandStatus.RUNNING:
            self.status = CommandStatus.PAUSED

    async def resume(self) -> None:
        """Resume the command execution.

        Override this method if the command supports resuming.
        """
        if self.status == CommandStatus.PAUSED:
            self.status = CommandStatus.RUNNING

    def mark_started(self) -> None:
        """Mark the command as started."""
        self.status = CommandStatus.RUNNING
        self.started_at = datetime.utcnow()

    def mark_completed(self) -> None:
        """Mark the command as completed."""
        self.status = CommandStatus.COMPLETED
        self.completed_at = datetime.utcnow()

    def mark_failed(self, error: str) -> None:
        """Mark the command as failed.

        Args:
            error: Error message
        """
        self.status = CommandStatus.FAILED
        self.error = error
        self.completed_at = datetime.utcnow()
