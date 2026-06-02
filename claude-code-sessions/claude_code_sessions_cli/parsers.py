"""JSONL session parsing utilities for Claude Code sessions.

This module provides utilities to parse Claude Code's JSONL session files
from ~/.claude/projects/ and transform them into structured data.
"""
import json
import re
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Dict, List, Any, Optional, Iterator, Tuple

from .models import (
    Project,
    SessionSummary,
    Session,
    Message,
    ToolCall,
    ToolCallStatus,
    Subagent,
    Todo,
    TodoStatus,
    TimelineEntry,
    TimelineEventType,
    SearchResult,
    SearchMatch,
)


def format_tool_call_entry(
    tc: ToolCall,
    session_id: str,
    project: str,
    timestamp: str,
    is_sidechain: bool = False,
    agent_id: Optional[str] = None,
    parent_tool_call_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Format a ToolCall into a standardized entry dict.

    This is the SINGLE source of truth for tool call formatting.
    All commands (tool-calls, subagent-activity, timeline) use this.

    Args:
        tc: Parsed ToolCall object
        session_id: Session ID
        project: Project name
        timestamp: ISO timestamp of the tool call
        is_sidechain: True if this is from a subagent
        agent_id: Subagent ID if applicable
        parent_tool_call_id: Task tool call ID that spawned the subagent

    Returns:
        Dict with standardized tool call fields
    """
    return {
        'id': tc.id,
        'session_id': session_id,
        'project': project,
        'timestamp': timestamp,
        'tool': tc.tool,
        'status': tc.status.value if hasattr(tc.status, 'value') else str(tc.status),
        'input': tc.input,
        'result': tc.result,
        'error': tc.error,
        'is_sidechain': is_sidechain,
        'agent_id': agent_id,
        'parent_tool_call_id': parent_tool_call_id,
    }


ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_RANGE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$")


def _today_local() -> date:
    """Return today's local-tz date."""
    return datetime.now().astimezone().date()


def _normalize_alias(value: str) -> str:
    """Lowercase + collapse whitespace/dashes/underscores."""
    return re.sub(r"[\s_\-]+", "_", value.strip().lower())


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
    """
    Resolve --date / --date-range / --date-alias into inclusive local-tz bounds.

    Returns None if all three are None. Raises ValueError on invalid input.

    Mutual exclusion among these three is enforced by the caller; this helper
    accepts whichever single value is provided.
    """
    provided = [v for v in (date_value, date_range, date_alias) if v]
    if not provided:
        return None
    if len(provided) > 1:
        raise ValueError(
            "Only one of --date, --date-range, --date-alias may be provided"
        )

    today = _today_local()

    if date_value:
        if not ISO_DATE_RE.match(date_value.strip()):
            raise ValueError(
                f"invalid --date value: {date_value!r}. accepted: YYYY-MM-DD "
                f"(use --date-alias for today/yesterday)"
            )
        d = date.fromisoformat(date_value.strip())
        return _datetime_bounds(d, d)

    if date_range:
        m = ISO_RANGE_RE.match(date_range.strip())
        if not m:
            raise ValueError(
                f"invalid --date-range value: {date_range!r}. accepted: YYYY-MM-DD..YYYY-MM-DD"
            )
        start = date.fromisoformat(m.group(1))
        end = date.fromisoformat(m.group(2))
        if start > end:
            raise ValueError(
                f"invalid --date-range value: {date_range!r}. start must be on or before end"
            )
        return _datetime_bounds(start, end)

    # date_alias
    norm = _normalize_alias(date_alias)
    iso_weekday = today.isoweekday()
    monday_this_week = today - timedelta(days=iso_weekday - 1)
    sunday_this_week = monday_this_week + timedelta(days=6)
    monday_last_week = monday_this_week - timedelta(days=7)
    sunday_last_week = monday_this_week - timedelta(days=1)

    aliases: Dict[str, Tuple[date, date]] = {
        "today": (today, today),
        "yesterday": (today - timedelta(days=1), today - timedelta(days=1)),
        "this_week": (monday_this_week, sunday_this_week),
        "last_week": (monday_last_week, sunday_last_week),
    }
    if norm not in aliases:
        raise ValueError(
            f"invalid --date-alias value: {date_alias!r}. "
            f"accepted: today, yesterday, this_week, last_week"
        )
    start, end = aliases[norm]
    return _datetime_bounds(start, end)


def _parse_iso_local(ts: str) -> Optional[datetime]:
    """Parse an ISO timestamp string to a local-tz datetime, or None if unparseable."""
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).astimezone()
    except (ValueError, AttributeError):
        return None


def in_date_window(ts: str, bounds: Tuple[datetime, datetime]) -> bool:
    """Check if an ISO timestamp falls within local-tz bounds (inclusive)."""
    dt = _parse_iso_local(ts)
    if dt is None:
        return False
    start, end = bounds
    return start <= dt <= end


def extract_user_prompts(
    messages: List[Any],
    first_n: int,
    last_n: int,
    max_chars: int = 400,
    clean: bool = True,
) -> Dict[str, List[str]]:
    """
    Extract first-N / last-N user prompts from a parsed message list.

    Operates on the message list `parse_full_session` produces; each item has
    `.type` and `.content` (str) attributes (Message model). To remain flexible
    this also accepts dicts with `type`/`content` keys.

    When clean=True:
      - skip messages whose stripped content starts with `<` (system reminders,
        command tags, local-command-stdout, etc.)
      - skip messages whose stripped content starts with `Caveat:`
      - tool_result-bearing list-content messages are already collapsed to '' by
        parse_message and will be filtered as empty

    Each kept prompt is truncated to max_chars.
    """
    def _get(attr_name: str, msg: Any) -> Any:
        if isinstance(msg, dict):
            return msg.get(attr_name)
        return getattr(msg, attr_name, None)

    kept: List[str] = []
    for msg in messages:
        if _get("type", msg) != "user":
            continue
        content = _get("content", msg)
        if not isinstance(content, str):
            continue
        stripped = content.strip()
        if not stripped:
            continue
        if clean:
            if stripped.startswith("<"):
                continue
            if stripped.startswith("Caveat:"):
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
    """Parse `--include-prompts first:N,last:N` into (first, last) ints."""
    if not value:
        raise ValueError("empty --include-prompts value")
    first = 0
    last = 0
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        raise ValueError(
            f"invalid --include-prompts value: {value!r}. expected 'first:N,last:N'"
        )
    for part in parts:
        if ":" not in part:
            raise ValueError(
                f"invalid --include-prompts segment: {part!r}. expected 'first:N' or 'last:N'"
            )
        key, _, raw = part.partition(":")
        key = key.strip().lower()
        try:
            n = int(raw.strip())
        except ValueError as exc:
            raise ValueError(
                f"invalid --include-prompts count: {raw!r} in {part!r}"
            ) from exc
        if n < 0:
            raise ValueError(
                f"invalid --include-prompts count: {n} in {part!r} (must be >= 0)"
            )
        if key == "first":
            first = n
        elif key == "last":
            last = n
        else:
            raise ValueError(
                f"invalid --include-prompts key: {key!r}. expected 'first' or 'last'"
            )
    return first, last


def parse_since(since: str) -> datetime:
    """
    Parse relative time string into datetime.

    Args:
        since: Relative time like "5h", "1d", "7d", "30d"

    Returns:
        datetime representing the cutoff time
    """
    pattern = r'^(\d+)([hdwm])$'
    match = re.match(pattern, since.lower())
    if not match:
        raise ValueError(f"Invalid --since format: {since}. Use format like '5h', '1d', '7d'")

    value = int(match.group(1))
    unit = match.group(2)

    now = datetime.now()

    if unit == 'h':
        return now - timedelta(hours=value)
    elif unit == 'd':
        return now - timedelta(days=value)
    elif unit == 'w':
        return now - timedelta(weeks=value)
    elif unit == 'm':
        return now - timedelta(days=value * 30)  # Approximate month
    else:
        raise ValueError(f"Unknown time unit: {unit}")


def format_local_time(timestamp: str, format: str = '%b %d %H:%M') -> str:
    """
    Convert an ISO timestamp to local timezone and format it.

    Args:
        timestamp: ISO format timestamp (e.g., "2025-01-13T14:30:45Z" or "2025-01-13T14:30:45+00:00")
        format: strftime format string (default: "Jan 13 14:30")

    Returns:
        Formatted time string in local timezone, or original timestamp if parsing fails
    """
    if not timestamp:
        return ''

    try:
        # Parse ISO timestamp - handle 'Z' suffix or timezone offset
        if timestamp.endswith('Z'):
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(timestamp)

        # Convert to local timezone
        local_dt = dt.astimezone()

        return local_dt.strftime(format)
    except (ValueError, AttributeError):
        # Fallback: return truncated timestamp if parsing fails
        return timestamp[:16] if len(timestamp) > 16 else timestamp


def format_local_time_only(timestamp: str) -> str:
    """
    Convert an ISO timestamp to local timezone and return just the time portion.

    Args:
        timestamp: ISO format timestamp (e.g., "2025-01-13T14:30:45Z")

    Returns:
        Time string in HH:MM:SS format in local timezone
    """
    return format_local_time(timestamp, '%H:%M:%S')


def decode_project_path(encoded_path: str) -> str:
    """
    Decode an encoded project path back to original.

    Args:
        encoded_path: Path like "-path-to-project"

    Returns:
        Original path like "/path/to/project"
    """
    # Replace leading hyphen with /
    if encoded_path.startswith('-'):
        return '/' + encoded_path[1:].replace('-', '/')
    return encoded_path.replace('-', '/')


def encode_project_path(original_path: str) -> str:
    """
    Encode a path for Claude Code's directory naming.

    Args:
        original_path: Path like "/path/to/project"

    Returns:
        Encoded path like "-path-to-project"
    """
    return original_path.replace('/', '-')


def extract_project_name(encoded_path: str) -> str:
    """
    Extract the project name from an encoded path.

    Args:
        encoded_path: Path like "-path-to-project-name"

    Returns:
        Project name like "Agent-ATABlogger"
    """
    # The last segment after the known prefixes is typically the project name
    # Handle cases like "-path-to-project-name"
    parts = encoded_path.split('-')

    # Find common parent path segments to skip. Claude Code encodes project
    # paths by replacing "/" with "-", so project names containing dashes are
    # ambiguous without stopping at common repo/workspace container names.
    skip_segments = {
        'Users',
        'home',
        'Desktop',
        'Documents',
        'Downloads',
        'GitRepos',
        'projects',
        'repos',
        'repo',
        'repositories',
        'source',
        'src',
        'workspace',
        'workspaces',
    }

    # Walk from the end to find project name
    result_parts = []
    for part in reversed(parts):
        if part in skip_segments or not part:
            break
        result_parts.insert(0, part)

    if result_parts:
        return '-'.join(result_parts)

    # Fallback: return last non-empty part
    return parts[-1] if parts else encoded_path


def iter_session_lines(session_path: Path) -> Iterator[Dict[str, Any]]:
    """
    Iterate over lines in a session JSONL file.

    Args:
        session_path: Path to the .jsonl file

    Yields:
        Parsed JSON objects from each line
    """
    with open(session_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def detect_conversation_boundaries(entries: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Detect conversation boundaries from parent_uuid chains.

    Returns mapping of message uuid -> conversation_id.

    New conversations start when:
    - First message (parent_uuid is None)
    - parent_uuid breaks the chain (references non-existent message)

    Args:
        entries: List of session entry dictionaries

    Returns:
        Dict mapping uuid to conversation_id (1, 2, 3...)
    """
    conversation_map = {}
    current_conversation_id = 0
    seen_uuids = set()

    for entry in entries:
        entry_type = entry.get('type')
        if entry_type not in ('user', 'assistant'):
            continue

        uuid = entry.get('uuid')
        parent_uuid = entry.get('parentUuid')

        # Start new conversation if parent breaks chain
        if parent_uuid is None or parent_uuid not in seen_uuids:
            current_conversation_id += 1

        if uuid:
            conversation_map[uuid] = current_conversation_id
            seen_uuids.add(uuid)

    return conversation_map


def parse_session_summary(session_path: Path, project_name: str) -> Optional[SessionSummary]:
    """
    Parse a session file into a summary (without full message content).

    Args:
        session_path: Path to the session .jsonl file
        project_name: Name of the project

    Returns:
        SessionSummary or None if file cannot be parsed
    """
    session_id = session_path.stem
    project_path = decode_project_path(session_path.parent.name)

    message_count = 0
    tool_call_count = 0
    has_errors = False
    has_subagents = False
    created_at = None
    last_activity = None
    # Token accumulators
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_read_tokens = 0
    total_cache_creation_tokens = 0
    # Conversation tracking
    current_conversation_id = 1

    try:
        # Collect all entries for conversation detection
        all_entries = list(iter_session_lines(session_path))
        conversation_map = detect_conversation_boundaries(all_entries)

        for entry in all_entries:
            entry_type = entry.get('type', '')
            timestamp = entry.get('timestamp')

            # Track timestamps
            if timestamp:
                if created_at is None:
                    created_at = timestamp
                last_activity = timestamp

            # Count messages
            if entry_type in ('user', 'assistant'):
                message_count += 1

                # Track current conversation ID
                uuid = entry.get('uuid')
                if uuid and uuid in conversation_map:
                    current_conversation_id = conversation_map[uuid]

                # Check for tool calls in assistant messages
                message = entry.get('message', {})
                content = message.get('content', '')

                # Extract token usage from assistant messages
                if entry_type == 'assistant':
                    usage = message.get('usage', {})
                    total_input_tokens += usage.get('input_tokens', 0)
                    total_output_tokens += usage.get('output_tokens', 0)
                    total_cache_read_tokens += usage.get('cache_read_input_tokens', 0)
                    total_cache_creation_tokens += usage.get('cache_creation_input_tokens', 0)

                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get('type') == 'tool_use':
                                tool_call_count += 1
                            if block.get('type') == 'tool_result':
                                # Check for errors in tool results
                                result_content = block.get('content', '')
                                if isinstance(result_content, str) and 'error' in result_content.lower():
                                    has_errors = True

                # Check for subagent invocations (Task tool)
                if entry.get('isSidechain'):
                    has_subagents = True

        if message_count == 0:
            return None

        # Calculate conversation count
        conversation_count = max(conversation_map.values()) if conversation_map else 1

        return SessionSummary(
            id=session_id,
            project=project_name,
            project_path=project_path,
            created_at=created_at or '',
            last_activity=last_activity or '',
            message_count=message_count,
            tool_call_count=tool_call_count,
            has_errors=has_errors,
            has_subagents=has_subagents,
            total_input_tokens=total_input_tokens + total_cache_read_tokens + total_cache_creation_tokens,
            total_output_tokens=total_output_tokens,
            total_cache_read_tokens=total_cache_read_tokens,
            total_cache_creation_tokens=total_cache_creation_tokens,
            conversation_count=conversation_count,
            current_conversation_id=current_conversation_id,
        )
    except Exception:
        return None


def parse_conversation_summaries(
    session_path: Path,
    project_name: str
) -> List['ConversationSummary']:
    """
    Parse conversation summaries from a session file.

    Groups messages by conversation_id and returns token totals per conversation.

    Args:
        session_path: Path to the session .jsonl file
        project_name: Name of the project

    Returns:
        List of ConversationSummary objects
    """
    from .models.conversation import ConversationSummary

    all_entries = list(iter_session_lines(session_path))
    conversation_map = detect_conversation_boundaries(all_entries)

    if not conversation_map:
        return []

    # Initialize conversation data structures
    conversations: Dict[int, Dict[str, Any]] = {}

    for entry in all_entries:
        entry_type = entry.get('type')
        uuid = entry.get('uuid')

        if uuid not in conversation_map:
            continue

        conv_id = conversation_map[uuid]

        # Initialize conversation if first time seeing it
        if conv_id not in conversations:
            conversations[conv_id] = {
                'session_id': session_path.stem,
                'project': project_name,
                'conversation_id': conv_id,
                'message_count': 0,
                'user_message_count': 0,
                'assistant_message_count': 0,
                'tool_call_count': 0,
                'created_at': '',
                'ended_at': None,
                'total_input_tokens': 0,
                'total_output_tokens': 0,
                'total_cache_read_tokens': 0,
                'total_cache_creation_tokens': 0,
            }

        conv_data = conversations[conv_id]

        # Update timestamps
        timestamp = entry.get('timestamp', '')
        if not conv_data['created_at']:
            conv_data['created_at'] = timestamp
        conv_data['ended_at'] = timestamp

        # Count messages
        if entry_type == 'user':
            conv_data['message_count'] += 1
            conv_data['user_message_count'] += 1
        elif entry_type == 'assistant':
            conv_data['message_count'] += 1
            conv_data['assistant_message_count'] += 1

            # Accumulate tokens
            message = entry.get('message', {})
            usage = message.get('usage', {})
            input_tok = usage.get('input_tokens', 0)
            cache_read = usage.get('cache_read_input_tokens', 0)
            cache_creation = usage.get('cache_creation_input_tokens', 0)
            # total_input_tokens includes base + cache tokens (consistent with session parsing)
            conv_data['total_input_tokens'] += input_tok + cache_read + cache_creation
            conv_data['total_output_tokens'] += usage.get('output_tokens', 0)
            conv_data['total_cache_read_tokens'] += cache_read
            conv_data['total_cache_creation_tokens'] += cache_creation

            # Count tool calls in assistant messages
            content = message.get('content', '')
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_use':
                        conv_data['tool_call_count'] += 1

    # Convert to ConversationSummary objects
    return [ConversationSummary(**data) for data in conversations.values()]


def parse_tool_call(tool_use: Dict[str, Any], tool_result: Optional[Dict[str, Any]] = None) -> ToolCall:
    """
    Parse a tool_use block and its result into a ToolCall model.

    Args:
        tool_use: The tool_use block from message content
        tool_result: Optional matching tool_result block

    Returns:
        ToolCall model
    """
    tool_id = tool_use.get('id', '')
    tool_name = tool_use.get('name', '')
    tool_input = tool_use.get('input', {})

    # Determine status and result/error
    status = ToolCallStatus.SUCCESS
    result = None
    error = None

    if tool_result:
        result_content = tool_result.get('content', '')
        is_error = tool_result.get('is_error', False)

        if is_error:
            status = ToolCallStatus.ERROR
            error = {
                'type': 'tool_error',
                'message': result_content if isinstance(result_content, str) else str(result_content)
            }
        else:
            result = {
                'output': result_content if isinstance(result_content, str) else result_content
            }

            # Check for timeout indicators
            if isinstance(result_content, str) and 'timeout' in result_content.lower():
                status = ToolCallStatus.TIMEOUT
                error = {'type': 'timeout', 'message': result_content}
                result = None

    return ToolCall(
        id=tool_id,
        tool=tool_name,
        status=status,
        input=tool_input,
        result=result,
        error=error,
    )


def parse_message(
    entry: Dict[str, Any],
    tool_results: Dict[str, Dict],
    conversation_map: Optional[Dict[str, int]] = None
) -> Message:
    """
    Parse a message entry into a Message model.

    Args:
        entry: The JSONL entry
        tool_results: Dict mapping tool_use_id to tool_result blocks
        conversation_map: Optional mapping of uuid to conversation_id

    Returns:
        Message model
    """
    message = entry.get('message', {})
    content = message.get('content', '')

    # Extract text content and tool calls
    text_content = ''
    tool_calls = []

    if isinstance(content, str):
        text_content = content
    elif isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                block_type = block.get('type', '')
                if block_type == 'text':
                    text_parts.append(block.get('text', ''))
                elif block_type == 'tool_use':
                    tool_id = block.get('id', '')
                    tool_result = tool_results.get(tool_id)
                    tool_calls.append(parse_tool_call(block, tool_result))
            elif isinstance(block, str):
                text_parts.append(block)
        text_content = '\n'.join(text_parts)

    # Get conversation_id from map if provided
    uuid = entry.get('uuid', '')
    conversation_id = conversation_map.get(uuid) if conversation_map and uuid else None

    return Message(
        uuid=uuid,
        parent_uuid=entry.get('parentUuid'),
        conversation_id=conversation_id,
        type=entry.get('type', ''),
        timestamp=entry.get('timestamp', ''),
        content=text_content,
        tool_calls=tool_calls,
    )


def parse_full_session(session_path: Path, project_name: str) -> Optional[Session]:
    """
    Parse a complete session file with all messages and tool calls.

    Args:
        session_path: Path to the session .jsonl file
        project_name: Name of the project

    Returns:
        Session model or None if file cannot be parsed
    """
    session_id = session_path.stem
    project_path = decode_project_path(session_path.parent.name)

    messages = []
    subagents = {}
    errors = []

    created_at = None
    last_activity = None
    claude_code_version = None
    model = None
    git_branch = None
    cwd = None

    # Collect all entries and detect conversation boundaries
    entries = list(iter_session_lines(session_path))
    conversation_map = detect_conversation_boundaries(entries)

    # First pass: collect tool results
    tool_results = {}
    for entry in entries:
        message = entry.get('message', {})
        content = message.get('content', '')

        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'tool_result':
                    tool_use_id = block.get('tool_use_id', '')
                    if tool_use_id:
                        tool_results[tool_use_id] = block

    # Second pass: build messages
    for entry in entries:
        entry_type = entry.get('type', '')
        timestamp = entry.get('timestamp')

        # Track metadata
        if timestamp:
            if created_at is None:
                created_at = timestamp
            last_activity = timestamp

        if entry.get('version'):
            claude_code_version = entry.get('version')
        if entry.get('gitBranch'):
            git_branch = entry.get('gitBranch')
        if entry.get('cwd'):
            cwd = entry.get('cwd')

        # Skip non-message entries
        if entry_type not in ('user', 'assistant'):
            continue

        # Skip meta messages
        if entry.get('isMeta'):
            continue

        message = parse_message(entry, tool_results, conversation_map)

        # Check if this is a sidechain (subagent) message
        if entry.get('isSidechain'):
            # Group sidechain messages by their parent
            parent_uuid = entry.get('parentUuid', '')
            if parent_uuid not in subagents:
                subagents[parent_uuid] = Subagent(
                    id=parent_uuid,
                    type='unknown',  # Will be determined from Task tool call
                    parent_tool_call_id=parent_uuid,
                    prompt='',
                    status='completed',
                    created_at=timestamp or '',
                    messages=[],
                )
            subagents[parent_uuid].messages.append(message)
        else:
            messages.append(message)

        # Track errors from tool calls
        for tc in message.tool_calls:
            if tc.status == ToolCallStatus.ERROR and tc.error:
                errors.append({
                    'timestamp': timestamp,
                    'type': 'tool_error',
                    'tool': tc.tool,
                    'message': tc.error.get('message', ''),
                })

    # Load todos for this session
    todos = load_session_todos(session_id)

    return Session(
        id=session_id,
        project=project_name,
        project_path=project_path,
        created_at=created_at or '',
        last_activity=last_activity or '',
        claude_code_version=claude_code_version,
        model=model,
        git_branch=git_branch,
        cwd=cwd,
        messages=messages,
        subagents=subagents,
        todos=todos,
        errors=errors,
    )


def load_session_todos(session_id: str) -> List[Todo]:
    """
    Load todos for a specific session from ~/.claude/todos/

    Args:
        session_id: The session UUID

    Returns:
        List of Todo models
    """
    todos_dir = Path.home() / '.claude' / 'todos'
    if not todos_dir.exists():
        return []

    todos = []

    # Find todo files matching this session
    for todo_file in todos_dir.glob(f'{session_id}-*.json'):
        try:
            with open(todo_file, 'r', encoding='utf-8') as f:
                todo_data = json.load(f)
                if isinstance(todo_data, list):
                    for item in todo_data:
                        status_str = item.get('status', 'pending')
                        try:
                            status = TodoStatus(status_str)
                        except ValueError:
                            status = TodoStatus.PENDING

                        todos.append(Todo(
                            id=item.get('id'),
                            content=item.get('content', ''),
                            active_form=item.get('activeForm'),
                            status=status,
                            priority=item.get('priority'),
                        ))
        except (json.JSONDecodeError, IOError):
            continue

    return todos


def extract_tool_calls_from_session(session_path: Path, project_name: str) -> List[Dict[str, Any]]:
    """
    Extract all tool calls from a session file.

    Args:
        session_path: Path to the session .jsonl file
        project_name: Name of the project

    Returns:
        List of tool call dictionaries with session context
    """
    session_id = session_path.stem
    tool_calls = []

    # First pass: collect tool results
    tool_results = {}
    entries = list(iter_session_lines(session_path))

    for entry in entries:
        message = entry.get('message', {})
        content = message.get('content', '')

        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'tool_result':
                    tool_use_id = block.get('tool_use_id', '')
                    if tool_use_id:
                        tool_results[tool_use_id] = block

    # Second pass: extract tool calls
    for entry in entries:
        if entry.get('type') != 'assistant':
            continue

        message = entry.get('message', {})
        content = message.get('content', '')
        timestamp = entry.get('timestamp', '')

        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'tool_use':
                    tool_id = block.get('id', '')
                    tool_result = tool_results.get(tool_id)
                    tc = parse_tool_call(block, tool_result)

                    tool_calls.append(format_tool_call_entry(
                        tc=tc,
                        session_id=session_id,
                        project=project_name,
                        timestamp=timestamp,
                        is_sidechain=entry.get('isSidechain', False),
                    ))

    return tool_calls


def extract_subagents_from_session(session_path: Path, project_name: str) -> List[Dict[str, Any]]:
    """
    Extract all subagent invocations from a session file.

    Subagent messages are stored in separate files at:
    <session_id>/subagents/agent-<agent_id>.jsonl

    Args:
        session_path: Path to the session .jsonl file
        project_name: Name of the project

    Returns:
        List of subagent dictionaries with session context
    """
    session_id = session_path.stem
    subagents = []

    # Track Task tool calls from main session (these create subagents)
    task_calls = {}

    for entry in iter_session_lines(session_path):
        entry_type = entry.get('type', '')
        timestamp = entry.get('timestamp', '')

        # Find Task tool calls
        if entry_type == 'assistant':
            message = entry.get('message', {})
            content = message.get('content', '')

            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_use':
                        if block.get('name') == 'Task':
                            tool_id = block.get('id', '')
                            tool_input = block.get('input', {})
                            task_calls[tool_id] = {
                                'id': tool_id,
                                'session_id': session_id,
                                'project': project_name,
                                'timestamp': timestamp,
                                'type': tool_input.get('subagent_type', 'unknown'),
                                'prompt': tool_input.get('prompt', ''),
                                'description': tool_input.get('description', ''),
                                'model': tool_input.get('model'),
                                'status': 'completed',
                                'message_count': 0,
                                'tool_calls': [],
                                'errors': [],
                                'total_input_tokens': 0,
                                'total_output_tokens': 0,
                                'total_cache_read_tokens': 0,
                                'total_cache_creation_tokens': 0,
                            }

    # Check for subagent files in <session_id>/subagents/ directory
    subagents_dir = session_path.parent / session_id / 'subagents'
    subagent_data = {}  # Map prompt prefix to subagent stats

    if subagents_dir.exists():
        for subagent_file in subagents_dir.glob('agent-*.jsonl'):
            agent_id = subagent_file.stem.replace('agent-', '')
            entries = list(iter_session_lines(subagent_file))

            if not entries:
                continue

            # First entry contains the prompt
            first_entry = entries[0]
            prompt_content = first_entry.get('message', {}).get('content', '')
            # Handle content as list of content blocks or string
            if isinstance(prompt_content, list):
                # Extract text from content blocks
                prompt_parts = []
                for block in prompt_content:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        prompt_parts.append(block.get('text', ''))
                    elif isinstance(block, str):
                        prompt_parts.append(block)
                prompt = ' '.join(prompt_parts)
            else:
                prompt = prompt_content if isinstance(prompt_content, str) else str(prompt_content)
            timestamp = first_entry.get('timestamp', '')

            # Count messages, tool calls, errors, and tokens
            message_count = 0
            tool_calls = []
            errors = []
            total_input_tokens = 0
            total_output_tokens = 0
            total_cache_read_tokens = 0
            total_cache_creation_tokens = 0

            # First pass: collect tool_results by tool_use_id
            tool_results_map: Dict[str, Dict] = {}
            for entry in entries:
                msg = entry.get('message', {})
                content = msg.get('content', '')
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get('type') == 'tool_result':
                            tool_use_id = block.get('tool_use_id', '')
                            if tool_use_id:
                                tool_results_map[tool_use_id] = block

            # Second pass: extract tool calls, errors, and tokens
            for entry in entries:
                entry_type = entry.get('type', '')
                entry_timestamp = entry.get('timestamp', timestamp)
                if entry_type in ('user', 'assistant'):
                    message_count += 1

                msg = entry.get('message', {})
                content = msg.get('content', '')

                # Accumulate token usage from assistant messages
                if entry_type == 'assistant':
                    usage = msg.get('usage', {})
                    input_tok = usage.get('input_tokens', 0)
                    cache_read = usage.get('cache_read_input_tokens', 0)
                    cache_creation = usage.get('cache_creation_input_tokens', 0)
                    total_input_tokens += input_tok + cache_read + cache_creation
                    total_output_tokens += usage.get('output_tokens', 0)
                    total_cache_read_tokens += cache_read
                    total_cache_creation_tokens += cache_creation

                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get('type') == 'tool_use':
                                tool_id = block.get('id', '')
                                tool_result = tool_results_map.get(tool_id)
                                tc = parse_tool_call(block, tool_result)
                                tool_calls.append(format_tool_call_entry(
                                    tc=tc,
                                    session_id=session_id,
                                    project=project_name,
                                    timestamp=entry_timestamp,
                                    is_sidechain=True,
                                    agent_id=agent_id,
                                ))
                                # Track errors separately for backward compatibility
                                if tc.error:
                                    errors.append({
                                        'tool_use_id': tool_id,
                                        'content': tc.error.get('message', '')[:500],
                                    })

            subagent_data[prompt[:100]] = {
                'agent_id': agent_id,
                'message_count': message_count,
                'tool_calls': tool_calls,
                'errors': errors,
                'timestamp': timestamp,
                'total_input_tokens': total_input_tokens,
                'total_output_tokens': total_output_tokens,
                'total_cache_read_tokens': total_cache_read_tokens,
                'total_cache_creation_tokens': total_cache_creation_tokens,
            }

    # Match Task calls to subagent data using prompt prefix
    for task_id, task_info in task_calls.items():
        prompt_prefix = task_info['prompt'][:100]
        if prompt_prefix in subagent_data:
            data = subagent_data[prompt_prefix]
            task_info['message_count'] = data['message_count']
            task_info['tool_calls'] = data['tool_calls']
            task_info['errors'] = data['errors']
            task_info['agent_id'] = data['agent_id']
            task_info['total_input_tokens'] = data['total_input_tokens']
            task_info['total_output_tokens'] = data['total_output_tokens']
            task_info['total_cache_read_tokens'] = data['total_cache_read_tokens']
            task_info['total_cache_creation_tokens'] = data['total_cache_creation_tokens']
            # Remove matched entry
            del subagent_data[prompt_prefix]

        subagents.append(task_info)

    # Add any unmatched subagent files (orphaned subagents)
    for prompt_prefix, data in subagent_data.items():
        subagents.append({
            'id': f"agent-{data['agent_id']}",
            'session_id': session_id,
            'project': project_name,
            'timestamp': data['timestamp'],
            'type': 'unknown',
            'prompt': prompt_prefix,
            'description': '',
            'model': None,
            'status': 'completed',
            'message_count': data['message_count'],
            'tool_calls': data['tool_calls'],
            'errors': data['errors'],
            'agent_id': data['agent_id'],
            'total_input_tokens': data['total_input_tokens'],
            'total_output_tokens': data['total_output_tokens'],
            'total_cache_read_tokens': data['total_cache_read_tokens'],
            'total_cache_creation_tokens': data['total_cache_creation_tokens'],
        })

    return subagents


def extract_skill_invocations_from_session(session_path: Path, project_name: str) -> List[Dict[str, Any]]:
    """
    Extract all skill/command invocations from a session file.

    Skill invocations appear in user messages with <command-name> tags.

    Args:
        session_path: Path to the session .jsonl file
        project_name: Name of the project

    Returns:
        List of skill invocation dictionaries
    """
    import re

    session_id = session_path.stem
    skills = []

    for entry in iter_session_lines(session_path):
        if entry.get('type') != 'user':
            continue

        message = entry.get('message', {})
        content = message.get('content', '')
        timestamp = entry.get('timestamp', '')
        uuid = entry.get('uuid', '')

        if not isinstance(content, str):
            continue

        # Look for command invocations: <command-name>/skill-name</command-name>
        command_match = re.search(r'<command-name>/([^<]+)</command-name>', content)
        if command_match:
            skill_name = command_match.group(1).strip()

            # Extract command message if present
            msg_match = re.search(r'<command-message>([^<]*)</command-message>', content)
            command_message = msg_match.group(1).strip() if msg_match else None

            # Extract args if present
            args_match = re.search(r'<command-args>([^<]*)</command-args>', content)
            args = args_match.group(1).strip() if args_match else None

            skills.append({
                'id': uuid,
                'session_id': session_id,
                'project': project_name,
                'timestamp': timestamp,
                'name': skill_name,
                'args': args if args else None,
                'message': command_message if command_message else None,
            })

    return skills


def extract_tool_calls_with_subagents(session_path: Path, project_name: str) -> List[Dict[str, Any]]:
    """
    Extract all tool calls from a session file AND its subagent files.

    Args:
        session_path: Path to the session .jsonl file
        project_name: Name of the project

    Returns:
        List of tool call dictionaries including subagent tool calls
    """
    session_id = session_path.stem

    # Get main session tool calls
    tool_calls = extract_tool_calls_from_session(session_path, project_name)

    # Build mapping from agent_id to parent Task tool call ID
    # by matching Task tool call prompts to subagent file prompts
    agent_to_task_id = _build_agent_to_task_mapping(session_path)

    # Check for subagent files
    subagents_dir = session_path.parent / session_id / 'subagents'
    if subagents_dir.exists():
        for subagent_file in subagents_dir.glob('agent-*.jsonl'):
            agent_id = subagent_file.stem.replace('agent-', '')
            parent_task_id = agent_to_task_id.get(agent_id)

            # Collect tool results first
            tool_results = {}
            entries = list(iter_session_lines(subagent_file))

            for entry in entries:
                message = entry.get('message', {})
                content = message.get('content', '')

                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get('type') == 'tool_result':
                            tool_use_id = block.get('tool_use_id', '')
                            if tool_use_id:
                                tool_results[tool_use_id] = block

            # Extract tool calls
            for entry in entries:
                if entry.get('type') != 'assistant':
                    continue

                message = entry.get('message', {})
                content = message.get('content', '')
                timestamp = entry.get('timestamp', '')

                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get('type') == 'tool_use':
                            tool_id = block.get('id', '')
                            tool_result = tool_results.get(tool_id)
                            tc = parse_tool_call(block, tool_result)

                            tool_calls.append(format_tool_call_entry(
                                tc=tc,
                                session_id=session_id,
                                project=project_name,
                                timestamp=timestamp,
                                is_sidechain=True,
                                agent_id=agent_id,
                                parent_tool_call_id=parent_task_id,
                            ))

    return tool_calls


def _build_agent_to_task_mapping(session_path: Path) -> Dict[str, str]:
    """
    Build a mapping from agent_id to parent Task tool call ID.

    Matches Task tool calls from the main session to subagent files
    by comparing prompt prefixes.

    Args:
        session_path: Path to the session .jsonl file

    Returns:
        Dict mapping agent_id to Task tool call ID
    """
    session_id = session_path.stem
    subagents_dir = session_path.parent / session_id / 'subagents'

    if not subagents_dir.exists():
        return {}

    # Collect Task tool calls with their prompts
    task_calls = {}  # prompt_prefix -> task_id
    for entry in iter_session_lines(session_path):
        if entry.get('type') != 'assistant':
            continue

        message = entry.get('message', {})
        content = message.get('content', '')

        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'tool_use':
                    if block.get('name') == 'Task':
                        tool_id = block.get('id', '')
                        tool_input = block.get('input', {})
                        prompt = tool_input.get('prompt', '')
                        prompt_prefix = prompt[:100]
                        task_calls[prompt_prefix] = tool_id

    # Match subagent files to Task calls by prompt
    agent_to_task = {}
    for subagent_file in subagents_dir.glob('agent-*.jsonl'):
        agent_id = subagent_file.stem.replace('agent-', '')
        entries = list(iter_session_lines(subagent_file))

        if not entries:
            continue

        # Get prompt from first entry
        first_entry = entries[0]
        prompt_content = first_entry.get('message', {}).get('content', '')

        if isinstance(prompt_content, list):
            prompt_parts = []
            for block in prompt_content:
                if isinstance(block, dict) and block.get('type') == 'text':
                    prompt_parts.append(block.get('text', ''))
                elif isinstance(block, str):
                    prompt_parts.append(block)
            prompt = ' '.join(prompt_parts)
        else:
            prompt = prompt_content if isinstance(prompt_content, str) else str(prompt_content)

        prompt_prefix = prompt[:100]

        if prompt_prefix in task_calls:
            agent_to_task[agent_id] = task_calls[prompt_prefix]

    return agent_to_task


def calculate_turn_cost(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
) -> int:
    """
    Calculate the effective token cost for a single API turn.

    Formula: input + output + cache_creation + (cache_read * 0.1)

    Cache read tokens are heavily discounted (90% off) in Claude's pricing,
    so we count them at 10% of their value for Claude Max usage tracking.

    Args:
        input_tokens: Base input tokens (excludes cache)
        output_tokens: Output tokens generated by Claude
        cache_read_tokens: Tokens read from cache (discounted)
        cache_creation_tokens: Tokens used to create cache entries

    Returns:
        Effective token cost for this turn
    """
    return input_tokens + output_tokens + cache_creation_tokens + int(cache_read_tokens * 0.1)


def extract_timeline_from_session(
    session_path: Path,
    project_name: str,
    show_thinking: bool = False,
) -> List[TimelineEntry]:
    """
    Extract a unified timeline of all activities from a session.

    Combines:
    - Skill/command invocations
    - Tool calls (main session)
    - Subagent launches
    - Subagent tool calls
    - Errors
    - Thinking blocks (when show_thinking=True)

    Args:
        session_path: Path to the session .jsonl file
        project_name: Name of the project
        show_thinking: Include Claude's thinking/reasoning blocks (default: False)

    Returns:
        List of TimelineEntry objects sorted by timestamp
    """
    import re

    session_id = session_path.stem
    timeline = []

    # Collect all entries and detect conversation boundaries
    entries = list(iter_session_lines(session_path))
    conversation_map = detect_conversation_boundaries(entries)

    # Collect tool results for status lookup
    tool_results = {}

    for entry in entries:
        message = entry.get('message', {})
        content = message.get('content', '')
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'tool_result':
                    tool_use_id = block.get('tool_use_id', '')
                    if tool_use_id:
                        tool_results[tool_use_id] = block

    # Track last user message to propagate token usage from first assistant response
    last_user_entry: Optional[TimelineEntry] = None
    # Track if we've already attributed costs to user message (first response only)
    user_got_first_response_cost = False
    # Track last usage to detect duplicate streaming chunks (same API response logged multiple times)
    last_usage_signature: Optional[tuple] = None
    # Track current conversation ID
    current_conversation_id = 1

    # Process main session entries
    for entry in entries:
        entry_type = entry.get('type', '')
        timestamp = entry.get('timestamp', '')
        uuid = entry.get('uuid', '')

        # Update current conversation ID from the map
        if uuid and uuid in conversation_map:
            current_conversation_id = conversation_map[uuid]

        # Extract user messages and skill invocations
        if entry_type == 'user':
            message = entry.get('message', {})
            content = message.get('content', '')
            if isinstance(content, str):
                # Check for skill invocation
                command_match = re.search(r'<command-name>/([^<]+)</command-name>', content)
                if command_match:
                    skill_name = command_match.group(1).strip()
                    user_entry = TimelineEntry(
                        id=uuid,
                        session_id=session_id,
                        timestamp=timestamp,
                        event_type=TimelineEventType.SKILL,
                        name=skill_name,
                        status='invoked',
                        conversation_id=current_conversation_id,
                    )
                    timeline.append(user_entry)
                    last_user_entry = user_entry
                    user_got_first_response_cost = False  # Reset for new user turn
                else:
                    # Extract user message (strip XML tags)
                    clean_content = re.sub(r'<[^>]+>', '', content).strip()
                    # Skip empty messages, system-only messages, or local command caveats
                    if clean_content and not clean_content.startswith('Caveat:'):
                        # Check if this is a warmup message (subagent initialization)
                        if clean_content == 'Warmup':
                            user_entry = TimelineEntry(
                                id=uuid,
                                session_id=session_id,
                                timestamp=timestamp,
                                event_type=TimelineEventType.AGENT_WARMUP,
                                name='agent warmup',
                                status=None,
                                input=clean_content,
                                conversation_id=current_conversation_id,
                            )
                            timeline.append(user_entry)
                            last_user_entry = user_entry
                            user_got_first_response_cost = False  # Reset for new user turn
                        else:
                            user_entry = TimelineEntry(
                                id=uuid,
                                session_id=session_id,
                                timestamp=timestamp,
                                event_type=TimelineEventType.USER_MESSAGE,
                                name='user prompt',
                                status=None,
                                input=clean_content,
                                conversation_id=current_conversation_id,
                            )
                            timeline.append(user_entry)
                            last_user_entry = user_entry
                            user_got_first_response_cost = False  # Reset for new user turn

        # Extract tool calls from assistant messages
        if entry_type == 'assistant':
            message = entry.get('message', {})
            content = message.get('content', '')

            # Extract token usage from the message
            usage = message.get('usage', {})
            input_tokens = usage.get('input_tokens', 0)
            output_tokens = usage.get('output_tokens', 0)
            cache_read_tokens = usage.get('cache_read_input_tokens', 0)
            cache_creation_tokens = usage.get('cache_creation_input_tokens', 0)
            # Total input includes base + cache tokens
            total_input_tokens = input_tokens + cache_read_tokens + cache_creation_tokens
            # Calculate effective turn cost for Claude Max tracking
            turn_cost = calculate_turn_cost(
                input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens
            )

            # Check what content types this entry has
            has_tool_use = False
            has_text = False
            has_thinking = False
            text_content = ''
            thinking_content = ''
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get('type') == 'tool_use':
                            has_tool_use = True
                        elif block.get('type') == 'text':
                            has_text = True
                            text_content = block.get('text', '')
                        elif block.get('type') == 'thinking':
                            has_thinking = True
                            thinking_content = block.get('thinking', '')

            # Skip entries that only have thinking content (no text, no tools) unless show_thinking is enabled
            if not has_tool_use and not has_text:
                if has_thinking and show_thinking:
                    # Create a thinking event
                    timeline.append(TimelineEntry(
                        id=uuid,
                        session_id=session_id,
                        timestamp=timestamp,
                        event_type=TimelineEventType.THINKING,
                        name='thinking',
                        status=None,
                        output=thinking_content,
                        conversation_id=current_conversation_id,
                    ))
                continue

            # Detect duplicate streaming chunks (multiple tool_use entries with same usage = same API response)
            usage_signature = (input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens)
            is_duplicate_usage = (usage_signature == last_usage_signature)
            if not is_duplicate_usage and turn_cost > 0:
                last_usage_signature = usage_signature

            # Determine if this is the first assistant response after a user message
            # First response cost goes to user message, subsequent response costs go to tool calls
            is_first_response = not user_got_first_response_cost

            # Attribute cost
            if not is_duplicate_usage:
                if is_first_response and last_user_entry is not None and turn_cost > 0:
                    # First response - propagate cost to user message
                    last_user_entry.input_tokens = total_input_tokens if total_input_tokens > 0 else None
                    last_user_entry.output_tokens = output_tokens if output_tokens > 0 else None
                    last_user_entry.cache_read_tokens = cache_read_tokens if cache_read_tokens > 0 else None
                    last_user_entry.cache_creation_tokens = cache_creation_tokens if cache_creation_tokens > 0 else None
                    last_user_entry.turn_cost = turn_cost
                    user_got_first_response_cost = True

            # If this is a text-only response (no tool calls), create an assistant message entry
            if has_text and not has_tool_use:
                # Determine cost attribution for text-only response
                if is_duplicate_usage:
                    msg_turn_cost = None
                    msg_tokens = (None, None, None, None)
                elif is_first_response and turn_cost > 0:
                    # First response - cost goes to user message, mark as attributed
                    user_got_first_response_cost = True
                    msg_turn_cost = None
                    msg_tokens = (None, None, None, None)
                else:
                    msg_turn_cost = turn_cost if turn_cost > 0 else None
                    msg_tokens = (
                        total_input_tokens if total_input_tokens > 0 else None,
                        output_tokens if output_tokens > 0 else None,
                        cache_read_tokens if cache_read_tokens > 0 else None,
                        cache_creation_tokens if cache_creation_tokens > 0 else None,
                    )

                timeline.append(TimelineEntry(
                    id=uuid,
                    session_id=session_id,
                    timestamp=timestamp,
                    event_type=TimelineEventType.ASSISTANT_MESSAGE,
                    name='assistant response',
                    status=None,
                    output=text_content,
                    input_tokens=msg_tokens[0],
                    output_tokens=msg_tokens[1],
                    cache_read_tokens=msg_tokens[2],
                    cache_creation_tokens=msg_tokens[3],
                    turn_cost=msg_turn_cost,
                    conversation_id=current_conversation_id,
                ))
                continue  # Skip tool processing since there are no tools

            # Track if we've assigned cost to a tool in this response (only first tool gets cost)
            first_tool_in_response = True

            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_use':
                        tool_name = block.get('name', '')
                        tool_id = block.get('id', '')
                        tool_input = block.get('input', {})
                        tool_result = tool_results.get(tool_id)

                        # Determine status and get output
                        status = 'success'
                        error_message = None
                        tool_output = None
                        if tool_result:
                            if tool_result.get('is_error'):
                                status = 'error'
                                error_message = str(tool_result.get('content', ''))[:200]
                            tool_output = tool_result.get('content')

                        # Assign cost to tool calls:
                        # - Duplicate entry (same usage as previous): no cost (already counted)
                        # - First response after user: cost goes to user message, tools get nothing
                        # - Subsequent responses: first tool gets cost, others in same entry get nothing
                        if is_duplicate_usage:
                            # Duplicate entry - skip cost
                            tool_turn_cost = None
                            tool_tokens = (None, None, None, None)
                        elif is_first_response:
                            # First response - user message has the cost
                            tool_turn_cost = None
                            tool_tokens = (None, None, None, None)
                        elif first_tool_in_response and turn_cost > 0:
                            # Subsequent response - first tool gets the cost
                            tool_turn_cost = turn_cost
                            tool_tokens = (
                                total_input_tokens if total_input_tokens > 0 else None,
                                output_tokens if output_tokens > 0 else None,
                                cache_read_tokens if cache_read_tokens > 0 else None,
                                cache_creation_tokens if cache_creation_tokens > 0 else None,
                            )
                            first_tool_in_response = False
                        else:
                            # Same entry, not first tool
                            tool_turn_cost = None
                            tool_tokens = (None, None, None, None)

                        # Check if this is a subagent launch
                        if tool_name == 'Task':
                            subagent_type = tool_input.get('subagent_type', 'unknown')
                            description = tool_input.get('description', '')
                            prompt = tool_input.get('prompt', '')
                            timeline.append(TimelineEntry(
                                id=tool_id,
                                session_id=session_id,
                                timestamp=timestamp,
                                event_type=TimelineEventType.SUBAGENT_START,
                                name=subagent_type,
                                status=status,
                                details={'description': description},
                                error_message=error_message,
                                input=prompt,
                                output=tool_output,
                                input_tokens=tool_tokens[0],
                                output_tokens=tool_tokens[1],
                                cache_read_tokens=tool_tokens[2],
                                cache_creation_tokens=tool_tokens[3],
                                turn_cost=tool_turn_cost,
                                conversation_id=current_conversation_id,
                            ))
                        else:
                            timeline.append(TimelineEntry(
                                id=tool_id,
                                session_id=session_id,
                                timestamp=timestamp,
                                event_type=TimelineEventType.TOOL_CALL,
                                name=tool_name,
                                status=status,
                                error_message=error_message,
                                input=tool_input,
                                output=tool_output,
                                input_tokens=tool_tokens[0],
                                output_tokens=tool_tokens[1],
                                cache_read_tokens=tool_tokens[2],
                                cache_creation_tokens=tool_tokens[3],
                                turn_cost=tool_turn_cost,
                                conversation_id=current_conversation_id,
                            ))

    # Build a mapping from agent_id to agent_name (subagent_type)
    # by matching Task calls to subagent files via prompt prefix
    agent_id_to_name = {}
    subagents_dir = session_path.parent / session_id / 'subagents'

    if subagents_dir.exists():
        # First, collect Task calls with their prompts and types
        task_calls = {}  # Maps prompt_prefix -> subagent_type
        for entry in entries:
            if entry.get('type') == 'assistant':
                message = entry.get('message', {})
                content = message.get('content', '')
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get('type') == 'tool_use':
                            if block.get('name') == 'Task':
                                tool_input = block.get('input', {})
                                prompt = tool_input.get('prompt', '')
                                subagent_type = tool_input.get('subagent_type', 'unknown')
                                if prompt:
                                    task_calls[prompt[:100]] = subagent_type

        # Match subagent files to Task calls by prompt prefix
        for subagent_file in subagents_dir.glob('agent-*.jsonl'):
            agent_id = subagent_file.stem.replace('agent-', '')
            subagent_entries = list(iter_session_lines(subagent_file))
            if subagent_entries:
                first_entry = subagent_entries[0]
                prompt = first_entry.get('message', {}).get('content', '')
                prompt_prefix = prompt[:100] if isinstance(prompt, str) else ''
                if prompt_prefix in task_calls:
                    agent_id_to_name[agent_id] = task_calls[prompt_prefix]

    # Process subagent files
    if subagents_dir.exists():
        for subagent_file in subagents_dir.glob('agent-*.jsonl'):
            agent_id = subagent_file.stem.replace('agent-', '')

            # Collect tool results
            subagent_tool_results = {}
            subagent_entries = list(iter_session_lines(subagent_file))

            for entry in subagent_entries:
                message = entry.get('message', {})
                content = message.get('content', '')
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get('type') == 'tool_result':
                            tool_use_id = block.get('tool_use_id', '')
                            if tool_use_id:
                                subagent_tool_results[tool_use_id] = block

            # Extract tool calls
            for entry in subagent_entries:
                if entry.get('type') != 'assistant':
                    continue

                message = entry.get('message', {})
                content = message.get('content', '')
                timestamp = entry.get('timestamp', '')

                # Extract token usage from the message
                usage = message.get('usage', {})
                input_tokens = usage.get('input_tokens', 0)
                output_tokens = usage.get('output_tokens', 0)
                cache_read_tokens = usage.get('cache_read_input_tokens', 0)
                cache_creation_tokens = usage.get('cache_creation_input_tokens', 0)
                total_input_tokens = input_tokens + cache_read_tokens + cache_creation_tokens
                # Calculate effective turn cost for Claude Max tracking
                turn_cost = calculate_turn_cost(
                    input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens
                )

                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get('type') == 'tool_use':
                            tool_name = block.get('name', '')
                            tool_id = block.get('id', '')
                            tool_input = block.get('input', {})
                            tool_result = subagent_tool_results.get(tool_id)

                            # Determine status and get output
                            status = 'success'
                            error_message = None
                            tool_output = None
                            if tool_result:
                                if tool_result.get('is_error'):
                                    status = 'error'
                                    error_message = str(tool_result.get('content', ''))[:200]
                                tool_output = tool_result.get('content')

                            timeline.append(TimelineEntry(
                                id=tool_id,
                                session_id=session_id,
                                timestamp=timestamp,
                                event_type=TimelineEventType.SUBAGENT_TOOL,
                                name=tool_name,
                                status=status,
                                agent_id=agent_id,
                                agent_name=agent_id_to_name.get(agent_id),
                                error_message=error_message,
                                input=tool_input,
                                output=tool_output,
                                input_tokens=total_input_tokens if total_input_tokens > 0 else None,
                                output_tokens=output_tokens if output_tokens > 0 else None,
                                cache_read_tokens=cache_read_tokens if cache_read_tokens > 0 else None,
                                cache_creation_tokens=cache_creation_tokens if cache_creation_tokens > 0 else None,
                                turn_cost=turn_cost if turn_cost > 0 else None,
                            ))

    # Sort by timestamp
    timeline.sort(key=lambda e: e.timestamp or '')

    # Calculate cumulative session_total and conversation_total
    # Track seen message IDs to avoid double-counting when multiple tools in same turn
    cumulative_total = 0
    conversation_totals: Dict[int, int] = {}  # conversation_id -> cumulative total
    seen_turns = set()

    for entry in timeline:
        if entry.turn_cost and entry.turn_cost > 0:
            # Use timestamp + a marker to identify unique API turns
            # Multiple tool calls in same turn will have same timestamp
            turn_key = f"{entry.timestamp}:{entry.event_type.value}"

            # Only add to cumulative if we haven't seen this turn
            # (handles multiple tool calls in same assistant message)
            if turn_key not in seen_turns:
                cumulative_total += entry.turn_cost

                # Track conversation total
                conv_id = entry.conversation_id
                if conv_id not in conversation_totals:
                    conversation_totals[conv_id] = 0
                conversation_totals[conv_id] += entry.turn_cost

                seen_turns.add(turn_key)

        entry.session_total = cumulative_total if cumulative_total > 0 else None
        entry.conversation_total = conversation_totals.get(entry.conversation_id, 0) or None

    return timeline


def _extract_text_content(content: Any) -> str:
    """Extract plain text from a message content field (string or content blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get('type') == 'text':
                    parts.append(block.get('text', ''))
                elif block.get('type') == 'tool_result':
                    rc = block.get('content', '')
                    if isinstance(rc, str):
                        parts.append(rc)
                    elif isinstance(rc, list):
                        for rb in rc:
                            if isinstance(rb, dict) and rb.get('type') == 'text':
                                parts.append(rb.get('text', ''))
            elif isinstance(block, str):
                parts.append(block)
        return '\n'.join(parts)
    return ''


def _snippet_around(text: str, keyword_lower: str, radius: int = 120) -> str:
    """Return a snippet of text centered on the first occurrence of keyword."""
    idx = text.lower().find(keyword_lower)
    if idx == -1:
        return text[:radius * 2]
    start = max(0, idx - radius)
    end = min(len(text), idx + len(keyword_lower) + radius)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = '...' + snippet
    if end < len(text):
        snippet = snippet + '...'
    return snippet


def search_session_file(
    session_path: Path,
    query: str,
    project_name: str,
    max_matches: int = 5,
) -> Optional[SearchResult]:
    """
    Fast keyword search through a session JSONL file.

    Does a raw text check on each line first (fast), then parses only
    matching lines to extract role, snippet, and timestamp.

    Args:
        session_path: Path to the .jsonl file
        query: Search keyword(s) — case-insensitive
        project_name: Project display name
        max_matches: Maximum snippet matches to return per session

    Returns:
        SearchResult if any matches found, None otherwise
    """
    session_id = session_path.stem
    project_path = decode_project_path(session_path.parent.name)
    query_lower = query.lower()

    matches: List[SearchMatch] = []
    created_at = ''
    last_activity = ''

    with open(session_path, 'r', encoding='utf-8') as f:
        for line in f:
            # Fast pre-check: skip lines that don't contain the query at all
            if query_lower not in line.lower():
                continue

            try:
                entry = json.loads(line.strip())
            except json.JSONDecodeError:
                continue

            timestamp = entry.get('timestamp', '')
            if timestamp:
                if not created_at:
                    created_at = timestamp
                last_activity = timestamp

            entry_type = entry.get('type', '')
            if entry_type not in ('user', 'assistant'):
                continue

            # Skip meta messages
            if entry.get('isMeta'):
                continue

            message = entry.get('message', {})
            content = message.get('content', '')
            text = _extract_text_content(content)

            if query_lower not in text.lower():
                continue

            snippet = _snippet_around(text, query_lower)
            matches.append(SearchMatch(
                role=entry_type,
                snippet=snippet,
                timestamp=timestamp,
            ))

            if len(matches) >= max_matches:
                break

    if not matches:
        return None

    # Get timestamps from first/last lines if we didn't capture them from matches
    if not created_at or not last_activity:
        with open(session_path, 'r', encoding='utf-8') as f:
            for raw_line in f:
                try:
                    e = json.loads(raw_line.strip())
                    ts = e.get('timestamp', '')
                    if ts:
                        if not created_at:
                            created_at = ts
                        last_activity = ts
                except json.JSONDecodeError:
                    continue

    return SearchResult(
        session_id=session_id,
        project=project_name,
        project_path=project_path,
        created_at=created_at,
        last_activity=last_activity,
        match_count=len(matches),
        matches=matches,
    )
