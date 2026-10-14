"""Main entry point for Frame.io CLI."""

from pathlib import Path
from typing import List, Optional

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_success, print_table

from . import __version__
from .client import MAX_ASSETS, PublicShare

ASSET_COLUMNS = ["id", "name", "type", "video", "size", "mime_type", "status"]

app = create_app(name="frameio", help="Read public Frame.io shares and download their original video files", version=__version__)
shares_app = typer.Typer(help="Inspect public Frame.io shares", no_args_is_help=True)
assets_app = typer.Typer(help="List and download assets in a public Frame.io share", no_args_is_help=True)

SHARE_URL = typer.Argument(..., help="Public share URL (https://next.frame.io/share/<uuid> or an f.io short link)")
ASSET_ID = typer.Argument(..., help="Asset ID (UUID)")
TABLE = typer.Option(False, "--table", "-t", help="Display as table")
PROPERTIES = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include")


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _render(rows: List[dict], table: bool, properties: Optional[str], columns: List[str], empty: str) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    columns = fields or columns
    print_table(rows, columns, [column.replace("_", " ").title() for column in columns])


def _render_one(row: dict, table: bool, properties: Optional[str]) -> None:
    fields = _property_fields(properties)
    if fields:
        _render([row], table, properties, [], "No result.")
    elif table:
        print_table(
            [{"field": key, "value": str(value)} for key, value in row.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
    else:
        print_json(row)


@shares_app.command("get")
@command
def get_share(
    share_url: str = SHARE_URL,
    table: bool = TABLE,
    properties: Optional[str] = PROPERTIES,
):
    """Get a share's id, url, enabled, downloadingEnabled and expiration."""
    _render_one(PublicShare(share_url).share(), table, properties)


@assets_app.command("list")
@command
def list_assets(
    share_url: str = SHARE_URL,
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=MAX_ASSETS, help="Maximum number of assets"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = TABLE,
    properties: Optional[str] = PROPERTIES,
):
    """List the assets in a share's file collection."""
    if filter:
        try:
            validate_filters(filter)
        except FilterValidationError as exc:
            print_error(str(exc))
            raise typer.Exit(1)
    rows = PublicShare(share_url).list_assets(limit)
    if filter:
        rows = apply_filters(rows, filter)
    _render(rows, table, properties, ASSET_COLUMNS, "No assets found.")


@assets_app.command("get")
@command
def get_asset(
    share_url: str = SHARE_URL,
    asset_id: str = ASSET_ID,
    table: bool = TABLE,
    properties: Optional[str] = PROPERTIES,
):
    """Get one asset in a share."""
    _render_one(PublicShare(share_url).get_asset(asset_id), table, properties)


@assets_app.command("download")
@command
def download_asset(
    share_url: str = SHARE_URL,
    asset_id: str = ASSET_ID,
    output: Path = typer.Option(..., "--output", "-o", help="File path to write the original video to"),
):
    """Download a video asset's original file to exactly --output."""
    path = output.expanduser()
    asset = PublicShare(share_url).download(asset_id, path)
    print_success(f"Downloaded {asset['name']} ({asset['size']} bytes) to {path}")
    print_json({"id": asset["id"], "name": asset["name"], "size": asset["size"], "path": str(path)})


app.add_typer(shares_app, name="shares")
app.add_typer(assets_app, name="assets")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
