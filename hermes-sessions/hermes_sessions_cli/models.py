"""Output models for the Hermes Sessions CLI.

Each model is the documented shape of one command's JSON rows. Text fields are
always bounded previews produced by `parsers.preview`; no model carries a raw
transcript.
"""
from typing import List, Optional

from cli_tools_shared.models import CLIModel


class TokenTotals(CLIModel):
    """Token and cost counters shared by session-shaped rows."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    # Cost-weighted total: input + output + (cache_read x 0.1). Hermes counts
    # `input_tokens` as uncached input, so cache reads must be added back
    # explicitly rather than assumed to be included.
    effective_tokens: int = 0
    estimated_cost_usd: float = 0.0


class Project(CLIModel):
    """A workspace directory that has Hermes sessions."""

    name: str
    full_path: Optional[str] = None
    session_count: int = 0
    subagent_session_count: int = 0
    message_count: int = 0
    tool_call_count: int = 0
    first_activity: Optional[str] = None
    last_activity: Optional[str] = None


class SessionSummary(TokenTotals):
    """Summary view of a session for list commands."""

    id: str
    title: Optional[str] = None
    # How the title was set: "llm", "user", or "derived".
    title_source: Optional[str] = None
    project: str
    project_path: Optional[str] = None
    # Gateway/runtime origin: cli, cron, slack, subagent, webui, email, ...
    source: str
    profile: Optional[str] = None
    model: Optional[str] = None
    created_at: str
    last_activity: str
    ended_at: Optional[str] = None
    end_reason: Optional[str] = None
    parent_session: Optional[str] = None
    is_subagent: bool = False
    subagent_count: int = 0
    message_count: int = 0
    tool_call_count: int = 0
    api_call_count: int = 0
    turn_count: int = 0
    conversation_count: int = 1
    archived: bool = False
    hidden: bool = False
    pinned: bool = False


class Session(SessionSummary):
    """Full session detail: metadata and counts, never message bodies."""

    cwd: Optional[str] = None
    chat_type: Optional[str] = None
    user_id: Optional[str] = None
    todo_count: int = 0
    skill_count: int = 0
    error_count: int = 0
    compacted_message_count: int = 0
    has_system_prompt: bool = False
    tool_names: List[str] = []
    # Exact number of messages stored for this session.
    stored_message_count: int = 0
    # Message-derived views read the newest `message_window_size` messages.
    # `message_window_truncated` is True when older messages exist outside it,
    # so a windowed view is never mistaken for a complete transcript.
    message_window_size: int = 0
    message_window_truncated: bool = False
    first_user_prompt: Optional[str] = None
    last_assistant_message: Optional[str] = None


class Conversation(CLIModel):
    """One context segment of a session, bounded by context compaction."""

    id: str
    session_id: str
    index: int
    # "session_start" for the first segment, "compaction" for every later one.
    started_by: str
    started_at: str
    ended_at: Optional[str] = None
    message_count: int = 0
    user_message_count: int = 0
    tool_call_count: int = 0
    first_user_prompt: Optional[str] = None


class Turn(CLIModel):
    """One user prompt and the assistant work it produced."""

    id: str
    session_id: str
    index: int
    started_at: str
    ended_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    user_prompt: Optional[str] = None
    assistant_message_count: int = 0
    tool_call_count: int = 0
    tools_used: List[str] = []
    finish_reason: Optional[str] = None
    has_errors: bool = False


class ToolCall(CLIModel):
    """One tool invocation and its result."""

    id: str
    session_id: str
    turn: Optional[int] = None
    tool: str
    timestamp: str
    status: str
    duration_seconds: Optional[float] = None
    arguments: Optional[str] = None
    result: Optional[str] = None


class Todo(CLIModel):
    """One item of a session's final todo list."""

    id: str
    session_id: str
    position: int
    content: str
    status: str
    updated_at: str


class Skill(CLIModel):
    """A skill load or a slash command invocation."""

    id: str
    session_id: str
    # "skill" for a skill tool load, "command" for a slash command.
    kind: str
    name: str
    timestamp: str
    status: str
    detail: Optional[str] = None


class SubagentActivity(CLIModel):
    """One delegated subagent run."""

    id: str
    parent_session: Optional[str] = None
    child_session: Optional[str] = None
    label: Optional[str] = None
    status: str
    started_at: str
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    model: Optional[str] = None
    message_count: int = 0
    tool_call_count: int = 0
    effective_tokens: int = 0
    result: Optional[str] = None


class TimelineEvent(CLIModel):
    """One chronological event in a session or consolidated view."""

    index: int
    session_id: str
    # Set on consolidated views when the event came from a child session.
    subagent_session: Optional[str] = None
    timestamp: str
    event_type: str
    actor: str
    tool: Optional[str] = None
    status: Optional[str] = None
    summary: Optional[str] = None


class SearchMatch(CLIModel):
    """One message matching a full-text search."""

    id: str
    session_id: str
    session_title: Optional[str] = None
    project: str
    role: str
    tool: Optional[str] = None
    timestamp: str
    snippet: Optional[str] = None


__all__ = [
    "Conversation",
    "Project",
    "SearchMatch",
    "Session",
    "SessionSummary",
    "Skill",
    "SubagentActivity",
    "TimelineEvent",
    "Todo",
    "ToolCall",
    "TokenTotals",
    "Turn",
]
