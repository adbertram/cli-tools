"""Marketplace commands for Facebook CLI."""
COMMAND_CREDENTIALS = {
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ],
    "status": [
        "browser_session"
    ]
}

import typer
from typing import Optional, List

from cli_tools_shared.output import command

from ..images import download_images, get_cached_image_paths
from .._helpers import client_session, output_list, output_single

app = typer.Typer(help="Search and browse Facebook Marketplace", no_args_is_help=True)

DEFAULT_COLUMNS = ["title", "price", "location", "item_id"]
DEFAULT_HEADERS = ["Title", "Price", "Location", "Item ID"]

# Source-CLI Sort Standard mapping: canonical sort fields -> Facebook Marketplace
# `sortBy` URL values, keyed by direction. Natural direction (no --desc):
#   newest -> most recently listed first  (creation_time_descend)
#   price  -> low to high                 (price_ascend)
# Facebook Marketplace exposes NO oldest-first ordering (there is no
# `creation_time_ascend` in the sort dropdown), so `newest --desc` has no
# upstream `sortBy` value and is rejected rather than silently returning
# arbitrary order.
SORT_FIELD_TO_SORTBY = {
    "newest": {"natural": "creation_time_descend", "desc": None},
    "price": {"natural": "price_ascend", "desc": "price_descend"},
}

# Fulfillment filter -> Facebook Marketplace `deliveryMethod` URL value.
#
# Both tokens were verified live 2026-08-18 by reading Facebook's OWN filter
# panel back off the search page, not by assuming them:
#   deliveryMethod=shipping      -> "Delivery method: Shipping"    (Shipping
#                                   radio aria-checked="true")
#   deliveryMethod=local_pick_up -> "Delivery method: Local pickup" (Local
#                                   pickup radio aria-checked="true")
# An unrecognized token is NOT ignored by Facebook: deliveryMethod=local left
# every radio unchecked and the button reading "Delivery method:" with no
# value, i.e. a broken filter state. Only these verified tokens are ever sent.
#
# `all` sends NO parameter at all, which is Facebook's own default state ("All"
# radio aria-checked="true") and preserves this CLI's historical behavior
# exactly, so it is the default here.
DELIVERY_METHOD_TO_PARAM = {
    "all": None,
    "local": "local_pick_up",
    "shipping": "shipping",
}


def _resolve_delivery_method(delivery_method: str, query: Optional[str]) -> Optional[str]:
    """Resolve --delivery-method to a Facebook `deliveryMethod` URL value.

    Returns None for 'all' (send no parameter). Fail-fast: raises
    typer.BadParameter for an unknown value, and for any real filter requested
    without --query, because Facebook honors `deliveryMethod` only on the
    SEARCH surface. Measured live 2026-08-18 on the browse feed
    (`/marketplace/evansville/?deliveryMethod=...`, no query): the feed has no
    delivery-method filter control at all, and `shipping` and `local_pick_up`
    returned the SAME 18 rows as each other -- including Chicago IL, Tyler TX,
    Valdosta GA, and Woodstown NJ rows under `local_pick_up`. The parameter
    perturbs that feed without filtering it, so it is refused rather than sent.
    """
    key = delivery_method.lower()
    if key not in DELIVERY_METHOD_TO_PARAM:
        valid = ", ".join(DELIVERY_METHOD_TO_PARAM)
        raise typer.BadParameter(
            f"Invalid --delivery-method value '{delivery_method}'. Valid values: {valid}."
        )
    param = DELIVERY_METHOD_TO_PARAM[key]
    if param is not None and not query:
        raise typer.BadParameter(
            f"'--delivery-method {key}' requires --query. Facebook applies its "
            "deliveryMethod filter only to a Marketplace search; the browse feed "
            "(\"Today's picks\", no --query) has no delivery-method filter and returns "
            "the same unfiltered rows for every value."
        )
    return param


def _resolve_sort_by(sort: str, desc: bool) -> str:
    """Resolve --sort/--desc to a Facebook Marketplace `sortBy` URL value.

    Fail-fast: raises typer.BadParameter for unknown sort fields or for a
    direction the upstream source cannot honor. Never silently falls back to a
    default value.
    """
    key = sort.lower()
    field = SORT_FIELD_TO_SORTBY.get(key)
    if field is None:
        valid = ", ".join(SORT_FIELD_TO_SORTBY)
        raise typer.BadParameter(f"Invalid --sort value '{sort}'. Valid values: {valid}.")
    sort_by = field["desc"] if desc else field["natural"]
    if sort_by is None:
        raise typer.BadParameter(
            f"'--sort {key} --desc' is not supported: Facebook Marketplace has no "
            f"reverse (oldest-first) ordering for '{key}'. Use '--sort {key}' for "
            "newest-first."
        )
    return sort_by


def _resolve_images(item_data: dict, image_urls: Optional[List[str]]) -> dict:
    """Download or use cached images, then set local_images on the dict."""
    item_id = item_data.get("item_id")
    if not item_id:
        return item_data

    cached = get_cached_image_paths(item_id)
    if cached:
        item_data["local_images"] = cached
    elif image_urls:
        paths = download_images(item_id, image_urls)
        if paths:
            item_data["local_images"] = paths

    return item_data


@app.command("list")
@command
def marketplace_list(
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Search query (e.g., 'LEGO', 'couch')"),
    location: str = typer.Option(
        "evansville", "--location", "-L",
        help=(
            "Location slug (e.g., 'evansville', 'chicago', 'seattle', 'nyc'). A slug "
            "Facebook does not recognize is an error, not a fallback: Facebook silently "
            "serves the account's own home-city inventory for an unknown slug, so the "
            "command fails instead. Ignored by '--delivery-method shipping', which "
            "returns the same nationwide pool from any slug."
        ),
    ),
    min_price: Optional[int] = typer.Option(None, "--min-price", help="Minimum price"),
    max_price: Optional[int] = typer.Option(None, "--max-price", help="Maximum price"),
    sort: str = typer.Option(
        "newest", "--sort", "-s",
        help="Sort field: 'newest' (default, most recently listed first) or 'price' (low to high).",
    ),
    desc: bool = typer.Option(
        False, "--desc", "-d",
        help="Reverse the sort field's natural direction (e.g. 'price --desc' = high to low). Not supported for 'newest' (Facebook has no oldest-first order).",
    ),
    delivery_method: str = typer.Option(
        "all", "--delivery-method", "-D",
        help=(
            "Fulfillment filter, requires --query: 'all' (default, Facebook's own "
            "unfiltered default), 'shipping' (NATIONWIDE -- only listings that ship, "
            "from sellers anywhere in the country), or 'local' (local pickup only). "
            "With 'shipping' the --location slug does not change the results; Facebook "
            "serves one nationwide shipping pool from any city slug."
        ),
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of listings"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    include_detail: bool = typer.Option(False, "--include-detail", help="Navigate to each listing for description and full details"),
    download_images: bool = typer.Option(False, "--download-images", help="Also save the listing images to the local cache (implies --include-detail). Image URLs are returned either way."),
):
    """List Facebook Marketplace listings.

    Without --query, browses "Today's picks" for the location.
    With --query, searches by keyword.

    Scrolls automatically to load enough listings to satisfy --limit.

    Results are ordered by --sort (default 'newest' = most recently listed
    first), mapped to Facebook's `sortBy` URL parameter. Use --desc to reverse a
    field's natural direction ('price --desc' = high to low). Facebook
    Marketplace has no oldest-first ordering, so 'newest --desc' is rejected.

    --delivery-method shipping searches NATIONWIDE: it returns only listings
    that ship, from sellers anywhere in the country, and the --location slug
    has no effect on that pool.

    An unrecognized --location slug fails instead of returning results.
    Facebook silently substitutes the account's own home city for a slug it
    does not know, so a clean-looking result set would describe the wrong city.

    Examples:
        facebook marketplace list
        facebook marketplace list --query "LEGO"
        facebook marketplace list --query "LEGO" --sort price
        facebook marketplace list --query "LEGO" --sort price --desc
        facebook marketplace list --query "couch" --min-price 50 --max-price 500
        facebook marketplace list --location chicago --table --limit 20
        facebook marketplace list --query "LEGO" --delivery-method shipping
        facebook marketplace list --query "LEGO" --delivery-method local
        facebook marketplace list --query "LEGO" --include-detail
        facebook marketplace list --query "LEGO" --download-images
        facebook marketplace list --query "LEGO" --limit 75
    """
    sort_by = _resolve_sort_by(sort, desc)
    delivery_method_param = _resolve_delivery_method(delivery_method, query)
    if download_images:
        include_detail = True

    with client_session() as client:
        listings = (
            client.search(query=query, location=location, min_price=min_price, max_price=max_price, limit=limit, sort_by=sort_by, delivery_method=delivery_method_param)
            if query
            else client.browse(location=location, limit=limit, sort_by=sort_by)
        )

        items = []
        if include_detail:
            for listing in listings:
                detail = client.get_item(listing.item_id)
                image_urls = detail.image_urls
                data = detail.model_dump()
                if download_images:
                    _resolve_images(data, image_urls)
                items.append(data)
        else:
            items = [listing.model_dump() for listing in listings]

        output_list(
            items, table=table, filter=filter, properties=properties,
            limit=limit, default_columns=DEFAULT_COLUMNS,
            default_headers=DEFAULT_HEADERS, noun="listing",
        )


@app.command("get")
@command
def marketplace_get(
    item_id: str = typer.Argument(..., help="Marketplace listing item ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    download_images: bool = typer.Option(False, "--download-images", help="Also save the listing images to the local cache. Image URLs are returned either way."),
):
    """Get details for a specific Facebook Marketplace listing.

    Examples:
        facebook marketplace get 123456789
        facebook marketplace get 123456789 --table
        facebook marketplace get 123456789 --properties title,price,location
        facebook marketplace get 123456789 --download-images
    """
    with client_session() as client:
        item = client.get_item(item_id)
        image_urls = item.image_urls
        data = item.model_dump()

        if download_images:
            _resolve_images(data, image_urls)

        output_single(data, table=table, properties=properties)


@app.command("status")
@command
def marketplace_status(
    item_id: str = typer.Argument(..., help="Marketplace listing item ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get current availability without requiring full listing details.

    This command reads Facebook's structured sold, pending, and live values.
    It does not require delivery types, prices, descriptions, or images.

    Examples:
        facebook marketplace status 123456789
        facebook marketplace status 123456789 --table
        facebook marketplace status 123456789 --properties item_id,availability
    """
    with client_session() as client:
        data = client.get_item_status(item_id)
        output_single(data, table=table, properties=properties)
