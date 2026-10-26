"""Typer contract for standalone Gumroad book builds and releases."""
import json
from pathlib import Path
from typing import List, Optional
import typer
from jsonschema import Draft202012Validator
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import command, print_json, print_table
from . import __version__
from .client import run_operation, install_engine
from .config import get_config

CONTRACTS = json.loads((Path(__file__).parent / "contracts.json").read_text())
app = create_app(name="gumroad", help="Build and release current Notion books through Gumroad APIs", version=__version__)


def render(data, table):
    if table:
        rows = data if isinstance(data, list) else [{"field": k, "value": json.dumps(v)} for k, v in data.items()]
        columns = list(rows[0]) if rows else ["id", "name"]
        print_table(rows, columns, [x.title() for x in columns])
    else:
        print_json(data)


def validate_input(operation, payload):
    errors = sorted(Draft202012Validator(CONTRACTS[operation]["schema"]).iter_errors(payload), key=lambda x: str(x.path))
    if errors:
        raise typer.BadParameter("Invalid operation input: " + "; ".join(e.message for e in errors))
    return payload


def invoke(operation, payload, profile, table=False):
    validate_input(operation, payload)
    render(run_operation(operation, payload, profile), table)


products = typer.Typer(help="Read safe product metadata and attachment IDs", no_args_is_help=True)

@products.command("list")
@command
def list_products(
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum matching products"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Client-side field:op:value filter"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output properties"),
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Gumroad authentication profile"),
):
    """List account product destinations; never expose paid-file download URLs."""
    if filter:
        validate_filters(filter)
    rows = run_operation("listGumroadProducts", {}, profile)["products"]
    if filter:
        rows = apply_filters(rows, filter)
    rows = rows[:limit]
    if properties:
        rows = apply_properties_filter(rows, properties)
    render(rows, table)

@products.command("get")
@command
def get_product(
    product_id: str = typer.Argument(..., help="Exact Gumroad product ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Gumroad authentication profile"),
):
    """Inspect product metadata, attachment IDs and target-state hash."""
    invoke("inspectGumroadProduct", {"productId": product_id}, profile, table)

app.add_typer(products, name="products")
books = typer.Typer(help="Read current Notion manuscripts and build derived artifacts", no_args_is_help=True)

@books.command("inspect")
@command
def inspect_book(
    book_page_url: str = typer.Argument(..., help="Exact Notion book root URL or ID"),
    mode: str = typer.Option(..., "--mode", help="publication or proof; explicit"),
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
):
    """Read-only source, schema, order and publication-readiness inspection."""
    invoke("inspectGumroadBuild", {"bookPageUrl": book_page_url, "mode": mode}, None, table)


def build_command(operation):
    @command
    def build(
        book_page_url: str = typer.Argument(..., help="Exact Notion book root URL or ID"),
        mode: str = typer.Option(..., "--mode", help="publication or proof; explicit"),
        author: Optional[str] = typer.Option(None, "--author", help="Known author; omitted means null"),
        image_mode: str = typer.Option(..., "--image-mode", help="native or explicitly approved ebook200"),
        table: bool = typer.Option(False, "--table", "-t", help="Table output"),
    ):
        """Build current Notion Drafts; attach exact artifact and source manifest to the root."""
        invoke(operation, {"bookPageUrl": book_page_url, "mode": mode, "author": author, "imageMode": image_mode}, None, table)
    return build

books.command("build-pdf")(build_command("buildGumroadBook"))
books.command("build-epub")(build_command("buildGumroadEpub"))
app.add_typer(books, name="books")


def file_command(operation):
    @command
    def execute(
        input_file: Path = typer.Option(..., "--input-file", exists=True, dir_okay=False, help="JSON object matching the documented operation schema"),
        table: bool = typer.Option(False, "--table", "-t", help="Table output"),
        profile: Optional[str] = typer.Option(None, "--profile", help="Gumroad authentication profile"),
    ):
        """Execute the exact input contract; approval fields are never inferred."""
        try:
            payload = json.loads(input_file.read_text())
        except (ValueError, OSError) as exc:
            raise typer.BadParameter("Input must be a readable JSON object") from exc
        invoke(operation, payload, profile, table)
    execute.__doc__ = f"{operation}: preserve exact source/hash/approval gates. See gumroad schema get {operation}."
    return execute

for group in ["uploads", "smoke-drafts", "releases", "formats"]:
    subapp = typer.Typer(help=f"{group.title()} operations with exact JSON inputs", no_args_is_help=True)
    for operation, spec in CONTRACTS.items():
        if spec["group"] == group:
            subapp.command(spec["command"])(file_command(operation))
    app.add_typer(subapp, name=group)

schema = typer.Typer(help="Inspect strict operation JSON schemas", no_args_is_help=True)
@schema.command("list")
@command
def list_schemas(
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum matching operation schemas"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Client-side field:op:value filter"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
):
    """Discover all capability keys and command mappings without credentials."""
    if filter:
        validate_filters(filter)
    rows = [{"id": operation, "group": spec["group"], "command": spec["command"]} for operation, spec in CONTRACTS.items()]
    if filter:
        rows = apply_filters(rows, filter)
    rows = rows[:limit]
    if properties:
        rows = apply_properties_filter(rows, properties)
    render(rows, table)

@schema.command("get")
@command
def get_schema(
    operation: str = typer.Argument(..., help="Original Worker capability key"),
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
):
    """Return an operation's complete input schema and CLI mapping without authentication."""
    if operation not in CONTRACTS:
        raise typer.BadParameter("Unknown operation. Choose: " + ", ".join(CONTRACTS))
    render(CONTRACTS[operation], table)
app.add_typer(schema, name="schema")

engine = typer.Typer(help="Install the local renderer and API engine", no_args_is_help=True)
@engine.command("install")
@command
def engine_install():
    """Install locked npm dependencies and compile the standalone engine."""
    print_json(install_engine())
app.add_typer(engine, name="engine")
app.add_typer(create_auth_app(get_config, tool_name="gumroad"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")

def main():
    run_app(app)

if __name__ == "__main__":
    main()
