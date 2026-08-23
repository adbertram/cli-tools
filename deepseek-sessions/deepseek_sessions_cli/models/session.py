"""Session models for DeepSeek Harness sessions."""
from typing import Any, Dict, List, Optional

from .base import CLIModel
from .message import Message
from .subagent import Subagent
from .todo import Todo
from .tokens import TokenTotals


class SessionSummary(TokenTotals):
    """Summary view of a session for list commands."""

    id: str
    custom_title: Optional[str] = None
    # How the title was set: "provider" (model-generated), "user", or
    # "fallback" (first prompt text, used when no model title was produced).
    title_source: Optional[str] = None
    project: str
    project_path: str = ""
    created_at: str
    last_activity: str
    # Model from the most recent assistant turn (None when none was recorded).
    model: Optional[str] = None
    provider: Optional[str] = None
    # dsh session-header fields with no Claude Code equivalent.
    origin: Optional[str] = None  # "subagent" for a spawned session
    parent_session: Optional[str] = None
    delegation_depth: int = 0
    agent_preset: Optional[str] = None
    # For origin == "subagent": the descriptor label the parent gave it.
    subagent_label: Optional[str] = None
    message_count: int
    tool_call_count: int
    turn_count: int = 0
    # Completed model round-trips, matching dsh's own `sessionStats.steps`.
    step_count: int = 0
    # Steps that started but never closed, because the session was killed or
    # abandoned mid-request. dsh tracks the same state as `openStep`.
    open_step_count: int = 0
    retry_count: int = 0
    has_errors: bool = False
    has_subagents: bool = False
    # A trailing partial Zstandard frame was dropped while reading this log.
    truncated: bool = False
    conversation_count: int = 1
    current_conversation_id: int = 1


class Session(CLIModel):
    """Full session with messages, tool calls, and metadata."""

    id: str
    custom_title: Optional[str] = None
    project: str
    project_path: str = ""
    created_at: str
    last_activity: str
    format_version: Optional[int] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    context_window: Optional[int] = None
    cwd: Optional[str] = None
    origin: Optional[str] = None
    parent_session: Optional[str] = None
    delegation_depth: int = 0
    agent_preset: Optional[str] = None
    subagent_label: Optional[str] = None
    permission_preset: Optional[str] = None
    sandbox_mode: Optional[str] = None
    approval_policy: Optional[str] = None
    truncated: bool = False
    messages: List[Message] = []
    subagents: Dict[str, Subagent] = {}
    todos: List[Todo] = []
    errors: List[Dict[str, Any]] = []
