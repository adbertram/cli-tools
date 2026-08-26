#!/usr/bin/env python3
"""BrickLink used-sold pricing for ONE verified minifigure identity.

The identifier's verified `fig_no` prices through the SAME shared
`catalog price` cache as sets (`set_sales.cached_bricklink_json`, 7-day TTL on
the rolling six-month sold guide). Nothing here duplicates subprocess or flock
machinery.

## The single-catalog-lookup rule

The identifier agent's `catalog minifig <fig_no>` retrieval is THE catalog
lookup for an identity. Its payload travels inside the identification artifact
(the agent needs the name/image for its mandatory visual comparison, and the
stored entry keeps that evidence). This module VALIDATES that payload -- the
priced `fig_no` must match the stored catalog record -- and invokes ONLY the
price guide. Pricing never performs a second catalog fetch: two lookups per
identity doubles quota burn and lets the two answers drift apart.

Fig numbers often carry letter suffixes (`sw0001a`). They are item IDs, not
set numbers: no normalization is ever applied, because a bare `sw0001` 404s
where `sw0001a` resolves.

Zero sales is a PRESENT answer (`lookup_status="zero_sales"`,
`unit_value=None`, `null_value_reason` set), not `$0` and not an exception --
an obscure figure stays visible with a crop and a reason, never an estimate.
"""
from __future__ import annotations

from typing import Any

from legoscout_cli.ledger import minifig_analysis
from legoscout_cli.pricing import set_sales

LookupFailed = set_sales.LookupFailed
LookupNotFound = set_sales.LookupNotFound


def price_guide_args(fig_no: str) -> list[str]:
    """The exact BrickLink invocation for one figure's used sold guide."""
    return [
        "catalog", "price", "MINIFIG", fig_no,
        "--condition", "U", "--sold",
    ]


def summarize_fig(
    fig_no: str,
    catalog: dict[str, Any] | None,
    runner: set_sales.Runner | None = None,
    cache_path: str | None = None,
    now=None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Used-sold evidence + unit value for one verified fig_no.

    `catalog` is the identifier artifact's stored BrickLink record; it is
    validated here (fig_no must match) and carried onto the result. `runner`
    replaces the whole lookup for tests; production callers pass cache/now/
    refresh through to the shared `cached_bricklink_json`.

    Raises `LookupNotFound` (stable absence -- cached by the shared layer) or
    `LookupFailed` (transient -- never cached). The CALLER owns failure
    isolation: one figure's raised condition becomes that entry's recorded
    error while siblings keep pricing.
    """
    if not isinstance(fig_no, str) or not fig_no.strip():
        raise LookupFailed(
            "fig_no must be a non-empty string like 'sw0001a', got %r"
            % (fig_no,))
    fig_no = fig_no.strip()
    if not isinstance(catalog, dict):
        raise LookupFailed(
            "minifig pricing requires the identifier artifact's stored "
            "catalog payload for %r; got %r -- the agent's `catalog minifig` "
            "retrieval is THE catalog lookup and pricing performs no second "
            "one" % (fig_no, catalog))
    stored_no = catalog.get("no")
    if not isinstance(stored_no, str) or stored_no.strip() != fig_no:
        raise LookupFailed(
            "fig_no=%r does not match the stored catalog number %r -- price "
            "the identity the agent verified, not a neighboring one"
            % (fig_no, stored_no))

    kwargs: dict[str, Any] = {}
    if runner is not None:
        kwargs["runner"] = runner
    if cache_path is not None:
        kwargs["cache_path"] = cache_path
    if now is not None:
        kwargs["now"] = now
    if refresh:
        kwargs["refresh"] = True

    raw = set_sales.cached_bricklink_json(price_guide_args(fig_no), **kwargs)
    used = set_sales.normalize_price_summary("U", raw)

    unit_value = used.get("six_month_avg_sold_price")
    result: dict[str, Any] = {
        "fig_no": fig_no,
        "catalog": minifig_analysis.normalize_catalog(catalog),
        "used": used,
        "lookup_status": "found",
        "unit_value": unit_value,
        "null_value_reason": None,
    }
    if unit_value is None:
        # A present answer with nothing in it: the guide ran and reported no
        # six-month sold data. Not $0, not an error, never an estimate.
        result["lookup_status"] = "zero_sales"
        result["null_value_reason"] = "zero_sales"
    return result
