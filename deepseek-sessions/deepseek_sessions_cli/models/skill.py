"""Skill and slash-command invocation model for DeepSeek Harness sessions.

Two dsh records surface here:
- a `tool/call` named `skill`, whose arguments carry the skill `name`;
- a `command/run` slash command (for example `permission`, `goal`), paired with
  its `command/done` outcome.
"""
from typing import Optional

from .base import CLIModel


class SkillInvocation(CLIModel):
    """A skill load or slash-command invocation."""

    id: str
    session_id: str
    project: str
    timestamp: str
    kind: str  # "skill" or "command"
    name: str
    args: Optional[str] = None
    status: Optional[str] = None
    result: Optional[str] = None
    turn: Optional[int] = None
    step: Optional[int] = None
