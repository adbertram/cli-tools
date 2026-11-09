from pathlib import Path
from types import SimpleNamespace

import typer
from cli_tools_shared import create_app, create_auth_app, create_cache_app, run_app
from cli_tools_shared.command_registry import register_commands
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_limit,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table

from . import __version__
from .client import APPLICATION_FIELD_LABELS, canonical_icon_color, get_client
from .commands.icons import COMMAND_CREDENTIALS as ICON_CREDENTIALS
from .commands.modules import COMMAND_CREDENTIALS as MODULE_CREDENTIALS
from .commands.slide_deck import COMMAND_CREDENTIALS as SLIDE_DECK_CREDENTIALS
from .config import AUTH_METHOD_OPPORTUNITIES, get_config

COLUMNS = ["id", "title", "opportunity_type", "category", "posted_date", "is_new"]
ICON_COLUMNS = ["id", "name", "category", "color", "tags", "file_type"]
ICON_FILTER_FIELDS = {"name", "category", "color", "tag", "tags"}
OPPORTUNITY_CREDENTIALS = {
    "list": [AUTH_METHOD_OPPORTUNITIES, "browser_session"],
    "get": [AUTH_METHOD_OPPORTUNITIES, "browser_session"],
    "apply": [AUTH_METHOD_OPPORTUNITIES, "browser_session"],
}
SEARCH_CREDENTIALS = {"query": [AUTH_METHOD_OPPORTUNITIES, "browser_session"]}
SLIDE_DECK_TARGETS = {"latest"}
SLIDE_DECK_FILTER_FIELDS = {"version", "filename", "title"}
app = create_app(
    name="pluralsight-author",
    help="CLI interface for Pluralsight Author tools",
    version=__version__,
)
opportunities_app = typer.Typer(help="List Pluralsight Author opportunities", no_args_is_help=True)
search_app = typer.Typer(help="Search Pluralsight Author opportunities", no_args_is_help=True)
icons_app = typer.Typer(help="Import, search, and download Author Kit PNG icons", no_args_is_help=True)
slide_deck_app = typer.Typer(help="Identify and download the newest Pluralsight slide-deck template", no_args_is_help=True)


def _property_fields(properties: str | None) -> list[str] | None:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _rows(items) -> list[dict]:
    return [item.model_dump() if hasattr(item, "model_dump") else item for item in items]


def _validate(filters: list[str] | None, allowed_fields=None) -> None:
    if not filters:
        return
    try:
        validate_filters(filters, allowed_fields)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _render(
    rows: list[dict],
    table: bool,
    properties: str | None,
    empty: str,
    columns: list[str] | None = None,
) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    columns = fields or columns or COLUMNS
    print_table(rows, columns, [column.replace("_", " ").title() for column in columns])


def _render_get(row: dict, table: bool, properties: str | None, empty: str, columns: list[str] | None = None) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter([row], properties)
        if table:
            _render(rows, table, None, empty, columns=fields or columns)
        else:
            print_json(rows[0] if rows else {})
        return
    if table:
        print_table(
            [{"field": key, "value": str(value)} for key, value in row.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
    else:
        print_json(row)


def _list(fetch, filters, table, properties, empty, columns=None, allowed_fields=None) -> None:
    _validate(filters, allowed_fields)
    rows = _rows(fetch())
    if filters:
        rows = apply_filters(rows, filters, allowed_fields)
    _render(rows, table, properties, empty, columns=columns)


def _filter_icons(rows: list[dict], filters: list[str] | None) -> list[dict]:
    _validate(filters, ICON_FILTER_FIELDS)
    if not filters:
        return rows
    filterable = [
        {
            **row,
            "tag": " ".join(row.get("tags", [])),
            "tags": " ".join(row.get("tags", [])),
        }
        for row in rows
    ]
    for filter_string in filters:
        filterable = apply_filters(filterable, [filter_string], ICON_FILTER_FIELDS)
    filtered_ids = {
        row["id"]
        for row in filterable
    }
    return [row for row in rows if row["id"] in filtered_ids]


def _icon_filters(filters: list[str] | None, color: str | None) -> list[str] | None:
    combined = list(filters or [])
    if color:
        combined.append(f"color:eq:{canonical_icon_color(color)}")
    return combined or None


def _render_icon_rows(
    rows: list[dict],
    limit: int,
    filters: list[str] | None,
    table: bool,
    properties: str | None,
    empty: str,
) -> None:
    rows = apply_limit(_filter_icons(rows, filters), limit)
    _render(rows, table, properties, empty, columns=ICON_COLUMNS)


@opportunities_app.command("list")
@command
def list_opportunities(
    limit: int = typer.Option(1000, "--limit", "-l", help="Maximum number of opportunities"),
    filter: list[str] | None = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: str | None = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List opportunities from the Pluralsight Author opportunities page."""
    client = get_client()
    try:
        _list(lambda: client.list_opportunities(limit), filter, table, properties, "No opportunities found.")
    finally:
        client.close()


@opportunities_app.command("get")
@command
def get_opportunity(
    item_id: str = typer.Argument(..., help="Opportunity slug from `opportunities list`"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: str | None = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a single opportunity by slug."""
    client = get_client()
    try:
        _render_get(_rows([client.get_item(item_id)])[0], table, properties, "No opportunity found.")
    finally:
        client.close()


@opportunities_app.command("apply")
@command
def apply_opportunity(
    item_id: str = typer.Argument(..., help="Opportunity slug from `opportunities list`"),
    start_date: str = typer.Option(
        ...,
        "--start_date",
        help=APPLICATION_FIELD_LABELS["start_date"],
    ),
    estimated_completion_weeks: str = typer.Option(
        ...,
        "--estimated_completion_weeks",
        help=APPLICATION_FIELD_LABELS["estimated_completion_weeks"],
    ),
    experience: str = typer.Option(
        ...,
        "--experience",
        help=APPLICATION_FIELD_LABELS["experience"],
    ),
):
    """Submit a single opportunity application with explicit form field values."""
    client = get_client()
    try:
        print_json(
            client.apply(
                item_id,
                {
                    "start_date": start_date,
                    "estimated_completion_weeks": estimated_completion_weeks,
                    "experience": experience,
                },
            )
        )
    finally:
        client.close()


@search_app.command("query")
@command
def search_query(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: list[str] | None = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: str | None = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Search opportunities by title, type, or category."""
    client = get_client()
    try:
        _list(lambda: client.search(query, limit), filter, table, properties, "No results found.")
    finally:
        client.close()


@icons_app.command("import")
@command
def import_icons(
    archive: Path = typer.Argument(..., help="Pluralsight Author Kit PNG archive"),
):
    """Replace the selected profile's Author Kit PNG archive."""
    client = get_client()
    try:
        print_json(client.import_icon_archive(archive))
    finally:
        client.close()


@icons_app.command("list")
@command
def list_icons(
    limit: int = typer.Option(0, "--limit", "-l", help="Maximum number of icons; 0 returns all"),
    color: str | None = typer.Option(None, "--color", help="Return only this icon color, e.g. blue or pink"),
    filter: list[str] | None = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results by name, category, color, tag, or tags (field:op:value)",
    ),
    properties: str | None = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """List icons from the Pluralsight Author Kit icon library."""
    client = get_client()
    try:
        _render_icon_rows(
            client.list_icons(limit=0),
            limit,
            _icon_filters(filter, color),
            table,
            properties,
            "No icons found.",
        )
    finally:
        client.close()


@icons_app.command("search")
@command
def search_icons(
    query: str = typer.Argument(..., help="Single keyword to match (substring, case-insensitive). A multi-word phrase rarely matches -- search one keyword at a time."),
    limit: int = typer.Option(0, "--limit", "-l", help="Maximum number of icons; 0 returns all"),
    color: str | None = typer.Option(None, "--color", help="Return only this icon color, e.g. blue or pink"),
    filter: list[str] | None = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results by name, category, color, tag, or tags (field:op:value)",
    ),
    properties: str | None = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Search icons by a single keyword matched (case-insensitively) across id, name, category, color, and tags. The query is matched as a literal substring, not tokenized -- a single keyword like 'branch' or 'lightbulb' matches; a multi-word phrase usually matches nothing. For a multi-word concept, search individual keywords separately and combine the results, or narrow with --filter/--color."""
    client = get_client()
    try:
        _render_icon_rows(
            client.search_icons(query, limit=0),
            limit,
            _icon_filters(filter, color),
            table,
            properties,
            "No icons found.",
        )
    finally:
        client.close()


@icons_app.command("get")
@command
def get_icon(
    item_id: str = typer.Argument(..., help="Icon ID from `icons list`"),
    color: str | None = typer.Option(None, "--color", help="Return this color variant, e.g. blue or pink"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: str | None = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a single icon by ID."""
    client = get_client()
    try:
        _render_get(
            _rows([client.get_icon(item_id, color=color)])[0],
            table,
            properties,
            "No icon found.",
            columns=ICON_COLUMNS,
        )
    finally:
        client.close()


@icons_app.command("download")
@command
def download_icon(
    item_id: str = typer.Argument(..., help="Icon ID from `icons list`"),
    output: Path = typer.Option(..., "--output", "-o", help="Output file path or existing directory"),
    color: str | None = typer.Option(None, "--color", help="Write this color variant, e.g. blue or pink"),
):
    """Download an icon asset by ID."""
    client = get_client()
    try:
        print_json(client.download_icon(item_id, output, color=color))
    finally:
        client.close()


@slide_deck_app.command("list")
@command
def list_slide_decks(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of templates"),
    filter: list[str] | None = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: str | None = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List whole PowerPoint template downloads from the Authors Downloads page."""
    client = get_client()
    try:
        _list(
            client.list_slide_decks,
            filter,
            table,
            properties,
            "No slide-deck templates found.",
            columns=["version", "filename", "title"],
            allowed_fields=SLIDE_DECK_FILTER_FIELDS,
        )
    finally:
        client.close()


@slide_deck_app.command("get")
@command
def get_slide_deck(
    target: str = typer.Argument(..., help="Template to read; supported value: latest"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: str | None = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Identify the newest whole slide-deck template on the Authors Downloads page."""
    if target not in SLIDE_DECK_TARGETS:
        raise typer.BadParameter("supported template is 'latest'", param_hint="target")
    client = get_client()
    try:
        _render_get(
            client.latest_slide_deck(),
            table,
            properties,
            "No slide-deck template found.",
            columns=["version", "filename", "title"],
        )
    finally:
        client.close()


@slide_deck_app.command("download")
@command
def download_slide_deck(
    target: str = typer.Argument(..., help="Template to download; supported value: latest"),
    output: Path = typer.Option(..., "--output", "-o", help="Output file path or existing directory"),
):
    """Download the newest whole slide-deck template into a .potx/.pptx file."""
    if target not in SLIDE_DECK_TARGETS:
        raise typer.BadParameter("supported template is 'latest'", param_hint="target")
    client = get_client()
    try:
        print_json(client.download_slide_deck(output))
    finally:
        client.close()


modules_app = typer.Typer(help="Submit and inspect Pluralsight module assets", no_args_is_help=True)


@modules_app.command("inspect")
@command
def inspect_module(course_id: int = typer.Argument(..., help="Numeric Author Dashboard course ID"),
                   module_order: int = typer.Option(..., "--module-order", help="One-based module order"),
                   table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Read the module and its current uploaded clips and deck."""
    from .module_submission import ModuleSubmission
    transport = ModuleSubmission()
    try:
        result = transport.inspect(course_id, module_order)
        # Keep signed downloads and internal synchronization details out of CLI output.
        result['clips'] = [{k: c[k] for k in ('id', 'guid', 'title', 'index', 'numberedVersion') if k in c} for c in result['clips']]
        result['assets'] = [{k: a[k] for k in ('id', 'fileName', 'type', 'status')} for a in result['assets']]
        _render_get(result, table, None, "Module not found.")
    finally:
        transport.close()


@modules_app.command("submit")
@command
def submit_module(manifest: Path = typer.Option(..., "--manifest", help="Module and edited-media manifest JSON"),
                  plan: bool = typer.Option(False, "--plan", help="Write nothing; report per clip whether it is unchanged, gets a new version, or would be a new clip")):
    """Upload a module deck and edited clips, verify contents, and submit for review."""
    import json
    from .module_submission import ModuleSubmission
    transport = ModuleSubmission()
    try:
        print_json(transport.submit(json.loads(manifest.read_text()), plan=plan))
    finally:
        transport.close()


register_commands(app, get_config,
    SimpleNamespace(app=modules_app, COMMAND_CREDENTIALS=MODULE_CREDENTIALS),
    name='modules', help='Submit and inspect Pluralsight module assets')

register_commands(
    app,
    get_config,
    SimpleNamespace(app=opportunities_app, COMMAND_CREDENTIALS=OPPORTUNITY_CREDENTIALS),
    name="opportunities",
    help="List Pluralsight Author opportunities",
)
register_commands(
    app,
    get_config,
    SimpleNamespace(app=search_app, COMMAND_CREDENTIALS=SEARCH_CREDENTIALS),
    name="search",
    help="Search Pluralsight Author opportunities",
)
register_commands(
    app,
    get_config,
    SimpleNamespace(app=icons_app, COMMAND_CREDENTIALS=ICON_CREDENTIALS),
    name="icons",
    help="Import, search, and download Author Kit PNG icons",
)
register_commands(
    app,
    get_config,
    SimpleNamespace(app=slide_deck_app, COMMAND_CREDENTIALS=SLIDE_DECK_CREDENTIALS),
    name="slide-deck",
    help="Identify and download the newest Pluralsight slide-deck template",
)
app.add_typer(create_auth_app(get_config, tool_name="pluralsight-author"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    run_app(app)


if __name__ == "__main__":
    main()
