"""Models for Codex session transcript data."""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import Field

from .base import CLIModel


class TimelineEventType(str, Enum):
    """Timeline event categories emitted by Codex rollout parsing."""

    SESSION = "session"
    TURN = "turn"
    MESSAGE = "message"
    EVENT = "event"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TODO = "todo"


class Project(CLIModel):
    name: str
    full_path: str
    encoded_path: str
    session_count: int
    last_activity: Optional[str] = None


class SessionSummary(CLIModel):
    id: str = Field(frozen=True)
    project: str
    project_path: str
    created_at: str
    last_activity: str
    message_count: int
    tool_call_count: int
    has_errors: bool
    has_subagents: bool
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read_tokens: int
    total_cache_creation_tokens: int
    conversation_count: int
    current_conversation_id: int
    effective_tokens: int
    path: str
    source: Optional[Any] = None
    cli_version: Optional[str] = None
    model_provider: Optional[str] = None
    git_branch: Optional[str] = None
    git_sha: Optional[str] = None
    git_origin_url: Optional[str] = None


class ConversationSummary(CLIModel):
    id: str = Field(frozen=True)
    session_id: str
    conversation_id: int
    project: str
    project_path: str
    created_at: str
    last_activity: str
    message_count: int
    tool_call_count: int
    summary: Optional[str] = None


class ToolCall(CLIModel):
    id: str = Field(frozen=True)
    session_id: str
    conversation_id: int
    time: str
    tool: str
    name: str
    status: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)
    output: Optional[Any] = None
    cwd: Optional[str] = None
    exit_code: Optional[int] = None


class SubagentActivity(CLIModel):
    id: str = Field(frozen=True)
    session_id: str
    conversation_id: int
    time: str
    agent_type: Optional[str] = None
    name: Optional[str] = None
    message: Optional[str] = None
    status: Optional[str] = None
    agent_id: Optional[str] = None
    output: Optional[Any] = None


class TodoItem(CLIModel):
    id: str = Field(frozen=True)
    session_id: str
    conversation_id: int
    time: str
    content: str
    status: str
    source_call_id: str


class SkillInvocation(CLIModel):
    id: str = Field(frozen=True)
    session_id: str
    conversation_id: int
    time: str
    name: str
    source: str
    text: str


class TimelineEvent(CLIModel):
    id: str = Field(frozen=True)
    time: str
    session_id: str
    event_type: TimelineEventType
    conversation_id: Optional[int] = None
    agent: Optional[str] = None
    name: Optional[str] = None
    status: Optional[str] = None
    role: Optional[str] = None
    text: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    raw_type: Optional[str] = None


class SessionDetail(SessionSummary):
    records: List[Dict[str, Any]] = Field(default_factory=list)
    messages: List[TimelineEvent] = Field(default_factory=list)
    tool_calls: List[ToolCall] = Field(default_factory=list)


def create_project(data: dict) -> Project:
    return Project(**data)


def create_session_summary(data: dict) -> SessionSummary:
    return SessionSummary(**data)


def create_conversation_summary(data: dict) -> ConversationSummary:
    return ConversationSummary(**data)


def create_tool_call(data: dict) -> ToolCall:
    return ToolCall(**data)


def create_subagent_activity(data: dict) -> SubagentActivity:
    return SubagentActivity(**data)


def create_todo_item(data: dict) -> TodoItem:
    return TodoItem(**data)


def create_skill_invocation(data: dict) -> SkillInvocation:
    return SkillInvocation(**data)


def create_timeline_event(data: dict) -> TimelineEvent:
    return TimelineEvent(**data)


def create_session_detail(data: dict) -> SessionDetail:
    return SessionDetail(**data)
