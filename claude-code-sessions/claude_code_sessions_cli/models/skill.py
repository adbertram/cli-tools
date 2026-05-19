"""Skill/command invocation model for Claude Code sessions."""
from typing import Optional
from .base import CLIModel


class SkillInvocation(CLIModel):
    """A skill or command invocation (e.g., /start-post-pipeline)."""

    id: str
    session_id: str
    project: str
    timestamp: str
    name: str  # e.g., "start-post-pipeline", "commit", "clear"
    args: Optional[str] = None
    message: Optional[str] = None
