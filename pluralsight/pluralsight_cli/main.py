"""Main entry point for Pluralsight CLI."""

import typer
from typing import List, Optional
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table

from . import __version__
from .client import get_client, normalize_item
from .config import get_config

COLUMNS = ["title", "category", "skillLevel", "duration", "rating"]
CATEGORY_HELP = "Content type (repeatable): course, path, labs, certificate, all"

app = create_app(
    name="pluralsight",
    help="Search the public Pluralsight catalog (courses, paths, labs, certificates)",
    version=__version__,
)


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _validate(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _render(rows: List[dict], table: bool, properties: Optional[str], empty: str) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    columns = fields or COLUMNS
    headers = [column.replace("publishedDate", "Published").replace("skillLevel", "Skill Level")
               .replace("ratingCount", "Ratings") for column in columns]
    print_table(rows, columns, headers)


def _emit_results(response: dict, query: str, page: int, per_page: int,
                  filters, table: bool, properties: Optional[str], full: bool) -> None:
    """Render one raw Cludo response according to the documented output contract."""
    _validate(filters)
    records = [normalize_item(doc) for doc in response.get("TypedDocuments") or []]
    if filters:
        records = apply_filters(records, filters)

    if full:
        payload = {
            "query": query,
            "page": page,
            "perPage": per_page,
            "total": response.get("TotalDocument"),
            "results": records,
            "facets": response.get("Facets"),
        }
        fields = _property_fields(properties)
        if fields:
            payload["results"] = apply_properties_filter(payload["results"], properties)
        print_json(payload)
        return

    _render(records, table, properties, "No items found.")


def _category_options(category: Optional[List[str]]):
    # None keeps the browse-page default content-type set (courses, labs,
    # certificates, skills); an explicit `-c all` widens to everything indexed.
    return category if category else None


@app.command("search")
@command
def search_items(
    query: str = typer.Argument(..., help="Search keywords (e.g. 'agentic ai')"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum number of results (server-side page size)"),
    page: int = typer.Option(1, "--page", "-P", min=1, help="Result page number"),
    category: Optional[List[str]] = typer.Option(None, "--category", "-c", help=CATEGORY_HELP),
    sort: str = typer.Option("relevance", "--sort", help="Sort order: relevance or newest"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    full: bool = typer.Option(False, "--full", help="Include total count and facets wrapper"),
):
    """Keyword search over the public Pluralsight catalog."""
    try:
        response = get_client().search_items(
            query=query,
            page=page,
            per_page=limit,
            categories=_category_options(category),
            sort=sort,
        )
    except Exception as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    _emit_results(response, query, page, limit, filter, table, properties, full)


@app.command("list")
@command
def list_items(
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum number of items (server-side page size)"),
    page: int = typer.Option(1, "--page", "-P", min=1, help="Result page number"),
    category: Optional[List[str]] = typer.Option(None, "--category", "-c", help=CATEGORY_HELP),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    full: bool = typer.Option(False, "--full", help="Include total count and facets wrapper"),
):
    """List newest catalog entries across the public Pluralsight library."""
    try:
        response = get_client().list_items(
            page=page,
            per_page=limit,
            categories=_category_options(category),
        )
    except Exception as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    _emit_results(response, "*", page, limit, filter, table, properties, full)


@app.command("get")
@command
def get_item(
    item_id: str = typer.Argument(..., help="Product id (e.g. docker-developers-docker-foundations)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a single catalog entry by product id."""
    try:
        row = get_client().get_item(item_id)
    except Exception as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    if row is None:
        print_info(f"No catalog entry found for product id '{item_id}'.")
        raise typer.Exit(1)
    fields = _property_fields(properties)
    if fields:
        row = apply_properties_filter([row], properties)[0]
    if table:
        print_table(
            [{"field": key, "value": str(value)} for key, value in row.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
    else:
        print_json(row)


@app.command("suggestions")
@command
def suggestions(
    query: str = typer.Argument(..., help="Partial search phrase"),
):
    """Return query suggestions from the catalog search engine."""
    try:
        print_json(get_client().get_suggestions(query))
    except Exception as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("modules")
@command
def course_modules(
    course_id: str = typer.Argument(..., help="Course product id (e.g. docker-developers-docker-foundations)"),
    clips: bool = typer.Option(True, "--clips/--no-clips", help="Include individual clip listings"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter modules (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get module titles, lengths, and clip structure for one course."""
    try:
        parsed = get_client().get_course_modules(course_id)
    except Exception as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    _validate(filter)
    modules = parsed.get("modules") or []
    if not clips:
        for module in modules:
            module.pop("clips", None)
    if filter:
        modules = apply_filters(modules, filter)
    payload = {"course": course_id, "title": parsed.get("title"), "moduleCount": len(modules), "modules": modules}
    fields = _property_fields(properties)
    if fields:
        modules_out = apply_properties_filter(modules, properties) if modules else []
        if not table:
            payload["modules"] = modules_out
            print_json(payload)
            return
        rows = modules_out
        columns = fields
    else:
        rows = modules
        columns = ["title", "duration"]
    if table:
        if not rows:
            print_info("No modules found.")
            return
        print_table(rows, columns, [c.replace("_", " ").title() for c in columns])
    else:
        print_json(payload)


app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
