"""Project model for Claude Code sessions."""
from typing import Optional
from .base import CLIModel


class Project(CLIModel):
    """A Claude Code project (directory with sessions)."""

    name: str
    full_path: str
    encoded_path: str
    session_count: int
    last_activity: Optional[str] = None
