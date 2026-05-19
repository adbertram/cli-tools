"""Parser for platform orchestrator logs (*_docker.log without default_ prefix)."""
from __future__ import annotations

import re
from datetime import datetime

from ...models import Entity, LogLevel
from ..types import ClassifiedLogFile, InternalLogEntry
from . import parse_iso_timestamp

_CONTAINER_NAME_RE = re.compile(
    r"(?:container[: ]+|Starting container: |Stopping container: |Deleting container: |Creating container with image:.+from registry:.+)"
    r"([a-f0-9]+_[\w-]+)"
)

# Keyword patterns for inferring log level from platform messages (no explicit level in raw logs)
_ERROR_RE = re.compile(r"(?i)failed|error|fatal|crash|OOM|killed|unhealthy")
_WARNING_RE = re.compile(r"(?i)warn|timeout|timed out|probe failed|terminating|revert|retry")


def extract_container_name(message: str) -> str | None:
    """Extract container name from message."""
    m = _CONTAINER_NAME_RE.search(message)
    return m.group(1) if m else None


def _infer_level(message: str) -> LogLevel:
    """Infer log level from message keywords (platform logs have no explicit level)."""
    if _ERROR_RE.search(message):
        return LogLevel.ERROR
    if _WARNING_RE.search(message):
        return LogLevel.WARNING
    return LogLevel.INFO


def parse(file: ClassifiedLogFile) -> list[InternalLogEntry]:
    """Parse a platform orchestrator log file."""
    entries: list[InternalLogEntry] = []
    instance = file.metadata.instance if file.metadata else None

    lines = file.path.read_text(encoding="utf-8", errors="replace").splitlines()

    for i, line in enumerate(lines):
        if not line.strip():
            continue

        ts = parse_iso_timestamp(line)
        if ts is None:
            entries.append(InternalLogEntry(
                timestamp=entries[-1].timestamp if entries else datetime.min,
                entity=Entity.PLATFORM_ORCHESTRATOR,
                service="podr",
                instance=instance,
                container=None,
                level=LogLevel.UNKNOWN,
                message=line,
                source_file=file.relative_path,
                line_number=i + 1,
            ))
            continue

        msg_start = line.index("Z") + 1
        message = line[msg_start:].lstrip()
        container_name = extract_container_name(message)

        entries.append(InternalLogEntry(
            timestamp=ts,
            entity=Entity.PLATFORM_ORCHESTRATOR,
            service="podr",
            instance=instance,
            container=container_name,
            level=_infer_level(message),
            message=message,
            source_file=file.relative_path,
            line_number=i + 1,
        ))

    return entries
