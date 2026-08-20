"""Subagent models for DeepSeek Harness sessions.

A dsh subagent is a full session of its own, written to its own log file in the
same project directory. Two records tie the pair together:

- the parent logs a `tool/call` named `subagent`, and its `tool/result` text
  reads `started subagent <child session id>`;
- the child's session header carries `origin: "subagent"`, `parentSession`,
  and `delegationDepth`, and its first event is a `subagent/descriptor` holding
  the label and the model the parent assigned.
"""
from typing import List, Optional

from .base import CLIModel
from .message import Message
from .tokens import TokenTotals


class Subagent(CLIModel):
    """A subagent invocation with its full child-session messages."""

    id: str  # the child session id
    label: str
    parent_session_id: str
    parent_tool_call_id: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    mode: Optional[str] = None
    prompt: str = ""
    description: Optional[str] = None
    status: str = "completed"
    created_at: str
    completed_at: Optional[str] = None
    messages: List[Message] = []


class SubagentSummary(TokenTotals):
    """Summary view of a subagent invocation for list commands."""

    id: str
    session_id: str  # the child session id
    parent_session_id: str
    project: str
    timestamp: str
    label: str
    parent_tool_call_id: Optional[str] = None
    prompt: str = ""
    description: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    mode: Optional[str] = None
    agent_preset: Optional[str] = None
    delegation_depth: int = 1
    status: str = "completed"
    message_count: int = 0
    tool_call_count: int = 0
    turn_count: int = 0
    retry_count: int = 0
    error_count: int = 0
    # The child's own `report` tool output, when it produced one.
    report: Optional[str] = None
