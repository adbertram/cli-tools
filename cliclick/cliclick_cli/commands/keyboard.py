"""Keyboard control commands for cliclick CLI wrapper."""
import typer

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Keyboard control commands", no_args_is_help=True)


@app.command("type")
def keyboard_type(
    text: str = typer.Argument(..., help="Text to type"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Verbose output from cliclick"),
    test: bool = typer.Option(False, "--test", "-T", help="Test mode (no actual typing)"),
    no_restore: bool = typer.Option(False, "--no-restore", help="Don't restore mouse position"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Type text into the active application.

    Example:
        cliclick keyboard type "Hello World"
        cliclick keyboard type "Test message" --test
    """
    try:
        client = get_client()
        result = client.type_text(text, verbose=verbose, test_mode=test, restore=not no_restore)

        if table:
            rows = [
                {"field": "success", "value": str(result.success)},
                {"field": "text", "value": text[:50] + "..." if len(text) > 50 else text},
                {"field": "duration_ms", "value": f"{result.duration_ms:.2f}" if result.duration_ms else "N/A"},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result.model_dump())

        if not result.success:
            raise typer.Exit(1)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("press")
def keyboard_press(
    key: str = typer.Argument(..., help="Key to press (e.g., return, tab, esc, f1, space)"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Verbose output"),
    test: bool = typer.Option(False, "--test", "-T", help="Test mode"),
    no_restore: bool = typer.Option(False, "--no-restore", help="Don't restore mouse position"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Press a key.

    Available keys: return, enter, tab, space, esc, delete, fwd-delete,
    home, end, arrow-up, arrow-down, arrow-left, arrow-right,
    page-up, page-down, f1-f16, and more.

    Example:
        cliclick keyboard press return
        cliclick keyboard press tab
        cliclick keyboard press f1
    """
    try:
        client = get_client()
        result = client.key_press(key, verbose=verbose, test_mode=test, restore=not no_restore)

        if table:
            rows = [
                {"field": "success", "value": str(result.success)},
                {"field": "key", "value": key},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result.model_dump())

        if not result.success:
            raise typer.Exit(1)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("key-down")
def keyboard_key_down(
    keys: str = typer.Argument(..., help="Comma-separated modifier keys (cmd, shift, alt, ctrl, fn)"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Verbose output"),
    test: bool = typer.Option(False, "--test", "-T", help="Test mode"),
    no_restore: bool = typer.Option(False, "--no-restore", help="Don't restore mouse position"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Press and hold modifier keys.

    Modifiers: cmd, shift, alt (option), ctrl, fn

    Use with key-up to create key combinations for other automation.

    Example:
        cliclick keyboard key-down cmd,shift
        cliclick keyboard key-down alt
    """
    try:
        client = get_client()
        result = client.key_down(keys, verbose=verbose, test_mode=test, restore=not no_restore)

        if table:
            rows = [
                {"field": "success", "value": str(result.success)},
                {"field": "keys", "value": keys},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result.model_dump())

        if not result.success:
            raise typer.Exit(1)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("key-up")
def keyboard_key_up(
    keys: str = typer.Argument(..., help="Comma-separated modifier keys to release"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Verbose output"),
    test: bool = typer.Option(False, "--test", "-T", help="Test mode"),
    no_restore: bool = typer.Option(False, "--no-restore", help="Don't restore mouse position"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Release modifier keys.

    Modifiers: cmd, shift, alt (option), ctrl, fn

    Example:
        cliclick keyboard key-up cmd,shift
        cliclick keyboard key-up alt
    """
    try:
        client = get_client()
        result = client.key_up(keys, verbose=verbose, test_mode=test, restore=not no_restore)

        if table:
            rows = [
                {"field": "success", "value": str(result.success)},
                {"field": "keys", "value": keys},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result.model_dump())

        if not result.success:
            raise typer.Exit(1)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
