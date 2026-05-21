"""Codex rollout JSONL parsing utilities."""
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SESSION_SUBDIRS = ("sessions", "archived_sessions")
ROLLOUT_PREFIX = "rollout-"
ROLLOUT_SUFFIX = ".jsonl"
MESSAGE_ROLES = {"user", "assistant"}
ERROR_STATUSES = {"error", "failed", "timed_out", "timeout", "cancelled", "canceled"}
SUBAGENT_TOOL_NAMES = {"spawn_agent", "Task"}
SKILL_PREFIXES = ("$", "@")


class OutputFormat(Enum):
    """Supported raw output formats kept for wrapper-template compatibility."""

    AUTO = "auto"
    JSON = "json"
    LINES = "lines"


@dataclass(frozen=True)
class RolloutRecord:
    path: Path
    line_number: int
    timestamp: str
    record_type: str
    payload: Dict[str, Any]
    raw: Dict[str, Any]


@dataclass(frozen=True)
class ParsedRollout:
    path: Path
    records: List[RolloutRecord]
    meta: Dict[str, Any]


@dataclass(frozen=True)
class RolloutIndex:
    path: Path
    session_id: str
    cwd: str
    created_at: str
    last_activity: str


def parse_cli_output(output: str, format: OutputFormat = OutputFormat.AUTO) -> Any:
    """Parse JSON or line output retained for compatibility with wrapper helpers."""
    text = output.strip()
    if not text:
        return []
    if format in (OutputFormat.AUTO, OutputFormat.JSON) and text[0] in "[{":
        return json.loads(text)
    return [{"name": line} for line in text.splitlines() if line.strip()]


def iter_rollout_paths(codex_home: Path) -> Iterable[Path]:
    """Yield Codex rollout JSONL files from active and archived session roots."""
    for subdir in SESSION_SUBDIRS:
        root = codex_home / subdir
        if root.exists():
            yield from sorted(root.rglob(f"{ROLLOUT_PREFIX}*{ROLLOUT_SUFFIX}"))


def _read_first_nonempty_line(path: Path) -> Optional[str]:
    """Read the first non-empty line from a JSONL file."""
    with path.open("rb") as handle:
        for raw_line in handle:
            if raw_line.strip():
                return raw_line.decode("utf-8")
    return None


def _read_last_nonempty_line(path: Path) -> Optional[str]:
    """Read the last non-empty line from a JSONL file without scanning the whole file."""
    block_size = 64 * 1024
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        if position == 0:
            return None

        tail = b""
        while position > 0:
            read_size = min(block_size, position)
            position -= read_size
            handle.seek(position)
            tail = handle.read(read_size) + tail
            stripped = tail.rstrip(b" \t\r\n")
            if stripped:
                tail = stripped
                break
            tail = b""

        if not tail:
            return None

        newline_index = tail.rfind(b"\n")
        if newline_index != -1:
            return tail[newline_index + 1 :].decode("utf-8")

        while position > 0:
            newline_index = tail.rfind(b"\n")
            if newline_index != -1:
                return tail[newline_index + 1 :].decode("utf-8")
            read_size = min(block_size, position)
            position -= read_size
            handle.seek(position)
            tail = handle.read(read_size) + tail

        return tail.decode("utf-8")


def load_rollout(path: Path) -> ParsedRollout:
    """Load a Codex rollout JSONL file and return parsed records."""
    raw_lines = load_jsonl_records(path)
    if not raw_lines:
        raise ValueError(f"{path} is empty")
    if "type" not in raw_lines[0] and "id" in raw_lines[0]:
        return load_legacy_rollout(path, raw_lines)
    return load_current_rollout(path, raw_lines)


def load_rollout_index(path: Path) -> RolloutIndex:
    """Load only the metadata needed to order and filter rollout files."""
    first_line = _read_first_nonempty_line(path)
    last_line = _read_last_nonempty_line(path)

    if first_line is None or last_line is None:
        raise ValueError(f"{path} is empty")

    try:
        first_raw = json.loads(first_line)
    except json.JSONDecodeError as error:
        raise ValueError(f"{path}:1 invalid JSON: {error.msg}") from error
    if "type" not in first_raw and "id" in first_raw:
        parsed = load_rollout(path)
        return RolloutIndex(
            path=path,
            session_id=parsed.meta["id"],
            cwd=parsed.meta["cwd"],
            created_at=parsed.meta["timestamp"],
            last_activity=max_timestamp(parsed.records),
        )
    try:
        last_raw = json.loads(last_line)
    except json.JSONDecodeError:
        parsed = load_rollout(path)
        return RolloutIndex(
            path=path,
            session_id=parsed.meta["id"],
            cwd=parsed.meta["cwd"],
            created_at=parsed.meta["timestamp"],
            last_activity=max_timestamp(parsed.records),
        )
    payload = first_raw.get("payload")
    if first_raw.get("type") != "session_meta" or not isinstance(payload, dict):
        parsed = load_rollout(path)
        return RolloutIndex(
            path=path,
            session_id=parsed.meta["id"],
            cwd=parsed.meta["cwd"],
            created_at=parsed.meta["timestamp"],
            last_activity=max_timestamp(parsed.records),
        )

    require_keys(payload, ("id", "cwd", "timestamp"), path)
    last_payload = last_raw.get("payload")
    last_timestamp = last_raw.get("timestamp")
    if last_timestamp is None and isinstance(last_payload, dict):
        last_timestamp = last_payload.get("timestamp")
    if not isinstance(last_timestamp, str):
        last_timestamp = payload["timestamp"]

    return RolloutIndex(
        path=path,
        session_id=str(payload["id"]),
        cwd=str(payload["cwd"]),
        created_at=str(payload["timestamp"]),
        last_activity=last_timestamp,
    )


def load_jsonl_records(path: Path) -> List[Dict[str, Any]]:
    """Load JSONL records with transcript file and line number in parse errors."""
    records = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number} invalid JSON: {error.msg}") from error
        if not isinstance(raw, dict):
            raise ValueError(f"{path}:{line_number} record must be an object")
        records.append(raw)
    return records


def load_current_rollout(path: Path, raw_lines: List[Dict[str, Any]]) -> ParsedRollout:
    """Load the current rollout envelope format."""
    records: List[RolloutRecord] = []
    meta: Optional[Dict[str, Any]] = None
    for line_number, raw in enumerate(raw_lines, start=1):
        record_type = raw["type"]
        payload = raw["payload"]
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number} payload must be an object")
        timestamp = raw.get("timestamp") or payload.get("timestamp")
        if not timestamp:
            raise ValueError(f"{path}:{line_number} missing timestamp")
        record = RolloutRecord(
            path=path,
            line_number=line_number,
            timestamp=timestamp,
            record_type=record_type,
            payload=payload,
            raw=raw,
        )
        records.append(record)
        if record_type == "session_meta" and meta is None:
            meta = payload
    if meta is None:
        raise ValueError(f"{path} does not contain a session_meta record")
    require_keys(meta, ("id", "cwd", "timestamp"), path)
    return ParsedRollout(path=path, records=records, meta=meta)


def load_legacy_rollout(path: Path, raw_lines: List[Dict[str, Any]]) -> ParsedRollout:
    """Load the legacy Codex rollout format with top-level records."""
    first = raw_lines[0]
    require_keys(first, ("id", "timestamp"), path)
    cwd = extract_legacy_cwd(raw_lines)
    if cwd is None:
        raise ValueError(f"{path} legacy rollout missing cwd in environment_context")
    meta = {
        "id": first["id"],
        "timestamp": first["timestamp"],
        "cwd": cwd,
        "source": first.get("source"),
        "cli_version": first.get("cli_version"),
        "model_provider": first.get("model_provider"),
        "git": first.get("git"),
    }
    records = [
        RolloutRecord(
            path=path,
            line_number=1,
            timestamp=meta["timestamp"],
            record_type="session_meta",
            payload=meta,
            raw={"timestamp": meta["timestamp"], "type": "session_meta", "payload": meta},
        )
    ]
    for line_number, raw in enumerate(raw_lines[1:], start=2):
        if raw.get("record_type") == "state":
            continue
        if "type" not in raw:
            raise ValueError(f"{path}:{line_number} legacy response item missing type")
        records.append(
            RolloutRecord(
                path=path,
                line_number=line_number,
                timestamp=raw.get("timestamp") or meta["timestamp"],
                record_type="response_item",
                payload=raw,
                raw={"timestamp": raw.get("timestamp") or meta["timestamp"], "type": "response_item", "payload": raw},
            )
        )
    return ParsedRollout(path=path, records=records, meta=meta)


def extract_legacy_cwd(raw_lines: List[Dict[str, Any]]) -> Optional[str]:
    for raw in raw_lines:
        content = raw.get("content")
        text = text_from_content(content)
        match = re.search(r"<cwd>(.*?)</cwd>", text, re.DOTALL)
        if match:
            return match.group(1).strip()
    return None


def require_keys(data: Dict[str, Any], keys: Iterable[str], path: Path) -> None:
    missing = [key for key in keys if key not in data]
    if missing:
        raise ValueError(f"{path} session_meta missing required keys: {', '.join(missing)}")


def project_name(project_path: str) -> str:
    return Path(project_path).name


def encode_project_path(project_path: str) -> str:
    return project_path.replace("/", "-")


def iso_to_epoch(timestamp: str) -> float:
    normalized = timestamp.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).timestamp()


def max_timestamp(records: List[RolloutRecord]) -> str:
    return max((record.timestamp for record in records), key=iso_to_epoch)


def conversation_id_for_record(records: List[RolloutRecord], target: RolloutRecord) -> int:
    current = 1
    for record in records:
        if record.record_type == "turn_context" and record.line_number <= target.line_number:
            current = turn_index(records, record)
        if record.line_number == target.line_number:
            return current
    return current


def conversation_count(records: List[RolloutRecord]) -> int:
    count = len([record for record in records if record.record_type == "turn_context"])
    return count if count > 0 else 1


def turn_index(records: List[RolloutRecord], target: RolloutRecord) -> int:
    index = 0
    for record in records:
        if record.record_type == "turn_context":
            index += 1
        if record.line_number == target.line_number:
            return index if index > 0 else 1
    return 1


def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if "text" in item:
                    parts.append(str(item["text"]))
                if "input_text" in item:
                    parts.append(str(item["input_text"]))
                if "output_text" in item:
                    parts.append(str(item["output_text"]))
        return "\n".join(parts)
    return ""


def parse_arguments(arguments: Any) -> Dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        parsed = json.loads(arguments)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("function_call arguments must be a JSON object")


def parse_output(output: Any) -> Any:
    if isinstance(output, str) and output.strip() and output.strip()[0] in "[{":
        return json.loads(output)
    return output


def response_items(parsed: ParsedRollout, payload_type: Optional[str] = None) -> List[RolloutRecord]:
    items = [record for record in parsed.records if record.record_type == "response_item"]
    if payload_type is None:
        return items
    return [record for record in items if record.payload.get("type") == payload_type]


def event_messages(parsed: ParsedRollout, event_type: Optional[str] = None) -> List[RolloutRecord]:
    items = [record for record in parsed.records if record.record_type == "event_msg"]
    if event_type is None:
        return items
    return [record for record in items if record.payload.get("type") == event_type]


def message_records(parsed: ParsedRollout) -> List[RolloutRecord]:
    return [
        record
        for record in response_items(parsed, "message")
        if record.payload.get("role") in MESSAGE_ROLES
    ]


def tool_call_records(parsed: ParsedRollout) -> List[RolloutRecord]:
    return response_items(parsed, "function_call")


def tool_result_records(parsed: ParsedRollout) -> List[RolloutRecord]:
    return response_items(parsed, "function_call_output")


def output_records_by_call_id(parsed: ParsedRollout) -> Dict[str, RolloutRecord]:
    records = {}
    for record in tool_result_records(parsed):
        records[record.payload["call_id"]] = record
    for record in event_messages(parsed, "exec_command_end"):
        records[record.payload["call_id"]] = record
    return records


def status_for_output(record: Optional[RolloutRecord]) -> Optional[str]:
    if record is None:
        return None
    if record.record_type == "event_msg":
        return record.payload.get("status")
    return "completed"


def output_for_record(record: Optional[RolloutRecord]) -> Any:
    if record is None:
        return None
    if record.record_type == "event_msg":
        if record.payload.get("stdout"):
            return record.payload["stdout"]
        if record.payload.get("stderr"):
            return record.payload["stderr"]
        return record.payload
    if "output" in record.payload:
        return parse_output(record.payload["output"])
    return record.payload


def has_errors(parsed: ParsedRollout) -> bool:
    for record in event_messages(parsed):
        payload = record.payload
        status = str(payload.get("status", "")).lower()
        if status in ERROR_STATUSES:
            return True
        exit_code = payload.get("exit_code")
        if isinstance(exit_code, int) and exit_code != 0:
            return True
    return False


def token_totals(parsed: ParsedRollout) -> Dict[str, int]:
    totals = {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_read_tokens": 0,
        "total_cache_creation_tokens": 0,
    }
    token_key_map = {
        "input_tokens": "total_input_tokens",
        "output_tokens": "total_output_tokens",
        "cache_read_tokens": "total_cache_read_tokens",
        "cache_creation_tokens": "total_cache_creation_tokens",
    }
    for record in event_messages(parsed, "token_count"):
        info = record.payload.get("info")
        if isinstance(info, dict):
            for source_key, target_key in token_key_map.items():
                value = info.get(source_key)
                if isinstance(value, int):
                    totals[target_key] += value
    totals["effective_tokens"] = (
        totals["total_input_tokens"]
        + totals["total_output_tokens"]
        + totals["total_cache_creation_tokens"]
    )
    return totals


def session_text(parsed: ParsedRollout) -> str:
    chunks = []
    for record in parsed.records:
        payload = record.payload
        if record.record_type == "event_msg" and "message" in payload:
            chunks.append(str(payload["message"]))
        if record.record_type == "response_item":
            chunks.append(text_from_content(payload.get("content")))
            if "arguments" in payload:
                chunks.append(str(payload["arguments"]))
            if "output" in payload:
                chunks.append(str(payload["output"]))
    return "\n".join(chunk for chunk in chunks if chunk)


def extract_skill_mentions(text: str) -> List[str]:
    names = []
    for token in text.split():
        if token.startswith(SKILL_PREFIXES) and len(token) > 1:
            name = token[1:].strip(".,:;()[]{}")
            if name:
                names.append(name)
    return names


ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_RANGE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$")
DATE_ALIASES = {"today", "yesterday", "this_week", "last_week"}


def _today_local() -> date:
    """Return today's date in the local timezone."""
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
    """Resolve any of --date/--date-range/--date-alias to an inclusive local-tz datetime window.

    - --date YYYY-MM-DD: single calendar day.
    - --date-range START..END: inclusive ISO date range, START <= END.
    - --date-alias today|yesterday|this_week|last_week: aliases. Weeks are ISO weeks
      (Monday-Sunday) in local time.

    Returns None when no selector is provided. Raises ValueError on invalid input.
    """
    provided = [name for name, val in (
        ("date", date_value),
        ("date_range", date_range),
        ("date_alias", date_alias),
    ) if val is not None]
    if not provided:
        return None
    if len(provided) > 1:
        raise ValueError(
            f"--date, --date-range, and --date-alias are mutually exclusive (got: {', '.join(provided)})"
        )

    if date_value is not None:
        if not ISO_DATE_RE.match(date_value.strip()):
            raise ValueError(
                f"invalid --date value: {date_value!r}. Expected YYYY-MM-DD."
            )
        d = date.fromisoformat(date_value.strip())
        return _datetime_bounds(d, d)

    if date_range is not None:
        m = ISO_RANGE_RE.match(date_range.strip())
        if not m:
            raise ValueError(
                f"invalid --date-range value: {date_range!r}. Expected YYYY-MM-DD..YYYY-MM-DD."
            )
        start = date.fromisoformat(m.group(1))
        end = date.fromisoformat(m.group(2))
        if start > end:
            raise ValueError(
                f"invalid --date-range value: {date_range!r}. Start date must be on or before end date."
            )
        return _datetime_bounds(start, end)

    # date_alias
    norm = _normalize_alias(date_alias)
    if norm not in DATE_ALIASES:
        raise ValueError(
            f"invalid --date-alias value: {date_alias!r}. "
            f"Accepted: today, yesterday, this_week, last_week."
        )
    today = _today_local()
    if norm == "today":
        return _datetime_bounds(today, today)
    if norm == "yesterday":
        d = today - timedelta(days=1)
        return _datetime_bounds(d, d)
    # ISO weeks: Monday=1 ... Sunday=7
    iso_weekday = today.isoweekday()
    monday_this_week = today - timedelta(days=iso_weekday - 1)
    sunday_this_week = monday_this_week + timedelta(days=6)
    if norm == "this_week":
        return _datetime_bounds(monday_this_week, sunday_this_week)
    # last_week
    monday_last_week = monday_this_week - timedelta(days=7)
    sunday_last_week = monday_this_week - timedelta(days=1)
    return _datetime_bounds(monday_last_week, sunday_last_week)


def _clean_prompt_text(text: str) -> Optional[str]:
    """Return cleaned prompt text or None if it should be skipped under --prompts-clean."""
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("<"):
        return None
    if stripped.startswith("Caveat:"):
        return None
    return stripped


def extract_user_prompts(
    rollout_path: Path,
    first_n: int,
    last_n: int,
    max_chars: int,
    clean: bool,
) -> Dict[str, List[str]]:
    """Extract first/last user prompts from a Codex rollout JSONL file.

    Reads the rollout, filters to record_type == "event_msg" AND payload.type ==
    "user_message" records (reusing the event_messages() helper), extracts each
    payload.message string, optionally cleans, truncates to max_chars, and returns
    {"first_user_prompts": [...], "last_user_prompts": [...]}.

    Raises ValueError if the rollout cannot be parsed (no silent fallback).
    """
    if first_n < 0 or last_n < 0:
        raise ValueError("first_n and last_n must be >= 0")
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")

    parsed = load_rollout(rollout_path)
    prompts: List[str] = []
    for record in event_messages(parsed, "user_message"):
        message = record.payload.get("message")
        if not isinstance(message, str):
            continue
        if clean:
            cleaned = _clean_prompt_text(message)
            if cleaned is None:
                continue
            text = cleaned
        else:
            text = message
        if len(text) > max_chars:
            text = text[:max_chars]
        prompts.append(text)

    first = prompts[:first_n] if first_n > 0 else []
    last = prompts[-last_n:] if last_n > 0 else []
    return {"first_user_prompts": first, "last_user_prompts": last}


def parse_include_prompts(value: str) -> Tuple[int, int]:
    """Parse --include-prompts 'first:N,last:N' into (first_n, last_n).

    Both 'first' and 'last' are optional; missing parts default to 0. Raises ValueError
    on malformed input.
    """
    first_n = 0
    last_n = 0
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        raise ValueError(
            f"invalid --include-prompts value: {value!r}. Expected 'first:N,last:N'."
        )
    for part in parts:
        if ":" not in part:
            raise ValueError(
                f"invalid --include-prompts segment: {part!r}. Expected 'first:N' or 'last:N'."
            )
        key, _, raw = part.partition(":")
        key = key.strip().lower()
        try:
            n = int(raw.strip())
        except ValueError as error:
            raise ValueError(
                f"invalid --include-prompts segment: {part!r}. N must be an integer."
            ) from error
        if n < 0:
            raise ValueError(
                f"invalid --include-prompts segment: {part!r}. N must be >= 0."
            )
        if key == "first":
            first_n = n
        elif key == "last":
            last_n = n
        else:
            raise ValueError(
                f"invalid --include-prompts key: {key!r}. Accepted keys: first, last."
            )
    return first_n, last_n
