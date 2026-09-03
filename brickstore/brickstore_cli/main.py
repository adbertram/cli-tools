"""Main entry point for the BrickStore CLI."""

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.output import command, print_json, print_table, print_warning

from . import __version__
from .client import MAX_BATCH_SIZE, get_client


app = create_app(
    name="brickstore",
    help="Read BrickStore price guide data through its local MCP server.",
    version=__version__,
    cache_support=False,
)


def _print_fields(fields: dict, table: bool) -> None:
    if not table:
        print_json(fields)
        return
    print_table(
        [{"field": field, "value": value} for field, value in fields.items()],
        columns=["field", "value"],
        headers=["Field", "Value"],
    )


def _item_numbers_argument(noun: str):
    return typer.Argument(
        ...,
        help="One through {} unique BrickLink {} item IDs".format(MAX_BATCH_SIZE, noun),
    )


def _skip_unknown_option(noun: str):
    return typer.Option(
        False,
        "--skip-unknown",
        help="Skip {} IDs the local database does not hold instead of failing".format(noun),
    )


def _print_contents(records: list, unknown: list, noun: str) -> None:
    for item_number in unknown:
        print_warning("skipped unknown {} ID {}".format(noun, item_number))
    print_json(records)


def _leave_open_option():
    return typer.Option(
        False,
        "--leave-open",
        help="Leave a BrickStore app started by this command open",
    )


@app.command("part")
@command
def part(
    item_number: str = typer.Argument(..., help="BrickLink part item ID"),
    color: str | None = typer.Argument(None, help="BrickStore color name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    leave_open: bool = _leave_open_option(),
) -> None:
    """Return BrickStore price guide data for one part."""
    _print_fields(get_client().part(item_number, color, leave_open=leave_open), table)


@app.command("minifig")
@command
def minifig(
    item_number: str = typer.Argument(..., help="BrickLink minifigure item ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    leave_open: bool = _leave_open_option(),
) -> None:
    """Return BrickStore price guide data for one minifigure."""
    _print_fields(get_client().minifig(item_number, leave_open=leave_open), table)


@app.command("set")
@command
def set_price(
    set_number: str = typer.Argument(..., help="BrickLink set item ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    leave_open: bool = _leave_open_option(),
) -> None:
    """Return BrickStore price guide data for one set."""
    _print_fields(get_client().set(set_number, leave_open=leave_open), table)


@app.command("query")
@command
def query(
    item_id: str | None = typer.Option(None, "--item-id", help="Filter by item ID (case-insensitive partial match)"),
    item_name: str | None = typer.Option(
        None, "--item-name", help="Filter by item name (case-insensitive partial match)"
    ),
    item_type: str | None = typer.Option(
        None, "--item-type", help="Item type name or BrickLink letter (Part, Set, Minifig, P, S, M, ...)"
    ),
    category: str | None = typer.Option(
        None, "--category", help="Filter by category name (case-insensitive partial match)"
    ),
    color: str | None = typer.Option(None, "--color", help="Filter by color name (case-insensitive partial match)"),
    related_to_item_id: str | None = typer.Option(
        None, "--related-to-item-id", help="Reference item ID for relationship filtering"
    ),
    related_to_item_type: str | None = typer.Option(
        None, "--related-to-item-type", help="Reference item type, required with --related-to-item-id"
    ),
    relationship: str | None = typer.Option(
        None, "--relationship", help="Relationship type name filter, used with --related-to-item-id"
    ),
    year_min: int | None = typer.Option(None, "--year-min", help="Minimum production year (inclusive)"),
    year_max: int | None = typer.Option(None, "--year-max", help="Maximum production year (inclusive)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    leave_open: bool = _leave_open_option(),
) -> None:
    """Return BrickStore catalog items matching the given filters."""
    result = get_client().query(
        item_id=item_id,
        item_name=item_name,
        item_type=item_type,
        category=category,
        color=color,
        related_to_item_id=related_to_item_id,
        related_to_item_type=related_to_item_type,
        relationship=relationship,
        year_min=year_min,
        year_max=year_max,
        leave_open=leave_open,
    )
    if table:
        print_table(
            result,
            columns=["id", "name", "type_name", "category", "year_released", "year_last_produced"],
            headers=["ID", "Name", "Type", "Category", "Released", "Last Produced"],
        )
    else:
        print_json(result)


@app.command("set-batch")
@command
def set_batch(
    set_numbers: list[str] = _item_numbers_argument("set"),
    leave_open: bool = _leave_open_option(),
) -> None:
    """Return price guide data for a set batch in one source call."""
    print_json(get_client().set_batch(set_numbers, leave_open=leave_open))


@app.command("set-contents")
@command
def set_contents(
    set_numbers: list[str] = _item_numbers_argument("set"),
    skip_unknown: bool = _skip_unknown_option("set"),
) -> None:
    """Return direct item records for one or more sets."""
    records, unknown = get_client().set_contents(set_numbers, skip_unknown=skip_unknown)
    _print_contents(records, unknown, "set")


@app.command("minifig-contents")
@command
def minifig_contents(
    minifig_numbers: list[str] = _item_numbers_argument("minifig"),
    skip_unknown: bool = _skip_unknown_option("minifig"),
) -> None:
    """Return direct component records for one or more minifigs."""
    records, unknown = get_client().minifig_contents(minifig_numbers, skip_unknown=skip_unknown)
    _print_contents(records, unknown, "minifig")


@app.command("part-contents")
@command
def part_contents(
    part_numbers: list[str] = _item_numbers_argument("part"),
    skip_unknown: bool = _skip_unknown_option("part"),
) -> None:
    """Return direct component records for one or more parts."""
    records, unknown = get_client().part_contents(part_numbers, skip_unknown=skip_unknown)
    _print_contents(records, unknown, "part")


database_app = typer.Typer(help="Manage the local BrickStore catalog database")
app.add_typer(database_app, name="database")


@database_app.command("update")
@command
def database_update(
    force: bool = typer.Option(False, "--force", "-f", help="Redownload even if the local copy is current"),
) -> None:
    """Download and install the newest local BrickStore catalog database."""
    print_json(get_client().database_update(force=force))


@database_app.command("status")
@command
def database_status(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
) -> None:
    """Return the local BrickStore catalog database's metadata."""
    _print_fields(get_client().database_status(), table)


def main() -> None:
    """Run the CLI application."""
    run_app(app)


if __name__ == "__main__":
    main()
