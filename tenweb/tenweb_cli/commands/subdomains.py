"""Subdomain commands for the 10Web CLI."""

import typer

from cli_tools_shared.output import handle_error, print_json, print_table

from ..client import get_client


COMMAND_CREDENTIALS = {
    "check": ["api_key"],
}


app = typer.Typer(help="Check 10Web subdomain availability", no_args_is_help=True)


@app.command("check")
def subdomains_check(
    subdomain: str = typer.Argument(..., help="Subdomain to check, without .10web.club"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Check whether a 10Web subdomain is available.

    Examples:
        tenweb subdomains check my-site
        tenweb subdomains check my-site --table
    """
    try:
        result = get_client().check_subdomain(subdomain)
        if table:
            print_table(
                [result],
                ["status", "message"],
                ["Status", "Message"],
            )
        else:
            print_json(result)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
