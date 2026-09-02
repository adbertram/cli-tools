"""Per-site adapters: one raw `tasks list` record -> one task-contract record.

`adapter_for(site)` is the only lookup. A site whose envelope is `ok` but has
no adapter is a `ClientError` at merge time; nothing is mapped by guesswork.
"""

from __future__ import annotations

from cli_tools_shared.exceptions import ClientError

from . import microworkers, taskerdata, toloka

ADAPTERS = {
    "microworkers": microworkers.to_task,
    "taskerdata": taskerdata.to_task,
    "toloka": toloka.to_task,
}


def adapter_for(site: str):
    if site not in ADAPTERS:
        raise ClientError(
            f"no adapter for site '{site}'; adapters exist for: "
            f"{', '.join(ADAPTERS)}")
    return ADAPTERS[site]
