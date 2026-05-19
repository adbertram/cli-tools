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

from cli_tools_shared.output import handle_error

from ..images import download_images, get_cached_image_paths
from .._helpers import client_session, output_list, output_single

app = typer.Typer(help="Search and browse Facebook Marketplace", no_args_is_help=True)

DEFAULT_COLUMNS = ["title", "price", "location", "item_id"]
DEFAULT_HEADERS = ["Title", "Price", "Location", "Item ID"]


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
def marketplace_list(
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Search query (e.g., 'LEGO', 'couch')"),
    location: str = typer.Option("evansville", "--location", "-L", help="Location slug (e.g., 'evansville', 'chicago')"),
    min_price: Optional[int] = typer.Option(None, "--min-price", help="Minimum price"),
    max_price: Optional[int] = typer.Option(None, "--max-price", help="Maximum price"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of listings"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    include_detail: bool = typer.Option(False, "--include-detail", help="Navigate to each listing for description and full details"),
    download_images: bool = typer.Option(False, "--download-images", help="Download listing images to local cache (implies --include-detail)"),
):
    """List Facebook Marketplace listings.

    Without --query, browses "Today's picks" for the location.
    With --query, searches by keyword.

    Scrolls automatically to load enough listings to satisfy --limit.

    Examples:
        facebook marketplace list
        facebook marketplace list --query "LEGO"
        facebook marketplace list --query "couch" --min-price 50 --max-price 500
        facebook marketplace list --location chicago --table --limit 20
        facebook marketplace list --query "LEGO" --include-detail
        facebook marketplace list --query "LEGO" --download-images
        facebook marketplace list --query "LEGO" --limit 75
    """
    try:
        if download_images:
            include_detail = True

        with client_session() as client:
            listings = (
                client.search(query=query, location=location, min_price=min_price, max_price=max_price, limit=limit)
                if query
                else client.browse(location=location, limit=limit)
            )

            items = []
            if include_detail:
                for listing in listings:
                    detail = client.get_item(listing.item_id, include_images=download_images)
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
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def marketplace_get(
    item_id: str = typer.Argument(..., help="Marketplace listing item ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    download_images: bool = typer.Option(False, "--download-images", help="Download listing images to local cache"),
):
    """Get details for a specific Facebook Marketplace listing.

    Examples:
        facebook marketplace get 123456789
        facebook marketplace get 123456789 --table
        facebook marketplace get 123456789 --properties title,price,location
        facebook marketplace get 123456789 --download-images
    """
    try:
        with client_session() as client:
            item = client.get_item(item_id, include_images=download_images)
            image_urls = item.image_urls
            data = item.model_dump()

            if download_images:
                _resolve_images(data, image_urls)

            output_single(data, table=table, properties=properties)
    except Exception as e:
        raise typer.Exit(handle_error(e))
