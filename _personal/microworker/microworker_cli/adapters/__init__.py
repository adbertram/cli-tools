"""Per-site adapters: one raw `tasks list` record -> one `MappedTask`.

`adapter_for(site)` is the only lookup. A site whose envelope is `ok` but has
no adapter is a `ClientError` at merge time; nothing is mapped by guesswork.

Every adapter returns `mapped.MappedTask`: the task-contract record, plus
whether the site published a price the adapter could not read. See
`mapped.py` for why that second fact cannot live inside the task.
"""

from __future__ import annotations

from cli_tools_shared.exceptions import ClientError

from . import humanrail, microworkers, oneforma, outlier, taskerdata

ADAPTERS = {
    "microworkers": microworkers.to_task,
    "taskerdata": taskerdata.to_task,
    "humanrail": humanrail.to_task,
    "oneforma": oneforma.to_task,
    "outlier": outlier.to_task,
}


def adapter_for(site: str):
    if site not in ADAPTERS:
        raise ClientError(
            f"no adapter for site '{site}'; adapters exist for: "
            f"{', '.join(ADAPTERS)}")
    return ADAPTERS[site]
