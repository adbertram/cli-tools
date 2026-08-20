"""Event parsing for DeepSeek Harness session logs.

This module turns the raw dsh event stream (see `logfile.py` for the physical
decode) into the models the commands print.

dsh event vocabulary used here, as declared by the harness itself in
`@deepseek-ai/dsh-session`'s KNOWN_SESSION_EVENT_TYPES:

  session (header)      log identity: id, createdAt, cwd, parentSession,
                        origin, delegationDepth, agentPreset
  user/message          a surfaced user message
  assistant/message     a surfaced assistant message, with usage
  tool/call             a tool invocation: callId, name, arguments (JSON text)
  tool/result           its result, keyed by message.source.callId
  tool/code-dispatch*   a sub-call executed inside a run_code tool call
  turn/start, turn/end  the agent turn bracket, with a finish reason
  step/start, step/end  one model round-trip inside a turn
  session/title         the session title and how it was chosen
  subagent/descriptor   a spawned session's label and assigned model
  todo/write            the full todo list, rewritten each time
  goal/change           a standing-goal revision
  llm/retry(-started)   a retryable provider failure and its retry
  approval/asked        a permission escalation request
  approval/decided      its outcome
  command/run, /done    a slash command and its result
  compaction/*          context compaction, which delimits conversations
  agent/inbox/spliced   messages injected into the next turn, including
                        system notices such as subagent-settled
  request/context       the provider, model, and context window in use
  permission/preset, sandbox/mode, approval/policy   the policy baseline

Delta rows (`text-chunks`, `reasoning-chunks`, `tool-call-chunks`) are the
streaming form of content that is also written durably as `assistant/message`.
They are deliberately ignored: reading them would double-count every token and
every tool call.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from .logfile import SessionLog, load_log
from .models import (
    ApprovalSummary,
    ConversationSummary,
    GoalSummary,
    Message,
    RetrySummary,
    SearchMatch,
    SearchResult,
    Session,
    SessionSummary,
    SkillInvocation,
    StepSummary,
    Subagent,
    SubagentSummary,
    TimelineEntry,
    TimelineEventType,
    Todo,
    TodoStatus,
    ToolCall,
    ToolCallStatus,
    ToolCallSummary,
    TurnSummary,
)
from .models.tokens import CACHE_READ_WEIGHT

# ==================== Time helpers ====================

# dsh timestamps are epoch milliseconds on every event (`time`, `time0`) and on
# the header (`createdAt`).


def epoch_to_iso(millis: Optional[Any]) -> str:
    """Convert dsh epoch milliseconds to an ISO 8601 UTC timestamp."""
    if not isinstance(millis, (int, float)):
        return ""
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat()


def event_time(event: Dict[str, Any]) -> Optional[int]:
    """Return an event's epoch-millisecond timestamp.

    Packed delta rows carry `time0` instead of `time`.
    """
    for key in ("time", "time0"):
        value = event.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


def event_iso(event: Dict[str, Any]) -> str:
    """Return an event's timestamp as ISO 8601 UTC."""
    return epoch_to_iso(event_time(event))


def format_local_time(timestamp: str, format: str = "%b %d %H:%M") -> str:
    """Convert an ISO timestamp to local time and format it."""
    if not timestamp:
        return ""
    try:
        if timestamp.endswith("Z"):
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        else:
            parsed = datetime.fromisoformat(timestamp)
        return parsed.astimezone().strftime(format)
    except (ValueError, AttributeError):
        return timestamp[:16] if len(timestamp) > 16 else timestamp


def parse_since(since: str) -> datetime:
    """Parse a relative time string such as `5h`, `1d`, `7d`, `2w`, `3m`."""
    match = re.match(r"^(\d+)([hdwm])$", since.lower())
    if not match:
        raise ValueError(
            f"Invalid --since format: {since}. Use format like '5h', '1d', '7d'"
        )
    value = int(match.group(1))
    unit = match.group(2)
    now = datetime.now(tz=timezone.utc)
    if unit == "h":
        return now - timedelta(hours=value)
    if unit == "d":
        return now - timedelta(days=value)
    if unit == "w":
        return now - timedelta(weeks=value)
    return now - timedelta(days=value * 30)


ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_RANGE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$")


def _today_local() -> date:
    return datetime.now().astimezone().date()


def _datetime_bounds(start: date, end: date) -> Tuple[datetime, datetime]:
    """Convert an inclusive date range to local-tz datetime bounds."""
    tz = datetime.now().astimezone().tzinfo
    start_dt = datetime(start.year, start.month, start.day, 0, 0, 0, 0, tzinfo=tz)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, 999999, tzinfo=tz)
    return start_dt, end_dt


def resolve_date_selector(
    date_value: Optional[str],
    date_range: Optional[str],
    date_alias: Optional[str],
) -> Optional[Tuple[datetime, datetime]]:
    """Resolve --date / --date-range / --date-alias to inclusive local bounds."""
    provided = [value for value in (date_value, date_range, date_alias) if value]
    if not provided:
        return None
    if len(provided) > 1:
        raise ValueError("Only one of --date, --date-range, --date-alias may be provided")

    today = _today_local()

    if date_value:
        if not ISO_DATE_RE.match(date_value.strip()):
            raise ValueError(
                f"invalid --date value: {date_value!r}. accepted: YYYY-MM-DD "
                f"(use --date-alias for today/yesterday)"
            )
        day = date.fromisoformat(date_value.strip())
        return _datetime_bounds(day, day)

    if date_range:
        match = ISO_RANGE_RE.match(date_range.strip())
        if not match:
            raise ValueError(
                f"invalid --date-range value: {date_range!r}. "
                f"accepted: YYYY-MM-DD..YYYY-MM-DD"
            )
        start = date.fromisoformat(match.group(1))
        end = date.fromisoformat(match.group(2))
        if start > end:
            raise ValueError(
                f"invalid --date-range value: {date_range!r}. "
                f"start must be on or before end"
            )
        return _datetime_bounds(start, end)

    normalized = re.sub(r"[\s_\-]+", "_", date_alias.strip().lower())
    iso_weekday = today.isoweekday()
    monday_this_week = today - timedelta(days=iso_weekday - 1)
    aliases = {
        "today": (today, today),
        "yesterday": (today - timedelta(days=1), today - timedelta(days=1)),
        "this_week": (monday_this_week, monday_this_week + timedelta(days=6)),
        "last_week": (
            monday_this_week - timedelta(days=7),
            monday_this_week - timedelta(days=1),
        ),
    }
    if normalized not in aliases:
        raise ValueError(
            f"invalid --date-alias value: {date_alias!r}. "
            f"accepted: today, yesterday, this_week, last_week"
        )
    start, end = aliases[normalized]
    return _datetime_bounds(start, end)


def _parse_iso(timestamp: str) -> Optional[datetime]:
    if not timestamp:
        return None
    try:
        if timestamp.endswith("Z"):
            timestamp = timestamp[:-1] + "+00:00"
        return datetime.fromisoformat(timestamp).astimezone()
    except (ValueError, AttributeError):
        return None


def in_date_window(timestamp: str, bounds: Tuple[datetime, datetime]) -> bool:
    """Check whether an ISO timestamp falls within local-tz bounds (inclusive)."""
    parsed = _parse_iso(timestamp)
    if parsed is None:
        return False
    start, end = bounds
    return start <= parsed <= end


def is_after_cutoff(timestamp: str, cutoff: datetime) -> bool:
    """Check whether an ISO timestamp is at or after an aware cutoff."""
    parsed = _parse_iso(timestamp)
    if parsed is None:
        return False
    return parsed >= cutoff


# ==================== Project path helpers ====================


def project_key(cwd: str) -> str:
    """Reproduce dsh's `projectKey(cwd)` directory name for a working directory.

    Mirrors `dsh-session-persistence-jsonl`: `/`, `\\`, and `:` collapse to a
    single `-`; `[A-Za-z0-9._-]` other than `~` stay literal; every other UTF-16
    code unit becomes `~XXXX`. Leading dashes are stripped, an empty result
    becomes `root`, the body is capped at 251 characters, and the whole key is
    wrapped in `--`.

    The separator collapse is lossy by design, so this direction is one-way: to
    recover a real path, read the `cwd` field from the session header instead.
    """
    if not cwd:
        raise ValueError("cannot encode an empty project path")

    readable: List[str] = []
    separator_run = False
    for char in cwd:
        if char in ("/", "\\", ":"):
            if not separator_run:
                readable.append("-")
            separator_run = True
        elif char != "~" and re.match(r"^[A-Za-z0-9._-]$", char):
            readable.append(char)
            separator_run = False
        else:
            readable.append(f"~{ord(char):04X}")
            separator_run = False

    body = "".join(readable).lstrip("-") or "root"
    return f"--{body[:251]}--"


def project_name_from_cwd(cwd: Optional[str]) -> str:
    """Return the human-facing project name: the working directory's basename."""
    if not cwd:
        return "_no-cwd"
    name = Path(cwd).name
    return name or cwd


# ==================== Content helpers ====================


def _blocks(container: Any) -> List[Dict[str, Any]]:
    """Return a content list, tolerating the absent/None shapes dsh may write."""
    if isinstance(container, list):
        return [block for block in container if isinstance(block, dict)]
    return []


def text_of(content: Any) -> str:
    """Join every `text` block in a dsh content array."""
    return "\n".join(
        block.get("text", "")
        for block in _blocks(content)
        if block.get("type") == "text" and block.get("text")
    )


def reasoning_of(content: Any) -> str:
    """Join every `reasoning` block in a dsh content array."""
    return "\n".join(
        block.get("text", "")
        for block in _blocks(content)
        if block.get("type") == "reasoning" and block.get("text")
    )


def decode_arguments(raw: Any) -> Dict[str, Any]:
    """Decode a tool call's arguments.

    `tool/call` stores arguments as a JSON string; `tool/code-dispatch` stores
    the already-decoded object. A string that is not valid JSON, or that decodes
    to a non-object, is preserved under a `_raw` key so nothing is silently lost.
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    if isinstance(decoded, dict):
        return decoded
    return {"_raw": decoded}


def _tool_result_text(message: Dict[str, Any]) -> Tuple[str, bool]:
    """Return a tool result's joined text and whether it reported an error."""
    parts: List[str] = []
    is_error = False
    for block in _blocks(message.get("content")):
        if block.get("type") != "tool-result":
            continue
        if block.get("isError"):
            is_error = True
        for inner in _blocks(block.get("content")):
            if inner.get("type") == "text" and inner.get("text"):
                parts.append(inner["text"])
    return "\n".join(parts), is_error


# The `subagent` tool's result text names the spawned session.
SUBAGENT_STARTED_RE = re.compile(r"started subagent ([0-9a-zA-Z_-]+)")


# ==================== Conversation (compaction) boundaries ====================


def conversation_boundaries(log: SessionLog) -> Dict[int, int]:
    """Map each event index to its conversation number.

    dsh has no `/clear`. A conversation is the run of events between context
    compactions: the log starts in conversation 1, and each `compaction/end`
    opens the next one. A session that was never compacted has one conversation.
    """
    mapping: Dict[int, int] = {}
    current = 1
    for index, event in enumerate(log.events):
        mapping[index] = current
        if event.get("type") == "compaction/end":
            current += 1
            mapping[index] = current
    return mapping


def compaction_summaries(log: SessionLog) -> Dict[int, str]:
    """Map a conversation number to the compaction summary that opened it."""
    summaries: Dict[int, str] = {}
    conversation = 1
    pending: Optional[str] = None
    for event in log.events:
        kind = event.get("type")
        data = event.get("data") or {}
        if kind == "compaction/summary":
            pending = data.get("summary") or text_of(data.get("content"))
        elif kind == "compaction/end":
            conversation += 1
            if pending:
                summaries[conversation] = pending
            pending = None
    return summaries


# ==================== Session-level parsing ====================


def _usage_totals(events: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    totals = {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_read_tokens": 0,
        "total_reasoning_tokens": 0,
    }
    for event in events:
        if event.get("type") != "assistant/message":
            continue
        usage = (event.get("data") or {}).get("usage") or {}
        totals["total_input_tokens"] += usage.get("inputTokens", 0) or 0
        totals["total_output_tokens"] += usage.get("outputTokens", 0) or 0
        totals["total_cache_read_tokens"] += usage.get("cacheReadTokens", 0) or 0
        totals["total_reasoning_tokens"] += usage.get("reasoningTokens", 0) or 0
    return totals


def _message_source(data: Dict[str, Any]) -> Dict[str, Any]:
    message = data.get("message") or {}
    source = message.get("source")
    return source if isinstance(source, dict) else {}


def parse_session_summary(log: SessionLog, project_name: str) -> SessionSummary:
    """Build a SessionSummary from a decoded log."""
    header = log.header
    title: Optional[str] = None
    title_source: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    subagent_label: Optional[str] = None
    message_count = 0
    tool_call_count = 0
    turns: set = set()
    started_steps: set = set()
    ended_steps: set = set()
    retry_count = 0
    has_errors = False
    has_subagents = False
    last_time = event_time({"time": header.get("createdAt")})

    for event in log.events:
        kind = event.get("type")
        data = event.get("data") or {}
        stamp = event_time(event)
        if stamp is not None and (last_time is None or stamp > last_time):
            last_time = stamp

        if kind == "session/title":
            title = data.get("title")
            title_source = (data.get("source") or {}).get("kind")
        elif kind == "subagent/descriptor":
            subagent_label = data.get("label")
        elif kind == "assistant/message":
            message_count += 1
            source = _message_source(data)
            if source.get("model"):
                model = source["model"]
                provider = source.get("provider")
        elif kind == "user/message":
            message_count += 1
        elif kind == "tool/call":
            tool_call_count += 1
            if data.get("name") == "subagent":
                has_subagents = True
        elif kind == "turn/start":
            turns.add(data.get("turn"))
        elif kind == "step/start":
            started_steps.add((data.get("turn"), data.get("step")))
        elif kind == "step/end":
            ended_steps.add((data.get("turn"), data.get("step")))
        elif kind == "llm/retry":
            retry_count += 1
        elif kind == "turn/end":
            if (data.get("reason") or {}).get("kind") == "error":
                has_errors = True
        elif kind == "tool/result":
            _, is_error = _tool_result_text(data.get("message") or {})
            if is_error or data.get("error"):
                has_errors = True

    conversations = conversation_boundaries(log)
    conversation_count = max(conversations.values()) if conversations else 1

    return SessionSummary(
        id=log.session_id,
        custom_title=title,
        title_source=title_source,
        project=project_name,
        project_path=log.cwd or "",
        created_at=epoch_to_iso(header.get("createdAt")),
        last_activity=epoch_to_iso(last_time),
        model=model,
        provider=provider,
        origin=header.get("origin"),
        parent_session=header.get("parentSession"),
        delegation_depth=header.get("delegationDepth", 0) or 0,
        agent_preset=header.get("agentPreset"),
        subagent_label=subagent_label,
        message_count=message_count,
        tool_call_count=tool_call_count,
        turn_count=len(turns),
        step_count=len(ended_steps),
        open_step_count=len(started_steps - ended_steps),
        retry_count=retry_count,
        has_errors=has_errors,
        has_subagents=has_subagents,
        truncated=log.truncated,
        conversation_count=conversation_count,
        current_conversation_id=conversation_count,
        **_usage_totals(log.events),
    )


def _collect_tool_calls(log: SessionLog) -> Dict[str, ToolCall]:
    """Pair every `tool/call` with its `tool/result` by call id."""
    calls: Dict[str, ToolCall] = {}
    for event in log.events:
        kind = event.get("type")
        data = event.get("data") or {}

        if kind == "tool/call":
            call_id = data.get("callId")
            if not call_id:
                continue
            calls[call_id] = ToolCall(
                id=call_id,
                tool=data.get("name", ""),
                status=ToolCallStatus.PENDING,
                turn=data.get("turn"),
                step=data.get("step"),
                started_at=event_iso(event),
                input=decode_arguments(data.get("arguments")),
            )
        elif kind == "tool/result":
            message = data.get("message") or {}
            call_id = (message.get("source") or {}).get("callId")
            call = calls.get(call_id)
            if call is None:
                continue
            result_text, is_error = _tool_result_text(message)
            call.result = result_text
            call.completed_at = event_iso(event)
            error = data.get("error")
            if is_error or error:
                call.status = ToolCallStatus.ERROR
                call.error = error if isinstance(error, dict) else {"message": result_text}
            else:
                call.status = ToolCallStatus.SUCCESS
    return calls


def parse_full_session(log: SessionLog, project_name: str) -> Session:
    """Build a full Session, including messages and per-call tool results."""
    header = log.header
    calls = _collect_tool_calls(log)
    conversations = conversation_boundaries(log)

    title: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    context_window: Optional[int] = None
    subagent_label: Optional[str] = None
    permission_preset: Optional[str] = None
    sandbox_mode: Optional[str] = None
    approval_policy: Optional[str] = None
    messages: List[Message] = []
    errors: List[Dict[str, Any]] = []
    last_time = header.get("createdAt")

    for index, event in enumerate(log.events):
        kind = event.get("type")
        data = event.get("data") or {}
        stamp = event_time(event)
        if stamp is not None and (last_time is None or stamp > last_time):
            last_time = stamp
        conversation_id = conversations.get(index, 1)

        if kind == "session/title":
            title = data.get("title")
        elif kind == "subagent/descriptor":
            subagent_label = data.get("label")
        elif kind == "request/context":
            context_window = data.get("contextWindow")
        elif kind == "permission/preset":
            permission_preset = data.get("preset")
        elif kind == "sandbox/mode":
            sandbox_mode = data.get("mode")
        elif kind == "approval/policy":
            approval_policy = data.get("policy")
        elif kind == "user/message":
            messages.append(
                Message(
                    id=data.get("id", f"user-{index}"),
                    conversation_id=conversation_id,
                    type="user",
                    timestamp=event_iso(event),
                    content=text_of(data.get("content")),
                )
            )
        elif kind == "assistant/message":
            message = data.get("message") or {}
            source = _message_source(data)
            if source.get("model"):
                model = source["model"]
                provider = source.get("provider")
            content = message.get("content")
            call_ids = [
                block.get("toolCallId") or block.get("id")
                for block in _blocks(content)
                if block.get("type") == "tool-call"
            ]
            messages.append(
                Message(
                    id=message.get("id", f"assistant-{index}"),
                    conversation_id=conversation_id,
                    type="assistant",
                    timestamp=event_iso(event),
                    turn=data.get("turn"),
                    step=data.get("step"),
                    model=source.get("model"),
                    provider=source.get("provider"),
                    content=text_of(content),
                    reasoning=reasoning_of(content) or None,
                    tool_calls=[
                        calls[call_id] for call_id in call_ids if call_id in calls
                    ],
                )
            )
        elif kind == "turn/end":
            reason = data.get("reason") or {}
            if reason.get("kind") == "error":
                error = reason.get("error") or {}
                errors.append(
                    {
                        "timestamp": event_iso(event),
                        "scope": "turn",
                        "turn": data.get("turn"),
                        "message": error.get("message"),
                        "code": error.get("code"),
                    }
                )

    for call in calls.values():
        if call.status == ToolCallStatus.ERROR:
            errors.append(
                {
                    "timestamp": call.completed_at,
                    "scope": "tool",
                    "tool": call.tool,
                    "call_id": call.id,
                    "message": (call.result or "")[:500],
                }
            )

    return Session(
        id=log.session_id,
        custom_title=title,
        project=project_name,
        project_path=log.cwd or "",
        created_at=epoch_to_iso(header.get("createdAt")),
        last_activity=epoch_to_iso(last_time),
        format_version=header.get("version"),
        model=model,
        provider=provider,
        context_window=context_window,
        cwd=log.cwd,
        origin=header.get("origin"),
        parent_session=header.get("parentSession"),
        delegation_depth=header.get("delegationDepth", 0) or 0,
        agent_preset=header.get("agentPreset"),
        subagent_label=subagent_label,
        permission_preset=permission_preset,
        sandbox_mode=sandbox_mode,
        approval_policy=approval_policy,
        truncated=log.truncated,
        messages=messages,
        subagents={},
        todos=extract_todos(log),
        errors=errors,
    )


# ==================== Conversations ====================


def parse_conversation_summaries(
    log: SessionLog, project_name: str
) -> List[ConversationSummary]:
    """Split a session into its compaction-delimited conversations."""
    conversations = conversation_boundaries(log)
    summaries = compaction_summaries(log)
    if not conversations:
        return []

    buckets: Dict[int, Dict[str, Any]] = {}
    for index, event in enumerate(log.events):
        conversation_id = conversations.get(index, 1)
        bucket = buckets.setdefault(
            conversation_id,
            {
                "first": None,
                "last": None,
                "user": 0,
                "assistant": 0,
                "tools": 0,
                "turns": set(),
                "model": None,
                "usage": [],
            },
        )
        stamp = event_time(event)
        if stamp is not None:
            if bucket["first"] is None or stamp < bucket["first"]:
                bucket["first"] = stamp
            if bucket["last"] is None or stamp > bucket["last"]:
                bucket["last"] = stamp

        kind = event.get("type")
        data = event.get("data") or {}
        if kind == "user/message":
            bucket["user"] += 1
        elif kind == "assistant/message":
            bucket["assistant"] += 1
            bucket["usage"].append(event)
            source = _message_source(data)
            if source.get("model"):
                bucket["model"] = source["model"]
        elif kind == "tool/call":
            bucket["tools"] += 1
        elif kind == "turn/start":
            bucket["turns"].add(data.get("turn"))

    result: List[ConversationSummary] = []
    for conversation_id in sorted(buckets):
        bucket = buckets[conversation_id]
        result.append(
            ConversationSummary(
                session_id=log.session_id,
                project=project_name,
                conversation_id=conversation_id,
                model=bucket["model"],
                message_count=bucket["user"] + bucket["assistant"],
                user_message_count=bucket["user"],
                assistant_message_count=bucket["assistant"],
                tool_call_count=bucket["tools"],
                turn_count=len(bucket["turns"]),
                created_at=epoch_to_iso(bucket["first"]),
                ended_at=epoch_to_iso(bucket["last"]) or None,
                started_by="session-start" if conversation_id == 1 else "compaction",
                compaction_summary=summaries.get(conversation_id),
                **_usage_totals(bucket["usage"]),
            )
        )
    return result


# ==================== Tool calls ====================


def extract_tool_calls(
    log: SessionLog,
    project_name: str,
    is_sidechain: bool = False,
    parent_tool_call_id: Optional[str] = None,
    include_code_dispatch: bool = True,
) -> List[ToolCallSummary]:
    """Extract every tool call in a session as a flat summary list.

    `run_code` dispatches nested sub-calls, recorded as `tool/code-dispatch`
    with their own `subCallId`. Those are included by default and carry
    `parent_call_id` so a caller can collapse them.
    """
    calls = _collect_tool_calls(log)
    rows: List[ToolCallSummary] = [
        ToolCallSummary(
            id=call.id,
            session_id=log.session_id,
            project=project_name,
            timestamp=call.started_at or "",
            tool=call.tool,
            status=call.status.value,
            turn=call.turn,
            step=call.step,
            is_sidechain=is_sidechain,
            parent_tool_call_id=parent_tool_call_id,
            input=call.input,
            result=call.result,
            error=call.error,
        )
        for call in calls.values()
    ]

    if include_code_dispatch:
        for event in log.events:
            if event.get("type") != "tool/code-dispatch":
                continue
            data = event.get("data") or {}
            sub_call_id = data.get("subCallId")
            if not sub_call_id:
                continue
            is_error = bool(data.get("isError"))
            result_text = "\n".join(
                block.get("text", "")
                for block in _blocks(data.get("content"))
                if block.get("type") == "text"
            )
            rows.append(
                ToolCallSummary(
                    id=sub_call_id,
                    session_id=log.session_id,
                    project=project_name,
                    timestamp=event_iso(event),
                    tool=data.get("name", ""),
                    status="error" if is_error else "success",
                    is_sidechain=is_sidechain,
                    parent_tool_call_id=parent_tool_call_id,
                    parent_call_id=data.get("parentCallId"),
                    input=decode_arguments(data.get("arguments")),
                    result=result_text,
                    error={"message": result_text} if is_error else None,
                )
            )

    rows.sort(key=lambda row: row.timestamp or "")
    return rows


# ==================== Subagents ====================


def extract_subagent_spawns(log: SessionLog) -> Dict[str, Dict[str, Any]]:
    """Map each spawned child session id to its parent `subagent` tool call.

    The parent's `tool/result` text is `started subagent <child session id>`.
    """
    spawns: Dict[str, Dict[str, Any]] = {}
    pending: Dict[str, Dict[str, Any]] = {}

    for event in log.events:
        kind = event.get("type")
        data = event.get("data") or {}
        if kind == "tool/call" and data.get("name") == "subagent":
            call_id = data.get("callId")
            if call_id:
                arguments = decode_arguments(data.get("arguments"))
                pending[call_id] = {
                    "parent_tool_call_id": call_id,
                    "timestamp": event_iso(event),
                    "prompt": arguments.get("prompt", ""),
                    "description": arguments.get("description"),
                }
        elif kind == "tool/result":
            message = data.get("message") or {}
            call_id = (message.get("source") or {}).get("callId")
            spawn = pending.get(call_id)
            if spawn is None:
                continue
            result_text, _ = _tool_result_text(message)
            match = SUBAGENT_STARTED_RE.search(result_text)
            if match:
                spawns[match.group(1)] = spawn
    return spawns


def summarize_subagent_session(
    child: SessionLog,
    project_name: str,
    spawn: Optional[Dict[str, Any]] = None,
) -> SubagentSummary:
    """Summarize a child session log as one subagent invocation."""
    header = child.header
    label: Optional[str] = None
    provider: Optional[str] = None
    mode: Optional[str] = None
    model: Optional[str] = None
    report: Optional[str] = None
    message_count = 0
    tool_call_count = 0
    turns: set = set()
    retry_count = 0
    error_count = 0
    last_time = header.get("createdAt")
    settled = False

    for event in child.events:
        kind = event.get("type")
        data = event.get("data") or {}
        stamp = event_time(event)
        if stamp is not None and (last_time is None or stamp > last_time):
            last_time = stamp

        if kind == "subagent/descriptor":
            label = data.get("label")
            provider = data.get("agentProvider")
            model = data.get("agentModel")
            mode = data.get("mode")
        elif kind in ("user/message", "assistant/message"):
            message_count += 1
        elif kind == "tool/call":
            tool_call_count += 1
            if data.get("name") == "report":
                report = decode_arguments(data.get("arguments")).get("output")
        elif kind == "turn/start":
            turns.add(data.get("turn"))
        elif kind == "turn/end":
            reason = data.get("reason") or {}
            if reason.get("kind") == "error":
                error_count += 1
            elif reason.get("kind") == "completed":
                settled = True
        elif kind == "llm/retry":
            retry_count += 1
        elif kind == "tool/result":
            _, is_error = _tool_result_text(data.get("message") or {})
            if is_error:
                error_count += 1

    spawn = spawn or {}
    return SubagentSummary(
        id=child.session_id,
        session_id=child.session_id,
        parent_session_id=header.get("parentSession", ""),
        project=project_name,
        timestamp=epoch_to_iso(header.get("createdAt")),
        label=label or spawn.get("description") or child.session_id,
        parent_tool_call_id=spawn.get("parent_tool_call_id"),
        prompt=spawn.get("prompt", ""),
        description=spawn.get("description"),
        model=model,
        provider=provider,
        mode=mode,
        agent_preset=header.get("agentPreset"),
        delegation_depth=header.get("delegationDepth", 1) or 1,
        status="completed" if settled else ("error" if error_count else "incomplete"),
        message_count=message_count,
        tool_call_count=tool_call_count,
        turn_count=len(turns),
        retry_count=retry_count,
        error_count=error_count,
        report=report,
        **_usage_totals(child.events),
    )


def build_subagent(
    child: SessionLog,
    project_name: str,
    spawn: Optional[Dict[str, Any]] = None,
) -> Subagent:
    """Build a full Subagent, including the child session's messages."""
    summary = summarize_subagent_session(child, project_name, spawn)
    session = parse_full_session(child, project_name)
    return Subagent(
        id=child.session_id,
        label=summary.label,
        parent_session_id=summary.parent_session_id,
        parent_tool_call_id=summary.parent_tool_call_id,
        model=summary.model,
        provider=summary.provider,
        mode=summary.mode,
        prompt=summary.prompt,
        description=summary.description,
        status=summary.status,
        created_at=summary.timestamp,
        completed_at=session.last_activity,
        messages=session.messages,
    )


# ==================== Todos ====================


def extract_todos(log: SessionLog) -> List[Todo]:
    """Return the final todo list of a session.

    dsh rewrites the whole list on each `todo/write`, so only the last event
    holds the end state.
    """
    latest: Optional[Dict[str, Any]] = None
    for event in log.events:
        if event.get("type") == "todo/write":
            latest = event
    if latest is None:
        return []

    todos: List[Todo] = []
    items = (latest.get("data") or {}).get("todos") or []
    for position, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        status = item.get("status", "pending")
        todos.append(
            Todo(
                id=f"{log.session_id}:{position}",
                content=item.get("content", ""),
                status=TodoStatus(status)
                if status in TodoStatus._value2member_map_
                else TodoStatus.PENDING,
                position=position,
            )
        )
    return todos


def extract_todo_write_time(log: SessionLog) -> Optional[str]:
    """Return the timestamp of the final `todo/write` in a session."""
    latest: Optional[Dict[str, Any]] = None
    for event in log.events:
        if event.get("type") == "todo/write":
            latest = event
    return event_iso(latest) if latest else None


# ==================== Skills and commands ====================


def extract_skill_invocations(log: SessionLog, project_name: str) -> List[SkillInvocation]:
    """Extract `skill` tool loads and slash-command runs."""
    rows: List[SkillInvocation] = []
    commands: Dict[str, SkillInvocation] = {}

    for index, event in enumerate(log.events):
        kind = event.get("type")
        data = event.get("data") or {}

        if kind == "tool/call" and data.get("name") == "skill":
            arguments = decode_arguments(data.get("arguments"))
            rows.append(
                SkillInvocation(
                    id=data.get("callId", f"skill-{index}"),
                    session_id=log.session_id,
                    project=project_name,
                    timestamp=event_iso(event),
                    kind="skill",
                    name=arguments.get("name", ""),
                    args=json.dumps(
                        {k: v for k, v in arguments.items() if k != "name"}
                    )
                    if len(arguments) > 1
                    else None,
                    turn=data.get("turn"),
                    step=data.get("step"),
                )
            )
        elif kind == "command/run":
            command_id = data.get("commandId", f"command-{index}")
            invocation = SkillInvocation(
                id=command_id,
                session_id=log.session_id,
                project=project_name,
                timestamp=event_iso(event),
                kind="command",
                name=data.get("name", ""),
                args=(data.get("args") or "").strip() or None,
            )
            commands[command_id] = invocation
            rows.append(invocation)
        elif kind == "command/done":
            invocation = commands.get(data.get("commandId"))
            if invocation is not None:
                invocation.status = data.get("kind")
                invocation.result = data.get("text")

    rows.sort(key=lambda row: row.timestamp or "")
    return rows


# ==================== Turns and steps ====================


def extract_turns(log: SessionLog, project_name: str) -> List[TurnSummary]:
    """Extract every agent turn with its finish reason and token cost."""
    conversations = conversation_boundaries(log)
    turns: Dict[int, Dict[str, Any]] = {}

    def bucket(number: Optional[int], index: int) -> Optional[Dict[str, Any]]:
        if number is None:
            return None
        return turns.setdefault(
            number,
            {
                "started_at": None,
                "ended_at": None,
                "start_ms": None,
                "end_ms": None,
                "reason": None,
                "error": {},
                "started_steps": set(),
                "ended_steps": set(),
                "messages": 0,
                "tools": 0,
                "retries": 0,
                "model": None,
                "provider": None,
                "usage": [],
                "conversation": conversations.get(index, 1),
            },
        )

    for index, event in enumerate(log.events):
        kind = event.get("type")
        data = event.get("data") or {}
        entry = bucket(data.get("turn"), index)
        if entry is None:
            continue
        stamp = event_time(event)

        if kind == "turn/start":
            entry["started_at"] = event_iso(event)
            entry["start_ms"] = stamp
        elif kind == "turn/end":
            entry["ended_at"] = event_iso(event)
            entry["end_ms"] = stamp
            reason = data.get("reason") or {}
            entry["reason"] = reason.get("kind")
            error = reason.get("error") or reason.get("failure") or {}
            if isinstance(error, dict):
                entry["error"] = error
        elif kind == "step/start":
            entry["started_steps"].add(data.get("step"))
        elif kind == "step/end":
            entry["ended_steps"].add(data.get("step"))
        elif kind == "assistant/message":
            entry["messages"] += 1
            entry["usage"].append(event)
            source = _message_source(data)
            if source.get("model"):
                entry["model"] = source["model"]
                entry["provider"] = source.get("provider")
        elif kind == "tool/call":
            entry["tools"] += 1
        elif kind == "llm/retry":
            entry["retries"] += 1

    rows: List[TurnSummary] = []
    for number in sorted(turns):
        entry = turns[number]
        duration = None
        if entry["start_ms"] is not None and entry["end_ms"] is not None:
            duration = int(entry["end_ms"] - entry["start_ms"])
        rows.append(
            TurnSummary(
                id=f"{log.session_id}:{number}",
                session_id=log.session_id,
                project=project_name,
                turn=number,
                started_at=entry["started_at"] or "",
                ended_at=entry["ended_at"],
                duration_ms=duration,
                finish_reason=entry["reason"],
                error_message=entry["error"].get("message"),
                error_code=entry["error"].get("code"),
                model=entry["model"],
                provider=entry["provider"],
                step_count=len(entry["ended_steps"]),
                open_step_count=len(entry["started_steps"] - entry["ended_steps"]),
                message_count=entry["messages"],
                tool_call_count=entry["tools"],
                retry_count=entry["retries"],
                conversation_id=entry["conversation"],
                **_usage_totals(entry["usage"]),
            )
        )
    return rows


def extract_steps(log: SessionLog, project_name: str, turn: Optional[int] = None) -> List[StepSummary]:
    """Extract every model round-trip, optionally scoped to one turn."""
    steps: Dict[Tuple[int, int], Dict[str, Any]] = {}

    for event in log.events:
        kind = event.get("type")
        data = event.get("data") or {}
        key = (data.get("turn"), data.get("step"))
        if key[0] is None or key[1] is None:
            continue
        if turn is not None and key[0] != turn:
            continue
        entry = steps.setdefault(
            key,
            {
                "started_at": None,
                "ended_at": None,
                "start_ms": None,
                "end_ms": None,
                "tools": 0,
                "model": None,
                "usage": {},
            },
        )
        stamp = event_time(event)

        if kind == "step/start":
            entry["started_at"] = event_iso(event)
            entry["start_ms"] = stamp
        elif kind == "step/end":
            entry["ended_at"] = event_iso(event)
            entry["end_ms"] = stamp
        elif kind == "tool/call":
            entry["tools"] += 1
        elif kind == "assistant/message":
            entry["usage"] = data.get("usage") or {}
            source = _message_source(data)
            if source.get("model"):
                entry["model"] = source["model"]

    rows: List[StepSummary] = []
    for turn_number, step_number in sorted(steps):
        entry = steps[(turn_number, step_number)]
        duration = None
        if entry["start_ms"] is not None and entry["end_ms"] is not None:
            duration = int(entry["end_ms"] - entry["start_ms"])
        usage = entry["usage"]
        rows.append(
            StepSummary(
                id=f"{log.session_id}:{turn_number}:{step_number}",
                session_id=log.session_id,
                project=project_name,
                turn=turn_number,
                step=step_number,
                started_at=entry["started_at"] or "",
                ended_at=entry["ended_at"],
                duration_ms=duration,
                model=entry["model"],
                tool_call_count=entry["tools"],
                input_tokens=usage.get("inputTokens"),
                output_tokens=usage.get("outputTokens"),
                cache_read_tokens=usage.get("cacheReadTokens"),
                reasoning_tokens=usage.get("reasoningTokens"),
            )
        )
    return rows


# ==================== Retries, approvals, goals ====================


def extract_retries(log: SessionLog, project_name: str) -> List[RetrySummary]:
    """Extract every retryable provider failure and whether its retry began."""
    rows: Dict[str, RetrySummary] = {}
    for index, event in enumerate(log.events):
        kind = event.get("type")
        data = event.get("data") or {}

        if kind == "llm/retry":
            retry_id = data.get("retryId", f"retry-{index}")
            failure = data.get("failure") or {}
            rows[retry_id] = RetrySummary(
                id=retry_id,
                session_id=log.session_id,
                project=project_name,
                timestamp=event_iso(event),
                turn=data.get("turn"),
                step=data.get("step"),
                provider=data.get("provider"),
                mode=data.get("mode"),
                attempt=data.get("retry", 0) or 0,
                max_retries=data.get("maxRetries", 0) or 0,
                delay_ms=data.get("delayMs"),
                error_code=failure.get("code"),
                error_message=failure.get("message"),
            )
        elif kind == "llm/retry-started":
            row = rows.get(data.get("retryId"))
            if row is not None:
                row.started = True
                row.started_at = event_iso(event)

    return sorted(rows.values(), key=lambda row: row.timestamp or "")


def extract_approvals(log: SessionLog, project_name: str) -> List[ApprovalSummary]:
    """Extract every permission escalation request and its decision."""
    rows: Dict[str, ApprovalSummary] = {}
    asked_ms: Dict[str, Optional[int]] = {}

    for index, event in enumerate(log.events):
        kind = event.get("type")
        data = event.get("data") or {}

        if kind == "approval/asked":
            approval_id = data.get("id", f"approval-{index}")
            asked_ms[approval_id] = event_time(event)
            rows[approval_id] = ApprovalSummary(
                id=approval_id,
                session_id=log.session_id,
                project=project_name,
                timestamp=event_iso(event),
                tool=data.get("toolName"),
                call_id=data.get("callId"),
                reason=data.get("reason"),
            )
        elif kind == "approval/decided":
            row = rows.get(data.get("id"))
            if row is None:
                continue
            row.outcome = data.get("outcome")
            row.decided_at = event_iso(event)
            decided_ms = event_time(event)
            started_ms = asked_ms.get(row.id)
            if decided_ms is not None and started_ms is not None:
                row.decision_latency_ms = int(decided_ms - started_ms)

    return sorted(rows.values(), key=lambda row: row.timestamp or "")


def extract_goals(log: SessionLog, project_name: str) -> List[GoalSummary]:
    """Extract every standing-goal revision."""
    rows: List[GoalSummary] = []
    for index, event in enumerate(log.events):
        if event.get("type") != "goal/change":
            continue
        data = event.get("data") or {}
        goal = data.get("goal") or {}
        rows.append(
            GoalSummary(
                id=goal.get("id", f"goal-{index}"),
                session_id=log.session_id,
                project=project_name,
                timestamp=event_iso(event),
                operation=data.get("operation", ""),
                revision=goal.get("revision", 1) or 1,
                objective=goal.get("objective", ""),
                phase=goal.get("phase"),
                rounds_started=data.get("roundsStarted"),
                max_goal_rounds=goal.get("maxGoalRounds"),
                created_at=epoch_to_iso(data.get("createdAt")),
                updated_at=epoch_to_iso(data.get("updatedAt")),
            )
        )
    return rows


# ==================== Timeline ====================

# Inbox notices that are harness-generated rather than typed by the user.
_NOTICE_KINDS = {
    "plugin",
    "goal",
    "subagent-report",
    "subagent-settled",
    "coordinator",
    "agent-instructions",
}


def _effective(usage: Dict[str, Any]) -> int:
    return (
        (usage.get("inputTokens", 0) or 0)
        + (usage.get("outputTokens", 0) or 0)
        + int((usage.get("cacheReadTokens", 0) or 0) * CACHE_READ_WEIGHT)
    )


def extract_timeline(
    log: SessionLog,
    project_name: str,
    show_thinking: bool = False,
    subagent_labels: Optional[Dict[str, str]] = None,
) -> List[TimelineEntry]:
    """Build one chronological timeline for a session.

    Rows are emitted for user and assistant messages, tool calls and their
    results, code dispatches, skill loads, slash commands, subagent spawns,
    todo writes, goal changes, approvals, retries, compactions, and turn ends.
    Assistant reasoning is included only when `show_thinking` is set.
    """
    conversations = conversation_boundaries(log)
    calls = _collect_tool_calls(log)
    spawns = extract_subagent_spawns(log)
    child_by_call = {
        spawn["parent_tool_call_id"]: child_id for child_id, spawn in spawns.items()
    }
    subagent_labels = subagent_labels or {}

    entries: List[TimelineEntry] = []
    session_total = 0
    conversation_totals: Dict[int, int] = {}

    for index, event in enumerate(log.events):
        kind = event.get("type")
        data = event.get("data") or {}
        stamp = event_iso(event)
        conversation_id = conversations.get(index, 1)
        entry_id = f"{log.session_id}:{index}"

        def add(**kwargs: Any) -> None:
            entries.append(
                TimelineEntry(
                    id=entry_id,
                    session_id=log.session_id,
                    timestamp=stamp,
                    conversation_id=conversation_id,
                    turn_number=data.get("turn"),
                    step_number=data.get("step"),
                    **kwargs,
                )
            )

        if kind == "user/message":
            source_kind = (data.get("source") or {}).get("kind")
            text = text_of(data.get("content"))
            add(
                event_type=TimelineEventType.NOTICE
                if source_kind in _NOTICE_KINDS
                else TimelineEventType.USER_MESSAGE,
                name=source_kind or "user",
                status="invoked",
                input=text,
                details={"source": data.get("source")},
            )

        elif kind == "assistant/message":
            message = data.get("message") or {}
            source = _message_source(data)
            usage = data.get("usage") or {}
            cost = _effective(usage)
            session_total += cost
            conversation_totals[conversation_id] = (
                conversation_totals.get(conversation_id, 0) + cost
            )
            content = message.get("content")

            reasoning = reasoning_of(content)
            if show_thinking and reasoning:
                add(
                    event_type=TimelineEventType.THINKING,
                    name="reasoning",
                    model=source.get("model"),
                    status="success",
                    output=reasoning,
                    reasoning_tokens=usage.get("reasoningTokens"),
                )

            text = text_of(content)
            if text:
                add(
                    event_type=TimelineEventType.ASSISTANT_MESSAGE,
                    name="assistant",
                    model=source.get("model"),
                    status="success",
                    output=text,
                    input_tokens=usage.get("inputTokens"),
                    output_tokens=usage.get("outputTokens"),
                    cache_read_tokens=usage.get("cacheReadTokens"),
                    reasoning_tokens=usage.get("reasoningTokens"),
                    turn_cost=cost,
                    session_total=session_total,
                    conversation_total=conversation_totals[conversation_id],
                )

        elif kind == "tool/call":
            call_id = data.get("callId")
            call = calls.get(call_id)
            name = data.get("name", "")
            child_id = child_by_call.get(call_id)

            if name == "subagent":
                add(
                    event_type=TimelineEventType.SUBAGENT_START,
                    name=subagent_labels.get(child_id or "", "")
                    or decode_arguments(data.get("arguments")).get("description", "subagent"),
                    status=call.status.value if call else "pending",
                    agent_id=child_id,
                    agent_name=subagent_labels.get(child_id or ""),
                    input=decode_arguments(data.get("arguments")).get("prompt"),
                    output=call.result if call else None,
                )
            else:
                event_type = (
                    TimelineEventType.SKILL_LOAD
                    if name == "skill"
                    else TimelineEventType.TOOL_CALL
                )
                arguments = decode_arguments(data.get("arguments"))
                add(
                    event_type=event_type,
                    name=arguments.get("name", name) if name == "skill" else name,
                    status=call.status.value if call else "pending",
                    input=arguments,
                    output=call.result if call else None,
                    error_message=(call.result or "")[:500]
                    if call and call.status == ToolCallStatus.ERROR
                    else None,
                )

        elif kind == "tool/code-dispatch":
            is_error = bool(data.get("isError"))
            add(
                event_type=TimelineEventType.CODE_DISPATCH,
                name=data.get("name", ""),
                status="error" if is_error else "success",
                input=decode_arguments(data.get("arguments")),
                output="\n".join(
                    block.get("text", "")
                    for block in _blocks(data.get("content"))
                    if block.get("type") == "text"
                ),
                details={"parent_call_id": data.get("parentCallId")},
            )

        elif kind == "command/run":
            add(
                event_type=TimelineEventType.COMMAND,
                name=data.get("name", ""),
                status="invoked",
                input=(data.get("args") or "").strip(),
            )

        elif kind == "todo/write":
            todos = data.get("todos") or []
            add(
                event_type=TimelineEventType.TODO_WRITE,
                name="todo_write",
                status="invoked",
                output=todos,
                details={"count": len(todos)},
            )

        elif kind == "goal/change":
            goal = data.get("goal") or {}
            add(
                event_type=TimelineEventType.GOAL_CHANGE,
                name=data.get("operation", "goal"),
                status=goal.get("phase"),
                input=goal.get("objective"),
            )

        elif kind == "approval/asked":
            add(
                event_type=TimelineEventType.APPROVAL,
                name=data.get("toolName", "approval"),
                status="invoked",
                input=data.get("reason"),
                details={"approval_id": data.get("id")},
            )

        elif kind == "approval/decided":
            add(
                event_type=TimelineEventType.APPROVAL,
                name="decided",
                status=data.get("outcome"),
                details={"approval_id": data.get("id")},
            )

        elif kind == "llm/retry":
            failure = data.get("failure") or {}
            add(
                event_type=TimelineEventType.RETRY,
                name=failure.get("code", "retry"),
                status="error",
                error_message=failure.get("message"),
                details={
                    "attempt": data.get("retry"),
                    "max_retries": data.get("maxRetries"),
                    "delay_ms": data.get("delayMs"),
                },
            )

        elif kind in ("compaction/start", "compaction/end", "compaction/summary"):
            add(
                event_type=TimelineEventType.COMPACTION,
                name=kind.split("/", 1)[1],
                status="invoked",
                output=data.get("summary"),
            )

        elif kind == "turn/end":
            reason = data.get("reason") or {}
            reason_kind = reason.get("kind")
            error = reason.get("error") or {}
            add(
                event_type=TimelineEventType.ERROR
                if reason_kind == "error"
                else TimelineEventType.TURN_END,
                name=reason_kind or "turn_end",
                status="error" if reason_kind == "error" else reason_kind,
                error_message=error.get("message") if isinstance(error, dict) else None,
                session_total=session_total,
                conversation_total=conversation_totals.get(conversation_id),
            )

    entries.sort(key=lambda entry: entry.timestamp or "")
    return entries


# ==================== Search ====================


def _snippet_around(text: str, keyword_lower: str, radius: int = 120) -> str:
    lowered = text.lower()
    position = lowered.find(keyword_lower)
    if position < 0:
        return text[: radius * 2]
    start = max(0, position - radius)
    end = min(len(text), position + len(keyword_lower) + radius)
    snippet = text[start:end].replace("\n", " ").strip()
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def search_log(
    log: SessionLog,
    query: str,
    project_name: str,
    max_matches: int = 5,
) -> Optional[SearchResult]:
    """Search one session's surfaced content, returning context snippets."""
    lowered = query.lower()
    summary = parse_session_summary(log, project_name)

    matches: List[SearchMatch] = []
    match_count = 0

    for event in log.events:
        kind = event.get("type")
        data = event.get("data") or {}

        if kind == "user/message":
            role, text = "user", text_of(data.get("content"))
        elif kind == "assistant/message":
            message = data.get("message") or {}
            role, text = "assistant", text_of(message.get("content"))
        elif kind == "tool/result":
            role, (text, _) = "tool", _tool_result_text(data.get("message") or {})
        else:
            continue

        if not text or lowered not in text.lower():
            continue
        match_count += 1
        if len(matches) < max_matches:
            matches.append(
                SearchMatch(
                    role=role,
                    snippet=_snippet_around(text, lowered),
                    timestamp=event_iso(event),
                )
            )

    if match_count == 0:
        return None

    return SearchResult(
        session_id=log.session_id,
        project=project_name,
        project_path=log.cwd or "",
        custom_title=summary.custom_title,
        created_at=summary.created_at,
        last_activity=summary.last_activity,
        model=summary.model,
        origin=summary.origin,
        match_count=match_count,
        matches=matches,
    )


# ==================== User prompt extraction ====================


def extract_user_prompts(
    messages: List[Any],
    first_n: int,
    last_n: int,
    max_chars: int = 400,
    clean: bool = True,
) -> Dict[str, List[str]]:
    """Extract first-N / last-N user prompts from a parsed message list.

    With clean=True, messages whose text opens with `<` (harness-injected tags)
    are skipped, as are empty messages.
    """

    def field(name: str, message: Any) -> Any:
        if isinstance(message, dict):
            return message.get(name)
        return getattr(message, name, None)

    kept: List[str] = []
    for message in messages:
        if field("type", message) != "user":
            continue
        content = field("content", message)
        if not isinstance(content, str):
            continue
        stripped = content.strip()
        if not stripped:
            continue
        if clean and stripped.startswith("<"):
            continue
        if max_chars and len(stripped) > max_chars:
            stripped = stripped[:max_chars]
        kept.append(stripped)

    first = kept[:first_n] if first_n > 0 else []
    if last_n > 0:
        last = kept[-last_n:] if len(kept) >= last_n else kept[:]
    else:
        last = []
    return {"first_user_prompts": first, "last_user_prompts": last}


def parse_include_prompts(value: str) -> Tuple[int, int]:
    """Parse `--include-prompts first:N,last:N` into (first, last)."""
    if not value:
        raise ValueError("empty --include-prompts value")
    first = 0
    last = 0
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        raise ValueError(
            f"invalid --include-prompts value: {value!r}. expected 'first:N,last:N'"
        )
    for part in parts:
        if ":" not in part:
            raise ValueError(
                f"invalid --include-prompts segment: {part!r}. "
                f"expected 'first:N' or 'last:N'"
            )
        key, _, raw = part.partition(":")
        key = key.strip().lower()
        try:
            count = int(raw.strip())
        except ValueError as exc:
            raise ValueError(
                f"invalid --include-prompts count: {raw!r} in {part!r}"
            ) from exc
        if count < 0:
            raise ValueError(
                f"invalid --include-prompts count: {count} in {part!r} (must be >= 0)"
            )
        if key == "first":
            first = count
        elif key == "last":
            last = count
        else:
            raise ValueError(
                f"invalid --include-prompts key: {key!r}. expected 'first' or 'last'"
            )
    return first, last
