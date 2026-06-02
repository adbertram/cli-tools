"""Subagent model for Claude Code sessions."""
from typing import Optional, List
from pydantic import computed_field
from .base import CLIModel
from .message import Message


class Subagent(CLIModel):
    """A subagent invocation (via Task tool)."""

    id: str
    type: str  # "Explore", "Bash", etc.
    parent_tool_call_id: str
    model: Optional[str] = None
    prompt: str
    status: str = "completed"
    created_at: str
    completed_at: Optional[str] = None
    messages: List[Message] = []


class SubagentSummary(CLIModel):
    """Summary view of a subagent for list commands."""

    id: str
    session_id: str
    project: str
    timestamp: str
    type: str
    prompt: str
    description: Optional[str] = None
    model: Optional[str] = None
    status: str = "completed"
    message_count: int = 0
    agent_id: Optional[str] = None
    tool_calls: List[dict] = []
    errors: List[dict] = []
    # Token usage totals for this subagent
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0

    @computed_field
    @property
    def effective_tokens(self) -> int:
        """
        Calculate effective token cost for Claude Max tracking.

        total_input_tokens = base_input + cache_read + cache_creation
        Effective = total_input + output - (cache_read * 0.9)

        Cache read tokens are 90% cheaper, so we discount them by 90%.
        """
        return (
            self.total_input_tokens
            + self.total_output_tokens
            - int(self.total_cache_read_tokens * 0.9)
        )
