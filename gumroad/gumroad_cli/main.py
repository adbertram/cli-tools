"""Gumroad service commands with JSON stdout and explicit write intent."""
import hashlib
from pathlib import Path
from typing import List, Optional
import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from cli_tools_shared.filters import apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import command, print_json, print_table
from cli_tools_shared.exceptions import ClientError
from . import __version__
from .client import GumroadClient, file_info, identifier, metadata, read_receipt, state_hash, draft_preview, validate_update
from .config import get_config
from .commands import products, files

app = create_app(name="gumroad", help="Manage Gumroad products and upload existing files", version=__version__)
products.app = typer.Typer(help="Inspect, create draft, update and publish Gumroad products", no_args_is_help=True)
files.app = typer.Typer(help="Upload existing local files to Gumroad staging", no_args_is_help=True)


def render(data, table, columns=None):
    if table:
        rows = data if isinstance(data, list) else [{"field": key, "value": str(value)} for key, value in data.items()]
        columns = columns or (["id", "name", "published", "price", "currency"] if isinstance(data, list) else ["field", "value"])
        print_table(rows, columns, [x.title() for x in columns])
    else:
        print_json(data)


def authorize(yes, dry_run):
    if not yes and not dry_run:
        raise ClientError("Refusing to write without --yes or --dry-run.")


def description_text(path):
    if path is None:
        return None
    try:
        return path.read_text()
    except (OSError, UnicodeError) as exc:
        raise ClientError("Description file must contain readable UTF-8 HTML.") from exc


@products.app.command("list")
@command
def list_products(
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum matching products"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Client-side field:op:value filter"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output properties"),
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Gumroad auth profile"),
):
    """List complete API product records; filter before applying the result limit."""
    if filter:
        validate_filters(filter)
    rows = GumroadClient(get_config(profile)).list_products()
    if filter:
        rows = apply_filters(rows, filter)
    rows = rows[:limit]
    if properties:
        rows = apply_properties_filter(rows, properties)
    render(rows, table, [value.strip() for value in properties.split(",") if value.strip()] if properties else None)


@products.app.command("get")
@command
def get_product(
    product_id: str = typer.Argument(..., help="Exact Gumroad product ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Gumroad auth profile"),
):
    """Return full product API response plus stable editable-state hash."""
    identifier(product_id)
    result = GumroadClient(get_config(profile)).get_product(product_id)
    render({**result, "state_hash": state_hash(result["product"])}, table)


@files.app.command("upload")
@command
def upload_file(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, help="Existing nonempty local file, at most20GiB"),
    yes: bool = typer.Option(False, "--yes", help="Authorize staging upload (does not attach to a product)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Hash/inspect local file; no API calls"),
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Gumroad auth profile"),
):
    """Upload through presign/parts/complete; return a private attachment receipt."""
    authorize(yes, dry_run)
    path, size = file_info(path)
    if dry_run:
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        result = {"dry_run": True, "filename": path.name, "size": size, "sha256": digest, "product_changed": False}
    else:
        result = GumroadClient(get_config(profile)).upload_file(path)
    render(result, table)


@products.app.command("create-draft")
@command
def create_draft(
    name: str = typer.Option(..., "--name", help="Explicit product name"),
    price_cents: int = typer.Option(..., "--price-cents", min=0, help="Explicit price in smallest currency units"),
    currency: str = typer.Option(..., "--currency", help="Explicit lowercase ISO currency"),
    description_file: Optional[Path] = typer.Option(None, "--description-file", exists=True, dir_okay=False, help="Approved UTF-8 HTML description"),
    upload_receipt: Optional[Path] = typer.Option(None, "--upload-receipt", exists=True, dir_okay=False, help="Exact files upload JSON receipt to attach"),
    yes: bool = typer.Option(False, "--yes", help="Authorize unpublished product creation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show request without API calls"),
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Gumroad auth profile"),
):
    """Create an explicitly priced product, always unpublished; optionally attach a staged file."""
    authorize(yes, dry_run)
    fields = metadata(name, price_cents, currency, description_text(description_file))
    receipt = read_receipt(upload_receipt) if upload_receipt else None
    if dry_run:
        result = draft_preview(fields, receipt)
    else:
        result = GumroadClient(get_config(profile)).create_draft(fields, receipt)
    render(result, table)


@products.app.command("update")
@command
def update_product(
    product_id: str = typer.Argument(..., help="Exact existing Gumroad product ID"),
    name: Optional[str] = typer.Option(None, "--name", help="New product name; omitted preserves current"),
    price_cents: Optional[int] = typer.Option(None, "--price-cents", min=0, help="New price in smallest currency units"),
    currency: Optional[str] = typer.Option(None, "--currency", help="New lowercase ISO currency"),
    description_file: Optional[Path] = typer.Option(None, "--description-file", exists=True, dir_okay=False, help="New UTF-8 HTML description; omitted preserves current"),
    upload_receipt: Optional[Path] = typer.Option(None, "--upload-receipt", exists=True, dir_okay=False, help="Exact staged files upload receipt"),
    replace_file_id: Optional[str] = typer.Option(None, "--replace-file-id", help="Exact existing attachment ID to replace"),
    append_file: bool = typer.Option(False, "--append-file", help="Explicitly add staged file while retaining all existing files"),
    expected_state: Optional[str] = typer.Option(None, "--expected-state", help="Optional state_hash from a prior get/dry-run"),
    confirm_live_update: bool = typer.Option(False, "--confirm-live-update", help="Authorize immediate buyer-facing changes to a published product"),
    yes: bool = typer.Option(False, "--yes", help="Authorize this product update"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Read current product and show exact request; no writes"),
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Gumroad auth profile"),
):
    """Update selected metadata and/or one attachment; retain all other files by exact ID."""
    authorize(yes, dry_run)
    identifier(product_id)
    if replace_file_id:
        identifier(replace_file_id)
    fields = metadata(name, price_cents, currency, description_text(description_file))
    receipt = read_receipt(upload_receipt) if upload_receipt else None
    validate_update(fields, receipt, replace_file_id, append_file)
    result = GumroadClient(get_config(profile)).update_product(product_id, fields, receipt,
        replace_file_id=replace_file_id, append_file=append_file, expected_state=expected_state,
        confirm_live=confirm_live_update, dry_run=dry_run)
    render(result, table)


@products.app.command("publish")
@command
def publish_product(
    product_id: str = typer.Argument(..., help="Exact existing Gumroad product ID"),
    confirm_product_id: Optional[str] = typer.Option(None, "--confirm-product-id", help="Repeat exact product ID to authorize publication"),
    expected_state: Optional[str] = typer.Option(None, "--expected-state", help="Optional state_hash from prior get/dry-run"),
    yes: bool = typer.Option(False, "--yes", help="Authorize publication"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Inspect current product and show publication request; no writes"),
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Gumroad auth profile"),
):
    """Publish the exact selected existing product separately from creation/upload."""
    authorize(yes, dry_run)
    identifier(product_id)
    result = GumroadClient(get_config(profile)).publish_product(product_id,
        confirmation=confirm_product_id, expected_state=expected_state, dry_run=dry_run)
    render(result, table)

register_commands(app, get_config, products, name="products", help=products.app.info.help)
register_commands(app, get_config, files, name="files", help=files.app.info.help)
app.add_typer(create_auth_app(get_config, tool_name="gumroad"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")

def main():
    run_app(app)

if __name__ == "__main__":
    main()
