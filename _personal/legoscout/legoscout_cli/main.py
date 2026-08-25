"""Main entry point for the LegoScout CLI.

Seven groups plus `triage`. Every `list` carries `--table/-t`, `--filter/-f`,
`--limit/-l` and `--properties/-p`; every `get` carries `--table/-t`.
"""

from cli_tools_shared import create_app, run_app

from . import __version__
from typing import Optional

import typer
from cli_tools_shared.output import command

from . import delegate
from .commands import deals, deploy, display, pricing, prospects, score, sellers, sources
from .sources import triage as triage_module

app = create_app(
    name="legoscout",
    help="Sources and prices used LEGO deals: ledger, scoring, pricing, "
         "sources, prospects, display",
    version=__version__,
    cache_support=False,
)

app.add_typer(sources.app, name="sources")
app.add_typer(deals.app, name="deals")
app.add_typer(sellers.app, name="sellers")
app.add_typer(prospects.app, name="prospects")
app.add_typer(pricing.app, name="pricing")
app.add_typer(score.app, name="score")
app.add_typer(display.app, name="display")
app.add_typer(deploy.app, name="deploy")



# `triage` absorbs three retired root scripts and belongs to no group, so it is
# a top-level command rather than a `commands/` module.
@app.command("triage")
@command
def triage(
    candidates: str = typer.Argument(
        ..., help="PATH to a JSON file holding an array of eBay candidate dicts"),
    min_price: Optional[float] = typer.Option(
        None, "--min-price", help="Price floor; the rules file states the default"),
    fetch_details: bool = typer.Option(
        False, "--fetch-details",
        help="Run `ebay listings get` per kept candidate and write the run "
             "artifact (live eBay calls)"),
    jobs: Optional[int] = typer.Option(
        None, "--jobs",
        help="Concurrent `ebay listings get` calls; each worker still waits "
             "between its own calls"),
    run_key: Optional[str] = typer.Option(
        None, "--run-key", help="The source-runs directory name to write into"),
    out: Optional[str] = typer.Option(
        None, "--out", help="Write the artifact under this directory instead"),
):
    """Filter, categorize and optionally detail a batch of raw eBay candidates."""
    argv = [candidates]
    delegate.option(argv, "--min-price", min_price)
    delegate.flag(argv, "--fetch-details", fetch_details)
    delegate.option(argv, "--jobs", jobs)
    delegate.option(argv, "--run-key", run_key)
    delegate.option(argv, "--out", out)
    delegate.run(triage_module, argv)


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
