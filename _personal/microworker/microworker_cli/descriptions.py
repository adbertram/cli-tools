"""`descriptions apply <file>`: persist descriptions on ledger tasks.

Every site worker must obtain a description for each of its tasks -- real text
from the site's detail page where the site publishes one (`microworker enrich`
owns that path), and a short factual generated description otherwise. This
command is the deterministic write half of that loop: it reads a JSON array of
`{site, task_id, description}`, validates every entry, and fills only rows
that carry NO stored description yet (`db.update_task_descriptions_many`), so
a real description is never overwritten by a later generated fallback.

Nothing else is stored, and no entry creates or removes a task: an entry whose
`(site, task_id)` is not in the ledger is reported as missing, not inserted.
The workers produce the text; this command only records it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cli_tools_shared.exceptions import ClientError

from . import db, jsonio


def _parse_entry(entry: Any, index: int) -> dict:
    if not isinstance(entry, dict):
        raise ClientError(f"description entry {index} is not a JSON object")
    site = entry.get("site")
    task_id = entry.get("task_id")
    if not isinstance(site, str) or not site:
        raise ClientError(f"description entry {index}: 'site' is required")
    if not isinstance(task_id, str) or not task_id:
        raise ClientError(f"description entry {index}: 'task_id' is required")
    description = entry.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ClientError(
            f"description entry {index} ({site}/{task_id}): 'description' "
            "must be a non-empty string")
    return {"site": site, "task_id": task_id, "description": description}


def apply_descriptions(file: Path) -> dict:
    """Read a descriptions file and fill empty rows for every entry."""
    data = jsonio.read_file(file, "descriptions file")
    if not isinstance(data, list):
        raise ClientError(
            "descriptions file must be a JSON array of "
            "{site, task_id, description} objects")
    entries = [_parse_entry(entry, index) for index, entry in enumerate(data)]
    result = db.update_task_descriptions_many(entries)
    return {
        "file": str(file),
        "entries": len(entries),
        "updated": result["updated"],
        "skipped": result["skipped"],
        "missing": result["missing"],
    }
