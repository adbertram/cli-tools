"""`legoscout score` -- the deterministic 0-100 deal score."""
from __future__ import annotations

from typing import List, Optional

import typer
from cli_tools_shared.output import command

from .. import delegate
from ..scoring import rescore as rescore_module, score as score_module

COMMAND_CREDENTIALS = ["no_auth"]

app = typer.Typer(help="The deterministic 0-100 deal score", no_args_is_help=True)


@app.command("deal")
@command
def deal(
    listing_key: List[str] = typer.Argument(..., help="One or more listing_keys"),
):
    """Score one or more stored deals.

    A model reports what it OBSERVES; this decides what that is worth. No model
    ever picks a point value.
    """
    delegate.run(score_module, list(listing_key))


@app.command("rescore")
@command
def rescore(
    apply: bool = typer.Option(False, "--apply", help="Write the new scores"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report and write nothing"),
    include_rejected: bool = typer.Option(
        False, "--include-rejected", help="Rescore rejected rows too"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Stop after this many rows"),
    ledger: Optional[str] = typer.Option(
        None, "--ledger", help="Score against this ledger copy, not the live one"),
):
    """Recompute every live deal's score through the current rules."""
    argv = []
    delegate.flag(argv, "--apply", apply)
    delegate.flag(argv, "--dry-run", dry_run)
    delegate.flag(argv, "--include-rejected", include_rejected)
    delegate.option(argv, "--limit", limit)
    delegate.option(argv, "--ledger", ledger)
    delegate.run(rescore_module, argv)
