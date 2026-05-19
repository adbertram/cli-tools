"""Member commands for Bricklink CLI."""
COMMAND_CREDENTIALS = {
    "delete-note": ["oauth"],
    "note": ["oauth"],
    "ratings": ["oauth"],
    "set-note": ["oauth"],
}

import typer
from typing import Optional

from ..client import get_client
from ..display import print_detail
from cli_tools_shared.output import print_json, print_success, handle_error

app = typer.Typer(help="Member information", no_args_is_help=True)


@app.command("ratings")
def member_ratings(
    username: str = typer.Argument(..., help="Bricklink username"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get member feedback/ratings.

    Examples:
        bricklink member ratings some_user
        bricklink member ratings some_user --table
    """
    try:
        client = get_client()
        data = client.get_member_ratings(username)
        print_detail(data, table)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("note")
def member_note(
    username: str = typer.Argument(..., help="Bricklink username"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get personal note for a member.

    Examples:
        bricklink member note some_user
        bricklink member note some_user --table
    """
    try:
        client = get_client()
        data = client.get_member_note(username)
        print_detail(data, table)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("set-note")
def member_set_note(
    username: str = typer.Argument(..., help="Bricklink username"),
    text: str = typer.Argument(..., help="Note text"),
):
    """
    Create or update a personal note for a member.

    Examples:
        bricklink member set-note some_user "Good buyer, fast payment"
        bricklink member set-note some_user "Problem buyer - opened dispute"
    """
    try:
        client = get_client()
        result = client.set_member_note(username, text)
        print_success(f"Note set for {username}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete-note")
def member_delete_note(
    username: str = typer.Argument(..., help="Bricklink username"),
):
    """
    Delete personal note for a member.

    Examples:
        bricklink member delete-note some_user
    """
    try:
        client = get_client()
        result = client.delete_member_note(username)
        print_success(f"Note deleted for {username}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
