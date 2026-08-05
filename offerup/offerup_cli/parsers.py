"""Normalize OfferUp GraphQL records into the documented command output.

OfferUp's own field set is returned verbatim — nothing is dropped, so the CLI
stays useful as the schema grows. The only additions are the convenience keys
the command contract documents:

  * ``id``  — mirrors ``listingId`` so every record has a stable primary key
              under the same name across search, list, and get.
  * ``url`` — the canonical offerup.com item URL, which the API never returns.

Both were validated against live responses: search/list records carry
``listingId``; detail records carry both ``id`` and ``listingId``, where ``id``
is the same UUID.
"""

from typing import Callable, Dict, List


def _with_identity(record: Dict, item_url: Callable[[str], str]) -> Dict:
    """Return ``record`` plus the ``id``/``url`` convenience keys."""
    listing_id = record.get("listingId")
    if not listing_id:
        raise ValueError(f"OfferUp record is missing listingId: {sorted(record)}")
    normalized = dict(record)
    normalized["id"] = listing_id
    normalized["url"] = item_url(listing_id)
    return normalized


def normalize_listings(
    listings: List[Dict], item_url: Callable[[str], str]
) -> List[Dict]:
    """Normalize feed listing records for `listings search` / `listings list`."""
    return [_with_identity(listing, item_url) for listing in listings]


def normalize_listing_detail(
    listing: Dict, item_url: Callable[[str], str]
) -> Dict:
    """Normalize one detail record for `listings get`."""
    return _with_identity(listing, item_url)
