"""Conversation models for DeepSeek Harness sessions.

dsh has no `/clear`. The equivalent boundary is compaction: when the context is
compacted, the surviving history is replaced by a summary and the session
continues. A conversation is therefore the run of turns between compactions,
numbered from 1. A session that was never compacted has exactly one
conversation.
"""
from typing import Dict, List, Optional

from .base import CLIModel
from .tokens import TokenTotals


class ConversationSummary(TokenTotals):
    """A compaction-delimited segment of a session."""

    session_id: str
    project: str
    conversation_id: int  # sequential, starting at 1

    model: Optional[str] = None

    message_count: int
    user_message_count: int
    assistant_message_count: int
    tool_call_count: int = 0
    turn_count: int = 0

    created_at: str
    ended_at: Optional[str] = None

    # How this segment began: "session-start" for the first one, otherwise
    # "compaction".
    started_by: str = "session-start"
    # Summary text dsh recorded when compacting into this segment.
    compaction_summary: Optional[str] = None


class ConversationDetail(ConversationSummary):
    """Conversation metadata plus its user and assistant message content."""

    messages: List[Dict[str, str]]
