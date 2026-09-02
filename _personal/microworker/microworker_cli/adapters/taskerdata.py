"""Adapter for `taskerdata tasks list` records.

Not implemented: no `ok` taskerdata envelope with tasks has been observed, so
there is no verified raw record shape to map. `merge` never reaches this while
taskerdata envelopes carry zero tasks.

The unimplemented case is a `ClientError`, not a `NotImplementedError`.
"this site has no verified record shape yet" is a contract failure of the
merge, and the CLI's exit-2 contract error handler only sees `ClientError`
and `ConfigError`; a bare `NotImplementedError` escapes it and exits 1,
which is the code the discovery agent reads as "unexpected crash".
"""

from __future__ import annotations

from cli_tools_shared.exceptions import ClientError

SITE = "taskerdata"


def to_task(raw: dict) -> dict:
    raise ClientError(
        f"{SITE} adapter is not implemented; no verified raw record shape yet "
        f"(record keys: {', '.join(sorted(raw))})")
