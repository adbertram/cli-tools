"""Auto-refill commands for CVS CLI."""
COMMAND_CREDENTIALS = {
    "start": [
        "browser_session"
    ],
    "stop": [
        "browser_session"
    ]
}

import typer

from ..client import get_client
from cli_tools_shared.output import handle_error, print_info, print_json, print_success


app = typer.Typer(help="Start or stop CVS auto-refill", no_args_is_help=True)


def _set_auto_refill(rx_id: str, enabled: bool, yes: bool) -> None:
    action = "start" if enabled else "stop"
    if not yes:
        confirmed = typer.confirm(f"{action.title()} auto-refill for prescription {rx_id}?")
        if not confirmed:
            print_info("Cancelled")
            raise typer.Exit(0)

    client = get_client()
    result = client.set_auto_refill(rx_id, enabled)
    if result.get("changed"):
        print_success(f"Auto-refill {action} completed for prescription {rx_id}")
    else:
        print_info(f"Auto-refill was already {'on' if enabled else 'off'} for prescription {rx_id}")
    print_json(result)


@app.command("start")
def auto_refills_start(
    rx_id: str = typer.Argument(..., help="Prescription ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Start CVS auto-refill for a prescription."""
    try:
        _set_auto_refill(rx_id, True, yes)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("stop")
def auto_refills_stop(
    rx_id: str = typer.Argument(..., help="Prescription ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Stop CVS auto-refill for a prescription."""
    try:
        _set_auto_refill(rx_id, False, yes)
    except Exception as e:
        raise typer.Exit(handle_error(e))
