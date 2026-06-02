"""Main entry point for the dev_to CLI."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_json, print_table

from . import __version__
from .client import get_client
from .config import get_config

DEFAULT_COLUMNS = ["id", "title", "published", "published_at", "url"]

app = create_app(
    name="dev_to",
    help="CLI interface for the DEV Community API",
    version=__version__,
)
posts_app = typer.Typer(help="Manage DEV Community posts", no_args_is_help=True)


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _validate_filters(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        raise typer.BadParameter(str(exc), param_hint="--filter")


def _render_rows(rows: List[dict], table: bool, properties: Optional[str]) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    columns = fields or DEFAULT_COLUMNS
    headers = [column.replace("_", " ").title() for column in columns]
    print_table(rows, columns, headers)


def _render_row(row: dict, table: bool, properties: Optional[str]) -> None:
    if properties:
        filtered_rows = apply_properties_filter([row], properties)
        row = filtered_rows[0]
    if not table:
        print_json(row)
        return
    if properties:
        columns = _property_fields(properties) or []
        headers = [column.replace("_", " ").title() for column in columns]
        print_table([row], columns, headers)
        return
    print_table([row], DEFAULT_COLUMNS, [column.replace("_", " ").title() for column in DEFAULT_COLUMNS])


def _read_body_markdown(body_markdown: Optional[str], body_file: Optional[Path]) -> str:
    source_count = int(body_markdown is not None) + int(body_file is not None)
    if source_count != 1:
        raise ValueError("Provide exactly one of --body-markdown or --body-file.")
    if body_file is not None:
        return body_file.read_text(encoding="utf-8")
    return body_markdown


@posts_app.command("list")
@command
def posts_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of posts"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results (field:op:value)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """List the authenticated user's DEV articles."""
    _validate_filters(filter)
    rows = get_client().list_posts(limit=limit)
    if filter:
        rows = apply_filters(rows, filter)
    _render_rows(rows, table, properties)


@posts_app.command("get")
@command
def posts_get(
    post_id: int = typer.Argument(..., help="DEV article ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """Get one DEV article by ID."""
    _render_row(get_client().get_post(post_id), table, properties)


@posts_app.command("create")
@command
def posts_create(
    title: str = typer.Option(..., "--title", help="Article title"),
    body_markdown: Optional[str] = typer.Option(None, "--body-markdown", help="Markdown body"),
    body_file: Optional[Path] = typer.Option(None, "--body-file", help="Read markdown body from file"),
    published: bool = typer.Option(False, "--published", help="Publish immediately"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tag list"),
    canonical_url: Optional[str] = typer.Option(None, "--canonical-url", help="Canonical URL"),
    description: Optional[str] = typer.Option(None, "--description", help="Article description"),
    series: Optional[str] = typer.Option(None, "--series", help="Series name"),
    main_image: Optional[str] = typer.Option(None, "--main-image", help="Main image URL"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """Create a new DEV article."""
    markdown = _read_body_markdown(body_markdown, body_file)
    article = get_client().create_post(
        title=title,
        body_markdown=markdown,
        published=published,
        tags=tags,
        canonical_url=canonical_url,
        description=description,
        series=series,
        main_image=main_image,
    )
    _render_row(article, table, properties)


@posts_app.command("unpublish")
@command
def posts_unpublish(
    post_id: int = typer.Argument(..., help="DEV article ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """Unpublish one DEV article and return it to draft status."""
    _render_row(get_client().remove_post(post_id), table, properties)


app.add_typer(posts_app, name="posts")
app.add_typer(create_auth_app(get_config, tool_name="dev_to"), name="auth", help="Manage authentication")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Run the CLI app."""
    run_app(app)


if __name__ == "__main__":
    main()
