"""Main entry point for the BrickStore CLI."""

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.output import command, print_json, print_table

from . import __version__
from .client import MAX_SET_BATCH_SIZE, get_client


SET_NUMBERS_HELP = "One through {} unique BrickLink set item IDs".format(MAX_SET_BATCH_SIZE)


app = create_app(
    name="brickstore",
    help="Read BrickStore price guide data through its local MCP server.",
    version=__version__,
    cache_support=False,
)


def _print_price_guide(price_guide: dict, table: bool) -> None:
    if not table:
        print_json(price_guide)
        return
    print_table(
        [{"field": field, "value": value} for field, value in price_guide.items()],
        columns=["field", "value"],
        headers=["Field", "Value"],
    )


def _set_numbers_argument():
    return typer.Argument(
        ...,
        help=SET_NUMBERS_HELP,
    )


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
    _print_price_guide(get_client().part(item_number, color, leave_open=leave_open), table)


@app.command("set")
@command
def set_price(
    set_number: str = typer.Argument(..., help="BrickLink set item ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    leave_open: bool = _leave_open_option(),
) -> None:
    """Return BrickStore price guide data for one set."""
    _print_price_guide(get_client().set(set_number, leave_open=leave_open), table)


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
    set_numbers: list[str] = _set_numbers_argument(),
    leave_open: bool = _leave_open_option(),
) -> None:
    """Return price guide data for a set batch in one source call."""
    print_json(get_client().set_batch(set_numbers, leave_open=leave_open))


@app.command("set-contents")
@command
def set_contents(
    set_numbers: list[str] = _set_numbers_argument(),
) -> None:
    """Return direct item records for one or more sets."""
    print_json(get_client().set_contents(set_numbers))


def main() -> None:
    """Run the CLI application."""
    run_app(app)


if __name__ == "__main__":
    main()
