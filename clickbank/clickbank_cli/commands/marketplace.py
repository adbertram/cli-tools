"""Marketplace commands for ClickBank CLI.

The ``marketplace`` subcommands search the public ClickBank affiliate
marketplace -- not your own ClickBank account.  Use these to discover
products you can promote.  Read access only; no write surface.

All three commands hit the private marketplace GraphQL endpoint via a
persistent Playwright session (see ``marketplace_client.py`` for the
rationale).  The session is the same one ``clickbank auth login`` boots, so
the first call after login is the slow one and everything subsequent piggy-
backs on the running browser daemon.

Credential gates: every marketplace command needs the
``browser_session`` credential.  REST API credentials are NOT required for
the marketplace surface and are deliberately omitted from the gate.
"""
from __future__ import annotations

from typing import List, Optional

import typer

from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import handle_error, print_json

from ..marketplace_client import VALID_SORT_FIELDS, get_marketplace_client
from . import emit_rows


COMMAND_CREDENTIALS = {
    "categories": ["browser_session"],
    "search": ["browser_session"],
    "product": ["browser_session"],
    # hoplink is offline; declare ``no_auth`` so the command-credential gate
    # treats it as exempt without triggering a session check.
    "hoplink": ["no_auth"],
}


app = typer.Typer(
    help="Search the public ClickBank affiliate marketplace",
    no_args_is_help=True,
)


# Per-subcommand default table column lists.  Adding a new view = adding an
# entry here, not threading more constants through each command body.
MARKETPLACE_VIEWS = {
    "categories": {
        "columns": ["name", "count"],
        "headers": ["Category", "Products"],
    },
    "search": {
        "columns": [
            "site", "title", "category", "subCategory", "gravity",
            "averageDollarsPerSale", "initialDollarsPerSale", "rebill", "hoplink",
        ],
        "headers": [
            "Vendor", "Title", "Category", "Subcategory", "Gravity",
            "Avg $/Sale", "Initial $/Sale", "Recurring", "Hoplink",
        ],
    },
    "product": {
        "columns": [
            "site", "title", "category", "subCategory", "gravity",
            "averageDollarsPerSale", "initialDollarsPerSale", "averageEPC",
            "conversionRate", "rebill", "rank", "hoplink",
        ],
        "headers": [
            "Vendor", "Title", "Category", "Subcategory", "Gravity",
            "Avg $/Sale", "Initial $/Sale", "Avg EPC", "Conv. Rate",
            "Recurring", "Rank", "Hoplink",
        ],
    },
}


@app.command("categories")
def marketplace_categories(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    flat: bool = typer.Option(
        False,
        "--flat",
        help="Top-level categories only, skipping subcategory expansion "
             "(one network call instead of ~25).",
    ),
    limit: int = typer.Option(
        100, "--limit", "-l", min=1,
        help="Maximum top-level categories to return.",
    ),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f",
        help="Filter: field:op:value (e.g. count:gt:50)",
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p",
        help="Comma-separated fields to include",
    ),
):
    """List the marketplace categories (and subcategories when --flat is off).

    The full category tree is cached on disk -- it changes rarely (every few
    weeks at most), so subsequent runs return instantly.  Use
    ``clickbank cache clear`` to force a refresh.
    """
    try:
        client = get_marketplace_client()
        rows = client.categories_flat_cached() if flat else client.categories_cached()
        if filter:
            rows = apply_filters(rows, filter)
        rows = rows[:limit]
        view = MARKETPLACE_VIEWS["categories"]
        emit_rows(
            rows, table=table, properties=properties,
            default_columns=view["columns"], default_headers=view["headers"],
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("search")
def marketplace_search(
    category: Optional[str] = typer.Option(
        None, "--category", help="Top-level category name (e.g. 'Health & Fitness')"
    ),
    subcategory: Optional[str] = typer.Option(
        None, "--subcategory",
        help="Subcategory name -- must match the category exactly",
    ),
    query: Optional[str] = typer.Option(
        None, "--query", "-q",
        help="Keyword search (matches product title and description)",
    ),
    min_gravity: Optional[float] = typer.Option(
        None, "--min-gravity", help="Minimum gravity score"
    ),
    max_gravity: Optional[float] = typer.Option(
        None, "--max-gravity", help="Maximum gravity score"
    ),
    min_avg_sale: Optional[float] = typer.Option(
        None, "--min-avg-sale", help="Minimum average dollars per sale",
    ),
    max_avg_sale: Optional[float] = typer.Option(
        None, "--max-avg-sale", help="Maximum average dollars per sale",
    ),
    recurring: bool = typer.Option(
        False, "--recurring",
        help="Filter to products with recurring billing only",
    ),
    sort: str = typer.Option(
        "gravity", "--sort",
        help="Sort field. ClickBank only allows: " + ", ".join(sorted(VALID_SORT_FIELDS)),
    ),
    ascending: bool = typer.Option(
        False, "--ascending",
        help="Sort ascending (default is descending for gravity/popularity, "
             "ascending for rank)",
    ),
    limit: int = typer.Option(
        25, "--limit", "-l", min=1, help="Maximum results to return"
    ),
    page: int = typer.Option(
        1, "--page", min=1, help="1-indexed page number for pagination"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Client-side filter: field:op:value",
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include",
    ),
):
    """Search the ClickBank affiliate marketplace.

    Examples:

        clickbank marketplace search --category 'Health & Fitness' --limit 10
        clickbank marketplace search --query keto --min-gravity 20 --table
        clickbank marketplace search --recurring --sort gravity --limit 25
    """
    try:
        client = get_marketplace_client()
        result = client.search(
            category=category, sub_category=subcategory, query=query,
            min_gravity=min_gravity, max_gravity=max_gravity,
            min_avg_sale=min_avg_sale, max_avg_sale=max_avg_sale,
            recurring=recurring, sort=sort, sort_descending=not ascending,
            limit=limit, page=page,
        )
        rows = [hit.model_dump(mode="json") for hit in result.hits]
        if filter:
            rows = apply_filters(rows, filter)
        view = MARKETPLACE_VIEWS["search"]
        emit_rows(
            rows, table=table, properties=properties,
            default_columns=view["columns"], default_headers=view["headers"],
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("product")
def marketplace_product(
    vendor: str = typer.Argument(..., help="Vendor nickname (uppercase)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include",
    ),
):
    """Show the full marketplace record for a single vendor.

    Combines the search-result snapshot with the historical metrics
    (returns / refunds / chargebacks / rank-and-gravity ranges) the
    marketplace UI shows on a product's detail page.

    Examples:

        clickbank marketplace product BRAINSONGX
        clickbank marketplace product YUSLEEP --table
    """
    try:
        client = get_marketplace_client()
        product = client.product(vendor)
        rows = [product.model_dump(mode="json")]
        view = MARKETPLACE_VIEWS["product"]
        emit_rows(
            rows, table=table, properties=properties,
            default_columns=view["columns"], default_headers=view["headers"],
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("hoplink")
def marketplace_hoplink(
    vendor: str = typer.Argument(..., help="Vendor nickname (uppercase)"),
):
    """Generate the affiliate tracking URL (hoplink) for a vendor.

    Offline -- does not call the marketplace.  Substitutes the affiliate
    nickname from ``CLICKBANK_AFFILIATE_NICKNAME`` if configured; otherwise
    emits a ``{affiliate}`` placeholder so the URL is clearly incomplete.
    """
    try:
        client = get_marketplace_client()
        url = client.hoplink(vendor)
        print_json({"vendor": vendor.upper(), "hoplink": url})
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
