"""Adapter for `taskerdata tasks list` records.

Not implemented: no `ok` taskerdata envelope with tasks has been observed, so
there is no verified raw record shape to map. `merge` never reaches this while
taskerdata envelopes carry zero tasks.
"""

from __future__ import annotations

SITE = "taskerdata"


def to_task(raw: dict) -> dict:
    raise NotImplementedError(
        f"{SITE} adapter is not implemented; no verified raw record shape yet "
        f"(record keys: {', '.join(sorted(raw))})")
