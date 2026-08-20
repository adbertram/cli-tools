"""dsh-native operational models: retries, approvals, and goals.

None of these have a Claude Code counterpart.

- `llm/retry` fires when a provider call fails a retryable way (timeout, rate
  limit, empty response, transport, server). `llm/retry-started` follows once
  the delay elapses and the attempt actually begins.
- `approval/asked` records a permission escalation the agent requested, and
  `approval/decided` records the outcome.
- `goal/change` records the goal-loop driver creating, advancing, or closing a
  standing objective.
"""
from typing import Optional

from .base import CLIModel


class RetrySummary(CLIModel):
    """One retryable provider failure and its scheduled retry."""

    id: str  # dsh retryId
    session_id: str
    project: str
    timestamp: str
    turn: Optional[int] = None
    step: Optional[int] = None
    provider: Optional[str] = None
    mode: Optional[str] = None
    attempt: int = 0
    max_retries: int = 0
    delay_ms: Optional[float] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    # False when `llm/retry-started` never followed, meaning the retry was
    # scheduled but the session ended first.
    started: bool = False
    started_at: Optional[str] = None


class ApprovalSummary(CLIModel):
    """One permission escalation request and its decision."""

    id: str
    session_id: str
    project: str
    timestamp: str
    tool: Optional[str] = None
    call_id: Optional[str] = None
    reason: Optional[str] = None
    # "allowed-once", "allowed-always", "denied", or None when never decided.
    outcome: Optional[str] = None
    decided_at: Optional[str] = None
    decision_latency_ms: Optional[int] = None


class GoalSummary(CLIModel):
    """One revision of a session's standing goal."""

    id: str  # dsh goal id
    session_id: str
    project: str
    timestamp: str
    operation: str  # create, update, complete, ...
    revision: int = 1
    objective: str = ""
    phase: Optional[str] = None
    rounds_started: Optional[int] = None
    max_goal_rounds: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
