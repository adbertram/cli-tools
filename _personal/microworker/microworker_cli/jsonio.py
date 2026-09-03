"""JSON in and out of this tool, restricted to JSON that is actually JSON.

Python's `json` module is not a strict JSON codec by default. `json.loads`
accepts the bare literals `NaN`, `Infinity` and `-Infinity`, and `json.dumps`
emits them; neither exists in RFC 8259, so a document carrying one is rejected
by `JSON.parse`, `jq`, and every other strict reader. Python also turns an
overflowing literal such as `1e999` into `float('inf')` with no diagnostic at
all, which `parse_constant` never sees.

A non-finite number crossing this tool is never harmless. `float('nan')` bound
to a SQLite parameter is stored as SQL NULL, so a task the site priced would
read back as `pay_amount: null` -- indistinguishable from "this site published
no price" -- while `pay_currency` still names a currency. `float('inf')` stores
as a real and then makes `tasks list` print `Infinity`, so the ledger's own
output cannot be parsed by the agents that consume it.

Every load and dump in this package therefore goes through here:

  `loads()`  rejects both spellings -- the bare literal via `parse_constant`,
             and the overflow via the `check_finite()` walk over the result.
  `dumps()`  passes `allow_nan=False`, so serializing a non-finite value is a
             `ValueError` at the write instead of a corrupt file.
  `check_finite()` is the reusable walk, so a validator can reject a non-finite
             number that arrived through some other door.

The failure is a `ClientError`, so it exits 2 with the offending path named,
like every other contract violation in this tool.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from cli_tools_shared.exceptions import ClientError


class NonFiniteNumberError(ClientError):
    """The document carries NaN, Infinity or -Infinity. That is not JSON."""


def loads(text: str, label: str = "document"):
    """`json.loads` with both non-finite spellings rejected.

    `parse_constant` catches the bare literals; the `check_finite()` walk
    catches the overflow form (`1e999`), which Python converts to infinity
    inside `parse_float` and never reports.
    """
    data = json.loads(text, parse_constant=_reject_constant)
    check_finite(data, label)
    return data


def read_file(path: Path, label: str | None = None):
    """`loads()` on a file's contents, labelled with its path by default."""
    return loads(path.read_text(encoding="utf-8"), label or str(path))


def dumps(data, **kwargs) -> str:
    """`json.dumps` that refuses to emit a literal no strict parser accepts.

    `allow_nan=False` makes the encoder raise a bare `ValueError`, which would
    escape the CLI's contract-error handler and exit 1; it is re-raised as the
    same `NonFiniteNumberError` the load side produces, so both directions of
    the same violation exit 2 with the same wording.
    """
    try:
        return json.dumps(data, allow_nan=False, **kwargs)
    except ValueError as exc:
        raise NonFiniteNumberError(
            f"refusing to serialize a non-finite number: {exc}") from exc


def check_finite(data, label: str = "document") -> None:
    """Raise if any float anywhere in `data` is NaN or infinite.

    Walks dicts and lists, so a non-finite value nested inside a task's `raw`
    site record is caught as surely as one at the top level.
    """
    _walk(data, label, ())


def _reject_constant(name: str):
    raise NonFiniteNumberError(
        f"JSON contains the literal {name}, which is not valid JSON; "
        "a number must be finite")


def _walk(node, label: str, where: tuple) -> None:
    if isinstance(node, float) and not math.isfinite(node):
        location = "/".join(str(part) for part in where)
        raise NonFiniteNumberError(
            f"{label} has the non-finite number {node!r} at "
            f"'{location or '<root>'}'; a JSON number must be finite")
    if isinstance(node, dict):
        for key, value in node.items():
            _walk(value, label, where + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk(value, label, where + (index,))
