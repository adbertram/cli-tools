"""Message model for Claude Code sessions."""
from typing import Optional, List
from .base import CLIModel
from .tool_call import ToolCall


class Message(CLIModel):
    """A message in a conversation (user or assistant)."""

    uuid: str
    parent_uuid: Optional[str] = None
    conversation_id: Optional[int] = None  # Computed during parsing
    type: str  # "user" or "assistant"
    timestamp: str
    content: str
    tool_calls: List[ToolCall] = []
