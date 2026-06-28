"""Session models for Claude Code sessions."""
from typing import Optional, List, Dict, Any
from pydantic import computed_field
from .base import CLIModel
from .message import Message
from .subagent import Subagent
from .todo import Todo


class SessionSummary(CLIModel):
    """Summary view of a session for list commands."""

    id: str
    custom_title: Optional[str] = None
    project: str
    project_path: str = ""
    created_at: str
    last_activity: str
    message_count: int
    tool_call_count: int
    has_errors: bool = False
    has_subagents: bool = False
    # Token usage totals
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    # Conversation tracking
    conversation_count: int = 1  # Number of conversations in session (default 1)
    current_conversation_id: int = 1  # Latest conversation number (1, 2, 3...)

    @computed_field
    @property
    def effective_tokens(self) -> int:
        """
        Calculate effective token cost for Claude Max tracking.

        total_input_tokens = base_input + cache_read + cache_creation
        Effective = base_input + output + cache_creation + (cache_read * 0.1)
                  = total_input + output - (cache_read * 0.9)

        Cache read tokens are 90% cheaper, so we discount them by 90%.
        """
        return (
            self.total_input_tokens
            + self.total_output_tokens
            - int(self.total_cache_read_tokens * 0.9)
        )


class Session(CLIModel):
    """Full session with all messages, tool calls, and metadata."""

    id: str
    project: str
    project_path: str = ""
    created_at: str
    last_activity: str
    claude_code_version: Optional[str] = None
    model: Optional[str] = None
    git_branch: Optional[str] = None
    cwd: Optional[str] = None
    messages: List[Message] = []
    subagents: Dict[str, Subagent] = {}
    todos: List[Todo] = []
    errors: List[Dict[str, Any]] = []
