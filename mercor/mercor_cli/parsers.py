"""Normalize Mercor listing records for command output.

Mercor's worker surface (https://work.mercor.com/explore) reads its role
listings from the internal JSON API `GET aws.api.mercor.com/work/listings-explore-page`,
which returns `{"listings": [...]}`. Every listing object is kept verbatim on
the public record (the output contract returns all data the API provides);
`normalize_listing` only adds the three stable, derived convenience fields
(`id`, `title`, `url`) that the documented command contract names. No value is
invented: the added fields are copies of or direct derivations from real API
fields.
"""

from typing import Any, Dict, List, Optional

EXPLORE_URL = "https://work.mercor.com/explore"


def listing_url(listing_id: str) -> str:
    """The worker-surface URL for one listing (the card href Mercor renders)."""
    return f"{EXPLORE_URL}?listingId={listing_id}"


def normalize_listing(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one raw listing dict from `/listings-explore-page`.

    Returns a copy of the raw record plus `id`, `title` and `url`, which are
    the record's public-key fields. Raises contract errors on records that are
    not dicts or lack a usable `listingId`.
    """
    if not isinstance(raw, dict):
        raise TypeError(f"listing record must be a dict, got {type(raw).__name__}")
    listing_id = raw.get("listingId")
    if not isinstance(listing_id, str) or not listing_id.strip():
        raise ValueError(f"listing record has no usable listingId: {raw!r:.200}")
    row = dict(raw)
    row["id"] = listing_id
    row["title"] = raw.get("title")
    row["url"] = listing_url(listing_id)
    return row


def normalize_listings(raw_items: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """Normalize the raw `listings` array into public listing records."""
    if raw_items is None:
        return []
    if not isinstance(raw_items, list):
        raise TypeError(
            f"listings payload must be a list, got {type(raw_items).__name__}"
        )
    return [normalize_listing(item) for item in raw_items if isinstance(item, dict)]
