"""Directory scanning + classification of log files."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..models import Entity
from .filename import entity_for_container_type, parse_docker_log_filename
from .types import ClassifiedLogFile


def _file_date_before_cutoff(date_str: str, cutoff: datetime) -> bool:
    """Check if a docker log filename date (YYYY_MM_DD) is before the cutoff date."""
    try:
        file_date = datetime.strptime(date_str, "%Y_%m_%d").date()
        return file_date < cutoff.date()
    except ValueError:
        return False


def discover_log_files(
    log_dir: Path, cutoff: Optional[datetime] = None,
) -> list[ClassifiedLogFile]:
    """Walk log_dir, classify each log file by entity type.

    If cutoff is provided, skip docker log files whose filename date is
    before the cutoff date. Non-docker files are always included.
    """
    results: list[ClassifiedLogFile] = []
    skipped = 0

    for path in sorted(log_dir.rglob("*")):
        if not path.is_file():
            continue

        relative = str(path.relative_to(log_dir))

        # Skip non-log files
        if path.suffix not in (".log", ".txt"):
            continue

        # Kudu trace .txt files
        if "kudu/trace/" in relative and path.suffix == ".txt":
            results.append(ClassifiedLogFile(
                path=path,
                relative_path=relative,
                entity=Entity.KUDU_TRACE,
                metadata=None,
            ))
            continue

        # ciem.log (application log)
        if path.name == "ciem.log":
            results.append(ClassifiedLogFile(
                path=path,
                relative_path=relative,
                entity=Entity.APP_LOG,
                metadata=None,
            ))
            continue

        # Docker log files in LogFiles/
        meta = parse_docker_log_filename(path.name)
        if meta is not None:
            # Skip docker files with dates before the cutoff
            if cutoff and _file_date_before_cutoff(meta.date, cutoff):
                skipped += 1
                continue

            entity = entity_for_container_type(meta.container_type)
            results.append(ClassifiedLogFile(
                path=path,
                relative_path=relative,
                entity=entity,
                metadata=meta,
            ))
            continue

        # Unknown .log files — skip silently

    if skipped:
        import sys
        print(f"Skipped {skipped} docker log files (before cutoff)", file=sys.stderr)

    return results


def group_by_entity(
    files: list[ClassifiedLogFile],
) -> dict[Entity, list[ClassifiedLogFile]]:
    """Group classified files by entity type."""
    groups: dict[Entity, list[ClassifiedLogFile]] = defaultdict(list)
    for f in files:
        groups[f.entity].append(f)
    return dict(groups)
