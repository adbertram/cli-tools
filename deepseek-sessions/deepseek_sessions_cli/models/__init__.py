"""DeepSeek Sessions CLI models.

All command entities are Pydantic models for consistent typing, validation, and
JSON serialization.

Model architecture:
- CLIModel: base class with CLI-friendly configuration
- TokenTotals: the four dsh usage counters plus the weighted effective total
- Project / Session / Message / ToolCall / Subagent / Todo / Skill: the
  claude-code-sessions parity entities
- Turn / Step / Retry / Approval / Goal: dsh-native entities with no Claude
  Code counterpart
"""
from .base import CLIModel
from .conversation import ConversationDetail, ConversationSummary
from .message import Message
from .operations import ApprovalSummary, GoalSummary, RetrySummary
from .project import Project
from .search import SearchMatch, SearchResult
from .session import Session, SessionSummary
from .skill import SkillInvocation
from .subagent import Subagent, SubagentSummary
from .timeline import TimelineEntry, TimelineEventType
from .todo import Todo, TodoStatus, TodoSummary
from .tokens import CACHE_READ_WEIGHT, TokenTotals
from .tool_call import ToolCall, ToolCallStatus, ToolCallSummary
from .turn import StepSummary, TurnSummary

__all__ = [
    "CLIModel",
    "TokenTotals",
    "CACHE_READ_WEIGHT",
    "Project",
    "Session",
    "SessionSummary",
    "Message",
    "ToolCall",
    "ToolCallStatus",
    "ToolCallSummary",
    "Subagent",
    "SubagentSummary",
    "Todo",
    "TodoStatus",
    "TodoSummary",
    "SkillInvocation",
    "TimelineEntry",
    "TimelineEventType",
    "ConversationDetail",
    "ConversationSummary",
    "SearchResult",
    "SearchMatch",
    "TurnSummary",
    "StepSummary",
    "RetrySummary",
    "ApprovalSummary",
    "GoalSummary",
]
