"""Adapter for `atlas-capture tasks list` records.

Raw records: Atlas Capture currently exposes NO task records to Adam's account
(verified live 2026-09-03 — see the atlas-capture CLI parsers module: the
/tasks route redirects to /dashboard; the account is not certified and the
platform is under a "Temporary Labeling Pause"). The only real payload is an
empty task list, so no real raw task record has ever been captured.

Consequence: there is no field mapping to write, and writing one from
guesswork would violate MicroWorker's evidence-only rule. ``to_task``
therefore refuses every record it is handed until the first real Atlas task
record is captured and its schema is documented here. An ``ok`` envelope with
zero tasks never calls ``to_task``, so registering this adapter in
``ADAPTERS`` is safe today; the day tasks appear, ``merge`` fails loudly
instead of storing invented fields — which is the cue to fill in the mapping
below from that real record.
"""

from __future__ import annotations

from cli_tools_shared.exceptions import ClientError

SITE = "atlas-capture"


def to_task(raw: dict):
    """Map one raw `atlas-capture tasks list` record to the task contract.

    Always raises today: no real Atlas task record exists to define the
    mapping against, and a contract is never guessed. Once the first record is
    captured (the day /tasks stops redirecting for this account), implement
    the mapping here following the other adapters (see oneforma.py), keeping
    the record's real keys as RAW_KEYS and returning a
    ``mapped.MappedTask`` (``task_id()``/``is_unparsed_payment()`` semantics
    unchanged).
    """
    raise ClientError(
        f"{SITE}: no real task record has ever been captured (the account's "
        "/tasks route redirects to /dashboard), so there is no schema to map "
        f"a record with. Refusing to guess a mapping for: {raw!r}"
    )
