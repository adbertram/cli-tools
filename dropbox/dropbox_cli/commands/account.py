"""Account commands for Dropbox CLI."""
import typer

from ..client import get_client
from ..output import print_json, print_table, handle_error, format_size

COMMAND_CREDENTIALS = {
    "info": [
        "oauth"
    ],
    "usage": [
        "oauth"
    ]
}

app = typer.Typer(help="View account information")


@app.command("info")
def account_info(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Display account information.

    Examples:
        dropbox account info
        dropbox account info --table
    """
    try:
        client = get_client()
        account = client.get_account()

        if table:
            print_table(
                [account],
                ["name", "email", "account_type", "country"],
                ["Name", "Email", "Account Type", "Country"],
            )
        else:
            print_json(account)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("usage")
def account_usage(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Display disk usage information.

    Examples:
        dropbox account usage
        dropbox account usage --table
    """
    try:
        client = get_client()
        usage = client.get_space_usage()

        # Calculate percentage used
        used = usage.get("used", 0)
        allocated = usage.get("allocated", 0)
        percentage = (used / allocated * 100) if allocated > 0 else 0

        display_data = {
            "used": format_size(used),
            "allocated": format_size(allocated),
            "percentage": f"{percentage:.1f}%",
            "used_bytes": used,
            "allocated_bytes": allocated,
        }

        if "team_used" in usage:
            display_data["team_used"] = format_size(usage["team_used"])
            display_data["team_used_bytes"] = usage["team_used"]

        if table:
            print_table(
                [display_data],
                ["used", "allocated", "percentage"],
                ["Used", "Allocated", "% Used"],
            )
        else:
            print_json(display_data)

    except Exception as e:
        raise typer.Exit(handle_error(e))
