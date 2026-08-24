"""`legoscout sellers` -- the per-seller table the ledger joins on."""
from __future__ import annotations

from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, print_json

from .. import delegate, render
from ..ledger import backfill_sellers as backfill_module
from ..ledger import db as ledger_db, sellers as sellers_db

COMMAND_CREDENTIALS = ["no_auth"]

app = typer.Typer(help="Sellers, and Adam's favorite flag", no_args_is_help=True)

COLUMNS = ["source", "seller_id", "seller_name", "is_favorite", "last_seen_at"]


@app.command("list")
@command
def list_sellers(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of sellers"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List every seller the ledger has seen."""
    render.check_filters(filter)
    rows = ledger_db.query(
        "SELECT * FROM sellers ORDER BY is_favorite DESC, source, seller_id")
    if filter:
        rows = apply_filters(rows, filter)
    render.rows(render.capped(rows, limit), table, properties, COLUMNS,
                "No sellers recorded.")


@app.command("get")
@command
def get_seller(
    source: str = typer.Argument(..., help="The canonical source, e.g. shopgoodwill"),
    seller_id: str = typer.Argument(..., help="The marketplace's own seller key"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one seller row."""
    render.one(sellers_db.get_seller(source, seller_id), table, properties,
               "No seller %s|%s." % (source, seller_id))


@app.command("favorite")
@command
def favorite(
    source: str = typer.Argument(..., help="The canonical source"),
    seller_id: str = typer.Argument(..., help="The marketplace's own seller key"),
    off: bool = typer.Option(False, "--off", help="Clear the flag instead of setting it"),
):
    """Flag a seller as a favorite. This changes every one of their deal scores."""
    sellers_db.set_favorite(source, seller_id, not off)
    print_json({"source": source, "seller_id": seller_id,
                "is_favorite": not off})


@app.command("backfill")
@command
def backfill(
    apply: bool = typer.Option(False, "--apply", help="Write the rows"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report and write nothing"),
    db: Optional[str] = typer.Option(None, "--db", help="A different ledger path"),
):
    """Build seller rows from the seller identity already on the deal records."""
    argv = []
    delegate.flag(argv, "--apply", apply)
    delegate.flag(argv, "--dry-run", dry_run)
    delegate.option(argv, "--db", db)
    delegate.run(backfill_module, argv)
