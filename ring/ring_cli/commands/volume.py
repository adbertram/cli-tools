"""Volume commands — set device speaker/chime volume."""
import typer

from cli_tools_shared.output import handle_error, print_output

from ..client import get_client


app = typer.Typer(help="Manage device volume", no_args_is_help=True)


COMMAND_CREDENTIALS = {
    "set": ["username_password"],
}


@app.command("set")
def volume_set(
    device: str = typer.Option(..., "--device", "-d", help="Device name or numeric ID"),
    value: int = typer.Option(..., "--value", "-v", help="Volume level (0-10)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Set the device volume to ``value`` (0-10)."""
    try:
        if not 0 <= value <= 10:
            raise typer.BadParameter("Volume must be between 0 and 10 inclusive.")
        client = get_client()
        state = client.set_volume(identifier=device, value=value)
        print_output(state, table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
