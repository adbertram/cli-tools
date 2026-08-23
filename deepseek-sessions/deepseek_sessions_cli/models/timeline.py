"""Timeline entry model for DeepSeek Harness sessions."""
from enum import Enum
from typing import Any, Dict, Optional

from .base import CLIModel


class TimelineEventType(str, Enum):
    """Type of timeline event."""

    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    THINKING = "thinking"            # assistant reasoning block
    NOTICE = "notice"                # inbox notice (subagent settled, goal, jobs)
    SKILL_LOAD = "skill_load"        # `skill` tool call
    COMMAND = "command"              # slash command (`command/run`)
    TOOL_CALL = "tool_call"
    CODE_DISPATCH = "code_dispatch"  # sub-call inside a run_code tool call
    SUBAGENT_START = "subagent_start"
    SUBAGENT_TOOL = "subagent_tool"  # tool call inside a subagent session
    TODO_WRITE = "todo_write"
    GOAL_CHANGE = "goal_change"
    APPROVAL = "approval"
    RETRY = "retry"
    COMPACTION = "compaction"
    TURN_END = "turn_end"
    ERROR = "error"


class TimelineEntry(CLIModel):
    """A single entry in the session timeline."""

    id: str
    session_id: str
    timestamp: str
    event_type: TimelineEventType
    name: str  # tool name, skill name, or subagent label
    model: Optional[str] = None
    status: Optional[str] = None  # success, error, invoked
    agent_id: Optional[str] = None   # subagent session id
    agent_name: Optional[str] = None  # subagent label
    details: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    # Raw dsh usage counters for the assistant message that closed this step.
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    # dsh turn/step structure.
    turn_number: Optional[int] = None
    step_number: Optional[int] = None
    turn_cost: Optional[int] = None       # effective tokens for this turn
    session_total: Optional[int] = None   # cumulative effective tokens
    conversation_id: int = 1
    conversation_total: Optional[int] = None
