"""Raw execution commands for cliclick CLI wrapper."""
import typer

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Execute raw cliclick commands", no_args_is_help=True)


@app.command("run")
def exec_run(
    commands: str = typer.Argument(..., help="Space-separated cliclick commands (e.g., 'c:100,200 w:500 t:hello')"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Verbose output from cliclick"),
    test: bool = typer.Option(False, "--test", "-T", help="Test mode (no actual execution)"),
    no_restore: bool = typer.Option(False, "--no-restore", help="Don't restore mouse position"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Execute raw cliclick command string.

    Accepts cliclick native syntax for complex command sequences.

    Command syntax:
        c:x,y      - Click at coordinates
        dc:x,y     - Double-click
        rc:x,y     - Right-click
        tc:x,y     - Triple-click
        m:x,y      - Move mouse
        dd:x,y     - Drag start (mouse down)
        dm:x,y     - Drag move
        du:x,y     - Drag end (mouse up)
        kp:key     - Press key
        kd:keys    - Key down (modifiers)
        ku:keys    - Key up (modifiers)
        t:text     - Type text
        w:ms       - Wait milliseconds
        p          - Print position
        cp:x,y     - Color at position

    Example:
        cliclick exec run "c:100,200 w:500 t:hello"
        cliclick exec run "m:500,300 c:. w:1000 t:test" --test
    """
    try:
        client = get_client()
        result = client.execute_raw(
            commands,
            verbose=verbose,
            test_mode=test,
            restore=not no_restore,
        )

        if table:
            rows = [
                {"field": "success", "value": str(result.success)},
                {"field": "commands_executed", "value": str(result.commands_executed)},
                {"field": "duration_ms", "value": f"{result.duration_ms:.2f}" if result.duration_ms else "N/A"},
            ]
            if result.output:
                rows.append({"field": "output", "value": result.output[:60]})
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result.model_dump())

        if not result.success:
            raise typer.Exit(1)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("wait")
def exec_wait(
    milliseconds: int = typer.Argument(..., help="Milliseconds to wait"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Verbose output"),
    test: bool = typer.Option(False, "--test", "-T", help="Test mode"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Wait for specified milliseconds.

    Example:
        cliclick exec wait 1000
        cliclick exec wait 500 --verbose
    """
    try:
        client = get_client()
        result = client.wait(milliseconds, verbose=verbose, test_mode=test)

        if table:
            rows = [
                {"field": "success", "value": str(result.success)},
                {"field": "wait_ms", "value": str(milliseconds)},
                {"field": "actual_ms", "value": f"{result.duration_ms:.2f}" if result.duration_ms else "N/A"},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result.model_dump())

        if not result.success:
            raise typer.Exit(1)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
