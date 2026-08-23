"""Turn and step models for DeepSeek Harness sessions.

dsh brackets its agent loop explicitly: a `turn/start` opens a turn, each model
round-trip inside it is a `step/start` / `step/end` pair, and `turn/end` closes
the turn with a reason of `completed`, `error`, or `aborted`. Claude Code has no
equivalent record, so this is a dsh-native view.
"""
from typing import Optional

from .base import CLIModel
from .tokens import TokenTotals


class TurnSummary(TokenTotals):
    """One agent turn within a session."""

    id: str
    session_id: str
    project: str
    turn: int
    started_at: str
    ended_at: Optional[str] = None
    duration_ms: Optional[int] = None
    # "completed", "error", "aborted", or None while a turn never closed.
    finish_reason: Optional[str] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    # Completed model round-trips; see SessionSummary.step_count.
    step_count: int = 0
    open_step_count: int = 0
    message_count: int = 0
    tool_call_count: int = 0
    retry_count: int = 0
    conversation_id: int = 1


class StepSummary(CLIModel):
    """One model round-trip inside a turn."""

    id: str
    session_id: str
    project: str
    turn: int
    step: int
    started_at: str
    ended_at: Optional[str] = None
    duration_ms: Optional[int] = None
    model: Optional[str] = None
    tool_call_count: int = 0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
