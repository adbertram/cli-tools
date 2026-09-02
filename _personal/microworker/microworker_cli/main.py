"""Main entry point for the Microworker CLI.

Commands: `discover`, `merge`, `validate`, and the `sites list|get` group.
`sites list` carries `--table/-t`, `--filter/-f`, `--limit/-l` and
`--properties/-p`; `sites get` carries `--table/-t` and `--properties/-p`.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import List, Optional

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.exceptions import ClientError, ConfigError
from cli_tools_shared.filters import (
    apply_filters,
    apply_limit,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table

from . import __version__, discover as discover_module, merge as merge_module, schema, sites

COLUMNS = ["name", "cli", "account", "lastpass_item", "auth_command"]

app = create_app(
    name="microworker",
    help="Runs the per-site gig CLIs for the MicroWorker project, writes site "
         "envelopes, and merges them into one task list",
    version=__version__,
    cache_support=False,
)
sites_app = typer.Typer(help="Sites registered in the project's config.json",
                        no_args_is_help=True)


def exit_2_on_contract_errors(fn):
    """Config and schema/contract errors are exit 2, not the generic 1.

    The shared `@command` decorator maps everything but `CredentialError` to
    exit 1; this sits beneath it so `ClientError` and `ConfigError` reach the
    documented exit code instead.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ClientError, ConfigError) as exc:
            print_error(str(exc))
            raise typer.Exit(2)
    return wrapper


@app.command("discover")
@command
@exit_2_on_contract_errors
def discover(
    site: str = typer.Argument(..., help="Site name from config.json"),
    run_id: str = typer.Option(..., "--run-id", help="Discovery run identifier; the envelope lands under agent_workspaces/discovery/<run_id>/"),
    timeout: int = typer.Option(300, "--timeout", help="Seconds allowed for each site CLI command"),
):
    """Run one site's CLI and write its envelope for this run."""
    print_json(discover_module.discover(site, run_id, timeout))


@app.command("merge")
@command
@exit_2_on_contract_errors
def merge(
    run_id: str = typer.Argument(..., help="Discovery run identifier whose envelopes to merge"),
):
    """Merge every site envelope of a run into merged.json."""
    print_json(merge_module.merge(run_id))


@app.command("validate")
@command
@exit_2_on_contract_errors
def validate(
    file: Path = typer.Argument(..., help="An envelope or merged.json file to validate"),
):
    """Validate an envelope or merged file against its schema."""
    kind = schema.validate_file(file)
    print_json({"file": str(file), "kind": kind, "valid": True})


@sites_app.command("list")
@command
@exit_2_on_contract_errors
def sites_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of sites"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List the sites in config.json."""
    if filter:
        validate_filters(filter)
    rows = [sites.site_row(site) for site in sites.load_sites().values()]
    if filter:
        rows = apply_filters(rows, filter)
    rows = apply_limit(rows, limit)
    rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info("No sites found.")
        return
    columns = list(rows[0])
    print_table(rows, columns, [column.replace("_", " ").title() for column in columns])


@sites_app.command("get")
@command
@exit_2_on_contract_errors
def sites_get(
    name: str = typer.Argument(..., help="Site name from config.json"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one site's config.json entry."""
    row = apply_properties_filter([sites.site_row(sites.get_site(name))], properties)[0]
    if not table:
        print_json(row)
        return
    print_table(
        [{"field": key, "value": str(value)} for key, value in row.items()],
        ["field", "value"],
        ["Field", "Value"],
    )


app.add_typer(sites_app, name="sites")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
