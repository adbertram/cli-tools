"""Floodlight / lights commands for Ring stickup_cams that have lights."""
import typer

from cli_tools_shared.output import handle_error, print_output

from ..client import get_client


app = typer.Typer(help="Control floodlights on Ring stickup_cams", no_args_is_help=True)


COMMAND_CREDENTIALS = {
    "on": ["username_password"],
    "off": ["username_password"],
}


@app.command("on")
def lights_on(
    device: str = typer.Option(..., "--device", "-d", help="Device name or numeric ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Turn the floodlights on."""
    try:
        client = get_client()
        state = client.set_lights(identifier=device, state="on")
        print_output(state, table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("off")
def lights_off(
    device: str = typer.Option(..., "--device", "-d", help="Device name or numeric ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Turn the floodlights off."""
    try:
        client = get_client()
        state = client.set_lights(identifier=device, state="off")
        print_output(state, table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
