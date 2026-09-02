"""Site envelopes: one JSON file per site per discovery run.

An envelope records what happened when the site's CLI was run -- `ok` with the
raw task list, or one of the four failure statuses with a reason. Every write
and read passes through the envelope schema.

Serialization goes through `jsonio`, never `json` directly, so an envelope file
is always strict JSON: a non-finite number inside a site's raw record fails the
write rather than producing a file that `microworker validate` calls valid and
`JSON.parse` rejects.

`fetched_at` is the OBSERVATION time -- when this site's CLI answered -- and it
is what `merge` records as the task's first/last seen time. It is not the merge
time; those two can be months apart when an old run is merged late.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import jsonio, schema

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
    path.write_text(jsonio.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def read(path: Path) -> dict:
    data = jsonio.read_file(path)
    schema.validate_envelope(data, label=str(path))
    return data
