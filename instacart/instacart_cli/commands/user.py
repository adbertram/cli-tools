"""User account commands for Instacart CLI."""
import typer

from ..client import get_client
from cli_tools_shared.output import handle_error, print_json, print_table

app = typer.Typer(help="Manage Instacart user account", no_args_is_help=True)


@app.command("me")
def user_me(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get current user information.

    Examples:
        instacart user me
        instacart user me --table
    """
    try:
        client = get_client()
        user = client.get_user()

        if table:
            print_table(
                [user],
                ["user_id", "email", "is_guest", "is_admin"],
                ["User ID", "Email", "Guest", "Admin"],
            )
        else:
            print_json(user)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("addresses")
def user_addresses(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    List user delivery addresses.

    Examples:
        instacart user addresses
        instacart user addresses --table
    """
    try:
        client = get_client()
        addresses = client.get_addresses()

        if table:
            print_table(
                addresses,
                ["street", "city", "state", "zip_code"],
                ["Street", "City", "State", "Zip"],
            )
        else:
            print_json(addresses)

    except Exception as e:
        raise typer.Exit(handle_error(e))




COMMAND_CREDENTIALS = {
    "addresses": [
        "custom"
    ],
    "me": [
        "custom"
    ]
}
