"""Line-level completeness verification."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..models import Entity, LogLevel
from .discovery import discover_log_files
from .types import ClassifiedLogFile, InternalLogEntry, InternalValidationResult


def count_nonempty_lines(path: Path) -> set[int]:
    """Return set of 1-indexed line numbers for non-empty lines."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {i + 1 for i, line in enumerate(lines) if line.strip()}


def count_file_lines(files: list[ClassifiedLogFile]) -> dict[str, set[int]]:
    return {f.relative_path: count_nonempty_lines(f.path) for f in files}


def build_line_coverage(entries: list[InternalLogEntry]) -> dict[str, set[int]]:
    coverage: dict[str, set[int]] = {}
    for entry in entries:
        lines_spanned = entry.message.count("\n") + 1
        file_set = coverage.setdefault(entry.source_file, set())
        for offset in range(lines_spanned):
            file_set.add(entry.line_number + offset)
    return coverage


def find_missing_lines(
    expected: dict[str, set[int]],
    covered: dict[str, set[int]],
) -> list[tuple[str, int]]:
    missing: list[tuple[str, int]] = []
    for filename, expected_lines in sorted(expected.items()):
        covered_lines = covered.get(filename, set())
        for line_num in sorted(expected_lines - covered_lines):
            missing.append((filename, line_num))
    return missing


def validate(
    log_dir: Path,
    entries: list[InternalLogEntry],
) -> InternalValidationResult:
    """Validate entries cover every non-empty line in raw files."""
    files = discover_log_files(log_dir)
    expected = count_file_lines(files)
    covered = build_line_coverage(entries)
    missing = find_missing_lines(expected, covered)

    total_raw = sum(len(s) for s in expected.values())
    total_covered = min(sum(len(s) for s in covered.values()), total_raw)

    return InternalValidationResult(
        total_raw_lines=total_raw,
        total_covered_lines=total_raw - len(missing),
        missing_lines=missing,
        is_valid=len(missing) == 0,
    )


def validate_jsonl(log_dir: Path, jsonl_path: Path) -> InternalValidationResult:
    """Read existing JSONL file, reconstruct entries, then validate."""
    entries: list[InternalLogEntry] = []
    with jsonl_path.open(encoding="utf-8") as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            d = json.loads(raw_line)
            entries.append(InternalLogEntry(
                timestamp=datetime.fromisoformat(d["timestamp"].rstrip("Z")),
                entity=Entity(d["entity"]),
                service=d["service"],
                instance=d.get("instance"),
                container=d.get("container"),
                level=LogLevel(d["level"]),
                message=d["message"],
                source_file=d["source_file"],
                line_number=d["line_number"],
            ))
    return validate(log_dir, entries)
