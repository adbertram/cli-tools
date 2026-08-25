#!/usr/bin/env python3
"""GovDeals asset pages require a Runtime browser read.

GovDeals terms prohibit crawler access. The source worker reads each asset page
in the Runtime browser. The listing key preserves both direct-URL segments as
``govdeals|<asset_id>/<opaque_id>``. Do not reduce or reorder the pair.
"""
from __future__ import annotations

from .. import listing

NAMESPACE = "govdeals"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE


def listing_key(asset_id, opaque_id):
    """Build a key from the two ordered segments in a GovDeals asset URL."""
    parts = (asset_id, opaque_id)
    if any(not isinstance(part, str) or not part or part != part.strip()
           or "/" in part or "|" in part for part in parts):
        raise ValueError(
            "GovDeals asset_id and opaque_id must be non-empty URL segments")
    return "%s|%s/%s" % (NAMESPACE, asset_id, opaque_id)


NEEDS_PAGE_READ = {
    "available_fulfillment": (
        "the asset page delivery options. Read the listing's shipping and "
        "local-pickup statements in the Runtime browser; GovDeals terms "
        "prohibit crawler access"),
    "item_location": (
        "the asset page Item Location label in the Runtime browser. Record "
        "the complete state-qualified value"),
    "auction_end_date": (
        "the asset page close date and time beside the bid details in the "
        "Runtime browser. Record the published timestamp; do not infer one"),
    "seller_id": (
        "the asset page Seller label in the Runtime browser. Preserve the "
        "published seller identity; do not infer it from the URL"),
    "seller_name": (
        "the asset page Seller label in the Runtime browser. Record the "
        "published seller name"),
}


shipping_estimate = listing.never_quotes_shipping(
    "GovDeals does not publish a destination shipping quote on its public "
    "asset page. Record delivery availability separately; never record 0.0")
