"""Marketplace commands for Facebook CLI."""
COMMAND_CREDENTIALS = {
    "get": [
        "browser_session"
    ],
    "list": [
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
    location: str = typer.Option("evansville", "--location", "-L", help="Location slug (e.g., 'evansville', 'chicago')"),
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

    Examples:
        facebook marketplace list
        facebook marketplace list --query "LEGO"
        facebook marketplace list --query "LEGO" --sort price
        facebook marketplace list --query "LEGO" --sort price --desc
        facebook marketplace list --query "couch" --min-price 50 --max-price 500
        facebook marketplace list --location chicago --table --limit 20
        facebook marketplace list --query "LEGO" --include-detail
        facebook marketplace list --query "LEGO" --download-images
        facebook marketplace list --query "LEGO" --limit 75
    """
    sort_by = _resolve_sort_by(sort, desc)
    if download_images:
        include_detail = True

    with client_session() as client:
        listings = (
            client.search(query=query, location=location, min_price=min_price, max_price=max_price, limit=limit, sort_by=sort_by)
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
