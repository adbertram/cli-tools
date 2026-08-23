"""Todo models for DeepSeek Harness sessions.

dsh writes the whole list on every `todo/write` event. The last such event in a
session is the final state; earlier ones are superseded.
"""
from enum import Enum
from typing import Optional

from .base import CLIModel


class TodoStatus(str, Enum):
    """Status of a todo item."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class Todo(CLIModel):
    """A todo item from the final `todo/write` event of a session."""

    id: str
    content: str
    status: TodoStatus = TodoStatus.PENDING
    position: int = 0


class TodoSummary(CLIModel):
    """Summary view of a todo for list commands."""

    id: str
    session_id: str
    project: str
    content: str
    status: str
    position: int = 0
    written_at: Optional[str] = None
