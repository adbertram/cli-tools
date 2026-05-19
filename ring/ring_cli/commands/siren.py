"""Siren commands for Ring stickup_cams."""
import typer

from cli_tools_shared.output import handle_error, print_output

from ..client import get_client


app = typer.Typer(help="Control the siren on Ring stickup_cams", no_args_is_help=True)


COMMAND_CREDENTIALS = {
    "on": ["username_password"],
    "off": ["username_password"],
}


@app.command("on")
def siren_on(
    device: str = typer.Option(..., "--device", "-d", help="Device name or numeric ID"),
    duration: int = typer.Option(
        30,
        "--duration",
        "-u",
        help="Siren duration in seconds (Ring enforces a max around 300s)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Trigger the siren for ``duration`` seconds."""
    try:
        client = get_client()
        state = client.set_siren(identifier=device, duration=duration)
        print_output(state, table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("off")
def siren_off(
    device: str = typer.Option(..., "--device", "-d", help="Device name or numeric ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Silence an active siren by setting its remaining duration to 0."""
    try:
        client = get_client()
        state = client.set_siren(identifier=device, duration=0)
        print_output(state, table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
