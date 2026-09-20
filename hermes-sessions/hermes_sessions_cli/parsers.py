"""Pure helpers: time handling, bounded/redacted text, and record shaping.

Nothing here touches SQLite. Every function is deterministic so the parsing
rules can be tested without a Hermes home.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Text the CLI prints is always a bounded preview, never a raw transcript.
DEFAULT_MAX_CHARS = 200

# Secret shapes that can appear inside a tool argument or a pasted message.
# Each entry is (pattern, replacement). `\1` keeps the label so a redacted
# preview still reads sensibly; patterns with no label mask the whole match.
_SECRET_PATTERNS = [
    # `Authorization: Bearer <token>` and `Authorization: Basic <base64>`.
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]{8,}"), r"\1=[REDACTED]"),
    (re.compile(r"\b(sk|rk|pk)-[A-Za-z0-9_\-]{12,}"), r"\1=[REDACTED]"),
    (re.compile(r"\b(gh[pousr]|github_pat)_[A-Za-z0-9_]{12,}"), r"\1=[REDACTED]"),
    (re.compile(r"\b(xox[abprs])-[A-Za-z0-9\-]{8,}"), r"\1=[REDACTED]"),
    # AWS access key identifiers. The 4-letter prefix set is AWS's documented
    # unique-id prefix list; the whole identifier is masked because the prefix
    # alone already identifies the credential class.
    (
        re.compile(
            r"\b(?:ABIA|ACCA|AGPA|AIDA|AIPA|AKIA|ANPA|ANVA|APKA|AROA|ASCA|ASIA)[0-9A-Z]{16}\b"
        ),
        "[REDACTED]",
    ),
    # Credentials embedded in a URL: scheme://user:secret@host.
    (
        re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@]{1,128}:[^/\s@]{1,256}@"),
        r"\1[REDACTED]@",
    ),
    # `curl -u user:secret` / `--user user:secret`.
    (
        re.compile(r"(?i)(?<![\w\-])(-u|--user)\s+[^\s:]{1,128}:[^\s]{1,256}"),
        r"\1 [REDACTED]",
    ),
    # Any `<something>key|secret|token|password|credential = value` assignment.
    # The label prefix is deliberately broad (api_key, access_key,
    # client_secret, refresh_token, ...): over-redacting a preview is always
    # safer than printing one live credential. The value alternation takes a
    # whole quoted string first so a multi-word secret cannot leave its tail
    # behind, and only then an unquoted run.
    (
        re.compile(
            r"(?i)\b([A-Za-z0-9_\-]*(?:key|secret|token|password|passwd|pwd|credential))"
            r'\s*[:=]\s*(?:"[^"\n]{1,256}"|\'[^\'\n]{1,256}\'|[^\s"\',;}]{4,})'
        ),
        r"\1=[REDACTED]",
    ),
]

# Marker appended when text is cut. The single-character form keeps the
# promise that a preview never exceeds its cap even at cap 1.
_LONG_ELLIPSIS = "..."
_SHORT_ELLIPSIS = "\u2026"


def redact(text: str) -> str:
    """Mask credential-shaped substrings, keeping the surrounding words."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def bounded_text(text: str, max_chars: int) -> str:
    """Cut `text` so the RESULT, ellipsis included, never exceeds the cap.

    A non-positive cap clamps to 1 rather than meaning "unbounded": this CLI's
    contract is that it can never print a raw transcript.
    """
    limit = max(1, max_chars)
    if len(text) <= limit:
        return text
    marker = _LONG_ELLIPSIS if limit > len(_LONG_ELLIPSIS) else _SHORT_ELLIPSIS
    if len(marker) >= limit:
        return marker[:limit]
    return text[: limit - len(marker)].rstrip() + marker


def preview(value: Any, max_chars: int = DEFAULT_MAX_CHARS) -> Optional[str]:
    """Render any value as one bounded, redacted, single-line string.

    Returns None for absent values so a missing field stays null in JSON
    instead of becoming an empty string.
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        text = json.dumps(value, separators=(",", ":"), default=str)
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return bounded_text(redact(text), max_chars)


def casefold_key(value: Optional[str]) -> Optional[str]:
    """Unicode-aware case-insensitive key for title comparison.

    SQLite's own `lower()` only folds ASCII, so "\u00dcBER" never matches
    "\u00fcber" there. `str.casefold()` applies full Unicode case folding,
    which also maps German "\u00df" to "ss".
    """
    if value is None:
        return None
    return value.casefold()


def to_iso(epoch: Optional[float]) -> Optional[str]:
    """Convert Hermes' REAL epoch seconds to an ISO-8601 UTC string."""
    if epoch is None:
        return None
    try:
        moment = datetime.fromtimestamp(float(epoch), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def format_local_time(iso: Optional[str], fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Render an ISO-8601 timestamp in the local timezone for table output."""
    if not iso:
        return ""
    try:
        moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return moment.astimezone().strftime(fmt)


def parse_since(since: Optional[str]) -> Optional[float]:
    """Convert a `5h` / `1d` / `30m` / `2w` window to an epoch-seconds cutoff."""
    if not since:
        return None
    match = re.fullmatch(r"(\d+)\s*([smhdw])", since.strip().lower())
    if not match:
        raise ValueError(
            f"invalid --since value {since!r}; use forms like 30m, 5h, 7d, 2w"
        )
    amount = int(match.group(1))
    unit = match.group(2)
    seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
    return (datetime.now(tz=timezone.utc) - timedelta(seconds=amount * seconds)).timestamp()


def _local_day_bounds(day: datetime) -> Tuple[float, float]:
    """Epoch bounds of one local calendar day."""
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def _parse_day(value: str) -> datetime:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").astimezone()
    except ValueError:
        raise ValueError(f"invalid date {value!r}; use YYYY-MM-DD")


def resolve_date_selector(
    date: Optional[str] = None,
    date_range: Optional[str] = None,
    date_alias: Optional[str] = None,
) -> Optional[Tuple[float, float]]:
    """Resolve one local-date selector to an inclusive epoch-seconds window."""
    provided = [value for value in (date, date_range, date_alias) if value]
    if not provided:
        return None
    if len(provided) > 1:
        raise ValueError("use only one of --date / --date-range / --date-alias")

    if date:
        return _local_day_bounds(_parse_day(date))

    if date_range:
        if ".." not in date_range:
            raise ValueError(
                f"invalid --date-range {date_range!r}; use START..END (YYYY-MM-DD..YYYY-MM-DD)"
            )
        raw_start, _, raw_end = date_range.partition("..")
        start = _parse_day(raw_start)
        end = _parse_day(raw_end)
        if end < start:
            raise ValueError(f"invalid --date-range {date_range!r}; END precedes START")
        return _local_day_bounds(start)[0], _local_day_bounds(end)[1]

    today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    alias = date_alias.strip().lower()
    if alias == "today":
        return _local_day_bounds(today)
    if alias == "yesterday":
        return _local_day_bounds(today - timedelta(days=1))
    if alias in ("this_week", "last_week"):
        monday = today - timedelta(days=today.weekday())
        if alias == "last_week":
            monday -= timedelta(days=7)
        return monday.timestamp(), (monday + timedelta(days=7)).timestamp()
    raise ValueError(
        f"invalid --date-alias {date_alias!r}; use today, yesterday, this_week, or last_week"
    )


# Hermes counts `input_tokens` as uncached input, so cache reads are weighted
# back in explicitly. Matching the sibling session CLIs' cost-weighted total.
CACHE_READ_WEIGHT = 0.1


def effective_tokens(row: Dict[str, Any]) -> int:
    """Cost-weighted token total for a session row."""
    return int(
        (row.get("input_tokens") or 0)
        + (row.get("output_tokens") or 0)
        + (row.get("cache_read_tokens") or 0) * CACHE_READ_WEIGHT
    )


NO_WORKSPACE = "(no-workspace)"


def workspace_key(cwd: Optional[str]) -> Optional[str]:
    """Canonical workspace identity for a session's `cwd`.

    Hermes writes NULL for gateway and cron sessions, but a session can also
    carry an empty or whitespace-only `cwd`. All of those mean "no workspace"
    and must collapse to the same key, otherwise a project row counts sessions
    that scoping to that project can never return.
    """
    if cwd is None:
        return None
    trimmed = cwd.strip()
    if not trimmed:
        return None
    normalized = trimmed.rstrip("/")
    return normalized or "/"


def project_name(cwd: Optional[str]) -> str:
    """Project label for a session's working directory."""
    key = workspace_key(cwd)
    if key is None:
        return NO_WORKSPACE
    return key.rsplit("/", 1)[-1] or key


def parse_tool_calls(raw: Optional[str]) -> List[Dict[str, Any]]:
    """Parse the OpenAI-style `messages.tool_calls` JSON array.

    Hermes writes a JSON array of objects carrying `id`/`call_id` and a
    `function` object with `name` and a JSON-encoded `arguments` string.
    Malformed or unexpected payloads yield no calls rather than raising, so one
    bad row never hides a whole session.
    """
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []

    calls = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        function = entry.get("function")
        function = function if isinstance(function, dict) else {}
        name = function.get("name") or entry.get("name")
        if not name:
            continue
        calls.append(
            {
                "id": entry.get("call_id") or entry.get("id") or "",
                "name": str(name),
                "arguments": parse_arguments(function.get("arguments")),
            }
        )
    return calls


def parse_arguments(raw: Any) -> Dict[str, Any]:
    """Parse a tool call's `arguments`, which Hermes stores as a JSON string."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def extract_todos(arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pull the `todos[]` list out of a `todo` tool call's arguments.

    Hermes rewrites the entire list on every `todo` call, so the last call in a
    session holds the final state.
    """
    todos = arguments.get("todos")
    if not isinstance(todos, list):
        return []
    rows = []
    for position, entry in enumerate(todos):
        if not isinstance(entry, dict):
            continue
        content = entry.get("content") or entry.get("task") or entry.get("title")
        if content is None:
            continue
        rows.append(
            {
                "position": position,
                "content": str(content),
                "status": str(entry.get("status") or "unknown"),
            }
        )
    return rows


# Tool names Hermes uses for its skills subsystem.
SKILL_TOOLS = {"skill_view", "skill_manage", "skills_list"}
# The subagent delegation tool.
DELEGATE_TOOL = "delegate_task"
# The todo list tool.
TODO_TOOL = "todo"

_SLASH_COMMAND = re.compile(r"^/([A-Za-z0-9][A-Za-z0-9_\-]*)")


def slash_command_name(content: Optional[str]) -> Optional[str]:
    """Return the command name when a user message starts with a slash command."""
    if not content:
        return None
    first_line = content.lstrip().splitlines()[0] if content.strip() else ""
    match = _SLASH_COMMAND.match(first_line)
    if not match:
        return None
    return match.group(1)


def skill_name_from_result(content: Optional[str], arguments: Dict[str, Any]) -> Optional[str]:
    """Best available name for a skill tool call.

    The call's own arguments are authoritative; the tool result JSON is used
    only when the arguments did not name the skill.
    """
    for key in ("name", "skill", "skill_name"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if content:
        try:
            payload = json.loads(content)
        except ValueError:
            return None
        if isinstance(payload, dict):
            value = payload.get("name")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


# A plaintext tool result that is unambiguously a failure.
_ERROR_TEXT_MARKERS = ("Traceback (most recent call last):",)


def tool_status(content: Optional[str]) -> str:
    """Classify a tool result as success, error, or pending.

    Hermes tool results are JSON objects. A successful `terminal` call writes
    `{"output": ..., "exit_code": 0, "error": null}`, so the failure signal is
    the *value* of `error`/`exit_code`/`success`, never the presence of the
    word "error" in the payload.
    """
    if content is None:
        return "pending"

    try:
        payload = json.loads(content)
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        if payload.get("success") is False:
            return "error"
        error = payload.get("error")
        if error not in (None, "", [], {}):
            return "error"
        exit_code = payload.get("exit_code")
        if isinstance(exit_code, int) and exit_code != 0:
            return "error"
        return "success"

    for marker in _ERROR_TEXT_MARKERS:
        if marker in content[:4000]:
            return "error"
    return "success"


def is_compaction_boundary(row: Dict[str, Any]) -> bool:
    """Whether a message row starts a new post-compaction context segment."""
    return bool(row.get("_compressed_summary"))


def segment_conversations(messages: Iterable[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Split a session's messages into context segments at compaction points.

    A session that was never compacted yields exactly one segment. An empty
    session yields no segments.
    """
    segments: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    for row in messages:
        if is_compaction_boundary(row) and current:
            segments.append(current)
            current = []
        current.append(row)
    if current:
        segments.append(current)
    return segments


def segment_turns(messages: Iterable[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Split a session's messages into turns, each opened by a user message.

    Messages that precede the first user message (system notices, resumed
    context) form a leading turn so no message is silently dropped.
    """
    turns: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    for row in messages:
        if row.get("role") == "user" and current:
            turns.append(current)
            current = []
        current.append(row)
    if current:
        turns.append(current)
    return turns
