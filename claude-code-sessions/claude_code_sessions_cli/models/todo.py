"""Todo model for Claude Code sessions."""
from enum import Enum
from typing import Optional
from .base import CLIModel


class TodoStatus(str, Enum):
    """Status of a todo item."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class Todo(CLIModel):
    """A todo item from a session."""

    id: Optional[str] = None
    content: str
    active_form: Optional[str] = None
    status: TodoStatus = TodoStatus.PENDING
    priority: Optional[str] = None


class TodoSummary(CLIModel):
    """Summary view of a todo for list commands."""

    id: Optional[str] = None
    session_id: str
    project: str
    content: str
    active_form: Optional[str] = None
    status: str
    priority: Optional[str] = None
