"""Per-site adapters: one raw `tasks list` record -> one `MappedTask`.

`adapter_for(site)` is the only lookup. A site whose envelope is `ok` but has
no adapter is a `ClientError` at merge time; nothing is mapped by guesswork.

Every adapter returns `mapped.MappedTask`: the task-contract record, plus
whether the site published a price the adapter could not read. See
`mapped.py` for why that second fact cannot live inside the task.
"""

from __future__ import annotations

from cli_tools_shared.exceptions import ClientError

from . import (
    atlas_capture,
    crowdgen,
    humanrail,
    mercor,
    microworkers,
    oneforma,
    outlier,
    trainee_digital,
)

ADAPTERS = {
    "atlas-capture": atlas_capture.to_task,
    "crowdgen": crowdgen.to_task,
    "humanrail": humanrail.to_task,
    "mercor": mercor.to_task,
    "microworkers": microworkers.to_task,
    "oneforma": oneforma.to_task,
    "outlier": outlier.to_task,
    "trainee-digital": trainee_digital.to_task,
}

# Sites whose task DETAIL records carry a description the listing does not.
# `microworker enrich` fetches each such site's detail pages after the merge
# and writes the text back through `db.update_task_description`. A site absent
# from this map is not enrichable -- its descriptions either arrive with the
# listing (mapped in `to_task`) or the site publishes none.
DETAIL_DESCRIPTIONS = {
    "microworkers": microworkers.detail_description,
}


def adapter_for(site: str):
    if site not in ADAPTERS:
        raise ClientError(
            f"no adapter for site '{site}'; adapters exist for: "
            f"{', '.join(ADAPTERS)}")
    return ADAPTERS[site]


def detail_description_for(site: str):
    """The detail->description extractor for a site, or None (not enrichable)."""
    return DETAIL_DESCRIPTIONS.get(site)
