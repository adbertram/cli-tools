"""Parser for Kudu trace logs (LogFiles/kudu/trace/*.txt)."""
from __future__ import annotations

from ...models import Entity, LogLevel
from ..types import ClassifiedLogFile, InternalLogEntry
from . import collect_multiline, parse_kudu_timestamp


def _starts_new_entry(line: str) -> bool:
    return parse_kudu_timestamp(line) is not None


def parse(file: ClassifiedLogFile) -> list[InternalLogEntry]:
    """Parse a Kudu trace log file."""
    content = file.path.read_text(encoding="utf-8", errors="replace")
    raw_lines = content.splitlines()
    if not raw_lines:
        return []

    entries: list[InternalLogEntry] = []
    grouped = collect_multiline(raw_lines, _starts_new_entry)

    for start_line, block_text in grouped:
        block_lines = block_text.split("\n")
        first_line = block_lines[0]

        ts = parse_kudu_timestamp(first_line)
        if ts is None:
            continue

        idx = first_line.index("  ") + 2
        msg = first_line[idx:]

        if len(block_lines) > 1:
            full_msg = "\n".join([msg] + block_lines[1:])
        else:
            full_msg = msg

        level = LogLevel.INFO
        msg_lower = full_msg.lower()
        if "error" in msg_lower or "exception" in msg_lower:
            level = LogLevel.ERROR
        elif "warn" in msg_lower:
            level = LogLevel.WARNING

        entries.append(InternalLogEntry(
            timestamp=ts, entity=Entity.KUDU_TRACE, service="kudu", instance=None,
            container=None, level=level, message=full_msg,
            source_file=file.relative_path, line_number=start_line,
        ))

    return entries
