"""Conversation summary model for Claude Code sessions."""
from typing import Optional
from pydantic import computed_field
from .base import CLIModel


class ConversationSummary(CLIModel):
    """Summary of a conversation within a session.

    A conversation is a chain of messages within a session,
    separated by /clear commands or other chain breaks.
    """

    # Identifiers
    session_id: str
    project: str
    conversation_id: int  # Sequential number (1, 2, 3...)

    # Message counts
    message_count: int
    user_message_count: int
    assistant_message_count: int
    tool_call_count: int = 0

    # Timestamps
    created_at: str  # First message timestamp
    ended_at: Optional[str] = None  # Last message timestamp

    # Token usage for this conversation only
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
