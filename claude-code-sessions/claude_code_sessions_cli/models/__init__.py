"""Claude Code Sessions CLI models.

All command entities are defined here as Pydantic models for consistent
typing, validation, and JSON serialization.

Model Architecture:
- CLIModel: Base class with CLI-friendly configuration
- Project: A Claude Code project directory
- Session/SessionSummary: Session data
- Message: Messages in a conversation
- ToolCall: Tool invocations with results
- Subagent: Subagent invocations via Task tool
- Todo: Todo items from sessions
"""
from .base import CLIModel
from .project import Project
from .tool_call import ToolCall, ToolCallStatus, ToolCallSummary
from .message import Message
from .todo import Todo, TodoStatus, TodoSummary
from .subagent import Subagent, SubagentSummary
from .session import Session, SessionSummary
from .skill import SkillInvocation
from .timeline import TimelineEntry, TimelineEventType
from .conversation import ConversationSummary
from .search import SearchResult, SearchMatch

__all__ = [
    # Base
    "CLIModel",
    # Project
    "Project",
    # Session
    "Session",
    "SessionSummary",
    # Message
    "Message",
    # Tool calls
    "ToolCall",
    "ToolCallStatus",
    "ToolCallSummary",
    # Subagent
    "Subagent",
    "SubagentSummary",
    # Todo
    "Todo",
    "TodoStatus",
    "TodoSummary",
    # Skill
    "SkillInvocation",
    # Timeline
    "TimelineEntry",
    "TimelineEventType",
    # Conversation
    "ConversationSummary",
    # Search
    "SearchResult",
    "SearchMatch",
]
