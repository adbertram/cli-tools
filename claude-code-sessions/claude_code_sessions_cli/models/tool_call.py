"""Tool call models for Claude Code sessions."""
from enum import Enum
from typing import Optional, Dict, Any
from .base import CLIModel


class ToolCallStatus(str, Enum):
    """Status of a tool call execution."""

    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ToolCall(CLIModel):
    """A single tool call within a message."""

    id: str
    tool: str
    status: ToolCallStatus = ToolCallStatus.SUCCESS
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    input: Dict[str, Any] = {}
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


class ToolCallSummary(CLIModel):
    """Summary view of a tool call for list commands."""

    id: str
    session_id: str
    project: str
    timestamp: str
    tool: str
    status: str
    is_sidechain: bool = False
    parent_tool_call_id: Optional[str] = None  # Task tool call ID that spawned this subagent
    input: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
