"""Site envelopes: one JSON file per site per discovery run.

An envelope records what happened when the site's CLI was run -- `ok` with the
raw task list, or one of the four failure statuses with a reason. Every write
and read passes through the envelope schema.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import schema

OK = "ok"
AUTH_FAILED = "auth_failed"
NO_CLI = "no_cli"
NO_ACCOUNT = "no_account"
ERROR = "error"
STATUSES = (OK, AUTH_FAILED, NO_CLI, NO_ACCOUNT, ERROR)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build(site: str, status: str, error: str | None, tasks: list) -> dict:
    return {
        "site": site,
        "status": status,
        "fetched_at": utc_now(),
        "error": error,
        "tasks": tasks,
    }


def write(path: Path, data: dict) -> None:
    schema.validate_envelope(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def read(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    schema.validate_envelope(data, label=str(path))
    return data
