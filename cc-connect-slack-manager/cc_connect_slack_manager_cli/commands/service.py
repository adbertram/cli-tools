"""LaunchAgent management commands."""
import typer

from cli_tools_shared.output import handle_error, print_json, print_table

from ..client import get_client

app = typer.Typer(help="Manage the Cody cc-connect LaunchAgent", no_args_is_help=True)


@app.command("status")
def status(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Show LaunchAgent status."""
    try:
        result = get_client().service_status()
        if table:
            print_table(
                [result],
                ["label", "loaded", "running", "pid", "state"],
                ["Label", "Loaded", "Running", "PID", "State"],
            )
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("start")
def start():
    """Bootstrap the Cody cc-connect LaunchAgent."""
    try:
        print_json(get_client().service_start())
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("stop")
def stop():
    """Boot out the Cody cc-connect LaunchAgent."""
    try:
        print_json(get_client().service_stop())
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("restart")
def restart():
    """Restart the Cody cc-connect LaunchAgent."""
    try:
        print_json(get_client().service_restart())
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("logs")
def logs(
    stream: str = typer.Option("stdout", "--stream", "-s", help="stdout or stderr"),
    lines: int = typer.Option(80, "--lines", "-l", help="Number of lines"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Show recent Cody cc-connect logs."""
    try:
        result = get_client().log_tail(stream=stream, lines=lines)
        if table:
            rows = [{"line": line} for line in result.lines]
            print_table(rows, ["line"], ["Line"])
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "logs": [
        "custom"
    ],
    "restart": [
        "custom"
    ],
    "start": [
        "custom"
    ],
    "status": [
        "custom"
    ],
    "stop": [
        "custom"
    ]
}
