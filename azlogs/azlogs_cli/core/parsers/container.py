"""Parser for app container and SCM sidecar logs."""
from __future__ import annotations

import re

from ...models import LogLevel
from ..types import ClassifiedLogFile, InternalLogEntry
from . import collect_multiline, normalize_level, parse_iso_timestamp

_STRUCTURED_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2} ([A-Z]{3})\] (\S+) (.*)$")
_BARE_LEVEL_RE = re.compile(r"^(info|warn|warning|fail|error|debug|dbg|err): (\S+?)(?:\[\d+\])?\s*$")


def _starts_new_entry(line: str) -> bool:
    return bool(parse_iso_timestamp(line))


def _split_iso_prefix(line: str) -> tuple[str, str]:
    idx = line.find("Z")
    if idx == -1:
        return line, ""
    return line[:idx + 1], line[idx + 1:].lstrip()


def parse_structured_line(text: str) -> tuple[str, LogLevel, str] | None:
    m = _STRUCTURED_RE.match(text)
    if not m:
        return None
    level_str, service, message = m.groups()
    return service, normalize_level(level_str), message


def parse_bare_level_line(text: str) -> tuple[str, LogLevel] | None:
    m = _BARE_LEVEL_RE.match(text)
    if not m:
        return None
    return m.group(2), normalize_level(m.group(1))


def parse(file: ClassifiedLogFile) -> list[InternalLogEntry]:
    """Parse a container log file (app or SCM)."""
    content = file.path.read_text(encoding="utf-8", errors="replace")
    raw_lines = content.splitlines()
    if not raw_lines:
        return []

    instance = file.metadata.instance if file.metadata else None
    entity = file.entity
    entries: list[InternalLogEntry] = []

    grouped = collect_multiline(raw_lines, _starts_new_entry)

    for start_line, block_text in grouped:
        block_lines = block_text.split("\n")
        first_line = block_lines[0]

        ts = parse_iso_timestamp(first_line)
        if ts is None:
            continue

        _, rest = _split_iso_prefix(first_line)

        # Structured format: [HH:MM:SS LVL] Service message
        parsed = parse_structured_line(rest)
        if parsed:
            service, level, msg = parsed
            extra_msgs: list[str] = []
            for continuation in block_lines[1:]:
                _, cont_rest = _split_iso_prefix(continuation)
                cont_parsed = parse_structured_line(cont_rest)
                if cont_parsed:
                    extra_msgs.append(cont_parsed[2])
                else:
                    extra_msgs.append(cont_rest if cont_rest else continuation)

            full_message = "\n".join([msg] + extra_msgs) if extra_msgs else msg

            entries.append(InternalLogEntry(
                timestamp=ts, entity=entity, service=service, instance=instance,
                container=None, level=level, message=full_message,
                source_file=file.relative_path, line_number=start_line,
            ))
            continue

        # Bare level format: warn: Service.Name[0]
        bare = parse_bare_level_line(rest)
        if bare:
            service, level = bare
            cont_parts: list[str] = []
            for continuation in block_lines[1:]:
                _, cont_rest = _split_iso_prefix(continuation)
                cont_parts.append(cont_rest.strip() if cont_rest else continuation.strip())

            full_message = "\n".join(cont_parts) if cont_parts else ""

            entries.append(InternalLogEntry(
                timestamp=ts, entity=entity, service=service, instance=instance,
                container=None, level=level, message=full_message,
                source_file=file.relative_path, line_number=start_line,
            ))
            continue

        # Plain message — e.g. SCM startup text
        entries.append(InternalLogEntry(
            timestamp=ts, entity=entity, service="container", instance=instance,
            container=None, level=LogLevel.INFO, message=rest if rest else "(empty)",
            source_file=file.relative_path, line_number=start_line,
        ))

    return entries
