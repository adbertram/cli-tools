"""Orchestration: discover → parse → sort → write JSONL/CSV."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..models import OutputFormat
from .discovery import discover_log_files
from .parsers import parser_for
from .sessions import assign_entries_to_sessions, detect_sessions
from .types import ClassifiedLogFile, InternalLogEntry

_CSV_FIELDS = [
    "timestamp", "entity", "service", "instance", "container",
    "level", "message", "source_file", "line_number", "session_id",
]


def parse_all_files(files: list[ClassifiedLogFile]) -> list[InternalLogEntry]:
    """Dispatch each file to its parser, flatten results."""
    entries: list[InternalLogEntry] = []
    for f in files:
        parser = parser_for(f.entity)
        entries.extend(parser(f))
    return entries


def sort_entries(entries: list[InternalLogEntry]) -> list[InternalLogEntry]:
    """Sort by (timestamp, entity, line_number)."""
    return sorted(entries, key=lambda e: (e.timestamp, e.entity.value, e.line_number))


def _entry_to_dict(entry: InternalLogEntry) -> dict:
    """Convert internal entry to serializable dict."""
    return {
        "timestamp": entry.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
        "entity": entry.entity.value,
        "service": entry.service,
        "instance": entry.instance,
        "container": entry.container,
        "level": entry.level.value,
        "message": entry.message,
        "source_file": entry.source_file,
        "line_number": entry.line_number,
        "session_id": entry.session_id,
    }


def write_jsonl(entries: list[InternalLogEntry], output_path: Path) -> int:
    """Write one JSON object per line. Returns count."""
    with output_path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(_entry_to_dict(entry), ensure_ascii=False) + "\n")
    return len(entries)


def write_csv(entries: list[InternalLogEntry], output_path: Path) -> int:
    """Write entries as CSV with header row. Returns count."""
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for entry in entries:
            writer.writerow(_entry_to_dict(entry))
    return len(entries)


def _default_output_path(log_dir: Path, fmt: OutputFormat) -> Path:
    ext = "csv" if fmt is OutputFormat.CSV else "jsonl"
    return log_dir / f"merged.{ext}"


def create_log_package(
    log_dir: Path,
    output_path: Path | None = None,
    fmt: OutputFormat = OutputFormat.JSONL,
    generate_html: bool = True,
    cutoff: Optional[datetime] = None,
) -> tuple[Path, list[InternalLogEntry]]:
    """Discover → parse → sort → write. Returns (output_path, entries).

    If cutoff is provided, skip docker files with dates before the cutoff
    and filter out entries with timestamps before the cutoff.
    """
    import sys

    if output_path is None:
        output_path = _default_output_path(log_dir, fmt)

    files = discover_log_files(log_dir, cutoff=cutoff)
    print(f"Discovered {len(files)} log files", file=sys.stderr)

    entries = parse_all_files(files)
    print(f"Parsed {len(entries)} log entries", file=sys.stderr)

    # Filter entries by cutoff timestamp
    if cutoff:
        pre_filter = len(entries)
        entries = [e for e in entries if e.timestamp >= cutoff]
        print(
            f"Filtered to {len(entries)} entries since {cutoff.strftime('%Y-%m-%d %H:%M')} "
            f"(removed {pre_filter - len(entries)})",
            file=sys.stderr,
        )

    entries = sort_entries(entries)

    # Detect container lifecycle sessions and assign entries
    sessions = detect_sessions(entries)
    assign_entries_to_sessions(entries, sessions)
    print(f"Detected {len(sessions)} sessions", file=sys.stderr)

    writer = write_csv if fmt is OutputFormat.CSV else write_jsonl
    count = writer(entries, output_path)
    print(f"Wrote {count} entries to {output_path}", file=sys.stderr)

    # Generate HTML report if requested
    if generate_html:
        from .report import generate_report
        report_path = output_path.parent / "report.html"
        generate_report(entries, report_path, sessions=sessions)

    return output_path, entries
