"""Motion detection commands — enable, disable, status per device.

Scope note: ring-doorbell exposes motion detection as a single boolean
toggle. Per-zone configuration and motion-sensitivity sliders are not
exposed by the library's Python API surface, so they are out of scope for
this CLI version. Use the Ring mobile app for zone editing.
"""
import typer

from cli_tools_shared.output import handle_error, print_output

from ..client import get_client


app = typer.Typer(help="Manage motion detection (enable/disable per device)", no_args_is_help=True)


COMMAND_CREDENTIALS = {
    "enable": ["username_password"],
    "disable": ["username_password"],
    "status": ["username_password"],
}


@app.command("enable")
def motion_enable(
    device: str = typer.Option(..., "--device", "-d", help="Device name or numeric ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Enable motion detection on a doorbell or camera."""
    try:
        client = get_client()
        state = client.set_motion_detection(identifier=device, enabled=True)
        print_output(state, table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("disable")
def motion_disable(
    device: str = typer.Option(..., "--device", "-d", help="Device name or numeric ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Disable motion detection on a doorbell or camera."""
    try:
        client = get_client()
        state = client.set_motion_detection(identifier=device, enabled=False)
        print_output(state, table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("status")
def motion_status(
    device: str = typer.Option(..., "--device", "-d", help="Device name or numeric ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Show whether motion detection is currently enabled."""
    try:
        client = get_client()
        state = client.get_motion_detection(identifier=device)
        print_output(state, table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
