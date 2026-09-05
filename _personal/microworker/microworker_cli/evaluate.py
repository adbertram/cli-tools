"""`evaluate apply <file>`: persist the task-evaluator's verdicts.

The `task-evaluator` agent reads ledger tasks, applies the `task-evaluator`
skill's rules, and returns a JSON array of verdicts. This command is the
deterministic write half of that loop: it reads the verdict file, validates
every entry against the evaluator's output contract, coerces each verdict's
boolean to the ledger's 1/0/NULL, and writes `ai_can_handle` in one
transaction via `db.set_task_ai_can_handle_many`.

Nothing else is stored, and no verdict creates or removes a task: a verdict
whose `(site, task_id)` is not in the ledger is reported as missing, not
inserted. The agent does the judgment; this command only records it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cli_tools_shared.exceptions import ClientError

from . import db, jsonio


def _coerce(value: Any) -> int | None:
    """A verdict boolean to the ledger's 1/0/NULL."""
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int) and value in (0, 1):
        return value
    raise ClientError(
        f"ai_can_handle must be true, false, 1, 0, or null; got {value!r}")


def _parse_entry(entry: Any, index: int) -> dict:
    if not isinstance(entry, dict):
        raise ClientError(f"evaluation entry {index} is not a JSON object")
    site = entry.get("site")
    task_id = entry.get("task_id")
    if not isinstance(site, str) or not site:
        raise ClientError(f"evaluation entry {index}: 'site' is required")
    if not isinstance(task_id, str) or not task_id:
        raise ClientError(f"evaluation entry {index}: 'task_id' is required")
    if "ai_can_handle" not in entry:
        raise ClientError(
            f"evaluation entry {index} ({site}/{task_id}): "
            "'ai_can_handle' is required")
    return {
        "site": site,
        "task_id": task_id,
        "ai_can_handle": _coerce(entry["ai_can_handle"]),
    }


def apply_evaluation(file: Path) -> dict:
    """Read a verdict file and write `ai_can_handle` for every entry."""
    data = jsonio.read_file(file, "evaluation file")
    if not isinstance(data, list):
        raise ClientError(
            "evaluation file must be a JSON array of verdict objects")
    entries = [_parse_entry(entry, index) for index, entry in enumerate(data)]
    result = db.set_task_ai_can_handle_many(entries)
    return {
        "file": str(file),
        "verdicts": len(entries),
        "updated": result["updated"],
        "missing": result["missing"],
    }
