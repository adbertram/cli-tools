"""Timeline entry model for Claude Code sessions."""
from typing import Optional, Dict, Any
from enum import Enum
from .base import CLIModel


class TimelineEventType(str, Enum):
    """Type of timeline event."""
    USER_MESSAGE = "user_message"     # User prompt/message
    ASSISTANT_MESSAGE = "assistant_message"  # Assistant text response (no tool calls)
    THINKING = "thinking"             # Claude's thinking/reasoning (hidden by default)
    AGENT_WARMUP = "agent_warmup"     # Subagent warmup initialization (not a real user message)
    SKILL = "skill"                   # Skill/command invocation (/start-post-pipeline)
    TOOL_CALL = "tool_call"           # Tool call in main session
    SUBAGENT_START = "subagent_start" # Subagent launched
    SUBAGENT_TOOL = "subagent_tool"   # Tool call inside a subagent
    ERROR = "error"                   # Any error


class TimelineEntry(CLIModel):
    """A single entry in the session timeline."""

    id: str
    session_id: str
    timestamp: str
    event_type: TimelineEventType
    name: str  # Tool name, skill name, or subagent type
    status: Optional[str] = None  # success, error, etc.
    agent_id: Optional[str] = None  # For subagent-related events
    agent_name: Optional[str] = None  # Subagent type (e.g., "Explore", "Bash") for agent tool calls
    details: Optional[Dict[str, Any]] = None  # Additional context
    error_message: Optional[str] = None  # Error details if applicable
    input: Optional[Any] = None  # Tool input/arguments
    output: Optional[Any] = None  # Tool output/result
    # Token usage (raw API values)
    input_tokens: Optional[int] = None  # Base input tokens (excludes cache)
    output_tokens: Optional[int] = None  # Output tokens
    cache_read_tokens: Optional[int] = None  # Tokens read from cache (discounted)
    cache_creation_tokens: Optional[int] = None  # Tokens used to create cache
    # Computed cost metrics for Claude Max tracking
    turn_cost: Optional[int] = None  # Effective tokens for this API turn
    session_total: Optional[int] = None  # Cumulative session cost up to this point
    # Conversation tracking
    conversation_id: int = 1  # Sequential conversation number (1, 2, 3...)
    conversation_total: Optional[int] = None  # Cumulative conversation cost up to this point
