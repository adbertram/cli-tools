"""Tool call models for DeepSeek Harness sessions."""
from enum import Enum
from typing import Any, Dict, Optional

from .base import CLIModel


class ToolCallStatus(str, Enum):
    """Status of a tool call execution."""

    SUCCESS = "success"
    ERROR = "error"
    PENDING = "pending"


class ToolCall(CLIModel):
    """A single tool call within a session.

    `input` is the decoded form of the `tool/call` event's `arguments` string.
    `result` holds the joined text of the matching `tool/result` blocks.
    """

    id: str
    tool: str
    status: ToolCallStatus = ToolCallStatus.PENDING
    turn: Optional[int] = None
    step: Optional[int] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    input: Dict[str, Any] = {}
    result: Optional[str] = None
    error: Optional[Dict[str, Any]] = None


class ToolCallSummary(CLIModel):
    """Summary view of a tool call for list commands."""

    id: str
    session_id: str
    project: str
    timestamp: str
    tool: str
    status: str
    turn: Optional[int] = None
    step: Optional[int] = None
    # True when this row came from a subagent session rather than the session
    # the user drove directly. Named to match claude-code-sessions.
    is_sidechain: bool = False
    # The parent session's `subagent` tool call id that spawned the subagent
    # session this row belongs to.
    parent_tool_call_id: Optional[str] = None
    # Set for run_code sub-calls dispatched inside a parent tool call.
    parent_call_id: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    result: Optional[str] = None
    error: Optional[Dict[str, Any]] = None
