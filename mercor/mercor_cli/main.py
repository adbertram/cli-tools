"""Main entry point for Mercor CLI."""

import typer
from typing import List, Optional

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_json, print_output

from . import __version__
from .client import ClientError, get_client
from .config import get_config

app = create_app(
    name="mercor",
    help="CLI interface for the Mercor worker app (browser automation)",
    version=__version__,
)
tasks_app = typer.Typer(
    help="Inspect Mercor role listings on the worker Explore surface",
    no_args_is_help=True,
)

# Public list-column mapping: the fields a `tasks list` row is summarized by
# in table mode. JSON output carries every field the API returns.
COLUMNS = {
    "id": "Listing ID",
    "title": "Title",
    "status": "Status",
    "listingType": "Type",
    "payRateFrequency": "Pay Frequency",
    "commitment": "Commitment",
    "workArrangement": "Arrangement",
    "location": "Location",
    "url": "URL",
}
DETAIL_COLUMNS = {
    "id": "Listing ID",
    "title": "Title",
    "status": "Status",
    "listingType": "Listing Type",
    "description": "Description",
    "rateMin": "Rate Min",
    "rateMax": "Rate Max",
    "payRateFrequency": "Pay Frequency",
    "commitment": "Commitment",
    "workArrangement": "Work Arrangement",
    "location": "Location",
    "remainingSlots": "Remaining Slots",
    "recentCandidatesCount": "Recent Candidates",
    "postedAt": "Posted At",
    "url": "URL",
}


def _emit(data, table: bool, properties: Optional[str], columns: dict) -> None:
    """Render list output (a list of dicts) or single-item output (one dict)."""
    if properties:
        keys = [field.strip() for field in properties.split(",") if field.strip()]
        if isinstance(data, list):
            data = apply_properties_filter(data, properties)
        else:
            data = apply_properties_filter([data], properties)[0]
        print_output(data, table=table, columns=keys, headers=keys)
        return
    print_output(data, table=table, columns=list(columns), headers=list(columns.values()))


def _validate(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@tasks_app.command("list")
@command
def tasks_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(1000, "--limit", "-l", help="Maximum number of listings"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., listing_type:eq:evergreen)",
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated properties"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List the role listings on Mercor's worker Explore surface."""
    _validate(filter)
    client = get_client(profile)
    try:
        rows = client.list_tasks(limit=limit)
    finally:
        client.close()
    if filter:
        rows = apply_filters(rows, filter)
    _emit(rows, table, properties, COLUMNS)


@tasks_app.command("get")
@command
def tasks_get(
    task_id: str = typer.Argument(..., help="Listing ID (the `id` from 'tasks list')"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated properties"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get the full record for a single Mercor listing."""
    client = get_client(profile)
    try:
        row = client.get_task(task_id)
    finally:
        client.close()
    _emit(row, table, properties, DETAIL_COLUMNS)


@tasks_app.command("apply")
@command
def tasks_apply(
    task_id: str = typer.Argument(..., help="Listing ID to (hypothetically) apply to"),
    confirm: bool = typer.Option(
        False, "--confirm", help="Acknowledge that this CLI never applies"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Dry-run stub. This CLI never applies to a Mercor listing.

    MicroWorker's hard rule is that discovery never applies: submitting an
    application is Adam's decision in a live conversation, so this command has
    no application path and performs no network mutation at all. Without
    ``--confirm`` it refuses; with ``--confirm`` it still only prints the
    dry-run record.
    """
    if not confirm:
        print_error(
            "Refusing to run 'mercor tasks apply' without --confirm. Even with "
            "--confirm this is a dry-run stub: the mercor CLI never applies to "
            "a listing (MicroWorker hard rule -- applying is Adam's decision)."
        )
        raise typer.Exit(1)
    print_json(
        {
            "task_id": task_id,
            "dry_run": True,
            "applied": False,
            "note": (
                "mercor tasks apply is a never-used stub; discovery never "
                "applies. No request was sent to Mercor."
            ),
        }
    )


app.add_typer(tasks_app, name="tasks")
app.add_typer(create_auth_app(get_config, tool_name="mercor"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    try:
        run_app(app)
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


if __name__ == "__main__":
    main()
